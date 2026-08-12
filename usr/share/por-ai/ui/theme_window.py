"""
Janela "Temas" do POR.ai.

Lista o tema do sistema e os esquemas pré-definidos (Everforest, Gruvbox,
Tokyo Night, Catppuccin, Dracula, Nord). A troca é aplicada imediatamente ao
clicar numa linha — não precisa fechar a janela para ver o resultado — e
persistida na config.
"""

from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

from core.config import Config
from ui import color_schemes


class ThemeWindow(Adw.PreferencesWindow):
    def __init__(
        self,
        parent: Gtk.Window,
        config: Config,
        current_scheme_id: str,
        on_selected: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.config = config
        self._on_selected = on_selected
        self._current = current_scheme_id or color_schemes.SYSTEM_SCHEME_ID

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Temas")
        self.set_search_enabled(False)
        self.set_default_size(420, 520)

        color_schemes.ensure_swatch_css_installed(Gdk.Display.get_default())

        self._build_page()

    def _build_page(self) -> None:
        page = Adw.PreferencesPage()
        page.set_title("Temas")
        page.set_icon_name("applications-graphics-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Esquema de cores")
        group.set_description(
            "Escolha uma paleta para a interface. A mudança é aplicada na hora."
        )

        radio_group: Optional[Gtk.CheckButton] = None
        for scheme_id in color_schemes.scheme_ids_in_order():
            row = Adw.ActionRow()
            row.set_title(color_schemes.scheme_label(scheme_id))
            row.set_activatable(True)

            swatches = color_schemes.scheme_swatches(scheme_id)
            if swatches:
                swatch_box = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=4
                )
                swatch_box.set_valign(Gtk.Align.CENTER)
                for index in range(len(swatches)):
                    chip = Gtk.Box()
                    chip.set_size_request(16, 16)
                    chip.add_css_class("card")
                    chip.add_css_class(f"porai-swatch-{scheme_id}-{index}")
                    chip.set_overflow(Gtk.Overflow.HIDDEN)
                    swatch_box.append(chip)
                row.add_prefix(swatch_box)
            else:
                icon = Gtk.Image.new_from_icon_name("preferences-desktop-theme-symbolic")
                icon.set_valign(Gtk.Align.CENTER)
                row.add_prefix(icon)

            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            if radio_group is None:
                radio_group = check
            else:
                check.set_group(radio_group)
            check.set_active(scheme_id == self._current)
            row.add_suffix(check)
            row.set_activatable_widget(check)

            check.connect("toggled", self._on_toggled, scheme_id, check)

            group.add(row)

        page.add(group)
        self.add(page)

    def _on_toggled(self, check: Gtk.CheckButton, scheme_id: str, _check_ref) -> None:
        if not check.get_active():
            return
        self._current = scheme_id
        self._on_selected(scheme_id)
