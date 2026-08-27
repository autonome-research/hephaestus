# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared scaffolding for the Gate G9C coupling suite (not a test module).

The FK-composition and derived-limit clauses in ``test_couplings.py`` run
against REAL published artifacts: the parts below are authored as ordinary
part scripts, built through the executor and published through the project
store, so a coupled child's derived motion is measured on a *reloaded* BRep
placed by forward kinematics — the whole ``KINEMATICS.md`` §5 path, not a
synthetic stand-in. The cast mirrors the Stage 9B ``_g9b`` mechanism rather
than importing it (the recorded rule: gate evidence must not shift when
another suite's fixture does), trimmed to what §5 needs.

The mechanism, in world mm (right-handed, +Z up), ``zero: "as_built"``:

    base     40 x 40 x 6 plate centred at the origin (z in [-3, +3]) with a
             Ø8 bore through it on the Z axis (tag ``hinge_bore``) and the
             plate top (z = +3, normal +Z) tagged ``slide_face``.
    arm      Ø7.8 pin coaxial with the bore (radial air 0.1 mm, tag
             ``hinge_pin``, z in [-9, 9]).
    slider   8 x 8 x 4 block floating 0.5 mm above the plate at -Y
             (z in [3.5, 7.5]), bottom face tagged ``foot_face``.

Numbers the clauses pin:

* ``j-hinge`` (revolute, bore axis) drives ``j-slide`` (prismatic along the
  ``slide_face`` +Z normal) through the coupling under test. At slide travel
  ``t`` the slider/base clearance is exactly ``SLIDER_BASE_GAP_MM + t``
  (slider bottom ``3.5 + t`` over plate top ``3.0``) — the ``_g9b`` pinned
  relation restated — so a derived ``t`` is directly readable off a real
  clearance measurement.
* with ``DRIVE_RATIO_MM_PER_DEG`` (1/18 mm per degree, a lead-screw-flavoured
  reduction), a +90 degree swing derives ``t = +5.0`` exactly.
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
    "COUPLING_PARTS",
    "DRIVE_RATIO_MM_PER_DEG",
    "SLIDER_BASE_GAP_MM",
    "assumed",
    "build_part",
    "make_project",
    "open_coupling_project",
]

#: Gap between the slider's bottom face (z 3.5) and the plate top (z 3.0).
SLIDER_BASE_GAP_MM = 0.5
#: The coupling ratio the composition clauses use: 90 deg -> exactly 5.0 mm.
DRIVE_RATIO_MM_PER_DEG = 1.0 / 18.0

BASE_SRC = """plate = Box(40.0, 40.0, 6.0)
body = plate - Cylinder(radius=4.0, height=20.0)
tag(body.faces().filter_by(GeomType.CYLINDER)[0], "hinge_bore")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "slide_face")
part.geometry = body
"""

ARM_SRC = """pin = Cylinder(radius=3.9, height=18.0)
arm_body = pin
tag(arm_body.faces().filter_by(GeomType.CYLINDER)[0], "hinge_pin")
part.geometry = arm_body
"""

SLIDER_SRC = """slider_body = Pos(0.0, -14.0, 5.5) * Box(8.0, 8.0, 4.0)
tag(slider_body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "foot_face")
part.geometry = slider_body
"""

#: The whole coupling cast, all built.
COUPLING_PARTS: Mapping[str, str] = {
    "base": BASE_SRC,
    "arm": ARM_SRC,
    "slider": SLIDER_SRC,
}


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "coupled") -> ProjectLayout:
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


def open_coupling_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The coupling cast, every part built and published."""
    layout = make_project(root, COUPLING_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in COUPLING_PARTS:
        build_part(publisher, layout, part)
    return layout, store


def assumed(reason: str = "no requirement covers this transmission yet") -> dict[str, JSONValue]:
    """The ``assumed`` provenance every test entry that cites no requirement carries."""
    return {"assumed": True, "reason": reason}
