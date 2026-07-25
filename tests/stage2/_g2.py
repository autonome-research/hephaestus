"""Shared harness for the Stage-2 gate suite (mission Gate G2).

Everything here is *plumbing*: the gate assertions live in the ``test_g2_*``
modules. The rule of this file is that it adds no product behaviour — it only
composes what ``server/`` already ships so a gate test can drive the REAL
Node sidecar over the REAL private bridge into the REAL core.

It reuses the Stage-2A package-local harnesses verbatim (``server/tests``):

* :mod:`fake_openai` — the scripted OpenAI-compatible provider the sidecar talks
  to (``start_fake_openai``, ``RequestInfo``);
* :mod:`tools_fixture` — the scaffolded project + principals used by the
  dispatcher-level tests;
* :mod:`test_e2e_fake_model` — the scripting/assertion helpers (``tool_call``,
  ``last_tool_result``, ``assert_stream_shape``, …);
* ``server/tests/conftest.py`` — ``FakeClock`` / ``FakeLiveness`` / ``owner``
  (loaded under an alias so it can never collide with this suite's own
  ``conftest`` module name).

The one thing it *adds* is :class:`G2Runtime`: ``BridgeRuntime`` with the tool
families Stage 2A left unwired for the runtime slice — registries, delegation
and the ``query_snapshot`` vision child — plugged in, plus a recorder that
captures the trusted invocation metadata Python actually received. Gate clauses
about "every generated tool through the real bridge" need all 27 tools routed,
and clauses about scheduling/idempotency need to observe *what Python saw*.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER_TESTS = REPO / "server" / "tests"
REGISTRIES = REPO / "registries"
FIXTURES = REPO / "corpus" / "public_fixtures"

if str(SERVER_TESTS) not in sys.path:
    sys.path.insert(0, str(SERVER_TESTS))

from fake_openai import (  # noqa: E402
    FakeOpenAI,
    RequestInfo,
    TurnResolver,
    start_fake_openai,
)
from fake_openai import _chunk as fake_openai_chunk  # noqa: E402
from fake_openai import _parse_body as fake_openai_parse  # noqa: E402
from hephaestus.agent_bridge.app import BridgeRuntime, PromptResult  # noqa: E402
from hephaestus.agent_bridge.delegation import (  # noqa: E402
    DelegationRow,
    DelegationService,
)
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher  # noqa: E402
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError  # noqa: E402
from hephaestus.agent_bridge.query_snapshot import (  # noqa: E402
    SnapshotRequest,
    SnapshotResult,
    SnapshotUsage,
)
from hephaestus.agent_bridge.supervisor import pid_alive  # noqa: E402
from hephaestus.core.registry import RegistryOps, RegistrySet, load_registry  # noqa: E402
from opstore.types import TerminalState  # noqa: E402
from test_e2e_fake_model import (  # noqa: E402
    assert_stream_shape,
    events_of,
    kinds_of,
    last_tool_result,
    payload_of,
    text,
    tool_call,
)
from tools_fixture import (  # noqa: E402
    ORCH,
    PART_WIDGET,
    QUICK_WIDGET,
    Project,
    make_project,
    scaffold,
)

__all__ = [
    "FIXTURES",
    "ORCH",
    "PART_WIDGET",
    "QUICK_WIDGET",
    "REGISTRIES",
    "REPO",
    "FakeClock",
    "FakeLiveness",
    "FakeOpenAI",
    "G2Harness",
    "G2Runtime",
    "Project",
    "PromptResult",
    "RequestInfo",
    "ToolCallRecord",
    "assert_stream_shape",
    "build_sidecar",
    "events_of",
    "kinds_of",
    "last_tool_result",
    "make_project",
    "node_available",
    "owner",
    "payload_of",
    "registry_ops",
    "scaffold",
    "scaffold_project",
    "start_scripted_openai",
    "text",
    "tool_call",
    "tool_calls",
]


def _load_aliased(alias: str, path: Path) -> ModuleType:
    """Import a file under an explicit module name (avoids ``conftest`` clashes)."""
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


_server_conftest = _load_aliased("g2_server_conftest", SERVER_TESTS / "conftest.py")
FakeClock = _server_conftest.FakeClock
FakeLiveness = _server_conftest.FakeLiveness
owner = _server_conftest.owner


# --------------------------------------------------------------------------
# environment


def node_available() -> bool:
    return bool(os.environ.get("HEPHAESTUS_NODE") or shutil.which("node"))


def build_sidecar() -> Path:
    """Build the packaged sidecar once; skip cleanly when Node/pnpm are absent."""
    if not node_available():
        pytest.skip("node is not available; the G2 bridge tests need the packaged sidecar")
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        pytest.skip("pnpm is not available; cannot build the sidecar")
    agent_dir = REPO / "agent"
    build = subprocess.run(
        [pnpm, "--dir", str(agent_dir), "build"],
        capture_output=True,
        text=True,
        check=False,
    )
    dist_main = agent_dir / "dist" / "main.js"
    if build.returncode != 0 or not dist_main.exists():
        pytest.fail(f"sidecar build failed:\n{build.stdout}\n{build.stderr}")
    return dist_main


def scaffold_project(root: Path, *, name: str = "g2") -> Path:
    """A minimal but real project: manifest + globals + empty parts/ and checks/."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    (root / "globals.py").write_text("# Project-shared namespace.\nPARAMS = {}\n", encoding="utf-8")
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    return root


def registry_ops(store: Any, *, sandbox: bool = False) -> RegistryOps:
    """The shipped registries (skills/parts/materials) over a project's opstore."""
    registries = RegistrySet(
        {kind: load_registry(REGISTRIES / kind) for kind in ("skills", "parts", "materials")}
    )
    backend: Any = None
    if sandbox:
        from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, find_bwrap

        if find_bwrap() is not None:
            backend = BwrapBackend()
    return RegistryOps(registries, store, backend=backend)


# --------------------------------------------------------------------------
# scripting helpers


#: ``(request) -> summary text`` for the tool-less summarization/compaction call.
Summarizer = Callable[[RequestInfo], str]


def start_scripted_openai(summarizer: Summarizer) -> FakeOpenAI:
    """:func:`start_fake_openai`, but with a scriptable *summarization* reply.

    Pi's compaction issues a **tool-less** completion whose messages are the
    conversation being summarized and whose instructions are Hephaestus's pinned
    CAD summary. ``server/tests``'s fake answers those with a fixed string, which
    is enough for its own tests but not for the G2 context clause: proving that a
    post-compaction model can answer a pre-compaction decision requires the
    summarizer to behave like a model (read the conversation, write a summary).
    Everything else — turn scripting, the SSE encoding, the provider spec — is
    reused verbatim from :mod:`fake_openai`.
    """
    holder: dict[str, FakeOpenAI] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_POST(self) -> None:
            fake = holder["fake"]
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            parsed = cast("dict[str, Any]", fake_openai_parse(body))
            info = RequestInfo(
                index=len(fake.requests),
                roles=cast("list[str]", parsed["roles"]),
                tool_names=cast("list[str]", parsed["tool_names"]),
                has_tool_result=any(r == "tool" for r in cast("list[str]", parsed["roles"])),
                body_text=body,
            )
            fake.requests.append(info)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.end_headers()
            chunks = [summarizer(info)] if not info.tool_names else None
            if chunks is None:
                turn = fake.next_turn(info)
                if turn.get("kind") == "tool_calls":
                    self._write_tool_calls(fake.model_id, cast("list[Any]", turn["calls"]))
                    return
                chunks = [str(c) for c in cast("list[Any]", turn.get("chunks", [""]))]
            self._write_text(fake.model_id, chunks)

        def _write(self, data: bytes) -> None:
            self.wfile.write(data)
            self.wfile.flush()

        def _write_text(self, model: str, chunks: list[str]) -> None:
            try:
                self._write(fake_openai_chunk(model, {"role": "assistant", "content": ""}, None))
                for part in chunks:
                    self._write(fake_openai_chunk(model, {"content": part}, None))
                self._write(fake_openai_chunk(model, {}, "stop"))
                self._write(b"data: [DONE]\n\n")
            except OSError:
                return

        def _write_tool_calls(self, model: str, calls: list[Any]) -> None:
            payload = [
                {
                    "index": i,
                    "id": call.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call.get("arguments", {})),
                    },
                }
                for i, call in enumerate(cast("list[dict[str, Any]]", calls))
            ]
            try:
                self._write(fake_openai_chunk(model, {"role": "assistant", "content": ""}, None))
                self._write(fake_openai_chunk(model, {"tool_calls": payload}, None))
                self._write(fake_openai_chunk(model, {}, "tool_calls"))
                self._write(b"data: [DONE]\n\n")
            except OSError:
                return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake = FakeOpenAI(port=port, _server=server, _thread=thread)
    holder["fake"] = fake
    return fake


def tool_calls(*calls: tuple[str, dict[str, Any], str]) -> dict[str, Any]:
    """One assistant turn emitting several tool calls: ``(name, arguments, id)``."""
    return {
        "kind": "tool_calls",
        "calls": [
            {"name": name, "arguments": args, "id": call_id} for name, args, call_id in calls
        ],
    }


# --------------------------------------------------------------------------
# recording the Python side of the bridge


@dataclass
class ToolCallRecord:
    """One ``py.tool_dispatch`` (or ``py.delegate``) as Python received it."""

    tool: str
    session_id: str
    run_id: str
    invocation: dict[str, Any]
    arguments: dict[str, Any]
    at: float
    #: Monotonic time the dispatch returned (for sequencing assertions).
    done: float = 0.0
    ok: bool = True
    error: str | None = None
    #: Stable machine token from :class:`DispatchError` (``scope_denied``, …).
    reason: str | None = None

    @property
    def invocation_id(self) -> str:
        """The trusted key the dispatcher derives (session|entry|ordinal|call)."""
        inv = self.invocation
        return "|".join(
            (
                str(inv.get("session_id", "")),
                str(inv.get("entry_id", "")),
                str(inv.get("ordinal", 0)),
                str(inv.get("provider_call_id", "")),
            )
        )


@dataclass
class Recorder:
    """Ordered log of what crossed the bridge into Python, with timestamps."""

    calls: list[ToolCallRecord] = field(default_factory=list[ToolCallRecord])
    questions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    answers: list[tuple[float, Any]] = field(default_factory=list[tuple[float, Any]])

    def tools(self) -> list[str]:
        return [record.tool for record in self.calls]

    def by_tool(self, tool: str) -> list[ToolCallRecord]:
        return [record for record in self.calls if record.tool == tool]

    def first(self, tool: str) -> ToolCallRecord:
        matches = self.by_tool(tool)
        assert matches, f"no {tool!r} call reached Python (saw {self.tools()})"
        return matches[0]


class _RecordingDispatcher:
    """Wraps :class:`ToolDispatcher`, logging every dispatch and its outcome."""

    def __init__(self, inner: ToolDispatcher, recorder: Recorder) -> None:
        self.inner = inner
        self.recorder = recorder

    def dispatch(self, principal: Principal, params: dict[str, Any]) -> Any:
        raw_inv = params.get("invocation")
        record = ToolCallRecord(
            tool=str(params.get("tool", "")),
            session_id=str(params.get("session_id", "")),
            run_id=str(params.get("run_id", "")),
            invocation=dict(cast("dict[str, Any]", raw_inv or {})),
            arguments=dict(cast("dict[str, Any]", params.get("arguments") or {})),
            at=time.monotonic(),
        )
        self.recorder.calls.append(record)
        try:
            return self.inner.dispatch(principal, params)
        except Exception as exc:
            record.ok = False
            record.error = f"{type(exc).__name__}: {exc}"
            reason = getattr(exc, "reason", None)
            record.reason = str(reason) if isinstance(reason, str) else None
            raise
        finally:
            record.done = time.monotonic()


class ScriptedSnapshotCaller:
    """A vision child stand-in: fixed answer, bounded usage, no images returned."""

    def __init__(self, answer: str = "the shelf overhangs the gusset by ~4 mm") -> None:
        self.answer = answer
        self.requests: list[SnapshotRequest] = []

    async def call(self, request: SnapshotRequest) -> SnapshotResult:
        self.requests.append(request)
        return SnapshotResult(
            text=self.answer,
            refs=request.image_refs,
            usage=SnapshotUsage(output_tokens=12, input_tokens=64, turns=1, cost=0.0),
        )


class CompletingDelegationRunner:
    """A delegation coordinator stand-in: dispatch, then one COMPLETED terminal."""

    def __init__(self, artifact: str = "artifact:build:sha256:" + "d" * 64) -> None:
        self.artifact = artifact
        self.children: list[str] = []

    def run(self, service: DelegationService, row: DelegationRow) -> None:
        self.children.append(row.child_run_id)
        service.dispatch(row.delegation_ref)
        service.ingest_terminal(
            row.delegation_ref, TerminalState.COMPLETED, result_artifact_ref=self.artifact
        )


# --------------------------------------------------------------------------
# the runtime under test


class G2Runtime(BridgeRuntime):
    """``BridgeRuntime`` with the full Stage-2 tool surface wired + recording.

    Stage 2A wires the file/CAD families only; the gate needs the registry,
    delegation and snapshot families routed as well. The composition here is the
    same one ``server/tests`` uses for those families, hung off the runtime's own
    project store so a single ``state.db`` backs admission, delegation and CAS.

    ``py.delegate`` (the sidecar sends delegation over its own method, not
    ``py.tool_dispatch``) is routed back into the dispatcher, resolving the
    calling session from the *trusted invocation* metadata — the wire params
    themselves carry no ``session_id``.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        providers: list[dict[str, Any]],
        dist_main: Path,
        delegation: bool = True,
        registry: bool = True,
        snapshot: ScriptedSnapshotCaller | None = None,
        sandbox: bool = False,
        clock: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            project_root=project_root, providers=providers, dist_main=dist_main, **kwargs
        )
        self.recorder = Recorder()
        self.snapshot_caller = snapshot
        self.delegation_runner = CompletingDelegationRunner()
        self.delegation: DelegationService | None = None
        if delegation:
            self.delegation = DelegationService(self._store.admission, self._store.db, clock=clock)
        self.registry: RegistryOps | None = None
        if registry:
            self.registry = registry_ops(self._store, sandbox=sandbox)
        inner = ToolDispatcher(
            self._project,
            cad=self._cad,
            delegation=self.delegation,
            delegation_runner=self.delegation_runner,
            registry=self.registry,
            snapshot_caller=snapshot,
        )
        self._dispatcher = cast("ToolDispatcher", _RecordingDispatcher(inner, self.recorder))

    # -- py.* -------------------------------------------------------------

    def _on_py_request(self, method: str, params: dict[str, Any]) -> Any:
        if method == "py.delegate":
            return self._handle_delegate(params)
        if method == "py.ask_user":
            self.recorder.questions.append(dict(params))
            answer = super()._on_py_request(method, params)
            self.recorder.answers.append((time.monotonic(), answer))
            return answer
        return super()._on_py_request(method, params)

    def _handle_delegate(self, params: dict[str, Any]) -> Any:
        raw_inv = cast("dict[str, Any]", params.get("invocation") or {})
        session_id = str(raw_inv.get("session_id", ""))
        principal = self._principals.get(session_id)
        if principal is None:
            raise ProtocolError(
                ErrorCode.INVALID_PARAMS, f"py.delegate from unknown session {session_id!r}"
            )
        arguments: dict[str, Any] = {
            "part": params.get("part"),
            "prompt": params.get("prompt"),
        }
        for optional in ("delivery", "deadline_seconds"):
            if params.get(optional) is not None:
                arguments[optional] = params[optional]
        return self._dispatcher.dispatch(
            principal,
            {
                "session_id": session_id,
                "run_id": str(params.get("parent_run_id", "")),
                "tool": "delegate_part_agent",
                "arguments": arguments,
                "invocation": raw_inv,
            },
        )

    # -- test conveniences -------------------------------------------------

    def sidecar_call(
        self, method: str, params: dict[str, Any], *, timeout: float | None = None
    ) -> Any:
        """Issue a raw bridge request (``session.compact``, ``query.snapshot``, …)."""
        return self._sup.call(method, params, timeout=timeout)


class G2Harness:
    """A started :class:`G2Runtime` plus its scripted provider (fake model)."""

    def __init__(
        self,
        project_root: Path,
        dist_main: Path,
        *,
        vision: bool = True,
        snapshot: bool = False,
        answerer: Any = None,
        summarizer: Summarizer | None = None,
        **wiring: Any,
    ) -> None:
        self.project_root = project_root
        self.fake: FakeOpenAI = (
            start_fake_openai([]) if summarizer is None else start_scripted_openai(summarizer)
        )
        spec = self.fake.provider_spec()
        if not vision:
            # A text-only ACTIVE model: renders cannot ride into this model.
            models = cast("list[dict[str, Any]]", spec["models"])
            models[0]["input"] = ["text"]
        self.snapshot_caller = ScriptedSnapshotCaller() if snapshot else None
        self.runtime = G2Runtime(
            project_root=project_root,
            providers=[spec],
            dist_main=dist_main,
            snapshot=self.snapshot_caller,
            answerer=answerer,
            **wiring,
        )
        self.runtime.start()
        self.child_pids: list[int] = [self.runtime.child_pid]

    # -- passthroughs ------------------------------------------------------

    @property
    def recorder(self) -> Recorder:
        return self.runtime.recorder

    def set_script(self, script: list[TurnResolver]) -> None:
        self.fake.set_script(script)

    def create_session(self, profile: str, **kwargs: Any) -> str:
        return self.runtime.create_session(profile, **kwargs)

    def prompt(self, session_id: str, message: str, **kwargs: Any) -> PromptResult:
        return self.runtime.prompt(session_id, message, **kwargs)

    def track_child(self) -> None:
        self.child_pids.append(self.runtime.child_pid)

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.fake.close()

    def assert_no_orphans(self) -> None:
        for pid in self.child_pids:
            assert not pid_alive(pid), f"sidecar pid {pid} outlived the supervisor"


# --------------------------------------------------------------------------
# assertions shared by several gate modules


def streamed_text(result: PromptResult) -> str:
    """The model's streamed assistant text for a run."""
    return "".join(payload_of(ev)["text"] for ev in events_of(result, "text_delta"))


def called_tools(result: PromptResult) -> list[str]:
    """Public tool-call event names, in order."""
    return [payload_of(ev)["name"] for ev in events_of(result, "tool_call")]


def model_tool_names(fake: FakeOpenAI) -> list[str]:
    """The tool names the sidecar advertised to the model on its last request."""
    assert fake.requests, "the model was never called"
    return list(fake.requests[-1].tool_names)
