# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8B: the cheap first look, and the same numbers in a second process.

Two gate clauses, both about trusting a comparison rather than computing one:

* *topology-only census on shapes too different to boolean cheaply* — the
  census is a function of the two shapes alone (``COMPARE.md`` §1: "the cheap
  first look before any boolean runs"), so it answers for solids a symmetric
  difference has no business being asked about: disjoint, unequal in face
  count, unequal in genus. Here it is exercised the way an external scorer and
  the tool would reach it — off STEP files through ``geom.step_io``, and off a
  real comparison through the dispatcher;
* *determinism (two separate processes, identical records to 1e-9, identical
  sample counts)* — asserted at the **product** surface: ``heph diff --json``
  run twice in two fresh interpreters over the same project must print the same
  document. The record-level version of this clause lives in
  ``core/tests/test_geom_compare.py``; what is added here is that nothing
  between the project store and the printed JSON — artifact resolution, import
  snapshotting, serialization — introduces a run-to-run difference.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from _g8b import StepFixtures, build_ok, compare, install_import, write_script
from hephaestus.testing.tools_fixture import Project

PLATE_SRC = "part.geometry = Box(40.0, 20.0, 5.0)\n"
HOLED_SRC = "part.geometry = Box(40.0, 20.0, 5.0) - Cylinder(3.0, 20.0)\n"
#: A part that shares no space at all with the plate: 500 mm away, and a
#: different kind of solid. Nothing useful comes out of a boolean here.
ELSEWHERE_SRC = "part.geometry = Cylinder(2.0, 9.0).moved(Location((500.0, 0.0, 0.0)))\n"


# ==========================================================================
# the census, with no boolean under it


def test_the_census_answers_for_solids_that_share_no_space(steps: StepFixtures) -> None:
    """Straight off two STEP files: counts, kinds and genus, no symmetric difference.

    This is the call an external scorer makes before it decides whether a
    submission is worth booleaning at all, so it runs where the engine does not:
    ``geom.step_io`` in, ``geom.topology_diff`` out.
    """
    from build123d import Cylinder, Location
    from hephaestus.geom import read_step_bytes, topology_diff

    plate = read_step_bytes(steps.plate)
    holed = read_step_bytes(steps.plate_holed)

    census = topology_diff(plate, holed)

    # b is the drilled plate: one more face, and that face is a cylinder.
    assert census.a.planar_faces == 6 and census.a.cylindrical_faces == 0
    assert census.b.cylindrical_faces == 1
    assert census.faces_delta == 1
    assert census.cylindrical_faces_delta == 1
    assert census.planar_faces_delta == 0
    assert census.genus_delta == 1
    assert census.a.sealed and census.b.sealed and not census.sealed_changed
    assert census.solids_delta == 0

    # …and for two solids with nothing whatever in common, where the answer is
    # "these are different objects", the census still reports every field.
    far = Cylinder(2.0, 9.0).moved(Location((500.0, 0.0, 0.0)))
    apart = topology_diff(plate, far)
    assert apart.solids_delta == 0
    assert apart.planar_faces_delta == -4  # six plate faces vs two cylinder caps
    assert apart.cylindrical_faces_delta == 1
    assert apart.genus_delta == 0
    assert apart.a.edges > 0 and apart.b.edges > 0


def test_the_census_is_pose_invariant_where_the_volumes_are_not(steps: StepFixtures) -> None:
    """The rigid copy: as-posed volumes disagree, the census cannot."""
    from hephaestus.geom import read_step_bytes, topology_diff, volume_diff

    plate = read_step_bytes(steps.plate)
    moved = read_step_bytes(steps.plate_moved)

    assert volume_diff(plate, moved).iou < 0.5  # as posed, they are elsewhere
    census = topology_diff(plate, moved)
    assert (census.faces_delta, census.edges_delta, census.genus_delta) == (0, 0, 0)
    assert census.a == census.b
    assert not census.sealed_changed


def test_a_comparison_of_disjoint_solids_still_carries_its_census(
    project: Project, steps: StepFixtures
) -> None:
    """Through the tool: zero overlap is a number, and the census explains it."""
    install_import(project.root, "plate.step", steps.plate)
    write_script(project, "elsewhere", ELSEWHERE_SRC)
    build_ok(project, "elsewhere")

    result = compare(project, "elsewhere", "import:plate.step")

    diff = cast("dict[str, Any]", result["diff"])
    volume = cast("dict[str, Any]", diff["volume"])
    assert volume["common_mm3"] == pytest.approx(0.0, abs=1e-9)
    assert volume["iou"] == pytest.approx(0.0, abs=1e-12)
    assert volume["a_only_mm3"] > 0.0 and volume["b_only_mm3"] > 0.0
    topology = cast("dict[str, Any]", diff["topology"])
    assert cast("dict[str, Any]", topology["a"])["cylindrical_faces"] == 1
    assert cast("dict[str, Any]", topology["b"])["planar_faces"] == 6
    assert topology["planar_faces_delta"] == 4
    assert topology["genus_delta"] == 0
    # The surface figures are real distances, and they say how far apart:
    # the census said "different objects", this says "half a metre away".
    surface = cast("dict[str, Any]", diff["surface"])
    assert surface["max_deviation_mm"] > 400.0


# ==========================================================================
# two processes, one answer


_CLI_PROGRAM = """
import sys
from hephaestus.core.cli import main
sys.exit(main(sys.argv[1:]))
"""


def heph(root: Path, *argv: str) -> str:
    """Run ``heph`` in a fresh interpreter rooted at the project."""
    result = subprocess.run(
        [sys.executable, "-c", _CLI_PROGRAM, *argv],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"heph {' '.join(argv)} failed:\n{result.stderr}"
    return result.stdout


@pytest.fixture
def built(project: Project, steps: StepFixtures) -> Project:
    install_import(project.root, "plate.step", steps.plate)
    write_script(project, "holed", HOLED_SRC)
    build_ok(project, "holed")
    project.store.close()  # the subprocesses open the same store
    return project


@pytest.mark.parametrize("align", ["as_posed", "principal"])
def test_two_processes_print_the_same_comparison(built: Project, align: str) -> None:
    first = heph(built.root, "diff", "holed", "import:plate.step", "--align", align, "--json")
    second = heph(built.root, "diff", "holed", "import:plate.step", "--align", align, "--json")

    # Byte-identical is the strongest form of the clause, and it is what a
    # regression-diffing operator relies on when they diff two runs' output.
    assert first == second
    reported = cast("dict[str, Any]", json.loads(first))
    diff = cast("dict[str, Any]", reported["diff"])
    assert diff["align"] == align
    # …and to the terms the gate states: numbers to 1e-9, sample counts exactly.
    other = cast("dict[str, Any]", cast("dict[str, Any]", json.loads(second))["diff"])
    for section in ("volume", "surface"):
        here = cast("dict[str, Any]", diff[section])
        there = cast("dict[str, Any]", other[section])
        assert sorted(here) == sorted(there)
        for key, value in here.items():
            if isinstance(value, float):
                assert there[key] == pytest.approx(value, abs=1e-9), key
            else:
                assert there[key] == value, key
    surface = cast("dict[str, Any]", diff["surface"])
    assert surface["a_samples"] > 0 and surface["b_samples"] > 0


def test_a_symmetric_part_aligns_the_same_way_in_a_second_process(
    project: Project, steps: StepFixtures
) -> None:
    """The tie-break clause at the product surface: a cube has no unique frame.

    ``principal_alignment`` must still choose one deterministically, or a
    symmetric part would score differently on two machines. The comparison is a
    cube against the plate, so the printed numbers depend on which frame the
    cube's tied moments resolved to.
    """
    install_import(project.root, "plate.step", steps.plate)
    write_script(project, "cube", "part.geometry = Box(10.0, 10.0, 10.0)\n")
    build_ok(project, "cube")
    project.store.close()

    outputs = {
        heph(project.root, "diff", "cube", "import:plate.step", "--align", "principal", "--json")
        for _ in range(2)
    }

    assert len(outputs) == 1, "a symmetric part's principal frame is not reproducible"
    diff = cast("dict[str, Any]", cast("dict[str, Any]", json.loads(outputs.pop()))["diff"])
    assert 0.0 < cast("dict[str, Any]", diff["volume"])["iou"] < 1.0
