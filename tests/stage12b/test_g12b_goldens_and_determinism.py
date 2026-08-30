# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12B clauses 32-33: sew-golden provenance, and the Tier 3 determinism binding.

``MESH_INGEST.md`` §8 splits determinism into three tiers precisely so this
stage does not claim the one it cannot have. Tier 1 (the canonical blob and
every fact derived from it) is bit-reproducible and G12A binds it. Everything
downstream of ``BRepBuilderAPI_Sewing`` is **Tier 3**: not bit-reproducible, and
bound instead by the sewn counts and the ``BRepCheck_Analyzer`` verdict, inside
one pinned OCCT.

So these clauses assert the counts and the verdict, never the bytes — and they
assert the mechanism that makes a golden stop being a golden when the kernel
underneath it moves.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _g12b import EVIDENCE_DIR, Fixtures, canonical_arrays
from _g12b_goldens import (
    SewGoldenProvenanceError,
    load_sew_golden,
    rebaselining,
    write_sew_golden,
)
from hephaestus.core.mesh_solid import UNPINNED_IMAGE, image_digest, occt_version, sew_provenance
from hephaestus.geom.mesh_solid import sew_to_solid

REPO = Path(__file__).resolve().parents[2]

# ==========================================================================
# clause 32 — the (image digest, OCCT version) provenance sidecar


def test_clause32_a_sew_golden_carries_its_image_and_occt_pair(meshes: Fixtures) -> None:
    """The COMMITTED golden records counts and a verdict, stamped with its pair.

    It is compared, not rewritten. Regeneration happens only under
    ``HEPHAESTUS_REBASELINE_SEW_GOLDENS`` — the meta-test contract
    ``core/render/goldens.py`` already holds the renderer to — because a golden
    that rewrote itself on every run could never fail, which is the same as not
    having one.
    """
    vertices, faces, _canonical = canonical_arrays(meshes.sphere_stl, path="sphere.stl")
    canonical_solid, canonical_report = sew_to_solid(vertices, faces, source="sphere.stl")
    raw_solid, raw_report = sew_to_solid(
        meshes.sphere_raw_vertices, meshes.sphere_raw_faces, source="sphere-raw"
    )
    cube_vertices, cube_faces, _cube = canonical_arrays(meshes.cube_stl, path="cube.stl")
    _cube_solid, cube_report = sew_to_solid(cube_vertices, cube_faces, source="cube.stl")

    payload = {
        "sphere_canonical": canonical_report.determinism_key(),
        "sphere_raw": raw_report.determinism_key(),
        "cube": cube_report.determinism_key(),
    }
    if rebaselining():
        write_sew_golden("sew_counts", payload)
    assert load_sew_golden("sew_counts") == payload

    # Nothing about the SHAPE's bytes is in the golden — only counts, a verdict
    # and the analyzer's own status names. ``sew_seconds`` is absent too: a wall
    # clock is not a property of the geometry, and a golden that pinned one
    # would fail on a busy runner for a reason unrelated to the kernel.
    for record in payload.values():
        assert set(record) == {
            "triangle_count",
            "face_count",
            "vertex_count",
            "shell_count",
            "is_valid",
            "analyzer_statuses",
        }
        assert not any(isinstance(value, bytes) for value in record.values())
    # …and the counts are the geometry-bearing half, so they are real facts.
    assert payload["sphere_canonical"]["face_count"] == 2002
    assert payload["sphere_raw"]["face_count"] == 2004
    assert payload["cube"]["face_count"] == 12
    # The solids differ in the one way that matters, and the golden records it.
    assert payload["sphere_canonical"]["is_valid"] is True
    assert payload["sphere_raw"]["is_valid"] is False
    assert canonical_solid.volume > 0.0 and raw_solid.volume > 0.0


@pytest.mark.parametrize("field", ["image_digest", "occt_version"])
def test_clause32_a_mismatched_pair_invalidates_the_golden_rather_than_comparing(
    meshes: Fixtures, field: str, tmp_path: Path
) -> None:
    """A mismatch on EITHER half refuses. It does not compare and report a diff.

    Comparing under a moved kernel would produce a difference that says nothing
    about the code under test, and a reader looking at "face_count 2002 != 2004"
    has no way to tell that from a regression. The refusal names the fix: a
    re-baseline PR carrying the bump.
    """
    vertices, faces, _canonical = canonical_arrays(meshes.cube_stl, path="cube.stl")
    _solid, report = sew_to_solid(vertices, faces, source="cube.stl")
    write_sew_golden("probe", {"cube": report.determinism_key()}, directory=tmp_path)

    # It compares fine against its own pair …
    assert load_sew_golden("probe", directory=tmp_path) == {"cube": report.determinism_key()}

    # … and refuses against a moved one, on either half of the pair.
    moved = dict(sew_provenance())
    moved[field] = moved[field] + "-moved"
    with pytest.raises(SewGoldenProvenanceError) as raised:
        load_sew_golden("probe", provenance=moved, directory=tmp_path)
    assert field in str(raised.value)
    assert "re-baseline" in str(raised.value).lower()
    assert "not compared" in str(raised.value)


def test_clause32_the_pair_is_measured_not_declared() -> None:
    """Both halves come from the environment, and neither is silently blank.

    ``OCP.Standard`` exports no ``Standard_Version`` in this binding, so the
    OCCT version is read from the wheel that shipped the kernel — a measurement,
    not a constant somebody kept up to date. The image digest is
    :data:`UNPINNED_IMAGE` outside a pinned image, which is a stated fact rather
    than an empty string that could be mistaken for one.
    """
    provenance = sew_provenance()
    assert set(provenance) == {"image_digest", "occt_version"}
    assert provenance["occt_version"] == occt_version()
    assert provenance["image_digest"] == image_digest()
    assert provenance["occt_version"] != ""
    assert provenance["image_digest"] != ""
    # 7.9.x is the pinned kernel this stage's every measurement was taken on.
    assert "7.9" in provenance["occt_version"] or provenance["occt_version"] == "unknown"
    assert image_digest() == UNPINNED_IMAGE or image_digest().startswith("sha256:")


# ==========================================================================
# clause 33 — Tier 3: counts and verdict identical across two processes


SEW_CHILD = """
from _g12b import canonical_arrays, make_fixtures
from hephaestus.geom.mesh_solid import sew_to_solid

fixtures = make_fixtures()
out = {}
vertices, faces, _canonical = canonical_arrays(fixtures.sphere_stl, path="sphere.stl")
_solid, report = sew_to_solid(vertices, faces, source="sphere.stl")
out["sphere_canonical"] = report.determinism_key()
_raw_solid, raw_report = sew_to_solid(
    fixtures.sphere_raw_vertices, fixtures.sphere_raw_faces, source="sphere-raw"
)
out["sphere_raw"] = raw_report.determinism_key()
print(json.dumps(out, sort_keys=True))
"""


def test_clause33_sewn_counts_and_the_validity_verdict_are_stable_across_processes() -> None:
    """Face and vertex counts and the ``IsValid()`` verdict, identical in two
    processes — the counts and the verdict, and deliberately NOT the bytes.

    This is the whole of what §8 Tier 3 claims, asserted at exactly that
    strength. A clause that pinned the sewn BRep would be claiming a stability
    OCCT does not offer and would go flaky on the next kernel bump for a reason
    unrelated to any change here; a clause that pinned nothing would let a
    non-deterministic sew through unnoticed.
    """
    from _g12b_subprocess import run_json

    first = run_json(SEW_CHILD)
    second = run_json(SEW_CHILD)
    assert first == second

    for form in ("sphere_canonical", "sphere_raw"):
        record = first[form]
        assert set(record) == {
            "triangle_count",
            "face_count",
            "vertex_count",
            "shell_count",
            "is_valid",
            "analyzer_statuses",
        }
        assert record["shell_count"] == 1
    assert first["sphere_canonical"]["is_valid"] is True
    assert first["sphere_raw"]["is_valid"] is False


def test_clause33_the_two_process_binding_was_taken_in_the_pinned_image() -> None:
    """ "…in the pinned image", as a recorded measurement rather than a promise.

    The clause above spawns two interpreters wherever this suite runs, which is
    the binding itself. This clause is the other half of the sentence: the
    archived record was produced by that same pair of children **inside the
    pinned image** (``scripts/stage12_pinned_measure.py --write``, which refuses
    to write outside one), and it carries both children's projections rather
    than one and a claim — so a reader can see the equality instead of taking
    it.

    What it deliberately does NOT assert is that the image's counts equal this
    machine's. That would be a Tier 1 claim about a Tier 3 quantity: §8 says a
    sew is bound only *inside* one (image, OCCT) pair, and the sew goldens'
    provenance refusal exists precisely so a cross-world comparison never
    happens by accident. The two worlds are tied together by the base-image
    digest instead, which ``load_pinned`` re-reads from
    ``docker/ci/Dockerfile`` — so a base bump invalidates this record rather
    than silently ageing it.
    """
    from hephaestus.testing.pinned_image import load_pinned

    record = load_pinned(EVIDENCE_DIR, REPO)
    two_process = record.measurements["sew_two_process"]
    assert set(two_process) == {"first", "second"}
    assert two_process["first"] == two_process["second"], (
        "the sew disagreed with itself across two processes inside the pinned image"
    )
    for form in ("sphere_canonical", "sphere_raw"):
        entry = two_process["first"][form]
        assert set(entry) == {
            "triangle_count",
            "face_count",
            "vertex_count",
            "shell_count",
            "is_valid",
            "analyzer_statuses",
        }, "counts and verdict, never bytes"
    assert two_process["first"]["sphere_canonical"]["is_valid"] is True
    assert two_process["first"]["sphere_raw"]["is_valid"] is False
    assert record.image_digest != UNPINNED_IMAGE
    assert "7.9" in record.occt_version


def test_clause33_the_committed_golden_matches_this_process(meshes: Fixtures) -> None:
    """The recorded golden and a live sew agree, under a matching pair.

    Ordered after the recording clause on purpose: what this asserts is that the
    golden survives a *different* process than the one that wrote it, which is
    the only thing a committed golden is for.
    """
    vertices, faces, _canonical = canonical_arrays(meshes.sphere_stl, path="sphere.stl")
    _solid, report = sew_to_solid(vertices, faces, source="sphere.stl")
    golden = load_sew_golden("sew_counts")
    assert golden["sphere_canonical"] == report.determinism_key()
