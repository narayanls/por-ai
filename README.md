<div align="center">

<img src="https://raw.githubusercontent.com/narayanls/por-ai/main/usr/share/icons/hicolor/scalable/apps/por-ai.svg" width="96" height="96" alt="POR.ai icon"/>

# POR.ai

**Personal Own Router AI**

Chat com modelos de IA via [OpenRouter](https://openrouter.ai), rodando localmente no seu Linux.  
Construído com Python + GTK4/Adwaita.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![GTK4](https://img.shields.io/badge/GTK-4-green?logo=gnome&logoColor=white)](https://gtk.org)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-API-purple)](https://openrouter.ai)
[![Downloads](https://img.shields.io/github/downloads/narayanls/por-ai/total?label=downloads&color=brightgreen)](https://github.com/narayanls/por-ai/releases)

</div>

---
## Disclaimer
Fiz este aplicativo para uso pessoal com auxílio de IA. Porém, como acredito que todo conhecimento é mais interessante quando compartilhado, decidi criar o repositório no Github sob licença GPL-3.0. Sendo assim, fique a vontade para reescrever todo o código sem auxílio de IA, se preferir, ou adicionar qualquer outra função que lhe seja útil.

## Não se esqueça
Você precisa criar uma chave de API no site do OpenRouter para usar este aplicativo. Acesse o site clicando [aqui.](https://openrouter.ai)

## ✨ Funcionalidades

- **Histórico persistente** — conversas salvas localmente em `~/.local/share/por-ai/`; renomeie, continue ou exclua quando quiser
- **Busca de modelos** — acesso ao catálogo completo do OpenRouter com busca por substring (ex.: digitar `kimi` encontra `moonshotai/kimi`)
- **Streaming em tempo real** — respostas aparecem sendo escritas, com botão para interromper
- **Markdown renderizado** — negrito, itálico, código, títulos.
- **Anexos** — até 4 arquivos por mensagem: PDF, ODT, TXT, MD e imagens (PNG, JPG, WebP)
- **Multimodal** — envie imagens (PNG, JPG, WebP) como entrada para modelos
  compatíveis analisarem (GPT-4o, Claude, Gemini…)
- **Links clicáveis** — URLs nas respostas são renderizadas como links, incluindo imagens geradas.
- **Interface nativa** — GTK4 + Adwaita, integrada ao tema do sistema (modo escuro/claro automático)

---

## 📦 Instalação

### Arch Linux e derivados

Baixe o `.pkg.tar.zst` na [página de releases](https://github.com/narayanls/por-ai/releases/latest) e instale com:

```sh
sudo pacman -U por-ai-*.pkg.tar.zst
```

**Dependências** (instaladas automaticamente pelo pacman):
`gtk4` `libadwaita` `python-gobject` `python-requests` `python-pypdf` `python-odfpy`

---

### Debian e derivados

Baixe o `.deb` na [página de releases](https://github.com/narayanls/por-ai/releases/latest) e instale com **duplo clique** no arquivo ou com:

```sh
sudo apt install ./por-ai_*.deb
```

**Dependências** (instaladas automaticamente pelo apt):
`libgtk-4-1` `libadwaita-1-0` `gir1.2-gtk-4.0` `gir1.2-adw-1` `python3-gi` `python3-requests` `python3-pypdf` `python3-odf`

---

### Rodando direto do código-fonte

```sh
git clone https://github.com/narayanls/por-ai.git
cd por-ai
python3 usr/share/por-ai/main.py
```

---

## 🚀 Primeiro uso

1. Abra o **Menu ▸ Preferências** e **cole sua chave da API** do [OpenRouter](https://openrouter.ai/keys)
2. Clique no seletor de modelo no cabeçalho e escolha o modelo desejado
3. Use **Menu ▸ Atualizar modelos** para puxar o catálogo completo a qualquer momento
4. **Enter** envia a mensagem — **Shift+Enter** quebra linha

---

## 🔒 Sobre privacidade

O POR.ai roda no seu computador, mas depende da conexão com a internet — sem telemetria, sem servidor intermediário próprio. As conversas são salvas localmente em `~/.local/share/por-ai/` e a chave da API fica em `~/.config/por-ai/config.json` (permissão `0600`).

O conteúdo das mensagens e arquivos anexados é enviado ao **OpenRouter**, que os encaminha ao provedor do modelo escolhido. Nas configurações da sua conta OpenRouter você pode restringir provedores que treinam com dados dos usuários.

---

## 🛠️ Construído com

- [Python 3](https://www.python.org) + [PyGObject](https://pygobject.gnome.org)
- [GTK4](https://gtk.org) + [Adwaita (libadwaita)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
- [OpenRouter API](https://openrouter.ai/docs)

- Vibe Coding:
  Claude Sonnet foi usada para geração de código. O programa foi revisado e testado por humanos.
---

## 📄 Licença

Distribuído sob a licença [GPL-3.0](LICENSE).
