"""The pypdf-backed PDF text extractor (``INGEST.md`` §2).

This is the *only* thing about references that is not core. The registry, its
content addressing, its state generations and every read path live in
:mod:`hephaestus.core.project_store.references`; extraction is injected, and
core decodes ``text/plain`` and ``text/markdown`` itself. Splitting the parser
out this way is what lets ``hephaestus-core`` keep its dependency set free of
``pypdf`` while the server — which is where documents are actually read to a
model — carries it as a runtime dependency.

Extraction is deliberately dumb: one string per PDF page, in page order, with no
layout reconstruction. Everything downstream (the ``read_reference`` paging, the
``heph lint`` citation check) works on exactly these strings, so what a lint
verifies is the same text the model was shown.
"""

from __future__ import annotations

import io

from hephaestus.core.project_store.references import ReferenceCapabilityError, TextExtractor

__all__ = ["extract_pdf_pages", "pdf_extractor"]


def extract_pdf_pages(data: bytes, *, mime_type: str, name: str) -> tuple[str, ...]:
    """Per-page text of a PDF (page 1 first); ``pypdf`` is imported lazily."""
    if mime_type != "application/pdf":  # pragma: no cover - core routes by mime
        raise ReferenceCapabilityError(
            f"reference {name!r}: the pypdf extractor handles application/pdf, not {mime_type}"
        )
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a server dependency
        raise ReferenceCapabilityError(
            f"reference {name!r}: pypdf is not installed, so PDF text cannot be extracted"
        ) from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        return tuple(str(page.extract_text() or "") for page in reader.pages)
    except ReferenceCapabilityError:
        raise
    except Exception as exc:
        raise ReferenceCapabilityError(
            f"reference {name!r}: PDF text extraction failed ({exc})"
        ) from exc


def pdf_extractor() -> TextExtractor:
    """The injectable extractor the CLI and the bench seeder hand to the registry."""
    return extract_pdf_pages
