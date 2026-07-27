"""The clarification gate: ``VALIDATION.md`` §3, enforced by rule.

``build_part`` is **refused** while the requirement ledger holds an entry that is
``source: "assumed"``, *material* (it moves geometry) and carries no runtime
clarification record. The refusal is a discriminated result — ``{status:
"clarification_required", entries, message}`` — not a transport error, so the
model branches on it the way it branches on any other outcome.

**What the gate is for.** It compels the *question*, not a good outcome: what
clears it is the runtime having recorded an ``ask_user`` exchange against the
entry — a committal answer (``resolution``, the assumption is settled) or a
declined one (``asked`` alone, the assumption stands unconfirmed). §3's closing
clause and §6's own example of a good ending — "built, but wall direction
unconfirmed and Y envelope is 46 mm against a stated 40 mm" — both describe a run
that reaches geometry with an assumption still open, so a declined answer hands
the burden to §5 rather than ending the run before anything is built. §5 keeps
that burden honest: it is fail-unless-*confirmed*, and only a ``resolution``
confirms, so the declining path can never terminate green.

Three rules live here, and all three are structural:

**Which assumption is material.** The model's own ``material`` flag is honoured
when it says *true*, but it cannot opt out of the gate by writing *false*: an
assumption whose ``applies_to``/``text`` names one of the §3 material classes —
envelope dimension, datum/origin placement, wall or feature direction, fit class
or clearance, joint mating direction, unstated thickness — is material because
the harness classifies it so. A gate the model can disarm by tagging its own
guess is not a gate.

**What a clarification question must look like.** A question raised against
ledger ids must offer 2-4 concrete options, *each stating its geometric
consequence* — the ``{label, consequence}`` option form. A question that does
not is refused with the discriminated ``invalid_question`` result before anyone
is asked. The concrete-options pattern is therefore a schema obligation, not
prompt advice.

**What an answer does to the ledger.** The answer is recorded against the
requirement id by the runtime, never by the model choosing to call
``update_requirement`` — ``asked`` and ``resolution`` are refused on every
model-facing ledger write (``_requirements.RUNTIME_ONLY_FIELDS``), which is what
makes their presence *evidence* rather than a claim. A committal answer lands as
``resolution``; a declined or non-committal answer — the bench answerer's
"unspecified — use your engineering judgment" is exactly this — sets ``asked:
true`` only and **leaves the entry assumed**, so it faces §5 as
fail-unless-confirmed and cannot end the run green.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Final

from opstore.types import JSONValue

from ._findings import DimensionFindingOps, DimensionFindingState
from ._requirements import LedgerState, RequirementEntry, RequirementOps

__all__ = [
    "CLARIFICATION_MAX_OPTIONS",
    "CLARIFICATION_MIN_OPTIONS",
    "INVALID_QUESTION_CODE",
    "MATERIAL_CLASSES",
    "ClarificationGate",
    "ClarificationOutcome",
    "answer_op_id",
    "answer_text",
    "clarification_gate",
    "invalid_question_result",
    "is_committal",
    "material_class",
    "option_consequence",
    "option_label",
    "question_problems",
    "question_refusal",
    "record_answers",
    "record_clarification_answer",
    "record_dimension_answer",
    "requirement_ids",
]

#: §3's material classes. Each is matched case-insensitively against the entry's
#: ``applies_to`` and ``text`` — the two free-text fields that say *what the
#: assumption is about*. The list is explicitly non-exhaustive; over-inclusion is
#: the safe direction, because the cost of a wrong classification is one question
#: and the cost of a missed one is a silently misread spec. Order is
#: most-specific-first — only the reported *label* depends on it, never whether
#: the entry gates.
MATERIAL_CLASSES: Final[tuple[tuple[str, str], ...]] = (
    (
        "feature_direction",
        r"\b(direction|inside|outside|inward|outward|inboard|outboard|"
        r"orientation|normal|side|face|wall|flange|rib)\b",
    ),
    (
        "datum_origin",
        r"datum|origin|reference (?:face|plane|edge)|coordinate|placement|"
        r"\b(centred|centered|located|location|position|offset)\b",
    ),
    (
        "fit_clearance",
        r"\b(fit|clearance|tolerance|slip|press|interference|gap|allowance)\b",
    ),
    (
        "material_thickness",
        r"\b(thick|thickness|gauge|sheet|stock|wall_thickness)\b",
    ),
    (
        "joint_mating",
        r"\b(joint|mate|mates|mating|assembly|assemble|interface|mount|mounting|bolt|fastener)\b",
    ),
    (
        "envelope_dimension",
        r"envelope|overall|bounding|footprint|extent|span|"
        r"\b(width|height|depth|length|diameter|radius|size|dimension)\b",
    ),
)

_CLASS_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (name, re.compile(pattern, re.IGNORECASE)) for name, pattern in MATERIAL_CLASSES
)

#: §3: "2-4 options, each stating its geometric consequence".
CLARIFICATION_MIN_OPTIONS: Final[int] = 2
CLARIFICATION_MAX_OPTIONS: Final[int] = 4

#: The discriminated code of a badly-shaped clarification question.
INVALID_QUESTION_CODE: Final[str] = "clarification_question_shape"

#: Answers that decline to decide. A run whose answer matches one of these has
#: raised the question (``asked: true``) without resolving the assumption.
_NON_COMMITTAL: Final[tuple[str, ...]] = (
    "unspecified",
    "not specified",
    "engineering judgment",
    "engineering judgement",
    "best judgment",
    "best judgement",
    "your judgment",
    "your judgement",
    "you decide",
    "you choose",
    "your call",
    "up to you",
    "as you see fit",
    "no preference",
    "no opinion",
    "no answer",
    "not sure",
    "unsure",
    "unknown",
    "don't know",
    "dont know",
    "do not know",
    "doesn't matter",
    "does not matter",
    "either way",
    "either is fine",
    "either one",
    "whatever you think",
    "decline",
    "skip",
    "n/a",
)


def material_class(entry: RequirementEntry) -> str | None:
    """The §3 material class this entry falls in, or ``None``.

    Classification reads ``applies_to`` and ``text`` only — never the model's own
    ``material`` flag — so it is an independent second opinion on that flag.
    """
    subject = f"{entry.applies_to or ''} {entry.text}"
    for name, pattern in _CLASS_PATTERNS:
        if pattern.search(subject):
            return name
    return None


def _is_material(entry: RequirementEntry) -> bool:
    """Material by the model's declaration OR by the harness's classification."""
    return entry.material is True or material_class(entry) is not None


def _blocking(entry: RequirementEntry) -> bool:
    """Whether this entry refuses the build right now (§3).

    What clears it is the *runtime's* clarification record — ``asked`` or
    ``resolution``, neither of which the model can write. So the gate compels the
    question and nothing else: guessing well does not clear it, and a declined
    answer clears the gate while leaving the assumption unconfirmed for §5.
    """
    return (
        entry.source == "assumed"
        and _is_material(entry)
        and not entry.asked
        and not entry.confirmed
    )


@dataclass(frozen=True)
class ClarificationGate:
    """The gate's verdict over one ledger generation."""

    generation: int
    entries: tuple[RequirementEntry, ...]
    #: No ledger exists at all — geometry may not precede requirements (§2).
    no_ledger: bool = False

    @property
    def blocked(self) -> bool:
        """Whether ``build_part`` must be refused right now."""
        return self.no_ledger or bool(self.entries)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(entry.id for entry in self.entries)

    def message(self) -> str:
        """Why the build is refused, and the exact shape of the way out."""
        if self.no_ledger:
            return (
                "build_part is refused: this project has no requirement ledger, and "
                "geometry may not precede requirements (VALIDATION.md §2). Call "
                "record_requirements(entries=[…]) first — one entry per constraint, each "
                'tagged source="specified" (with the quote it comes from), "derived" '
                '(with the ids it follows from), or "assumed" (with a rationale and '
                "whether it moves geometry). Ledger calls are not charged against the "
                "tool-call budget."
            )
        listed = "; ".join(
            f"{entry.id} ({material_class(entry) or 'declared material'}): {entry.text}"
            for entry in self.entries
        )
        return (
            f"build_part is refused: {len(self.entries)} material assumption(s) were never "
            f"put to the user [{listed}]. Ask with ask_user(requirement_ids=[…]) offering "
            f"{CLARIFICATION_MIN_OPTIONS}-{CLARIFICATION_MAX_OPTIONS} concrete options, each "
            "carrying the geometric consequence of choosing it "
            '({"label": …, "consequence": …}). The runtime records the answer itself: a '
            "committal one resolves the entry, a non-committal one leaves it assumed and "
            "unconfirmed for the termination review. Either way the build unblocks — but you "
            "cannot write the answer yourself, and an unconfirmed assumption cannot finish green."
        )

    def to_result(self) -> dict[str, Any]:
        """The discriminated ``build_part`` refusal result of §3."""
        return {
            "status": "clarification_required",
            "reason": "no_ledger" if self.no_ledger else "unresolved_material_assumption",
            "generation": self.generation,
            "entries": [entry.to_json() for entry in self.entries],
            "unresolved_material": list(self.ids),
            "message": self.message(),
        }


def clarification_gate(state: LedgerState) -> ClarificationGate:
    """Evaluate §3 over a ledger generation (no I/O; pure over the state).

    An EMPTY ledger blocks too. ``VALIDATION.md`` §2 opens "before any geometry,
    the agent emits a ledger", and the ladder's design rule is that every rung
    fires by rule rather than by model choice — so if the mere absence of a
    ledger were permitted, an agent that never calls ``record_requirements``
    would face no gate (§3), give the reviewer nothing to verify against (§5),
    and make §8's coverage metric vacuous. Measured on 2026-07-26: a bench run
    reported ``compelled=0`` on every run, i.e. the whole ladder sat inert
    behind a tool the model simply never called.
    """
    return ClarificationGate(
        generation=state.generation,
        no_ledger=not state.entries,
        entries=tuple(entry for entry in state.entries if _blocking(entry)),
    )


# -- question shape ---------------------------------------------------------


def option_label(option: JSONValue) -> str:
    """The display text of an option in either supported form."""
    if isinstance(option, Mapping):
        raw = option.get("label")  # pyright: ignore[reportUnknownMemberType]
        return str(raw) if isinstance(raw, str) else ""
    return str(option)


def option_consequence(option: JSONValue) -> str | None:
    """The stated geometric consequence of an option, if it carries one."""
    if not isinstance(option, Mapping):
        return None
    raw = option.get("consequence")  # pyright: ignore[reportUnknownMemberType]
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def question_problems(question: JSONValue, options: JSONValue) -> tuple[str, ...]:
    """Every way this clarification question fails §3's concrete-options pattern.

    Empty means the question may be asked. This is the whole enforcement: a
    question raised against ledger ids either carries 2-4 options that each state
    a geometric consequence, or it is never put to the user at all.
    """
    problems: list[str] = []
    if not isinstance(question, str) or not question.strip():
        problems.append("question must be a non-empty string")
    if not isinstance(options, list):
        return (*problems, "options must be an array of 2-4 concrete options")
    items: list[JSONValue] = list(options)
    if not CLARIFICATION_MIN_OPTIONS <= len(items) <= CLARIFICATION_MAX_OPTIONS:
        problems.append(
            f"a clarification needs {CLARIFICATION_MIN_OPTIONS}-{CLARIFICATION_MAX_OPTIONS} "
            f"options, got {len(items)}"
        )
    for index, option in enumerate(items):
        if not option_label(option).strip():
            problems.append(f"option {index}: a non-empty label is required")
        if option_consequence(option) is None:
            problems.append(
                f"option {index}: must state its geometric consequence "
                '({"label": …, "consequence": …})'
            )
    return tuple(problems)


def invalid_question_result(problems: Sequence[str]) -> dict[str, Any]:
    """The discriminated ``ask_user`` refusal for a badly-shaped clarification."""
    return {
        "status": "invalid_question",
        "code": INVALID_QUESTION_CODE,
        "message": (
            "a clarification question must offer "
            f"{CLARIFICATION_MIN_OPTIONS}-{CLARIFICATION_MAX_OPTIONS} concrete options, each "
            "stating its geometric consequence; the question was not asked"
        ),
        "problems": list(problems),
    }


# -- recording the answer ---------------------------------------------------


def answer_text(selection: JSONValue) -> str:
    """One flat string for any ``ask_user`` selection shape (str / list / option)."""
    if isinstance(selection, list):
        parts: list[str] = [answer_text(item) for item in selection]
        return "; ".join(part for part in parts if part)
    if isinstance(selection, Mapping):
        label = option_label(selection)
        consequence = option_consequence(selection)
        return f"{label} — {consequence}" if consequence else label
    if selection is None:
        return ""
    return str(selection)


def is_committal(selection: JSONValue) -> bool:
    """Whether this answer actually decides the question (§3 / §7).

    A declined or non-committal answer is not a resolution: the entry stays
    ``assumed`` and only records that it was ``asked``. Classification is
    deliberately conservative — an answer wrongly read as non-committal keeps the
    build blocked, which is the safe direction.
    """
    text = answer_text(selection).strip().lower()
    if not text:
        return False
    return not any(marker in text for marker in _NON_COMMITTAL)


@dataclass(frozen=True)
class ClarificationOutcome:
    """What one answer did to one ledger entry — or to one binding §4 finding."""

    requirement_id: str
    committal: bool
    answer: str
    #: The generation the answer produced; ``None`` when the id was unknown, which
    #: is the one case where an answer records nothing.
    state: LedgerState | DimensionFindingState | None

    @property
    def recorded(self) -> bool:
        return self.state is not None


def record_clarification_answer(
    project: RequirementOps,
    requirement_id: str,
    selection: JSONValue,
    *,
    op_id: str,
) -> ClarificationOutcome:
    """Apply §3's answer rule to one entry; the runtime does this, not the model.

    Committal → ``{asked: true, resolution: <answer>}`` (the gate opens).
    Non-committal / declined → ``{asked: true}`` only (the entry stays assumed,
    the gate stays shut, and §5 sees an unconfirmed assumption).
    """
    text = answer_text(selection)
    committal = is_committal(selection)
    fields: dict[str, JSONValue] = {"asked": True}
    if committal:
        fields["resolution"] = text
    if requirement_id not in project.ledger_state().by_id:
        return ClarificationOutcome(requirement_id, committal, text, None)
    state = project.update_requirement(requirement_id, fields, op_id=op_id, provenance="runtime")
    return ClarificationOutcome(requirement_id, committal, text, state)


def requirement_ids(raw: JSONValue) -> tuple[str, ...]:
    """The ledger ids a question is raised against (``[]`` when it is not one)."""
    if not isinstance(raw, list):
        return ()
    items: list[JSONValue] = list(raw)
    return tuple(item for item in items if isinstance(item, str) and item.strip())


# -- the two hooks the ``py.ask_user`` handler is made of -------------------


def question_refusal(params: Mapping[str, Any]) -> dict[str, Any] | None:
    """The refusal to *ask* a badly-shaped clarification, or ``None`` to proceed.

    Called before the answerer runs: a malformed clarification never reaches a
    human. A question that names no ledger ids is an ordinary question and is
    always allowed through.
    """
    if not requirement_ids(params.get("requirement_ids")):
        return None
    problems = question_problems(params.get("question"), params.get("options"))
    return invalid_question_result(problems) if problems else None


def record_dimension_answer(
    project: DimensionFindingOps,
    finding_id: str,
    selection: JSONValue,
    *,
    op_id: str,
) -> ClarificationOutcome:
    """§4/§6: a user's answer about one **binding dimension finding**.

    The dismissal path, and the only one there is. It mirrors
    :func:`record_clarification_answer` exactly — the runtime writes it, from a
    real answer, and the same committal test decides: a committal answer dismisses
    the finding (the user has judged that dimension), a declined or non-committal
    one records that the question was put and dismisses nothing. That is why the
    bench, which answers "unspecified — use your engineering judgment" by rule,
    can never answer its way past its own measurement.
    """
    text = answer_text(selection)
    committal = is_committal(selection)
    state = project.dismiss_dimension_finding(
        finding_id,
        answer=text,
        dismissed=committal,
        op_id=op_id,
        provenance="runtime",
    )
    return ClarificationOutcome(finding_id, committal, text, None if state is None else state)


def record_answers(
    project: RequirementOps,
    run_id: str,
    params: Mapping[str, Any],
    selection: JSONValue,
) -> list[dict[str, Any]]:
    """Write one answer back to every requirement the question was raised against.

    ``requirement_ids`` names ledger entries *and* binding §4 dimension findings —
    the two things a run can be blocked on, both cleared only by a runtime-recorded
    answer. An id that is a known finding is routed to the findings store
    (:func:`record_dimension_answer`); anything else is a ledger id
    (:func:`record_clarification_answer`). An id in neither is reported
    ``recorded: false`` rather than silently accepted.

    The op id is derived from ``(run_id, id, answer)`` — never model-supplied — so
    a repeated identical answer replays instead of piling up generations, while a
    *different* answer to the same question is a new write.
    """
    known_findings: dict[str, object] = (
        dict(project.dimension_findings().by_id) if isinstance(project, DimensionFindingOps) else {}
    )
    outcomes: list[dict[str, Any]] = []
    for requirement_id in requirement_ids(params.get("requirement_ids")):
        op_id = answer_op_id(run_id, requirement_id, selection)
        if requirement_id in known_findings and isinstance(project, DimensionFindingOps):
            outcome = record_dimension_answer(project, requirement_id, selection, op_id=op_id)
            outcomes.append(
                {
                    "id": requirement_id,
                    "kind": "dimension_finding",
                    "committal": outcome.committal,
                    "recorded": outcome.recorded,
                    "dismissed": outcome.committal and outcome.recorded,
                    "resolution": outcome.answer if outcome.committal else None,
                }
            )
            continue
        clarification = record_clarification_answer(project, requirement_id, selection, op_id=op_id)
        outcomes.append(
            {
                "id": requirement_id,
                "committal": clarification.committal,
                "recorded": clarification.recorded,
                "resolution": clarification.answer if clarification.committal else None,
            }
        )
    return outcomes


def answer_op_id(run_id: str, requirement_id: str, selection: JSONValue) -> str:
    """The derived idempotency key of one clarification write."""
    payload = json.dumps(selection, sort_keys=True, default=str)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"clarify:{run_id}:{requirement_id}:{digest}"
