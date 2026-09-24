# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G14B evidence suite (not a test module).

Stage 14B ships declared state and toolpath geometry, and **nothing is
emitted** (CAM.md "Gates", G14B). The cast here is two real part scripts built
through the executor and published through the project store — so anchors,
tags, stock fits and feature geometry are measured against reloaded BReps the
way 8C requires — plus one declared-but-never-built part (`ghost`) for the
``no_current_build`` half of clause 10.

The fixture geometry, hand-computed
-----------------------------------
``bracket`` — a 120 x 80 x 20 block on the origin corner (+Z up), carrying:

* ``pocket_rect`` — a 30 x 20 pocket, 6 deep (floor z = 14). With the 6 mm
  end mill (r = 3) at stepover 2 the ladder emits rings at inward d = 3, 5,
  7, 9 with areas (30-2d)(20-2d) = **336, 200, 96, 24** exactly, then
  collapses at d = 11: **4 loops** (clause 2).
* ``pocket_round`` — a Ø20 pocket, 5 deep (floor z = 15). Same tool and
  stepover: areas pi(10-d)^2 for d = 3, 5, 7, 9: **4 loops** (clause 2).
* ``pocket_bell`` — a dumbbell pocket, 3 deep (floor z = 17): a 15 x 15
  square (x 75..90) and an 11 x 11 square (x 100..111) joined by a 10 x 5
  neck (x 90..100, y 8..13). With the 3 mm end mill (r = 1.5) at stepover
  1.5 the inward offset SPLITS past the neck: rung d = 1.5 is one connected
  ring; d = 3.0 gives two disjoint rings (9x9 = 81 and 5x5 = 25); d = 4.5
  gives two (6x6 = 36 and 2x2 = 4); at d = 6.0 the smaller square has died
  **on its own** while the larger still yields 3x3 = 9 — **6 loops**, and the
  independent termination clause 3 wants (the degenerate split-threshold
  branch never lands on a rung: thresholds sit at d = 2.5 and the rungs at
  1.5 + 1.5k).
* ``pocket_narrow`` — a 20 x 2 slot, 4 deep: half-width 1 mm, below the 3 mm
  tool's 1.5 mm radius — the ``feature_below_tool_radius`` fixture, decided
  before any ladder runs.
* ``drill_hole`` — a Ø5 through-bore at (70, 45), matching ``drill_5mm_hss``.
* ``pocket_wall`` — the round pocket's cylindrical WALL face: a pocket
  operation on it reaches generation (its axis is +Z) and refuses
  ``pocket_floor_not_planar``.
* ``face_top`` / ``profile_outer`` / ``mill_top`` — the top face, three tags:
  facing, the profile boundary (the 120 x 80 outline), and the generic
  ``mill_`` prefix. ``pocket_edge`` tags one of its edges (an open path — the
  ``pocket_boundary_not_closed`` fixture). ``pocket_under`` tags the BOTTOM
  face: parallel to a +Z spindle but facing away — ``unreachable_feature``.

``tiltpart`` — a 40 x 20 x 10 block with two Ø5 bores: ``drill_ok`` tilted
0.3 deg from +Z (inside ``CAM_AXIS_EPS_DEG`` = 0.5) and ``drill_tilted``
tilted 0.7 deg (outside) — the two sides of clause 9.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.cam import CamState
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.registry import MaterialsIndex, load_registry
from hephaestus.core.registry._tools import ToolsIndex
from opstore.types import JSONValue

from opstore import OpStore

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"

BRACKET_SRC = """body = Pos(60.0, 40.0, 10.0) * Box(120.0, 80.0, 20.0)
body = body - Pos(20.0, 15.0, 17.0) * Box(30.0, 20.0, 6.0)
body = body - Pos(55.0, 15.0, 17.5) * Cylinder(radius=10.0, height=5.0)
body = body - Pos(82.5, 12.5, 18.5) * Box(15.0, 15.0, 3.0)
body = body - Pos(105.5, 10.5, 18.5) * Box(11.0, 11.0, 3.0)
body = body - Pos(95.0, 10.5, 18.5) * Box(10.0, 5.0, 3.0)
body = body - Pos(25.0, 45.0, 18.0) * Box(20.0, 2.0, 4.0)
body = body - Pos(70.0, 45.0, 10.0) * Cylinder(radius=2.5, height=40.0)
floors = body.faces().filter_by(Axis.Z)
tag([f for f in floors if abs(f.center().Z - 14.0) < 1e-6][0], "pocket_rect")
tag([f for f in floors if abs(f.center().Z - 15.0) < 1e-6][0], "pocket_round")
tag([f for f in floors if abs(f.center().Z - 17.0) < 1e-6][0], "pocket_bell")
tag([f for f in floors if abs(f.center().Z - 16.0) < 1e-6][0], "pocket_narrow")
top = [f for f in floors if abs(f.center().Z - 20.0) < 1e-6][0]
tag(top, "face_top")
tag(top, "profile_outer")
tag(top, "mill_top")
tag(top.edges()[0], "pocket_edge")
tag([f for f in floors if abs(f.center().Z) < 1e-6][0], "pocket_under")
cyls = body.faces().filter_by(GeomType.CYLINDER)
tag([f for f in cyls if abs(f.center().Y - 45.0) < 1.0][0], "drill_hole")
tag([f for f in cyls if abs(f.center().Y - 15.0) < 1.0][0], "pocket_wall")
part.geometry = body
"""

TILT_SRC = """body = Pos(20.0, 10.0, 5.0) * Box(40.0, 20.0, 10.0)
body = body - Pos(10.0, 10.0, 5.0) * Rotation(0.3, 0.0, 0.0) * Cylinder(radius=2.5, height=40.0)
body = body - Pos(30.0, 10.0, 5.0) * Rotation(0.7, 0.0, 0.0) * Cylinder(radius=2.5, height=40.0)
cyls = body.faces().filter_by(GeomType.CYLINDER)
tag([f for f in cyls if f.center().X < 20.0][0], "drill_ok")
tag([f for f in cyls if f.center().X > 20.0][0], "drill_tilted")
part.geometry = body
"""

GHOST_SRC = """part.geometry = Box(10.0, 10.0, 10.0)
"""

#: The whole cast; ``ghost`` is deliberately never built (clause 10).
BENCH_PARTS: Mapping[str, str] = {
    "bracket": BRACKET_SRC,
    "tiltpart": TILT_SRC,
    "ghost": GHOST_SRC,
}
BUILT_PARTS: tuple[str, ...] = ("bracket", "tiltpart")


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "g14b") -> ProjectLayout:
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
        BuildRequest(part=part, script=frozen.script, globals_source=frozen.globals_source),
        backend=UnsafeLocalBackend(),
        out_dir=layout.store_root / "builds" / f"{part}-{len(part)}",
    )
    assert build.result.status == "ok", build.result.error
    outcome = publisher.publish_build(build, op_id=f"build-{part}-{build.result.artifact_ref}")
    assert outcome.kind == "current", outcome.details


def open_bench_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The cast built and published (``ghost`` declared, never built)."""
    layout = make_project(root, BENCH_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in BUILT_PARTS:
        build_part(publisher, layout, part)
    return layout, store


def tools_index() -> ToolsIndex:
    return ToolsIndex(load_registry(REGISTRIES / "tools"))


def materials_index() -> MaterialsIndex:
    return MaterialsIndex(load_registry(REGISTRIES / "materials"))


# --------------------------------------------------------------------------
# declaration helpers: each test states only its subject


def provenance() -> dict[str, JSONValue]:
    return {"assumed": True, "reason": "the gate's own fixture"}


def stock_entry(**overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "st-plate",
        "kind": "rectangular",
        "extents_mm": [120.0, 80.0, 20.0],
        "origin_anchor": "bracket",
        "origin_offset_mm": [0.0, 0.0, 0.0],
        "material": "al-6061",
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def fixture_entry(**overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "fx-vise",
        "members": [{"part": "tiltpart", "anchor": "tiltpart", "offset_mm": [0.0, -30.0, -10.0]}],
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def wcs_entry(**overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "w-g54",
        "code": "G54",
        "datum": "bracket:face_top",
        "z_zero": "stock_top",
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def setup_entry(**overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "s-op1",
        "spindle_axis": "+Z",
        "order": 1,
        "stock": "st-plate",
        "fixture": "fx-vise",
        "wcs": "w-g54",
        "tolerance": {
            "gouge_budget_mm3": 0.5,
            "rest_budget_mm3": 40.0,
            "max_deviation_mm": 0.1,
            "rejects_mm3": 2.0,
        },
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def operation_entry(**overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "op-rect",
        "setup": "s-op1",
        "kind": "pocket",
        "feature": "bracket:pocket_rect",
        "tool": "em_6mm_3fl_carbide",
        "depth_mm": 6.0,
        "stepdown_mm": 3.0,
        "stepover_mm": 2.0,
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def declare_baseline(cam: CamState, *, setup_id: str = "s-op1") -> None:
    """Stock + fixture + WCS + one setup, the base every scenario extends."""
    cam.stock.declare(stock_entry())
    cam.fixtures.declare(fixture_entry())
    cam.wcs.declare(wcs_entry())
    cam.setups.declare(setup_entry(id=setup_id))


def rect_ring_areas(width: float, height: float, distances: list[float]) -> list[float]:
    return [(width - 2.0 * d) * (height - 2.0 * d) for d in distances]


def circle_ring_areas(radius: float, distances: list[float]) -> list[float]:
    return [math.pi * (radius - d) ** 2 for d in distances]
