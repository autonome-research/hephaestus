"""``heph assembly`` / ``heph assembly check`` — the operator's view (§3).

The verb group is what makes a declared constraint inspectable without a model
in the loop: an operator (or a script) asks the project what it claims and
whether those claims currently hold, in a table or as JSON. Pinned here: both
output modes carry the same facts, ``check`` re-measures where the bare verb
reports the projection, staleness is *said* rather than silently repaired, and
the exit code follows the never-green rule so a build script can gate on it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _assembly_project import build_part, fit_entry, open_project, pin_script
from hephaestus.core.assembly import AssemblyEvaluator
from hephaestus.core.cli import main
from hephaestus.core.project_store.constraints import ConstraintSet
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher

from opstore import OpStore


@pytest.fixture
def project(tmp_path: Path) -> Iterator[tuple[ProjectLayout, OpStore]]:
    layout, store = open_project(tmp_path / "proj")
    yield layout, store
    store.close()


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    """Invoke the real CLI entry point with the project as the working directory."""
    monkeypatch.chdir(root)
    return main(list(argv))


def emitted(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    return payload


class TestReporting:
    def test_a_project_with_no_constraints_says_so(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        store.close()
        assert run(layout.root, monkeypatch, "assembly") == 0
        assert "no constraints declared" in capsys.readouterr().out

    def test_declared_but_never_evaluated_is_not_reported_as_passing(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        ConstraintSet(layout, store).declare(fit_entry())
        store.close()

        assert run(layout.root, monkeypatch, "assembly") == 0
        assert "never evaluated" in capsys.readouterr().out

        assert run(layout.root, monkeypatch, "assembly", "--json") == 0
        payload = emitted(capsys)
        assert payload["status"] == "not_evaluated"
        assert payload["constraints"][0]["id"] == "c-pin-fit"

    def test_check_measures_and_the_table_carries_the_residual(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        ConstraintSet(layout, store).declare(fit_entry())
        store.close()

        assert run(layout.root, monkeypatch, "assembly", "check") == 0
        out = capsys.readouterr().out
        assert "c-pin-fit" in out
        assert "base:bore_face" in out
        assert "0.1 mm" in out
        assert "1 satisfied, 0 violated, 0 unresolvable" in out

    def test_json_mode_is_the_status_document(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        ConstraintSet(layout, store).declare(fit_entry())
        store.close()

        assert run(layout.root, monkeypatch, "assembly", "check", "--json") == 0
        checked = emitted(capsys)
        assert checked["counts"] == {"satisfied": 1, "violated": 0, "unresolvable": 0}
        assert checked["constraints"][0]["residual"]["measured"] == pytest.approx(0.1, abs=1e-9)
        assert checked["blocking"] == []

        # The bare verb reports the projection the check just wrote.
        assert run(layout.root, monkeypatch, "assembly", "--json") == 0
        reported = emitted(capsys)
        assert reported["constraints"] == checked["constraints"]

    def test_a_named_subset_is_evaluated_alone(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        constraints = ConstraintSet(layout, store)
        constraints.declare(fit_entry())
        constraints.declare(fit_entry(id="c-two"))
        store.close()

        assert run(layout.root, monkeypatch, "assembly", "check", "--id", "c-two", "--json") == 0
        payload = emitted(capsys)
        assert [item["id"] for item in payload["constraints"]] == ["c-two"]


class TestExitCodesAndStaleness:
    def test_a_violated_constraint_exits_nonzero_in_both_modes(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        ConstraintSet(layout, store).declare(fit_entry(min_mm=0.2, max_mm=0.4))
        store.close()

        assert run(layout.root, monkeypatch, "assembly", "check") == 1
        assert "VIOLATED" in capsys.readouterr().out
        assert run(layout.root, monkeypatch, "assembly") == 1
        assert run(layout.root, monkeypatch, "assembly", "--json") == 1
        assert emitted(capsys)["blocking"] == ["c-pin-fit"]

    def test_an_unresolvable_constraint_also_blocks(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        ConstraintSet(layout, store).declare(fit_entry(a="ghost:bore_face"))
        store.close()

        assert run(layout.root, monkeypatch, "assembly", "check", "--json") == 1
        payload = emitted(capsys)
        assert payload["constraints"][0]["state"] == "unresolvable"
        assert payload["constraints"][0]["reason"] == "missing_part"
        assert payload["blocking"] == ["c-pin-fit"]

    def test_a_rebuild_shows_up_as_stale_not_as_a_new_number(
        self,
        project: tuple[ProjectLayout, OpStore],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, store = project
        ConstraintSet(layout, store).declare(fit_entry())
        AssemblyEvaluator(layout, store).evaluate()

        layout.part_path("pin").write_text(pin_script(4.99), encoding="utf-8")
        build_part(Publisher(layout, store), layout, "pin")
        store.close()

        assert run(layout.root, monkeypatch, "assembly") == 0
        out = capsys.readouterr().out
        assert "stale: pin rebuilt since this status was measured" in out

        assert run(layout.root, monkeypatch, "assembly", "check") == 1
        rechecked = capsys.readouterr().out
        assert "VIOLATED" in rechecked
        assert "stale" not in rechecked
