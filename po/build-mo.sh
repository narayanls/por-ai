#!/bin/sh
# Compila os .po em .mo dentro de <destino>/share/locale.
#   po/build-mo.sh                 -> usr/share/locale (rodar do repositório)
#   po/build-mo.sh "$pkgdir/usr"   -> dentro do pacote (PKGBUILD)
#   po/build-mo.sh /app            -> Flatpak
# Requisito: gettext (msgfmt).
set -eu
PO_DIR="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${1:-$(cd "$PO_DIR/.." && pwd)/usr}"

for lang in $(cat "$PO_DIR/LINGUAS"); do
    dest="$PREFIX/share/locale/$lang/LC_MESSAGES"
    mkdir -p "$dest"
    msgfmt --check --output-file="$dest/por-ai.mo" "$PO_DIR/$lang.po"
    echo "  $lang -> $dest/por-ai.mo"
done
