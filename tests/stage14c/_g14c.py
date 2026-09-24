# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G14C evidence suite (not a test module).

Stage 14C ships verification — coverage, round-trip, removal simulation,
collision — and still emits nothing (CAM.md "Gates", G14C; the D2 mandate).
The cast is real part scripts built through the executor and published through
the project store, so every check below measures reloaded BReps through the
whole engine path.

The fixture geometry, hand-computed
-----------------------------------
Every gate fixture's measured quantity sits at least ``CAM_VERDICT_MARGIN``
(10x) from its threshold (clause 8), so a kernel-build difference cannot flip
a clause. The drill-driven simulation fixtures are chosen because a drilled
volume is literal cylinder arithmetic:

* ``simpart`` — a 30 x 20 x 6 block with ONE blind bore Ø5, 4 deep, at
  (10, 10), tagged ``drill_a``. Volumes: bore = pi * 2.5^2 * 4 = 78.54 mm^3.
  - **matches**: drill depth 4 -> a_only/b_only are kernel noise, budgets
    (gouge 1.5, rest 3.0) are >= 10x above both.
  - **gouge**: drill depth 5 (a deliberate 1.0 mm overdepth) -> b_only =
    pi * 2.5^2 * 1 = 19.63 mm^3 >= 10 x gouge_budget (1.5); and the same
    fixture's iou stays > 0.99 (19.6 of a ~3500 mm^3 part barely moves it),
    which is the clause that proves iou is not a legal threshold.
  - **rest**: drill depth 2 (declared 2 mm shallow) -> a_only =
    pi * 2.5^2 * 2 = 39.27 mm^3 >= 10 x rest_budget (3.0).
* ``covpart`` — the §5.1 coverage cast: a tagged bore WITH an operation
  (``drill_hole``), a tagged bore with NO operation (``drill_lone``), one
  UNTAGGED Ø4 bore, and a 10 x 2 slot tagged ``pocket_narrow`` whose claiming
  operation is refused ``feature_below_tool_radius`` (em_6mm r=3 vs 1 mm
  half-width).
* ``occpart`` — order consistency: a Ø16 pocket 3 deep (floor z = 5) and a
  Ø5 bore drilled 3 further from that floor. Declaring the drill BEFORE the
  pocket buries it: ``feature_occluded_by_order`` naming both.
* ``deep`` — the §5.5 narrowing fixture: a Ø10 pocket 4 deep milled with
  em_3mm (flute 12, stickout 18). Against a TALL declared stock
  (30 x 20 x 40) the shank spans z 14..20 — well inside the undisturbed
  stock envelope — and the holder's low end (z 20) is below the stock top
  (40): no collision finding at all (the scene is fixture members and
  keepouts ONLY), and the ``holder_below_stock_top_at_samples`` advisory
  fires with the depth. Against the true-height stock (z extent 6) the
  holder clears and the advisory stays silent.
* ``refpart`` — the reference setup (clauses 3, 16, 21, 22): a Ø10 pocket
  2 deep (em_6mm: one clearing ring at inward d=3 -> R=2) plus a Ø5 bore
  4 deep (drill_5mm), fixture ``clampbar`` placed clear.
* ``clampbar`` — a 10 x 10 x 80 post: the declared fixture member. Placed at
  offset (2, 2, 20) it stands inside the drill holder's swept envelope
  (holder Ø43 around (10, 10), z 62+) — the fouling-clamp fixture; placed at
  (-50, 0, 0) it is clear.
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
from hephaestus.core.registry import MaterialsIndex, load_registry
from hephaestus.core.registry._tools import ToolsIndex
from opstore.types import JSONValue

from opstore import OpStore

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"

#: Hand-computed fixture volumes (mm^3): the drilled bore's cylinder terms.
BORE_MM3_PER_MM = math.pi * 2.5 * 2.5

SIMPART_SRC = """body = Pos(15.0, 10.0, 3.0) * Box(30.0, 20.0, 6.0)
body = body - Pos(10.0, 10.0, 4.0) * Cylinder(radius=2.5, height=4.0)
cyls = body.faces().filter_by(GeomType.CYLINDER)
tag(cyls[0], "drill_a")
top = [f for f in body.faces().filter_by(Axis.Z) if abs(f.center().Z - 6.0) < 1e-6][0]
tag(top, "datum_top")
part.geometry = body
"""

COVPART_SRC = """body = Pos(15.0, 10.0, 3.0) * Box(30.0, 20.0, 6.0)
body = body - Pos(8.0, 10.0, 4.0) * Cylinder(radius=2.5, height=4.0)
body = body - Pos(16.0, 10.0, 4.0) * Cylinder(radius=2.5, height=4.0)
body = body - Pos(24.0, 10.0, 4.5) * Cylinder(radius=2.0, height=3.0)
body = body - Pos(15.0, 3.0, 5.0) * Box(10.0, 2.0, 2.0)
cyls = sorted(body.faces().filter_by(GeomType.CYLINDER), key=lambda f: f.bounding_box().min.X)
tag(cyls[0], "drill_hole")
tag(cyls[1], "drill_lone")
floors = body.faces().filter_by(Axis.Z)
tag([f for f in floors if abs(f.center().Z - 4.0) < 1e-6][0], "pocket_narrow")
top = [f for f in floors if abs(f.center().Z - 6.0) < 1e-6][0]
tag(top, "datum_top")
part.geometry = body
"""

OCCPART_SRC = """body = Pos(15.0, 10.0, 4.0) * Box(30.0, 20.0, 8.0)
body = body - Pos(15.0, 10.0, 6.5) * Cylinder(radius=8.0, height=3.0)
body = body - Pos(15.0, 10.0, 3.5) * Cylinder(radius=2.5, height=3.0)
floors = body.faces().filter_by(Axis.Z)
tag([f for f in floors if abs(f.center().Z - 5.0) < 1e-6][0], "pocket_top")
cyls = sorted(body.faces().filter_by(GeomType.CYLINDER), key=lambda f: f.bounding_box().min.Z)
tag(cyls[0], "drill_deep")
tag(cyls[1], "wall_top")
top = [f for f in floors if abs(f.center().Z - 8.0) < 1e-6][0]
tag(top, "datum_top")
part.geometry = body
"""

DEEP_SRC = """body = Pos(15.0, 10.0, 3.0) * Box(30.0, 20.0, 6.0)
body = body - Pos(15.0, 10.0, 4.0) * Cylinder(radius=5.0, height=4.0)
floors = body.faces().filter_by(Axis.Z)
tag([f for f in floors if abs(f.center().Z - 2.0) < 1e-6][0], "pocket_deep")
cyls = body.faces().filter_by(GeomType.CYLINDER)
tag(cyls[0], "wall_deep")
top = [f for f in floors if abs(f.center().Z - 6.0) < 1e-6][0]
tag(top, "datum_top")
part.geometry = body
"""

REFPART_SRC = """body = Pos(15.0, 10.0, 3.0) * Box(30.0, 20.0, 6.0)
body = body - Pos(9.0, 10.0, 5.0) * Cylinder(radius=5.0, height=2.0)
body = body - Pos(22.0, 10.0, 4.0) * Cylinder(radius=2.5, height=4.0)
floors = body.faces().filter_by(Axis.Z)
tag([f for f in floors if abs(f.center().Z - 4.0) < 1e-6][0], "pocket_ref")
cyls = sorted(body.faces().filter_by(GeomType.CYLINDER), key=lambda f: f.bounding_box().min.X)
tag(cyls[0], "wall_ref")
tag(cyls[1], "drill_ref")
top = [f for f in floors if abs(f.center().Z - 6.0) < 1e-6][0]
tag(top, "datum_top")
part.geometry = body
"""

CLAMPBAR_SRC = """part.geometry = Pos(5.0, 5.0, 40.0) * Box(10.0, 10.0, 80.0)
"""

BENCH_PARTS: Mapping[str, str] = {
    "simpart": SIMPART_SRC,
    "covpart": COVPART_SRC,
    "occpart": OCCPART_SRC,
    "deep": DEEP_SRC,
    "refpart": REFPART_SRC,
    "clampbar": CLAMPBAR_SRC,
}


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "g14c") -> ProjectLayout:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'name = "{name}"\nunits = "mm"\n', encoding="utf-8")
    parts_dir = root / "parts"
    parts_dir.mkdir(exist_ok=True)
    for part, script in parts.items():
        (parts_dir / f"{part}.py").write_text(script, encoding="utf-8")
    return load_project(root)


def build_part(layout: ProjectLayout, store: OpStore, part: str) -> None:
    from hephaestus.core.project_store.publication import Publisher

    publisher = Publisher(layout, store)
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
    layout = make_project(root, BENCH_PARTS)
    store = open_store(layout)
    for part in BENCH_PARTS:
        build_part(layout, store, part)
    return layout, store


def tools_index() -> ToolsIndex:
    return ToolsIndex(load_registry(REGISTRIES / "tools"))


def materials_index() -> MaterialsIndex:
    return MaterialsIndex(load_registry(REGISTRIES / "materials"))


# --------------------------------------------------------------------------
# declaration helpers (the _g14b shape: each test states only its subject)


def provenance() -> dict[str, JSONValue]:
    return {"assumed": True, "reason": "the gate's own fixture"}


def stock_entry(part: str = "simpart", **overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "st-block",
        "kind": "rectangular",
        "extents_mm": [30.0, 20.0, 6.0],
        "origin_anchor": part,
        "origin_offset_mm": [0.0, 0.0, 0.0],
        "material": "al-6061",
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def fixture_entry(**overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "fx-post",
        "members": [{"part": "clampbar", "anchor": "clampbar", "offset_mm": [-50.0, 0.0, 0.0]}],
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def wcs_entry(part: str = "simpart", **overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "w-g54",
        "code": "G54",
        "datum": f"{part}:datum_top",
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
        "stock": "st-block",
        "fixture": "fx-post",
        "wcs": "w-g54",
        "tolerance": {
            "gouge_budget_mm3": 1.5,
            "rest_budget_mm3": 3.0,
            "max_deviation_mm": 0.5,
            "rejects_mm3": 1.5,
        },
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def drill_op(part: str = "simpart", tag: str = "drill_a", **overrides: Any) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": "op-drill",
        "setup": "s-op1",
        "kind": "drill",
        "feature": f"{part}:{tag}",
        "tool": "drill_5mm_hss",
        "depth_mm": 4.0,
        "provenance": provenance(),
    }
    entry.update(overrides)
    return entry


def declare_drill_setup(
    cam: CamState,
    *,
    part: str = "simpart",
    depth_mm: float = 4.0,
    fixture_overrides: Mapping[str, JSONValue] | None = None,
    setup_overrides: Mapping[str, JSONValue] | None = None,
    stock_overrides: Mapping[str, JSONValue] | None = None,
) -> None:
    """Stock + fixture + WCS + one setup + one drill op, the base scenario."""
    cam.stock.declare(stock_entry(part, **(dict(stock_overrides or {}))))
    cam.fixtures.declare(fixture_entry(**(dict(fixture_overrides or {}))))
    cam.wcs.declare(wcs_entry(part))
    cam.setups.declare(setup_entry(**(dict(setup_overrides or {}))))
    cam.operations.declare(drill_op(part, depth_mm=depth_mm))


def declare_reference_setup(cam: CamState) -> None:
    """The reference setup on ``refpart``: one pocket, one drill, clear fixture."""
    cam.stock.declare(stock_entry("refpart"))
    cam.fixtures.declare(fixture_entry())
    cam.wcs.declare(wcs_entry("refpart"))
    # The pocket's wall scallops leave ~0.45 mm^3 of honest rest material at
    # the reference step, so the reference budgets sit 10x above THAT (clause
    # 8's margin, from the other side): 8.0 >= 10 x 0.45.
    cam.setups.declare(
        setup_entry(
            tolerance={
                "gouge_budget_mm3": 1.5,
                "rest_budget_mm3": 8.0,
                "max_deviation_mm": 0.5,
                "rejects_mm3": 1.5,
            }
        )
    )
    cam.operations.declare(
        {
            "id": "op-pocket",
            "setup": "s-op1",
            "kind": "pocket",
            "feature": "refpart:pocket_ref",
            "tool": "em_6mm_3fl_carbide",
            "depth_mm": 2.0,
            "stepdown_mm": 2.0,
            "stepover_mm": 2.4,
            "provenance": provenance(),
        }
    )
    cam.operations.declare(drill_op("refpart", "drill_ref", id="op-drill"))


def declare_coverage_setup(cam: CamState) -> None:
    """The §5.1 cast on ``covpart``: covered, no-op, refused-op, untagged bore."""
    cam.stock.declare(stock_entry("covpart", id="st-cov"))
    cam.fixtures.declare(fixture_entry(id="fx-cov"))
    cam.wcs.declare(wcs_entry("covpart", id="w-cov"))
    cam.setups.declare(setup_entry(id="s-cov", stock="st-cov", fixture="fx-cov", wcs="w-cov"))
    cam.operations.declare(drill_op("covpart", "drill_hole", id="op-hole", setup="s-cov"))
    cam.operations.declare(
        {
            "id": "op-narrow",
            "setup": "s-cov",
            "kind": "pocket",
            "feature": "covpart:pocket_narrow",
            "tool": "em_6mm_3fl_carbide",
            "depth_mm": 2.0,
            "stepdown_mm": 2.0,
            "stepover_mm": 2.4,
            "provenance": provenance(),
        }
    )


def declare_occlusion_setup(cam: CamState) -> None:
    """Drill declared BEFORE the pocket that buries it (§5.1 order clause)."""
    cam.stock.declare(stock_entry("occpart", id="st-occ", extents_mm=[30.0, 20.0, 8.0]))
    cam.fixtures.declare(fixture_entry(id="fx-occ"))
    cam.wcs.declare(wcs_entry("occpart", id="w-occ"))
    cam.setups.declare(setup_entry(id="s-occ", stock="st-occ", fixture="fx-occ", wcs="w-occ"))
    cam.operations.declare(drill_op("occpart", "drill_deep", id="op-first", setup="s-occ", depth_mm=3.0))
    cam.operations.declare(
        {
            "id": "op-second",
            "setup": "s-occ",
            "kind": "pocket",
            "feature": "occpart:pocket_top",
            "tool": "em_6mm_3fl_carbide",
            "depth_mm": 3.0,
            "stepdown_mm": 3.0,
            "stepover_mm": 2.4,
            "provenance": provenance(),
        }
    )


def declare_deep_setup(
    cam: CamState, *, tall_stock: bool = True, stepdown_mm: float = 4.0
) -> None:
    """The §5.5 narrowing fixture on ``deep`` (shank inside the stock envelope)."""
    extents = [30.0, 20.0, 40.0] if tall_stock else [30.0, 20.0, 6.0]
    cam.stock.declare(stock_entry("deep", id="st-deep", extents_mm=extents))
    cam.fixtures.declare(fixture_entry(id="fx-deep"))
    cam.wcs.declare(wcs_entry("deep", id="w-deep"))
    cam.setups.declare(
        setup_entry(
            id="s-deep",
            stock="st-deep",
            fixture="fx-deep",
            wcs="w-deep",
            tolerance={
                "gouge_budget_mm3": 1.5,
                "rest_budget_mm3": 30000.0,
                "max_deviation_mm": 40.0,
                "rejects_mm3": 1.5,
            },
        )
    )
    cam.operations.declare(
        {
            "id": "op-deep",
            "setup": "s-deep",
            "kind": "pocket",
            "feature": "deep:pocket_deep",
            "tool": "em_3mm_2fl_carbide",
            "depth_mm": 4.0,
            "stepdown_mm": stepdown_mm,
            "stepover_mm": 1.2,
            "provenance": provenance(),
        }
    )


def foul_members() -> list[JSONValue]:
    """The clampbar standing inside the drill holder's swept envelope."""
    return [{"part": "clampbar", "anchor": "clampbar", "offset_mm": [2.0, 2.0, 20.0]}]


def check_kwargs() -> dict[str, Any]:
    return {"tools": tools_index(), "materials": materials_index()}
