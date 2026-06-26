"""
Gerenciamento de configuração do POR.ai.

A configuração fica em ``~/.config/por-ai/config.json`` (caminho XDG) e guarda
a chave da API do OpenRouter, o modelo padrão, o prompt de sistema e algumas
preferências. O arquivo é gravado com permissão 0600 (somente o dono lê/escreve).

Observação de privacidade: a chave da API é gravada em texto plano no JSON.
Para algo mais robusto no futuro, vale guardar a chave no Secret Service
(libsecret / GNOME Keyring) em vez do arquivo. Veja a nota no README.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from typing import Any, Dict, List

from gi.repository import GLib

logger = logging.getLogger(__name__)

APP_DIRNAME = "por-ai"
CONFIG_FILENAME = "config.json"

# Prompt de sistema padrão. Pode ser alterado em Preferências.
DEFAULT_SYSTEM_PROMPT = (
    "Você é um assistente útil, direto e honesto. Responda em português do "
    "Brasil, a menos que o usuário peça outro idioma. Quando o usuário enviar "
    "um arquivo para análise, trate-o como conteúdo de autoria dele e não o "
    "reescreva sem ser solicitado."
)

# Lista inicial de modelos favoritos exibidos no seletor. O usuário pode
# atualizar a lista completa do catálogo do OpenRouter pelo menu do app.
DEFAULT_MODELS: List[str] = [
    "openrouter/auto",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3-70b-instruct",
]

DEFAULTS: Dict[str, Any] = {
    "api_key": "",
    "default_model": "openrouter/auto",
    "models": DEFAULT_MODELS,
    "site_url": "",
    "site_name": "POR.ai",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 1.0,
    "stream": True,
}


class Config:
    """Lê e grava a configuração do app em disco."""

    def __init__(self) -> None:
        self._dir = os.path.join(GLib.get_user_config_dir(), APP_DIRNAME)
        self._path = os.path.join(self._dir, CONFIG_FILENAME)
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ #
    # Leitura / escrita                                                    #
    # ------------------------------------------------------------------ #

    def load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                # Mescla com os defaults para tolerar versões antigas do arquivo.
                merged = dict(DEFAULTS)
                merged.update(stored)
                self._data = merged
        except FileNotFoundError:
            logger.info("Config inexistente; usando padrões.")
        except (ValueError, OSError) as exc:
            logger.warning("Falha ao ler config (%s); usando padrões.", exc)

    def save(self) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
            # Permissão 0600: somente o dono lê e escreve.
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            logger.error("Falha ao gravar config: %s", exc)

    # ------------------------------------------------------------------ #
    # Acesso genérico                                                      #
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    # ------------------------------------------------------------------ #
    # Acessos tipados (conveniência)                                       #
    # ------------------------------------------------------------------ #

    @property
    def api_key(self) -> str:
        return str(self.get("api_key", "")).strip()

    @api_key.setter
    def api_key(self, value: str) -> None:
        self.set("api_key", (value or "").strip())

    @property
    def default_model(self) -> str:
        return str(self.get("default_model", "")).strip() or "openrouter/auto"

    @default_model.setter
    def default_model(self, value: str) -> None:
        self.set("default_model", (value or "").strip())

    @property
    def models(self) -> List[str]:
        value = self.get("models", DEFAULT_MODELS)
        if not isinstance(value, list):
            return list(DEFAULT_MODELS)
        # Remove vazios e duplicados preservando a ordem.
        seen: Dict[str, None] = {}
        for item in value:
            item = str(item).strip()
            if item and item not in seen:
                seen[item] = None
        return list(seen.keys()) or list(DEFAULT_MODELS)

    @models.setter
    def models(self, value: List[str]) -> None:
        self.set("models", [str(v).strip() for v in value if str(v).strip()])

    @property
    def site_url(self) -> str:
        return str(self.get("site_url", "")).strip()

    @property
    def site_name(self) -> str:
        return str(self.get("site_name", "")).strip()

    @property
    def system_prompt(self) -> str:
        return str(self.get("system_prompt", DEFAULT_SYSTEM_PROMPT))

    @property
    def temperature(self) -> float:
        try:
            return float(self.get("temperature", 1.0))
        except (TypeError, ValueError):
            return 1.0

    @property
    def stream(self) -> bool:
        return bool(self.get("stream", True))

    def is_configured(self) -> bool:
        """True se há chave da API suficiente para usar o app."""
        return bool(self.api_key)
