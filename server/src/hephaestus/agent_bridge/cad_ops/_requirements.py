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

from hephaestus.contract.tools_decl import REQUIREMENT_ID_PATTERN, REQUIREMENT_SOURCES
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager
from hephaestus.core.project_store.references import ReferenceRegistry
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.project_store.store import (
    blob_hash_of_ref,
)
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
    "RequirementCite",
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


def _cite_text(entry_id: str, data: Mapping[str, JSONValue], key: str) -> str | None:
    """One optional ``cite`` string field, refusing a non-string outright."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CadOpError(
            "invalid_requirement",
            f"requirement {entry_id}: cite.{key} must be a non-empty string",
        )
    return value


def _text(raw: JSONValue | None) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise CadOpError("invalid_requirement", f"expected a string, got {type(raw).__name__}")
    return raw


@dataclass(frozen=True)
class RequirementCite:
    """A citation of an operator-supplied reference (``INGEST.md`` §2).

    The alternative to a prompt ``quote`` for a ``specified`` entry: the spec was
    not in the request, it was on the drawing. ``page`` is 1-based and documents
    only. A *document* citation is machine-verifiable — ``heph lint`` checks the
    quote against the reference's extracted text — while an *image* citation
    (a callout on a scanned drawing) is lint-unverifiable by construction and is
    routed to the §5 termination reviewer's vision channel instead.

    ``PARTS_STORE.md`` §7.4 adds two optional fields naming *what the quote
    transcribes*: ``component`` (a store component the project's registries
    carry) and ``claim`` (an id in that component's ``claims``). They are what
    makes the store⇄project provenance join **operator-declared** rather than
    inferred. An earlier draft proposed selecting the candidate reference *by*
    ``sha256`` equality with the component's datasheet and reporting a mismatch
    if the digests differed — a set defined by equality contains no unequal
    member, so that rule could never fire. With the join declared, the digest
    comparison is decidable in both directions, and both directions are gated
    (G11C clauses 6 and 7).

    Both fields are present or both absent: half a join names nothing, and
    ``incomplete_component_cite`` says which half is missing rather than
    silently ignoring the one that was supplied.
    """

    reference: str
    quote: str
    page: int | None = None
    #: §7.4: the component id whose claim this quote transcribes.
    component: str | None = None
    #: §7.4: the ``claims[].id`` within that component.
    claim: str | None = None

    @property
    def names_component_claim(self) -> bool:
        """True when this citation declares the §7.4 join (both halves present)."""
        return bool(self.component) and bool(self.claim)

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "reference": self.reference,
            "page": self.page,
            "quote": self.quote,
        }
        # Emitted only when declared: a stored entry from before §7.4 must round
        # -trip byte-identically, and `lint_requirements` reads these documents.
        if self.component is not None:
            out["component"] = self.component
        if self.claim is not None:
            out["claim"] = self.claim
        return out

    @classmethod
    def from_json(cls, entry_id: str, data: Mapping[str, JSONValue]) -> RequirementCite:
        reference = data.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry_id}: cite.reference must name a registered reference",
            )
        quote = data.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry_id}: cite.quote is required — cite what the reference says",
            )
        page = data.get("page")
        if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry_id}: cite.page must be a 1-based page number",
            )
        component = _cite_text(entry_id, data, "component")
        claim = _cite_text(entry_id, data, "claim")
        if (component is None) != (claim is None):
            # §7.4: "Both fields are present or both absent". Half a join names
            # nothing — a component with no claim id does not say which number
            # was transcribed, and a claim id with no component does not say
            # whose. Naming the missing half is the whole content of the refusal.
            missing = "claim" if claim is None else "component"
            supplied = "component" if claim is None else "claim"
            raise CadOpError(
                "incomplete_component_cite",
                f"requirement {entry_id}: cite carries {supplied!r} but not {missing!r}; a "
                "component-claim citation names both or neither (PARTS_STORE.md §7.4), and "
                "nothing was written",
            )
        return cls(
            reference=reference,
            quote=quote,
            page=None if page is None else int(page),
            component=component,
            claim=claim,
        )


@dataclass(frozen=True)
class RequirementEntry:
    """One ledger entry, exactly the shape ``VALIDATION.md`` §2 fixes."""

    id: str
    text: str
    source: str
    quote: str | None = None
    #: ``INGEST.md`` §2: a reference citation standing in for the prompt quote.
    cite: RequirementCite | None = None
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
            "cite": None if self.cite is None else self.cite.to_json(),
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
        raw_cite = data.get("cite")
        cite: RequirementCite | None = None
        if isinstance(raw_cite, dict):
            cite = RequirementCite.from_json(raw_id, cast("Mapping[str, JSONValue]", raw_cite))
        elif raw_cite is not None:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {raw_id}: cite must be {{reference, page?, quote}} (INGEST.md §2)",
            )
        return cls(
            id=raw_id,
            text=text,
            source=source,
            quote=_text(data.get("quote")),
            cite=cite,
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
        if self.source == "specified" and not (self.quote or "").strip() and self.cite is None:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {self.id}: source='specified' requires a quote from the request "
                "or a cite={reference, page?, quote} of a registered reference (INGEST.md §2)",
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
            "cite",
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
                validated = _validate_all(apply(current), cite_check=self._cite_checks)
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

    def _cite_checks(self, entry: RequirementEntry) -> None:
        """Both citation checks, in the order their subjects resolve.

        The reference first (``INGEST.md`` §2), then the component claim
        (``PARTS_STORE.md`` §7.4): a cite whose reference does not resolve has
        nothing for the component half to be a citation *of*, and reporting the
        component before the reference would name the second problem first.
        """
        self._check_cite(entry)
        self._check_component_cite(entry)

    def _check_cite(self, entry: RequirementEntry) -> None:
        """``INGEST.md`` §2: a citation must name a *registered* reference.

        Checked structurally for the same reason ``quote`` is: a citation of a
        reference the project does not carry is not a weaker specification, it is
        a fabricated one, and nothing downstream could tell the difference later.
        """
        cite = entry.cite
        if cite is None:
            return
        registry = ReferenceRegistry(self.layout, self._store)
        try:
            reference = registry.get(cite.reference)
        except AddressingError as exc:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry.id}: cite names reference {cite.reference!r}, which is not "
                f"registered ({', '.join(exc.candidates) or 'none registered'}) — "
                "list_references() shows what this project carries",
            ) from exc
        if cite.page is None:
            return
        if reference.kind != "document":
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry.id}: cite.page is for documents; "
                f"{cite.reference!r} is an image",
            )
        if reference.pages is not None and cite.page > reference.pages:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry.id}: cite.page {cite.page} is past the end of "
                f"{cite.reference!r} ({reference.pages} page(s))",
            )

    def _check_component_cite(self, entry: RequirementEntry) -> None:
        """``PARTS_STORE.md`` §7.4: the named component and claim must both exist.

        Checked on the *existing* refusal path, for the reason ``INGEST.md`` §2's
        reference check is: a citation of a component the project's registries do
        not carry, or of a claim that component does not declare, is not a weaker
        provenance record — it is a fabricated one, and every reader downstream
        (``datasheet_digest_mismatch`` included) would then be joining on a name
        that resolves to nothing. ``invalid_requirement``, nothing written.

        A citation carrying neither field never reaches here, so an entry written
        before §7.4 is accepted and checked exactly as it was.
        """
        cite = entry.cite
        if cite is None or not cite.names_component_claim:
            return
        # Imported here: the ledger is written far more often than it is written
        # with a component citation, and opening the registry set verifies every
        # pinned tree's Merkle root.
        from hephaestus.core.registry import RegistryError, RegistrySet

        registries = RegistrySet.open(self.layout.root)
        try:
            part = registries.parts.get(str(cite.component))
        except RegistryError as exc:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry.id}: cite names component {cite.component!r}, which "
                f"this project's pinned registries do not carry ({exc.reason}: {exc}) — "
                "nothing was written",
            ) from exc
        component = part.component
        declared = () if component is None else tuple(claim.id for claim in component.claims)
        if str(cite.claim) not in declared:
            raise CadOpError(
                "invalid_requirement",
                f"requirement {entry.id}: component {cite.component!r} declares no claim "
                f"{cite.claim!r} (declared: {', '.join(declared) or 'none'}) — a ledger "
                "citation resolves to exactly one claim or it is not a citation; nothing "
                "was written",
            )

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


def _validate_all(
    entries: Sequence[RequirementEntry],
    *,
    cite_check: Callable[[RequirementEntry], None] | None = None,
) -> tuple[RequirementEntry, ...]:
    """Per-entry obligations plus cross-entry ``derived``-from resolution.

    ``cite_check`` resolves an ``INGEST.md`` §2 citation against the project's
    reference registry; it is injected so this function stays a pure validator.
    """
    known = {entry.id for entry in entries}
    for entry in entries:
        entry.validated()
        if cite_check is not None:
            cite_check(entry)
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
