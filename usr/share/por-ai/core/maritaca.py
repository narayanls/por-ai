"""
Cliente da Maritaca AI (modelos Sabiá) para o POR.ai.

A API da Maritaca é compatível com a da OpenAI (``/chat/completions`` com
streaming SSE), então o cliente herda quase tudo de ``OpenRouterClient`` e só
troca a URL base, o nome do provedor e a listagem de modelos.

Para conviver com os modelos do OpenRouter no mesmo seletor, os modelos da
Maritaca recebem o prefixo ``maritaca/`` dentro do app (ex.:
``maritaca/sabia-4``). O prefixo é removido aqui, antes de cada envio, porque
a API da Maritaca espera só o nome do modelo (``sabia-4``).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)

MARITACA_BASE = "https://chat.maritaca.ai/api"
MARITACA_PREFIX = "maritaca/"

# Usados quando a API não lista os modelos (ou a listagem falha), para o
# seletor nunca ficar vazio. Nomes conforme a documentação da Maritaca.
MARITACA_FALLBACK_MODELS: List[str] = [
    "sabia-4",
    "sabiazinho-4",
]


def is_maritaca_model(model: str) -> bool:
    """True se o ID do modelo (como usado no app) for da Maritaca."""
    return isinstance(model, str) and model.strip().startswith(MARITACA_PREFIX)


def to_app_id(model: str) -> str:
    """``sabia-4`` → ``maritaca/sabia-4`` (sem duplicar o prefixo)."""
    model = (model or "").strip()
    return model if is_maritaca_model(model) else f"{MARITACA_PREFIX}{model}"


def to_api_id(model: str) -> str:
    """``maritaca/sabia-4`` → ``sabia-4`` (o nome que a API espera)."""
    model = (model or "").strip()
    return model[len(MARITACA_PREFIX):] if is_maritaca_model(model) else model


class MaritacaClient(OpenRouterClient):
    BASE_URL = MARITACA_BASE
    PROVIDER_NAME = "Maritaca"
    MODELS_PATH = "/models"
    MISSING_KEY_MESSAGE = "Configure a chave da API da Maritaca em Preferências."

    def __init__(self, api_key: str, timeout: int = 240) -> None:
        # site_url/site_name são cabeçalhos de estatística do OpenRouter;
        # não fazem sentido aqui.
        super().__init__(api_key=api_key, timeout=timeout)

    def _extra_payload(self) -> Dict[str, Any]:
        # ``usage.include`` é exclusivo do OpenRouter.
        return {}

    # ------------------------------------------------------------------ #
    # Catálogo de modelos                                                  #
    # ------------------------------------------------------------------ #

    def list_models(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """Modelos da Maritaca no formato do catálogo do app (``id`` já com
        o prefixo ``maritaca/``). Se a API não listar nada, devolve a lista
        fixa ``MARITACA_FALLBACK_MODELS``; erros de chave (401/403) sobem
        normalmente para o usuário ver."""
        try:
            raw = self._get_data_list(self.MODELS_PATH, timeout)
        except OpenRouterError as exc:
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                raise
            logger.warning("Maritaca: falha ao listar modelos (%s); usando lista fixa.", exc)
            raw = []

        models: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            api_id = entry.get("id")
            if not isinstance(api_id, str) or not api_id.strip():
                continue
            app_id = to_app_id(api_id)
            if app_id in seen:
                continue
            seen.add(app_id)
            item = dict(entry)
            item["id"] = app_id
            item.setdefault("name", f"Maritaca: {api_id.strip()}")
            models.append(item)

        if not models:
            models = [
                {"id": to_app_id(name), "name": f"Maritaca: {name}"}
                for name in MARITACA_FALLBACK_MODELS
            ]
        return models

    def list_zdr_model_ids(self, timeout: Optional[float] = None) -> Set[str]:
        # O filtro de retenção zero (ZDR) é um recurso do OpenRouter. A
        # Maritaca é um provedor direto, então nenhum modelo é filtrado aqui.
        return {model["id"] for model in self.list_models(timeout)}

    # ------------------------------------------------------------------ #
    # Completagem                                                          #
    # ------------------------------------------------------------------ #

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **params: Any,
    ) -> Tuple[str, List[str], Optional[Dict[str, Any]], str]:
        return super().chat(to_api_id(model), messages, **params)

    def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        on_delta: Callable[[str], None],
        should_cancel: Optional[Callable[[], bool]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        **params: Any,
    ) -> Tuple[str, List[str], Optional[Dict[str, Any]], str]:
        return super().stream_chat(
            to_api_id(model),
            messages,
            on_delta,
            should_cancel=should_cancel,
            on_reasoning=on_reasoning,
            **params,
        )
