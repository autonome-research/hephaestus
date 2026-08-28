# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Two artifact surfaces, two authorizations (``INTERFACE.md`` §2.6).

``read_artifact`` is a **model-facing tool** whose ``ref`` is a capability scoped
to an authorized Pi session, and it refuses binary artifacts outright ("binary
artifacts return metadata and must be consumed by their dedicated render/export
path"). The browser is neither a Pi session nor satisfied by metadata. Hence two
routes and one extraction.

**Authorization for both** is ``WorkspacePrincipal`` + reachability from the open
project's opstore (§2.2) — a *project-scoped capability*, a different model from
the session-scoped tool capability, and said out loud because G5.8 forces exactly
that divergence. A ref must resolve in the open project's store and **nothing
else authorizes it**.

**Text** — ``GET /artifacts/{ref}/text?offset_bytes=``. The UTF-8 boundary
contract is :func:`hephaestus.core.artifacts.page_text`, called by both the tool
and this route. Mission rule 6 forbids reimplementation and G5.8's word
*losslessly* makes any divergence a gate failure.

**Bytes** — ``GET /artifacts/{ref}/bytes``. The exact stored bytes, and the route
is closed **by enumeration, not by set membership** (§19 item 14). See
:data:`BYTES_ROUTE_KINDS` for why that distinction is the whole point.

**No image transformation** (§2.6 TIGHTENING, binds G5.10): no re-encode, no
resample, no colour-profile insertion, no compression change. The palette
bijection (``id_to_rgb``, 24-bit big-endian ``n+1``, ``BACKGROUND_RGB = (0,0,0)``
never a valid occurrence colour) survives only if the bytes are the
``encode_png`` bytes. This module reads a blob and writes it out; there is
nowhere for a transformation to hide.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from hephaestus.agent_bridge.cad_ops._artifacts import TEXT_ARTIFACT_MIME
from hephaestus.core.artifacts import page_text
from hephaestus.core.project_store.store import blob_hash_of_ref

from opstore import OpStore

from .errors import HttpRefusal

__all__ = [
    "BUILD_REF_KINDS",
    "BYTES_ROUTE_KINDS",
    "GLTF_KIND",
    "GLTF_ROUTE_KINDS",
    "REFUSED_BYTES_KINDS",
    "artifact_bytes",
    "artifact_kind",
    "artifact_meta",
    "artifact_text_page",
    "mime_for_kind",
]

#: ``INTERFACE.md`` §2.6 TIGHTENING (binds §15.17's refusal, which was otherwise
#: decorative). ``GET /artifacts/{ref}/bytes`` serves **exactly** these kinds.
#: Every other kind is a 404 ``unknown_artifact_kind_for_route``.
#:
#: WHY this is enumeration and not membership: an earlier draft scoped the route
#: to ``BINARY_ARTIFACT_KINDS``, and ``export`` is a member of that frozenset in
#: the shipped code (``cad_ops/_artifacts.py``:22-34). Any bearer-holding browser
#: could therefore have fetched export bytes from the workspace, which would have
#: made "no export path" a statement about which buttons exist rather than about
#: what the server will serve. A refusal a route quietly contradicts is worse
#: than no refusal, because a reader stops looking.
#:
#: ``selection-crop`` (§12.5) is on the list because Stage 5 mints it. There is
#: no ``selection-pass`` kind — the three pass layers are ``selection-solid``,
#: ``selection-face``, ``selection-edge``.
BYTES_ROUTE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "build",
        "build-checkpoint",
        "render",
        "gltf",
        "selection-solid",
        "selection-face",
        "selection-edge",
        "selection-preview",
        "selection-crop",
    }
)

#: The artifact kind a published GLB is stored under (``INTERFACE.md`` §5.1).
GLTF_KIND: Final[str] = "gltf"

#: The build kinds ``GET /artifacts/{ref}/gltf`` mints a GLB *from*, enumerated.
#: ``build`` is a part's published build artifact; ``build-checkpoint`` is the
#: last-good checkpoint of a failed build, which ``inspect_part(last_good=True)``
#: already renders and which the workspace pins the same way. Nothing else is a
#: build, and a ref of any other kind is not a candidate for a viewport.
BUILD_REF_KINDS: Final[frozenset[str]] = frozenset({"build", "build-checkpoint"})

#: Everything the gltf route accepts: a build to mint from, or a GLB to re-serve
#: (the second only after its bundle link is re-resolved — §12.3). Closed by
#: enumeration on the same principle as :data:`BYTES_ROUTE_KINDS`: a kind absent
#: here is a 404, never a best effort.
GLTF_ROUTE_KINDS: Final[frozenset[str]] = BUILD_REF_KINDS | {GLTF_KIND}

#: Named explicitly rather than left to fall out of the enumeration: ``export``
#: is *the* kind this route refuses, and the pytest that proves it submits an
#: ``export`` ref (§19 item 14). A constant makes the refusal greppable from the
#: test as well as from the route.
REFUSED_BYTES_KINDS: Final[frozenset[str]] = frozenset({"export"})

#: Content types for the kinds the bytes route serves. Every kind of
#: :data:`BYTES_ROUTE_KINDS` has a row; the fallback exists only for a kind added
#: to that set without a type, which the enumeration test catches.
_BYTES_MIME: Final[dict[str, str]] = {
    "build": "model/step",
    "build-checkpoint": "model/step",
    "render": "image/png",
    "gltf": "model/gltf-binary",
    "selection-solid": "image/png",
    "selection-face": "image/png",
    "selection-edge": "image/png",
    "selection-preview": "image/png",
    "selection-crop": "image/png",
}


def artifact_kind(ref: str) -> str:
    """The kind segment of ``artifact:<kind>:<alg>:<hash>``.

    A ref that is not an artifact ref at all is ``invalid_ref`` — the same
    reason ``cad_ops`` raises, because it is the same malformation.
    """
    parts = ref.split(":")
    if len(parts) != 4 or parts[0] != "artifact":
        raise HttpRefusal(400, "invalid_ref", f"{ref!r} is not an artifact reference")
    return parts[1]


def _blob(store: OpStore, ref: str) -> bytes:
    """The stored bytes for ``ref``, or the §2.2 project-scoped refusal.

    This *is* the authorization: an artifact ref is a project-scoped capability
    for the web principal, so "reachable from the open project's opstore" is the
    whole check. A ref minted in another project simply is not here.
    """
    blob = blob_hash_of_ref(ref)
    if not store.blobs.has(blob):
        raise HttpRefusal(
            404, "unknown_artifact", f"artifact {ref} is not stored in the open project"
        )
    return store.blobs.get(blob)


def mime_for_kind(kind: str) -> str:
    """``Content-Type`` for one artifact kind, text kinds included."""
    text = TEXT_ARTIFACT_MIME.get(kind)
    if text is not None:
        return text
    return _BYTES_MIME.get(kind, "application/octet-stream")


def artifact_meta(store: OpStore, ref: str) -> dict[str, Any]:
    """``GET /artifacts/{ref}/meta`` — ``{kind, mime_type, total_bytes, sha256, links}``.

    ``links`` names which of the two content routes this ref may be read
    through, so the client branches on the server's answer instead of on a kind
    list it would otherwise have to carry (and drift from).
    """
    kind = artifact_kind(ref)
    data = _blob(store, ref)
    links: dict[str, str] = {}
    if kind in BYTES_ROUTE_KINDS:
        links["bytes"] = f"/api/v1/artifacts/{ref}/bytes"
    if kind in TEXT_ARTIFACT_MIME or _decodes_utf8(kind, data):
        links["text"] = f"/api/v1/artifacts/{ref}/text"
    if kind in GLTF_ROUTE_KINDS:
        # The third content route (§5.1). Advertised here for the same reason
        # the other two are: the client branches on the server's answer instead
        # of carrying a kind list of its own to drift from. A build ref offers
        # both `bytes` (its stored BREP) and `gltf` (the viewport's geometry),
        # and they are different artifacts, so both links are named.
        links["gltf"] = f"/api/v1/artifacts/{ref}/gltf"
    return {
        "status": "ok",
        "kind": kind,
        "mime_type": mime_for_kind(kind),
        "total_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "links": links,
    }


def artifact_text_page(
    store: OpStore, ref: str, offset_bytes: int, max_bytes: int
) -> dict[str, Any]:
    """``GET /artifacts/{ref}/text`` — the shared UTF-8 pager under the web principal.

    The principal check is the caller's (``WorkspacePrincipal`` + reachability,
    applied by :func:`_blob`); the boundary contract is
    :func:`hephaestus.core.artifacts.page_text`, which the ``read_artifact`` tool
    also calls under *its* different check. One contract, two authorizations.

    A ref whose bytes are not UTF-8 is refused rather than mangled: the text
    route has nothing honest to return for a PNG, and returning empty content
    with a 200 would read as "this artifact is empty".
    """
    kind = artifact_kind(ref)
    data = _blob(store, ref)
    if kind not in TEXT_ARTIFACT_MIME and not _decodes_utf8(kind, data):
        raise HttpRefusal(
            404,
            "unknown_artifact_kind_for_route",
            f"artifact kind {kind!r} is not text; read it through /bytes",
        )
    page = page_text(data, offset_bytes, max_bytes)
    if "error" in page:
        raise HttpRefusal(
            400,
            str(page["error"]),
            f"offset_bytes={offset_bytes} is not a code-point boundary of {ref}",
            data={k: v for k, v in page.items() if k != "error"},
        )
    return {"status": "ok", "mime_type": mime_for_kind(kind), **page}


def artifact_bytes(store: OpStore, ref: str) -> tuple[bytes, str]:
    """``GET /artifacts/{ref}/bytes`` — exact stored bytes, no transformation.

    Closed **by enumeration** (:data:`BYTES_ROUTE_KINDS`): every other kind,
    ``export`` first among them, is a 404 ``unknown_artifact_kind_for_route``.
    The refusal is raised *before* the blob is read, so a refused kind never even
    loads its bytes into this process.
    """
    kind = artifact_kind(ref)
    if kind not in BYTES_ROUTE_KINDS:
        raise HttpRefusal(
            404,
            "unknown_artifact_kind_for_route",
            f"artifact kind {kind!r} is not served by this route",
            data={"kind": kind, "served": sorted(BYTES_ROUTE_KINDS)},
        )
    return _blob(store, ref), mime_for_kind(kind)


def _decodes_utf8(kind: str, data: bytes) -> bool:
    """Whether an *unknown* kind's blob is model-readable text.

    Mirrors ``read_artifact``: a kind with no declared mime type is text only if
    its bytes decode. Known binary kinds never reach this — they are excluded by
    name, not by a decode attempt that a lucky byte sequence could pass.
    """
    if kind in BYTES_ROUTE_KINDS or kind in REFUSED_BYTES_KINDS:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
