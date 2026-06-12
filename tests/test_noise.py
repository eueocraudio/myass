import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cryptography.exceptions import InvalidTag  # noqa: E402

from myass.noise import primitives as P  # noqa: E402
from myass.noise.channel import connect, initiate, listen, respond  # noqa: E402
from myass.noise.framing import MAX_CHUNK, frame, unframe  # noqa: E402
from myass.noise.handshake import HandshakeState  # noqa: E402
from myass.noise.symmetric import CipherState  # noqa: E402

PROLOGUE = b"myass/subspace/v1"


def static_pair():
    return P.generate_keypair()  # (priv_obj, pub_bytes)


class TestHandshakeKKpsk0(unittest.TestCase):
    def setUp(self):
        self.i_priv, self.i_pub = static_pair()
        self.r_priv, self.r_pub = static_pair()
        self.psk = os.urandom(32)

    def _pair(self, psk_i=None, psk_r=None, rs_i=None, rs_r=None):
        hi = HandshakeState(True, PROLOGUE, self.i_priv, self.i_pub,
                            rs_i or self.r_pub, psk_i or self.psk)
        hr = HandshakeState(False, PROLOGUE, self.r_priv, self.r_pub,
                            rs_r or self.i_pub, psk_r or self.psk)
        return hi, hr

    def test_full_handshake_and_transport(self):
        hi, hr = self._pair()
        msg1, _ = hi.write_message(b"hello")
        p1, k_r = hr.read_message(msg1)
        self.assertEqual(p1, b"hello")
        self.assertIsNone(k_r)  # respondedor ainda não terminou

        msg2, (rc1, rc2) = hr.write_message(b"world")
        p2, (ic1, ic2) = hi.read_message(msg2)
        self.assertEqual(p2, b"world")

        # Handshake hash idêntico nas duas pontas (canal autenticado igual).
        self.assertEqual(hi.handshake_hash(), hr.handshake_hash())

        # Transporte: iniciador->respondedor usa c1; respondedor->iniciador usa c2.
        ct = ic1.encrypt_with_ad(b"", b"ping")
        self.assertEqual(rc1.decrypt_with_ad(b"", ct), b"ping")
        ct2 = rc2.encrypt_with_ad(b"", b"pong")
        self.assertEqual(ic2.decrypt_with_ad(b"", ct2), b"pong")

    def test_nonce_counter_advances(self):
        hi, hr = self._pair()
        _, _ = hr.read_message(hi.write_message()[0])
        msg2, (rc1, _rc2) = hr.write_message()
        _, (ic1, _ic2) = hi.read_message(msg2)
        a = ic1.encrypt_with_ad(b"", b"m1")
        b = ic1.encrypt_with_ad(b"", b"m1")
        self.assertNotEqual(a, b)  # mesmo plaintext, nonce diferente -> ct diferente
        self.assertEqual(rc1.decrypt_with_ad(b"", a), b"m1")
        self.assertEqual(rc1.decrypt_with_ad(b"", b), b"m1")

    def test_wrong_psk_fails(self):
        hi, hr = self._pair(psk_r=os.urandom(32))
        with self.assertRaises(InvalidTag):
            hr.read_message(hi.write_message(b"x")[0])

    def test_wrong_remote_static_fails(self):
        # Respondedor espera outra estática do iniciador -> ss/es divergem.
        bogus = static_pair()[1]
        hi, hr = self._pair(rs_r=bogus)
        with self.assertRaises(InvalidTag):
            hr.read_message(hi.write_message(b"x")[0])

    def test_tamper_fails(self):
        hi, hr = self._pair()
        msg1 = bytearray(hi.write_message(b"x")[0])
        msg1[-1] ^= 0x01
        with self.assertRaises(InvalidTag):
            hr.read_message(bytes(msg1))


class TestFraming(unittest.TestCase):
    def _cs_pair(self):
        key = os.urandom(32)
        a, b = CipherState(), CipherState()
        a.initialize_key(key)
        b.initialize_key(key)
        return a, b  # a=envia, b=recebe (nonces em sincronia)

    def _roundtrip(self, payload):
        send, recv = self._cs_pair()
        wire = frame(send, payload)
        n = int.from_bytes(wire[:4], "big")
        body = wire[4:]
        self.assertEqual(len(body), n)
        return unframe(recv, body)

    def test_small_roundtrip(self):
        self.assertEqual(self._roundtrip(b"ola mundo"), b"ola mundo")

    def test_empty_roundtrip(self):
        self.assertEqual(self._roundtrip(b""), b"")

    def test_large_payload_chunked(self):
        payload = os.urandom(MAX_CHUNK * 2 + 1234)  # força múltiplos blocos
        self.assertEqual(self._roundtrip(payload), payload)

    def test_padding_hides_size(self):
        # Dois payloads pequenos diferentes caem no mesmo bucket de 256 -> mesmo
        # tamanho de fio (o observador não distingue 10 de 100 bytes).
        send1, _ = self._cs_pair()
        send2, _ = self._cs_pair()
        self.assertEqual(len(frame(send1, b"x" * 10)), len(frame(send2, b"y" * 100)))


class TestNoiseChannelOverSocket(unittest.TestCase):
    def setUp(self):
        self.i_priv, self.i_pub = static_pair()
        self.r_priv, self.r_pub = static_pair()
        self.psk = os.urandom(32)

    def test_direct_transport_full_cycle(self):
        srv = listen("127.0.0.1", 0)
        port = srv.getsockname()[1]
        box = {}

        def server():
            conn, _ = srv.accept()
            ch = respond(conn, PROLOGUE, self.r_priv, self.r_pub, self.i_pub, self.psk)
            box["hh"] = ch.handshake_hash
            ch.send(b"echo:" + ch.recv())
            ch.close()

        th = threading.Thread(target=server)
        th.start()
        try:
            sock = connect({"transport": "direct", "host": "127.0.0.1", "port": port})
            ch = initiate(sock, PROLOGUE, self.i_priv, self.i_pub, self.r_pub, self.psk)
            ch.send(b"hello over noise")
            self.assertEqual(ch.recv(), b"echo:hello over noise")
            self.assertEqual(ch.handshake_hash, box["hh"])  # mesmo canal
            ch.close()
        finally:
            th.join(timeout=5)
            srv.close()

    def test_unknown_transport_raises(self):
        with self.assertRaises(ValueError):
            connect({"transport": "carrier-pigeon"})


if __name__ == "__main__":
    unittest.main()
