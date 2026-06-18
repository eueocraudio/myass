// myass-crypto.js — gêmeo client-side do src/myass/edge/crypto.py.
//
// Toda a cifra/decifra acontece AQUI, no browser: a chave do cliente nunca chega
// ao servidor PHP (que fica cego). Primitivos vêm de libs AUDITADAS (@noble) — o
// equivalente JS da `cryptography` do Python; nunca escritos à mão.
//
// Compatível byte-a-byte com o Python:
//   derive(secret, person) = BLAKE2s(data="myass/edge/v1", key=secret,
//                                    person=<person 0-pad p/ 8>, dkLen=32)
//   AEAD = ChaCha20-Poly1305 (IETF, nonce 12B); blob = nonce(12) || ct||tag.

import { blake2s } from 'https://esm.sh/@noble/hashes@1.5.0/blake2s';
import { chacha20poly1305 } from 'https://esm.sh/@noble/ciphers@1.0.0/chacha';

const enc = new TextEncoder();
const DATA = enc.encode('myass/edge/v1');

function person8(s) {                       // BLAKE2s 'person' tem 8 bytes (0-pad)
  const p = new Uint8Array(8);
  p.set(enc.encode(s).slice(0, 8));
  return p;
}
function derive(secret, label) {
  return blake2s(DATA, { key: secret, personalization: person8(label), dkLen: 32 });
}
function toHex(b) {
  return Array.from(b, x => x.toString(16).padStart(2, '0')).join('');
}
export function hexToBytes(h) {
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
  return out;
}

// Chaves e endereços derivados do segredo (32 bytes).
export const requestKey      = s => derive(s, 'k-req');
export const responseKey     = s => derive(s, 'k-resp');
export const catalogKey      = s => derive(s, 'k-cat');
export const requestAddress  = s => toHex(derive(s, 'a-req'));
export const responseAddress = s => toHex(derive(s, 'a-resp'));
export const catalogAddress  = s => toHex(derive(s, 'a-cat'));
// ocorrências: índice por cliente + detalhe por occ_id (endereço = BLAKE2s
// chaveado com o occ_id como dado — espelha o crypto.py).
export const occIndexKey     = s => derive(s, 'k-occ');
export const occIndexAddress = s => toHex(derive(s, 'a-occ'));
export const occDetailKey    = s => derive(s, 'k-occd');
export const occDetailAddress = (s, occId) =>
  toHex(blake2s(enc.encode(occId), { key: derive(s, 'a-occd'), dkLen: 32 }));

const AAD_REQ  = enc.encode('myass/edge/v1|req');
const AAD_RESP = enc.encode('myass/edge/v1|resp');
const AAD_CAT  = enc.encode('myass/edge/v1|cat');
const AAD_OCC  = enc.encode('myass/edge/v1|occ');
const AAD_OCCD = enc.encode('myass/edge/v1|occd');

function seal(key, plaintext, aad) {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ct = chacha20poly1305(key, nonce, aad).encrypt(plaintext);
  const out = new Uint8Array(12 + ct.length);
  out.set(nonce); out.set(ct, 12);
  return out;
}
function open(key, blob, aad) {
  return chacha20poly1305(key, blob.slice(0, 12), aad).decrypt(blob.slice(12));
}

export const sealRequest  = (k, pt) => seal(k, pt, AAD_REQ);
export const openResponse = (k, b)  => open(k, b, AAD_RESP);
export const openCatalog  = (k, b)  => open(k, b, AAD_CAT);
export const openOccIndex  = (k, b) => open(k, b, AAD_OCC);
export const openOccDetail = (k, b) => open(k, b, AAD_OCCD);

export const utf8  = s => enc.encode(s);
export const fromUtf8 = b => new TextDecoder().decode(b);
