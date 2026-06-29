"""
Preferências do POR.ai.

Usa ``Adw.PreferencesWindow`` (estável em todas as versões 1.x da libadwaita).
As alterações são gravadas na configuração assim que o usuário fecha a janela.
"""

from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from core.config import Config


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(
        self,
        parent: Gtk.Window,
        config: Config,
        on_saved: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self._on_saved = on_saved
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Preferências")
        self.set_search_enabled(True)

        self._build_api_page()
        self._build_behavior_page()

        # Grava ao fechar.
        self.connect("close-request", self._on_close)

    # ------------------------------------------------------------------ #
    # Página: OpenRouter                                                   #
    # ------------------------------------------------------------------ #

    def _build_api_page(self) -> None:
        page = Adw.PreferencesPage()
        page.set_title("OpenRouter")
        page.set_icon_name("network-transmit-receive-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Conexão")
        group.set_description(
            "Sua chave fica salva localmente em ~/.config/por-ai/config.json "
            "(permissão 0600). O conteúdo das conversas é enviado ao provedor do "
            "modelo escolhido através do OpenRouter."
        )

        self._api_key_row = Adw.PasswordEntryRow()
        self._api_key_row.set_title("Chave da API")
        self._api_key_row.set_text(self.config.api_key)
        group.add(self._api_key_row)

        self._site_name_row = Adw.EntryRow()
        self._site_name_row.set_title("Nome do app (X-Title)")
        self._site_name_row.set_text(self.config.site_name)
        group.add(self._site_name_row)

        #self._site_url_row = Adw.EntryRow()
        #self._site_url_row.set_title("URL do site (HTTP-Referer)")
        #self._site_url_row.set_text(self.config.site_url)
        #group.add(self._site_url_row)

        page.add(group)

        models_group = Adw.PreferencesGroup()
        models_group.set_title("Modelos favoritos")
        models_group.set_description(
            "Um ID por linha (ex.: anthropic/claude-3.5-sonnet). Esses aparecem "
            "no seletor da janela. Use o menu ▸ Atualizar modelos para puxar o "
            "catálogo completo do OpenRouter."
        )

        self._models_view = Gtk.TextView()
        self._models_view.set_monospace(True)
        self._models_view.set_top_margin(8)
        self._models_view.set_bottom_margin(8)
        self._models_view.set_left_margin(8)
        self._models_view.set_right_margin(8)
        self._models_view.get_buffer().set_text("\n".join(self.config.models))

        models_scroller = Gtk.ScrolledWindow()
        models_scroller.set_min_content_height(140)
        models_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        models_scroller.set_child(self._models_view)
        models_scroller.add_css_class("card")

        models_group.add(models_scroller)
        page.add(models_group)

        self.add(page)

    # ------------------------------------------------------------------ #
    # Página: Comportamento                                                #
    # ------------------------------------------------------------------ #

    def _build_behavior_page(self) -> None:
        page = Adw.PreferencesPage()
        page.set_title("Comportamento")
        page.set_icon_name("preferences-system-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Geração")

        self._stream_row = Adw.SwitchRow()
        self._stream_row.set_title("Streaming")
        self._stream_row.set_subtitle("Mostrar a resposta sendo escrita em tempo real")
        self._stream_row.set_active(self.config.stream)
        group.add(self._stream_row)

        self._tray_row = Adw.SwitchRow()
        self._tray_row.set_title("Ícone na bandeja do sistema")
        self._tray_row.set_subtitle(
            "Mantém o app acessível pela área de notificação. "
            "No GNOME, requer a extensão “AppIndicator and KStatusNotifierItem "
            "Support”."
        )
        self._tray_row.set_active(self.config.show_tray_icon)
        group.add(self._tray_row)

        # Temperatura via slider. Evita o Adw.SpinRow, cujos botões -/+ dependem
        # dos ícones simbólicos value-decrease/increase-symbolic, que podem estar
        # quebrados em alguns pacotes de ícones (ex.: Tela-circle).
        temp_row = Adw.ActionRow()
        temp_row.set_title("Temperatura")
        temp_row.set_subtitle("0 = determinístico, 2 = muito criativo")

        adjustment = Gtk.Adjustment(
            value=self.config.temperature,
            lower=0.0,
            upper=2.0,
            step_increment=0.1,
            page_increment=0.5,
        )
        self._temperature_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=adjustment,
        )
        self._temperature_scale.set_digits(1)
        self._temperature_scale.set_draw_value(True)
        self._temperature_scale.set_value_pos(Gtk.PositionType.LEFT)
        self._temperature_scale.set_size_request(220, -1)
        self._temperature_scale.set_valign(Gtk.Align.CENTER)
        temp_row.add_suffix(self._temperature_scale)
        group.add(temp_row)

        page.add(group)

        prompt_group = Adw.PreferencesGroup()
        prompt_group.set_title("Prompt de sistema")
        prompt_group.set_description(
            "Instrução enviada no início de toda conversa."
        )

        self._prompt_view = Gtk.TextView()
        self._prompt_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._prompt_view.set_top_margin(8)
        self._prompt_view.set_bottom_margin(8)
        self._prompt_view.set_left_margin(8)
        self._prompt_view.set_right_margin(8)
        self._prompt_view.get_buffer().set_text(self.config.system_prompt)

        prompt_scroller = Gtk.ScrolledWindow()
        prompt_scroller.set_min_content_height(160)
        prompt_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        prompt_scroller.set_child(self._prompt_view)
        prompt_scroller.add_css_class("card")

        prompt_group.add(prompt_scroller)
        page.add(prompt_group)

        self.add(page)

    # ------------------------------------------------------------------ #
    # Persistência                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _buffer_text(view: Gtk.TextView) -> str:
        buffer = view.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, False)

    def _on_close(self, *_args) -> bool:
        self.config.api_key = self._api_key_row.get_text()
        self.config.set("site_name", self._site_name_row.get_text().strip())
        #self.config.set("site_url", self._site_url_row.get_text().strip())
        self.config.set("stream", self._stream_row.get_active())
        self.config.set("temperature", round(self._temperature_scale.get_value(), 2))
        self.config.set("system_prompt", self._buffer_text(self._prompt_view))
        self.config.set("show_tray_icon", self._tray_row.get_active())

        models_text = self._buffer_text(self._models_view)
        models = [line.strip() for line in models_text.splitlines() if line.strip()]
        if models:
            self.config.models = models
            if self.config.default_model not in models:
                self.config.default_model = models[0]

        self.config.save()
        if self._on_saved is not None:
            self._on_saved()
        return False  # permite o fechamento
