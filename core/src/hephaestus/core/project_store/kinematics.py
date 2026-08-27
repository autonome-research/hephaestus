# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The joint set and pose set: a mechanism's configuration family as project state.

``KINEMATICS.md`` §1 and §3. A joint relates two parts, so — like an 8C
constraint — it cannot live in any one part script; the project carries it. A
named pose binds joint parameter values, so it is project state for the same
reason. Both sets ride the requirement ledger's pattern, copied from
:mod:`hephaestus.core.project_store.constraints` rather than reinvented (§7
names this deliberately — four uses of one pattern, not four patterns): every
generation is an immutable content-addressed document
(``artifact:joints:sha256:…`` / ``artifact:poses:sha256:…``) naming its
parent, published by a compare-and-swap of its live pointer under the
**project-config lock**. Older generations stay readable forever, which is
what makes "declare → update → withdraw" replayable and what makes a
withdrawal a new generation rather than an erasure.

A joint entry is exactly the ``KINEMATICS.md`` §1 shape::

    {"id": "j-elbow", "kind": "revolute",
     "parent": "arm_upper:elbow_bore", "child": "arm_fore:elbow_pin",
     "limits": {"min": -5.0, "max": 150.0},
     "zero": "as_built",
     "provenance": {"requirement": "r-3"}, "note": "elbow travel per spec table 2"}

**Anchors are the 8C anchor grammar, exactly** (§1): ``part[:selector]``
under the same ``ANCHOR_PATTERN``, imported from the constraint set rather
than restated. A slash in an anchor is refused ``invalid_joint`` for the same
two-grammars reason the 8C module records: ``"<part>/<selector>"`` is the
script-contract §7 *cross-part selector* form, and an anchor already knows
which part it means, so accepting that spelling would invite two grammars for
one string.

**The joint graph must be a forest** (§1): parent/child edges over parts,
each part riding at most one joint, no cycles. A cycle is refused
``cyclic_joint_graph`` at declaration with the cycle named — closed-loop
mechanisms are expressed as an open chain plus a pose-bound 8C constraint, so
loop closure is *measured* honestly rather than solved.

**Provenance is compulsory** on joints and poses alike, the ``VALIDATION.md``
§2 taxonomy: cite a ledger requirement or be ``assumed`` with a reason.
Travel limits and parameter bindings are interpretations of intent, so they
say whose; an entry with neither is refused (``invalid_joint`` /
``invalid_pose``) and nothing is written.

**A pose may only bind declared, unwithdrawn joints at declaration** (§3);
naming an unknown or already-withdrawn joint is refused ``invalid_pose``. A
pose whose joint is withdrawn *later* is a different thing entirely: that is
``orphaned_pose``, a per-POSE evaluation state (§2) — the pose is not erased
and the withdrawal is not a failure, so declaration must not be re-refused
retroactively and this module never re-validates stored generations against
the live joint set.

**The motion-check set** (Stage 9B, ``KINEMATICS.md`` §4) is the third rider
on the same pattern: a motion check states a requirement about a *family* of
configurations — clearance across a travel, no interference through a swing,
a point reached somewhere in a range — so like a joint it belongs to the
project, not to any part script. An entry is exactly the §4 shape::

    {"id": "mc-elbow-clear", "kind": "sweep_clearance",
     "a": "arm_fore", "b": "arm_upper:wire_channel",
     "sweep": {"j-elbow": {"from": -5.0, "to": 150.0}},
     "min_mm": 2.0, "samples": 64,
     "provenance": {"requirement": "r-5"}}

Kinds are the closed §4 set (``sweep_clearance`` / ``sweep_no_interference``
/ ``reach``); anchors are the 8C grammar exactly as joint anchors are; sweep
ranges name declared, unwithdrawn joints with one declarable DOF (a ``fixed``
joint has no parameter to sweep, and a ``cylindrical`` joint's ``(degrees,
mm)`` pair has no scalar wire form in 9A — either would be a check born
unevaluatable, refused at declaration like a pose born orphaned). ``samples``
is the PER-AXIS request (default :data:`SWEEP_SAMPLES_DEFAULT`, endpoints
inclusive) and **the cap is on the computed grid total**: a declaration whose
product ``samples ** n_joints`` exceeds :data:`SWEEP_SAMPLES_MAX` is refused
at declaration with the refusal naming the computed total — per-axis honesty
cannot smuggle in an unbounded grid. A swept joint withdrawn *later* is
``orphaned_sweep`` at evaluation (:mod:`hephaestus.core.motion`), the exact
``orphaned_pose`` rule restated: not erased, not re-refused, named when read.

What lives elsewhere: *evaluating* joints, poses and motion checks — anchor
frames, forward kinematics, ``MotionStatus``, sampled sweeps — is Stage 9's
engine and geom work (``KINEMATICS.md`` §2/§4), and the staleness of a
projected status is :mod:`hephaestus.core.project_store.projections`. This
module only knows what was declared, by whom, and why.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Final, Literal, cast

from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.project_store.constraints import (
    ANCHOR_PATTERN,
    ANCHOR_SEPARATOR,
    WHOLE_PART_SELECTOR,
    Anchor,
)
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
    "JOINTS_POINTER",
    "JOINT_ARTIFACT_KIND",
    "JOINT_ID_PATTERN",
    "JOINT_KINDS",
    "JOINT_REF_PREFIX",
    "MOTION_CHECKS_POINTER",
    "MOTION_CHECK_ARTIFACT_KIND",
    "MOTION_CHECK_KINDS",
    "MOTION_CHECK_REF_PREFIX",
    "POSES_POINTER",
    "POSE_ARTIFACT_KIND",
    "POSE_REF_PREFIX",
    "SWEEP_SAMPLES_DEFAULT",
    "SWEEP_SAMPLES_MAX",
    "JointChange",
    "JointEntry",
    "JointError",
    "JointSet",
    "JointState",
    "KinematicProvenance",
    "LimitPair",
    "MotionCheckChange",
    "MotionCheckEntry",
    "MotionCheckError",
    "MotionCheckSet",
    "MotionCheckState",
    "PoseChange",
    "PoseEntry",
    "PoseError",
    "PoseSet",
    "PoseState",
    "SweepRange",
    "parse_check_anchor",
    "parse_joint_anchor",
]

#: CAS pointer naming the current joint-set generation's state blob.
JOINTS_POINTER: Final[str] = "joints-state"
#: Artifact kind of an immutable joint-set generation document.
JOINT_ARTIFACT_KIND: Final[str] = "joints"
JOINT_REF_PREFIX: Final[str] = f"artifact:{JOINT_ARTIFACT_KIND}:"

#: CAS pointer naming the current pose-set generation's state blob.
POSES_POINTER: Final[str] = "poses-state"
#: Artifact kind of an immutable pose-set generation document.
POSE_ARTIFACT_KIND: Final[str] = "poses"
POSE_REF_PREFIX: Final[str] = f"artifact:{POSE_ARTIFACT_KIND}:"

#: CAS pointer naming the current motion-check-set generation's state blob.
MOTION_CHECKS_POINTER: Final[str] = "motion-checks-state"
#: Artifact kind of an immutable motion-check-set generation document.
MOTION_CHECK_ARTIFACT_KIND: Final[str] = "motion-checks"
MOTION_CHECK_REF_PREFIX: Final[str] = f"artifact:{MOTION_CHECK_ARTIFACT_KIND}:"

#: The Stage 9 kind set (``KINEMATICS.md`` §1); each later kind is a contract
#: amendment, so the set is closed here rather than extensible.
JOINT_KINDS: Final[tuple[str, ...]] = ("fixed", "revolute", "prismatic", "cylindrical")

#: The Stage 9 motion-check kind set (``KINEMATICS.md`` §4), closed for the
#: same reason. Swept-volume envelopes are §6 *facts*, not check kinds.
MOTION_CHECK_KINDS: Final[tuple[str, ...]] = (
    "sweep_clearance",
    "sweep_no_interference",
    "reach",
)

#: Default PER-AXIS sample count of a sweep (``KINEMATICS.md`` §4), inclusive
#: of both endpoints — which is why the smallest honest request is 2: a
#: one-sample "sweep" is a pose wearing a sweep's name.
SWEEP_SAMPLES_DEFAULT: Final[int] = 64

#: Cap on the COMPUTED GRID TOTAL ``samples ** n_joints`` (``KINEMATICS.md``
#: §4). The cap is deliberately not per-axis: a two-joint sweep at 65 per axis
#: is 4225 measurements, and a declaration is refused on that computed total,
#: the refusal naming it, so cost is visible where it is incurred.
SWEEP_SAMPLES_MAX: Final[int] = 4096

#: Joint and pose ids are stable handles a requirement, a tool call and a
#: reviewer finding all name, so they are pattern-checked like constraint ids.
JOINT_ID_PATTERN: Final[str] = r"^[A-Za-z][A-Za-z0-9._-]{0,63}$"
_ID_RE: Final[re.Pattern[str]] = re.compile(JOINT_ID_PATTERN)

#: The 8C anchor grammar, compiled from the constraint set's own pattern so the
#: two surfaces cannot drift (``KINEMATICS.md`` §1: "no new naming scheme").
_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(ANCHOR_PATTERN)

#: The only ``zero`` value in the 9A contract (§1): the authored positions ARE
#: parameter zero. A numeric zero offset is a 9C amendment candidate.
ZERO_AS_BUILT: Final[str] = "as_built"

_JOINT_ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "kind",
        "parent",
        "child",
        "limits",
        "zero",
        "provenance",
        "note",
        "withdrawn",
        "withdrawn_reason",
    }
)
_POSE_ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    {"id", "joints", "provenance", "note", "withdrawn", "withdrawn_reason"}
)
#: Fields every motion-check kind shares; the per-kind extras are in
#: :data:`_MOTION_CHECK_KIND_FIELDS` so a ``reach`` entry smuggling ``min_mm``
#: (or a sweep entry smuggling a target) is refused by name, never ignored.
_MOTION_CHECK_BASE_FIELDS: Final[frozenset[str]] = frozenset(
    {"id", "kind", "sweep", "samples", "provenance", "note", "withdrawn", "withdrawn_reason"}
)
#: ``kind -> (allowed extra fields, required extra fields)`` per §4.
_MOTION_CHECK_KIND_FIELDS: Final[Mapping[str, tuple[frozenset[str], frozenset[str]]]] = {
    "sweep_clearance": (frozenset({"a", "b", "min_mm"}), frozenset({"a", "b", "min_mm"})),
    "sweep_no_interference": (frozenset({"a", "b"}), frozenset({"a", "b"})),
    "reach": (
        frozenset({"anchor", "target_point_mm", "tol_mm"}),
        frozenset({"anchor", "target_point_mm", "tol_mm"}),
    ),
}

JointRefusal = Literal["invalid_joint", "unknown_joint", "cyclic_joint_graph"]
PoseRefusal = Literal["invalid_pose", "unknown_pose"]
MotionCheckRefusal = Literal["invalid_motion_check", "unknown_motion_check"]
ChangeKind = Literal["declare", "update", "withdraw"]


class JointError(ValidationError):
    """A joint write was refused; ``reason`` is the stable machine token.

    ``invalid_joint`` covers every malformed or dishonest entry (unknown kind,
    slash-bearing anchor, wrong limit shape, absent provenance, a second
    parent for a part); ``cyclic_joint_graph`` is a declaration that would
    close a cycle over parts, with the cycle named in the message;
    ``unknown_joint`` is a patch or withdrawal naming an id the set does not
    carry. Nothing is ever written on any of them.
    """

    def __init__(self, message: str, *, reason: JointRefusal = "invalid_joint") -> None:
        super().__init__(message, kind="contract")
        self.reason: JointRefusal = reason


class PoseError(ValidationError):
    """A pose write was refused; ``reason`` is the stable machine token.

    ``invalid_pose`` covers every malformed or dishonest entry, including a
    declaration binding a joint id the joint set does not currently carry
    active (``KINEMATICS.md`` §3 — ``orphaned_pose`` is the *evaluation* state
    for poses whose joints are withdrawn later, never a declaration outcome);
    ``unknown_pose`` is a patch or withdrawal naming an undeclared pose id.
    """

    def __init__(self, message: str, *, reason: PoseRefusal = "invalid_pose") -> None:
        super().__init__(message, kind="contract")
        self.reason: PoseRefusal = reason


class MotionCheckError(ValidationError):
    """A motion-check write was refused; ``reason`` is the stable machine token.

    ``invalid_motion_check`` covers every malformed or dishonest entry —
    unknown kind, slash-bearing anchor, a sweep over an undeclared/withdrawn/
    zero-scalar-DOF joint, absent provenance, and the §4 grid-total cap (the
    refusal message names the computed ``samples ** n_joints`` total);
    ``unknown_motion_check`` is a patch or withdrawal naming an id the set
    does not carry. Nothing is ever written on any of them.
    """

    def __init__(
        self, message: str, *, reason: MotionCheckRefusal = "invalid_motion_check"
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason: MotionCheckRefusal = reason


# --------------------------------------------------------------------------
# anchors: the 8C grammar, refusing under each set's own token


def _parse_anchor(
    label: str, text: JSONValue, *, field: str, refuse: Callable[[str], ValidationError]
) -> Anchor:
    """The one anchor parse both kinematic sets share (see the public twins)."""
    if not isinstance(text, str):
        raise refuse(f"{label}: anchor {field} must be a string (part[:selector])")
    if "/" in text:
        raise refuse(
            f"{label}: anchor {field}={text!r} contains a slash — kinematic anchors "
            f"use the 8C 'part{ANCHOR_SEPARATOR}selector' grammar, not the cross-part "
            "'part/selector' selector form (KINEMATICS.md §1)"
        )
    if not _ANCHOR_RE.match(text):
        raise refuse(
            f"{label}: anchor {field}={text!r} must be 'part' or "
            f"'part{ANCHOR_SEPARATOR}selector' (matching {ANCHOR_PATTERN})"
        )
    part, separator, selector = text.partition(ANCHOR_SEPARATOR)
    return Anchor(text=text, part=part, selector=selector if separator else WHOLE_PART_SELECTOR)


def parse_joint_anchor(joint_id: str, text: JSONValue, *, field: str) -> Anchor:
    """Parse ``part[:selector]`` under EXACTLY the 8C anchor grammar (§1).

    Structural only, like the 8C parse: whether the part has a current build
    or the selector resolves to frame-defining geometry is an *evaluation*
    question with its own named unresolvable states. A slash anywhere in the
    anchor is refused explicitly and first: ``"<part>/<selector>"`` is the
    script-contract §7 cross-part selector form, and an anchor already knows
    which part it means — accepting it would invite two grammars for one
    string (the same rationale the 8C module records for its separator).
    """
    return _parse_anchor(f"joint {joint_id}", text, field=field, refuse=JointError)


def parse_check_anchor(check_id: str, text: JSONValue, *, field: str) -> Anchor:
    """:func:`parse_joint_anchor`'s motion-check twin (§4: same grammar, same
    slash refusal, this set's own ``invalid_motion_check`` token)."""
    return _parse_anchor(f"motion check {check_id}", text, field=field, refuse=MotionCheckError)


# --------------------------------------------------------------------------
# provenance: the 8C compulsion, shared by both sets


@dataclass(frozen=True)
class KinematicProvenance:
    """Why this joint or pose is claimed intended — a requirement, or an assumption.

    The ``VALIDATION.md`` §2 taxonomy applied to motion (``KINEMATICS.md``
    §1/§3): either the entry traces to a ledger requirement id, or the model
    supplied it and must say why. There is no third state, and the absence of
    both is a refusal rather than a default. Mirrors the 8C
    ``ConstraintProvenance`` deliberately — one honesty rule, restated under
    this set's own refusal tokens so a joint refusal never spells "constraint".
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
    def from_json(
        cls,
        label: str,
        data: JSONValue | None,
        *,
        refuse: Callable[[str], ValidationError],
    ) -> KinematicProvenance:
        if not isinstance(data, dict):
            raise refuse(
                f"{label}: provenance is required — cite a requirement "
                '({"requirement": "r-3"}) or declare an assumption '
                '({"assumed": true, "reason": "…"}) (KINEMATICS.md §1)'
            )
        raw = cast("Mapping[str, JSONValue]", data)
        unknown = sorted(set(raw) - {"requirement", "assumed", "reason"})
        if unknown:
            raise refuse(f"{label}: unknown provenance field(s) {', '.join(unknown)}")
        requirement = raw.get("requirement")
        assumed = raw.get("assumed", False)
        reason = raw.get("reason")
        malformed = not isinstance(requirement, str) or not requirement.strip()
        if requirement is not None and malformed:
            raise refuse(f"{label}: provenance.requirement must be a requirement id")
        if not isinstance(assumed, bool):
            raise refuse(f"{label}: provenance.assumed must be a boolean")
        if reason is not None and not isinstance(reason, str):
            raise refuse(f"{label}: provenance.reason must be a string")
        provenance = cls(
            requirement=requirement if isinstance(requirement, str) else None,
            assumed=assumed,
            reason=reason if isinstance(reason, str) and reason.strip() else None,
        )
        return provenance.validated(label, refuse=refuse)

    def validated(
        self, label: str, *, refuse: Callable[[str], ValidationError]
    ) -> KinematicProvenance:
        """Enforce the compulsion (raises the set's refusal, never repairs)."""
        if self.requirement is not None and self.assumed:
            raise refuse(
                f"{label}: provenance is either a cited requirement or an assumption, "
                "not both — an assumed claim a requirement already demands is not an "
                "assumption"
            )
        if self.requirement is None and not self.assumed:
            raise refuse(
                f"{label}: provenance must cite a requirement id or set "
                '"assumed": true with a reason (KINEMATICS.md §1) — travel limits and '
                "parameter bindings are interpretations of intent, so they say whose"
            )
        if self.assumed and self.reason is None:
            raise refuse(
                f"{label}: an assumed entry requires a reason "
                "(why is this motion believed to be intended?)"
            )
        return self


# --------------------------------------------------------------------------
# limits


@dataclass(frozen=True)
class LimitPair:
    """One declared travel range: ``min < max``, in the kind's own unit (§1)."""

    min: float
    max: float

    def to_json(self) -> dict[str, JSONValue]:
        return {"min": self.min, "max": self.max}

    @classmethod
    def from_json(cls, joint_id: str, data: JSONValue, *, axis: str) -> LimitPair:
        if not isinstance(data, dict):
            raise JointError(f'joint {joint_id}: {axis} must be a {{"min": …, "max": …}} pair')
        raw = cast("Mapping[str, JSONValue]", data)
        unknown = sorted(set(raw) - {"min", "max"})
        if unknown:
            raise JointError(f"joint {joint_id}: {axis} does not take {', '.join(unknown)}")
        values: dict[str, float] = {}
        for name in ("min", "max"):
            value = raw.get(name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise JointError(f"joint {joint_id}: {axis}.{name} must be a number")
            values[name] = float(value)
        if values["min"] >= values["max"]:
            raise JointError(
                f"joint {joint_id}: {axis} must satisfy min < max "
                f"(got {values['min']} .. {values['max']}) — a joint with no travel "
                "is declared 'fixed', not limited to a point"
            )
        return cls(min=values["min"], max=values["max"])


def _parse_limits(
    joint_id: str, kind: str, data: Mapping[str, JSONValue]
) -> tuple[LimitPair | None, LimitPair | None, LimitPair | None]:
    """``(limits, rotation, translation)`` per the §1 kind table, refused by name.

    ``fixed`` has 0 DOF, so limits do not apply and supplying them is refused
    rather than ignored; ``revolute``/``prismatic`` carry one pair (degrees /
    mm); ``cylindrical`` carries exactly the two named pairs. Limits are
    required wherever a DOF exists — an unlimited joint would be a claim about
    travel with no stated intent, which is what provenance-compelled limits
    exist to prevent.
    """
    raw = data.get("limits")
    if kind == "fixed":
        if raw is not None:
            raise JointError(f"joint {joint_id}: kind 'fixed' has 0 DOF — limits do not apply")
        return None, None, None
    if kind == "cylindrical":
        if not isinstance(raw, dict):
            raise JointError(
                f"joint {joint_id}: kind 'cylindrical' requires limits with two pairs: "
                '{"rotation": {"min": …, "max": …}, "translation": {"min": …, "max": …}}'
            )
        pairs = cast("Mapping[str, JSONValue]", raw)
        unknown = sorted(set(pairs) - {"rotation", "translation"})
        if unknown:
            raise JointError(
                f"joint {joint_id}: cylindrical limits do not take {', '.join(unknown)} "
                "(they take: rotation, translation)"
            )
        missing = [name for name in ("rotation", "translation") if name not in pairs]
        if missing:
            raise JointError(f"joint {joint_id}: cylindrical limits require {', '.join(missing)}")
        rotation = LimitPair.from_json(joint_id, pairs["rotation"], axis="limits.rotation")
        translation = LimitPair.from_json(joint_id, pairs["translation"], axis="limits.translation")
        return None, rotation, translation
    # revolute (degrees) / prismatic (mm): one pair.
    if raw is None:
        unit = "degrees" if kind == "revolute" else "mm"
        raise JointError(
            f'joint {joint_id}: kind {kind!r} requires limits ({{"min": …, "max": …}} in {unit})'
        )
    return LimitPair.from_json(joint_id, raw, axis="limits"), None, None


# --------------------------------------------------------------------------
# joint entries


@dataclass(frozen=True)
class JointEntry:
    """One declared joint, exactly the ``KINEMATICS.md`` §1 entry shape."""

    id: str
    kind: str
    parent: str
    child: str
    provenance: KinematicProvenance
    #: Single-DOF travel (``revolute`` degrees / ``prismatic`` mm); ``None``
    #: for ``fixed`` (0 DOF) and ``cylindrical`` (which carries two pairs).
    limits: LimitPair | None = None
    rotation: LimitPair | None = None
    translation: LimitPair | None = None
    #: §1: the authored positions ARE parameter zero — the only value in 9A.
    zero: str = ZERO_AS_BUILT
    note: str | None = None
    #: A withdrawn entry stays in every later generation with its reason:
    #: withdrawal is a new generation, never an erasure, so what a project
    #: *stopped* claiming stays inspectable (the 8C rule, §1).
    withdrawn: bool = False
    withdrawn_reason: str | None = None

    @property
    def anchors(self) -> tuple[Anchor, Anchor]:
        return (
            parse_joint_anchor(self.id, self.parent, field="parent"),
            parse_joint_anchor(self.id, self.child, field="child"),
        )

    @property
    def parts(self) -> tuple[str, ...]:
        """The part names this joint relates, deduplicated in parent/child order."""
        names = [anchor.part for anchor in self.anchors]
        return tuple(dict.fromkeys(names))

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "kind": self.kind,
            "parent": self.parent,
            "child": self.child,
        }
        if self.limits is not None:
            out["limits"] = cast("JSONValue", self.limits.to_json())
        if self.rotation is not None and self.translation is not None:
            out["limits"] = {
                "rotation": cast("JSONValue", self.rotation.to_json()),
                "translation": cast("JSONValue", self.translation.to_json()),
            }
        out["zero"] = self.zero
        out["provenance"] = cast("JSONValue", self.provenance.to_json())
        if self.note is not None:
            out["note"] = self.note
        if self.withdrawn:
            out["withdrawn"] = True
            out["withdrawn_reason"] = self.withdrawn_reason
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> JointEntry:
        """Build a validated entry from tool arguments or a stored generation."""
        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not _ID_RE.match(raw_id):
            raise JointError(f"joint id {raw_id!r} must match {JOINT_ID_PATTERN}")
        unknown = sorted(set(data) - _JOINT_ENTRY_FIELDS)
        if unknown:
            raise JointError(
                f"joint {raw_id}: unknown field(s) {', '.join(unknown)} "
                f"(a joint entry takes: {', '.join(sorted(_JOINT_ENTRY_FIELDS))})"
            )
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in JOINT_KINDS:
            raise JointError(
                f"joint {raw_id}: kind must be one of {', '.join(JOINT_KINDS)}, got {kind!r}"
            )
        parent = data.get("parent")
        child = data.get("child")
        parse_joint_anchor(raw_id, parent, field="parent")
        parse_joint_anchor(raw_id, child, field="child")
        limits, rotation, translation = _parse_limits(raw_id, kind, data)
        zero = data.get("zero", ZERO_AS_BUILT)
        if zero != ZERO_AS_BUILT:
            raise JointError(
                f"joint {raw_id}: zero must be {ZERO_AS_BUILT!r}, got {zero!r} — the only "
                "value in the 9A contract; a numeric zero offset is a 9C amendment "
                "candidate (KINEMATICS.md §1)"
            )
        note = data.get("note")
        if note is not None and not isinstance(note, str):
            raise JointError(f"joint {raw_id}: note must be a string")
        withdrawn = data.get("withdrawn", False)
        if not isinstance(withdrawn, bool):
            raise JointError(f"joint {raw_id}: withdrawn must be a boolean")
        withdrawn_reason = data.get("withdrawn_reason")
        if withdrawn_reason is not None and not isinstance(withdrawn_reason, str):
            raise JointError(f"joint {raw_id}: withdrawn_reason must be a string")
        if withdrawn and not (withdrawn_reason or "").strip():
            raise JointError(f"joint {raw_id}: a withdrawal must record a reason")
        return cls(
            id=raw_id,
            kind=kind,
            parent=cast("str", parent),
            child=cast("str", child),
            provenance=KinematicProvenance.from_json(
                f"joint {raw_id}", data.get("provenance"), refuse=JointError
            ),
            limits=limits,
            rotation=rotation,
            translation=translation,
            zero=ZERO_AS_BUILT,
            note=note,
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason if withdrawn else None,
        )


def _validate_forest(entries: tuple[JointEntry, ...]) -> None:
    """Refuse any active edge set that is not a forest over parts (§1).

    Two named refusals, checked at every write rather than at evaluation:

    * a part riding two joints (``invalid_joint`` naming the joint it already
      rides) — forward kinematics composes root-to-leaf, and a part with two
      parents has no single composition;
    * a cycle over parts (``cyclic_joint_graph`` with the cycle named) —
      closed loops are expressed as an open chain plus a pose-bound 8C
      constraint, measured rather than solved.

    Withdrawn entries contribute no edges: never evaluated, per the 8C rule.
    """
    parent_of: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if entry.withdrawn:
            continue
        parent_part, child_part = entry.parts[0], entry.anchors[1].part
        if parent_part == child_part:
            raise JointError(
                f"joint {entry.id}: cyclic joint graph — {parent_part} -> {parent_part} "
                "(a joint cannot relate a part to itself)",
                reason="cyclic_joint_graph",
            )
        prior = parent_of.get(child_part)
        if prior is not None:
            raise JointError(
                f"joint {entry.id}: part {child_part!r} already rides joint {prior[1]!r} — "
                "the joint graph is a forest, one parent joint per part "
                "(KINEMATICS.md §1)"
            )
        parent_of[child_part] = (parent_part, entry.id)
    for start in parent_of:
        path: list[str] = [start]
        joints: list[str] = []
        seen = {start}
        current = start
        while current in parent_of:
            parent_part, joint_id = parent_of[current]
            joints.append(joint_id)
            path.append(parent_part)
            if parent_part in seen:
                cycle = " -> ".join(path[path.index(parent_part) :])
                raise JointError(
                    f"cyclic joint graph: {cycle} (via joints {', '.join(joints)}) — "
                    "declare closed loops as an open chain plus a pose-bound 8C "
                    "constraint (KINEMATICS.md §1)",
                    reason="cyclic_joint_graph",
                )
            seen.add(parent_part)
            current = parent_part


# --------------------------------------------------------------------------
# pose entries


@dataclass(frozen=True)
class PoseEntry:
    """One named pose, exactly the ``KINEMATICS.md`` §3 entry shape.

    ``joints`` binds parameter values by joint id; joints omitted take their
    zero value, so the empty binding is legal and means "everything as built".
    Validation here is structural only: whether the bound joints still exist
    unwithdrawn is checked at *declaration* against the live joint set (the
    set's write path), never re-checked on load — a stored pose whose joint
    was withdrawn later is ``orphaned_pose`` at evaluation, not a corrupt
    generation.
    """

    id: str
    joints: Mapping[str, float]
    provenance: KinematicProvenance
    note: str | None = None
    withdrawn: bool = False
    withdrawn_reason: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "joints": {name: self.joints[name] for name in sorted(self.joints)},
        }
        out["provenance"] = cast("JSONValue", self.provenance.to_json())
        if self.note is not None:
            out["note"] = self.note
        if self.withdrawn:
            out["withdrawn"] = True
            out["withdrawn_reason"] = self.withdrawn_reason
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> PoseEntry:
        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not _ID_RE.match(raw_id):
            raise PoseError(f"pose id {raw_id!r} must match {JOINT_ID_PATTERN}")
        unknown = sorted(set(data) - _POSE_ENTRY_FIELDS)
        if unknown:
            raise PoseError(
                f"pose {raw_id}: unknown field(s) {', '.join(unknown)} "
                f"(a pose entry takes: {', '.join(sorted(_POSE_ENTRY_FIELDS))})"
            )
        raw_joints = data.get("joints")
        if not isinstance(raw_joints, dict):
            raise PoseError(
                f"pose {raw_id}: joints must be an object of {{joint_id: value}} "
                "(joints omitted take their zero value, KINEMATICS.md §3)"
            )
        joints: dict[str, float] = {}
        for name, value in cast("Mapping[str, JSONValue]", raw_joints).items():
            if not _ID_RE.match(name):
                raise PoseError(f"pose {raw_id}: joint id {name!r} must match {JOINT_ID_PATTERN}")
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise PoseError(f"pose {raw_id}: value for joint {name!r} must be a number")
            joints[name] = float(value)
        note = data.get("note")
        if note is not None and not isinstance(note, str):
            raise PoseError(f"pose {raw_id}: note must be a string")
        withdrawn = data.get("withdrawn", False)
        if not isinstance(withdrawn, bool):
            raise PoseError(f"pose {raw_id}: withdrawn must be a boolean")
        withdrawn_reason = data.get("withdrawn_reason")
        if withdrawn_reason is not None and not isinstance(withdrawn_reason, str):
            raise PoseError(f"pose {raw_id}: withdrawn_reason must be a string")
        if withdrawn and not (withdrawn_reason or "").strip():
            raise PoseError(f"pose {raw_id}: a withdrawal must record a reason")
        return cls(
            id=raw_id,
            joints=joints,
            provenance=KinematicProvenance.from_json(
                f"pose {raw_id}", data.get("provenance"), refuse=PoseError
            ),
            note=note,
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason if withdrawn else None,
        )


# --------------------------------------------------------------------------
# motion-check entries (Stage 9B, §4)


@dataclass(frozen=True)
class SweepRange:
    """One joint's declared sweep interval, the §4 ``{"from": …, "to": …}`` pair.

    ``start < stop`` in the joint kind's own unit (degrees / mm) — a
    zero-width "sweep" is a pose wearing a sweep's name and is refused, the
    :class:`LimitPair` rule restated. Whether the interval sits inside the
    joint's declared limits is deliberately an *evaluation* question: limits
    can be revised after declaration, and the evaluator refuses an
    out-of-limits sample by geom's own ``joint_limit_exceeded`` name rather
    than this module re-checking a moving target.
    """

    start: float
    stop: float

    def to_json(self) -> dict[str, JSONValue]:
        return {"from": self.start, "to": self.stop}

    @classmethod
    def from_json(cls, check_id: str, joint_id: str, data: JSONValue) -> SweepRange:
        if not isinstance(data, dict):
            raise MotionCheckError(
                f"motion check {check_id}: sweep[{joint_id!r}] must be a "
                '{"from": …, "to": …} range'
            )
        raw = cast("Mapping[str, JSONValue]", data)
        unknown = sorted(set(raw) - {"from", "to"})
        if unknown:
            raise MotionCheckError(
                f"motion check {check_id}: sweep[{joint_id!r}] does not take "
                f"{', '.join(unknown)} (it takes: from, to)"
            )
        values: dict[str, float] = {}
        for name in ("from", "to"):
            value = raw.get(name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise MotionCheckError(
                    f"motion check {check_id}: sweep[{joint_id!r}].{name} must be a number"
                )
            values[name] = float(value)
        if values["from"] >= values["to"]:
            raise MotionCheckError(
                f"motion check {check_id}: sweep[{joint_id!r}] must satisfy from < to "
                f"(got {values['from']} .. {values['to']}) — a zero-width sweep is a "
                "pose, and poses have their own set (KINEMATICS.md §3/§4)"
            )
        return cls(start=values["from"], stop=values["to"])


@dataclass(frozen=True)
class MotionCheckEntry:
    """One declared motion check, exactly the ``KINEMATICS.md`` §4 entry shape.

    ``sweep`` maps joint ids to :class:`SweepRange`; ``samples`` is the
    PER-AXIS request (endpoints inclusive), and :attr:`grid_total` is the
    number a multi-joint check actually evaluates — the quantity the §4 cap
    binds and every result restates as ``samples_evaluated``. The anchor
    fields are per kind: ``a``/``b`` (plus ``min_mm`` for ``sweep_clearance``)
    on the universal kinds, ``anchor``/``target_point_mm``/``tol_mm`` on
    ``reach``. Validation here is structural plus the statically-knowable
    refusals; whether the anchors resolve and the swept joints still exist is
    the evaluator's question, with its own named unresolvable states.
    """

    id: str
    kind: str
    sweep: Mapping[str, SweepRange]
    provenance: KinematicProvenance
    samples: int = SWEEP_SAMPLES_DEFAULT
    a: str | None = None
    b: str | None = None
    min_mm: float | None = None
    anchor: str | None = None
    target_point_mm: tuple[float, float, float] | None = None
    tol_mm: float | None = None
    note: str | None = None
    withdrawn: bool = False
    withdrawn_reason: str | None = None

    @property
    def grid_total(self) -> int:
        """The computed grid product ``samples ** n_joints`` (§4: the capped total)."""
        return self.samples ** len(self.sweep)

    @property
    def anchor_fields(self) -> tuple[tuple[str, Anchor], ...]:
        """``(field_name, parsed anchor)`` per anchor this kind declares."""
        names = ("anchor",) if self.kind == "reach" else ("a", "b")
        out: list[tuple[str, Anchor]] = []
        for name in names:
            text = getattr(self, name)
            out.append((name, parse_check_anchor(self.id, text, field=name)))
        return tuple(out)

    @property
    def parts(self) -> tuple[str, ...]:
        """The part names this check measures, deduplicated in field order."""
        names = [anchor.part for _, anchor in self.anchor_fields]
        return tuple(dict.fromkeys(names))

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {"id": self.id, "kind": self.kind}
        for name in ("a", "b", "anchor"):
            value = getattr(self, name)
            if value is not None:
                out[name] = cast("JSONValue", value)
        out["sweep"] = {
            joint_id: cast("JSONValue", self.sweep[joint_id].to_json())
            for joint_id in sorted(self.sweep)
        }
        if self.min_mm is not None:
            out["min_mm"] = self.min_mm
        if self.target_point_mm is not None:
            out["target_point_mm"] = list(self.target_point_mm)
        if self.tol_mm is not None:
            out["tol_mm"] = self.tol_mm
        out["samples"] = self.samples
        out["provenance"] = cast("JSONValue", self.provenance.to_json())
        if self.note is not None:
            out["note"] = self.note
        if self.withdrawn:
            out["withdrawn"] = True
            out["withdrawn_reason"] = self.withdrawn_reason
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> MotionCheckEntry:
        """Build a validated entry from tool arguments or a stored generation."""
        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not _ID_RE.match(raw_id):
            raise MotionCheckError(f"motion check id {raw_id!r} must match {JOINT_ID_PATTERN}")
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in MOTION_CHECK_KINDS:
            raise MotionCheckError(
                f"motion check {raw_id}: kind must be one of "
                f"{', '.join(MOTION_CHECK_KINDS)}, got {kind!r}"
            )
        allowed_extra, required_extra = _MOTION_CHECK_KIND_FIELDS[kind]
        allowed = _MOTION_CHECK_BASE_FIELDS | allowed_extra
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise MotionCheckError(
                f"motion check {raw_id}: field(s) {', '.join(unknown)} do not belong to "
                f"kind {kind!r} (it takes: {', '.join(sorted(allowed))})"
            )
        missing = sorted(name for name in required_extra if data.get(name) is None)
        if missing:
            raise MotionCheckError(
                f"motion check {raw_id}: kind {kind!r} requires {', '.join(missing)} "
                "(KINEMATICS.md §4)"
            )
        for field_name in allowed_extra & {"a", "b", "anchor"}:
            parse_check_anchor(raw_id, data.get(field_name), field=field_name)
        raw_sweep = data.get("sweep")
        if not isinstance(raw_sweep, dict) or not raw_sweep:
            raise MotionCheckError(
                f"motion check {raw_id}: sweep must be a non-empty object of "
                '{joint_id: {"from": …, "to": …}} (KINEMATICS.md §4)'
            )
        sweep: dict[str, SweepRange] = {}
        for joint_id, value in cast("Mapping[str, JSONValue]", raw_sweep).items():
            if not _ID_RE.match(joint_id):
                raise MotionCheckError(
                    f"motion check {raw_id}: sweep joint id {joint_id!r} must match "
                    f"{JOINT_ID_PATTERN}"
                )
            sweep[joint_id] = SweepRange.from_json(raw_id, joint_id, value)
        raw_samples = data.get("samples", SWEEP_SAMPLES_DEFAULT)
        if isinstance(raw_samples, bool) or not isinstance(raw_samples, int):
            raise MotionCheckError(
                f"motion check {raw_id}: samples must be an integer (the per-axis count)"
            )
        if raw_samples < 2:
            raise MotionCheckError(
                f"motion check {raw_id}: samples must be at least 2 — endpoints are "
                "inclusive (KINEMATICS.md §4), so 1 sample is a pose, not a sweep"
            )
        # THE CAP IS ON THE COMPUTED GRID TOTAL (§4): refuse on the product,
        # naming it — a per-axis count under the cap proves nothing.
        total = raw_samples ** len(sweep)
        if total > SWEEP_SAMPLES_MAX:
            raise MotionCheckError(
                f"motion check {raw_id}: sweep grid is {raw_samples}^{len(sweep)} = "
                f"{total} samples, exceeding SWEEP_SAMPLES_MAX ({SWEEP_SAMPLES_MAX}) — "
                "the cap is on the computed grid total (KINEMATICS.md §4)"
            )
        min_mm = _opt_number(raw_id, data.get("min_mm"), field="min_mm")
        if min_mm is not None and min_mm < 0.0:
            raise MotionCheckError(f"motion check {raw_id}: min_mm must be >= 0")
        tol_mm = _opt_number(raw_id, data.get("tol_mm"), field="tol_mm")
        if tol_mm is not None and tol_mm <= 0.0:
            raise MotionCheckError(f"motion check {raw_id}: tol_mm must be > 0")
        target = _opt_point(raw_id, data.get("target_point_mm"))
        note = data.get("note")
        if note is not None and not isinstance(note, str):
            raise MotionCheckError(f"motion check {raw_id}: note must be a string")
        withdrawn = data.get("withdrawn", False)
        if not isinstance(withdrawn, bool):
            raise MotionCheckError(f"motion check {raw_id}: withdrawn must be a boolean")
        withdrawn_reason = data.get("withdrawn_reason")
        if withdrawn_reason is not None and not isinstance(withdrawn_reason, str):
            raise MotionCheckError(f"motion check {raw_id}: withdrawn_reason must be a string")
        if withdrawn and not (withdrawn_reason or "").strip():
            raise MotionCheckError(f"motion check {raw_id}: a withdrawal must record a reason")
        return cls(
            id=raw_id,
            kind=kind,
            sweep=sweep,
            provenance=KinematicProvenance.from_json(
                f"motion check {raw_id}", data.get("provenance"), refuse=MotionCheckError
            ),
            samples=raw_samples,
            a=cast("str | None", data.get("a")),
            b=cast("str | None", data.get("b")),
            min_mm=min_mm,
            anchor=cast("str | None", data.get("anchor")),
            target_point_mm=target,
            tol_mm=tol_mm,
            note=note,
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason if withdrawn else None,
        )


def _opt_number(check_id: str, value: JSONValue | None, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MotionCheckError(f"motion check {check_id}: {field} must be a number")
    return float(value)


def _opt_point(check_id: str, value: JSONValue | None) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(cast("list[JSONValue]", value)) != 3:
        raise MotionCheckError(
            f"motion check {check_id}: target_point_mm must be [x, y, z] in world mm"
        )
    out: list[float] = []
    for axis, item in zip("xyz", cast("list[JSONValue]", value), strict=True):
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise MotionCheckError(
                f"motion check {check_id}: target_point_mm.{axis} must be a number"
            )
        out.append(float(item))
    return (out[0], out[1], out[2])


# --------------------------------------------------------------------------
# generations (the ledger shape, thrice — one per set)


@dataclass(frozen=True)
class JointChange:
    """What produced one joint-set generation: the act, the entry, the reason."""

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
    def from_json(cls, data: JSONValue | None) -> JointChange | None:
        parsed = _change_fields(data)
        if parsed is None:
            return None
        kind, entry_id, reason, patch = parsed
        return cls(kind=kind, id=entry_id, reason=reason, patch=patch)


@dataclass(frozen=True)
class PoseChange:
    """What produced one pose-set generation: the act, the entry, the reason."""

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
    def from_json(cls, data: JSONValue | None) -> PoseChange | None:
        parsed = _change_fields(data)
        if parsed is None:
            return None
        kind, entry_id, reason, patch = parsed
        return cls(kind=kind, id=entry_id, reason=reason, patch=patch)


@dataclass(frozen=True)
class MotionCheckChange:
    """What produced one motion-check-set generation: the act, the entry, the reason."""

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
    def from_json(cls, data: JSONValue | None) -> MotionCheckChange | None:
        parsed = _change_fields(data)
        if parsed is None:
            return None
        kind, entry_id, reason, patch = parsed
        return cls(kind=kind, id=entry_id, reason=reason, patch=patch)


def _change_fields(
    data: JSONValue | None,
) -> tuple[ChangeKind, str, str | None, Mapping[str, JSONValue] | None] | None:
    if not isinstance(data, dict):
        return None
    raw = cast("Mapping[str, JSONValue]", data)
    kind = raw.get("kind")
    entry_id = raw.get("id")
    if kind not in ("declare", "update", "withdraw") or not isinstance(entry_id, str):
        return None
    reason = raw.get("reason")
    patch = raw.get("patch")
    return (
        kind,
        entry_id,
        reason if isinstance(reason, str) else None,
        cast("Mapping[str, JSONValue]", patch) if isinstance(patch, dict) else None,
    )


@dataclass(frozen=True)
class JointState:
    """One immutable joint-set generation."""

    generation: int
    entries: tuple[JointEntry, ...]
    blob: str | None
    parent: str | None = None
    change: JointChange | None = None

    @property
    def artifact_ref(self) -> str | None:
        """``artifact:joints:sha256:…`` of this generation (None when empty)."""
        if self.blob is None:
            return None
        return make_artifact_ref(JOINT_ARTIFACT_KIND, self.blob)

    @property
    def by_id(self) -> dict[str, JointEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def active(self) -> tuple[JointEntry, ...]:
        """Entries still claimed (withdrawn ones stay stored, never evaluated)."""
        return tuple(entry for entry in self.entries if not entry.withdrawn)

    @property
    def parts(self) -> tuple[str, ...]:
        """Every part an active joint relates, lexically sorted — the forest's
        parts, which is exactly the set whose rebuilds restale the motion
        projection (``KINEMATICS.md`` §2)."""
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
        """The projection every joint reader shares."""
        return {
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "change": None if self.change is None else cast("JSONValue", self.change.to_json()),
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> JointState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise JointError("joint-set generation must be an integer")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise JointError("joint-set entries must be an array")
        entries = tuple(
            JointEntry.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_entries)
            if isinstance(item, dict)
        )
        parent = data.get("parent")
        return cls(
            generation=generation,
            entries=entries,
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
            change=JointChange.from_json(data.get("change")),
        )


@dataclass(frozen=True)
class PoseState:
    """One immutable pose-set generation."""

    generation: int
    entries: tuple[PoseEntry, ...]
    blob: str | None
    parent: str | None = None
    change: PoseChange | None = None

    @property
    def artifact_ref(self) -> str | None:
        """``artifact:poses:sha256:…`` of this generation (None when empty)."""
        if self.blob is None:
            return None
        return make_artifact_ref(POSE_ARTIFACT_KIND, self.blob)

    @property
    def by_id(self) -> dict[str, PoseEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def active(self) -> tuple[PoseEntry, ...]:
        """Entries still claimed (withdrawn ones stay stored, never evaluated)."""
        return tuple(entry for entry in self.entries if not entry.withdrawn)

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "change": None if self.change is None else self.change.to_json(),
            "entries": [entry.to_json() for entry in self.entries],
        }

    def to_json(self) -> dict[str, JSONValue]:
        """The projection every pose reader shares."""
        return {
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "change": None if self.change is None else cast("JSONValue", self.change.to_json()),
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> PoseState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise PoseError("pose-set generation must be an integer")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise PoseError("pose-set entries must be an array")
        entries = tuple(
            PoseEntry.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_entries)
            if isinstance(item, dict)
        )
        parent = data.get("parent")
        return cls(
            generation=generation,
            entries=entries,
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
            change=PoseChange.from_json(data.get("change")),
        )


@dataclass(frozen=True)
class MotionCheckState:
    """One immutable motion-check-set generation."""

    generation: int
    entries: tuple[MotionCheckEntry, ...]
    blob: str | None
    parent: str | None = None
    change: MotionCheckChange | None = None

    @property
    def artifact_ref(self) -> str | None:
        """``artifact:motion-checks:sha256:…`` of this generation (None when empty)."""
        if self.blob is None:
            return None
        return make_artifact_ref(MOTION_CHECK_ARTIFACT_KIND, self.blob)

    @property
    def by_id(self) -> dict[str, MotionCheckEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def active(self) -> tuple[MotionCheckEntry, ...]:
        """Entries still claimed (withdrawn ones stay stored, never evaluated)."""
        return tuple(entry for entry in self.entries if not entry.withdrawn)

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "change": None if self.change is None else self.change.to_json(),
            "entries": [entry.to_json() for entry in self.entries],
        }

    def to_json(self) -> dict[str, JSONValue]:
        """The projection every motion-check reader shares."""
        return {
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "change": None if self.change is None else cast("JSONValue", self.change.to_json()),
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> MotionCheckState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise MotionCheckError("motion-check-set generation must be an integer")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise MotionCheckError("motion-check-set entries must be an array")
        entries = tuple(
            MotionCheckEntry.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_entries)
            if isinstance(item, dict)
        )
        parent = data.get("parent")
        return cls(
            generation=generation,
            entries=entries,
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
            change=MotionCheckChange.from_json(data.get("change")),
        )


_EMPTY_JOINTS: Final[JointState] = JointState(
    generation=0, entries=(), blob=None, parent=None, change=None
)
_EMPTY_POSES: Final[PoseState] = PoseState(
    generation=0, entries=(), blob=None, parent=None, change=None
)
_EMPTY_CHECKS: Final[MotionCheckState] = MotionCheckState(
    generation=0, entries=(), blob=None, parent=None, change=None
)


class JointSet:
    """Declare / update / withdraw joints as immutable generations.

    Engine-side and model-writable on the recorded 8C quartet rationale
    (``KINEMATICS.md`` §6): declaring is cheap, reversible, and measured
    against geometry the model didn't choose, so compelled honesty beats
    gatekeeping. What it cannot do is erase — every act is a new generation
    naming its parent and its reason, published under the project-config lock
    exactly as the constraint set is.
    """

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store

    # -- reads --------------------------------------------------------------

    def state(self) -> JointState:
        """The current generation (empty generation 0 when never written)."""
        blob = self._store.blobs.read_pointer(JOINTS_POINTER)
        if blob is None:
            return _EMPTY_JOINTS
        return self._state_from_blob(blob)

    def generation(self, artifact_ref: str) -> JointState:
        """Any historical generation by its immutable artifact ref."""
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise JointError(f"joint generation {artifact_ref} is not stored")
        return self._state_from_blob(blob)

    def history(self) -> tuple[JointState, ...]:
        """Every stored generation, oldest first (the ledger replay).

        Walks the ``parent`` chain from the live pointer. A generation whose
        blob has been collected ends the walk rather than faking a gap.
        """
        chain: list[JointState] = []
        current = self.state()
        while current.blob is not None:
            chain.append(current)
            parent = current.parent
            if parent is None or not self._store.blobs.has(parent):
                break
            current = self._state_from_blob(parent)
        return tuple(reversed(chain))

    def get(self, joint_id: str) -> JointEntry:
        """One entry, or ``addressing_error`` naming the ids that do exist."""
        entries = self.state().by_id
        entry = entries.get(joint_id)
        if entry is None:
            raise AddressingError(
                f"no joint {joint_id!r} is declared",
                selector=joint_id,
                candidates=tuple(sorted(entries)),
            )
        return entry

    def _state_from_blob(self, blob: str) -> JointState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise JointError("joint-set state document is malformed")
        return JointState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    # -- writes -------------------------------------------------------------

    def declare(self, entry: Mapping[str, JSONValue], *, op_id: str | None = None) -> JointState:
        """Declare one new joint; advances one generation.

        A repeated id is refused rather than silently replaced: revising a
        claim is :meth:`update`, which records why. The candidate edge set is
        forest-checked before anything is written (§1).
        """
        parsed = JointEntry.from_json(entry)

        def apply(current: JointState) -> tuple[JointEntry, ...]:
            if parsed.id in current.by_id:
                raise JointError(
                    f"joint {parsed.id} is already declared — revise it with "
                    "update_joint(id, patch, reason) so the change records a reason"
                )
            entries = (*current.entries, parsed)
            _validate_forest(entries)
            return entries

        return self._mutate(
            JointChange(kind="declare", id=parsed.id, patch=parsed.to_json()),
            apply,
            op_id=op_id,
        )

    def update(
        self,
        joint_id: str,
        patch: Mapping[str, JSONValue],
        reason: str,
        *,
        op_id: str | None = None,
    ) -> JointState:
        """Revise one entry's declared fields; advances one generation.

        ``reason`` is compulsory and recorded on the generation. The patch is
        merged onto the stored entry and the whole result revalidated —
        including the forest check, since a re-parented joint can close a
        cycle a declaration could not.
        """
        if not reason.strip():
            raise JointError(f"joint {joint_id}: update requires a reason")
        cleaned = {name: value for name, value in patch.items() if value is not None}
        if not cleaned:
            raise JointError(f"joint {joint_id}: update patches nothing")
        if "id" in cleaned:
            raise JointError(
                f"joint {joint_id}: id is not patchable — declare a new joint and withdraw this one"
            )

        def apply(current: JointState) -> tuple[JointEntry, ...]:
            existing = _require_joint(current, joint_id)
            merged = dict(existing.to_json())
            if "kind" in cleaned and cleaned["kind"] != existing.kind:
                # A new kind takes a different limit shape; keeping the old
                # kind's limits would silently smuggle them past validation.
                merged.pop("limits", None)
            merged.update(cleaned)
            updated = JointEntry.from_json(merged)
            entries = tuple(updated if e.id == joint_id else e for e in current.entries)
            _validate_forest(entries)
            return entries

        return self._mutate(
            JointChange(
                kind="update",
                id=joint_id,
                reason=reason,
                patch=cast("Mapping[str, JSONValue]", dict(sorted(cleaned.items()))),
            ),
            apply,
            op_id=op_id,
        )

    def withdraw(self, joint_id: str, reason: str, *, op_id: str | None = None) -> JointState:
        """Stop claiming one joint; advances one generation, erases nothing.

        A pose that binds this joint is deliberately NOT touched: withdrawal
        is not a failure, and the pose becomes ``orphaned_pose`` at evaluation
        (``KINEMATICS.md`` §2/§3) rather than being erased or refused here.
        """
        if not reason.strip():
            raise JointError(f"joint {joint_id}: withdrawal requires a reason")

        def apply(current: JointState) -> tuple[JointEntry, ...]:
            existing = _require_joint(current, joint_id)
            if existing.withdrawn:
                raise JointError(f"joint {joint_id} is already withdrawn")
            updated = replace(existing, withdrawn=True, withdrawn_reason=reason)
            return tuple(updated if e.id == joint_id else e for e in current.entries)

        return self._mutate(
            JointChange(kind="withdraw", id=joint_id, reason=reason), apply, op_id=op_id
        )

    # -- the one generation-advancing path ----------------------------------

    def _mutate(
        self,
        change: JointChange,
        apply: Callable[[JointState], tuple[JointEntry, ...]],
        *,
        op_id: str | None,
    ) -> JointState:
        """Publish one new immutable generation under the project-config lock.

        With ``op_id`` the pointer flip goes through the opstore WAL and is
        idempotent on that id, exactly as the constraint set's writes are;
        without one it is a plain pointer compare-and-swap (the operator/test
        path, where there is no invocation id to be idempotent on).
        """
        if op_id is None:
            return self._publish(change, apply)
        payload: JSONValue = {"kind": "joint_write", "change": change.to_json()}
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            return self._replayed(outcome.response)
        if not isinstance(outcome, Fresh):
            raise JointError(f"joint write {op_id!r} cannot proceed: prior state {outcome!r}")
        locks = LockManager(self._store)
        try:
            with locks.holding(PROJECT_CONFIG_LOCK):
                current = self.state()
                candidate, new_blob = self._candidate(current, change, apply)
                self._store.wal.publish(
                    outcome,
                    JOINTS_POINTER,
                    current.blob,
                    new_blob,
                    intended_outcome=canonical_json(
                        {"generation": candidate.generation, "state": new_blob}
                    ),
                )
                return candidate
        except JointError:
            # Nothing was written: release the fresh opkey skeleton so a
            # corrected retry with the same invocation id is not a mismatch.
            self._store.wal.recover(outcome.op_key)
            raise

    def _publish(
        self,
        change: JointChange,
        apply: Callable[[JointState], tuple[JointEntry, ...]],
    ) -> JointState:
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            candidate, new_blob = self._candidate(current, change, apply)
            self._store.blobs.cas_swap(JOINTS_POINTER, current.blob, new_blob)
            return candidate

    def _candidate(
        self,
        current: JointState,
        change: JointChange,
        apply: Callable[[JointState], tuple[JointEntry, ...]],
    ) -> tuple[JointState, str]:
        """Compute, store and pin the next generation's document (no pointer move)."""
        entries = apply(current)
        candidate = JointState(
            generation=current.generation + 1,
            entries=entries,
            blob=None,
            parent=current.blob,
            change=change,
        )
        new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
        # Pinned, not merely pointer-protected: an older generation must stay
        # readable after the pointer has moved on, or "nothing is erased" would
        # be true only until the next GC pass (the 8C rule, verbatim).
        self._store.gc.pin(new_blob)
        if current.blob is not None:
            self._store.gc.link(new_blob, current.blob)
        return replace(candidate, blob=new_blob), new_blob

    def _replayed(self, response: str | None) -> JointState:
        """The generation a committed same-id call produced (immutable, so exact)."""
        recorded = _recorded_state(response)
        if recorded is not None and self._store.blobs.has(recorded):
            return self._state_from_blob(recorded)
        # Tombstoned replay: only the terminal state survives, so report live.
        return self.state()


class PoseSet:
    """Declare / update / withdraw named poses as immutable generations.

    Carries a :class:`JointSet` because a pose's bindings are claims about
    declared joints: an unknown or already-withdrawn joint id is refused at
    declaration (``invalid_pose``), read under the same project-config lock
    the write holds so a concurrent withdrawal cannot race the check. A joint
    withdrawn *after* declaration orphans the pose at evaluation instead
    (``orphaned_pose``, ``KINEMATICS.md`` §2/§3) — nothing here re-refuses it.
    """

    def __init__(self, layout: ProjectLayout, store: OpStore, joints: JointSet) -> None:
        self.layout = layout
        self._store = store
        self._joints = joints

    # -- reads --------------------------------------------------------------

    def state(self) -> PoseState:
        """The current generation (empty generation 0 when never written)."""
        blob = self._store.blobs.read_pointer(POSES_POINTER)
        if blob is None:
            return _EMPTY_POSES
        return self._state_from_blob(blob)

    def generation(self, artifact_ref: str) -> PoseState:
        """Any historical generation by its immutable artifact ref."""
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise PoseError(f"pose generation {artifact_ref} is not stored")
        return self._state_from_blob(blob)

    def history(self) -> tuple[PoseState, ...]:
        """Every stored generation, oldest first (the ledger replay)."""
        chain: list[PoseState] = []
        current = self.state()
        while current.blob is not None:
            chain.append(current)
            parent = current.parent
            if parent is None or not self._store.blobs.has(parent):
                break
            current = self._state_from_blob(parent)
        return tuple(reversed(chain))

    def get(self, pose_id: str) -> PoseEntry:
        """One entry, or ``addressing_error`` naming the ids that do exist."""
        entries = self.state().by_id
        entry = entries.get(pose_id)
        if entry is None:
            raise AddressingError(
                f"no pose {pose_id!r} is declared",
                selector=pose_id,
                candidates=tuple(sorted(entries)),
            )
        return entry

    def _state_from_blob(self, blob: str) -> PoseState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise PoseError("pose-set state document is malformed")
        return PoseState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    # -- writes -------------------------------------------------------------

    def declare(self, entry: Mapping[str, JSONValue], *, op_id: str | None = None) -> PoseState:
        """Declare one new pose; advances one generation.

        Every bound joint id must be declared and unwithdrawn *now* — refused
        ``invalid_pose`` otherwise, naming the ids that do exist. A pose that
        would be born orphaned is a claim about nothing.
        """
        parsed = PoseEntry.from_json(entry)

        def apply(current: PoseState) -> tuple[PoseEntry, ...]:
            if parsed.id in current.by_id:
                raise PoseError(
                    f"pose {parsed.id} is already declared — revise it with "
                    "update_pose(id, patch, reason) so the change records a reason"
                )
            self._check_bindings(parsed)
            return (*current.entries, parsed)

        return self._mutate(
            PoseChange(kind="declare", id=parsed.id, patch=parsed.to_json()),
            apply,
            op_id=op_id,
        )

    def update(
        self,
        pose_id: str,
        patch: Mapping[str, JSONValue],
        reason: str,
        *,
        op_id: str | None = None,
    ) -> PoseState:
        """Revise one entry's declared fields; advances one generation.

        A patch that supplies a NEW ``joints`` binding is a fresh claim and is
        validated against the live joint set; a patch that leaves the binding
        alone is not — an orphaned pose (its joint withdrawn since) must stay
        editable, because orphanhood is an evaluation state, not corruption.
        """
        if not reason.strip():
            raise PoseError(f"pose {pose_id}: update requires a reason")
        cleaned = {name: value for name, value in patch.items() if value is not None}
        if not cleaned:
            raise PoseError(f"pose {pose_id}: update patches nothing")
        if "id" in cleaned:
            raise PoseError(
                f"pose {pose_id}: id is not patchable — declare a new pose and withdraw this one"
            )

        def apply(current: PoseState) -> tuple[PoseEntry, ...]:
            existing = _require_pose(current, pose_id)
            merged = dict(existing.to_json())
            merged.update(cleaned)
            updated = PoseEntry.from_json(merged)
            if "joints" in cleaned:
                self._check_bindings(updated)
            return tuple(updated if e.id == pose_id else e for e in current.entries)

        return self._mutate(
            PoseChange(
                kind="update",
                id=pose_id,
                reason=reason,
                patch=cast("Mapping[str, JSONValue]", dict(sorted(cleaned.items()))),
            ),
            apply,
            op_id=op_id,
        )

    def withdraw(self, pose_id: str, reason: str, *, op_id: str | None = None) -> PoseState:
        """Stop claiming one pose; advances one generation, erases nothing."""
        if not reason.strip():
            raise PoseError(f"pose {pose_id}: withdrawal requires a reason")

        def apply(current: PoseState) -> tuple[PoseEntry, ...]:
            existing = _require_pose(current, pose_id)
            if existing.withdrawn:
                raise PoseError(f"pose {pose_id} is already withdrawn")
            updated = replace(existing, withdrawn=True, withdrawn_reason=reason)
            return tuple(updated if e.id == pose_id else e for e in current.entries)

        return self._mutate(
            PoseChange(kind="withdraw", id=pose_id, reason=reason), apply, op_id=op_id
        )

    def _check_bindings(self, pose: PoseEntry) -> None:
        """Refuse bindings to joints the joint set does not currently claim (§3)."""
        joints = self._joints.state()
        known = joints.by_id
        for joint_id in sorted(pose.joints):
            entry = known.get(joint_id)
            if entry is None:
                declared = ", ".join(sorted(known)) or "(none)"
                raise PoseError(
                    f"pose {pose.id}: joint {joint_id!r} is not declared "
                    f"(declared joints: {declared})"
                )
            if entry.withdrawn:
                raise PoseError(
                    f"pose {pose.id}: joint {joint_id!r} is withdrawn "
                    f"({entry.withdrawn_reason}) — a pose declared against it would be "
                    "born orphaned; orphaned_pose is the evaluation state for poses "
                    "whose joints are withdrawn LATER (KINEMATICS.md §3)"
                )

    # -- the one generation-advancing path ----------------------------------

    def _mutate(
        self,
        change: PoseChange,
        apply: Callable[[PoseState], tuple[PoseEntry, ...]],
        *,
        op_id: str | None,
    ) -> PoseState:
        """Publish one new immutable generation under the project-config lock.

        The binding check inside ``apply`` reads the joint set under this same
        lock, so a pose can never be admitted concurrently with the withdrawal
        of a joint it binds. WAL/idempotency semantics are the joint set's.
        """
        if op_id is None:
            return self._publish(change, apply)
        payload: JSONValue = {"kind": "pose_write", "change": change.to_json()}
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            return self._replayed(outcome.response)
        if not isinstance(outcome, Fresh):
            raise PoseError(f"pose write {op_id!r} cannot proceed: prior state {outcome!r}")
        locks = LockManager(self._store)
        try:
            with locks.holding(PROJECT_CONFIG_LOCK):
                current = self.state()
                candidate, new_blob = self._candidate(current, change, apply)
                self._store.wal.publish(
                    outcome,
                    POSES_POINTER,
                    current.blob,
                    new_blob,
                    intended_outcome=canonical_json(
                        {"generation": candidate.generation, "state": new_blob}
                    ),
                )
                return candidate
        except PoseError:
            # Nothing was written: release the fresh opkey skeleton so a
            # corrected retry with the same invocation id is not a mismatch.
            self._store.wal.recover(outcome.op_key)
            raise

    def _publish(
        self,
        change: PoseChange,
        apply: Callable[[PoseState], tuple[PoseEntry, ...]],
    ) -> PoseState:
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            candidate, new_blob = self._candidate(current, change, apply)
            self._store.blobs.cas_swap(POSES_POINTER, current.blob, new_blob)
            return candidate

    def _candidate(
        self,
        current: PoseState,
        change: PoseChange,
        apply: Callable[[PoseState], tuple[PoseEntry, ...]],
    ) -> tuple[PoseState, str]:
        """Compute, store and pin the next generation's document (no pointer move)."""
        entries = apply(current)
        candidate = PoseState(
            generation=current.generation + 1,
            entries=entries,
            blob=None,
            parent=current.blob,
            change=change,
        )
        new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
        # Pinned, not merely pointer-protected — see the joint set's twin.
        self._store.gc.pin(new_blob)
        if current.blob is not None:
            self._store.gc.link(new_blob, current.blob)
        return replace(candidate, blob=new_blob), new_blob

    def _replayed(self, response: str | None) -> PoseState:
        """The generation a committed same-id call produced (immutable, so exact)."""
        recorded = _recorded_state(response)
        if recorded is not None and self._store.blobs.has(recorded):
            return self._state_from_blob(recorded)
        # Tombstoned replay: only the terminal state survives, so report live.
        return self.state()


class MotionCheckSet:
    """Declare / update / withdraw motion checks as immutable generations.

    The third rider on the ledger pattern (``KINEMATICS.md`` §4/§7),
    model-writable on the same recorded 8C quartet rationale as the joint set.
    Carries a :class:`JointSet` because a sweep's ranges are claims about
    declared joints: an unknown, withdrawn, or scalar-unsweepable joint id is
    refused at declaration (``invalid_motion_check``), read under the same
    project-config lock the write holds so a concurrent withdrawal cannot race
    the check. A joint withdrawn *after* declaration orphans the check at
    evaluation instead (``orphaned_sweep``, the ``orphaned_pose`` rule
    restated) — nothing here re-refuses it.
    """

    def __init__(self, layout: ProjectLayout, store: OpStore, joints: JointSet) -> None:
        self.layout = layout
        self._store = store
        self._joints = joints

    # -- reads --------------------------------------------------------------

    def state(self) -> MotionCheckState:
        """The current generation (empty generation 0 when never written)."""
        blob = self._store.blobs.read_pointer(MOTION_CHECKS_POINTER)
        if blob is None:
            return _EMPTY_CHECKS
        return self._state_from_blob(blob)

    def generation(self, artifact_ref: str) -> MotionCheckState:
        """Any historical generation by its immutable artifact ref."""
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise MotionCheckError(f"motion-check generation {artifact_ref} is not stored")
        return self._state_from_blob(blob)

    def history(self) -> tuple[MotionCheckState, ...]:
        """Every stored generation, oldest first (the ledger replay)."""
        chain: list[MotionCheckState] = []
        current = self.state()
        while current.blob is not None:
            chain.append(current)
            parent = current.parent
            if parent is None or not self._store.blobs.has(parent):
                break
            current = self._state_from_blob(parent)
        return tuple(reversed(chain))

    def get(self, check_id: str) -> MotionCheckEntry:
        """One entry, or ``addressing_error`` naming the ids that do exist."""
        entries = self.state().by_id
        entry = entries.get(check_id)
        if entry is None:
            raise AddressingError(
                f"no motion check {check_id!r} is declared",
                selector=check_id,
                candidates=tuple(sorted(entries)),
            )
        return entry

    def _state_from_blob(self, blob: str) -> MotionCheckState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise MotionCheckError("motion-check-set state document is malformed")
        return MotionCheckState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    # -- writes -------------------------------------------------------------

    def declare(
        self, entry: Mapping[str, JSONValue], *, op_id: str | None = None
    ) -> MotionCheckState:
        """Declare one new motion check; advances one generation.

        A repeated id is refused rather than silently replaced (revising is
        :meth:`update`, which records why), and every swept joint must be
        declared, unwithdrawn, and scalar-sweepable *now* — a check that would
        be born unevaluatable is a claim about nothing.
        """
        parsed = MotionCheckEntry.from_json(entry)

        def apply(current: MotionCheckState) -> tuple[MotionCheckEntry, ...]:
            if parsed.id in current.by_id:
                raise MotionCheckError(
                    f"motion check {parsed.id} is already declared — revise it with "
                    "update_motion_check(id, patch, reason) so the change records a reason"
                )
            self._check_sweep_bindings(parsed)
            return (*current.entries, parsed)

        return self._mutate(
            MotionCheckChange(kind="declare", id=parsed.id, patch=parsed.to_json()),
            apply,
            op_id=op_id,
        )

    def update(
        self,
        check_id: str,
        patch: Mapping[str, JSONValue],
        reason: str,
        *,
        op_id: str | None = None,
    ) -> MotionCheckState:
        """Revise one entry's declared fields; advances one generation.

        ``reason`` is compulsory and recorded on the generation. A patch that
        supplies a NEW ``sweep`` is a fresh claim and is validated against the
        live joint set; a patch that leaves it alone is not — an orphaned
        check (its joint withdrawn since) must stay editable, because
        orphanhood is an evaluation state, not corruption. A kind change drops
        the old kind's own fields from the merged entry first, so a stale
        ``min_mm`` (or target) cannot be smuggled past the per-kind field
        check — the joint set's kind/limits rule, restated.
        """
        if not reason.strip():
            raise MotionCheckError(f"motion check {check_id}: update requires a reason")
        cleaned = {name: value for name, value in patch.items() if value is not None}
        if not cleaned:
            raise MotionCheckError(f"motion check {check_id}: update patches nothing")
        if "id" in cleaned:
            raise MotionCheckError(
                f"motion check {check_id}: id is not patchable — declare a new check "
                "and withdraw this one"
            )

        def apply(current: MotionCheckState) -> tuple[MotionCheckEntry, ...]:
            existing = _require_check(current, check_id)
            merged = dict(existing.to_json())
            if "kind" in cleaned and cleaned["kind"] != existing.kind:
                for name in ("a", "b", "min_mm", "anchor", "target_point_mm", "tol_mm"):
                    merged.pop(name, None)
            merged.update(cleaned)
            updated = MotionCheckEntry.from_json(merged)
            if "sweep" in cleaned:
                self._check_sweep_bindings(updated)
            return tuple(updated if e.id == check_id else e for e in current.entries)

        return self._mutate(
            MotionCheckChange(
                kind="update",
                id=check_id,
                reason=reason,
                patch=cast("Mapping[str, JSONValue]", dict(sorted(cleaned.items()))),
            ),
            apply,
            op_id=op_id,
        )

    def withdraw(self, check_id: str, reason: str, *, op_id: str | None = None) -> MotionCheckState:
        """Stop claiming one motion check; advances one generation, erases nothing."""
        if not reason.strip():
            raise MotionCheckError(f"motion check {check_id}: withdrawal requires a reason")

        def apply(current: MotionCheckState) -> tuple[MotionCheckEntry, ...]:
            existing = _require_check(current, check_id)
            if existing.withdrawn:
                raise MotionCheckError(f"motion check {check_id} is already withdrawn")
            updated = replace(existing, withdrawn=True, withdrawn_reason=reason)
            return tuple(updated if e.id == check_id else e for e in current.entries)

        return self._mutate(
            MotionCheckChange(kind="withdraw", id=check_id, reason=reason), apply, op_id=op_id
        )

    def _check_sweep_bindings(self, check: MotionCheckEntry) -> None:
        """Refuse sweeps over joints the joint set cannot supply a scalar DOF for (§4).

        Three statically-knowable refusals, all ``invalid_motion_check``: an
        undeclared joint, a withdrawn joint (a check declared against it would
        be born orphaned; ``orphaned_sweep`` is the evaluation state for
        joints withdrawn LATER), and a joint whose kind has no scalar
        parameter to sweep — ``fixed`` has 0 DOF, and ``cylindrical`` takes a
        ``(degrees, mm)`` pair the 9A scalar sweep wire shape cannot bind
        (the pose set's ``invalid_pose`` evaluation rule, caught at
        declaration here because a sweep names its joints structurally).
        """
        joints = self._joints.state()
        known = joints.by_id
        for joint_id in sorted(check.sweep):
            entry = known.get(joint_id)
            if entry is None:
                declared = ", ".join(sorted(known)) or "(none)"
                raise MotionCheckError(
                    f"motion check {check.id}: joint {joint_id!r} is not declared "
                    f"(declared joints: {declared})"
                )
            if entry.withdrawn:
                raise MotionCheckError(
                    f"motion check {check.id}: joint {joint_id!r} is withdrawn "
                    f"({entry.withdrawn_reason}) — a check declared against it would be "
                    "born orphaned; orphaned_sweep is the evaluation state for joints "
                    "withdrawn LATER (KINEMATICS.md §4)"
                )
            if entry.kind == "fixed":
                raise MotionCheckError(
                    f"motion check {check.id}: joint {joint_id!r} is 'fixed' (0 DOF) "
                    "and has no parameter to sweep"
                )
            if entry.kind == "cylindrical":
                raise MotionCheckError(
                    f"motion check {check.id}: joint {joint_id!r} is 'cylindrical' — "
                    "its (degrees, mm) pair has no scalar sweep form in the 9A wire "
                    "shape (KINEMATICS.md §4); sweep a revolute or prismatic joint"
                )

    # -- the one generation-advancing path ----------------------------------

    def _mutate(
        self,
        change: MotionCheckChange,
        apply: Callable[[MotionCheckState], tuple[MotionCheckEntry, ...]],
        *,
        op_id: str | None,
    ) -> MotionCheckState:
        """Publish one new immutable generation under the project-config lock.

        The binding check inside ``apply`` reads the joint set under this same
        lock, so a check can never be admitted concurrently with the
        withdrawal of a joint it sweeps. WAL/idempotency semantics are the
        joint set's, verbatim.
        """
        if op_id is None:
            return self._publish(change, apply)
        payload: JSONValue = {"kind": "motion_check_write", "change": change.to_json()}
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            return self._replayed(outcome.response)
        if not isinstance(outcome, Fresh):
            raise MotionCheckError(
                f"motion-check write {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        locks = LockManager(self._store)
        try:
            with locks.holding(PROJECT_CONFIG_LOCK):
                current = self.state()
                candidate, new_blob = self._candidate(current, change, apply)
                self._store.wal.publish(
                    outcome,
                    MOTION_CHECKS_POINTER,
                    current.blob,
                    new_blob,
                    intended_outcome=canonical_json(
                        {"generation": candidate.generation, "state": new_blob}
                    ),
                )
                return candidate
        except MotionCheckError:
            # Nothing was written: release the fresh opkey skeleton so a
            # corrected retry with the same invocation id is not a mismatch.
            self._store.wal.recover(outcome.op_key)
            raise

    def _publish(
        self,
        change: MotionCheckChange,
        apply: Callable[[MotionCheckState], tuple[MotionCheckEntry, ...]],
    ) -> MotionCheckState:
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            candidate, new_blob = self._candidate(current, change, apply)
            self._store.blobs.cas_swap(MOTION_CHECKS_POINTER, current.blob, new_blob)
            return candidate

    def _candidate(
        self,
        current: MotionCheckState,
        change: MotionCheckChange,
        apply: Callable[[MotionCheckState], tuple[MotionCheckEntry, ...]],
    ) -> tuple[MotionCheckState, str]:
        """Compute, store and pin the next generation's document (no pointer move)."""
        entries = apply(current)
        candidate = MotionCheckState(
            generation=current.generation + 1,
            entries=entries,
            blob=None,
            parent=current.blob,
            change=change,
        )
        new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
        # Pinned, not merely pointer-protected — see the joint set's twin.
        self._store.gc.pin(new_blob)
        if current.blob is not None:
            self._store.gc.link(new_blob, current.blob)
        return replace(candidate, blob=new_blob), new_blob

    def _replayed(self, response: str | None) -> MotionCheckState:
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


def _require_joint(current: JointState, joint_id: str) -> JointEntry:
    existing = current.by_id.get(joint_id)
    if existing is None:
        raise JointError(
            f"no joint {joint_id!r} is declared (known: {sorted(current.by_id)})",
            reason="unknown_joint",
        )
    return existing


def _require_pose(current: PoseState, pose_id: str) -> PoseEntry:
    existing = current.by_id.get(pose_id)
    if existing is None:
        raise PoseError(
            f"no pose {pose_id!r} is declared (known: {sorted(current.by_id)})",
            reason="unknown_pose",
        )
    return existing


def _require_check(current: MotionCheckState, check_id: str) -> MotionCheckEntry:
    existing = current.by_id.get(check_id)
    if existing is None:
        raise MotionCheckError(
            f"no motion check {check_id!r} is declared (known: {sorted(current.by_id)})",
            reason="unknown_motion_check",
        )
    return existing
