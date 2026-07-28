# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G8B (solid comparison) evidence suite.

Every G8B clause here is asserted against a **real project driven through the
real tool dispatcher**, the real CLI, or the real bench scorer — the surfaces a
model, an operator and an external benchmark actually use. The exhaustive
unit coverage of the geometry itself lives in ``core/tests/test_geom_compare.py``
(``COMPARE.md`` §1: identity, alignment, known edits, cross-process
determinism); this suite is the gate evidence, so what it asserts is *product
behaviour* — what a model can compare, what it is refused, what an operator
sees, and what an external scorer decides.

The STEP fixtures are authored here rather than imported from ``core/tests`` or
``corpus/`` so a gate assertion cannot be satisfied by a change to somebody
else's fixture. They are written once per session (OCCT stamps a timestamp into
the STEP header, so identical bytes must be produced once and reused) and handed
round as bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hephaestus.testing.tools_fixture import Project

__all__ = [
    "HOLE_MM3",
    "PLATE_MM3",
    "PLATE_X",
    "PLATE_Y",
    "PLATE_Z",
    "StepFixtures",
    "build_ok",
    "compare",
    "install_import",
    "make_step_fixtures",
    "write_script",
]

#: The plate fixture: 40 x 20 x 5 mm.
PLATE_X, PLATE_Y, PLATE_Z = 40.0, 20.0, 5.0
PLATE_MM3 = PLATE_X * PLATE_Y * PLATE_Z

#: The Ø6 hole drilled through it (the "known local edit" clause).
HOLE_MM3 = 3.0 * 3.0 * 3.14159265358979 * PLATE_Z


@dataclass(frozen=True)
class StepFixtures:
    """The session's STEP bytes: the plate and three deliberate variations."""

    #: The plate itself, at the origin.
    plate: bytes
    #: The same solid rigidly transformed (rotated, then translated).
    plate_moved: bytes
    #: The plate with a Ø6 hole through it: one known local edit.
    plate_holed: bytes
    #: A visibly different plate (8 mm thick), for a replacement.
    plate_taller: bytes


def make_step_fixtures(scratch: Path) -> StepFixtures:
    """Author the STEP fixtures once, through the product's own writer."""
    from build123d import Box, Cylinder, Location, Rotation
    from hephaestus.geom.step_io import write_step

    scratch.mkdir(parents=True, exist_ok=True)
    plate = Box(PLATE_X, PLATE_Y, PLATE_Z)
    files = {
        "plate.step": plate,
        # A rigid move: same solid, different pose. `as_posed` must see the
        # difference and `principal` must not.
        "plate_moved.step": plate.moved(Location((13.0, -7.0, 4.0))).moved(
            Rotation(0.0, 0.0, 35.0)
        ),
        "plate_holed.step": plate - Cylinder(3.0, 4 * PLATE_Z),
        "plate_taller.step": Box(PLATE_X, PLATE_Y, 8.0),
    }
    written: dict[str, bytes] = {}
    for name, shape in files.items():
        path = scratch / name
        write_step(shape, path)
        written[name] = path.read_bytes()
    return StepFixtures(
        plate=written["plate.step"],
        plate_moved=written["plate_moved.step"],
        plate_holed=written["plate_holed.step"],
        plate_taller=written["plate_taller.step"],
    )


def install_import(root: Path, name: str, data: bytes) -> Path:
    """Put a file in the project's ``imports/`` the way an operator would."""
    target = root / "imports" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def write_script(project: Project, name: str, script: str) -> None:
    """Author a part through the model's own tools (create_part + write_part)."""
    created = cast("dict[str, Any]", project.call("create_part", {"name": name}))
    applied = cast(
        "dict[str, Any]",
        project.call(
            "write_part",
            {"name": name, "expected_hash": created["content_hash"], "script": script},
        ),
    )
    assert applied["applied"] is True, applied


def build_ok(project: Project, name: str) -> dict[str, Any]:
    """``build_part`` that must have succeeded; returns the tool result."""
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "ok", result
    return result


def compare(project: Project, part: str, target: str, **extra: Any) -> dict[str, Any]:
    """``compare_solids`` through the dispatcher; returns the tool result."""
    arguments: dict[str, Any] = {"part": part, "target": target, **extra}
    return cast("dict[str, Any]", project.call("compare_solids", arguments))
