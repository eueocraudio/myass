# bot_ip — URLhaus como 3ª fonte (v0.3) + runbook de produção

Documenta a integração do **URLhaus** (abuse.ch) ao `bots/bot_ip/` como terceira
fonte de enriquecimento e o procedimento operacional usado para **publicar** e
**desativar** versões no quadrante de produção. Ver também `bots/bot_ip/README.md`
e o resumo em `CLAUDE.md` (*2º BOT de exemplo*).

## Visão geral

O `bot_ip` extrai IPs de WAN de um texto e, num loop por IP, consulta agora
**três fontes** independentes (cada `action` roteia/classifica por hardware sozinha;
o registro acumulado viaja por `$prev`):

| Passo (node) | Script | Fonte | Sinal |
|---|---|---|---|
| `02_01_shodan` | `task02_shodan.py` | Shodan | exposição (portas, serviços, vulns) |
| `02_02_abuseipdb` | `task03_abuseipdb.py` | AbuseIPDB | reputação (abuse score, reports) |
| `02_03_urlhaus` | `task03b_urlhaus.py` | **URLhaus** | **distribuição de malware** (URLs, famílias, tags) |

O relatório PDF consolida as três (1 IP/página) e ordena por **abuse → malware
servido → exposição**.

## A API do URLhaus (o que o bot usa)

Dois hosts, uma `Auth-Key` (portal `auth.abuse.ch`). O bot usa **só** o lookup de
host:

```
POST https://urlhaus-api.abuse.ch/v1/host/
  header:  Auth-Key: <URLHAUS_API_KEY>
  corpo:   host=<ip>                      (application/x-www-form-urlencoded)
```

Resposta gateada por `query_status` (`ok` / `no_results` / `invalid_host` / …).
Em `ok`, o bot resume: `url_count`, URLs online, `firstseen`, `threats`, `tags`
(famílias, ex. `Mozi`/`mirai`), `blacklists` (spamhaus_dbl/surbl) e amostras de
URLs.

> Outros endpoints da API (não usados aqui, mas documentados p/ referência):
> lookups `POST /v1/url|payload|tag|signature/`, feeds `GET /v2/files/exports/<KEY>/…`
> (chave **no path**, não no header), e submissão `POST https://urlhaus.abuse.ch/api/`.
> Detalhe completo na memória de referência do projeto.

## Implementação

- **`scripts/task03b_urlhaus.py`** — espelha o padrão do AbuseIPDB: recebe `$prev`
  (ip + shodan + abuseipdb) e **acumula** a chave `urlhaus`. Chave ausente =
  **erro lógico** (RuntimeError → exit 1, cadeia de catch); falha de rede/HTTP é
  **tolerada** (`urlhaus_erro`/`urlhaus_nota` e segue, pra um IP não derrubar o
  relatório). `query_status != ok` vira nota.
- **`lib/http.py`** — novo helper `post_form_json(url, fields, headers)`
  (form-urlencoded → JSON), o padrão dos lookups do URLhaus.
- **`scripts/task04_report.py`** — seção *"Malware distribution — URLhaus"* por
  IP + amostras de URLs, coluna **Malware** no resumo, ordenação
  `abuse → malware → exposição`, metodologia de três fontes.
- **`build.py`** — script `urlhaus-host` (capacidade `api:urlhaus`,
  `apis:["https://urlhaus-api.abuse.ch"]`); **versão 0.2 → 0.3** (o registro
  `(nome,versao) → hash` é imutável, então conteúdo novo exige versão nova).
  `manifest.json`/`workflow.json` regerados.

### Invariante de segurança das chaves

`URLHAUS_API_KEY` (como `SHODAN_API_KEY`/`ABUSEIPDB_API_KEY`) vive **no ENV DO
DRONE**, nunca no pedido/ocorrência — é capacidade do block, não parâmetro. Em
produção: `/opt/myass/drone.env` (chmod 600), referenciado por `EnvironmentFile=`
no `myass-drone.service`.

## Teste isolado (sem Rainha)

```bash
cd bots/bot_ip
WD=$(mktemp -d); echo '{"occurrence_id":"t","params":{"ip":"110.39.232.231"}}' > "$WD/input.json"
echo "{\"workdir\":\"$WD\"}" | URLHAUS_API_KEY=... python3 scripts/task03b_urlhaus.py
cat "$WD/output.json"   # -> {... "urlhaus": {"url_count":…, "tags":["Mozi","mirai",…]}}
```

## Runbook — publicar uma versão nova em produção

O admin publica **da máquina dev** (não do host): `quadrante/admin-0.json`
(role `publicador`) aponta `direct` para o core de produção pela LAN.

1. **Regerar hashes** após mudar o código:
   ```bash
   cd bots/bot_ip && python3 build.py    # manifest.json + workflow.json (BLAKE2)
   ```
2. **Encenar o subconjunto canônico** (senão `publish-bot` tara a pasta inteira e
   o `project_hash` não casa com o `bot_ref` do workflow):
   ```bash
   mkdir -p quadrante/bot_ip_pub
   cp -r bots/bot_ip/lib bots/bot_ip/scripts bots/bot_ip/manifest.json quadrante/bot_ip_pub/
   # conferir: tree_hash(staged) == project_hash do build.py == bot_ref do workflow
   ```
3. **Chave no drone** (se a versão usa uma API nova) — `URLHAUS_API_KEY` no
   `/opt/myass/drone.env` e reiniciar o drone:
   ```bash
   ssh user@<host> 'printf "URLHAUS_API_KEY=%s\n" "<key>" >> /opt/myass/drone.env \
     && chmod 600 /opt/myass/drone.env && sudo systemctl restart myass-drone'
   ```
4. **Publicar** bot + workflow no core (conecta na LAN ao Scheduler):
   ```bash
   PYTHONPATH=src python3 -m myass.ops admin --config quadrante/admin-0.json publish-bot quadrante/bot_ip_pub
   PYTHONPATH=src python3 -m myass.ops admin --config quadrante/admin-0.json publish-workflow bots/bot_ip/workflow.json
   ```
   Bump de versão = publicação **aditiva**: as versões antigas ficam intactas, **sem
   drop de DB** (a imutabilidade só morde quando se republica o *mesmo* `(nome,versao)`
   com hash diferente).
5. **Autorizar na chave web** (a allow-list é o muro independente do que a web
   mostra) — não há comando no CLI; usar o `AdminClient`:
   ```python
   from myass.client.admin import AdminClient   # montar com quadrante/admin-0.json
   web = next(c for c in cli.list_clients() if c["name"] == "web")
   cli.update_client("web", web["workflows"] + ["<template_hash novo>"])
   ```
6. **Validar fim-a-fim**: `... admin ... start <template_hash> '{"texto":"… 110.39.232.231 …"}'`
   e acompanhar a ocorrência até `done` (o PDF deve trazer a seção URLhaus).

## Runbook — desativar uma versão

"Desativar" tem duas camadas; faça as duas para um estado consistente:

1. **Revogar no registro** (o muro real — a Rainha deixa de agendar/iniciar). Não
   há REVOKE no protocolo/AdminClient; revoga-se direto no Mongo do núcleo com o
   método testado:
   ```python
   from pymongo import MongoClient
   from myass.publish.registry import PublishRegistry
   db = MongoClient("mongodb://127.0.0.1:27017")["myass"]
   reg = PublishRegistry(db, None)          # revoke não usa blobs
   reg.revoke("<bot project_hash>")         # ex. bot_ip 0.2
   reg.revoke("<workflow template_hash>")   # seta status:revogado + audita
   ```
   (Reversível: `status` de volta a `ativo`. Versões com hash distinto são
   independentes — revogar a 0.2 não afeta a 0.3.)
2. **Remover da allow-list da chave web** via `cli.update_client("web", lista_sem_o_hash)`.

Verificação: `start <template_hash revogado>` deve retornar
`{erro: 'workflow não aprovado'}`, e o `catalog` só lista as versões ativas.
