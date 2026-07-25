"""G3: the recorded Claude Code bracket-101 session replays against the live server.

The fixture is a real ``claude`` CLI session (stream-json transcript) that drove
``heph serve --mcp`` end to end: open -> read globals -> create -> write ->
build -> checks/measures -> export STEP. The replay re-executes the recorded
authoring calls in order against a freshly seeded bracket-101 project through
the in-process MCP app and asserts the same terminal evidence: a clean build,
every acceptance check passing, and a STEP export.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import Client
from hephaestus.bench.harness import grade, load_tasks, seed_project
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.mcp.app import build_app

FIXTURE = Path(__file__).parent / "fixtures" / "claude_code_bracket101"

#: The authoring calls that must replay verbatim; read-only calls are elided
#: (they cannot change the outcome and their responses are session-relative).
REPLAYED_TOOLS = {"create_part", "write_part", "edit_part", "build_part", "export_part"}


def load_recorded_calls() -> list[dict[str, Any]]:
    meta = json.loads((FIXTURE / "meta.json").read_text())
    return [c for c in meta["calls"] if c["tool"] in REPLAYED_TOOLS]


@pytest.fixture()
def seeded_project(tmp_path: Path) -> Path:
    task = {t.id: t for t in load_tasks()}["bracket-101"]
    root = tmp_path / "project"
    seed_project(task, root)
    return root


def structured(result: Any) -> dict[str, Any]:
    content = cast("dict[str, Any] | None", result.structured_content)
    assert content is not None
    return content


def test_recorded_session_replays_to_a_passing_bracket(seeded_project: Path) -> None:
    calls = load_recorded_calls()
    assert [c["tool"] for c in calls][:3] == ["create_part", "write_part", "build_part"]

    _, runtime = build_app(backend=UnsafeLocalBackend())

    async def scenario() -> None:
        content_hash: str | None = None
        exported = False
        async with Client(runtime.app) as client:
            await client.call_tool("open_project", {"path": str(seeded_project)})
            for call in calls:
                args = dict(call["arguments"])
                # CAS hashes are session-relative: rebind to the live hash chain.
                if call["tool"] in {"write_part", "edit_part"} and content_hash is not None:
                    args["expected_hash"] = content_hash
                result = structured(await client.call_tool(call["tool"], args))
                if call["tool"] == "create_part":
                    content_hash = str(result["content_hash"])
                elif call["tool"] in {"write_part", "edit_part"}:
                    assert result.get("applied", True), result
                    content_hash = str(result["content_hash"])
                elif call["tool"] == "build_part":
                    assert result["status"] == "ok", result.get("error")
                elif call["tool"] == "export_part":
                    exported = True
                    assert result["paths"], result
        assert exported, "the recorded session must end in a STEP export"

    try:
        asyncio.run(scenario())
    finally:
        runtime.close()

    task = {t.id: t for t in load_tasks()}["bracket-101"]
    report = grade(task, seeded_project, tool_calls=len(calls))
    assert report.passed, report.reasons


def test_fixture_transcript_is_a_complete_claude_code_session() -> None:
    lines = (FIXTURE / "session.jsonl").read_text().splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    kinds = {e.get("type") for e in events}
    assert {"system", "assistant", "result"} <= kinds
    result = next(e for e in events if e.get("type") == "result")
    assert result.get("is_error") is False
    meta = json.loads((FIXTURE / "meta.json").read_text())
    assert meta["graded_passed"] is True
    assert meta["tool_calls"] >= 10
