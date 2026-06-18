# install_admin.sh — guia de instalação do cliente Admin

Instalação reproduzível e **sem assistência** do **cliente Admin** (Cliente Parte I)
numa máquina, via `install_admin.sh`. O Admin é o painel do **publicador/administrador**:
publica BOTs e workflows, autora workflows (canvas Nassi na GUI PySide6), inicia e
acompanha ocorrências, lê o catálogo e o inventário. Fala com o **núcleo** pelo
canal Noise (transporte direto na LAN, ou `.onion` via Tor).

> O Admin roda numa máquina **separada** do núcleo (papel `publicador`, provisionado
> como cliente Noise com chave estática + PSK). Aqui ele aponta para o núcleo de
> produção em `192.168.3.3:8400`. Ver `CLAUDE.md` → *Cliente — duas partes → Parte I*.

## O que o script faz

Roda **na máquina do Admin**, como **usuário comum** (não root), da raiz do repo,
em passos idempotentes:

1. **Pré-requisito** — garante `python3-venv` (sudo só se faltar).
2. **Cura resíduo de sudo** — se o `.venv` ou `src/*.egg-info` estiverem de dono
   `root` (de um `sudo pip install -e` anterior, que faz o pip do usuário cair para
   `--user` e a build editable falhar), toma posse via `sudo chown`.
3. **venv** — cria/reusa o virtualenv do usuário (`--system-site-packages` por
   padrão, para reaproveitar o PySide6 do sistema e evitar baixar ~100 MB).
4. **Pacote** — `pip install -e ".[admin]"` (myass + pymongo + cryptography +
   PySide6) e valida imports + GUI.
5. **Endpoint (opcional)** — se `CORE_HOST` setado, reescreve o `endpoint` do
   `admin-0.json` para `direct CORE_HOST:CORE_PORT` (apontar para o núcleo).
6. **Teste de handshake** — roda `admin … catalog` contra o núcleo (best-effort;
   não falha a instalação se o núcleo estiver fora).

> **Idempotente:** reexecutar é seguro — reusa o venv, refaz o editable install,
> retesta o handshake.

## Pré-requisitos

- **Debian** com `python3-venv` (o script instala se faltar) e **sudo** (só p/
  curar dono / instalar venv).
- **Config do Admin** em `./quadrante/admin-0.json` (papel `publicador`). Na
  **mesma máquina** do núcleo, o `install_quadrant.sh` já a auto-provisionou.
  Em **outra máquina**, copie `admin-0.json` out-of-band do provision do núcleo
  (as chaves têm de ser as MESMAS) e aponte com `CORE_HOST=<IP do núcleo>`.
- O script **instala o comando global `madmin`** e grava `MADMIN_*` no `~/.env`
  automaticamente (turnkey) — desligue com `INSTALL_MADMIN=0`.
  Esse JSON **carrega a chave privada estática do Admin** — leve-o à máquina
  **out-of-band**, nunca pela WAN em claro.

## Uso

Da raiz do repo, **na máquina do Admin**:

```bash
./install_admin.sh                        # usa quadrante/admin-0.json como está
CORE_HOST=192.168.3.3 ./install_admin.sh  # já aponta o endpoint p/ o núcleo na LAN
```

### Variáveis de ambiente (defaults = o setup atual)

| Variável | Default | Para quê |
|---|---|---|
| `VENV` | `.venv` | caminho do virtualenv (do usuário) |
| `ADMIN_CONFIG` | `./quadrante/admin-0.json` | config do Admin |
| `CORE_HOST` | *(vazio)* | se setado, reescreve o endpoint p/ `direct CORE_HOST:CORE_PORT` |
| `CORE_PORT` | `8400` | porta do núcleo |
| `SYSTEM_SITE` | `1` | venv com `--system-site-packages` (reusa PySide6 do sistema) |

## O comando `madmin`

Para abrir o painel sem digitar o caminho do venv, há um comando global instalado:

- **`/usr/local/bin/madmin`** — wrapper que roda o Python do `.venv` sobre o launcher.
- **`/usr/local/lib/myass/madmin_launch.py`** — lê o `admin-0.json`, **força o
  endpoint para `192.168.3.3:8400`** (transporte direto) e abre a GUI conectada.

```bash
madmin                          # abre o painel conectado a 192.168.3.3
MADMIN_HOST=10.0.0.5 madmin      # outro núcleo
MADMIN_PORT=8401 madmin
MADMIN_CONFIG=/caminho/admin.json madmin
```

> O wrapper embute caminhos **absolutos** desta máquina (`/home/user/desenv/myass/.venv`
> e `…/quadrante/admin-0.json`). Se mover o repo, atualize o wrapper/launcher.
> `/usr/local/bin` é o local correto (já no `PATH`); `/bin` em Debian é symlink de
> `/usr/bin` (usr-merge), território de pacotes da distro — se quiser lá:
> `sudo ln -s /usr/local/bin/madmin /bin/madmin`.

## Uso do Admin (CLI)

```bash
.venv/bin/python -m myass.ops admin --config quadrante/admin-0.json catalog
.venv/bin/python -m myass.ops admin --config quadrante/admin-0.json publish-bot ./bots/bot_cve
.venv/bin/python -m myass.ops admin --config quadrante/admin-0.json publish-workflow ./wf.json
.venv/bin/python -m myass.ops admin --config quadrante/admin-0.json start <workflow_hash> '{"texto":"..."}'
.venv/bin/python -m myass.ops admin --config quadrante/admin-0.json list
```

## Topologia: alcançar o núcleo

O Admin usa **transporte direto** (`endpoint: {transport: direct, host, port}`).
Para alcançar o núcleo de produção, este precisa **escutar a LAN** (não só
loopback) — no deploy atual o `core.json` está com `host: 0.0.0.0` (= LAN
`192.168.3.0/24` + loopback, LAN fechada). Se o núcleo só escutar `127.0.0.1`,
alternativas: rebind p/ `0.0.0.0`, ou túnel SSH
(`ssh -L 8400:127.0.0.1:8400 user@núcleo` e apontar o Admin p/ `127.0.0.1:8400`).
Drone atrás de rede hostil usa `.onion` (núcleo com `--onion`); o Admin pode
usar o mesmo caminho. A autenticação é sempre o Noise `KKpsk0` (só peers
provisionados fecham handshake). Ver `CLAUDE.md` → *Canais seguros → Transporte*.

## Solução de problemas

| Sintoma | Causa provável / ação |
|---|---|
| `config do admin ausente` | rode o `provision --admins`; confira `./quadrante/admin-0.json` |
| `rode como usuário comum, NÃO root` | o venv deve ser do usuário; não use `sudo ./install_admin.sh` |
| pip cai para `--user` / `Cannot update time stamp … egg-info` | resíduo de `sudo pip` — o script já cura via `chown`; se persistir, `sudo chown -R $USER .venv src/*.egg-info` |
| `núcleo inalcançável` no teste | núcleo fora, não escuta a LAN, ou endpoint errado — veja *Topologia* |
| handshake recusado | `psk`/`scheduler_pub`/`prologue` precisam bater entre `admin-0.json` e o `core.json` do núcleo; papel deve ser `publicador` |
| GUI não abre (`madmin`) | precisa de display gráfico (`DISPLAY`); rode num terminal da sessão gráfica |

Ver também `install_quadrant.md` (núcleo + drone), `doc/DEPLOY.md` (operação) e
`CLAUDE.md` (arquitetura autoritativa).
