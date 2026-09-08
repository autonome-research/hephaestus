"""``core.executor.bounded_pass`` (J-build-state-5): the one bounded-subprocess loop.

Four call sites — ``project_compare.bounded_solid_diff``, ``motion``'s bounded
sweep, ``scan_compare.bounded_scan_distance`` and ``placement._verify`` —
hand-copy the same spawn/poll/deadline/drain/kill loop. The scan copy was the
only one that (a) drains the pipe once more *after* the deadline fires, so a
terminal message that landed in the final poll window is never discarded, and
(b) recomputes the death flag from that drain, so a run that answered can
never be reported as having died. ``core/executor/bounded_pass.py`` is the
extraction: one helper, with each call site keeping only its own message
protocol — an ``on_message(kind, payload) -> bool`` callback saying which
message is terminal — and its own refusal vocabulary.

The module is split in two, and this suite tests both halves for a reason.
``run_bounded_pass`` is the spawn wiring, exercised here through **real**
subprocesses (the ``_bounded_grind.py`` precedent) for the straightforward
cases: a clean answer, a crash, a silent ceiling. ``supervise`` is the
poll/deadline/drain/kill body over an *already-started* process and
connection, exercised here through a **scripted fake** process/connection pair
for the two genuinely timing-sensitive properties — a message the ceiling's
own poll window would otherwise miss, and a child that answered right as it
exited. Real wall-clock timing cannot reliably force a message into the
handful of microseconds either race needs; a fake driven by an explicit clock
can, exactly.

Third, two structural guards: :mod:`multiprocessing` may be imported by this
module and nothing else in the engine — which is what stops a fifth
hand-copied loop from appearing — and every child function a
``run_bounded_pass`` call site hands over must quiet the OCCT messenger, which
is what stops the next bounded pass from writing kernel diagnostics onto the
fd 1 it inherited (J-cli-robustness-14).
"""

from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.executor.bounded_pass import BoundedPassOutcome, run_bounded_pass, supervise

# ==========================================================================
# real-subprocess children — the straightforward, non-racy cases
#
# Module scope, stdlib-only (the ``_bounded_grind.py`` precedent): these are
# ``multiprocessing`` spawn targets and must start well inside the tiny
# ceilings the tests below set.

PID_FILE_ENV = "HEPHAESTUS_TEST_BOUNDED_PASS_PID_FILE"


def _report_pid() -> None:
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")


def _answering_child(conn: Any, message: str) -> None:
    """Sends one terminal message and exits cleanly."""
    _report_pid()
    conn.send(("done", message))
    conn.close()


def _streaming_child(conn: Any, prelude: str, message: str) -> None:
    """One non-terminal message, then the terminal one."""
    _report_pid()
    conn.send(("progress", prelude))
    conn.send(("done", message))
    conn.close()


def _dying_child(conn: Any, exit_code: int) -> None:
    """Exits with a known status and sends nothing."""
    _report_pid()
    conn.close()
    os._exit(exit_code)


def _dying_after_progress_child(conn: Any, prelude: str, exit_code: int) -> None:
    """Streams one non-terminal message, then dies without ever answering."""
    _report_pid()
    conn.send(("progress", prelude))
    conn.close()
    os._exit(exit_code)


def _silent_child(conn: Any) -> None:
    """Never answers at all."""
    _ = conn
    _report_pid()
    time.sleep(600.0)


def _terminal_on(*terminal_kinds: str) -> Any:
    """An ``on_message`` that treats any of ``terminal_kinds`` as terminal."""

    def _on_message(kind: str, _payload: Any) -> bool:
        return kind in terminal_kinds

    return _on_message


def _assert_child_dead(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_terminal_message_is_returned_and_the_child_is_reaped() -> None:
    outcome = run_bounded_pass(
        _answering_child, ("hello",), timeout_s=30.0, on_message=_terminal_on("done")
    )
    assert outcome.terminal == ("done", "hello")
    assert outcome.died is False
    assert outcome.cut_short is False
    # NOT asserted: the exact ``exit_code``. Once a terminal message is in
    # hand, the loop's own ``finally`` kills whatever is still alive without
    # waiting for it to finish exiting on its own (the same thing the
    # reference scan-copy does) — so a child that answered and was about to
    # exit cleanly can still be reaped as a killed process (-9). ``terminal``
    # is the success signal; ``exit_code`` is only meaningful on the death
    # path (see the dying-child tests below).


def test_a_non_terminal_message_does_not_end_the_pass() -> None:
    seen: list[tuple[str, Any]] = []

    def on_message(kind: str, payload: Any) -> bool:
        seen.append((kind, payload))
        return kind == "done"

    outcome = run_bounded_pass(
        _streaming_child, ("first", "second"), timeout_s=30.0, on_message=on_message
    )
    assert outcome.terminal == ("done", "second")
    assert seen == [("progress", "first"), ("done", "second")]


def test_a_child_that_dies_before_answering_is_reported_dead_with_its_exit_code(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"
    os.environ[PID_FILE_ENV] = str(pid_file)
    try:
        outcome = run_bounded_pass(
            _dying_child, (11,), timeout_s=30.0, on_message=_terminal_on("done")
        )
    finally:
        del os.environ[PID_FILE_ENV]
    assert outcome.terminal is None
    assert outcome.died is True
    assert outcome.exit_code == 11
    assert outcome.cut_short is True
    _assert_child_dead(pid_file)


def test_a_child_that_streams_then_dies_is_still_reported_dead() -> None:
    seen: list[tuple[str, Any]] = []

    def on_message(kind: str, payload: Any) -> bool:
        seen.append((kind, payload))
        return kind == "done"

    outcome = run_bounded_pass(
        _dying_after_progress_child, ("partial", 7), timeout_s=30.0, on_message=on_message
    )
    assert seen == [("progress", "partial")]
    assert outcome.terminal is None
    assert outcome.died is True
    assert outcome.exit_code == 7


def test_a_silent_child_is_killed_at_the_ceiling_and_reaped(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    os.environ[PID_FILE_ENV] = str(pid_file)
    try:
        outcome = run_bounded_pass(_silent_child, timeout_s=1.0, on_message=_terminal_on("done"))
    finally:
        del os.environ[PID_FILE_ENV]
    assert outcome.terminal is None
    # Killed by the ceiling, not a crash: the process was still alive when the
    # deadline fired, so this is the timeout case, not the death case.
    assert outcome.died is False
    _assert_child_dead(pid_file)


# ==========================================================================
# supervise: the two timing-sensitive properties, driven by a scripted fake


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start


class _FakeConn:
    """The parent end of a pipe, driven by a scripted ``(available_at, message)`` queue."""

    def __init__(self, clock: _FakeClock, schedule: list[tuple[float, Any]]) -> None:
        self._clock = clock
        self._schedule = list(schedule)

    def poll(self, timeout: float = 0.0) -> bool:
        call_deadline = self._clock.now + timeout
        if self._schedule and self._schedule[0][0] <= call_deadline:
            return True
        # Nothing arrives in this window: the call still consumes it, exactly
        # as a real blocking ``poll(timeout)`` would.
        self._clock.now = call_deadline
        return False

    def recv(self) -> Any:
        at, message = self._schedule.pop(0)
        self._clock.now = max(self._clock.now, at)
        return message

    def close(self) -> None:
        pass


class _FakeProc:
    def __init__(self, *, alive_until: float, exitcode: int, clock: _FakeClock) -> None:
        self._alive_until = alive_until
        self._exitcode_final = exitcode
        self._clock = clock
        self.killed = False

    def is_alive(self) -> bool:
        return self._clock.now < self._alive_until

    def kill(self) -> None:
        self.killed = True

    def join(self, timeout: float | None = None) -> None:
        pass

    @property
    def exitcode(self) -> int | None:
        return None if self.is_alive() else self._exitcode_final


def _patch_clock(monkeypatch: pytest.MonkeyPatch, clock: _FakeClock) -> None:
    import hephaestus.core.executor.bounded_pass as bounded_pass

    monkeypatch.setattr(
        bounded_pass.time,  # pyright: ignore[reportPrivateImportUsage]
        "monotonic",
        lambda: clock.now,
    )


def test_a_zero_budget_pass_whose_child_had_already_answered_is_not_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-deadline drain: with the ceiling already at "now", a message
    already sitting in the pipe is still read rather than discarded — the poll
    LOOP never runs at all here (``timeout_s=0``), so only the drain after it
    can be what finds this. A hand-written loop lacking the drain reports a
    timeout even though the child had already answered."""
    clock = _FakeClock(start=5.0)
    _patch_clock(monkeypatch, clock)
    parent = _FakeConn(clock, schedule=[(5.0, ("done", "the answer"))])
    proc = _FakeProc(alive_until=1000.0, exitcode=0, clock=clock)

    outcome = supervise(proc, parent, timeout_s=0.0, on_message=_terminal_on("done"))

    assert outcome.terminal == ("done", "the answer")
    assert outcome.died is False


def test_a_child_that_answers_right_as_it_exits_is_not_reported_as_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Death recomputation: the short poll misses the answer (it arrives just
    after that poll's own window), and by the time the loop notices the
    process is no longer alive, the death-drain's longer window finds the
    answer sitting there after all — so this must NOT be reported as a crash,
    which is exactly the bug the newest (scan) copy alone had fixed."""
    clock = _FakeClock()
    _patch_clock(monkeypatch, clock)
    # The short poll(0.05) call at t=0 covers [0, 0.05]; the message is not
    # visible until 0.1, so that call returns False and the clock lands on
    # 0.05 — exactly when the process is already gone. The death-drain's
    # longer window (``poll_s * 4`` == 0.2) then reaches all the way to 0.1.
    parent = _FakeConn(clock, schedule=[(0.1, ("done", "ok"))])
    proc = _FakeProc(alive_until=0.05, exitcode=0, clock=clock)

    outcome = supervise(proc, parent, timeout_s=10.0, on_message=_terminal_on("done"))

    assert outcome.terminal == ("done", "ok")
    assert outcome.died is False, "a run that answered must never be reported as having died"
    assert outcome.exit_code == 0


def test_a_child_that_truly_dies_silently_is_still_reported_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recomputation must not swing the other way and hide a real crash:
    nothing ever arrives, so ``died`` stays True."""
    clock = _FakeClock()
    _patch_clock(monkeypatch, clock)
    parent = _FakeConn(clock, schedule=[])
    proc = _FakeProc(alive_until=0.05, exitcode=9, clock=clock)

    outcome = supervise(proc, parent, timeout_s=10.0, on_message=_terminal_on("done"))

    assert outcome.terminal is None
    assert outcome.died is True
    assert outcome.exit_code == 9


def test_a_message_that_never_comes_yields_no_terminal_and_no_death(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ceiling with the child still alive throughout: neither answered nor
    died, and the still-alive child is killed."""
    clock = _FakeClock()
    _patch_clock(monkeypatch, clock)
    parent = _FakeConn(clock, schedule=[])
    proc = _FakeProc(alive_until=1000.0, exitcode=0, clock=clock)

    outcome = supervise(proc, parent, timeout_s=1.0, on_message=_terminal_on("done"))

    assert outcome.terminal is None
    assert outcome.died is False
    assert proc.killed, "the ceiling fired, so the still-alive child must be killed"


# ==========================================================================
# structural guard — only this module supervises a subprocess


ENGINE_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "hephaestus"

#: The one module allowed to import :mod:`multiprocessing` in the engine.
#: Everything else asking for a bounded subprocess pass must go through it —
#: this is what stops a fifth hand-copied loop.
_ALLOWED_MULTIPROCESSING_MODULE = "core/executor/bounded_pass.py"

_IMPORT_RE = re.compile(r"^\s*(import multiprocessing\b|from multiprocessing\b)", re.MULTILINE)


def test_multiprocessing_is_imported_by_the_helper_and_nowhere_else_in_the_engine() -> None:
    """J-build-state-5 names FOUR hand-copied loops (compare, motion, scan,
    placement); this guard checks the whole engine tree, and on first writing
    it caught a FIFTH the item does not name: ``core/mesh_solid.py``'s bounded
    sew (``MESH_INGEST.md`` §4.1), which duplicated the identical five-part
    loop *without* either of the two fixes the newest copy had earned. It has
    since been migrated onto ``run_bounded_pass`` too. The assertion stays
    strict — an allowlist would let the next copy in the way this one got in —
    so a sixth duplicate fails here rather than being laundered into a passing
    suite.
    """
    offenders: list[str] = []
    for path in ENGINE_SOURCE_ROOT.rglob("*.py"):
        rel = path.relative_to(ENGINE_SOURCE_ROOT).as_posix()
        if rel == _ALLOWED_MULTIPROCESSING_MODULE:
            continue
        text = path.read_text(encoding="utf-8")
        if _IMPORT_RE.search(text):
            offenders.append(rel)
    assert offenders == [], (
        "only core/executor/bounded_pass.py may import multiprocessing directly; "
        f"found it also in: {offenders} — route these through run_bounded_pass "
        "(J-build-state-5). Migrate the offender rather than silencing this "
        "assertion: the copies drift, which is the whole reason the helper exists."
    )


def test_bounded_pass_outcome_is_the_documented_shape() -> None:
    outcome = BoundedPassOutcome(terminal=("done", 1), died=False, exit_code=0)
    assert outcome.terminal == ("done", 1)
    assert outcome.died is False
    assert outcome.exit_code == 0
    assert outcome.cut_short is False
    assert BoundedPassOutcome(terminal=None, died=False, exit_code=None).cut_short is True


#: The child's first act, once it has bound OCP: move OCCT's printer off
#: ``std::cout``. Fd 1 is inherited from the parent, where ``docs/cli.md``
#: makes it the ``--json`` document and, under ``heph serve --mcp``, the
#: JSON-RPC transport itself.
_QUIET_CALL = "quiet_messenger"


def _bounded_pass_children() -> dict[str, list[str]]:
    """``{engine module: [child function names handed to run_bounded_pass]}``."""
    children: dict[str, list[str]] = {}
    for path in ENGINE_SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ENGINE_SOURCE_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "run_bounded_pass" or not node.args:
                continue
            target = node.args[0]
            if isinstance(target, ast.Name):
                children.setdefault(rel, []).append(target.id)
    return children


def test_every_bounded_child_quiets_the_kernel_messenger() -> None:
    """J-cli-robustness-14, structurally: fixing only ``step_io`` left the four
    bounded children able to print, because each spawns with the parent's fd 1
    and calls OCCT through paths that never touch ``step_io``'s guards. The
    guard cannot live in ``run_bounded_pass`` itself — the wiring is shared
    with children that hold no geometry and must not pay the kernel's import
    to start — so it lives in each child beside the import that binds OCP,
    and this test is what makes "each" mean *every*, including the next one.
    """
    call_sites = _bounded_pass_children()
    assert call_sites, "no run_bounded_pass call sites found — the guard would be vacuous"
    silent: list[str] = []
    for rel, names in sorted(call_sites.items()):
        tree = ast.parse((ENGINE_SOURCE_ROOT / rel).read_text(encoding="utf-8"))
        defined = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for child_name in names:
            child = defined.get(child_name)
            assert child is not None, (
                f"{rel}: run_bounded_pass({child_name}) names no function here"
            )
            calls = [
                inner
                for inner in ast.walk(child)
                if isinstance(inner, ast.Call)
                and (
                    (isinstance(inner.func, ast.Name) and inner.func.id == _QUIET_CALL)
                    or getattr(inner.func, "attr", None) == _QUIET_CALL
                )
            ]
            if not calls:
                silent.append(f"{rel}:{child_name}")
    assert silent == [], (
        f"every bounded child must call {_QUIET_CALL}() beside its geometry import "
        f"(J-cli-robustness-14); these do not: {silent}"
    )
