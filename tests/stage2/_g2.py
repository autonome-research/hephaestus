"""Shared harness for the Stage-2 gate suite (mission Gate G2).

Everything here is *plumbing*: the gate assertions live in the ``test_g2_*``
modules. The rule of this file is that it adds no product behaviour — it only
composes what ``server/`` already ships so a gate test can drive the REAL
Node sidecar over the REAL private bridge into the REAL core.

It reuses the shipped-but-private test-support package verbatim
(:mod:`hephaestus.testing`):

* :mod:`~hephaestus.testing.fake_openai` — the scripted OpenAI-compatible
  provider the sidecar talks to (``start_fake_openai``, ``RequestInfo``);
* :mod:`~hephaestus.testing.tools_fixture` — the scaffolded project + principals
  used by the dispatcher-level tests;
* :mod:`~hephaestus.testing.stream_assertions` — the scripting/assertion helpers
  (``tool_call``, ``last_tool_result``, ``assert_stream_shape``, …);
* :mod:`~hephaestus.testing.doubles` — ``FakeClock`` / ``FakeLiveness`` /
  ``owner``;
* :mod:`~hephaestus.testing.sidecar` — the one-per-process ``agent/dist`` build.

The one thing it *adds* is :class:`G2Runtime`: the shipped ``BridgeRuntime``
with a recorder over its dispatcher, so clauses about scheduling and idempotency
can observe the trusted invocation metadata Python actually received, plus
scripted stand-ins for the two capabilities that need a live child run (the
``query_snapshot`` vision child and the delegation coordinator), handed over
through the shipped ``bind_runtime`` seam. It does **not** wire the tool
families any more: registries and the delegation service are resolved by
``hephaestus.agent_bridge.wiring.build_dispatcher``, the one place every shipped
runtime asks. It used to wire them here, and that is exactly why the gate stayed
green through audit-2026-09-04-broken.md's B-2 — a harness that composes the
product's capabilities tests a runtime that does not ship.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, PromptResult
from hephaestus.agent_bridge.delegation import DelegationRow, DelegationService
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.agent_bridge.query_snapshot import SnapshotRequest, SnapshotResult, SnapshotUsage
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.testing.doubles import FakeClock, FakeLiveness, owner
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, TurnResolver, start_fake_openai
from hephaestus.testing.fake_openai import _chunk as fake_openai_chunk
from hephaestus.testing.fake_openai import _parse_body as fake_openai_parse
from hephaestus.testing.projects import scaffold_project as _scaffold_project
from hephaestus.testing.sidecar import build_agent_dist, node_available
from hephaestus.testing.stream_assertions import (
    assert_stream_shape,
    events_of,
    kinds_of,
    last_tool_result,
    payload_of,
    text,
    tool_call,
)
from hephaestus.testing.tools_fixture import (
    ORCH,
    PART_WIDGET,
    QUICK_WIDGET,
    Project,
    make_project,
    scaffold,
)
from opstore.types import TerminalState

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"
FIXTURES = REPO / "corpus" / "public_fixtures"

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
    "scaffold",
    "scaffold_project",
    "start_scripted_openai",
    "text",
    "tool_call",
    "tool_calls",
]


# --------------------------------------------------------------------------
# environment


def build_sidecar() -> Path:
    """Build the packaged sidecar once; skip cleanly when Node/pnpm are absent."""
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; the G2 bridge tests need the packaged sidecar")
    return built[0]


def scaffold_project(root: Path, *, name: str = "g2", seed_ledger: bool = True) -> Path:
    """A minimal but real project: manifest + globals + empty parts/ and checks/.

    ``seed_ledger`` defaults on for the same reason it does upstream: §2 refuses
    every build while the requirement ledger is empty. Turn it off in the tests
    that record (and assert on) a ledger of their own.
    """
    return _scaffold_project(
        root,
        name=name,
        globals_src="# Project-shared namespace.\nPARAMS = {}\n",
        seed_ledger=seed_ledger,
    )


def _sandbox_backend() -> ExecBackend | None:
    """The probed bwrap backend registry generators run under, when the host has one.

    ``heph agent`` injects no backend, so ``instance_store_part`` refuses there
    with ``capability_not_available`` — the contract
    ``core/registry/_ops.py`` states, and the honest answer until the sandbox
    blocker named in audit-2026-09-04-broken.md is cleared. Supplying one here
    is what lets the gate prove the generator path itself.
    """
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, find_bwrap

    return BwrapBackend() if find_bwrap() is not None else None


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

    def bind_runtime(self, **capabilities: Any) -> None:
        """Pass the live-sidecar capabilities through to the wrapped dispatcher."""
        self.inner.bind_runtime(**capabilities)

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
    """The **shipped** ``BridgeRuntime``, recording what crossed the bridge.

    This class used to construct the registry set, the delegation service and
    the dispatcher itself, and to override ``_on_py_request`` with the
    ``py.delegate`` routing production was missing. That is why the gate was
    green while nine model-visible tools refused in every shipped runtime
    (audit-2026-09-04-broken.md B-2/B-3): every G2 clause exercised a runtime
    that did not ship. All of it now lives in ``server/`` — the capability set
    in :mod:`hephaestus.agent_bridge.wiring`, the delegation routing in
    :meth:`BridgeRuntime._handle_delegate` — and this subclass adds only what a
    *test* legitimately owns:

    * a recording decorator over the shipped dispatcher, so clauses about
      scheduling and idempotency can observe what Python actually received;
    * the two **live-sidecar** capabilities, scripted and handed over through
      the shipped :meth:`~hephaestus.agent_bridge.dispatch.ToolDispatcher.bind_runtime`
      seam rather than by rebuilding the dispatcher: a scripted vision child and
      a scripted delegation coordinator. Production supplies neither yet — both
      would have to call the sidecar from inside a ``py.*`` handler, which is
      the reader-thread deadlock ``app.py`` documents — so scripting them is the
      only way to drive the child-run clauses at all, and doing it through
      ``bind_runtime`` means the *rest* of the surface is the shipped one.
    * ``sandbox=True`` supplies the probed bwrap backend registry generators run
      under. ``heph agent`` has none (``CadOpsState`` defaults to the unsafe
      local backend), so ``instance_store_part`` refuses there by design; the
      gate proves the generator path itself works when a secure backend exists.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        providers: list[dict[str, Any]],
        dist_main: Path,
        snapshot: ScriptedSnapshotCaller | None = None,
        sandbox: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            project_root=project_root,
            providers=providers,
            dist_main=dist_main,
            backend=_sandbox_backend() if sandbox else None,
            **kwargs,
        )
        self.recorder = Recorder()
        self.snapshot_caller = snapshot
        self.delegation_runner = CompletingDelegationRunner()
        self._dispatcher = cast(
            "ToolDispatcher", _RecordingDispatcher(self._dispatcher, self.recorder)
        )

    def _bind_runtime_capabilities(self) -> None:
        """Script the two capabilities a live sidecar would own; keep the rest."""
        super()._bind_runtime_capabilities()
        self._dispatcher.bind_runtime(
            snapshot_caller=self.snapshot_caller, delegation_runner=self.delegation_runner
        )

    # -- py.* -------------------------------------------------------------

    def _on_py_request(self, method: str, params: dict[str, Any]) -> Any:
        if method == "py.ask_user":
            self.recorder.questions.append(dict(params))
            answer = super()._on_py_request(method, params)
            self.recorder.answers.append((time.monotonic(), answer))
            return answer
        return super()._on_py_request(method, params)

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
