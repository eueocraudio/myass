# bot_cve

BOT de exemplo do myass: a partir de um texto, extrai CVEs, enriquece cada um
(MITRE + MITRE ADP/CISA + CISA KEV + exploit-db + referências + NER + ATT&CK) e
gera um **relatório PDF rico** (capa, índice clicável, 1 CVE por página, tabelas
coloridas, texto justificado). É a reescrita do antigo `bot_cve` (`/opt/myass`)
na **arquitetura nova**, e roda de ponta a ponta sobre o quadrante real
(núcleo + drone).

## Workflow (Nassi)

A árvore de atividades está em `workflow.json` (template Nassi, JSON canônico).
Task02 é o nó **loop** (não tem script); Task06 tem `catch: ignorar`.

```
Task01 ACTION  split texto → array[CVE] (uppercase, dedup)
Task02 LOOP    foreach cve  ── fan-out async ──
  └ corpo (sync por CVE):
      Task03 ACTION  dados do CVE (MITRE + ADP p/ CVSS + fallback de título)
      Task04 ACTION  CVE ∈ KEV/CISA? (anota)
      Task05 ACTION  exploits (exploit-db)
      Task06 ACTION  download refs   ╲catch: IGNORA╱
      Task07 ACTION  NER → Impact (entidades) + Knowledge (frases)
      Task08 ACTION  finaliza doc (fim do filho)
  JOIN → array[doc_cve]
Task09 ACTION  consolida → array único (ordena por score)
Task10 ACTION  PDF rico → devolve INLINE (base64) no resultado
```

## Conteúdo do relatório (Task10)

Capa com **Severity table**, **Methodology** e **Índice clicável** (título …
nº de página, com links internos); e por CVE, em **sua própria página**:

- Banner `CVE-XXXX (SCORE): TÍTULO`, Publish/Update, vetor CVSS, severidade.
- **Descrição** (justificada), **Impact** (entidades), **CISA KEV**.
- **Vector Details** (CVSS decodificado em tabela) + **painel visual da
  calculadora** (cada métrica com as opções, a selecionada em destaque) + link
  da calculadora interativa do NVD.
- **Exploits** (exploit-db), **Knowledge (CVE Mitre)** (frases), **CWE** (com
  descrição), **MITRE ATT&CK Techniques** (via CWE→CAPEC, tabela + links),
  **Recommended links**, **References**.

## Fontes de dados (defaults — fáceis de trocar)

1. **Task03 = MITRE** (`cveawg.mitre.org`) para dados-base (título, descrição,
   CWE, referências). O **CVSS** (score/vetor) costuma faltar no container do
   CNA → buscamos no container **ADP** (CISA Vulnrichment), na mesma chamada (o
   NVD é instável/limitado, então não dependemos dele). **Título**: quando a
   MITRE não traz, derivamos da 1ª frase da descrição.
2. **Task04 só anota** o KEV (não ramifica — não é `decision`).
3. **Task06 `catch: ignorar`** (engole) — disposição explícita do enunciado.
4. **Task07** produz `object` (Impact) e `lista_knowledge` (frases), via spaCy
   quando disponível, com fallback stdlib.
5. **ATT&CK** (`lib/attack.py` + `data/cwe_attack.json`): mapa **CWE→CAPEC→
   ATT&CK** pré-computado offline do CAPEC+CWE da MITRE. Cobertura é **parcial
   por natureza** (muitos CWEs de aplicação não têm técnica correspondente).
6. **Entrega do PDF: inline (base64)** no resultado da ocorrência
   (`{"pdf": {"$b64": "...", "nome": "relatorio.pdf"}}`) — bom para artefatos
   pequenos; o cliente decodifica/visualiza/salva. (Para artefatos grandes, o
   caminho seria o **plano de dados** `$file`/`$data` no GridFS.)

## Contrato dos scripts

```
stdin: {"workdir": "..."}            (cwd do processo = workdir)
workdir/input.json : {"occurrence_id", "params"}
workdir/output.json: <retorno>       (vira o RESULT)
exit 0 = ok · exit != 0 = erro lógico
```

Testável isolado: `echo '{"workdir": "/tmp/x"}' | python scripts/task01_split.py`
(com `input.json` em `/tmp/x`).

## Plano de teste SEM a Rainha

`test/run_pipeline.py` encadeia todos os scripts via subprocess (simulando o
Scheduler: cursor, loop foreach, join, catch).

```bash
python test/run_pipeline.py                 # texto de exemplo embutido
python test/run_pipeline.py < entrada.txt   # texto do stdin
MYASS_PROXY=socks/http_proxy python test/run_pipeline.py   # egress via Tor
```

Com rede traz dados reais; **offline degrada** para um relatório parcial — o
pipeline completa mesmo assim.

## (Re)gerar manifest + workflow

```bash
python build.py     # recomputa script_hash/project_hash/template_hash
```

`manifest.json` (canônico) declara, por script, `exigencia`/`capacidades`/`apis`/
`params`/`retorno`; `workflow.json` é o template Nassi com os `bot_ref`.

## Dependências

Tudo **stdlib** (HTTP via `urllib`; PDF via `lib/minipdf.py` — gerador próprio
com cores, tabelas, métricas Helvetica para justificação e TOC clicável; CVSS
via `lib/cvss.py` + `data/cvss.json`; ATT&CK via `lib/attack.py` +
`data/cwe_attack.json`). NER usa **spaCy (`en_core_web_md`)** se disponível —
capacidade do block (classe B); sem ela, `lib/text.py` cai num fallback regex.

## Publicação (pegadinha)

Publicar pelo `provision`/admin deve empacotar **só o subconjunto executável**
(`lib/ scripts/ data/ manifest.json`) — não a pasta crua (que inclui `build.py`,
`workflow.json`, `test/`, `README.md` e mudaria o `project_hash`, fazendo o
`bot_ref` do workflow não casar).
