# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""G12A clauses 5-9: two hashes, staleness, determinism, staged identity, the sidecar.

These five clauses are the load-bearing half of the stage, and clause 8 is the
one the spec says outright "fails against the unmodified ``staged_filename``,
which is the point of writing it". The failure it catches is not exotic:
``staged_filename`` was a pure function of the content hash and ``stage_import``
returns the existing file when the name exists, so two byte-identical scans
declared ``units="mm"`` and ``units="in"`` would have resolved to ONE staged
blob, the second declaration would have silently received the first's geometry,
and the build would have been wrong by a factor of 25.4 with nothing recording
it.

Clause 5's shape carries the §1.4 two-hash design: ``input_hashes.imports`` is
the RAW bytes and stays the invalidation key, while ``mesh_canonical_hash`` is
geometry identity and never substitutes for it. A re-export that only changed a
comment banner is therefore a NEW build whose geometry is provably the same —
and the harness can say exactly that, which is the whole reason there are two.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from _g12a import (
    MeshFixtures,
    build_ok,
    cube_faces,
    cube_vertices,
    export_mesh,
    install_import,
    scan_facts,
    write_script,
)
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core.executor.imports import stage_import, staged_filename
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.publication import FrozenBuildInputs, Publisher
from hephaestus.geom.mesh import (
    MeshReadError,
    canonicalize_mesh,
    facts_to_json,
    mesh_asset_from_staged,
)
from hephaestus.testing.tools_fixture import Project

from opstore import sha256_bytes

MM_TO_IN = 25.4

#: The fixed 32-byte canonical header (§1.5 step 7); vertex bytes start after it.
_BLOB_HEADER_SIZE = 32

#: A part whose geometry is a FUNCTION of the scan it imported, so the two
#: revalidation clauses below can tell "the frozen bytes" from "whatever is on
#: disk now" by measuring the part rather than by trusting a hash.
SCAN_SRC = (
    'scan = import_mesh("limb.ply", units="mm")\npart.geometry = Box(scan.bbox_mm[0], 2.0, 2.0)\n'
)


def _current_imports(project: Project, part: str) -> dict[str, str]:
    current = project.cad.current_build(part)
    assert current is not None
    return dict(current.input_hashes.imports)


# ==========================================================================
# clause 5: the raw hash invalidates; the canonical hash explains


def test_input_hashes_carry_the_raw_mesh_bytes(project: Project, meshes: MeshFixtures) -> None:
    """Nothing is normalized before hashing an input (§1.4), mesh included."""
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(
        project,
        "scanned",
        'scan = import_mesh("limb.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    build_ok(project, "scanned")

    assert _current_imports(project, "scanned") == {
        "limb.ply": sha256_bytes(meshes.cube_ply_binary)
    }


def test_a_changed_unit_is_a_changed_build_on_identical_bytes(
    project: Project, meshes: MeshFixtures
) -> None:
    """Same file, different declared unit ⇒ different geometry, and it shows.

    The input hash is the same — the file did not change — and the *geometry*
    is different by 25.4, which is precisely why the unit had to join the staged
    identity rather than riding along as metadata.
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(
        project,
        "in_mm",
        'scan = import_mesh("limb.ply", units="mm")\n'
        "part.geometry = Box(scan.bbox_mm[0], scan.bbox_mm[1], scan.bbox_mm[2])\n",
    )
    write_script(
        project,
        "in_inches",
        'scan = import_mesh("limb.ply", units="in")\n'
        "part.geometry = Box(scan.bbox_mm[0], scan.bbox_mm[1], scan.bbox_mm[2])\n",
    )
    build_ok(project, "in_mm")
    build_ok(project, "in_inches")

    assert _current_imports(project, "in_mm") == _current_imports(project, "in_inches")
    mm_build = project.cad.current_build("in_mm")
    inch_build = project.cad.current_build("in_inches")
    assert mm_build is not None and inch_build is not None
    assert mm_build.metrics is not None and inch_build.metrics is not None
    assert inch_build.metrics.bbox_mm[0] == pytest.approx(
        mm_build.metrics.bbox_mm[0] * MM_TO_IN, rel=1e-9
    )


def test_a_changed_banner_is_a_new_build_with_the_same_geometry(
    meshes: MeshFixtures,
) -> None:
    """The two-hash design, stated as the only test that can show it.

    A re-exported scan with a new comment line has different bytes and the same
    triangles. The input hash MUST move (the freeze runs before the parse, so
    the harness cannot know the re-export is geometrically identical), and the
    canonical hash MUST NOT — that pair is what lets a build say "the file
    changed, the geometry did not" instead of guessing.
    """
    original = meshes.cube_ply_ascii
    rebanded = original.replace(b"format ascii 1.0\n", b"format ascii 1.0\ncomment re-exported\n")

    assert sha256_bytes(original) != sha256_bytes(rebanded)
    assert (
        scan_facts("limb.ply", original, "mm").canonical_hash
        == scan_facts("limb.ply", rebanded, "mm").canonical_hash
    )


def test_the_canonical_hash_reaches_the_build_record(
    project: Project, meshes: MeshFixtures
) -> None:
    """§12 item 15: a second hash the record has never carried, now carried."""
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(
        project,
        "scanned",
        'scan = import_mesh("limb.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    build_ok(project, "scanned")

    bundle = Publisher(project.layout, project.store).current_bundle("scanned")
    assert bundle is not None
    hashes = cast("dict[str, Any]", bundle["mesh_canonical_hashes"])
    expected = scan_facts("limb.ply", meshes.cube_ply_binary, "mm").canonical_hash
    assert list(hashes.values()) == [expected]
    # Beside the first hash, never in place of it: the raw-bytes hash is still
    # what the build's identity is keyed on.
    result = cast("dict[str, Any]", bundle["result"])
    assert result["input_hashes"]["imports"]["limb.ply"] == sha256_bytes(meshes.cube_ply_binary)


# ==========================================================================
# clause 6: staleness and revalidation, on the new kind


def test_a_replaced_mesh_makes_its_consumer_stale(project: Project, meshes: MeshFixtures) -> None:
    """The G8A invalidation clauses re-run on a mesh import (INGEST.md §1)."""
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(
        project,
        "scanned",
        'scan = import_mesh("limb.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    build_ok(project, "scanned")
    Publisher(project.layout, project.store).sync_import_state()

    bigger = export_mesh(cube_vertices(20.0), cube_faces(), "ply")
    install_import(project.root, "limb.ply", bigger)
    report = Publisher(project.layout, project.store).sync_import_state()

    assert report is not None
    assert "scanned" in set(report.stale)


def _run_from_frozen(inputs: FrozenBuildInputs, out_dir: Path) -> UnpublishedBuild:
    """One build straight from frozen inputs — the CLI's own request shape.

    The two clauses below drive the publisher directly because "the file changed
    between freeze and publish" has no tool call that expresses it: it is a race,
    and the gate has to be able to lose it deliberately. This is G8A's own
    helper, re-run on the new kind rather than re-imagined for it — the payload
    it hands over now carries the declared unit, which is the only difference a
    mesh makes.
    """
    request = BuildRequest(
        part=inputs.part,
        script=inputs.script,
        globals_source=inputs.globals_source,
        imports=dict(inputs.imports),
        import_errors=dict(inputs.import_errors),
    )
    return run_build(request, backend=UnsafeLocalBackend(), out_dir=out_dir)


def test_a_mesh_replaced_mid_build_loses_the_current_flip(
    project: Project, meshes: MeshFixtures, tmp_path: Path
) -> None:
    """Revalidation refuses the flip for a scan exactly as it does for a STEP.

    This is the half of clause 6 that a staleness test cannot reach. Staleness
    is noticed *after* a build is current; revalidation is the check that stops
    a build becoming current at all when its inputs moved underneath it. Without
    it, an operator who re-exported a limb scan while a socket was building
    would get a current build attributed to bytes that no longer exist anywhere
    — the record would name a scan whose geometry the harness could not produce
    again, which is exactly what content-addressed inputs are for.
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(project, "scanned", SCAN_SRC)
    pub = Publisher(project.layout, project.store)
    frozen = pub.freeze_inputs("scanned")
    build = _run_from_frozen(frozen, tmp_path / "out")
    assert build.result.status == "ok", build.result.error

    # The operator re-exports the scan while the build is in flight.
    install_import(project.root, "limb.ply", export_mesh(cube_vertices(20.0), cube_faces(), "ply"))
    outcome = pub.publish_build(build, op_id="g12a-raced")

    assert outcome.kind == "raced"
    assert any(detail.startswith("imports[limb.ply]") for detail in outcome.details), (
        outcome.details
    )
    # Nothing became current, so the model has nothing to export either.
    assert project.cad.current_build("scanned") is None
    with pytest.raises(DispatchError) as excinfo:
        project.call("export_part", {"name": "scanned", "format": "step"})
    assert excinfo.value.reason == "invalid_part"


def test_a_retried_mesh_publication_replays_the_original_bytes(
    project: Project, meshes: MeshFixtures, tmp_path: Path
) -> None:
    """The §8 retry contract, with the scan in the frozen input set.

    Two facts in one clause, and the first is the one a mesh makes newly
    interesting: a build run from frozen inputs uses the ORIGINAL bytes, so the
    geometry it measures is the scan that was frozen and not whatever is on disk
    now — asserted through the bbox, which is 10 mm for the frozen cube and
    would be 20 mm for the replacement. Then the retry itself: publishing the
    same build twice on one op id replays the first record rather than
    re-flipping.
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(project, "scanned", SCAN_SRC)
    pub = Publisher(project.layout, project.store)
    frozen = pub.freeze_inputs("scanned")
    bigger = export_mesh(cube_vertices(20.0), cube_faces(), "ply")
    install_import(project.root, "limb.ply", bigger)

    build = _run_from_frozen(frozen, tmp_path / "out")

    assert build.result.status == "ok", build.result.error
    metrics = build.result.metrics
    assert metrics is not None
    assert metrics.bbox_mm[0] == pytest.approx(10.0, abs=1e-6), "the frozen scan, not the new one"

    # Put the frozen file back so revalidation passes, then publish twice on the
    # same op id: the second call replays the first record rather than re-flipping.
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    first = pub.publish_build(build, op_id="g12a-retry")
    again = pub.publish_build(build, op_id="g12a-retry")

    assert first.kind == "current"
    assert again.replayed
    assert again.record_blob == first.record_blob
    current = project.cad.current_build("scanned")
    assert current is not None
    assert current.input_hashes.imports == build.result.input_hashes.imports
    assert current.input_hashes.imports["limb.ply"] == sha256_bytes(meshes.cube_ply_binary)


def test_an_unchanged_mesh_tree_moves_nothing(project: Project, meshes: MeshFixtures) -> None:
    """An unchanged tree must not bump the audit revision — the G8A rule holds."""
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(
        project,
        "scanned",
        'scan = import_mesh("limb.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    build_ok(project, "scanned")
    # ``build_part`` syncs on its way through, so the tree is already current
    # here — which is the state the clause is about: repeated syncs over an
    # unchanged tree must all report nothing.
    assert Publisher(project.layout, project.store).sync_import_state() is None
    assert Publisher(project.layout, project.store).sync_import_state() is None


# ==========================================================================
# clause 7: canonicalization determinism


_CANONICAL_PROGRAM = textwrap.dedent(
    """
    import base64, hashlib, sys
    from hephaestus.geom.mesh import canonicalize_mesh
    data = base64.b64decode(sys.argv[1])
    blob = canonicalize_mesh("limb.ply", data, sys.argv[2]).blob
    print(hashlib.sha256(blob).hexdigest())
    """
)


def test_the_canonical_blob_is_identical_in_two_separate_processes(
    meshes: MeshFixtures,
) -> None:
    """Tier 1 of §8: bit-reproducible, and gated as such.

    Two processes, not two calls: an in-process repeat would measure the
    session's caches rather than the pipeline's determinism.
    """
    import base64

    encoded = base64.b64encode(meshes.cube_ply_binary).decode("ascii")
    digests = set()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", _CANONICAL_PROGRAM, encoded, "mm"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        digests.add(result.stdout.strip())
    assert len(digests) == 1


def test_a_permuted_file_canonicalizes_to_the_identical_blob(
    meshes: MeshFixtures,
) -> None:
    """The file's own vertex and triangle order is GONE, deliberately (§1.5 step 6).

    That is the honest cost of ``process=False``: canonical order is a
    documented function of the geometry, so a re-export that renumbered
    everything produces the same blob — and §2.4 draws the consequence, that
    mesh topology carries no identity a ``tag()`` could name.
    """
    vertices, faces = cube_vertices(), cube_faces()
    rng = np.random.default_rng(12345)
    permutation = rng.permutation(len(vertices))
    inverse = np.empty_like(permutation)
    inverse[permutation] = np.arange(len(vertices))
    shuffled_faces = inverse[faces][rng.permutation(len(faces))]

    original = canonicalize_mesh("a.ply", export_mesh(vertices, faces, "ply"), "mm")
    permuted = canonicalize_mesh(
        "b.ply", export_mesh(vertices[permutation], shuffled_faces, "ply"), "mm"
    )

    assert original.blob == permuted.blob


def test_one_moved_vertex_changes_the_canonical_blob(meshes: MeshFixtures) -> None:
    """Beyond the weld tolerance, a moved vertex is different geometry."""
    vertices, faces = cube_vertices(), cube_faces()
    moved = vertices.copy()
    moved[0, 0] += 1e-3  # three orders of magnitude past MESH_WELD_TOL_MM

    assert (
        canonicalize_mesh("a.ply", export_mesh(vertices, faces, "ply"), "mm").blob
        != canonicalize_mesh("b.ply", export_mesh(moved, faces, "ply"), "mm").blob
    )


# ==========================================================================
# clause 8: unit scaling and staged identity, in ONE build


UNIT_SCRIPT = """mm = import_mesh("limb.ply", units="mm")
cm = import_mesh("limb.ply", units="cm")
m = import_mesh("limb.ply", units="m")
inch = import_mesh("limb.ply", units="in")
again = import_mesh("limb.ply", units="mm")
part.geometry = Box(mm.bbox_mm[0], mm.bbox_mm[1], mm.bbox_mm[2])
for asset in (mm, cm, m, inch):
    print(asset.bbox_mm[0], asset.bbox_mm[1], asset.bbox_mm[2])
print(mm.canonical_hash == again.canonical_hash)
print(len({mm.canonical_hash, cm.canonical_hash, m.canonical_hash, inch.canonical_hash}))
"""


def test_four_units_of_one_byte_stream_never_share_a_staged_mesh(
    project: Project, meshes: MeshFixtures, tmp_path: Path
) -> None:
    """The finding-1 clause: one file, four units, one build, four staged blobs.

    Against the unmodified, unit-blind ``staged_filename`` all four resolve to
    one name and the last three silently receive the first's geometry. Here they
    are asserted pairwise distinct, the four bboxes stand in the exact ratios
    1 : 10 : 1000 : 25.4, and a fifth declaration repeating an earlier
    (bytes, unit) pair resolves back to the SAME staged file — reuse preserved,
    collision impossible.

    **The ratios are read out of the build's own four assets**, not recomputed
    in this process. The third repair pass's verifier is why: the clause says
    "in one script and therefore one build … the four resulting
    ``MeshAsset.bbox_mm`` triples", and a version that asserted the ratios from
    ``scan_facts()`` recomputed here was asserting that the *canonicalizer*
    scales — which nobody doubted — while the thing the clause exists to catch
    is four declarations in one build **sharing** a staged blob. So the script
    prints all three components of all four triples from inside the sandbox,
    and this reads them back from the worker's captured stdout. Recomputing them
    here would pass on a build in which all four assets were the same object.
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(project, "four_units", UNIT_SCRIPT)

    build_ok(project, "four_units")

    content_hash = "sha256:" + sha256_bytes(meshes.cube_ply_binary).removeprefix("sha256:")
    names = {
        unit: staged_filename(content_hash, kind="mesh", units=unit)
        for unit in ("mm", "cm", "m", "in")
    }
    assert len(set(names.values())) == 4, names
    # And the fifth declaration is the first one's file, not a fifth artifact.
    assert names["mm"] == staged_filename(content_hash, kind="mesh", units="mm")

    # The build's own output, re-run from its frozen inputs so the worker's
    # captured stdout is reachable: the tool response carries the published
    # record, and the four assets live only inside the script that made them.
    inputs = Publisher(project.layout, project.store).freeze_inputs("four_units")
    build = _run_from_frozen(inputs, tmp_path)
    assert build.result.status == "ok", build.result.error
    printed = str(cast("dict[str, Any]", build.worker_result).get("stdout", "")).splitlines()
    assert len(printed) == 6, printed

    triples = [tuple(float(value) for value in line.split()) for line in printed[:4]]
    assert all(len(triple) == 3 for triple in triples)
    # The fixture is a 10 mm cube, so every component of every triple is the
    # edge times that declaration's factor: the ratios are asserted over all
    # three axes, because a scale applied on one axis only would satisfy a
    # single-component check.
    edge = 10.0
    for triple, factor in zip(triples, (1.0, 10.0, 1000.0, 25.4), strict=True):
        for component in triple:
            assert component == pytest.approx(edge * factor, rel=1e-12), (triples, factor)
    # And the ratios between the four, stated as ratios rather than as absolutes,
    # so the clause binds even if the fixture's edge ever changes.
    base = triples[0][0]
    assert [t[0] / base for t in triples] == pytest.approx([1.0, 10.0, 1000.0, 25.4], rel=1e-12)

    # The fifth declaration is the first's geometry (reuse), and the four
    # declarations are four DIFFERENT staged geometries (no collision) —
    # measured by the assets the build itself held, not by the filename formula.
    assert printed[4] == "True"
    assert printed[5] == "4"


def test_step_staged_names_do_not_move(tmp_path: Path) -> None:
    """The STEP branch is the EXISTING expression, not a hash of the hash.

    A formula that re-hashed would silently rename every staged STEP artifact in
    the tree while claiming to change nothing, so the STEP name is pinned to the
    content hash's own hex prefix.
    """
    content_hash = "sha256:" + "ab" * 32
    assert staged_filename(content_hash) == ("ab" * 32)[:32] + ".brep"
    assert staged_filename(content_hash, kind="step") == ("ab" * 32)[:32] + ".brep"


def test_staging_the_same_bytes_and_unit_twice_reuses_one_file(
    tmp_path: Path, meshes: MeshFixtures
) -> None:
    data = meshes.cube_ply_binary
    content_hash = sha256_bytes(data)
    first = stage_import(
        data, path="limb.ply", content_hash=content_hash, out_dir=tmp_path, kind="mesh", units="mm"
    )
    second = stage_import(
        data, path="limb.ply", content_hash=content_hash, out_dir=tmp_path, kind="mesh", units="mm"
    )
    inches = stage_import(
        data, path="limb.ply", content_hash=content_hash, out_dir=tmp_path, kind="mesh", units="in"
    )

    assert first == second
    assert first != inches
    assert first.read_bytes() != inches.read_bytes()
    # Staged read-only, exactly as a STEP import is.
    assert first.stat().st_mode & 0o222 == 0


# ==========================================================================
# clause 9: pre-canonical counts survive the sandbox boundary, via the sidecar


def test_welded_pairs_and_as_read_count_come_from_the_sidecar(
    meshes: MeshFixtures,
) -> None:
    """A file with 36 duplicated corners welds to 8 vertices: 28 merges, recorded.

    ``vertex_count_as_read`` minus ``vertex_count`` is exactly
    ``welded_vertex_pairs`` — arithmetic, not a golden — and none of the three is
    recoverable from the post-weld blob, which is why the sidecar exists.
    """
    asset = scan_facts("limb.stl", meshes.duplicated_vertices_stl, "mm")
    assert asset.vertex_count_as_read == 36
    assert asset.vertex_count == 8
    assert asset.quality.welded_vertex_pairs == 28
    assert asset.vertex_count_as_read - asset.vertex_count == asset.quality.welded_vertex_pairs


def test_dropped_degenerates_are_recorded_never_absorbed(meshes: MeshFixtures) -> None:
    """One zero-area triangle beside the cube's twelve: dropped, and counted."""
    asset = scan_facts("limb.ply", meshes.degenerate_ply, "mm")
    assert asset.triangle_count == 12
    assert asset.quality.degenerate_triangles_dropped == 1


def test_mutating_the_sidecar_moves_the_facts_and_not_the_hash(
    tmp_path: Path, meshes: MeshFixtures
) -> None:
    """The separation, pinned in BOTH directions (§1.5.2).

    The hash names geometry; the sidecar reports history. Edit the sidecar and
    the reported history changes while the identity does not; edit the blob and
    the identity moves. If either direction were the other way round, a
    normalizer would be deciding what counts as the same geometry.
    """
    canonical = canonicalize_mesh("limb.stl", meshes.duplicated_vertices_stl, "mm")
    facts = json.loads(facts_to_json(canonical))
    facts["vertex_count_as_read"] = 999
    facts["quality"]["welded_vertex_pairs"] = 991
    edited = json.dumps(facts, sort_keys=True)

    honest = mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path="limb.ply", units="mm"
    )
    tampered = mesh_asset_from_staged(canonical.blob, edited, source_path="limb.stl", units="mm")

    assert tampered.vertex_count_as_read == 999
    assert tampered.quality.welded_vertex_pairs == 991
    assert tampered.canonical_hash == honest.canonical_hash

    # The other direction: touch the geometry and the hash moves. The byte
    # chosen is a VERTEX coordinate's low bit, not a triangle index: flipping an
    # index bit corrupts the blob into something the deserializer refuses by
    # name (``mesh_unreadable``), which is correct behaviour but a different
    # assertion than the one this clause is making.
    mutated = bytearray(canonical.blob)
    mutated[_BLOB_HEADER_SIZE] ^= 0x01
    moved = mesh_asset_from_staged(
        bytes(mutated), facts_to_json(canonical), source_path="limb.stl", units="mm"
    )
    assert moved.canonical_hash != honest.canonical_hash


def test_a_corrupt_canonical_blob_is_refused_by_name(meshes: MeshFixtures) -> None:
    """An index outside the vertex array is ``mesh_unreadable``, not an IndexError.

    The blob is staged read-only, so this fires on real corruption — and that is
    exactly when an unnamed crash out of numpy would be least useful.
    """
    canonical = canonicalize_mesh("limb.ply", meshes.cube_ply_binary, "mm")
    mutated = bytearray(canonical.blob)
    mutated[-1] ^= 0x7F
    with pytest.raises(MeshReadError) as excinfo:
        mesh_asset_from_staged(
            bytes(mutated), facts_to_json(canonical), source_path="limb.ply", units="mm"
        )
    assert excinfo.value.reason == "mesh_unreadable"


def test_recomputing_the_pre_canonical_facts_from_the_blob_is_impossible(
    meshes: MeshFixtures,
) -> None:
    """Asserted by fixture, because "unimplementable" is a claim that needs proof.

    Two files differing ONLY in duplicated vertices produce the identical
    canonical blob. A worker-side attempt to recompute ``welded_vertex_pairs``
    from that blob therefore cannot distinguish 28 merges from 0 — the number is
    gone, and no amount of care inside the sandbox brings it back.
    """
    welded = canonicalize_mesh("welded.stl", meshes.duplicated_vertices_stl, "mm")
    already = canonicalize_mesh("already.ply", meshes.cube_ply_binary, "mm")

    assert welded.blob == already.blob
    assert welded.quality.welded_vertex_pairs == 28
    assert already.quality.welded_vertex_pairs == 0


def test_the_sidecar_is_staged_read_only_beside_the_blob(
    tmp_path: Path, meshes: MeshFixtures
) -> None:
    staged = stage_import(
        meshes.cube_ply_binary,
        path="limb.ply",
        content_hash=sha256_bytes(meshes.cube_ply_binary),
        out_dir=tmp_path,
        kind="mesh",
        units="mm",
    )
    sidecar = staged.with_name(staged.name + ".facts")
    assert sidecar.is_file()
    assert sidecar.stat().st_mode & 0o222 == 0
    # Byte-reproducible: sorted keys and round-trippable floats, so the sidecar
    # is a cache of the parent's computation and not a second source of truth.
    assert sidecar.read_text(encoding="utf-8") == json.dumps(
        json.loads(sidecar.read_text(encoding="utf-8")), sort_keys=True
    )


def test_the_sidecar_is_not_part_of_the_canonical_hash(meshes: MeshFixtures) -> None:
    """Stated once more as a direct assertion over the hash's own input."""
    import hashlib

    canonical = canonicalize_mesh("limb.ply", meshes.cube_ply_binary, "mm")
    asset = mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path="limb.ply", units="mm"
    )
    assert asset.canonical_hash == "sha256:" + hashlib.sha256(canonical.blob).hexdigest()
