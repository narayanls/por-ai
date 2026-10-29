"""
Cliente do OpenRouter para o POR.ai.

Também serve de base para outros provedores compatíveis com a API da OpenAI
(``/chat/completions`` com SSE): basta uma subclasse trocar ``BASE_URL`` e
companhia — ver ``core/maritaca.py``.

O padrão de cabeçalhos segue o recomendado pelo OpenRouter:
``Authorization: Bearer <chave>`` e, opcionalmente, ``HTTP-Referer`` (site_url)
e ``X-Title`` (site_name) para aparecer nas estatísticas da sua conta.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


import requests

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def web_search_tool(max_results: int = 5) -> Dict[str, Any]:
    """Entrada do array ``tools`` que liga a pesquisa na web do OpenRouter.

    É uma *server tool*: o próprio OpenRouter executa a busca e devolve os
    resultados ao modelo, então o app não precisa tratar ``tool_calls``.
    O modelo decide se e quantas vezes pesquisar; as páginas usadas voltam
    como anotações ``url_citation`` (ver ``_collect_citations``).

    Substitui o antigo ``plugins: [{"id": "web"}]`` / sufixo ``:online``,
    marcados como obsoletos na documentação do OpenRouter.

    ``engine`` fica no padrão ("auto"): busca nativa do provedor quando o
    modelo tem (OpenAI, Anthropic, Google, xAI, Perplexity), senão Exa.
    """
    return {
        "type": "openrouter:web_search",
        "parameters": {"max_results": max_results},
    }


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
    # Pontos de personalização para outros provedores compatíveis com a API
    # da OpenAI (ver ``core/maritaca.py``). Uma subclasse só precisa trocar
    # estes atributos e, se quiser, ``_extra_payload``.
    BASE_URL = OPENROUTER_BASE
    PROVIDER_NAME = "OpenRouter"
    MODELS_PATH = "/models/user"
    MISSING_KEY_MESSAGE = "Configure a chave da API OpenRouter em Preferências."
    # ``stream_options.include_usage`` faz parte da API da OpenAI e devolve o
    # uso de tokens no último pedaço do streaming.
    STREAM_INCLUDE_USAGE = True

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
        # Fontes (páginas da web) citadas na última resposta, quando a
        # pesquisa na web estava ligada. Lista de {"url", "title"} sem
        # repetições, na ordem em que apareceram. Zerada a cada chamada.
        self.last_citations: List[Dict[str, str]] = []

    # ------------------------------------------------------------------ #
    # Cabeçalhos                                                           #
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise OpenRouterError(self.MISSING_KEY_MESSAGE)
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

    def list_models(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """Retorna a lista de modelos do OpenRouter (campo ``data``).

        ``timeout`` permite um limite menor que o do chat (o catálogo fica
        no caminho da primeira mensagem, então não pode esperar 240 s)."""
        return self._get_data_list(self.MODELS_PATH, timeout)

    def list_zdr_model_ids(self, timeout: Optional[float] = None) -> Set[str]:
        """IDs dos modelos com pelo menos um endpoint de retenção zero (ZDR).

        O endpoint ``/endpoints/zdr`` lista um item por par modelo +
        provedor; o campo ``model_id`` usa o mesmo formato dos IDs do
        catálogo (ex.: ``deepseek/deepseek-v4.1-flash-1017``).

        Necessário porque ``/models/user`` só aplica a política de
        privacidade da CONTA (configurada no site); o filtro escolhido em
        Preferências vai apenas no envio de cada mensagem.
        """
        ids: Set[str] = set()
        for entry in self._get_data_list("/endpoints/zdr", timeout):
            if isinstance(entry, dict):
                model_id = entry.get("model_id")
                if isinstance(model_id, str) and model_id.strip():
                    ids.add(model_id.strip())
        return ids

    def _get_data_list(
        self, path: str, timeout: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """GET em ``BASE_URL + path`` e devolve o campo ``data``."""
        url = f"{self.BASE_URL}{path}"
        try:
            response = requests.get(
                url, headers=self._headers(), timeout=timeout or self.timeout
            )
        except requests.Timeout as exc:
            raise OpenRouterError(
                f"Tempo de espera esgotado ao contatar {self.PROVIDER_NAME}: {exc}", retryable=True
            ) from exc
        except requests.ConnectionError as exc:
            raise OpenRouterError(
                f"Falha de conexão com {self.PROVIDER_NAME}: {exc}", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise OpenRouterError(f"Falha ao contatar {self.PROVIDER_NAME}: {exc}") from exc

        # As APIs respondem em UTF-8; fixamos para o requests não assumir
        # ISO-8859-1 e gerar acentuação corrompida ("Ã§" no lugar de "ç").
        response.encoding = "utf-8"

        self._raise_for_status(response)

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenRouterError(f"{self.PROVIDER_NAME} retornou JSON inválido.") from exc

        data = payload.get("data") if isinstance(payload, dict) else None
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
        url = f"{self.BASE_URL}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._normalise_messages(messages),
        }
        payload.update(self._extra_payload())
        payload.update(self._clean_params(params))
        self.last_citations = []

        started = time.monotonic()
        try:
            response = requests.post(
                url, headers=self._headers(), json=payload, timeout=self.timeout
            )
        except requests.Timeout as exc:
            raise OpenRouterError(
                f"Tempo de espera esgotado ao contatar {self.PROVIDER_NAME}: {exc}", retryable=True
            ) from exc
        except requests.ConnectionError as exc:
            raise OpenRouterError(
                f"Falha de conexão com {self.PROVIDER_NAME}: {exc}", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise OpenRouterError(f"Falha ao contatar {self.PROVIDER_NAME}: {exc}") from exc

        response.encoding = "utf-8"

        self._raise_for_status(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise OpenRouterError(f"{self.PROVIDER_NAME} retornou JSON inválido.") from exc

        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError("O provedor retornou uma resposta vazia.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        reasoning_field = message.get("reasoning") if isinstance(message, dict) else None
        image_urls = self._extract_images(
            message.get("images") if isinstance(message, dict) else None
        )
        if isinstance(message, dict):
            self._collect_citations(message.get("annotations"), self.last_citations)
        finish_reason = choices[0].get("finish_reason") if isinstance(choices[0], dict) else None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        self._debug_log(
            model,
            finish_reason,
            usage,
            timing={"total": time.monotonic() - started},
            provider=data.get("provider"),
        )
        text = content.strip() if isinstance(content, str) else ""
        reasoning = reasoning_field.strip() if isinstance(reasoning_field, str) else ""
        if not text and not image_urls:
            if finish_reason == "error":
                raise OpenRouterError(
                    "O modelo esgotou o limite de tokens pensando e não chegou a "
                    "gerar a resposta final (finish_reason=error). Aumente o "
                    "limite de tokens em Preferências, reduza o esforço de "
                    "raciocínio, reduza o tamanho do prompt, ou tente um "
                    "modelo com raciocínio menos verboso."
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
        url = f"{self.BASE_URL}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._normalise_messages(messages),
            "stream": True,
        }
        if self.STREAM_INCLUDE_USAGE:
            payload["stream_options"] = {"include_usage": True}
        payload.update(self._extra_payload())
        payload.update(self._clean_params(params))
        self.last_citations = []

        collected: List[str] = []
        collected_reasoning: List[str] = []
        collected_images: List[str] = []
        finish_reason: Optional[str] = None
        usage: Optional[Dict[str, Any]] = None
        stream_error: Optional[str] = None
        # Marcos de tempo (segundos desde o envio) para o log de depuração.
        # Separam o que é rede/OpenRouter (resposta HTTP), o que é o modelo
        # pensando (1º raciocínio → 1º texto) e a velocidade de geração.
        started = time.monotonic()
        timing: Dict[str, float] = {}
        provider: Optional[str] = None
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
                timing["http"] = time.monotonic() - started

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
                    if provider is None and isinstance(chunk.get("provider"), str):
                        provider = chunk["provider"]
                    self._collect_chunk_citations(chunk, self.last_citations)
                    delta_text, delta_reasoning, delta_images = self._extract_delta(chunk)
                    if delta_reasoning and "first_reasoning" not in timing:
                        timing["first_reasoning"] = time.monotonic() - started
                    if delta_text and "first_content" not in timing:
                        timing["first_content"] = time.monotonic() - started
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
                f"Tempo de espera esgotado ao contatar {self.PROVIDER_NAME}: {exc}", retryable=True
            ) from exc
        except requests.ConnectionError as exc:
            raise OpenRouterError(
                f"Falha de conexão com {self.PROVIDER_NAME}: {exc}", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise OpenRouterError(f"Falha ao contatar {self.PROVIDER_NAME}: {exc}") from exc

        timing["total"] = time.monotonic() - started
        self._debug_log(model, finish_reason, usage, timing=timing, provider=provider)

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
                    "limite de tokens em Preferências, reduza o esforço de "
                    "raciocínio, reduza o tamanho do prompt, ou tente um "
                    "modelo com raciocínio menos verboso."
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

    def _extra_payload(self) -> Dict[str, Any]:
        """Campos extras que só este provedor entende. No OpenRouter,
        ``usage.include`` pede o custo detalhado de cada resposta; outros
        provedores podem rejeitar o campo, então a subclasse devolve ``{}``."""
        return {"usage": {"include": True}}

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
    def _collect_citations(
        annotations: Any, sink: List[Dict[str, str]]
    ) -> None:
        """Acrescenta a ``sink`` as fontes de uma lista de anotações.

        O formato padronizado pelo OpenRouter (o mesmo do Chat Completions
        da OpenAI) é::

            {"type": "url_citation",
             "url_citation": {"url": ..., "title": ..., "content": ...}}

        Alguns provedores mandam os campos direto no objeto, sem o nível
        ``url_citation`` — aceitamos os dois. URLs repetidas (a mesma página
        citada em vários trechos da resposta) entram uma vez só.
        """
        if not isinstance(annotations, list):
            return
        seen = {item["url"] for item in sink}
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            if annotation.get("type") not in (None, "url_citation"):
                continue
            inner = annotation.get("url_citation")
            data = inner if isinstance(inner, dict) else annotation
            url = data.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            url = url.strip()
            if url in seen:
                continue
            seen.add(url)
            title = data.get("title")
            title = title.strip() if isinstance(title, str) else ""
            sink.append({"url": url, "title": title})

    @staticmethod
    def _collect_chunk_citations(
        chunk: Dict[str, Any], sink: List[Dict[str, str]]
    ) -> None:
        """No streaming, as anotações costumam chegar em ``delta.annotations``
        (geralmente nos últimos pedaços). Por segurança olhamos também
        ``message.annotations`` dentro do chunk, que alguns provedores usam
        no pedaço final."""
        choices = chunk.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return
        for key in ("delta", "message"):
            part = choices[0].get(key)
            if isinstance(part, dict):
                OpenRouterClient._collect_citations(part.get("annotations"), sink)

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
        timing: Optional[Dict[str, float]] = None,
        provider: Optional[str] = None,
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
        if timing:
            OpenRouterClient._debug_log_timing(timing, usage, provider)

    @staticmethod
    def _debug_log_timing(
        timing: Dict[str, float],
        usage: Optional[Dict[str, Any]],
        provider: Optional[str],
    ) -> None:
        """Imprime onde o tempo foi gasto. Leitura rápida:

        * ``http`` alto (vários segundos): fila/rede no OpenRouter ou no
          provedor — ``provider_sort="latency"`` pode ajudar.
        * ``pensando`` alto: o modelo raciocinando — reduza
          ``reasoning_effort`` ou use um modelo sem raciocínio.
        * ``tok/s`` baixo: provedor lento — ``provider_sort="throughput"``.
        """

        def fmt(key: str) -> str:
            value = timing.get(key)
            return f"{value:.1f}s" if value is not None else "-"

        parts = [f"resposta HTTP={fmt('http')}"]
        if "first_reasoning" in timing:
            parts.append(f"1º raciocínio={fmt('first_reasoning')}")
        parts.append(f"1º texto={fmt('first_content')}")
        parts.append(f"total={fmt('total')}")

        first = timing.get("first_reasoning", timing.get("first_content"))
        if first is not None and "first_content" in timing:
            parts.append(f"pensando={timing['first_content'] - first:.1f}s")

        completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
        if isinstance(completion, (int, float)) and first is not None:
            generating = timing.get("total", 0.0) - first
            if generating > 0.2:
                parts.append(f"velocidade={completion / generating:.0f} tok/s")

        parts.append(f"provedor={provider or '?'}")
        print("[por-ai][debug] tempos: " + "  ".join(parts), flush=True)

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

    @classmethod
    def _raise_for_status(cls, response: requests.Response) -> None:
        if response.status_code < 400:
            return
        message = cls._format_error(response)
        retryable = response.status_code in cls._RETRYABLE_STATUS_CODES
        raise OpenRouterError(message, retryable=retryable)

    @classmethod
    def _format_error(cls, response: requests.Response) -> str:
        name = cls.PROVIDER_NAME
        status = response.status_code
        fallback = (response.text or "").strip() or "Erro desconhecido."
        try:
            payload = response.json()
        except ValueError:
            return f"{name} respondeu HTTP {status}: {fallback}"

        error_obj = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error_obj, str):
            error_obj = {"message": error_obj}
        if not isinstance(error_obj, dict) and isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message")
            if detail:
                error_obj = {"message": detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)}
        if not isinstance(error_obj, dict):
            return f"{name} respondeu HTTP {status}: {fallback}"

        # Formato OpenAI/OpenRouter: {"error": {"message": ...}}. Algumas APIs
        # devolvem só {"detail": ...} ou {"message": ...}; aceitamos também.
        message = error_obj.get("message") or fallback
        metadata = error_obj.get("metadata") or {}
        provider_name = metadata.get("provider_name")
        raw_detail = metadata.get("raw")
        details = [str(d) for d in (provider_name, raw_detail) if d]
        suffix = f" ({' | '.join(details)})" if details else ""
        return f"{name} respondeu HTTP {status}: {message}{suffix}"
