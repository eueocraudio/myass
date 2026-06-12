"""Distribuição de BOTs no drone — hash em árvore, cache imutável e venv.

Implementa a camada de projeto do Executor (ver *BOT → Distribuição* e
*Dependências* em CLAUDE.md):

- **Identidade por hash em árvore:** ``project_hash = BLAKE2(lista ordenada de
  (caminho normalizado, BLAKE2(conteúdo)))``. Só caminho + conteúdo entram (nada
  de mtime/dono/permissões). O ``.tar.gz`` é só transporte — quem recebe **extrai
  e recomputa a árvore** e verifica contra o ``project_hash`` esperado.
- **Extração defensiva:** ``tarfile`` com ``filter="data"`` (rejeita caminho
  absoluto, ``..``, symlink, device).
- **Cache imutável:** ``~/.myass/projects/<hash>/`` (árvore verificada) +
  ``~/.myass/envs/<hash>/`` (venv por projeto). Nunca invalida, só cresce
  (versão nova = hash novo). Uma transferência em voo por ``project_hash`` (lock).
- **Dependências classe A:** ``pip install --require-hashes`` num venv por projeto
  (pacotes pinados no manifesto → PyPI comprometida = instalação **falha**).
  Sem requirements → sem venv (usa o interpretador base). Convenção: pip via Tor.
- **``ProjectResolver``** implementa a interface ``Resolver`` do ``ExecutorAgent``:
  ``bot_ref`` → (interpretador, entrypoint), baixando via ``Source`` se frio e
  **recomputando o hash do entrypoint antes do spawn** (defesa final).

O ``project_hash`` segue o mesmo esquema do ``build.py`` dos BOTs (BLAKE2b,
prefixo ``blake2:``); a regra de quais arquivos entram é a deste módulo (tudo
menos ``__pycache__``/``*.pyc``) — é ela a autoritativa para o que o drone verifica.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
from typing import Protocol

REF_PREFIX = "blake2:"


class ProjectMissing(Exception):
    pass


class IntegrityError(Exception):
    pass


# ---- hash em árvore ----------------------------------------------------
def _blake2(data: bytes) -> str:
    return REF_PREFIX + hashlib.blake2b(data).hexdigest()


def file_hash(path: str) -> str:
    with open(path, "rb") as f:
        return _blake2(f.read())


def _iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for fn in sorted(filenames):
            if fn.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            yield rel, full


def tree_hash(root: str) -> str:
    """``project_hash`` do diretório extraído."""
    entries = [(rel, file_hash(full)) for rel, full in _iter_files(root)]
    entries.sort()
    tree = "\n".join(f"{rel}\t{h}" for rel, h in entries)
    return _blake2(tree.encode("utf-8"))


# ---- tar (transporte) --------------------------------------------------
def pack(root: str) -> bytes:
    """Empacota a árvore num ``.tar.gz`` (apenas transporte; a identidade vem da
    árvore recomputada, não dos bytes do tar)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, full in _iter_files(root):
            tar.add(full, arcname=rel)
    return buf.getvalue()


def extract(tar_bytes: bytes, dest: str) -> None:
    """Extração defensiva (``filter='data'``: rejeita abs/``..``/symlink/device)."""
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")


# ---- manifesto / dependências -----------------------------------------
def read_manifest(project_dir: str) -> dict:
    with open(os.path.join(project_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def requirements_txt(manifest: dict) -> str:
    """Gera o ``requirements.txt`` com hashes para ``pip --require-hashes``
    (pip só fala SHA-256, então usamos o ``sha256:`` que acompanha cada pacote)."""
    lines = []
    for name, spec in (manifest.get("requirements") or {}).items():
        line = f"{name}=={spec['versao']}"
        for h in spec.get("hashes", []):
            if h.startswith("sha256:"):
                line += f" --hash={h}"
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def build_venv(env_dir: str, project_dir: str, manifest: dict, run=subprocess.run) -> None:
    """Cria o venv do projeto e instala as deps pinadas (``--require-hashes``).
    ``run`` é injetável para teste. Convenção: o pip sai via Tor."""
    run([sys.executable, "-m", "venv", env_dir], check=True)
    req_file = os.path.join(project_dir, ".requirements.txt")
    with open(req_file, "w", encoding="utf-8") as f:
        f.write(requirements_txt(manifest))
    env_py = os.path.join(env_dir, "bin", "python")
    run([env_py, "-m", "pip", "install", "--require-hashes", "-r", req_file], check=True)


# ---- cache imutável ----------------------------------------------------
def _safe(project_hash: str) -> str:
    return project_hash.split(":")[-1]  # parte hex, nome de diretório seguro


class ProjectCache:
    def __init__(self, base_dir: str | None = None, env_builder=build_venv):
        base = base_dir or os.path.expanduser("~/.myass")
        self.projects = os.path.join(base, "projects")
        self.envs = os.path.join(base, "envs")
        os.makedirs(self.projects, exist_ok=True)
        os.makedirs(self.envs, exist_ok=True)
        self._env_builder = env_builder
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def project_path(self, project_hash: str) -> str:
        return os.path.join(self.projects, _safe(project_hash))

    def env_path(self, project_hash: str) -> str:
        return os.path.join(self.envs, _safe(project_hash))

    def is_cached(self, project_hash: str) -> bool:
        return os.path.isdir(self.project_path(project_hash))

    def env_python(self, project_hash: str) -> str:
        """Interpretador do projeto: o do venv se existir, senão o base."""
        venv_py = os.path.join(self.env_path(project_hash), "bin", "python")
        return venv_py if os.path.exists(venv_py) else sys.executable

    def _lock_for(self, project_hash: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(project_hash, threading.Lock())

    def install(self, project_hash: str, tar_bytes: bytes, build_env: bool = True) -> str:
        """Extrai, **verifica a árvore contra ``project_hash``**, publica no cache
        e cria o venv. Idempotente; uma transferência em voo por hash."""
        with self._lock_for(project_hash):
            pp = self.project_path(project_hash)
            if os.path.isdir(pp):
                return pp  # já em cache (imutável)
            tmp = pp + ".tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            extract(tar_bytes, tmp)
            actual = tree_hash(tmp)
            if actual != project_hash:
                shutil.rmtree(tmp, ignore_errors=True)
                raise IntegrityError(
                    f"project_hash não confere: esperado {project_hash}, obtido {actual}")
            os.replace(tmp, pp)  # publica atômico
            if build_env:
                manifest = read_manifest(pp)
                if manifest.get("requirements"):
                    self._env_builder(self.env_path(project_hash), pp, manifest)
            return pp


# ---- fontes de projeto (transporte) -----------------------------------
class Source(Protocol):
    def fetch(self, project_hash: str) -> bytes: ...


class DirSource:
    """Fonte local: lê ``<root>/<hex>.tar.gz`` (dev/teste). A fonte de rede
    (PROJECT_GET sobre o canal Noise → GridFS) implementa a mesma interface."""

    def __init__(self, root: str):
        self.root = root

    def fetch(self, project_hash: str) -> bytes:
        path = os.path.join(self.root, _safe(project_hash) + ".tar.gz")
        if not os.path.exists(path):
            raise ProjectMissing(project_hash)
        with open(path, "rb") as f:
            return f.read()


# ---- resolver (a interface Resolver do ExecutorAgent) ------------------
class ProjectResolver:
    def __init__(self, cache: ProjectCache, source: Source | None = None):
        self.cache = cache
        self.source = source

    def resolve(self, bot_ref: dict) -> tuple[str, str]:
        project_hash = bot_ref["project_hash"]
        script_hash = bot_ref["script_hash"]

        if not self.cache.is_cached(project_hash):
            if self.source is None:
                raise ProjectMissing(project_hash)
            self.cache.install(project_hash, self.source.fetch(project_hash))

        project_dir = self.cache.project_path(project_hash)
        manifest = read_manifest(project_dir)
        entrypoint = _find_entrypoint(manifest, script_hash)
        entry_abs = os.path.join(project_dir, entrypoint)

        # Defesa final entre download e execução: recomputa o hash do entrypoint.
        if file_hash(entry_abs) != script_hash:
            raise IntegrityError(f"entrypoint não confere com {script_hash}")

        return self.cache.env_python(project_hash), entry_abs


def _find_entrypoint(manifest: dict, script_hash: str) -> str:
    for meta in (manifest.get("scripts") or {}).values():
        if meta.get("script_hash") == script_hash:
            return meta["entrypoint"]
    raise IntegrityError(f"script_hash não está no manifesto: {script_hash}")
