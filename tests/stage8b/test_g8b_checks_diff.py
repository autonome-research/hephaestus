# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8B: a ``CHECKS`` predicate over ``m.diff`` (``COMPARE.md`` §2, contract §6).

Gate clause: *a ``CHECKS`` predicate over ``m.diff`` passing and failing on
either side of its named threshold*.

This is the clause that makes an editing task checkable the way ``VALIDATION.md``
§1 demands: a functional property with a named tolerance, evaluated by the
harness on every build and recorded in the artifact — not a model's assurance
that it got close enough. The two builds below differ only in whether the part
actually matches the seeded target, and the *same* predicate reads pass on one
and fail on the other.

Also asserted here, because it is what makes the check trustworthy: the
comparison target is a **build input**. It is frozen and hashed with the
script's own imports (INGEST.md §1), so replacing the file changes the recorded
inputs and the check's verdict together.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from _g8b import StepFixtures, build_ok, install_import, write_script
from hephaestus.testing.tools_fixture import Project

#: The predicate COMPARE.md §2 puts in the spec, verbatim in spirit: a named
#: tolerance on a functional property.
MATCHING_SRC = """part.geometry = Box(40.0, 20.0, 5.0)

CHECKS = {
    "matches_target": lambda m: m.diff("part", "import:target.step").iou >= 0.995,
}
"""

#: The same check on a part that is 3 mm too thick: same threshold, other side.
DRIFTED_SRC = """part.geometry = Box(40.0, 20.0, 8.0)

CHECKS = {
    "matches_target": lambda m: m.diff("part", "import:target.step").iou >= 0.995,
}
"""

#: A check whose target is another part, and one that reads a surface fact.
CROSS_SRC = """part.geometry = Box(40.0, 20.0, 5.0)

CHECKS = {
    "converged": lambda m: m.diff("part", "import:target.step").chamfer_mm <= 0.01,
    "no_new_holes": lambda m: m.diff("part", "import:target.step").genus_delta == 0,
}
"""


@pytest.fixture
def seeded(project: Project, steps: StepFixtures) -> Project:
    """A project whose ``imports/target.step`` is the 40 x 20 x 5 plate."""
    install_import(project.root, "target.step", steps.plate)
    return project


def _checks(project: Project, part: str) -> dict[str, Any]:
    """The part's CHECKS report, through the model's own ``run_checks`` tool."""
    report = cast("dict[str, Any]", project.call("run_checks", {"name": part}))
    assert report["status"] == "ok", report
    return cast("dict[str, Any]", report["checks"])


def _frozen_imports(project: Project, part: str) -> dict[str, str]:
    """``input_hashes.imports`` of the part's current build (§8 build record)."""
    current = project.cad.current_build(part)
    assert current is not None
    return dict(current.input_hashes.imports)


def test_the_predicate_passes_when_the_part_matches_the_target(seeded: Project) -> None:
    write_script(seeded, "widget_a", MATCHING_SRC)

    built = build_ok(seeded, "widget_a")

    assert built["status"] == "ok"
    check = cast("dict[str, Any]", _checks(seeded, "widget_a")["matches_target"])
    assert check["pass"] is True, check
    # The measured value is the WHOLE record, not the one number that was read:
    # the evidence behind a check outlives the predicate that asked for it.
    measured = cast("dict[str, Any]", check["measured"])
    assert cast("dict[str, Any]", measured["volume"])["iou"] == pytest.approx(1.0, abs=1e-6)
    assert measured["align"] == "as_posed"
    assert cast("dict[str, Any]", measured["surface"])["a_samples"] > 0


def test_the_same_predicate_fails_on_the_other_side_of_its_threshold(seeded: Project) -> None:
    write_script(seeded, "widget_b", DRIFTED_SRC)

    built = build_ok(seeded, "widget_b")

    check = cast("dict[str, Any]", _checks(seeded, "widget_b")["matches_target"])
    assert check["pass"] is False, check
    measured = cast("dict[str, Any]", check["measured"])
    iou = cast("dict[str, Any]", measured["volume"])["iou"]
    assert iou < 0.995
    # A failing check fails the report, never the build (§6).
    assert built["status"] == "ok"


def test_surface_and_topology_facts_are_available_to_predicates(seeded: Project) -> None:
    write_script(seeded, "widget_c", CROSS_SRC)

    built = build_ok(seeded, "widget_c")

    assert built["status"] == "ok"
    checks = _checks(seeded, "widget_c")
    assert cast("dict[str, Any]", checks["converged"])["pass"] is True
    assert cast("dict[str, Any]", checks["no_new_holes"])["pass"] is True


def test_the_comparison_target_is_a_frozen_build_input(seeded: Project) -> None:
    """Changed bytes are a changed build: the hash is recorded, the verdict moves."""
    write_script(seeded, "widget_d", MATCHING_SRC)
    built = build_ok(seeded, "widget_d")

    assert built["status"] == "ok"
    inputs = _frozen_imports(seeded, "widget_d")
    assert "target.step" in inputs, inputs
    assert inputs["target.step"].startswith("sha256:")
    assert cast("dict[str, Any]", _checks(seeded, "widget_d")["matches_target"])["pass"] is True


def test_replacing_the_target_file_flips_the_check(seeded: Project, steps: StepFixtures) -> None:
    write_script(seeded, "widget_e", MATCHING_SRC)
    build_ok(seeded, "widget_e")
    assert cast("dict[str, Any]", _checks(seeded, "widget_e")["matches_target"])["pass"] is True
    before = _frozen_imports(seeded, "widget_e")["target.step"]

    # An operator swaps the seeded target for a different solid.
    install_import(seeded.root, "target.step", steps.plate_taller)
    build_ok(seeded, "widget_e")

    after = _frozen_imports(seeded, "widget_e")["target.step"]
    assert after != before
    assert cast("dict[str, Any]", _checks(seeded, "widget_e")["matches_target"])["pass"] is False


def test_an_unresolvable_target_fails_the_check_not_the_build(project: Project) -> None:
    """No such import: the check's report entry carries the error, the build stands."""
    write_script(project, "widget_f", MATCHING_SRC)

    built = build_ok(project, "widget_f")

    assert built["status"] == "ok"
    check = cast("dict[str, Any]", _checks(project, "widget_f")["matches_target"])
    assert check["pass"] is False
    assert "error" in cast("dict[str, Any]", check["measured"])
