"""
Coordenador de chat do POR.ai.

Formatos de texto suportados (enviados como bloco na mensagem):
  txt, md, rst, org, tex, csv, log, pdf, odt

Formatos de imagem suportados (enviados como base64 multimodal):
  jpg, jpeg, png, webp
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from gi.repository import GLib

from core.config import Config
from core.openrouter import OpenRouterClient, OpenRouterError

# ── Dependências opcionais ────────────────────────────────────────────────────

try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from odf.opendocument import load as odf_load
    from odf.text import P
    ODT_AVAILABLE = True
except ImportError:
    ODT_AVAILABLE = False



# ── Extensões suportadas ──────────────────────────────────────────────────────

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".org",
    ".tex", ".csv", ".log",
}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

logger = logging.getLogger(__name__)


class ChatAssistant:
    """Envia conversas ao OpenRouter sem travar a interface."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._inflight = False
        self._cancel = threading.Event()

    # ------------------------------------------------------------------ #
    # Estado                                                               #
    # ------------------------------------------------------------------ #

    def is_busy(self) -> bool:
        with self._lock:
            return self._inflight

    def cancel(self) -> None:
        self._cancel.set()

    def _build_client(self) -> OpenRouterClient:
        return OpenRouterClient(
            api_key=self.config.api_key,
            site_url=self.config.site_url,
            site_name=self.config.site_name,
        )

    # ------------------------------------------------------------------ #
    # Envio                                                                #
    # ------------------------------------------------------------------ #

    def send(
        self,
        model: str,
        messages: List[Any],
        on_delta: Callable[[str], None],
        on_done: Callable[[str], None],
        on_error: Callable[[str], None],
        on_usage: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> bool:
        with self._lock:
            if self._inflight:
                return False
            self._inflight = True
            self._cancel.clear()

        threading.Thread(
            target=self._worker,
            args=(model, messages, on_delta, on_done, on_error, on_usage),
            daemon=True,
        ).start()
        return True

    def _worker(
        self,
        model: str,
        messages: List[Any],
        on_delta: Callable[[str], None],
        on_done: Callable[[str], None],
        on_error: Callable[[str], None],
        on_usage: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        try:
            client = self._build_client()
            if self.config.stream:
                full, images, usage = client.stream_chat(
                    model=model,
                    messages=messages,
                    on_delta=lambda text: GLib.idle_add(on_delta, text),
                    should_cancel=self._cancel.is_set,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
            else:
                full, images, usage = client.chat(
                    model=model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                GLib.idle_add(on_delta, full)

            if images:
                markdown_links = self._save_generated_images(images)
                if markdown_links:
                    extra = ("\n\n" if full.strip() else "") + markdown_links
                    full += extra
                    GLib.idle_add(on_delta, extra)

            if usage and on_usage is not None:
                GLib.idle_add(on_usage, usage)

            GLib.idle_add(on_done, full)
        except OpenRouterError as exc:
            GLib.idle_add(on_error, str(exc))
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Erro inesperado no chat")
            GLib.idle_add(on_error, str(exc))
        finally:
            with self._lock:
                self._inflight = False

    # ------------------------------------------------------------------ #
    # Modelos                                                              #
    # ------------------------------------------------------------------ #

    def fetch_models(
        self,
        on_done: Callable[[List[str]], None],
        on_error: Callable[[str], None],
    ) -> None:
        def worker() -> None:
            try:
                client = self._build_client()
                raw = client.list_models()
                ids = sorted(
                    {
                        str(item.get("id")).strip()
                        for item in raw
                        if isinstance(item, dict) and item.get("id")
                    }
                )
                GLib.idle_add(on_done, ids)
            except OpenRouterError as exc:
                GLib.idle_add(on_error, str(exc))
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Erro ao buscar modelos")
                GLib.idle_add(on_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Suporte a anexos                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_image(path: str) -> bool:
        return os.path.splitext(path)[1].lower() in _IMAGE_EXTENSIONS

    @staticmethod
    def supported_attachment(path: str) -> bool:
        ext = os.path.splitext(path)[1].lower()
        if ext in _TEXT_EXTENSIONS:
            return True
        if ext in _IMAGE_EXTENSIONS:
            return True
        if ext == ".pdf":
            return PDF_AVAILABLE
        if ext == ".odt":
            return ODT_AVAILABLE
        
        return False

    @staticmethod
    def unsupported_reason(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf" and not PDF_AVAILABLE:
            return "Instale python3-pypdf para anexar PDFs."
        if ext == ".odt" and not ODT_AVAILABLE:
            return "Instale python3-odfpy para anexar arquivos ODT."
        
        return "Tipo de arquivo não suportado."

    @staticmethod
    def read_text_attachment(path: str) -> str:
        """Extrai texto de documentos (PDF, ODT, texto puro)."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            return ChatAssistant._read_pdf(path)
        if ext == ".odt":
            return ChatAssistant._read_odt(path)
        
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError as exc:
            raise RuntimeError(f"Erro ao ler arquivo: {exc}") from exc

    # Alias para compatibilidade com código existente.
    read_attachment = read_text_attachment

    # Assinaturas (magic numbers) dos formatos de imagem suportados. A
    # extensão do arquivo (.jpg, .png etc.) é só um nome escolhido pelo
    # usuário — nada garante que os bytes reais batem com ela. É comum uma
    # captura de tela sair como PNG e depois ser renomeada para .jpg (ou
    # vice-versa). Se a data URI declarar um MIME que não bate com os bytes
    # de fato, o provedor tenta decodificar no formato errado, falha e em
    # vez de dar erro claro alguns pipelines simplesmente repassam o blob
    # bruto ao modelo como texto — que aí "vê" só ruído/caracteres
    # repetidos. Por isso sempre inspecionamos os bytes primeiro.
    _MAGIC_SIGNATURES = (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
    )

    @staticmethod
    def _sniff_mime(data: bytes, fallback: str) -> str:
        for signature, mime in ChatAssistant._MAGIC_SIGNATURES:
            if data.startswith(signature):
                return mime
        # WEBP: RIFF....WEBP — os 4 primeiros bytes são "RIFF", só nos
        # bytes 8-12 é que aparece o marcador "WEBP" de fato.
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        # Formato não reconhecido pela assinatura: cai para o palpite feito
        # pela extensão do arquivo, em vez de travar o envio.
        return fallback

    @staticmethod
    def read_image_attachment(path: str) -> Dict[str, Any]:
        """
        Lê uma imagem e devolve o bloco multimodal para a API:
        {"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}
        """
        guessed, _ = mimetypes.guess_type(path)
        if not guessed:
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            # jpg → jpeg para compatibilidade com o padrão MIME
            ext = "jpeg" if ext == "jpg" else ext
            guessed = f"image/{ext}"
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            raise RuntimeError(f"Erro ao ler imagem: {exc}") from exc
        # A extensão é só um palpite; os bytes reais mandam.
        mime = ChatAssistant._sniff_mime(raw, guessed)
        data = base64.b64encode(raw).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{data}"},
        }

    _RE_DATA_URI = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)

    @staticmethod
    def _save_generated_images(image_urls: List[str]) -> str:
        """Salva imagens geradas pelo modelo (data URIs base64) em disco e
        devolve um bloco Markdown com links clicáveis para cada uma."""
        if not image_urls:
            return ""
        images_dir = os.path.join(GLib.get_user_data_dir(), "por-ai", "images")
        try:
            os.makedirs(images_dir, exist_ok=True)
        except OSError:
            return ""

        links: List[str] = []
        for url in image_urls:
            if not isinstance(url, str):
                continue
            match = ChatAssistant._RE_DATA_URI.match(url)
            if not match:
                if url.startswith(("http://", "https://")):
                    links.append(f"[Imagem gerada]({url})")
                continue
            mime, b64data = match.group(1), match.group(2)
            ext = mimetypes.guess_extension(mime) or ".png"
            if ext == ".jpe":
                ext = ".jpg"
            try:
                raw = base64.b64decode(b64data)
            except Exception:
                continue
            filename = f"{uuid.uuid4().hex}{ext}"
            path = os.path.join(images_dir, filename)
            try:
                with open(path, "wb") as f:
                    f.write(raw)
            except OSError:
                continue
            links.append(f"[Imagem gerada]({GLib.filename_to_uri(path, None)})")
        return "\n".join(links)

    # ------------------------------------------------------------------ #
    # Leitores específicos                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_pdf(path: str) -> str:
        if not PDF_AVAILABLE:
            raise RuntimeError("Instale python3-pypdf para ler PDFs.")
        try:
            reader = PdfReader(path)
            parts = [p.extract_text() for p in reader.pages if p.extract_text()]
            text = "\n".join(parts)
        except Exception as exc:
            raise RuntimeError(f"Erro ao ler PDF: {exc}") from exc
        if not text.strip():
            raise RuntimeError(
                "Não foi possível extrair texto do PDF "
                "(pode ser imagem ou estar vazio)."
            )
        return text

    @staticmethod
    def _read_odt(path: str) -> str:
        if not ODT_AVAILABLE:
            raise RuntimeError("Instale python3-odfpy para ler ODT.")
        try:
            doc = odf_load(path)
            paragraphs = doc.getElementsByType(P)
            lines = []
            for para in paragraphs:
                text = "".join(
                    node.data
                    for node in para.childNodes
                    if node.nodeType == node.TEXT_NODE
                )
                lines.append(text)
            return "\n".join(lines)
        except Exception as exc:
            raise RuntimeError(f"Erro ao ler ODT: {exc}") from exc

    @staticmethod
    def _read_docx(path: str) -> str:
        if not DOCX_AVAILABLE:
            raise RuntimeError("Instale python3-docx para ler DOCX.")
        try:
            doc = DocxDocument(path)
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:
            raise RuntimeError(f"Erro ao ler DOCX: {exc}") from exc
