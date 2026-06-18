# myass

Assistente Pessoal Local — plataforma de orquestração de rotinas (inclusive de
IA) que roda inteiramente em infraestrutura privada e fechada do usuário.
Ver `CLAUDE.md` para a especificação de arquitetura autoritativa.

## Estado

Sistema implementado por inteiro em Python (suíte com ~180 testes; rodado sobre
infra real — MongoDB + processos separados + sockets + `bdd` HTTPS). Um
**quadrante** completo (Rainha escondida = broker + scheduler + motor de
workflow Nassi, borda GET/SET, canal Noise/Tor, executor/drone, cliente admin
PySide6 e web PHP) está montado e comprovadamente rodando ponta a ponta.

## Desenvolvimento

Tudo em **Python** (alvo 3.14; sem containers, sem stacks web). Layout `src/`,
testes com `unittest` da stdlib.

```bash
# suíte completa (offscreen é obrigatório por causa do test_admin_gui)
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 -m unittest discover -s tests

./install.sh                 # apt + pip extras + roda a suíte
```

Os testes usam `mongomock`/in-process e **não exigem** MongoDB/Tor rodando.

## Rodar um quadrante de verdade

```bash
# 1) provisiona identidades/configs (parteira)
PYTHONPATH=src python3 -m myass.ops provision --out ./quadrante --drones 1 --admins 1

# 2) sobe núcleo e drone (precisam de mongod rodando)
PYTHONPATH=src python3 -m myass.ops core  --config quadrante/core.json
PYTHONPATH=src python3 -m myass.ops drone --config quadrante/drone-0.json

# 3) cliente admin (PySide6): publica BOTs/workflows, inicia/acompanha ocorrências
PYTHONPATH=src python3 -c "from myass.client import admin_gui; admin_gui.main()"
```

Demo fim-a-fim sobre infra real: `examples/run_real_quadrant.py`.
Deploy operacional: `doc/DEPLOY.md`.

## Estrutura

```
src/myass/
  broker/      fila multinível (classes MEM×CPU + ring + lastro Mongo)
  scheduler/   despacho + lease/regeneração + servidor Noise (a Rainha)
  workflow/    motor Nassi (block/action/decision/loop + catch) + validação de inputs
  edge/        borda GET/SET (AEAD ChaCha20) + Locutus
  executor/    drone (workdir, runner, plano de dados, projeto/venv)
  noise/       canal sub-espacial (Noise KKpsk0/NNpsk0 + Tor)
  proto/       protocolo de aplicação (envelope)
  publish/     registro de publicação (imutável, (nome,versao)→hash)
  core/        montagem do núcleo (GET→engine→SET)
  relay/       inter-quadrante (X3DH + subspace relay sobre o bdd)
  client/      admin.py + admin_gui.py (PySide6: Tela de Workflow, ocorrências,
               visualizador de PDF embutido)
  ops/         provision + nodes + CLI (python -m myass.ops ...)
  storage/     Mongo/GridFS
bots/bot_cve/  BOT de exemplo (relatório PDF rico de CVEs) — ver seu README
client/web/    Locutus web (PHP + MySQL), deploy por FTP
tests/         unittest
doc/           design (diagramas, análises, DEPLOY)
```
