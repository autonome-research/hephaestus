# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared scaffolding for the Gate G9A motion-engine suite (not a test module).

Every clause in ``test_motion_engine.py`` and ``test_pose_bound_constraints.py``
is asserted against REAL published artifacts: the parts below are authored as
ordinary part scripts, built through the executor and published through the
project store, so a joint anchor that resolves resolves against a *reloaded*
BRep the way ``KINEMATICS.md`` §2 requires — a frame extracted from a synthetic
in-memory shape would prove nothing about the 8C anchoring path.

The mechanism, in world mm (right-handed, +Z up), ``zero: "as_built"``:

    base     40 x 40 x 6 plate centred at the origin (z in [-3, +3]) with a
             Ø8 bore through it on the Z axis (tag ``hinge_bore``, top rim
             circle tag ``bore_rim`` at z = +3), the top face tagged
             ``slide_face``, one Z-parallel edge tagged ``slide_edge``, and a
             6 mm stop cube ON the +X side (x in [9, 15], z in [3, 9]).
             ``body`` carries the label ``base_body``.
    arm      Ø7.8 pin coaxial with the bore (radial air 0.1 mm, tag
             ``hinge_pin``), a 6 mm paddle cube at +Y (y in [9, 15],
             z in [3.5, 9.5]) and an X-axis spike at z = 20 (so the WHOLE
             part names two different axes: the ambiguous-axis case).
    slider   8 x 8 x 4 block floating 0.5 mm above the plate at -Y, bottom
             face tagged ``foot_face`` (normal -Z, anti-parallel to
             ``slide_face``'s +Z: the folded prismatic direction).
    slider2  the same block at +X/-Y, for the linear-edge prismatic form.
    knob     Ø4 cylinder on the bore axis at z = 40, *bound but never
             labelled*: §5.1 label-fill makes ``knob_body`` the
             binding-form anchor.
    clip     a loose cube (the ``fixed``-kind child).
    probes   four Ø2 pins on (or near) the bore axis, one part each so the
             joint forest stays a forest: ``probe_off`` 4e-4 mm off axis
             (inside ``JOINT_FRAME_EPS_MM``), ``probe_far`` 0.5 mm off
             (beyond it), ``probe_tilt`` tilted 0.05 deg (beyond
             ``JOINT_FRAME_EPS_DEG``), ``probe_teps`` tilted 5e-4 deg
             (inside it).
    unbuilt  declared, never built: the ``no_current_build`` case.

Numbers the clauses pin: at zero the arm/base clearance is the pin/bore radial
air, exactly 0.1 mm; the paddle centre (0, 12) rotated -90 deg about the bore
axis lands exactly on the stop centre (12, 0), so the arm/base clearance at
that pose is exactly 0.0 mm.

``make_wire_project`` is a separate, deliberately 8C-only pair (a bored plate
and its pin, one satisfied ``fit`` entry) used by the byte-for-byte wire
regression: its evaluated status was recorded to ``data/`` BEFORE Stage 9A
touched ``hephaestus.core.assembly``, and the gate holds the unbound path to
those exact bytes.
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
    "ARM_PADDLE_CLEARANCE_AT_SWING_MM",
    "HINGE_PARTS",
    "MOTION_PARTS",
    "NOMINAL_RADIAL_AIR_MM",
    "assumed",
    "build_part",
    "make_project",
    "make_wire_project",
    "open_hinge_project",
    "open_motion_project",
    "wire_fit_entry",
]

#: Radial air between the arm's pin (r 3.9) and the base's bore (r 4.0).
NOMINAL_RADIAL_AIR_MM = 0.1
#: The paddle lands exactly on the stop at the -90 deg pose.
ARM_PADDLE_CLEARANCE_AT_SWING_MM = 0.0

BASE_SRC = """plate = Box(40.0, 40.0, 6.0)
body = plate - Cylinder(radius=4.0, height=20.0)
body = body + Pos(12.0, 0.0, 6.0) * Box(6.0, 6.0, 6.0)
body.label = "base_body"
tag(body.faces().filter_by(GeomType.CYLINDER)[0], "hinge_bore")
tag(body.edges().filter_by(GeomType.CIRCLE).sort_by(Axis.Z)[-1], "bore_rim")
flats = body.faces().filter_by(Axis.Z).sort_by(Axis.Z)
tag(flats[0], "floor_face")
tag(flats[-1], "stop_top")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-2], "slide_face")
tag(body.edges().filter_by(Axis.Z)[0], "slide_edge")
part.geometry = body
"""

ARM_SRC = """pin = Cylinder(radius=3.9, height=18.0)
paddle = Pos(0.0, 12.0, 6.5) * Box(6.0, 6.0, 6.0)
spike = Pos(10.0, 0.0, 20.0) * Rotation(0.0, 90.0, 0.0) * Cylinder(radius=1.0, height=6.0)
arm_body = pin + paddle + spike
tag(arm_body.faces().filter_by(GeomType.CYLINDER).sort_by(Axis.Z)[0], "hinge_pin")
part.geometry = arm_body
"""

SLIDER_SRC = """slider_body = Pos({x}, -14.0, 5.5) * Box(8.0, 8.0, 4.0)
tag(slider_body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "foot_face")
part.geometry = slider_body
"""

#: Bound, never labelled: §5.1 label-fill names it, the binding anchor form.
KNOB_SRC = """knob_body = Pos(0.0, 0.0, 40.0) * Cylinder(radius=2.0, height=4.0)
part.geometry = knob_body
"""

CLIP_SRC = """clip_body = Pos(-16.0, 14.0, 5.0) * Box(4.0, 4.0, 4.0)
part.geometry = clip_body
"""

PROBE_SRC = """probe_body = Pos({x}, 0.0, {z}) * Rotation({tilt}, 0.0, 0.0) * Cylinder(
    radius=1.0, height=1.0
)
tag(probe_body.faces().filter_by(GeomType.CYLINDER)[0], "pin_face")
part.geometry = probe_body
"""

UNBUILT_SRC = "part.geometry = Box(2.0, 2.0, 2.0)\n"

#: The whole motion cast. ``unbuilt`` is declared and never built.
MOTION_PARTS: Mapping[str, str] = {
    "base": BASE_SRC,
    "arm": ARM_SRC,
    "slider": SLIDER_SRC.format(x="0.0"),
    "slider2": SLIDER_SRC.format(x="12.0"),
    "knob": KNOB_SRC,
    "clip": CLIP_SRC,
    "probe_off": PROBE_SRC.format(x="0.0004", z="20.0", tilt="0.0"),
    "probe_far": PROBE_SRC.format(x="0.5", z="24.0", tilt="0.0"),
    "probe_tilt": PROBE_SRC.format(x="0.0", z="28.0", tilt="0.05"),
    "probe_teps": PROBE_SRC.format(x="0.0", z="32.0", tilt="0.0005"),
    "unbuilt": UNBUILT_SRC,
}

#: The 8C-only wire-regression pair (mirrors ``core/tests/_assembly_project.py``
#: rather than importing it: the gate evidence must not shift when another
#: suite's fixture does).
WIRE_BASE_SRC = (
    "plate = Box(40, 40, 10)\n"
    "bored = plate - Cylinder(radius=5.0, height=40)\n"
    'tag(bored.faces().filter_by(GeomType.CYLINDER)[0], "bore_face")\n'
    "part.geometry = bored\n"
)
WIRE_PIN_SRC = (
    "shaft_body = Cylinder(radius=4.9, height=30)\n"
    'tag(shaft_body.faces().filter_by(GeomType.CYLINDER)[0], "shaft_face")\n'
    "part.geometry = shaft_body\n"
)

WIRE_PARTS: Mapping[str, str] = {"base": WIRE_BASE_SRC, "pin": WIRE_PIN_SRC}


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "mech") -> ProjectLayout:
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


def open_motion_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The motion cast, every part but ``unbuilt`` built and published."""
    layout = make_project(root, MOTION_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in MOTION_PARTS:
        if part != "unbuilt":
            build_part(publisher, layout, part)
    return layout, store


#: Just the hinge pair — for the pose-bound constraint clauses and the
#: two-process determinism clause, where ten builds would buy nothing.
HINGE_PARTS: Mapping[str, str] = {"base": BASE_SRC, "arm": ARM_SRC}


def open_hinge_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """``base`` + ``arm`` built and published, nothing declared yet."""
    layout = make_project(root, HINGE_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in HINGE_PARTS:
        build_part(publisher, layout, part)
    return layout, store


def make_wire_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The 8C wire-regression pair: ``base`` + ``pin`` built, one fit declared."""
    from hephaestus.core.project_store.constraints import ConstraintSet

    layout = make_project(root, WIRE_PARTS, name="wire")
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in WIRE_PARTS:
        build_part(publisher, layout, part)
    ConstraintSet(layout, store).declare(wire_fit_entry())
    return layout, store


def wire_fit_entry() -> dict[str, JSONValue]:
    """The canonical unbound ``fit`` entry the wire regression evaluates."""
    return {
        "id": "c-pin-fit",
        "kind": "fit",
        "a": "base:bore_face",
        "b": "pin:shaft_face",
        "min_mm": 0.05,
        "max_mm": 0.2,
        "provenance": {"requirement": "r-1"},
        "note": "slip fit per datasheet",
    }


def assumed(reason: str = "no requirement covers this motion yet") -> dict[str, JSONValue]:
    """The ``assumed`` provenance every test entry that cites no requirement carries."""
    return {"assumed": True, "reason": reason}
