"""Binding dimension findings: the §4 critique with teeth (``VALIDATION.md`` §4/§6).

§4's ``prompt_number_diff`` already fires, unrequested and by rule, on the exact
failure this stage exists to catch — measured on ``bracket-101`` seed 2, it said
"request says 40 mm on Y but bbox.y measures 46 mm" and "nothing in the built
geometry measures 40 mm on Y". The model read it and shipped anyway, because a
warning is advice. This module is what turns that advice into an obligation: a
``dimension_mismatch`` / ``unmatched_request_number`` raised by a **successful**
build is recorded as an *open finding on the run*, and §6's terminal cannot be
green while one is open.

Three properties make the record evidence rather than a claim:

**It is harness-derived.** Findings are computed from the request text the
runtime bound and the geometry the build actually published. No tool writes them
and no tool deletes them; there is no model-facing surface here at all.

**It is measured against measured dimensions.** The clearing comparison uses the
bbox extents and tagged edge lengths only — never the script's own ``CHECKS``
thresholds. §5 refuses to hand the reviewer the agent's acceptance tests for
exactly this reason, and the same reasoning applies one rung down: a run that
could silence a binding finding by asserting the number in its own ``CHECKS``
would be clearing the finding with the misreading that caused it. The *advisory*
§4 block still matches against thresholds (a threshold really is a dimension the
script claims); only the binding view refuses to.

**It clears in exactly two ways** (:meth:`DimensionFindingOps.record_dimension_findings`
and :func:`.._gate.record_dimension_answer`):

1. a **later successful build** of the same part whose binding diff no longer
   raises it — that is, the geometry changed to match; or
2. an **explicit dismissal by the user** through the ``ask_user`` path, recorded
   by the runtime from a committal answer exactly the way §3 records a
   clarification ``resolution``. A non-committal answer (the bench answerer's
   "unspecified — use your engineering judgment") records ``asked`` and dismisses
   nothing, so the bench cannot answer its way past its own measurement.

Storage mirrors the requirement ledger: an immutable content-addressed state
document per generation (``artifact:dimension-findings:sha256:…``) published by a
pointer CAS, so the archive can show what was open when and how it closed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Final, cast

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
    "BINDING_WARNING_KINDS",
    "DIMENSION_FINDINGS_POINTER",
    "DIMENSION_FINDING_ARTIFACT_KIND",
    "DIMENSION_FINDING_ID_PREFIX",
    "DimensionFinding",
    "DimensionFindingOps",
    "DimensionFindingState",
    "dimension_finding_id",
    "dimension_findings",
    "finding_views",
]

#: CAS pointer naming the current findings generation's state blob.
DIMENSION_FINDINGS_POINTER: Final[str] = "dimension-findings-state"
#: Artifact kind of an immutable findings generation document.
DIMENSION_FINDING_ARTIFACT_KIND: Final[str] = "dimension-findings"

#: The §4 warning kinds that bind, on the **axis-resolved** numbers only (see
#: :func:`_finding_from_warning`). Both are statements about a number in the
#: request that the delivered geometry does not honour; the other §4 kinds
#: (interference, manifold, DFM) have their own rungs and are untouched here.
BINDING_WARNING_KINDS: Final[frozenset[str]] = frozenset(
    {"dimension_mismatch", "unmatched_request_number"}
)

#: Finding ids are ``dim.<10 hex>``: short enough and in the character class of
#: ``REQUIREMENT_ID_PATTERN``, so a finding id can be passed straight to
#: ``ask_user(requirement_ids=[…])`` — the one route by which a user (never the
#: model) can dismiss one.
DIMENSION_FINDING_ID_PREFIX: Final[str] = "dim."

#: Marks the one caller allowed to record a dismissal: a real ``ask_user`` answer.
_RUNTIME: Final[str] = "runtime"

_STATUSES: Final[tuple[str, ...]] = ("open", "cleared", "dismissed")


def dimension_finding_id(part: str, kind: str, axis: str | None, request_value_mm: float) -> str:
    """The stable identity of one unmet request number on one part.

    Deliberately *not* a function of the built value: a rebuild that moves 46 mm
    to 47 mm has not resolved "the request says 40 mm", it has failed the same
    way again — which is what §6's repeat-escalation must see.
    """
    payload = f"{part}|{kind}|{axis or ''}|{request_value_mm:.6f}"
    return DIMENSION_FINDING_ID_PREFIX + sha256(payload.encode("utf-8")).hexdigest()[:10]


@dataclass(frozen=True)
class DimensionFinding:
    """One binding §4 dimension finding, with how it was raised and how it closed."""

    id: str
    part: str
    kind: str
    request_value_mm: float
    request_text: str
    message: str
    axis: str | None = None
    dimension: str | None = None
    dimension_value_mm: float | None = None
    status: str = "open"
    first_build: int = 1
    last_build: int = 1
    #: The user was asked about this finding (runtime-written, like §3's ``asked``).
    asked: bool = False
    #: The committal answer that dismissed it (runtime-written; never the model's).
    dismissal: str | None = None
    #: How a non-open finding closed: ``rebuild`` or ``dismissed``.
    closed_by: str | None = None

    @property
    def open(self) -> bool:
        return self.status == "open"

    @property
    def expected(self) -> str:
        axis = f" on {self.axis.upper()}" if self.axis else ""
        return f"{self.request_text}{axis} (from the request)"

    @property
    def observed(self) -> str:
        if self.dimension is None or self.dimension_value_mm is None:
            return "no dimension in the built geometry corresponds to it"
        return f"{self.dimension} measures {self.dimension_value_mm:g} mm"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "part": self.part,
            "kind": self.kind,
            "request_value_mm": self.request_value_mm,
            "request_text": self.request_text,
            "message": self.message,
            "axis": self.axis,
            "dimension": self.dimension,
            "dimension_value_mm": self.dimension_value_mm,
            "status": self.status,
            "first_build": self.first_build,
            "last_build": self.last_build,
            "asked": self.asked,
            "dismissal": self.dismissal,
            "closed_by": self.closed_by,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> DimensionFinding:
        raw_id = data.get("id")
        part = data.get("part")
        kind = data.get("kind")
        value = data.get("request_value_mm")
        if not isinstance(raw_id, str) or not isinstance(part, str) or not isinstance(kind, str):
            raise CadOpError("invalid_dimension_finding", "a finding needs id, part and kind")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise CadOpError(
                "invalid_dimension_finding", f"finding {raw_id}: request_value_mm must be a number"
            )
        status = data.get("status")
        if status not in _STATUSES:
            raise CadOpError(
                "invalid_dimension_finding", f"finding {raw_id}: status must be one of {_STATUSES}"
            )
        return cls(
            id=raw_id,
            part=part,
            kind=kind,
            request_value_mm=float(value),
            request_text=_str(data.get("request_text")) or "",
            message=_str(data.get("message")) or "",
            axis=_str(data.get("axis")),
            dimension=_str(data.get("dimension")),
            dimension_value_mm=_number(data.get("dimension_value_mm")),
            status=status,
            first_build=_int(data.get("first_build"), 1),
            last_build=_int(data.get("last_build"), 1),
            asked=data.get("asked") is True,
            dismissal=_str(data.get("dismissal")),
            closed_by=_str(data.get("closed_by")),
        )


def _str(raw: JSONValue | None) -> str | None:
    return raw if isinstance(raw, str) and raw.strip() else None


def _number(raw: JSONValue | None) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _int(raw: JSONValue | None, fallback: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return fallback
    return raw


@dataclass(frozen=True)
class DimensionFindingState:
    """One immutable findings generation: every finding ever raised, and its status."""

    generation: int
    findings: tuple[DimensionFinding, ...]
    builds: int = 0
    blob: str | None = None
    parent: str | None = None

    @property
    def artifact_ref(self) -> str | None:
        if self.blob is None:
            return None
        return make_artifact_ref(DIMENSION_FINDING_ARTIFACT_KIND, self.blob)

    @property
    def by_id(self) -> dict[str, DimensionFinding]:
        return {finding.id: finding for finding in self.findings}

    @property
    def open(self) -> tuple[DimensionFinding, ...]:
        """The findings that still keep the run out of green (§6)."""
        return tuple(finding for finding in self.findings if finding.open)

    @property
    def open_ids(self) -> tuple[str, ...]:
        return tuple(finding.id for finding in self.open)

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "builds": self.builds,
            "findings": [finding.to_json() for finding in self.findings],
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "builds": self.builds,
            "findings": [finding.to_json() for finding in self.findings],
            "open": list(self.open_ids),
        }

    @classmethod
    def from_document(
        cls, data: Mapping[str, JSONValue], blob: str | None
    ) -> DimensionFindingState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise CadOpError("invalid_dimension_finding", "findings generation must be an integer")
        raw = data.get("findings")
        if not isinstance(raw, list):
            raise CadOpError("invalid_dimension_finding", "findings must be an array")
        parent = data.get("parent")
        return cls(
            generation=generation,
            findings=tuple(
                DimensionFinding.from_json(cast("Mapping[str, JSONValue]", item))
                for item in cast("list[JSONValue]", raw)
                if isinstance(item, dict)
            ),
            builds=_int(data.get("builds"), 0),
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
        )


#: The empty state every project starts from.
_EMPTY: Final[DimensionFindingState] = DimensionFindingState(generation=0, findings=())


def _finding_from_warning(
    warning: Mapping[str, JSONValue], *, part: str, build: int
) -> DimensionFinding | None:
    """One §4 warning as a finding, or ``None`` when the kind does not bind."""
    kind = warning.get("kind")
    if not isinstance(kind, str) or kind not in BINDING_WARNING_KINDS:
        return None
    value = warning.get("request_value_mm")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    axis = _str(warning.get("axis"))
    if axis is None:
        # An *axis-less* unmatched number ("no dimension corresponds to 12 mm")
        # says the harness could not find the number, not that the geometry
        # contradicts it — the 12 mm may well be there, untagged and unmeasured.
        # It stays the advisory warning it always was: binding on the harness's
        # blindness would make every run red and the terminal meaningless. What
        # binds is a number the request pinned to an axis, which the bbox always
        # measures, so the contradiction is real either way round.
        return None
    request_value = float(value)
    return DimensionFinding(
        id=dimension_finding_id(part, kind, axis, request_value),
        part=part,
        kind=kind,
        request_value_mm=request_value,
        request_text=_str(warning.get("request_text")) or f"{request_value:g} mm",
        message=_str(warning.get("message")) or "",
        axis=axis,
        dimension=_str(warning.get("dimension")),
        dimension_value_mm=_number(warning.get("dimension_value_mm")),
        status="open",
        first_build=build,
        last_build=build,
    )


def _reconcile(
    current: DimensionFindingState, part: str, raised: Sequence[DimensionFinding], build: int
) -> tuple[DimensionFinding, ...]:
    """Apply one successful build of ``part`` to the finding set.

    The clearing rule, and the whole of it: a finding open against *this part*
    that this build's binding diff no longer raises has been resolved by the
    geometry, and closes as ``rebuild``. Everything else is untouched — a finding
    on another part is not evidence about this one, and a dismissal stays
    dismissed even if the number is raised again, because a user already judged
    that dimension.
    """
    incoming = {finding.id: finding for finding in raised}
    out: list[DimensionFinding] = []
    for existing in current.findings:
        fresh = incoming.pop(existing.id, None)
        if fresh is not None:
            if existing.status == "dismissed":
                out.append(existing)  # already judged by a human; do not reopen
                continue
            out.append(
                replace(
                    existing,
                    status="open",
                    closed_by=None,
                    message=fresh.message,
                    dimension=fresh.dimension,
                    dimension_value_mm=fresh.dimension_value_mm,
                    last_build=build,
                )
            )
            continue
        if existing.part == part and existing.status == "open":
            out.append(replace(existing, status="cleared", closed_by="rebuild", last_build=build))
            continue
        out.append(existing)
    out.extend(incoming[key] for key in sorted(incoming))
    return tuple(out)


class DimensionFindingOps(CadOpsState):
    """The runtime-owned store of binding §4 findings (no model-facing writes)."""

    # -- reading -----------------------------------------------------------

    def dimension_findings(self) -> DimensionFindingState:
        """The current findings generation (empty when nothing was ever raised)."""
        blob = self._store.blobs.read_pointer(DIMENSION_FINDINGS_POINTER)
        if blob is None:
            return _EMPTY
        return self._findings_from_blob(blob)

    def dimension_findings_generation(self, artifact_ref: str) -> DimensionFindingState:
        """Any historical generation by its immutable artifact ref."""
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_ref", f"findings generation {artifact_ref} is not stored")
        return self._findings_from_blob(blob)

    def _findings_from_blob(self, blob: str) -> DimensionFindingState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise CadOpError("invalid_dimension_finding", "findings document is malformed")
        return DimensionFindingState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    # -- writing (runtime only) --------------------------------------------

    def record_dimension_findings(
        self, part: str, warnings: Iterable[Mapping[str, JSONValue]]
    ) -> DimensionFindingState:
        """Record one successful build's binding diff: raise, refresh and clear.

        Called by ``build_part`` itself, from the critique it just computed — not
        by the model, which has no way to reach this at all. Idempotent: an
        identical build against an unchanged state replays instead of advancing a
        generation.
        """
        current = self.dimension_findings()
        build = current.builds + 1
        raised = [
            finding
            for finding in (
                _finding_from_warning(warning, part=part, build=build) for warning in warnings
            )
            if finding is not None
        ]
        # Deduplicate: two warnings can describe the same unmet number (an
        # axis-tagged mismatch raises both kinds), but two identical ids cannot.
        unique: dict[str, DimensionFinding] = {}
        for finding in raised:
            unique.setdefault(finding.id, finding)
        if not unique and not current.findings:
            # The overwhelmingly common build: nothing raised, nothing on record.
            # Counting it would mint a generation per build for no evidence.
            return current
        payload: JSONValue = {
            "kind": "record_dimension_findings",
            "part": part,
            "before": current.blob,
            "raised": [finding.to_json() for finding in unique.values()],
        }
        return self._publish(
            current,
            payload,
            lambda state: _reconcile(state, part, tuple(unique.values()), build),
            builds=build,
            op_id=f"dimfind:{sha256_canonical_json(payload)[:32]}",
        )

    def dismiss_dimension_finding(
        self,
        finding_id: str,
        *,
        answer: str,
        dismissed: bool,
        op_id: str,
        provenance: str = "model",
    ) -> DimensionFindingState | None:
        """Record a user's answer about one finding; ``None`` when it is unknown.

        ``provenance`` defaults to the untrusted caller and is refused: the only
        way here is :func:`.._gate.record_dimension_answer`, applying a real
        ``ask_user`` answer. ``dismissed`` is that answer's committal-ness, judged
        by the same rule §3 uses — so "unspecified, use your judgement" records
        that the question was put and closes nothing.
        """
        if provenance != _RUNTIME:
            raise CadOpError(
                "invalid_dimension_finding",
                f"dimension finding {finding_id!r} may only be dismissed by the runtime from a "
                "real ask_user answer, so nothing was written. A binding dimension finding is "
                "cleared by rebuilding the geometry to match the request, or by the user "
                "dismissing it through ask_user(requirement_ids=[…]).",
            )
        current = self.dimension_findings()
        existing = current.by_id.get(finding_id)
        if existing is None:
            return None
        updated = (
            replace(existing, asked=True, status="dismissed", dismissal=answer, closed_by="user")
            if dismissed and existing.status == "open"
            else replace(existing, asked=True)
        )
        payload: JSONValue = {
            "kind": "dismiss_dimension_finding",
            "id": finding_id,
            "before": current.blob,
            "after": updated.to_json(),
        }
        return self._publish(
            current,
            payload,
            lambda state: tuple(
                updated if finding.id == finding_id else finding for finding in state.findings
            ),
            builds=current.builds,
            op_id=op_id,
        )

    # -- the one generation-advancing path ---------------------------------

    def _publish(
        self,
        current: DimensionFindingState,
        payload: JSONValue,
        apply: Callable[[DimensionFindingState], tuple[DimensionFinding, ...]],
        *,
        builds: int,
        op_id: str,
    ) -> DimensionFindingState:
        """Publish one immutable generation, idempotent on ``op_id``.

        No project-config lock: unlike the ledger this is never written by a tool
        call, only by the runtime inside an already-sequential ``build_part`` or
        ``ask_user`` handler, and the pointer CAS on ``current.blob`` is what makes
        a lost race fail loudly instead of silently dropping a finding.
        """
        candidate = DimensionFindingState(
            generation=current.generation + 1,
            findings=apply(current),
            builds=builds,
            blob=None,
            parent=current.blob,
        )
        if candidate.findings == current.findings and candidate.builds == current.builds:
            return current  # nothing moved; do not mint a generation for it
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            blob = recorded_ref(outcome.response, "state", "")
            if blob and self._store.blobs.has(blob):
                return self._findings_from_blob(blob)
            return self.dimension_findings()
        if not isinstance(outcome, Fresh):
            raise CadOpError(
                "conflict", f"dimension-finding write {op_id!r} cannot proceed: {outcome!r}"
            )
        new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
        self._store.wal.publish(
            outcome,
            DIMENSION_FINDINGS_POINTER,
            current.blob,
            new_blob,
            intended_outcome=canonical_json(
                {"generation": candidate.generation, "state": new_blob}
            ),
        )
        return replace(candidate, blob=new_blob)


def dimension_findings(project: DimensionFindingOps) -> DimensionFindingState:
    """The typed reader §5/§6 use (mirrors :func:`.._requirements.ledger_state`)."""
    return project.dimension_findings()


def finding_views(findings: Iterable[DimensionFinding]) -> list[dict[str, JSONValue]]:
    """Findings as plain JSON objects (the shape the critique block carries)."""
    return [finding.to_json() for finding in findings]
