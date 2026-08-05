"""
Conversão de Markdown para Pango markup.

Cobre os elementos mais comuns que modelos de IA retornam:
  * Links [texto](url) e URLs nuas → <a href="...">...</a>  (clicáveis)
  * **negrito** / __negrito__      → <b>...</b>
  * *itálico* / _itálico_         → <i>...</i>
  * `código inline`               → <tt>...</tt>
  * ```bloco de código```         → <tt> com fundo diferente
  * # Títulos (H1–H3)             → <big><b> / <b> / <i>
  * Listas - item / * item        → • item
  * Linhas horizontais ---        → linha de traços

O Pango markup é um subconjunto de XML, então os caracteres
especiais do texto puro (<, >, &) são escapados antes de aplicar
as tags, para não quebrar a renderização.

ORDEM DE PROCESSAMENTO
----------------------
Blocos de código, código inline e links são extraídos para placeholders
ANTES de qualquer regra de inline. Isso é obrigatório para os links: o
href de um arquivo local (file:///home/joao_silva/...) contém `_` e `-`
com frequência, e se as regras de negrito/itálico rodassem sobre ele o
resultado seria um href com tags Pango dentro — markup inválido que o
Gtk.Label rejeita silenciosamente.

Listas são convertidas antes do itálico, senão "* item" é lido como
abertura de itálico e a linha inteira é destruída.
"""

from __future__ import annotations

import re

# ── Pré-compilação das expressões regulares ──────────────────────────────────

# Blocos de código (``` ... ```)  — processado antes dos inlines.
_RE_CODE_BLOCK = re.compile(
    r"```(?:[^\n]*)?\n(.*?)```",
    re.DOTALL,
)

# Código inline: `código`
_RE_CODE_INLINE = re.compile(r"`([^`\n]+)`")

# Links Markdown: [texto](url) — inclui file:// para arquivos gerados
# localmente pelo assistant.py (imagens e planilhas).
_RE_LINK = re.compile(r"\[([^\]\n]+)\]\(((?:https?|file)://[^\)\s]+)\)")

# URLs nuas: http://, https:// ou file:// soltas no texto.
_RE_URL_BARE = re.compile(r"((?:https?|file)://[^\s\)<>\"]+)")

# Título H1 (# Texto)
_RE_H1 = re.compile(r"^#{1}\s+(.+)$", re.MULTILINE)
# Título H2 (## Texto)
_RE_H2 = re.compile(r"^#{2}\s+(.+)$", re.MULTILINE)
# Título H3 (### Texto)
_RE_H3 = re.compile(r"^#{3,}\s+(.+)$", re.MULTILINE)

# Listas: linhas que começam com - ou * seguidos de espaço.
_RE_LIST = re.compile(r"^[ \t]*[\-\*][ \t]+(.+)$", re.MULTILINE)

# Linha horizontal: --- ou *** sozinhos na linha.
_RE_HR = re.compile(r"^(\-{3,}|\*{3,})$", re.MULTILINE)

# Negrito: **texto** ou __texto__ (sem DOTALL: não atravessa parágrafos).
_RE_BOLD = re.compile(
    r"\*\*(?!\s)([^\n]+?)(?<!\s)\*\*"
    r"|(?<![\w_])__(?!\s)([^\n]+?)(?<!\s)__(?![\w_])"
)

# Itálico: *texto* ou _texto_.
#   (?<![\w*]) / (?![\w*])  → não dispara no meio de snake_case nem em
#                             restos de ** que sobraram do negrito
#   (?!\s) / (?<!\s)        → "* item" de lista não abre itálico
#   [^*\n] / [^_\n]         → não atravessa linhas
_RE_ITALIC = re.compile(
    r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])"
    r"|(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])"
)


# ── Placeholders ─────────────────────────────────────────────────────────────
# Protegem trechos que não podem sofrer as regras de inline. O \x00 não
# aparece em texto vindo do modelo e sobrevive ao _escape().

_PH_CODE = "\x00CODE\x00"
_PH_ICODE = "\x00ICODE\x00"
_PH_LINK = "\x00LINK\x00"


def md_to_pango(text: str) -> str:
    """
    Converte texto com Markdown básico para Pango markup.

    O resultado é adequado para ``Gtk.Label.set_markup()``.
    """
    if not text:
        return ""

    # 1) Blocos de código → placeholder.
    code_blocks: list[str] = []

    def _save_code_block(match: re.Match) -> str:
        escaped = _escape(match.group(1).rstrip())
        code_blocks.append(f"<tt><small>{escaped}</small></tt>")
        return f"{_PH_CODE}{len(code_blocks) - 1}\x00"

    text = _RE_CODE_BLOCK.sub(_save_code_block, text)

    # 2) Código inline → placeholder. Evita que `*`, `_` dentro de nomes de
    # variáveis (wrap_text, __init__, 2**32) virem negrito/itálico.
    inline_codes: list[str] = []

    def _save_inline_code(match: re.Match) -> str:
        inline_codes.append(f"<tt>{_escape(match.group(1))}</tt>")
        return f"{_PH_ICODE}{len(inline_codes) - 1}\x00"

    text = _RE_CODE_INLINE.sub(_save_inline_code, text)

    # 3) Links → placeholder. Precisa vir antes de negrito/itálico, senão
    # um `_` no caminho do arquivo injeta <i> dentro do href.
    links: list[str] = []

    def _save_link(label: str, url: str) -> str:
        anchor = f'<a href="{_escape(url)}">{_escape(label)}</a>'
        links.append(anchor)
        return f"{_PH_LINK}{len(links) - 1}\x00"

    text = _RE_LINK.sub(lambda m: _save_link(m.group(1), m.group(2)), text)
    # 3b) URLs nuas (as de dentro de [](...) já saíram no passo anterior).
    text = _RE_URL_BARE.sub(lambda m: _save_link(m.group(1), m.group(1)), text)

    # 4) Escapa os caracteres especiais do XML no texto restante.
    text = _escape(text)

    # 5) Títulos (H3 antes de H2 antes de H1 para não conflitar).
    text = _RE_H3.sub(lambda m: f"<i><b>{m.group(1)}</b></i>", text)
    text = _RE_H2.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _RE_H1.sub(lambda m: f"<big><b>{m.group(1)}</b></big>", text)

    # 6) Linha horizontal antes da lista: "***" sozinho não é bullet.
    text = _RE_HR.sub("──────────────────────", text)

    # 7) Listas — ANTES do itálico, senão "* item" abre um <i>.
    text = _RE_LIST.sub(lambda m: f"• {m.group(1)}", text)

    # 8) Negrito (antes do itálico para não confundir ** com *).
    text = _RE_BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)

    # 9) Itálico.
    text = _RE_ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)

    # 10) Restaura os placeholders (ordem inversa da extração).
    for i, anchor in enumerate(links):
        text = text.replace(f"{_PH_LINK}{i}\x00", anchor)
    for i, block in enumerate(inline_codes):
        text = text.replace(f"{_PH_ICODE}{i}\x00", block)
    for i, block in enumerate(code_blocks):
        text = text.replace(f"{_PH_CODE}{i}\x00", block)

    return text


def escape_plain(text: str) -> str:
    """Escapa texto puro para uso seguro como Pango markup (sem formatação).

    Usado como rede de segurança quando ``md_to_pango`` produz markup
    inválido (ex.: tags que ficam desbalanceadas momentaneamente durante o
    streaming) — garante que o texto continue aparecendo por inteiro, só
    que sem negrito/itálico/código, em vez do label travar sem atualizar.
    """
    return _escape(text)


def _escape(text: str) -> str:
    """Escapa &, < e > para uso em Pango markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")