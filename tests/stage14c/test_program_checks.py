# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clauses 15 and 17: ``m.program`` and the program-status projection.

``m.program(setup_id)`` is a project-scope read surface on the discriminated-
facade mechanism (script_contract.md §6, the ``m.at_pose``/``m.sweep``
precedent): the part-scope facade was never handed the resolver, so a
part-scope predicate is refused BY NAME at evaluation, recorded as that
check's failure — no load-time inspection of predicate bodies anywhere. A CAM
simulation timeout inside a predicate lands as ``unverifiable`` — not a pass
and not a crash.

The projection is the one piece of non-ledger persistence this stage adds
(CAM.md §11 item 26): restaled when a checked setup's part rebuilds into
different geometry, with the GC edge that keeps a stale status readable —
because a collected status would read as "never evaluated", a different (and
false) claim about the project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from _g14c import build_part, check_kwargs, declare_drill_setup
from hephaestus.core.cam_check import (
    CamSimTimeout,
    SnapshotProgramContext,
    check_program,
    projected_statuses,
)
from hephaestus.core.checks.engine import run_checks
from hephaestus.core.checks.facade import part_measurement, project_measurement
from hephaestus.core.project_store.cam import CamState
from hephaestus.core.project_store.locks import LockManager
from hephaestus.core.project_store.projections import STATE_POINTER, Projections
from hephaestus.core.project_store.publication import Publisher


def _snapshot_ref(layout: Any, store: Any) -> str:
    projections = Publisher(layout, store).projections
    return projections.assemble_snapshot(layout.part_names()).ref


# -- clause 15: m.program ----------------------------------------------------


def test_m_program_resolves_against_the_frozen_snapshot(
    bench_copy: tuple[Any, Any], tmp_path: Path
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    context = SnapshotProgramContext(
        layout,
        store,
        snapshot_ref=_snapshot_ref(layout, store),
        scratch=tmp_path,
        **check_kwargs(),
    )
    m = project_measurement({}, program=context.program)
    facts = m.program("s-op1")
    # The flattened §5.9 facts a predicate asserts on (script_contract.md §6).
    assert facts.state == "checked"
    assert facts.coverage == "covered"
    assert facts.round_trip == "round_trip_identical"
    assert facts.simulation == "matches_at_samples"
    assert facts.collision == "no_collision_at_samples_in_declared_scene"
    assert facts.raw["setup"] == "s-op1"
    # The whole record is the measured value the report will carry.
    assert m.measured_json() == dict(facts.raw)
    # Memoized: one run has one program state (the m.sweep rule).
    assert m.program("s-op1").raw is facts.raw


def test_a_part_scope_predicate_is_refused_at_evaluation_as_contract(
    bench: tuple[Any, Any],
) -> None:
    """The part-scope facade carries no program resolver — the refusal is
    structural, ``kind="contract"``, recorded as that check's failure."""
    layout, _store = bench
    del layout

    class _Source:
        from hephaestus.core.addressing import GeometryIndex

        index = GeometryIndex()

        def shape(self, resolution: object) -> object:  # pragma: no cover - never reached
            raise AssertionError

    results = run_checks(
        {"programmed": lambda m: m.program("s-op1").coverage == "covered"},
        lambda: part_measurement("simpart", _Source()),
    )
    outcome = results["programmed"]
    assert outcome.passed is False
    measured = cast("dict[str, Any]", outcome.measured)
    error = measured["error"]
    assert error["code"] == "validation_error"
    assert "project-scope read surface" in error["message"]
    assert "m.program" in error["message"]


def test_a_cam_timeout_inside_a_predicate_lands_as_unverifiable(
    bench_copy: tuple[Any, Any], tmp_path: Path
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))

    def grinding_resolver(setup_id: str) -> Any:
        from hephaestus.core.cam_check import check_setup

        return check_setup(
            layout,
            store,
            setup_id,
            **check_kwargs(),
            scratch=tmp_path,
            timeout_s=10.0,
            fault={"slow_boolean_s": 120},
            raise_timeout=True,
        ).to_json()

    results = run_checks(
        {"programmed": lambda m: m.program("s-op1").simulation == "matches_at_samples"},
        lambda: project_measurement({}, program=grinding_resolver),
    )
    outcome = results["programmed"]
    assert outcome.passed is False
    measured = cast("dict[str, Any]", outcome.measured)
    # unverifiable is NOT the crash shape: the predicate was never answered.
    assert "error" not in measured
    refusal = measured["unverifiable"]
    assert refusal["reason"] == "cam_sim_timeout"
    assert refusal["timeout_s"] == 10.0
    assert refusal["cheap"]["coverage"] == "covered"


def test_the_snapshot_context_raises_the_timeout_through_check_setup(
    bench_copy: tuple[Any, Any], tmp_path: Path
) -> None:
    """The context's own path raises rather than filing, so the engine's
    unverifiable rule — not a quiet refusal row — owns the outcome."""
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    context = SnapshotProgramContext(
        layout,
        store,
        snapshot_ref=_snapshot_ref(layout, store),
        scratch=tmp_path,
        timeout_s=10.0,
        **check_kwargs(),
    )
    from hephaestus.core import cam_check as engine

    original = engine.check_setup

    def slow_check(*args: Any, **kwargs: Any) -> Any:
        kwargs["fault"] = {"slow_boolean_s": 120}
        return original(*args, **kwargs)

    engine.check_setup = slow_check
    try:
        with pytest.raises(CamSimTimeout):
            context.program("s-op1")
    finally:
        engine.check_setup = original


# -- clause 17: the projection restales, and the GC edge holds --------------


def test_the_projection_restales_on_rebuild_and_the_gc_edge_keeps_it_readable(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    statuses, partial = check_program(layout, store, None, **check_kwargs())
    assert partial is False and len(statuses) == 1

    projections = Projections(store, locks=LockManager(store))
    state = projections.state()
    assert state.program is not None
    assert state.program.stale == ()
    assert state.program.parts["simpart"].startswith("artifact:build:")
    statuses_blob = state.program.statuses_blob

    # The GC edge: the statuses document hangs off the projection-state blob,
    # so a stale status can never be collected into "never evaluated".
    state_blob = store.blobs.read_pointer(STATE_POINTER)
    assert (state_blob, statuses_blob) in store.gc.links()

    # Rebuild the checked part into DIFFERENT geometry: the projection goes
    # stale by name — a stale status never reads as fresh.
    script = layout.part_path("simpart")
    script.write_text(
        script.read_text(encoding="utf-8").replace("radius=2.5", "radius=2.4"),
        encoding="utf-8",
    )
    build_part(layout, store, "simpart")
    restaled = projections.state()
    assert restaled.program is not None
    assert restaled.program.stale == ("simpart",)
    # …and the stale statuses document is STILL readable (the GC edge's whole
    # point), byte for byte what was measured.
    assert store.blobs.has(statuses_blob)
    new_state_blob = store.blobs.read_pointer(STATE_POINTER)
    assert (new_state_blob, statuses_blob) in store.gc.links()
    recorded = projected_statuses(store)
    assert recorded is not None and recorded[0]["setup"] == "s-op1"


def test_a_named_subset_is_evaluated_but_never_projected(
    bench_copy: tuple[Any, Any],
) -> None:
    """The check_assembly/check_motion rule: partial runs record nothing."""
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    statuses, partial = check_program(layout, store, ["s-op1"], **check_kwargs())
    assert partial is True and len(statuses) == 1
    assert Projections(store, locks=LockManager(store)).state().program is None
