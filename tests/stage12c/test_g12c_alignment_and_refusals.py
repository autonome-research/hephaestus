# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12C: alignment, the refusals around it, and the ceiling (§6.5, §7.3).

Gate clauses covered here:

* **39** ``as_posed`` and ``declared`` both name their mode, the declared
  transform is echoed and validated as rigid or refused, and ``principal``
  refuses ``scan_principal_unavailable`` on both a scan mesh and a point cloud;
* **40** ``compare_solids`` and ``m.diff`` refuse a ``scan:`` target with
  ``scan_target_unsupported``, naming the replacement, and every existing G8B
  ``SolidDiff`` record is byte-for-byte unchanged;
* **44** ``scan_timeout``: a fault-injected slow distance returns the named
  refusal carrying the partial facts, and inside a predicate lands as
  ``unverifiable`` — not a pass, not a crash.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any, cast

import pytest
from _g12c import BOX_X, BOX_Y, BOX_Z, Fixtures, build_ok, install_import
from hephaestus.core.errors import ValidationError
from hephaestus.core.project_compare import CompareRefusal, ProjectComparer
from hephaestus.core.scan_compare import (
    SCAN_TIMEOUT_ENV,
    ScanRefusal,
    ScanTimeout,
    bounded_scan_distance,
    scan_timeout_s,
)
from hephaestus.geom.compare import (
    RIGID_EPS,
    SCAN_ALIGN_MODES,
    ScanCompareError,
    refuse_scan_principal,
    scan_distance,
    validate_declared_transform,
)
from hephaestus.testing.tools_fixture import Project

IDENTITY: tuple[float, ...] = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)  # fmt: skip

#: A rigid move: +5 mm along X, no rotation.
SHIFT_X: tuple[float, ...] = (
    1.0, 0.0, 0.0, 5.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)  # fmt: skip


def _target() -> Any:
    from build123d import Box

    return Box(BOX_X + 4.0, BOX_Y + 4.0, BOX_Z + 4.0)


#: The gap the fixture pair holds by construction: the target box is 4 mm larger
#: in every dimension and both are centred, so every face of the scan sits
#: exactly 2 mm inside the part. Arithmetic, not a golden.
SCAN_GAP_MM = 2.0


# ==========================================================================
# clause 39 — the two admitted modes, and the refused one


def test_as_posed_names_its_mode_and_carries_no_transform(meshes: Fixtures) -> None:
    record = scan_distance(cast("Any", _target()), meshes.box_vertices, meshes.box_faces)
    assert record.align == "as_posed"
    assert record.declared_transform is None


def test_declared_echoes_its_transform_and_moves_the_scan(meshes: Fixtures) -> None:
    """The declared mode moves the SCAN and says exactly which transform it used.

    Hand-computable again. The target is 44 x 34 x 24, so its walls are at
    x = +/-22, y = +/-17, z = +/-12. Shifting the scan +5 mm along X puts its
    +X corners at x = 25 — 3 mm *outside* the wall, an unsigned 3.0 — while its
    -X corners land at x = -15, still inside, whose nearest wall is 2 mm away in
    y and z. So min 2.0, max 3.0: the numbers MOVED, and the record names the
    mode and echoes the transform that moved them.
    """
    record = scan_distance(
        cast("Any", _target()),
        meshes.box_vertices,
        meshes.box_faces,
        align="declared",
        declared_transform=SHIFT_X,
    )
    assert record.align == "declared"
    assert record.declared_transform == SHIFT_X
    assert record.scan_to_part_min_mm == pytest.approx(2.0, abs=1e-9)
    assert record.scan_to_part_max_mm == pytest.approx(3.0, abs=1e-9)


def test_a_declared_identity_reproduces_the_as_posed_numbers(meshes: Fixtures) -> None:
    """The transform is applied, not merely recorded — identity is the control."""
    posed = scan_distance(cast("Any", _target()), meshes.box_vertices, meshes.box_faces)
    declared = scan_distance(
        cast("Any", _target()),
        meshes.box_vertices,
        meshes.box_faces,
        align="declared",
        declared_transform=IDENTITY,
    )
    assert declared.scan_to_part_mean_mm == pytest.approx(posed.scan_to_part_mean_mm, abs=1e-12)
    assert declared.align != posed.align


@pytest.mark.parametrize(
    ("transform", "why"),
    [
        (
            (2.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0),
            "a scale is not a pose",
        ),
        (
            (-1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0),
            "determinant -1: a mirror is not a rotation",
        ),
        (
            (1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 2.0),
            "the last row of a rigid 4x4 is 0 0 0 1",
        ),
        ((1.0, 0.0, 0.0), "sixteen numbers, not three"),
        (
            (float("nan"), 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0),
            "a non-finite entry",
        ),
    ],
)
def test_a_transform_that_is_not_rigid_is_refused_by_name(
    transform: tuple[float, ...], why: str
) -> None:
    with pytest.raises(ScanCompareError) as caught:
        validate_declared_transform(transform)
    assert caught.value.reason == "declared_transform_not_rigid", why


def test_a_rotation_is_admitted_and_a_near_rotation_is_not() -> None:
    """The tolerance is real: 1e-9 orthonormality, checked in both directions."""
    angle = math.radians(30.0)
    rotation = (
        math.cos(angle), -math.sin(angle), 0.0, 0.0,
        math.sin(angle), math.cos(angle), 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )  # fmt: skip
    assert validate_declared_transform(rotation) == rotation

    nudged = list(rotation)
    nudged[0] += 10 * RIGID_EPS
    with pytest.raises(ScanCompareError) as caught:
        validate_declared_transform(tuple(nudged))
    assert caught.value.reason == "declared_transform_not_rigid"


def test_a_transform_supplied_with_as_posed_is_refused(meshes: Fixtures) -> None:
    """Alignment is a DECLARED choice: a transform that the mode does not name
    would be a normalization the record never states (``COMPARE.md`` §1)."""
    with pytest.raises(ScanCompareError) as caught:
        scan_distance(
            cast("Any", _target()),
            meshes.box_vertices,
            meshes.box_faces,
            align="as_posed",
            declared_transform=SHIFT_X,
        )
    assert caught.value.reason == "declared_transform_not_rigid"


def test_principal_is_absent_from_the_admitted_modes() -> None:
    assert set(SCAN_ALIGN_MODES) == {"as_posed", "declared"}
    assert "principal" not in SCAN_ALIGN_MODES


def test_the_principal_refusal_carries_both_of_its_reasons() -> None:
    """§6.5 gives two independent reasons and the message carries both.

    The pure function, once. It never inspects its target — the refusal is
    structurally kind-independent — so calling it twice with two different
    strings would be one code path run twice and would prove nothing about
    either kind. The clause's "on both a scan mesh and a point cloud" half is
    asserted below, where the two kinds are real files that the engine and the
    tool actually resolve.
    """
    with pytest.raises(ScanCompareError) as caught:
        refuse_scan_principal("scan:limb-l.stl")
    assert caught.value.reason == "scan_principal_unavailable"
    assert "needs a shape with volume" in caught.value.message
    assert "PARTIAL" in caught.value.message or "partial" in caught.value.message


@pytest.mark.parametrize(
    ("name", "fixture"), [("limb.stl", "box_stl"), ("landmarks.xyz", "points_xyz")]
)
def test_principal_refuses_on_both_a_scan_mesh_and_a_point_cloud(
    project: Project, meshes: Fixtures, name: str, fixture: str
) -> None:
    """Both kinds, as files the engine resolves — not one code path run twice.

    The third repair pass's verifier: the earlier version of this clause
    parametrized two target STRINGS against ``refuse_scan_principal``, which
    never looks at its argument's kind, so "on both a scan mesh and a point
    cloud" was decoration over a single path. Here each kind is a real staged
    import that the tool reads, canonicalizes and would have measured — a point
    cloud reaching this surface is measured for real in the clause below, so it
    is genuinely a different operand — and the refusal must arrive for both.

    The refusal being kind-independent is the *correct* design (a point cloud
    cannot have principal axes for the same two §6.5 reasons a partial mesh
    cannot), and this is what would catch an implementation that resolved the
    operand first and let one of the two kinds through on its way.
    """
    from hephaestus.agent_bridge.dispatch import DispatchError
    from hephaestus.core.scan_compare import ProjectScanComparer

    install_import(project.root, name, cast("bytes", getattr(meshes, fixture)))
    build_ok(project, "cuff", "part.geometry = Box(44.0, 34.0, 24.0)\n")

    # The engine surface, where the operands exist and could have been resolved.
    comparer = ProjectScanComparer(project.layout, project.store)
    with pytest.raises(ScanCompareError) as engine:
        comparer.compare("cuff", f"scan:{name}", units="mm", align="principal")
    assert engine.value.reason == "scan_principal_unavailable"

    # And the tool surface, where a model receives it as the stable token.
    with pytest.raises(DispatchError) as tool:
        project.call(
            "compare_to_scan",
            {"part": "cuff", "scan": name, "units": "mm", "align": "principal"},
        )
    assert tool.value.reason == "scan_principal_unavailable"


def test_a_point_cloud_is_measured_with_the_declared_bound_not_the_exact_method(
    meshes: Fixtures,
) -> None:
    """§2.3 + §6.3: no triangles means no exact refinement, and the record says so.

    A point set has no surface between its points, so the nearest-point distance
    is all it can honestly support — and it IS a sound upper bound on the
    distance to whatever surface the points were sampled from, which is §6.3
    step 2's own argument one level weaker.
    """
    record = scan_distance(cast("Any", _target()), meshes.box_vertices, None)
    assert record.part_to_scan_method == "vertex_nn_upper_bound"
    assert record.part_to_scan_bias == "over"
    assert record.part_to_scan_mean_mm is None
    assert record.part_to_scan_upper_bound_mm is not None


def test_a_point_cloud_reaches_the_tool_and_is_measured_as_a_point_cloud(
    project: Project, meshes: Fixtures
) -> None:
    """§2.3 + §6.2 at the engine surface, not only in geom.

    A point cloud IS a measurement target — bbox, count, point-to-part distances
    — and the tool measures it. What it does not get is a mesh's vocabulary: the
    quality record is empty rather than zero-filled, because a record of zeros
    would read as a clean mesh, and direction B comes back as the declared upper
    bound because there is no surface between the points to refine against.
    """
    install_import(project.root, "landmarks.xyz", meshes.points_xyz)
    build_ok(project, "shroud", "part.geometry = Box(44.0, 34.0, 24.0)\n")
    result = cast(
        "dict[str, Any]",
        project.call(
            "compare_to_scan",
            {"part": "shroud", "scan": "landmarks.xyz", "units": "mm"},
        ),
    )
    distance = cast("dict[str, Any]", result["distance"])
    assert distance["scan_to_part_min_mm"] == pytest.approx(2.0, abs=1e-9)
    assert distance["scan_samples"] == 8
    assert distance["part_to_scan_method"] == "vertex_nn_upper_bound"
    assert distance["part_to_scan_bias"] == "over"
    assert distance["part_to_scan_mean_mm"] is None
    assert distance["part_to_scan_upper_bound_mm"] is not None
    assert result["quality"] == {}, "a point cloud has no MeshQuality to report"


def test_the_facade_refuses_principal_before_it_touches_geometry() -> None:
    """``m.scan_diff(..., align="principal")`` names the refusal at the surface."""
    from hephaestus.core.addressing import GeometryIndex
    from hephaestus.core.checks.facade import GeometrySource, part_measurement

    source = cast(
        "GeometrySource",
        type(
            "Src",
            (),
            {
                "index": GeometryIndex(labels=("part",), bindings={}, tags=frozenset()),
                "shape": lambda self, resolution: object(),
            },
        )(),
    )
    facade = part_measurement("widget", source, scan=lambda *_: {})
    with pytest.raises(ValidationError) as caught:
        facade.scan_diff("part", "scan:limb.stl", align="principal")
    assert "scan_principal_unavailable" in caught.value.message


# ==========================================================================
# clause 40 — compare_solids and m.diff refuse a scan: target


def test_compare_solids_refuses_a_scan_target_by_name(project: Project) -> None:
    """The tool's own path, through the resolver ``heph diff`` uses."""
    comparer = ProjectComparer(project.layout, project.store)
    with pytest.raises(CompareRefusal) as caught:
        comparer.target_operand("scan:limb-l.stl", None)
    assert caught.value.reason == "scan_target_unsupported"
    assert "compare_to_scan" in caught.value.message
    assert "m.scan_diff" in caught.value.message


def test_compare_solids_refuses_a_scan_target_through_dispatch(
    project: Project, meshes: Fixtures
) -> None:
    """And it arrives at a model as the stable token, never as an exception."""
    from hephaestus.agent_bridge.dispatch import DispatchError

    install_import(project.root, "limb.stl", meshes.box_stl)
    build_ok(project, "cuff", "part.geometry = Box(44.0, 34.0, 24.0)\n")
    with pytest.raises(DispatchError) as caught:
        project.call("compare_solids", {"part": "cuff", "target": "scan:limb.stl"})
    assert caught.value.reason == "scan_target_unsupported"
    assert "compare_to_scan" in str(caught.value)


def test_m_diff_refuses_a_scan_target_by_name() -> None:
    """The CHECKS facade's half of the same rule."""
    from hephaestus.core.addressing import GeometryIndex
    from hephaestus.core.checks.facade import GeometrySource, part_measurement

    source = cast(
        "GeometrySource",
        type(
            "Src",
            (),
            {
                "index": GeometryIndex(labels=("part",), bindings={}, tags=frozenset()),
                "shape": lambda self, resolution: object(),
            },
        )(),
    )
    facade = part_measurement("widget", source, imports=lambda path: object())
    with pytest.raises(ValidationError) as caught:
        facade.diff("part", "scan:limb.stl")
    assert "scan_target_unsupported" in caught.value.message
    assert "m.scan_diff" in caught.value.message


def test_the_solid_diff_record_is_byte_for_byte_unchanged() -> None:
    """The G8B regression: ``SolidDiff`` gained nothing and lost nothing.

    Field names AND order, because ``dataclasses.asdict`` IS the wire form every
    G8B record was written with (``COMPARE.md`` §1): an inserted field would
    change every stored comparison's shape while every individual assertion
    about it still passed.
    """
    from hephaestus.geom.compare import (
        SolidDiff,
        SurfaceDistance,
        TopologyCensus,
        TopologyDiff,
        VolumeDiff,
    )

    assert [f.name for f in dataclasses.fields(SolidDiff)] == [
        "align",
        "volume",
        "surface",
        "topology",
        "a_bbox_mm",
        "b_bbox_mm",
        "a_volume_mm3",
        "b_volume_mm3",
    ]
    assert [f.name for f in dataclasses.fields(VolumeDiff)] == [
        "common_mm3",
        "a_only_mm3",
        "b_only_mm3",
        "iou",
        "align",
    ]
    assert [f.name for f in dataclasses.fields(SurfaceDistance)] == [
        "a_to_b_mean_mm",
        "b_to_a_mean_mm",
        "chamfer_mm",
        "max_deviation_mm",
        "a_samples",
        "b_samples",
        "align",
    ]
    assert [f.name for f in dataclasses.fields(TopologyCensus)] == [
        "solids",
        "faces",
        "edges",
        "planar_faces",
        "cylindrical_faces",
        "other_faces",
        "genus",
        "sealed",
    ]
    assert [f.name for f in dataclasses.fields(TopologyDiff)][:2] == ["a", "b"]


def test_compare_solids_still_answers_a_part_target(project: Project) -> None:
    """The negative control for the refusal: the tool is otherwise untouched."""
    build_ok(project, "plate", "part.geometry = Box(40.0, 20.0, 5.0)\n")
    result = cast(
        "dict[str, Any]",
        project.call("compare_solids", {"part": "plate", "target": "part:plate"}),
    )
    diff = cast("dict[str, Any]", result["diff"])
    assert cast("dict[str, Any]", diff["volume"])["iou"] == pytest.approx(1.0, abs=1e-9)


# ==========================================================================
# clause 44 — scan_timeout


def test_the_ceiling_is_env_overridable_under_the_local_floor_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SCAN_TIMEOUT_ENV, "12.5")
    assert scan_timeout_s() == pytest.approx(12.5)
    monkeypatch.setenv(SCAN_TIMEOUT_ENV, "not-a-number")
    assert scan_timeout_s() == pytest.approx(300.0)


def test_a_deadline_that_expires_before_anything_streams_says_so_and_claims_nothing(
    meshes: Fixtures, tmp_path: Path
) -> None:
    """The degenerate deadline: nothing arrived, and the refusal says nothing arrived.

    A zero-second ceiling expires before the child can send its first message,
    so ``partial`` is ``None`` and ``lost`` names the cheap facts too. That is
    the correct answer and it is asserted here **as its own case**, apart from
    the clause-44 evidence below — because a test that ran this deadline and
    then claimed to be about "the partial facts" would be asserting the empty
    case under the name of the full one.
    """
    from hephaestus.geom.mesh import canonicalize_mesh, facts_to_json

    canonical = canonicalize_mesh("limb.stl", meshes.box_stl, "mm")
    with pytest.raises(ScanTimeout) as caught:
        bounded_scan_distance(
            _target(),
            canonical.blob,
            facts_to_json(canonical),
            source="limb.stl",
            timeout_s=0.0,
            scratch=tmp_path,
        )
    refusal = caught.value
    assert refusal.reason == "scan_timeout"
    assert set(refusal.lost) == {"scan_facts", "scan_to_part", "part_to_scan"}
    assert refusal.partial is None, "nothing arrived, so nothing is claimed"
    payload = refusal.to_json()
    assert payload["status"] == "scan_timeout"
    assert payload["timeout_s"] == pytest.approx(0.0)


def _grinding_scan(
    stage: str, *, timeout_s: float, meshes: Fixtures, tmp_path: Path, pid_file: Path
) -> tuple[ScanTimeout, object]:
    """Run one fault-injected scan comparison to its ceiling; return the refusal.

    The fault is injected INSIDE the child's geometry call (``_g12c_grind``), so
    everything before the ground stage runs for real and what the refusal
    carries is the product's own measurement.
    """
    import _g12c_grind
    from hephaestus.core import scan_compare as engine
    from hephaestus.geom.mesh import canonicalize_mesh, facts_to_json

    canonical = canonicalize_mesh("limb.stl", meshes.box_stl, "mm")
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(engine, "_distance_child", _g12c_grind.grinding_distance_child)
        monkey.setenv(_g12c_grind.GRIND_STAGE_ENV, stage)
        monkey.setenv(_g12c_grind.PID_FILE_ENV, str(pid_file))
        with pytest.raises(ScanTimeout) as caught:
            bounded_scan_distance(
                _target(),
                canonical.blob,
                facts_to_json(canonical),
                source="limb.stl",
                timeout_s=timeout_s,
                scratch=tmp_path,
            )
    finally:
        monkey.undo()
    return caught.value, canonical


def test_a_ceiling_kill_returns_scan_timeout_carrying_the_partial_facts(
    meshes: Fixtures, tmp_path: Path
) -> None:
    """Clause 44, first half: quality + bbox survive the kill, and they are REAL.

    The fault is a direction-A distance that never returns, at a ceiling the
    cheap facts comfortably beat — so the refusal carries what the child had
    already sent, and every number in it is asserted against the canonicalizer's
    own record rather than against "is not empty". That is the shape
    ``mesh_sew_timeout`` (G12B.24) already uses, and it is the shape that makes
    the difference between "the refusal has a partial" and "the partial is
    true".
    """
    from _g12c_grind import STAGE_SCAN_TO_PART
    from hephaestus.core.scan_compare import PARTIAL_COMPLETED

    refusal, canonical = _grinding_scan(
        STAGE_SCAN_TO_PART,
        timeout_s=6.0,
        meshes=meshes,
        tmp_path=tmp_path,
        pid_file=tmp_path / "a.pid",
    )

    assert refusal.reason == "scan_timeout"
    assert refusal.partial is not None, "the cheap facts had time to stream"
    partial = cast("dict[str, Any]", refusal.partial)
    # The §3 quality record, verbatim from the sidecar the canonicalizer wrote.
    assert partial["quality"] == cast("Any", canonical).quality.to_json()
    # Both bounding boxes: the scan's, and the part the comparison was against.
    assert partial["scan_bbox_mm"] == pytest.approx(
        [float(v) for v in cast("Any", canonical).bbox_mm], abs=1e-9
    )
    assert len(cast("list[float]", partial["part_bbox_mm"])) == 3
    assert partial["source_path"] == "limb.stl"
    assert partial["kind"] == "mesh"
    assert int(cast("int", partial["triangle_count"])) == len(meshes.box_faces)
    # Neither direction ran, so neither is claimed and both are named lost.
    assert PARTIAL_COMPLETED not in partial
    assert set(refusal.lost) == {"scan_to_part", "part_to_scan"}
    assert "scan_facts" not in refusal.lost, "the facts arrived, so they are not lost"


def test_a_kill_after_one_direction_carries_the_direction_that_completed(
    meshes: Fixtures, tmp_path: Path
) -> None:
    """Clause 44's "whichever direction completed", exercised rather than assumed.

    Direction A is exact and cheap; direction B is the expensive one, so the
    deadline in a real socket comparison falls inside B. Here it is made to fall
    there deliberately, and the refusal carries the scan→part distances the run
    had actually finished measuring — with ``lost`` naming only the direction
    that did not arrive.

    That distinction is the operator-facing point of the clause. "The comparison
    timed out" is not actionable; "the scan comes no closer than 2.00 mm to your
    part and the part→scan half never finished" is, and it is exactly as true as
    the completed direction is.
    """
    from _g12c_grind import STAGE_PART_TO_SCAN
    from hephaestus.core.scan_compare import PARTIAL_COMPLETED
    from hephaestus.geom.compare import SCAN_DIRECTION_SCAN_TO_PART

    refusal, _canonical = _grinding_scan(
        STAGE_PART_TO_SCAN,
        timeout_s=12.0,
        meshes=meshes,
        tmp_path=tmp_path,
        pid_file=tmp_path / "b.pid",
    )

    assert refusal.reason == "scan_timeout"
    partial = cast("dict[str, Any]", refusal.partial)
    assert partial is not None
    completed = cast("dict[str, Any]", partial[PARTIAL_COMPLETED])
    assert set(completed) == {SCAN_DIRECTION_SCAN_TO_PART}
    direction_a = cast("dict[str, Any]", completed[SCAN_DIRECTION_SCAN_TO_PART])
    # The real measurement: the fixture scan is the part's own box offset by
    # 2.00 mm, which is the same number the completed comparison reports.
    assert direction_a["scan_to_part_min_mm"] == pytest.approx(SCAN_GAP_MM, abs=1e-6)
    assert direction_a["scan_samples"] > 0
    assert direction_a["align"] == "as_posed"
    # ``lost`` and ``completed`` partition the vocabulary: exactly the direction
    # that did not arrive, and nothing else.
    assert set(refusal.lost) == {"part_to_scan"}
    assert "scan_to_part" not in refusal.lost
    # …and no part→scan figure leaked in beside it. A refusal that carried a
    # half-computed distance would be the plausible wrong answer this stage
    # exists to refuse, arriving through the refusal itself.
    for forbidden in (
        "part_to_scan_mean_mm",
        "part_to_scan_max_mm",
        "part_to_scan_upper_bound_mm",
    ):
        assert forbidden not in direction_a


def test_the_killed_scan_subprocess_is_dead_and_not_orphaned(
    meshes: Fixtures, tmp_path: Path
) -> None:
    """The ceiling is a kill, not a request. The child does not outlive it."""
    import os
    import time as _time

    from _g12c_grind import STAGE_PART_TO_SCAN

    pid_file = tmp_path / "c.pid"
    refusal, _canonical = _grinding_scan(
        STAGE_PART_TO_SCAN,
        timeout_s=6.0,
        meshes=meshes,
        tmp_path=tmp_path,
        pid_file=pid_file,
    )
    assert refusal.reason == "scan_timeout"

    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
    with pytest.raises(OSError):
        for _ in range(50):
            os.kill(child_pid, 0)
            _time.sleep(0.1)


def test_a_predicate_whose_scan_times_out_is_unverifiable_not_a_pass() -> None:
    """§7.3: inside a ``CHECKS`` predicate the kill lands as ``unverifiable``.

    Not a pass and not a crash. The check report records the named refusal under
    ``measured.unverifiable`` — the same discrimination ``compare_timeout`` and
    ``motion_timeout`` already get, extended to this refusal rather than
    reinvented for it.
    """
    from hephaestus.core.checks.engine import run_checks
    from hephaestus.core.checks.facade import Measurement

    def _factory() -> Measurement:
        return Measurement(sources={}, current_part="widget")

    def _predicate(_m: Measurement) -> bool:
        raise ScanTimeout(
            "scan_timeout: fault-injected",
            timeout_s=1.0,
            partial={"quality": {}, "scan_bbox_mm": [1.0, 2.0, 3.0]},
            lost=("scan_to_part", "part_to_scan"),
        )

    results = run_checks({"clears_the_limb": _predicate}, _factory)
    outcome = results["clears_the_limb"]
    assert outcome.passed is False
    measured = cast("dict[str, Any]", outcome.measured)
    assert "unverifiable" in measured
    assert "error" not in measured
    unverifiable = cast("dict[str, Any]", measured["unverifiable"])
    assert unverifiable["reason"] == "scan_timeout"
    assert unverifiable["partial"]["scan_bbox_mm"] == [1.0, 2.0, 3.0]


def test_a_scan_refusal_is_not_a_timeout(meshes: Fixtures, project: Project) -> None:
    """The two refusals stay apart: a file that cannot be admitted is not a kill."""
    from hephaestus.core.scan_compare import ProjectScanComparer

    install_import(project.root, "broken.stl", b"not a mesh at all")
    build_ok(project, "cuff", "part.geometry = Box(44.0, 34.0, 24.0)\n")
    comparer = ProjectScanComparer(project.layout, project.store)
    with pytest.raises(ScanRefusal) as caught:
        comparer.compare("cuff", "scan:broken.stl", units="mm")
    assert not isinstance(caught.value, ScanTimeout)
    assert caught.value.reason == "unreadable_scan"
