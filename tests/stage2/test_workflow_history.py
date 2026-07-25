"""Gate G2 — bounded historical reads: frozen high-water cursors, no Pi JSONL in Python.

Digest §2: a *private bounded bridge method* reads Pi's JSONL through Pi's own
session API, normalizes it into the public Hephaestus event vocabulary, and
**freezes a first-page high-water mark into opaque cursors**; HTTP/CLI serve only
that normalized snapshot, and Python never parses Pi JSONL directly.

The Stage 2A e2e suite only checks that one page comes back after a restart.
This file proves the two clauses that make the contract real:

* pagination is **frozen**: a page taken after the session has grown returns the
  events of the snapshot the first page froze — never the newer ones — while a
  fresh (cursor-less) read does see them;
* the same public events reconstruct **after a process restart**, byte for byte,
  through the resumed session;
* and the Python side has no Pi-JSONL parsing at all — proved over the import
  graph of ``hephaestus.agent_bridge`` / ``hephaestus.core``, so the only route
  to a transcript is the bridge method.
"""

from __future__ import annotations

import ast
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g2b import REPO_ROOT, build_agent_dist, scaffold_project
from fake_openai import FakeOpenAI, start_fake_openai
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.supervisor import pid_alive

WIDGET_SRC = """body = Box(20.0, 10.0, 4.0)
body.label = "widget_body"
part.geometry = body
"""

#: Normalized events per scripted turn: 8 tool calls in one assistant message
#: (8 ``tool_call`` events) plus their 8 tool-result entries.
EVENTS_PER_TURN = 16
#: ``agent/src/session/history.ts`` HISTORY_PAGE_SIZE.
HISTORY_PAGE_SIZE = 250
#: Enough turns to need more than one page.
TURNS = 20
#: ``TURNS`` tool-call turns plus the closing assistant text turn.
TRANSCRIPT_EVENTS = TURNS * EVENTS_PER_TURN + 1

MARKER = "SECOND-TURN-MARKER"


class Harness:
    """The packaged sidecar over one real project, with a scripted provider."""

    def __init__(self, root: Path, dist_main: Path) -> None:
        self.root = scaffold_project(root, name="history")
        (self.root / "parts" / "widget.py").write_text(WIDGET_SRC, encoding="utf-8")
        self.dist_main = dist_main
        self.fake: FakeOpenAI = start_fake_openai([])
        self.runtime = BridgeRuntime(
            project_root=self.root,
            providers=[self.fake.provider_spec()],
            dist_main=dist_main,
        )
        self.runtime.start()
        self.pids = [self.runtime.child_pid]

    def restart(self) -> None:
        old = self.runtime.child_pid
        os.kill(old, 9)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and pid_alive(old):
            time.sleep(0.05)
        assert not pid_alive(old)
        self.runtime.restart()
        self.pids.append(self.runtime.child_pid)

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


def parallel_reads(count: int, turn: int) -> dict[str, Any]:
    """One assistant message carrying ``count`` read-only tool calls."""
    return {
        "kind": "tool_calls",
        "calls": [
            {"name": "read_part", "arguments": {"name": "widget"}, "id": f"t{turn}-{i}"}
            for i in range(count)
        ],
    }


def transcript_script(turns: int) -> list[Any]:
    script: list[Any] = []
    for turn in range(turns):
        script.append(parallel_reads(EVENTS_PER_TURN // 2, turn))
    script.append({"kind": "text", "chunks": ["transcript built"]})
    return script


def read_all_pages(harness: Harness, session_id: str) -> list[dict[str, Any]]:
    """Page a session's normalized history to exhaustion, following its cursors."""
    events: list[dict[str, Any]] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = harness.runtime.history_page(session_id, cursor)
        events.extend(cast("list[dict[str, Any]]", page["events"]))
        pages += 1
        assert pages < 50, "history paging did not terminate"
        raw_cursor = page.get("cursor")
        if page["done"] is True or raw_cursor is None:
            assert page["cursor"] is None
            break
        cursor = str(raw_cursor)
    return events


def build_transcript(harness: Harness, session_id: str) -> None:
    harness.fake.set_script(transcript_script(TURNS))
    result = harness.runtime.prompt(session_id, "read the widget many times", timeout=600)
    assert result.status == "completed", result.status


def test_workflow_history_freezes_a_high_water_cursor(harness: Harness) -> None:
    session_id = harness.runtime.create_session("part", part="widget", session_id="hist-freeze")
    build_transcript(harness, session_id)

    # The first page freezes the high-water mark and hands back a cursor.
    first = harness.runtime.history_page(session_id)
    events = cast("list[dict[str, Any]]", first["events"])
    assert len(events) == HISTORY_PAGE_SIZE, len(events)
    assert first["done"] is False
    cursor = str(first["cursor"])
    assert cursor and cursor == str(first["cursor"])

    # The session now grows underneath the paginator.
    harness.fake.set_script([{"kind": "text", "chunks": [MARKER]}])
    grown = harness.runtime.prompt(session_id, "say the marker", timeout=300)
    assert grown.status == "completed"

    # Continuing from the frozen cursor never sees the new entries.
    rest: list[dict[str, Any]] = []
    token: str | None = cursor
    while token is not None:
        page = harness.runtime.history_page(session_id, token)
        rest.extend(cast("list[dict[str, Any]]", page["events"]))
        token = None if page["cursor"] is None else str(page["cursor"])
    frozen = events + rest
    assert MARKER not in json.dumps(frozen)
    # The frozen snapshot is exactly the pre-growth transcript.
    assert len(frozen) == TRANSCRIPT_EVENTS, len(frozen)

    # A cursor-less read freezes a *new* high-water mark, which does include it.
    refreshed = read_all_pages(harness, session_id)
    assert MARKER in json.dumps(refreshed)
    assert len(refreshed) > len(frozen)
    # The frozen prefix is a genuine prefix of the newer snapshot: append-only.
    assert refreshed[: len(frozen)] == frozen


def test_workflow_history_reconstructs_the_same_events_after_a_restart(
    harness: Harness,
) -> None:
    session_id = harness.runtime.create_session("part", part="widget", session_id="hist-restart")
    build_transcript(harness, session_id)

    before = read_all_pages(harness, session_id)
    assert len(before) == TRANSCRIPT_EVENTS
    # Every record is a public Hephaestus event; no Pi/bridge vocabulary leaks.
    for event in before:
        assert set(event) <= {"run_id", "seq", "kind", "tool_call_id", "payload"}
        assert event["kind"] in {
            "tool_call",
            "tool_result",
            "text_delta",
            "thought",
            "image",
            "audit",
        }
        assert "jsonrpc" not in event and "hv" not in event
    seqs = [int(event["seq"]) for event in before]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    # kill -9 the sidecar, respawn it, resume the persisted session.
    harness.restart()
    resumed = harness.runtime.resume_session("part", session_id, part="widget")
    assert resumed == session_id

    after = read_all_pages(harness, session_id)
    assert after == before, "the normalized history changed across a restart"


# ---------------------------------------------------------------------------
# the import-graph clause: no Python module parses Pi JSONL


def python_modules(package: Path) -> Iterator[tuple[Path, str]]:
    for path in sorted(package.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def string_constants(source: str) -> list[str]:
    return [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def jsonl_filenames(source: str) -> list[str]:
    """String constants that *name* a JSONL file (prose mentions are not paths)."""
    return [value for value in string_constants(source) if value.endswith(".jsonl")]


def test_workflow_history_no_python_module_parses_pi_jsonl() -> None:
    """No Python package names a ``.jsonl`` transcript except the bench archives."""
    bridge = REPO_ROOT / "server" / "src" / "hephaestus" / "agent_bridge"
    core = REPO_ROOT / "core" / "src" / "hephaestus" / "core"
    bench = REPO_ROOT / "server" / "src" / "hephaestus" / "bench"

    for package in (bridge, core):
        for path, source in python_modules(package):
            offenders = jsonl_filenames(source)
            assert offenders == [], f"{path} names a JSONL file: {offenders}"

    # The bench harness writes its *own* archives; it reads no Pi transcript.
    archives: set[str] = set()
    for _path, source in python_modules(bench):
        archives.update(jsonl_filenames(source))
    assert archives == {"runs.jsonl", "events.jsonl"}, archives


def test_workflow_history_python_reaches_transcripts_only_through_the_bridge() -> None:
    """``history.page`` is the sole Python entry point, and it is an RPC call."""
    bridge = REPO_ROOT / "server" / "src" / "hephaestus" / "agent_bridge"
    callers: dict[Path, list[str]] = {}
    for path, source in python_modules(bridge):
        if "history.page" not in string_constants(source):
            continue
        tree = ast.parse(source)
        methods: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and first.value == "history.page":
                methods.append(node.func.attr)
        callers[path] = methods

    # Exactly two modules mention it: the frozen method registry and the runtime.
    assert {path.name for path in callers} == {"protocol.py", "app.py"}, sorted(
        path.name for path in callers
    )
    # …and the runtime's only use is a supervisor request, never a file read.
    assert callers[bridge / "app.py"] == ["call"]
    assert callers[bridge / "protocol.py"] == []

    # Nothing in the bridge reaches into the sidecar's app-owned agent directory.
    for path, source in python_modules(bridge):
        for value in string_constants(source):
            assert "sessions/" not in value, f"{path} addresses a Pi session directory"
