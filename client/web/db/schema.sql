-- Esquema do Locutus (banco público MySQL). Só blobs opacos — o servidor é cego.
-- O endereço de 64-hex é derivado no browser do segredo do cliente; o servidor
-- nunca o relaciona a um cliente nem lê o conteúdo (ciphertext E2E).

CREATE TABLE IF NOT EXISTS blobs (
    addr        CHAR(64)  NOT NULL PRIMARY KEY,   -- endereço opaco (dead drop)
    data        LONGBLOB  NOT NULL,               -- ciphertext E2E (nonce||ct||tag)
    expires_at  BIGINT    NOT NULL,               -- TTL (epoch s) — dilui metadado temporal
    created_at  BIGINT    NOT NULL,
    KEY idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=binary;
