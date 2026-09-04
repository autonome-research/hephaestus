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
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.testing.fake_openai import FakeOpenAI, start_fake_openai

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
    #
    # AMENDMENT (INTERFACE.md §2.8(1), 2026-09-03): ``turn`` joins the closed
    # set. It is public history-page vocabulary, not Pi's and not the bridge's —
    # the 0-based ordinal of the user message whose turn recorded the event,
    # counted over the frozen entry slice. The set stays CLOSED rather than
    # becoming a subset-of-anything: it is the guard that would catch a real
    # leak, and widening it by one named field is not the same as removing it.
    for event in before:
        assert set(event) <= {"run_id", "seq", "kind", "tool_call_id", "payload", "turn"}
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


#: Callables that turn a string literal into a filesystem path or open one.
PATH_BUILDERS = frozenset(
    {
        "Path",
        "PurePath",
        "open",
        "join",
        "joinpath",
        "glob",
        "rglob",
        "iterdir",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
    }
)


def session_path_literals(source: str) -> list[str]:
    """String literals this module builds a *filesystem path* from that name a session store.

    Two structural forms, which together are how a Python module could reach the
    sidecar's app-owned session directory at all: a ``pathlib`` division join
    (``agent_dir / "sessions"``) and a literal handed to a path builder
    (``Path("sessions/x")``, ``os.path.join(root, "sessions")``, ``open(...)``).
    Prose, JSON keys, and URL routes are structurally excluded because none of
    them is an operand of a path construction.
    """
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            for operand in (node.left, node.right):
                if (
                    isinstance(operand, ast.Constant)
                    and isinstance(operand.value, str)
                    and "session" in operand.value
                ):
                    offenders.append(operand.value)
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in PATH_BUILDERS:
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and "session" in arg.value
                ):
                    offenders.append(arg.value)
    return offenders


def method_def(source: str, name: str) -> ast.FunctionDef:
    """The ``def`` node of one method, so a clause can be checked over its body alone."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"method went missing: {name}")


def dotted_target(func: ast.expr) -> str:
    """Render a call's callee as a dotted name (``self._sup.call``, ``open``)."""
    parts: list[str] = []
    node: ast.expr = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.append(node.id if isinstance(node, ast.Name) else f"<{type(node).__name__}>")
    return ".".join(reversed(parts))


def call_targets(node: ast.AST) -> list[str]:
    """Every callee inside ``node``, dotted, in walk order."""
    return [dotted_target(call.func) for call in ast.walk(node) if isinstance(call, ast.Call)]


def module_level_names(source: str) -> set[str]:
    """Names this module itself defines at top level (its own helpers and types)."""
    return {
        node.name
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }


def test_workflow_history_no_python_module_parses_pi_jsonl() -> None:
    """No Python package names a ``.jsonl`` transcript except the bench archives."""
    bridge = REPO_ROOT / "server" / "src" / "hephaestus" / "agent_bridge"
    core = REPO_ROOT / "core" / "src" / "hephaestus" / "core"
    geom = REPO_ROOT / "core" / "src" / "hephaestus" / "geom"
    bench = REPO_ROOT / "bench" / "src" / "hephaestus" / "bench"
    # A stale path would scan nothing and pass vacuously; fail loudly instead.
    for package in (bridge, core, geom, bench):
        assert package.is_dir(), f"package path went stale: {package}"

    for package in (bridge, core, geom):
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
    #
    # AMENDMENT (2026-09-03 — INTERFACE.md §2.8(6)). The literal no longer names
    # ``self._sup.call`` directly: every session-scoped request now goes through
    # ``BridgeRuntime._call_for_session``, the one seam that re-adopts a session
    # the sidecar has forgotten and retries **exactly once**, so a transcript
    # that exists intact on disk stops answering an unnamed 500. Renaming the
    # expected literal alone would rename *past* the clause this test exists for,
    # so it is checked in two halves: the ``history.page`` literal reaches the
    # seam, and the seam's own body reaches nothing but the supervisor.
    assert callers[bridge / "app.py"] == ["_call_for_session"]
    assert callers[bridge / "protocol.py"] == []

    runtime_source = (bridge / "app.py").read_text(encoding="utf-8")
    seam = call_targets(method_def(runtime_source, "_call_for_session"))
    # The seam speaks to the supervisor and to nothing else that could be a
    # transport: the first attempt and the single retry, both ``Supervisor.call``.
    assert [target for target in seam if target.startswith("self._sup.")] == [
        "self._sup.call",
        "self._sup.call",
    ], seam
    # …and every *other* call it makes is its own method or this module's own
    # helper — never ``open``, ``Path``, or anything reached through an import.
    # That is the half a rename would have dropped: it still catches a future
    # edit that healed a forgotten session by reading the JSONL itself.
    strays = [
        target
        for target in seam
        if not target.startswith("self.") and target not in module_level_names(runtime_source)
    ]
    assert strays == [], strays

    # Nothing in the bridge reaches into the sidecar's app-owned agent directory.
    #
    # AMENDMENT (Stage 4 — INTERFACE.md §2.1, §2.3, §2.7). This clause used to be
    # spelled ``"sessions/" not in value`` over *every* string constant. Stage 4
    # makes ``sessions`` the first segment of the owning server's route table and
    # a key in its JSON and WebSocket frames, so ``heph agent`` in client mode
    # (``client_mode.py``) now legitimately carries ``"/sessions/"``,
    # ``body.get("sessions", [])`` and ``{"subscribe": {"sessions": [...]}}``.
    # Addressing a *route* on the process that owns the leases is the exact
    # opposite of reaching past it into its files, so the substring form had
    # become a false positive on the topology §2.1 requires.
    #
    # The replacement tests what the clause means — filesystem addressing — and
    # is net *stronger*: it catches ``agent_dir / "sessions"`` and
    # ``os.path.join(root, "sessions")``, neither of which contains the substring
    # ``sessions/`` and both of which the old form missed entirely. The blunt ban
    # on naming a ``.jsonl`` transcript is unchanged and still applies above.
    for path, source in python_modules(bridge):
        offenders = session_path_literals(source)
        assert offenders == [], f"{path} builds a Pi session directory path: {offenders}"
