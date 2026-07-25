"""Gate G2 — the delegation prompt contract through the REAL sidecar proxy.

The ``x-hephaestus-maxUtf8Bytes = 32768`` keyword is a *cross-language* contract:
Python enforces it in :mod:`hephaestus.agent_bridge.dispatch` (proved in
``tests/stage2/test_delegation_matrix.py``) and the generated TypeBox proxy
enforces it in the sidecar **before** the bridge request is built. Only a test
that drives ``node agent/dist/main.js`` can prove the second half at bridge
level: the assertion is not merely that the model sees an error, but that
``py.delegate`` **never reaches Python** — an oversized or ill-formed prompt is
refused on the model's side of the wire, never truncated into a smaller one that
would succeed.

``agent/test/tools_proxy.test.ts`` covers the same rule at unit level; this file
is the end-to-end half.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g2b import build_agent_dist, scaffold_project
from fake_openai import FakeOpenAI, RequestInfo, start_fake_openai
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.delegation import PROMPT_MAX_UTF8_BYTES
from hephaestus.agent_bridge.supervisor import pid_alive


class RecordingRuntime(BridgeRuntime):
    """A :class:`BridgeRuntime` that records every ``py.*`` request it answers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.py_calls: list[tuple[str, dict[str, Any]]] = []

    def _on_py_request(self, method: str, params: dict[str, Any]) -> Any:
        self.py_calls.append((method, dict(params)))
        return super()._on_py_request(method, params)

    def methods(self) -> list[str]:
        return [method for method, _params in self.py_calls]


class Harness:
    """The packaged sidecar + a scripted provider over one real project."""

    def __init__(self, root: Path, dist_main: Path) -> None:
        self.root = scaffold_project(root, name="delegation-bridge")
        self.fake: FakeOpenAI = start_fake_openai([])
        self.runtime = RecordingRuntime(
            project_root=self.root,
            providers=[self.fake.provider_spec()],
            dist_main=dist_main,
        )
        self.runtime.start()
        self.pids = [self.runtime.child_pid]

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.fake.close()

    def assert_no_orphans(self) -> None:
        for pid in self.pids:
            assert not pid_alive(pid), f"sidecar pid {pid} outlived the supervisor"


@pytest.fixture(scope="module")
def dist_main() -> Path:
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm are required to drive the packaged sidecar")
    return built[0]


@pytest.fixture
def harness(tmp_path: Path, dist_main: Path) -> Iterator[Harness]:
    h = Harness(tmp_path / "proj", dist_main)
    try:
        yield h
    finally:
        h.close()
        h.assert_no_orphans()


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"kind": "tool_calls", "calls": [{"name": name, "arguments": arguments, "id": call_id}]}


def text(chunk: str) -> dict[str, Any]:
    return {"kind": "text", "chunks": [chunk]}


def last_tool_message(info: RequestInfo) -> str:
    """The raw text of the most recent ``role: tool`` message the model was handed."""
    body = cast("dict[str, Any]", json.loads(info.body_text))
    for message in reversed(cast("list[Any]", body.get("messages", []))):
        if isinstance(message, dict) and message.get("role") == "tool":
            content = cast("dict[str, Any]", message).get("content")
            return content if isinstance(content, str) else json.dumps(content)
    return ""


def run_delegation(harness: Harness, prompt: str, *, session: str) -> str:
    """Script one ``delegate_part_agent`` call and return the tool text the model saw."""
    seen: dict[str, str] = {}

    def report(info: RequestInfo) -> dict[str, Any]:
        seen["tool"] = last_tool_message(info)
        return text("reported")

    harness.fake.set_script(
        [
            tool_call(
                "delegate_part_agent",
                {"part": "widget", "prompt": prompt, "delivery": "follow_up"},
                "d0",
            ),
            report,
        ]
    )
    session_id = harness.runtime.create_session("orchestrator", session_id=session)
    result = harness.runtime.prompt(session_id, "delegate the widget", timeout=300)
    assert result.status == "completed", result.status
    return seen.get("tool", "")


def test_delegation_prompt_at_the_cap_crosses_the_bridge(harness: Harness) -> None:
    """Exactly 32768 UTF-8 bytes is a valid prompt: the proxy forwards it."""
    at_cap = "a" * PROMPT_MAX_UTF8_BYTES
    assert len(at_cap.encode("utf-8")) == PROMPT_MAX_UTF8_BYTES
    run_delegation(harness, at_cap, session="cap-ok")

    delegates = [params for method, params in harness.runtime.py_calls if method == "py.delegate"]
    assert len(delegates) == 1, harness.runtime.methods()
    # The prompt arrived byte-for-byte: never truncated, never re-encoded.
    forwarded = str(delegates[0]["prompt"])
    assert forwarded == at_cap
    assert len(forwarded.encode("utf-8")) == PROMPT_MAX_UTF8_BYTES
    # The trusted invocation rides with it; the model never supplies it.
    assert isinstance(delegates[0]["invocation"], dict)
    assert delegates[0]["parent_run_id"]


def test_delegation_prompt_one_byte_over_the_cap_never_reaches_python(
    harness: Harness,
) -> None:
    """>32 KiB is rejected in the sidecar: no bridge request, no truncation."""
    over = "a" * (PROMPT_MAX_UTF8_BYTES + 1)
    tool_text = run_delegation(harness, over, session="cap-over")

    assert "py.delegate" not in harness.runtime.methods(), harness.runtime.methods()
    # The model is told the exact measurement and the cap it broke — evidence
    # that the prompt was *measured* in UTF-8 and refused, not shortened.
    assert str(PROMPT_MAX_UTF8_BYTES + 1) in tool_text, tool_text
    assert str(PROMPT_MAX_UTF8_BYTES) in tool_text, tool_text
    # …and no shortened prompt was smuggled through on a later call.
    assert not [p for m, p in harness.runtime.py_calls if m == "py.delegate"]


def test_delegation_prompt_over_the_cap_in_multibyte_bytes_not_code_points(
    harness: Harness,
) -> None:
    """The cap is exact UTF-8 bytes: half as many 2-byte characters is over."""
    # Half the cap in code points, one byte over the cap in UTF-8.
    over = "é" * (PROMPT_MAX_UTF8_BYTES // 2) + "é"
    assert len(over) < PROMPT_MAX_UTF8_BYTES
    assert len(over.encode("utf-8")) > PROMPT_MAX_UTF8_BYTES
    tool_text = run_delegation(harness, over, session="cap-utf8")
    assert "py.delegate" not in harness.runtime.methods()
    assert str(len(over.encode("utf-8"))) in tool_text, tool_text


def test_delegation_lone_surrogate_is_refused_by_the_sidecar(harness: Harness) -> None:
    """A ``\\ud800`` escape in the model's arguments never becomes a delegation.

    The provider emits a JSON ``\\ud800`` escape, so the sidecar really parses a
    lone UTF-16 surrogate out of the tool arguments — the case that would be
    silently coerced to U+FFFD by a naive JS implementation.
    """
    lone = "build the \ud800 widget"
    tool_text = run_delegation(harness, lone, session="surrogate")

    assert "py.delegate" not in harness.runtime.methods(), harness.runtime.methods()
    # The refusal names the offending scalar and its position, so the model can
    # repair it rather than guess.
    assert "surrogate" in tool_text and "D800" in tool_text.upper(), tool_text
    # No replacement-character coercion anywhere on the wire.
    assert "�" not in tool_text
