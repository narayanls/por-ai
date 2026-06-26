"""
Verificação e download de atualizações do POR.ai.

Fluxo:
  1. Lê a versão instalada de /usr/share/por-ai/version.txt
  2. Consulta a API do GitHub para obter a última release
  3. Compara as versões (semver simples)
  4. Se houver atualização, detecta o sistema e baixa o pacote correto
  5. Abre o pacote com xdg-open para o instalador do sistema assumir
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Arquivo gravado pelo PKGBUILD/build-deb.sh com a versão da tag.
VERSION_FILE = "/usr/share/por-ai/version.txt"

# API do GitHub — sem autenticação, limite de 60 req/hora por IP (suficiente).
GITHUB_API = "https://api.github.com/repos/narayanls/por-ai/releases/latest"


# ── Detecção de sistema ───────────────────────────────────────────────────────

def _detect_system() -> str:
    """Retorna 'arch', 'deb' ou 'unknown'."""
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
    return ".pkg.tar.zst" if system == "arch" else ".deb"


# ── Leitura da versão local ───────────────────────────────────────────────────

def read_local_version() -> Optional[str]:
    """Lê a versão instalada do version.txt. Retorna None se não encontrado."""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


# ── Comparação de versões ─────────────────────────────────────────────────────

def _version_tuple(version: str):
    """Converte '0.1.6' ou 'v0.1.6' em (0, 1, 6) para comparação."""
    clean = version.lstrip("v").split("-")[0]   # remove 'v' e sufixos como '-1'
    parts = re.split(r"[.\-]", clean)
    try:
        return tuple(int(p) for p in parts if p.isdigit())
    except ValueError:
        return (0,)


def is_newer(remote: str, local: str) -> bool:
    """True se a versão remota for maior que a local."""
    return _version_tuple(remote) > _version_tuple(local)


# ── Consulta à API do GitHub ──────────────────────────────────────────────────

def fetch_latest_release(timeout: int = 10) -> Dict[str, Any]:
    """
    Retorna o dict da última release do GitHub.
    Campos relevantes: tag_name, body, assets[].browser_download_url
    """
    import requests
    response = requests.get(
        GITHUB_API,
        headers={"Accept": "application/vnd.github+json"},
        timeout=timeout,
    )
    response.encoding = "utf-8"
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
    with requests.get(url, stream=True, timeout=timeout) as response:
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


# ── Abertura com instalador do sistema ────────────────────────────────────────

def open_with_system_installer(path: str) -> None:
    """Abre o pacote com xdg-open para o instalador do sistema assumir."""
    subprocess.Popen(["xdg-open", path])


# ── Verificação completa (roda em thread) ─────────────────────────────────────

class UpdateChecker:
    def __init__(self) -> None:
        self._system = _detect_system()

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
                # Instalação de desenvolvimento sem version.txt: silencioso.
                logger.info("version.txt não encontrado; verificação ignorada.")
                return

            release = fetch_latest_release()
            remote_tag = release.get("tag_name", "")

            if not remote_tag:
                logger.warning("GitHub não retornou tag_name.")
                return

            if is_newer(remote_tag, local):
                on_update_available(release, local)
            else:
                if on_no_update:
                    on_no_update()

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Verificação de update falhou: %s", exc)
            if on_error:
                on_error(str(exc))

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
        on_done: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Baixa o pacote em /tmp e abre com o instalador do sistema.
        Todos os callbacks chamados na thread de trabalho.
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
        dest = os.path.join(tempfile.gettempdir(), filename)

        def worker() -> None:
            try:
                download_asset(url, dest, on_progress=on_progress)
                open_with_system_installer(dest)
                if on_done:
                    on_done(dest)
            except Exception as exc:  # pylint: disable=broad-except
                if on_error:
                    on_error(str(exc))

        threading.Thread(target=worker, daemon=True).start()
