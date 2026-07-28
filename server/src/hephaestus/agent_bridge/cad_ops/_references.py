"""``list_references`` / ``read_reference``: the model's read-only view of §2.

``INGEST.md`` §2. Operator-supplied documents and images are context, not
artifacts the run produces — so this module has **no write path at all**. The
registry's mutating methods live in
:mod:`hephaestus.core.project_store.references` and are reached only by
``heph reference add`` and the bench seeder; a model can list what a project
carries and read it, and that is the whole surface.

Document text arrives inside the same provenance delimiters registry skills use
(:func:`~hephaestus.core.registry.wrap_reference`), because it is the same kind
of thing: a datasheet is reference material, never instructions. Paging is a
byte cursor under the §5 dual cap — bytes *and* lines — over the extracted text
stored at registration, so a cursor is stable across reads and independent of
whether a parser is installed. Images ride inline within the §5 image budgets,
with their artifact ref alongside so a big drawing can also be paged as bytes
through ``read_artifact``.
"""

from __future__ import annotations

import base64
from typing import Any, Final

from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.references import ReferenceEntry, ReferenceRegistry
from hephaestus.core.registry import TEXT_MAX_BYTES, TEXT_MAX_LINES, json_bytes, wrap_reference
from opstore.types import JSONValue

from ..limits import ImageError, parse_image_header
from ._base import CadOpError, CadOpsState

__all__ = ["REFERENCE_WRAPPER_REGISTRY", "ReferenceOps"]

#: The ``registry="…"`` attribute of the provenance header for reference text.
#: Not a content registry — it names the *project's own* reference set, which is
#: exactly the provenance a reader needs to know.
REFERENCE_WRAPPER_REGISTRY: Final[str] = "project:references"


class ReferenceOps(CadOpsState):
    """The two read-only reference tools (INGEST.md §2)."""

    def references(self) -> ReferenceRegistry:
        """The project's reference registry (read paths only, from here)."""
        return ReferenceRegistry(self.layout, self._store)

    def list_references(self) -> list[dict[str, JSONValue]]:
        """``[{name, kind, mime_type, pages?, sha256, bytes, artifact_ref}]``."""
        return [entry.listing() for entry in self.references().list_references()]

    def read_reference(
        self, name: str, *, page: int | None = None, offset_bytes: int = 0
    ) -> dict[str, Any]:
        """One reference: delimited document text (paged), or an inline image."""
        registry = self.references()
        try:
            entry = registry.get(name)
        except AddressingError as exc:
            known = ", ".join(exc.candidates) or "none registered"
            raise CadOpError(
                "unknown_reference",
                f"{exc.message} (registered: {known}) — list_references() shows what "
                "this project carries",
            ) from exc
        if entry.kind == "image":
            return self._image_result(registry, entry)
        return self._document_result(registry, entry, page=page, offset_bytes=offset_bytes)

    # -- images -------------------------------------------------------------

    def _image_result(self, registry: ReferenceRegistry, entry: ReferenceEntry) -> dict[str, Any]:
        """Inline image content under the §5 image budgets, plus the artifact ref."""
        data = registry.payload(entry)
        try:
            # Bounded header parse BEFORE anything decodes the payload (§5) —
            # the same gate every rendered image passes through.
            parse_image_header(data)
        except ImageError as exc:
            raise CadOpError(exc.code, f"reference {entry.name!r}: {exc.message}") from exc
        return {
            "status": "ok",
            "name": entry.name,
            "kind": "image",
            "mime_type": entry.mime_type,
            "artifact_ref": entry.artifact_ref,
            "sha256": entry.sha256,
            "images": [
                {
                    "data": base64.b64encode(data).decode("ascii"),
                    "mime_type": entry.mime_type,
                }
            ],
        }

    # -- documents ----------------------------------------------------------

    def _document_result(
        self,
        registry: ReferenceRegistry,
        entry: ReferenceEntry,
        *,
        page: int | None,
        offset_bytes: int,
    ) -> dict[str, Any]:
        pages = registry.pages(entry)
        total_pages = len(pages)
        index = 0 if page is None else int(page) - 1
        if total_pages == 0:
            raise CadOpError(
                "unreadable_reference",
                f"reference {entry.name!r} has no extracted text",
            )
        if index < 0 or index >= total_pages:
            raise CadOpError(
                "unknown_page",
                f"reference {entry.name!r} has {total_pages} page(s); page "
                f"{index + 1} does not exist",
            )
        data = pages[index].encode("utf-8")
        total = len(data)
        cursor = max(0, int(offset_bytes))
        if cursor > total or (cursor not in (0, total) and (data[cursor] & 0xC0) == 0x80):
            return {
                "error": "invalid_utf8_offset",
                "offset_bytes": cursor,
                "total_bytes": total,
            }
        end = _page_end(data, cursor, _budget(entry.name, index + 1, total_pages))
        body = data[cursor:end].decode("utf-8")
        truncated = end < total
        result: dict[str, Any] = {
            "status": "ok",
            "name": entry.name,
            "kind": "document",
            "mime_type": entry.mime_type,
            "artifact_ref": entry.artifact_ref,
            "sha256": entry.sha256,
            "page": index + 1,
            "pages": total_pages,
            "content": wrap_reference(
                body,
                kind="reference",
                name=entry.name,
                registry=REFERENCE_WRAPPER_REGISTRY,
                digest=entry.sha256,
                lines=f"page {index + 1}/{total_pages} bytes {cursor}-{end}/{total}",
            ),
            "offset_bytes": cursor,
            "total_bytes": total,
            "truncated": truncated,
            "oversized_line": False,
        }
        if truncated:
            result["next_offset_bytes"] = end
        return result


def _budget(name: str, page: int, pages: int) -> int:
    """Wire-byte budget for the body: the §5 cap minus the wrapper's own cost."""
    empty = wrap_reference(
        "",
        kind="reference",
        name=name,
        registry=REFERENCE_WRAPPER_REGISTRY,
        digest="sha256:" + "0" * 64,
        lines=f"page {page}/{pages} bytes 0-0/0",
    )
    return max(1, TEXT_MAX_BYTES - json_bytes(empty))


def _page_end(data: bytes, cursor: int, budget: int) -> int:
    """End of one page: the byte budget, the line cap, and always progress.

    Both §5 caps bind: the slice never exceeds ``budget`` bytes and never spans
    more than ``TEXT_MAX_LINES`` lines. The end is walked back to a code-point
    boundary, and when that would return nothing it extends over exactly one
    code point so a cursor always advances.
    """
    total = len(data)
    end = min(cursor + budget, total)
    while end > cursor and end < total and (data[end] & 0xC0) == 0x80:
        end -= 1
    # The line cap, applied inside the byte page: cut after the 2000th newline.
    newlines = 0
    for position in range(cursor, end):
        if data[position] != 0x0A:
            continue
        newlines += 1
        if newlines == TEXT_MAX_LINES:
            end = position + 1
            break
    if end == cursor and cursor < total:
        end = cursor + 1
        while end < total and (data[end] & 0xC0) == 0x80:
            end += 1
    return end
