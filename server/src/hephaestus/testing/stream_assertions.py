"""Scripting turns for the fake model and reading back what the bridge streamed.

Two halves of one loop. :func:`tool_call` / :func:`text` build the turn payloads
:mod:`hephaestus.testing.fake_openai` replays; :func:`last_tool_result`,
:func:`kinds_of`, :func:`events_of`, :func:`payload_of` and
:func:`assert_stream_shape` read the other end — the public event stream a
:class:`~hephaestus.agent_bridge.app.PromptResult` carries, plus the exact bytes
the model saw for a tool result.

:func:`assert_stream_shape` is the invariant every bridge suite re-asserts: a
streamed record is a well-formed *public* event (known kind, monotonic unique
sequence, no bridge/JSON-RPC vocabulary leaking through).
"""

from __future__ import annotations

import json
from typing import Any, cast

from hephaestus.agent_bridge.app import PromptResult

from .fake_openai import RequestInfo

__all__ = [
    "assert_stream_shape",
    "events_of",
    "kinds_of",
    "last_tool_result",
    "payload_of",
    "text",
    "tool_call",
]

#: The complete public event vocabulary a run may stream.
PUBLIC_EVENT_KINDS = frozenset(
    {
        "text_delta",
        "thought",
        "tool_call",
        "tool_result",
        "image",
        "question",
        "answer",
        "audit",
        "progress",
        "terminal",
    }
)


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "c0") -> dict[str, Any]:
    """One assistant turn emitting a single tool call."""
    return {
        "kind": "tool_calls",
        "calls": [{"name": name, "arguments": arguments, "id": call_id}],
    }


def text(*chunks: str) -> dict[str, Any]:
    """One assistant turn streaming ``chunks`` as assistant text."""
    return {"kind": "text", "chunks": list(chunks)}


def last_tool_result(info: RequestInfo) -> dict[str, Any]:
    """The JSON body of the most recent tool result in the request transcript.

    This is exactly what a real model would read: the proxy's bounded text
    rendering of the tool result (base64 image bytes are stripped from the text
    and ride as separate image content blocks).
    """
    body = cast("dict[str, Any]", json.loads(info.body_text))
    messages = cast("list[Any]", body.get("messages", []))
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        entry = cast("dict[str, Any]", message)
        if entry.get("role") != "tool":
            continue
        content = entry.get("content")
        raw = content if isinstance(content, str) else json.dumps(content)
        try:
            # raw_decode: the rendering may be followed by provider-side notes.
            parsed, _end = json.JSONDecoder().raw_decode(raw.lstrip())
        except json.JSONDecodeError:
            return {"_text": raw}
        if isinstance(parsed, dict):
            return cast("dict[str, Any]", parsed)
        return {"_value": parsed}
    return {}


def kinds_of(result: PromptResult) -> list[str]:
    """The ordered event kinds a run streamed."""
    return result.kinds()


def events_of(result: PromptResult, kind: str) -> list[dict[str, Any]]:
    """Every streamed event of one kind, in order."""
    return [ev for ev in result.events if ev.get("kind") == kind]


def payload_of(event: dict[str, Any]) -> dict[str, Any]:
    """An event's payload mapping (empty when it carries none)."""
    payload = event.get("payload")
    return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}


def assert_stream_shape(result: PromptResult) -> None:
    """Every streamed record is a well-formed public Hephaestus event."""
    seqs: list[int] = []
    for ev in result.events:
        assert set(ev) <= {"run_id", "seq", "kind", "tool_call_id", "payload"}, ev
        assert ev["run_id"] == result.run_id
        assert ev["kind"] in PUBLIC_EVENT_KINDS, ev["kind"]
        assert isinstance(ev["seq"], int)
        seqs.append(int(ev["seq"]))
        # No bridge/JSON-RPC vocabulary may leak into a public event.
        assert "jsonrpc" not in ev and "hv" not in ev and "method" not in ev
    assert seqs == sorted(seqs), "event sequence numbers must be monotonic per run"
    assert len(set(seqs)) == len(seqs), "event sequence numbers must be unique per run"
