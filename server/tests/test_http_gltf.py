# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pygltflib ships no type stubs; the same file-level relaxations
# `tests/stage1/test_gltf_gate.py` declares, for the same reason.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""§5.1/§5.2 — the geometry wire: GLB publication and the explode displacement.

``INTERFACE.md`` §19 items 11 and 12, as the tests that hold them up.

**Item 12 — GLB export and publication for a build artifact ref.** Before it,
``export_gltf`` had no production caller and could not have had one: its bundle,
source and table refs are mandatory and exist only after a selection inspection
has minted a bundle for that exact build. So the only GLB a server could have
produced for a freshly built artifact was an *unlinked* one, which §12.3 requires
be rejected — a viewport that is pickable but unresolvable, the worst possible
failure because it looks like it works. The route therefore mints rather than
hopes, and the tests here assert the four things §5.1 and mission_plan G1's GLTF
clause name: the GLB **validates**, its **mesh count equals the build result's
solid count**, its selection IDs **resolve through its linked bundle**, and an
**unlinked GLB is refused** rather than served.

**Item 11 — ``explode_offset`` in GLTF mesh ``extras``.** The named invariant is
byte-equivalence: for every solid and every ``t``, the client's
``explode_offset · t`` equals ``channels._explode_offset(scene, solid, t)`` — the
*same function* ``heph render --explode`` renders through
(``channels.py::_render_explode``). Without this test the viewport and the
explode/section golden family drift silently, and the drift first surfaces as a
golden mismatch in an unrelated stage.

**Validation follows the Stage 1 precedent** (``tests/stage1/test_gltf_gate.py``,
``gltf.py``'s module docstring): ``validate_gltf`` asserts the structural
invariants the gate names without requiring the Khronos ``gltf-validator``, which
is a separate non-Python tool. Where that binary *is* installed, one extra test
runs it — strengthening CI that has it without making it a dependency of CI that
does not.

The fixture is the **public clean-room** ``assembly`` project (§14): six solids,
which is what makes §5.2's pairwise-centroid clause non-vacuous — G4.6 demands a
strict increase over **all** pairs, and a single-solid fixture would make it true
by having no pairs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Generator
from contextlib import ExitStack
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.project_store.store import artifact_ref, blob_hash_of_ref
from hephaestus.core.render.bundle import resolve_selection
from hephaestus.core.render.channels import RenderScene, _explode_offset, scene_from_shape
from hephaestus.core.render.gltf import (
    BUNDLE_REF_KEY,
    EXPLODE_OFFSET_KEY,
    SOURCE_REF_KEY,
    resolve_gltf_pick,
    validate_gltf,
)
from hephaestus.core.render.gltf_publish import GLB_MAGIC, resolve_published_gltf
from hephaestus.http.artifacts import GLTF_ROUTE_KINDS
from hephaestus.http.geometry import BUNDLE_HEADER, SOURCE_HEADER
from hephaestus.testing.workspace import Workspace, uuid7, workspace
from opstore.hashing import sha256_bytes

FIXTURE = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures" / "assembly"

#: ``assembly/primary`` is an open-frame shelf: two decks + four posts. Named
#: here so a fixture change that collapsed it to one solid fails loudly instead
#: of quietly making §5.2's "over **all** pairs" clause vacuous.
PRIMARY_SOLIDS = 6


@dataclass(frozen=True)
class Geometry:
    """One built assembly project, its build ref, and the GLB the route served."""

    web: Workspace
    build_ref: str
    glb: bytes
    gltf_ref: str
    bundle_ref: str
    scene: RenderScene


@pytest.fixture(scope="module")
def geometry(tmp_path_factory: pytest.TempPathFactory) -> Generator[Geometry]:
    """The public ``assembly`` fixture, built through the route, GLB fetched once.

    Module-scoped because minting tessellates and drives an offscreen GL session:
    the *subject* is the published GLB, and re-publishing it per test would buy
    nothing but wall time. Each test that needs a fresh store makes its own.
    """
    root = tmp_path_factory.mktemp("gltf-web") / "assembly"
    shutil.copytree(FIXTURE, root)
    with ExitStack() as stack:
        web = stack.enter_context(workspace(root, scaffold=False))
        built = web.post("/parts/primary/build", json={}, key=uuid7())
        assert built.status_code == 200, built.text
        assert built.json()["status"] == "ok", built.text
        build_ref = web.get("/parts/primary/build").json()["artifact_ref"]

        response = web.get(f"/artifacts/{build_ref}/gltf")
        assert response.status_code == 200, response.text
        brep = web.runtime.store.blobs.get(blob_hash_of_ref(build_ref))
        yield Geometry(
            web=web,
            build_ref=build_ref,
            glb=response.content,
            gltf_ref=response.headers["ETag"],
            bundle_ref=response.headers[BUNDLE_HEADER],
            scene=scene_from_shape(cast("Any", load_brep_shape(brep))),
        )


# --------------------------------------------------------------------------
# §19 item 12 — publication


def test_the_route_mints_and_publishes_a_linked_glb(geometry: Geometry) -> None:
    """§5.1: the route *does the minting* rather than hoping it already happened.

    ``export_gltf`` has no other production caller, and the bundle its
    ``bundle_ref`` names exists only because this route published it. The served
    bytes are a GLB, the ``ETag`` is a real ``gltf`` artifact ref (which is what
    makes §2.6's ``immutable`` claim honest rather than optimistic), and the blob
    behind that ref is genuinely stored.
    """
    assert geometry.glb[:4] == GLB_MAGIC
    assert geometry.gltf_ref.startswith("artifact:gltf:sha256:")
    assert geometry.gltf_ref == artifact_ref("gltf", sha256_bytes(geometry.glb))
    assert geometry.web.runtime.store.blobs.has(blob_hash_of_ref(geometry.gltf_ref))


def test_the_meta_route_advertises_the_gltf_link_for_a_build_ref(geometry: Geometry) -> None:
    """§2.6: ``links`` names which content routes a ref may be read through.

    The point of ``links`` is that the client branches on the *server's* answer
    rather than carrying a kind list of its own to drift from — so the third
    content route has to appear there too, or a client would have to hard-code
    "build refs also have GLBs". A build ref offers both: ``bytes`` is its stored
    BREP, ``gltf`` is the viewport's geometry, and they are different artifacts.
    """
    meta = geometry.web.get(f"/artifacts/{geometry.build_ref}/meta").json()
    assert set(meta["links"]) == {"bytes", "gltf"}
    assert meta["links"]["gltf"] == f"/api/v1/artifacts/{geometry.build_ref}/gltf"

    gltf_meta = geometry.web.get(f"/artifacts/{geometry.gltf_ref}/meta").json()
    assert set(gltf_meta["links"]) == {"bytes", "gltf"}
    assert gltf_meta["mime_type"] == "model/gltf-binary"
    assert gltf_meta["total_bytes"] == len(geometry.glb)


def test_the_provenance_headers_are_the_servers_answer_not_a_client_decode(
    geometry: Geometry,
) -> None:
    """§1: selection links are server values; the client reads, never decodes.

    The GLB body is binary, so without these headers the only way for the client
    to learn which bundle backs the geometry would be to pull ``asset.extras``
    out of the blob itself. The headers say the same thing the extras do — and
    the test asserts they *agree*, so a header can never become a second, drifting
    source of the same fact.
    """
    validation = validate_gltf(geometry.glb)
    response = geometry.web.get(f"/artifacts/{geometry.build_ref}/gltf")
    assert response.headers[BUNDLE_HEADER] == validation.bundle_ref
    assert response.headers[SOURCE_HEADER] == validation.source_artifact_ref
    assert response.headers[SOURCE_HEADER] == geometry.build_ref


def test_the_glb_validates_structurally(geometry: Geometry) -> None:
    """The Stage 1 precedent's validator, on the bytes the *route* served.

    ``validate_gltf`` parses the container, bounds-checks every bufferView
    against the buffer and every accessor against its bufferView, and — asserted
    separately below — checks the mesh count. It also now requires every mesh to
    carry a float3 ``explode_offset``, so a GLB that left the viewport with
    nothing to translate by fails here rather than at runtime.
    """
    validation = validate_gltf(geometry.glb)
    assert validation.primitive_count > 0
    assert validation.accessor_count > 0
    assert validation.buffer_length > 0
    assert len(validation.explode_offsets) == validation.mesh_count


def test_mesh_count_equals_the_build_results_solid_count(geometry: Geometry) -> None:
    """G1's GLTF clause, against the **build result** rather than a recount.

    §6.1 fixes "geometry count" as the build result's own number, and §1's closed
    list forbids re-counting anything a build result already counts. So the
    expected mesh count is read out of ``GET /parts/{part}/build`` — the same
    projection the tree row count is asserted against in G4.2 — not recomputed
    from the geometry.
    """
    build = geometry.web.get("/parts/primary/build").json()
    declared = sum(int(entry["solids"]) for entry in build["geometries"])
    assert declared == PRIMARY_SOLIDS, "the public fixture must keep >= 3 solids (§5.2)"
    validation = validate_gltf(geometry.glb, expected_solid_count=declared)
    assert validation.mesh_count == declared


def test_asset_extras_bind_the_exact_source_build_and_its_bundle(geometry: Geometry) -> None:
    """§5.1: ``asset.extras`` carry the bundle, the source build, and the table.

    The *exactness* is the point: the bundle was minted for this build ref and
    resolves against it, so a pick made against this GLB can never be authorized
    by a bundle belonging to some other build.
    """
    validation = validate_gltf(geometry.glb)
    assert validation.source_artifact_ref == geometry.build_ref
    assert validation.bundle_ref == geometry.bundle_ref
    resolution = resolve_selection(
        geometry.web.runtime.store,
        geometry.bundle_ref,
        expected_source_artifact_ref=geometry.build_ref,
    )
    assert resolution.source_artifact_ref == geometry.build_ref
    assert resolution.entries


def test_every_solid_pick_resolves_through_the_linked_bundle(geometry: Geometry) -> None:
    """§12.3: the GLB alone never authorizes a selection — the bundle does.

    Run against the **server-held GLB bytes** (shape (A) of the resolve route),
    which is the only arrangement in which the server can notice an unlinked GLB
    at all; §12.3 says so explicitly, and this is the same resolution path the
    Stage 5 route will call.
    """
    for solid_index in range(PRIMARY_SOLIDS):
        entry = resolve_gltf_pick(geometry.web.runtime.store, geometry.glb, solid_index)
        assert entry.kind == "solid"
        assert entry.solid_index == solid_index


def test_a_second_request_resolves_the_publication_instead_of_re_minting(
    geometry: Geometry,
) -> None:
    """ "Resolves, **or** publishes on demand" — the resolve half.

    The second GET returns the same bytes under the same ETag, and the engine
    call reports ``minted=False``: the GC edges recorded at publication are
    walked back to the existing GLB rather than a second bundle being rendered.
    """
    again = geometry.web.get(f"/artifacts/{geometry.build_ref}/gltf")
    assert again.status_code == 200
    assert again.content == geometry.glb
    assert again.headers["ETag"] == geometry.gltf_ref

    published = geometry.web.runtime.cad.publish_gltf(geometry.build_ref)
    assert published.minted is False
    assert published.ref == geometry.gltf_ref
    assert published.bundle_ref == geometry.bundle_ref

    resolved = resolve_published_gltf(geometry.web.runtime.store, geometry.build_ref)
    assert resolved is not None and resolved.ref == geometry.gltf_ref


def test_the_published_glb_is_addressable_by_its_own_ref(geometry: Geometry) -> None:
    """A ``gltf`` ref reaches the same bytes through both artifact routes.

    ``/gltf`` re-verifies the bundle link before serving (the §12.3 second line
    of defence); ``/bytes`` serves it because ``gltf`` is on §2.6's enumeration.
    Both must agree with what the build ref returned, or the ``ETag`` would be
    naming bytes that differ by route.
    """
    by_ref = geometry.web.get(f"/artifacts/{geometry.gltf_ref}/gltf")
    assert by_ref.status_code == 200
    assert by_ref.content == geometry.glb

    as_bytes = geometry.web.get(f"/artifacts/{geometry.gltf_ref}/bytes")
    assert as_bytes.status_code == 200
    assert as_bytes.content == geometry.glb
    assert as_bytes.headers["content-type"].startswith("model/gltf-binary")


def test_the_route_accepts_exactly_the_enumerated_kinds(geometry: Geometry) -> None:
    """Closed by enumeration, not by "whatever resolves" (§2.6's discipline).

    A stored artifact of an unlisted kind is a 404 about the **kind**, not about
    the ref failing to resolve — so the refusal cannot be mistaken for an
    addressing miss and quietly relaxed later.
    """
    assert {"build", "build-checkpoint", "gltf"} == GLTF_ROUTE_KINDS
    store = geometry.web.runtime.store
    store.blobs.put(b"solid exported\n")
    export_ref = artifact_ref("export", sha256_bytes(b"solid exported\n"))
    response = geometry.web.get(f"/artifacts/{export_ref}/gltf")
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_artifact_kind_for_route"
    assert response.json()["kind"] == "export"


def test_a_build_checkpoint_ref_mints_a_linked_glb_without_a_part(geometry: Geometry) -> None:
    """The second enumerated build kind, and the label-less resolution path.

    A ``build-checkpoint`` is the last-good checkpoint of a *failed* build, so it
    is never any part's current build — which means the producer finds no part to
    join and gets no build result and no source map. Solid labels and tag
    placements are therefore absent, and that is the honest answer for a ref
    whose provenance was never published: the selection table still names every
    solid/face/edge occurrence, it simply carries no tag or label. What must NOT
    change is the link, so that is what this asserts.

    The checkpoint is addressed by re-kinding a blob that is genuinely stored:
    the refs are ``artifact:<kind>:sha256:<hash>`` and the hash is the whole
    identity, so this exercises the exact code path a real checkpoint takes
    without needing a build that fails halfway.
    """
    blob = blob_hash_of_ref(geometry.build_ref)
    checkpoint = artifact_ref("build-checkpoint", blob)
    response = geometry.web.get(f"/artifacts/{checkpoint}/gltf")
    assert response.status_code == 200, response.text

    validation = validate_gltf(response.content, expected_solid_count=PRIMARY_SOLIDS)
    assert validation.source_artifact_ref == checkpoint
    assert validation.bundle_ref is not None
    # A *different* bundle from the current build's: the bundle is minted for the
    # exact ref requested, and these are two different refs over the same bytes.
    assert validation.bundle_ref != geometry.bundle_ref
    resolution = resolve_selection(
        geometry.web.runtime.store,
        validation.bundle_ref,
        expected_source_artifact_ref=checkpoint,
    )
    assert resolution.source_artifact_ref == checkpoint
    assert all(entry.label is None and entry.tag is None for entry in resolution.entries.values())


def test_a_ref_that_is_not_in_the_open_project_is_refused(geometry: Geometry) -> None:
    """§2.2: reachability from the open project's opstore *is* the authorization."""
    absent = artifact_ref("build", sha256_bytes(b"a build that was never stored"))
    response = geometry.web.get(f"/artifacts/{absent}/gltf")
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_artifact"


def test_an_unlinked_glb_is_refused_and_never_served(geometry: Geometry) -> None:
    """§12.3, binds G5.12: an **unlinked** GLTF is rejected.

    Constructed the way the failure would actually arrive — a real, structurally
    valid GLB with numerically valid selection IDs whose ``asset.extras`` have
    lost their immutable bundle link. It is stored in the open project, so it
    resolves; the refusal is about the *link*, and it carries the five-value
    vocabulary's ``malformed`` rather than a collapsed generic error (§2.4
    TIGHTENING, binds G5.15).

    §5.1's route never serves an unlinked GLB in the first place, so this is the
    second line of defence — and §12.3 requires both to be tested.
    """
    unlinked = _strip_bundle_link(geometry.glb)
    assert unlinked != geometry.glb
    assert validate_gltf(unlinked).bundle_ref is None
    geometry.web.runtime.store.blobs.put(unlinked)
    ref = artifact_ref("gltf", sha256_bytes(unlinked))

    response = geometry.web.get(f"/artifacts/{ref}/gltf")
    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "stale_selection"
    assert body["stale_reason"] == "malformed"

    # And the bytes are genuinely present: the refusal is about the missing link,
    # not about the artifact failing to resolve.
    assert geometry.web.runtime.store.blobs.has(blob_hash_of_ref(ref))


def test_a_glb_whose_bundle_no_longer_resolves_is_refused(tmp_path: Path) -> None:
    """A published GLB whose bundle has aged out is refused, not served stale.

    ``resolve_published_gltf`` re-resolves the bundle every time; when the source
    build's blob is gone the resolution is ``expired`` and the candidate is not
    accepted. The route then has no linked GLB to serve and says so, rather than
    handing the viewport a GLB whose picks would all fail.
    """
    root = tmp_path / "assembly"
    shutil.copytree(FIXTURE, root)
    with workspace(root, scaffold=False) as web:
        assert web.post("/parts/primary/build", json={}, key=uuid7()).status_code == 200
        build_ref = web.get("/parts/primary/build").json()["artifact_ref"]
        first = web.get(f"/artifacts/{build_ref}/gltf")
        assert first.status_code == 200
        gltf_ref = first.headers["ETag"]

        # Age out the source build: `resolve_selection` reports `expired` for a
        # bundle whose source blob is no longer stored (bundle.py:383-387).
        web.runtime.store.blobs.remove(blob_hash_of_ref(build_ref))
        assert resolve_published_gltf(web.runtime.store, build_ref) is None

        response = web.get(f"/artifacts/{gltf_ref}/gltf")
    assert response.status_code == 409
    assert response.json()["reason"] == "stale_selection"


@pytest.mark.skipif(
    shutil.which("gltf_validator") is None and shutil.which("gltf-validator") is None,
    reason="the Khronos gltf-validator is a separate non-Python tool (Stage 1 precedent)",
)
def test_the_khronos_validator_accepts_the_glb(geometry: Geometry, tmp_path: Path) -> None:
    """The Khronos validator, when the machine has it.

    ``gltf.py``'s module docstring states the Stage 1 precedent: the binary is a
    separate non-Python tool, and :func:`validate_gltf` asserts the structural
    invariants the gate names without requiring it. This test is the *bonus*
    lane — it strengthens a CI image that installs the binary and skips
    everywhere else, rather than making one dependency of the suite.
    """
    binary = shutil.which("gltf_validator") or shutil.which("gltf-validator")
    assert binary is not None
    path = tmp_path / "primary.glb"
    path.write_bytes(geometry.glb)
    completed = subprocess.run(
        [binary, "-r", "-o", str(tmp_path), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    report_path = tmp_path / "primary.glb.report.json"
    raw: object = json.loads(report_path.read_text()) if report_path.is_file() else {}
    report = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    issues = cast("dict[str, Any]", report.get("issues", {}))
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert int(issues.get("numErrors", 0)) == 0, json.dumps(issues)


# --------------------------------------------------------------------------
# §19 item 11 — explode_offset


def test_explode_offset_is_byte_equivalent_to_the_render_transform(geometry: Geometry) -> None:
    """§5.1's named invariant, asserted byte-for-byte rather than approximately.

    For every solid and every ``t``, the client's ``explode_offset · t`` must be
    byte-equivalent to ``_explode_offset(scene, solid, t)`` — the one definition
    of the explode transform, and the exact function
    ``channels.py::_render_explode`` applies for ``heph render --explode`` and
    ``explode_silhouette`` counts pixels through for the G1 explode gate.

    Byte-equivalence, not ``allclose``: ``EXPLODE_SCALE`` is ``1.0``, so
    ``(c - C) * (t * 1.0)`` and ``((c - C) * 1.0) * t`` are the *same*
    multiplication and any difference at all would mean the two paths had stopped
    being the same arithmetic. ``t = 0`` is excluded from the byte comparison and
    asserted separately: ``_explode_offset`` short-circuits it to ``+0.0`` while
    ``offset · 0`` yields a signed zero, which is the same displacement with
    different bytes — a distinction with no geometric content, said out loud
    rather than hidden inside a tolerance.
    """
    offsets = validate_gltf(geometry.glb).explode_offsets
    assert len(offsets) == PRIMARY_SOLIDS

    for solid in geometry.scene.solids:
        shipped = np.array(offsets[solid.solid_index], dtype=np.float64)
        for t in (1.0, 0.75, 0.5, 0.25, 0.1, 1e-9):
            expected = _explode_offset(geometry.scene, solid, t)
            assert (shipped * t).tobytes() == expected.tobytes(), (
                f"solid {solid.solid_index} at t={t}: the GLB's explode_offset and "
                "channels._explode_offset have drifted"
            )
        assert np.all(_explode_offset(geometry.scene, solid, 0.0) == 0.0)


def test_the_compared_function_is_the_one_the_explode_render_calls() -> None:
    """The tie to ``heph render --explode``, made mechanical rather than asserted.

    The test above compares the GLB against ``_explode_offset``. That is only
    evidence about the *renderer* if the renderer calls the same object — so this
    asserts the identity directly: ``channels._render_explode`` (the shaded pass
    behind ``heph render --explode``) and ``channels.explode_silhouette`` (the
    pixel count behind the G1 explode gate) both close over exactly the function
    the byte-comparison used. If someone gave the GLB its own copy of the
    displacement maths, this fails immediately instead of surfacing later as a
    golden mismatch in an unrelated stage.
    """
    from hephaestus.core.render import channels

    render_explode = cast("Any", channels)._render_explode
    assert render_explode.__globals__["_explode_offset"] is _explode_offset
    assert channels.explode_silhouette.__globals__["_explode_offset"] is _explode_offset


def test_the_shipped_vector_is_the_displacement_not_a_unit_axis(geometry: Geometry) -> None:
    """§5.2: a displacement vector, and the rejected alternative stays rejected.

    The transform is a **homothety** about the assembly centroid: each solid
    moves a distance proportional to ``|c_i - C|``. A unit axis with the only
    ``explode_scale`` that exists (the global ``1.0``) would move every solid the
    same distance along different directions — a different transform that can
    fail G4.6 outright. This asserts the shipped magnitudes actually differ, so a
    future "simplification" to unit vectors fails here instead of in a gate.
    """
    magnitudes = sorted(
        float(np.linalg.norm(np.array(offset, dtype=np.float64)))
        for offset in validate_gltf(geometry.glb).explode_offsets
    )
    assert magnitudes[0] > 0.0
    assert magnitudes[-1] > magnitudes[0], (
        "every solid at the same radius means a unit axis was shipped, not a displacement"
    )


def test_explode_at_t1_increases_every_pairwise_centroid_distance(geometry: Geometry) -> None:
    """§5.2 / G4.6, as the server-side half of the clause.

    G4.6 reads pairwise centroid distances back out of the *scene graph* after
    the client applies ``offset · t``. The client's translation is exactly
    ``centroid + offset · t``, so the same arithmetic is checkable here — and if
    it fails here it can only fail in the browser too. Over **all** pairs, which
    is why the fixture carries six solids rather than one.
    """
    offsets = validate_gltf(geometry.glb).explode_offsets
    at_rest = {s.solid_index: s.centroid() for s in geometry.scene.solids}
    exploded = {
        index: centroid + np.array(offsets[index], dtype=np.float64)
        for index, centroid in at_rest.items()
    }
    pairs = list(combinations(sorted(at_rest), 2))
    assert len(pairs) == PRIMARY_SOLIDS * (PRIMARY_SOLIDS - 1) // 2
    for a, b in pairs:
        before = float(np.linalg.norm(at_rest[a] - at_rest[b]))
        after = float(np.linalg.norm(exploded[a] - exploded[b]))
        assert after > before, f"solids {a} and {b} did not separate at t=1"


# --------------------------------------------------------------------------
# helpers


def _strip_bundle_link(glb: bytes) -> bytes:
    """The same GLB with its ``asset.extras`` bundle link removed.

    Everything else survives — the meshes, the primitives, the embedded selection
    IDs — which is precisely the shape §12.3 describes: "numerically valid IDs
    but no immutable bundle link in its metadata".
    """
    from pygltflib import GLTF2

    parsed = cast("Any", GLTF2.load_from_bytes(glb))
    extras = dict(cast("dict[str, Any]", parsed.asset.extras or {}))
    extras.pop(BUNDLE_REF_KEY, None)
    assert SOURCE_REF_KEY in extras
    parsed.asset.extras = extras
    return b"".join(parsed.save_to_bytes())


def test_the_stripped_glb_helper_really_only_removes_the_link(geometry: Geometry) -> None:
    """The negative fixture is a *valid* GLB, or the refusal proves nothing.

    If ``_strip_bundle_link`` produced something malformed, the 409 above would
    be about the malformation rather than about the missing bundle link, and
    G5.12's clause would be untested while looking tested.
    """
    unlinked = _strip_bundle_link(geometry.glb)
    validation = validate_gltf(unlinked, expected_solid_count=PRIMARY_SOLIDS)
    assert validation.bundle_ref is None
    assert validation.source_artifact_ref == geometry.build_ref
    assert validation.primitive_count == validate_gltf(geometry.glb).primitive_count
    assert len(validation.explode_offsets) == PRIMARY_SOLIDS
    for mesh_index in range(PRIMARY_SOLIDS):
        # The IDs are still numerically valid: only the authorization is gone.
        with pytest.raises(Exception, match="carries no linked selection bundle ref"):
            resolve_gltf_pick(geometry.web.runtime.store, unlinked, mesh_index)


def test_a_glb_missing_its_explode_offsets_is_not_valid(geometry: Geometry) -> None:
    """``explode_offset`` is structural, not optional (§5.1).

    A GLB whose meshes carry no displacement leaves the client with nothing to
    translate by and no legal way to derive one — §1's closed list forbids it
    computing centroids — so the absence is a malformed GLB rather than a feature
    the viewport degrades around.
    """
    from pygltflib import GLTF2

    parsed = cast("Any", GLTF2.load_from_bytes(geometry.glb))
    for mesh in cast("list[Any]", parsed.meshes):
        extras = dict(cast("dict[str, Any]", mesh.extras or {}))
        extras.pop(EXPLODE_OFFSET_KEY, None)
        mesh.extras = extras
    stripped = b"".join(parsed.save_to_bytes())
    with pytest.raises(ValidationError, match=EXPLODE_OFFSET_KEY):
        validate_gltf(stripped)
