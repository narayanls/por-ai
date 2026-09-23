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
import re

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ui.markup import escape_plain, md_to_pango
from typing import List, Optional


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

        if self._is_assistant:
            # Cabeçalho da bolha: "Assistente" à esquerda, botão de copiar
            # à direita — fica no topo pra ser fácil de achar em respostas
            # longas (ex.: scripts), sem precisar rolar até o fim.
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            sender = Gtk.Label(label="Assistente")
            sender.add_css_class("caption")
            sender.add_css_class("dim-label")
            sender.set_halign(Gtk.Align.START)
            sender.set_hexpand(True)
            header.append(sender)

            copy_button = Gtk.Button()
            copy_button.set_icon_name("edit-copy-symbolic")
            copy_button.add_css_class("flat")
            copy_button.add_css_class("circular")
            copy_button.set_tooltip_text("Copiar resposta")
            copy_button.set_valign(Gtk.Align.START)
            copy_button.set_halign(Gtk.Align.END)
            copy_button.connect("clicked", self._on_copy)
            header.append(copy_button)
            self._copy_button = copy_button

            bubble.append(header)
        else:
            sender = Gtk.Label(label="Você")
            sender.add_css_class("caption")
            sender.add_css_class("dim-label")
            sender.set_halign(Gtk.Align.START)
            bubble.append(sender)
            self._copy_button = None

        self._label = Gtk.Label()
        self._label.set_wrap(True)
        self._label.set_xalign(0.0)
        self._label.set_halign(Gtk.Align.START)
        self._label.set_max_width_chars(80)

        if self._is_assistant:
            self._label.set_selectable(True)
            self._label.set_focus_on_click(False)
            self._label.set_can_focus(True)
            self._label.set_use_markup(True)
            self._label.connect("activate-link", self._on_link_activated)
            self._set_markup(text)
        else:
            self._label.set_selectable(True)
            self._label.set_text(text)

        bubble.append(self._label)

        if self._is_assistant:
            self._meta_label = Gtk.Label()
            self._meta_label.add_css_class("caption")
            self._meta_label.add_css_class("dim-label")
            self._meta_label.set_halign(Gtk.Align.START)
            self._meta_label.set_visible(False)
            bubble.append(self._meta_label)
        else:
            self._meta_label = None



    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #

    def set_text(self, text: str) -> None:
        self._text = text
        # Os destaques da busca usam posições do texto antigo; com o texto
        # trocado eles cairiam no lugar errado.
        self.clear_search_highlights()
        if self._is_assistant:
            self._set_markup(text)
        else:
            self._label.set_text(text)

    def append_text(self, chunk: str) -> None:
        self._text += chunk
        self.clear_search_highlights()
        if self._is_assistant:
            self._set_markup(self._text)
        else:
            self._label.set_text(self._text)

    def get_text(self) -> str:
        return self._text

    # ------------------------------------------------------------------ #
    # Busca na conversa                                                    #
    # ------------------------------------------------------------------ #

    # Cores dos destaques (Pango usa 16 bits por canal). Texto sempre
    # preto por cima, para ficar legível tanto no tema claro quanto no
    # escuro e também na bolha do usuário (fundo com a cor de destaque).
    _HL_MATCH = (0xF6F6, 0xD3D3, 0x2D2D)    # amarelo: todas as ocorrências
    _HL_CURRENT = (0xFFFF, 0x7878, 0x0000)  # laranja: ocorrência atual

    def get_display_text(self) -> str:
        """Texto como aparece na tela (sem Markdown nem markup) — é nele
        que a busca procura, para que as posições batam com o que o usuário
        vê. ``Gtk.Label.get_text()`` já devolve o texto sem o markup."""
        return self._label.get_text()

    def set_search_highlights(
        self, ranges: List[tuple], current: Optional[int] = None
    ) -> None:
        """Destaca as ocorrências ``ranges`` ([(início, fim), ...] em
        caracteres do texto exibido). ``current`` é o índice, dentro de
        ``ranges``, da ocorrência selecionada agora."""
        if not ranges:
            self.clear_search_highlights()
            return
        # Recomeça de um layout limpo antes de aplicar os destaques novos
        # (ver clear_search_highlights).
        self.clear_search_highlights()
        text = self._label.get_text()
        attrs = Pango.AttrList()
        for index, (start, end) in enumerate(ranges):
            # Pango trabalha com posições em BYTES de UTF-8, não caracteres.
            byte_start = len(text[:start].encode("utf-8"))
            byte_end = byte_start + len(text[start:end].encode("utf-8"))
            color = self._HL_CURRENT if index == current else self._HL_MATCH
            background = Pango.attr_background_new(*color)
            background.start_index = byte_start
            background.end_index = byte_end
            attrs.insert(background)
            foreground = Pango.attr_foreground_new(0, 0, 0)
            foreground.start_index = byte_start
            foreground.end_index = byte_end
            attrs.insert(foreground)
        # Os atributos são aplicados por cima do markup já existente.
        self._label.set_attributes(attrs)
        self._has_search_highlights = True

    def clear_search_highlights(self) -> None:
        """Remove os destaques da busca.

        Só ``set_attributes(None)`` não basta: em labels com markup, o GTK
        mescla os atributos manuais com os do markup, e os destaques
        continuavam na tela (e se acumulavam a cada tecla digitada na
        busca) até a bolha ser recriada. É preciso obrigar o label a
        refazer o markup do zero.

        NÃO REMOVA o ``set_markup("")``: o GTK ignora ``set_markup`` quando
        o texto é idêntico ao atual, então reaplicar o mesmo markup direto
        não refaz nada — foi exatamente o que falhou na primeira correção.
        Esvaziar antes garante que o texto "mudou" e o markup é reprocessado.
        """
        if not getattr(self, "_has_search_highlights", False):
            return
        self._has_search_highlights = False
        self._label.set_attributes(None)
        if self._is_assistant:
            self._label.set_markup("")
            self._set_markup(self._text)
        else:
            self._label.set_text("")
            self._label.set_text(self._text)

    def search_match_point(self, start: int) -> Optional[tuple]:
        """Devolve ``(widget, y)``: a posição vertical da ocorrência que
        começa no caractere ``start``, em coordenadas do label — usada pela
        janela para rolar até a linha exata, não só até o topo da bolha."""
        text = self._label.get_text()
        index = len(text[:start].encode("utf-8"))
        try:
            rect = self._label.get_layout().index_to_pos(index)
            _x, offset_y = self._label.get_layout_offsets()
            return self._label, offset_y + rect.y / Pango.SCALE
        except Exception:  # pylint: disable=broad-except
            return self._label, 0.0

    # ------------------------------------------------------------------ #
    # Internos                                                             #
    # ------------------------------------------------------------------ #

    def _set_markup(self, text: str) -> None:
        """Converte Markdown → Pango markup e aplica no label com fallback.

        ``Gtk.Label.set_markup()`` NÃO levanta exceção em Python quando o
        markup é inválido — ele só registra um aviso (g_critical) e mantém
        o conteúdo anterior do label, fazendo a UI "travar" silenciosamente
        no meio do streaming mesmo com o texto completo acumulado em
        ``self._text``. Por isso validamos o markup nós mesmos com
        ``Pango.parse_markup`` (que sim levanta ``GLib.Error``) antes de
        aplicar, e caímos para texto puro escapado em caso de falha — assim
        o texto sempre continua aparecendo por inteiro, mesmo que sem
        formatação em algum chunk intermediário.
        """
        if not text:
            self._label.set_markup("")
            return
        markup = md_to_pango(text)
        if self._is_valid_markup(markup):
            self._label.set_markup(markup)
        else:
            self._label.set_markup(escape_plain(text))

    _RE_A_TAG = re.compile(r"</?a\b[^>]*>")

    @staticmethod
    def _is_valid_markup(markup: str) -> bool:
        """Valida o markup, ignorando as tags de link.

        NÃO REMOVA o ``sub()`` abaixo. A tag ``<a href>`` é uma extensão do
        GTK, implementada no ``gtk_label_set_markup`` — o parser do Pango
        não a conhece e ``Pango.parse_markup`` responde "Unknown tag 'a'".
        Validar o markup completo reprova toda mensagem que contenha um
        link (planilha gerada, imagem gerada, URL citada pelo modelo), a
        bolha cai no ``escape_plain`` e o link aparece como texto cru.

        A contrapartida é que um href malformado não seria detectado aqui.
        Isso é coberto na origem: ``md_to_pango`` extrai os links para
        placeholder antes das regras de inline e escapa a URL ao montar o
        anchor, então o href não tem como chegar corrompido.
        """
        stripped = MessageRow._RE_A_TAG.sub("", markup)
        try:
            Pango.parse_markup(stripped, -1, "\0")
            return True
        except GLib.Error:
            return False

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

    def set_usage(self, total_tokens: Optional[int] = None, cost: Optional[float] = None) -> None:
        """Mostra tokens/custo em letra pequena no rodapé da bolha."""
        if not self._is_assistant or self._meta_label is None:
            return
        parts: List[str] = []
        if total_tokens is not None:
            parts.append(f"{total_tokens} tokens")
        if cost is not None:
            parts.append(self._format_cost(cost))
        if not parts:
            return
        self._meta_label.set_text(" · ".join(parts))
        self._meta_label.set_visible(True)

    @staticmethod
    def _format_cost(cost: float) -> str:
        if cost <= 0:
            return "$0"
        # mantém casas suficientes pra não virar "$0"
        text = f"{cost:.6f}".rstrip("0").rstrip(".")
        return f"${text}"
