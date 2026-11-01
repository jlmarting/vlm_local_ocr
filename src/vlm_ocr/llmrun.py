from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from .catalog import CatalogError, ModelEntry, ModelRef
from .errors import ContractError

try:
    from llama_cpp import Llama
except ImportError:  # permite usar el modo Markdown sin el motor LLM
    Llama = None  # type: ignore[assignment]


@dataclass
class BuiltPrompt:
    """Prompt listo para un runner: mensajes de chat o texto de completion."""

    messages: list[dict] | None = None
    raw: str | None = None
    response_format: dict[str, Any] | None = None
    text_for_tokens: str = ""


class Runner(Protocol):
    load_time_ms: float | None

    def complete(
        self, prompt: BuiltPrompt, max_tokens: int
    ) -> tuple[str, dict[str, Any] | None, str | None]: ...

    def estimate_tokens(self, prompt: BuiltPrompt) -> int: ...


class LocalRunner:
    """Ejecuta el modelo GGUF con llama.cpp."""

    def __init__(self, model_path: Path | str, n_ctx: int = 4096) -> None:
        if Llama is None:
            raise ContractError(
                "llama-cpp-python no está instalado; instálalo para usar --format json"
            )
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise ContractError(f"no existe el modelo: {self.model_path}")
        start = perf_counter()
        try:
            self._llm = Llama(model_path=str(self.model_path), n_ctx=n_ctx, verbose=False)
        except Exception as exc:
            raise ContractError(f"no se pudo cargar el modelo {self.model_path}: {exc}") from exc
        self.load_time_ms: float = round((perf_counter() - start) * 1000, 1)

    def estimate_tokens(self, prompt: BuiltPrompt) -> int:
        text = prompt.text_for_tokens
        if not text and prompt.messages:
            text = "\n".join(str(message.get("content", "")) for message in prompt.messages)
        text = text or prompt.raw or ""
        tokenize = getattr(self._llm, "tokenize", None)
        if callable(tokenize):
            try:
                return max(1, len(tokenize(text.encode("utf-8"))))
            except (AttributeError, TypeError, ValueError, RuntimeError):
                return max(1, len(text) // 4)
        return max(1, len(text) // 4)

    def complete(
        self, prompt: BuiltPrompt, max_tokens: int
    ) -> tuple[str, dict[str, Any] | None, str | None]:
        kwargs: dict[str, Any] = {"temperature": 0, "max_tokens": max_tokens}
        if prompt.messages is not None:
            if prompt.response_format is not None:
                kwargs["response_format"] = prompt.response_format
            response = self._llm.create_chat_completion(messages=prompt.messages, **kwargs)
            choice = response["choices"][0]
            content = choice["message"]["content"]
        else:
            # create_completion no admite ``response_format`` (llama-cpp-python 0.3.36);
            # el JSON se garantiza validando y, si procede, con el contrato de chat.
            response = self._llm.create_completion(prompt=prompt.raw or "", **kwargs)
            choice = response["choices"][0]
            content = choice["text"]
        usage = response.get("usage")
        return content, usage if isinstance(usage, dict) else None, choice.get("finish_reason")


class OllamaRunner:
    """Ejecuta el modelo en un servidor ollama (nube o daemon) por su API nativa."""

    load_time_ms: float | None = None

    def __init__(self, entry: ModelEntry, n_ctx: int = 4096) -> None:
        self.entry = entry
        self.n_ctx = n_ctx
        self.timeout = _timeout_seconds()

    def estimate_tokens(self, prompt: BuiltPrompt) -> int:
        text = prompt.text_for_tokens
        if not text and prompt.messages:
            text = "\n".join(str(message.get("content", "")) for message in prompt.messages)
        return max(1, len(text or prompt.raw or "") // 4)

    def complete(
        self, prompt: BuiltPrompt, max_tokens: int
    ) -> tuple[str, dict[str, Any] | None, str | None]:
        if prompt.messages is None:
            raise CatalogError("prompt_style nuextract solo con modelos locales")
        key = self._api_key()
        schema = (prompt.response_format or {}).get("schema")
        prompt_tokens = self.estimate_tokens(prompt)
        context = int(self.entry.context or 8192)
        num_ctx = min(context, max(8192, prompt_tokens + max_tokens + 256))
        body = {
            "model": self.entry.model,
            "messages": prompt.messages,
            "stream": False,
            "format": schema if schema is not None else "json",
            "options": {
                "temperature": 0,
                "num_ctx": num_ctx,
                "num_predict": max_tokens,
            },
        }
        if self.entry.think is not None:
            body["think"] = self.entry.think
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        url = f"{str(self.entry.base_url).rstrip('/')}/api/chat"
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CatalogError(self._http_error(exc.code, url)) from exc
        except TimeoutError as exc:
            raise CatalogError(f"no se pudo contactar {self.entry.base_url}: timeout") from exc
        except urllib.error.URLError as exc:
            raise CatalogError(f"no se pudo contactar {self.entry.base_url}: {exc.reason}") from exc

        message = data.get("message") or {}
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        usage: dict[str, Any] | None = None
        if prompt_tokens is not None or completion_tokens is not None:
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0),
            }
        return message.get("content", ""), usage, data.get("done_reason")

    def _api_key(self) -> str | None:
        if not self.entry.requires_key:
            return None
        env = self.entry.api_key_env or "OLLAMA_API_KEY"
        key = os.environ.get(env)
        if not key:
            raise CatalogError(f"falta la API key del proveedor remoto: export {env}=...")
        return key

    def _http_error(self, code: int, url: str) -> str:
        if code == 401:
            env = self.entry.api_key_env or "OLLAMA_API_KEY"
            return f"API key ausente o inválida ({env}): {url}"
        if code == 404:
            return f"modelo no disponible en {self.entry.base_url}: {self.entry.model}"
        return f"error HTTP {code} al llamar a {url}"


def _timeout_seconds() -> float:
    """Timeout HTTP configurable por entorno; si el valor no es un número, 300 s."""
    try:
        return float(os.environ.get("VLM_OCR_TIMEOUT", "300"))
    except ValueError:
        return 300.0


def runner_for(ref: ModelRef, n_ctx: int = 4096) -> Runner:
    """Runner adecuado al tipo de modelo resuelto."""
    if ref.entry.kind == "gguf":
        if ref.path is None:
            raise CatalogError(f"el modelo {ref.label} no está descargado")
        return LocalRunner(ref.path, n_ctx)
    if ref.entry.kind == "ollama":
        return OllamaRunner(ref.entry, n_ctx)
    raise CatalogError(f"proveedor desconocido: {ref.entry.kind}")
