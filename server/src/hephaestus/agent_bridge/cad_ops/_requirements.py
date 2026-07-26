"""The requirement ledger: interpretation as an inspectable project artifact.

``VALIDATION.md`` §2. Before any geometry the agent emits one entry per
constraint — ``specified`` (traceable to a phrase of the request, ``quote``
required), ``derived`` (computed from other entries, ``from`` lists their ids)
or ``assumed`` (the model supplied it; ``rationale`` required and ``material``
declares whether it moves geometry). Every later rung reads this ledger: the
clarification gate refuses ``build_part`` on an unresolved *material* assumption
(§3), the reviewer scores per requirement (§5), and ``heph lint`` flags a
``specified`` entry whose quote is not in the request (§2).

Storage mirrors the check-set generation pattern
(:class:`hephaestus.core.checks.engine.CheckSet`): each generation is an
immutable content-addressed state document
(``artifact:requirements:sha256:…``) naming its parent, published by a CAS swap
of the ``requirements-state`` pointer under the **project-config lock**. Older
generations stay readable forever, which is what lets an idempotent replay
return exactly the state its original call produced rather than whatever the
pointer names now.

Validation is structural and happens here, not in a prompt: a ``specified``
entry without a quote, a ``derived`` entry whose ``from`` does not resolve, or
an ``assumed`` entry without a rationale and a ``material`` flag is refused with
``invalid_requirement`` and nothing is written.

**Two fields are not the model's to write.** ``asked`` and ``resolution`` record
what happened when a human was consulted, and everything downstream keys on them:
the §3 gate opens on them, §5 treats an assumption without a ``resolution`` as a
failure however confidently it is argued, and §8's ``clarification_rate`` counts
``asked``. A model that could set them would be grading its own clarification —
so :data:`RUNTIME_ONLY_FIELDS` is refused on every model-facing write
(``record_requirements`` and ``update_requirement``) and may only be written
through ``provenance="runtime"``, which is reachable from exactly one place:
:func:`.._gate.record_clarification_answer`, applying a real ``ask_user`` answer.
Their presence on a stored entry is therefore itself the provenance — no separate
provenance field can drift from the value it describes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, cast

from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.project_store.store import (
    blob_hash_of_ref,
)
from hephaestus.core.tools_decl import REQUIREMENT_ID_PATTERN, REQUIREMENT_SOURCES
from opstore.types import JSONValue

from opstore import (
    Fresh,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_canonical_json,
)

from ._base import CadOpError, CadOpsState, recorded_ref

__all__ = [
    "REQUIREMENTS_POINTER",
    "REQUIREMENT_ARTIFACT_KIND",
    "REQUIREMENT_ID_PATTERN",
    "REQUIREMENT_SOURCES",
    "RUNTIME_ONLY_FIELDS",
    "LedgerState",
    "RequirementEntry",
    "RequirementOps",
    "entry_views",
    "ledger_state",
]

#: CAS pointer naming the current ledger generation's state blob.
REQUIREMENTS_POINTER: Final[str] = "requirements-state"
#: Artifact kind of an immutable ledger generation document.
REQUIREMENT_ARTIFACT_KIND: Final[str] = "requirements"
_ID_RE: Final[re.Pattern[str]] = re.compile(REQUIREMENT_ID_PATTERN)

#: The clarification record: written by the runtime from a real ``ask_user``
#: answer, never by the model. See the module docstring — this tuple *is* the §3
#: provenance rule.
RUNTIME_ONLY_FIELDS: Final[tuple[str, ...]] = ("asked", "resolution")

#: Marks the one caller allowed to write :data:`RUNTIME_ONLY_FIELDS`.
_RUNTIME: Final[str] = "runtime"


def _reject_runtime_fields(context: str, supplied: Iterable[str]) -> None:
    """Refuse a model-facing write that touches the clarification record."""
    # Materialize first: `supplied` is routinely a generator, and testing each
    # runtime field against a freshly-built set would consume it on the first one.
    names = set(supplied)
    offending = [name for name in RUNTIME_ONLY_FIELDS if name in names]
    if not offending:
        return
    raise CadOpError(
        "invalid_requirement",
        f"{context}: {offending} may only be written by the runtime from a real "
        "ask_user answer, so nothing was written. Ask the user with "
        "ask_user(requirement_ids=[…]) offering concrete options — a committal answer "
        "records the resolution and opens the clarification gate; a declined one "
        "records asked and leaves the assumption unconfirmed for the termination review.",
    )


def _text(raw: JSONValue | None) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise CadOpError("invalid_requirement", f"expected a string, got {type(raw).__name__}")
    return raw


@dataclass(frozen=True)
class RequirementEntry:
    """One ledger entry, exactly the shape ``VALIDATION.md`` §2 fixes."""

    id: str
    text: str
    source: str
    quote: str | None = None
    from_ids: tuple[str, ...] = ()
    rationale: str | None = None
    material: bool | None = None
    value: float | None = None
    unit: str | None = None
    applies_to: str | None = None
    #: §3: a material assumption that produced an ``ask_user`` question. Runtime-
    #: written only (:data:`RUNTIME_ONLY_FIELDS`), so it means *a human was asked*.
    asked: bool = False
    #: §3: the recorded committal answer. Runtime-written only, so its presence is
    #: proof an answer was obtained — never the model's own guess.
    resolution: str | None = None

    @property
    def confirmed(self) -> bool:
        """§5: a human's committal answer is on record for this entry."""
        return bool((self.resolution or "").strip())

    @property
    def unresolved_material(self) -> bool:
        """§3: an assumed, geometry-moving entry with no recorded resolution."""
        return self.source == "assumed" and self.material is True and not self.confirmed

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "quote": self.quote,
            "from": list(self.from_ids),
            "rationale": self.rationale,
            "material": self.material,
            "value": self.value,
            "unit": self.unit,
            "applies_to": self.applies_to,
            "asked": self.asked,
            "resolution": self.resolution,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> RequirementEntry:
        """Build an entry from tool arguments / a stored generation (validated)."""
        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not _ID_RE.match(raw_id):
            raise CadOpError(
                "invalid_requirement",
                f"requirement id {raw_id!r} must match {REQUIREMENT_ID_PATTERN}",
            )
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CadOpError("invalid_requirement", f"requirement {raw_id}: text is required")
        source = data.get("source")
        if source not in REQUIREMENT_SOURCES:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {raw_id}: source must be one of {list(REQUIREMENT_SOURCES)}",
            )
        raw_from = data.get("from")
        from_ids: tuple[str, ...] = ()
        if isinstance(raw_from, list):
            ids: list[str] = []
            for item in cast("list[JSONValue]", raw_from):
                if not isinstance(item, str) or not _ID_RE.match(item):
                    raise CadOpError(
                        "invalid_requirement",
                        f"requirement {raw_id}: 'from' must list requirement ids",
                    )
                ids.append(item)
            from_ids = tuple(ids)
        elif raw_from is not None:
            raise CadOpError(
                "invalid_requirement", f"requirement {raw_id}: 'from' must be an array of ids"
            )
        material = data.get("material")
        if material is not None and not isinstance(material, bool):
            raise CadOpError(
                "invalid_requirement", f"requirement {raw_id}: material must be a boolean"
            )
        value = data.get("value")
        if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
            raise CadOpError("invalid_requirement", f"requirement {raw_id}: value must be a number")
        asked = data.get("asked")
        if asked is not None and not isinstance(asked, bool):
            raise CadOpError(
                "invalid_requirement", f"requirement {raw_id}: asked must be a boolean"
            )
        return cls(
            id=raw_id,
            text=text,
            source=source,
            quote=_text(data.get("quote")),
            from_ids=from_ids,
            rationale=_text(data.get("rationale")),
            material=material,
            value=None if value is None else float(value),
            unit=_text(data.get("unit")),
            applies_to=_text(data.get("applies_to")),
            asked=bool(asked),
            resolution=_text(data.get("resolution")),
        )

    def validated(self) -> RequirementEntry:
        """Enforce the per-source obligations of §2 (raises, never repairs)."""
        if self.source == "specified" and not (self.quote or "").strip():
            raise CadOpError(
                "invalid_requirement",
                f"requirement {self.id}: source='specified' requires a quote from the request",
            )
        if self.source == "derived" and not self.from_ids:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {self.id}: source='derived' requires 'from' entry ids",
            )
        if self.source == "assumed":
            if not (self.rationale or "").strip():
                raise CadOpError(
                    "invalid_requirement",
                    f"requirement {self.id}: source='assumed' requires a rationale",
                )
            if self.material is None:
                raise CadOpError(
                    "invalid_requirement",
                    f"requirement {self.id}: source='assumed' requires material: true|false "
                    "(does this assumption move geometry?)",
                )
        return self


@dataclass(frozen=True)
class LedgerState:
    """One immutable ledger generation: its entries, blob and provenance ref."""

    generation: int
    entries: tuple[RequirementEntry, ...]
    blob: str | None
    parent: str | None = None

    @property
    def artifact_ref(self) -> str | None:
        """``artifact:requirements:sha256:…`` of this generation (None if empty)."""
        if self.blob is None:
            return None
        return make_artifact_ref(REQUIREMENT_ARTIFACT_KIND, self.blob)

    @property
    def by_id(self) -> dict[str, RequirementEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def unresolved_material(self) -> tuple[str, ...]:
        """Ids of assumed+material entries with no recorded resolution (§3)."""
        return tuple(entry.id for entry in self.entries if entry.unresolved_material)

    def document(self) -> JSONValue:
        """The canonical state document this generation is stored as."""
        return {
            "generation": self.generation,
            "parent": self.parent,
            "entries": [entry.to_json() for entry in self.entries],
        }

    def to_json(self) -> dict[str, Any]:
        """The tool-result projection shared by all three ledger tools."""
        return {
            "status": "ok",
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "entries": [entry.to_json() for entry in self.entries],
            "unresolved_material": list(self.unresolved_material),
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> LedgerState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise CadOpError("invalid_requirement", "ledger generation must be an integer")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise CadOpError("invalid_requirement", "ledger entries must be an array")
        entries = tuple(
            RequirementEntry.from_json(cast("Mapping[str, JSONValue]", item))
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


#: The empty ledger every project starts from (generation 0, no blob).
_EMPTY: Final[LedgerState] = LedgerState(generation=0, entries=(), blob=None, parent=None)


class RequirementOps(CadOpsState):
    """``record_requirements`` / ``read_requirements`` / ``update_requirement``."""

    # -- reading -----------------------------------------------------------

    def ledger_state(self) -> LedgerState:
        """The current generation (generation 0 with no entries when unset)."""
        blob = self._store.blobs.read_pointer(REQUIREMENTS_POINTER)
        if blob is None:
            return _EMPTY
        return self._state_from_blob(blob)

    def ledger_generation(self, artifact_ref: str) -> LedgerState:
        """Any historical generation by its immutable artifact ref."""
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_ref", f"ledger generation {artifact_ref} is not stored")
        return self._state_from_blob(blob)

    def _state_from_blob(self, blob: str) -> LedgerState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise CadOpError("invalid_requirement", "ledger state document is malformed")
        return LedgerState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    # -- writing -----------------------------------------------------------

    def record_requirements(
        self, entries: Sequence[Mapping[str, JSONValue]], *, op_id: str
    ) -> LedgerState:
        """Append/replace ledger entries by id; advances one generation.

        Recording is an upsert keyed on entry id: first-seen ids append in the
        given order, a repeated id replaces its entry in place — except for the
        clarification record, which :func:`_merge` carries across, so re-recording
        an entry cannot erase (or forge) the fact that a user was asked. Either the
        whole batch validates and lands, or nothing does.
        """
        if not entries:
            raise CadOpError("invalid_requirement", "record_requirements needs at least one entry")
        for item in entries:
            _reject_runtime_fields(
                f"requirement {item.get('id', '?')!r}",
                (key for key, value in item.items() if value is not None),
            )
        parsed = [RequirementEntry.from_json(item) for item in entries]
        seen: set[str] = set()
        for entry in parsed:
            if entry.id in seen:
                raise CadOpError(
                    "invalid_requirement", f"requirement {entry.id} appears twice in one batch"
                )
            seen.add(entry.id)
        return self._mutate(
            {"kind": "record_requirements", "entries": [e.to_json() for e in parsed]},
            lambda current: _merge(current, parsed),
            op_id=op_id,
        )

    def update_requirement(
        self,
        requirement_id: str,
        fields: Mapping[str, JSONValue],
        *,
        op_id: str,
        provenance: str = "model",
    ) -> LedgerState:
        """Patch one existing entry (only the supplied fields); one generation.

        ``provenance`` defaults to the untrusted caller: a model-facing patch of
        :data:`RUNTIME_ONLY_FIELDS` is refused rather than silently dropped, so a
        run cannot resolve its own clarification. Only
        :func:`.._gate.record_clarification_answer` passes ``"runtime"``.
        """
        known = {
            "text",
            "source",
            "quote",
            "from",
            "rationale",
            "material",
            "value",
            "unit",
            "applies_to",
            *RUNTIME_ONLY_FIELDS,
        }
        patch = {key: value for key, value in fields.items() if key in known and value is not None}
        if provenance != _RUNTIME:
            _reject_runtime_fields(f"requirement {requirement_id!r}", patch)
        payload: JSONValue = {
            "kind": "update_requirement",
            "id": requirement_id,
            "fields": cast("JSONValue", dict(sorted(patch.items()))),
        }

        def apply(current: LedgerState) -> tuple[RequirementEntry, ...]:
            existing = current.by_id.get(requirement_id)
            if existing is None:
                raise CadOpError(
                    "unknown_requirement",
                    f"no requirement {requirement_id!r} in the ledger "
                    f"(known: {sorted(current.by_id)})",
                )
            merged = dict(existing.to_json())
            merged.update(patch)
            updated = RequirementEntry.from_json(merged)
            return tuple(updated if e.id == requirement_id else e for e in current.entries)

        return self._mutate(payload, apply, op_id=op_id)

    # -- the one generation-advancing path ---------------------------------

    def _mutate(
        self,
        payload: JSONValue,
        apply: Callable[[LedgerState], tuple[RequirementEntry, ...]],
        *,
        op_id: str,
    ) -> LedgerState:
        """Validate, publish one new immutable generation, idempotent on ``op_id``.

        The idempotency payload is the *request*, so a lost-response retry
        replays the generation its own committed write produced — recorded by
        blob, and readable forever because generations are immutable.
        """
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            return self._replayed(outcome.response)
        if not isinstance(outcome, Fresh):
            raise CadOpError(
                "conflict", f"requirement write {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        locks = LockManager(self._store)
        try:
            with locks.holding(PROJECT_CONFIG_LOCK):
                current = self.ledger_state()
                validated = _validate_all(apply(current))
                candidate = LedgerState(
                    generation=current.generation + 1,
                    entries=validated,
                    blob=None,
                    parent=current.blob,
                )
                new_blob = self._store.blobs.put(
                    canonical_json(candidate.document()).encode("utf-8")
                )
                published = replace(candidate, blob=new_blob)
                self._store.wal.publish(
                    outcome,
                    REQUIREMENTS_POINTER,
                    current.blob,
                    new_blob,
                    intended_outcome=canonical_json(
                        {"generation": published.generation, "state": new_blob}
                    ),
                )
                return published
        except CadOpError:
            # Nothing was written: release the fresh opkey skeleton so a corrected
            # retry with the same invocation id is not a payload mismatch.
            self._store.wal.recover(outcome.op_key)
            raise

    def _replayed(self, response: str | None) -> LedgerState:
        """The generation a committed same-id call produced (immutable, so exact)."""
        blob = recorded_ref(response, "state", "")
        if blob and self._store.blobs.has(blob):
            return self._state_from_blob(blob)
        # Tombstoned replay: only the terminal state survives, so report live.
        return self.ledger_state()


def _merge(
    current: LedgerState, incoming: Sequence[RequirementEntry]
) -> tuple[RequirementEntry, ...]:
    """Upsert ``incoming`` into ``current`` by id, preserving first-seen order.

    A replacement inherits the replaced entry's clarification record: ``asked`` and
    ``resolution`` are the runtime's to write, so re-recording an entry may neither
    forge one (the caller cannot supply them) nor erase one.
    """
    by_id = {entry.id: entry for entry in incoming}
    existing = {entry.id for entry in current.entries}
    merged = [
        replace(by_id[entry.id], asked=entry.asked, resolution=entry.resolution)
        if entry.id in by_id
        else entry
        for entry in current.entries
    ]
    merged.extend(entry for entry in incoming if entry.id not in existing)
    return tuple(merged)


def _validate_all(entries: Sequence[RequirementEntry]) -> tuple[RequirementEntry, ...]:
    """Per-entry obligations plus cross-entry ``derived``-from resolution."""
    known = {entry.id for entry in entries}
    for entry in entries:
        entry.validated()
        missing = [ref for ref in entry.from_ids if ref not in known]
        if missing:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry.id}: 'from' names unknown entries {missing}",
            )
        if entry.id in entry.from_ids:
            raise CadOpError(
                "invalid_requirement", f"requirement {entry.id}: 'from' may not name itself"
            )
    return tuple(entries)


def ledger_state(project: RequirementOps) -> LedgerState:
    """The typed reader every later rung uses (§3/§5/§8 all read this).

    ``project`` is the :class:`~hephaestus.agent_bridge.cad_ops.CadOps` bound to
    the project; the returned state carries the entries and the
    ``unresolved_material`` id set the clarification gate keys on.
    """
    return project.ledger_state()


def entry_views(entries: Iterable[RequirementEntry]) -> list[dict[str, JSONValue]]:
    """Ledger entries as plain JSON objects (the shape ``heph lint`` consumes)."""
    return [entry.to_json() for entry in entries]
