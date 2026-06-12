# Locutus — web pública (Cliente, Parte II)

Interface web em **PHP + MySQL** para o usuário final: informa uma **chave
criptográfica**, vê seus **workflows** e cria **ocorrências**. É também o **Locutus**
(armazém público cego) da Rainha.

## Modelo de cegueira

- **Toda a cifra/decifra é no browser** (`js/myass-crypto.js`, gêmeo de
  `src/myass/edge/crypto.py`): a chave **nunca** vai ao servidor.
- O PHP é um **blob store puro** (`index.php`): `GET`/`PUT`/`DELETE` de blobs
  opacos em endereços de 64-hex (`db/schema.sql`). Não conhece clientes nem lê
  conteúdo — nem o **catálogo**, que também é um **blob E2E** publicado pelo núcleo
  e decifrado no browser (mais cego que o trade-off de metadado de CLAUDE.md).
- Endereços (`a-req`/`a-resp`/`a-cat`) e chaves derivam do segredo via BLAKE2s; o
  núcleo (`edge/gateway.py` + `HttpLocutus`) puxa/empurra nos mesmos endereços.

## Fluxo

```
browser              Locutus (PHP/MySQL)            núcleo (Rainha)
 chave→addrs    PUT /<a-req>  (pedido cifrado) ──▶  GET decifra → cria ocorrência
 GET /<a-cat>  ◀── catálogo E2E                     SET ──▶ PUT /<a-resp> (resposta)
 GET /<a-resp> ◀── resposta cifrada  (poll)
```

## Deploy (FTP)

1. `cp .env.example .env` e preencha `DB_*` (MySQL) + `FTP_*`.
2. Crie o banco: `mysql … < db/schema.sql`.
3. Suba os arquivos por **FTP** para `FTP_DIR` (ver `.env`). O `.htaccess` roteia
   os endereços de blob para o `index.php`; `index.html`/`js/` são estáticos.

Requer PHP 8+ com PDO MySQL. Sem dependências PHP externas; o JS usa `@noble`
(crypto auditada) via CDN ESM.
