# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Request text is bound per **run** — the §7A.4 invariant under concurrency.

``INTERFACE.md`` §7A.4 / §19.23. The 2026-08-28 review found the composer's
request-text purity invariant did not survive its own concurrency: ``CadOps``
held one ``_request_text`` for the whole runtime, so a second overlapping turn
clobbered the first and session A's build was critiqued against session B's
prompt — ``prompt_number_diff`` reporting a **fabricated request diff**, which is
the exact failure §7A.4 exists to prevent. "Two single-run regression pytests
cannot see it", so the load-bearing test here runs **two concurrent turns on two
sessions** and asserts each critique sees its own request.

The second half is §7A.5's guard, with the reason the spec names: a turn refused
``run_in_flight`` — never ``session_busy``, which means a foreign lease holder
owns the session and has a different remedy.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import (
    active_run,
    bind_run_request_text,
    inherit_run_request_text,
    release_run_request_text,
    run_request_text,
)
from hephaestus.agent_bridge.dispatch import Principal
from hephaestus.agent_bridge.sessions import RUN_IN_FLIGHT_SCOPES, RunInFlightError
from hephaestus.testing.tools_fixture import Project, make_project

#: The scripted python fake sidecar (``server/tests/fake_sidecar.py``): the
#: real bridge wiring with no Node and no provider, the same stand-in
#: ``test_supervisor.py`` drives ``BridgeRuntime`` with.
FAKE_SIDECAR = Path(__file__).with_name("fake_sidecar.py")

#: Two requests whose numbers cannot be confused for each other. The widget's
#: bbox is 40 x 20 x 2 mm (``tools_fixture``'s ``WIDGET_SRC`` on the default
#: ``wall``), so "40 mm wide" is a number the build MATCHES and "77 mm wide" is a
#: number nothing built answers — which is what tells the two turns apart in the
#: critique rather than in a mock.
REQUEST_A = "make the widget 40 mm wide"
REQUEST_B = "make the widget 77 mm wide"

SESSION_A = Principal(session_id="sess-a", profile="orchestrator", part=None)
SESSION_B = Principal(session_id="sess-b", profile="orchestrator", part=None)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


def _widths(project: Project, principal: Principal, run_id: str) -> list[float]:
    """The request numbers ``build_part`` reports for this run's critique."""
    result = cast(
        "dict[str, Any]",
        project.call("build_part", {"name": "widget"}, principal=principal, run_id=run_id),
    )
    assert result["status"] == "ok", result.get("error")
    critique = cast("dict[str, Any]", result["critique"])
    diff = cast("dict[str, Any]", critique["prompt_number_diff"])
    return [float(n["value_mm"]) for n in cast("list[dict[str, Any]]", diff["numbers"])]


# --------------------------------------------------------------------------
# the review's own case: two concurrent turns, two requests


def test_two_concurrent_runs_each_read_their_own_request(project: Project) -> None:
    """THE case (§19.23): two sessions prompting at once, each critiqued honestly.

    Before the binding moved to the run this was the fabricated request diff:
    whichever turn called ``set_request_text`` last owned the field, so both
    builds were measured against one prompt. The two builds here overlap on real
    threads and each critique must name only its own number.
    """
    bind_run_request_text("run-a", REQUEST_A)
    bind_run_request_text("run-b", REQUEST_B)
    try:
        seen: dict[str, list[float]] = {}
        errors: list[BaseException] = []
        both_in = threading.Barrier(2, timeout=60)

        def turn(key: str, principal: Principal, run_id: str) -> None:
            try:
                both_in.wait()  # neither build starts until both threads are here
                seen[key] = _widths(project, principal, run_id)
            except BaseException as exc:  # pragma: no cover - the regression itself
                errors.append(exc)

        threads = [
            threading.Thread(target=turn, args=("a", SESSION_A, "run-a")),
            threading.Thread(target=turn, args=("b", SESSION_B, "run-b")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)
        assert errors == [], f"a concurrent turn crashed: {errors[0]!r}"

        assert seen["a"] == [40.0], "session A's critique read session B's request"
        assert seen["b"] == [77.0], "session B's critique read session A's request"
    finally:
        release_run_request_text("run-a")
        release_run_request_text("run-b")


def test_interleaved_dispatches_do_not_leak_across_runs(project: Project) -> None:
    """The supervisor's reader thread is serial: interleaving must hold too.

    ``py.tool_dispatch`` requests for two live runs arrive on ONE thread today,
    so the invariant cannot rest on thread confinement. The scope is entered per
    dispatch, which is why alternating between runs on a single thread reads
    correctly both times.
    """
    bind_run_request_text("run-a", REQUEST_A)
    bind_run_request_text("run-b", REQUEST_B)
    try:
        assert _widths(project, SESSION_A, "run-a") == [40.0]
        assert _widths(project, SESSION_B, "run-b") == [77.0]
        assert _widths(project, SESSION_A, "run-a") == [40.0]
    finally:
        release_run_request_text("run-a")
        release_run_request_text("run-b")


# --------------------------------------------------------------------------
# what a run's binding outranks, and what it does not


def test_a_run_binding_outranks_the_object_field(project: Project) -> None:
    """A bound run reads its own text, never whatever the object was set to."""
    project.cad.set_request_text("make the widget 77 mm wide")
    bind_run_request_text("run-a", REQUEST_A)
    try:
        assert _widths(project, SESSION_A, "run-a") == [40.0]
    finally:
        release_run_request_text("run-a")


def test_an_unbound_run_falls_back_to_the_object_field(project: Project) -> None:
    """A caller that is not a run — HTTP tool route, MCP, a direct test — is unchanged.

    Presence in the table, not truthiness, is what makes a run authoritative, so
    a dispatch carrying a run id nobody bound still sees the embedder's request
    instead of silently losing it.
    """
    project.cad.set_request_text(REQUEST_A)
    assert _widths(project, SESSION_A, "run-never-bound") == [40.0]


def test_a_bound_run_with_no_request_is_known_to_have_none(project: Project) -> None:
    """An empty prompt binds ``None`` — known absent, not unknown.

    A critique with no request **omits** ``prompt_number_diff`` rather than
    inventing one, and that must survive an object field left over from an
    embedder: the run said it has no request.
    """
    project.cad.set_request_text(REQUEST_A)
    bind_run_request_text("run-empty", "   ")
    try:
        result = cast(
            "dict[str, Any]",
            project.call("build_part", {"name": "widget"}, run_id="run-empty"),
        )
        assert result["status"] == "ok", result.get("error")
        assert "prompt_number_diff" not in cast("dict[str, Any]", result["critique"])
    finally:
        release_run_request_text("run-empty")


def test_a_released_run_reads_no_neighbouring_request(project: Project) -> None:
    """A late tool call from a finished run resolves to absence, not to a neighbour."""
    bind_run_request_text("run-a", REQUEST_A)
    bind_run_request_text("run-b", REQUEST_B)
    release_run_request_text("run-a")
    try:
        result = cast(
            "dict[str, Any]", project.call("build_part", {"name": "widget"}, run_id="run-a")
        )
        assert "prompt_number_diff" not in cast("dict[str, Any]", result["critique"])
    finally:
        release_run_request_text("run-b")


# --------------------------------------------------------------------------
# the registry's own rules


def test_a_delegated_child_inherits_the_parent_request() -> None:
    """A part agent's build is critiqued against the ORIGINAL request (``app.py``).

    Delegated child prompts never pass through ``BridgeRuntime.prompt``, so with
    the text bound per run the inheritance is explicit at the dispatcher.
    """
    bind_run_request_text("run-parent", REQUEST_A)
    try:
        inherit_run_request_text("run-parent", "cr-child")
        assert run_request_text("cr-child") == REQUEST_A
    finally:
        release_run_request_text("run-parent")
        release_run_request_text("cr-child")


def test_an_unbound_parent_leaves_its_child_unbound() -> None:
    """The absence is inherited too — a child never invents a request."""
    inherit_run_request_text("run-nothing", "cr-orphan")
    with active_run("cr-orphan"):
        assert run_request_text("cr-orphan") is None


def test_the_scope_is_left_on_the_way_out() -> None:
    """``active_run`` resets through its token, so nesting cannot strand a scope."""
    bind_run_request_text("run-outer", REQUEST_A)
    bind_run_request_text("run-inner", REQUEST_B)
    try:
        with active_run("run-outer"):
            with active_run("run-inner"):
                assert run_request_text("run-inner") == REQUEST_B
            assert run_request_text("run-outer") == REQUEST_A
    finally:
        release_run_request_text("run-outer")
        release_run_request_text("run-inner")


# --------------------------------------------------------------------------
# §7A.5's guard: run_in_flight, and never session_busy


def test_run_in_flight_is_its_own_reason_with_its_own_ids() -> None:
    """§7A.5: a new, distinct reason carrying the HOLDING session and run.

    ``session_busy`` already means a foreign lease holder owns the session (§2.1)
    — a different fact with a different remedy — so the two must stay tellable
    apart in the one place the operator has to tell them apart.
    """
    exc = RunInFlightError("sess-a", "run-a", scope="session")
    assert exc.code == "run_in_flight"
    assert exc.code != "session_busy"
    assert (exc.session_id, exc.run_id) == ("sess-a", "run-a")
    assert exc.scope in RUN_IN_FLIGHT_SCOPES
    assert "sess-a" in str(exc) and "run-a" in str(exc)


def test_run_in_flight_maps_to_409_with_its_payload() -> None:
    """§2.4: the refusal keeps its own reason and its ids ride through verbatim."""
    from hephaestus.http.errors import REASON_STATUS, refusal_for

    assert REASON_STATUS["run_in_flight"] == 409
    refusal = refusal_for(RunInFlightError("sess-a", "run-a", scope="session"))
    assert refusal.status == 409
    assert refusal.reason == "run_in_flight"
    assert refusal.data["session_id"] == "sess-a"
    assert refusal.data["run_id"] == "run-a"


def test_a_second_turn_on_a_live_session_is_refused_run_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7A.5, at the one place that admits a turn: ``BridgeRuntime.prompt``.

    Driven through the scripted fake sidecar (``HEPHAESTUS_NODE`` + a python
    ``dist_main``), so this is the real runtime wiring with no Node and no
    provider. The second prompt is issued from the **first run's own event
    callback** — the reader thread, while run A is registered and mid-turn — so
    the overlap is deterministic rather than timed.
    """
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.testing.projects import scaffold_project

    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    project_root = scaffold_project(tmp_path / "proj", name="inflight")
    runtime = BridgeRuntime(
        project_root=project_root,
        providers=[{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
        dist_main=FAKE_SIDECAR,
    )
    runtime.start()
    try:
        session_id = runtime.create_session("orchestrator", session_id="inflight-a")
        refused: list[RunInFlightError] = []

        def second_turn(_event: dict[str, Any]) -> None:
            if refused:
                return
            try:
                runtime.prompt(session_id, REQUEST_B, run_id="run-b")
            except RunInFlightError as exc:
                refused.append(exc)

        first = runtime.prompt(session_id, REQUEST_A, run_id="run-a", on_event=second_turn)
        assert first.status == "completed"

        assert refused, "a second turn on a live session was admitted"
        exc = refused[0]
        assert exc.code == "run_in_flight"
        assert exc.scope == "session"
        # It names the HOLDING session and run, not the refused one (§7A.5).
        assert (exc.session_id, exc.run_id) == (session_id, "run-a")
        # …and the refused turn started nothing: no binding, no admitted run.
        assert run_request_text("run-b") is None
        assert runtime.session_for_run("run-b") is None

        # The session is usable the moment the first turn is over.
        assert runtime.prompt(session_id, REQUEST_B).status == "completed"
    finally:
        runtime.close()


def test_a_live_run_id_cannot_be_reused_for_a_second_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``run_id`` clause: one key cannot carry two requests.

    This is "the binding cannot be honoured" literally — request text is keyed by
    run id, and two live turns on one id would be one key with two requests. It
    is refused across sessions, not only within one, because run ids are a single
    runtime-wide namespace (``BridgeRuntime.new_run_id`` owns it).
    """
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.testing.projects import scaffold_project

    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    project_root = scaffold_project(tmp_path / "proj", name="reuse")
    runtime = BridgeRuntime(
        project_root=project_root,
        providers=[{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
        dist_main=FAKE_SIDECAR,
    )
    runtime.start()
    try:
        held = runtime.create_session("orchestrator", session_id="reuse-a")
        other = runtime.create_session("orchestrator", session_id="reuse-b")
        refused: list[RunInFlightError] = []

        def same_id_from_another_session(_event: dict[str, Any]) -> None:
            if refused:
                return
            try:
                runtime.prompt(other, REQUEST_B, run_id="run-shared")
            except RunInFlightError as exc:
                refused.append(exc)

        first = runtime.prompt(
            held, REQUEST_A, run_id="run-shared", on_event=same_id_from_another_session
        )
        assert first.status == "completed"
        assert refused, "a live run id was reused"
        assert refused[0].scope == "run_id"
        assert (refused[0].session_id, refused[0].run_id) == (held, "run-shared")
    finally:
        runtime.close()


def test_two_sessions_may_think_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The interim restriction §19.23 buys back (§7A.5, §15.28's limit 12).

    While ``_request_text`` was per runtime the guard had to be project-wide —
    "an operator cannot ask the orchestrator something while a part session is
    thinking", in a workspace whose §7.1 renders three levels of concurrent
    sessions as nested tabs. With the text bound per run the scope narrows to per
    session and ``run_in_flight`` keeps its meaning, so this pair — the exact one
    §7A.2 sells — must now be admitted, genuinely overlapping.

    The sidecar is stubbed at the process boundary rather than scripted, because
    the two turns have to be **in flight at the same time**: the scripted fake
    answers a prompt before the next one can start, so it can prove a refusal
    (above) but never an admission. Everything above that boundary — the guard,
    the run table, the per-run binding — is the real runtime.
    """
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.testing.projects import scaffold_project

    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    project_root = scaffold_project(tmp_path / "proj", name="concurrent")
    runtime = BridgeRuntime(
        project_root=project_root,
        providers=[{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
        dist_main=FAKE_SIDECAR,
    )
    held = _HeldSidecar()
    runtime._sup = held  # type: ignore[assignment]  # the process boundary, stubbed
    try:
        orchestrator = runtime.create_session("orchestrator", session_id="concurrent-orch")
        part = runtime.create_session("part", part="widget", session_id="concurrent-part")
        outcomes: dict[str, Any] = {}

        def turn(key: str, session_id: str, text: str, run_id: str) -> None:
            try:
                outcomes[key] = runtime.prompt(session_id, text, run_id=run_id).status
            except BaseException as exc:  # a refusal here is the regression
                outcomes[key] = exc

        threads = [
            threading.Thread(target=turn, args=("orch", orchestrator, REQUEST_A, "run-orch")),
            threading.Thread(target=turn, args=("part", part, REQUEST_B, "run-part")),
        ]
        for t in threads:
            t.start()
        assert held.in_flight.wait(timeout=30), "neither turn reached the sidecar"
        # Both are mid-turn, and each reads its OWN request while they overlap.
        assert run_request_text("run-orch") == REQUEST_A
        assert run_request_text("run-part") == REQUEST_B
        held.release.set()
        for t in threads:
            t.join(timeout=30)

        assert outcomes == {"orch": "completed", "part": "completed"}, outcomes
        # Both bindings are released when their turns end — no leak into the next.
        assert run_request_text("run-orch") is None
        assert run_request_text("run-part") is None
    finally:
        held.release.set()
        runtime.close()


class _HeldSidecar:
    """A supervisor stub that holds every prompt open until released.

    Only the four members :meth:`BridgeRuntime.prompt` and :meth:`close` reach on
    the supervisor. It exists to make two turns genuinely concurrent; nothing
    about the guard, the run table or the binding is stubbed.
    """

    def __init__(self, *, expected: int = 2) -> None:
        self.release = threading.Event()
        self.in_flight = threading.Event()
        self._expected = expected
        self._live = 0
        self._lock = threading.Lock()

    def call(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        if method == "session.create":
            return {"session_id": params["session_id"]}
        if method != "session.prompt":  # pragma: no cover - nothing else is called
            return {}
        with self._lock:
            self._live += 1
            if self._live >= self._expected:
                self.in_flight.set()
        self.release.wait(timeout=60)
        with self._lock:
            self._live -= 1
        return {"status": "completed"}

    def track_run(self, run_id: str) -> None: ...

    def untrack_run(self, run_id: str) -> None: ...

    def notify(self, method: str, params: dict[str, Any]) -> None: ...

    def close(self) -> None: ...
