"""
Geração de apresentações (.odp) a partir de uma spec JSON.

Mesma filosofia de sheet_gen: o modelo descreve o CONTEÚDO (slides, textos,
dados, tema) e o app cuida do LAYOUT. Posição, tamanho de fonte e quebra
de slides são calculados aqui, porque o modelo não tem como saber se um
texto cabe numa caixa de 25 cm — e um slide com texto vazando é o defeito
mais comum de apresentação gerada por LLM.

Só ODP (OpenDocument), com o odfpy que o app já usa para as planilhas:
nenhuma dependência nova. LibreOffice Impress abre nativamente; PowerPoint
e Google Slides também importam .odp. Quem precisar de .pptx salva como
pptx no Impress.

Tudo é nativo e editável no Impress: título e tópicos são caixas de texto
com listas de verdade (não "• " digitado), tabela é tabela do Impress, as
notas do apresentador vão no campo de notas e o número do slide é um campo
que se atualiza se a pessoa reordenar os slides. A exceção é o gráfico,
que é uma imagem PNG gerada por chart_gen — pelo mesmo motivo explicado lá
(gráfico nativo exigiria montar um objeto embutido à mão).

Todas as chaves são opcionais exceto "slides". Cores inválidas caem no
tema padrão e cores sem contraste suficiente são corrigidas, porque o
valor vem de um LLM e não dá para confiar.
"""

from __future__ import annotations

import logging
import math
import re
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

try:
    from odf.dc import Title as DcTitle
    from odf.draw import Frame, Image as DrawImage, Page, Rect, TextBox
    from odf.opendocument import OpenDocumentPresentation
    from odf.namespaces import PRESENTATIONNS
    from odf.presentation import Notes
    from odf.style import (
        DrawingPageProperties,
        GraphicProperties,
        ListLevelProperties,
        MasterPage,
        PageLayout,
        PageLayoutProperties,
        ParagraphProperties,
        Style,
        TableColumnProperties,
        TableRowProperties,
        TextProperties,
    )
    from odf.table import Table, TableCell, TableColumn, TableRow
    from odf.text import (
        List as TextList,
        ListItem,
        ListLevelStyleBullet,
        ListStyle,
        P,
        PageNumber,
    )
    ODP_BACKEND = True
except ImportError:
    ODP_BACKEND = False

from core import chart_gen
from core.i18n import _


# ── Geometria (cm) ───────────────────────────────────────────────────────────
#
# 16:9 em 28 x 15,75 cm, o mesmo tamanho "Tela 16:9" do Impress.

_PAGE_W = 28.0
_PAGE_H = 15.75
_MARGIN_X = 1.5
_CONTENT_W = _PAGE_W - 2 * _MARGIN_X

_TITLE_Y = 0.6
_TITLE_H = 2.2
_RULE_Y = 2.95
_BODY_Y = 3.5
_BODY_H = _PAGE_H - _BODY_Y - 1.1  # sobra embaixo para o número do slide

_CM_PER_PT = 0.03528

# Tamanhos de fonte tentados nos tópicos, do maior para o menor. Abaixo de
# 16 pt o texto fica ilegível projetado: em vez de encolher mais, o
# conteúdo é dividido em mais de um slide.
_BULLET_SIZES = (26, 24, 22, 20, 18, 16)
_SPLIT_SIZE = 20  # tamanho usado para decidir quanto cabe em cada parte

_MAX_SLIDES = 80
_MAX_TABLE_ROWS_PER_SLIDE = 8


# ── Tema de fallback ─────────────────────────────────────────────────────────
#
# Como em sheet_gen: não é "o tema do app", é o que sobra quando o modelo
# omite "theme" ou manda hex inválido. Neutro e claro de propósito — slide
# claro imprime bem e funciona em projetor fraco.

_DEFAULT_THEME = {
    "bg": "FFFFFF",         # fundo dos slides
    "title_fg": "1F2933",   # títulos
    "fg": "3A4750",         # texto
    "accent": "3A4750",     # marcadores, filetes, cabeçalho de tabela, slide de seção
    "accent_fg": "FFFFFF",  # texto sobre o accent
}

_RE_HEX = re.compile(r"[0-9A-F]{6}")
_RE_SLUG = re.compile(r"[^a-z0-9]+")

LAYOUTS = ("title", "section", "bullets", "two_columns", "table", "chart")


class SlideSpecError(ValueError):
    """Especificação inválida (JSON fora do formato esperado)."""


def available() -> bool:
    """True se dá para gerar .odp nesta instalação (odfpy presente)."""
    return ODP_BACKEND


def capabilities_prompt() -> str:
    """Texto a acrescentar ao system prompt, como sheet_gen.capabilities_prompt().

    Vazio quando o odfpy não está instalado: o modelo nunca é instruído a
    produzir um bloco que ninguém vai converter.
    """
    if not ODP_BACKEND:
        return ""

    lines = [
        "Ao gerar uma apresentação de slides para o usuário, produza um "
        "bloco de código cercado com ```odp (escreva exatamente odp após as "
        "crases, não json); dentro da cerca vai APENAS um JSON válido, sem "
        "comentários. O formato é sempre .odp, mesmo que o "
        "usuário peça PowerPoint/pptx: nesse caso diga a ele que o "
        "PowerPoint abre .odp e que o LibreOffice Impress salva em .pptx.",
        "Formato:",
        '{"title": "...", "theme": {"bg": "RRGGBB", "title_fg": "RRGGBB", '
        '"fg": "RRGGBB", "accent": "RRGGBB", "accent_fg": "RRGGBB"}, '
        '"slides": [ ... ]}',
        "Cada slide é um objeto com \"layout\" e as chaves do layout:",
        '- "title": {"layout": "title", "title": "...", "subtitle": "..."} '
        "— capa ou encerramento.",
        '- "section": {"layout": "section", "title": "...", "subtitle": "..."} '
        "— divisória entre partes.",
        '- "bullets": {"layout": "bullets", "title": "...", "bullets": '
        '["tópico", ["subtópico", "subtópico"], "tópico"]} — uma lista '
        "dentro da lista vira subtópicos do item anterior.",
        '- "two_columns": {"layout": "two_columns", "title": "...", '
        '"left_title": "...", "left": [...], "right_title": "...", '
        '"right": [...]} — comparações, prós e contras, antes e depois.',
        '- "table": {"layout": "table", "title": "...", "columns": '
        '["Col1", ...], "rows": [[v1, ...], ...]}',
    ]
    if chart_gen.CHART_BACKEND:
        lines.append(
            '- "chart": {"layout": "chart", "title": "...", "columns": [...], '
            '"rows": [...], "chart": {"type": "bar" | "line" | "pie" | '
            '"scatter", "category_column": "...", "value_columns": ["..."], '
            '"x_label": "...", "y_label": "..."}} — category_column e '
            "value_columns DEVEM ser nomes que existem em columns; scatter "
            "usa x_column no lugar de category_column."
        )
    else:
        lines.append(
            "Gráficos NÃO estão disponíveis nesta instalação: não use o "
            'layout "chart"; para dados, use "table".'
        )
    lines += [
        'Qualquer slide aceita "notes": texto para as notas do apresentador.',
        "Escreva tópicos curtos (frases de slide, não parágrafos), no máximo "
        "6 por slide; o app ajusta a fonte e divide slides longos, mas o "
        "resultado é melhor com texto enxuto.",
        "Em \"table\", os valores aparecem exatamente como enviados: mande "
        "números já formatados como texto no idioma do usuário quando fizer "
        "sentido (\"R$ 1.250,00\", \"12%\"). Em \"chart\", os valores das "
        "colunas usadas no gráfico vão como number JSON (sem aspas nem "
        "separador de milhar).",
        "'theme' é opcional. Escolha as cores conforme o pedido; se o "
        "usuário citar um tema conhecido (everforest, gruvbox, nord, "
        "dracula...), use as cores reais dessa paleta, sempre com contraste "
        "legível entre texto e fundo.",
        "O bloco é trocado por um link de download antes de a resposta "
        "chegar ao usuário: não descreva o bloco nem explique como o "
        "arquivo é gerado. Fora do bloco, no máximo uma frase sobre a "
        "apresentação.",
    ]
    return "\n".join(lines)


# ── Normalização da spec ─────────────────────────────────────────────────────

def _hex_color(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip().lstrip("#").upper()
    return cleaned if _RE_HEX.fullmatch(cleaned) else fallback


def _luminance(hex_color: str) -> float:
    """Luminância relativa (WCAG 2.x)."""
    channels = []
    for i in (0, 2, 4):
        c = int(hex_color[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _readable_on(fg: str, bg: str, minimum: float = 3.0) -> str:
    """Devolve ``fg`` se tiver contraste suficiente com ``bg``; senão,
    preto ou branco, o que contrastar mais. 3:1 é o mínimo WCAG para texto
    grande — slide é quase todo texto grande."""
    if _contrast(fg, bg) >= minimum:
        return fg
    return "000000" if _contrast("000000", bg) >= _contrast("FFFFFF", bg) else "FFFFFF"


def _parse_theme(raw: Any) -> Dict[str, str]:
    theme = dict(_DEFAULT_THEME)
    if isinstance(raw, dict):
        theme.update({k: v for k, v in raw.items() if k in _DEFAULT_THEME})
    theme = {key: _hex_color(theme.get(key), default)
             for key, default in _DEFAULT_THEME.items()}
    theme["title_fg"] = _readable_on(theme["title_fg"], theme["bg"])
    theme["fg"] = _readable_on(theme["fg"], theme["bg"], 4.5)
    theme["accent_fg"] = _readable_on(theme["accent_fg"], theme["accent"])
    return theme


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


# Um "grupo" é um tópico com os seus subtópicos: [(nível, texto), ...].
# É a unidade mínima de divisão entre slides — um subtópico nunca vai
# parar num slide diferente do tópico a que pertence.
_Group = List[Tuple[int, str]]


def _parse_bullets(raw: Any) -> List[_Group]:
    if isinstance(raw, str):
        raw = [line for line in raw.splitlines() if line.strip()]
    if not isinstance(raw, list):
        return []
    groups: List[_Group] = []
    for item in raw:
        if isinstance(item, (list, tuple)):
            subs = [(1, _text(s)) for s in item if _text(s)]
            if not subs:
                continue
            if groups:
                groups[-1].extend(subs)
            else:
                # Subtópicos sem tópico-pai: sobem de nível.
                groups.extend([[(0, text)] for _level, text in subs])
        elif isinstance(item, dict):
            # Tolerância: {"text": "...", "sub": [...]}, forma comum de LLM.
            text = _text(item.get("text") or item.get("title"))
            if not text:
                continue
            group = [(0, text)]
            sub = item.get("sub") or item.get("children") or item.get("bullets")
            if isinstance(sub, list):
                group += [(1, _text(s)) for s in sub if _text(s)]
            groups.append(group)
        else:
            text = _text(item)
            if text:
                groups.append([(0, text)])
    return groups


def _parse_table(slide: Dict[str, Any]) -> Tuple[List[str], List[list]]:
    columns = slide.get("columns")
    rows = slide.get("rows")
    if not isinstance(columns, list) or not columns:
        return [], []
    columns = [_text(c) for c in columns]
    rows = [list(r) for r in rows if isinstance(r, (list, tuple))] if isinstance(rows, list) else []
    return columns, rows


def _infer_layout(slide: Dict[str, Any], index: int) -> str:
    layout = _text(slide.get("layout")).lower().replace("-", "_")
    aliases = {"cover": "title", "capa": "title", "closing": "title",
               "divider": "section", "secao": "section",
               "list": "bullets", "content": "bullets",
               "columns": "two_columns", "comparison": "two_columns"}
    layout = aliases.get(layout, layout)
    if layout in LAYOUTS:
        return layout
    if isinstance(slide.get("chart"), dict):
        return "chart"
    if slide.get("columns") and slide.get("rows"):
        return "table"
    if slide.get("left") or slide.get("right"):
        return "two_columns"
    if slide.get("bullets"):
        return "bullets"
    return "title" if index == 0 else "section"


def parse_spec(spec: Dict[str, Any]) -> Tuple[str, Dict[str, str], List[Dict[str, Any]]]:
    """Valida e normaliza a spec. Devolve (título, tema, slides)."""
    if not isinstance(spec, dict):
        raise SlideSpecError("spec não é um objeto JSON")
    slides = spec.get("slides")
    if not isinstance(slides, list):
        raise SlideSpecError("chave 'slides' ausente ou não é lista")
    slides = [s for s in slides if isinstance(s, dict)][:_MAX_SLIDES]
    if not slides:
        raise SlideSpecError("nenhum slide utilizável")

    theme = _parse_theme(spec.get("theme") or spec.get("style"))
    title = _text(spec.get("title"))
    if not title:
        title = _text(slides[0].get("title")) or _("Apresentação")

    normalized = []
    for index, slide in enumerate(slides):
        item = dict(slide)
        item["layout"] = _infer_layout(slide, index)
        normalized.append(item)
    return title, theme, normalized


def filename_slug(title: str) -> str:
    """Nome de arquivo legível a partir do título ("Resultados Q3" →
    "resultados-q3"), só ASCII para não depender do sistema de arquivos."""
    import unicodedata
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    slug = _RE_SLUG.sub("-", ascii_title.lower()).strip("-")
    return slug[:50].rstrip("-") or "apresentacao"


# ── Estimativa de espaço ─────────────────────────────────────────────────────
#
# Sem renderizador de texto à mão, a medida é aproximada: largura média de
# caractere ≈ 0,5 em nas fontes sem serifa padrão. Erra para mais, de
# propósito — sobra de espaço não é defeito, texto vazando é.

_INDENT_CM = 1.0
_LINE_FACTOR = 1.2
_SPACE_FACTOR = 0.5   # espaço entre tópicos, em "em"
_CHAR_EM = 0.52


def _line_height(size: float) -> float:
    return size * _CM_PER_PT * _LINE_FACTOR


def _text_lines(text: str, width_cm: float, size: float) -> int:
    chars_per_line = max(8, int(width_cm / (size * _CM_PER_PT * _CHAR_EM)))
    total = 0
    for paragraph in text.split("\n"):
        total += max(1, math.ceil(len(paragraph) / chars_per_line))
    return total


def _groups_height(groups: Sequence[_Group], width_cm: float, size: float) -> float:
    height = 0.0
    for group in groups:
        for level, text in group:
            item_size = size if level == 0 else size * 0.85
            usable = width_cm - _INDENT_CM * (level + 1)
            height += _text_lines(text, usable, item_size) * _line_height(item_size)
            height += item_size * _CM_PER_PT * _SPACE_FACTOR
    return height


def _fit_size(groups: Sequence[_Group], width_cm: float, height_cm: float) -> Optional[int]:
    for size in _BULLET_SIZES:
        if _groups_height(groups, width_cm, size) <= height_cm:
            return size
    return None


def _split_groups(groups: List[_Group], width_cm: float, height_cm: float) -> List[List[_Group]]:
    """Divide os tópicos em partes que caibam a _SPLIT_SIZE pt."""
    parts: List[List[_Group]] = [[]]
    for group in groups:
        candidate = parts[-1] + [group]
        if parts[-1] and _groups_height(candidate, width_cm, _SPLIT_SIZE) > height_cm:
            parts.append([group])
        else:
            parts[-1] = candidate
    return parts


def _title_size(text: str, base: int = 32) -> int:
    length = len(text)
    if length > 80:
        return base - 10
    if length > 55:
        return base - 6
    if length > 35:
        return base - 3
    return base


def _png_size(data: bytes) -> Optional[Tuple[int, int]]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height) if width and height else None


# ── Construção do documento ──────────────────────────────────────────────────

def _cm(value: float) -> str:
    return f"{value:.2f}cm"


class _Builder:
    """Monta o .odp. Guarda os estilos criados para não duplicar: o mesmo
    tamanho de fonte usado em dez slides vira um estilo só."""

    def __init__(self, title: str, theme: Dict[str, str]) -> None:
        self.theme = theme
        self.doc = OpenDocumentPresentation()
        self.doc.meta.addElement(DcTitle(text=title))
        self._styles: Dict[Tuple, Any] = {}
        self._page_count = 0

        layout = PageLayout(name="PL16x9")
        layout.addElement(PageLayoutProperties(
            pagewidth=_cm(_PAGE_W), pageheight=_cm(_PAGE_H),
            printorientation="landscape",
            margintop="0cm", marginbottom="0cm", marginleft="0cm", marginright="0cm",
        ))
        self.doc.automaticstyles.addElement(layout)
        self.master = MasterPage(name="PorAi", pagelayoutname=layout)
        self.doc.masterstyles.addElement(self.master)

    # Estilos ------------------------------------------------------------

    def _cached(self, key: Tuple, factory):
        style = self._styles.get(key)
        if style is None:
            style = factory(f"s{len(self._styles)}")
            self.doc.automaticstyles.addElement(style)
            self._styles[key] = style
        return style

    def page_style(self, bg: str):
        def make(name):
            style = Style(name=name, family="drawing-page")
            style.addElement(DrawingPageProperties(
                fill="solid", fillcolor=f"#{bg}", backgroundsize="full",
            ))
            return style
        return self._cached(("page", bg), make)

    def box_style(self, valign: str = "top", shrink: bool = True):
        """Caixa sem preenchimento nem borda. Sem isso o Impress pinta a
        caixa com o azul padrão de forma. O "shrink-to-fit" é a rede de
        segurança do Impress caso a estimativa de espaço erre."""
        def make(name):
            style = Style(name=name, family="graphic")
            props = dict(
                fill="none", stroke="none",
                textareaverticalalign=valign,
                autogrowheight="false", autogrowwidth="false",
                paddingtop="0.1cm", paddingbottom="0.1cm",
                paddingleft="0.1cm", paddingright="0.1cm",
            )
            if shrink:
                props["fittosize"] = "shrink-to-fit"
            style.addElement(GraphicProperties(**props))
            return style
        return self._cached(("box", valign, shrink), make)

    def fill_style(self, color: str):
        def make(name):
            style = Style(name=name, family="graphic")
            style.addElement(GraphicProperties(
                fill="solid", fillcolor=f"#{color}", stroke="none",
            ))
            return style
        return self._cached(("fill", color), make)

    def image_style(self):
        def make(name):
            style = Style(name=name, family="graphic")
            style.addElement(GraphicProperties(fill="none", stroke="none"))
            return style
        return self._cached(("image",), make)

    def para_style(self, size: float, color: str, bold: bool = False,
                   align: str = "start", space_after: float = 0.0):
        def make(name):
            style = Style(name=name, family="paragraph")
            style.addElement(ParagraphProperties(
                textalign=align, marginbottom=_cm(space_after),
                margintop="0cm",
            ))
            style.addElement(TextProperties(
                fontsize=f"{size:g}pt", color=f"#{color}",
                fontweight="bold" if bold else "normal",
                fontsizeasian=f"{size:g}pt", fontsizecomplex=f"{size:g}pt",
            ))
            return style
        return self._cached(("para", size, color, bold, align, round(space_after, 2)), make)

    def list_style(self, size: float):
        """Lista com marcadores de verdade: no Impress a pessoa continua
        editando com Tab / Shift+Tab e o marcador acompanha."""
        accent = self.theme["accent"]
        if _contrast(accent, self.theme["bg"]) < 2.0:
            accent = self.theme["fg"]

        def make(name):
            style = ListStyle(name=name)
            for level, char in ((1, "●"), (2, "–")):
                bullet = ListLevelStyleBullet(level=level, bulletchar=char,
                                              bulletrelativesize="75%")
                bullet.addElement(ListLevelProperties(
                    spacebefore=_cm(_INDENT_CM * (level - 1)),
                    minlabelwidth=_cm(_INDENT_CM),
                ))
                bullet.addElement(TextProperties(color=f"#{accent}"))
                style.addElement(bullet)
            return style
        return self._cached(("list", size, accent), make)

    def cell_style(self, bg: str, fg: str, size: float, bold: bool):
        border = self.theme["bg"]

        def make(name):
            style = Style(name=name, family="table-cell")
            style.addElement(GraphicProperties(
                fill="solid", fillcolor=f"#{bg}",
                textareaverticalalign="middle",
                paddingleft="0.25cm", paddingright="0.25cm",
                paddingtop="0.1cm", paddingbottom="0.1cm",
            ))
            style.addElement(ParagraphProperties(border=f"0.5pt solid #{border}"))
            style.addElement(TextProperties(
                fontsize=f"{size:g}pt", color=f"#{fg}",
                fontweight="bold" if bold else "normal",
            ))
            return style
        return self._cached(("cell", bg, fg, size, bold), make)

    def column_style(self, width: float):
        def make(name):
            style = Style(name=name, family="table-column")
            style.addElement(TableColumnProperties(columnwidth=_cm(width)))
            return style
        return self._cached(("col", round(width, 2)), make)

    def row_style(self, height: float):
        def make(name):
            style = Style(name=name, family="table-row")
            style.addElement(TableRowProperties(rowheight=_cm(height)))
            return style
        return self._cached(("row", round(height, 2)), make)

    # Elementos ----------------------------------------------------------

    def new_page(self, bg: Optional[str] = None):
        self._page_count += 1
        page = Page(
            name=f"Slide {self._page_count}",
            masterpagename=self.master,
            stylename=self.page_style(bg or self.theme["bg"]),
        )
        self.doc.presentation.addElement(page)
        return page

    def text_frame(self, page, x, y, w, h, paragraphs, valign="top", shrink=True):
        frame = Frame(stylename=self.box_style(valign, shrink),
                      x=_cm(x), y=_cm(y), width=_cm(w), height=_cm(h))
        box = TextBox()
        for element in paragraphs:
            box.addElement(element)
        frame.addElement(box)
        page.addElement(frame)
        return frame

    def rule(self, page, x, y, w, h, color):
        page.addElement(Rect(stylename=self.fill_style(color),
                             x=_cm(x), y=_cm(y), width=_cm(w), height=_cm(h)))

    def bullet_list(self, groups: Sequence[_Group], size: float):
        """Elemento <text:list> com os tópicos e subtópicos."""
        lst = TextList(stylename=self.list_style(size))
        fg = self.theme["fg"]
        top_style = self.para_style(size, fg, space_after=size * _CM_PER_PT * _SPACE_FACTOR)
        sub_size = round(size * 0.85)
        sub_style = self.para_style(sub_size, fg,
                                    space_after=sub_size * _CM_PER_PT * _SPACE_FACTOR)
        for group in groups:
            item = ListItem()
            item.addElement(P(stylename=top_style, text=group[0][1]))
            subs = [text for level, text in group[1:]]
            if subs:
                sub_list = TextList()
                for text in subs:
                    sub_item = ListItem()
                    sub_item.addElement(P(stylename=sub_style, text=text))
                    sub_list.addElement(sub_item)
                item.addElement(sub_list)
            lst.addElement(item)
        return lst

    def notes(self, page, text: str) -> None:
        text = _text(text)
        if not text:
            return
        notes = Notes()
        frame = Frame(x="2cm", y="14cm", width="17cm", height="11cm")
        # presentation:class não está na lista de atributos do odfpy para
        # draw:frame, então vai direto pelo namespace.
        frame.setAttrNS(PRESENTATIONNS, "class", "notes")
        box = TextBox()
        style = self.para_style(12, "000000")
        for line in text.splitlines() or [text]:
            box.addElement(P(stylename=style, text=line))
        frame.addElement(box)
        notes.addElement(frame)
        page.addElement(notes)

    def slide_number(self, page, color: str) -> None:
        """Campo de número do slide (atualiza sozinho se reordenar)."""
        para = P(stylename=self.para_style(12, color, align="end"))
        para.addElement(PageNumber(selectpage="current"))
        self.text_frame(page, _PAGE_W - _MARGIN_X - 3, _PAGE_H - 1.0, 3, 0.7,
                        [para], valign="middle", shrink=False)

    def save(self, path: str) -> None:
        self.doc.save(path)


# ── Layouts ──────────────────────────────────────────────────────────────────

def _content_header(b: _Builder, page, title: str) -> None:
    if title:
        size = _title_size(title)
        b.text_frame(page, _MARGIN_X, _TITLE_Y, _CONTENT_W, _TITLE_H,
                     [P(stylename=b.para_style(size, b.theme["title_fg"], bold=True),
                        text=title)],
                     valign="bottom")
    b.rule(page, _MARGIN_X, _RULE_Y, 3.0, 0.12, b.theme["accent"])


def _finish(b: _Builder, page, slide: Dict[str, Any], numbered: bool = True,
            number_color: Optional[str] = None) -> None:
    if numbered:
        b.slide_number(page, number_color or b.theme["fg"])
    b.notes(page, slide.get("notes"))


def _continued(title: str, index: int) -> str:
    if index == 0:
        return title
    suffix = _("(cont.)")
    return f"{title} {suffix}" if title else suffix


def _layout_title(b: _Builder, slide: Dict[str, Any]) -> None:
    page = b.new_page()
    title = _text(slide.get("title"))
    subtitle = _text(slide.get("subtitle"))
    t = b.theme
    b.rule(page, 0, 0, 0.6, _PAGE_H, t["accent"])
    b.text_frame(page, 2.5, 3.0, _PAGE_W - 5, 5.0,
                 [P(stylename=b.para_style(_title_size(title, 46), t["title_fg"], bold=True),
                    text=title)],
                 valign="bottom")
    b.rule(page, 2.6, 8.35, 4.0, 0.15, t["accent"])
    if subtitle:
        b.text_frame(page, 2.5, 8.9, _PAGE_W - 5, 3.5,
                     [P(stylename=b.para_style(24, t["fg"]), text=line)
                      for line in subtitle.splitlines()])
    _finish(b, page, slide, numbered=False)


def _layout_section(b: _Builder, slide: Dict[str, Any]) -> None:
    t = b.theme
    page = b.new_page(bg=t["accent"])
    title = _text(slide.get("title"))
    subtitle = _text(slide.get("subtitle"))
    b.text_frame(page, 2.5, 3.5, _PAGE_W - 5, 4.5,
                 [P(stylename=b.para_style(_title_size(title, 40), t["accent_fg"], bold=True),
                    text=title)],
                 valign="bottom")
    if subtitle:
        b.text_frame(page, 2.5, 8.4, _PAGE_W - 5, 3.0,
                     [P(stylename=b.para_style(22, t["accent_fg"]), text=subtitle)])
    _finish(b, page, slide, number_color=t["accent_fg"])


def _layout_bullets(b: _Builder, slide: Dict[str, Any]) -> None:
    title = _text(slide.get("title"))
    groups = _parse_bullets(slide.get("bullets"))
    if not groups:
        groups = _parse_bullets(slide.get("text") or slide.get("body"))

    width, height = _CONTENT_W, _BODY_H
    parts = [groups] if _fit_size(groups, width, height) else _split_groups(groups, width, height)
    for index, part in enumerate(parts):
        page = b.new_page()
        _content_header(b, page, _continued(title, index))
        if part:
            size = _fit_size(part, width, height) or _BULLET_SIZES[-1]
            b.text_frame(page, _MARGIN_X, _BODY_Y + 0.2, width, height - 0.2,
                         [b.bullet_list(part, size)])
        # Notas só na primeira parte: são da ideia, não de cada pedaço.
        _finish(b, page, slide if index == 0 else {})


def _layout_two_columns(b: _Builder, slide: Dict[str, Any]) -> None:
    page = b.new_page()
    _content_header(b, page, _text(slide.get("title")))
    gap = 1.2
    col_w = (_CONTENT_W - gap) / 2
    t = b.theme

    columns = []
    for side in ("left", "right"):
        heading = _text(slide.get(f"{side}_title"))
        groups = _parse_bullets(slide.get(side))
        columns.append((heading, groups))

    has_heading = any(h for h, _g in columns)
    heading_h = 1.2 if has_heading else 0.0
    body_h = _BODY_H - heading_h - 0.2
    sizes = [_fit_size(g, col_w, body_h) or _BULLET_SIZES[-1] for _h, g in columns if g]
    size = min(sizes) if sizes else _BULLET_SIZES[0]

    for index, (heading, groups) in enumerate(columns):
        x = _MARGIN_X + index * (col_w + gap)
        y = _BODY_Y + 0.2
        if heading:
            b.text_frame(page, x, y, col_w, heading_h,
                         [P(stylename=b.para_style(min(size + 2, 26), t["accent"]
                                                  if _contrast(t["accent"], t["bg"]) >= 3
                                                  else t["title_fg"], bold=True),
                            text=heading)],
                         valign="middle")
        if groups:
            b.text_frame(page, x, y + heading_h, col_w, body_h,
                         [b.bullet_list(groups, size)])
    _finish(b, page, slide)


def _cell_text(value: Any) -> str:
    if isinstance(value, bool):
        return _("Sim") if value else _("Não")
    return _text(value)


def _layout_table(b: _Builder, slide: Dict[str, Any], title: Optional[str] = None) -> None:
    title = _text(slide.get("title")) if title is None else title
    columns, rows = _parse_table(slide)
    if not columns:
        _layout_bullets(b, {"title": title, "bullets": [], "notes": slide.get("notes")})
        return
    ncols = len(columns)
    rows = [[_cell_text(v) for v in (r + [""] * ncols)[:ncols]] for r in rows]
    t = b.theme

    # Partes equilibradas: 13 linhas viram 7 + 6, não 8 + 5.
    parts = max(1, math.ceil(len(rows) / _MAX_TABLE_ROWS_PER_SLIDE))
    per_part = math.ceil(len(rows) / parts) if rows else 0
    chunks = [rows[i:i + per_part] for i in range(0, len(rows), per_part)] if rows else [[]]

    # Largura das colunas proporcional ao texto mais longo de cada uma,
    # com piso e teto para nenhuma coluna sumir ou engolir as outras.
    weights = []
    for i, name in enumerate(columns):
        longest = max([len(name)] + [len(r[i]) for r in rows])
        weights.append(min(max(longest, 4), 40))
    total = sum(weights)
    widths = [_CONTENT_W * w / total for w in weights]

    # Fundo das linhas: um leve contraste com o fundo do slide, nas duas
    # direções (escurece slide claro, clareia slide escuro).
    def _shade(color: str, amount: float) -> str:
        light = _luminance(color) > 0.4
        out = ""
        for i in (0, 2, 4):
            c = int(color[i:i + 2], 16)
            c = c - (c * amount) if light else c + ((255 - c) * amount)
            out += f"{int(max(0, min(255, c))):02X}"
        return out

    row_bg = (_shade(t["bg"], 0.04), _shade(t["bg"], 0.10))

    for index, chunk in enumerate(chunks):
        page = b.new_page()
        _content_header(b, page, _continued(title, index))
        nrows = len(chunk) + 1
        size = 20 if nrows <= 5 else 18 if nrows <= 7 else 16 if nrows <= 9 else 14
        # Altura de cada linha: a célula mais "alta" da linha manda.
        heights = []
        for row in [columns] + chunk:
            lines = max(_text_lines(cell, widths[i] - 0.5, size) for i, cell in enumerate(row))
            heights.append(lines * _line_height(size) + 0.35)
        scale = min(1.0, (_BODY_H - 0.3) / sum(heights))
        heights = [h * scale for h in heights]

        table = Table(name=f"Tabela{b._page_count}")
        for width in widths:
            table.addElement(TableColumn(stylename=b.column_style(width)))
        for r_index, row in enumerate([columns] + chunk):
            tr = TableRow(stylename=b.row_style(heights[r_index]))
            if r_index == 0:
                style = b.cell_style(t["accent"], t["accent_fg"], size, True)
            else:
                bg = row_bg[(r_index - 1) % 2]
                style = b.cell_style(bg, _readable_on(t["fg"], bg, 4.5), size, False)
            for cell_text in row:
                cell = TableCell(stylename=style)
                cell.addElement(P(text=cell_text))
                tr.addElement(cell)
            table.addElement(tr)

        frame = Frame(x=_cm(_MARGIN_X), y=_cm(_BODY_Y + 0.3),
                      width=_cm(_CONTENT_W), height=_cm(sum(heights)))
        frame.addElement(table)
        page.addElement(frame)
        _finish(b, page, slide if index == 0 else {})


def _layout_chart(b: _Builder, slide: Dict[str, Any]) -> None:
    title = _text(slide.get("title"))
    columns, rows = _parse_table(slide)
    chart_spec = slide.get("chart") if isinstance(slide.get("chart"), dict) else None
    png = None
    if columns and rows and chart_spec is not None:
        # O título vai no slide; repetido dentro da imagem só ocupa espaço.
        spec = {k: v for k, v in chart_spec.items() if k != "title"}
        png = chart_gen.render_chart(
            spec, columns, rows,
            {"header_bg": b.theme["accent"], "row_fg": "1F2933"},
        )
    if not png:
        # Sem matplotlib ou com spec ruim: os dados ainda chegam, como tabela.
        logger.info("Gráfico indisponível no slide %r; usando tabela", title)
        _layout_table(b, slide, title)
        return

    page = b.new_page()
    _content_header(b, page, title)
    box_w, box_h = _CONTENT_W, _BODY_H - 0.2
    width, height = box_w, box_h
    size = _png_size(png)
    if size:
        ratio = size[0] / size[1]
        width = min(box_w, box_h * ratio)
        height = width / ratio
    x = (_PAGE_W - width) / 2
    y = _BODY_Y + 0.2 + (box_h - height) / 2
    href = b.doc.addPictureFromString(png, "image/png")
    frame = Frame(stylename=b.image_style(), x=_cm(x), y=_cm(y),
                  width=_cm(width), height=_cm(height))
    frame.addElement(DrawImage(href=href))
    page.addElement(frame)
    _finish(b, page, slide)


_LAYOUT_BUILDERS = {
    "title": _layout_title,
    "section": _layout_section,
    "bullets": _layout_bullets,
    "two_columns": _layout_two_columns,
    "table": _layout_table,
    "chart": _layout_chart,
}


def build_presentation(spec: Dict[str, Any], path: str) -> str:
    """Escreve a apresentação descrita por ``spec`` em ``path`` (.odp).

    Levanta ``SlideSpecError`` se a spec não tiver slides utilizáveis ou se
    o odfpy não estiver instalado — o chamador então preserva o bloco
    original na resposta em vez de mostrar link para um arquivo vazio.
    Um slide com problema não derruba os outros: ele é pulado (com log).
    """
    if not ODP_BACKEND:
        raise SlideSpecError("odfpy não instalado")
    title, theme, slides = parse_spec(spec)
    builder = _Builder(title, theme)
    for slide in slides:
        pages_before = list(builder.doc.presentation.childNodes)
        count_before = builder._page_count
        try:
            _LAYOUT_BUILDERS[slide["layout"]](builder, slide)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Slide ignorado (%s)", slide.get("layout"))
            # Tira as páginas que o layout chegou a criar antes de falhar,
            # para não sobrar um slide pela metade.
            for node in list(builder.doc.presentation.childNodes):
                if node not in pages_before:
                    builder.doc.presentation.removeChild(node)
            builder._page_count = count_before
    if builder._page_count == 0:
        raise SlideSpecError("nenhum slide pôde ser gerado")
    builder.save(path)
    return path
