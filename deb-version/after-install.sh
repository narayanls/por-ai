#!/bin/sh
# Executado pelo dpkg após instalar o por-ai.
chmod 755 /usr/bin/por-ai /usr/share/por-ai/main.py

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
