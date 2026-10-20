<div align="center">

<img src="https://raw.githubusercontent.com/narayanls/por-ai/main/usr/share/icons/hicolor/scalable/apps/por-ai.svg" width="96" height="96" alt="POR.ai icon"/>

# POR.ai

**Personal Own Router AI**

Chat com modelos de IA via [OpenRouter](https://openrouter.ai), rodando localmente no seu Linux e usando a velocidade e potência dos servidores dos modelos.  
Construído com Python + GTK4/Adwaita.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![GTK4](https://img.shields.io/badge/GTK-4-green?logo=gnome&logoColor=white)](https://gtk.org)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-API-purple)](https://openrouter.ai)
[![Downloads](https://img.shields.io/github/downloads/narayanls/por-ai/total?label=downloads&color=brightgreen)](https://github.com/narayanls/por-ai/releases)

</div>
<div align="center">
<img width="751" height="827" alt="satty-20261005-130107" src="https://github.com/user-attachments/assets/5acc6ff9-907b-499c-99dd-5807d9990cf5" />
</div>

---
## Disclaimer
Fiz este aplicativo para uso pessoal com auxílio de IA. Porém, como acredito que todo conhecimento é mais interessante quando compartilhado, decidi criar o repositório no Github sob licença GPL-3.0. Sendo assim, fique a vontade para reescrever todo o código sem auxílio de IA, se preferir, ou adicionar qualquer outra função que lhe seja útil.


## Não se esqueça
Você precisa criar uma chave de API no site do OpenRouter para usar este aplicativo. Acesse o site clicando [aqui.](https://openrouter.ai) Existem **modelos PAGOS** e gratuitos, a maior parte é pago. Adicione saldo no site do OpenRouter ou pesquise por "free" para achar modelos grátis.

## 🚀 Primeiro uso

1. Abra o **Menu ▸ Preferências** e **cole sua chave da API** do [OpenRouter](https://openrouter.ai/keys)
2. Escolha quais provedores podem receber suas mensagens: **Todos**, **Sem treino** ou **Retenção zero** (dá para mudar depois em Preferências)
3. Carregue os modelos: **Atualizar agora**, ou **Deixar automático** para o app manter a lista atualizada sozinho
4. Clique no seletor de modelo no cabeçalho e escolha o modelo desejado
5. **Enter** envia a mensagem — **Shift+Enter** quebra linha

Os passos 2 e 3 aparecem como balões logo depois de você confirmar a chave.

<div align="left">
<img width="398" height="238" alt="satty-20261018-192109" src="https://github.com/user-attachments/assets/bf787f38-6ac9-44bb-b3a6-a3107e056da5" />
</div>

<img width="376" height="227" alt="satty-20261018-192130" src="https://github.com/user-attachments/assets/fa951ee8-2ace-4afe-baf1-0989973f22b0" />


## ✨ Funcionalidades

- **Histórico persistente** — conversas salvas localmente em `~/.local/share/por-ai/`; renomeie, continue ou exclua quando quiser
- **Busca de modelos** — acesso ao catálogo completo do OpenRouter com busca por substring (ex.: digitar `kimi` encontra `moonshotai/kimi`)
- **Streaming em tempo real** — respostas aparecem sendo escritas, com botão para interromper
- **Markdown renderizado** — negrito, itálico, código, títulos.
- **Anexos** — até 4 arquivos por mensagem: PDF, ODT, TXT, MD, ODS, XLSX, CSV, JSON, PY e imagens (PNG, JPG, WebP)
- **Multimodal** — envie imagens (PNG, JPG, WebP) como entrada para modelos
  compatíveis analisarem (GPT-4o, Claude, Gemini…)
- **Pesquisa na web com fontes** — o botão 🌐 ao lado de "Enviar" liga a pesquisa na web do OpenRouter (`openrouter:web_search`) só para a próxima mensagem; as páginas consultadas aparecem numeradas, com link, no fim da resposta. O botão desliga sozinho após cada envio, porque a pesquisa tem custo extra. Funciona com modelos que aceitam ferramentas (tools), ex. Deepseek, Claude, Gemini, Qwen, Zai.
- **Links clicáveis** — URLs nas respostas são renderizadas como links (imagens e planilhas). As imagens ficam salvas em /home/user/.local/share/por-ai/images e as planilhas em /home/user/.local/share/por-ai/spreadsheets
- **Filtro de privacidade** — escolha se o OpenRouter pode usar qualquer provedor, só os que não treinam com seus prompts, ou só os de retenção zero; neste último caso, a lista de modelos mostra apenas os compatíveis.
- **Atualização automática do catálogo** — opcional, uma vez a cada 24 horas ao abrir o app
- **Interface nativa** — GTK4 + Adwaita, integrada ao tema do sistema (modo escuro/claro automático). É possível personalizar escolhendo entre diversos temas como Dracula, Nord, Everforest.
Exemplo de temas:
<img width="460" height="560" alt="Imagem colada (15)" src="https://github.com/user-attachments/assets/1d1f0b1b-b544-4c7a-ba2d-9e387a2c33e1" />


---

## 📦 Instalação

### Arch Linux e derivados

Baixe o `.pkg.tar.zst` na [página de releases](https://github.com/narayanls/por-ai/releases/latest) e instale com:

```sh
sudo pacman -U por-ai-*.pkg.tar.zst
```

**Dependências** (instaladas automaticamente pelo pacman):
`gtk4` `libadwaita` `python-gobject` `python-requests` `python-pypdf` `python-odfpy` `gtksourceview5` `libspelling` `hunspell` `hunspell-pt-br` `python-matplotlib`

---

### Debian e derivados

Baixe o `.deb` na [página de releases](https://github.com/narayanls/por-ai/releases/latest) e instale com **duplo clique** no arquivo ou com:

```sh
sudo apt install ./por-ai_*.deb
```

**Dependências** (instaladas automaticamente pelo apt):
`libgtk-4-1` `libadwaita-1-0` `gir1.2-gtk-4.0` `gir1.2-adw-1` `python3-gi` `python3-requests` `python3-pypdf` `python3-odf` `gir1.2-gtksource-5` `libgtksourceview-5-0` `libspelling-1-1` `gir1.2-spelling-1` `hunspell` `hunspell-pt-br` `python3-matplotlib`

---

### Pacote universal Flatpak
Baixe o `.flatpak` na [página de releases](https://github.com/narayanls/por-ai/releases/latest) e instale com:
```sh
flatpak install --user ./por-ai*.flatpak
```

---
### Rodando direto do código-fonte

```sh
git clone https://github.com/narayanls/por-ai.git
cd por-ai
python3 usr/share/por-ai/main.py
```

---

## 🔒 Sobre privacidade

O POR.ai roda no seu computador, mas depende da conexão com a internet — sem telemetria, sem servidor intermediário próprio. As conversas são salvas localmente em `~/.local/share/por-ai/` e a chave da API fica em `~/.config/por-ai/config.json` (permissão `0600`).

O conteúdo das mensagens e arquivos anexados é enviado ao **OpenRouter**, que os encaminha ao provedor do modelo escolhido. Cada provedor tem sua política de dados, indicada no site do OpenRouter por um escudo: **verde** não retém as conversas nem as usa para treinar IAs; **amarelo** pode reter, mas não treina com elas; **vermelho** retém e treina.

### Pelo próprio app

Em **Preferências ▸ OpenRouter ▸ Privacidade ▸ Provedores permitidos**, escolha:

- **Todos** — qualquer provedor (a política da sua conta no OpenRouter continua valendo);
- **Sem treino** — só provedores que não treinam com seus prompts (escudos amarelo e verde). A lista de modelos não muda; se um modelo não tiver provedor compatível, o app avisa no envio;
- **Retenção zero** — só provedores que não retêm nem treinam com seus prompts (escudo verde). A lista de modelos passa a mostrar apenas os compatíveis.

Ao mudar essa opção, o app recarrega a lista de modelos automaticamente. A pesquisa na web (botão 🌐) usa um serviço de busca à parte, que não passa por esse filtro.

<img width="635" height="367" alt="satty-20261018-192242" src="https://github.com/user-attachments/assets/96ac2208-e950-4c46-a396-b9c3f89ca81b" />


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
