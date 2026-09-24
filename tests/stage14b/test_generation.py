# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Gate G14B clauses 2 (engine half), 15-17 and 21: the generation path.

Clause 2's engine half — the hand-computed pockets report ``loops_emitted``
and an **empty refusal list** — and clause 16's — ``toolpath_offset_failed``
fires only under kernel fault injection, zero times on normal collapse — are
asserted here through :func:`hephaestus.core.machining.generate_setup`, the
same path ``check_program`` will drive at 14C.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from _g14b import (
    declare_baseline,
    materials_index,
    operation_entry,
    tools_index,
)
from hephaestus.core.limits import CAM_SIM_SAMPLES_MAX
from hephaestus.core.machining import generate_setup, resolve_setup
from hephaestus.core.project_store.cam import CamState
from hephaestus.geom import toolpath as tp

TOOLS = tools_index()
MATERIALS = materials_index()


def _resolve(layout: Any, store: Any, setup_id: str = "s-op1") -> Any:
    return resolve_setup(layout, store, setup_id, tools=TOOLS, materials=MATERIALS)


def _refusal_reasons(program: Any, op_id: str) -> list[str]:
    for op in program.operations:
        if op.op_id == op_id:
            return [str(refusal.get("reason")) for refusal in op.refusals]
    raise AssertionError(f"no operation {op_id} in {program}")


# -- clause 2 (engine half): loops_emitted with EMPTY refusal lists ---------


def test_generated_pockets_report_loops_and_empty_refusal_lists(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_baseline(cam)
    cam.operations.declare(operation_entry(id="op-rect"))
    cam.operations.declare(
        operation_entry(
            id="op-round", feature="bracket:pocket_round", depth_mm=5.0, stepdown_mm=3.0
        )
    )
    program = generate_setup(_resolve(layout, store))
    by_id = {op.op_id: op for op in program.operations}
    # 30 x 20 at r=3 stepover 2 -> 4 rings; Ø20 likewise -> 4 rings.
    assert by_id["op-rect"].loops_emitted == 4
    assert by_id["op-round"].loops_emitted == 4
    # THE clause: an empty refusal list, not merely an absent named refusal.
    assert by_id["op-rect"].refusals == ()
    assert by_id["op-round"].refusals == ()
    assert program.refusals == ()
    # termination is a reported fact on each operation.
    assert by_id["op-rect"].termination is not None
    assert by_id["op-rect"].termination.reason in ("offset_collapsed", "below_min_loop_area")
    assert len(program.move_list) > 0


# -- clause 15: six generation refusals, each on its own fixture ------------


@pytest.mark.parametrize(
    ("op_id", "overrides", "reason"),
    [
        (
            "op-mismatch",
            {
                "kind": "drill",
                "feature": "bracket:drill_hole",
                "tool": "em_6mm_3fl_carbide",  # 6 mm tool, Ø5 bore
                "depth_mm": 20.0,
                "stepdown_mm": 5.0,
                "stepover_mm": None,
                "feed_mm_min": 100.0,
                "rpm": 3000.0,
                "plunge_mm_min": 100.0,
                "doc_mm": 3.0,
            },
            "no_matching_tool",
        ),
        (
            "op-short",
            {
                "feature": "bracket:pocket_rect",
                "tool": "em_3mm_2fl_carbide",  # flute 12 / stickout 18 < 15? no:
                "depth_mm": 15.0,  # 15 > flute 12 -> too short
                "stepdown_mm": 1.5,
                "stepover_mm": 1.5,
                "doc_mm": 1.5,
            },
            "tool_too_short",
        ),
        (
            "op-narrow",
            {
                "feature": "bracket:pocket_narrow",  # 2 mm slot vs r = 1.5
                "tool": "em_3mm_2fl_carbide",
                "depth_mm": 4.0,
                "stepdown_mm": 1.5,
                "stepover_mm": 1.5,
                "doc_mm": 1.5,
            },
            "feature_below_tool_radius",
        ),
        (
            "op-edge",
            {"feature": "bracket:pocket_edge", "depth_mm": 2.0},  # an open path
            "pocket_boundary_not_closed",
        ),
        (
            "op-wall",
            {"feature": "bracket:pocket_wall", "depth_mm": 2.0},  # a cylinder wall
            "pocket_floor_not_planar",
        ),
        (
            "op-under",
            {"feature": "bracket:pocket_under", "depth_mm": 2.0},  # faces -Z
            "unreachable_feature",
        ),
    ],
)
def test_each_generation_refusal_fires_on_its_own_fixture(
    bench_copy: tuple[Any, Any], op_id: str, overrides: dict[str, Any], reason: str
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_baseline(cam)
    cam.operations.declare(operation_entry(id=op_id, **overrides))
    program = generate_setup(_resolve(layout, store))
    assert _refusal_reasons(program, op_id) == [reason]
    # a refused operation carries NO moves — nothing degrades to a plausible path.
    refused = next(op for op in program.operations if op.op_id == op_id)
    assert refused.moves == ()


# -- clause 16 (engine half): fault-injected kernel, and only that ----------


def test_toolpath_offset_failed_through_the_engine_only_on_kernel_fault(
    bench_copy: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_baseline(cam)
    cam.operations.declare(operation_entry(id="op-rect"))
    resolved = _resolve(layout, store)

    # (b) first: the normal-collapse run raises it ZERO times.
    clean = generate_setup(resolved)
    assert _refusal_reasons(clean, "op-rect") == []

    # (a) the fault-injected kernel (the kerf.py:227-230 except-branch shape):
    # the refusal carries the operation, the ring and the distance.
    def kernel_fault(_wire: Any, _distance: float) -> list[Any]:
        raise RuntimeError("BRepOffsetAPI_MakeOffset: no result")

    monkeypatch.setattr(tp, "_kernel_offset", kernel_fault)
    faulted = generate_setup(resolved)
    refused = next(op for op in faulted.operations if op.op_id == "op-rect")
    assert [r.get("reason") for r in refused.refusals] == ["toolpath_offset_failed"]
    data = refused.refusals[0].get("data")
    assert isinstance(data, dict)
    assert data["operation"] == "op-rect"
    assert data["ring"] == 0
    assert data["offset_mm"] == pytest.approx(-3.0)


# -- clause 17: sample_cap_exceeded at generation only ----------------------


def test_sample_cap_exceeded_fires_at_generation_naming_total_and_operation(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_baseline(cam)
    # A LEGAL per-move step (em_3mm -> 0.15 mm) whose computed total blows the
    # cap through sheer path length: 120 stepdown levels over the rect pocket.
    entry = operation_entry(
        id="op-dense",
        tool="em_3mm_2fl_carbide",
        depth_mm=6.0,
        stepdown_mm=0.05,
        stepover_mm=1.5,
        doc_mm=1.5,
    )
    # …and the declaration path accepts it: the cap is UNRAISABLE there,
    # because the declaration path has no move list (the clause's own words).
    cam.operations.declare(entry)
    program = generate_setup(_resolve(layout, store))
    assert program.samples_total > CAM_SIM_SAMPLES_MAX
    reasons = [str(r.get("reason")) for r in program.refusals]
    assert reasons == ["sample_cap_exceeded"]
    data = program.refusals[0].get("data")
    assert isinstance(data, dict)
    assert data["samples_total"] == program.samples_total
    assert data["operation"] == "op-dense"
    assert data["cap"] == CAM_SIM_SAMPLES_MAX == 200000


# -- clause 21: byte-identical MoveList across processes --------------------

_WORKER = textwrap.dedent(
    """
    import hashlib, sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[2])
    from hephaestus.core.machining import generate_setup, resolve_setup
    from hephaestus.core.project_store.layout import load_project, open_store
    import _g14b

    layout = load_project(Path(sys.argv[1]))
    store = open_store(layout)
    try:
        resolved = resolve_setup(
            layout, store, "s-op1",
            tools=_g14b.tools_index(), materials=_g14b.materials_index(),
        )
        program = generate_setup(resolved)
        print(hashlib.sha256(program.move_list.serialize()).hexdigest())
        print(len(program.move_list))
    finally:
        store.close()
    """
)


def test_move_list_serialization_is_byte_identical_across_processes(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, _store = bench_copy
    cam = CamState(layout, _store)
    declare_baseline(cam)
    cam.operations.declare(operation_entry(id="op-rect"))

    digests: list[str] = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", _WORKER, str(layout.root), str(Path(__file__).parent)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        digests.append(result.stdout.strip())
    assert digests[0] == digests[1]

    # and the in-process serialization matches the subprocess bytes too.
    program = generate_setup(_resolve(layout, _store))
    local = hashlib.sha256(program.move_list.serialize()).hexdigest()
    assert digests[0].splitlines()[0] == local
