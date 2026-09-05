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
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError
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
    child would raise here, which is the invariant ``app.py``'s ``_PY_HANDLER``
    exists to protect (a ``py.*`` handler that calls ``Supervisor.call`` blocks
    the only thread that could answer it).
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


# -- the reader-thread flag the wrapper owns -------------------------------


def test_the_py_handler_flag_is_cleared_even_when_the_handler_raises(
    runtime: BridgeRuntime,
) -> None:
    """``_on_py_request`` marks the thread "servicing a sidecar request" for the
    whole handler so nothing under it calls back into the child (``app.py``'s
    single-reader invariant). A handler that raises must still clear it, or the
    reader thread would refuse every later ``query_snapshot`` for the life of
    the process — a leak no delegation test would otherwise notice.
    """
    from hephaestus.agent_bridge import app as bridge_app

    def flag() -> object:
        return bridge_app._PY_HANDLER  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ProtocolError):
        runtime._on_py_request("py.nope", {})  # pyright: ignore[reportPrivateUsage]
    assert getattr(flag(), "active", False) is False

    session_id = _orchestrator(runtime)
    runtime.admission.admit_run("run-1")
    _delegate(runtime, part="widget", session_id=session_id)
    assert getattr(flag(), "active", False) is False
