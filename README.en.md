<div align="center">

<img src="https://raw.githubusercontent.com/narayanls/por-ai/main/usr/share/icons/hicolor/scalable/apps/por-ai.svg" width="96" height="96" alt="POR.ai icon"/>

# POR.ai

**Personal Own Router AI**

[Português](README.md) | **English**

Chat with AI models through [OpenRouter](https://openrouter.ai) and [Maritaca AI](https://www.maritaca.ai), running locally on your Linux machine while using the speed and power of the models' servers.  
Built with Python + GTK4/Adwaita.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![GTK4](https://img.shields.io/badge/GTK-4-green?logo=gnome&logoColor=white)](https://gtk.org)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-API-purple)](https://openrouter.ai)
[![Maritaca AI](https://img.shields.io/badge/Maritaca-API-orange)](https://www.maritaca.ai)
[![Downloads](https://img.shields.io/github/downloads/narayanls/por-ai/total?label=downloads&color=brightgreen)](https://github.com/narayanls/por-ai/releases)

</div>
<div align="center">
<img width="751" height="827" alt="satty-20261005-130107" src="https://github.com/user-attachments/assets/5acc6ff9-907b-499c-99dd-5807d9990cf5" />
</div>

---
## Disclaimer
I made this app for personal use with the help of AI. However, since I believe all knowledge is more interesting when shared, I decided to create this GitHub repository under the GPL-3.0 license. So feel free to rewrite all the code without AI assistance, if you prefer, or to add any other feature you find useful.


## Don't forget

You need at least one API key to use this app. You can use either one, or both at the same time:

- **OpenRouter** — visit the website by clicking [here.](https://openrouter.ai) There are **PAID** and free models; most of them are paid. Add credit on the OpenRouter website or search for free models.
- **Maritaca AI** — a Brazilian company, creator of the **Sabiá** models, trained with a focus on Portuguese. Create your key on the [Maritaca platform](https://plataforma.maritaca.ai). The models are **paid**, priced in Brazilian reais; see the [pricing table](https://docs.maritaca.ai/pt/precos).

## 🚀 First use

1. Open **Menu ▸ Preferences** and **paste your API key**:
   - in the **OpenRouter** tab, the [OpenRouter](https://openrouter.ai/keys) key;
   - in the **Maritaca** tab, the [Maritaca AI](https://plataforma.maritaca.ai) key.
2. Choose which OpenRouter providers may receive your messages: **All**, **No training** or **Zero retention** (you can change this later in Preferences; see [About privacy](#-about-privacy))
3. Load the models: **Update now**, or **Leave automatic** to let the app keep the list up to date on its own. Later, **Menu ▸ Update models** fetches the full catalog at any time (it updates both providers)
4. Click the model selector in the header and choose the model you want. Maritaca models appear with the `maritaca/` prefix
5. **Enter** sends the message — **Shift+Enter** inserts a line break

Steps 2 and 3 appear as popovers right after you confirm the key.

<div align="left">
<img width="398" height="238" alt="satty-20261018-192109" src="https://github.com/user-attachments/assets/bf787f38-6ac9-44bb-b3a6-a3107e056da5" />
</div>

<img width="376" height="227" alt="satty-20261018-192130" src="https://github.com/user-attachments/assets/fa951ee8-2ace-4afe-baf1-0989973f22b0" />

> **Note:** web search, the privacy filter, provider priority, reasoning effort and the $ cost in the response footer are OpenRouter features. With Maritaca models, the footer shows only the number of tokens.


## ✨ Features

- **Persistent history** — conversations saved locally in `~/.local/share/por-ai/`; rename, continue or delete them whenever you want
- **Model search** — access to the full OpenRouter catalog with substring search (e.g. typing `kimi` finds `moonshotai/kimi`)
- **Brazilian models** — with a Maritaca key, the Sabiá models (`maritaca/sabia-4`, `maritaca/sabiazinho-4`…) show up in the same selector, next to the OpenRouter models
- **Real-time streaming** — responses appear as they are written, with a button to stop them
- **Rendered Markdown** — bold, italics, code, headings.
- **Attachments** — up to 6 files per message: PDF, ODT, TXT, MD, ODS, XLSX, CSV, JSON, PY, TOML, KDL and images (PNG, JPG, WebP, SVG)
- **Multimodal** — send images as input for compatible models
  to analyze (GPT-4o, Claude, Gemini, etc.)
- **Web search with sources** — the 🌐 button next to "Send" turns on OpenRouter's web search (`openrouter:web_search`) for the next message only; the pages consulted appear numbered, with links, at the end of the response. The button turns itself off after each message, because search has an extra cost. It works with models that accept tools, e.g. Deepseek, Claude, Gemini, Qwen, Zai.
- **Clickable links** — URLs in responses are rendered as links (images and spreadsheets). Images are saved in `/home/user/.local/share/por-ai/images` and spreadsheets in `/home/user/.local/share/por-ai/spreadsheets`
- **Privacy filter** — choose whether OpenRouter may use any provider, only those that don't train on your prompts, or only zero-retention ones; in the last case, the model list shows only compatible models.
- **Automatic catalog update** — optional, once every 24 hours when the app opens
- **Native interface** — GTK4 + Adwaita, integrated with the system theme (automatic dark/light mode). You can customize it by choosing from several themes such as Dracula, Nord and Everforest.
- **Languages** — the interface is available in Portuguese, English and Spanish and follows the system language.

Theme examples:
<img width="460" height="560" alt="Imagem colada (15)" src="https://github.com/user-attachments/assets/1d1f0b1b-b544-4c7a-ba2d-9e387a2c33e1" />


---

## 📦 Installation

### Arch Linux and derivatives

Download the `.pkg.tar.zst` from the [releases page](https://github.com/narayanls/por-ai/releases/latest) and install it with:

```sh
sudo pacman -U por-ai-*.pkg.tar.zst
```

**Dependencies** (installed automatically by pacman):
`gtk4` `libadwaita` `python-gobject` `python-requests` `python-pypdf` `python-odfpy` `gtksourceview5` `libspelling` `hunspell` `hunspell-pt-br` `python-matplotlib`

---

### Debian and derivatives

Download the `.deb` from the [releases page](https://github.com/narayanls/por-ai/releases/latest) and install it by **double-clicking** the file or with:

```sh
sudo apt install ./por-ai_*.deb
```

**Dependencies** (installed automatically by apt):
`libgtk-4-1` `libadwaita-1-0` `gir1.2-gtk-4.0` `gir1.2-adw-1` `python3-gi` `python3-requests` `python3-pypdf` `python3-odf` `gir1.2-gtksource-5` `libgtksourceview-5-0` `libspelling-1-1` `gir1.2-spelling-1` `hunspell` `hunspell-pt-br` `python3-matplotlib`

> **Spell checking in English:** the spell checker follows the interface language. Install the English dictionary to use it: `hunspell-en_us` on Arch, `hunspell-en-us` on Debian/Ubuntu.

---

### Universal Flatpak package
Download the `.flatpak` from the [releases page](https://github.com/narayanls/por-ai/releases/latest) and install it with:
```sh
flatpak install --user ./por-ai*.flatpak
```

---
### Running from source

```sh
git clone https://github.com/narayanls/por-ai.git
cd por-ai
python3 usr/share/por-ai/main.py
```

---

## 🔒 About privacy

POR.ai runs on your computer, but it depends on an internet connection — no telemetry, no intermediary server of its own. Conversations are saved locally in `~/.local/share/por-ai/` and the API keys are stored in `~/.config/por-ai/config.json` (permission `0600`).

The content of your messages and attached files is sent to **OpenRouter**, which forwards it to the provider of the chosen model. Each provider has its own data policy, shown on the OpenRouter website by a shield: **green** neither retains conversations nor uses them to train AI; **yellow** may retain them but does not train on them; **red** retains and trains. In your OpenRouter account settings, or in the app itself (below), you can restrict providers that train on user data.

With **Maritaca** models, messages go straight to the Maritaca API, without going through OpenRouter. Models ending in `-br-sp` process everything within Brazilian territory.

### In the app itself

In **Preferences ▸ OpenRouter ▸ Privacy ▸ Allowed providers**, choose:

- **All** — any provider (your OpenRouter account policy still applies);
- **No training** — only providers that don't train on your prompts (yellow and green shields). The model list doesn't change; if a model has no compatible provider, the app warns you when sending;
- **Zero retention** — only providers that neither retain nor train on your prompts (green shield). The model list then shows only compatible models.

When you change this option, the app reloads the model list automatically. Web search (the 🌐 button) uses a separate search service that does not go through this filter.

<img width="635" height="367" alt="satty-20261018-192242" src="https://github.com/user-attachments/assets/96ac2208-e950-4c46-a396-b9c3f89ca81b" />



---

## 🛠️ Built with

- [Python 3](https://www.python.org) + [PyGObject](https://pygobject.gnome.org)
- [GTK4](https://gtk.org) + [Adwaita (libadwaita)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
- [OpenRouter API](https://openrouter.ai/docs)
- [Maritaca AI API](https://docs.maritaca.ai/pt/api/comeco-rapido)

- Vibe Coding:
  Claude Sonnet was used for code generation. The program was reviewed and tested by humans.
---

## 📄 License

Distributed under the [GPL-3.0](LICENSE) license.
