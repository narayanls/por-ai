#!/bin/sh
# Regenera po/por-ai.pot a partir do código e atualiza os .po existentes.
# Rode na raiz do repositório depois de adicionar ou mudar textos com _().
# Requisito: gettext (xgettext, msgmerge).
set -eu
cd "$(dirname "$0")/.."

# Mantém a lista de arquivos em dia: todo .py que importa o _().
grep -rl "core.i18n import" --include='*.py' usr/share/por-ai | sort > po/POTFILES

xgettext \
    --language=Python \
    --from-code=UTF-8 \
    --keyword=_ --keyword=N_ --keyword=ngettext:1,2 --keyword=pgettext:1c,2 \
    --add-comments=TRANSLATORS \
    --package-name=por-ai \
    --msgid-bugs-address="https://github.com/narayanls/por-ai/issues" \
    --files-from=po/POTFILES \
    --output=po/por-ai.pot

for lang in $(cat po/LINGUAS); do
    if [ -f "po/$lang.po" ]; then
        msgmerge --quiet --update --backup=none "po/$lang.po" po/por-ai.pot
    else
        msginit --no-translator --locale="$lang" \
            --input=po/por-ai.pot --output-file="po/$lang.po"
    fi
done
echo "po/por-ai.pot atualizado. Traduza as entradas novas/fuzzy nos .po."
