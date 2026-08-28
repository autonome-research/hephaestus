# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``GET /artifacts/{ref}/gltf`` — the geometry wire (``INTERFACE.md`` §5.1).

The viewport loads this route for the **pinned** build. What comes back is the
existing ``core/render/gltf.py`` output — one mesh per solid, one primitive per
face, ``extras`` carrying selection IDs, descriptors and each solid's
``explode_offset``, and ``asset.extras`` carrying ``selection_bundle_ref`` /
``source_artifact_ref`` / ``selection_table_ref``. Model, browser raycast, and
tests therefore share one namespace with no new format.

**This module holds no geometry.** It names a ref, enumerates the kinds the
route accepts, and maps the engine's refusal onto §2.4's envelope; the producing
half is :class:`hephaestus.agent_bridge.cad_ops.GeometryOps` over
:mod:`hephaestus.core.render.gltf_publish`. That split is not fastidiousness: the
GLB's IDs, its bundle link and its explode displacements are every one of them
values on §1's closed list, and ``server/http`` reaches engine values through the
same ``CadOps`` seam the MCP server and the bridge ride — never around it.

**The route never returns an unlinked GLB** (§5.1, §12.3). Two dispositions:

* a **build** ref (or a last-good **build-checkpoint**) is resolved-or-minted,
  and the producer verifies the bundle link before it stores a byte — so an
  unlinked GLB is never minted, let alone served;
* an explicit **gltf** ref is served only after its ``asset.extras`` bundle link
  is re-resolved against the build it names. §12.3 calls this the *second line of
  defence* and requires both to be tested; this is the second.

Every other artifact kind is a 404 ``unknown_artifact_kind_for_route`` — the same
refusal, and the same enumerated (not membership-derived) discipline, that
:mod:`hephaestus.http.artifacts` applies to the bytes route.
"""

from __future__ import annotations

from typing import Final

from hephaestus.agent_bridge.cad_ops import CadOpError, PublishedGltf

from .artifacts import GLTF_KIND, GLTF_ROUTE_KINDS, artifact_kind
from .errors import HttpRefusal, status_for_reason
from .runtime import WorkspaceRuntime

__all__ = ["BUNDLE_HEADER", "SOURCE_HEADER", "gltf_for_ref"]

#: Response headers naming the published GLB's provenance. A closed pair, and
#: they exist because the body is *binary*: without them the only way for the
#: client to learn which bundle backs the geometry it is rendering would be to
#: decode ``asset.extras`` out of the GLB itself — which is the client reading a
#: selection link out of a blob, exactly what §1's closed list makes a server
#: value. Both are also in ``asset.extras``; these are the server saying so.
BUNDLE_HEADER: Final[str] = "X-Hephaestus-Selection-Bundle"
SOURCE_HEADER: Final[str] = "X-Hephaestus-Source-Artifact"


def gltf_for_ref(runtime: WorkspaceRuntime, ref: str) -> PublishedGltf:
    """The published, **linked** GLB for ``ref``, minting one if needed.

    Blocking: a first request tessellates and drives an offscreen GL session.
    Callers on the event loop run this through ``asyncio.to_thread``.
    """
    kind = artifact_kind(ref)
    if kind not in GLTF_ROUTE_KINDS:
        raise HttpRefusal(
            404,
            "unknown_artifact_kind_for_route",
            f"artifact kind {kind!r} is not served by this route",
            data={"kind": kind, "served": sorted(GLTF_ROUTE_KINDS)},
        )
    try:
        if kind == GLTF_KIND:
            return runtime.cad.linked_gltf(ref)
        return runtime.cad.publish_gltf(ref)
    except CadOpError as exc:
        # One mapping point, and it is §2.4's: the engine's reason string rides
        # through unrewritten, its data rides through whole (the five-value
        # `stale_reason` vocabulary included), and the status comes from the
        # closed table rather than from a guess made here.
        raise HttpRefusal(
            status_for_reason(exc.reason),
            exc.reason,
            exc.message,
            data=dict(exc.data),
        ) from exc
