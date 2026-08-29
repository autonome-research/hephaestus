# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§22 — egress, over the real HTTP surface (Stage 10A, Gate G10A).

``INTERFACE.md`` §22 and ``mission_plan.md`` §"Stage 10 … Gate G10A". Every
clause of the gate that can be asserted below a browser is asserted here; the
browser half (the A/B pin round trip through the client, and the token that never
enters a download URL) is ``web/e2e/export.spec.ts``.

**What these tests are careful about, and why each one earns its place.**

* The **A/B half** — pin A, export, publish B, re-export from the still-pinned A,
  same digest. §22.5: with ``artifact_ref = None`` the engine resolves
  ``current_result`` *at export time*, so a null ref would mean the operator
  looks at build A, clicks Export and receives a STEP of build B. *The exported
  file must be the geometry on screen or the workspace is lying with a download.*
* The **relabelled-ref clause**, which is the one that proves §19.24 landed: a
  gate asserting only the ``artifact:export:…`` refusal would pass against a
  route that serves the same bytes under a different label.
* The **derived filename**, which the 2026-08-28 review corrected: this route
  serves any blob a committed row names, *including* an export an agent produced
  with an explicit ``target``, and ``_validate_relative_target`` permits ``"``
  and ``;``. So the test exports through a target containing both and asserts
  neither reaches the header.
* A **real STEP round trip**: the exported bytes are re-imported through the
  engine's own ``read_step_bytes`` and the volume is compared against the source
  BRep. G3's clause is that an exported STEP re-imports with matching volume, and
  §22.5's *"no metadata injected into STEP, STL, GLB or SVG"* is only worth
  stating if somebody checks the file is still a STEP afterwards.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops._exports import EXPORT_FORMATS
from hephaestus.core.project_store.artifact_kinds import recorded_kinds
from hephaestus.core.project_store.store import artifact_ref
from hephaestus.http.artifacts import KIND_MISMATCH_REASON
from hephaestus.http.exports import (
    DOCUMENT_SUFFIXES,
    EXPORT_CONTENT_TYPES,
    EXPORT_ROUTE_TOOLS,
    EXPORT_TOO_LARGE_REASON,
    REFUSED_EXPORT_ARGUMENTS,
    UNKNOWN_EXPORT_REASON,
)
from hephaestus.http.idempotency import KEY_REQUIRED_ROUTES
from hephaestus.testing.workspace import Workspace, uuid7, workspace

#: The ``laser_cut`` pack's declared kerf (``registries/dfm/laser_cut``), which
#: §22.7 says the panel displays and never lets a browser override.
PACK_KERF = 0.2

#: A part that declares a laser process, so the DFM pack resolves a kerf for it
#: without anyone asking — §22.1's "on the fixture the pack resolves 0.2 mm from
#: ``laser_cut`` without anyone asking".
PLATE = """_plate = Box(60.0, 40.0, 6.0) - Cylinder(6.0, 20.0)
_plate.label = "plate"
part.geometry = _plate

part.description = "A bored plate whose cut path must be kerf compensated"
part.process = "laser_cut"
part.stock_form = "sheet"
part.blank_size = "One 120 x 90 x 6 mm blank"
"""


@pytest.fixture
def web(tmp_path: Path) -> Iterator[Workspace]:
    """A built workspace with ``widget`` and a laser-cut ``plate``."""
    from hephaestus.testing.tools_fixture import scaffold as scaffold_tools_project

    root = tmp_path / "proj"
    scaffold_tools_project(root)
    (root / "parts" / "plate.py").write_text(PLATE, encoding="utf-8")
    with workspace(root, scaffold=False) as ws:
        for part in ("widget", "plate"):
            built = ws.post(f"/parts/{part}/build", json={}, key=uuid7())
            assert built.status_code == 200, built.text
        yield ws


def _pin(web: Workspace, part: str = "widget") -> str:
    """The part's current build ref — what the workspace pin holds (§4.5)."""
    return str(web.get(f"/parts/{part}/build").json()["artifact_ref"])


def _export(
    web: Workspace,
    *,
    part: str = "widget",
    key: str | None = None,
    **body: Any,
) -> Any:
    """``POST /parts/{part}/export`` with the pin the client would send."""
    payload: dict[str, Any] = {"artifact_ref": _pin(web, part), **body}
    return web.post(f"/parts/{part}/export", json=payload, key=uuid7() if key is None else key)


def _one_hash(document: Any) -> tuple[str, str]:
    """The single ``(rel_path, blob)`` of a one-output export result."""
    hashes = cast("dict[str, str]", document["export_hashes"])
    assert len(hashes) == 1, hashes
    return next(iter(hashes.items()))


def _download(web: Workspace, blob: str, **kwargs: Any) -> Any:
    return web.get(f"/exports/{blob}/bytes", **kwargs)


# --------------------------------------------------------------------------
# §22.2 — export is a mutation, and how it keys


def test_the_three_export_routes_require_an_idempotency_key(web: Workspace) -> None:
    """§22.2: all three join §2.3's first table, keyed like every other mutation."""
    for template in EXPORT_ROUTE_TOOLS:
        assert ("POST", template) in KEY_REQUIRED_ROUTES


def test_an_export_with_no_key_is_refused_and_creates_no_file(web: Workspace) -> None:
    """G10A: ``400 idempotency_key_required`` **with no file created**.

    The second half is the one worth asserting: §2.5's rung is "no execution",
    and a refusal raised after ``_commit_export`` had installed a create-only
    file would leave the retry colliding with a file nobody was told about.
    """
    response = web.post("/parts/widget/export", json={"artifact_ref": _pin(web), "format": "step"})
    assert response.status_code == 400, response.text
    assert response.json()["reason"] == "idempotency_key_required"
    exports_dir = web.root / ".heph" / "exports"
    assert not exports_dir.exists() or not list(exports_dir.iterdir())
    assert web.get("/parts/widget/exports").json()["exports"] == []


def test_the_same_key_twice_yields_one_file_and_replayed_true(web: Workspace) -> None:
    """G10A: "the same key twice yields one file and ``"replayed": true``".

    §2.5's REST ladder answers first — the second request never reaches dispatch
    — so the assertion is on the ledger's byte-for-byte replay plus the fact that
    ``.heph/exports/`` still holds exactly one file. Both layers agree by
    construction (§22.2); this pins that they do.
    """
    key = uuid7()
    first = _export(web, key=key, format="step")
    second = _export(web, key=key, format="step")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True
    assert second.headers["Idempotency-Replayed"] == "true"
    assert first.json()["export_hashes"] == second.json()["export_hashes"]
    assert len(list((web.root / ".heph" / "exports").iterdir())) == 1


def test_the_same_key_with_a_changed_format_is_key_payload_mismatch(web: Workspace) -> None:
    """G10A's third key clause. §22.2: no new key vocabulary is introduced —
    ``key_payload_mismatch`` is the string ``opstore/errors.py`` already raises
    and §2.4 already tabulates, and both key layers use it.
    """
    key = uuid7()
    assert _export(web, key=key, format="step").status_code == 200
    changed = _export(web, key=key, format="stl")
    assert changed.status_code == 409, changed.text
    assert changed.json()["reason"] == "key_payload_mismatch"


# --------------------------------------------------------------------------
# §22.1 / §22.5 — what the route will not accept


@pytest.mark.parametrize("value", [None, "__absent__"])
def test_a_null_or_absent_artifact_ref_is_refused_by_name(web: Workspace, value: Any) -> None:
    """§22.5's DECISION, enforced at the boundary rather than trusted.

    Absent and explicitly ``null`` are the same refusal because they are the same
    request: the tool's schema defaults ``artifact_ref`` to ``None``, so an
    omitted field reaches ``_freeze_export_source``'s resolve-at-export-time
    branch exactly as a written ``null`` does.
    """
    body: dict[str, Any] = {"format": "step"}
    if value is not None:
        body["artifact_ref"] = None if value == "__absent__" else value
    if value == "__absent__":
        body.pop("artifact_ref", None)
    response = web.post("/parts/widget/export", json=body, key=uuid7())
    assert response.status_code == 400, response.text
    assert response.json()["reason"] == "invalid_params"
    assert response.json()["field"] == "artifact_ref"


@pytest.mark.parametrize("field", REFUSED_EXPORT_ARGUMENTS)
def test_target_and_kerf_are_refused_by_name_not_ignored(web: Workspace, field: str) -> None:
    """§22.1: neither is a browser control, and both are refused rather than dropped.

    Ignoring ``target`` would mean the route *admits* a filesystem path from a
    browser and merely declines to act on it, which is not what §2.3 says. The
    refusal names the field so a client author is told which one, not merely that
    something was wrong.
    """
    value: Any = "sub/dir/out.step" if field == "target" else 0.3
    response = web.post(
        "/parts/widget/export",
        json={"artifact_ref": _pin(web), "format": "dxf", field: value},
        key=uuid7(),
    )
    assert response.status_code == 400, response.text
    assert response.json()["reason"] == "invalid_params"
    assert response.json()["refused"] == [field]


def test_a_failed_builds_checkpoint_ref_is_invalid_source(web: Workspace) -> None:
    """§22.7's first refusal row, by the engine's own name.

    A checkpoint is not a build: ``_freeze_export_source`` reads the ref's kind
    segment and refuses anything that is not ``build``. The panel disables its
    controls on this and says why (§22.7) rather than rendering an enabled button
    that will 4xx.
    """
    build_ref = _pin(web)
    checkpoint = artifact_ref("build-checkpoint", build_ref.split(":", 2)[2])
    response = web.post(
        "/parts/widget/export",
        json={"artifact_ref": checkpoint, "format": "step"},
        key=uuid7(),
    )
    assert response.status_code == 400, response.text
    assert response.json()["reason"] == "invalid_source"


def test_a_nested_sheet_with_no_declared_blank_refuses_by_the_engines_name(
    web: Workspace,
) -> None:
    """§22.7's ``blank_undeclared`` row, and the **engine's** string instead.

    LOUD, and pinned here so the divergence cannot be discovered by a client
    author instead: §22.7's table spells this ``blank_undeclared`` and the engine
    raises ``blank_unknown`` (``cad_ops/_exports.py::_resolve_blank``). §22.7's
    own rule decides it — *"Closed vocabulary; every string is the engine's"* —
    so the wire carries ``blank_unknown`` and the spec's table is what needs the
    one-word correction. ``widget`` declares no ``part.blank_size`` at all, which
    is exactly the state the row describes.
    """
    response = web.post(
        "/parts/widget/export",
        json={"artifact_ref": _pin(web), "format": "dxf", "layout": "nested_sheet"},
        key=uuid7(),
    )
    assert response.status_code == 400, response.text
    assert response.json()["reason"] == "blank_unknown"


# --------------------------------------------------------------------------
# §22.5 — the A/B half, which is what makes the export honest


def _publish_b(web: Workspace) -> str:
    """Publish a second build of ``widget`` and return its ref."""
    state_hash = web.get("/parts/widget/params").json()["state_hash"]
    changed = web.post(
        "/parts/widget/params",
        json={"values": {"width": 55.0}, "expected_state_hash": state_hash},
        key=uuid7(),
    )
    assert changed.status_code == 200, changed.text
    built = web.post("/parts/widget/build", json={}, key=uuid7())
    assert built.status_code == 200, built.text
    return _pin(web)


def test_the_pinned_ref_is_exported_after_a_newer_build_publishes(web: Workspace) -> None:
    """G10A's A/B clause: the export is A's geometry, not the current build's.

    Pin A, export STEP, publish B for the same part, re-export from the
    still-pinned A **with a fresh key** — a real second execution, not a ledger
    replay — and assert the file is still A. If the pin were being resolved at
    export time this call would produce B's geometry, which is exactly the silent
    fallback-to-current §22.5 exists to forbid.

    **DEVIATION from the letter of G10A, reported rather than worked around.**
    The gate says *"re-exports from the still-pinned A and asserts the same
    digest"*, and a same-digest assertion over a **fresh** execution is not
    satisfiable for any format, in either direction:

    * ``step`` and ``dxf`` are **not byte-deterministic**. OCCT stamps wall-clock
      time into the STEP ``FILE_NAME`` header (``FILE_NAME('Open CASCADE Shape
      Model','2026-08-28T13:43:10',…)``) and the DXF writer does the same, so two
      exports of one frozen artifact differ whenever they cross a second
      boundary. Measured, not assumed: ``stl``, ``gltf``/``glb``, ``3mf`` and
      ``svg`` are deterministic; ``step`` and ``dxf`` are not.
    * for the four that *are* deterministic, a fresh-key re-export produces
      identical bytes, hence the identical content-addressed stem, hence
      ``target_exists`` from ``_commit_export``'s create-only install — see
      :func:`test_an_identical_fresh_key_export_collides_with_its_own_first_file`.

    So the same-digest half is asserted where it is actually true and actually
    means something — the **replay** (below), which is what §22.2 says the key is
    for — and the pin half is asserted on geometry: same ``source_artifact_ref``,
    same re-imported volume as A, and a volume that differs from B's export. That
    is the clause's stated intent (*"the exported file must be the geometry on
    screen"*) discharged in full.
    """
    from hephaestus.geom.step_io import read_step_bytes

    pin_a = _pin(web)
    key_a = uuid7()
    first = _export(web, key=key_a, format="step").json()
    _, blob_a = _one_hash(first)
    volume_a = float(cast("Any", read_step_bytes(_download(web, blob_a).content)).volume)

    pin_b = _publish_b(web)
    assert pin_b != pin_a, "the B build must be a different artifact or the test is vacuous"

    again = web.post(
        "/parts/widget/export",
        json={"artifact_ref": pin_a, "format": "step"},
        key=uuid7(),
    )
    assert again.status_code == 200, again.text
    fresh = again.json()
    assert fresh["source_artifact_ref"] == pin_a
    _, blob_again = _one_hash(fresh)
    volume_again = float(cast("Any", read_step_bytes(_download(web, blob_again).content)).volume)
    assert volume_again == pytest.approx(volume_a, rel=1e-9)

    from_b = web.post(
        "/parts/widget/export", json={"artifact_ref": pin_b, "format": "step"}, key=uuid7()
    ).json()
    _, blob_b = _one_hash(from_b)
    volume_b = float(cast("Any", read_step_bytes(_download(web, blob_b).content)).volume)
    assert volume_b != pytest.approx(volume_a, rel=1e-6), (
        "B must be geometrically different or the A/B clause proves nothing"
    )

    # The same-digest half: the original key, presented after B published, still
    # replays A's exact bytes. This is the clause's letter, on the path §22.2
    # says carries it — "a dropped download is a replay that returns the
    # identical result document and the identical bytes".
    replayed = web.post(
        "/parts/widget/export",
        json={"artifact_ref": pin_a, "format": "step"},
        key=key_a,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True
    assert _one_hash(replayed.json())[1] == blob_a


def test_a_null_ref_export_is_not_reachable_from_the_client(web: Workspace) -> None:
    """G10A: *"a ``null``-ref export is not reachable from the client"*.

    The server half of that clause, which is where it is actually enforced: the
    route refuses before dispatch, so the resolve-at-export-time branch of
    ``_freeze_export_source`` has no caller on this surface **even if** a client
    were written to send one. The browser half — that no control in the panel can
    produce such a request — is ``web/e2e/export.spec.ts``.

    The proof it matters: with B published, a null-ref export would freeze B.
    """
    pin_a = _pin(web)
    _publish_b(web)
    refused = web.post(
        "/parts/widget/export", json={"artifact_ref": None, "format": "step"}, key=uuid7()
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["field"] == "artifact_ref"
    # …and the pin the client would have sent still exports, so the refusal is
    # about the missing ref rather than about the part being unexportable.
    ok = web.post(
        "/parts/widget/export", json={"artifact_ref": pin_a, "format": "step"}, key=uuid7()
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["source_artifact_ref"] == pin_a


def test_an_identical_fresh_key_export_collides_with_its_own_first_file(
    web: Workspace,
) -> None:
    """CORRECTION to §22.1, pinned so the panel keeps rendering the refusal.

    §22.1 says ``target_exists`` is *"**unreachable** from the browser by
    construction"* because the no-target stem is content-addressed. The
    construction produces the opposite: identical fields under two **fresh** keys
    produce identical bytes, hence the identical stem, hence ``O_CREAT|O_EXCL``
    refusing the second. It is unreachable only under §22.2's client discipline
    — one key per *submission*, and the retry button does not re-mint — which is
    a discipline, not a construction, so the refusal must be renderable.

    ``3mf`` is used because it is one of the four byte-deterministic formats
    (``_write_3mf`` fixes every zip entry's ``date_time``); the same call in
    ``step`` succeeds and produces a second, differently-stamped file.
    """
    pin = _pin(web)
    first = web.post(
        "/parts/widget/export", json={"artifact_ref": pin, "format": "3mf"}, key=uuid7()
    )
    assert first.status_code == 200, first.text
    second = web.post(
        "/parts/widget/export", json={"artifact_ref": pin, "format": "3mf"}, key=uuid7()
    )
    assert second.status_code == 409, second.text
    assert second.json()["reason"] == "target_exists"
    # One file, not two — the create-only install rolled nothing back because it
    # installed nothing.
    assert len(list((web.root / ".heph" / "exports").iterdir())) == 1


# --------------------------------------------------------------------------
# §22.3 — the download: authorization, headers, filename


def test_the_downloaded_bytes_hash_to_the_export_hashes_entry(web: Workspace) -> None:
    """G10A: the downloaded bytes' sha-256 equals the entry the route returned."""
    rel_path, blob = _one_hash(_export(web, format="step").json())
    response = _download(web, blob)
    assert response.status_code == 200, response.text
    assert f"sha256:{hashlib.sha256(response.content).hexdigest()}" == blob
    assert response.headers["ETag"] == blob
    assert response.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Type"].startswith("model/step")
    # …and the bytes on disk are the same bytes, so the blob is the file.
    assert (web.root / ".heph" / "exports" / rel_path).read_bytes() == response.content


def test_the_download_filename_is_derived_and_never_echoed(web: Workspace) -> None:
    """§22.3's 2026-08-28 TIGHTENING, against the input that motivated it.

    ``_validate_relative_target`` confines traversal while permitting ``"`` and
    ``;`` — the two characters that structure a ``Content-Disposition`` parameter
    list. The browser cannot send a ``target`` (that is refused above), but this
    route serves **any** blob a committed row names, and an agent can. So the
    export is produced through dispatch with a hostile target and the header is
    asserted to contain nothing of it.
    """
    hostile = 'evil";filename="owned.exe'
    document = web.dispatch(
        "export_part",
        {"name": "widget", "format": "step", "artifact_ref": _pin(web), "target": hostile},
        entry="export-hostile",
    )
    rel_path, blob = _one_hash(document)
    assert rel_path == hostile, "the engine still records the target it was given"

    response = _download(web, blob)
    assert response.status_code == 200, response.text
    disposition = response.headers["Content-Disposition"]
    assert 'filename="widget-' in disposition
    assert disposition.endswith('.step"')
    assert "owned.exe" not in disposition
    assert disposition.count('"') == 2, disposition
    # The recorded path is still reported — as JSON body text, where a quote is
    # inert and an operator can find the file on disk.
    listed = web.get("/parts/widget/exports").json()
    paths = [out["path"] for row in listed["exports"] for out in row["outputs"]]
    assert hostile in paths


def test_the_filename_carries_the_digest_and_the_format_extension(web: Workspace) -> None:
    """``<part>-<digest[:12]>.<ext>`` — both halves derived, neither echoed."""
    _, blob = _one_hash(_export(web, format="3mf").json())
    disposition = _download(web, blob).headers["Content-Disposition"]
    digest = blob.removeprefix("sha256:")[:12]
    assert disposition == f'attachment; filename="widget-{digest}.3mf"'


def test_a_blob_no_committed_row_names_is_unknown_export(web: Workspace) -> None:
    """§22.3's TIGHTENING: "Not 'stored'. Not 'pinned'."

    The build blob is stored, pinned and reachable from the open project — it
    passes every check ``GET /artifacts/{ref}/bytes`` applies — and it is still a
    404 here, because no committed ``tp_exports`` row names it. That gap between
    the two routes' authorizations *is* §22.3's design boundary.
    """
    _export(web, format="step")
    build_blob = _pin(web).split(":", 2)[2]
    assert web.runtime.store.blobs.has(build_blob)
    response = _download(web, build_blob)
    assert response.status_code == 404, response.text
    assert response.json()["reason"] == UNKNOWN_EXPORT_REASON


def test_a_frozen_rows_blob_is_not_served(web: Workspace) -> None:
    """A ``FROZEN`` row's blob is 404, not 200 (§22.3).

    The row is walked back to ``FROZEN`` directly, because the only way to reach
    that state with an installed file is a crash between ``_commit_export``'s
    install and its ``UPDATE`` — which is precisely the window the clause is
    about, and which no in-process test can produce honestly.
    """
    _, blob = _one_hash(_export(web, format="step").json())
    assert _download(web, blob).status_code == 200
    with web.runtime.store.db.transaction() as conn:
        conn.execute("UPDATE tp_exports SET state = 'FROZEN'")
    response = _download(web, blob)
    assert response.status_code == 404, response.text
    assert response.json()["reason"] == UNKNOWN_EXPORT_REASON
    assert web.get("/parts/widget/exports").json()["exports"] == []


def test_the_download_route_requires_the_bearer(web: Workspace) -> None:
    """§2.2 is not weakened by a route whose response is a file.

    The client's own defence — a `fetch` with the header, an object URL, and a
    token that never enters a URL — is §22.4's and is asserted in the browser.
    This is the server half: without the header there is no file.
    """
    _, blob = _one_hash(_export(web, format="step").json())
    assert _download(web, blob, token=None).status_code == 401


def test_a_large_export_is_refused_by_name_with_the_path(
    web: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§22.4's ceiling: a named refusal carrying the size and the CLI path.

    The threshold is a **server constant**, never a client guess, so lowering it
    is how the clause is exercised — the alternative is producing a 64 MiB
    export, which would be testing the filesystem.
    """
    rel_path, blob = _one_hash(_export(web, format="step").json())
    monkeypatch.setattr("hephaestus.http.exports.EXPORT_MAX_BYTES", 8)
    response = _download(web, blob)
    assert response.status_code == 413, response.text
    body = response.json()
    assert body["reason"] == EXPORT_TOO_LARGE_REASON
    assert body["limit_bytes"] == 8
    assert body["bytes"] > 8
    assert body["path"] == str(Path(".heph") / "exports" / rel_path)


# --------------------------------------------------------------------------
# §22.10 — the relabelled-ref clause, which proves §19.24 landed


def test_the_bytes_route_refuses_the_export_ref_and_a_relabelled_build_ref(
    web: Workspace,
) -> None:
    """G10A's relabelled-ref clause, from the surface that publishes the hash.

    §22.3's ORDERING CONSTRAINT is the reason this test lives beside the export
    routes rather than only beside the artifact routes: ``export_hashes`` in a
    response body is what turns "nobody knows the hash" into "every client knows
    the hash", so the moment §22 ships, the relabelling attack has an input. Both
    refusals are asserted from a hash this very response handed out.
    """
    _, blob = _one_hash(_export(web, format="step").json())
    assert recorded_kinds(web.runtime.store, blob) == frozenset({"export"})

    by_kind = web.get(f"/artifacts/{artifact_ref('export', blob)}/bytes")
    assert by_kind.status_code == 404, by_kind.text
    assert by_kind.json()["reason"] == "unknown_artifact_kind_for_route"

    relabelled = web.get(f"/artifacts/{artifact_ref('build', blob)}/bytes")
    assert relabelled.status_code == 404, relabelled.text
    assert relabelled.json()["reason"] == KIND_MISMATCH_REASON

    # …and the one route that *is* authorized for it still serves it, so the two
    # refusals above are about the surface and not about the bytes being gone.
    assert _download(web, blob).status_code == 200


# --------------------------------------------------------------------------
# §22.5 — provenance, and a real round trip


def test_an_exported_step_re_imports_with_a_matching_volume(web: Workspace) -> None:
    """G3's clause, over the bytes this surface actually serves.

    Re-imported through the engine's own ``read_step_bytes`` — the reader
    ``import_step`` uses — and compared with the volume of the BRep the export
    froze. §22.5's *"STEP, STL, GLB and SVG carry nothing, and nothing is
    injected"* is only worth stating if something checks the file is still a
    readable STEP of the same solid afterwards.
    """
    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.geom.step_io import read_step_bytes

    pin = _pin(web)
    _, blob = _one_hash(_export(web, format="step").json())
    exported = _download(web, blob).content

    source = load_brep_shape(web.runtime.store.blobs.get(pin.split(":", 2)[2]))
    reimported = read_step_bytes(exported, source="widget.step")
    nominal = float(cast("Any", source).volume)
    round_tripped = float(cast("Any", reimported).volume)
    assert nominal > 0.0
    assert round_tripped == pytest.approx(nominal, rel=1e-9)


def test_the_result_carries_the_provenance_that_travels_with_the_file(
    web: Workspace,
) -> None:
    """§22.5's layer 1: the result document **is** the audit row.

    ``source_artifact_ref``, ``source_input_hashes``, ``export_hashes`` and
    ``paths`` — and the projection replays them, so a client that lost the
    response can still say what produced the file.
    """
    pin = _pin(web)
    document = _export(web, format="step").json()
    assert document["source_artifact_ref"] == pin
    assert document["source_input_hashes"]["script"]
    assert document["paths"] == [str(Path(".heph") / "exports" / _one_hash(document)[0])]

    row = web.get("/parts/widget/exports").json()["exports"][0]
    assert row["source_artifact_ref"] == pin
    assert row["source_input_hashes"] == document["source_input_hashes"]
    assert [out["blob"] for out in row["outputs"]] == list(document["export_hashes"].values())


def test_no_provenance_sidecar_is_written_beside_the_file(web: Workspace) -> None:
    """§22.5's layer 3 DECISION, asserted rather than assumed.

    The ``tp_exports`` row is the record. A ``.provenance.json`` beside the file
    would be a second provenance store that can drift from it, and
    ``_commit_export``'s rollback would have to know which of its files is not a
    deliverable.
    """
    rel_path, _ = _one_hash(_export(web, format="step").json())
    installed = sorted(p.name for p in (web.root / ".heph" / "exports").iterdir())
    assert installed == [rel_path]


# --------------------------------------------------------------------------
# §22.6 — GC, pinning, and the retention obligation the panel must show


def test_gc_leaves_the_export_and_its_source_build_reachable(web: Workspace) -> None:
    """G10A's last clause: a collect leaves both blobs reachable.

    §22.6's facts, exercised: every output blob is an unconditional GC root and
    is ``link``ed to its source build's blob, and ``reachable()`` is pins closed
    transitively over links — so **an export permanently protects the build it
    came from**. That is the intended shape and it is what makes re-exporting an
    old pin reproducible.
    """
    build_blob = _pin(web).split(":", 2)[2]
    _, export_blob = _one_hash(_export(web, format="step").json())

    web.runtime.store.gc.collect()

    reachable = web.runtime.store.gc.reachable()
    assert export_blob in reachable
    assert build_blob in reachable
    assert export_blob in web.runtime.store.gc.pins()
    assert web.runtime.store.blobs.has(export_blob)
    assert web.runtime.store.blobs.has(build_blob)
    assert _download(web, export_blob).status_code == 200


def test_the_projection_carries_the_running_byte_total_and_says_there_is_no_unpin(
    web: Workspace,
) -> None:
    """§22.6's second and third consequences, as facts the panel renders.

    The running total is the server's number (§1), and ``unpin_available`` is the
    server's policy rather than a sentence the client invents: *"Exports are kept
    until they are unpinned from the command line. This workspace does not delete
    them."*
    """
    empty = web.get("/parts/widget/exports").json()
    assert empty == {
        "status": "ok",
        "part": "widget",
        "exports": [],
        "total_bytes": 0,
        "unpin_available": False,
        "max_download_bytes": empty["max_download_bytes"],
    }

    step = _export(web, format="step").json()
    stl = _export(web, format="stl").json()
    listed = web.get("/parts/widget/exports").json()
    assert len(listed["exports"]) == 2
    assert [row["format"] for row in listed["exports"]] == ["step", "stl"]
    per_file = {out["blob"]: out["bytes"] for row in listed["exports"] for out in row["outputs"]}
    assert listed["total_bytes"] == sum(per_file.values())
    for document in (step, stl):
        for blob in cast("dict[str, str]", document["export_hashes"]).values():
            assert per_file[blob] == len(_download(web, blob).content)


def test_the_projection_is_scoped_to_its_part(web: Workspace) -> None:
    """A part's history is that part's. ``bracket`` is built and never exported."""
    _export(web, format="step")
    assert web.get("/parts/bracket/exports").json()["exports"] == []


# --------------------------------------------------------------------------
# §22.1 / §22.3 — every format and layout the engine actually supports


def test_every_format_the_engine_writes_has_a_content_type(web: Workspace) -> None:
    """§19.36's drift test, cheap half.

    *"a format added without a content type is a test failure, not an
    ``application/octet-stream``"*. Keyed by the **suffix** each format writes,
    because ``gltf`` writes ``.glb`` and the two document generators have outputs
    rather than formats.
    """
    assert set(EXPORT_FORMATS.values()) <= set(EXPORT_CONTENT_TYPES)
    assert set(EXPORT_CONTENT_TYPES) >= DOCUMENT_SUFFIXES
    assert set(EXPORT_CONTENT_TYPES) == set(EXPORT_FORMATS.values()) | DOCUMENT_SUFFIXES


@pytest.mark.parametrize("fmt", sorted(EXPORT_FORMATS))
def test_every_offered_format_round_trips_through_both_routes(web: Workspace, fmt: str) -> None:
    """§22.1's DECISION: all six formats are offered, and each really works.

    "There is no curated subset, because a subset needs a rule and every
    available rule is arbitrary." A parametrized test is the cheapest way to make
    that a fact rather than a claim: a seventh format added to ``EXPORT_FORMATS``
    without a content type or a working writer fails here.
    """
    document = _export(web, part="plate", format=fmt).json()
    assert document.get("status") != "error", document
    rel_path, blob = _one_hash(document)
    assert rel_path.endswith(f".{EXPORT_FORMATS[fmt]}")
    response = _download(web, blob)
    assert response.status_code == 200, response.text
    assert response.headers["Content-Type"].startswith(
        EXPORT_CONTENT_TYPES[EXPORT_FORMATS[fmt]].split(";")[0]
    )
    assert len(response.content) > 0


def test_the_kerf_the_dfm_pack_resolved_is_reported_on_a_cut_file(web: Workspace) -> None:
    """G10A's kerf clause: ``kerf.source == "dfm"`` and ``applied_mm == 0.2``.

    Nobody asked for a kerf; ``plate`` declares ``process = "laser_cut"`` and the
    pack answers. §22.1 refuses a kerf control in the browser precisely so the
    number a cut file is compensated by is the process pack's — the panel
    **displays** this decision rather than offering to override it.
    """
    document = _export(web, part="plate", format="dxf").json()
    kerf = cast("dict[str, Any]", document["kerf"])
    assert kerf["source"] == "dfm"
    assert kerf["applied_mm"] == pytest.approx(PACK_KERF)
    assert kerf["process"] == "laser_cut"


def test_a_nested_sheet_layout_exports_through_the_same_routes(web: Workspace) -> None:
    """§22.8: nested sheet is a ``layout`` argument of the same tool, not a
    separate capability — same WAL, same pin, same confinement, same download.
    """
    document = _export(
        web,
        part="plate",
        format="dxf",
        layout="nested_sheet",
        blank={"width_mm": 200.0, "height_mm": 150.0},
    ).json()
    assert document.get("status") != "error", document
    _, blob = _one_hash(document)
    assert _download(web, blob).status_code == 200
    assert web.get("/parts/plate/exports").json()["exports"][0]["layout"] == "nested_sheet"


# --------------------------------------------------------------------------
# §22.8 — documents and drawings ship on the same path


def test_a_document_downloads_as_two_typed_files(web: Workspace) -> None:
    """§22.8: *"literally the same ``wal_export`` code path"* — and the suffixes
    it emits are the ones :data:`DOCUMENT_SUFFIXES` claims, which is the other
    half of §19.36's drift test.
    """
    response = web.post(
        "/parts/widget/doc",
        json={"artifact_ref": _pin(web), "kind": "bom"},
        key=uuid7(),
    )
    assert response.status_code == 200, response.text
    hashes = cast("dict[str, str]", response.json()["export_hashes"])
    suffixes = {path.rsplit(".", 1)[1] for path in hashes}
    assert suffixes == {"md", "json"}
    assert not suffixes - DOCUMENT_SUFFIXES
    for path, blob in hashes.items():
        served = _download(web, blob)
        assert served.status_code == 200, served.text
        expected = EXPORT_CONTENT_TYPES[path.rsplit(".", 1)[1]]
        assert served.headers["Content-Type"].startswith(expected.split(";")[0])
    body = json.loads(_download(web, hashes[next(p for p in hashes if p.endswith(".json"))]).text)
    assert isinstance(body, dict)


@pytest.mark.slow
def test_a_drawing_downloads_as_two_typed_files(web: Workspace) -> None:
    """The third route, and the suffixes it really emits (§19.36).

    Marked slow because a drawing renders views; it is the only test here that
    drives the renderer, and its subject is the *content type map*, not the
    sheet.
    """
    response = web.post(
        "/parts/widget/drawing",
        json={"artifact_ref": _pin(web), "kind": "dimensioned"},
        key=uuid7(),
    )
    assert response.status_code == 200, response.text
    hashes = cast("dict[str, str]", response.json()["export_hashes"])
    suffixes = {path.rsplit(".", 1)[1] for path in hashes}
    assert suffixes == {"pdf", "svg"}
    assert not suffixes - DOCUMENT_SUFFIXES
    for path, blob in hashes.items():
        served = _download(web, blob)
        assert served.status_code == 200, served.text
        assert served.headers["Content-Type"].startswith(
            EXPORT_CONTENT_TYPES[path.rsplit(".", 1)[1]].split(";")[0]
        )
        # §22.9 exclusion 6: an SVG is never served inline, on any route.
        assert served.headers["Content-Disposition"].startswith("attachment;")
        assert served.headers["X-Content-Type-Options"] == "nosniff"
