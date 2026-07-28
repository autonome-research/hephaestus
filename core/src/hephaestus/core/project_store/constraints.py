"""The constraint set: cross-part mates as generational project state.

``ASSEMBLY.md`` §1. A constraint spans parts, so it cannot live in any one part
script — the project carries it. Storage is the requirement ledger's pattern,
copied rather than reinvented: every generation is an immutable
content-addressed document (``artifact:constraints:sha256:…``) naming its
parent, published by a compare-and-swap of the ``constraints-state`` pointer
under the **project-config lock**. Older generations stay readable forever,
which is what makes "declare → update → withdraw" replayable and what makes a
withdrawal a new generation rather than an erasure.

Each entry is exactly the ``ASSEMBLY.md`` §1 shape::

    {"id": "c-lid-fit", "kind": "clearance_min",
     "a": "lid:register_wall", "b": "base:register_slot",
     "value_mm": 0.15, "tol_mm": 0.05,
     "provenance": {"requirement": "r-7"}, "note": "slip fit per datasheet"}

Declared parameters sit at the top level, as written above, and are validated
against :data:`hephaestus.geom.constraints.REQUIRED_PARAMS` /
``OPTIONAL_PARAMS`` — the same tables the evaluator dispatches on, so the entry
schema cannot drift from what geometry will actually be asked. (The geom module
is imported lazily: it pulls in the kernel bindings, and declaring a constraint
must not cost a build123d import.)

**Provenance is compulsory** (``ASSEMBLY.md`` §1): an entry cites a requirement
id, or is ``assumed`` with a reason. A constraint IS an interpretation of
intent, so it carries the ``VALIDATION.md`` §2 honesty taxonomy; an entry with
neither is refused ``invalid_constraint`` and nothing is written.

What lives elsewhere: *evaluating* a constraint is
:mod:`hephaestus.core.assembly` (anchors resolved against current build
artifacts, residuals from :mod:`hephaestus.geom.constraints`), and what to DO
about an unsatisfied one is the ``VALIDATION.md`` §5 reviewer's rule. This
module only knows what was declared, by whom, and why.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Final, Literal, cast

from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import (
    Fresh,
    OpStore,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_canonical_json,
)

__all__ = [
    "ANCHOR_PATTERN",
    "ANCHOR_SEPARATOR",
    "CONSTRAINTS_POINTER",
    "CONSTRAINT_ARTIFACT_KIND",
    "CONSTRAINT_ID_PATTERN",
    "CONSTRAINT_REF_PREFIX",
    "ENTRY_FIELDS",
    "WHOLE_PART_SELECTOR",
    "Anchor",
    "ConstraintChange",
    "ConstraintEntry",
    "ConstraintError",
    "ConstraintProvenance",
    "ConstraintSet",
    "ConstraintState",
    "constraint_kinds",
    "declared_parameters",
    "entry_views",
    "parse_anchor",
]

#: CAS pointer naming the current constraint-set generation's state blob.
CONSTRAINTS_POINTER: Final[str] = "constraints-state"
#: Artifact kind of an immutable constraint-set generation document.
CONSTRAINT_ARTIFACT_KIND: Final[str] = "constraints"
CONSTRAINT_REF_PREFIX: Final[str] = f"artifact:{CONSTRAINT_ARTIFACT_KIND}:"

#: Constraint ids are stable handles a requirement, a tool call and a reviewer
#: finding all name, so they are plain and pattern-checked like requirement ids.
CONSTRAINT_ID_PATTERN: Final[str] = r"^[A-Za-z][A-Za-z0-9._-]{0,63}$"
_ID_RE: Final[re.Pattern[str]] = re.compile(CONSTRAINT_ID_PATTERN)

#: An anchor is ``part[:selector]`` (``ASSEMBLY.md`` §1). The separator is a
#: colon and not a slash on purpose: ``"<part>/<selector>"`` is the §7
#: *cross-part selector* form, and an anchor already knows which part it means,
#: so reusing that spelling would invite two grammars for one string.
ANCHOR_SEPARATOR: Final[str] = ":"
#: The selector a bare ``part`` anchor means: the whole compound (§7 rule 1).
WHOLE_PART_SELECTOR: Final[str] = "part"
ANCHOR_PATTERN: Final[str] = r"^[A-Za-z_][A-Za-z0-9_]*(:[^\s:]+)?$"
_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(ANCHOR_PATTERN)

#: Structural keys of an entry. Every OTHER key must be a declared parameter of
#: the entry's kind — that is what keeps the wire shape of ``ASSEMBLY.md`` §1
#: (``value_mm`` next to ``id``) from needing a second, restated schema.
ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    {"id", "kind", "a", "b", "provenance", "note", "withdrawn", "withdrawn_reason"}
)

ConstraintRefusal = Literal["invalid_constraint", "unknown_constraint"]
ChangeKind = Literal["declare", "update", "withdraw"]


class ConstraintError(ValidationError):
    """A constraint write was refused; ``reason`` is the stable machine token.

    ``invalid_constraint`` covers every malformed or dishonest entry (unknown
    kind, missing declared parameter, malformed anchor, absent provenance);
    ``unknown_constraint`` is a patch or withdrawal naming an id the set does
    not carry. Nothing is ever written on either.
    """

    def __init__(self, message: str, *, reason: ConstraintRefusal = "invalid_constraint") -> None:
        super().__init__(message, kind="contract")
        self.reason: ConstraintRefusal = reason


# --------------------------------------------------------------------------
# the kind vocabulary, borrowed from geom rather than restated


@lru_cache(maxsize=1)
def _kind_tables() -> tuple[
    tuple[str, ...], Mapping[str, tuple[str, ...]], Mapping[str, tuple[str, ...]]
]:
    """``(kinds, required, optional)`` from :mod:`hephaestus.geom.constraints`.

    Imported lazily and cached: the geometry package binds the OCP/build123d
    kernel at import time, and neither declaring a constraint nor reading the
    set should pay for that. The tables are the evaluator's own, so a kind this
    module accepts is by construction a kind geometry can answer.
    """
    import importlib

    module = importlib.import_module("hephaestus.geom.constraints")
    kinds = cast("tuple[str, ...]", tuple(module.CONSTRAINT_KINDS))
    required = cast("Mapping[str, tuple[str, ...]]", module.REQUIRED_PARAMS)
    optional = cast("Mapping[str, tuple[str, ...]]", module.OPTIONAL_PARAMS)
    return kinds, required, optional


def constraint_kinds() -> tuple[str, ...]:
    """The 8C kind vocabulary (``ASSEMBLY.md`` §1), in declaration order."""
    return _kind_tables()[0]


def declared_parameters(kind: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(required, optional)`` declared-parameter names for one kind."""
    kinds, required, optional = _kind_tables()
    if kind not in kinds:
        raise ConstraintError(f"unknown constraint kind {kind!r}; known: {', '.join(kinds)}")
    return tuple(required[kind]), tuple(optional[kind])


# --------------------------------------------------------------------------
# anchors


@dataclass(frozen=True)
class Anchor:
    """One parsed ``part[:selector]`` anchor (``ASSEMBLY.md`` §1)."""

    text: str
    part: str
    selector: str

    @property
    def whole_part(self) -> bool:
        return self.selector == WHOLE_PART_SELECTOR


def parse_anchor(text: str, *, field: str = "a") -> Anchor:
    """Parse ``part[:selector]``; a bare part anchors the whole compound.

    Structural only. Whether the part exists, has a current build, or carries
    that selector is an *evaluation* question with its own named unresolvable
    state (:mod:`hephaestus.core.assembly`) — refusing a declaration because a
    part has not been built yet would make the constraint set unusable exactly
    when it is most useful, before the geometry exists.
    """
    if not isinstance(text, str) or not _ANCHOR_RE.match(text):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ConstraintError(
            f"anchor {field}={text!r} must be 'part' or 'part{ANCHOR_SEPARATOR}selector' "
            f"(matching {ANCHOR_PATTERN})"
        )
    part, separator, selector = text.partition(ANCHOR_SEPARATOR)
    return Anchor(text=text, part=part, selector=selector if separator else WHOLE_PART_SELECTOR)


# --------------------------------------------------------------------------
# entries


@dataclass(frozen=True)
class ConstraintProvenance:
    """Why this constraint is claimed to hold — a requirement, or an assumption.

    The ``VALIDATION.md`` §2 taxonomy applied to a mate: either it traces to a
    ledger requirement id, or the model supplied it and must say why. There is
    no third state, and the absence of both is a refusal rather than a default.
    """

    requirement: str | None = None
    assumed: bool = False
    reason: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {}
        if self.requirement is not None:
            out["requirement"] = self.requirement
        if self.assumed:
            out["assumed"] = True
        if self.reason is not None:
            out["reason"] = self.reason
        return out

    @classmethod
    def from_json(cls, entry_id: str, data: JSONValue | None) -> ConstraintProvenance:
        if not isinstance(data, dict):
            raise ConstraintError(
                f"constraint {entry_id}: provenance is required — cite a requirement "
                '({"requirement": "r-7"}) or declare an assumption '
                '({"assumed": true, "reason": "…"}) (ASSEMBLY.md §1)'
            )
        raw = cast("Mapping[str, JSONValue]", data)
        unknown = sorted(set(raw) - {"requirement", "assumed", "reason"})
        if unknown:
            raise ConstraintError(
                f"constraint {entry_id}: unknown provenance field(s) {', '.join(unknown)}"
            )
        requirement = raw.get("requirement")
        assumed = raw.get("assumed", False)
        reason = raw.get("reason")
        malformed = not isinstance(requirement, str) or not requirement.strip()
        if requirement is not None and malformed:
            raise ConstraintError(
                f"constraint {entry_id}: provenance.requirement must be a requirement id"
            )
        if not isinstance(assumed, bool):
            raise ConstraintError(f"constraint {entry_id}: provenance.assumed must be a boolean")
        if reason is not None and not isinstance(reason, str):
            raise ConstraintError(f"constraint {entry_id}: provenance.reason must be a string")
        provenance = cls(
            requirement=requirement if isinstance(requirement, str) else None,
            assumed=assumed,
            reason=reason if isinstance(reason, str) and reason.strip() else None,
        )
        return provenance.validated(entry_id)

    def validated(self, entry_id: str) -> ConstraintProvenance:
        """Enforce the §1 compulsion (raises ``invalid_constraint``, never repairs)."""
        if self.requirement is not None and self.assumed:
            raise ConstraintError(
                f"constraint {entry_id}: provenance is either a cited requirement or an "
                "assumption, not both — an assumed mate that a requirement already "
                "demands is not an assumption"
            )
        if self.requirement is None and not self.assumed:
            raise ConstraintError(
                f"constraint {entry_id}: provenance must cite a requirement id or set "
                '"assumed": true with a reason (ASSEMBLY.md §1) — a constraint is an '
                "interpretation of intent, so it says whose"
            )
        if self.assumed and self.reason is None:
            raise ConstraintError(
                f"constraint {entry_id}: an assumed constraint requires a reason "
                "(why is this mate believed to be intended?)"
            )
        return self


@dataclass(frozen=True)
class ConstraintEntry:
    """One declared constraint, exactly the ``ASSEMBLY.md`` §1 entry shape."""

    id: str
    kind: str
    a: str
    b: str
    #: Declared numbers, name-sorted; the kind's required parameters plus any
    #: optional ones actually supplied. Passed straight to
    #: ``geom.evaluate_residual`` as its ``declared`` mapping.
    values: Mapping[str, float]
    provenance: ConstraintProvenance
    note: str | None = None
    #: A withdrawn entry stays in every later generation, carrying the reason it
    #: was withdrawn: ``ASSEMBLY.md`` §3 makes withdrawal a new generation, never
    #: an erasure, so what a project *stopped* claiming stays inspectable.
    withdrawn: bool = False
    withdrawn_reason: str | None = None

    @property
    def anchors(self) -> tuple[Anchor, Anchor]:
        return (parse_anchor(self.a, field="a"), parse_anchor(self.b, field="b"))

    @property
    def parts(self) -> tuple[str, ...]:
        """The part names this constraint anchors, deduplicated in a/b order."""
        names = [anchor.part for anchor in self.anchors]
        return tuple(dict.fromkeys(names))

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {"id": self.id, "kind": self.kind, "a": self.a, "b": self.b}
        for name in sorted(self.values):
            out[name] = self.values[name]
        out["provenance"] = cast("JSONValue", self.provenance.to_json())
        if self.note is not None:
            out["note"] = self.note
        if self.withdrawn:
            out["withdrawn"] = True
            out["withdrawn_reason"] = self.withdrawn_reason
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> ConstraintEntry:
        """Build a validated entry from tool arguments or a stored generation."""
        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not _ID_RE.match(raw_id):
            raise ConstraintError(f"constraint id {raw_id!r} must match {CONSTRAINT_ID_PATTERN}")
        kind = data.get("kind")
        kinds = constraint_kinds()
        if not isinstance(kind, str) or kind not in kinds:
            raise ConstraintError(
                f"constraint {raw_id}: kind must be one of {', '.join(kinds)}, got {kind!r}"
            )
        a = data.get("a")
        b = data.get("b")
        if not isinstance(a, str) or not isinstance(b, str):
            raise ConstraintError(
                f"constraint {raw_id}: anchors 'a' and 'b' are required (part[:selector])"
            )
        parse_anchor(a, field="a")
        parse_anchor(b, field="b")
        values = _declared_values(raw_id, kind, data)
        note = data.get("note")
        if note is not None and not isinstance(note, str):
            raise ConstraintError(f"constraint {raw_id}: note must be a string")
        withdrawn = data.get("withdrawn", False)
        if not isinstance(withdrawn, bool):
            raise ConstraintError(f"constraint {raw_id}: withdrawn must be a boolean")
        withdrawn_reason = data.get("withdrawn_reason")
        if withdrawn_reason is not None and not isinstance(withdrawn_reason, str):
            raise ConstraintError(f"constraint {raw_id}: withdrawn_reason must be a string")
        if withdrawn and not (withdrawn_reason or "").strip():
            raise ConstraintError(f"constraint {raw_id}: a withdrawal must record a reason")
        return cls(
            id=raw_id,
            kind=kind,
            a=a,
            b=b,
            values=values,
            provenance=ConstraintProvenance.from_json(raw_id, data.get("provenance")),
            note=note,
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason if withdrawn else None,
        )


def _declared_values(entry_id: str, kind: str, data: Mapping[str, JSONValue]) -> dict[str, float]:
    """The kind's declared numbers, refusing missing and unknown ones by name."""
    required, optional = declared_parameters(kind)
    allowed = set(required) | set(optional)
    supplied = {name: value for name, value in data.items() if name not in ENTRY_FIELDS}
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        known = ", ".join(sorted(allowed)) or "(none)"
        raise ConstraintError(
            f"constraint {entry_id}: kind {kind!r} does not take {', '.join(unknown)} "
            f"(it takes: {known})"
        )
    missing = [name for name in required if name not in supplied]
    if missing:
        raise ConstraintError(f"constraint {entry_id}: kind {kind!r} requires {', '.join(missing)}")
    values: dict[str, float] = {}
    for name in sorted(supplied):
        value = supplied[name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConstraintError(f"constraint {entry_id}: {name} must be a number")
        values[name] = float(value)
    return values


# --------------------------------------------------------------------------
# generations


@dataclass(frozen=True)
class ConstraintChange:
    """What produced one generation: the act, the entry, and the stated reason.

    Recorded on the generation rather than only on the entry so a replay of the
    history answers "why did this change?" for revisions as well as
    withdrawals — a revised tolerance with no reason is exactly the silent edit
    ``ASSEMBLY.md`` §3 forbids.
    """

    kind: ChangeKind
    id: str
    reason: str | None = None
    patch: Mapping[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {"kind": self.kind, "id": self.id}
        if self.reason is not None:
            out["reason"] = self.reason
        if self.patch is not None:
            out["patch"] = cast("JSONValue", dict(self.patch))
        return out

    @classmethod
    def from_json(cls, data: JSONValue | None) -> ConstraintChange | None:
        if not isinstance(data, dict):
            return None
        raw = cast("Mapping[str, JSONValue]", data)
        kind = raw.get("kind")
        entry_id = raw.get("id")
        if kind not in ("declare", "update", "withdraw") or not isinstance(entry_id, str):
            return None
        reason = raw.get("reason")
        patch = raw.get("patch")
        return cls(
            kind=kind,
            id=entry_id,
            reason=reason if isinstance(reason, str) else None,
            patch=cast("Mapping[str, JSONValue]", patch) if isinstance(patch, dict) else None,
        )


@dataclass(frozen=True)
class ConstraintState:
    """One immutable constraint-set generation."""

    generation: int
    entries: tuple[ConstraintEntry, ...]
    blob: str | None
    parent: str | None = None
    change: ConstraintChange | None = None

    @property
    def artifact_ref(self) -> str | None:
        """``artifact:constraints:sha256:…`` of this generation (None when empty)."""
        if self.blob is None:
            return None
        return make_artifact_ref(CONSTRAINT_ARTIFACT_KIND, self.blob)

    @property
    def by_id(self) -> dict[str, ConstraintEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def active(self) -> tuple[ConstraintEntry, ...]:
        """Entries still claimed (withdrawn ones stay stored, never evaluated)."""
        return tuple(entry for entry in self.entries if not entry.withdrawn)

    @property
    def parts(self) -> tuple[str, ...]:
        """Every part an active constraint anchors, lexically sorted."""
        names: set[str] = set()
        for entry in self.active:
            names.update(entry.parts)
        return tuple(sorted(names))

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "change": None if self.change is None else self.change.to_json(),
            "entries": [entry.to_json() for entry in self.entries],
        }

    def to_json(self) -> dict[str, JSONValue]:
        """The projection every constraint reader shares."""
        return {
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "change": None if self.change is None else cast("JSONValue", self.change.to_json()),
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> ConstraintState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ConstraintError("constraint-set generation must be an integer")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise ConstraintError("constraint-set entries must be an array")
        entries = tuple(
            ConstraintEntry.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_entries)
            if isinstance(item, dict)
        )
        parent = data.get("parent")
        return cls(
            generation=generation,
            entries=entries,
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
            change=ConstraintChange.from_json(data.get("change")),
        )


#: The empty set every project starts from (generation 0, no blob).
_EMPTY: Final[ConstraintState] = ConstraintState(
    generation=0, entries=(), blob=None, parent=None, change=None
)


class ConstraintSet:
    """Declare / update / withdraw constraints as immutable generations.

    Engine-side and model-writable (``ASSEMBLY.md`` §3): unlike the reference
    registry, declaring a constraint is cheap and reversible, so the tool
    surface writes here directly. What it cannot do is erase — every act is a
    new generation naming its parent and its reason.
    """

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store

    # -- reads --------------------------------------------------------------

    def state(self) -> ConstraintState:
        """The current generation (empty generation 0 when never written)."""
        blob = self._store.blobs.read_pointer(CONSTRAINTS_POINTER)
        if blob is None:
            return _EMPTY
        return self._state_from_blob(blob)

    def generation(self, artifact_ref: str) -> ConstraintState:
        """Any historical generation by its immutable artifact ref."""
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise ConstraintError(f"constraint generation {artifact_ref} is not stored")
        return self._state_from_blob(blob)

    def history(self) -> tuple[ConstraintState, ...]:
        """Every stored generation, oldest first — the replay ``ASSEMBLY.md`` §1 wants.

        Walks the ``parent`` chain from the live pointer. A generation whose
        blob has been collected ends the walk rather than faking a gap.
        """
        chain: list[ConstraintState] = []
        current = self.state()
        while current.blob is not None:
            chain.append(current)
            parent = current.parent
            if parent is None or not self._store.blobs.has(parent):
                break
            current = self._state_from_blob(parent)
        return tuple(reversed(chain))

    def get(self, constraint_id: str) -> ConstraintEntry:
        """One entry, or ``addressing_error`` naming the ids that do exist."""
        entries = self.state().by_id
        entry = entries.get(constraint_id)
        if entry is None:
            raise AddressingError(
                f"no constraint {constraint_id!r} is declared",
                selector=constraint_id,
                candidates=tuple(sorted(entries)),
            )
        return entry

    def _state_from_blob(self, blob: str) -> ConstraintState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise ConstraintError("constraint-set state document is malformed")
        return ConstraintState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    # -- writes -------------------------------------------------------------

    def declare(
        self, entry: Mapping[str, JSONValue], *, op_id: str | None = None
    ) -> ConstraintState:
        """Declare one new constraint; advances one generation.

        A repeated id is refused rather than silently replaced: revising a
        claim is :meth:`update`, which records why.
        """
        parsed = ConstraintEntry.from_json(entry)

        def apply(current: ConstraintState) -> tuple[ConstraintEntry, ...]:
            if parsed.id in current.by_id:
                raise ConstraintError(
                    f"constraint {parsed.id} is already declared — revise it with "
                    "update_constraint(id, patch, reason) so the change records a reason"
                )
            return (*current.entries, parsed)

        return self._mutate(
            ConstraintChange(kind="declare", id=parsed.id, patch=parsed.to_json()),
            apply,
            op_id=op_id,
        )

    def update(
        self,
        constraint_id: str,
        patch: Mapping[str, JSONValue],
        reason: str,
        *,
        op_id: str | None = None,
    ) -> ConstraintState:
        """Revise one entry's declared fields; advances one generation.

        ``reason`` is compulsory and recorded on the generation. The patch is
        merged onto the stored entry and the whole result revalidated, so a
        patch cannot produce an entry that could not have been declared.
        """
        if not reason.strip():
            raise ConstraintError(f"constraint {constraint_id}: update requires a reason")
        cleaned = {name: value for name, value in patch.items() if value is not None}
        if not cleaned:
            raise ConstraintError(f"constraint {constraint_id}: update patches nothing")
        if "id" in cleaned:
            raise ConstraintError(
                f"constraint {constraint_id}: id is not patchable — declare a new "
                "constraint and withdraw this one"
            )

        def apply(current: ConstraintState) -> tuple[ConstraintEntry, ...]:
            existing = _require(current, constraint_id)
            merged = dict(existing.to_json())
            if "kind" in cleaned and cleaned["kind"] != existing.kind:
                # A new kind takes a different parameter set; keeping the old
                # kind's numbers would silently smuggle them past validation.
                for name in existing.values:
                    merged.pop(name, None)
            merged.update(cleaned)
            updated = ConstraintEntry.from_json(merged)
            return tuple(updated if e.id == constraint_id else e for e in current.entries)

        return self._mutate(
            ConstraintChange(
                kind="update",
                id=constraint_id,
                reason=reason,
                patch=cast("Mapping[str, JSONValue]", dict(sorted(cleaned.items()))),
            ),
            apply,
            op_id=op_id,
        )

    def withdraw(
        self, constraint_id: str, reason: str, *, op_id: str | None = None
    ) -> ConstraintState:
        """Stop claiming one constraint; advances one generation, erases nothing."""
        if not reason.strip():
            raise ConstraintError(f"constraint {constraint_id}: withdrawal requires a reason")

        def apply(current: ConstraintState) -> tuple[ConstraintEntry, ...]:
            existing = _require(current, constraint_id)
            if existing.withdrawn:
                raise ConstraintError(f"constraint {constraint_id} is already withdrawn")
            updated = replace(existing, withdrawn=True, withdrawn_reason=reason)
            return tuple(updated if e.id == constraint_id else e for e in current.entries)

        return self._mutate(
            ConstraintChange(kind="withdraw", id=constraint_id, reason=reason), apply, op_id=op_id
        )

    # -- the one generation-advancing path ----------------------------------

    def _mutate(
        self,
        change: ConstraintChange,
        apply: Callable[[ConstraintState], tuple[ConstraintEntry, ...]],
        *,
        op_id: str | None,
    ) -> ConstraintState:
        """Publish one new immutable generation under the project-config lock.

        With ``op_id`` the pointer flip goes through the opstore WAL and is
        idempotent on that id (a lost-response retry replays the generation its
        own committed write produced, exactly as the requirement ledger does).
        Without one — the operator/test path, where there is no invocation id to
        be idempotent on — it is a plain pointer compare-and-swap.
        """
        if op_id is None:
            return self._publish(change, apply)
        payload: JSONValue = {"kind": "constraint_write", "change": change.to_json()}
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            return self._replayed(outcome.response)
        if not isinstance(outcome, Fresh):
            raise ConstraintError(
                f"constraint write {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        locks = LockManager(self._store)
        try:
            with locks.holding(PROJECT_CONFIG_LOCK):
                current = self.state()
                candidate, new_blob = self._candidate(current, change, apply)
                self._store.wal.publish(
                    outcome,
                    CONSTRAINTS_POINTER,
                    current.blob,
                    new_blob,
                    intended_outcome=canonical_json(
                        {"generation": candidate.generation, "state": new_blob}
                    ),
                )
                return candidate
        except ConstraintError:
            # Nothing was written: release the fresh opkey skeleton so a
            # corrected retry with the same invocation id is not a mismatch.
            self._store.wal.recover(outcome.op_key)
            raise

    def _publish(
        self,
        change: ConstraintChange,
        apply: Callable[[ConstraintState], tuple[ConstraintEntry, ...]],
    ) -> ConstraintState:
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            candidate, new_blob = self._candidate(current, change, apply)
            self._store.blobs.cas_swap(CONSTRAINTS_POINTER, current.blob, new_blob)
            return candidate

    def _candidate(
        self,
        current: ConstraintState,
        change: ConstraintChange,
        apply: Callable[[ConstraintState], tuple[ConstraintEntry, ...]],
    ) -> tuple[ConstraintState, str]:
        """Compute, store and pin the next generation's document (no pointer move)."""
        entries = apply(current)
        candidate = ConstraintState(
            generation=current.generation + 1,
            entries=entries,
            blob=None,
            parent=current.blob,
            change=change,
        )
        new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
        # Pinned, not merely pointer-protected: an older generation must stay
        # readable after the pointer has moved on, or "nothing is erased" would
        # be true only until the next GC pass.
        self._store.gc.pin(new_blob)
        if current.blob is not None:
            self._store.gc.link(new_blob, current.blob)
        return replace(candidate, blob=new_blob), new_blob

    def _replayed(self, response: str | None) -> ConstraintState:
        """The generation a committed same-id call produced (immutable, so exact)."""
        recorded = _recorded_state(response)
        if recorded is not None and self._store.blobs.has(recorded):
            return self._state_from_blob(recorded)
        # Tombstoned replay: only the terminal state survives, so report live.
        return self.state()


def _recorded_state(response: str | None) -> str | None:
    """The state blob a WAL-recorded ``intended_outcome`` names (used on replay)."""
    if response is None:  # tombstone replay: only the terminal state survives
        return None
    try:
        decoded = cast("Mapping[str, JSONValue]", json.loads(response))
    except (ValueError, TypeError):  # pragma: no cover - responses are our own JSON
        return None
    value = decoded.get("state")
    return value if isinstance(value, str) else None


def _require(current: ConstraintState, constraint_id: str) -> ConstraintEntry:
    existing = current.by_id.get(constraint_id)
    if existing is None:
        raise ConstraintError(
            f"no constraint {constraint_id!r} is declared (known: {sorted(current.by_id)})",
            reason="unknown_constraint",
        )
    return existing


def entry_views(entries: Sequence[ConstraintEntry]) -> list[dict[str, JSONValue]]:
    """Entries as plain JSON objects (the shape tools and the CLI emit)."""
    return [entry.to_json() for entry in entries]
