"""Plano de dados no lado do Executor: tradução ``$file`` <-> ``$data``.

A invariante de pulverização proíbe "deixa no disco que o próximo pega": dado só
viaja pelo workflow. Artefato grande é **content-addressed** (``data_ref =
blake2:<hash>``) e sobe/baixa do núcleo (ver *Plano de dados* em ``CLAUDE.md``).
O script, porém, só conhece arquivos no workdir — quem traduz é o Executor:

    ENTRADA   ordem traz {"imagem": {"$data": "blake2:…"}}
              -> DATA_GET (data_store.get) -> confere hash -> grava workdir/in/…
              -> input.json do filho: {"imagem": {"$file": "in/…"}}

    SAÍDA     filho grava saida.png + output.json {"imagem": {"$file": "saida.png"}}
              -> BLAKE2(saida.png) -> DATA_PUT (data_store.put)
              -> {"imagem": {"$data": "blake2:…", "tamanho": N}}

Dado pequeno fica inline no JSON (o autor escolhe pelo gesto ``$file``). A
transferência real ao núcleo (GridFS pelo canal sub-espacial) é injetada como um
``DataStore``; aqui mora só a tradução local + a verificação de integridade
(o receptor **sempre** recomputa o BLAKE2).
"""

from __future__ import annotations

import hashlib
import itertools
import os
from pathlib import Path
from typing import Any, Protocol

REF_PREFIX = "blake2:"


def compute_ref(data: bytes) -> str:
    """``data_ref`` content-addressed de um artefato (BLAKE2b, bom para dados grandes)."""
    return REF_PREFIX + hashlib.blake2b(data).hexdigest()


class DataStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, data_ref: str) -> bytes: ...


class MemoryDataStore:
    """``DataStore`` em memória (testes/dev). O real fala GridFS pelo canal."""

    def __init__(self):
        self._blobs: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        ref = compute_ref(data)
        self._blobs[ref] = data  # dedup natural: mesmo conteúdo, mesmo ref
        return ref

    def get(self, data_ref: str) -> bytes:
        data = self._blobs[data_ref]
        if compute_ref(data) != data_ref:  # paranoia: integridade na leitura
            raise ValueError(f"data_ref corrompido: {data_ref}")
        return data


def resolve_inputs(params: Any, data_store: DataStore, workdir: str) -> Any:
    """Substitui todo ``{"$data": ref}`` por ``{"$file": rel}``, baixando o artefato
    para ``workdir/in/`` e conferindo o hash. Valores inline passam intactos."""
    counter = itertools.count()
    in_dir = os.path.join(workdir, "in")

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            if "$data" in value:
                ref = value["$data"]
                data = data_store.get(ref)  # get verifica o hash
                if compute_ref(data) != ref:
                    raise ValueError(f"artefato de entrada não confere com {ref}")
                os.makedirs(in_dir, exist_ok=True)
                rel = os.path.join("in", f"d{next(counter)}.bin")
                with open(os.path.join(workdir, rel), "wb") as f:
                    f.write(data)
                return {"$file": rel}
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(params)


def resolve_outputs(output: Any, data_store: DataStore, workdir: str) -> Any:
    """Substitui todo ``{"$file": rel}`` por ``{"$data": ref, "tamanho": N}``, subindo
    o artefato e computando o hash. Rejeita ``$file`` que escape do workdir."""
    root = Path(workdir).resolve()

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            if "$file" in value:
                rel = value["$file"]
                path = (root / rel).resolve()
                # Defesa: o filho controla output.json; um $file com ../ não pode
                # ler fora do workdir.
                if root not in path.parents and path != root:
                    raise ValueError(f"$file escapa do workdir: {rel}")
                data = path.read_bytes()
                return {"$data": data_store.put(data), "tamanho": len(data)}
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(output)
