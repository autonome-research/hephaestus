# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``py.*`` dispatch runs on a bounded pool, never on the frame reader.

audit-2026-09-04 J-agent-wiring-13. The supervisor used to read a frame, route
it, and call the registered ``py.*`` handler **inline on the reader thread** —
the single thread that decodes every frame the child sends. A handler that
issued :meth:`~hephaestus.agent_bridge.supervisor.Supervisor.call` was therefore
waiting for a response only the thread it was blocking could deliver: the call
timed out, the watchdog killed the child as unresponsive, and the reader died
with it. That is why the delegation runner could not be bound (a delegation
prompts its child part session over this same pipe) and why a question suspended
on one session stalled every frame of every *other* session for as long as a
human took to answer.

These tests drive a real child process over the real framing, because the defect
is a property of the two threads and the pipe between them; an in-process fake
would prove nothing. The first test is the direct pin: it hangs against the
pre-fix supervisor and passes in about a millisecond against this one.

Also covers J-build-state-2's supervisor half: a recovery hook that raises no
longer vanishes into ``contextlib.suppress`` — the restart still completes *and*
the fault is archived on ``restart_events`` with its detail redacted.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.protocol import ErrorCode
from hephaestus.agent_bridge.supervisor import (
    ProcessLossEvent,
    Supervisor,
    SupervisorConfig,
)
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.testing.tools_fixture import scaffold
from opstore.types import TerminalState

#: A child that does exactly two things: answers ``ping``, and originates the
#: ``py.*`` requests a test asks it for, reporting each response back as a
#: ``done`` notification. Written per-test-session rather than reusing
#: ``fake_sidecar.py`` so this file's scenarios cannot perturb that fixture's
#: many other consumers.
CHILD_SOURCE = r"""
import json
import sys
import threading

LOCK = threading.Lock()


def send(obj):
    payload = (json.dumps({"hv": 1, "jsonrpc": "2.0", **obj}) + "\n").encode("utf-8")
    with LOCK:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()


next_id = [1000]

for line in sys.stdin.buffer:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    msg_id = msg.get("id")
    if method is None and msg_id is not None:
        # A response to one of the py.* requests we originated.
        send({"method": "done", "params": {"id": msg_id, "frame": msg}})
        continue
    if method == "ping":
        send({"id": msg_id, "result": {"pong": msg.get("params", {}).get("tag")}})
    elif method == "fire":
        params = msg.get("params", {})
        for _ in range(int(params.get("count", 1))):
            rid = next_id[0]
            next_id[0] += 1
            send({"id": rid, "method": params.get("py_method", "py.probe"), "params": {}})
    elif msg_id is not None:
        send({"id": msg_id, "error": {"code": -32601, "message": "no such method"}})
"""


@pytest.fixture
def child(tmp_path: Path) -> Path:
    path = tmp_path / "dispatch_child.py"
    path.write_text(CHILD_SOURCE, encoding="utf-8")
    return path


class _Notifications:
    """Collects the child's ``done`` notifications for assertion."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self._event = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, method: str, params: dict[str, Any]) -> None:
        if method != "done":
            return
        with self._lock:
            self.frames.append(dict(params))
        self._event.set()

    def wait(self, count: int, timeout: float) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if len(self.frames) >= count:
                    return list(self.frames)
            self._event.wait(0.05)
            self._event.clear()
        with self._lock:
            return list(self.frames)


def _supervisor(
    child: Path,
    handler: Any,
    sink: Any,
    *,
    workers: int | None = None,
) -> Supervisor:
    argv = [sys.executable, str(child)]
    config = (
        SupervisorConfig(argv=argv)
        if workers is None
        else SupervisorConfig(argv=argv, py_handler_workers=workers)
    )
    return Supervisor(config, py_handler=handler, notification_sink=sink)


@pytest.fixture
def notifications() -> _Notifications:
    return _Notifications()


def _run(sup: Supervisor) -> Iterator[Supervisor]:
    sup.start()
    try:
        yield sup
    finally:
        sup.close()


# -- the direct pin --------------------------------------------------------


def test_a_handler_that_calls_back_into_the_sidecar_completes(
    child: Path, notifications: _Notifications
) -> None:
    """The test that hangs against the pre-fix supervisor.

    The handler for the child's ``py.*`` request issues an outbound ``ping``
    and returns its result. Inline on the reader thread that is a deadlock: the
    ``ping`` response can only be decoded by the thread now sitting inside the
    handler. On a worker it is an ordinary round trip.
    """
    holder: dict[str, Supervisor] = {}

    def handler(_method: str, _params: dict[str, Any]) -> Any:
        return holder["sup"].call("ping", {"tag": "from-handler"}, timeout=5.0)

    sup = _supervisor(child, handler, notifications)
    holder["sup"] = sup
    for live in _run(sup):
        live.notify("fire", {"py_method": "py.probe", "count": 1})
        frames = notifications.wait(1, timeout=10.0)
        assert len(frames) == 1, "the handler never answered: the reader thread is blocked"
        assert frames[0]["frame"]["result"] == {"pong": "from-handler"}


def test_two_handlers_run_concurrently(child: Path, notifications: _Notifications) -> None:
    """Two sleeping handlers cost one sleep, not two.

    Serial execution on the reader thread was the *only* reason a second
    ``py.tool_dispatch`` waited for the first. The bound asserted is deliberately
    loose (well under two sleeps, not "about one") so a loaded runner cannot
    make it flaky while still failing outright on serialization.
    """
    sleep_s = 0.4

    def handler(_method: str, _params: dict[str, Any]) -> Any:
        time.sleep(sleep_s)
        return {"ok": True}

    sup = _supervisor(child, handler, notifications)
    for live in _run(sup):
        started = time.monotonic()
        live.notify("fire", {"py_method": "py.probe", "count": 2})
        frames = notifications.wait(2, timeout=10.0)
        elapsed = time.monotonic() - started
        assert len(frames) == 2, frames
        assert elapsed < sleep_s * 1.8, f"handlers ran serially ({elapsed:.2f}s)"


def test_a_saturated_pool_refuses_by_name_and_leaves_the_pipe_readable(
    child: Path, notifications: _Notifications
) -> None:
    """Backpressure is a named refusal, never a stall.

    With one worker and one handler parked, the second request must come back as
    ``handler_overloaded`` rather than queueing behind the reader — and, the
    half that matters, an unrelated outbound call must still complete while the
    worker is occupied. That second assertion is the shipped guarantee the old
    shape broke: a suspended question froze every other session's traffic.
    """
    release = threading.Event()

    def handler(_method: str, _params: dict[str, Any]) -> Any:
        release.wait(timeout=10.0)
        return {"ok": True}

    sup = _supervisor(child, handler, notifications, workers=1)
    for live in _run(sup):
        live.notify("fire", {"py_method": "py.probe", "count": 2})
        frames = notifications.wait(1, timeout=10.0)
        assert len(frames) == 1, "the overload refusal never came back"
        error = frames[0]["frame"]["error"]
        assert error["code"] == ErrorCode.BUSY
        assert error["data"]["reason"] == "handler_overloaded"
        assert live.handler_overloads == 1

        # The pipe is still readable while the one worker is parked.
        assert live.call("ping", {"tag": "unrelated"}, timeout=5.0) == {"pong": "unrelated"}
        release.set()
        assert len(notifications.wait(2, timeout=10.0)) == 2


def test_the_pool_size_is_read_from_the_shared_limits_document() -> None:
    """No literal: the worker count is a field of ``schemas/bridge_limits.json``."""
    from hephaestus.agent_bridge.limits import LIMITS

    assert SupervisorConfig(argv=["/bin/true"]).py_handler_workers == int(
        LIMITS["rpc"]["py_handler_workers"]
    )


def test_the_cad_build_class_is_no_longer_a_supervisor_field() -> None:
    """J-http-limits-8: the field was correctly named and on the wrong object.

    Builds travel sidecar-to-Python, so the deadline that decides one is the
    sidecar's RPC peer default — not anything this side could select. Keeping a
    ``cad_build_timeout_s`` here that no call site can reach is what made the
    limit dead for a year; it is gone, and the enforcement is in
    ``agent/src/tools/proxy.ts``.
    """
    assert not hasattr(SupervisorConfig(argv=["/bin/true"]), "cad_build_timeout_s")


# -- J-build-state-2: a recovery-hook fault is archived, not swallowed ------


def test_a_raising_recovery_hook_is_recorded_and_the_restart_still_completes(
    child: Path,
) -> None:
    """The suppression stays; the silence does not.

    A store fault inside the recovery hook used to produce no row, no event and
    no log line anywhere — there is no logger configured in this process — so
    "the terminal was written" and "the write failed" looked identical from
    outside. The fault now lands on the same archived-evidence list the restart
    itself does.
    """
    seen: list[ProcessLossEvent] = []

    def hook(event: ProcessLossEvent) -> None:
        seen.append(event)
        raise RuntimeError("state.db is locked by /tmp/sekrit-token-value/x")

    sup = Supervisor(SupervisorConfig(argv=[sys.executable, str(child)]), recovery_hook=hook)
    sup.add_redaction("sekrit-token-value")
    sup.start()
    try:
        sup.track_run("run-a")
        sup.restart(reason="manual")
        assert seen, "the hook never ran"
        faults = [row for row in sup.restart_events if row["reason"] == "recovery_fault"]
        assert len(faults) == 1, sup.restart_events
        assert "RuntimeError" in faults[0]["detail"]
        # §23.6: a database error can quote a path that carries a secret.
        assert "sekrit-token-value" not in faults[0]["detail"]
        assert "[redacted]" in faults[0]["detail"]
        # The restart still completed: a fresh child is up and answering.
        assert sup.is_running()
        assert sup.call("ping", {"tag": "after"}, timeout=5.0) == {"pong": "after"}
    finally:
        sup.close()


def test_a_recovery_fault_names_the_run_it_is_about(child: Path) -> None:
    """The row carries the run id, which is the whole point of recording it.

    A fault row that did not name the run would tell an operator that *a*
    terminal was lost without saying which admission slot is now held forever.
    """
    sup = Supervisor(SupervisorConfig(argv=[sys.executable, str(child)]))
    sup.start()
    try:
        sup.record_recovery_fault(run_id="run-x", detail="OperationalError: disk is full")
        row = sup.restart_events[-1]
        assert row == {
            "reason": "recovery_fault",
            "returncode": None,
            "restart_generation": row["restart_generation"],
            "run_id": "run-x",
            "detail": "OperationalError: disk is full",
            "at": row["at"],
        }
        json.dumps(row)  # archived evidence has to serialize
    finally:
        sup.close()


# -- J-build-state-2, the BridgeRuntime half --------------------------------
#
# The two tests above pin the supervisor's own recording contract
# (`record_recovery_fault` / `_fire_recovery`). These exercise the actual
# *caller*, `BridgeRuntime._on_process_loss` (app.py), against a real
# `BridgeAdmission` store with one run's `ingest_terminal` faulted — the
# concrete "a store fault on one of two tracked runs" scenario the ledger's
# Tests section names, and the one place the per-run distinction between an
# *expected* miss (`NotFoundError`/`TerminalConflictError`, silent) and an
# *unexpected* fault (recorded) is actually made.


@pytest.fixture
def delegate_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[BridgeRuntime]:
    """A real, unstarted ``BridgeRuntime`` (mirrors
    ``test_agent_bridge_delegate.py``'s fixture). No sidecar is spawned;
    ``_on_process_loss`` is called directly rather than through a real crash —
    the documented, narrow fault-injection seam this class of regression
    needs."""
    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    root = scaffold(tmp_path / "proj")
    rt = BridgeRuntime(
        backend=UnsafeLocalBackend(),
        project_root=root,
        providers=[],
        dist_main=tmp_path / "never-spawned-main.js",
    )
    try:
        yield rt
    finally:
        rt.close()


def test_a_store_fault_on_one_run_does_not_cost_the_other_its_terminal(
    delegate_runtime: BridgeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assertion that pins the ``continue`` in ``_on_process_loss`` and
    would catch anyone "fixing" it into a re-raise: run "bad" fails to ingest
    its terminal, run "good" — processed in the same recovery pass — still
    gets its own, and the failure leaves a named, redacted trace behind rather
    than vanishing."""
    rt = delegate_runtime
    rt.admission.admit_run("bad")
    rt.admission.admit_run("good")

    real_ingest = rt.admission.ingest_terminal

    def flaky_ingest(run_id: str, *args: Any, **kwargs: Any) -> Any:
        if run_id == "bad":
            raise RuntimeError("database is locked")
        return real_ingest(run_id, *args, **kwargs)

    monkeypatch.setattr(rt.admission, "ingest_terminal", flaky_ingest)

    rt._on_process_loss(  # pyright: ignore[reportPrivateUsage]
        ProcessLossEvent(
            reason="crash",
            returncode=1,
            tracked_run_ids=frozenset({"bad", "good"}),
            restart_generation=1,
        )
    )

    assert rt.admission.get_terminal("good") is not None, (
        "a store fault on one run must not cost a DIFFERENT run its terminal"
    )
    assert rt.admission.get_terminal("bad") is None, (
        "the failing run gets NO terminal — the fix records the leak, "
        "never pretends to have written one"
    )

    fault_rows = [
        e
        for e in rt._sup.restart_events  # pyright: ignore[reportPrivateUsage]
        if e.get("reason") == "recovery_fault"
    ]
    assert fault_rows, (
        "no recovery-fault row was archived for the failing run — "
        "BridgeRuntime._on_process_loss swallowed the store fault silently"
    )
    assert fault_rows[0]["run_id"] == "bad"
    assert "database is locked" in fault_rows[0]["detail"]


def test_a_recovery_fault_detail_is_redacted_through_bridgeruntime(
    delegate_runtime: BridgeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same token-shaped-secret redaction requirement, exercised through
    the real ``BridgeRuntime`` path rather than the supervisor directly —
    ``add_redaction`` is registered per credential this process forwards, and
    a store error message can quote one back."""
    rt = delegate_runtime
    rt.admission.admit_run("leaky")
    secret = "sk-leaky-store-connection-string"
    rt._sup.add_redaction(secret)  # pyright: ignore[reportPrivateUsage]

    def raising_ingest(run_id: str, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"connect failed: {secret}")

    monkeypatch.setattr(rt.admission, "ingest_terminal", raising_ingest)

    rt._on_process_loss(  # pyright: ignore[reportPrivateUsage]
        ProcessLossEvent(
            reason="watchdog",
            returncode=None,
            tracked_run_ids=frozenset({"leaky"}),
            restart_generation=1,
        )
    )

    fault_rows = [
        e
        for e in rt._sup.restart_events  # pyright: ignore[reportPrivateUsage]
        if e.get("reason") == "recovery_fault"
    ]
    assert fault_rows, "no recovery-fault row archived"
    assert secret not in fault_rows[0]["detail"]
    assert "[redacted]" in fault_rows[0]["detail"]


def test_an_expected_miss_stays_silent_and_records_no_fault(
    delegate_runtime: BridgeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NotFoundError`` (a run this runtime never admitted) is the state this
    loop already wants — it must stay silent, not be misreported as a fault."""
    from opstore.errors import NotFoundError

    rt = delegate_runtime

    def not_found(run_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotFoundError("no such run")

    monkeypatch.setattr(rt.admission, "ingest_terminal", not_found)

    rt._on_process_loss(  # pyright: ignore[reportPrivateUsage]
        ProcessLossEvent(
            reason="crash",
            returncode=1,
            tracked_run_ids=frozenset({"never-admitted"}),
            restart_generation=1,
        )
    )

    fault_rows = [
        e
        for e in rt._sup.restart_events  # pyright: ignore[reportPrivateUsage]
        if e.get("reason") == "recovery_fault"
    ]
    assert fault_rows == [], "an expected NotFoundError must not be reported as a fault"


# -- J-build-state-2, the app half: the hook records rather than skipping ----


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[BridgeRuntime]:
    """A real, unstarted :class:`BridgeRuntime` over a scaffolded project.

    Unstarted on purpose: ``_on_process_loss`` is the supervisor's recovery
    callback and takes its event as an argument, so nothing here needs a child.
    """
    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    root = scaffold(tmp_path / "proj")
    rt = BridgeRuntime(
        backend=UnsafeLocalBackend(),
        project_root=root,
        providers=[],
        dist_main=tmp_path / "never-spawned-main.js",
    )
    try:
        yield rt
    finally:
        rt.close()


def test_one_runs_failed_terminal_does_not_cost_the_others_theirs(
    runtime: BridgeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assertion that pins the ``continue`` — and the one that pins the record.

    The hook synthesizes one interrupted terminal per tracked run. A store fault
    on one of them used to be swallowed twice (a bare catch-and-continue inside,
    a blanket suppression outside), so the run kept its admission slot, kept
    appearing live, and produced no row, no event and no log line anywhere. The
    ``continue`` is deliberate and stays: this asserts the OTHER run still gets
    its terminal, which is what would catch anyone "fixing" this into a re-raise.
    """
    runtime.admission.admit_run("run-good")
    runtime.admission.admit_run("run-bad")
    real = runtime.admission.ingest_terminal

    def flaky(run_id: str, terminal_id: str, state: Any, data: Any = None) -> Any:
        if run_id == "run-bad":
            raise RuntimeError("database is locked: /var/db/tok-abcdefghijkl/state.db")
        return real(run_id, terminal_id, state, data)

    monkeypatch.setattr(runtime.admission, "ingest_terminal", flaky)
    runtime._sup.add_redaction("tok-abcdefghijkl")  # pyright: ignore[reportPrivateUsage]

    runtime._on_process_loss(  # pyright: ignore[reportPrivateUsage]
        ProcessLossEvent(
            reason="crash",
            returncode=9,
            tracked_run_ids=frozenset({"run-good", "run-bad"}),
            restart_generation=1,
        )
    )

    # The healthy run got its terminal…
    good = runtime.admission.get_terminal("run-good")
    assert good is not None
    assert good.state is TerminalState.INTERRUPTED
    # …the failing one did NOT — the fix records the leak rather than pretending
    # to have written a terminal it could not write.
    assert runtime.admission.get_terminal("run-bad") is None
    # …and the fault is archived evidence naming the run, with the secret gone.
    faults = [
        row
        for row in runtime._sup.restart_events  # pyright: ignore[reportPrivateUsage]
        if row["reason"] == "recovery_fault"
    ]
    assert len(faults) == 1, faults
    assert faults[0]["run_id"] == "run-bad"
    assert "RuntimeError" in faults[0]["detail"]
    assert "tok-abcdefghijkl" not in faults[0]["detail"]


def test_an_expected_recovery_refusal_stays_silent(
    runtime: BridgeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two failures are EXPECTED and must not fill the archive with noise.

    A run this runtime never admitted has no admission row to terminate
    (``NotFoundError``), and a terminal another writer won mid-loop is the race
    the ``get_terminal`` guard is already testing for (``TerminalConflictError``).
    Both mean the row is already in the state the loop wants; recording them
    would make the fault list unreadable exactly when it matters.
    """
    runtime._on_process_loss(  # pyright: ignore[reportPrivateUsage]
        ProcessLossEvent(
            reason="crash",
            returncode=9,
            tracked_run_ids=frozenset({"never-admitted"}),
            restart_generation=1,
        )
    )
    assert [
        row
        for row in runtime._sup.restart_events  # pyright: ignore[reportPrivateUsage]
        if row["reason"] == "recovery_fault"
    ] == []
