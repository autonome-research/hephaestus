# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12C: the two directions, and the record that reports them (§6.2-§6.4).

Gate clauses covered here:

* **34** direction A exactness against hand-computed closed-form distances;
* **35** direction B exactness against a brute-force all-triangle reference,
  proving the ``d_v + L_max`` candidate set is a sound superset;
* **36** ``scan_neighborhood_overflow`` on a pathological mesh, with the bound
  asserted to be **≥** the true distance;
* **37** record discipline: no ``iou``, no ``chamfer_mm``, and the §6.4
  invariant over all three part→scan fields;
* **38** ``scan_iou_unavailable`` where a caller asks for an IoU;
* **47** Tier 2 determinism across two processes, method strings included.
"""

from __future__ import annotations

import dataclasses
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from _g12c import BOX_X, BOX_Y, BOX_Z, Fixtures, brute_force_distances
from hephaestus.core.errors import ValidationError
from hephaestus.geom.compare import (
    SCAN_REFUSALS,
    ScanCompareError,
    ScanDistance,
    scan_distance,
    scan_iou,
)
from hephaestus.geom.mesh import (
    SCAN_METHOD_BOUND,
    SCAN_METHOD_EXACT,
    point_mesh_distances,
)

REPO = Path(__file__).resolve().parents[2]


# ==========================================================================
# clause 34 — direction A is exact, against closed-form arithmetic


def test_scan_to_part_equals_hand_computed_distances(meshes: Fixtures) -> None:
    """The scan's own vertices measured against an analytic target.

    The fixture is chosen so the answer is arithmetic rather than a second
    measurement: a 44 x 34 x 24 box concentric with the 40 x 30 x 20 scan box
    puts EVERY one of the scan's eight corners exactly 2 mm from the target's
    nearest face — the same distance in all three axes, so the mean, the max and
    the min are all 2.0 and any one of them being wrong is visible.
    """
    from build123d import Box

    target = Box(BOX_X + 4.0, BOX_Y + 4.0, BOX_Z + 4.0)
    record = scan_distance(
        cast("Any", target),
        meshes.box_vertices,
        meshes.box_faces,
        scan_canonical_hash="sha256:test",
        part_artifact_ref="artifact:test",
    )
    assert record.scan_samples == 8
    assert record.scan_to_part_mean_mm == pytest.approx(2.0, abs=1e-9)
    assert record.scan_to_part_max_mm == pytest.approx(2.0, abs=1e-9)
    assert record.scan_to_part_min_mm == pytest.approx(2.0, abs=1e-9)


def test_scan_to_part_max_and_min_are_separate_numbers(meshes: Fixtures) -> None:
    """A target the scan is NOT concentric with: three different closed forms.

    A 200 x 200 x 10 plate whose top face lies at z = -25 puts the scan box's
    four lower corners (z = -10) exactly 15 mm away and its four upper corners
    (z = +10) exactly 35 mm away — the plate is wide enough that every corner's
    nearest point is on the top face, so the arithmetic is one subtraction.
    Mean 25, max 35, min 15: a record reporting one averaged figure, or
    reporting the max where the min belongs, fails here.
    """
    from build123d import Box, Location

    target = Box(200.0, 200.0, 10.0).moved(Location((0.0, 0.0, -30.0)))
    record = scan_distance(
        cast("Any", target),
        meshes.box_vertices,
        meshes.box_faces,
        scan_canonical_hash="sha256:test",
        part_artifact_ref="artifact:test",
    )
    assert record.scan_to_part_min_mm == pytest.approx(15.0, abs=1e-9)
    assert record.scan_to_part_max_mm == pytest.approx(35.0, abs=1e-9)
    assert record.scan_to_part_mean_mm == pytest.approx(25.0, abs=1e-9)


# ==========================================================================
# clause 35 — direction B is exact, against a brute-force reference


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_direction_b_matches_a_brute_force_all_triangle_reference(
    meshes: Fixtures, seed: int
) -> None:
    """The kd-tree candidate set is a SOUND SUPERSET, not an approximation.

    Deterministic pseudo-random query points around the box (a fixed seed, so
    the fixture is a function of the test rather than of the run), measured both
    ways. Equality to 1e-9 is the claim §6.3 step 4 makes: *exact*, not
    approximate — the kd-tree only chooses which triangles to test.
    """
    rng = np.random.default_rng(seed)
    queries = rng.uniform(-40.0, 40.0, size=(60, 3))
    measured = point_mesh_distances(meshes.box_vertices, meshes.box_faces, queries)
    reference = brute_force_distances(meshes.box_vertices, meshes.box_faces, queries)

    assert measured.method == SCAN_METHOD_EXACT
    assert measured.exact is True
    assert measured.refusal is None
    np.testing.assert_allclose(measured.distances, reference, rtol=0.0, atol=1e-9)


def test_a_query_inside_the_mesh_is_still_the_distance_to_the_surface(
    meshes: Fixtures,
) -> None:
    """The centre of the box is 10 mm from its nearest face, not 0 and not 20.

    An unsigned distance to the triangle set is what this direction claims, and
    a point strictly inside is the case where a nearest-*vertex* answer (here
    sqrt(20² + 15² + 10²) = 26.9) is wildly wrong — so this is the clause that
    would fail if the refinement were ever quietly dropped.
    """
    queries = np.array([[0.0, 0.0, 0.0]])
    measured = point_mesh_distances(meshes.box_vertices, meshes.box_faces, queries)
    assert measured.distances[0] == pytest.approx(BOX_Z / 2.0, abs=1e-9)


# ==========================================================================
# clause 36 — scan_neighborhood_overflow, and the bound is an over-estimate


def test_a_pathological_mesh_abandons_the_refinement_by_name(meshes: Fixtures) -> None:
    """One enormous triangle inflates ``L_max``; the record says so and bounds."""
    # Deliberately NOT above a grid vertex: a query directly over one has a
    # vertex-NN distance that already equals the true distance, so it could not
    # show the bound being an over-estimate at all.
    queries = np.array([[2.1, 2.1, 1.0], [1.05, 3.07, 0.5]])
    measured = point_mesh_distances(
        meshes.pathological_vertices, meshes.pathological_faces, queries
    )
    assert measured.exact is False
    assert measured.method == SCAN_METHOD_BOUND
    assert measured.refusal == "scan_neighborhood_overflow"
    assert measured.max_candidates > measured.candidate_max

    truth = brute_force_distances(meshes.pathological_vertices, meshes.pathological_faces, queries)
    # §6.3 step 2's soundness: the vertex-nearest distance is an UPPER bound on
    # the true point-to-surface distance, never an under-estimate. An
    # under-estimate is the only direction that would matter, and it is the one
    # this asserts cannot happen.
    assert np.all(measured.distances >= truth - 1e-12)
    assert np.any(measured.distances > truth)


def test_an_orphan_vertex_cannot_undercut_the_bound(meshes: Fixtures) -> None:
    """An orphan vertex must not be the "nearest vertex" step 2 reasons from.

    Regression for the defect the Stage 12 verifier found and reproduced
    (2026-08-30): §6.3 step 2 argued that ``d_v`` is a sound upper bound
    "because the nearest vertex lies on some triangle", but canonicalization
    KEEPS every welded vertex including any the degenerate-triangle drop leaves
    unreferenced (``MeshAsset``), and the tree was built over all of them. A
    query near an orphan therefore got ``d_v`` to a point that is not on the
    surface — measured then at 1.208 mm against a true 19.8 mm, a 16x
    UNDER-estimate published under a field name and a bias that both promise
    the opposite, which makes a clearance predicate pass on a part that is
    nowhere near. The tree now holds referenced vertices only.

    This fixture is the reproduction, not a paraphrase of it: one real triangle
    at z = 0 and three collinear vertices at z ~ 19 that survive as orphans.
    Before the fix this asserted 1.0; the true distance is 20.0.
    """
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.5, 0.0, 0.0],
            [0.0, 0.5, 0.0],
            [0.0, 0.0, 19.0],
            [0.0, 0.0, 19.5],
            [0.0, 0.0, 20.0],
        ]
    )
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    queries = np.array([[0.0, 0.0, 20.0]])

    measured = point_mesh_distances(vertices, faces, queries)
    truth = brute_force_distances(vertices, faces, queries)

    # The soundness the field name promises, asserted on the geometry that
    # broke it rather than on one where the old premise happened to hold.
    assert np.all(measured.distances >= truth - 1e-12)
    # And it is not merely sound: with the orphans out of the tree the radius
    # query finds the real triangle, so the refinement succeeds outright.
    assert measured.exact is True
    assert np.allclose(measured.distances, truth, atol=1e-12)


def test_the_overflow_record_reports_the_bound_and_leaves_the_exact_fields_none(
    meshes: Fixtures,
) -> None:
    """The whole ``ScanDistance``, not just the mesh-side helper (§6.3 step 5)."""
    from build123d import Box

    record = scan_distance(
        cast("Any", Box(2.0, 2.0, 2.0)),
        meshes.pathological_vertices,
        meshes.pathological_faces,
        scan_canonical_hash="sha256:test",
        part_artifact_ref="artifact:test",
    )
    assert record.part_to_scan_method == SCAN_METHOD_BOUND
    assert record.part_to_scan_bias == "over"
    assert record.part_to_scan_refusal == "scan_neighborhood_overflow"
    assert record.part_to_scan_mean_mm is None
    assert record.part_to_scan_max_mm is None
    assert record.part_to_scan_upper_bound_mm is not None


# ==========================================================================
# clause 37 — record discipline


def test_scan_distance_has_no_iou_and_no_chamfer_field() -> None:
    """A rename that reintroduced either would fail the gate here (§6.4)."""
    names = {field.name for field in dataclasses.fields(ScanDistance)}
    assert "iou" not in names
    assert "chamfer_mm" not in names
    for forbidden in ("iou", "chamfer_mm"):
        assert not hasattr(ScanDistance, forbidden)


def _record(**overrides: Any) -> ScanDistance:
    base: dict[str, Any] = {
        "align": "as_posed",
        "declared_transform": None,
        "scan_to_part_mean_mm": 1.0,
        "scan_to_part_max_mm": 2.0,
        "scan_to_part_min_mm": 0.5,
        "scan_samples": 10,
        "part_to_scan_mean_mm": 1.0,
        "part_to_scan_max_mm": 2.0,
        "part_to_scan_upper_bound_mm": None,
        "part_to_scan_method": SCAN_METHOD_EXACT,
        "part_to_scan_bias": "exact",
        "part_to_scan_refusal": None,
        "part_samples": 10,
        "scan_canonical_hash": "sha256:x",
        "part_artifact_ref": "artifact:x",
    }
    base.update(overrides)
    return ScanDistance(**base)


def _invariant_holds(record: ScanDistance) -> bool:
    """§6.4's invariant over ALL THREE part→scan fields, as one predicate."""
    exact = (record.part_to_scan_mean_mm is not None, record.part_to_scan_max_mm is not None)
    bound = record.part_to_scan_upper_bound_mm is not None
    if exact[0] != exact[1]:
        return False  # a mean without its max describes a computation never run
    # Never both, never neither: the bound is the complement of the exact pair.
    return exact[0] != bound


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "part_to_scan_mean_mm": None,
            "part_to_scan_max_mm": None,
            "part_to_scan_upper_bound_mm": 3.0,
            "part_to_scan_method": SCAN_METHOD_BOUND,
            "part_to_scan_bias": "over",
            "part_to_scan_refusal": "scan_neighborhood_overflow",
        },
    ],
)
def test_the_three_part_to_scan_fields_move_together(overrides: dict[str, Any]) -> None:
    """Both legal shapes satisfy the invariant; the illegal ones below do not."""
    assert _invariant_holds(_record(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        # a mean without its max: one measurement's two halves, split
        {"part_to_scan_max_mm": None},
        # an exact figure standing beside a bound
        {"part_to_scan_upper_bound_mm": 3.0},
        # all three absent
        {
            "part_to_scan_mean_mm": None,
            "part_to_scan_max_mm": None,
            "part_to_scan_upper_bound_mm": None,
        },
    ],
)
def test_the_illegal_record_shapes_are_recognised_as_illegal(overrides: dict[str, Any]) -> None:
    assert not _invariant_holds(_record(**overrides))


def test_every_produced_record_satisfies_the_invariant(meshes: Fixtures) -> None:
    """Not a rule about hand-built records: the product's own outputs obey it."""
    from build123d import Box

    exact = scan_distance(
        cast("Any", Box(BOX_X + 4.0, BOX_Y + 4.0, BOX_Z + 4.0)),
        meshes.box_vertices,
        meshes.box_faces,
    )
    bounded = scan_distance(
        cast("Any", Box(2.0, 2.0, 2.0)),
        meshes.pathological_vertices,
        meshes.pathological_faces,
    )
    for record in (exact, bounded):
        assert _invariant_holds(record)
    assert exact.part_to_scan_method == SCAN_METHOD_EXACT
    assert bounded.part_to_scan_method == SCAN_METHOD_BOUND


def test_a_part_with_no_faces_refuses_instead_of_reporting_a_zero(meshes: Fixtures) -> None:
    """§6.4/§10 ``scan_unmeasurable`` at the PRODUCER, not only at the readers.

    The third repair pass's verifier reproduced this end to end through the
    product's own tool: a part authored as a bare ``Line`` builds, and
    ``compare_to_scan`` came back with ``part_to_scan_upper_bound_mm = 0.0``,
    ``part_samples = 0``, ``part_to_scan_bias = "over"``, no refusal — and
    ``part_to_scan_method = "kdtree_bound_exact_triangle"``, the name §6.3
    reserves for the EXACT route. §6.4 says the exact pair is ``None`` "exactly
    when the exact refinement was abandoned"; nothing was abandoned here, there
    was simply nothing to sample.

    Clause 37's invariant is *satisfied* by that record — a populated bound
    beside a ``None`` exact pair is a legal shape — which is why this test is
    written beside it rather than folded into it: the invariant can see a record
    whose three fields disagree, and it structurally cannot see a record whose
    three fields agree about a measurement that never happened. And it is the
    producer's defect, so closing it at either reader would leave the number
    manufactured: ``ScanFacts`` reads the bound through the *optional* reader
    (correctly — ``None`` there is a §6.4 statement), so a predicate written
    ``… .part_to_scan_upper_bound_mm <= tol`` PASSED on a comparison that
    sampled nothing.

    Both directions are covered. Direction A's empty case is unreachable through
    a build today — admission refuses an empty payload as ``mesh_empty`` (§1.7)
    — and is refused anyway, because ``geom`` is a pure service any caller may
    hand arrays to and "unreachable today" is not a property of this seam.
    """
    from build123d import Line

    line = cast("Any", Line((0.0, 0.0, 0.0), (30.0, 0.0, 0.0)))
    assert not line.faces()  # the fixture is what it claims to be: no surface

    with pytest.raises(ScanCompareError) as caught:
        scan_distance(line, meshes.box_vertices, meshes.box_faces)
    assert caught.value.reason == "scan_unmeasurable"
    assert "[scan_unmeasurable]" in caught.value.message
    assert "no faces" in caught.value.message

    from build123d import Box

    with pytest.raises(ScanCompareError) as empty_scan:
        scan_distance(
            cast("Any", Box(4.0, 4.0, 4.0)),
            np.zeros((0, 3), dtype=np.float64),
            np.zeros((0, 3), dtype=np.int64),
        )
    assert empty_scan.value.reason == "scan_unmeasurable"

    # And the code is in the closed §10 comparison vocabulary, so a caller can
    # branch on it rather than matching prose.
    assert "scan_unmeasurable" in SCAN_REFUSALS


def test_the_no_faces_refusal_survives_the_subprocess_boundary(meshes: Fixtures) -> None:
    """The bounded path keeps the refusal's identity, and does not stutter it.

    ``bounded_scan_distance`` re-raises the child's named refusal as a
    :class:`~hephaestus.core.scan_compare.ScanRefusal`, which derives its own
    ``[code]`` suffix — so this also pins that the derivation is idempotent: a
    refusal that already crossed a process boundary carries its name once.
    """
    from build123d import Line
    from hephaestus.core.scan_compare import ScanRefusal, bounded_scan_distance
    from hephaestus.geom.mesh import canonicalize_mesh, facts_to_json

    canonical = canonicalize_mesh("scan.stl", meshes.box_stl, "mm")
    with pytest.raises(ScanRefusal) as caught:
        bounded_scan_distance(
            cast("Any", Line((0.0, 0.0, 0.0), (30.0, 0.0, 0.0))),
            canonical.blob,
            facts_to_json(canonical),
            source="scan.stl",
        )
    assert caught.value.reason == "scan_unmeasurable"
    assert caught.value.message.count("[scan_unmeasurable]") == 1


# ==========================================================================
# clause 38 — scan_iou_unavailable


def test_asking_for_an_iou_against_a_scan_is_refused_by_name() -> None:
    with pytest.raises(ScanCompareError) as caught:
        scan_iou("scan:limb-l.stl")
    assert caught.value.reason == "scan_iou_unavailable"
    assert "scan_iou_unavailable" in caught.value.message


def test_the_checks_facade_names_the_refusal_instead_of_raising_attribute_error() -> None:
    """A predicate reaching for ``.iou`` gets a reason, not a stack trace."""
    from hephaestus.core.checks.facade import ScanFacts

    facts = ScanFacts.from_json(
        {
            "align": "as_posed",
            "scan_to_part_mean_mm": 1.0,
            "scan_to_part_max_mm": 2.0,
            "scan_to_part_min_mm": 0.5,
            "scan_samples": 4,
            "part_to_scan_method": SCAN_METHOD_EXACT,
            "part_samples": 4,
        }
    )
    for forbidden in ("iou", "chamfer_mm"):
        with pytest.raises(ValidationError) as caught:
            getattr(facts, forbidden)
        assert "scan_iou_unavailable" in caught.value.message
    # And an attribute that is simply not there is still an AttributeError:
    # the refusal names two fields, it does not swallow every typo.
    with pytest.raises(AttributeError):
        _ = facts.nonesuch  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    "missing", ["scan_to_part_mean_mm", "scan_to_part_max_mm", "scan_to_part_min_mm"]
)
def test_an_absent_required_field_refuses_instead_of_reading_as_a_zero(missing: str) -> None:
    """§6.4, §10 ``scan_unmeasurable``: absence is not a measurement of zero.

    The bench grader's own honesty finding, one layer up. ``_number`` defaults an
    absent field to ``0.0``, and a predicate written the way §7.3's example
    writes one — ``m.scan_diff(…).scan_to_part_max_mm <= 1.5`` — would then
    **pass** on a record that measured nothing at all. The other direction
    (``>= clearance``) fails safe under the same default, and that asymmetry is
    exactly what made the grader's version of this easy to miss: one of the two
    was wrong and neither looked it.

    It is latent on today's records — ``ScanDistance.to_json`` is
    ``dataclasses.asdict``, so these keys are always present, and a comparison
    that cannot measure raises rather than handing back a zeroed record. The
    guard is against the record shape moving underneath the predicate, which is
    the only way this ever fires and the only way it would ever be silent.

    The ``part_to_scan_*`` fields are deliberately NOT covered by it: ``None``
    there is the record's own §6.4 statement that the expensive direction did
    not resolve, and turning that into a refusal would delete the distinction
    the whole record exists to carry.
    """
    from hephaestus.core.checks.facade import ScanFacts

    complete: dict[str, Any] = {
        "align": "as_posed",
        "scan_to_part_mean_mm": 1.0,
        "scan_to_part_max_mm": 2.0,
        "scan_to_part_min_mm": 0.5,
        "scan_samples": 4,
        "part_to_scan_method": SCAN_METHOD_EXACT,
        "part_samples": 4,
    }
    # It reads fine when the field is there …
    assert ScanFacts.from_json(complete).scan_to_part_max_mm == 2.0
    # … and refuses by name when it is not, rather than answering 0.0.
    for absent in (
        {key: value for key, value in complete.items() if key != missing},
        {
            **complete,
            missing: None,
        },
    ):
        with pytest.raises(ValidationError) as caught:
            ScanFacts.from_json(absent)
        assert "scan_unmeasurable" in caught.value.message
        assert missing in caught.value.message
        assert "not a zero" in caught.value.message
    # The part→scan half keeps its optional reader: None there is a fact, and
    # ``complete`` above never carried one.
    assert ScanFacts.from_json(complete).part_to_scan_max_mm is None


def test_the_comparison_refusal_vocabulary_is_closed_and_disjoint() -> None:
    """§10: a third group, sharing no string with the other two."""
    from hephaestus.geom.mesh import MESH_OPERATION_REFUSALS, MESH_REFUSALS

    assert set(SCAN_REFUSALS) == {
        "scan_target_unsupported",
        "scan_principal_unavailable",
        "scan_iou_unavailable",
        "scan_neighborhood_overflow",
        "scan_timeout",
        # §10 lists ``scan_unmeasurable`` among the comparison codes and the
        # third repair pass is what made it one HERE: it was spent only by the
        # two readers (the bench grader, the CHECKS facade) while the producer
        # manufactured a 0.0 from zero samples. A code the producer cannot spend
        # is a code the producer will not spend.
        "scan_unmeasurable",
        # A tightening: §6.5 requires the refusal and does not spell the code
        # (recorded in "What 12C actually built", deviation 4).
        "declared_transform_not_rigid",
    }
    assert set(SCAN_REFUSALS).isdisjoint(MESH_REFUSALS)
    assert set(SCAN_REFUSALS).isdisjoint(MESH_OPERATION_REFUSALS)


# ==========================================================================
# clause 47 — Tier 2 determinism across two processes


_CHILD = """
import json, sys
import numpy as np
sys.path.insert(0, {tests!r})
from _g12c import make_fixtures
from build123d import Box
from hephaestus.geom.compare import scan_distance
import dataclasses

meshes = make_fixtures()
record = scan_distance(
    Box(44.0, 34.0, 24.0),
    meshes.box_vertices,
    meshes.box_faces,
    scan_canonical_hash="sha256:test",
    part_artifact_ref="artifact:test",
)
print(json.dumps(record.to_json(), sort_keys=True))
"""


def _in_a_fresh_interpreter() -> dict[str, Any]:
    """One ``ScanDistance``, computed in a process that shares nothing with this one."""
    source = _CHILD.format(tests=str(Path(__file__).resolve().parent))
    completed = subprocess.run(
        [sys.executable, "-c", source],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    return cast("dict[str, Any]", json.loads(completed.stdout.strip().splitlines()[-1]))


def test_a_scan_distance_is_identical_to_1e_9_across_two_processes(meshes: Fixtures) -> None:
    """Tier 2 (§8): identical to 1e-9, identical counts, identical METHOD strings.

    The method strings are asserted first and exactly, because a differing one is
    a *different measurement* and fails the clause rather than the number: an
    exact figure and an upper bound are not two readings of one quantity.
    """
    from build123d import Box

    here = scan_distance(
        cast("Any", Box(BOX_X + 4.0, BOX_Y + 4.0, BOX_Z + 4.0)),
        meshes.box_vertices,
        meshes.box_faces,
        scan_canonical_hash="sha256:test",
        part_artifact_ref="artifact:test",
    ).to_json()
    there = _in_a_fresh_interpreter()

    assert here["part_to_scan_method"] == there["part_to_scan_method"]
    assert here["part_to_scan_bias"] == there["part_to_scan_bias"]
    assert here["align"] == there["align"]
    assert here["scan_samples"] == there["scan_samples"]
    assert here["part_samples"] == there["part_samples"]
    for key, value in here.items():
        other = there[key]
        if isinstance(value, float) and isinstance(other, float):
            assert math.isclose(value, other, rel_tol=0.0, abs_tol=1e-9), key
        else:
            assert value == other, key


def test_a_differing_method_string_fails_the_clause_rather_than_the_number() -> None:
    """The negative control for the sentence above, stated as a test.

    Two records whose numbers agree to 1e-9 but whose methods differ are NOT
    equal for Tier 2 purposes, and the comparison must reject them — otherwise
    "identical method strings" is a sentence in a document rather than a rule.
    """
    exact = _record().to_json()
    bounded = _record(part_to_scan_method=SCAN_METHOD_BOUND, part_to_scan_bias="over").to_json()
    assert exact["part_to_scan_method"] != bounded["part_to_scan_method"]
    numeric = [
        key
        for key, value in exact.items()
        if isinstance(value, float) and math.isclose(value, cast("float", bounded[key]))
    ]
    assert numeric, "the two records agree numerically, which is the point"
    assert exact != bounded
