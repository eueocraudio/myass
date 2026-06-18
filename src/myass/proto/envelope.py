"""Camada de aplicação Executor↔Scheduler — o envelope dentro de cada record.

Roda por dentro do enquadramento de records Noise. Formato (ver *Camada de
aplicação* em CLAUDE.md):

    header_len (4B BE) ‖ header JSON ‖ corpo (bytes crus, opcional)

O header é sempre JSON com ao menos ``{"t": tipo}``. O corpo cru só é usado em
transferências binárias (``PROJECT_DATA``/``DATA_CHUNK``); mensagens de controle
vão com corpo vazio. A identidade vem sempre do handshake, nunca do header.
"""

from __future__ import annotations

import json

# Executor -> Scheduler
HELLO = "HELLO"
WORK_GET = "WORK_GET"
WORK_BEAT = "WORK_BEAT"
RESULT = "RESULT"
WORK_RELEASE = "WORK_RELEASE"
PROJECT_GET = "PROJECT_GET"
DATA_GET = "DATA_GET"
DATA_PUT = "DATA_PUT"              # corpo binário: o artefato
PING = "PING"

# Admin (papel publicador) -> Scheduler
PUBLISH = "PUBLISH"                 # corpo binário: tar do BOT ou JSON do template
CATALOG_GET = "CATALOG_GET"
START_OCCURRENCE = "START_OCCURRENCE"
LIST_OCCURRENCES = "LIST_OCCURRENCES"
OCCURRENCE_GET = "OCCURRENCE_GET"
ENVIRONMENT = "ENVIRONMENT"
CREATE_CLIENT = "CREATE_CLIENT"     # cria chave de cliente (nome + workflows permitidos)
UPDATE_CLIENT = "UPDATE_CLIENT"     # edita os workflows permitidos de uma chave
LIST_CLIENTS = "LIST_CLIENTS"

# Scheduler -> Executor
HELLO_OK = "HELLO_OK"
WORK = "WORK"
NO_WORK = "NO_WORK"
BEAT_ACK = "BEAT_ACK"
WORK_CANCEL = "WORK_CANCEL"
RESULT_ACK = "RESULT_ACK"
RELEASE_ACK = "RELEASE_ACK"
PROJECT_DATA = "PROJECT_DATA"     # corpo binário: o tar do projeto
PROJECT_MISS = "PROJECT_MISS"
DATA_CHUNK = "DATA_CHUNK"         # corpo binário: o artefato
DATA_MISS = "DATA_MISS"
DATA_ACK = "DATA_ACK"
PONG = "PONG"

# Scheduler -> Admin
PUBLISH_ACK = "PUBLISH_ACK"
CATALOG = "CATALOG"
START_ACK = "START_ACK"
OCCURRENCES = "OCCURRENCES"
OCCURRENCE_INFO = "OCCURRENCE_INFO"
ENV_INFO = "ENV_INFO"
CLIENT_ACK = "CLIENT_ACK"           # ack de create/update (devolve segredo no create)
CLIENTS = "CLIENTS"                 # lista de chaves de cliente
DENIED = "DENIED"                   # papel sem permissão para a operação


def encode(t: str, fields: dict | None = None, body: bytes = b"") -> bytes:
    header = {"t": t}
    if fields:
        header.update(fields)
    hb = json.dumps(header, ensure_ascii=False).encode("utf-8")
    return len(hb).to_bytes(4, "big") + hb + body


def decode(payload: bytes) -> tuple[str, dict, bytes]:
    n = int.from_bytes(payload[:4], "big")
    header = json.loads(payload[4:4 + n].decode("utf-8"))
    return header["t"], header, bytes(payload[4 + n:])
