# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""GLB publication for a build artifact ref (``INTERFACE.md`` §5.1, §19 item 12).

The engine seam behind ``GET /artifacts/{ref}/gltf``. The web layer holds no
geometry: it names a ref and maps a refusal, and *this* is where the ref becomes
a re-tessellation, a minted selection bundle, and a published GLB — through
:mod:`hephaestus.core.render.gltf_publish`, which is where the work actually
lives. Two thin operations, one refusal vocabulary, no geometry logic of its own.

Why it is a ``CadOps`` domain and not a route helper: ``server/http`` may not
import the renderer (§1's closed list is unreachable from the web layer *by
construction*, asserted in ``server/tests/test_http_boundary.py``), and the GLB,
its selection IDs, and its explode displacements are every one of them engine
values. ``CadOps`` is the seam the MCP server and the bridge already ride to
reach the engine, so the workspace rides the same one — mission rule 6.

**Never an unlinked GLB** (§5.1, and §12.3's second line of defence):
:meth:`GeometryOps.publish_gltf` verifies the bundle link before a byte is
stored, and :meth:`GeometryOps.linked_gltf` re-verifies it before an
already-published GLB is handed back. Both refuse rather than degrade — a
viewport that is pickable but unresolvable is the worst possible failure,
because it looks like it works.
"""

from __future__ import annotations

from typing import Any

from hephaestus.core.errors import HephaestusError
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import StaleSelectionError, resolve_selection
from hephaestus.core.render.gltf_publish import (
    PublishedGltf,
    publish_gltf_for_build,
    resolve_published_gltf,
)

from ._base import CadOpError, CadOpsState

__all__ = ["GeometryOps", "PublishedGltf"]


class GeometryOps(CadOpsState):
    """``publish_gltf`` / ``linked_gltf`` — the geometry wire's engine half."""

    def publish_gltf(self, source_artifact_ref: str) -> PublishedGltf:
        """Resolve, or publish on demand, the linked GLB for one build ref.

        §5.1's route contract in one call: re-tessellate from the stored BREP,
        mint (or resolve) the selection bundle for **that exact ref**, export the
        GLB bound to it, and publish under the ``gltf`` artifact kind. A second
        call for the same ref resolves the first publication rather than minting
        again (``PublishedGltf.minted`` says which happened).
        """
        self._require_stored(source_artifact_ref)
        try:
            return publish_gltf_for_build(self._render_project(), source_artifact_ref)
        except StaleSelectionError as exc:
            raise _stale(exc, source_artifact_ref) from exc
        except HephaestusError as exc:
            # A build ref that cannot yield a linked GLB — a BREP that will not
            # load, a build result whose solid count disagrees with its own
            # stored geometry. Named as its own refusal rather than leaked as a
            # generic validation error, because the client's next move (drop the
            # viewport, keep the panels) depends on knowing it is this one.
            raise CadOpError(
                "gltf_not_published",
                f"no linked GLB could be published for {source_artifact_ref}: {exc.message}",
                data={"ref": source_artifact_ref, "cause": exc.code},
            ) from exc

    def describe_selection(
        self,
        bundle_ref: str,
        selection_id: str,
        *,
        expected_source_artifact_ref: str | None = None,
    ) -> dict[str, Any]:
        """One selection id, resolved against its bundle (``INTERFACE.md`` §12.3).

        The engine half of §7A.3's context envelope. The composer submits
        ``{selection_id, bundle_ref}``; §7A.3 says the envelope "carries the ids;
        the server resolves them through §12.3 against the pinned ref; a
        selection that does not resolve is ``stale_selection`` — **never** a
        fallback to current geometry (§15.3), and never a prompt that quietly
        drops the selection it claimed to carry."

        It lives here rather than in ``server/http`` for the reason this whole
        module exists: the web layer may not import the renderer (§1's closed
        list is unreachable from it *by construction*,
        ``server/tests/test_http_boundary.py``), and a resolved selection is an
        engine value — its kind, its owning solid, its tag and its label all come
        from the selection table the renderer published. The route names ids and
        renders words; this resolves them.

        The returned document carries **no geometry**: four already-published
        table fields plus the two refs the resolution is bound to. A caller that
        needs the pass images asks the artifact routes for them.
        """
        self._require_stored(bundle_ref)
        try:
            resolution = resolve_selection(
                self._store, bundle_ref, expected_source_artifact_ref=expected_source_artifact_ref
            )
        except StaleSelectionError as exc:
            raise _stale(exc, bundle_ref) from exc
        try:
            numeric = int(selection_id)
        except ValueError as exc:
            raise CadOpError(
                "stale_selection",
                f"{selection_id!r} is not a selection id in {bundle_ref}",
                data={"stale_reason": "malformed", "ref": bundle_ref},
            ) from exc
        entry = resolution.entries.get(numeric)
        if entry is None:
            # `mismatched` rather than `malformed`: the id is well formed and the
            # bundle resolved — what failed is that THIS bundle does not contain
            # it, which is the same fact as a selection taken against another
            # build. Collapsing the two would make G5.15's enumeration untestable.
            raise CadOpError(
                "stale_selection",
                f"selection {numeric} is not in the selection table of {bundle_ref}",
                data={"stale_reason": "mismatched", "ref": bundle_ref},
            )
        return {
            "selection_id": numeric,
            "bundle_ref": resolution.bundle_ref,
            "source_artifact_ref": resolution.source_artifact_ref,
            "kind": entry.kind,
            "solid_index": entry.solid_index,
            "topology_index": entry.topology_index,
            "tag": entry.tag,
            "label": entry.label,
        }

    def linked_gltf(self, gltf_artifact_ref: str) -> PublishedGltf:
        """An already-published GLB, re-checked against its bundle before serving.

        §12.3 (binds G5.12): an **unlinked** GLTF — numerically valid IDs, no
        immutable bundle link in its metadata — is rejected. The GLB alone never
        authorizes a selection, and a GLB this workspace hands out is one it has
        vouched for. §5.1's route never serves an unlinked GLB in the first
        place, so this is the *second* line of defence; both are tested.
        """
        self._require_stored(gltf_artifact_ref)
        data = self._store.blobs.get(blob_hash_of_ref(gltf_artifact_ref))
        source = self._declared_source(data)
        published = None if source is None else resolve_published_gltf(self._store, source)
        if published is None or published.ref != gltf_artifact_ref:
            raise CadOpError(
                "stale_selection",
                f"{gltf_artifact_ref} carries no resolvable selection bundle link; "
                "an unlinked GLB is never served",
                data={"stale_reason": "malformed", "ref": gltf_artifact_ref},
            )
        return published

    # -- internals ---------------------------------------------------------

    def _require_stored(self, ref: str) -> None:
        """Reachability from the open project's opstore, refused by name.

        For the web principal this *is* the authorization (``INTERFACE.md``
        §2.2): an artifact ref is a project-scoped capability, and a ref minted
        in another project simply is not here. Checked before any geometry work
        so an unknown ref costs a lookup rather than a tessellation.
        """
        if not self._store.blobs.has(blob_hash_of_ref(ref)):
            raise CadOpError(
                "unknown_artifact", f"artifact {ref} is not stored in the open project"
            )

    @staticmethod
    def _declared_source(data: bytes) -> str | None:
        """A GLB's ``asset.extras.source_artifact_ref``, or ``None``.

        Read through ``validate_gltf`` so a blob that does not parse, or whose
        meshes carry no ``explode_offset``, is already ``None`` here rather than
        failing later with a less specific message.
        """
        from hephaestus.core.errors import ValidationError
        from hephaestus.core.render.gltf import validate_gltf

        try:
            return validate_gltf(data).source_artifact_ref
        except ValidationError:
            return None


def _stale(exc: StaleSelectionError, ref: str) -> CadOpError:
    """A core ``StaleSelectionError`` as the tool surface's own refusal.

    The five-value ``StaleReason`` vocabulary is preserved verbatim in ``data``
    (``INTERFACE.md`` §2.4 TIGHTENING, binds G5.15: ``malformed`` is never
    collapsed into ``mismatched`` and never degraded to a generic 400).
    """
    return CadOpError(
        "stale_selection",
        f"selection bundle for {ref} does not resolve: {exc}",
        data={"stale_reason": exc.stale.reason, "ref": ref},
    )
