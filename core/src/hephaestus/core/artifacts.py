# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The UTF-8 boundary contract of artifact text paging, as one shared function.

``INTERFACE.md`` §2.6 and §19 item 5: ``read_artifact`` (a *model-facing tool*
whose ref is a capability scoped to an authorized Pi session) and
``GET /artifacts/{ref}/text`` (a *project-scoped* capability held by the
workspace bearer) page the same blobs under two different authorizations. The
boundary contract itself is authorization-free, so it lives here and each caller
applies its own principal check — mission rule 6's "extraction is permitted;
duplication is not", and the only way G5.8's word *losslessly* can be true of
both surfaces at once.

The contract, restated where it is implemented rather than only where it is
specified (``INTERFACE.md`` §2.6):

* the page is clamped to ``[1, READ_ARTIFACT_PAGE_MAX]``;
* a code point is never split — the end walks back to the preceding boundary;
* when walking back would return nothing the page instead extends over exactly
  one code point, so a cursor always makes progress (a single oversized line is
  therefore supported);
* ``next_offset_bytes`` is boundary-aligned and present only when more remains;
* an offset that is neither ``0``, nor ``total_bytes``, nor an exact code-point
  boundary returns ``invalid_utf8_offset`` **without normalizing it**.
"""

from __future__ import annotations

from typing import Any, Final

from hephaestus.contract.tools_decl import READ_ARTIFACT_PAGE_MAX

__all__ = ["PAGE_MAX_BYTES", "page_text"]

#: The largest page either caller may ask for (the tool default is the same
#: number; ``tool_schema.md`` calls it a tool default, not a §5 cap).
PAGE_MAX_BYTES: Final[int] = READ_ARTIFACT_PAGE_MAX


def page_text(blob: bytes, offset_bytes: int, max_bytes: int) -> dict[str, Any]:
    """One UTF-8-boundary-safe page of ``blob``, or the invalid-offset refusal.

    Returns either ``{content, mime_type?, offset_bytes, total_bytes, truncated,
    next_offset_bytes?}`` — ``mime_type`` is the caller's to attach, since kind →
    mime is a store question, not a paging one — or
    ``{error: "invalid_utf8_offset", offset_bytes, total_bytes}``. The refusal
    reports the offset **as presented**: normalizing a bad cursor is how a caller
    silently loses bytes.
    """
    total = len(blob)
    page = max(1, min(PAGE_MAX_BYTES, max_bytes))
    if offset_bytes < 0 or offset_bytes > total or _is_continuation(blob, offset_bytes, total):
        return {
            "error": "invalid_utf8_offset",
            "offset_bytes": offset_bytes,
            "total_bytes": total,
        }
    end = min(offset_bytes + page, total)
    # Shorten the page end to the preceding code-point boundary...
    while end > offset_bytes and end < total and (blob[end] & 0xC0) == 0x80:
        end -= 1
    if end == offset_bytes and offset_bytes < total:
        # ...but always guarantee cursor progress: extend over one code point.
        end = offset_bytes + 1
        while end < total and (blob[end] & 0xC0) == 0x80:
            end += 1
    payload: dict[str, Any] = {
        "content": blob[offset_bytes:end].decode("utf-8"),
        "offset_bytes": offset_bytes,
        "total_bytes": total,
        "truncated": end < total,
    }
    if end < total:
        payload["next_offset_bytes"] = end
    return payload


def _is_continuation(blob: bytes, offset: int, total: int) -> bool:
    """True when ``offset`` lands mid-code-point (never for ``0`` or ``total``)."""
    if offset in (0, total):
        return False
    return (blob[offset] & 0xC0) == 0x80
