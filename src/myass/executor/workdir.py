"""Alocação e limpeza do workdir de uma atividade.

Cada execução roda num diretório efêmero próprio (ver *BOT → Execução* em
``CLAUDE.md``). Limpeza é **estrutural, não de memória**: ``rmtree`` no ``finally``
de todo caminho (sucesso, erro lógico, cancelamento) + uma **varredura de órfãos
na partida** do Executor (cobre morte no meio — o trabalho em si o lease já
reentregou).

O ``/tmp`` é tmpfs na maioria dos alvos, então o dado da atividade fica em **RAM,
nunca no disco** — alinhado ao risco de acesso físico do modelo de ameaça.

Artefato gigante de VAI (``workdir_mb`` declarado no manifesto) deve usar um
**workdir LUKS efêmero** em vez do tmpfs (chave só em RAM, container removido no
mesmo ``finally``). Isso exige ``cryptsetup``/privilégio e fica como ponto de
extensão (``alloc_workdir(workdir_mb=...)`` levanta ``NotImplementedError`` por
ora) — o caminho tmpfs é o implementado.
"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile

WORKDIR_PREFIX = "myass-"
WORKDIR_ROOT = "/tmp"


def alloc_workdir(occurrence_id: str = "", workdir_mb: int | None = None) -> str:
    """Cria um workdir efêmero modo 700 e devolve seu caminho.

    Com ``workdir_mb`` definido, o contrato pede um volume LUFS efêmero
    (pendente); sem ele, um diretório no tmpfs.
    """
    if workdir_mb is not None:
        raise NotImplementedError(
            "workdir LUKS efêmero (workdir_mb) ainda não implementado — ver workdir.py"
        )
    # mkdtemp já cria com modo 0700.
    safe = "".join(c for c in occurrence_id if c.isalnum() or c in "-_")[:32]
    return tempfile.mkdtemp(prefix=f"{WORKDIR_PREFIX}{safe}-", dir=WORKDIR_ROOT)


def cleanup_workdir(workdir: str) -> None:
    """Remove o workdir inteiro (idempotente)."""
    shutil.rmtree(workdir, ignore_errors=True)


def sweep_orphans(root: str = WORKDIR_ROOT) -> int:
    """Remove workdirs órfãos deixados por uma morte no meio. Chamar na partida do
    Executor. Retorna quantos foram removidos."""
    removed = 0
    for path in glob.glob(os.path.join(root, f"{WORKDIR_PREFIX}*")):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
