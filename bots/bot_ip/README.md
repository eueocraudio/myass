# bot_ip

Recebe um **texto**, extrai os **IPs de WAN** (IPv4 públicos; descarta
privados/reservados/loopback/CGNAT), e para cada IP consulta o **Shodan**
(exposição: portas, serviços, hostnames, vulns) e o **AbuseIPDB** (reputação:
abuse confidence score, reports, tipo de uso). No fim, consolida tudo num
**relatório PDF** (1 IP por página, ordenado por abuse score → exposição) e o
**publica** num serviço de upload (se configurado).

## Workflow (estrutograma)

```
01_quebrar_texto  (split-ips)            texto → [ips de WAN]
02_dividir  (loop, foreach ip)
    02_01_shodan     (shodan-host)       ip   → {ip, shodan:{ports,vulns,...}}
    02_02_abuseipdb  (abuse-check)       $prev→ {..., abuseipdb:{abuse_score,...}}
03_report  (report-pdf)                  [ips] → PDF (inline b64)
04_publish (publish)                     sobe o PDF → URL (só se configurado)
```

## Configuração — no ENV DO DRONE (nunca no pedido)

```
SHODAN_API_KEY=...                 # obrigatória p/ o passo Shodan
ABUSEIPDB_API_KEY=...              # obrigatória p/ o passo AbuseIPDB
# upload (opcional — sem isto, 04_publish PULA sem falhar; o PDF fica inline):
MYASS_UPLOAD_URL=...               # destino (PUT na URL EXATA = ideal p/ S3 presigned)
MYASS_UPLOAD_AUTH=Bearer ...       # token / Authorization
MYASS_UPLOAD_METHOD=PUT            # PUT (default) | POST
MYASS_UPLOAD_FIELD=file            # campo do POST multipart
MYASS_UPLOAD_APPEND_NAME=1         # no PUT, anexa /<nome> (endpoint tipo diretório)
```

As keys/segredos vivem no drone (ex.: `/opt/myass/drone.env`, `chmod 600`,
referenciado por `EnvironmentFile=` na unit `myass-drone`). Egress sai via Tor
quando `MYASS_PROXY` está setado (ver `lib/http.py`). A task de **upload só roda
se houver path E token** — senão pula sem falhar.

## Build e publicação

```bash
python3 build.py        # (re)gera manifest.json + workflow.json (hashes BLAKE2)
```

Publicar = só o subconjunto **`lib/ + scripts/ + manifest.json`** (não a pasta
crua, senão o `project_hash` não casa com o `bot_ref` do workflow):

```bash
# stage do subconjunto e publish via admin (ver a forma usada no bot_cve)
python3 -m myass.ops admin --config quadrante/admin-0.json publish-bot <stage_dir>
python3 -m myass.ops admin --config quadrante/admin-0.json publish-workflow bots/bot_ip/workflow.json
```

Para expor a um usuário da web, adicione o `template_hash` do workflow à
allow-list de uma chave de cliente (Admin → Chaves), que republica o catálogo.

## Teste isolado (sem Rainha)

```bash
mkdir -p /tmp/x && echo '{"occurrence_id":"t","params":{"ip":"8.8.8.8"}}' > /tmp/x/input.json
echo '{"workdir":"/tmp/x"}' | SHODAN_API_KEY=... python3 scripts/task02_shodan.py
echo '{"workdir":"/tmp/x"}' | ABUSEIPDB_API_KEY=... python3 scripts/task03_abuseipdb.py
```

> Validado de ponta a ponta no quadrante real (ex.: `185.220.101.1` → AbuseIPDB
> abuse 100; `200.53.201.243` → ISP fixo brasileiro, abuse 0).
