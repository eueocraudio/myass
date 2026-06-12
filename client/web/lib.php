<?php
// lib.php — config (.env) + conexão MySQL do Locutus.
//
// O Locutus é o armazém público CEGO: guarda só blobs opacos (ciphertext E2E) em
// endereços opacos de 64-hex. Não há chave criptográfica aqui — toda cifra/decifra
// acontece no browser (ver js/myass-crypto.js). Ver "Cliente — duas partes" em
// CLAUDE.md.

declare(strict_types=1);

function load_env(string $path): array {
    $env = [];
    if (is_file($path)) {
        foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
            $line = trim($line);
            if ($line === '' || $line[0] === '#') continue;
            [$k, $v] = array_pad(explode('=', $line, 2), 2, '');
            $env[trim($k)] = trim($v);
        }
    }
    return $env;
}

function pdo_connect(array $env): PDO {
    $host = $env['DB_HOST'] ?? '127.0.0.1';
    $name = $env['DB_NAME'] ?? 'myass_locutus';
    $dsn  = "mysql:host=$host;dbname=$name;charset=binary";
    return new PDO($dsn, $env['DB_USER'] ?? 'root', $env['DB_PASS'] ?? '', [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    ]);
}
