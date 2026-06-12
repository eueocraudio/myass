import base64
import os
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myass.noise import primitives as P  # noqa: E402
from myass.noise.channel import connect_tor, initiate, listen, respond  # noqa: E402
from myass.noise.tor import (  # noqa: E402
    OnionService, client_auth_line, gen_client_auth,
)

PROLOGUE = b"myass/subspace/v1"


def _b32dec(s: str) -> bytes:
    return base64.b32decode(s + "=" * ((8 - len(s) % 8) % 8))


def _tor_control_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9051), timeout=1):
            return True
    except OSError:
        return False


class TestClientAuth(unittest.TestCase):
    def test_gen_client_auth_keys_are_32_bytes_x25519(self):
        priv, pub = gen_client_auth()
        self.assertEqual(len(_b32dec(priv)), 32)
        self.assertEqual(len(_b32dec(pub)), 32)
        self.assertNotEqual(priv, pub)

    def test_pairs_are_unique(self):
        self.assertNotEqual(gen_client_auth()[0], gen_client_auth()[0])

    def test_client_auth_line_format(self):
        priv, _ = gen_client_auth()
        self.assertEqual(client_auth_line("abc.onion", priv),
                         f"abc:descriptor:x25519:{priv}")


@unittest.skipUnless(_tor_control_up(), "precisa de um Tor com ControlPort 9051")
class TestOnionServiceIntegration(unittest.TestCase):
    """Publica o Scheduler atrás de um onion v3 e o alcança via SOCKS + Noise.
    Só roda com um Tor real (ControlPort 9051 / SOCKS 9050)."""

    def test_noise_over_onion(self):
        i_priv, i_pub = P.generate_keypair()
        r_priv, r_pub = P.generate_keypair()
        psk = os.urandom(32)

        srv = listen("127.0.0.1", 0)
        local_port = srv.getsockname()[1]
        box = {}

        def server():
            conn, _ = srv.accept()
            ch = respond(conn, PROLOGUE, r_priv, r_pub, i_pub, psk)
            ch.send(b"onion-echo:" + ch.recv())
            ch.close()

        threading.Thread(target=server, daemon=True).start()
        try:
            with OnionService(local_port, virtual_port=9735) as onion:
                self.assertTrue(onion.onion_address.endswith(".onion"))
                sock = connect_tor(onion.onion_address, 9735)
                ch = initiate(sock, PROLOGUE, i_priv, i_pub, r_pub, psk)
                ch.send(b"oi")
                self.assertEqual(ch.recv(), b"onion-echo:oi")
                ch.close()
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
