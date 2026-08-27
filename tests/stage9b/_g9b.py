# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared scaffolding for the Gate G9B sweep-evaluation suite (not a test module).

Every sweep clause in ``test_sweep_evaluation.py`` runs against REAL published
artifacts: the parts below are authored as ordinary part scripts, built through
the executor and published through the project store, so a grid sample measures
a *reloaded* BRep placed by forward kinematics — the whole ``KINEMATICS.md``
§4 path, not a synthetic in-memory stand-in. The cast mirrors the Stage 9A
``_g9a`` mechanism rather than importing it (the recorded rule: gate evidence
must not shift when another suite's fixture does), trimmed to what §4 needs.

The mechanism, in world mm (right-handed, +Z up), ``zero: "as_built"``:

    base     40 x 40 x 6 plate centred at the origin (z in [-3, +3]) with a
             Ø8 bore through it on the Z axis (tag ``hinge_bore``), the plate
             top tagged ``slide_face``, and a 6 mm stop cube ON the +X side
             (x in [9, 15], z in [3, 9]).
    arm      Ø7.8 pin coaxial with the bore (radial air 0.1 mm, tag
             ``hinge_pin``, z in [-9, 9]) and a 6 mm paddle cube at +Y
             (y in [9, 15], z in [3.5, 9.5]). Deliberately NO spike (the 9A
             ambiguous-axis probe): the reach clauses need the pin to be the
             arm's closest geometry to the +X target at small angles.
    slider   8 x 8 x 4 block floating 0.5 mm above the plate at -Y
             (z in [3.5, 7.5]), bottom face tagged ``foot_face``.
    unbuilt  declared, never built: the ``no_current_build`` case.

Numbers the clauses pin:

* arm/base minimum clearance over small swings is the pin/bore radial air,
  exactly ``NOMINAL_RADIAL_AIR_MM`` (0.1 mm) — every other pair is >= 0.5 mm
  away, so a ``sweep_clearance`` threshold on either side of 0.1 decides.
* the paddle rotated -90 deg lands exactly on the stop: footprint-identical
  6 x 6 boxes, z overlap [3.5, 9] — interference exactly
  ``PADDLE_STOP_OVERLAP_MM3`` (198 mm³) and strictly the sweep's maximum,
  since any other angle overlaps a rotated square less.
* the paddle's outer face at that pose is the plane x = 15, so the reach
  target ``REACH_TARGET_MM`` = (15, 0, 6.5) is touched (distance 0) at
  -90 deg; over [-10, 10] deg the arm's closest geometry to it is the pin
  surface at 15 - 3.9 = ``REACH_MISS_AT_SMALL_ANGLES_MM`` (11.1 mm).
* slider/base clearance is 0.5 + t mm at slide travel t — the multi-joint
  grid clause's worst sample is t = 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "NOMINAL_RADIAL_AIR_MM",
    "PADDLE_STOP_OVERLAP_MM3",
    "REACH_MISS_AT_SMALL_ANGLES_MM",
    "REACH_TARGET_MM",
    "SWEEP_PARTS",
    "assumed",
    "build_part",
    "make_project",
    "open_sweep_project",
]

#: Radial air between the arm's pin (r 3.9) and the base's bore (r 4.0).
NOMINAL_RADIAL_AIR_MM = 0.1
#: Paddle ∩ stop at the -90 deg sample: 6 x 6 footprint x 5.5 z-overlap.
PADDLE_STOP_OVERLAP_MM3 = 6.0 * 6.0 * 5.5
#: The point the paddle's outer face sweeps through at -90 deg.
REACH_TARGET_MM = (15.0, 0.0, 6.5)
#: Distance from the pin surface to the target when the paddle stays at +Y.
REACH_MISS_AT_SMALL_ANGLES_MM = 15.0 - 3.9

BASE_SRC = """plate = Box(40.0, 40.0, 6.0)
body = plate - Cylinder(radius=4.0, height=20.0)
body = body + Pos(12.0, 0.0, 6.0) * Box(6.0, 6.0, 6.0)
tag(body.faces().filter_by(GeomType.CYLINDER)[0], "hinge_bore")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-2], "slide_face")
part.geometry = body
"""

ARM_SRC = """pin = Cylinder(radius=3.9, height=18.0)
paddle = Pos(0.0, 12.0, 6.5) * Box(6.0, 6.0, 6.0)
arm_body = pin + paddle
tag(arm_body.faces().filter_by(GeomType.CYLINDER)[0], "hinge_pin")
part.geometry = arm_body
"""

SLIDER_SRC = """slider_body = Pos(0.0, -14.0, 5.5) * Box(8.0, 8.0, 4.0)
tag(slider_body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "foot_face")
part.geometry = slider_body
"""

UNBUILT_SRC = "part.geometry = Box(2.0, 2.0, 2.0)\n"

#: The whole sweep cast. ``unbuilt`` is declared and never built.
SWEEP_PARTS: Mapping[str, str] = {
    "base": BASE_SRC,
    "arm": ARM_SRC,
    "slider": SLIDER_SRC,
    "unbuilt": UNBUILT_SRC,
}


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "sweep") -> ProjectLayout:
    """Write a minimal real project tree under ``root`` and load its layout."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'name = "{name}"\nunits = "mm"\n', encoding="utf-8")
    parts_dir = root / "parts"
    parts_dir.mkdir(exist_ok=True)
    for part, script in parts.items():
        (parts_dir / f"{part}.py").write_text(script, encoding="utf-8")
    return load_project(root)


def build_part(publisher: Publisher, layout: ProjectLayout, part: str) -> None:
    """Freeze, build and publish one part through the ordinary pipeline."""
    frozen = publisher.freeze_inputs(part)
    build = run_build(
        BuildRequest(
            part=part,
            script=frozen.script,
            globals_source=frozen.globals_source,
        ),
        backend=UnsafeLocalBackend(),
        out_dir=layout.store_root / "builds" / f"{part}-{len(part)}",
    )
    assert build.result.status == "ok", build.result.error
    outcome = publisher.publish_build(build, op_id=f"build-{part}-{build.result.artifact_ref}")
    assert outcome.kind == "current", outcome.details


def open_sweep_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The sweep cast, every part but ``unbuilt`` built and published."""
    layout = make_project(root, SWEEP_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in SWEEP_PARTS:
        if part != "unbuilt":
            build_part(publisher, layout, part)
    return layout, store


def assumed(reason: str = "no requirement covers this motion yet") -> dict[str, JSONValue]:
    """The ``assumed`` provenance every test entry that cites no requirement carries."""
    return {"assumed": True, "reason": reason}
