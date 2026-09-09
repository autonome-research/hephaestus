"""``core.placement``'s verification pass (J-build-state-3): a crash gets a name.

``_verify`` (``SOLVER.md`` §7, §10) used to raise one static-message
``solver_timeout`` for every non-terminal outcome — the ceiling, a kernel
crash, a child that dies at spawn, an OOM kill — because the loop had no death
flag to discriminate with and the closed run-time refusal vocabulary had no
member to name a death by. This item widens the vocabulary by one
(``verification_process_died``), adopts the shared
:func:`~hephaestus.core.executor.bounded_pass.run_bounded_pass` so the death
flag and exit code exist, and threads the caller's best iterate into *both*
branches — the ceiling used to carry none either, which ``SOLVER.md`` §6.3
promises every run-time refusal does.

These tests drive ``_verify`` directly with a stand-in for ``_verify_child``
(module-scope, stdlib-only), the narrowest fixture that exercises the split
without a real solve.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, cast

import hephaestus.core.placement as placement
import pytest
from hephaestus.core.placement import (
    PARAM_SOLVE_VERDICTS,
    POSE_SOLVE_VERDICTS,
    SOLVE_RUNTIME_REFUSALS,
    TRANSFORM_SOLVE_VERDICTS,
    VERIFY_TIMEOUT_ENV,
    SolveRunRefusal,
    _verify,  # pyright: ignore[reportPrivateUsage]
)

PID_FILE_ENV = "HEPHAESTUS_TEST_VERIFY_PID_FILE"


def _report_pid() -> None:
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")


def _dying_verify_child(conn: Any, spec: Any) -> None:
    """Dies at spawn without ever answering — a kernel crash or an OOM kill."""
    _ = (conn, spec)
    _report_pid()
    os._exit(11)


def _silent_verify_child(conn: Any, spec: Any) -> None:
    """Never answers: the pathological-B-rep-grind mode the ceiling exists for."""
    _ = (conn, spec)
    _report_pid()
    time.sleep(600.0)


def _assert_child_dead(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_verification_process_died_is_in_the_closed_runtime_vocabulary() -> None:
    assert "verification_process_died" in SOLVE_RUNTIME_REFUSALS


def test_verification_process_died_is_not_a_verdict_spelling() -> None:
    """The dangerous mistake the ledger names by name: a kill readable as an
    outcome. The reason must be disjoint from every verdict tuple in every
    solve space."""
    for verdicts in (POSE_SOLVE_VERDICTS, TRANSFORM_SOLVE_VERDICTS, PARAM_SOLVE_VERDICTS):
        assert "verification_process_died" not in verdicts


def test_a_dead_verification_child_is_verification_process_died_with_the_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(placement, "_verify_child", _dying_verify_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    with pytest.raises(SolveRunRefusal) as excinfo:
        _verify({}, timeout_s=120.0, payload={"best_iterate": {"x": 1.0}})

    refusal = excinfo.value
    assert refusal.reason == "verification_process_died"
    assert refusal.reason not in POSE_SOLVE_VERDICTS
    assert refusal.reason not in TRANSFORM_SOLVE_VERDICTS
    assert "11" in refusal.message
    document = refusal.to_json()
    assert document["reason"] == "verification_process_died"
    # SOLVER.md §6.3: every run-time refusal carries the best iterate.
    assert document["best_iterate"] == {"x": 1.0}
    _assert_child_dead(pid_file)


def test_a_genuine_verification_ceiling_still_says_solver_timeout_and_carries_the_iterate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half of the split, and the §6.3 regression this item names
    directly: a real ceiling must keep its own reason (not the death reason)
    and must now carry the best iterate, which it did not before this item —
    mirroring the solve-side timeout test."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(placement, "_verify_child", _silent_verify_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    with pytest.raises(SolveRunRefusal) as excinfo:
        _verify({}, timeout_s=1.0, payload={"best_iterate": {"x": 2.0}})

    refusal = excinfo.value
    assert refusal.reason == "solver_timeout"
    document = refusal.to_json()
    assert document["reason"] == "solver_timeout"
    assert document["best_iterate"] == {"x": 2.0}
    assert VERIFY_TIMEOUT_ENV in refusal.message
    _assert_child_dead(pid_file)


def test_the_solver_import_closure_clause_still_holds_after_adopting_the_shared_helper() -> None:
    """SOLVER.md §7: the verification pass must not drag ``hephaestus.geom.solve``
    into the parent. ``run_bounded_pass`` is pure Python with no geometry
    import, so importing it here must not have widened the closure — proven by
    checking the module actually imported for the split (``bounded_pass``)
    itself imports no geometry, rather than trusting the docstring's claim."""
    import ast

    from hephaestus.core.executor import bounded_pass

    tree = ast.parse(Path(bounded_pass.__file__).read_text(encoding="utf-8"))
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)
    geometry_imports = [
        name for name in imported_names if name.split(".")[0] in ("OCP", "build123d")
    ]
    assert geometry_imports == [], (
        f"core/executor/bounded_pass.py must import no geometry module, found: {geometry_imports}"
    )


# ==========================================================================
# J-agent-results-8b: an unresolvable solve records no sentinel generations


class _StubRequest:
    """The narrowest stand-in for a solve request: the record only echoes it."""

    space = "pose"

    def to_json(self) -> dict[str, Any]:
        return {"space": "pose", "targets": []}


def test_an_unresolvable_solve_records_null_generations_not_minus_one() -> None:
    """Minus one is not a generation (SOLVER.md §7.0 / §9).

    An unresolvable solve establishes neither the constraint- nor the
    joint-set generation, and the record used to say so with ``-1`` — a value
    inside the field's normal integer domain, so a consumer that records or
    diffs generations recorded minus one *as if it were one*. The fix is at
    the dataclass, not at a serialisation boundary, because the record's
    canonical form is the input to the §9 byte-identity claim: a null patched
    into a copy would leave the hashed bytes still carrying the sentinel.
    """
    from hephaestus.core.placement import (
        SolveUnresolvable,
        _unresolvable_record,  # pyright: ignore[reportPrivateUsage]
    )

    record = _unresolvable_record(
        cast("Any", _StubRequest()),
        SolveUnresolvable("stale_inputs", "the widget's build is not current", subject="widget"),
    )

    assert record.verdict == "unresolvable"
    assert record.constraint_generation is None
    assert record.joint_generation is None
    document = record.to_json()
    assert document["constraint_generation"] is None
    assert document["joint_generation"] is None
    # The canonical form is what is hashed and compared byte for byte, so the
    # sentinel has to be gone from THAT, not merely from an accessor.
    canonical = record.canonical()
    assert '"constraint_generation":null' in canonical.replace(" ", "")
    assert "-1" not in canonical
    # The refusal's own facts are unaffected: nulling what was never
    # established must not cost what was.
    assert record.reason == "stale_inputs"
    assert record.subject == "widget"


def test_no_solve_record_construction_still_passes_a_generation_sentinel() -> None:
    """The other unresolvable constructor (parameter/transform space) is inline
    in ``solve_placement``'s handler and cannot be reached with a stub, so the
    guard is structural: ``-1`` may not be assigned to either generation
    anywhere in the module. It is the same shape of guard as the
    multiprocessing one — an allowlist would let the next copy back in."""
    source = Path(placement.__file__).read_text(encoding="utf-8")
    offenders = [
        line.strip() for line in source.splitlines() if "generation=-1" in line.replace(" ", "")
    ]
    assert offenders == [], (
        f"a solve record still encodes an unestablished generation as -1: {offenders} "
        "(J-agent-results-8b — 'not established' is null)"
    )
