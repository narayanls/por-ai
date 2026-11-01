"""
Tradução da interface (gettext).

Os textos do código-fonte estão em português do Brasil, que é o idioma de
origem: com o sistema em português, nenhuma tradução é carregada. Para os
demais idiomas, os catálogos ficam em

    <prefixo>/share/locale/<idioma>/LC_MESSAGES/por-ai.mo

(/usr/share/locale no pacote nativo, /app/share/locale no Flatpak). Os
fontes .po ficam na pasta po/ do repositório.

Escolha do idioma:
  - POR_AI_LANG=en|es|pt força um idioma (útil para testar);
  - senão, segue LANGUAGE / LC_ALL / LC_MESSAGES / LANG, como o gettext;
  - idiomas sem tradução caem para o inglês, não para o português.

Este módulo se configura sozinho na primeira importação, então qualquer
``_()`` chamado em nível de módulo (constantes, dicionários de opções) já
sai traduzido — basta que nada chame ``_()`` antes de importar daqui.
"""

from __future__ import annotations

import gettext
import locale
import os
from typing import List, Optional

DOMAIN = "por-ai"

# Idioma em que o código-fonte está escrito.
SOURCE_LANGUAGE = "pt"
# Idiomas com catálogo .po no repositório.
AVAILABLE_LANGUAGES = ("en", "es")
# Para quem usa um idioma sem tradução.
FALLBACK_LANGUAGE = "en"

# Este arquivo está em <prefixo>/share/por-ai/core/i18n.py.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCALE_DIRS = (
    os.environ.get("POR_AI_LOCALEDIR", ""),
    # <prefixo>/share/locale — vale para /usr, /app e para o repositório
    # (usr/share/locale, depois de rodar po/build-mo.sh).
    os.path.normpath(os.path.join(_APP_DIR, "..", "locale")),
)


def _requested_languages() -> List[str]:
    """Idiomas pedidos pelo ambiente, na ordem de preferência."""
    forced = os.environ.get("POR_AI_LANG", "").strip()
    if forced:
        return [forced]
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "").strip()
        if value:
            return [v for v in value.split(":") if v]
    return []


def _base(lang: str) -> str:
    """'es_AR.UTF-8' -> 'es'; 'C' e 'POSIX' -> ''."""
    code = lang.split(".")[0].split("@")[0].split("_")[0].lower()
    return "" if code in ("c", "posix") else code


def resolve_language() -> str:
    """Idioma efetivo da interface: 'pt', 'en' ou 'es'."""
    for lang in _requested_languages():
        code = _base(lang)
        if code == SOURCE_LANGUAGE or code in AVAILABLE_LANGUAGES:
            return code
    return FALLBACK_LANGUAGE


def _find_localedir(lang: str) -> Optional[str]:
    for directory in _LOCALE_DIRS:
        if directory and os.path.isfile(
            os.path.join(directory, lang, "LC_MESSAGES", DOMAIN + ".mo")
        ):
            return directory
    return None


def _load() -> gettext.NullTranslations:
    try:
        # Datas, números e textos internos do GTK no idioma do sistema.
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass

    lang = resolve_language()
    if lang == SOURCE_LANGUAGE:
        return gettext.NullTranslations()
    localedir = _find_localedir(lang)
    if localedir is None:
        # Catálogo ausente (ex.: rodando do repositório sem compilar os .mo):
        # mostra o texto original em vez de quebrar.
        return gettext.NullTranslations()
    return gettext.translation(DOMAIN, localedir, languages=[lang], fallback=True)


_translation = _load()
LANGUAGE = resolve_language()


def _(message: str) -> str:
    """Traduz ``message`` para o idioma da interface."""
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Escolhe singular/plural conforme ``n`` e traduz."""
    return _translation.ngettext(singular, plural, n)


def pgettext(context: str, message: str) -> str:
    """Tradução com contexto, para palavras ambíguas fora de contexto."""
    return _translation.pgettext(context, message)


def N_(message: str) -> str:
    """Marca o texto para extração sem traduzir agora (traduza no uso)."""
    return message


def spellcheck_language() -> str:
    """Dicionário do corretor ortográfico que combina com a interface.

    Usa a variante regional do sistema quando ela é do mesmo idioma
    (es_AR, en_GB…); senão, a variante mais comum. Português continua
    sendo pt_BR, como antes da tradução.
    """
    if LANGUAGE == SOURCE_LANGUAGE:
        return "pt_BR"
    for lang in _requested_languages():
        code = lang.split(".")[0].split("@")[0]
        if _base(code) == LANGUAGE and "_" in code:
            return code
    return {"en": "en_US", "es": "es_ES"}.get(LANGUAGE, "en_US")
