<?php
// index.php — roteador do Locutus (blob store cego) + serve a UI.
//
// Rotas:
//   GET  /                      -> a interface web (index.html)
//   GET  /<addr 64-hex>         -> lê um blob (o cliente puxa a resposta/catálogo)
//   PUT  /<addr 64-hex>         -> grava um blob write-once (o cliente deposita o pedido)
//   DELETE /<addr 64-hex>       -> remove um blob
//
// Compatível com o HttpLocutus do núcleo (GET/PUT/DELETE em <base>/<addr>): o
// núcleo puxa os pedidos e empurra as respostas pelos mesmos endereços. O servidor
// nunca decifra nada.

declare(strict_types=1);
require __DIR__ . '/lib.php';

$env  = load_env(__DIR__ . '/.env');
$path = trim(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?? '', '/');

if ($path === '' || $path === 'index.html') {
    header('Content-Type: text/html; charset=utf-8');
    readfile(__DIR__ . '/index.html');
    exit;
}

if (!preg_match('/^[0-9a-f]{64}$/', $path)) {
    http_response_code(404);
    exit;
}

$pdo  = pdo_connect($env);
$ttl  = (int)($env['BLOB_TTL'] ?? 86400);
$now  = time();
$addr = $path;
$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'GET') {
    $st = $pdo->prepare('SELECT data, expires_at FROM blobs WHERE addr = ?');
    $st->execute([$addr]);
    $row = $st->fetch(PDO::FETCH_ASSOC);
    if (!$row) { http_response_code(404); exit; }
    if ((int)$row['expires_at'] <= $now) {                  // expiração preguiçosa
        $pdo->prepare('DELETE FROM blobs WHERE addr = ?')->execute([$addr]);
        http_response_code(404);
        exit;
    }
    header('Content-Type: application/octet-stream');
    echo $row['data'];
    exit;
}

if ($method === 'PUT' || $method === 'POST') {
    $data = file_get_contents('php://input');
    // Write-once: o primeiro a gravar vence (dead drop). Republicar é no-op.
    $st = $pdo->prepare(
        'INSERT INTO blobs (addr, data, expires_at, created_at) VALUES (?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE addr = addr');
    $st->execute([$addr, $data, $now + $ttl, $now]);
    http_response_code(204);
    exit;
}

if ($method === 'DELETE') {
    $pdo->prepare('DELETE FROM blobs WHERE addr = ?')->execute([$addr]);
    http_response_code(204);
    exit;
}

http_response_code(405);
