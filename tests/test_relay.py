import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cryptography.exceptions import InvalidSignature, InvalidTag  # noqa: E402

from myass.relay import x3dh  # noqa: E402
from myass.relay.relay import (  # noqa: E402
    MemoryRelayTransport, SubspaceRelay, channel,
)
from myass.relay.x3dh import Identity, PrekeyVault, verify_bundle  # noqa: E402


class TestX3DH(unittest.TestCase):
    def setUp(self):
        self.a = Identity.generate()
        self.b = Identity.generate()
        self.psk = os.urandom(32)
        self.vault_b = PrekeyVault(self.b)

    def test_both_sides_derive_same_sk(self):
        bundle = self.vault_b.bundle()
        verify_bundle(bundle, self.b.ik_sig_pub)
        sk_a, header = x3dh.agree_sender(self.a, bundle, self.psk)
        sk_b = x3dh.agree_receiver(self.b, self.vault_b, header, self.psk)
        self.assertEqual(sk_a, sk_b)

    def test_fallback_without_opk(self):
        vault = PrekeyVault(self.b, n_opks=0)
        bundle = vault.bundle()
        sk_a, header = x3dh.agree_sender(self.a, bundle, self.psk)
        self.assertIsNone(header["opk_id"])
        self.assertEqual(x3dh.agree_receiver(self.b, vault, header, self.psk), sk_a)

    def test_wrong_psk_diverges(self):
        bundle = self.vault_b.bundle()
        sk_a, header = x3dh.agree_sender(self.a, bundle, self.psk)
        sk_b = x3dh.agree_receiver(self.b, self.vault_b, header, os.urandom(32))
        self.assertNotEqual(sk_a, sk_b)

    def test_bundle_tamper_rejected(self):
        bundle = self.vault_b.bundle()
        bundle["spk_pub"] = PrekeyVault(self.b).bundle()["spk_pub"]  # troca a SPK
        with self.assertRaises(InvalidSignature):
            verify_bundle(bundle, self.b.ik_sig_pub)

    def test_wrong_identity_rejected(self):
        bundle = self.vault_b.bundle()
        with self.assertRaises(InvalidSignature):
            verify_bundle(bundle, self.a.ik_sig_pub)  # IK errada

    def test_opk_consumed_once(self):
        bundle = self.vault_b.bundle()
        _, header = x3dh.agree_sender(self.a, bundle, self.psk)
        x3dh.agree_receiver(self.b, self.vault_b, header, self.psk)        # consome
        with self.assertRaises(InvalidSignature):
            x3dh.agree_receiver(self.b, self.vault_b, header, self.psk)    # já gasta

    def test_seal_open_roundtrip_and_tamper(self):
        sk = os.urandom(32)
        ad = b"ad"
        ct = x3dh.seal(sk, b"req", 1, b"segredo", ad)
        self.assertEqual(x3dh.open_(sk, b"req", 1, ct, ad), b"segredo")
        with self.assertRaises(InvalidTag):
            x3dh.open_(sk, b"req", 1, ct, b"outra-ad")   # AD diferente
        with self.assertRaises(InvalidTag):
            x3dh.open_(os.urandom(32), b"req", 1, ct, ad)  # chave errada


class TestSubspaceRelay(unittest.TestCase):
    def setUp(self):
        self.t = MemoryRelayTransport()
        self.a = Identity.generate()
        self.b = Identity.generate()
        psk = os.urandom(32)
        self.ra = SubspaceRelay(self.a, self.t,
                                {self.b.quadrante_id: {"psk": psk, "ik_sig_pub": self.b.ik_sig_pub}})
        self.rb = SubspaceRelay(self.b, self.t,
                                {self.a.quadrante_id: {"psk": psk, "ik_sig_pub": self.a.ik_sig_pub}})

    def test_full_request_response_cycle(self):
        self.rb.publish_prekeys()
        rid = self.ra.send_request(self.b.quadrante_id, b"ola, Rainha B")
        self.assertIsNotNone(rid)

        reqs = self.rb.receive_requests()
        self.assertEqual(reqs, [(self.a.quadrante_id, rid, b"ola, Rainha B")])

        self.assertTrue(self.rb.send_response(self.a.quadrante_id, rid, b"oi, Rainha A"))
        self.assertEqual(self.ra.receive_responses(), [(rid, b"oi, Rainha A")])

    def test_send_request_without_prekeys_returns_none(self):
        self.assertIsNone(self.ra.send_request(self.b.quadrante_id, b"x"))

    def test_replay_of_request_is_noop(self):
        self.rb.publish_prekeys()
        rid = self.ra.send_request(self.b.quadrante_id, b"once")
        ch = channel(self.a.quadrante_id, self.b.quadrante_id)
        blob = self.t.fetch(ch, "request")          # captura o REQUEST
        self.assertEqual(len(self.rb.receive_requests()), 1)  # processa 1x
        self.t.deposit(ch, "request", blob)         # replay do mesmo blob
        self.assertEqual(self.rb.receive_requests(), [])      # request_id já visto -> no-op

    def test_tampered_request_is_dropped(self):
        self.rb.publish_prekeys()
        self.ra.send_request(self.b.quadrante_id, b"intacto")
        ch = channel(self.a.quadrante_id, self.b.quadrante_id)
        import json
        msg = json.loads(self.t.fetch(ch, "request"))
        msg["ct"] = "00" + msg["ct"][2:]            # corrompe o ciphertext
        self.t.deposit(ch, "request", json.dumps(msg).encode())
        self.assertEqual(self.rb.receive_requests(), [])      # adulteração -> descartado


class TestBddAdapter(unittest.TestCase):
    def test_cycle_over_bdd_adapter(self):
        from myass.relay.bdd_transport import BddRelayTransport
        store = {}  # o "bdd" compartilhado: (channel_int, part) -> blob

        class FakeBdd:  # interface do DeadDropClient (send/receive)
            def __init__(self, host, port, secret, insecure):
                self.secret = secret
            def send(self, part, channel, plaintext):
                store[(channel, part)] = plaintext   # o bdd re-sela; o fake só guarda
            def receive(self, part, channel):
                return store.get((channel, part))     # não consome (como o bdd real)

        factory = lambda h, p, s, i: FakeBdd(h, p, s, i)
        a, b = Identity.generate(), Identity.generate()
        psk, root = os.urandom(32), os.urandom(32)
        ta = BddRelayTransport(a.quadrante_id,
                               {b.quadrante_id: {"host": "x", "port": 1, "secret": root}}, factory)
        tb = BddRelayTransport(b.quadrante_id,
                               {a.quadrante_id: {"host": "x", "port": 1, "secret": root}}, factory)
        ra = SubspaceRelay(a, ta, {b.quadrante_id: {"psk": psk, "ik_sig_pub": b.ik_sig_pub}})
        rb = SubspaceRelay(b, tb, {a.quadrante_id: {"psk": psk, "ik_sig_pub": a.ik_sig_pub}})

        rb.publish_prekeys()
        rid = ra.send_request(b.quadrante_id, b"ola via bdd")
        self.assertIsNotNone(rid)
        self.assertEqual(rb.receive_requests(), [(a.quadrante_id, rid, b"ola via bdd")])
        self.assertTrue(rb.send_response(a.quadrante_id, rid, b"oi via bdd"))
        self.assertEqual(ra.receive_responses(), [(rid, b"oi via bdd")])


if __name__ == "__main__":
    unittest.main()
