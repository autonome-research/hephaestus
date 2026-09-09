"""``read_artifact``: UTF-8-boundary-safe byte-cursor paging over stored blobs.

Only model-readable artifacts return content. Everything else returns a
**discriminated status**, never a page: ``status="binary_artifact"`` for a kind
that is binary by design, naming the tool that *does* consume it, and
``status="undecodable_artifact"`` for an unknown kind whose bytes are not UTF-8.
Those are different facts and they get different names — the first is a routing
answer ("ask ``inspect_part`` for this"), the second is a corruption answer.

Both used to be the success branch: a page-shaped document with empty content,
an octet-stream mime, offset zero, the real byte total and ``truncated: false``
— i.e. an assertion that a multi-kilobyte artifact had been read completely and
was empty (audit-2026-09-04 J-agent-results-3). The result schema had exactly
two branches, a page and an invalid-offset refusal, so the code took the only
one available. The page-shaped members are still emitted beside the status for
one release, so a naive consumer does not crash; the ``status`` is what a model
branches on.

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

from ._base import CHECK_SNAPSHOT_KIND, LEGACY_CHECK_SNAPSHOT_KIND, CadOpError, CadOpsState

#: Every binary artifact kind, mapped to the tool that DOES consume it. A map
#: rather than a set, because "binary artifacts are consumed by their dedicated
#: path" is only actionable if the payload says which path (J-agent-results-3):
#: the model was being told a kilobyte artifact was empty and given nothing to
#: try next. Totality over the binary kind set is asserted at import below, so a
#: new binary kind cannot be added without naming its reader — which is exactly
#: how this set grew silently when the web workspace added its own kinds.
BINARY_ARTIFACT_READERS: Final[dict[str, str]] = {
    "build": "inspect_part",
    "build-checkpoint": "inspect_part",
    "render": "inspect_part",
    "export": "export_part",
    "selection-solid": "inspect_part",
    "selection-face": "inspect_part",
    "selection-edge": "inspect_part",
    "selection-preview": "inspect_part",
    "gltf": "inspect_part",
}

#: Artifact kinds whose blobs are binary: ``read_artifact`` returns a
#: discriminated status, never a page.
BINARY_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset(BINARY_ARTIFACT_READERS)

#: ``status`` of the two non-page branches.
BINARY_ARTIFACT_STATUS: Final[str] = "binary_artifact"
UNDECODABLE_ARTIFACT_STATUS: Final[str] = "undecodable_artifact"

#: Artifact kinds with a known model-readable mime type.
TEXT_ARTIFACT_MIME: Final[dict[str, str]] = {
    LEGACY_CHECK_SNAPSHOT_KIND: "text/x-python",
    # J-agent-results-S5: a check snapshot is Python source too, and it is now
    # minted under its own kind so a reference says which of the two it
    # snapshots. Registered here in the SAME change that starts minting it —
    # renaming the kind without registering it would have made every check
    # snapshot ref unreadable and silently degraded the conflict-continuation
    # contract that hands one back. The legacy row above is what keeps a
    # reference minted before the rename readable.
    CHECK_SNAPSHOT_KIND: "text/x-python",
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
        reader = BINARY_ARTIFACT_READERS.get(kind)
        if reader is not None:
            return _non_text_result(
                status=BINARY_ARTIFACT_STATUS,
                kind=kind,
                total=total,
                message=(
                    f"artifact kind {kind!r} is binary by design and carries no readable "
                    f"text; read it with {reader}"
                ),
                consumed_by=reader,
            )
        mime = TEXT_ARTIFACT_MIME.get(kind)
        if mime is None:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                return _non_text_result(
                    status=UNDECODABLE_ARTIFACT_STATUS,
                    kind=kind,
                    total=total,
                    message=(
                        f"artifact kind {kind!r} is not a known model-readable kind and its "
                        "bytes are not valid UTF-8, so there is no text to page"
                    ),
                )
            mime = "text/plain"
        # The principal check for this surface is the tool's own: ``ref`` is a
        # capability scoped to the authorized Pi session that reached dispatch.
        page = page_text(data, offset_bytes, max_bytes)
        if "error" in page:
            return page
        payload: dict[str, Any] = {"content": page["content"], "mime_type": mime}
        payload.update({k: v for k, v in page.items() if k != "content"})
        return payload


def _non_text_result(
    *, status: str, kind: str, total: int, message: str, consumed_by: str | None = None
) -> dict[str, Any]:
    """One of the two non-page branches, with the page-shaped members retained.

    ``content``/``offset_bytes``/``truncated`` are kept for one release so a
    consumer written against the old two-branch schema does not crash on a
    missing key; ``status`` is the discriminator, and it is unambiguous — a page
    never carries one.
    """
    result: dict[str, Any] = {
        "status": status,
        "kind": kind,
        "mime_type": "application/octet-stream",
        "total_bytes": total,
        "message": message,
        # Retained page-shaped members (see the docstring).
        "content": "",
        "offset_bytes": 0,
        "truncated": False,
    }
    if consumed_by is not None:
        result["consumed_by"] = consumed_by
    return result
