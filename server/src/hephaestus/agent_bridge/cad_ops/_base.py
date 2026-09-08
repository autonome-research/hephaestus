"""Shared state, persisted-override storage and the error taxonomy for CadOps.

Every domain mixin in this package derives from :class:`CadOpsState`, which owns
the three things the operations share — the project layout, the opstore and the
execution backend — plus the helpers built directly on them: publisher/render/
check-set constructors, scratch and build directories, the sandboxed build call,
and geometry resolution from artifact or project-snapshot refs.

Also here, because they sit *below* every domain: :class:`CadOpError` (the stable
machine-token refusal every op raises), :class:`ParamStore` (the CAS-pointer
override document each scope persists, journaled and idempotent on the trusted
invocation id) and the JSON decoding helpers that read worker results and
WAL-recorded outcomes.
"""

from __future__ import annotations

import contextlib
import difflib
import json
import shutil
import tempfile
import uuid
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.checks.engine import CheckSet
from hephaestus.core.checks.facade import GeometrySource
from hephaestus.core.executor.artifact_geometry import ArtifactGeometry, published_source_for
from hephaestus.core.executor.imports import ImportPayload
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.projections import PROJECT_SNAPSHOT_REF_PREFIX
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.project_store.store import (
    blob_hash_of_ref,
)
from hephaestus.core.registry import TEXT_MAX_BYTES, TEXT_MAX_LINES, RegistrySet

# The skill loader's tested pager, reused rather than re-implemented
# (ledger J-http-limits-3). ``hephaestus.core.registry.__init__`` re-exports
# the two limits but not the pager itself; importing the defining module is
# the honest form until that package chooses to widen its own surface.
from hephaestus.core.registry._reference import Page, paginate
from hephaestus.core.render.inspect import RenderProject
from opstore.types import JSONValue

from opstore import (
    Fresh,
    OpStore,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_canonical_json,
)

from ._request import request_text_for_active_run

#: The artifact kind an immutable snapshot of ``checks/<name>.py`` is minted
#: under. It used to be ``part-snapshot`` because that kind was already
#: registered as readable Python source and the reference therefore *worked* —
#: but the kind is the type tag in an otherwise opaque capability, and a reader
#: holding one could not tell whether it snapshots a part script or a check
#: script (audit-2026-09-04 J-agent-results-S5). It lives HERE, below every
#: domain, because three modules must agree on it and none of them may import
#: the others: ``_checks`` mints it, ``_artifacts`` registers its mime so the
#: reference stays readable, and ``dispatch`` reconstructs a base reference from
#: a caller's expected hash — and a client's own reconstruction must match the
#: server's byte for byte.
CHECK_SNAPSHOT_KIND: Final[str] = "check-snapshot"

#: The kind check snapshots were minted under before that change. Accepted on
#: *read* for one release: retained check-report and journal evidence carries
#: it, and a reference already handed to a model must not become unreadable
#: because the server renamed a type tag.
LEGACY_CHECK_SNAPSHOT_KIND: Final[str] = "part-snapshot"

#: CAS pointer holding a part's persisted parameter-override document.
PART_PARAMS_POINTER_PREFIX: Final[str] = "part-params:"
#: CAS pointer holding the project's persisted parameter-override document.
PROJECT_PARAMS_POINTER: Final[str] = "project-params"


class CadOpError(Exception):
    """A core-backed operation refused; ``reason`` is a stable machine token."""

    def __init__(
        self, reason: str, message: str, *, data: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.data: dict[str, JSONValue] = dict(data or {})


# --------------------------------------------------------------------------
# JSON decoding helpers


def recorded_ref(response: str | None, key: str, fallback: str) -> str:
    """A field of a WAL-recorded ``intended_outcome`` (used on replay)."""
    if response is None:  # tombstone replay: only the terminal state survives
        return fallback
    try:
        decoded = cast("Mapping[str, JSONValue]", json.loads(response))
    except (ValueError, TypeError):  # pragma: no cover - responses are our own JSON
        return fallback
    value = decoded.get(key)
    return value if isinstance(value, str) else fallback


def numeric_map(raw: JSONValue | None) -> dict[str, int | float]:
    out: dict[str, int | float] = {}
    if not isinstance(raw, dict):
        return out
    for name, value in cast("Mapping[str, JSONValue]", raw).items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        out[name] = value
    return out


def json_map(raw: JSONValue | None) -> dict[str, JSONValue]:
    if not isinstance(raw, dict):
        return {}
    return dict(cast("Mapping[str, JSONValue]", raw))


def _names_artifact(bundle: Mapping[str, JSONValue], artifact_ref: str) -> bool:
    """True when ``bundle`` records ``artifact_ref``, or records none at all.

    A bundle written before publication stored the ref names no artifact and is
    taken at its word; one that names a different artifact is a store we should
    not read from (``Publisher.bundle_for_artifact`` refuses the same way).
    """
    recorded = bundle.get("artifact_ref")
    return not isinstance(recorded, str) or recorded == artifact_ref


# --------------------------------------------------------------------------
# persisted parameter overrides


def params_pointer(scope: str, name: str | None) -> str:
    """The CAS pointer holding one scope's persisted override document."""
    if scope == "project":
        return PROJECT_PARAMS_POINTER
    if not name:
        raise CadOpError("invalid_params", "part scope requires a part name")
    return PART_PARAMS_POINTER_PREFIX + name


@dataclass(frozen=True)
class ParamState:
    """A scope's persisted override document plus its optimistic state hash."""

    scope: str
    name: str | None
    values: Mapping[str, int | float]
    state_hash: str
    blob: str | None  # pointer target the state was read from (None = unset)

    def to_json(self) -> dict[str, JSONValue]:
        return {"scope": self.scope, "name": self.name, "values": dict(self.values)}


class ParamConflict(CadOpError):
    """A stale ``expected_state_hash``: carries the live state, nothing written."""

    def __init__(self, current: ParamState) -> None:
        super().__init__(
            "stale_state_hash",
            f"parameter state for {current.scope} {current.name!r} moved to {current.state_hash}",
        )
        self.current = current


def _override_document(values: Mapping[str, int | float]) -> JSONValue:
    return {"values": {name: values[name] for name in sorted(values)}}


class ParamStore:
    """Durable, journaled, idempotent parameter-override documents over opstore."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self._layout = layout
        self._store = store

    def read(self, scope: str, name: str | None) -> ParamState:
        """The persisted overrides for one scope (empty when never written)."""
        pointer = params_pointer(scope, name)
        blob = self._store.blobs.read_pointer(pointer)
        values: dict[str, int | float] = {}
        if blob is not None:
            raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
            recorded = cast("Mapping[str, JSONValue]", raw).get("values")
            if isinstance(recorded, dict):
                for key, value in cast("Mapping[str, JSONValue]", recorded).items():
                    if isinstance(value, bool) or not isinstance(value, int | float):
                        continue
                    values[key] = value
        return ParamState(
            scope=scope,
            name=name,
            values=values,
            state_hash=sha256_canonical_json(_override_document(values)),
            blob=blob,
        )

    def write(
        self,
        scope: str,
        name: str | None,
        values: Mapping[str, int | float],
        *,
        expected_state_hash: str,
        op_id: str,
    ) -> tuple[ParamState, str]:
        """CAS the override document; returns the new state and its journal ref.

        Raises :class:`ParamConflict` when ``expected_state_hash`` is stale
        (nothing is written). Idempotent on ``op_id``.
        """
        pointer = params_pointer(scope, name)
        current = self.read(scope, name)
        document = _override_document(values)
        new_blob = self._store.blobs.put(canonical_json(document).encode("utf-8"))
        # The idempotency payload is the *request* (presented base + candidate),
        # never the live state — otherwise a retry after a committed write would
        # hash differently and be misreported as a payload mismatch.
        payload: JSONValue = {
            "kind": "param_write",
            "scope": scope,
            "name": name,
            "expected_state_hash": expected_state_hash,
            "after": new_blob,
        }
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            # The recorded response names the journal entry of the original write.
            return self.read(scope, name), recorded_ref(
                outcome.response, "journal", make_artifact_ref("param-journal", new_blob)
            )
        if not isinstance(outcome, Fresh):
            raise CadOpError(
                "conflict", f"parameter write {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        if current.state_hash != expected_state_hash:
            self._store.wal.recover(outcome.op_key)  # abort the fresh skeleton
            raise ParamConflict(current)
        journal_ref = self._journal(scope, name, current, new_blob)
        self._store.wal.publish(
            outcome,
            pointer,
            current.blob,
            new_blob,
            intended_outcome=canonical_json({"published": new_blob, "journal": journal_ref}),
        )
        return self.read(scope, name), journal_ref

    def _journal(self, scope: str, name: str | None, before: ParamState, after_blob: str) -> str:
        """Journal the previous override document under ``.heph/journal/``."""
        entry: JSONValue = {
            "kind": "param_write",
            "scope": scope,
            "name": name,
            "before": dict(before.values),
            "before_state_hash": before.state_hash,
            "after_blob": after_blob,
        }
        payload = canonical_json(entry).encode("utf-8")
        blob = self._store.blobs.put(payload)
        self._layout.journal_dir.mkdir(parents=True, exist_ok=True)
        (self._layout.journal_dir / f"params-{blob.removeprefix('sha256:')[:32]}.json").write_bytes(
            payload
        )
        return make_artifact_ref("param-journal", blob)


# --------------------------------------------------------------------------
# bounded source pages: the read/edit tools' paging and near-miss contract


@dataclass(frozen=True)
class SourcePage:
    """One bounded slice of a text source, with absolute line and byte cursors.

    ``tools_decl`` gives ``read_part`` / ``read_globals`` / ``read_project_check``
    an ``offset_line`` / ``limit_lines`` pair and splices four paging members
    into their results, and until ledger J-http-limits-3 all three handlers
    returned the whole document with ``truncated: false`` and no cursor (RC-9).
    The sidecar's text renderer then cut the oversized result at its own byte
    budget, so the model received a JSON string chopped mid-value beside a
    result claiming it was complete — the one loss the paging contract exists
    to prevent.

    The paging itself is :func:`hephaestus.core.registry._reference.paginate`,
    the tested pager the skill loader already stands on: one implementation of
    "greedy page under a line count and a wire-byte budget, reporting a single
    line too large to ever fit", not a fourth.
    """

    body: str
    #: 1-based, inclusive; ``last_line + 1`` when the page is empty.
    first_line: int
    #: 1-based, inclusive; ``first_line - 1`` when the page is empty.
    last_line: int
    total_lines: int
    total_bytes: int
    truncated: bool
    oversized_line: bool
    #: Absolute byte offset of the next unread line, for ``read_artifact`` over
    #: the same snapshot ref. ``None`` when the page reached the end.
    next_offset_bytes: int | None
    #: 1-based line to pass back as ``offset_line``. ``None`` at the end. The
    #: byte cursor cannot be fed back to a *line*-paged tool, which is why both
    #: are reported rather than only the one the pager computes.
    next_offset_line: int | None
    oversized_line_offset_bytes: int | None


def page_source(
    content: str, *, offset_line: int = 1, limit_lines: int = TEXT_MAX_LINES
) -> SourcePage:
    """Page ``content`` under the §5 dual text cap from an absolute line offset."""
    data = content.encode("utf-8")
    raw_lines = data.splitlines(keepends=True)
    starts: list[int] = []
    cursor = 0
    for line in raw_lines:
        starts.append(cursor)
        cursor += len(line)
    starts.append(len(data))

    total_lines = len(raw_lines)
    first = max(0, int(offset_line) - 1)
    limit = max(1, min(int(limit_lines), TEXT_MAX_LINES))
    if first >= total_lines:
        # An offset past the end is an EMPTY page, never the whole file: the
        # caller asked for lines that do not exist and answering with lines it
        # did not ask for is how a model loses its place in a large script.
        page = Page(
            body="",
            end_line=total_lines,
            truncated=False,
            oversized_line=False,
            next_offset_bytes=None,
            oversized_line_offset_bytes=None,
        )
    else:
        page = paginate(raw_lines, starts, first, limit, max(1, TEXT_MAX_BYTES))
    return SourcePage(
        body=page.body,
        first_line=first + 1,
        # An empty page reports `first_line - 1`, so the window is empty
        # rather than inverted: an offset past the end asked for lines
        # that do not exist and the answer is that none were returned.
        last_line=page.end_line if page.end_line > first else first,
        total_lines=total_lines,
        total_bytes=len(data),
        truncated=page.truncated,
        oversized_line=page.oversized_line,
        next_offset_bytes=page.next_offset_bytes,
        next_offset_line=page.end_line + 1 if page.truncated else None,
        oversized_line_offset_bytes=page.oversized_line_offset_bytes,
    )


def numbered_source(body: str, *, start: int = 1) -> str:
    """``body`` with absolute line numbers, starting at ``start``.

    ``start`` is not decoration: the helper always numbered from one, so every
    page after the first would have labelled its lines with the wrong numbers —
    and an ``edit_part`` built from those numbers would target the wrong text.
    """
    lines = body.splitlines()
    width = len(str(max(start + len(lines) - 1, 1)))
    return "\n".join(f"{i:>{width}}  {line}" for i, line in enumerate(lines, start=start))


def paging_fields(page: SourcePage, *, prefix: str = "") -> dict[str, JSONValue]:
    """The declared paging members for ``page``; cursors omitted when absent.

    ``prefix`` renders the same facts under the conflict payload's
    ``current_*`` names, so a stale-hash conflict and a read report the page
    they carry in one vocabulary.
    """
    fields: dict[str, JSONValue] = {
        f"{prefix}truncated": page.truncated,
        f"{prefix}oversized_line": page.oversized_line,
    }
    if not prefix:
        # A conflict payload always pages from line 1, so its window is not a
        # fact worth a field; a read's is.
        fields["first_line"] = page.first_line
        fields["last_line"] = page.last_line
        fields["total_lines"] = page.total_lines
        fields["total_bytes"] = page.total_bytes
    if page.next_offset_line is not None:
        fields[f"{prefix}next_offset_line"] = page.next_offset_line
    if page.next_offset_bytes is not None:
        fields[f"{prefix}next_offset_bytes"] = page.next_offset_bytes
    if page.oversized_line_offset_bytes is not None:
        fields[f"{prefix}oversized_line_offset_bytes"] = page.oversized_line_offset_bytes
    return fields


def conflict_payload(
    *,
    current_hash: str | None,
    current_script: str | None,
    current_snapshot_ref: str | None,
    base_snapshot_ref: str | None = None,
    attempted_snapshot_ref: str | None = None,
) -> dict[str, JSONValue]:
    """The ONE stale-hash conflict document, for every editor and both paths.

    ``edit_part`` had two conflict shapes — a three-field one built by its own
    pre-check and the full declared one built by the store's compare-and-set
    failure — while the declaration lists nine members (ledger
    J-agent-results-2). One tool, two shapes, is what makes the continuation
    rule unenforceable: a model receiving no truncation flag cannot know
    whether the ``current_script`` it got back is the whole file. This builds
    the declared set once, with the page cap applied and the continuation
    cursors set when they bite.
    """
    # A store conflict can be raised without live content (the part vanished
    # between the read and the write); the members stay present and null rather
    # than absent, so a consumer branches on a value instead of on a key.
    page = page_source(current_script or "")
    payload: dict[str, JSONValue] = {
        "current_hash": current_hash,
        "current_script": None if current_script is None else page.body,
        "current_snapshot_ref": current_snapshot_ref,
        **paging_fields(page, prefix="current_"),
    }
    # Always PRESENT, null when unknown: the declared field set is what a
    # consumer branches on, and an absent key and a null one are different
    # facts to a reader that does `"base_snapshot_ref" in conflict`. Only the
    # continuation CURSORS are omitted when absent — a cursor that does not
    # apply has no null to mean.
    payload["base_snapshot_ref"] = base_snapshot_ref
    payload["attempted_snapshot_ref"] = attempted_snapshot_ref
    return payload


def attempted_snapshot(
    store: OpStore, base_hash: str, old_str: str, new_str: str, *, kind: str
) -> str | None:
    """Register the candidate the caller MEANT to write, from its own base.

    The edit is replayed against the immutable snapshot registered for
    ``expected_hash`` — not against the live file, which is a *different*
    document — so ``attempted_snapshot_ref`` names exactly the bytes the caller
    intended. ``edit_project_check`` used to answer with the live snapshot ref
    instead, handing back the file already on disk under the name of the
    rejected contender (ledger J-agent-results-2, the same defect class as
    J-agent-results-9: a field whose value is not what its name says).

    ``None`` when that base was never registered here (a fabricated hash, or one
    from another project) or when ``old_str`` does not match it exactly once:
    there is then no single candidate to name, and inventing one would misreport
    the caller's intent. ``kind`` is the artifact kind to mint, so a check
    snapshot is not minted as a part snapshot (J-agent-results-S5).
    """
    from hephaestus.core.project_store.artifact_kinds import record_artifact_kind

    if not base_hash.startswith("sha256:") or not store.blobs.has(base_hash):
        return None
    base = store.blobs.get(base_hash).decode("utf-8", errors="replace")
    if base.count(old_str) != 1:
        return None
    attempted = store.blobs.put(base.replace(old_str, new_str, 1).encode("utf-8"))
    record_artifact_kind(store, kind, attempted)
    return make_artifact_ref(kind, attempted)


#: How many near misses an exact-match failure reports, and the similarity a
#: window must reach to be one. Both are constants rather than tuning knobs
#: because the tool result feeds the bench: a non-deterministic candidate list
#: would make two identical runs produce two different transcripts.
NEAR_MISS_LIMIT: Final[int] = 3
NEAR_MISS_CUTOFF: Final[float] = 0.6


def near_misses(content: str, old_str: str) -> list[JSONValue]:
    """At most :data:`NEAR_MISS_LIMIT` ``{line, text, ratio}`` near misses.

    ``tool_schema.md`` promises an exact-match failure returns the closest
    candidates and no editor implemented it (ledger J-agent-results-2): the
    model's only recourse was to re-read the file and guess. The pass slides a
    window the size of ``old_str`` over the file's lines and keeps the closest
    ones, ordered by descending ratio then by line, so the list is a function
    of the two inputs alone.
    """
    needle = old_str.strip("\n")
    if not needle:
        return []
    lines = content.splitlines()
    span = max(1, len(needle.splitlines()))
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(needle)
    scored: list[tuple[float, int, str]] = []
    for index in range(0, max(0, len(lines) - span + 1)):
        window = "\n".join(lines[index : index + span])
        matcher.set_seq1(window)
        # The two cheap upper bounds first: a full ratio() over every window of
        # a large script is the one thing that could make a failed edit slow.
        if matcher.real_quick_ratio() < NEAR_MISS_CUTOFF:
            continue
        if matcher.quick_ratio() < NEAR_MISS_CUTOFF:
            continue
        ratio = matcher.ratio()
        if ratio < NEAR_MISS_CUTOFF:
            continue
        scored.append((ratio, index + 1, window))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [
        cast("JSONValue", {"line": line, "text": text, "ratio": round(ratio, 4)})
        for ratio, line, text in scored[:NEAR_MISS_LIMIT]
    ]


# --------------------------------------------------------------------------
# the state every domain mixin shares


class CadOpsState:
    """The layout/opstore/backend triple and the helpers built on top of it."""

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        backend: ExecBackend,
    ) -> None:
        self._layout = layout
        self._store = store
        # REQUIRED, with no default (ledger J-agent-wiring-4). This parameter
        # used to default to ``UnsafeLocalBackend()`` "for fast tests", and the
        # one production caller that injected nothing — ``BridgeRuntime``, the
        # runtime behind ``heph agent`` and ``heph mcp`` — inherited it, so the
        # test default was the shipped default and every model-authored script
        # ran with no OS sandbox at all.
        # ``core/executor/sandbox/unsafe.py``'s governing clause is "Never a
        # default"; making the parameter required is what enforces it, because
        # omitting it is now a ``TypeError`` at the call site rather than an
        # unsandboxed build at run time. Callers that genuinely want the unsafe
        # backend (the fixtures and the stage suites) say so in one word.
        self._backend: ExecBackend = backend
        self.params = ParamStore(layout, store)
        # The *embedder's* request, for a caller that is not a run at all: the
        # HTTP tool routes, MCP, a test driving CadOps directly. A run's own text
        # is bound per run (``_request.py``) and outranks this — see
        # :attr:`request_text`.
        self._request_text: str | None = None

    @property
    def layout(self) -> ProjectLayout:
        return self._layout

    # -- registries --------------------------------------------------------

    #: The project's verified registry set, opened once per ops object. Cached
    #: on the state rather than per mixin so the DFM rule packs, the bill of
    #: materials and ``measure``'s density binding all read one verified set —
    #: opening it twice would verify the same Merkle pin twice and, worse,
    #: could observe two different ones across a re-pin mid-call.
    _registry_set: RegistrySet | None = None

    def registries(self) -> RegistrySet:
        """The project's verified registry set (loaded once per ops object)."""
        if self._registry_set is None:
            self._registry_set = RegistrySet.open(self._layout.root)
        return self._registry_set

    # -- the original request (VALIDATION.md §4 / §5) -----------------------

    @property
    def request_text(self) -> str | None:
        """The request **this run** is working from, or None when unknown.

        ``VALIDATION.md`` §4 diffs the numbers in the request against the built
        geometry, and §5 hands the reviewer the request verbatim; both need the
        text to reach the ops layer, which the bridge does by binding it on the
        run's prompt. Unknown is a first-class state: a critique with no request
        **omits** ``prompt_number_diff`` rather than inventing one.

        ``INTERFACE.md`` §7A.4 / §19.23: the binding is per **run**, not per
        object. One field on ``CadOps`` was shared by every session, so two
        overlapping turns made session A's build get critiqued against session
        B's prompt — a fabricated request diff. The dispatcher scopes each tool
        call to the run that issued it (``_request.active_run``) and this reads
        that run's own text; the object's field answers only for callers that
        are not runs (HTTP tool routes, MCP, direct tests).
        """
        return request_text_for_active_run(self._request_text)

    def set_request_text(self, text: str | None) -> None:
        """Bind the *embedder's* request text, for callers that are not runs.

        A run binds its own text through ``BridgeRuntime.prompt``, which is what
        makes the §7A.4 invariant survive concurrency; this setter remains for
        the surfaces that have no run to bind to and is not what the agent path
        uses. It is deliberately **not** reachable from inside a run: writing it
        mid-turn would be writing the one shared field §19.23 exists to remove.
        """
        cleaned = text.strip() if text is not None else None
        self._request_text = cleaned or None

    def _publisher(self) -> Publisher:
        return Publisher(self._layout, self._store)

    def _render_project(self) -> RenderProject:
        return RenderProject(layout=self._layout, store=self._store)

    def _check_set(self) -> CheckSet:
        return CheckSet(self._layout.checks_dir, self._store)

    def _scratch(self, prefix: str) -> tempfile.TemporaryDirectory[str]:
        self._layout.store_root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix=prefix, dir=self._layout.store_root)

    def _project_overrides(self) -> dict[str, int | float | str]:
        """Manifest ``[params]`` merged under the persisted project overrides."""
        merged: dict[str, int | float | str] = dict(self._layout.manifest.params)
        merged.update(self.params.read("project", None).values)
        return merged

    def _sync_projections(self, publisher: Publisher, hc_state: Mapping[str, JSONValue]) -> None:
        """Advance the audit revision to a worker-computed live ``hc`` projection."""
        live = publisher.projections.state().hc_state
        if canonical_json(dict(live)) != canonical_json(dict(hc_state)):
            publisher.projections.apply_hc_state(
                hc_state, reason="globals.py or project parameters changed"
            )

    @contextlib.contextmanager
    def _build_dir(self, part: str) -> Generator[Path]:
        """A scratch output directory that outlives the build until publication.

        Artifact *files* live here until the publisher installs them as
        content-addressed blobs, so the tree may only be removed after the caller
        is done with ``UnpublishedBuild.artifact_files``.
        """
        out_dir = self._layout.store_root / "builds" / f"{part}-{uuid.uuid4().hex[:12]}"
        try:
            yield out_dir
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def _run(
        self,
        part: str,
        script: str,
        globals_source: str | None,
        *,
        out_dir: Path,
        part_overrides: Mapping[str, int | float | str],
        project_overrides: Mapping[str, int | float | str],
        baseline: object = None,
        imports: Mapping[str, ImportPayload] | None = None,
        import_errors: Mapping[str, str] | None = None,
    ) -> UnpublishedBuild:
        request = BuildRequest(
            part=part,
            script=script,
            globals_source=globals_source,
            part_overrides=dict(part_overrides),
            project_overrides=dict(project_overrides),
            origin="local",
            # INGEST.md §1: the frozen import payloads travel with the
            # request, so a retry replays the original content rather than
            # whatever is on disk now. A payload rather than bare bytes since
            # Stage 12 (``MESH_INGEST.md`` §1.1): the declared kind and unit
            # have to reach the staging code, and a mapping to bytes carries
            # neither.
            imports=dict(imports or {}),
            import_errors=dict(import_errors or {}),
        )
        return run_build(
            request,
            backend=self._backend,
            out_dir=out_dir,
            baseline=cast("Any", baseline),
        )

    # -- geometry resolution (measure and project checks share this) --------

    def _snapshot_sources(
        self, snapshot_ref: str, scratch: Path
    ) -> tuple[dict[str, GeometrySource], list[str]]:
        if not snapshot_ref.startswith(PROJECT_SNAPSHOT_REF_PREFIX):
            raise CadOpError("invalid_params", f"{snapshot_ref} is not a project-snapshot ref")
        blob = blob_hash_of_ref(snapshot_ref)
        if not self._store.blobs.has(blob):
            raise CadOpError(
                "invalid_params", f"project snapshot {snapshot_ref} is not durably stored"
            )
        manifest = cast(
            "Mapping[str, JSONValue]", json.loads(self._store.blobs.get(blob).decode("utf-8"))
        )
        parts_raw = manifest.get("parts")
        if not isinstance(parts_raw, dict):
            raise CadOpError("invalid_params", f"project snapshot {snapshot_ref} is malformed")
        sources: dict[str, GeometrySource] = {}
        refs: list[str] = [snapshot_ref]
        for name, entry in sorted(cast("Mapping[str, JSONValue]", parts_raw).items()):
            if not isinstance(entry, dict):
                continue
            record = cast("Mapping[str, JSONValue]", entry)
            ref = record.get("artifact_ref")
            if not isinstance(ref, str):
                continue
            # Manifest version 2 names the bundle the snapshot froze; version 1
            # does not, and the (part, artifact) pointer answers for it.
            bundle_ref = record.get("bundle_ref")
            sources[name] = self._artifact_geometry(
                ref,
                scratch,
                part=name,
                bundle_ref=bundle_ref if isinstance(bundle_ref, str) else None,
            )
            refs.append(ref)
        return sources, refs

    def _artifact_geometry(
        self,
        ref: str,
        scratch: Path,
        *,
        part: str | None = None,
        bundle_ref: str | None = None,
    ) -> ArtifactGeometry:
        """One published artifact as an addressable §7 source.

        ``part`` is what makes the full grammar reachable (audit-2026-09-04
        B-1): the build's recorded namespace is keyed by the part that published
        it, because an artifact ref is content-addressed over BRep bytes alone
        and two parts with identical geometry share one. Without a part this
        falls back to ``"part"``-only addressing rather than picking a namespace
        that may belong to a different part.
        """
        blob = blob_hash_of_ref(ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_params", f"artifact {ref} is not durably stored")
        bundle = self._artifact_bundle(ref, part=part, bundle_ref=bundle_ref)
        return published_source_for(
            self._store,
            part=part,
            artifact_ref=ref,
            bundle=bundle,
            scratch_dir=scratch,
        )

    def _artifact_bundle(
        self, ref: str, *, part: str | None, bundle_ref: str | None
    ) -> Mapping[str, JSONValue] | None:
        """What publication recorded ABOUT one build, or ``None`` if unrecorded."""
        if bundle_ref is not None:
            blob = blob_hash_of_ref(bundle_ref)
            if self._store.blobs.has(blob):
                raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
                # The same guard ``Publisher.bundle_for_artifact`` puts on the
                # pointer path, spelled once more because a manifest is just
                # another way of naming a bundle: one that names a DIFFERENT
                # artifact would resolve this ref's selectors against another
                # build's namespace, which is the silent wrong answer §7 forbids.
                if isinstance(raw, dict) and _names_artifact(
                    cast("Mapping[str, JSONValue]", raw), ref
                ):
                    return cast("Mapping[str, JSONValue]", raw)
        if part is None:
            return None
        return self._publisher().bundle_for_artifact(part, ref)
