# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""G12A clauses 17-20: the geom seam, ``heph scan``, the budget, and the ceilings.

Clause 20 is the one that had to be written twice, because "before the parser"
turned out not to be a strong enough specification. A ceiling that fires after
``stream.read()`` has already spent the memory it was protecting and has already
put the bytes in the opstore blob store — so it is not a ceiling, it is a report.
The clause therefore asserts all three consequences that distinguish a real one:
no blob was added, no ``ImportSnapshot`` was registered, and the bytes were never
read at all, proved against a **sparse** fixture far larger than this process's
memory. A ``read()``-first implementation cannot survive that fixture, which is
exactly why it is the fixture.

And the clause's second half is the door a declaration-driven ceiling cannot
close: ``sync_import_state`` walks EVERY regular file under ``imports/``,
declared or not, and there is no declaration on that path to read a kind from.
The same sparse file is left undeclared and a full staleness sync is run over
it.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, cast

import pytest
from _g12a import MeshFixtures, build_error, install_import
from hephaestus.core.project_store.publication import Publisher
from hephaestus.geom.mesh import MESH_MAX_BYTES, mesh_max_bytes
from hephaestus.testing.pinned_image import CLOCK_HEADROOM, load_pinned
from hephaestus.testing.tools_fixture import Project

REPO = Path(__file__).resolve().parents[2]

#: The ceiling this budget carried BEFORE the pinned image measured it, kept as
#: a named constant for one reason: mission rule 4's budgets tighten and never
#: loosen, and the assertion below enforces that against this number. A
#: re-measurement that produced a *larger* derived ceiling would be a
#: regression wearing a measurement's clothes.
PRE_MEASUREMENT_CEILING_S = 20.0

#: Where the image's own measurement lives. Loaded at import, and a **refusal**
#: rather than a default when it is missing or was recorded outside a pinned
#: image (``hephaestus.testing.pinned_image``): a budget whose constant cannot
#: name the measurement it came from is the thing G12A.19 exists to prevent.
PINNED = load_pinned(Path(__file__).resolve().parent / "evidence", REPO)

#: Parse + canonicalize + quality budget for the reference fixture scan, in
#: seconds — **derived from the pinned image's own measurement**, not typed in.
#:
#: G12A.19's words are "measured in the pinned image and enforced as a ceiling,
#: the constant set from the image's own measurement". So it is computed here
#: from the archived figure rather than transcribed beside it: a transcribed
#: number can drift from its record silently, and this one cannot exist without
#: one. The headroom is :data:`CLOCK_HEADROOM`, the same band
#: ``scripts/stage12_pinned_measure.py --check`` re-measures against — three
#: times, which a shared CI runner fits inside and an implementation that went
#: quadratic in the triangle count does not. It is also the largest headroom
#: that keeps the derived ceiling at or below :data:`PRE_MEASUREMENT_CEILING_S`,
#: which the clause below asserts: budgets tighten, never loosen.
#:
#: Recorded 2026-08-30 at **6.1365 s** for 20 480 triangles, in a container
#: built from the repository's unchanged ``docker/ci/Dockerfile`` (the GHCR
#: digest ``ci.yml`` pins is not pullable without ``read:packages``; the record
#: names which route produced it and ``load_pinned`` re-checks the Dockerfile's
#: own ``FROM`` digest). The stock-runner venv measured 6.15 s on the same
#: commit, so the image is not where this number's uncertainty lives.
SCAN_BUDGET_S = round(CLOCK_HEADROOM * PINNED.number("parse_canonicalize_quality_s"), 1)

#: The reference fixture: a sphere tessellated finely enough to be a realistic
#: scan-sized mesh rather than a toy.
REFERENCE_TRIANGLES = 20_000


def _sparse_fixture(path: Path, size: int) -> None:
    """A file whose ``st_size`` is huge and whose blocks are not allocated.

    A ceiling that reads first cannot survive this: the read would materialize
    ``size`` bytes in the parent. A ceiling that fires off ``fstat`` on the
    already-open descriptor never touches a block.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


def _sparse_digest(size: int) -> str:
    """The opstore hash the sparse fixture WOULD have, computed without reading it.

    The fixture is a hole: every byte of it is zero. Hashing those zeros a chunk
    at a time costs nothing and gives the ceiling clause the one assertion that
    is genuinely about *this* file rather than about the store's population —
    ``blobs.has(...)`` on the exact digest the refused read would have produced.
    """
    digest = hashlib.sha256()
    chunk = bytes(1 << 23)
    whole, remainder = divmod(size, len(chunk))
    for _ in range(whole):
        digest.update(chunk)
    digest.update(bytes(remainder))
    return "sha256:" + digest.hexdigest()


def _blob_digests(store: Any) -> set[str]:
    """Every blob committed in this project's CAS, read off the real store.

    ``BlobStore`` publishes no ``list_all``; the previous shape of this clause
    guarded its assertion behind ``hasattr(store.blobs, "list_all")`` and so
    never ran it at all — a dead assertion is worse than a missing one, because
    it reads as covered. The sharded layout is public (``path_for``), so the
    directory is walked through the store's own address arithmetic rather than
    through a private attribute: ``path_for`` of a known digest names the
    ``blobs/sha256/<aa>/<digest>`` file, and its grandparent is the root of the
    shard tree.
    """
    probe = Path(store.blobs.path_for("sha256:" + "0" * 64))
    shard_root = probe.parent.parent
    if not shard_root.is_dir():
        return set()
    return {entry.name for entry in shard_root.rglob("*") if entry.is_file()}


# ==========================================================================
# clause 17: the geom seam stays clean


def test_geom_mesh_reaches_the_render_package_nowhere() -> None:
    """The §2.1 seam, mechanically: ``render.tessellate`` and ``geom.mesh`` share
    a data shape and no code.

    It is not an obstacle to route around; it is the mission rule 6 answer.
    ``render.tessellate`` owns B-rep -> triangles for rendering, and its
    deflection constants are golden provenance; ``geom.mesh`` owns external
    triangles -> facts. Neither is a second implementation of the other's job,
    and the import-closure check is what keeps that true when somebody is in a
    hurry.
    """
    program = textwrap.dedent(
        """
        import json, sys
        import hephaestus.geom.mesh  # noqa: F401
        print(json.dumps(sorted(sys.modules)))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    loaded: list[str] = json.loads(result.stdout)

    forbidden = [
        name
        for name in loaded
        if name.startswith(
            (
                "hephaestus.core.render",
                "hephaestus.core.executor",
                "hephaestus.core.project_store",
                "hephaestus.core.cli",
                "hephaestus.agent_bridge",
                "hephaestus.mcp",
            )
        )
    ]
    assert not forbidden, forbidden


def test_geom_mesh_is_in_the_packages_public_surface() -> None:
    """The tenth service is reachable as a service, not as a private module."""
    import hephaestus.geom.mesh as mesh_service

    assert mesh_service.__all__
    for name in mesh_service.__all__:
        assert hasattr(mesh_service, name), name


def test_the_existing_geom_boundary_tests_still_pass() -> None:
    """The boundary suite is the seam's own gate; it must stay green beside this."""
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "core/tests/test_geom_import_boundary.py", "-q"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ==========================================================================
# clause 18: heph scan, human and --json, over each admitted format


@pytest.mark.parametrize(
    ("name", "attribute", "kind"),
    [
        ("cube.stl", "cube_stl_binary", "mesh"),
        ("cube_ascii.stl", "cube_stl_ascii", "mesh"),
        ("cube.ply", "cube_ply_binary", "mesh"),
        ("cube_ascii.ply", "cube_ply_ascii", "mesh"),
        ("cube.obj", "cube_obj", "mesh"),
        ("cube.off", "cube_off", "mesh"),
        ("marks.xyz", "points_xyz", "points"),
    ],
)
def test_heph_scan_prints_the_facts_for_each_admitted_format(
    project: Project, meshes: MeshFixtures, name: str, attribute: str, kind: str
) -> None:
    """Human and ``--json``, through the CLI's own entry point.

    ``--units`` is required, and that is asserted below: a default here would be
    the harness guessing a scale on the operator's behalf, which is the one
    thing §1.3 exists to forbid.
    """
    from hephaestus.core.cli import main

    install_import(project.root, name, getattr(meshes, attribute))
    cwd = Path.cwd()
    os.chdir(project.root)
    try:
        assert main(["scan", name, "--units", "mm"]) == 0
        assert main(["scan", name, "--units", "mm", "--json"]) == 0
    finally:
        os.chdir(cwd)


def test_heph_scan_json_is_the_record_and_the_human_form_names_its_caveats(
    project: Project, meshes: MeshFixtures, capsys: pytest.CaptureFixture[str]
) -> None:
    from hephaestus.core.cli import main

    install_import(project.root, "holed.ply", meshes.holed_ply)
    cwd = Path.cwd()
    os.chdir(project.root)
    try:
        capsys.readouterr()
        assert main(["scan", "holed.ply", "--units", "mm", "--json"]) == 0
        document = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
        assert main(["scan", "holed.ply", "--units", "mm"]) == 0
        human = capsys.readouterr().out
    finally:
        os.chdir(cwd)

    assert document["triangle_count"] == 11
    assert document["watertight_at_weld_tol"] is False
    # `None`, not 0: the JSON says null and the human form says n/a — neither
    # says zero, because a volume from an open surface is not a volume.
    assert document["tessellated_volume_mm3"] is None
    assert "n/a" in human
    assert "0.000000 mm^3" not in human
    # And no field the record may not carry leaked into the document.
    for forbidden in ("volume", "sealed", "genus", "iou", "chamfer_mm"):
        assert forbidden not in document


def test_heph_scan_refuses_to_default_the_unit(project: Project, meshes: MeshFixtures) -> None:
    """No ``--units`` is a usage error, not an assumed millimetre."""
    from hephaestus.core.cli import main

    install_import(project.root, "cube.ply", meshes.cube_ply_binary)
    cwd = Path.cwd()
    os.chdir(project.root)
    try:
        with pytest.raises(SystemExit) as excinfo:
            main(["scan", "cube.ply"])
        assert excinfo.value.code == 2
    finally:
        os.chdir(cwd)


def test_heph_scan_refuses_a_traversing_path(project: Project) -> None:
    """It goes through the same confined walk a build uses, refusals included."""
    from hephaestus.core.cli import main

    (project.root / "secret.txt").write_text("SECRET-CONTENT-42\n", encoding="utf-8")
    (project.root / "imports").mkdir(exist_ok=True)
    cwd = Path.cwd()
    os.chdir(project.root)
    try:
        assert main(["scan", "../secret.txt", "--units", "mm"]) == 1
    finally:
        os.chdir(cwd)


# ==========================================================================
# clause 19: the parse + canonicalize + quality budget


def test_the_budget_constant_is_set_from_the_pinned_images_own_measurement() -> None:
    """G12A.19's other half: where the ceiling's *value* came from.

    The clause says the constant is "set from the image's own measurement". That
    is a claim about provenance, and provenance is not something the test below
    can assert by running fast. So it is asserted here, against the archived
    record: the record exists, it was taken inside a pinned image (a
    developer-host run cannot produce that stamp — ``pinned_stamp`` refuses),
    it was taken against the ``docker/ci/Dockerfile`` base this checkout still
    declares, and ``SCAN_BUDGET_S`` is exactly the recorded figure times the
    declared headroom.

    And the direction is pinned too: the derived ceiling must be **at or below**
    the one that stood before any image measured this, because mission rule 4's
    budgets tighten and never loosen. A re-measurement on a slower image would
    otherwise quietly buy the implementation room it never earned.
    """
    from hephaestus.core.mesh_solid import UNPINNED_IMAGE

    measured = PINNED.number("parse_canonicalize_quality_s")
    assert PINNED.image_digest != UNPINNED_IMAGE
    assert PINNED.image_digest.startswith("sha256:")
    assert "7.9" in PINNED.occt_version
    assert PINNED.number("reference_triangles") >= REFERENCE_TRIANGLES
    assert round(CLOCK_HEADROOM * measured, 1) == SCAN_BUDGET_S
    assert measured < SCAN_BUDGET_S
    assert SCAN_BUDGET_S <= PRE_MEASUREMENT_CEILING_S, (
        f"the derived ceiling {SCAN_BUDGET_S}s is above the {PRE_MEASUREMENT_CEILING_S}s "
        "that stood before the image measured anything; budgets tighten, never loosen "
        "(mission rule 4)"
    )


def test_the_reference_scan_parses_canonicalizes_and_measures_within_budget() -> None:
    """A ceiling, enforced — against a constant the pinned image measured.

    ``SCAN_BUDGET_S`` is derived at import from the archived pinned-image figure
    (the clause above asserts that derivation), so this test is the enforcement
    half and the record is the provenance half. What the headroom buys is the
    thing orders of magnitude are load-bearing for: an implementation that went
    quadratic in the triangle count fails this by a wide margin rather than
    squeaking past.
    """
    import trimesh
    from hephaestus.core.mesh_solid import image_digest
    from hephaestus.geom.mesh import canonicalize_mesh

    sphere = trimesh.creation.icosphere(subdivisions=5, radius=100.0)
    assert len(sphere.faces) >= REFERENCE_TRIANGLES
    payload = sphere.export(file_type="ply")
    data = payload if isinstance(payload, bytes) else payload.encode()

    started = time.perf_counter()
    canonical = canonicalize_mesh("reference.ply", data, "mm")
    elapsed = time.perf_counter() - started

    assert canonical.quality.connected_component_count == 1
    # Printed, not only asserted. The `stage12 measurements (pinned image)` CI
    # lane runs this test with `-s` inside the pinned image precisely so this
    # line lands in the log beside the recorded figure the ceiling is derived
    # from: a gate that only reports "under the ceiling" hands the next agent
    # nothing to re-record from when the image moves.
    print(
        f"\nG12A.19 parse+canonicalize+quality: {elapsed:.3f}s "
        f"for {len(sphere.faces)} triangles "
        f"(ceiling {SCAN_BUDGET_S}s derived from the pinned image's "
        f"{PINNED.number('parse_canonicalize_quality_s')}s in {PINNED.image_digest}; "
        f"this run is in image {image_digest()})"
    )
    assert elapsed < SCAN_BUDGET_S, (
        f"reference scan took {elapsed:.2f}s against a {SCAN_BUDGET_S}s ceiling"
    )


# ==========================================================================
# clause 20: the byte ceiling fires INSIDE the walk, before anything is spent


def test_an_over_ceiling_mesh_is_refused_before_a_single_byte_is_read(
    project: Project,
) -> None:
    """All three consequences that distinguish this from a post-read check.

    The fixture is sparse and far larger than the process's address-space
    budget, so an implementation that read first would die rather than refuse.
    Then: the opstore blob store gained no blob, no ``ImportSnapshot`` was
    registered, and the refusal names the ceiling and the variable that raises
    it.
    """
    store = project.store
    size = mesh_max_bytes() * 2
    huge = project.root / "imports" / "huge.ply"
    _sparse_fixture(huge, size)
    assert huge.stat().st_size > mesh_max_bytes()
    assert huge.stat().st_blocks * 512 < 1_000_000, "fixture must be sparse, not allocated"

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    error = build_error(
        project,
        "over_ceiling",
        'scan = import_mesh("huge.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    assert error["line"] == 1
    assert "ceiling" in error["message"]
    assert "HEPHAESTUS_MESH_MAX_BYTES" in error["message"]
    assert "[mesh_import_too_large]" in error["message"]
    # The file's own bytes are NOT in the CAS. This is the assertion that binds
    # ``store.py:259`` — ``blobs.put(data)`` is content-addressed, so if that
    # line had ever run on this file the store would hold exactly this digest.
    # It is computed without reading the fixture (every byte of a hole is zero),
    # so the test does not spend the memory the ceiling exists to save.
    assert not store.blobs.has(_sparse_digest(size))
    # …and the freeze that would have called it adds NO blob at all: snapshot
    # the store either side of the one operation that registers an import, not
    # either side of a whole build, so the comparison is about this path rather
    # than about everything a build legitimately writes.
    before = _blob_digests(store)
    # The walk itself is asserted to see something, so "no new blob" can never
    # be satisfied by a reader that found no blobs at all — which is how the
    # previous shape of this clause passed while asserting nothing.
    assert before, "the store must be populated for the comparison to mean anything"
    frozen = Publisher(project.layout, project.store).freeze_inputs("over_ceiling")
    assert _blob_digests(store) == before
    # No snapshot was registered for it: the publisher's own freeze recorded a
    # refusal instead of an import ref.
    assert "huge.ply" not in frozen.imports
    assert "huge.ply" not in frozen.import_refs
    assert "huge.ply" in frozen.import_errors
    # …and the bytes were never read, MEASURED rather than argued from the
    # fixture's size. The sparse fixture proves an implementation that read the
    # whole file would die; this proves the process did not grow by anything
    # like it even where the kernel would have been happy to serve the holes
    # from the page cache. ``ru_maxrss`` is in KiB.
    assert (rss_after - rss_before) * 1024 < mesh_max_bytes() // 2


def test_a_step_import_of_the_same_size_is_unaffected(project: Project) -> None:
    """STEP passes ``None``, so the existing path is bit-for-bit what it was.

    The ceiling is per-kind. A STEP file over ``MESH_MAX_BYTES`` is read exactly
    as it always was and fails, if it fails, on its own terms — because an
    over-large STEP simply does not parse, which is the reasoning ``INGEST.md``
    already relies on and this stage does not disturb.
    """
    from hephaestus.core.executor.imports import ImportResolutionError, read_import

    huge = project.root / "imports" / "huge.step"
    _sparse_fixture(huge, MESH_MAX_BYTES * 2)

    with pytest.raises(ImportResolutionError) as excinfo:
        read_import(project.root / "imports", "huge.step", max_bytes=mesh_max_bytes())
    assert excinfo.value.reason == "mesh_import_too_large"

    # …and with STEP's own ceiling — ``None`` — the walk does not refuse it. The
    # read itself is not performed here: a sparse multi-gigabyte read is the
    # very cost this test is about. What is asserted is that the CEILING is what
    # differs, which the two calls above and below isolate.
    from hephaestus.core.executor.imports import max_bytes_for_kind

    assert max_bytes_for_kind("step") is None
    assert max_bytes_for_kind("mesh") == mesh_max_bytes()
    assert max_bytes_for_kind("points") == mesh_max_bytes()


def test_an_undeclared_over_ceiling_file_is_never_read_by_a_staleness_sync(
    project: Project, meshes: MeshFixtures
) -> None:
    """The door a declaration-driven ceiling cannot close (§1.6).

    ``sync_import_state`` drives ``import_hash`` over EVERY regular file under
    ``imports/``, whether or not any script declares it — so an undeclared 40 GB
    scan dropped in the directory would be read whole into the parent by the
    next sync. Here the same sparse fixture is left undeclared, a full sync is
    run, and the clause asserts it completes, that the fixture's staleness entry
    is the unreadable-file ``None`` rather than a hash, and that its bytes were
    never read. A ceiling resolved only from a declaration cannot pass this
    half, which is why it is written.
    """
    install_import(project.root, "small.ply", meshes.cube_ply_binary)
    huge = project.root / "imports" / "undeclared.ply"
    _sparse_fixture(huge, mesh_max_bytes() * 2)

    publisher = Publisher(project.layout, project.store)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    publisher.sync_import_state()

    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    state = dict(publisher.projections.state().import_state)
    assert "undeclared.ply" in state
    # ``import_hash`` returns None for a file it cannot read, and the projection
    # stores that as the empty string — "not the frozen bytes", which is all
    # either caller needs to know. A hash here would mean the bytes were read.
    assert state["undeclared.ply"] == ""
    assert state["small.ply"].startswith("sha256:")
    # The process did not grow by anything like the fixture's size.
    assert (after - before) * 1024 < mesh_max_bytes() // 2


def test_an_undeclared_step_sized_file_keeps_steps_none_ceiling() -> None:
    """Extension resolution moves nothing for STEP or for unknown extensions."""
    from hephaestus.core.executor.imports import max_bytes_for_path

    assert max_bytes_for_path("vendor/plate.step") is None
    assert max_bytes_for_path("notes.txt") is None
    assert max_bytes_for_path("limb.ply") == mesh_max_bytes()
    assert max_bytes_for_path("LIMB.PLY") == mesh_max_bytes()
    assert max_bytes_for_path("marks.xyz") == mesh_max_bytes()


def test_the_triangle_and_point_ceilings_fire_on_a_declared_count(
    project: Project,
) -> None:
    """A small file declaring 10⁸ triangles is refused before trimesh allocates.

    These two fire after the bytes are resident — the spec says so rather than
    letting §1.6's opening sentence imply otherwise — and that is sound only
    because ``MESH_MAX_BYTES`` has already bounded them. What they bound is the
    PARSER's working set: a 100-byte header can claim a hundred million
    triangles, and the byte ceiling has no opinion about that at all.
    """
    import struct

    from hephaestus.core.executor.imports import ImportResolutionError, stage_import

    from opstore import sha256_bytes

    # A binary STL header claiming 10⁸ triangles, with none of them present.
    claim = bytes(80) + struct.pack("<I", 100_000_000)
    with pytest.raises(ImportResolutionError) as excinfo:
        stage_import(
            claim,
            path="liar.stl",
            content_hash=sha256_bytes(claim),
            out_dir=project.root / "out",
            kind="mesh",
            units="mm",
        )
    assert excinfo.value.reason == "mesh_import_too_large"
    assert "HEPHAESTUS_MESH_MAX_TRIANGLES" in excinfo.value.message


def test_the_point_ceiling_fires_on_a_counting_pre_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """XYZ declares nothing, so the pre-pass counts — and ABORTS at the ceiling.

    A pass that ran to completion on a 10⁸-point file would have done the work
    the ceiling exists to refuse, so what it returns is "the count, or
    ceiling + 1" and never more. The ceiling is lowered here by patching the
    resolver rather than the environment, because the env override for a SAFETY
    ceiling may only raise it (the ``COMPARE.md`` §5 local-floor rule) — an
    operator cannot quietly lower one below the shipped floor and turn a passing
    build into a refusal nobody declared.
    """
    from hephaestus.geom.mesh import MeshReadError, count_ceiling_check

    cloud = b"\n".join(b"%d 0 0" % index for index in range(10)) + b"\n"
    count_ceiling_check("marks.xyz", cloud, "points", "xyz")  # under the real floor

    monkeypatch.setattr("hephaestus.geom.mesh.mesh_max_points", lambda: 3)
    with pytest.raises(MeshReadError) as excinfo:
        count_ceiling_check("marks.xyz", cloud, "points", "xyz")
    assert excinfo.value.reason == "mesh_import_too_large"
    assert "HEPHAESTUS_MESH_MAX_POINTS" in excinfo.value.message


def test_a_safety_ceiling_env_override_may_only_raise_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The local-floor rule, asserted in both directions for the byte ceiling."""
    monkeypatch.setitem(os.environ, "HEPHAESTUS_MESH_MAX_BYTES", "1")
    assert mesh_max_bytes() == MESH_MAX_BYTES
    monkeypatch.setitem(os.environ, "HEPHAESTUS_MESH_MAX_BYTES", str(MESH_MAX_BYTES * 4))
    assert mesh_max_bytes() == MESH_MAX_BYTES * 4
