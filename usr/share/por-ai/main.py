#!/usr/bin/env python3
"""
POR.ai — Personal Own Router AI.

"""

from __future__ import annotations

import logging
import os
import sys
import signal

# Permite importar os pacotes locais (core/ e ui/) independentemente do
# diretório de trabalho a partir do qual o app foi iniciado.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

from core.config import Config
from ui.tray import MenuItem, TrayIcon
from ui.window import PorAiWindow

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- #
# Método de entrada (acentos e dead keys)                                #
# --------------------------------------------------------------------- #
#
# Nunca usar "xim": não é suportado pelo GTK4 e faz teclas de edição serem
# entregues como texto bruto.
#
# Solução completa e recomendada pelo GTK: ter ibus ou fcitx5 ativo na
# sessão. O "simple" é a implementação ingênua — cobre o português bem, mas
# não substitui um IME de verdade.

_NO_TEXT_INPUT_PROTOCOL = {"Hyprland", "niri", "sway", "Wayfire", "river"}


def _configure_im_module() -> None:
    """Define GTK_IM_MODULE apenas quando o ambiente exige.

    Deve rodar antes de qualquer widget ser criado. Idempotente e
    conservador: nunca sobrescreve uma escolha explícita do usuário, exceto
    o valor quebrado "xim".

    Escape hatch para depuração ou para quem tem um setup específico::

        POR_AI_IM_MODULE=ibus por-ai     # força um módulo
        POR_AI_IM_MODULE= por-ai         # não mexe em nada
    """
    override = os.environ.get("POR_AI_IM_MODULE")
    if override is not None:
        if override:
            os.environ["GTK_IM_MODULE"] = override
            logger.info("GTK_IM_MODULE=%r forçado via POR_AI_IM_MODULE.", override)
        else:
            os.environ.pop("GTK_IM_MODULE", None)
            logger.info("GTK_IM_MODULE removido via POR_AI_IM_MODULE vazio.")
        return

    current = os.environ.get("GTK_IM_MODULE", "").strip()

    if current == "xim":
        os.environ["GTK_IM_MODULE"] = "simple"
        logger.info("GTK_IM_MODULE=xim não é suportado no GTK4; usando 'simple'.")
        return

    if current:
        # ibus, fcitx, wayland… escolha explícita do usuário ou do ambiente.
        logger.debug("GTK_IM_MODULE já definido como %r; mantido.", current)
        return

    # Se há um IME de verdade ativo, o GTK conversa com ele — não interferir.
    if any(k in os.environ.get("XMODIFIERS", "") for k in ("ibus", "fcitx")):
        logger.debug("IME detectado em XMODIFIERS; GTK_IM_MODULE não alterado.")
        return

    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" and any(d in _NO_TEXT_INPUT_PROTOCOL for d in desktops):
        os.environ["GTK_IM_MODULE"] = "simple"
        logger.info(
            "Compositor sem protocolo de texto (%s); GTK_IM_MODULE=simple "
            "para manter acentos funcionando.",
            ":".join(d for d in desktops if d),
        )


_configure_im_module()

APPLICATION_ID = "io.github.narayanls.PorAi"


class PorAiApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.config = Config()
        self._window: PorAiWindow | None = None
        self._tray: TrayIcon | None = None
        self._tray_held = False

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        GLib.set_application_name("POR.ai")
        # Atalhos de teclado.
        self.set_accels_for_action("win.new-chat", ["<Control>n"])
        self.set_accels_for_action("win.preferences", ["<Control>comma"])
        self.set_accels_for_action("win.search-chat", ["<Control>f"])
        self.set_accels_for_action("window.close", ["<Control>w"])
        print("[tray] do_startup -> chamando apply_tray_setting", flush=True)
        # Cria o ícone da bandeja, se a preferência estiver ativa.
        self.apply_tray_setting()

    def _ensure_window(self) -> PorAiWindow:
        if self._window is None:
            self._window = PorAiWindow(self, self.config)
        return self._window

    def do_activate(self) -> None:
        # Chamado quando o app é aberto sem arquivos.
        self._ensure_window().present()

    def do_open(self, files, _n_files, _hint) -> None:
        # Chamado quando o app é aberto com um ou mais arquivos. Anexa os
        # arquivos suportados (até o limite da janela) e mostra a interface.
        window = self._ensure_window()
        for gfile in files:
            path = gfile.get_path()
            if path:
                window.attach_file(path)
        window.present()

    # ------------------------------------------------------------------ #
    # Bandeja do sistema                                                   #
    # ------------------------------------------------------------------ #

    def apply_tray_setting(self) -> None:
        """Cria ou destrói o ícone da bandeja conforme a configuração atual.

        Idempotente. Deve ser chamado no startup e sempre que a preferência
        ``show_tray_icon`` mudar (ver gancho em ``on_saved`` das preferências).
        """
        want = self.config.show_tray_icon
        print(
            f"[tray] apply_tray_setting: want={want!r} "
            f"(tipo {type(want).__name__}), tray_existe={self._tray is not None}",
            flush=True,
        )

        if want and self._tray is None:
            print("[tray] -> entrando no ramo de CRIACAO da bandeja", flush=True)
            self._tray = TrayIcon(
                app_id=APPLICATION_ID,
                icon_name="por-ai",  # mesmo nome usado no AboutWindow / tema
                title="POR.ai",
                on_activate=self._toggle_window,
                menu_items=[
                    MenuItem("toggle", "Mostrar / Ocultar", self._toggle_window),
                    MenuItem.separator(),
                    MenuItem("quit", "Sair", self.quit),
                ],
                on_unavailable=self._on_tray_unavailable,
                debug=True,
            )
            self._tray.register()
            # Mantém o processo vivo mesmo com a janela oculta.
            if not self._tray_held:
                self.hold()
                self._tray_held = True

        elif not want and self._tray is not None:
            print("[tray] -> entrando no ramo de REMOCAO da bandeja", flush=True)
            self._tray.unregister()
            self._tray = None
            if self._tray_held:
                self.release()
                self._tray_held = False
            # Sem bandeja, se a janela estiver oculta, o app ficaria invisível
            # e sem como reaparecer — então a trazemos de volta.
            if self._window is not None and not self._window.get_visible():
                self._window.present()
        else:
            print("[tray] -> nenhum ramo: nada a fazer", flush=True)

    def _toggle_window(self) -> None:
        window = self._ensure_window()
        if window.get_visible():
            window.set_visible(False)
        else:
            window.present()

    @property
    def tray_active(self) -> bool:
        """True se a bandeja está ativa — usado pela janela ao fechar."""
        return self._tray is not None

    def _on_tray_unavailable(self) -> None:
        logger.warning(
            "Nenhum 'watcher' de bandeja (StatusNotifierItem) foi encontrado no "
            "barramento. No GNOME, instale a extensão 'AppIndicator and "
            "KStatusNotifierItem Support' para ver o ícone."
        )

        if self._tray is not None:
            self._tray.unregister()
            self._tray = None
        if self._tray_held:
            self.release()
            self._tray_held = False
        if self._window is not None and not self._window.get_visible():
            self._window.present()



def main() -> int:
    app = PorAiApplication()

    def _quit_on_signal(*_args) -> None:
        GLib.idle_add(app.quit)

    signal.signal(signal.SIGINT, _quit_on_signal)
    signal.signal(signal.SIGTERM, _quit_on_signal)

    try:
        return app.run(sys.argv)
    except KeyboardInterrupt:
        return 130  # código convencional de "interrompido por Ctrl+C"

if __name__ == "__main__":
    sys.exit(main())
