"""
Verificação e download de atualizações do POR.ai.

Fluxo:
  1. Lê a versão instalada do version.txt que fica ao lado de core/ e ui/
     (/usr/share/por-ai no pacote nativo, /app/share/por-ai no Flatpak)
  2. Consulta a API do GitHub para obter a última release
  3. Compara as versões (semver simples)
  4. Se houver atualização, detecta o sistema e baixa o pacote correto
  5. Instala o pacote:
       - Arch/Debian: gerenciador nativo (pacman -U / apt install), elevando
         privilégio via pkexec (ou terminal + sudo como fallback)
       - Flatpak: `flatpak install --bundle` rodando no HOST, via
         flatpak-spawn (exige --talk-name=org.freedesktop.Flatpak no manifesto)
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Arquivo gravado pelo PKGBUILD / build-deb.sh / manifesto do Flatpak com a
# versão do pacote. Fica na raiz do app, ao lado de core/ e ui/ — por isso o
# caminho é relativo a este arquivo: dá /usr/share/por-ai/version.txt no pacote
# nativo e /app/share/por-ai/version.txt dentro do Flatpak.
VERSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "version.txt"
)

# API do GitHub — sem autenticação, limite de 60 req/hora por IP (suficiente).
GITHUB_API = "https://api.github.com/repos/narayanls/por-ai/releases/latest"

# O GitHub exige um User-Agent descritivo; sem ele (ou com o genérico do
# python-requests) a API costuma responder HTTP 403.
USER_AGENT = "por-ai-update-checker/1.0 (+https://github.com/narayanls/por-ai)"

# Nome do pacote, usado para extrair a versão do nome do asset.
PKG_NAME = "por-ai"


# ── Detecção de sistema ───────────────────────────────────────────────────────

# Gravado pelo Flatpak na raiz de toda sandbox; a seção [Instance] traz o
# caminho real da instalação (app-path).
FLATPAK_INFO = "/.flatpak-info"


def running_in_flatpak() -> bool:
    """True se este processo está rodando dentro da sandbox do Flatpak."""
    return os.path.exists(FLATPAK_INFO) or bool(os.environ.get("FLATPAK_ID"))


def _detect_system() -> str:
    """Retorna 'flatpak', 'arch', 'deb' ou 'unknown'."""
    # Flatpak vem primeiro: dentro da sandbox não existe pacman nem dpkg, e o
    # pacote certo a baixar é o bundle .flatpak, qualquer que seja a distro.
    if running_in_flatpak():
        return "flatpak"
    # Arch/CachyOS/Manjaro: pacman disponível
    try:
        subprocess.run(["pacman", "--version"], capture_output=True, timeout=3)
        return "arch"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Debian/Ubuntu/Zorin: dpkg disponível
    try:
        subprocess.run(["dpkg", "--version"], capture_output=True, timeout=3)
        return "deb"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _asset_suffix(system: str) -> str:
    if system == "flatpak":
        return ".flatpak"
    return ".pkg.tar.zst" if system == "arch" else ".deb"


def _version_from_asset_name(name: str) -> Optional[str]:
    """
    Extrai a versão do nome do asset — ou seja, a versão REAL do pacote
    (pkgver), que é o que o version.txt registra após a instalação.

      por-ai-0.1.7.3-1-any.pkg.tar.zst  ->  0.1.7.3-1
      por-ai_0.1.7.3_all.deb            ->  0.1.7.3
      por-ai-0.1.7.3.flatpak            ->  0.1.7.3
      io.github.narayanls.PorAi.flatpak ->  None (quem chama usa a tag)

    Comparar contra isto (em vez da tag do git) evita o descasamento entre
    o esquema da tag e o esquema do pacote.
    """
    if name.endswith(".pkg.tar.zst"):
        # <pkgname>-<pkgver>-<pkgrel>-<arch>.pkg.tar.zst
        m = re.match(
            rf"^{re.escape(PKG_NAME)}-(.+)-[^-]+\.pkg\.tar\.zst$", name
        )
        if m:
            return m.group(1)
    elif name.endswith(".deb"):
        # <pkgname>_<version>_<arch>.deb
        m = re.match(rf"^{re.escape(PKG_NAME)}_(.+?)_[^_]+\.deb$", name)
        if m:
            return m.group(1)
    elif name.endswith(".flatpak"):
        # Aceita qualquer nome que contenha a versão (com ou sem "v" e com
        # revisão opcional): por-ai-0.1.7.3.flatpak, por-ai-v0.1.7.3-2.flatpak…
        # O ID do app não atrapalha: "io.github.narayanls.PorAi" não tem
        # números separados por ponto.
        m = re.search(r"(?<![\d.])v?(\d+(?:\.\d+)+(?:-\d+)?)(?!\.?\d)", name)
        if m:
            return m.group(1)
    return None


# ── Leitura da versão local ───────────────────────────────────────────────────

def read_local_version() -> Optional[str]:
    """Lê a versão instalada do version.txt. Retorna None se não encontrado."""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


# ── Comparação de versões ─────────────────────────────────────────────────────

def _version_tuple(version: str) -> tuple:
    """
    Converte 'v0.1.7.1-2' em (0, 1, 7, 1, 2) para comparação.

    O sufixo de revisão ('-1', '-2'…) NÃO é descartado — ele entra como mais
    um número de versão, igual ao Tac Writer. Assim 'v0.1.7.1-1' e
    'v0.1.7.1-2' deixam de ser considerados iguais.
    """
    clean = version.strip().lstrip("v")
    # Remove o epoch (ex.: '1:0.1.7') se existir, para não quebrar o .isdigit().
    if ":" in clean:
        clean = clean.split(":", 1)[-1]
    parts = re.split(r"[.\-]", clean)
    nums = [int(p) for p in parts if p.isdigit()]
    return tuple(nums) if nums else (0,)


def is_newer(remote: str, local: str) -> bool:
    """True se a versão remota for maior que a local."""
    rt, lt = _version_tuple(remote), _version_tuple(local)
    # Iguala o comprimento para uma comparação posicional consistente.
    length = max(len(rt), len(lt))
    rt += (0,) * (length - len(rt))
    lt += (0,) * (length - len(lt))
    return rt > lt


# ── Consulta à API do GitHub ──────────────────────────────────────────────────

def fetch_latest_release(timeout: int = 10) -> Dict[str, Any]:
    """
    Retorna o dict da última release do GitHub.
    Campos relevantes: tag_name, body, assets[].browser_download_url
    """
    import requests
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Opcional: token do GitHub eleva o limite de 60 → 5000 req/hora. Útil em
    # dev para não esbarrar no 403 ao testar repetidamente. Ignorado se ausente.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("POR_AI_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(GITHUB_API, headers=headers, timeout=timeout)
    response.encoding = "utf-8"

    if response.status_code == 403:
        # 403 do GitHub é quase sempre limite de requisições por IP
        # (60/hora sem autenticação) ou User-Agent ausente/bloqueado.
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining == "0" and reset:
            import datetime
            try:
                when = datetime.datetime.fromtimestamp(int(reset))
                quando = f" Tente novamente após {when:%H:%M}."
            except (ValueError, OSError):
                quando = ""
            raise RuntimeError(
                "Limite de requisições do GitHub atingido "
                f"(60/hora por IP).{quando}"
            )
        raise RuntimeError(
            "GitHub recusou a requisição (HTTP 403) — possível limite de "
            "requisições ou User-Agent bloqueado."
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"GitHub respondeu HTTP {response.status_code}."
        )
    return response.json()


# ── Download do pacote ────────────────────────────────────────────────────────

def download_asset(
    url: str,
    dest_path: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    timeout: int = 120,
) -> None:
    """
    Baixa um asset do GitHub para dest_path.
    on_progress(bytes_baixados, total_bytes) chamado a cada chunk.
    """
    import requests
    with requests.get(
        url,
        stream=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)


# ── Instalação com o gerenciador de pacotes nativo ────────────────────────────

def _install_argv(system: str, path: str) -> Optional[list]:
    """Monta o comando de instalação nativo (sem o sudo/pkexec)."""
    if system == "arch":
        # Caminho absoluto: o pkexec não herda o PATH e algumas políticas do
        # polkit exigem o caminho completo do programa.
        pacman = shutil.which("pacman") or "pacman"
        return [pacman, "-U", "--noconfirm", path]
    if system == "deb":
        apt = shutil.which("apt-get") or "apt-get"
        return [apt, "install", "-y", path]
    return None


def _find_terminal() -> Optional[Tuple[str, str]]:
    """Retorna (comando, flag_de_exec) do primeiro terminal encontrado."""
    terminals = [
        ("gnome-terminal", "--"),
        ("konsole", "-e"),
        ("xfce4-terminal", "-e"),
        ("mate-terminal", "-e"),
        ("alacritty", "-e"),
        ("kitty", "-e"),
        ("ptyxis", "--"),
        ("tilix", "-e"),
        ("xterm", "-e"),
        ("terminator", "-x"),
    ]
    for cmd, flag in terminals:
        if shutil.which(cmd):
            return cmd, flag
    return None


# ── Instalação do bundle no Flatpak ───────────────────────────────────────────

def _download_dir(system: str) -> str:
    """Pasta onde o pacote é baixado.

    No Flatpak o /tmp é privado da sandbox: o `flatpak` do host não enxergaria
    o arquivo. Já a pasta de cache do app (~/.var/app/<id>/cache) existe com o
    MESMO caminho dentro e fora da sandbox, então é para lá que o bundle vai.
    """
    if system != "flatpak":
        return tempfile.gettempdir()
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = os.path.join(base, PKG_NAME, "updates")
    os.makedirs(path, exist_ok=True)
    return path


def _flatpak_scope() -> str:
    """'--user' ou '--system', conforme onde ESTA instalação está.

    Atualizar na instalação errada criaria uma segunda cópia do app em vez de
    substituir a que está rodando.
    """
    app_path = ""
    try:
        with open(FLATPAK_INFO, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("app-path="):
                    app_path = line.split("=", 1)[1].strip()
                    break
    except OSError:
        pass
    return "--system" if app_path.startswith("/var/lib/flatpak/") else "--user"


def _install_flatpak_bundle(
    path: str,
    on_status: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """Instala o bundle .flatpak por cima da versão atual.

    O binário `flatpak` não existe dentro da sandbox: o comando roda no host
    via flatpak-spawn. `flatpak install --bundle` sobre um app já instalado
    funciona como atualização (mesma origem, novo commit).
    """
    if not shutil.which("flatpak-spawn"):
        return False, "flatpak-spawn não encontrado dentro da sandbox."

    scope = _flatpak_scope()
    argv = [
        "flatpak-spawn", "--host",
        "flatpak", "install", scope, "--noninteractive", "-y", "--bundle", path,
    ]
    if on_status:
        on_status(
            "Instalando… confirme a senha de administrador se o sistema pedir."
            if scope == "--system" else "Instalando a nova versão…"
        )
    print(f"[POR.ai] Instalando via flatpak: {' '.join(argv)}", flush=True)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True)
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"Falha ao iniciar o flatpak: {exc}"

    if proc.returncode == 0:
        return True, ""

    output = (proc.stderr or proc.stdout or "").strip()
    if "org.freedesktop.Flatpak" in output:
        # flatpak-spawn não conseguiu falar com o host.
        return False, (
            "Este Flatpak não tem permissão para instalar atualizações "
            "(falta --talk-name=org.freedesktop.Flatpak). Baixe o arquivo "
            ".flatpak na página de releases e instale manualmente."
        )
    detail = output.splitlines()[-1] if output else ""
    return False, detail or f"flatpak retornou código {proc.returncode}."


def install_package(
    path: str,
    system: str,
    on_status: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """
    Instala o pacote baixado usando o gerenciador nativo, com elevação de
    privilégio. Retorna (sucesso, mensagem_de_erro).

    No Flatpak, instala o bundle pelo `flatpak` do host (ver
    _install_flatpak_bundle). Nos pacotes nativos, a estratégia é:
      1. pkexec  → prompt gráfico de senha, código de saída real (preferido)
      2. terminal + sudo → fallback quando não há agente polkit/pkexec
    """
    if system == "flatpak":
        return _install_flatpak_bundle(path, on_status=on_status)

    argv = _install_argv(system, path)
    if argv is None:
        return False, "Sistema não suportado para instalação automática."

    # 1) pkexec: janela gráfica de senha e código de saída confiável.
    if shutil.which("pkexec"):
        if on_status:
            on_status(
                "Instalando… confirme a senha de administrador na "
                "janela do sistema."
            )
        print(f"[POR.ai] Instalando via pkexec: {' '.join(argv)}", flush=True)
        try:
            proc = subprocess.run(
                ["pkexec"] + argv,
                capture_output=True,
                text=True,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return False, f"Falha ao iniciar o instalador: {exc}"

        if proc.returncode == 0:
            return True, ""
        if proc.returncode == 126:
            return False, "Autenticação cancelada pelo usuário."
        if proc.returncode != 127:
            # 127 = pkexec não conseguiu autorizar/executar → tenta terminal.
            # Qualquer outro código é erro real do pacman/apt.
            detail = (proc.stderr or proc.stdout or "").strip()
            detail = detail.splitlines()[-1] if detail else ""
            return False, detail or f"Instalador retornou código {proc.returncode}."

    # 2) Fallback: abre um terminal e roda com sudo, usando um arquivo
    #    sentinela para detectar sucesso (o código de saída do terminal não
    #    reflete o do comando interno).
    term = _find_terminal()
    if term is None:
        manual = "sudo " + " ".join(shlex.quote(a) for a in argv)
        return False, (
            "Não foi possível instalar automaticamente (sem pkexec nem "
            f"terminal). Instale manualmente com:\n{manual}"
        )

    cmd, flag = term
    sentinel = os.path.join(
        tempfile.gettempdir(), f"por-ai-install-{os.getpid()}.ok"
    )
    try:
        if os.path.exists(sentinel):
            os.remove(sentinel)
    except OSError:
        pass

    inner = (
        "sudo " + " ".join(shlex.quote(a) for a in argv)
        + f" && touch {shlex.quote(sentinel)}; "
        + "echo; read -n1 -r -p 'Instalação finalizada. "
        + "Pressione qualquer tecla para fechar…'"
    )
    if on_status:
        on_status("Instalando… digite sua senha no terminal que abriu.")
    try:
        subprocess.run([cmd, flag, "bash", "-c", inner])
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"Falha ao abrir o terminal: {exc}"

    if os.path.exists(sentinel):
        try:
            os.remove(sentinel)
        except OSError:
            pass
        return True, ""
    return False, "A instalação não foi concluída (verifique o terminal)."


# ── Verificação completa (roda em thread) ─────────────────────────────────────

class UpdateChecker:
    def __init__(self, current_version: Optional[str] = None) -> None:
        self._system = _detect_system()
        # Versão embutida no app, usada como fallback quando o version.txt
        # não existe (ex.: rodando do código-fonte, sem pacote instalado).
        self._current_version = current_version

    @property
    def system(self) -> str:
        return self._system

    def check_async(
        self,
        on_update_available: Callable[[Dict[str, Any], str], None],
        on_no_update: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Verifica atualizações em background.
        Chama on_update_available(release_dict, local_version) se houver update.
        Todos os callbacks são chamados na thread de trabalho — use GLib.idle_add
        na camada de UI para atualizar a interface.
        """
        threading.Thread(
            target=self._worker,
            args=(on_update_available, on_no_update, on_error),
            daemon=True,
        ).start()

    def _worker(
        self,
        on_update_available,
        on_no_update,
        on_error,
    ) -> None:
        try:
            local = read_local_version()
            if local is None:
                # Sem version.txt (instalação de desenvolvimento): usa a versão
                # embutida no app como fallback, em vez de abortar em silêncio.
                local = self._current_version
                if local is None:
                    logger.warning(
                        "version.txt não encontrado e nenhuma versão de app "
                        "informada; verificação ignorada."
                    )
                    return
                logger.info(
                    "version.txt ausente; usando versão do app: %s", local
                )

            release = fetch_latest_release()
            remote_tag = release.get("tag_name", "")

            # No Flatpak só existe atualização quando a release traz o bundle
            # .flatpak. Sem isso (ex.: release publicada só com os pacotes
            # Arch/Debian) o diálogo ofereceria um update impossível de instalar.
            if self._system == "flatpak" and not self.find_asset_url(release):
                logger.info(
                    "Release %s ainda não tem bundle .flatpak; nada a fazer.",
                    remote_tag,
                )
                if on_no_update:
                    on_no_update()
                return

            # Versão REAL do pacote (do nome do asset), que é o que o
            # version.txt guarda. Cai para a tag só se não houver asset.
            remote_version = self.remote_version(release) or remote_tag

            if not remote_version:
                logger.warning("GitHub não retornou versão utilizável.")
                return

            logger.info(
                "Comparando versões — local: %s | remota: %s (tag: %s)",
                local, remote_version, remote_tag,
            )

            if is_newer(remote_version, local):
                on_update_available(release, local)
            else:
                if on_no_update:
                    on_no_update()

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Verificação de update falhou: %s", exc)
            if on_error:
                on_error(str(exc))

    def remote_version(self, release: Dict[str, Any]) -> Optional[str]:
        """Versão do asset correspondente ao sistema atual (= pkgver)."""
        suffix = _asset_suffix(self._system)
        for asset in release.get("assets") or []:
            name = asset.get("name", "")
            if name.endswith(suffix):
                version = _version_from_asset_name(name)
                if version:
                    return version
        return None

    def find_asset_url(self, release: Dict[str, Any]) -> Optional[str]:
        """Retorna a URL do asset correto para o sistema atual."""
        suffix = _asset_suffix(self._system)
        assets = release.get("assets") or []
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(suffix):
                return asset.get("browser_download_url")
        return None

    def download_and_open(
        self,
        release: Dict[str, Any],
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_done: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Baixa o pacote (em /tmp, ou no cache do app quando em Flatpak) e o
        instala com o gerenciador nativo / `flatpak install --bundle`.
        Todos os callbacks são chamados na thread de trabalho — use
        GLib.idle_add na camada de UI.
        """
        url = self.find_asset_url(release)
        if not url:
            if on_error:
                on_error(
                    f"Nenhum pacote encontrado para este sistema "
                    f"({_asset_suffix(self._system)})."
                )
            return

        filename = url.split("/")[-1]
        dest = os.path.join(_download_dir(self._system), filename)

        def worker() -> None:
            try:
                download_asset(url, dest, on_progress=on_progress)
                success, message = install_package(
                    dest, self._system, on_status=on_status
                )
                if success:
                    if on_done:
                        on_done(dest)
                elif on_error:
                    on_error(message)
            except Exception as exc:  # pylint: disable=broad-except
                if on_error:
                    on_error(str(exc))
            finally:
                # O bundle fica no cache do app (não em /tmp, que o sistema
                # limpa sozinho): apaga para não acumular a cada atualização.
                if self._system == "flatpak":
                    try:
                        os.remove(dest)
                    except OSError:
                        pass

        threading.Thread(target=worker, daemon=True).start()
