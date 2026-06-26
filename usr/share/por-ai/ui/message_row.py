"""
Bolha de mensagem do chat.

Mensagens do usuário ficam alinhadas à direita e exibem texto puro.
Mensagens do assistente ficam à esquerda, renderizam Markdown básico
(negrito, itálico, código, títulos) e links clicáveis via Pango markup.
Durante o streaming, o texto é acumulado em texto puro e convertido a
cada chunk — o Label usa set_markup, então a conversão precisa ser
válida a cada atualização.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ui.markup import md_to_pango


class MessageRow(Gtk.Box):
    def __init__(self, role: str, text: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.role = role
        self._text = text          # sempre texto puro (Markdown)
        self._is_assistant = role == "assistant"

        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_halign(
            Gtk.Align.START if self._is_assistant else Gtk.Align.END
        )
        self.append(row)

        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bubble.add_css_class("message-bubble")
        bubble.add_css_class(
            "message-assistant" if self._is_assistant else "message-user"
        )
        bubble.set_hexpand(False)
        row.append(bubble)

        sender = Gtk.Label(
            label="Assistente" if self._is_assistant else "Você"
        )
        sender.add_css_class("caption")
        sender.add_css_class("dim-label")
        sender.set_halign(Gtk.Align.START)
        bubble.append(sender)

        self._label = Gtk.Label()
        self._label.set_wrap(True)
        self._label.set_xalign(0.0)
        self._label.set_halign(Gtk.Align.START)
        self._label.set_max_width_chars(80)

        if self._is_assistant:
            # Links precisam de set_selectable(False) para abrir no primeiro
            # clique: com selectable=True o label captura o evento para seleção
            # de texto antes de activate-link ser emitido, causando scroll da
            # página. O botão de copiar já garante acesso ao texto completo.
            self._label.set_selectable(False)
            self._label.set_use_markup(True)
            self._label.connect("activate-link", self._on_link_activated)
            self._set_markup(text)
        else:
            self._label.set_selectable(True)
            self._label.set_text(text)

        bubble.append(self._label)

        if self._is_assistant:
            copy_button = Gtk.Button()
            copy_button.set_icon_name("edit-copy-symbolic")
            copy_button.add_css_class("flat")
            copy_button.set_tooltip_text("Copiar resposta")
            copy_button.set_halign(Gtk.Align.START)
            copy_button.connect("clicked", self._on_copy)
            bubble.append(copy_button)
            self._copy_button = copy_button
        else:
            self._copy_button = None

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #

    def set_text(self, text: str) -> None:
        self._text = text
        if self._is_assistant:
            self._set_markup(text)
        else:
            self._label.set_text(text)

    def append_text(self, chunk: str) -> None:
        self._text += chunk
        if self._is_assistant:
            self._set_markup(self._text)
        else:
            self._label.set_text(self._text)

    def get_text(self) -> str:
        return self._text

    # ------------------------------------------------------------------ #
    # Internos                                                             #
    # ------------------------------------------------------------------ #

    def _set_markup(self, text: str) -> None:
        """Converte Markdown → Pango markup e aplica no label com fallback."""
        if not text:
            self._label.set_markup("")
            return
        markup = md_to_pango(text)
        try:
            self._label.set_markup(markup)
        except Exception:
            # Se o markup gerado for inválido (pode ocorrer no meio do
            # streaming com tags incompletas), cai para texto puro.
            self._label.set_text(text)

    @staticmethod
    def _on_link_activated(_label: Gtk.Label, uri: str) -> bool:
        """Abre o link no navegador padrão via GIO."""
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception:
            pass
        return True  # True = GTK não tenta abrir o link por conta própria

    def _on_copy(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            # Copia o texto puro (Markdown), não o markup.
            display.get_clipboard().set(self._text)
        if self._copy_button is not None:
            self._copy_button.set_icon_name("object-select-symbolic")
            self._copy_button.set_tooltip_text("Copiado!")

            def restore() -> bool:
                if self._copy_button is not None:
                    self._copy_button.set_icon_name("edit-copy-symbolic")
                    self._copy_button.set_tooltip_text("Copiar resposta")
                return False

            GLib.timeout_add_seconds(2, restore)
