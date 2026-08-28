# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§2.6 — two artifact surfaces, two authorizations, one enumerated byte route.

``INTERFACE.md`` §2.6 and §19 item 14. The two claims under test:

* the text route and the ``read_artifact`` tool page the **same** blob through
  the **same** boundary contract under two different principal checks — G5.8's
  word *losslessly* makes any divergence a gate failure;
* the bytes route is closed **by enumeration, not by set membership**, and
  ``export`` is refused. An earlier draft scoped it to
  ``BINARY_ARTIFACT_KINDS``, of which ``export`` is a member in the shipped code
  (``cad_ops/_artifacts.py``:22-34) — so any bearer-holding browser could have
  fetched export bytes, and §15.17's "no export path" would have been a
  statement about which buttons exist rather than about what the server serves.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.agent_bridge.cad_ops._artifacts import BINARY_ARTIFACT_KINDS
from hephaestus.core.artifacts import page_text
from hephaestus.core.project_store.store import artifact_ref
from hephaestus.http.artifacts import BYTES_ROUTE_KINDS, REFUSED_BYTES_KINDS
from hephaestus.testing.workspace import Workspace, uuid7, workspace
from opstore.hashing import sha256_bytes


def _store_blob(web: Workspace, kind: str, data: bytes) -> str:
    """Put ``data`` in the open project's store and return its ``kind`` ref.

    The bytes route's authorization *is* reachability from the open project's
    opstore (§2.2), so a test about which kinds it serves has to put real blobs
    there rather than fabricate refs.
    """
    web.runtime.store.blobs.put(data)
    return artifact_ref(kind, sha256_bytes(data))


def test_export_kind_is_refused_by_the_bytes_route(tmp_path: Path) -> None:
    """§19 item 14's named pytest: an ``export`` ref is refused.

    404 ``unknown_artifact_kind_for_route``, and the blob is genuinely present —
    so the refusal is about the *kind*, not about the ref failing to resolve.
    """
    with workspace(tmp_path / "proj") as web:
        ref = _store_blob(web, "export", b"solid exported\n")
        assert web.runtime.store.blobs.has(ref.split(":", 2)[2])
        response = web.get(f"/artifacts/{ref}/bytes")
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_artifact_kind_for_route"
    assert response.json()["kind"] == "export"


def test_the_bytes_route_is_not_scoped_to_binary_artifact_kinds(tmp_path: Path) -> None:
    """The enumeration and the frozenset are deliberately *different* sets.

    This is the regression the enumeration exists to prevent: if someone ever
    "simplifies" the route to ``kind in BINARY_ARTIFACT_KINDS``, ``export``
    becomes servable and this test is the thing that notices.
    """
    assert "export" in BINARY_ARTIFACT_KINDS
    assert "export" not in BYTES_ROUTE_KINDS
    assert REFUSED_BYTES_KINDS <= BINARY_ARTIFACT_KINDS - BYTES_ROUTE_KINDS


@pytest.mark.parametrize("kind", sorted(BYTES_ROUTE_KINDS))
def test_every_enumerated_kind_is_served_with_immutable_caching(tmp_path: Path, kind: str) -> None:
    """Each enumerated kind serves its exact stored bytes, ``ETag`` = the ref.

    ``Cache-Control: immutable`` is honest rather than optimistic because refs
    are content-addressed, and the bytes are asserted **identical** because §2.6
    forbids any transformation: no re-encode, no resample, no colour-profile
    insertion, no compression change. The palette bijection G5.10 depends on
    survives only if these are the ``encode_png`` bytes.
    """
    payload = f"bytes-for-{kind}".encode() + bytes(range(256))
    with workspace(tmp_path / "proj") as web:
        ref = _store_blob(web, kind, payload)
        response = web.get(f"/artifacts/{ref}/bytes")
    assert response.status_code == 200, response.text
    assert response.content == payload
    assert response.headers["ETag"] == ref
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_an_unstored_ref_is_unknown_artifact_not_a_leak(tmp_path: Path) -> None:
    """§2.2: an artifact ref is a **project-scoped** capability, nothing more.

    A ref minted in another project simply is not in this store, so the answer is
    404 ``unknown_artifact`` — the same answer a nonexistent ref gets, which is
    what stops the route from being a cross-project existence oracle.
    """
    with workspace(tmp_path / "proj") as web:
        ref = artifact_ref("render", sha256_bytes(b"not stored here"))
        response = web.get(f"/artifacts/{ref}/bytes")
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_artifact"


def test_a_malformed_ref_is_invalid_ref(tmp_path: Path) -> None:
    """The same reason ``cad_ops`` raises, because it is the same malformation."""
    with workspace(tmp_path / "proj") as web:
        response = web.get("/artifacts/not-a-ref/meta")
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_ref"


def test_text_route_and_read_artifact_tool_page_identically(tmp_path: Path) -> None:
    """§2.6 / §19 item 5: one boundary contract, two authorizations.

    Paged to the end in lockstep. Equality at every cursor is the assertion that
    a second implementation would eventually break, and "losslessly" is a claim
    about the whole sequence rather than about the first page.
    """
    with workspace(tmp_path / "proj") as web:
        ref = next(
            p["snapshot_ref"] for p in web.get("/parts").json()["parts"] if p["name"] == "widget"
        )
        offset = 0
        pages: list[str] = []
        while True:
            route = web.get(
                f"/artifacts/{ref}/text",
                params={"offset_bytes": str(offset), "max_bytes": "17"},
            ).json()
            tool = web.dispatch(
                "read_artifact",
                {"ref": ref, "offset_bytes": offset, "max_bytes": 17},
                entry=f"page-{offset}",
            )
            assert route["content"] == tool["content"]
            assert route["truncated"] == tool["truncated"]
            assert route.get("next_offset_bytes") == tool.get("next_offset_bytes")
            pages.append(route["content"])
            if not route["truncated"]:
                break
            offset = route["next_offset_bytes"]
        blob = web.runtime.store.blobs.get(ref.split(":", 2)[2])
    assert "".join(pages).encode("utf-8") == blob


def test_a_non_boundary_offset_is_refused_without_being_normalized(tmp_path: Path) -> None:
    """§2.6: ``invalid_utf8_offset`` — **without normalizing** the offset.

    Normalizing a bad cursor is how a caller silently loses bytes, so the
    refusal reports the offset *as presented* and the client has to fix its own
    arithmetic.
    """
    multibyte = "é" * 40
    with workspace(tmp_path / "proj") as web:
        ref = _store_blob(web, "mask-legend", multibyte.encode("utf-8"))
        response = web.get(f"/artifacts/{ref}/text", params={"offset_bytes": "1"})
    assert response.status_code == 400
    body = response.json()
    assert body["reason"] == "invalid_utf8_offset"
    assert body["offset_bytes"] == 1  # as presented, not walked back to 0


def test_the_pager_always_makes_progress_on_a_single_oversized_code_point() -> None:
    """The extracted contract, at its sharpest point.

    A page whose byte budget cannot hold one code point extends over exactly one
    rather than returning nothing — otherwise a cursor would stall forever and
    "pages losslessly" would be false for any text with a multi-byte character.
    """
    blob = "€".encode()  # three bytes
    page = page_text(blob, 0, 1)
    assert page["content"] == "€"
    assert page["truncated"] is False


def test_meta_names_which_content_route_a_ref_may_be_read_through(tmp_path: Path) -> None:
    """``links`` is the server's answer, so the client carries no kind list."""
    with workspace(tmp_path / "proj") as web:
        text_ref = next(
            p["snapshot_ref"] for p in web.get("/parts").json()["parts"] if p["name"] == "widget"
        )
        png_ref = _store_blob(web, "render", b"\x89PNG\r\n\x1a\n" + bytes(64))
        export_ref = _store_blob(web, "export", b"solid\n")

        text_meta = web.get(f"/artifacts/{text_ref}/meta").json()
        png_meta = web.get(f"/artifacts/{png_ref}/meta").json()
        export_meta = web.get(f"/artifacts/{export_ref}/meta").json()

    assert set(text_meta["links"]) == {"text"}
    assert text_meta["mime_type"] == "text/x-python"
    assert set(png_meta["links"]) == {"bytes"}
    assert png_meta["mime_type"] == "image/png"
    # An export ref resolves and reports its size, and is offered NEITHER route:
    # the refusal is about what the server will serve, not about what exists.
    assert export_meta["links"] == {}
    assert export_meta["total_bytes"] == len(b"solid\n")


def test_gltf_route_never_returns_an_unlinked_glb(tmp_path: Path) -> None:
    """§5.1: the route never returns an unlinked GLB.

    REPOINTED, not weakened: §19 item 12 has landed. When this test was written,
    minting the selection bundle for a build ref had no production caller, so the
    only honest answer for a build ref was a **named absence** (404
    ``gltf_not_published``) rather than a synthesized unlinked GLB. The route now
    mints — ``GET /artifacts/{ref}/gltf`` "resolves, or publishes on demand, the
    selection bundle for that exact build ref … and publishes the GLB under the
    existing ``gltf`` artifact kind" — so the same clause is asserted against the
    answer the spec actually calls for: a GLB that **is** linked.

    The clause's other half — an unlinked GLB is refused rather than served —
    lives with the rest of the geometry wire in ``test_http_gltf.py``, over the
    six-solid public fixture §5.2 requires.
    """
    from hephaestus.core.render.bundle import resolve_selection
    from hephaestus.core.render.gltf import validate_gltf

    with workspace(tmp_path / "proj") as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        build_ref = web.get("/parts/widget/build").json()["artifact_ref"]
        response = web.get(f"/artifacts/{build_ref}/gltf")
        assert response.status_code == 200, response.text
        validation = validate_gltf(response.content)
        assert validation.bundle_ref is not None
        assert validation.source_artifact_ref == build_ref
        # The link is not merely present: it resolves, against this exact build.
        resolution = resolve_selection(
            web.runtime.store, validation.bundle_ref, expected_source_artifact_ref=build_ref
        )
    assert resolution.source_artifact_ref == build_ref
    assert response.headers["ETag"].startswith("artifact:gltf:")
