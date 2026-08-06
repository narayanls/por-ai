"""
Diálogo de atualização do POR.ai.

Mostra a versão nova e as notas do release. Ao clicar em "Atualizar", o
diálogo PERMANECE aberto e vai informando o progresso: download, instalação
e, por fim, sucesso ou erro — trocando os botões conforme o estado.

Implementado como Adw.Dialog (e não Adw.AlertDialog) justamente porque o
AlertDialog se fecha sozinho ao ativar uma resposta, o que impediria mostrar
o andamento e o resultado da instalação.
"""

from __future__ import annotations

from typing import Any, Dict

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from core.updater import UpdateChecker


class UpdateDialog(Adw.Dialog):
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
        self._local_version = local_version
        self._busy = False

        remote_tag = release.get("tag_name", "?")
        self.set_title("Atualização disponível")
        self.set_content_width(440)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(18)
        box.set_margin_end(18)

        heading = Gtk.Label()
        heading.set_markup(f"<b>POR.ai {remote_tag} disponível</b>")
        heading.set_xalign(0.0)
        heading.set_wrap(True)
        box.append(heading)

        self._body = Gtk.Label(label=f"Versão instalada: {local_version}")
        self._body.set_xalign(0.0)
        self._body.set_wrap(True)
        box.append(self._body)

        # Notas do release (campo body do GitHub).
        notes = (release.get("body") or "").strip()
        if notes:
            notes_label = Gtk.Label(label=notes)
            notes_label.set_wrap(True)
            notes_label.set_xalign(0.0)
            notes_label.set_max_width_chars(52)

            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_min_content_height(80)
            scroller.set_max_content_height(200)
            scroller.add_css_class("card")
            scroller.set_child(notes_label)
            box.append(scroller)

        # Área de status (spinner + texto), escondida até começar a baixar.
        self._status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        self._spinner = Gtk.Spinner()
        self._status_label = Gtk.Label()
        self._status_label.set_xalign(0.0)
        self._status_label.set_wrap(True)
        self._status_box.append(self._spinner)
        self._status_box.append(self._status_label)
        self._status_box.set_visible(False)
        box.append(self._status_box)

        # Botões.
        button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(4)

        self._later_btn = Gtk.Button(label="Agora não")
        self._later_btn.connect("clicked", lambda *_: self.close())

        self._update_btn = Gtk.Button(label="Atualizar")
        self._update_btn.add_css_class("suggested-action")
        self._update_btn.connect("clicked", self._on_update_clicked)

        button_box.append(self._later_btn)
        button_box.append(self._update_btn)
        box.append(button_box)

        toolbar.set_content(box)
        self.set_child(toolbar)
        self.present(parent)

    # ------------------------------------------------------------------ #

    def _on_update_clicked(self, _btn: Gtk.Button) -> None:
        if self._busy:
            return
        self._busy = True

        self._update_btn.set_sensitive(False)
        self._later_btn.set_sensitive(False)
        # Bloqueia o fechamento enquanto baixa/instala.
        self.set_can_close(False)

        self._status_box.set_visible(True)
        self._spinner.start()
        self._set_status("Baixando atualização…")

        self._checker.download_and_open(
            self._release,
            on_progress=self._on_progress,
            on_status=self._on_status,
            on_done=self._on_done,
            on_error=self._on_error,
        )

    def _set_status(self, text: str) -> bool:
        self._status_label.set_text(text)
        return False

    # Callbacks vindos da thread de trabalho — sempre via GLib.idle_add.

    def _on_progress(self, downloaded: int, total: int) -> bool:
        if total > 0:
            pct = int(downloaded * 100 / total)
            GLib.idle_add(self._set_status, f"Baixando… {pct}%")
        return False

    def _on_status(self, message: str) -> bool:
        GLib.idle_add(self._set_status, message)
        return False

    def _on_done(self, _path: str) -> bool:
        GLib.idle_add(self._finish_success)
        return False

    def _on_error(self, message: str) -> bool:
        GLib.idle_add(self._finish_error, message)
        return False

    # Transições de estado finais (rodam na thread principal).

    def _finish_success(self) -> bool:
        self._spinner.stop()
        self._status_box.set_visible(False)
        self._body.set_text(
            "POR.ai atualizado com sucesso! "
            "Reinicie o aplicativo para usar a nova versão."
        )
        self._update_btn.set_visible(False)
        self._later_btn.set_label("Fechar")
        self._later_btn.set_sensitive(True)
        self.set_can_close(True)
        return False

    def _finish_error(self, message: str) -> bool:
        self._spinner.stop()
        self._status_box.set_visible(False)
        self._body.set_text(f"Erro ao atualizar: {message}")
        self._update_btn.set_label("Tentar de novo")
        self._update_btn.set_sensitive(True)
        self._later_btn.set_label("Fechar")
        self._later_btn.set_sensitive(True)
        self.set_can_close(True)
        self._busy = False
        return False
