# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clauses 9-12: §5.5 collision, against the declared scene and nothing else.

The three-fixture trio pins the narrowing: a clean scene; a clamp standing in
the drill holder's path (``crash_risk``); and a deep pocket whose shank sits
WELL INSIDE the undisturbed stock envelope raising no collision finding at
all — an implementation that quietly reintroduced the stock as a collision
target fails here rather than shipping a ``crash_risk`` on every correct
pocketing program. The boolean count binds to a counted curve: exactly
``samples x |checked bodies| x |scene bodies|``, measured at two sample
counts.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest
from _g14c import (
    check_kwargs,
    declare_deep_setup,
    declare_drill_setup,
    foul_members,
)
from hephaestus.core.cam_check import (
    CAM_COLLISION_SAMPLES_MAX,
    CAM_COLLISION_SUBSAMPLE,
    IN_PROCESS_STOCK_STAMP,
    CamCheckError,
    check_setup,
    collision_check,
    grid_placements,
    resolve_scene,
)
from hephaestus.core.machining import generate_setup, resolve_setup
from hephaestus.core.project_store.cam import CamState


def _check(layout: Any, store: Any, setup_id: str = "s-op1", **kwargs: Any) -> Any:
    return check_setup(layout, store, setup_id, **check_kwargs(), simulate=False, **kwargs)


# -- clause 9: the trio ------------------------------------------------------


def test_a_clean_scene_is_no_collision_at_samples_in_declared_scene(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    collision = _check(layout, store).collision.to_json()
    assert collision["state"] == "checked"
    assert collision["verdict"] == "no_collision_at_samples_in_declared_scene"
    assert collision["events"] == []
    assert collision["scene"] == ["fixture:fx-post:clampbar"]
    assert collision["checked_bodies"] == ["shank", "holder"]


def test_a_fouling_clamp_is_collision_at_samples_naming_everything(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store), fixture_overrides={"members": foul_members()})
    collision = _check(layout, store).collision.to_json()
    assert collision["verdict"] == "collision_at_samples"
    event = collision["events"][0]
    # The move, the sample, BOTH bodies and the overlap volume (§5.5).
    assert isinstance(event["move"], int)
    assert isinstance(event["sample"], int)
    assert event["body"] in ("shank", "holder")
    assert event["scene_body"] == "fixture:fx-post:clampbar"
    assert event["overlap_mm3"] > 0.0
    # …raising a crash_risk finding — the one severity that blocks emission.
    crash = [f for f in collision["findings"] if f["severity"] == "crash_risk"]
    assert crash and all(f["reason"] == "collision_at_samples" for f in crash)


def test_a_deep_pocket_shank_inside_the_stock_envelope_raises_no_finding(
    bench_copy: tuple[Any, Any],
) -> None:
    """THE narrowing clause: em_3mm's shank spans z 14..20 against a declared
    stock top of 40 — deep inside the undisturbed envelope — and the declared
    scene (one clear clampbar) is all that is checked."""
    layout, store = bench_copy
    declare_deep_setup(CamState(layout, store))
    collision = _check(layout, store, "s-deep").collision.to_json()
    assert collision["verdict"] == "no_collision_at_samples_in_declared_scene"
    assert collision["events"] == []
    assert not any(f["severity"] == "crash_risk" for f in collision["findings"])


# -- clause 10: undeclared_scene is unresolvable, never a clean pass --------


def test_an_empty_fixture_is_undeclared_scene_not_a_clean_verdict(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store), fixture_overrides={"members": []})
    status = _check(layout, store)
    collision = status.collision.to_json()
    assert collision["state"] == "unresolvable"
    assert collision["reason"] == "undeclared_scene"
    # Asserted NOT EQUAL to the clean verdict: an unchecked scene is not a
    # clear one (VALIDATION.md §5's rule, restated by §5.5).
    assert collision["verdict"] != "no_collision_at_samples_in_declared_scene"
    assert collision["verdict"] is None
    assert any(r["reason"] == "undeclared_scene" for r in status.refusals)


def test_a_tool_without_a_holder_is_undeclared_scene(bench: tuple[Any, Any], tmp_path: Any) -> None:
    """The other half of clause 10, through the collision checker itself: a
    tool record stripped of its holder (the registry refuses one at load, so
    the record is doctored in memory) makes the scene unresolvable — without
    a holder envelope there is no collision claim to make at all (§3.5)."""
    import shutil

    from hephaestus.core.assembly import AnchorResolver
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.publication import Publisher

    layout0, store0 = bench
    root = tmp_path / "holderless"
    shutil.copytree(layout0.root, root)
    layout = load_project(root)
    store = open_store(layout)
    try:
        cam = CamState(layout, store)
        declare_drill_setup(cam)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
        resolved = resolve_setup(
            layout, store, "s-op1", **check_kwargs(), scratch=scratch, resolver=resolver
        )
        holderless = dataclasses.replace(
            resolved,
            operations=tuple(
                dataclasses.replace(op, tool=dataclasses.replace(op.tool, holder=None))
                for op in resolved.operations
            ),
        )
        program = generate_setup(holderless)
        fixture = cam.fixtures.get("fx-post")
        scene = resolve_scene(resolved, fixture, resolver)
        report = collision_check(
            holderless, program, scene, subsample=CAM_COLLISION_SUBSAMPLE
        )
        assert report.state == "unresolvable"
        assert report.reason == "undeclared_scene"
        assert report.verdict != "no_collision_at_samples_in_declared_scene"
    finally:
        store.close()


# -- clause 11: the stamp on EVERY result, and the holder advisory ----------


def test_every_collision_result_carries_the_in_process_stock_stamp(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_drill_setup(cam)
    clean = _check(layout, store).collision.to_json()
    cam.fixtures.update("fx-post", {"members": foul_members()}, "the fouling fixture")
    fouled = _check(layout, store).collision.to_json()
    cam.fixtures.update("fx-post", {"members": []}, "the undeclared fixture")
    undeclared = _check(layout, store).collision.to_json()
    # The clean one INCLUDED (§5.5): the omission is a named non-claim, and
    # the §1.5 not-checked manifest names it beside the machine geometry.
    for record in (clean, fouled, undeclared):
        assert record[IN_PROCESS_STOCK_STAMP] is True
        assert IN_PROCESS_STOCK_STAMP in record["not_checked"]
        assert "axis_travel_limits" in record["not_checked"]


def test_holder_below_stock_top_is_an_advisory_and_never_crash_risk(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_deep_setup(CamState(layout, store))
    collision = _check(layout, store, "s-deep").collision.to_json()
    advisory = next(
        f for f in collision["findings"] if f["reason"] == "holder_below_stock_top_at_samples"
    )
    # The sample and the depth in mm, named (§5.5); severity advisory — it is
    # not evidence of contact, and filing it as crash_risk would teach
    # operators to waive the one class that must never be routine.
    assert advisory["severity"] == "advisory"
    assert isinstance(advisory["sample"], int)
    # em_3mm holder low = tip + 18; worst tip z = 2 -> depth = 40 - 20 = 20.
    assert advisory["depth_mm"] == pytest.approx(20.0, abs=0.5)
    assert not any(
        f["severity"] == "crash_risk"
        for f in collision["findings"]
        if f["reason"] == "holder_below_stock_top_at_samples"
    )


def test_the_advisory_stays_silent_when_the_holder_clears(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    declare_deep_setup(CamState(layout, store), tall_stock=False)
    collision = _check(layout, store, "s-deep").collision.to_json()
    assert not any(
        f["reason"] == "holder_below_stock_top_at_samples" for f in collision["findings"]
    )


# -- clause 12: the counted curve, the subsample rule, the generation cap ----


def test_boolean_count_equals_samples_times_bodies_times_scene_exactly_twice(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    default = _check(layout, store).collision.to_json()
    finer = _check(layout, store, collision_subsample=2).collision.to_json()

    # The collision grid is the DECLARED subsample of the simulation grid.
    grid_total = 37  # the drill plunge's placements: ceil(9/0.25) + 1
    assert default["subsample"] == CAM_COLLISION_SUBSAMPLE
    assert default["samples_evaluated"] == len(range(0, grid_total, CAM_COLLISION_SUBSAMPLE))
    assert finer["samples_evaluated"] == len(range(0, grid_total, 2))

    # EXACTLY samples x |checked bodies| x |scene bodies|, at two different
    # sample counts, so the linear relation is checked rather than assumed —
    # this is what makes the §5.8 budget a bound on a curve (§5.5).
    for record in (default, finer):
        product = (
            record["samples_evaluated"]
            * len(record["checked_bodies"])
            * len(record["scene"])
        )
        assert record["booleans_evaluated"] == product
    assert finer["booleans_evaluated"] > default["booleans_evaluated"]


def test_a_coarser_subsample_override_is_refused_and_one_is_accepted(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    with pytest.raises(CamCheckError) as caught:
        _check(layout, store, collision_subsample=CAM_COLLISION_SUBSAMPLE * 2)
    assert caught.value.reason == "invalid_collision_subsample"
    assert "downward only" in caught.value.message
    # An operator may declare 1 and pay for the full grid (§5.5).
    full = _check(layout, store, collision_subsample=1).collision.to_json()
    assert full["samples_evaluated"] == 37
    assert full["booleans_evaluated"] == 37 * 2 * 1


def test_collision_sample_cap_exceeded_fires_at_generation_naming_the_total(
    bench_copy: tuple[Any, Any],
) -> None:
    """A 0.1 mm stepdown ladder at subsample 1 computes tens of thousands of
    collision samples: refused at GENERATION time, before any boolean runs."""
    layout, store = bench_copy
    declare_deep_setup(CamState(layout, store), stepdown_mm=0.1)
    status = _check(layout, store, "s-deep", collision_subsample=1)
    refusal = next(
        r for r in status.refusals if r["reason"] == "collision_sample_cap_exceeded"
    )
    assert refusal["data"]["collision_samples"] > CAM_COLLISION_SAMPLES_MAX
    assert refusal["data"]["cap"] == CAM_COLLISION_SAMPLES_MAX
    # No boolean ran: the collision section was refused, not measured.
    assert status.collision is None


def test_the_collision_grid_is_the_declared_subsample_of_the_simulation_grid(
    bench_copy: tuple[Any, Any],
) -> None:
    """The grid indexes are every n-th simulation placement — one sampling,
    subsampled, never a second enumeration with its own drift."""
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    from hephaestus.core.assembly import AnchorResolver
    from hephaestus.core.project_store.publication import Publisher

    scratch = layout.root / "scratch-grid"
    scratch.mkdir()
    resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
    resolved = resolve_setup(
        layout, store, "s-op1", **check_kwargs(), scratch=scratch, resolver=resolver
    )
    program = generate_setup(resolved)
    placements = grid_placements(
        program.operations[0].moves, resolved.operations[0].step_mm
    )
    expected = math.ceil(len(placements) / CAM_COLLISION_SUBSAMPLE)
    collision = _check(layout, store).collision.to_json()
    assert collision["samples_evaluated"] == expected
