"""``read_artifact``: UTF-8-boundary-safe byte-cursor paging over stored blobs.

Only model-readable artifacts return content. Kinds listed in
``BINARY_ARTIFACT_KINDS`` — and any unknown kind whose bytes do not decode —
return metadata only, because they are consumed by their dedicated render or
export path instead.

For text, the page never splits a code point: the end is walked back to the
preceding boundary, and when that would return nothing the page instead extends
over exactly one code point so a cursor always makes progress.
"""

from __future__ import annotations

from typing import Any, Final

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
        if offset_bytes > total or (
            offset_bytes not in (0, total) and (data[offset_bytes] & 0xC0) == 0x80
        ):
            return {
                "error": "invalid_utf8_offset",
                "offset_bytes": offset_bytes,
                "total_bytes": total,
            }
        end = min(offset_bytes + max_bytes, total)
        # Shorten the page end to the preceding code-point boundary...
        while end > offset_bytes and end < total and (data[end] & 0xC0) == 0x80:
            end -= 1
        if end == offset_bytes and offset_bytes < total:
            # ...but always guarantee cursor progress: extend over one code point.
            end = offset_bytes + 1
            while end < total and (data[end] & 0xC0) == 0x80:
                end += 1
        payload: dict[str, Any] = {
            "content": data[offset_bytes:end].decode("utf-8"),
            "mime_type": mime,
            "offset_bytes": offset_bytes,
            "total_bytes": total,
            "truncated": end < total,
        }
        if end < total:
            payload["next_offset_bytes"] = end
        return payload
