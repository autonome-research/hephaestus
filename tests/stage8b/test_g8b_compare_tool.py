# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8B: ``compare_solids`` through the dispatcher (``COMPARE.md`` §2).

Gate clauses covered here:

* *``compare_solids`` through dispatch against both ``part:`` and ``import:``
  targets with import-hash attribution and confinement refusals intact*;
* the product-level readings of the §1 clauses the tool is the delivery vehicle
  for: identity, a rigid-transformed copy under both frames, a known local edit,
  and determinism across two calls.

The subject is what a model sees. A refusal is asserted as the stable machine
token it is handed — never as an exception escaping the harness, and never as a
message that leaked the content of a file it was not allowed to reach.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest
from _g8b import (
    HOLE_MM3,
    PLATE_MM3,
    StepFixtures,
    build_ok,
    compare,
    install_import,
    write_script,
)
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.testing.tools_fixture import Project

PLATE_SRC = "part.geometry = Box(40.0, 20.0, 5.0)\n"
MOVED_SRC = (
    "body = Box(40.0, 20.0, 5.0).moved(Location((13.0, -7.0, 4.0)))\n"
    "part.geometry = body.moved(Rotation(0.0, 0.0, 35.0))\n"
)
HOLED_SRC = "part.geometry = Box(40.0, 20.0, 5.0) - Cylinder(3.0, 20.0)\n"


@pytest.fixture
def plated(project: Project, steps: StepFixtures) -> Project:
    """A project whose ``imports/`` carries the plate and its variations."""
    install_import(project.root, "plate.step", steps.plate)
    install_import(project.root, "plate_moved.step", steps.plate_moved)
    install_import(project.root, "plate_holed.step", steps.plate_holed)
    return project


# ==========================================================================
# part: targets


def test_a_part_compared_with_itself_is_identical(project: Project) -> None:
    """Identity: zero mismatch volume, iou 1.0, zero chamfer — through the tool."""
    write_script(project, "plate", PLATE_SRC)
    build_ok(project, "plate")

    result = compare(project, "plate", "part:plate")

    diff = cast("dict[str, Any]", result["diff"])
    volume = cast("dict[str, Any]", diff["volume"])
    surface = cast("dict[str, Any]", diff["surface"])
    assert volume["iou"] == pytest.approx(1.0, abs=1e-9)
    assert volume["a_only_mm3"] == pytest.approx(0.0, abs=1e-6)
    assert volume["b_only_mm3"] == pytest.approx(0.0, abs=1e-6)
    assert surface["chamfer_mm"] == pytest.approx(0.0, abs=1e-9)
    assert surface["max_deviation_mm"] == pytest.approx(0.0, abs=1e-9)
    # The counts behind those means are reported, never implied.
    assert surface["a_samples"] > 0 and surface["b_samples"] > 0


def test_both_operands_are_attributed_to_the_artifacts_they_were_read_from(
    project: Project,
) -> None:
    """A comparison names its evidence: two artifact refs, both resolved."""
    write_script(project, "plate", PLATE_SRC)
    write_script(project, "holed", HOLED_SRC)
    build_ok(project, "plate")
    build_ok(project, "holed")

    result = compare(project, "holed", "part:plate")

    a = cast("dict[str, Any]", result["a"])
    b = cast("dict[str, Any]", result["b"])
    assert a["kind"] == "part" and a["name"] == "holed"
    assert b["kind"] == "part" and b["name"] == "plate"
    assert a["artifact_ref"] and b["artifact_ref"]
    assert a["artifact_ref"] != b["artifact_ref"]
    assert result["resolved_artifact_refs"] == [a["artifact_ref"], b["artifact_ref"]]


def test_a_known_local_edit_shows_up_as_the_cylinder_volume(project: Project) -> None:
    """A drilled hole: ``b_only`` is exactly the removed cylinder, ``a_only`` nothing."""
    write_script(project, "plate", PLATE_SRC)
    write_script(project, "holed", HOLED_SRC)
    build_ok(project, "plate")
    build_ok(project, "holed")

    volume = cast(
        "dict[str, Any]",
        cast("dict[str, Any]", compare(project, "holed", "part:plate")["diff"])["volume"],
    )

    # a = the holed plate, b = the solid one: the plate has material the holed
    # part does not, and the holed part has none the plate lacks.
    assert volume["b_only_mm3"] == pytest.approx(HOLE_MM3, rel=1e-3)
    assert volume["a_only_mm3"] == pytest.approx(0.0, abs=1e-6)
    assert volume["common_mm3"] == pytest.approx(PLATE_MM3 - HOLE_MM3, rel=1e-3)


def test_the_chamfer_localizes_the_edit(project: Project) -> None:
    """A local edit reads as one: a big max deviation over a small mean."""
    write_script(project, "plate", PLATE_SRC)
    write_script(project, "holed", HOLED_SRC)
    build_ok(project, "plate")
    build_ok(project, "holed")

    surface = cast(
        "dict[str, Any]",
        cast("dict[str, Any]", compare(project, "holed", "part:plate")["diff"])["surface"],
    )

    # The bore wall is the only place the two surfaces disagree, so the worst
    # deviation sits an order of magnitude above the symmetric mean: that ratio
    # is what tells an editing model "one feature is wrong", not "everything is".
    assert surface["max_deviation_mm"] > 1.0
    assert 0.0 < surface["chamfer_mm"] < surface["max_deviation_mm"] / 10.0
    # …and the disagreement is on the drilled side: a's samples are the ones
    # sitting on a wall b does not have.
    assert surface["a_to_b_mean_mm"] > surface["b_to_a_mean_mm"] > 0.0


def test_the_topology_census_names_the_hole(project: Project) -> None:
    """The cheap first look: a cylindrical face and a genus, before any threshold."""
    write_script(project, "plate", PLATE_SRC)
    write_script(project, "holed", HOLED_SRC)
    build_ok(project, "plate")
    build_ok(project, "holed")

    topology = cast(
        "dict[str, Any]",
        cast("dict[str, Any]", compare(project, "holed", "part:plate")["diff"])["topology"],
    )

    assert cast("dict[str, Any]", topology["a"])["cylindrical_faces"] == 1
    assert cast("dict[str, Any]", topology["b"])["cylindrical_faces"] == 0
    assert topology["cylindrical_faces_delta"] == -1
    assert topology["genus_delta"] == -1  # b - a: the plate has no through hole


# ==========================================================================
# alignment is a declared choice


def test_a_rigid_copy_disagrees_as_posed_and_agrees_under_principal(project: Project) -> None:
    """Both answers are correct; the record always says which question was asked."""
    write_script(project, "plate", PLATE_SRC)
    write_script(project, "moved", MOVED_SRC)
    build_ok(project, "plate")
    build_ok(project, "moved")

    as_posed = compare(project, "moved", "part:plate")
    principal = compare(project, "moved", "part:plate", align="principal")

    assert as_posed["align"] == "as_posed"
    assert cast("dict[str, Any]", as_posed["diff"])["align"] == "as_posed"
    assert cast("dict[str, Any]", cast("dict[str, Any]", as_posed["diff"])["volume"])["iou"] < 0.5
    assert principal["align"] == "principal"
    assert cast("dict[str, Any]", principal["diff"])["align"] == "principal"
    assert cast("dict[str, Any]", cast("dict[str, Any]", principal["diff"])["volume"])[
        "iou"
    ] == pytest.approx(1.0, abs=1e-6)


def test_an_unknown_alignment_mode_is_refused(project: Project) -> None:
    """``align`` is an enum, and an unknown one is a named refusal, not a default."""
    write_script(project, "plate", PLATE_SRC)
    build_ok(project, "plate")

    with pytest.raises(DispatchError) as excinfo:
        compare(project, "plate", "part:plate", align="whatever")
    assert excinfo.value.reason in ("invalid_params", "schema_invalid")


# ==========================================================================
# import: targets — the Stage 8A machinery, unchanged


def test_an_import_target_is_attributed_to_its_content_hash(plated: Project) -> None:
    """The comparison names the exact bytes it was computed against."""
    write_script(plated, "plate", PLATE_SRC)
    build_ok(plated, "plate")

    result = compare(plated, "plate", "import:plate.step")

    b = cast("dict[str, Any]", result["b"])
    expected = (
        "sha256:"
        + hashlib.sha256((plated.root / "imports" / "plate.step").read_bytes()).hexdigest()
    )
    assert b["kind"] == "import"
    assert b["path"] == "plate.step"
    assert b["sha256"] == expected
    assert b["snapshot_ref"].endswith(expected)
    assert b["snapshot_ref"] in result["resolved_artifact_refs"]
    # …and the geometry really is the imported plate.
    volume = cast("dict[str, Any]", cast("dict[str, Any]", result["diff"])["volume"])
    assert volume["iou"] == pytest.approx(1.0, abs=1e-6)


def test_replacing_the_imported_file_changes_the_hash_and_the_answer(
    plated: Project, steps: StepFixtures
) -> None:
    """A changed file is changed evidence: new hash, new numbers, same call."""
    write_script(plated, "plate", PLATE_SRC)
    build_ok(plated, "plate")
    before = compare(plated, "plate", "import:plate.step")

    install_import(plated.root, "plate.step", steps.plate_taller)
    after = compare(plated, "plate", "import:plate.step")

    assert (
        cast("dict[str, Any]", before["b"])["sha256"]
        != cast("dict[str, Any]", after["b"])["sha256"]
    )
    assert cast("dict[str, Any]", cast("dict[str, Any]", after["diff"])["volume"])["iou"] < 0.7


def test_an_import_target_compares_against_a_locally_edited_part(plated: Project) -> None:
    """The editing loop's shape: import → modify → compare → converge."""
    write_script(plated, "holed", HOLED_SRC)
    build_ok(plated, "holed")

    against_source = compare(plated, "holed", "import:plate.step")
    against_target = compare(plated, "holed", "import:plate_holed.step")

    source_iou = cast("dict[str, Any]", cast("dict[str, Any]", against_source["diff"])["volume"])[
        "iou"
    ]
    target_iou = cast("dict[str, Any]", cast("dict[str, Any]", against_target["diff"])["volume"])[
        "iou"
    ]
    # Convergence is measured, not asserted: the edit moved the part towards
    # the target and away from the untouched vendor solid.
    assert target_iou == pytest.approx(1.0, abs=1e-6)
    assert source_iou < target_iou


def test_a_missing_import_names_the_file_and_refuses(plated: Project) -> None:
    write_script(plated, "plate", PLATE_SRC)
    build_ok(plated, "plate")

    with pytest.raises(DispatchError) as excinfo:
        compare(plated, "plate", "import:absent.step")
    assert excinfo.value.reason == "unknown_import"
    assert "absent.step" in str(excinfo.value)


def test_a_traversing_import_target_is_refused_without_leaking_the_file(
    plated: Project,
) -> None:
    """Confinement is the INGEST.md §1 walk, and it holds for comparison too."""
    (plated.root / "secret.txt").write_text("SECRET-CONTENT-42\n", encoding="utf-8")
    write_script(plated, "plate", PLATE_SRC)
    build_ok(plated, "plate")

    with pytest.raises(DispatchError) as excinfo:
        compare(plated, "plate", "import:../secret.txt")
    assert excinfo.value.reason == "path_confinement"
    assert "SECRET-CONTENT-42" not in str(excinfo.value)


def test_a_symlinked_import_target_is_refused(plated: Project) -> None:
    outside = plated.root.parent / "outside.step"
    outside.write_bytes(b"not a step file\n")
    (plated.root / "imports" / "escape.step").symlink_to(outside)
    write_script(plated, "plate", PLATE_SRC)
    build_ok(plated, "plate")

    with pytest.raises(DispatchError) as excinfo:
        compare(plated, "plate", "import:escape.step")
    assert excinfo.value.reason == "path_confinement"


def test_an_unparseable_import_is_named_as_such(plated: Project) -> None:
    install_import(plated.root, "broken.step", b"ISO-10303-21;\nnot really\n")
    write_script(plated, "plate", PLATE_SRC)
    build_ok(plated, "plate")

    with pytest.raises(DispatchError) as excinfo:
        compare(plated, "plate", "import:broken.step")
    assert excinfo.value.reason == "unreadable_step"


def test_a_target_that_is_neither_form_is_refused(plated: Project) -> None:
    write_script(plated, "plate", PLATE_SRC)
    build_ok(plated, "plate")

    with pytest.raises(DispatchError) as excinfo:
        compare(plated, "plate", "plate.step")
    assert excinfo.value.reason == "invalid_params"


# ==========================================================================
# scope, preconditions, determinism


def test_a_bound_part_session_may_not_reach_another_part_through_a_target(
    project: Project,
) -> None:
    """A ``part:`` target addresses that part, so object scope applies to it."""
    write_script(project, "plate", PLATE_SRC)
    write_script(project, "holed", HOLED_SRC)
    build_ok(project, "plate")
    build_ok(project, "holed")
    bound = Principal(session_id="s-part", profile="part", part="holed")

    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "compare_solids",
            {"part": "holed", "target": "part:plate"},
            principal=bound,
        )
    assert excinfo.value.reason == "scope_denied"
    # …and the same session may compare its own part against an import.
    project.call(
        "compare_solids",
        {"part": "holed", "target": "part:holed"},
        principal=bound,
    )


def test_a_part_with_no_current_build_cannot_be_compared(project: Project) -> None:
    write_script(project, "plate", PLATE_SRC)  # written, never built

    with pytest.raises(DispatchError) as excinfo:
        compare(project, "plate", "part:plate")
    assert excinfo.value.reason == "invalid_part"


def test_two_calls_return_identical_records(plated: Project) -> None:
    """Determinism at the surface: no RNG, no cache, same numbers twice."""
    write_script(plated, "holed", HOLED_SRC)
    build_ok(plated, "holed")

    first = compare(plated, "holed", "import:plate.step")
    second = compare(plated, "holed", "import:plate.step")

    assert first["diff"] == second["diff"]
