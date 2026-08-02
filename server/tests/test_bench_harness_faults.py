"""``EXTERNAL_EVAL.md`` §5: harness faults are never charged to the model.

The 2026-07-29 sweep's autopsy: 13 of 14 failed editing runs had built a
correct-status candidate, and five of six infrastructure deaths ended on an
unanswered ``compare_solids``. The budget guard now refunds a charged tool call
the moment its *result* turns out to be a named harness fault — a bounded-diff
``compare_timeout``, a bridge RPC timeout or backpressure refusal, a sidecar
loss — and the per-call charged/uncharged split is archived on the run record.

Also here: the §5 sidecar-evidence archive. ``run_task`` asks the runtime for
the supervisor's restart events and bounded stderr tail after ``close()`` and
writes them beside the run (``restarts.json`` / ``sidecar.log``); a runtime
double that offers no evidence archives none, and the run is otherwise
untouched.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.bench import harness
from hephaestus.bench.harness import (
    ARCHIVE_RESTARTS_FILENAME,
    ARCHIVE_SIDECAR_LOG_FILENAME,
    BenchTask,
    ProviderConfig,
    harness_fault,
)
from hephaestus.bench.harness._run import _BudgetGuard  # pyright: ignore[reportPrivateUsage]

# --------------------------------------------------------------------------
# the fault vocabulary


def _error(text: str) -> dict[str, Any]:
    return {"isError": True, "text": text, "toolName": "compare_solids"}


def test_harness_fault_names_every_shape_the_sweep_produced() -> None:
    """Each named fault matches the event stream's own error text, by prefix."""
    assert harness_fault(_error("compare_timeout: solid diff exceeded 300.0 s")) == (
        "compare_timeout"
    )
    assert harness_fault(_error("no response for py.tool_dispatch within 120000ms")) == (
        "bridge_timeout"
    )
    assert harness_fault(_error("pending request queue full (max 64)")) == "bridge_backpressure"
    assert harness_fault(_error("sidecar restarted")) == "sidecar_restarted"
    assert harness_fault(_error("sidecar exited (rc=9)")) == "sidecar_exited"


def test_a_model_error_is_not_a_harness_fault() -> None:
    """A refusal the model earned (bad params, its own broken script) stays charged."""
    assert harness_fault(_error("invalid_params: unknown view 'top'")) is None
    assert harness_fault(_error("build_failed: build worker exited with code 3")) is None
    # A successful result is never a fault, whatever its text says.
    assert harness_fault({"isError": False, "text": "compare_timeout: quoted in prose"}) is None


# --------------------------------------------------------------------------
# the guard's refund

_RUNTIME = cast("BridgeRuntime", object())


def _call(guard: _BudgetGuard, call_id: str, name: str = "measure") -> None:
    guard.on_event(
        {"kind": "tool_call", "tool_call_id": call_id, "payload": {"name": name, "arguments": {}}}
    )


def _result(guard: _BudgetGuard, call_id: str, *, text: str | None = None) -> None:
    payload: dict[str, Any] = (
        {"isError": True, "text": text} if text is not None else {"text": '{"status": "ok"}'}
    )
    guard.on_event({"kind": "tool_result", "tool_call_id": call_id, "payload": payload})


def test_a_harness_fault_result_refunds_the_charge_per_call() -> None:
    guard = _BudgetGuard(_RUNTIME, "run-1", budget=10)

    _call(guard, "c1", "compare_solids")
    _call(guard, "c2")
    assert guard.tool_calls == 2

    _result(guard, "c1", text="compare_timeout: solid diff exceeded 300.0 s")
    _result(guard, "c2")

    assert guard.tool_calls == 1
    assert guard.uncharged_tool_calls == 1
    assert guard.uncharged_calls == [
        {"tool_call_id": "c1", "name": "compare_solids", "fault": "compare_timeout"}
    ]


def test_a_refund_clears_a_budget_exceeded_mark_it_undoes() -> None:
    """A budget "exceeded" only by our faults was never exceeded."""
    guard = _BudgetGuard(_RUNTIME, "run-1", budget=2)

    for call_id in ("c1", "c2", "c3"):
        _call(guard, call_id)
    assert guard.budget_exceeded_at == 3

    _result(guard, "c3", text="no response for py.tool_dispatch within 120000ms")

    assert guard.tool_calls == 2
    assert guard.budget_exceeded_at is None


def test_a_result_is_refunded_at_most_once_and_only_for_charged_calls() -> None:
    guard = _BudgetGuard(_RUNTIME, "run-1", budget=10)

    _call(guard, "c1")
    _result(guard, "c1", text="sidecar exited (rc=9)")
    # A duplicate result for the same call cannot refund twice.
    _result(guard, "c1", text="sidecar exited (rc=9)")
    # A compelled call was never charged, so its fault refunds nothing.
    guard.on_event({"kind": "tool_call", "tool_call_id": "c2", "payload": {"name": "ask_user"}})
    _result(guard, "c2", text="sidecar restarted")

    assert guard.tool_calls == 0
    assert guard.compelled_tool_calls == 1
    assert guard.uncharged_tool_calls == 1


# --------------------------------------------------------------------------
# run_task: the archived split and the sidecar evidence


@dataclass
class _PromptResult:
    status: str = "completed"
    terminal: dict[str, Any] | None = None


class _ScriptedRuntime:
    """A runtime double: replays scripted events, offers sidecar evidence."""

    def __init__(self, events: list[dict[str, Any]], evidence: dict[str, Any] | None) -> None:
        self._events = events
        self._evidence = evidence

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def create_session(self, profile: str, *, session_id: str | None = None) -> str:
        return session_id or "session-1"

    def new_run_id(self) -> str:
        return "run-1"

    def cancel(self, run_id: str) -> None:
        pass

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = None,
        answerer: Callable[[Mapping[str, Any]], Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        timeout: float | None = None,
    ) -> _PromptResult:
        if on_event is not None:
            for event in self._events:
                on_event(event)
        return _PromptResult()

    def sidecar_evidence(self) -> dict[str, Any]:
        if self._evidence is None:
            raise AttributeError("no evidence on this double")
        return dict(self._evidence)


def _task(tmp_path: Path, budget: int = 2) -> BenchTask:
    return BenchTask(
        id="fault-task",
        directory=tmp_path / "task",
        prompt="build nothing",
        budget_tool_calls=budget,
    )


def _run(
    tmp_path: Path, events: list[dict[str, Any]], evidence: dict[str, Any] | None
) -> harness.RunRecord:
    runtime = cast("BridgeRuntime", _ScriptedRuntime(events, evidence))
    provider = ProviderConfig(
        providers=({"id": "fake", "kind": "openai_compatible"},), model_id="m"
    )
    return harness.run_task(
        _task(tmp_path),
        1,
        provider=provider,
        archive_dir=tmp_path / "archive",
        runtime_factory=lambda _root, _provider: runtime,
        date="2026-08-02",
    )


_EVIDENCE: dict[str, Any] = {
    "restarts": [
        {"reason": "watchdog", "returncode": -9, "restart_generation": 1, "at": "2026-08-02"}
    ],
    "stderr_tail": ["[sidecar] boom", "[sidecar] respawning"],
    "auto_respawns": 1,
    "spawn_count": 2,
    "spawn_errors": [],
}


def test_run_task_archives_the_charged_uncharged_split_and_sidecar_evidence(
    tmp_path: Path,
) -> None:
    events: list[dict[str, Any]] = [
        {"kind": "tool_call", "tool_call_id": "c1", "payload": {"name": "compare_solids"}},
        {
            "kind": "tool_result",
            "tool_call_id": "c1",
            "payload": {"isError": True, "text": "compare_timeout: diff exceeded 300.0 s"},
        },
        {"kind": "tool_call", "tool_call_id": "c2", "payload": {"name": "measure"}},
        {"kind": "tool_call", "tool_call_id": "c3", "payload": {"name": "measure"}},
        {
            "kind": "tool_result",
            "tool_call_id": "c3",
            "payload": {"isError": True, "text": "sidecar restarted"},
        },
    ]

    record = _run(tmp_path, events, _EVIDENCE)

    # c1 and c3 were our faults; only c2 is charged, so the budget of 2 holds.
    assert record.tool_calls == 1
    assert record.uncharged_tool_calls == 2
    assert [c["fault"] for c in record.uncharged_calls] == ["compare_timeout", "sidecar_restarted"]
    assert record.budget_exceeded_at is None
    assert cast("dict[str, Any]", record.grade)["within_budget"] is True

    run_dir = Path(record.archive_dir)
    restarts = cast(
        "dict[str, Any]",
        json.loads((run_dir / ARCHIVE_RESTARTS_FILENAME).read_text(encoding="utf-8")),
    )
    assert restarts["restarts"] == _EVIDENCE["restarts"]
    assert restarts["auto_respawns"] == 1
    tail = (run_dir / ARCHIVE_SIDECAR_LOG_FILENAME).read_text(encoding="utf-8")
    assert tail == "[sidecar] boom\n[sidecar] respawning\n"
    # …and the split rides in the archived record itself.
    archived = cast(
        "dict[str, Any]", json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    )
    assert archived["uncharged_tool_calls"] == 2
    assert [c["tool_call_id"] for c in cast("list[Any]", archived["uncharged_calls"])] == [
        "c1",
        "c3",
    ]


def test_a_runtime_without_evidence_archives_none_and_the_run_survives(tmp_path: Path) -> None:
    record = _run(tmp_path, [], None)

    run_dir = Path(record.archive_dir)
    assert not (run_dir / ARCHIVE_RESTARTS_FILENAME).exists()
    assert not (run_dir / ARCHIVE_SIDECAR_LOG_FILENAME).exists()
    assert (run_dir / "result.json").is_file()
