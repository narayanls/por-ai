#!/usr/bin/env python3
"""
POR.ai — Private OpenRouter AI.

"""

from __future__ import annotations

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
from ui.window import PorAiWindow

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

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        GLib.set_application_name("POR.ai")
        # Atalhos de teclado.
        self.set_accels_for_action("win.new-chat", ["<Control>n"])
        self.set_accels_for_action("win.preferences", ["<Control>comma"])
        self.set_accels_for_action("window.close", ["<Control>w"])

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


def main() -> int:
    app = PorAiApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
