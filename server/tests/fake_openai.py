"""A scripted, in-process OpenAI-compatible chat-completions server for tests.

Mirrors ``agent/src/session/runtime.ts`` ``FakeModel`` but is driven from Python
so an end-to-end test owns the turn script while the REAL Node sidecar (pointed
at this server's ``baseUrl`` through ``runtime.configure``) runs the Pi model +
tool loop. Each tool-enabled request consumes the next scripted turn; tool-less
requests (compaction/summarization) return text and never advance the script.

Turn forms::

    {"kind": "text", "chunks": [...]}
    {"kind": "tool_calls", "calls": [{"name": ..., "arguments": {...}, "id": ...}]}
    {"kind": "stall"}                      # emit one chunk, then hang (abort test)

A turn may also be a callable ``(request_info) -> turn`` for request-dependent
scripting. When the script is exhausted the server returns a terminal text turn
so the agent loop always settles.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

Turn = dict[str, Any]
TurnResolver = Turn | Callable[["RequestInfo"], Turn]


@dataclass
class RequestInfo:
    index: int
    roles: list[str]
    tool_names: list[str]
    has_tool_result: bool
    body_text: str


@dataclass
class FakeOpenAI:
    """A running fake server; feed :meth:`provider_spec` to ``runtime.configure``."""

    port: int
    _server: ThreadingHTTPServer
    _thread: threading.Thread
    model_id: str = "heph-fake-model"
    provider_id: str = "heph-fake"
    context_window: int = 128000
    max_tokens: int = 4096
    requests: list[RequestInfo] = field(default_factory=list[RequestInfo])
    _script: list[TurnResolver] = field(default_factory=list["TurnResolver"])
    _cursor: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def set_script(self, script: list[TurnResolver]) -> None:
        with self._lock:
            self._script = list(script)
            self._cursor = 0

    def provider_spec(self) -> dict[str, Any]:
        """A ``runtime.configure`` provider spec pointing at this server.

        The model declares ``input: ["text", "image"]`` so ``inspect_part``
        renders actually reach the model inline instead of being replaced with
        Pi's "model does not support images" note.
        """
        return {
            "id": self.provider_id,
            "kind": "openai_compatible",
            "name": "Hephaestus Fake Provider",
            "baseUrl": self.base_url,
            "models": [
                {
                    "id": self.model_id,
                    "name": "Heph Fake Model",
                    "contextWindow": self.context_window,
                    "maxTokens": self.max_tokens,
                    "input": ["text", "image"],
                }
            ],
        }

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # -- turn selection (called from the handler thread) -------------------

    def next_turn(self, info: RequestInfo) -> Turn:
        with self._lock:
            resolver = self._script[self._cursor] if self._cursor < len(self._script) else None
            if resolver is not None:
                self._cursor += 1
        if resolver is None:
            return {"kind": "text", "chunks": ["HEPH_DONE"]}
        return resolver(info) if callable(resolver) else resolver


def _chunk(model: str, delta: dict[str, Any], finish: str | None) -> bytes:
    payload: dict[str, Any] = {
        "id": "chatcmpl-heph-fake",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if finish is not None:
        payload["usage"] = {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
    return f"data: {json.dumps(payload)}\n\n".encode()


def start_fake_openai(script: list[TurnResolver] | None = None) -> FakeOpenAI:
    """Start a threaded fake server on an ephemeral port."""
    fake_holder: dict[str, FakeOpenAI] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return  # silence access logs

        def do_POST(self) -> None:
            fake = fake_holder["fake"]
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            parsed = _parse_body(body)
            info = RequestInfo(
                index=len(fake.requests),
                roles=parsed["roles"],
                tool_names=parsed["tool_names"],
                has_tool_result=any(r == "tool" for r in parsed["roles"]),
                body_text=body,
            )
            fake.requests.append(info)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.end_headers()

            # Tool-less request => compaction/summarization: answer with text.
            if not info.tool_names:
                self._write_text(fake.model_id, ["COMPACTED: session summarized."])
                return
            turn = fake.next_turn(info)
            kind = turn.get("kind")
            if kind == "stall":
                self._safe_write(_chunk(fake.model_id, {"role": "assistant", "content": "…"}, None))
                # Hang until the client aborts the connection.
                try:
                    while True:
                        time.sleep(0.05)
                        self._safe_write(b": keep-alive\n\n")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            elif kind == "tool_calls":
                self._write_tool_calls(fake.model_id, turn["calls"])
            else:
                self._write_text(fake.model_id, turn.get("chunks", [""]))

        # -- writers -------------------------------------------------------

        def _safe_write(self, data: bytes) -> None:
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                raise

        def _write_text(self, model: str, chunks: list[str]) -> None:
            try:
                self._safe_write(_chunk(model, {"role": "assistant", "content": ""}, None))
                for part in chunks:
                    self._safe_write(_chunk(model, {"content": part}, None))
                self._safe_write(_chunk(model, {}, "stop"))
                self._safe_write(b"data: [DONE]\n\n")
            except OSError:
                return

        def _write_tool_calls(self, model: str, calls: list[dict[str, Any]]) -> None:
            tool_calls = [
                {
                    "index": i,
                    "id": call.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call.get("arguments", {})),
                    },
                }
                for i, call in enumerate(calls)
            ]
            try:
                self._safe_write(_chunk(model, {"role": "assistant", "content": ""}, None))
                self._safe_write(_chunk(model, {"tool_calls": tool_calls}, None))
                self._safe_write(_chunk(model, {}, "tool_calls"))
                self._safe_write(b"data: [DONE]\n\n")
            except OSError:
                return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake = FakeOpenAI(port=port, _server=server, _thread=thread, _script=list(script or []))
    fake_holder["fake"] = fake
    return fake


def _parse_body(body: str) -> dict[str, Any]:
    raw: object
    try:
        raw = json.loads(body or "{}")
    except json.JSONDecodeError:
        raw = {}
    obj: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    messages_raw = obj.get("messages")
    tools_raw = obj.get("tools")
    roles: list[str] = []
    if isinstance(messages_raw, list):
        for message in cast("list[Any]", messages_raw):
            if isinstance(message, dict):
                roles.append(str(cast("dict[str, Any]", message).get("role", "")))
            else:
                roles.append("")
    tool_names: list[str] = []
    if isinstance(tools_raw, list):
        for tool in cast("list[Any]", tools_raw):
            if not isinstance(tool, dict):
                continue
            fn = cast("dict[str, Any]", tool).get("function")
            if isinstance(fn, dict):
                fn_obj = cast("dict[str, Any]", fn)
                if "name" in fn_obj:
                    tool_names.append(str(fn_obj["name"]))
    return {"roles": roles, "tool_names": tool_names}
