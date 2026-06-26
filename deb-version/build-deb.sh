#!/bin/sh
# build-deb.sh — gera o .deb do POR.ai.
# Rode na raiz do repositório (~/Github/por-ai-deb/).
# Requisito: fpm  →  sudo gem install fpm

set -eu

PKGNAME="por-ai"
VERSION="0.1.7"

# ── 1. Limpa caches de bytecode e garante permissões ────────────────────────
find usr -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find usr -type f -name '*.pyc'       -delete              2>/dev/null || true

# Grava a versão no version.txt para o updater do app.
echo "v${VERSION}" > usr/share/por-ai/version.txt

# Todos os .py ficam com 644, depois repõe +x nos dois executáveis.
find usr/share/por-ai -type f -name '*.py' | xargs chmod 644
chmod 755 usr/bin/por-ai
chmod 755 usr/share/por-ai/main.py
chmod 644 usr/share/applications/io.github.porai.PorAi.desktop
chmod 644 usr/share/icons/hicolor/scalable/apps/por-ai.svg

# ── 2. Remove .deb anterior ──────────────────────────────────────────────────
rm -f "${PKGNAME}_${VERSION}_all.deb"

# ── 3. Empacota — aponta direto para usr/ sem staging ───────────────────────
#    -C .   define o diretório raiz como o atual (~/Github/por-ai-deb/)
#    usr/   é o único caminho incluído no pacote
fpm -s dir -t deb \
    -n "$PKGNAME" \
    -v "$VERSION" \
    -a all \
    -C . \
    --description "Chat privado com modelos do OpenRouter (GTK4/Adwaita)" \
    --url "https://github.com/SEU_USUARIO/por-ai" \
    --maintainer "Seu Nome <voce@example.com>" \
    --license "GPL-3.0-or-later" \
    --category "utils" \
    --no-auto-depends \
    --after-install after-install.sh \
    --depends "python3" \
    --depends "python3-gi" \
    --depends "python3-requests" \
    --depends "python3-pypdf" \
    --depends "libgtk-4-1" \
    --depends "gir1.2-gtk-4.0" \
    --depends "libadwaita-1-0" \
    --depends "gir1.2-adw-1" \
    --depends "python3-odf" \
    usr/

echo
echo "Gerado: ${PKGNAME}_${VERSION}_all.deb"
echo "Instale: sudo apt install ./${PKGNAME}_${VERSION}_all.deb"
