"""
Armazenamento de conversas do POR.ai.

Cada conversa é um arquivo JSON em
``~/.local/share/por-ai/conversations/<id>.json`` (caminho XDG de dados).

Estrutura de uma conversa::

    {
      "id": "…",
      "title": "…",
      "created_at": 1719250000.0,
      "updated_at": 1719250500.0,
      "model": "openrouter/auto",
      "messages": [
        {"role": "user", "content": "<enviado à API>", "display": "<mostrado>"},
        {"role": "assistant", "content": "…", "display": "…"}
      ]
    }

Para mensagens do usuário, ``content`` pode conter o texto dos arquivos
anexados, enquanto ``display`` mostra apenas o texto digitado + os nomes dos
anexos. Para o assistente, ``content`` e ``display`` são iguais.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from gi.repository import GLib

logger = logging.getLogger(__name__)


class ConversationStore:
    def __init__(self) -> None:
        self._dir = os.path.join(
            GLib.get_user_data_dir(), "por-ai", "conversations"
        )
        try:
            os.makedirs(self._dir, exist_ok=True)
        except OSError as exc:
            logger.error("Falha ao criar pasta de conversas: %s", exc)

    # ------------------------------------------------------------------ #
    # Utilidades                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def _path(self, conv_id: str) -> str:
        # Evita travessia de diretório: usa só o basename.
        safe = os.path.basename(conv_id)
        return os.path.join(self._dir, f"{safe}.json")

    # ------------------------------------------------------------------ #
    # Listagem / leitura / escrita / remoção                               #
    # ------------------------------------------------------------------ #

    def list_meta(self) -> List[Dict[str, Any]]:
        """Lista metadados das conversas (sem as mensagens), mais recentes primeiro."""
        metas: List[Dict[str, Any]] = []
        try:
            entries = os.listdir(self._dir)
        except OSError:
            return metas

        for name in entries:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._dir, name), "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (ValueError, OSError):
                continue
            if not isinstance(data, dict) or "id" not in data:
                continue
            metas.append(
                {
                    "id": data.get("id"),
                    "title": data.get("title") or "Conversa",
                    "created_at": float(data.get("created_at", 0) or 0),
                    "updated_at": float(data.get("updated_at", 0) or 0),
                    "model": data.get("model", ""),
                }
            )

        metas.sort(key=lambda m: m["updated_at"], reverse=True)
        return metas

    def load(self, conv_id: str) -> Optional[Dict[str, Any]]:
        try:
            with open(self._path(conv_id), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (ValueError, OSError):
            logger.warning("Falha ao carregar conversa %s", conv_id)
        return None

    def save(self, conversation: Dict[str, Any]) -> None:
        conv_id = conversation.get("id")
        if not conv_id:
            return
        conversation["updated_at"] = time.time()
        path = self._path(conv_id)
        try:
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(conversation, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            logger.error("Falha ao salvar conversa %s: %s", conv_id, exc)

    def delete(self, conv_id: str) -> None:
        try:
            os.remove(self._path(conv_id))
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.error("Falha ao remover conversa %s: %s", conv_id, exc)
