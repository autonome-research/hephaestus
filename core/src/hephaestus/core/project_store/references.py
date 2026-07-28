"""Operator-supplied reference documents and images (``INGEST.md`` §2).

A project may carry ``references/`` — drawings, datasheets, photos, PDFs. They
are **operator-supplied context, not model-writable artifacts**: registration
happens on the operator's side (``heph reference add <file>``, or a bench task
fixture), and the model surface is read-only (``list_references`` /
``read_reference``). There is deliberately no tool that adds one.

Each registration is content-addressed: the payload bytes go into the opstore
CAS, the registry state document is an immutable CAS blob published by a
compare-and-swap of the ``references-state`` pointer under the project-config
lock — the same generation pattern the requirement ledger and check set use, so
an older generation stays readable forever.

**Extraction is done once, at registration, and stored.** A ``document`` entry
carries a ``reference-text`` blob holding its per-page extracted text, so every
later reader — the ``read_reference`` tool, ``heph lint``'s
``unsourced_requirement`` citation check — reads plain stored text and needs no
parser at all. Only *producing* that text can need a third party: ``text/plain``
and ``text/markdown`` are decoded here, while ``application/pdf`` is delegated to
an injected :class:`TextExtractor`. Core therefore never imports ``pypdf``; the
pypdf-backed extractor ships with the server package
(:mod:`hephaestus.agent_bridge.references_pdf`) and is passed in by whoever
registers. A core-only install registers text, markdown and images normally and
refuses a PDF with the named ``capability_not_available`` reason rather than
degrading — engine-first is about where the *state* lives, and all of it lives
here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Protocol, cast

from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager
from opstore.types import JSONValue

from opstore import OpStore, canonical_json, sha256_bytes

__all__ = [
    "DOCUMENT_MIME_TYPES",
    "IMAGE_MIME_TYPES",
    "REFERENCES_POINTER",
    "REFERENCE_ARTIFACT_KIND",
    "REFERENCE_NAME_PATTERN",
    "REFERENCE_REF_PREFIX",
    "REFERENCE_TEXT_ARTIFACT_KIND",
    "REFERENCE_TEXT_REF_PREFIX",
    "ReferenceCapabilityError",
    "ReferenceEntry",
    "ReferenceRegistry",
    "ReferenceState",
    "TextExtractor",
    "classify",
    "extract_pages",
]

#: CAS pointer naming the current reference-registry generation.
REFERENCES_POINTER: Final[str] = "references-state"
#: Artifact kind of a registered reference payload (the operator's bytes).
REFERENCE_ARTIFACT_KIND: Final[str] = "reference"
#: Artifact kind of a document reference's extracted per-page text.
REFERENCE_TEXT_ARTIFACT_KIND: Final[str] = "reference-text"
REFERENCE_REF_PREFIX: Final[str] = f"artifact:{REFERENCE_ARTIFACT_KIND}:"
REFERENCE_TEXT_REF_PREFIX: Final[str] = f"artifact:{REFERENCE_TEXT_ARTIFACT_KIND}:"

#: A reference name is one plain filename: no separators, no traversal, no dot
#: prefix. The registry is keyed on it and ``references/`` stores it verbatim.
REFERENCE_NAME_PATTERN: Final[str] = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_NAME_RE: Final[re.Pattern[str]] = re.compile(REFERENCE_NAME_PATTERN)

#: ``kind="document"`` suffixes and their mime types (INGEST.md §2).
DOCUMENT_MIME_TYPES: Final[Mapping[str, str]] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
#: ``kind="image"`` suffixes; both are within the §5 image budgets the bridge
#: already enforces on every inline image.
IMAGE_MIME_TYPES: Final[Mapping[str, str]] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

#: Payload magic every registration is checked against, so a ``.png`` that is
#: really a PDF is refused at the operator's hand rather than at the model's.
_MAGIC: Final[Mapping[str, tuple[bytes, ...]]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


class ReferenceCapabilityError(ValidationError):
    """Registration needs an extractor this installation does not have.

    Carries ``reason="capability_not_available"`` so the CLI and the bench
    seeder can report the missing capability by name instead of guessing.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, kind="contract")
        self.reason = "capability_not_available"


class TextExtractor(Protocol):
    """Turns document bytes into per-page text (page 1 is index 0)."""

    def __call__(self, data: bytes, *, mime_type: str, name: str) -> tuple[str, ...]: ...


def classify(name: str) -> tuple[str, str]:
    """``(kind, mime_type)`` for a reference filename, or ``validation_error``."""
    suffix = Path(name).suffix.lower()
    document = DOCUMENT_MIME_TYPES.get(suffix)
    if document is not None:
        return ("document", document)
    image = IMAGE_MIME_TYPES.get(suffix)
    if image is not None:
        return ("image", image)
    supported = sorted({*DOCUMENT_MIME_TYPES, *IMAGE_MIME_TYPES})
    raise ValidationError(
        f"reference {name!r}: unsupported extension {suffix!r} (supported: {supported})",
        kind="contract",
    )


def extract_pages(
    data: bytes, *, mime_type: str, name: str, extractor: TextExtractor | None = None
) -> tuple[str, ...]:
    """Per-page text of one document reference (one page for plain text).

    ``text/plain`` and ``text/markdown`` decode here — no dependency, no
    ambiguity. ``application/pdf`` needs ``extractor``; without one this raises
    :class:`ReferenceCapabilityError` rather than registering a document whose
    text nothing can later verify a citation against.
    """
    if mime_type in ("text/plain", "text/markdown"):
        return (data.decode("utf-8", errors="replace"),)
    if extractor is None:
        raise ReferenceCapabilityError(
            f"reference {name!r}: extracting text from {mime_type} needs the pypdf-backed "
            "extractor that ships with hephaestus-server (hephaestus.agent_bridge."
            "references_pdf.pdf_extractor); nothing was registered"
        )
    pages = extractor(data, mime_type=mime_type, name=name)
    return tuple(str(page) for page in pages)


@dataclass(frozen=True)
class ReferenceEntry:
    """One registered reference: what it is, and where its bytes live."""

    name: str
    kind: str  # "document" | "image"
    mime_type: str
    sha256: str  # "sha256:<hex>" of the payload bytes
    size_bytes: int
    blob: str  # CAS hash of the payload (== sha256)
    pages: int | None = None  # documents only
    text_blob: str | None = None  # CAS hash of the extracted-text document

    @property
    def artifact_ref(self) -> str:
        """``artifact:reference:sha256:…`` — the payload's immutable ref."""
        return REFERENCE_REF_PREFIX + self.blob

    @property
    def text_ref(self) -> str | None:
        """``artifact:reference-text:sha256:…`` of the extracted text, if any."""
        if self.text_blob is None:
            return None
        return REFERENCE_TEXT_REF_PREFIX + self.text_blob

    def listing(self) -> dict[str, JSONValue]:
        """The ``list_references()`` projection (INGEST.md §2)."""
        out: dict[str, JSONValue] = {
            "name": self.name,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "bytes": self.size_bytes,
            "artifact_ref": self.artifact_ref,
        }
        if self.pages is not None:
            out["pages"] = self.pages
        return out

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "bytes": self.size_bytes,
            "blob": self.blob,
            "pages": self.pages,
            "text_blob": self.text_blob,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> ReferenceEntry:
        name = data.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValidationError(f"reference name {name!r} is malformed", kind="contract")
        kind = data.get("kind")
        if kind not in ("document", "image"):
            raise ValidationError(
                f"reference {name}: kind must be 'document' or 'image'", kind="contract"
            )
        mime_type = data.get("mime_type")
        blob = data.get("blob")
        sha256 = data.get("sha256")
        if not (isinstance(mime_type, str) and isinstance(blob, str) and isinstance(sha256, str)):
            raise ValidationError(f"reference {name}: malformed registry entry", kind="contract")
        size = data.get("bytes")
        pages = data.get("pages")
        text_blob = data.get("text_blob")
        return cls(
            name=name,
            kind=kind,
            mime_type=mime_type,
            sha256=sha256,
            size_bytes=int(size) if isinstance(size, int) and not isinstance(size, bool) else 0,
            blob=blob,
            pages=pages if isinstance(pages, int) and not isinstance(pages, bool) else None,
            text_blob=text_blob if isinstance(text_blob, str) else None,
        )


@dataclass(frozen=True)
class ReferenceState:
    """One immutable registry generation."""

    generation: int
    entries: tuple[ReferenceEntry, ...]
    blob: str | None
    parent: str | None = None

    @property
    def by_name(self) -> dict[str, ReferenceEntry]:
        return {entry.name: entry for entry in self.entries}

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> ReferenceState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ValidationError(
                "reference registry generation must be an integer", kind="contract"
            )
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise ValidationError("reference registry entries must be an array", kind="contract")
        entries = tuple(
            ReferenceEntry.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_entries)
            if isinstance(item, dict)
        )
        parent = data.get("parent")
        return cls(
            generation=generation,
            entries=entries,
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
        )


_EMPTY: Final[ReferenceState] = ReferenceState(generation=0, entries=(), blob=None, parent=None)


class ReferenceRegistry:
    """Operator-side registration and read-only access to ``references/``.

    Every mutating method here is reachable only from the operator CLI or a
    bench fixture seeder. Nothing on the model's tool surface calls them — that
    absence is the INGEST.md §2 rule "the model cannot add references", enforced
    by there being no such tool at all.
    """

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store

    # -- reads --------------------------------------------------------------

    def state(self) -> ReferenceState:
        """The current registry generation (empty generation 0 when unset)."""
        blob = self._store.blobs.read_pointer(REFERENCES_POINTER)
        if blob is None:
            return _EMPTY
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise ValidationError("reference registry document is malformed", kind="contract")
        return ReferenceState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    def list_references(self) -> tuple[ReferenceEntry, ...]:
        """Every registered reference, name-sorted."""
        return tuple(sorted(self.state().entries, key=lambda entry: entry.name))

    def get(self, name: str) -> ReferenceEntry:
        """One registered reference, or ``addressing_error`` naming the rest."""
        entries = self.state().by_name
        entry = entries.get(name)
        if entry is None:
            raise AddressingError(
                f"no reference named {name!r} is registered",
                selector=name,
                candidates=tuple(sorted(entries)),
            )
        return entry

    def payload(self, entry: ReferenceEntry) -> bytes:
        """The registered bytes (from the CAS, never re-read off disk)."""
        return self._store.blobs.get(entry.blob)

    def pages(self, entry: ReferenceEntry) -> tuple[str, ...]:
        """Extracted per-page text of a document reference (``()`` for images)."""
        if entry.text_blob is None:
            return ()
        raw = json.loads(self._store.blobs.get(entry.text_blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            return ()
        pages = cast("Mapping[str, JSONValue]", raw).get("pages")
        if not isinstance(pages, list):  # pragma: no cover - our own canonical JSON
            return ()
        return tuple(item for item in cast("list[JSONValue]", pages) if isinstance(item, str))

    def extracted_text(self) -> dict[str, tuple[str, ...]]:
        """``{name: pages}`` for every document reference (what ``heph lint`` reads)."""
        return {
            entry.name: self.pages(entry)
            for entry in self.list_references()
            if entry.kind == "document"
        }

    # -- operator-side writes ----------------------------------------------

    def add_file(
        self, path: Path, *, name: str | None = None, extractor: TextExtractor | None = None
    ) -> ReferenceEntry:
        """Copy ``path`` into ``references/`` and register it.

        The operator's file may live anywhere; the copy under ``references/``
        is what the project carries, and the CAS blob is what every reader
        actually reads, so a later edit of the file on disk cannot silently
        change what a recorded citation was checked against.
        """
        if not path.is_file():
            raise ValidationError(f"no such file: {path}", kind="contract")
        target_name = name if name is not None else path.name
        data = path.read_bytes()
        entry = self.add_bytes(data, name=target_name, extractor=extractor)
        destination = self._reference_path(target_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return entry

    def add_bytes(
        self, data: bytes, *, name: str, extractor: TextExtractor | None = None
    ) -> ReferenceEntry:
        """Register payload bytes under ``name`` (upsert), advancing a generation."""
        if not _NAME_RE.match(name):
            raise ValidationError(
                f"reference name {name!r} must match {REFERENCE_NAME_PATTERN} "
                "(one plain filename, no path separators)",
                kind="contract",
            )
        kind, mime_type = classify(name)
        _check_magic(name, mime_type, data)
        blob = self._store.blobs.put(data)
        self._store.gc.pin(blob)
        pages: int | None = None
        text_blob: str | None = None
        if kind == "document":
            texts = extract_pages(data, mime_type=mime_type, name=name, extractor=extractor)
            pages = len(texts)
            text_blob = self._store.blobs.put(
                canonical_json({"name": name, "pages": list(texts)}).encode("utf-8")
            )
            self._store.gc.pin(text_blob)
        entry = ReferenceEntry(
            name=name,
            kind=kind,
            mime_type=mime_type,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
            blob=blob,
            pages=pages,
            text_blob=text_blob,
        )
        self._publish(lambda current: _upsert(current, entry))
        return entry

    def remove(self, name: str) -> ReferenceEntry:
        """Deregister ``name`` and delete its ``references/`` copy."""
        entry = self.get(name)
        self._publish(lambda current: tuple(e for e in current if e.name != name))
        path = self._reference_path(name)
        if path.is_file():
            path.unlink()
        return entry

    def seed_directory(
        self, *, extractor: TextExtractor | None = None
    ) -> tuple[ReferenceEntry, ...]:
        """Register every file already sitting in ``references/`` (bench seeding).

        A task fixture ships ``references/`` as plain files in its seed tree;
        this is the operator-side registration that turns them into project
        state. Symlinks are skipped — a seeded fixture is bytes, not a link out
        of the project.
        """
        root = self.layout.references_dir
        if not root.is_dir():
            return ()
        registered: list[ReferenceEntry] = []
        for path in sorted(root.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            registered.append(
                self.add_bytes(path.read_bytes(), name=path.name, extractor=extractor)
            )
        return tuple(registered)

    # -- internals ----------------------------------------------------------

    def _reference_path(self, name: str) -> Path:
        if not _NAME_RE.match(name):  # pragma: no cover - callers validate first
            raise ValidationError(f"reference name {name!r} is malformed", kind="contract")
        return self.layout.references_dir / name

    def _publish(
        self,
        apply: _Apply,
    ) -> ReferenceState:
        """Publish one new immutable generation under the project-config lock."""
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            candidate = ReferenceState(
                generation=current.generation + 1,
                entries=tuple(apply(current.entries)),
                blob=None,
                parent=current.blob,
            )
            new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
            self._store.gc.pin(new_blob)
            self._store.blobs.cas_swap(REFERENCES_POINTER, current.blob, new_blob)
            return replace(candidate, blob=new_blob)


class _Apply(Protocol):
    def __call__(self, current: Sequence[ReferenceEntry], /) -> Sequence[ReferenceEntry]: ...


def _upsert(current: Sequence[ReferenceEntry], entry: ReferenceEntry) -> tuple[ReferenceEntry, ...]:
    """Replace an entry of the same name in place, else append."""
    if any(existing.name == entry.name for existing in current):
        return tuple(entry if existing.name == entry.name else existing for existing in current)
    return (*current, entry)


def _check_magic(name: str, mime_type: str, data: bytes) -> None:
    """Refuse a payload whose bytes contradict its declared extension."""
    signatures = _MAGIC.get(mime_type)
    if signatures is None:
        return
    if not any(data.startswith(signature) for signature in signatures):
        raise ValidationError(
            f"reference {name!r}: content does not look like {mime_type}",
            kind="contract",
        )
