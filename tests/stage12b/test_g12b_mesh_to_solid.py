# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12B clauses 21-25: the sew, the mandatory validity gate, and the offset finding.

The whole stage turns on one measurement: OCCT's offset of a mesh-derived solid
returns a plausible-looking, catastrophically wrong answer that passes every
sanity signal the harness has. These clauses assert that the harness withholds
the operand rather than checking the result, that the two "is this closed"
predicates it owns are pinned as DIFFERENT predicates, that the sew is bounded,
and that the §4.5 repair question was decided by a number rather than an opinion.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, cast

import pytest
from _g12b import (
    Fixtures,
    canonical_arrays,
    evidence_world,
    read_evidence,
    write_evidence,
)
from _g12b_goldens import rebaselining
from hephaestus.core.mesh_solid import UNPINNED_IMAGE
from hephaestus.geom.mesh import MeshOperationError
from hephaestus.geom.mesh_solid import (
    MESH_REPAIR_AVAILABLE,
    MESH_SOLID_INTENTS,
    MeshDerivedSolid,
    gate_sewn_solid,
    sew_to_solid,
    shapefix_probe,
)

# ==========================================================================
# clause 21 — the sew runs, IsValid() is EVALUATED, the verdict is recorded


def test_clause21_sew_evaluates_the_validity_verdict_and_records_it(
    meshes: Fixtures,
) -> None:
    """The sew runs on a clean tessellated sphere and the analyzer verdict is
    MEASURED rather than presumed; a False verdict refuses ``mesh_solid_invalid``
    carrying the analyzer status list, the triangle count and the quality record.

    Both fixtures are asserted, because the two disagree and the disagreement is
    the finding: the tessellator's raw output sews to an INVALID solid, and the
    same bytes through §1.5 canonicalization sew to a VALID one. ``MESH_INGEST.md``
    §4.3 predicted the first and this stage's own pipeline produces the second.
    """
    raw_solid, raw_report = sew_to_solid(
        meshes.sphere_raw_vertices, meshes.sphere_raw_faces, source="sphere-raw"
    )
    assert raw_report.triangle_count == 2004
    assert raw_report.shell_count == 1
    # The verdict is recorded, not presumed — and on the unwelded reference mesh
    # it is False, exactly as §4.1 measured.
    assert raw_report.is_valid is False
    assert "wire:BRepCheck_SelfIntersectingWirex1" in raw_report.analyzer_statuses
    assert "face:BRepCheck_UnorientableShapex1" in raw_report.analyzer_statuses
    with pytest.raises(MeshOperationError) as raised:
        gate_sewn_solid(raw_solid, raw_report, source="sphere-raw", quality="Q-RECORD")
    refusal = raised.value
    assert refusal.reason == "mesh_solid_invalid"
    assert "2004 triangles" in str(refusal)
    assert "BRepCheck_SelfIntersectingWire" in str(refusal)
    assert "Q-RECORD" in str(refusal)

    vertices, faces, canonical = canonical_arrays(meshes.sphere_stl, path="sphere.stl")
    assert canonical.quality.welded_vertex_pairs == 5009
    canonical_solid, canonical_report = sew_to_solid(vertices, faces, source="sphere.stl")
    assert canonical_report.triangle_count == 2002
    assert canonical_report.vertex_count == 1003
    assert canonical_report.is_valid is True
    assert canonical_report.analyzer_statuses == ()
    # A valid verdict returns the solid unchanged — the gate withholds, it does
    # not transform.
    assert gate_sewn_solid(canonical_solid, canonical_report, source="sphere.stl") is (
        canonical_solid
    )
    # The polyhedron is inscribed, so its volume is systematically LOW against
    # the sphere it approximates; the record says "tessellated", and this is why.
    assert canonical_solid.volume == pytest.approx(33273.57, abs=0.5)


@pytest.mark.parametrize("fixture", ["holed_stl", "nonmanifold_fin_stl"])
def test_clause21_a_defective_scan_is_refused_by_name(meshes: Fixtures, fixture: str) -> None:
    """The refusal is real on defects the canonical weld cannot remove.

    A cube with one triangle deleted has a genuine hole; a fin has a genuine
    non-manifold edge. Neither is a duplicated-vertex artifact, so neither is
    welded away, and both are refused with the analyzer's own reason attached.
    """
    vertices, faces, _canonical = canonical_arrays(
        cast("bytes", getattr(meshes, fixture)), path=f"{fixture}.stl"
    )
    solid, report = sew_to_solid(vertices, faces, source=fixture)
    assert report.is_valid is False
    with pytest.raises(MeshOperationError) as raised:
        gate_sewn_solid(solid, report, source=fixture)
    assert raised.value.reason == "mesh_solid_invalid"
    # Never an empty "invalid for no reason": the walk names what OCCT found.
    assert report.analyzer_statuses != ()


def test_clause21_the_gate_is_not_optional_and_intent_is_a_closed_set() -> None:
    """``intent`` has exactly two members and no offset-shaped third one (§4.3)."""
    assert MESH_SOLID_INTENTS == ("measurement_target", "boolean_operand")
    assert not any("offset" in intent for intent in MESH_SOLID_INTENTS)


# ==========================================================================
# clause 22 — the §4.2 offset finding, pinned as a regression


def test_clause22_offset_is_unreachable_through_intent_and_the_gate_withholds_it(
    meshes: Fixtures,
) -> None:
    """The §4.2 finding is a regression pin, in both halves.

    First half: an offset of a mesh-derived solid is not reachable through
    ``mesh_to_solid``'s ``intent`` set — the set has two members, neither of
    them an offset, and adding one would fail this clause.

    Second half: the direct fixture. The unwelded reference sphere is exactly
    the solid the validity gate withholds, and offsetting *that* solid
    reproduces 279 faces, ``is_sealed=True``, ``genus=0`` and 0.003 mm³ where the
    answer is 44602 mm³. Every sanity signal the harness owns says the operation
    succeeded. That is what the gate is for, and it is asserted here rather than
    quoted, because a quoted measurement stops being a measurement.
    """
    from build123d import Solid
    from hephaestus.geom.metrics import genus, is_sealed
    from OCP.BRepOffset import BRepOffset_Mode  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepOffsetAPI import (  # pyright: ignore[reportAttributeAccessIssue]
        BRepOffsetAPI_MakeOffsetShape,
    )
    from OCP.GeomAbs import GeomAbs_JoinType  # pyright: ignore[reportAttributeAccessIssue]

    solid, report = sew_to_solid(
        meshes.sphere_raw_vertices, meshes.sphere_raw_faces, source="sphere-raw"
    )
    with pytest.raises(MeshOperationError):
        gate_sewn_solid(solid, report, source="sphere-raw")

    started = time.monotonic()
    maker = BRepOffsetAPI_MakeOffsetShape()
    maker.PerformByJoin(
        solid.wrapped,
        2.0,
        1e-4,
        BRepOffset_Mode.BRepOffset_Skin,
        False,
        False,
        GeomAbs_JoinType.GeomAbs_Intersection,
    )
    seconds = time.monotonic() - started
    shape = maker.Shape()
    offset_solid = cast("Any", Solid(shape))

    # Every green light OCCT and this harness can show, all of them wrong.
    assert maker.IsDone() is True
    assert shape.IsNull() is False
    assert is_sealed(offset_solid) is True
    assert genus(offset_solid) == 0
    assert len(offset_solid.faces()) == 279
    # …and the answer, which is not 44602.
    assert offset_solid.volume == pytest.approx(0.00302, abs=1e-4)
    assert offset_solid.volume < 1.0

    if rebaselining():
        write_evidence(
            "offset_finding.json",
            {
                "spec": "MESH_INGEST.md §4.2",
                "fixture": "tessellate(Sphere(20)) raw, 2004 triangles, 1027 vertices",
                "join_type": "GeomAbs_Intersection",
                "offset_mm": 2.0,
                "seconds": round(seconds, 2),
                "is_done": True,
                "is_null": False,
                "face_count": len(offset_solid.faces()),
                "is_sealed": True,
                "genus": 0,
                "volume_mm3": offset_solid.volume,
                "correct_volume_mm3": 44602.0,
            },
        )
    archived = read_evidence("offset_finding.json")
    assert archived["face_count"] == 279
    assert archived["volume_mm3"] < 1.0
    assert seconds > 0.0
    # …and it says which world it was recorded in. The sew goldens beside it
    # have carried this pair since 12B; the §4.2 evidence did not, so the
    # archived 30.83 s and 0.003 mm³ could not be attributed to a kernel.
    world = evidence_world("offset_finding.json")
    assert "7.9" in world["occt_version"]


# ==========================================================================
# clause 23 — is_sealed and IsValid() are DIFFERENT predicates


def test_clause23_is_sealed_and_is_valid_are_pinned_as_different_predicates(
    meshes: Fixtures,
) -> None:
    """On the §4.1 fixture ``geom.metrics.is_sealed`` is True while
    ``BRepCheck_Analyzer.IsValid()`` is False, so the two can never be silently
    conflated.

    This is asserted as a FACT about the kernel, not as a property of this
    stage's code: ``is_sealed`` is a combinatorial statement about shells and
    ``IsValid()`` is a geometric one about the surfaces underneath them. A
    future change that made one imply the other would fail here, which is the
    point — ``MeshAsset.watertight_at_weld_tol`` carries its tolerance in its
    name for the same reason.
    """
    from hephaestus.geom.metrics import genus, is_sealed

    solid, report = sew_to_solid(
        meshes.sphere_raw_vertices, meshes.sphere_raw_faces, source="sphere-raw"
    )
    assert is_sealed(solid) is True
    assert genus(solid) == 0
    assert report.is_valid is False
    assert is_sealed(solid) is not report.is_valid


# ==========================================================================
# clause 24 — the sew ceiling


def test_clause24_a_sew_that_cannot_finish_is_a_named_refusal_with_partial_facts(
    meshes: Fixtures, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A fault-injected slow sew returns ``mesh_sew_timeout`` carrying the quality
    record and the bbox, and the subprocess is dead afterwards.

    The facts it carries are precisely the ones the parent already had before
    the sew started (§3 quality, the canonical bbox), which is why the refusal
    can be honest about them: nothing here is recomputed from a solid that does
    not exist.
    """
    import os

    from _g12b_grind import PID_FILE_ENV, grinding_sew_child
    from hephaestus.core import mesh_solid as engine
    from hephaestus.geom.mesh import canonicalize_mesh

    canonical = canonicalize_mesh("cube.stl", meshes.cube_stl, "mm")
    pid_file = tmp_path_factory.mktemp("sewgrind") / "child.pid"
    monkeypatch.setattr(engine, "_sew_child", grinding_sew_child)
    monkeypatch.setenv(engine.MESH_SEW_TIMEOUT_ENV, "3.0")
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    started = time.monotonic()
    with pytest.raises(engine.MeshSewTimeout) as raised:
        engine.bounded_sew_to_solid(
            canonical.blob,
            source="cube.stl",
            quality=canonical.quality,
            bbox_mm=canonical.bbox_mm,
        )
    elapsed = time.monotonic() - started

    refusal = raised.value
    assert refusal.reason == "mesh_sew_timeout"
    assert refusal.timeout_s == 3.0
    assert refusal.lost == (engine.LOST_SEW, engine.LOST_VALIDITY)
    # Partial facts, and they are the REAL ones the canonicalizer measured.
    assert refusal.partial["quality"] == canonical.quality.to_json()
    assert refusal.partial["bbox_mm"] == [10.0, 10.0, 10.0]
    assert refusal.partial["source_path"] == "cube.stl"
    assert refusal.to_json()["status"] == "mesh_sew_timeout"
    assert "MESH_INGEST.md" in str(refusal)
    assert engine.MESH_SEW_TIMEOUT_ENV in str(refusal)
    # The refusal arrived on the ceiling's clock, not the grinder's 600 s one.
    assert elapsed < 60.0
    # …and the killed subprocess is dead, not orphaned behind the refusal.
    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
    with pytest.raises(OSError):
        for _ in range(50):
            os.kill(child_pid, 0)
            time.sleep(0.1)


def test_clause24_the_ceiling_is_env_overridable_and_defaults_are_declared() -> None:
    """The ``COMPARE.md`` §5 local-floor pattern, reused rather than reinvented."""
    from hephaestus.core import mesh_solid as engine

    assert engine.mesh_sew_timeout_s() == engine.MESH_SEW_TIMEOUT_S
    assert engine.MESH_SEW_TIMEOUT_ENV == "HEPHAESTUS_MESH_SEW_TIMEOUT_S"


def test_clause24_a_bounded_sew_returns_the_same_solid_the_direct_call_does(
    meshes: Fixtures,
) -> None:
    """The ceiling changes when the caller gives up, never what it receives."""
    from hephaestus.core.mesh_solid import bounded_sew_to_solid
    from hephaestus.geom.mesh import canonicalize_mesh

    canonical = canonicalize_mesh("cube.stl", meshes.cube_stl, "mm")
    vertices, faces, _c = canonical_arrays(meshes.cube_stl, path="cube.stl")
    direct, direct_report = sew_to_solid(vertices, faces, source="cube.stl")
    bounded, bounded_report = bounded_sew_to_solid(
        canonical.blob,
        source="cube.stl",
        quality=canonical.quality,
        bbox_mm=canonical.bbox_mm,
    )
    assert bounded_report.determinism_key() == direct_report.determinism_key()
    assert bounded.volume == pytest.approx(direct.volume, rel=1e-12)
    assert isinstance(bounded, MeshDerivedSolid)
    assert bounded.mesh_source == "cube.stl"


# ==========================================================================
# clause 25 — the §4.5 ShapeFix experiment, and the branch its outcome selects


def test_clause25_the_shapefix_experiment_runs_and_selects_its_disposition_branch(
    meshes: Fixtures,
) -> None:
    """§4.5 pre-committed to a disposition RULE and left the result unmeasured.
    This clause measures it, archives it, and asserts the branch it selects.

    Measured on the pinned kernel against the §4.1 reference solid — the
    unwelded sphere, the only one that needs repairing at all: all three fixers
    complete far inside the §4.1 ceiling, and **none of them reaches**
    ``IsValid()``. ``ShapeFix_Shape`` and ``ShapeFix_Solid`` additionally hand
    back a solid whose volume has flipped SIGN, which is the plausible-looking
    wrong answer this whole stage exists to refuse, produced by the thing that
    was supposed to be the repair.

    The rule's second branch therefore holds: ``mesh_to_solid`` keeps refusing,
    the socket workflow is §5.2 only, and ``repair=True`` does not exist — which
    the second half of this clause asserts against the actual signatures rather
    than against a docstring.

    **Where it was measured.** The clause says the experiment runs *on the
    pinned image*, and the archived evidence carries the stamp that says it did
    (``_g12b.evidence_world``). The live re-run below happens wherever this
    suite runs, which is the half that keeps the disposition true as the code
    moves; the stamp is the half that keeps it true about the kernel. Neither
    replaces the other, and the earlier draft of this clause had only the first.
    """
    from hephaestus.core.executor.namespace import ImportRegistry

    solid, report = sew_to_solid(
        meshes.sphere_raw_vertices, meshes.sphere_raw_faces, source="sphere-raw"
    )
    assert report.is_valid is False, "the repair experiment needs something to repair"

    outcomes = [
        shapefix_probe(solid, fixer=name)
        for name in ("ShapeFix_Shape", "ShapeFix_Solid", "ShapeFix_Shell")
    ]
    if rebaselining():
        write_evidence(
            "shapefix_experiment.json",
            {
                "spec": "MESH_INGEST.md §4.5",
                "fixture": "tessellate(Sphere(20)) raw, 2004 triangles, sewn, IsValid=False",
                "ceiling_s": 120.0,
                "outcomes": [outcome.to_json() for outcome in outcomes],
                "disposition": "second branch: no repair= argument",
            },
        )
    archived = read_evidence("shapefix_experiment.json")
    assert archived["disposition"] == "second branch: no repair= argument"

    # "runs ON THE PINNED IMAGE", asserted rather than promised. The experiment
    # above runs live wherever this suite runs — that is the half that keeps the
    # disposition honest as the code moves. This half is the clause's other
    # words: the ARCHIVED evidence must have been recorded inside a pinned
    # image, and the record's own stamp is what says so. A run on a developer
    # host cannot produce that stamp (`pinned_image.pinned_stamp` refuses), so
    # the two halves cannot be satisfied by the same convenient world.
    world = evidence_world("shapefix_experiment.json")
    assert world["image_digest"] != UNPINNED_IMAGE, (
        "the §4.5 experiment is archived from a run outside the pinned image; "
        "re-record it there (ci.yml: `stage12 measurements (pinned image)`)"
    )
    assert world["image_digest"].startswith("sha256:")
    assert "7.9" in world["occt_version"]
    # The archived outcomes are the same categorical result this run just
    # measured — recorded in the image, reproduced here.
    assert [entry["reached_valid"] for entry in archived["outcomes"]] == [False, False, False]

    # The measurement, asserted.
    assert [outcome.reached_valid for outcome in outcomes] == [False, False, False]
    assert all(outcome.seconds < 120.0 for outcome in outcomes)
    shape_fix = outcomes[0]
    assert shape_fix.volume_after_mm3 == pytest.approx(-shape_fix.volume_before_mm3, rel=1e-9)

    # The branch it selects, asserted against the code rather than the prose.
    assert MESH_REPAIR_AVAILABLE is False
    signature = inspect.signature(ImportRegistry.mesh_to_solid)
    assert "repair" not in signature.parameters
    assert set(signature.parameters) == {"self", "asset", "intent"}
    assert "repair" not in inspect.signature(sew_to_solid).parameters
    assert "repair" not in inspect.signature(gate_sewn_solid).parameters
