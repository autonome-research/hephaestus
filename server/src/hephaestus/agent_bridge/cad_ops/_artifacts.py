"""``read_artifact``: UTF-8-boundary-safe byte-cursor paging over stored blobs.

Only model-readable artifacts return content. Kinds listed in
``BINARY_ARTIFACT_KINDS`` — and any unknown kind whose bytes do not decode —
return metadata only, because they are consumed by their dedicated render or
export path instead.

For text, the page never splits a code point: the end is walked back to the
preceding boundary, and when that would return nothing the page instead extends
over exactly one code point so a cursor always makes progress. That boundary
contract itself lives in :func:`hephaestus.core.artifacts.page_text`, which
``server/http``'s ``GET /artifacts/{ref}/text`` also calls under its own,
different principal check (``INTERFACE.md`` §2.6, §19 item 5): one contract, two
authorizations, no second implementation.
"""

from __future__ import annotations

from typing import Any, Final

from hephaestus.core.artifacts import page_text
from hephaestus.core.project_store.store import blob_hash_of_ref

from ._base import CadOpError, CadOpsState

#: Artifact kinds whose blobs are binary: ``read_artifact`` returns metadata only.
BINARY_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "build",
        "build-checkpoint",
        "render",
        "export",
        "selection-solid",
        "selection-face",
        "selection-edge",
        "selection-preview",
        "gltf",
    }
)

#: Artifact kinds with a known model-readable mime type.
TEXT_ARTIFACT_MIME: Final[dict[str, str]] = {
    "part-snapshot": "text/x-python",
    "mask-legend": "application/json",
    "source-map": "application/json",
    "check-bundle": "application/json",
    "check-diagnostics": "application/json",
    "project-snapshot": "application/json",
    "selection-table": "application/json",
    "snapshot-issues": "application/json",
    "build-result": "application/json",
    "check-report": "application/json",
    # One immutable requirement-ledger generation (VALIDATION.md §2).
    "requirements": "application/json",
}


class ArtifactOps(CadOpsState):
    """Paged reads of durably stored artifacts."""

    def read_artifact(self, ref: str, offset_bytes: int, max_bytes: int) -> dict[str, Any]:
        """UTF-8-boundary-safe byte-cursor page over a model-readable artifact."""
        parts = ref.split(":")
        if len(parts) != 4 or parts[0] != "artifact":
            raise CadOpError("invalid_ref", f"{ref!r} is not an artifact reference")
        kind = parts[1]
        blob = blob_hash_of_ref(ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_ref", f"artifact {ref} is not durably stored")
        data = self._store.blobs.get(blob)
        total = len(data)
        if kind in BINARY_ARTIFACT_KINDS:
            # Binary artifacts return metadata only; they are consumed by their
            # dedicated render/export path.
            return {
                "content": "",
                "mime_type": "application/octet-stream",
                "offset_bytes": 0,
                "total_bytes": total,
                "truncated": False,
            }
        mime = TEXT_ARTIFACT_MIME.get(kind)
        if mime is None:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                return {
                    "content": "",
                    "mime_type": "application/octet-stream",
                    "offset_bytes": 0,
                    "total_bytes": total,
                    "truncated": False,
                }
            mime = "text/plain"
        # The principal check for this surface is the tool's own: ``ref`` is a
        # capability scoped to the authorized Pi session that reached dispatch.
        page = page_text(data, offset_bytes, max_bytes)
        if "error" in page:
            return page
        payload: dict[str, Any] = {"content": page["content"], "mime_type": mime}
        payload.update({k: v for k, v in page.items() if k != "content"})
        return payload
