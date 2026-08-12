"""
Esquemas de cores pré-definidos do POR.ai.

A libadwaita expõe um conjunto de "cores nomeadas" (named colors) usadas por
todos os widgets padrão — @window_bg_color, @accent_bg_color, etc. Para
"temar" o app sem reescrever CSS de cada widget, basta redefinir essas cores
com `@define-color` num CssProvider de prioridade alta; todo o resto (botões,
listas, popovers, cabeçalho...) se ajusta sozinho.

Cada entrada de THEMES guarda só um punhado de cores-base (bg, bg_dim,
surface, fg, accent, accent_fg, border) e `_expand()` deriva delas todas as
cores nomeadas que a libadwaita espera.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

# Cada tema é definido por um pequeno conjunto de cores-base. "swatches" são
# as 3 cores mostradas como pré-visualização na janela de seleção.
THEMES: Dict[str, Dict] = {
    "everforest": {
        "label": "Everforest",
        "bg": "#2d353b",
        "bg_dim": "#272e33",
        "surface": "#3d484d",
        "fg": "#d3c6aa",
        "accent": "#a7c080",
        "accent_fg": "#2d353b",
        "border": "#4f585e",
    },
    "gruvbox": {
        "label": "Gruvbox",
        "bg": "#282828",
        "bg_dim": "#1d2021",
        "surface": "#3c3836",
        "fg": "#ebdbb2",
        "accent": "#fe8019",
        "accent_fg": "#282828",
        "border": "#504945",
    },
    "tokyo-night": {
        "label": "Tokyo Night",
        "bg": "#1a1b26",
        "bg_dim": "#16161e",
        "surface": "#24283b",
        "fg": "#c0caf5",
        "accent": "#7aa2f7",
        "accent_fg": "#1a1b26",
        "border": "#292e42",
    },
    "catppuccin": {
        "label": "Catppuccin (Mocha)",
        "bg": "#1e1e2e",
        "bg_dim": "#181825",
        "surface": "#313244",
        "fg": "#cdd6f4",
        "accent": "#cba6f7",
        "accent_fg": "#1e1e2e",
        "border": "#45475a",
    },
    "dracula": {
        "label": "Dracula",
        "bg": "#282a36",
        "bg_dim": "#21222c",
        "surface": "#343746",
        "fg": "#f8f8f2",
        "accent": "#bd93f9",
        "accent_fg": "#282a36",
        "border": "#44475a",
    },
    "nord": {
        "label": "Nord",
        "bg": "#2e3440",
        "bg_dim": "#272c36",
        "surface": "#3b4252",
        "fg": "#eceff4",
        "accent": "#88c0d0",
        "accent_fg": "#2e3440",
        "border": "#434c5e",
    },
    "ayu": {
        "label": "Ayu",
        "bg": "#0a0e14",
        "bg_dim": "#060a10",
        "surface": "#131721",
        "fg": "#b3b1ad",
        "accent": "#ffb454",
        "accent_fg": "#0a0e14",
        "border": "#1b202b",
    },
    "cherry-blossom": {
        "label": "Cherry Blossom",
        "bg": "#fdf6f8",
        "bg_dim": "#f7e9ee",
        "surface": "#ffffff",
        "fg": "#4a3b3f",
        "accent": "#d1667c",
        "accent_fg": "#fef7f9",
        "border": "#eccdd6",
    },
}

# Chave especial: sem override, usa o tema do sistema/GTK normalmente.
SYSTEM_SCHEME_ID = "system"
SYSTEM_LABEL = "Padrão do sistema"

_STYLE_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_USER


def scheme_ids_in_order() -> List[str]:
    """Ids na ordem em que devem aparecer na UI (sistema primeiro)."""
    return [SYSTEM_SCHEME_ID, *THEMES.keys()]


def scheme_label(scheme_id: str) -> str:
    if scheme_id == SYSTEM_SCHEME_ID or scheme_id not in THEMES:
        return SYSTEM_LABEL
    return THEMES[scheme_id]["label"]


def scheme_swatches(scheme_id: str) -> List[str]:
    """3 cores para a pré-visualização; lista vazia para 'sistema'."""
    theme = THEMES.get(scheme_id)
    if not theme:
        return []
    return [theme["bg"], theme["surface"], theme["accent"]]


def _expand(colors: Dict[str, str]) -> Dict[str, str]:
    """Deriva todas as cores nomeadas da libadwaita a partir da paleta base."""
    bg = colors["bg"]
    bg_dim = colors["bg_dim"]
    surface = colors["surface"]
    fg = colors["fg"]
    accent = colors["accent"]
    accent_fg = colors["accent_fg"]
    border = colors["border"]

    return {
        "accent_color": accent,
        "accent_bg_color": accent,
        "accent_fg_color": accent_fg,
        "window_bg_color": bg,
        "window_fg_color": fg,
        "view_bg_color": bg_dim,
        "view_fg_color": fg,
        "headerbar_bg_color": bg,
        "headerbar_fg_color": fg,
        "headerbar_border_color": border,
        "headerbar_backdrop_color": bg,
        "headerbar_shade_color": "rgba(0, 0, 0, 0.36)",
        "card_bg_color": surface,
        "card_fg_color": fg,
        "card_shade_color": "rgba(0, 0, 0, 0.25)",
        "dialog_bg_color": surface,
        "dialog_fg_color": fg,
        "popover_bg_color": surface,
        "popover_fg_color": fg,
        "shade_color": "rgba(0, 0, 0, 0.25)",
        "scrollbar_outline_color": "rgba(0, 0, 0, 0.5)",
        "sidebar_bg_color": bg_dim,
        "sidebar_fg_color": fg,
        "sidebar_border_color": border,
        "sidebar_backdrop_color": bg_dim,
        "sidebar_shade_color": "rgba(0, 0, 0, 0.25)",
        # Aliases "legados" (GTK3-era) que alguns widgets/temas de ícone ou
        # estilos internos (como a classe .navigation-sidebar) ainda usam
        # como fallback em vez das cores nomeadas mais novas do libadwaita.
        "theme_bg_color": bg,
        "theme_fg_color": fg,
        "theme_base_color": bg_dim,
        "theme_text_color": fg,
        "theme_selected_bg_color": accent,
        "theme_selected_fg_color": accent_fg,
        "theme_unfocused_bg_color": bg,
        "theme_unfocused_fg_color": fg,
        "theme_unfocused_base_color": bg_dim,
        "theme_unfocused_text_color": fg,
        "borders": border,
        "unfocused_borders": border,
    }


def _extra_rules(colors: Dict[str, str]) -> str:
    """Regras explícitas para widgets que não seguem só as cores nomeadas
    (ex.: a lista lateral usa a classe `.navigation-sidebar`, cujo fundo em
    algumas versões do libadwaita não reage a @sidebar_bg_color)."""
    bg_dim = colors["bg_dim"]
    surface = colors["surface"]
    fg = colors["fg"]
    accent = colors["accent"]
    accent_fg = colors["accent_fg"]

    return f"""
list.navigation-sidebar,
.navigation-sidebar {{
    background-color: {bg_dim};
    color: {fg};
}}
.navigation-sidebar > row {{
    background-color: transparent;
    color: {fg};
}}
.navigation-sidebar > row:hover {{
    background-color: alpha(currentColor, 0.08);
}}
.navigation-sidebar > row:selected {{
    background-color: {surface};
}}
.navigation-sidebar > row:selected:hover {{
    background-color: alpha({accent}, 0.18);
}}
""".strip()


def build_css(scheme_id: str) -> Optional[str]:
    """CSS com @define-color para o esquema, ou None para o tema do sistema."""
    theme = THEMES.get(scheme_id)
    if theme is None:
        return None
    named = _expand(theme)
    lines = [f"@define-color {name} {value};" for name, value in named.items()]
    lines.append(_extra_rules(theme))
    return "\n".join(lines)


def apply_scheme(display: Optional[Gdk.Display], scheme_id: str) -> Optional[Gtk.CssProvider]:
    """Instala (ou None se 'sistema') o provider de cores no display dado.

    Quem chamar é responsável por remover o provider anterior antes, com
    `Gtk.StyleContext.remove_provider_for_display`.
    """
    if display is None:
        return None
    css = build_css(scheme_id)
    if css is None:
        return None
    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(css)
    else:
        try:
            provider.load_from_data(css, -1)
        except TypeError:
            provider.load_from_data(css.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(display, provider, _STYLE_PRIORITY)
    return provider


_SWATCH_CSS_INSTALLED = False


def ensure_swatch_css_installed(display: Optional[Gdk.Display]) -> None:
    """Instala (uma única vez) as classes .porai-swatch-<id>-<n> usadas nos
    quadradinhos de pré-visualização da janela de temas."""
    global _SWATCH_CSS_INSTALLED
    if _SWATCH_CSS_INSTALLED or display is None:
        return

    rules = []
    for scheme_id in THEMES:
        for index, color in enumerate(scheme_swatches(scheme_id)):
            rules.append(
                f".porai-swatch-{scheme_id}-{index} {{ background-color: {color}; }}"
            )
    css = "\n".join(rules)

    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(css)
    else:
        try:
            provider.load_from_data(css, -1)
        except TypeError:
            provider.load_from_data(css.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _SWATCH_CSS_INSTALLED = True
