# bot_cve

BOT de exemplo do myass: a partir de um texto, extrai CVEs, enriquece cada um
(MITRE + CISA KEV + exploit-db + referências + NER) e gera um relatório PDF.
É a reescrita do antigo `bot_cve` (`/opt/myass`) na **arquitetura nova**.

## Workflow (Nassi)

A árvore de atividades está em `workflow.json` (template Nassi, JSON canônico) e
desenhada em ASCII abaixo. Task02 é o nó **loop** (não tem script); Task06 tem
`catch: ignorar`.

```
Task01 ACTION  split texto → array[CVE] (uppercase)
Task02 LOOP    foreach cve  ── fan-out async ──
  └ corpo (sync por CVE):
      Task03 ACTION  dados do CVE (MITRE)
      Task04 ACTION  CVE ∈ KEV/CISA? (anota)
      Task05 ACTION  exploits (exploit-db)
      Task06 ACTION  download refs   ╲catch: IGNORA╱
      Task07 ACTION  NER (spaCy/fallback)
      Task08 ACTION  finaliza doc (fim do filho)
  JOIN → array[doc_cve]
Task09 ACTION  consolida → array único
Task10 ACTION  PDF rico → /tmp/<UUID>.pdf
```

## Decisões (defaults — fáceis de trocar)

1. **Task03 = MITRE** (`cveawg.mitre.org`) para os dados-base ricos; o exploit-db
   fica só para os **exploits** (Task05). O enunciado citava exploit-db para
   ambos; o MITRE dá descrição/CVSS/refs para um relatório melhor.
2. **Task04 só anota** o KEV (não ramifica o fluxo — não é `decision`).
3. **Task06 `catch: ignorar`** (engole) — disposição explícita do enunciado.
   Há também tolerância por-referência dentro do script.
4. **Task09 consolida o array do join** (não relê o Mongo).
5. **Task08 "salva" retornando o doc**: no myass real o núcleo persiste via o
   **canal de dados** (`DATA_PUT`/GridFS); um script de drone não fala direto com
   o Mongo do núcleo.

## Contrato dos scripts (novo)

Cada script segue o contrato do Executor (não o legado de `/opt/myass`):

```
stdin: {"workdir": "..."}
workdir/input.json : {"occurrence_id", "params"}
workdir/output.json: <retorno>      (vira o RESULT)
exit 0 = ok · exit != 0 = erro lógico
```

Testável isolado:

```bash
echo '{"workdir": "/tmp/x"}' | python scripts/task01_split.py   # (com input.json em /tmp/x)
```

## Plano de teste SEM a Rainha

`test/run_pipeline.py` encadeia todos os scripts via subprocess (simulando o
Scheduler: cursor, loop foreach, join, catch), no estilo do bot_cve legado.

```bash
python test/run_pipeline.py                 # texto de exemplo embutido
python test/run_pipeline.py < entrada.txt   # texto do stdin
MYASS_PROXY=socks/http_proxy python test/run_pipeline.py   # egress via Tor
```

Com rede traz dados reais; **offline degrada** para um relatório parcial — o
pipeline completa mesmo assim e gera o PDF em `/tmp/<UUID>.pdf`.

## (Re)gerar manifest + workflow

```bash
python build.py     # recomputa script_hash/project_hash/template_hash
```

`manifest.json` (canônico) declara, por script, `exigencia`/`capacidades`/`apis`/
`params`/`retorno`; `workflow.json` é o template Nassi com os `bot_ref`.

## Dependências

Tudo **stdlib** (HTTP via `urllib`, PDF via `lib/minipdf.py`). NER usa **spaCy
(`en_core_web_md`)** se disponível — é **capacidade do block** (classe B),
declarada no manifesto; sem ela, o `lib/text.py` cai num fallback regex.

## Pendências (dependem do core)

Rodar de verdade pela Rainha precisa do que ainda falta no myass: **motor de
workflow Nassi** (loop/join/catch), **canal Noise/Tor**, **gestão de projeto/venv**
e o **canal de dados** lado-núcleo (`DATA_PUT`/GridFS). Este BOT já é o alvo
concreto desses componentes.
```
