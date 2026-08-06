"""
Ícone na bandeja do sistema (system tray) para o POR.ai.

Por que não usamos AppIndicator?
--------------------------------
O GTK4 removeu ``Gtk.StatusIcon`` e ``Gtk.Menu``. As bibliotecas
``AppIndicator3`` / ``AyatanaAppIndicator3`` são GTK*3* e exigem ``Gtk.Menu``;
carregá-las no mesmo processo de um app GTK4 causa conflito de ABI (libgtk-3 e
libgtk-4 juntas) e trava. Por isso implementamos diretamente o protocolo
**StatusNotifierItem (SNI)** + **com.canonical.dbusmenu** via D-Bus (Gio).

Isso é independente da versão do GTK e não adiciona nenhuma dependência nova:
``Gio`` já vem no PyGObject.

Onde aparece o ícone:
  - KDE Plasma: nativo.
  - Cinnamon: nativo (applet de systray).
  - GNOME Shell: precisa da extensão "AppIndicator and KStatusNotifierItem
    Support" (o Shell não mostra bandeja por conta própria desde a 3.26).
    Se não houver nenhum "watcher" SNI no barramento, o ícone simplesmente
    não é exibido — ``available`` retorna False e ``on_unavailable`` é chamado.

Uso típico:

    tray = TrayIcon(
        app_id="dev.narayanls.por-ai",
        icon_name="dev.narayanls.por-ai",   # ou um nome do tema de ícones
        title="POR.ai",
        on_activate=lambda: window.toggle_visible(),
        menu_items=[
            MenuItem("show", "Mostrar / Ocultar", lambda: window.toggle_visible()),
            MenuItem.separator(),
            MenuItem("quit", "Sair", lambda: app.quit()),
        ],
        on_unavailable=lambda: print("Nenhum systray disponível (no GNOME, "
                                     "instale a extensão AppIndicator)."),
    )
    tray.register()
    ...
    tray.unregister()   # ao desligar a opção ou fechar o app
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

# --------------------------------------------------------------------------- #
# Modelo de menu                                                              #
# --------------------------------------------------------------------------- #


@dataclass
class MenuItem:
    """Um item do menu de contexto da bandeja."""

    key: str
    label: str = ""
    callback: Optional[Callable[[], None]] = None
    enabled: bool = True
    is_separator: bool = False
    # id numérico atribuído internamente (preenchido pelo TrayIcon)
    _dbus_id: int = field(default=0, repr=False)

    @classmethod
    def separator(cls) -> "MenuItem":
        return cls(key="__sep__", is_separator=True, enabled=False)


# --------------------------------------------------------------------------- #
# Definições de interface D-Bus                                               #
# --------------------------------------------------------------------------- #

_SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>
"""

_MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
</node>
"""

_SNI_PATH = "/StatusNotifierItem"
_MENU_PATH = "/MenuBar"
_WATCHER_NAME = "org.kde.StatusNotifierWatcher"
_WATCHER_PATH = "/StatusNotifierWatcher"


# --------------------------------------------------------------------------- #
# TrayIcon                                                                     #
# --------------------------------------------------------------------------- #


class TrayIcon:
    def __init__(
        self,
        app_id: str,
        icon_name: str,
        title: str = "",
        on_activate: Optional[Callable[[], None]] = None,
        menu_items: Optional[List[MenuItem]] = None,
        on_unavailable: Optional[Callable[[], None]] = None,
        icon_theme_path: str = "",
        category: str = "ApplicationStatus",
        debug: bool = False,
    ) -> None:
        self.app_id = app_id
        self.icon_name = icon_name
        self.title = title or app_id
        self.category = category
        self.icon_theme_path = icon_theme_path
        self.on_activate = on_activate
        self.on_unavailable = on_unavailable
        self.debug = debug

        # Atribui ids numéricos sequenciais aos itens (o id 0 é a raiz).
        self.menu_items: List[MenuItem] = menu_items or []
        for i, item in enumerate(self.menu_items, start=1):
            item._dbus_id = i

        self._conn: Optional[Gio.DBusConnection] = None
        self._bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._owner_id = 0
        self._sni_reg_id = 0
        self._menu_reg_id = 0
        self._menu_revision = 1
        self._registered = False
        # Cache do ícone em pixels (a(iiay)). None = ainda não calculado;
        # False = tentou e não conseguiu (cai para IconName).
        self._icon_pixmap = None

        self._sni_info = Gio.DBusNodeInfo.new_for_xml(_SNI_XML).interfaces[0]
        self._menu_info = Gio.DBusNodeInfo.new_for_xml(_MENU_XML).interfaces[0]

    # ----------------------------- ciclo de vida --------------------------- #

    def _log(self, *parts) -> None:
        if self.debug:
            print("[tray]", *parts, flush=True)

    def register(self) -> None:
        """Publica o ícone na bandeja. Idempotente."""
        if self._registered:
            self._log("register() ignorado: já registrado")
            return
        self._log("register() iniciando; bus name =", self._bus_name)
        self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._log("conexão com a sessão D-Bus:", self._conn is not None,
                  "| unique name =",
                  self._conn.get_unique_name() if self._conn else None)

        self._sni_reg_id = self._conn.register_object(
            _SNI_PATH,
            self._sni_info,
            self._on_sni_method,
            self._on_sni_get_property,
            None,
        )
        self._menu_reg_id = self._conn.register_object(
            _MENU_PATH,
            self._menu_info,
            self._on_menu_method,
            self._on_menu_get_property,
            None,
        )
        self._log("register_object SNI id =", self._sni_reg_id,
                  "| menu id =", self._menu_reg_id)

        self._owner_id = Gio.bus_own_name_on_connection(
            self._conn,
            self._bus_name,
            Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired,
            self._on_name_lost,
        )
        self._log("bus_own_name owner_id =", self._owner_id)
        self._registered = True

    def unregister(self) -> None:
        """Remove o ícone da bandeja. Idempotente."""
        if not self._registered:
            return
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        if self._conn:
            if self._sni_reg_id:
                self._conn.unregister_object(self._sni_reg_id)
                self._sni_reg_id = 0
            if self._menu_reg_id:
                self._conn.unregister_object(self._menu_reg_id)
                self._menu_reg_id = 0
        self._registered = False

    def set_icon(self, icon_name: str) -> None:
        """Troca o ícone em tempo de execução (ex.: indicar 'pensando')."""
        self.icon_name = icon_name
        if self._conn and self._registered:
            self._conn.emit_signal(
                None, _SNI_PATH, "org.kde.StatusNotifierItem", "NewIcon", None
            )

    # ----------------------------- registro SNI ---------------------------- #

    def _on_name_acquired(self, _conn, name) -> None:
        self._log("name acquired:", name, "-> registrando no watcher")
        # Avisa o watcher (KDE/Cinnamon/extensão do GNOME) que existimos.
        self._conn.call(
            _WATCHER_NAME,
            _WATCHER_PATH,
            _WATCHER_NAME,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self._bus_name,)),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            self._on_register_done,
        )

    def _on_register_done(self, conn, result) -> None:
        try:
            conn.call_finish(result)
            self._log("RegisterStatusNotifierItem OK (watcher aceitou o item)")
        except GLib.Error as exc:
            # Erro ao falar com o watcher (ex.: GNOME puro sem a extensão, ou
            # algum problema no barramento). Antes era engolido em silêncio.
            self._log("RegisterStatusNotifierItem FALHOU:", exc.message)
            if self.on_unavailable is not None:
                self.on_unavailable()

    def _on_name_lost(self, _conn, name) -> None:
        self._log("name LOST:", name, "(não foi possível possuir o bus name)")

    # --------------------------- métodos do SNI ---------------------------- #

    def _on_sni_method(
        self, _conn, _sender, _path, _iface, method, _params, invocation
    ) -> None:
        if method in ("Activate", "SecondaryActivate"):
            if self.on_activate is not None:
                self.on_activate()
            invocation.return_value(None)
        elif method in ("ContextMenu", "Scroll"):
            # O menu é tratado pelo host via dbusmenu; nada a fazer aqui.
            invocation.return_value(None)
        else:
            invocation.return_value(None)

    def _ensure_pixmap(self):
        """Carrega o ícone como pixels (ARGB32) via tema do GTK. Cacheado.

        Retorna um GLib.Variant 'a(iiay)' ou None se não foi possível. Manda
        o ícone como bitmap evita depender de o host SNI resolver ``IconName``
        no tema do sistema — que é o motivo mais comum de "ícone invisível".
        """
        if self._icon_pixmap is not None:
            return self._icon_pixmap or None  # False vira None

        self._icon_pixmap = False  # marca como tentado
        try:
            gi.require_version("Gtk", "4.0")
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import Gdk, GdkPixbuf, Gtk

            display = Gdk.Display.get_default()
            self._log("pixmap: display disponível?", display is not None)
            if display is None:
                return None

            size = 24
            theme = Gtk.IconTheme.get_for_display(display)
            has_icon = theme.has_icon(self.icon_name)
            self._log("pixmap: tema tem o ícone", repr(self.icon_name), "?",
                      has_icon)
            paintable = theme.lookup_icon(
                self.icon_name, None, size, 1, Gtk.TextDirection.NONE, 0
            )
            gfile = paintable.get_file() if paintable is not None else None
            path = gfile.get_path() if gfile is not None else None
            self._log("pixmap: arquivo resolvido =", path)
            if not path:
                return None

            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
            if not pixbuf.get_has_alpha():
                pixbuf = pixbuf.add_alpha(False, 0, 0, 0)

            width = pixbuf.get_width()
            height = pixbuf.get_height()
            rowstride = pixbuf.get_rowstride()
            channels = pixbuf.get_n_channels()
            pixels = pixbuf.get_pixels()

            # SNI espera ARGB32 em ordem de rede (big-endian): A, R, G, B.
            argb = bytearray(width * height * 4)
            out = 0
            for y in range(height):
                base = y * rowstride
                for x in range(width):
                    i = base + x * channels
                    r = pixels[i]
                    g = pixels[i + 1]
                    b = pixels[i + 2]
                    a = pixels[i + 3] if channels == 4 else 255
                    argb[out] = a
                    argb[out + 1] = r
                    argb[out + 2] = g
                    argb[out + 3] = b
                    out += 4

            self._icon_pixmap = GLib.Variant(
                "a(iiay)", [(width, height, bytes(argb))]
            )
            self._log("pixmap: carregado", f"{width}x{height}",
                      f"({len(argb)} bytes)")
        except Exception as exc:  # noqa: BLE001 — qualquer falha: cai p/ IconName
            self._log("pixmap: FALHOU ->", repr(exc))
            self._icon_pixmap = False

        return self._icon_pixmap or None

    def _on_sni_get_property(self, _conn, _sender, _path, _iface, prop):
        self._log("host consultou propriedade:", prop)
        pixmap = self._ensure_pixmap()
        # Se temos pixmap, zeramos IconName: a spec manda o host preferir
        # IconName quando preenchido, mesmo que ele não resolva no tema.
        icon_name = "" if pixmap is not None else self.icon_name

        values = {
            "Category": GLib.Variant("s", self.category),
            "Id": GLib.Variant("s", self.app_id),
            "Title": GLib.Variant("s", self.title),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", icon_name),
            "IconPixmap": pixmap if pixmap is not None
            else GLib.Variant("a(iiay)", []),
            "IconThemePath": GLib.Variant("s", self.icon_theme_path),
            "Menu": GLib.Variant("o", _MENU_PATH),
            "ItemIsMenu": GLib.Variant("b", False),
        }
        return values.get(prop)

    # --------------------------- métodos do menu --------------------------- #

    def _item_props(self, item: MenuItem) -> dict:
        if item.is_separator:
            return {"type": GLib.Variant("s", "separator")}
        return {
            "label": GLib.Variant("s", item.label),
            "enabled": GLib.Variant("b", item.enabled),
            "visible": GLib.Variant("b", True),
        }

    def _on_menu_method(
        self, _conn, _sender, _path, _iface, method, params, invocation
    ) -> None:
        self._log("host chamou método do menu:", method)
        if method == "GetLayout":
            children = []
            for item in self.menu_items:
                # Cada filho é um variant de tipo (ia{sv}av); como o array
                # externo é 'av', ele entra diretamente como elemento.
                children.append(
                    GLib.Variant(
                        "(ia{sv}av)",
                        (item._dbus_id, self._item_props(item), []),
                    )
                )
            # Atenção: aqui passamos VALORES NATIVOS (tuplas). Num format
            # string composto, só posições 'v' recebem GLib.Variant prontos;
            # o resto é construído a partir de valores Python.
            root_value = (0, {}, children)
            invocation.return_value(
                GLib.Variant("(u(ia{sv}av))", (self._menu_revision, root_value))
            )

        elif method == "GetGroupProperties":
            ids = params.unpack()[0]
            out = []
            for item in self.menu_items:
                if not ids or item._dbus_id in ids:
                    out.append((item._dbus_id, self._item_props(item)))
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))

        elif method == "GetProperty":
            item_id, name = params.unpack()
            value = GLib.Variant("s", "")
            for item in self.menu_items:
                if item._dbus_id == item_id:
                    value = self._item_props(item).get(name, GLib.Variant("s", ""))
                    break
            invocation.return_value(GLib.Variant("(v)", (value,)))

        elif method == "Event":
            item_id, event_id = params.unpack()[0], params.unpack()[1]
            if event_id == "clicked":
                for item in self.menu_items:
                    if item._dbus_id == item_id and item.callback is not None:
                        item.callback()
                        break
            invocation.return_value(None)

        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))

        else:
            invocation.return_value(None)

    def _on_menu_get_property(self, _conn, _sender, _path, _iface, prop):
        values = {
            "Version": GLib.Variant("u", 3),
            "Status": GLib.Variant("s", "normal"),
            "TextDirection": GLib.Variant("s", "ltr"),
        }
        return values.get(prop)
