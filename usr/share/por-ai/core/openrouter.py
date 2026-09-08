"""
Cliente do OpenRouter para o POR.ai.

Este módulo é "puro": não importa GTK nem toca na interface. Ele só fala HTTP
com o OpenRouter usando o endpoint compatível com OpenAI
(``/api/v1/chat/completions``) e expõe:

  * :meth:`OpenRouterClient.stream_chat` — completagem em streaming (SSE);
  * :meth:`OpenRouterClient.chat`        — completagem sem streaming;
  * :meth:`OpenRouterClient.list_models` — catálogo de modelos disponíveis.

O padrão de cabeçalhos segue o recomendado pelo OpenRouter:
``Authorization: Bearer <chave>`` e, opcionalmente, ``HTTP-Referer`` (site_url)
e ``X-Title`` (site_name) para aparecer nas estatísticas da sua conta.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple


import requests

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterError(RuntimeError):
    """Erro de comunicação ou de resposta do OpenRouter.

    ``retryable`` sinaliza se faz sentido tentar de novo automaticamente:
    True para timeouts, quedas de conexão e HTTP 408/429/5xx (falhas
    transitórias); False para erros definitivos (401 chave inválida, 400
    payload malformado, 404 modelo inexistente, etc.), onde tentar de novo
    só atrasaria um erro que não vai se resolver sozinho.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        site_url: str = "",
        site_name: str = "",
        timeout: int = 240,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.site_url = (site_url or "").strip()
        self.site_name = (site_name or "").strip()
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Cabeçalhos                                                           #
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise OpenRouterError("Configure a chave da API OpenRouter em Preferências.")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name
        return headers

    # ------------------------------------------------------------------ #
    # Catálogo de modelos                                                  #
    # ------------------------------------------------------------------ #

    def list_models(self) -> List[Dict[str, Any]]:
        """Retorna a lista de modelos do OpenRouter (campo ``data``)."""
        url = f"{OPENROUTER_BASE}/models/user"
        try:
            response = requests.get(url, headers=self._headers(), timeout=self.timeout)
        except requests.Timeout as exc:
            raise OpenRouterError(
                f"Tempo de espera esgotado ao contatar OpenRouter: {exc}", retryable=True
            ) from exc
        except requests.ConnectionError as exc:
            raise OpenRouterError(
                f"Falha de conexão com OpenRouter: {exc}", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise OpenRouterError(f"Falha ao contatar OpenRouter: {exc}") from exc

        # O OpenRouter responde em UTF-8; fixamos para o requests não assumir
        # ISO-8859-1 e gerar acentuação corrompida ("Ã§" no lugar de "ç").
        response.encoding = "utf-8"

        self._raise_for_status(response)

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenRouterError("OpenRouter retornou JSON inválido.") from exc

        data = payload.get("data")
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------ #
    # Completagem sem streaming                                            #
    # ------------------------------------------------------------------ #

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **params: Any,
    ) -> Tuple[str, List[str], Optional[Dict[str, Any]], str]:
        """Retorna (texto, urls_de_imagem, usage, reasoning). ``reasoning``
        é o raciocínio interno que alguns modelos expõem separado do
        conteúdo final; vem vazio para modelos que não o expõem."""
        url = f"{OPENROUTER_BASE}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._normalise_messages(messages),
            "usage": {"include": True},
        }
        payload.update(self._clean_params(params))

        try:
            response = requests.post(
                url, headers=self._headers(), json=payload, timeout=self.timeout
            )
        except requests.Timeout as exc:
            raise OpenRouterError(
                f"Tempo de espera esgotado ao contatar OpenRouter: {exc}", retryable=True
            ) from exc
        except requests.ConnectionError as exc:
            raise OpenRouterError(
                f"Falha de conexão com OpenRouter: {exc}", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise OpenRouterError(f"Falha ao contatar OpenRouter: {exc}") from exc

        response.encoding = "utf-8"

        self._raise_for_status(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise OpenRouterError("OpenRouter retornou JSON inválido.") from exc

        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError("O provedor retornou uma resposta vazia.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        reasoning_field = message.get("reasoning") if isinstance(message, dict) else None
        image_urls = self._extract_images(
            message.get("images") if isinstance(message, dict) else None
        )
        finish_reason = choices[0].get("finish_reason") if isinstance(choices[0], dict) else None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        self._debug_log(model, finish_reason, usage)
        text = content.strip() if isinstance(content, str) else ""
        reasoning = reasoning_field.strip() if isinstance(reasoning_field, str) else ""
        if not text and not image_urls:
            if finish_reason == "error":
                raise OpenRouterError(
                    "O modelo esgotou o limite de tokens pensando e não chegou a "
                    "gerar a resposta final (finish_reason=error). Aumente o "
                    "limite de tokens em Preferências, reduza o tamanho do "
                    "prompt, ou tente um modelo com raciocínio menos verboso."
                )
            if reasoning:
                raise OpenRouterError(
                    "O modelo só retornou raciocínio interno, sem uma resposta "
                    f"final (finish_reason={finish_reason or 'desconhecido'})."
                )
            raise OpenRouterError("O provedor não retornou conteúdo utilizável.")
        return text, image_urls, usage, reasoning

    # ------------------------------------------------------------------ #
    # Completagem em streaming (SSE)                                       #
    # ------------------------------------------------------------------ #

    def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        on_delta: Callable[[str], None],
        should_cancel: Optional[Callable[[], bool]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        **params: Any,
    ) -> Tuple[str, List[str], Optional[Dict[str, Any]], str]:
        """
        Envia a conversa em modo streaming. Para cada pedaço de texto do
        conteúdo final, chama ``on_delta(texto)``. Modelos que expõem
        raciocínio separado (campo ``reasoning`` no delta — é o caso de
        GLM, DeepSeek-R1, o1/o3 e outros roteados como "reasoning" no
        OpenRouter) chamam ``on_reasoning(texto)`` à medida que os tokens de
        "pensamento" chegam, ANTES do conteúdo final começar. Sem esse
        callback, o app só mostra algo quando o modelo já parou de pensar
        e começa a escrever a resposta — daí a sensação de "trava e só
        depois aparece tudo de uma vez".

        Retorna (texto_completo, urls_de_imagem, usage, raciocínio_completo).

        ``should_cancel`` é uma função opcional; se retornar True, o stream é
        interrompido e a conexão fechada.
        """
        url = f"{OPENROUTER_BASE}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._normalise_messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
            "usage": {"include": True},
        }
        payload.update(self._clean_params(params))

        collected: List[str] = []
        collected_reasoning: List[str] = []
        collected_images: List[str] = []
        finish_reason: Optional[str] = None
        usage: Optional[Dict[str, Any]] = None
        stream_error: Optional[str] = None
        try:
            with requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                stream=True,
            ) as response:
                # Garante UTF-8 (útil também para a leitura do corpo de erro).
                response.encoding = "utf-8"

                self._raise_for_status(response)

                # Lê linhas como bytes e decodifica em UTF-8 nós mesmos. Cada
                # linha é uma sequência UTF-8 completa (o '\n' que separa linhas
                # nunca aparece dentro de um caractere multibyte), então é
                # seguro decodificar linha a linha — e evita o requests assumir
                # ISO-8859-1 para 'text/event-stream' sem charset (mojibake).
                for raw_line in response.iter_lines(decode_unicode=False):
                    if should_cancel is not None and should_cancel():
                        break
                    if not raw_line:
                        continue
                    if isinstance(raw_line, bytes):
                        line = raw_line.decode("utf-8", "replace").strip()
                    else:
                        line = raw_line.strip()
                    # O OpenRouter envia comentários de keep-alive começando com ':'.
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except ValueError:
                        continue
                    # Alguns provedores mandam um objeto de erro DENTRO do
                    # stream (HTTP 200, SSE normal) em vez de cortar a
                    # conexão com status >= 400. Sem checar isso, um erro
                    # no meio da geração vira silenciosamente uma resposta
                    # "vazia".
                    chunk_error = chunk.get("error")
                    if isinstance(chunk_error, dict):
                        stream_error = chunk_error.get("message") or str(chunk_error)
                    chunk_finish = self._extract_finish_reason(chunk)
                    if chunk_finish:
                        finish_reason = chunk_finish
                    chunk_usage = chunk.get("usage")
                    if isinstance(chunk_usage, dict):
                        usage = chunk_usage
                    delta_text, delta_reasoning, delta_images = self._extract_delta(chunk)
                    if delta_reasoning:
                        collected_reasoning.append(delta_reasoning)
                        if on_reasoning is not None:
                            on_reasoning(delta_reasoning)
                    if delta_text:
                        collected.append(delta_text)
                        on_delta(delta_text)
                    if delta_images:
                        collected_images.extend(delta_images)
        except requests.Timeout as exc:
            raise OpenRouterError(
                f"Tempo de espera esgotado ao contatar OpenRouter: {exc}", retryable=True
            ) from exc
        except requests.ConnectionError as exc:
            raise OpenRouterError(
                f"Falha de conexão com OpenRouter: {exc}", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise OpenRouterError(f"Falha ao contatar OpenRouter: {exc}") from exc

        self._debug_log(model, finish_reason, usage)

        final_text = "".join(collected)
        final_reasoning = "".join(collected_reasoning)

        if stream_error:
            raise OpenRouterError(f"O provedor retornou um erro durante a geração: {stream_error}")

        if not final_text and not collected_images:
            if should_cancel is not None and should_cancel():
                # Cancelado pelo usuário: não é erro, devolve o que tiver
                # (tipicamente só o raciocínio, se o modelo chegou a pensar).
                return final_text, collected_images, usage, final_reasoning
            if finish_reason == "error":
                raise OpenRouterError(
                    "O modelo esgotou o limite de tokens pensando e não chegou a "
                    "gerar a resposta final (finish_reason=error). Aumente o "
                    "limite de tokens em Preferências, reduza o tamanho do "
                    "prompt, ou tente um modelo com raciocínio menos verboso."
                )
            if final_reasoning:
                raise OpenRouterError(
                    "O modelo só retornou raciocínio interno, sem uma resposta "
                    f"final (finish_reason={finish_reason or 'desconhecido'})."
                )
            raise OpenRouterError("O provedor não retornou conteúdo utilizável.")

        return final_text, collected_images, usage, final_reasoning

    # ------------------------------------------------------------------ #
    # Auxiliares                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_images(images_field: Any) -> List[str]:
        """Extrai as URLs (geralmente data URIs base64) do campo `images`
        que modelos de geração de imagem devolvem ao lado de `content`."""
        if not isinstance(images_field, list):
            return []
        urls: List[str] = []
        for img in images_field:
            if not isinstance(img, dict):
                continue
            image_url = img.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else img.get("url")
            if isinstance(url, str) and url:
                urls.append(url)
        return urls

    
    @staticmethod
    def _extract_delta(chunk: Dict[str, Any]) -> Tuple[str, str, List[str]]:
        """Retorna (texto_conteudo, texto_raciocinio, urls_de_imagem) de um
        chunk SSE. O raciocínio vem em ``delta.reasoning`` (padrão usado pelo
        OpenRouter para modelos "reasoning") ou, em alguns provedores, em
        ``delta.reasoning_content`` — checamos os dois nomes."""
        choices = chunk.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return "", "", []
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        text = content if isinstance(content, str) else ""
        reasoning = delta.get("reasoning")
        if not isinstance(reasoning, str):
            reasoning = delta.get("reasoning_content")
        reasoning_text = reasoning if isinstance(reasoning, str) else ""
        images = OpenRouterClient._extract_images(delta.get("images"))
        return text, reasoning_text, images

    @staticmethod
    def _extract_finish_reason(chunk: Dict[str, Any]) -> Optional[str]:
        choices = chunk.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return None
        reason = choices[0].get("finish_reason")
        return reason if isinstance(reason, str) else None

    @staticmethod
    def _debug_log(
        model: str,
        finish_reason: Optional[str],
        usage: Optional[Dict[str, Any]],
    ) -> None:
        """Imprime no terminal o motivo de término e o uso de tokens.

        Útil para diagnosticar respostas cortadas: se ``finish_reason`` vier
        como "length", a resposta foi truncada por atingir o limite de
        tokens (``max_tokens``) configurado em Preferências.
        """
        usage_str = "indisponível"
        if isinstance(usage, dict):
            print(f"[por-ai][debug] usage bruto = {usage!r}")
            prompt = usage.get("prompt_tokens", "?")
            completion = usage.get("completion_tokens", "?")
            total = usage.get("total_tokens", "?")
            usage_str = f"prompt={prompt} completion={completion} total={total}"
            reasoning_tokens = None
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                reasoning_tokens = details.get("reasoning_tokens")
            if reasoning_tokens is not None:
                usage_str += f" reasoning={reasoning_tokens}"

        reason_str = finish_reason or "desconhecido"
        flag = " ⚠️ TRUNCADA (limite de tokens atingido)" if finish_reason == "length" else ""
        print(
            f"[por-ai][debug] modelo={model} finish_reason={reason_str} "
            f"tokens=({usage_str}){flag}"
        )

    @staticmethod
    def _normalise_messages(
        messages: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        valid_roles = {"system", "user", "assistant"}
        normalised: List[Dict[str, str]] = []
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, list):
                # Mensagem multimodal (texto + imagem): cada item já vem
                # pronto de assistant.py (blocos {"type": "text", ...} ou
                # {"type": "image_url", ...}). Só descartamos se a lista
                # vier vazia — o formato em si é válido para a API.
                if not content:
                    continue
            elif not isinstance(content, str) or not content:
                # Mensagem de texto puro: descarta se vazia ou de tipo
                # inesperado (nem str, nem list).
                continue
            role = message.get("role")
            if role not in valid_roles:
                role = "user"
            normalised.append({"role": role, "content": content})
        return normalised

    @staticmethod
    def _clean_params(params: Dict[str, Any]) -> Dict[str, Any]:
        # Remove valores None para não enviar campos vazios.
        return {key: value for key, value in params.items() if value is not None}

    # HTTP 408/425/429 e 5xx costumam ser falhas transitórias (rate limit,
    # provedor sobrecarregado, gateway instável) — vale tentar de novo. Os
    # demais 4xx (401 chave inválida, 400 payload malformado, 404 modelo
    # inexistente etc.) são definitivos: tentar de novo não muda o resultado.
    _RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code < 400:
            return
        message = OpenRouterClient._format_error(response)
        retryable = response.status_code in OpenRouterClient._RETRYABLE_STATUS_CODES
        raise OpenRouterError(message, retryable=retryable)

    @staticmethod
    def _format_error(response: requests.Response) -> str:
        status = response.status_code
        fallback = (response.text or "").strip() or "Erro desconhecido."
        try:
            payload = response.json()
        except ValueError:
            return f"OpenRouter respondeu HTTP {status}: {fallback}"

        error_obj = payload.get("error")
        if not isinstance(error_obj, dict):
            return f"OpenRouter respondeu HTTP {status}: {fallback}"

        message = error_obj.get("message") or fallback
        metadata = error_obj.get("metadata") or {}
        provider_name = metadata.get("provider_name")
        raw_detail = metadata.get("raw")
        details = [str(d) for d in (provider_name, raw_detail) if d]
        suffix = f" ({' | '.join(details)})" if details else ""
        return f"OpenRouter respondeu HTTP {status}: {message}{suffix}"