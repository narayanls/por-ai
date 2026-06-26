"""
Janela principal do POR.ai.

Monta a interface de chat: cabeçalho com seletor de modelo e menu, área de
mensagens rolável, campo de entrada multilinha (Enter envia, Shift+Enter quebra
linha), botão de anexar arquivo e botão enviar/parar.

A privacidade aqui significa: o app é seu, roda localmente e não loga suas
conversas em servidores de terceiros além do próprio OpenRouter (que encaminha
ao provedor do modelo). O conteúdo de arquivos anexados é incluído na mensagem
enviada ao modelo — fica claro na interface quando isso acontece.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from core.assistant import ChatAssistant
from core.config import Config
from core.storage import ConversationStore
from ui.message_row import MessageRow
from ui.preferences import PreferencesWindow

_CSS = b"""
.message-bubble {
    padding: 10px 12px;
    border-radius: 14px;
}
.message-user {
    background-color: @accent_bg_color;
    color: @accent_fg_color;
}
.message-assistant {
    background-color: @card_bg_color;
}
.attachment-chip {
    padding: 4px 8px;
    border-radius: 999px;
}
.input-area {
    padding: 8px 12px 12px 12px;
}
"""


class PorAiWindow(Adw.ApplicationWindow):
    MAX_ATTACHMENTS = 4

    def __init__(self, application: Adw.Application, config: Config) -> None:
        super().__init__(application=application)
        self.config = config
        self.assistant = ChatAssistant(config)
        self.store = ConversationStore()

        # Conversa atual: lista de mensagens com role/content/display.
        # 'content' é o que vai à API (inclui texto de anexos); 'display' é o
        # que aparece na bolha. Para o assistente, ambos são iguais.
        self._messages: List[Dict[str, str]] = []
        self._current_conv_id: Optional[str] = None
        self._created_at: Optional[float] = None
        # Arquivos aguardando envio na próxima mensagem (até MAX_ATTACHMENTS).
        self._pending_attachments: List[str] = []
        # Bolha do assistente em construção durante o streaming.
        self._streaming_row: Optional[MessageRow] = None

        self.set_title("POR.ai")
        self.set_default_size(720, 720)

        self._install_css()
        self._install_actions()
        self._build_ui()

        if not self.config.is_configured():
            GLib.idle_add(self._prompt_for_api_key)

    # ------------------------------------------------------------------ #
    # Estilo e ações                                                       #
    # ------------------------------------------------------------------ #

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        css_text = _CSS.decode("utf-8")
        # A assinatura de load_from_* mudou entre versões do GTK4; tentamos as
        # variantes mais novas primeiro e caímos para a antiga se necessário.
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(css_text)  # GTK 4.12+
        else:
            try:
                provider.load_from_data(css_text, -1)
            except TypeError:
                provider.load_from_data(_CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _install_actions(self) -> None:
        actions = {
            "new-chat": self._on_new_chat,
            "refresh-models": self._on_refresh_models,
            "preferences": self._on_preferences,
            "about": self._on_about,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    # ------------------------------------------------------------------ #
    # Construção da interface                                              #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # Conteúdo (chat) à direita.
        content_view = Adw.ToolbarView()
        content_view.add_top_bar(self._build_header())
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.append(self._build_chat_area())
        content_box.append(self._build_input_area())
        content_view.set_content(content_box)

        # Barra lateral (histórico) à esquerda.
        sidebar = self._build_sidebar()

        # Split view: sidebar + conteúdo, recolhível em telas estreitas.
        self._split_view = Adw.OverlaySplitView()
        self._split_view.set_sidebar(sidebar)
        self._split_view.set_content(content_view)
        self._split_view.set_min_sidebar_width(220)
        self._split_view.set_max_sidebar_width(320)
        self._split_view.set_show_sidebar(True)

        # Liga o botão de alternância da barra de título ao estado da sidebar.
        self._split_view.bind_property(
            "show-sidebar",
            self._sidebar_toggle,
            "active",
            GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.BIDIRECTIONAL,
        )

        # Em janelas estreitas a sidebar vira sobreposição.
        breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 640px")
        )
        breakpoint.add_setter(self._split_view, "collapsed", True)
        self.add_breakpoint(breakpoint)

        # Toasts cobrem tudo.
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._split_view)
        self.set_content(self._toast_overlay)

        self._reload_sidebar()

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()

        # Botão de mostrar/ocultar a barra lateral.
        self._sidebar_toggle = Gtk.ToggleButton()
        self._sidebar_toggle.set_icon_name("sidebar-show-symbolic")
        self._sidebar_toggle.set_tooltip_text("Mostrar/ocultar conversas")
        header.pack_start(self._sidebar_toggle)

        # Seletor de modelo: MenuButton + Popover próprio com SearchEntry e
        # ListBox. Controle total — sem estados internos do DropDown causando
        # seleções automáticas durante a digitação.
        self._model_list: List[str] = list(self.config.models)
        self._selected_model_id: Optional[str] = self.config.default_model

        self._model_button = Gtk.MenuButton()
        self._model_button.set_tooltip_text("Selecionar modelo")
        self._model_button.add_css_class("flat")
        self._model_button.set_label(self._short_model_label(self._selected_model_id))
        self._model_popover = self._build_model_popover()
        self._model_button.set_popover(self._model_popover)
        header.set_title_widget(self._model_button)

        # Botão "nova conversa".
        new_button = Gtk.Button()
        new_button.set_icon_name("document-new-symbolic")
        new_button.set_tooltip_text("Nova conversa")
        new_button.set_action_name("win.new-chat")
        header.pack_start(new_button)

        # Menu principal.
        menu = Gio.Menu()
        menu.append("Nova conversa", "win.new-chat")
        menu.append("Atualizar modelos do OpenRouter", "win.refresh-models")
        menu.append("Preferências", "win.preferences")
        menu.append("Sobre o POR.ai", "win.about")

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text("Menu")
        header.pack_end(menu_button)

        return header

    def _build_sidebar(self) -> Gtk.Widget:
        view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Adw.WindowTitle(title="Conversas", subtitle=""))
        #new_button = Gtk.Button()
        #new_button.set_icon_name("document-new-symbolic")
        #new_button.set_tooltip_text("Nova conversa")
        #new_button.set_action_name("win.new-chat")
        #header.pack_start(new_button)
        view.add_top_bar(header)

        self._conv_list = Gtk.ListBox()
        self._conv_list.add_css_class("navigation-sidebar")
        self._conv_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._conv_list.connect("row-activated", self._on_conv_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self._conv_list)
        view.set_content(scroller)
        return view

    def _build_chat_area(self) -> Gtk.Widget:
        self._messages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._messages_box.set_margin_top(8)
        self._messages_box.set_margin_bottom(8)
        self._messages_box.set_valign(Gtk.Align.START)

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_vexpand(True)
        self._scroller.set_child(self._messages_box)

        # Mensagem de boas-vindas.
        self._show_placeholder()
        return self._scroller

    def _build_input_area(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.add_css_class("input-area")

        # Barra de chips de anexo (FlowBox: quebra linha quando há vários).
        self._attachment_bar = Gtk.FlowBox()
        self._attachment_bar.set_selection_mode(Gtk.SelectionMode.NONE)
        self._attachment_bar.set_max_children_per_line(self.MAX_ATTACHMENTS)
        self._attachment_bar.set_column_spacing(6)
        self._attachment_bar.set_row_spacing(6)
        self._attachment_bar.set_visible(False)
        outer.append(self._attachment_bar)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_valign(Gtk.Align.END)

        attach_button = Gtk.Button()
        attach_button.set_icon_name("mail-attachment-symbolic")
        attach_button.set_tooltip_text("Anexar arquivos — até 4 (pdf, odt, txt, md, png, jpg, webp)")
        attach_button.add_css_class("flat")
        attach_button.set_valign(Gtk.Align.END)
        attach_button.connect("clicked", self._on_attach)
        row.append(attach_button)

        # Campo de entrada multilinha.
        self._input_view = Gtk.TextView()
        self._input_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._input_view.set_accepts_tab(False)
        self._input_view.set_top_margin(8)
        self._input_view.set_bottom_margin(8)
        self._input_view.set_left_margin(8)
        self._input_view.set_right_margin(8)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_input_key)
        self._input_view.add_controller(key_controller)

        input_scroller = Gtk.ScrolledWindow()
        input_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        input_scroller.set_min_content_height(44)
        input_scroller.set_max_content_height(160)
        input_scroller.set_propagate_natural_height(True)
        input_scroller.set_hexpand(True)
        input_scroller.set_child(self._input_view)
        input_scroller.add_css_class("card")
        row.append(input_scroller)

        self._send_button = Gtk.Button()
        self._send_button.set_icon_name("send-to-symbolic")
        self._send_button.set_tooltip_text("Enviar (Enter)")
        self._send_button.add_css_class("suggested-action")
        self._send_button.set_valign(Gtk.Align.END)
        self._send_button.connect("clicked", self._on_send_clicked)
        row.append(self._send_button)

        outer.append(row)
        return outer

    # ------------------------------------------------------------------ #
    # Placeholder / boas-vindas                                            #
    # ------------------------------------------------------------------ #

    def _show_placeholder(self) -> None:
        status = Adw.StatusPage()
        status.set_icon_name("user-available-symbolic")
        status.set_title("POR.ai")
        status.set_description(
            "Chat privado com modelos do OpenRouter.\n"
            "Digite uma mensagem ou anexe um arquivo para análise."
        )
        status.set_vexpand(True)
        self._placeholder = status
        self._messages_box.append(status)

    def _clear_placeholder(self) -> None:
        if getattr(self, "_placeholder", None) is not None:
            self._messages_box.remove(self._placeholder)
            self._placeholder = None

    # ------------------------------------------------------------------ #
    # Seletor de modelo (MenuButton + Popover próprio)                     #
    # ------------------------------------------------------------------ #

    def _build_model_popover(self) -> Gtk.Popover:
        popover = Gtk.Popover()
        popover.set_size_request(320, -1)
        popover.connect("show", self._on_model_popover_show)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        self._model_search = Gtk.SearchEntry()
        self._model_search.set_placeholder_text("Buscar modelo…")
        self._model_search.connect("search-changed", self._on_model_search_changed)
        # Esc fecha o popover.
        self._model_search.connect("stop-search", lambda *_: popover.popdown())
        box.append(self._model_search)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(260)
        scroller.set_max_content_height(400)
        scroller.set_margin_top(4)

        self._model_listbox = Gtk.ListBox()
        self._model_listbox.add_css_class("navigation-sidebar")
        self._model_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._model_listbox.connect("row-activated", self._on_model_row_activated)
        scroller.set_child(self._model_listbox)
        box.append(scroller)

        popover.set_child(box)
        self._populate_model_listbox(self._model_list)
        return popover

    def _populate_model_listbox(self, models: List[str]) -> None:
        """Limpa e repovoa a ListBox com os modelos dados."""
        child = self._model_listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._model_listbox.remove(child)
            child = nxt
        for model_id in models:
            row = Gtk.ListBoxRow()
            row.set_name(model_id)
            label = Gtk.Label(label=model_id)
            label.set_xalign(0.0)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            row.set_child(label)
            self._model_listbox.insert(row, -1)

    def _on_model_popover_show(self, _popover) -> None:
        """Limpa a busca e foca o SearchEntry ao abrir."""
        self._model_search.set_text("")
        self._populate_model_listbox(self._model_list)
        GLib.idle_add(self._model_search.grab_focus)

    def _on_model_search_changed(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().lower().strip()
        filtered = (
            self._model_list if not query
            else [m for m in self._model_list if query in m.lower()]
        )
        self._populate_model_listbox(filtered)

    def _on_model_row_activated(self, _listbox, row: Gtk.ListBoxRow) -> None:
        model_id = row.get_name()
        if model_id:
            self._selected_model_id = model_id
            self._model_button.set_label(self._short_model_label(model_id))
            self.config.default_model = model_id
            self.config.save()
        self._model_popover.popdown()

    @staticmethod
    def _short_model_label(model_id: Optional[str]) -> str:
        """Mostra só a parte após a '/' para não sobrecarregar o header."""
        if not model_id:
            return "Selecionar modelo"
        parts = model_id.split("/", 1)
        return parts[1] if len(parts) == 2 else model_id

    def _select_model(self, model_id: str) -> None:
        if not model_id:
            return
        self._selected_model_id = model_id
        self._model_button.set_label(self._short_model_label(model_id))
        # Garante que o modelo esteja na lista.
        if model_id not in self._model_list:
            self._model_list.insert(0, model_id)

    def _current_model(self) -> str:
        return self._selected_model_id or self.config.default_model

    def _on_model_changed(self, *_args) -> None:
        pass  # mantido para compatibilidade, não usado com o popover próprio

    # ------------------------------------------------------------------ #
    # Entrada de texto                                                     #
    # ------------------------------------------------------------------ #

    def _on_input_key(self, _controller, keyval, _keycode, state) -> bool:
        is_enter = keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if is_enter and not shift:
            self._on_send_clicked(self._send_button)
            return True  # consome o Enter (não insere quebra de linha)
        return False

    def _get_input_text(self) -> str:
        buffer = self._input_view.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, False).strip()

    def _clear_input(self) -> None:
        self._input_view.get_buffer().set_text("")

    # ------------------------------------------------------------------ #
    # Envio                                                                #
    # ------------------------------------------------------------------ #

    def _on_send_clicked(self, _button) -> None:
        # Se já está respondendo, o botão funciona como "parar".
        if self.assistant.is_busy():
            self.assistant.cancel()
            return

        text = self._get_input_text()
        if not text and not self._pending_attachments:
            return

        if not self.config.is_configured():
            self._toast("Configure a chave da API em Preferências.")
            self._prompt_for_api_key()
            return

        self._clear_placeholder()

        # Monta o conteúdo enviado à API (texto + arquivos, se houver).
        api_content: Any = text
        display_text = text
        if self._pending_attachments:
            text_blocks: List[str] = []
            image_parts: List[Dict[str, Any]] = []
            names: List[str] = []

            for path in self._pending_attachments:
                filename = os.path.basename(path)
                try:
                    if self.assistant.is_image(path):
                        image_parts.append(
                            self.assistant.read_image_attachment(path)
                        )
                    else:
                        file_text = self.assistant.read_text_attachment(path)
                        text_blocks.append(
                            f"--- INÍCIO DO ARQUIVO: {filename} ---\n"
                            f"{file_text}\n"
                            f"--- FIM DO ARQUIVO ---"
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    self._toast(f"{filename}: {exc}")
                    return
                names.append(filename)

            prefix = f"{text}\n\n" if text else ""
            chips = "\n".join(f"📎 {n}" for n in names)
            display_text = prefix + chips

            if image_parts:
                # Mensagem multimodal: lista com texto + imagens em base64.
                content_parts: List[Any] = []
                full_text = prefix + "\n\n".join(text_blocks) if text_blocks else (text or "")
                if full_text:
                    content_parts.append({"type": "text", "text": full_text})
                content_parts.extend(image_parts)
                api_content = content_parts
            else:
                api_content = prefix + "\n\n".join(text_blocks)

            self._clear_attachments()

        # Bolha do usuário.
        user_row = MessageRow("user", display_text)
        self._messages_box.append(user_row)
        self._messages.append(
            {"role": "user", "content": api_content, "display": display_text}
        )

        # Garante que a conversa exista em disco a partir da 1ª mensagem.
        self._persist()

        # Bolha do assistente (vazia, preenchida via streaming).
        self._streaming_row = MessageRow("assistant", "")
        self._messages_box.append(self._streaming_row)

        self._clear_input()
        self._set_busy(True)
        self._scroll_to_bottom()

        messages = [{"role": "system", "content": self.config.system_prompt}]
        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in self._messages
        )

        started = self.assistant.send(
            model=self._current_model(),
            messages=messages,
            on_delta=self._on_delta,
            on_done=self._on_done,
            on_error=self._on_error,
        )
        if not started:
            self._set_busy(False)
            self._toast("Já existe uma resposta em andamento.")

    def _on_delta(self, chunk: str) -> bool:
        if self._streaming_row is not None:
            self._streaming_row.append_text(chunk)
            self._scroll_to_bottom()
        return False  # GLib.idle_add: não repetir

    def _on_done(self, full_text: str) -> bool:
        if self._streaming_row is not None:
            if not full_text.strip():
                self._streaming_row.set_text("(resposta vazia ou cancelada)")
            self._messages.append(
                {"role": "assistant", "content": full_text, "display": full_text}
            )
            self._persist()
        self._streaming_row = None
        self._set_busy(False)
        self._scroll_to_bottom()
        return False

    def _on_error(self, message: str) -> bool:
        if self._streaming_row is not None and not self._streaming_row.get_text().strip():
            self._streaming_row.set_text(f"⚠️ {message}")
        else:
            self._toast(message)
        self._streaming_row = None
        self._set_busy(False)
        return False

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._send_button.set_icon_name("media-playback-stop-symbolic")
            self._send_button.set_tooltip_text("Parar")
            self._send_button.remove_css_class("suggested-action")
            self._send_button.add_css_class("destructive-action")
        else:
            self._send_button.set_icon_name("send-to-symbolic")
            self._send_button.set_tooltip_text("Enviar (Enter)")
            self._send_button.remove_css_class("destructive-action")
            self._send_button.add_css_class("suggested-action")

    def _scroll_to_bottom(self) -> None:
        def scroll() -> bool:
            adj = self._scroller.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False

        GLib.idle_add(scroll)

    # ------------------------------------------------------------------ #
    # Anexos                                                               #
    # ------------------------------------------------------------------ #

    def attach_file(self, path: str) -> None:
        """Anexa um arquivo externo (linha de comando / 'Abrir com…')."""
        status = self._add_attachment(path)
        if status == "ok":
            self._refresh_attachment_bar()
        elif status == "full":
            self._toast(f"Máximo de {self.MAX_ATTACHMENTS} arquivos por mensagem.")
        elif status == "unsupported":
            self._toast_unsupported(path)

    def _add_attachment(self, path: str) -> str:
        """
        Tenta registrar um anexo (sem atualizar a UI).
        Retorna: 'ok', 'dup', 'full' ou 'unsupported'.
        """
        if not path:
            return "unsupported"
        if path in self._pending_attachments:
            return "dup"
        if len(self._pending_attachments) >= self.MAX_ATTACHMENTS:
            return "full"
        if not self.assistant.supported_attachment(path):
            return "unsupported"
        self._pending_attachments.append(path)
        return "ok"

    def _toast_unsupported(self, path: str) -> None:
        self._toast(self.assistant.unsupported_reason(path))

    def _on_attach(self, _button) -> None:
        # Não abre o seletor se já atingiu o limite.
        if len(self._pending_attachments) >= self.MAX_ATTACHMENTS:
            self._toast(f"Máximo de {self.MAX_ATTACHMENTS} arquivos por mensagem.")
            return

        dialog = Gtk.FileDialog()
        dialog.set_title("Anexar arquivos")

        filters = Gio.ListStore.new(Gtk.FileFilter)

        doc_filter = Gtk.FileFilter()
        doc_filter.set_name("Documentos e imagens")
        for pattern in (
            "*.txt", "*.md", "*.markdown", "*.rst", "*.org",
            "*.tex", "*.csv", "*.log",
            "*.pdf", "*.odt", "*.docx",
            "*.png", "*.jpg", "*.jpeg", "*.webp",
        ):
            doc_filter.add_pattern(pattern)
        filters.append(doc_filter)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("Todos os arquivos")
        all_filter.add_pattern("*")
        filters.append(all_filter)

        dialog.set_filters(filters)
        dialog.set_default_filter(doc_filter)
        dialog.open_multiple(self, None, self._on_attach_chosen)

    def _on_attach_chosen(self, dialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # usuário cancelou
        if not files:
            return

        added = 0
        reached_limit = False
        unsupported = 0
        for gfile in files:
            path = gfile.get_path()
            status = self._add_attachment(path) if path else "unsupported"
            if status == "ok":
                added += 1
            elif status == "full":
                reached_limit = True
                break
            elif status == "unsupported":
                unsupported += 1

        if added:
            self._refresh_attachment_bar()
        if reached_limit:
            self._toast(f"Limite de {self.MAX_ATTACHMENTS} arquivos atingido.")
        elif unsupported and not added:
            self._toast("Nenhum arquivo suportado foi anexado.")

    def _remove_attachment(self, path: str) -> None:
        if path in self._pending_attachments:
            self._pending_attachments.remove(path)
            self._refresh_attachment_bar()

    def _clear_attachments(self) -> None:
        self._pending_attachments.clear()
        self._refresh_attachment_bar()

    def _refresh_attachment_bar(self) -> None:
        # Remove os chips atuais.
        child = self._attachment_bar.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._attachment_bar.remove(child)
            child = nxt

        if not self._pending_attachments:
            self._attachment_bar.set_visible(False)
            return

        for path in self._pending_attachments:
            self._attachment_bar.insert(self._make_chip(path), -1)
        self._attachment_bar.set_visible(True)

    def _make_chip(self, path: str) -> Gtk.Widget:
        chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        chip.add_css_class("attachment-chip")
        chip.add_css_class("card")

        icon_name = (
            "image-x-generic-symbolic"
            if self.assistant.is_image(path)
            else "mail-attachment-symbolic"
        )
        icon = Gtk.Image.new_from_icon_name(icon_name)
        chip.append(icon)

        label = Gtk.Label(label=os.path.basename(path))
        label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        label.set_max_width_chars(24)
        label.set_tooltip_text(path)
        chip.append(label)

        remove = Gtk.Button()
        remove.set_icon_name("window-close-symbolic")
        remove.add_css_class("flat")
        remove.add_css_class("circular")
        remove.set_tooltip_text("Remover anexo")
        remove.connect("clicked", lambda *_: self._remove_attachment(path))
        chip.append(remove)
        return chip

    # ------------------------------------------------------------------ #
    # Ações do menu                                                        #
    # ------------------------------------------------------------------ #

    def _reset_chat_view(self) -> None:
        """Limpa a área de chat e o estado da conversa atual (sem apagar disco)."""
        if self.assistant.is_busy():
            self.assistant.cancel()
        self._streaming_row = None
        self._messages = []
        self._current_conv_id = None
        self._created_at = None
        self._clear_attachments()

        child = self._messages_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._messages_box.remove(child)
            child = nxt

        self._placeholder = None
        self._show_placeholder()
        self._set_busy(False)

    def _on_new_chat(self, *_args) -> None:
        # A conversa anterior já está salva (persistimos a cada turno), então
        # aqui só abrimos uma conversa nova e limpa.
        self._reset_chat_view()
        if getattr(self, "_conv_list", None) is not None:
            self._conv_list.unselect_all()

    # ------------------------------------------------------------------ #
    # Histórico / persistência                                            #
    # ------------------------------------------------------------------ #

    def _derive_title(self) -> str:
        for message in self._messages:
            if message.get("role") == "user":
                text = (message.get("display") or "").strip()
                first_line = text.splitlines()[0] if text else ""
                first_line = first_line.strip()
                if first_line:
                    return first_line[:50]
        return "Nova conversa"

    def _persist(self) -> None:
        if not self._messages:
            return
        if self._current_conv_id is None:
            self._current_conv_id = self.store.new_id()
            self._created_at = time.time()
        conversation = {
            "id": self._current_conv_id,
            "title": self._derive_title(),
            "created_at": self._created_at or time.time(),
            "updated_at": time.time(),
            "model": self._current_model(),
            "messages": self._messages,
        }
        self.store.save(conversation)
        self._reload_sidebar(select_current=True)

    def _reload_sidebar(self, select_current: bool = False) -> None:
        if getattr(self, "_conv_list", None) is None:
            return

        # Remove linhas atuais.
        child = self._conv_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._conv_list.remove(child)
            child = nxt

        selected_row = None
        for meta in self.store.list_meta():
            row = self._make_conv_row(meta)
            self._conv_list.insert(row, -1)
            if select_current and meta["id"] == self._current_conv_id:
                selected_row = row

        if selected_row is not None:
            self._conv_list.select_row(selected_row)

    def _make_conv_row(self, meta: Dict[str, Any]) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_name(meta["id"])  # guarda o id no nome do widget

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(4)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text_box.set_hexpand(True)

        title = Gtk.Label(label=meta["title"])
        title.set_xalign(0.0)
        title.set_ellipsize(3)  # END
        title.set_max_width_chars(24)
        text_box.append(title)

        subtitle = Gtk.Label(label=self._relative_time(meta["updated_at"]))
        subtitle.set_xalign(0.0)
        subtitle.add_css_class("caption")
        subtitle.add_css_class("dim-label")
        text_box.append(subtitle)

        box.append(text_box)

        # Botão renomear.
        rename = Gtk.Button()
        rename.set_icon_name("document-edit-symbolic")
        rename.add_css_class("flat")
        rename.set_valign(Gtk.Align.CENTER)
        rename.set_tooltip_text("Renomear conversa")
        rename.connect(
            "clicked",
            lambda *_: self._on_rename_conv(meta["id"], meta["title"]),
        )
        box.append(rename)

        delete = Gtk.Button()
        delete.set_icon_name("user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_valign(Gtk.Align.CENTER)
        delete.set_tooltip_text("Excluir conversa")
        delete.connect("clicked", lambda *_: self._on_delete_conv(meta["id"]))
        box.append(delete)

        # Duplo clique na linha também abre o renomear.
        gesture = Gtk.GestureClick()
        gesture.set_button(1)  # botão esquerdo
        gesture.connect(
            "pressed",
            lambda g, n, x, y: self._on_rename_conv(meta["id"], meta["title"])
            if n == 2
            else None,
        )
        row.add_controller(gesture)

        row.set_child(box)
        return row

    @staticmethod
    def _relative_time(epoch: float) -> str:
        if not epoch:
            return ""
        delta = max(0, int(time.time() - epoch))
        if delta < 60:
            return "agora"
        if delta < 3600:
            return f"há {delta // 60} min"
        if delta < 86400:
            return f"há {delta // 3600} h"
        if delta < 172800:
            return "ontem"
        if delta < 604800:
            return f"há {delta // 86400} dias"
        return time.strftime("%d/%m/%Y", time.localtime(epoch))

    def _on_conv_activated(self, _listbox, row: Gtk.ListBoxRow) -> None:
        conv_id = row.get_name()
        if conv_id and conv_id != self._current_conv_id:
            self._load_conversation(conv_id)
        # Em modo recolhido, esconde a sidebar após escolher.
        if self._split_view.get_collapsed():
            self._split_view.set_show_sidebar(False)

    def _load_conversation(self, conv_id: str) -> None:
        data = self.store.load(conv_id)
        if data is None:
            self._toast("Não foi possível abrir a conversa.")
            self._reload_sidebar()
            return

        if self.assistant.is_busy():
            self.assistant.cancel()
        self._streaming_row = None
        self._clear_attachments()

        self._current_conv_id = conv_id
        self._created_at = float(data.get("created_at", 0) or time.time())
        self._messages = [
            {
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
                "display": m.get("display", m.get("content", "")),
            }
            for m in data.get("messages", [])
            if isinstance(m, dict)
        ]

        model = data.get("model")
        if model:
            self._select_model(model)

        # Recria as bolhas.
        child = self._messages_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._messages_box.remove(child)
            child = nxt
        self._placeholder = None

        if not self._messages:
            self._show_placeholder()
        else:
            for message in self._messages:
                row = MessageRow(message["role"], message["display"])
                self._messages_box.append(row)

        self._set_busy(False)
        self._scroll_to_bottom()

    def _on_delete_conv(self, conv_id: str) -> None:
        self.store.delete(conv_id)
        if conv_id == self._current_conv_id:
            self._reset_chat_view()
        self._reload_sidebar(select_current=True)

    def _on_rename_conv(self, conv_id: str, current_title: str) -> None:
        """Abre um diálogo para renomear a conversa."""
        dialog = Adw.AlertDialog()
        dialog.set_heading("Renomear conversa")
        dialog.set_body("Digite o novo nome:")
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("rename", "Renomear")
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance(
            "rename", Adw.ResponseAppearance.SUGGESTED
        )

        entry = Gtk.Entry()
        entry.set_text(current_title)
        entry.set_activates_default(True)
        entry.set_margin_top(8)
        dialog.set_extra_child(entry)

        # Seleciona todo o texto para facilitar a edição.
        entry.select_region(0, -1)

        def on_response(d, response):
            if response != "rename":
                return
            new_title = entry.get_text().strip()
            if not new_title or new_title == current_title:
                return
            data = self.store.load(conv_id)
            if data is None:
                return
            data["title"] = new_title
            self.store.save(data)
            self._reload_sidebar(select_current=True)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_refresh_models(self, *_args) -> None:
        if not self.config.is_configured():
            self._toast("Configure a chave da API para buscar modelos.")
            return
        self._toast("Buscando catálogo de modelos…")
        self.assistant.fetch_models(
            on_done=self._on_models_fetched,
            on_error=lambda msg: self._toast(msg) or False,
        )

    def _on_models_fetched(self, model_ids: List[str]) -> bool:
        if not model_ids:
            self._toast("Nenhum modelo retornado.")
            return False
        current = self._current_model()
        self.config.models = model_ids
        self.config.save()
        self._model_list = list(model_ids)
        self._select_model(current if current in model_ids else model_ids[0])
        self._toast(f"{len(model_ids)} modelos disponíveis.")
        return False

    def _on_preferences(self, *_args) -> None:
        prefs = PreferencesWindow(self, self.config, on_saved=self._on_prefs_saved)
        prefs.present()

    def _on_prefs_saved(self) -> None:
        current = self._current_model()
        models = self.config.models
        self._model_list = list(models)
        self._select_model(current if current in models else self.config.default_model)

    def _on_about(self, *_args) -> None:
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="POR.ai",
            application_icon="por-ai",
            version="0.1.6",
            developer_name="Você",
            comments=(
                "Private OpenRouter AI — um chat com modelos do OpenRouter, "
                "rodando localmente para manter o controle dos seus arquivos."
            ),
            license_type=Gtk.License.GPL_3_0,
            website="https://openrouter.ai",
        )
        about.present()

    # ------------------------------------------------------------------ #
    # Diversos                                                             #
    # ------------------------------------------------------------------ #

    def _prompt_for_api_key(self) -> bool:
        self._toast("Bem-vinda! Defina sua chave da API em Preferências.")
        return False

    def _toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))
