# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9B: the ``CHECKS`` motion read surfaces (``KINEMATICS.md`` §4, last bullet).

The four gate clauses of the ``m.at_pose`` / ``m.sweep`` slice:

* *project scope resolves against the run's FROZEN snapshot* (§2, last
  bullet) — proved the hard way: a part is republished with different
  geometry AFTER the snapshot and motion context freeze, and the check still
  measures the frozen state's numbers; a context built after the
  republication refuses by name rather than reading CURRENT.
* *the part-scope refusal is at EVALUATION* — the part-scope facade simply
  carries no motion resolvers (the ``m.diff`` import-target discriminated
  facade, in the other direction), so a part-scope predicate calling either
  surface raises the named ``kind="contract"`` refusal when the predicate
  runs, recorded as that check's failure — no load-time pass over predicate
  bodies exists anywhere.
* *an in-predicate motion timeout is UNVERIFIABLE* — the ``run_checks``
  discrimination extended from ``compare_timeout`` to ``motion_timeout``:
  not a pass, not the generic crash shape, and the refusal carries the
  partial per-sample facts the killed grid streamed.
* *a run that resolved motion state records the frozen motion generations*
  in its ``CheckReport`` alongside ``project_snapshot_ref``; a run that
  never touched motion records none.

Everything measures real published artifacts through the real engine path:
the ``_g9b`` mechanism, real ``CheckSet`` generations, real snapshots, and
the numbers asserted are the fixture's pinned facts (0.1 mm pin/bore air,
198 mm³ paddle-on-stop overlap at -90 deg).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import hephaestus.core.motion as motion_module
import pytest
from _g9b import (
    NOMINAL_RADIAL_AIR_MM,
    PADDLE_STOP_OVERLAP_MM3,
    assumed,
    build_part,
    open_sweep_project,
)
from _sweep_children import STREAMED_SAMPLES, grinding_child
from hephaestus.core.checks.engine import CheckSet, run_bundle, run_checks
from hephaestus.core.checks.facade import GeometrySource, Measurement, part_measurement
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.artifact_geometry import artifact_source, part_only_source
from hephaestus.core.motion import BoundPoseError, SnapshotMotionContext
from hephaestus.core.project_store.kinematics import JointSet, MotionCheckSet, PoseSet
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.types import CheckReport
from opstore.types import JSONValue

from opstore import OpStore

# The arm republished mid-test: pin radius 3.0 (radial air 1.0 mm, ten times
# the frozen 0.1) and NO paddle (posed interference 0 instead of 198 mm³) —
# every frozen number this suite asserts is unmistakably different live.
MUTATED_ARM_SRC = """pin = Cylinder(radius=3.0, height=18.0)
tag(pin.faces().filter_by(GeomType.CYLINDER)[0], "hinge_pin")
part.geometry = pin
"""

#: The cross-part check module every project-scope clause runs. Coarse
#: thresholds on purpose: the predicates decide pass/fail, and the TESTS then
#: assert the recorded measured values against the pinned facts exactly.
MOTION_CHECKS_SRC = """# motion read surfaces (KINEMATICS.md §4)
CHECKS = {
    "closed_hits_stop": lambda m: m.at_pose("p-swing").interference(
        "arm/part", "base/part") > 190.0,
    "zero_pose_air": lambda m: m.at_pose("p-zero").clearance(
        "arm/part", "base/part") < 0.15,
    "travel_clear": lambda m: m.sweep("mc-clear").verdict == "holds_at_samples",
}
"""


def declare_motion_state(layout: ProjectLayout, store: OpStore) -> None:
    """The joint, poses, and motion checks every project in this suite carries."""
    joints = JointSet(layout, store)
    joints.declare(
        {
            "id": "j-hinge",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "arm:hinge_pin",
            "limits": {"min": -180.0, "max": 180.0},
            "provenance": {"requirement": "r-1"},
        }
    )
    poses = PoseSet(layout, store, joints)
    poses.declare(
        {"id": "p-zero", "joints": {"j-hinge": 0.0}, "provenance": {"requirement": "r-1"}}
    )
    poses.declare(
        {"id": "p-swing", "joints": {"j-hinge": -90.0}, "provenance": {"requirement": "r-1"}}
    )
    checks = MotionCheckSet(layout, store, joints)
    checks.declare(
        {
            "id": "mc-clear",
            "kind": "sweep_clearance",
            "a": "arm",
            "b": "base",
            "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
            "min_mm": 0.05,
            "samples": 3,
            "provenance": {"requirement": "r-1"},
        }
    )
    checks.declare(
        {
            "id": "mc-tight",
            "kind": "sweep_clearance",
            "a": "arm",
            "b": "base",
            "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
            "min_mm": 0.2,
            "samples": 3,
            "provenance": assumed(),
        }
    )
    checks.declare(
        {
            "id": "mc-gone",
            "kind": "sweep_no_interference",
            "a": "arm",
            "b": "base",
            "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
            "samples": 3,
            "provenance": assumed(),
        }
    )
    checks.withdraw("mc-gone", "superseded by mc-clear")


def freeze_run(
    layout: ProjectLayout, store: OpStore, scratch: Path
) -> tuple[str, dict[str, GeometrySource]]:
    """One run's freeze: the coherent snapshot ref and sources from ITS bytes.

    Mirrors the server's ``run_project_checks`` exactly — the sources come
    from the snapshot manifest's pinned artifact blobs, not from live
    pointers, which is half of what "frozen" means (the motion context is
    the other half).
    """
    publisher = Publisher(layout, store)
    snapshot = publisher.projections.assemble_snapshot(["arm", "base", "slider"])
    sources: dict[str, GeometrySource] = {}
    parts = cast("Mapping[str, JSONValue]", snapshot.manifest["parts"])
    for name, entry in sorted(parts.items()):
        ref = cast("Mapping[str, JSONValue]", entry)["artifact_ref"]
        assert isinstance(ref, str)
        sources[name] = artifact_source(store.blobs.get(blob_hash_of_ref(ref)), scratch_dir=scratch)
    return snapshot.ref, sources


def install_checks(layout: ProjectLayout, store: OpStore, source: str) -> CheckSet:
    layout.checks_dir.mkdir(parents=True, exist_ok=True)
    check_set = CheckSet(layout.checks_dir, store)
    check_set.write_check("motion.py", source, op_id=f"g9b-{uuid.uuid4().hex}")
    return check_set


def run_motion_bundle(
    layout: ProjectLayout,
    store: OpStore,
    *,
    source: str,
    snapshot_ref: str,
    sources: Mapping[str, GeometrySource],
    motion: SnapshotMotionContext | None,
) -> CheckReport:
    """The server wiring, reproduced at the engine surface it delegates to."""
    bundle = install_checks(layout, store, source).capture()
    return run_bundle(
        bundle,
        sources,
        part="sweep",
        project_snapshot_ref=snapshot_ref,
        at_pose=None if motion is None else motion.at_pose,
        sweep=None if motion is None else motion.sweep,
        motion_generations=None if motion is None else motion.generations,
    )


def measured_of(report: CheckReport, name: str) -> Mapping[str, JSONValue]:
    measured = report.checks[name].measured
    assert isinstance(measured, dict), f"{name}: expected a record, got {measured!r}"
    return measured


def error_of(report: CheckReport, name: str) -> Mapping[str, JSONValue]:
    error = measured_of(report, name)["error"]
    assert isinstance(error, dict)
    return cast("Mapping[str, JSONValue]", error)


# ==========================================================================
# the frozen-snapshot proof: freeze, republish the arm, measure anyway


@pytest.fixture(scope="module")
def frozen_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[ProjectLayout, OpStore, str, dict[str, GeometrySource], SnapshotMotionContext, str]:
    """A run frozen BEFORE the arm is republished with different geometry.

    Returns ``(layout, store, snapshot_ref, sources, context, live_arm_ref)``
    where ``live_arm_ref`` is the post-mutation current artifact — provably
    different from the snapshot's pinned one, so any CURRENT-mid-run leak in
    the surfaces under test would change the numbers the tests assert.
    """
    layout, store = open_sweep_project(tmp_path_factory.mktemp("frozen-proj"))
    declare_motion_state(layout, store)
    scratch = tmp_path_factory.mktemp("frozen-scratch")
    snapshot_ref, sources = freeze_run(layout, store, scratch)
    context = SnapshotMotionContext(layout, store, snapshot_ref=snapshot_ref, scratch=scratch)
    publisher = Publisher(layout, store)
    before = publisher.current_result("arm")
    assert before is not None and before.artifact_ref is not None
    pinned_arm = before.artifact_ref
    (layout.root / "parts" / "arm.py").write_text(MUTATED_ARM_SRC, encoding="utf-8")
    build_part(publisher, layout, "arm")
    after = publisher.current_result("arm")
    assert after is not None and after.artifact_ref is not None
    assert after.artifact_ref != pinned_arm, "the mutation must actually republish the arm"
    return layout, store, snapshot_ref, sources, context, after.artifact_ref


class TestFrozenSnapshotResolution:
    def test_at_pose_measures_the_frozen_configuration(
        self,
        frozen_run: tuple[
            ProjectLayout, OpStore, str, dict[str, GeometrySource], SnapshotMotionContext, str
        ],
    ) -> None:
        """Posed interference and clearance are the FROZEN mechanism's pinned
        facts (198 mm³ on the stop at -90 deg, 0.1 mm pin/bore air at zero) —
        the live arm has no paddle and 1.0 mm of air, so a CURRENT read would
        fail both predicates and both exact assertions."""
        layout, store, snapshot_ref, sources, context, _live = frozen_run
        report = run_motion_bundle(
            layout,
            store,
            source=MOTION_CHECKS_SRC,
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=context,
        )
        assert report.checks["motion:closed_hits_stop"].passed is True
        assert report.checks["motion:zero_pose_air"].passed is True
        assert report.checks["motion:closed_hits_stop"].measured == pytest.approx(
            PADDLE_STOP_OVERLAP_MM3, rel=1e-6
        )
        assert report.checks["motion:zero_pose_air"].measured == pytest.approx(
            NOMINAL_RADIAL_AIR_MM, abs=1e-6
        )

    def test_sweep_measures_the_frozen_configuration(
        self,
        frozen_run: tuple[
            ProjectLayout, OpStore, str, dict[str, GeometrySource], SnapshotMotionContext, str
        ],
    ) -> None:
        """The sweep grid resolves its anchors through the pinned resolver:
        worst clearance is the frozen 0.1 mm air, not the live arm's 1.0."""
        layout, store, snapshot_ref, sources, context, _live = frozen_run
        report = run_motion_bundle(
            layout,
            store,
            source=MOTION_CHECKS_SRC,
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=context,
        )
        assert report.checks["motion:travel_clear"].passed is True
        record = measured_of(report, "motion:travel_clear")
        assert record["verdict"] == "holds_at_samples"
        assert record["samples_evaluated"] == 3
        worst = record["worst"]
        assert isinstance(worst, dict)
        assert worst["measured"] == pytest.approx(NOMINAL_RADIAL_AIR_MM, abs=1e-6)

    def test_report_records_the_frozen_motion_generations(
        self,
        frozen_run: tuple[
            ProjectLayout, OpStore, str, dict[str, GeometrySource], SnapshotMotionContext, str
        ],
    ) -> None:
        """§4: alongside ``project_snapshot_ref``, and round-trippable."""
        layout, store, snapshot_ref, sources, context, _live = frozen_run
        report = run_motion_bundle(
            layout,
            store,
            source=MOTION_CHECKS_SRC,
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=context,
        )
        assert report.project_snapshot_ref == snapshot_ref
        assert report.motion_generations == context.generations
        # Repointed by Stage 9C (KINEMATICS.md §5): the coupling set is the
        # fourth frozen generation — it governs the derived values the run's
        # posed measurements and sweeps composed, so the report records it
        # alongside the other three (this project declares none: generation 0).
        assert report.motion_generations == {
            "joints": 1,
            "poses": 2,
            "motion_checks": 4,
            "couplings": 0,
        }
        document = report.to_json()
        assert document["motion_generations"] == report.motion_generations
        assert CheckReport.from_json(document) == report

    def test_motion_untouched_records_no_generations(
        self,
        frozen_run: tuple[
            ProjectLayout, OpStore, str, dict[str, GeometrySource], SnapshotMotionContext, str
        ],
    ) -> None:
        """A run whose predicates never resolve motion state records none —
        the generations say what governed the run, not what was on offer."""
        layout, store, snapshot_ref, sources, context, _live = frozen_run
        report = run_motion_bundle(
            layout,
            store,
            source='CHECKS = {"static": lambda m: m.volume("base/part") > 0.0}\n',
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=context,
        )
        assert report.checks["motion:static"].passed is True
        assert report.motion_generations is None
        assert report.to_json()["motion_generations"] is None

    def test_context_built_after_republication_refuses_by_name(
        self,
        frozen_run: tuple[
            ProjectLayout, OpStore, str, dict[str, GeometrySource], SnapshotMotionContext, str
        ],
        tmp_path: Path,
    ) -> None:
        """The other half of never-CURRENT: a context frozen from the OLD
        snapshot after the arm moved on cannot reconstruct the frozen build's
        addressable geometry, and says so by name — the sweep comes back
        ``unresolvable`` with zero samples, never a measurement of the live
        arm (whose 1.0 mm air would pass ``mc-clear`` just as the frozen
        0.1 mm does — only the refusal distinguishes honest from leaky)."""
        layout, store, snapshot_ref, sources, _context, live_arm = frozen_run
        late = SnapshotMotionContext(layout, store, snapshot_ref=snapshot_ref, scratch=tmp_path)
        report = run_motion_bundle(
            layout,
            store,
            source=MOTION_CHECKS_SRC,
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=late,
        )
        record = measured_of(report, "motion:travel_clear")
        # The predicate compares verdict to "holds_at_samples" and fails.
        assert report.checks["motion:travel_clear"].passed is False
        assert record["verdict"] == "unresolvable"
        assert record["reason"] == "unresolvable_joint"
        detail = record["detail"]
        assert isinstance(detail, str)
        assert "republished after this run's snapshot froze" in detail
        assert live_arm in detail
        assert record["samples_evaluated"] == 0
        assert record["worst"] is None
        # The posed reads refuse through the same pinned resolver.
        for name in ("motion:closed_hits_stop", "motion:zero_pose_air"):
            assert report.checks[name].passed is False
            error = error_of(report, name)
            assert error["type"] == "BoundPoseError"
            message = error["message"]
            assert isinstance(message, str)
            assert "unresolvable" in message


# ==========================================================================
# the steady project every remaining clause shares (never mutated)


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> tuple[ProjectLayout, OpStore]:
    layout, store = open_sweep_project(tmp_path_factory.mktemp("surface-proj"))
    declare_motion_state(layout, store)
    return layout, store


@pytest.fixture(scope="module")
def run_env(
    project: tuple[ProjectLayout, OpStore], tmp_path_factory: pytest.TempPathFactory
) -> tuple[str, dict[str, GeometrySource]]:
    layout, store = project
    return freeze_run(layout, store, tmp_path_factory.mktemp("surface-scratch"))


class TestProjectScopeRefusals:
    """Named refusals THROUGH the surfaces, recorded as the check's failure."""

    def test_unknown_pose_is_the_named_pose_refusal(
        self,
        project: tuple[ProjectLayout, OpStore],
        run_env: tuple[str, dict[str, GeometrySource]],
        tmp_path: Path,
    ) -> None:
        layout, store = project
        snapshot_ref, sources = run_env
        context = SnapshotMotionContext(layout, store, snapshot_ref=snapshot_ref, scratch=tmp_path)
        report = run_motion_bundle(
            layout,
            store,
            source=(
                'CHECKS = {"ghost": lambda m: '
                'm.at_pose("p-nope").clearance("arm/part", "base/part") > 0.0}\n'
            ),
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=context,
        )
        assert report.checks["motion:ghost"].passed is False
        error = error_of(report, "motion:ghost")
        assert error["type"] == "BoundPoseError"
        message = error["message"]
        assert isinstance(message, str)
        assert "no pose 'p-nope' is declared" in message
        # A refusal still read the frozen motion state: generations recorded.
        assert report.motion_generations == context.generations

    def test_unknown_and_withdrawn_motion_checks_refuse_by_name(
        self,
        project: tuple[ProjectLayout, OpStore],
        run_env: tuple[str, dict[str, GeometrySource]],
        tmp_path: Path,
    ) -> None:
        layout, store = project
        snapshot_ref, sources = run_env
        context = SnapshotMotionContext(layout, store, snapshot_ref=snapshot_ref, scratch=tmp_path)
        report = run_motion_bundle(
            layout,
            store,
            source=(
                "CHECKS = {\n"
                '    "unknown": lambda m: m.sweep("mc-nope").verdict == "holds_at_samples",\n'
                '    "withdrawn": lambda m: m.sweep("mc-gone").verdict == "holds_at_samples",\n'
                "}\n"
            ),
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=context,
        )
        assert report.checks["motion:unknown"].passed is False
        unknown = error_of(report, "motion:unknown")
        assert unknown["code"] == "addressing_error"
        message = unknown["message"]
        assert isinstance(message, str)
        assert "mc-nope" in message
        assert report.checks["motion:withdrawn"].passed is False
        withdrawn = error_of(report, "motion:withdrawn")
        assert withdrawn["code"] == "validation_error"
        message = withdrawn["message"]
        assert isinstance(message, str)
        assert "withdrawn" in message
        assert "never evaluated" in message


class TestPartScopeRefusal:
    """The scope rule, enforced where it lives: the facade carries nothing."""

    def test_at_pose_refusal_is_contract_kind_at_evaluation(self) -> None:
        m = part_measurement("arm", part_only_source(object()))
        with pytest.raises(ValidationError) as excinfo:
            m.at_pose("p-zero")
        assert excinfo.value.kind == "contract"
        assert "script_contract.md §6" in excinfo.value.message
        assert "KINEMATICS.md §4" in excinfo.value.message
        assert "part-scope" in excinfo.value.message

    def test_sweep_refusal_is_contract_kind_at_evaluation(self) -> None:
        m = part_measurement("arm", part_only_source(object()))
        with pytest.raises(ValidationError) as excinfo:
            m.sweep("mc-clear")
        assert excinfo.value.kind == "contract"
        assert "script_contract.md §6" in excinfo.value.message

    def test_part_scope_predicate_refusal_is_recorded_as_the_checks_failure(self) -> None:
        """The gate clause verbatim: evaluation-time, named, and it is the
        CHECK that fails — collection succeeded, nothing was inspected at
        load time, and the sibling predicate in the same module still runs."""

        def factory() -> Measurement:
            return part_measurement("arm", part_only_source(object()))

        results = run_checks(
            {
                "posed": lambda m: m.at_pose("p-zero").clearance("part", "part") > 0.0,
                "swept": lambda m: m.sweep("mc-clear").verdict == "holds_at_samples",
                "static": lambda _m: True,
            },
            factory,
        )
        for name in ("posed", "swept"):
            assert results[name].passed is False
            measured = results[name].measured
            assert isinstance(measured, dict)
            error = measured["error"]
            assert isinstance(error, dict)
            assert error["code"] == "validation_error"
            message = error["message"]
            assert isinstance(message, str)
            assert "script_contract.md §6" in message
        assert results["static"].passed is True

    def test_project_facade_without_motion_context_keeps_the_refusal(
        self,
        project: tuple[ProjectLayout, OpStore],
        run_env: tuple[str, dict[str, GeometrySource]],
    ) -> None:
        """``run_bundle`` with no motion threading (every pre-9B caller) is
        indistinguishable from part scope for these calls: same named
        refusal, and no motion generations appear in the report."""
        layout, store = project
        snapshot_ref, sources = run_env
        report = run_motion_bundle(
            layout,
            store,
            source=(
                'CHECKS = {"posed": lambda m: '
                'm.at_pose("p-zero").clearance("arm/part", "base/part") > 0.0}\n'
            ),
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=None,
        )
        assert report.checks["motion:posed"].passed is False
        error = error_of(report, "motion:posed")
        assert error["code"] == "validation_error"
        assert report.motion_generations is None


class TestInPredicateTimeout:
    def test_motion_timeout_lands_as_unverifiable_with_partial_facts(
        self,
        project: tuple[ProjectLayout, OpStore],
        run_env: tuple[str, dict[str, GeometrySource]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """§4: not a pass, not the crash shape — the named ``motion_timeout``
        refusal under ``measured.unverifiable``, carrying the per-sample
        facts the grinding child streamed before the ceiling kill."""
        layout, store = project
        snapshot_ref, sources = run_env
        # The ceiling must dominate the spawn interpreter's bootstrap even on a
        # loaded machine (see TEST_CEILING_S in test_sweep_evaluation.py): too
        # short and the child is killed before it streams a single sample.
        context = SnapshotMotionContext(
            layout, store, snapshot_ref=snapshot_ref, scratch=tmp_path, timeout_s=10.0
        )
        monkeypatch.setattr(motion_module, "_sweep_child", grinding_child)
        report = run_motion_bundle(
            layout,
            store,
            source=(
                'CHECKS = {"tight": lambda m: m.sweep("mc-tight").verdict == "holds_at_samples"}\n'
            ),
            snapshot_ref=snapshot_ref,
            sources=sources,
            motion=context,
        )
        outcome = report.checks["motion:tight"]
        assert outcome.passed is False
        measured = outcome.measured
        assert isinstance(measured, dict)
        assert "error" not in measured  # unverifiable is not the crash shape
        refusal = measured["unverifiable"]
        assert isinstance(refusal, dict)
        assert refusal["reason"] == "motion_timeout"
        assert refusal["id"] == "mc-tight"
        assert refusal["timeout_s"] == 10.0
        assert refusal["samples_evaluated"] == len(STREAMED_SAMPLES)
        partial = refusal["partial"]
        assert isinstance(partial, list)
        assert [cast("dict[str, JSONValue]", s)["values"] for s in partial] == [
            values for values, _measured in STREAMED_SAMPLES
        ]
        # The run DID resolve motion state; the frozen generations say so.
        assert report.motion_generations == context.generations


class TestPosedContextValidation:
    """Direct facade behavior the bundle clauses exercise only indirectly."""

    def test_at_pose_validates_the_pose_at_the_call(
        self,
        project: tuple[ProjectLayout, OpStore],
        run_env: tuple[str, dict[str, GeometrySource]],
        tmp_path: Path,
    ) -> None:
        layout, store = project
        snapshot_ref, _sources = run_env
        context = SnapshotMotionContext(layout, store, snapshot_ref=snapshot_ref, scratch=tmp_path)
        with pytest.raises(BoundPoseError) as excinfo:
            context.at_pose("p-nope")
        assert excinfo.value.reason == "unknown_pose"
        placement = context.at_pose("p-swing")
        assert placement.pose_id == "p-swing"

    def test_sweep_results_are_memoized_per_run(
        self,
        project: tuple[ProjectLayout, OpStore],
        run_env: tuple[str, dict[str, GeometrySource]],
        tmp_path: Path,
    ) -> None:
        """One run has one motion state: asking twice restates the same
        record without paying for (or re-deciding) a second grid."""
        layout, store = project
        snapshot_ref, _sources = run_env
        context = SnapshotMotionContext(layout, store, snapshot_ref=snapshot_ref, scratch=tmp_path)
        first = context.sweep("mc-clear")
        second = context.sweep("mc-clear")
        assert first == second
        assert first["verdict"] == "holds_at_samples"
