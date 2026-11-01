from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from .catalog import CatalogError, ModelRef
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
        if prompt.response_format is not None:
            kwargs["response_format"] = prompt.response_format
        if prompt.messages is not None:
            response = self._llm.create_chat_completion(messages=prompt.messages, **kwargs)
            choice = response["choices"][0]
            content = choice["message"]["content"]
        else:
            response = self._llm.create_completion(prompt=prompt.raw or "", **kwargs)
            choice = response["choices"][0]
            content = choice["text"]
        usage = response.get("usage")
        return content, usage if isinstance(usage, dict) else None, choice.get("finish_reason")


def runner_for(ref: ModelRef, n_ctx: int = 4096) -> Runner:
    """Runner adecuado al tipo de modelo resuelto."""
    if ref.entry.kind == "gguf":
        if ref.path is None:
            raise CatalogError(f"el modelo {ref.label} no está descargado")
        return LocalRunner(ref.path, n_ctx)
    raise CatalogError(f"proveedor no soportado todavía: {ref.entry.kind}")
