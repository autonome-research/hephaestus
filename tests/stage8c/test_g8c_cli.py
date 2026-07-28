"""G8C: ``heph assembly`` — the operator's view of the same measurement.

Gate clause: *``heph assembly`` human + ``--json``*.

The operator and the model must read the SAME document: the JSON the CLI prints
is asserted to be exactly the ``AssemblyStatus`` the ``check_assembly`` tool
returned, because a residual an operator quotes and a residual a model acted on
have to be one number or the evidence trail forks.

The two verbs are deliberately asymmetric (``ASSEMBLY.md`` §3) and the clause
covers both: ``heph assembly`` reports what was last measured — including that
nothing has been, and including which parts have been rebuilt since — while
``heph assembly check`` is the only one that measures. Exit codes follow the
engine CLI so a script can gate on assembly state: 0 clean, 1 for a status with
anything blocking in it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from _g8c import build_all, check, declare, lid_src, rewrite
from hephaestus.core.cli import main
from hephaestus.testing.tools_fixture import Project


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


@pytest.fixture
def declared(pair: Project) -> Project:
    """Two mates the geometry meets and one it does not, nothing measured yet."""
    declare(
        pair,
        "c-register-fit",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.05,
        max_mm=0.25,
    )
    declare(pair, "c-seat-flush", "coincident", "base:rim_top", "lid:seat_face", tol_mm=0.01)
    declare(
        pair,
        "c-too-tight",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.30,
        max_mm=0.40,
    )
    return pair


def test_a_project_that_never_measured_says_so_and_exits_zero(
    declared: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "Not measured" is a fact about the project, not a CLI failure — and not a pass."""
    declared.store.close()

    assert run(declared.root, monkeypatch, "assembly") == 0

    out = capsys.readouterr().out
    assert "3 constraint(s) declared, never evaluated" in out
    assert "heph assembly check" in out


def test_check_prints_the_table_and_exits_one_on_a_blocking_status(
    declared: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    declared.store.close()

    assert run(declared.root, monkeypatch, "assembly", "check") == 1

    out = capsys.readouterr().out
    header, *rows = [line for line in out.splitlines() if line.strip()]
    assert header.split() == ["id", "kind", "a", "b", "state", "measured", "detail"]
    table = {line.split()[0]: line for line in rows if line.startswith("c-")}
    # Every declared mate has a row naming its anchors and its measurement…
    assert "base:register_slot" in table["c-register-fit"]
    assert "lid:register_wall" in table["c-register-fit"]
    assert "0.15" in table["c-register-fit"] and "mm" in table["c-register-fit"]
    # …the satisfied ones read quietly, the failing one SHOUTS.
    assert " satisfied " in f" {table['c-register-fit']} "
    assert "VIOLATED" in table["c-too-tight"]
    assert "\ngeneration 3: 2 satisfied, 1 violated, 0 unresolvable" in out


def test_the_json_form_is_the_document_the_tool_returned(
    declared: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One measurement, two readers: the model's result and the operator's print."""
    from_tool = json.loads(json.dumps(check(declared)))
    declared.store.close()

    assert run(declared.root, monkeypatch, "assembly", "--json") == 1

    printed = cast("Mapping[str, Any]", json.loads(capsys.readouterr().out))
    assert printed == from_tool
    assert list(cast("list[Any]", printed["blocking"])) == ["c-too-tight"]


def test_a_named_subset_is_evaluated_without_being_projected(
    declared: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--id`` answers about one mate and does not overwrite the project's status."""
    declared.store.close()

    assert run(declared.root, monkeypatch, "assembly", "check", "--id", "c-seat-flush") == 0
    capsys.readouterr()

    assert (
        run(declared.root, monkeypatch, "assembly", "check", "--id", "c-too-tight", "--json") == 1
    )
    status = cast("Mapping[str, Any]", json.loads(capsys.readouterr().out))
    rows = cast("list[Any]", status["constraints"])
    assert [cast("Mapping[str, Any]", row)["id"] for row in rows] == ["c-too-tight"]

    # …and the project still reports never having measured its whole set.
    assert run(declared.root, monkeypatch, "assembly") == 0
    assert "never evaluated" in capsys.readouterr().out


def test_a_rebuild_since_the_last_check_is_reported_as_stale(
    declared: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The operator is told the number is old rather than handed a new one."""
    check(declared)
    rewrite(declared, "lid", lid_src(0.35))
    build_all(declared, "lid")
    declared.store.close()

    assert run(declared.root, monkeypatch, "assembly") == 1

    out = capsys.readouterr().out
    assert "stale: lid rebuilt since this status was measured" in out
    assert "heph assembly check" in out
    # Re-measuring clears the staleness and re-decides the two fits: 0.35 mm of
    # clearance is outside the slip window and inside the loose one, so the pair
    # of contradictory claims about one measurement swaps verdicts.
    capsys.readouterr()
    assert run(declared.root, monkeypatch, "assembly", "check", "--json") == 1
    status = cast("Mapping[str, Any]", json.loads(capsys.readouterr().out))
    assert list(cast("list[Any]", status["stale"])) == []
    assert list(cast("list[Any]", status["blocking"])) == ["c-register-fit"]


def test_a_project_with_no_constraints_at_all_is_not_an_error(
    pair: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pair.store.close()

    assert run(pair.root, monkeypatch, "assembly") == 0
    assert "no constraints declared" in capsys.readouterr().out
    assert run(pair.root, monkeypatch, "assembly", "check") == 0
    assert "no constraints declared" in capsys.readouterr().out
