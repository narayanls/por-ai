"""
Arquivos completos gerados pelo modelo (scripts, páginas, configs).

Quando o modelo entrega um arquivo inteiro, ele marca o bloco com o nome:

    ```python arquivo=html_gen.py
    ...conteúdo completo...
    ```

O app grava o conteúdo em ``~/.local/share/por-ai/files/<id>/html_gen.py``
e troca o bloco por um link. Todos os arquivos de uma mesma resposta vão
para a mesma pasta ``<id>``: uma página dividida em index.html, style.css
e script.js continua funcionando, porque as referências relativas entre
eles batem. Cada resposta ganha uma pasta nova, então pedir ajustes nunca
sobrescreve a versão anterior. O arquivo já sai com o nome certo, e a pessoa
não precisa copiar da bolha (o que levava junto a cerca e o texto em
volta) nem renderizar centenas de linhas de código no rótulo.

Blocos SEM ``arquivo=`` continuam como código na bolha: trechos, exemplos
curtos e comandos de terminal são para ler, não para baixar.

Duas proteções, porque o conteúdo vem de um LLM:

* Resposta cortada pelo limite de tokens (``finish_reason == "length"``)
  com o bloco ainda aberto: o arquivo estaria pela metade, então não é
  gravado — o bloco fica cru e o ChatAssistant mostra o aviso de corte.
* Trechos omitidos ("# ... resto do código igual ..."): o arquivo é
  gravado, mas o link vem com um aviso apontando a linha, porque um
  arquivo com buraco no meio quebra sem dar pista de onde.

Só biblioteca padrão: nenhuma dependência.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Callable, List, Optional, Tuple

from core.i18n import _, ngettext

logger = logging.getLogger(__name__)


def capabilities_prompt() -> str:
    """Texto acrescentado ao system prompt (ver ChatAssistant._inject_capabilities)."""
    return "\n".join([
        "Ao entregar um ARQUIVO COMPLETO (um script ou arquivo novo, ou a "
        "versão inteira de um arquivo anexado quando o usuário pedir o "
        "arquivo todo ou quando a alteração mudar boa parte dele), "
        "acrescente o nome do arquivo na linha de abertura da cerca, depois "
        "da linguagem: ```python arquivo=html_gen.py",
        "O conteúdo desse bloco é gravado exatamente como está e entregue ao "
        "usuário como link de download. Por isso, num bloco com arquivo=, "
        "escreva o arquivo inteiro, do início ao fim: NUNCA abrevie com "
        "'...', '# resto do código igual', '// código existente' ou "
        "parecidos. Se o arquivo for grande demais para caber na resposta, "
        "diga isso ao usuário em vez de entregar um arquivo incompleto.",
        "Se o conteúdo do arquivo tiver ``` no início de alguma linha (um "
        "README com exemplos de código, por exemplo), abra e feche o bloco "
        "com quatro crases: ````markdown arquivo=README.md ... ````.",
        "Para uma página, app ou jogo web, prefira UM arquivo .html com o "
        "CSS e o JavaScript embutidos: ele abre direto no navegador com um "
        "clique. Se precisar dividir (index.html, style.css, script.js), "
        "entregue todos na mesma resposta e referencie-os pelo nome "
        "simples (href=\"style.css\"): os arquivos de uma resposta ficam na "
        "mesma pasta.",
        "Use um nome de arquivo simples, sem pastas (html_gen.py, não "
        "core/html_gen.py). Para alterar um arquivo anexado, use o mesmo "
        "nome dele.",
        "Trechos, exemplos curtos e comandos de terminal vão em cerca "
        "normal, sem arquivo=: eles continuam visíveis na resposta.",
        "Não repita o conteúdo do arquivo fora do bloco nem explique que ele "
        "vira um link; fora do bloco, comente só o que mudou ou como usar.",
    ])


# ── Reconhecimento do bloco ──────────────────────────────────────────────────
#
# A linha de abertura aceita as variações que os modelos produzem mesmo
# instruídos a usar "arquivo=":
#
#   ```python arquivo=html_gen.py      (o formato pedido)
#   ```python file="html_gen.py"       (file, filename, nome, name, path, title)
#   ```python:html_gen.py
#   ```html_gen.py                     (só o nome, com extensão)
#
# O fechamento `(?:```|\Z)` aceita bloco sem cerca final; quem decide se um
# bloco aberto pode ser gravado é save_generated_files (ver `truncated`).

_RE_FILE_BLOCK = re.compile(
    r"^(?P<indent>[ \t]{0,3})(?P<fence>`{3,})[ \t]*(?P<info>[^\n`]*?)[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"(?P<close>^[ \t]{0,3}(?P=fence)`*[ \t]*(?=\r?\n|\Z)|\Z)",
    re.DOTALL | re.MULTILINE,
)
# As cercas só valem no início da linha (com até 3 espaços, como no
# Markdown), e a de fechamento precisa ter pelo menos as crases da
# abertura. Assim um ```html DENTRO de uma string do script — comum em
# código que monta prompts, como o próprio slide_gen.py — não fecha o
# bloco no meio. Para conteúdo com ``` no início de linha (um README com
# exemplos), o prompt pede cerca de quatro crases.
_RE_NAME_ATTR = re.compile(
    r"""(?:^|\s)(?:arquivo|file|filename|nome|name|path|title)\s*[=:]\s*
        (?:"(?P<q1>[^"]+)"|'(?P<q2>[^']+)'|(?P<bare>\S+))""",
    re.IGNORECASE | re.VERBOSE,
)
_RE_LANG_COLON_NAME = re.compile(r"^[\w+#-]+:(?P<name>[^\s:]+\.\w+)$")
_RE_BARE_NAME = re.compile(r"^(?P<name>[\w.-]+\.[A-Za-z0-9]{1,8})$")

_RE_SAFE_NAME = re.compile(r"[^\w.\-+@ ]", re.UNICODE)
_MAX_NAME = 80

# Extensão a usar quando o nome vem sem ela ("arquivo=Makefile" fica como
# está; "arquivo=gerador" com ```python vira gerador.py).
_LANG_EXT = {
    "python": ".py", "py": ".py", "html": ".html", "css": ".css",
    "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts",
    "json": ".json", "toml": ".toml", "yaml": ".yaml", "yml": ".yaml",
    "bash": ".sh", "sh": ".sh", "shell": ".sh", "zsh": ".sh", "fish": ".fish",
    "lua": ".lua", "markdown": ".md", "md": ".md", "xml": ".xml",
    "svg": ".svg", "sql": ".sql", "rust": ".rs", "go": ".go", "c": ".c",
    "cpp": ".cpp", "java": ".java", "kdl": ".kdl", "ini": ".ini",
    "csv": ".csv", "txt": ".txt", "text": ".txt",
}
_NO_EXT_OK = {"makefile", "dockerfile", "pkgbuild", "license", "readme",
              "containerfile", "justfile", "procfile"}


def _split_info(info: str) -> Tuple[str, Optional[str]]:
    """Separa a linha de abertura em (linguagem, nome do arquivo ou None)."""
    info = info.strip()
    if not info:
        return "", None
    attr = _RE_NAME_ATTR.search(info)
    if attr:
        name = attr.group("q1") or attr.group("q2") or attr.group("bare")
        lang = info[:attr.start()].strip().split()[0] if info[:attr.start()].strip() else ""
        return lang.lower(), name
    colon = _RE_LANG_COLON_NAME.match(info)
    if colon:
        return info.split(":", 1)[0].lower(), colon.group("name")
    bare = _RE_BARE_NAME.match(info)
    if bare:
        return "", bare.group("name")
    return info.split()[0].lower(), None


def safe_filename(name: str, lang: str = "") -> Optional[str]:
    """Nome seguro para gravar: só o último componente do caminho, sem
    caracteres estranhos, com extensão. None se não sobrar nada usável.

    O nome vem do modelo: "../../.bashrc" não pode virar um arquivo fora
    da pasta do app, e um nome oculto (".env") vira "env" visível.
    """
    name = name.strip().strip("`'\"").replace("\\", "/")
    name = name.rsplit("/", 1)[-1]
    dotfile = name.startswith(".")  # .bashrc, .env: não inventar extensão
    name = _RE_SAFE_NAME.sub("_", name).strip(" .")
    if not name or name in {".", ".."}:
        return None
    if len(name) > _MAX_NAME:
        stem, ext = os.path.splitext(name)
        name = stem[:_MAX_NAME - len(ext)] + ext
    if "." not in name and not dotfile and name.lower() not in _NO_EXT_OK:
        name += _LANG_EXT.get(lang, ".txt")
    return name


# ── Trechos omitidos ─────────────────────────────────────────────────────────
#
# Só linhas de COMENTÁRIO contam (mais uma linha que é só reticências, fora
# de Python): um "..." dentro de string, docstring ou f"{a}..." é código
# legítimo, e em Python ``...`` sozinho é o Ellipsis dos stubs.

_RE_COMMENT = re.compile(r"^\s*(?:#|//|/\*|<!--|--|;|\*)\s*(?P<text>.*)$")
_RE_ELLIPSIS = re.compile(r"\.\.\.|…")
_RE_OMISSION_WORD = re.compile(
    r"\b(?:resto|restante|demais|mesm[oa]s?|igua(?:l|is)|inalterad\w*|"
    r"sem altera\w*|n[ãa]o mud\w*|mant[eéi]\w*|continua\w*|existente|"
    r"anterior(?:es)?|omitid\w*|rest|remaining|unchanged|existing|same|"
    r"previous|omitted)\b",
    re.IGNORECASE,
)
_RE_CODE_WORD = re.compile(r"\b(?:c[óo]digo|code|implementa\w*|fun[çc][õo]es|functions?|m[ée]todos?|methods?)\b",
                           re.IGNORECASE)


def find_omission(content: str, lang: str = "") -> Optional[int]:
    """Número (1-based) da primeira linha que parece um trecho omitido."""
    bare_ellipsis_ok = lang in ("python", "py")
    for number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped in ("...", "…") and not bare_ellipsis_ok:
            return number
        comment = _RE_COMMENT.match(line)
        if not comment:
            continue
        text = comment.group("text")
        if len(text) > 90:
            continue  # comentário longo é explicação, não marcador
        has_ellipsis = bool(_RE_ELLIPSIS.search(text))
        has_word = bool(_RE_OMISSION_WORD.search(text))
        if text.startswith(("...", "…")) or (has_ellipsis and has_word):
            return number
        if has_word and _RE_CODE_WORD.search(text):
            return number
    return None


# ── Gravação ─────────────────────────────────────────────────────────────────

def files_dir(user_data_dir: str) -> Optional[str]:
    path = os.path.join(user_data_dir, "por-ai", "files")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        logger.warning("Não foi possível criar %s: %s", path, exc)
        return None
    return path


def save_generated_files(
    text: str,
    user_data_dir: str,
    to_uri: Callable[[str], str],
    truncated: bool = False,
) -> str:
    """Troca cada bloco com nome de arquivo por um link para o arquivo gravado.

    ``truncated``: a resposta foi cortada pelo limite de tokens. Um bloco
    sem cerca de fechamento, nesse caso, é um arquivo pela metade e fica
    cru. Sem corte, um bloco aberto no fim da resposta é só o modelo que
    esqueceu de fechar a cerca — esse é gravado.

    Blocos sem nome, e blocos que não puderem ser gravados, ficam intactos.
    """
    if "```" not in text:
        return text
    # Pasta desta resposta, criada só se houver arquivo para gravar.
    folder: List[Optional[str]] = []
    used_names: set = set()

    def _replace(match: re.Match) -> str:
        lang, name = _split_info(match.group("info"))
        if not name:
            return match.group(0)
        if truncated and not match.group("close"):
            logger.info("Arquivo %s cortado pelo limite de tokens; não gravado", name)
            return match.group(0)
        filename = safe_filename(name, lang)
        if not filename:
            return match.group(0)
        content = match.group("body")
        if not content.strip():
            return match.group(0)
        if not content.endswith("\n"):
            content += "\n"

        if not folder:
            base = files_dir(user_data_dir)
            folder.append(os.path.join(base, uuid.uuid4().hex[:12]) if base else None)
        if folder[0] is None:
            return match.group(0)
        # Mesmo nome duas vezes na mesma resposta: a segunda vira nome-2.ext
        # em vez de sobrescrever a primeira.
        stem, ext = os.path.splitext(filename)
        counter = 2
        while filename.lower() in used_names:
            filename = f"{stem}-{counter}{ext}"
            counter += 1
        used_names.add(filename.lower())
        path = os.path.join(folder[0], filename)
        try:
            os.makedirs(folder[0], exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        except OSError as exc:
            logger.info("Falha ao gravar %s: %s", path, exc)
            return match.group(0)

        lines = content.count("\n")
        label = "📄 " + ngettext(
            "Baixar {name} ({lines} linha)", "Baixar {name} ({lines} linhas)", lines
        ).format(name=filename, lines=lines)
        link = f"[{label}]({to_uri(path)})"
        omitted = find_omission(content, lang or os.path.splitext(filename)[1].lstrip("."))
        if omitted is not None:
            link += "\n\n_⚠️ " + _(
                "A linha {line} de {name} parece um trecho omitido pelo modelo "
                "(\"...\", \"resto do código\"). Confira antes de usar ou peça "
                "o arquivo completo de novo."
            ).format(line=omitted, name=f"`{filename}`") + "_"
        return link

    return _RE_FILE_BLOCK.sub(_replace, text)


# ── Bolha durante o streaming ────────────────────────────────────────────────

_RE_GENERATED_SPEC = re.compile(r"^(?:odp|pptx|ods|xlsx)$", re.IGNORECASE)


def streaming_preview(text: str) -> str:
    """Versão da resposta parcial para exibir enquanto chega.

    Blocos que vão virar arquivo (com nome, ou ```odp/```ods/```xlsx)
    aparecem como uma linha de progresso em vez do conteúdo: redesenhar
    centenas de linhas de código ou JSON a cada pedaço deixava a janela
    lenta, e o conteúdo some de qualquer jeito quando vira link.
    """
    if "```" not in text:
        return text

    def _replace(match: re.Match) -> str:
        info = match.group("info")
        lang, name = _split_info(info)
        body = match.group("body")
        lines = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
        if name:
            label = safe_filename(name, lang) or name
            status = _("gerando {name}…") if not match.group("close") else _("salvando {name}…")
            # Nome em `código`: protege os "_" de html_gen.py do itálico.
            return "_📄 " + status.format(name=f"`{label}`") + " " + ngettext(
                "({lines} linha)", "({lines} linhas)", lines).format(lines=lines) + "_"
        if _RE_GENERATED_SPEC.match(lang or ""):
            kind = _("apresentação") if lang.lower() in ("odp", "pptx") else _("planilha")
            return "_⏳ " + _("gerando {kind}…").format(kind=kind) + "_"
        return match.group(0)

    return _RE_FILE_BLOCK.sub(_replace, text)
