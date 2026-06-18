<?php
// setup.php — cria a tabela `blobs` no MySQL e SE AUTOREMOVE. Uso único.
//
// Suba junto no primeiro deploy e acesse https://<dominio>/setup.php uma vez.
// Roda no servidor (conecta no MySQL pelo DB_HOST do .env), então não depende de
// "Remote MySQL" liberado. Após criar a tabela, tenta apagar a si mesmo.
declare(strict_types=1);
header('Content-Type: text/plain; charset=utf-8');
require __DIR__ . '/lib.php';

try {
    $env = load_env(__DIR__ . '/.env');
    $pdo = pdo_connect($env);
    $pdo->exec(
        "CREATE TABLE IF NOT EXISTS blobs (
            addr        CHAR(64)  NOT NULL PRIMARY KEY,
            data        LONGBLOB  NOT NULL,
            expires_at  BIGINT    NOT NULL,
            created_at  BIGINT    NOT NULL,
            KEY idx_expires (expires_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=binary"
    );
    // sanity: a tabela existe?
    $n = $pdo->query("SELECT COUNT(*) FROM blobs")->fetchColumn();
    echo "OK: tabela `blobs` pronta (linhas atuais: {$n}).\n";
} catch (Throwable $e) {
    http_response_code(500);
    echo "ERRO: " . $e->getMessage() . "\n";
    echo "Confira DB_HOST/DB_NAME/DB_USER/DB_PASS no .env (e a tabela no hPanel).\n";
    exit;
}

// autoremoção (uso único). Se o host não permitir unlink, avisa para remover à mão.
if (@unlink(__FILE__)) {
    echo "setup.php removido (autodestruição ok).\n";
} else {
    echo "AVISO: remova setup.php manualmente (FTP) — unlink falhou.\n";
}
