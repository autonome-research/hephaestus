"""``py.delegate`` on the shipped ``BridgeRuntime`` (audit-2026-09-04-broken.md B-3).

``delegate_part_agent`` is the one model-visible tool that does **not** arrive
over ``py.tool_dispatch``: ``agent/src/tools/proxy.ts`` special-cases it onto its
own bridge method so the sidecar can hold the parent turn open while a child
part agent runs. Because of that, every dispatcher-level delegation test in this
suite — ``test_dispatch_delegation.py``, ``test_delegation.py`` — exercised a
path production never took, and the Stage-2A placeholder that answered
``py.delegate`` in ``app.py`` was never touched by any of them. It returned an
unconditional::

    {"status": "rejected", "reason": "no_run_slot", "part_session_id": None}

which was both **illegal** (an optional property present as ``null`` fails the
committed result schema in both validators, so the model read "result from
delegate_part_agent failed its result schema") and **untrue** (no admission slot
had been contended). B-3 replaced it with
:meth:`~hephaestus.agent_bridge.app.BridgeRuntime._handle_delegate`, which routes
into the one dispatcher.

These tests pin that lift at the seam the sidecar actually uses. They drive
:meth:`BridgeRuntime._on_py_request` — the wrapper the supervisor's reader thread
calls — on a runtime whose dispatcher is the shipped one
(``wiring.build_dispatcher``), so a regression that re-introduces a hand-built
reply, drops the route, or lets ``part_session_id`` back in as ``null`` fails
here rather than in a model transcript.

**No sidecar is spawned.** ``BridgeRuntime.__init__`` resolves and configures a
child but starts nothing, and ``py.delegate`` is a request travelling *into*
Python: the only thing a live child contributes is the session id, which
``create_session`` records from the sidecar's own answer. That one call is
stubbed; everything below it — principal resolution, authorization, the
delegation service, its gate, admission, the WAL — is real.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.testing.tools_fixture import scaffold

REPO = Path(__file__).resolve().parents[2]

#: The session id the stubbed ``session.create`` mints. The sidecar owns this
#: value in production; nothing below the bridge cares where it came from.
STUB_SESSION = "s-1"


def _result_schema(tool: str) -> dict[str, Any]:
    document = cast(
        "dict[str, Any]",
        json.loads((REPO / "schemas" / "tools" / f"{tool}.schema.json").read_text("utf-8")),
    )
    return cast("dict[str, Any]", document["result"])


class _StubbedSidecar:
    """Answers the one bridge call ``create_session`` makes, records the rest.

    Deliberately narrow: anything a ``py.delegate`` handler tried to ask the
    child raises here, which keeps these cases honest about their reach. They
    exercise the routing, the gate and the refusal shapes with no child session
    in existence; the delegation that actually prompts a child over the bridge
    is ``test_delegation_e2e.py``, against a real sidecar. (Before
    J-agent-wiring-13 this narrowness was an *invariant* rather than a choice —
    a ``py.*`` handler ran on the frame reader, so calling ``Supervisor.call``
    from one blocked the only thread that could answer it. Handlers now run on
    a bounded worker pool and may call back into the sidecar.)
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, method: str, params: dict[str, Any] | None = None, **_: Any) -> Any:
        self.calls.append((method, dict(params or {})))
        if method == "session.create":
            return {"session_id": STUB_SESSION}
        raise AssertionError(f"no sidecar is running; unexpected bridge call {method!r}")


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[BridgeRuntime]:
    """A real, unstarted ``BridgeRuntime`` over a scaffolded project.

    ``HEPHAESTUS_NODE`` is the documented "spawn exactly this" override
    (``agent_bridge/sidecar.py``), so constructing the supervisor's argv needs no
    Node on this machine — and nothing is spawned regardless.
    """
    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    root = scaffold(tmp_path / "proj")
    rt = BridgeRuntime(
        backend=UnsafeLocalBackend(),
        project_root=root,
        providers=[],
        dist_main=tmp_path / "never-spawned-main.js",
    )
    sidecar = _StubbedSidecar()
    monkeypatch.setattr(rt._sup, "call", sidecar)  # pyright: ignore[reportPrivateUsage]
    try:
        yield rt
    finally:
        rt.close()


def _orchestrator(rt: BridgeRuntime) -> str:
    """Register the orchestrator principal the way the shipped runtime does."""
    return rt.create_session("orchestrator")


def _delegate(
    rt: BridgeRuntime,
    *,
    part: str,
    session_id: str,
    parent_run_id: str = "run-1",
    prompt: str = "make it wider",
    entry: str = "e-delegate-1",
    **extra: Any,
) -> Any:
    """One ``py.delegate`` exactly as ``tools/proxy.ts`` frames it."""
    params: dict[str, Any] = {
        "parent_run_id": parent_run_id,
        "part": part,
        "prompt": prompt,
        "invocation": {
            "session_id": session_id,
            "entry_id": entry,
            "ordinal": 1,
            "provider_call_id": "call_0",
        },
        **extra,
    }
    return rt._on_py_request("py.delegate", params)  # pyright: ignore[reportPrivateUsage]


# -- the lift itself -------------------------------------------------------


def test_py_delegate_reaches_the_shipped_dispatcher(runtime: BridgeRuntime) -> None:
    """B-3 step 3: the route lands in ``ToolDispatcher._delegate``, not a stub.

    The Stage-2A placeholder answered ``rejected/no_run_slot`` for every input.
    A real delegation to a part that exists, on a runtime with no delegation
    runner bound, reaches a durable ``interrupted`` terminal with a delegation
    ref and a child run — three fields the stub could not produce.
    """
    session_id = _orchestrator(runtime)
    runtime.admission.admit_run("run-1")

    result = _delegate(runtime, part="widget", session_id=session_id)

    assert result["status"] == "interrupted", result
    assert result["delegation_ref"], "a real delegation is durably referenced"
    assert result["child_run_id"], "a real delegation admitted a child run"
    assert result["part_session_id"] == "part:widget"
    jsonschema.validate(result, _result_schema("delegate_part_agent"))


def test_py_delegate_honours_the_optional_wire_fields(runtime: BridgeRuntime) -> None:
    """``delivery``/``deadline_seconds`` are forwarded, and only when present.

    ``delivery="follow_up"`` takes the other branch of ``_delegate`` — the slot
    is reserved and the call returns ``queued`` rather than settling — so a
    handler that dropped the optional fields on the floor would answer
    ``interrupted`` here.
    """
    session_id = _orchestrator(runtime)
    runtime.admission.admit_run("run-1")

    result = _delegate(
        runtime,
        part="widget",
        session_id=session_id,
        delivery="follow_up",
        deadline_seconds=120,
    )

    assert result["status"] == "queued", result
    jsonschema.validate(result, _result_schema("delegate_part_agent"))


# -- the rejection shape ---------------------------------------------------


def test_a_rejection_names_a_reason_and_carries_no_null_part_session_id(
    runtime: BridgeRuntime,
) -> None:
    """The B-3 defect, pinned from both sides.

    The reply must (1) name a real reason — ``invalid_part``, produced by
    ``wiring.PartExistsGate`` — rather than the stub's invented
    ``no_run_slot``; (2) carry no key whose value is ``null``; and (3) validate
    against the committed result schema. The last assertion proves the schema
    is the thing that catches it: the exact stub payload is checked and rejected.
    """
    session_id = _orchestrator(runtime)
    runtime.admission.admit_run("run-1")

    result = _delegate(runtime, part="ghost", session_id=session_id)

    assert result["status"] == "rejected", result
    assert result["reason"] == "invalid_part", result
    assert None not in result.values(), f"an optional key present as null: {result}"
    jsonschema.validate(result, _result_schema("delegate_part_agent"))

    stage_2a_stub = {"status": "rejected", "reason": "no_run_slot", "part_session_id": None}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(stage_2a_stub, _result_schema("delegate_part_agent"))


def test_a_rejected_delegation_admits_no_child_run(runtime: BridgeRuntime) -> None:
    """The gate runs *before* admission: nothing is reserved for a part that
    does not exist, and the parent's own slot is the only one occupied."""
    session_id = _orchestrator(runtime)
    runtime.admission.admit_run("run-1")
    occupied = runtime.admission.occupancy()

    result = _delegate(runtime, part="ghost", session_id=session_id)

    assert result["status"] == "rejected"
    assert "child_run_id" not in result and "delegation_ref" not in result
    assert runtime.admission.occupancy() == occupied


# -- refusals that are not tool results ------------------------------------


def test_py_delegate_from_an_unknown_session_is_a_protocol_error(
    runtime: BridgeRuntime,
) -> None:
    """The wire params carry no session id of their own — the trusted invocation
    is the only place the calling session is named, so an unrecognized one is
    refused rather than silently treated as the orchestrator."""
    _orchestrator(runtime)
    with pytest.raises(ProtocolError) as ei:
        _delegate(runtime, part="widget", session_id="someone-else")
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_py_delegate_without_a_live_parent_run_is_typed(runtime: BridgeRuntime) -> None:
    """No admission row for the parent run is a named ``invalid_params``
    refusal, not the opstore's own exception crossing the bridge untyped."""
    session_id = _orchestrator(runtime)
    with pytest.raises(DispatchError) as ei:
        _delegate(runtime, part="widget", session_id=session_id, parent_run_id="never-admitted")
    assert ei.value.reason == "invalid_params"


def test_a_part_session_may_not_delegate(runtime: BridgeRuntime) -> None:
    """Delegation is orchestrator-only, and the route does not bypass authz:
    the principal recorded at ``create_session`` is what ``_authorize`` reads."""
    session_id = runtime.create_session("part", part="widget")
    runtime.admission.admit_run("run-1")
    with pytest.raises(DispatchError) as ei:
        _delegate(runtime, part="widget", session_id=session_id)
    assert ei.value.reason == "scope_denied"


def test_an_unknown_py_method_is_still_method_not_found(runtime: BridgeRuntime) -> None:
    """The route table gained ``py.delegate`` without loosening its default."""
    with pytest.raises(ProtocolError) as ei:
        runtime._on_py_request("py.nope", {})  # pyright: ignore[reportPrivateUsage]
    assert ei.value.code == ErrorCode.METHOD_NOT_FOUND


# -- the ordering the handler pool introduced ------------------------------


def test_a_sequential_tool_dispatch_is_serialized_across_handler_workers(
    runtime: BridgeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``py.*`` handlers now run concurrently, and sequential tools must not.

    Before audit-2026-09-04 J-agent-wiring-13 the supervisor ran every ``py.*``
    handler inline on its single reader thread, so two tool dispatches from one
    sidecar were serial by construction and nothing had to say so. They run on a
    bounded worker pool now — which is what lets a handler call back into the
    child at all — and that makes two mutating dispatches genuinely concurrent
    for the first time. The tools the contract declares ``sequential`` are the
    ones that write through the project, and ``_handle_tool_dispatch`` holds one
    per-runtime lock across them.

    Pinned by observation, not by reading the lock: two threads enter a dispatch
    that sleeps, and the recorded enter/exit order is asserted to be
    non-overlapping for a sequential tool.
    """
    session_id = _orchestrator(runtime)
    order: list[str] = []
    lock = threading.Lock()

    def slow_dispatch(_principal: Any, params: dict[str, Any]) -> Any:
        tag = str(params["arguments"]["name"])
        with lock:
            order.append(f"enter:{tag}")
        time.sleep(0.1)
        with lock:
            order.append(f"exit:{tag}")
        return {"ok": True}

    monkeypatch.setattr(runtime._dispatcher, "dispatch", slow_dispatch)  # pyright: ignore[reportPrivateUsage]

    def call(tag: str) -> None:
        runtime._on_py_request(  # pyright: ignore[reportPrivateUsage]
            "py.tool_dispatch",
            {
                "session_id": session_id,
                "run_id": "run-1",
                "tool": "create_part",  # sequential per the tool contract
                "arguments": {"name": tag},
            },
        )

    threads = [threading.Thread(target=call, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(order) == 4, order
    # Whoever went first finished before the other started.
    assert order[1].startswith("exit:"), order
    assert order[0].split(":")[1] == order[1].split(":")[1], order


def test_a_read_tool_dispatch_is_not_serialized(
    runtime: BridgeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock is for writers only: two reads still overlap.

    The whole point of moving dispatch off the reader thread is concurrency; a
    lock taken for every tool would give it back. ``read_part`` is declared
    non-sequential, so two of them are expected to be inside the dispatcher at
    the same moment.
    """
    session_id = _orchestrator(runtime)
    inside = threading.Semaphore(0)
    both = threading.Event()
    overlapped: list[bool] = []

    def dispatch(_principal: Any, _params: dict[str, Any]) -> Any:
        inside.release()
        overlapped.append(both.wait(timeout=5))
        return {"ok": True}

    monkeypatch.setattr(runtime._dispatcher, "dispatch", dispatch)  # pyright: ignore[reportPrivateUsage]

    def call() -> None:
        runtime._on_py_request(  # pyright: ignore[reportPrivateUsage]
            "py.tool_dispatch",
            {
                "session_id": session_id,
                "run_id": "run-1",
                "tool": "read_part",
                "arguments": {"name": "widget"},
            },
        )

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert inside.acquire(timeout=5)
    assert inside.acquire(timeout=5), "the second read never entered: reads are serialized"
    both.set()
    for thread in threads:
        thread.join(timeout=10)
    assert overlapped == [True, True]


# -- the prompt registry is not a leak -------------------------------------


def _registry(rt: BridgeRuntime) -> dict[str, str]:
    """The live prompt cache, read the only way a test can: by inspection."""
    return rt._delegation_prompts._prompts  # pyright: ignore[reportPrivateUsage]


def test_a_rejected_delegation_leaves_no_prompt_text_behind(
    runtime: BridgeRuntime,
) -> None:
    """J-agent-wiring-6's registry is bounded by the dispatch, not by luck.

    ``_handle_delegate`` registers the prompt before dispatching, because a
    synchronous delegation runs its child *inside* the dispatch and the durable
    row carries only the prompt's hash. The runner forgets what it consumed —
    but a rejection reaches no runner, and the registry is an unbounded dict
    holding model-authored text bounded only by ``PROMPT_MAX_UTF8_BYTES``. A
    model looping on ``invalid_part`` would therefore grow this process without
    limit, which is why the forget is in a ``finally`` on every exit.
    """
    session_id = _orchestrator(runtime)
    runtime.admission.admit_run("run-1")

    result = _delegate(runtime, part="ghost", session_id=session_id, prompt="REJECTED-TEXT")

    assert result["status"] == "rejected"
    assert _registry(runtime) == {}, "prompt text survived a rejected delegation"


def test_a_follow_up_delegation_leaves_no_prompt_text_behind(
    runtime: BridgeRuntime,
) -> None:
    """The second exit that reaches no runner.

    ``ToolDispatcher._delegate`` returns the queued row for a ``follow_up``
    delivery without running anything, and nothing in this bridge ever runs a
    queued row afterwards — so the text would sit in the cache for the life of
    the process. A future coordinator that does run queued rows must re-derive
    the prompt from its own record; this cache is only ever a hand-off across
    one synchronous call.
    """
    session_id = _orchestrator(runtime)
    runtime.admission.admit_run("run-1")

    result = _delegate(
        runtime,
        part="widget",
        session_id=session_id,
        prompt="FOLLOWUP-TEXT",
        delivery="follow_up",
    )

    assert result["status"] == "queued", result
    assert _registry(runtime) == {}, "prompt text survived a follow_up delegation"
