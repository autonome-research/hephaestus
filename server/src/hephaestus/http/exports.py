# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Egress — the three keyed mutations, the projection, and the byte route (§22).

``INTERFACE.md`` §22, normative under Stage 10A / Gate G10A. This module is the
*construction* half of egress: what the routes accept, what the history says, and
what a download is authorized by. The routes themselves live in
:mod:`hephaestus.http.app` beside every other row of §2.3's table, and each of the
three mutations rides :meth:`~hephaestus.http.app._Api.keyed_mutation` onto
``ToolDispatcher.dispatch`` — the one dispatcher, mission rule 6. Nothing here
exports anything; ``cad_ops/_exports.py`` is still the only export path in the
product, and it is unmodified by this section.

**Its hard prerequisite is §19.24, and it is checked rather than assumed.**
§22.3's ORDERING CONSTRAINT is *"``export_hashes`` in a response body and
``GET /parts/{part}/exports`` are what turn 'nobody knows the hash' into 'every
client knows the hash'. **Neither ships before §19.24.**"* The binding landed
(``core/project_store/artifact_kinds``, recorded by ``ExportOps._commit_export``
and ``_replay_commit``), which is what makes it safe for this module to publish
the hashes at all: a client that learns an export blob's hash can no longer
relabel it as ``artifact:build:…`` and read it back through
``GET /artifacts/{ref}/bytes``.

**Three authorizations, and the third is the narrowest in the product.**
``GET /artifacts/{ref}/bytes`` is authorized by project-scoped reachability
(§2.2); the ``read_artifact`` tool is authorized by a Pi session capability;
``GET /exports/{blob}/bytes`` is authorized by *"this blob is named by the
``outputs`` column of a ``COMMITTED`` ``tp_exports`` row in the open project"*.
Not "stored". Not "pinned". A ``FROZEN`` row's blob, a blob stored for any other
reason, and a blob from another project are all 404 :data:`UNKNOWN_EXPORT_REASON`.
That is what lets egress be a **named operation** rather than a side effect of
blob storage: it is not a blob-fetch primitive, it is a re-read of a recorded
result (§22.3).

**The filename is derived, never echoed** (§22.3's 2026-08-28 TIGHTENING). This
route serves any blob a committed row names, *including* every export an agent
produced with an explicit ``target``, and ``_validate_relative_target`` confines
traversal while permitting ``"`` and ``;`` — the two characters that structure a
``Content-Disposition`` parameter list. So neither the recorded ``rel_path`` nor
anything derived from it by string manipulation reaches a header:
:meth:`ExportedFile.filename` is built from the part stem, the blob digest and a
suffix drawn from a **closed** vocabulary. The recorded path is still reported —
as JSON body text in the projection, where a quote is inert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final

from hephaestus.agent_bridge.cad_ops._exports import EXPORT_FORMATS
from hephaestus.agent_bridge.cad_ops.export_history import COMMITTED_STATE as _COMMITTED_STATE
from hephaestus.agent_bridge.cad_ops.export_history import EXPORTS_DIR as _EXPORTS_DIR
from hephaestus.agent_bridge.cad_ops.export_history import ExportRecord, export_records
from hephaestus.core.project_store.publication import EXPORT_ARTIFACT_KIND
from hephaestus.core.project_store.store import artifact_ref

from opstore import OpStore

from .artifacts import reachable_blob
from .errors import HttpRefusal

__all__ = [
    "COMMITTED_STATE",
    "DOCUMENT_SUFFIXES",
    "EXPORTS_DIR",
    "EXPORT_CONTENT_TYPES",
    "EXPORT_MAX_BYTES",
    "EXPORT_ROUTE_TOOLS",
    "EXPORT_TOO_LARGE_REASON",
    "REFUSED_EXPORT_ARGUMENTS",
    "UNKNOWN_EXPORT_REASON",
    "UNTYPED_SUFFIX",
    "ExportedFile",
    "export_arguments",
    "export_bytes",
    "exports_projection",
    "find_export",
    "suffix_for",
]

#: The WAL state a row must be in before this surface will admit its outputs.
#: ``FROZEN`` means the source was frozen and the files were never installed —
#: a crashed export, whose blobs do not exist. Re-exported from the WAL's own
#: reader (``cad_ops/export_history``) rather than restated: a second literal
#: here would be a second place for the state vocabulary to drift.
COMMITTED_STATE: Final[str] = _COMMITTED_STATE

#: §22.7's reason for a blob no committed row names. Spelled ``unknown_…`` so
#: §2.4's family rule would answer 404 even without the explicit row this module's
#: registration adds — belt and braces, since the status is normative.
UNKNOWN_EXPORT_REASON: Final[str] = "unknown_export"

#: §22.4's ceiling. The whole file buffers in the tab's memory before it reaches
#: disk (see §22.4's rejected alternatives — no streaming, no service worker), so
#: above this the workspace refuses **by name and with the size** rather than
#: handing a tab a multi-hundred-megabyte ``Blob`` and letting it die.
#:
#: WHY a server constant and not a client guess (§22.4 says so outright): the
#: client cannot know what this process will attempt, and two numbers that drift
#: apart would produce a button that offers a download the server refuses. 64 MiB
#: is chosen against the mechanism rather than a filesystem: the fetch's
#: ``ArrayBuffer`` and the ``Blob`` it becomes are two copies, so the tab's real
#: cost is ~2x this, which is a stall on a modern machine and not a crash. Every
#: fixture output is four orders of magnitude below it.
EXPORT_MAX_BYTES: Final[int] = 64 * 1024 * 1024

#: §22.7's reason for a file above :data:`EXPORT_MAX_BYTES`.
EXPORT_TOO_LARGE_REASON: Final[str] = "export_too_large"

#: The three keyed mutations of §22.3, route template → the tool each dispatches.
#: Kept as data so ``app.py``'s handlers and the §1 boundary test read one map,
#: and so "which tool does the drawing route call" is answerable without reading
#: a handler body.
EXPORT_ROUTE_TOOLS: Final[dict[str, str]] = {
    "/parts/{part}/export": "export_part",
    "/parts/{part}/drawing": "generate_drawing",
    "/parts/{part}/doc": "generate_doc",
}

#: Arguments the three tools accept that the **browser** may not send (§22.1).
#:
#: ``target`` — §2.3 admits no raw filesystem path in a request body and §22 does
#: not reopen it. The server always takes the no-target branch of
#: ``_output_paths``, whose stem is content-addressed over the whole output set.
#: One consequence is exactly as §22.1 states it: the operator cannot choose the
#: on-disk filename.
#:
#: **CORRECTION to §22.1's second consequence.** That section adds that
#: ``target_exists`` is therefore "**unreachable** from the browser by
#: construction". It is not, and the difference matters because §22.1's reason for
#: the claim — "a create-only collision is a failure the operator could neither
#: see nor clear from a browser" — is what would make an unrenderable refusal
#: dangerous. The no-target stem is content-addressed over the whole output set,
#: so two *fresh keys* over identical fields produce identical bytes, an identical
#: stem, and ``O_CREAT|O_EXCL`` refusing the second — measured, for the four
#: formats whose writers are byte-deterministic (``stl``, ``glb``, ``3mf``,
#: ``svg``; ``step`` and ``dxf`` stamp a wall-clock time into their own headers
#: and so never collide). What actually makes it unreachable is §22.2's
#: TIGHTENING: one key per *submission*, and the retry button does not re-mint, so
#: an unchanged resubmission is a ledger replay rather than a second execution.
#: That is a **client discipline**, not a construction, so the refusal is mapped
#: (``errors.py``: 409) and the panel renders it by name.
#:
#: ``kerf_mm`` — the resolution order is fixed in ``core/geom/kerf.py`` (explicit
#: → the DFM pack's ``kerf_mm`` → none, plus a ``kerf_uncompensated`` note) and a
#: default kerf is never invented. A number box in a download dialog is the worst
#: place in the product to override a manufacturing constant: it is per-click, it
#: is recorded nowhere a second operator will read it, and it silently disagrees
#: with the process pack the DFM panel is displaying two tabs away. The panel
#: **displays** the resolved decision instead.
#:
#: Refused by name with the offending keys, never dropped: a route that silently
#: ignored ``target`` would take a filesystem path from a browser and merely
#: decline to act on it, which is not the same as not admitting one.
REFUSED_EXPORT_ARGUMENTS: Final[tuple[str, ...]] = ("target", "kerf_mm")

#: ``.heph/exports/`` — the confined directory ``_commit_export`` installs into.
#: Reported to a client only inside :data:`EXPORT_TOO_LARGE_REASON`'s payload, so
#: an operator who cannot download a file is told where the CLI will find it.
EXPORTS_DIR: Final[str] = _EXPORTS_DIR

#: The suffixes the two multi-file generators produce, enumerated because their
#: ``ExportOutput`` suffixes are literals inside ``produce`` callbacks
#: (``cad_ops/_doc.py``:303-307, ``cad_ops/_drawing.py``:712-713) and there is no
#: constant in the engine to import. §19.36's drift test does not trust this list:
#: it runs both generators and asserts every suffix they actually emit is typed
#: below, so a fourth output kind fails a test rather than shipping untyped.
DOCUMENT_SUFFIXES: Final[frozenset[str]] = frozenset({"pdf", "svg", "md", "json"})

#: The suffix used when a recorded path's extension is outside the closed
#: vocabulary. Reachable **only** through an agent-authored ``target`` naming an
#: extension no generator produces — never through a ``format``, because a
#: format-derived suffix is a value of :data:`EXPORT_FORMATS`.
UNTYPED_SUFFIX: Final[str] = "bin"

#: ``Content-Type`` per output suffix (§22.3). One enumerated map with a drift
#: test: *"a format added without a content type is a test failure, not an
#: ``application/octet-stream``"*. Keyed by **suffix** rather than by ``format``
#: because the two document generators have no format — they have outputs.
EXPORT_CONTENT_TYPES: Final[dict[str, str]] = {
    # export_part's six, by `EXPORT_FORMATS`' value (`gltf` writes `.glb`).
    "step": "model/step",
    "stl": "model/stl",
    "glb": "model/gltf-binary",
    "3mf": "model/3mf",
    "dxf": "image/vnd.dxf",
    "svg": "image/svg+xml",
    # generate_drawing (pdf + svg) and generate_doc (md + json).
    "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json",
}

#: What survives into a derived filename's stem. Not a sanitizer over the
#: recorded value — a **closed** character class over the part name, so the
#: header parameter cannot be structured by anything a caller wrote. A part name
#: is ``^[a-z][a-z0-9_]{0,63}$`` at every boundary that admits one; this is the
#: guarantee restated where the string reaches a header, because the WAL column
#: is whatever the process that wrote it passed.
_STEM_ALLOWED: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_-]+")

#: The stem a part name reduces to when nothing of it survives the class above.
_FALLBACK_STEM: Final[str] = "export"

#: How much of the digest the filename carries. Enough to be unique in a download
#: directory, short enough to read.
_FILENAME_DIGEST_CHARS: Final[int] = 12


@dataclass(frozen=True, slots=True)
class ExportedFile:
    """One committed output: the row it belongs to, its blob, and its identity.

    Everything a download needs, resolved once from the WAL row so the route
    body is a lookup and a write rather than a second place that knows how an
    export is named.
    """

    part: str
    op_id: str
    #: The recorded relative path under ``.heph/exports/``. Body text only —
    #: never a header, never a filename (§22.3's TIGHTENING).
    rel_path: str
    blob: str
    #: The recorded ``format`` column: a format for ``export_part``, and
    #: ``"<operation>:<variant>"`` for a drawing or a document.
    recorded_format: str
    size_bytes: int

    @property
    def suffix(self) -> str:
        """The output's extension, from the closed vocabulary."""
        return suffix_for(self.recorded_format, self.rel_path)

    @property
    def content_type(self) -> str:
        """``Content-Type`` for this output.

        ``application/octet-stream`` is reachable only for
        :data:`UNTYPED_SUFFIX`, i.e. an agent-authored ``target`` with an
        extension no generator produces. §22.3's *"never an
        ``application/octet-stream``"* is a rule about **formats**, and every
        format has a row; there is no honest type for a file the engine did not
        choose the name of.
        """
        return EXPORT_CONTENT_TYPES.get(self.suffix, "application/octet-stream")

    @property
    def filename(self) -> str:
        """``<part>-<digest[:12]>.<ext>`` — derived, never echoed (§22.3).

        DEVIATION, small and deliberate, recorded rather than silently taken.
        §22.3 writes the pattern as ``<part>-<blob[:12]>.<ext>`` and ``blob`` is
        the ``sha256:<hex>`` the store assigns, whose first twelve characters are
        ``"sha256:12345"`` — a colon, which is legal in a quoted
        ``Content-Disposition`` parameter and illegal in a filename on Windows.
        The twelve characters taken are therefore the **digest's**, which is what
        §22.3's own argument (*"derived from the blob hash and the format"*)
        describes and what a reader expects to see.
        """
        digest = self.blob.rpartition(":")[2][:_FILENAME_DIGEST_CHARS]
        return f"{_safe_stem(self.part)}-{digest}.{self.suffix}"

    def to_json(self) -> dict[str, Any]:
        """One output of one export, as the projection reports it."""
        return {
            "path": self.rel_path,
            "blob": self.blob,
            "bytes": self.size_bytes,
            "content_type": self.content_type,
            "filename": self.filename,
        }


def suffix_for(recorded_format: str, rel_path: str) -> str:
    """The output extension for one recorded output, from a closed vocabulary.

    Two sources, in this order, and neither is a string the caller controls:

    1. an ``export_part`` row's ``format`` column is a key of
       :data:`EXPORT_FORMATS`, whose **value** is the extension. Fully derived:
       the caller chose a format from a schema enum, not a filename.
    2. a drawing's or a document's row has no format, so the recorded path's
       extension is read — and **admitted only if it is in
       :data:`EXPORT_CONTENT_TYPES`**. That membership test is what makes this
       derivation rather than echoing: a value outside the vocabulary becomes
       :data:`UNTYPED_SUFFIX`, so nothing a ``target`` could contain reaches a
       header.
    """
    from_format = EXPORT_FORMATS.get(recorded_format)
    if from_format is not None:
        return from_format
    candidate = PurePosixPath(rel_path).suffix.removeprefix(".").lower()
    return candidate if candidate in EXPORT_CONTENT_TYPES else UNTYPED_SUFFIX


def _safe_stem(part: str) -> str:
    """A filename stem from a part name, over a closed character class."""
    reduced = _STEM_ALLOWED.sub("", part)[:64]
    return reduced or _FALLBACK_STEM


def _files_of(store: OpStore, record: ExportRecord) -> list[ExportedFile]:
    """The one row's outputs, each sized from the blob store.

    The row shape itself — the ``outputs`` column, the pre-``outputs`` legacy
    ``rel_path``/``export_blob`` pair, and which states carry blobs at all — is
    read by ``cad_ops/export_history``, the WAL's one reader. This module adds
    only what a *download* needs on top of it: a size, a content type and a
    derived filename.
    """
    return [
        ExportedFile(
            part=record.part,
            op_id=record.op_id,
            rel_path=rel_path,
            blob=blob,
            recorded_format=record.recorded_format,
            size_bytes=store.blobs.size(blob) if store.blobs.has(blob) else 0,
        )
        for rel_path, blob in record.outputs
    ]


def exports_projection(store: OpStore, part: str) -> dict[str, Any]:
    """``GET /parts/{part}/exports`` — the committed ``tp_exports`` rows.

    §22.6's second consequence made visible: *"Export is the first affordance in
    the workspace that lets a browser user create an unbounded, un-collectable
    retention obligation … That is not a reason to refuse it; it is a reason to
    **show** it, which is why §22.7's panel carries an export history with a
    running byte total rather than a fire-and-forget button."* The total is this
    document's, not the panel's — §1: numbers are the server's.

    **``COMMITTED`` rows only, and that is a statement rather than a filter.** A
    ``FROZEN`` row is an export whose source was frozen and whose files were
    never installed; it names no blob, nothing can be downloaded from it, and
    listing it would put a row in a history that the download route refuses by
    name. The state is reported on every row anyway, so the column is not a
    secret the projection keeps.

    Ordered by insertion (``rowid``): ``tp_exports`` carries no timestamp, and
    inventing one from the blob store's mtimes would be a derived fact
    (``architecture.md`` §4.4). Insertion order is the true order of a
    single-writer WAL.
    """
    exports: list[dict[str, Any]] = []
    total = 0
    for record in export_records(store, part=part):
        files = _files_of(store, record)
        row_bytes = sum(f.size_bytes for f in files)
        total += row_bytes
        exports.append(
            {
                "op_id": record.op_id,
                "format": record.recorded_format,
                "layout": record.layout,
                "state": record.state,
                "source_artifact_ref": record.source_artifact_ref,
                "source_input_hashes": dict(record.source_input_hashes),
                "extra": dict(record.extra),
                "outputs": [f.to_json() for f in files],
                "total_bytes": row_bytes,
            }
        )
    return {
        "status": "ok",
        "part": part,
        "exports": exports,
        "total_bytes": total,
        # §22.6's DECISION, as a fact the client renders rather than a sentence it
        # authors: there is no unpin and no delete on this surface, and the panel
        # must say so. The flag is here so the client is not asserting a server
        # policy of its own (§1).
        "unpin_available": False,
        "max_download_bytes": EXPORT_MAX_BYTES,
    }


def find_export(store: OpStore, blob: str) -> ExportedFile:
    """The committed output named ``blob``, or 404 :data:`UNKNOWN_EXPORT_REASON`.

    §22.3's TIGHTENING, which is the whole authorization of the byte route:
    *"serves a blob **only** when it is named by the ``outputs`` column of a
    ``tp_exports`` row in the **``COMMITTED``** state in the open project. Not
    'stored'. Not 'pinned'."*

    The match is on each row's own decoded ``outputs`` rather than a JSON scan
    with ``LIKE``: a ``LIKE '%<blob>%'`` over that column would match a blob
    named in any position of any row — including a *source* hash — which is
    exactly the widening this clause exists to prevent.
    """
    for record in export_records(store):
        for file in _files_of(store, record):
            if file.blob == blob:
                return file
    raise HttpRefusal(
        404,
        UNKNOWN_EXPORT_REASON,
        f"{blob} is not an output of any committed export in the open project",
        data={"blob": blob},
    )


def export_bytes(store: OpStore, blob: str) -> tuple[bytes, ExportedFile]:
    """``GET /exports/{blob}/bytes`` — the file, once both checks have passed.

    Two authorizations in series, and the second is deliberately the *shared*
    one (§22.3: *"The extraction is shared: it calls the same ``_blob()``
    reachability check, so mission rule 6 is satisfied by construction"*):

    1. :func:`find_export` — a ``COMMITTED`` row in the open project names this
       blob. This is the narrow one, and it is what makes egress a named
       operation instead of a second blob-fetch primitive.
    2. :func:`~hephaestus.http.artifacts.reachable_blob` — the very function
       ``GET /artifacts/{ref}/bytes`` uses, under an ``artifact:export:…`` ref.
       It re-checks reachability from the open project's opstore **and** runs
       §19.24's kind binding, so a blob a committed row names but the store
       published under some other kind cannot be served here either. There is one
       blob-reading path in this layer, not two.

    :data:`EXPORT_TOO_LARGE_REASON` is raised from the recorded size **before**
    the bytes are read, so a file above the ceiling never enters this process's
    memory on its way to being refused (§22.4).
    """
    file = find_export(store, blob)
    if file.size_bytes > EXPORT_MAX_BYTES:
        raise HttpRefusal(
            413,
            EXPORT_TOO_LARGE_REASON,
            f"{file.rel_path} is {file.size_bytes} bytes, above this workspace's "
            f"{EXPORT_MAX_BYTES}-byte download ceiling; the file is on disk under "
            f"{EXPORTS_DIR}",
            data={
                "blob": blob,
                "bytes": file.size_bytes,
                "limit_bytes": EXPORT_MAX_BYTES,
                # The recorded path, as body text — the CLI path §22.4 requires
                # the refusal to carry. It is never a header (§22.3).
                "path": str(PurePosixPath(EXPORTS_DIR) / file.rel_path),
            },
        )
    return reachable_blob(store, artifact_ref(EXPORT_ARTIFACT_KIND, blob)), file


def export_arguments(body: dict[str, Any], *, part: str, template: str) -> dict[str, Any]:
    """The tool arguments for one export route, or a named refusal (§22.1, §22.5).

    Three rules, each of them a §22 DECISION rather than a validation habit:

    * **the path wins over the body** for ``name``, as on every part-addressed
      route: a request whose path says ``tread`` and whose body says ``riser``
      must not export ``riser``;
    * **``artifact_ref`` is required and is never ``null``** (§22.5, and the most
      important decision in the section). ``_freeze_export_source`` has two
      branches, and with ``artifact_ref=None`` it resolves
      ``publisher.current_result(name)`` **at export time** — so a ``null`` ref
      means the operator looks at build A, clicks Export, and receives a STEP of
      build B because B published in between. That is the silent
      fallback-to-current ``architecture.md`` §4.4 forbids outright. *The exported
      file must be the geometry on screen or the workspace is lying with a
      download.* The client sends ``WorkspaceState.artifact_ref`` verbatim;
      "current" is not a value this route understands;
    * **``target`` and ``kerf_mm`` are refused by name**, not ignored (see
      :data:`REFUSED_EXPORT_ARGUMENTS`).

    Everything else — ``format``, ``layout``, ``blank``, ``kind``, ``sheet`` — is
    forwarded untouched to the canonical schema validator ``app.py`` already runs,
    so this function never becomes a second copy of the tool's enums. §22.1's
    *"the engine's enum **is** the closed vocabulary"* survives only if exactly
    one place enumerates it, and that place is ``contract/tools_decl.py``.
    """
    if template not in EXPORT_ROUTE_TOOLS:  # pragma: no cover - call sites are the table
        raise HttpRefusal(404, "not_found", f"{template} is not an export route")
    refused = [key for key in REFUSED_EXPORT_ARGUMENTS if key in body]
    if refused:
        raise HttpRefusal(
            400,
            "invalid_params",
            "the workspace never sends "
            + " or ".join(sorted(refused))
            + ": the export filename is the server's and the kerf is the DFM "
            "pack's (INTERFACE.md §22.1)",
            data={"refused": sorted(refused)},
        )
    if "artifact_ref" not in body or body["artifact_ref"] is None:
        raise HttpRefusal(
            400,
            "invalid_params",
            "artifact_ref is required and is never null: an export resolved at "
            "click time would freeze a different build than the one on screen "
            "(INTERFACE.md §22.5)",
            data={"field": "artifact_ref"},
        )
    return {**body, "name": part}
