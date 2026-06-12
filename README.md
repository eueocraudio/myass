# myass

Assistente Pessoal Local — plataforma de orquestração de rotinas (inclusive de IA) que roda inteiramente em infraestrutura privada e fechada do usuário. Ver `CLAUDE.md` para a especificação de arquitetura.

## Estado

Implementação inicial. Primeiro componente em código: o **broker** (a fila/messageria multinível, parte da Rainha).

## Desenvolvimento

Tudo em **Python** (alvo: 3.14; sem containers, sem stacks web). Layout `src/`, testes com `unittest` da stdlib.

```bash
./install.sh                 # cria venv, instala (pymongo + mongomock), roda os testes
# ou, manualmente:
PYTHONPATH=src python3 -m unittest discover -s tests
```

Os testes usam `mongomock` e não exigem um MongoDB rodando. Em produção o broker
fala com um MongoDB real (`mongodb://localhost:27017/`).

## Estrutura

```
src/myass/
  broker/
    classes.py   # nível 1: tabela de classes MEM x CPU (classify / eligible)
    ring.py      # nível 2: ring buffer W/R por nó
    store.py     # lastro durável das atividades no MongoDB
    broker.py    # junta tudo: enqueue/dequeue + carga preguiçosa do ring
tests/           # unittest (test_classes, test_ring, test_broker)
doc/             # artefatos de design (diagramas, análises)
```
