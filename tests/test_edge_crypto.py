import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cryptography.exceptions import InvalidTag  # noqa: E402

from myass.edge import crypto  # noqa: E402


class TestEdgeCrypto(unittest.TestCase):
    def setUp(self):
        self.secret = crypto.new_secret()

    def test_secret_length(self):
        self.assertEqual(len(self.secret), crypto.SECRET_LEN)

    def test_request_roundtrip(self):
        k = crypto.request_key(self.secret)
        blob = crypto.seal_request(k, b"ola mundo")
        self.assertEqual(crypto.open_request(k, blob), b"ola mundo")

    def test_response_roundtrip(self):
        k = crypto.response_key(self.secret)
        blob = crypto.seal_response(k, b"resultado")
        self.assertEqual(crypto.open_response(k, blob), b"resultado")

    def test_addresses_are_64_hex_and_distinct(self):
        a_req = crypto.request_address(self.secret)
        a_resp = crypto.response_address(self.secret)
        self.assertEqual(len(a_req), 64)
        self.assertEqual(len(a_resp), 64)
        self.assertNotEqual(a_req, a_resp)
        int(a_req, 16)  # é hex válido

    def test_keys_and_addresses_are_independent(self):
        # Saber o endereço não revela a chave (derivações 'person' distintas).
        self.assertNotEqual(crypto.request_key(self.secret),
                            crypto.response_key(self.secret))
        self.assertNotEqual(crypto.request_key(self.secret).hex(),
                            crypto.request_address(self.secret))

    def test_per_client_separation(self):
        other = crypto.new_secret()
        self.assertNotEqual(crypto.request_address(self.secret),
                            crypto.request_address(other))
        # Blob de um cliente não abre com a chave de outro.
        blob = crypto.seal_request(crypto.request_key(self.secret), b"x")
        with self.assertRaises(InvalidTag):
            crypto.open_request(crypto.request_key(other), blob)

    def test_direction_separation(self):
        # Um blob de pedido não abre como resposta (AAD de direção difere), mesmo
        # que as chaves fossem iguais.
        k = crypto.request_key(self.secret)
        blob = crypto.seal_request(k, b"x")
        with self.assertRaises(InvalidTag):
            crypto.open_response(k, blob)

    def test_tamper_detected(self):
        k = crypto.request_key(self.secret)
        blob = bytearray(crypto.seal_request(k, b"intacto"))
        blob[-1] ^= 0x01  # corrompe a tag
        with self.assertRaises(InvalidTag):
            crypto.open_request(k, bytes(blob))

    def test_catalog_roundtrip_and_distinct(self):
        k = crypto.catalog_key(self.secret)
        blob = crypto.seal_catalog(k, b'[{"hash":"h","label":"L"}]')
        self.assertEqual(crypto.open_catalog(k, blob), b'[{"hash":"h","label":"L"}]')
        # endereço/chave de catálogo são independentes dos de req/resp
        addrs = {crypto.request_address(self.secret), crypto.response_address(self.secret),
                 crypto.catalog_address(self.secret)}
        self.assertEqual(len(addrs), 3)

    def test_rejects_wrong_secret_length(self):
        with self.assertRaises(ValueError):
            crypto.request_key(os.urandom(16))


if __name__ == "__main__":
    unittest.main()
