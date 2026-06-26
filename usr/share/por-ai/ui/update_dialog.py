"""
Diálogo de atualização do POR.ai.

Exibe a versão nova, as notas do release e dois botões:
  • Atualizar — baixa o pacote e abre com o instalador do sistema
  • Agora não — fecha o diálogo
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from core.updater import UpdateChecker


class UpdateDialog(Adw.AlertDialog):
    def __init__(
        self,
        parent: Gtk.Window,
        release: Dict[str, Any],
        local_version: str,
        checker: UpdateChecker,
    ) -> None:
        super().__init__()

        self._release = release
        self._checker = checker
        self._downloading = False

        remote_tag = release.get("tag_name", "?")
        self.set_heading(f"POR.ai {remote_tag} disponível")
        self.set_body(f"Versão instalada: {local_version}")

        # Notas do release (campo body do GitHub).
        notes = (release.get("body") or "").strip()
        if notes:
            notes_label = Gtk.Label(label=notes)
            notes_label.set_wrap(True)
            notes_label.set_xalign(0.0)
            notes_label.set_margin_top(8)
            notes_label.set_max_width_chars(52)

            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_min_content_height(80)
            scroller.set_max_content_height(200)
            scroller.set_child(notes_label)
            self.set_extra_child(scroller)

        self.add_response("later", "Agora não")
        self.add_response("update", "Atualizar")
        self.set_default_response("update")
        self.set_close_response("later")
        self.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)

        self.connect("response", self._on_response)
        self.present(parent)

    # ------------------------------------------------------------------ #

    def _on_response(self, _dialog, response: str) -> None:
        if response != "update":
            return
        if self._downloading:
            return
        self._downloading = True

        # Troca o botão por um spinner enquanto baixa.
        self.set_response_enabled("update", False)
        self.set_response_enabled("later", False)
        self.set_body("Baixando atualização…")

        self._checker.download_and_open(
            self._release,
            on_progress=self._on_progress,
            on_done=self._on_done,
            on_error=self._on_error,
        )

    def _on_progress(self, downloaded: int, total: int) -> bool:
        if total > 0:
            pct = int(downloaded * 100 / total)
            GLib.idle_add(self.set_body, f"Baixando… {pct}%")
        return False

    def _on_done(self, _path: str) -> bool:
        GLib.idle_add(
            self.set_body,
            "Download concluído. O instalador do sistema foi aberto.",
        )
        GLib.idle_add(self.set_response_enabled, "later", True)
        return False

    def _on_error(self, message: str) -> bool:
        GLib.idle_add(self.set_body, f"Erro ao baixar: {message}")
        GLib.idle_add(self.set_response_enabled, "update", True)
        GLib.idle_add(self.set_response_enabled, "later", True)
        self._downloading = False
        return False
