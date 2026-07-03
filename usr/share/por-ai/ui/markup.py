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
"""

from __future__ import annotations

import re

# ── Pré-compilação das expressões regulares ──────────────────────────────────

# Blocos de código (``` ... ```)  — processado antes dos inlines.
_RE_CODE_BLOCK = re.compile(
    r"```(?:[^\n]*)?\n(.*?)```",
    re.DOTALL,
)

# Título H1 (# Texto)
_RE_H1 = re.compile(r"^#{1}\s+(.+)$", re.MULTILINE)
# Título H2 (## Texto)
_RE_H2 = re.compile(r"^#{2}\s+(.+)$", re.MULTILINE)
# Título H3 (### Texto)
_RE_H3 = re.compile(r"^#{3,}\s+(.+)$", re.MULTILINE)

# Negrito: **texto** ou __texto__
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)

# Itálico: *texto* ou _texto_  (não confunde com negrito, pois bold é processado antes)
_RE_ITALIC = re.compile(r"\*(.+?)\*|_(.+?)_", re.DOTALL)

# Código inline: `código`
_RE_CODE_INLINE = re.compile(r"`([^`\n]+)`")

# Links Markdown: [texto](url)
# imagens geradas, salvas localmente pelo assistant.py).
_RE_LINK = re.compile(r"\[([^\]]+)\]\(((?:https?|file)://[^\)]+)\)")

# URLs nuas: http:// ou https:// não precedidas de href=" ou de (
_RE_URL_BARE = re.compile(
    r'(?<!href=")'          # não já dentro de um atributo href
    r"(?<!\()"              # não dentro de um link Markdown [](...)
    r"(https?://[^\s\)<>\"]+)"
)

# Listas: linhas que começam com - ou * seguidos de espaço
_RE_LIST = re.compile(r"^[\-\*]\s+(.+)$", re.MULTILINE)

# Linha horizontal: --- ou *** sozinhos na linha
_RE_HR = re.compile(r"^(\-{3,}|\*{3,})$", re.MULTILINE)


# ── Placeholder para blocos de código ────────────────────────────────────────
# Usamos um placeholder durante a conversão para proteger o conteúdo do bloco
# de ser modificado pelas regras de inline (negrito, itálico etc.).

_PLACEHOLDER_PREFIX = "\x00CODE\x00"
_PLACEHOLDER_INLINE_PREFIX = "\x00ICODE\x00"


def md_to_pango(text: str) -> str:
    """
    Converte texto com Markdown básico para Pango markup.

    O resultado é adequado para ``Gtk.Label.set_markup()``.
    """
    if not text:
        return ""

    # 1) Extrai blocos de código e substitui por placeholders.
    code_blocks: list[str] = []

    def _save_code_block(match: re.Match) -> str:
        content = match.group(1)
        # Escapa o conteúdo do bloco para Pango.
        escaped = _escape(content.rstrip())
        markup = f'<tt><small>{escaped}</small></tt>'
        code_blocks.append(markup)
        return f"{_PLACEHOLDER_PREFIX}{len(code_blocks) - 1}\x00"

    text = _RE_CODE_BLOCK.sub(_save_code_block, text)

    # 1b) Extrai código inline (`código`) e protege do mesmo jeito. Isso
    # evita que `*`, `_` dentro de nomes/expressões de código (ex.:
    # wrap_text, __init__, 2**32) sejam interpretados como negrito/itálico
    # e gerem tags Pango aninhadas de forma inválida (markup quebrado).
    inline_codes: list[str] = []

    def _save_inline_code(match: re.Match) -> str:
        content = match.group(1)
        escaped = _escape(content)
        markup = f"<tt>{escaped}</tt>"
        inline_codes.append(markup)
        return f"{_PLACEHOLDER_INLINE_PREFIX}{len(inline_codes) - 1}\x00"

    text = _RE_CODE_INLINE.sub(_save_inline_code, text)

    # 2) Escapa os caracteres especiais do XML no texto restante.
    text = _escape(text)

    # 3) Títulos (H3 antes de H2 antes de H1 para não conflitar).
    text = _RE_H3.sub(lambda m: f"<i><b>{m.group(1)}</b></i>", text)
    text = _RE_H2.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _RE_H1.sub(lambda m: f"<big><b>{m.group(1)}</b></big>", text)

    # 4) Negrito (antes do itálico para não confundir ** com *).
    text = _RE_BOLD.sub(
        lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text
    )

    # 5) Itálico.
    text = _RE_ITALIC.sub(
        lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text
    )

    # 6) (código inline já foi extraído e protegido no passo 1b)

    # 7) Links Markdown [texto](url) — url já foi escapada em step 2.
    text = _RE_LINK.sub(
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text
    )

    # 8) URLs nuas (não dentro de href já existente).
    text = _RE_URL_BARE.sub(
        lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', text
    )

    # 9) Listas.
    text = _RE_LIST.sub(lambda m: f"• {m.group(1)}", text)

    # 10) Linhas horizontais.
    text = _RE_HR.sub("──────────────────────", text)

    # 11) Restaura os blocos de código.
    for i, block in enumerate(code_blocks):
        text = text.replace(f"{_PLACEHOLDER_PREFIX}{i}\x00", block)

    # 12) Restaura os trechos de código inline.
    for i, block in enumerate(inline_codes):
        text = text.replace(f"{_PLACEHOLDER_INLINE_PREFIX}{i}\x00", block)

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