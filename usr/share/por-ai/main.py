#!/usr/bin/env python3
"""
POR.ai — Personal Own Router AI.

"""

from __future__ import annotations

import logging
import os
import sys

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

# Identifica o ambiente gráfico e o tipo de sessão
current_desktop = os.environ.get('XDG_CURRENT_DESKTOP', '')
session_type = os.environ.get('XDG_SESSION_TYPE', '').lower()

# Fix for dead keys/accents in different Desktop Environments
if current_desktop in ('Hyprland', 'niri'):
    os.environ.setdefault('GTK_IM_MODULE', 'gtk-im-context-simple')
elif current_desktop == 'KDE':
    if session_type == 'wayland':
        # KDE Plasma 6+ (Wayland default)
        os.environ.setdefault('GTK_IM_MODULE', 'gtk-im-context-simple')
    else:
        # Legacy KDE Plasma (X11)
        os.environ.setdefault('GTK_IM_MODULE', 'xim')

APPLICATION_ID = "io.github.narayanls.PorAi"


class PorAiApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APPLICATION_ID,
            # HANDLES_OPEN permite ser chamado com arquivos (ex.: "por-ai a.pdf"
            # ou "Abrir com…" no gerenciador de arquivos). Sem isso, qualquer
            # argumento vira "arquivo para abrir" e o GIO recusa, sem abrir a
            # janela ("This application can not open files").
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.config = Config()
        self._window: PorAiWindow | None = None
        self._tray: TrayIcon | None = None
        # Rastreia se hold() está ativo, já que apply_tray_setting() chama
        # hold() de forma otimista, antes de saber se o registro assíncrono
        # da bandeja no D-Bus (ver tray.py) realmente vai dar certo. Sem essa
        # flag, um hold()/release() desbalanceado no caminho de erro
        # (_on_tray_unavailable) prendia o app vivo mesmo sem bandeja
        # nenhuma funcionando.
        self._tray_held = False

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        GLib.set_application_name("POR.ai")
        # Atalhos de teclado.
        self.set_accels_for_action("win.new-chat", ["<Control>n"])
        self.set_accels_for_action("win.preferences", ["<Control>comma"])
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
            # Mantém o processo vivo mesmo com a janela oculta. Chamado de
            # forma otimista aqui — se o registro assíncrono falhar depois,
            # _on_tray_unavailable desfaz isso.
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
        # apply_tray_setting() já tinha assumido sucesso (self._tray setado,
        # hold() chamado) antes desta confirmação assíncrona chegar. Como o
        # registro de fato falhou, não existe ícone nenhum — desfazemos esse
        # estado para o app não ficar "preso" vivo por um hold() órfão.
        if self._tray is not None:
            self._tray.unregister()
            self._tray = None
        if self._tray_held:
            self.release()
            self._tray_held = False
        # Sem bandeja de verdade, se a janela estiver oculta ela ficaria
        # inacessível — traz de volta, igual ao ramo de remoção manual.
        if self._window is not None and not self._window.get_visible():
            self._window.present()


def main() -> int:
    app = PorAiApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
