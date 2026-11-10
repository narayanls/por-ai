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
from core.i18n import _

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
                    "title": data.get("title") or _("Conversa"),
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

    # ------------------------------------------------------------------ #
    # Exportação / importação                                              #
    # ------------------------------------------------------------------ #

    # Marca gravada no arquivo exportado. A importação também aceita os
    # arquivos crus da pasta de conversas (sem essa marca).
    EXPORT_FORMAT = "por-ai-conversation"
    EXPORT_VERSION = 1

    _VALID_ROLES = ("user", "assistant", "system")

    def export_to_file(self, conversation: Dict[str, Any], path: str) -> None:
        """Grava ``conversation`` como JSON em ``path``.

        Lança ``OSError`` se não conseguir escrever o arquivo.
        """
        data = {
            "format": self.EXPORT_FORMAT,
            "version": self.EXPORT_VERSION,
            "exported_at": time.time(),
            "conversation": {
                "id": conversation.get("id"),
                "title": conversation.get("title") or _("Conversa"),
                "created_at": conversation.get("created_at"),
                "updated_at": conversation.get("updated_at"),
                "model": conversation.get("model", ""),
                "messages": conversation.get("messages", []),
            },
        }
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def _clean_message(cls, raw: Any) -> Optional[Dict[str, Any]]:
        """Valida uma mensagem importada; devolve ``None`` se for inválida."""
        if not isinstance(raw, dict):
            return None
        role = raw.get("role")
        content = raw.get("content")
        if role not in cls._VALID_ROLES:
            return None
        # O conteúdo pode ser texto ou uma lista de partes (texto + imagens).
        if not isinstance(content, (str, list)):
            return None
        display = raw.get("display")
        if not isinstance(display, str):
            display = content if isinstance(content, str) else ""
        message: Dict[str, Any] = {
            "role": role,
            "content": content,
            "display": display,
        }
        for key in ("tokens", "cost", "sources", "web_searches", "cached_tokens"):
            if raw.get(key) is not None:
                message[key] = raw[key]
        return message

    def import_from_file(self, path: str) -> Dict[str, Any]:
        """Lê uma conversa exportada e salva como uma conversa nova.

        Sempre gera um ``id`` novo, para nunca sobrescrever uma conversa
        existente (importar o mesmo arquivo duas vezes cria duas cópias).
        Devolve a conversa salva. Lança ``ValueError`` se o arquivo não for
        uma conversa válida e ``OSError`` se não puder ser lido.
        """
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except ValueError as exc:
                raise ValueError(_("O arquivo não é um JSON válido.")) from exc

        if isinstance(data, dict) and data.get("format") == self.EXPORT_FORMAT:
            data = data.get("conversation")
        if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
            raise ValueError(_("O arquivo não contém uma conversa do POR.ai."))

        messages = [
            m for m in (self._clean_message(raw) for raw in data["messages"]) if m
        ]
        if not messages:
            raise ValueError(_("A conversa importada não tem mensagens."))

        try:
            created_at = float(data.get("created_at") or 0) or time.time()
        except (TypeError, ValueError):
            created_at = time.time()

        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            title = _("Conversa importada")

        model = data.get("model")
        conversation: Dict[str, Any] = {
            "id": self.new_id(),
            "title": title.strip()[:200],
            "created_at": created_at,
            "updated_at": time.time(),
            "model": model if isinstance(model, str) else "",
            "messages": messages,
        }
        self.save(conversation)
        return conversation
