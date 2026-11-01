from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from vlm_ocr.catalog import CatalogError, ModelEntry, ModelRef
from vlm_ocr.llmrun import BuiltPrompt, OllamaRunner, runner_for


def entry(**overrides) -> ModelEntry:
    data = {
        "alias": "remoto",
        "name": "Remoto",
        "kind": "ollama",
        "license": "MIT",
        "model": "m:1b",
        "base_url": "https://ollama.com",
        "api_key_env": "OLLAMA_API_KEY",
        "requires_key": True,
    }
    data.update(overrides)
    return ModelEntry(**data)


@contextmanager
def serve(status: int = 200, payload: dict | None = None, delay: float = 0.0):
    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            captured["path"] = self.path
            captured["headers"] = {name.lower(): value for name, value in self.headers.items()}
            captured["body"] = json.loads(body)
            if delay:
                time.sleep(delay)
            data = json.dumps(payload or {}).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured
    finally:
        server.shutdown()
        server.server_close()


def prompt(**overrides) -> BuiltPrompt:
    data = {
        "messages": [{"role": "user", "content": "extrae"}],
        "response_format": {"type": "json_object"},
    }
    data.update(overrides)
    return BuiltPrompt(**data)


def test_success_maps_usage_and_sends_options(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "clave")
    payload = {
        "message": {"content": '{"a": 1}'},
        "prompt_eval_count": 10,
        "eval_count": 5,
        "done_reason": "stop",
    }
    with serve(payload=payload) as (url, captured):
        runner = OllamaRunner(entry(base_url=url))

        content, usage, finish = runner.complete(prompt(), 128)

    assert content == '{"a": 1}'
    assert usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert finish == "stop"
    assert captured["path"] == "/api/chat"
    assert captured["headers"]["authorization"] == "Bearer clave"
    assert captured["body"]["model"] == "m:1b"
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["temperature"] == 0
    assert captured["body"]["options"]["num_predict"] == 128


def test_schema_is_sent_as_format(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "clave")
    schema = {"type": "object", "properties": {"a": {"type": "number"}}}
    with serve(payload={"message": {"content": "{}"}}) as (url, captured):
        runner = OllamaRunner(entry(base_url=url))

        runner.complete(prompt(response_format={"type": "json_object", "schema": schema}), 64)

    assert captured["body"]["format"] == schema


def test_no_authorization_without_key_requirement() -> None:
    with serve(payload={"message": {"content": "{}"}}) as (url, captured):
        runner = OllamaRunner(entry(base_url=url, requires_key=False))

        runner.complete(prompt(), 64)

    assert "authorization" not in captured["headers"]


def test_401_mentions_env_and_hides_key(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "supersecreta")
    with serve(status=401, payload={"error": "unauthorized"}) as (url, _):
        runner = OllamaRunner(entry(base_url=url))

        with pytest.raises(CatalogError) as excinfo:
            runner.complete(prompt(), 64)

    message = str(excinfo.value)
    assert "OLLAMA_API_KEY" in message
    assert "supersecreta" not in message


def test_404_reports_model_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "clave")
    with serve(status=404, payload={}) as (url, _):
        runner = OllamaRunner(entry(base_url=url))

        with pytest.raises(CatalogError, match="no disponible"):
            runner.complete(prompt(), 64)


def test_timeout_reports_contact_failure(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "clave")
    monkeypatch.setenv("VLM_OCR_TIMEOUT", "0.05")
    with serve(payload={"message": {"content": "{}"}}, delay=0.5) as (url, _):
        runner = OllamaRunner(entry(base_url=url))

        with pytest.raises(CatalogError, match="no se pudo contactar"):
            runner.complete(prompt(), 64)


def test_missing_key_raises_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    runner = OllamaRunner(entry(base_url="http://127.0.0.1:9"))

    with pytest.raises(CatalogError, match="OLLAMA_API_KEY"):
        runner.complete(prompt(), 64)


def test_raw_prompt_is_rejected() -> None:
    runner = OllamaRunner(entry())

    with pytest.raises(CatalogError, match="solo con modelos locales"):
        runner.complete(BuiltPrompt(raw="<|input|>"), 64)


def test_runner_for_dispatches_ollama() -> None:
    runner = runner_for(ModelRef(entry()))

    assert isinstance(runner, OllamaRunner)
    assert runner.load_time_ms is None


def test_invalid_timeout_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("VLM_OCR_TIMEOUT", "no-es-un-numero")

    assert OllamaRunner(entry()).timeout == 300.0
