"""Canal Noise sobre TCP + transporte plugável (direto/LAN e Tor).

Junta o handshake (``handshake.py``) e o enquadramento (``framing.py``) sobre um
socket, e oferece o **transporte plugável** decidido pela topologia (ver *Canais
seguros → Transporte* em CLAUDE.md):

- **direto** (`connect_direct`) — TCP cru para localhost/LAN da zona de confiança
  (Tor de localhost↔localhost é overhead absurdo);
- **Tor** (`connect_tor`) — TCP via SOCKS5 até um ``.onion`` para travessia de WAN.

O Noise ``KKpsk0`` é **idêntico** nos dois — só muda quem conhece o endereço. O
endpoint (direto vs onion) vem provisionado out-of-band por drone; ``connect`` o
seleciona.
"""

from __future__ import annotations

import socket
import struct

from cryptography.exceptions import InvalidTag

from .framing import frame, unframe
from .handshake import HandshakeState


class AuthError(Exception):
    """Nenhum drone conhecido casou com o handshake recebido."""

_HS_LEN = 2  # prefixo de tamanho das mensagens de handshake (pequenas)


# ---- transporte plugável ----------------------------------------------
def connect_direct(host: str, port: int, timeout: float = 30.0) -> socket.socket:
    """TCP direto (localhost/LAN da zona de confiança)."""
    return socket.create_connection((host, port), timeout=timeout)


def connect_tor(onion: str, port: int, socks_host: str = "127.0.0.1",
                socks_port: int = 9050, timeout: float = 60.0) -> socket.socket:
    """TCP via SOCKS5 do Tor até ``onion:port`` (CONNECT por nome de host).

    SOCKS5 mínimo em stdlib (sem PySocks): no-auth + CONNECT a domínio. O Tor
    resolve o ``.onion``. Não exercitado pelos testes (precisa de um tor rodando).
    """
    s = socket.create_connection((socks_host, socks_port), timeout=timeout)
    s.sendall(b"\x05\x01\x00")                      # ver 5, 1 método, no-auth
    if s.recv(2) != b"\x05\x00":
        s.close()
        raise OSError("SOCKS5: no-auth recusado")
    host = onion.encode()
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host
              + struct.pack(">H", port))            # CONNECT, ATYP=domínio
    rep = s.recv(4)
    if len(rep) < 2 or rep[1] != 0x00:
        s.close()
        raise OSError(f"SOCKS5 CONNECT falhou: rep={rep!r}")
    atyp = rep[3] if len(rep) > 3 else 0x01
    s.recv({0x01: 4, 0x04: 16}.get(atyp, 0) + 2)    # consome BND.ADDR/PORT
    return s


def connect(endpoint: dict, timeout: float | None = None) -> socket.socket:
    """Abre o transporte conforme o endpoint provisionado do drone.

    ``{"transport": "direct", "host", "port"}`` ou
    ``{"transport": "tor", "onion", "port", "socks_host"?, "socks_port"?}``.
    """
    t = endpoint.get("transport", "direct")
    if t == "direct":
        return connect_direct(endpoint["host"], endpoint["port"],
                              timeout if timeout is not None else 30.0)
    if t == "tor":
        return connect_tor(endpoint["onion"], endpoint["port"],
                           endpoint.get("socks_host", "127.0.0.1"),
                           endpoint.get("socks_port", 9050),
                           timeout if timeout is not None else 60.0)
    raise ValueError(f"transporte desconhecido: {t}")


def listen(host: str, port: int, backlog: int = 16) -> socket.socket:
    """Socket de escuta do Scheduler (lado direto/LAN; no Tor a escuta é o onion)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(backlog)
    return srv


# ---- handshake sobre o socket -----------------------------------------
def _send_raw(sock: socket.socket, data: bytes) -> None:
    sock.sendall(len(data).to_bytes(_HS_LEN, "big") + data)


def _recv_raw(sock: socket.socket) -> bytes:
    n = int.from_bytes(_recvn(sock, _HS_LEN), "big")
    return _recvn(sock, n)


def _recvn(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("conexão fechada durante a leitura")
        buf += chunk
    return bytes(buf)


def initiate(sock, prologue, s_priv, s_pub, rs_pub, psk) -> "NoiseChannel":
    """Lado iniciador (Executor): -> msg1, <- msg2, abre o canal."""
    hs = HandshakeState(True, prologue, s_priv, s_pub, rs_pub, psk)
    msg1, _ = hs.write_message(b"")
    _send_raw(sock, msg1)
    _, keys = hs.read_message(_recv_raw(sock))
    send_cs, recv_cs = keys           # iniciador: c1=envia, c2=recebe
    return NoiseChannel(sock, send_cs, recv_cs, hs.handshake_hash())


def respond(sock, prologue, s_priv, s_pub, rs_pub, psk) -> "NoiseChannel":
    """Lado respondedor (Scheduler): <- msg1, -> msg2, abre o canal."""
    hs = HandshakeState(False, prologue, s_priv, s_pub, rs_pub, psk)
    hs.read_message(_recv_raw(sock))
    msg2, keys = hs.write_message(b"")
    c1, c2 = keys                     # respondedor: c2=envia, c1=recebe
    _send_raw(sock, msg2)
    return NoiseChannel(sock, c2, c1, hs.handshake_hash())


def respond_trial(sock, prologue, s_priv, s_pub, peers):
    """Respondedor KK com múltiplos drones possíveis: descobre **qual** é pela
    estática + PSK que decifra a 1ª mensagem (a identidade vem do handshake,
    nunca auto-reportada). ``peers`` = iterável de ``(peer_id, rs_pub, psk)``.

    Retorna ``(peer_id, NoiseChannel)``; levanta ``AuthError`` se nenhum casar.
    """
    msg1 = _recv_raw(sock)
    for peer_id, rs_pub, psk in peers:
        hs = HandshakeState(False, prologue, s_priv, s_pub, rs_pub, psk)
        try:
            hs.read_message(msg1)
        except InvalidTag:
            continue  # estática/PSK erradas para este candidato; tenta o próximo
        msg2, (c1, c2) = hs.write_message(b"")
        _send_raw(sock, msg2)
        return peer_id, NoiseChannel(sock, c2, c1, hs.handshake_hash())
    raise AuthError("nenhuma estática/PSK de drone casou com o handshake")


# ---- canal em modo transporte -----------------------------------------
class NoiseChannel:
    def __init__(self, sock, send_cs, recv_cs, handshake_hash: bytes):
        self.sock = sock
        self._send_cs = send_cs
        self._recv_cs = recv_cs
        self.handshake_hash = handshake_hash

    def send(self, payload: bytes) -> None:
        self.sock.sendall(frame(self._send_cs, payload))

    def recv(self) -> bytes:
        n = int.from_bytes(_recvn(self.sock, 4), "big")
        return unframe(self._recv_cs, _recvn(self.sock, n))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
