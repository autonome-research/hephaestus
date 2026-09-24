# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""CAM declared state: setups, stock, fixtures, WCS and operations (CAM.md §3).

A setup spans the part, the stock, the fixture and the tools, so by the
argument ``ASSEMBLY.md`` §1 and ``KINEMATICS.md`` §1 both make verbatim, it
cannot live in any part script. The five stores here ride **the ledger
pattern, unchanged and unextended** (the ``constraints.py`` precedent):
CAS-swap under the project-config lock, immutable content-addressed
generations, provenance mandatory on every entry, withdrawal a new generation
and never an erasure, and every read returning withdrawn entries with their
reasons.

What is validated here is exactly the **declaration-time** half of CAM.md
§4.3 — decidable from an entry's own declared fields and the entries it
names, with no geometry, no registry resolution and no tool in the loop:

* the five ``invalid_*`` refusals (malformed entries, absent provenance, the
  anchor grammar — ``ANCHOR_PATTERN`` reused verbatim, a slash-bearing anchor
  refused for the same two-grammars reason 8C records);
* ``invalid_tool_ref``, ``tag_prefix_mismatch`` / ``tag_prefix_unknown`` (the
  ``cutfile.layer_for_tag`` rule generalized from four layers to five
  operation kinds — a lookup, never a search), ``duplicate_feature_claim``;
* the tolerance **shape** rules ``no_declared_tolerance`` and
  ``budget_missing_rejects`` (``VALIDATION.md`` §1 rule 2 — a budget carries
  the smallest deviation it must reject);
* ``op_sample_bound_exceeded`` — the closed-form ``levels x loops_bound``
  sieve over an operation entry's own numbers and the named stock's
  ``extents_mm`` (:data:`hephaestus.core.limits.CAM_OP_PASS_BOUND_MAX`). It
  bounds passes, not samples; the sample cap is generation-time machinery
  (CAM.md §5.3) and deliberately does not live here.

Everything needing resolution or geometry — ``stock_too_small``, feed
transport, ``budget_below_resolution``, axis checks, generation — is
:mod:`hephaestus.core.machining`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, Literal, cast

from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.limits import CAM_OP_PASS_BOUND_MAX
from hephaestus.core.project_store.constraints import ANCHOR_PATTERN, ANCHOR_SEPARATOR
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
    "CAM_ID_PATTERN",
    "CAM_TAG_PREFIXES",
    "KEEPOUT_TAG_PREFIX",
    "OPERATION_KINDS",
    "SPINDLE_AXES",
    "STOCK_KINDS",
    "Z_ZERO_MODES",
    "CamEntry",
    "CamError",
    "CamLedger",
    "CamProvenance",
    "CamState",
    "FixtureEntry",
    "FixtureMember",
    "FixtureSet",
    "OperationEntry",
    "OperationSet",
    "SetupEntry",
    "SetupSet",
    "StockEntry",
    "StockSet",
    "WcsEntry",
    "WcsSet",
    "operation_kind_for_tag",
    "operation_pass_bound",
    "validate_feature_tag",
]

#: CAM entry ids: stable handles a requirement, a tool call and a reviewer
#: finding all name — the constraint-id pattern verbatim.
CAM_ID_PATTERN: Final[str] = r"^[A-Za-z][A-Za-z0-9._-]{0,63}$"
_ID_RE: Final[re.Pattern[str]] = re.compile(CAM_ID_PATTERN)
_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(ANCHOR_PATTERN)

#: The six declared spindle directions (CAM.md §3.1) — declared, never inferred.
SPINDLE_AXES: Final[tuple[str, ...]] = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")

#: Stage 14 stock kinds. Cylindrical bar and previously-machined-solid stock
#: are named future kinds, each a contract amendment (CAM.md §3.2).
STOCK_KINDS: Final[tuple[str, ...]] = ("rectangular",)

#: Declared Z-zero modes (CAM.md §3.4) — a Z zero the harness picked is the
#: single fastest way to bury a cutter in a vise, so there is no default.
Z_ZERO_MODES: Final[tuple[str, ...]] = ("stock_top", "part_top", "datum")

#: The Stage 14 operation kinds (CAM.md §3.7); each later kind is a contract
#: amendment, the ASSEMBLY.md §1 / KINEMATICS.md §1 rule.
OPERATION_KINDS: Final[tuple[str, ...]] = ("drill", "pocket", "profile", "face")

#: The §5.3 CAM tag-prefix table (CAM.md §3.7): ``cutfile.layer_for_tag``
#: (``cutfile.py:117-144``) generalized from four layers to five operation
#: kinds — the same lookup, never a search, never a heuristic. ``mill_`` is
#: the generic prefix any operation kind may claim (``None`` below).
CAM_TAG_PREFIXES: Final[tuple[tuple[str, str | None], ...]] = (
    ("drill_", "drill"),
    ("pocket_", "pocket"),
    ("profile_", "profile"),
    ("face_", "face"),
    ("mill_", None),
)

#: Reserved for §5.5 keep-out volumes: never claimable by an operation.
KEEPOUT_TAG_PREFIX: Final[str] = "keepout_"


class CamError(ValidationError):
    """A CAM declaration was refused; ``reason`` is the stable machine token.

    Every token is from the closed declaration-time set of CAM.md §4.3 (plus
    the per-kind ``unknown_*`` for a patch or withdrawal naming an id the set
    does not carry — the ``unknown_constraint`` precedent). Nothing is ever
    written on a refusal.
    """

    def __init__(
        self, message: str, *, reason: str, data: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason = reason
        self.data: dict[str, JSONValue] = dict(data or {})


def operation_kind_for_tag(tag: str) -> tuple[str | None, str | None]:
    """``(prefix, operation_kind)`` a §5.3 tag names, or ``(None, None)``.

    The whole assignment rule, on ``layer_for_tag``'s shape: a lookup over the
    fixed prefix table, and a bare prefix — nothing after it — names no
    feature (the ``cutfile.py:139-143`` boundary rule). ``keepout_`` is a
    known prefix reserved for scenes, returned with kind ``"keepout"`` so the
    caller can refuse it as a mismatch rather than an unknown.
    """
    if tag.startswith(KEEPOUT_TAG_PREFIX) and len(tag) > len(KEEPOUT_TAG_PREFIX):
        return (KEEPOUT_TAG_PREFIX, "keepout")
    for prefix, kind in CAM_TAG_PREFIXES:
        if tag.startswith(prefix) and len(tag) > len(prefix):
            return (prefix, kind if kind is not None else "*")
    return (None, None)


def validate_feature_tag(op_id: str, op_kind: str, tag: str) -> None:
    """Refuse a feature tag whose prefix does not name ``op_kind`` (CAM.md §3.7)."""
    prefix, tag_kind = operation_kind_for_tag(tag)
    if prefix is None:
        raise CamError(
            f"operation {op_id}: feature tag {tag!r} carries no CAM prefix, or a bare "
            f"prefix that names no feature — the §5.3 CAM prefixes are "
            f"{', '.join(p for p, _ in CAM_TAG_PREFIXES)}",
            reason="tag_prefix_unknown",
            data={"operation": op_id, "tag": tag},
        )
    if tag_kind == "keepout":
        raise CamError(
            f"operation {op_id}: tag {tag!r} is a keep-out volume (CAM.md §5.5), "
            f"never an operation feature",
            reason="tag_prefix_mismatch",
            data={"operation": op_id, "tag": tag, "kind": op_kind},
        )
    if tag_kind != "*" and tag_kind != op_kind:
        raise CamError(
            f"operation {op_id}: feature tag {tag!r} names a {tag_kind!r} feature, "
            f"but the operation kind is {op_kind!r}",
            reason="tag_prefix_mismatch",
            data={"operation": op_id, "tag": tag, "kind": op_kind},
        )


# --------------------------------------------------------------------------
# shared field parsing


@dataclass(frozen=True)
class CamProvenance:
    """Why this entry is claimed — a requirement, or an assumption with a reason.

    The ``VALIDATION.md`` §2 taxonomy on the 8C compulsion: a setup IS an
    interpretation of intent, so it says whose. The absence of both is a
    refusal under the owning kind's ``invalid_*`` token, never a default.
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


def _parse_provenance(
    entry_id: str, data: JSONValue | None, refuse: Callable[[str], CamError]
) -> CamProvenance:
    if not isinstance(data, dict):
        raise refuse(
            f"{entry_id}: provenance is required — cite a requirement "
            '({"requirement": "r-11"}) or declare an assumption '
            '({"assumed": true, "reason": "…"}) (CAM.md §3.1)'
        )
    raw = cast("Mapping[str, JSONValue]", data)
    unknown = sorted(set(raw) - {"requirement", "assumed", "reason"})
    if unknown:
        raise refuse(f"{entry_id}: unknown provenance field(s) {', '.join(unknown)}")
    requirement = raw.get("requirement")
    assumed = raw.get("assumed", False)
    reason = raw.get("reason")
    if requirement is not None and (not isinstance(requirement, str) or not requirement.strip()):
        raise refuse(f"{entry_id}: provenance.requirement must be a requirement id")
    if not isinstance(assumed, bool):
        raise refuse(f"{entry_id}: provenance.assumed must be a boolean")
    if reason is not None and not isinstance(reason, str):
        raise refuse(f"{entry_id}: provenance.reason must be a string")
    requirement_id = requirement if isinstance(requirement, str) else None
    clean_reason = reason if isinstance(reason, str) and reason.strip() else None
    if requirement_id is not None and assumed:
        raise refuse(
            f"{entry_id}: provenance is either a cited requirement or an assumption, not both"
        )
    if requirement_id is None and not assumed:
        raise refuse(
            f"{entry_id}: provenance must cite a requirement id or set "
            '"assumed": true with a reason (CAM.md §3.1)'
        )
    if assumed and clean_reason is None:
        raise refuse(f"{entry_id}: an assumed entry requires a reason")
    return CamProvenance(requirement=requirement_id, assumed=assumed, reason=clean_reason)


def _parse_id(data: Mapping[str, JSONValue], refuse: Callable[[str], CamError]) -> str:
    raw = data.get("id")
    if not isinstance(raw, str) or not _ID_RE.match(raw):
        raise refuse(f"entry id {raw!r} must match {CAM_ID_PATTERN}")
    return raw


def _parse_anchor(
    entry_id: str, value: JSONValue | None, *, fieldname: str, refuse: Callable[[str], CamError]
) -> str:
    """The 8C ``part[:selector]`` anchor grammar, verbatim — no new naming scheme.

    A slash-bearing anchor is refused for the two-grammars reason 8C records:
    ``<part>/<selector>`` is the §7 cross-part selector spelling, and one
    string must not have two grammars.
    """
    if not isinstance(value, str) or not _ANCHOR_RE.match(value):
        raise refuse(
            f"{entry_id}: {fieldname}={value!r} must be 'part' or "
            f"'part{ANCHOR_SEPARATOR}selector' (matching {ANCHOR_PATTERN})"
        )
    return value


def _parse_number(
    entry_id: str,
    data: Mapping[str, JSONValue],
    key: str,
    refuse: Callable[[str], CamError],
    *,
    required: bool = True,
    positive: bool = True,
) -> float | None:
    value = data.get(key)
    if value is None:
        if required:
            raise refuse(f"{entry_id}: {key} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise refuse(f"{entry_id}: {key} must be a finite number")
    number = float(value)
    if positive and number <= 0.0:
        raise refuse(f"{entry_id}: {key} must be positive (got {number})")
    return number


def _parse_note(
    entry_id: str, data: Mapping[str, JSONValue], refuse: Callable[[str], CamError]
) -> str | None:
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise refuse(f"{entry_id}: note must be a string")
    return note


def _parse_withdrawal(
    entry_id: str, data: Mapping[str, JSONValue], refuse: Callable[[str], CamError]
) -> tuple[bool, str | None]:
    withdrawn = data.get("withdrawn", False)
    if not isinstance(withdrawn, bool):
        raise refuse(f"{entry_id}: withdrawn must be a boolean")
    reason = data.get("withdrawn_reason")
    if reason is not None and not isinstance(reason, str):
        raise refuse(f"{entry_id}: withdrawn_reason must be a string")
    if withdrawn and not (reason or "").strip():
        raise refuse(f"{entry_id}: a withdrawal must record a reason")
    return withdrawn, reason if withdrawn else None


def _reject_unknown(
    entry_id: str,
    data: Mapping[str, JSONValue],
    allowed: frozenset[str],
    refuse: Callable[[str], CamError],
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise refuse(f"{entry_id}: unknown field(s) {', '.join(unknown)}")


# --------------------------------------------------------------------------
# the five entry kinds


@dataclass(frozen=True)
class CamEntry:
    """Fields every CAM ledger entry shares (the constraint-entry shape)."""

    id: str
    provenance: CamProvenance
    note: str | None = None
    withdrawn: bool = False
    withdrawn_reason: str | None = None

    def common_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {}
        out["provenance"] = cast("JSONValue", self.provenance.to_json())
        if self.note is not None:
            out["note"] = self.note
        if self.withdrawn:
            out["withdrawn"] = True
            out["withdrawn_reason"] = self.withdrawn_reason
        return out


def _refuser(reason: str) -> Callable[[str], CamError]:
    def refuse(message: str) -> CamError:
        return CamError(message, reason=reason)

    return refuse


@dataclass(frozen=True)
class SetupEntry(CamEntry):
    """One declared setup (CAM.md §3.1): spindle axis, order, the named records.

    ``tolerance`` is a material budget in the ``VALIDATION.md`` §1 rule-2
    sense: each budget carries the smallest deviation it must reject
    (``rejects_mm3``). Only the block's own **shape** is decidable here; the
    resolution floor comparison is :mod:`hephaestus.core.machining`'s
    ``budget_below_resolution``, because a setup entry names no tool.
    """

    spindle_axis: str = "+Z"
    order: int = 1
    stock: str = ""
    fixture: str = ""
    wcs: str = ""
    tolerance: Mapping[str, float] = field(default_factory=dict[str, float])

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "spindle_axis": self.spindle_axis,
            "order": self.order,
            "stock": self.stock,
            "fixture": self.fixture,
            "wcs": self.wcs,
            "tolerance": {name: self.tolerance[name] for name in sorted(self.tolerance)},
        }
        out.update(self.common_json())
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> SetupEntry:
        refuse = _refuser("invalid_setup")
        entry_id = _parse_id(data, refuse)
        _reject_unknown(
            entry_id,
            data,
            frozenset(
                {
                    "id",
                    "spindle_axis",
                    "order",
                    "stock",
                    "fixture",
                    "wcs",
                    "tolerance",
                    "provenance",
                    "note",
                    "withdrawn",
                    "withdrawn_reason",
                }
            ),
            refuse,
        )
        axis = data.get("spindle_axis")
        if axis not in SPINDLE_AXES:
            raise refuse(
                f"{entry_id}: spindle_axis must be one of {', '.join(SPINDLE_AXES)} "
                f"(got {axis!r}) — declared, never inferred (CAM.md §3.1)"
            )
        order = data.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 1:
            raise refuse(f"{entry_id}: order must be a positive integer")
        names: dict[str, str] = {}
        for key in ("stock", "fixture", "wcs"):
            value = data.get(key)
            if not isinstance(value, str) or not _ID_RE.match(value):
                raise refuse(f"{entry_id}: {key} must name a declared {key} entry id")
            names[key] = value
        tolerance = _parse_tolerance(entry_id, data.get("tolerance"))
        withdrawn, withdrawn_reason = _parse_withdrawal(entry_id, data, refuse)
        return cls(
            id=entry_id,
            spindle_axis=cast("str", axis),
            order=order,
            stock=names["stock"],
            fixture=names["fixture"],
            wcs=names["wcs"],
            tolerance=tolerance,
            provenance=_parse_provenance(entry_id, data.get("provenance"), refuse),
            note=_parse_note(entry_id, data, refuse),
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason,
        )


def _parse_tolerance(entry_id: str, raw: JSONValue | None) -> dict[str, float]:
    """The §3.1 tolerance-budget shape rules, and only the shape rules.

    An absent block is ``no_declared_tolerance``; a budget carrying no
    ``rejects_mm3`` is ``budget_missing_rejects`` — the two declaration-time
    checks CAM.md §3.1 files here. Whether a budget is below the simulation's
    resolution floor is a **resolution-time** question and deliberately not
    asked here.
    """
    if raw is None:
        raise CamError(
            f"{entry_id}: a setup declares its tolerance budgets "
            "(gouge_budget_mm3, rest_budget_mm3, max_deviation_mm, rejects_mm3) — "
            "an absent block is refused, never defaulted (CAM.md §3.1)",
            reason="no_declared_tolerance",
            data={"setup": entry_id},
        )
    refuse = _refuser("invalid_setup")
    if not isinstance(raw, dict):
        raise refuse(f"{entry_id}: tolerance must be an object of budgets")
    block = cast("Mapping[str, JSONValue]", raw)
    allowed = {"gouge_budget_mm3", "rest_budget_mm3", "max_deviation_mm", "rejects_mm3"}
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise refuse(f"{entry_id}: unknown tolerance field(s) {', '.join(unknown)}")
    out: dict[str, float] = {}
    for key in ("gouge_budget_mm3", "rest_budget_mm3", "max_deviation_mm"):
        value = _parse_number(entry_id, block, key, refuse, required=True)
        assert value is not None
        out[key] = value
    rejects = block.get("rejects_mm3")
    if rejects is None:
        raise CamError(
            f"{entry_id}: the tolerance block carries no rejects_mm3 — a budget "
            "states the smallest deviation it must reject (VALIDATION.md §1 rule 2); "
            "an inline budget justifying nothing is rejected",
            reason="budget_missing_rejects",
            data={"setup": entry_id},
        )
    value = _parse_number(entry_id, block, "rejects_mm3", refuse, required=True)
    assert value is not None
    out["rejects_mm3"] = value
    return out


@dataclass(frozen=True)
class StockEntry(CamEntry):
    """One declared stock record (CAM.md §3.2)."""

    kind: str = "rectangular"
    extents_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    origin_anchor: str = ""
    origin_offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    material: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "kind": self.kind,
            "extents_mm": list(self.extents_mm),
            "origin_anchor": self.origin_anchor,
            "origin_offset_mm": list(self.origin_offset_mm),
            "material": self.material,
        }
        out.update(self.common_json())
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> StockEntry:
        refuse = _refuser("invalid_stock")
        entry_id = _parse_id(data, refuse)
        _reject_unknown(
            entry_id,
            data,
            frozenset(
                {
                    "id",
                    "kind",
                    "extents_mm",
                    "origin_anchor",
                    "origin_offset_mm",
                    "material",
                    "provenance",
                    "note",
                    "withdrawn",
                    "withdrawn_reason",
                }
            ),
            refuse,
        )
        kind = data.get("kind")
        if kind not in STOCK_KINDS:
            raise refuse(
                f"{entry_id}: stock kind must be one of {', '.join(STOCK_KINDS)} "
                f"(got {kind!r}); cylindrical bar and machined-solid stock are named "
                f"future kinds, each a contract amendment (CAM.md §3.2)"
            )
        extents = _parse_triple(entry_id, data.get("extents_mm"), "extents_mm", refuse, True)
        offset_raw = data.get("origin_offset_mm")
        offset = (
            (0.0, 0.0, 0.0)
            if offset_raw is None
            else _parse_triple(entry_id, offset_raw, "origin_offset_mm", refuse, False)
        )
        anchor = _parse_anchor(
            entry_id, data.get("origin_anchor"), fieldname="origin_anchor", refuse=refuse
        )
        material = data.get("material")
        if not isinstance(material, str) or not material.strip():
            raise refuse(f"{entry_id}: material must name a materials-registry id")
        withdrawn, withdrawn_reason = _parse_withdrawal(entry_id, data, refuse)
        return cls(
            id=entry_id,
            kind=cast("str", kind),
            extents_mm=extents,
            origin_anchor=anchor,
            origin_offset_mm=offset,
            material=material,
            provenance=_parse_provenance(entry_id, data.get("provenance"), refuse),
            note=_parse_note(entry_id, data, refuse),
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason,
        )


def _parse_triple(
    entry_id: str,
    raw: JSONValue | None,
    fieldname: str,
    refuse: Callable[[str], CamError],
    positive: bool,
) -> tuple[float, float, float]:
    if not isinstance(raw, list) or len(cast("list[JSONValue]", raw)) != 3:
        raise refuse(f"{entry_id}: {fieldname} must be a [x, y, z] triple in millimetres")
    values: list[float] = []
    for item in cast("list[JSONValue]", raw):
        if isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item):
            raise refuse(f"{entry_id}: {fieldname} components must be finite numbers")
        number = float(item)
        if positive and number <= 0.0:
            raise refuse(f"{entry_id}: {fieldname} components must be positive")
        values.append(number)
    return (values[0], values[1], values[2])


@dataclass(frozen=True)
class FixtureMember:
    """One placed fixture member: a part, an anchor, and a rigid offset."""

    part: str
    anchor: str
    offset_mm: tuple[float, float, float]

    def to_json(self) -> dict[str, JSONValue]:
        return {"part": self.part, "anchor": self.anchor, "offset_mm": list(self.offset_mm)}


@dataclass(frozen=True)
class FixtureEntry(CamEntry):
    """One declared fixture (CAM.md §3.3): declared geometry, honestly named.

    There is no work-holding precedent anywhere in this repo — this record is
    the whole reason the strongest collision sentence is
    ``no_collision_at_samples_in_declared_scene``. An empty member list is
    declarable (the project may not have modelled its vise yet), and a
    collision check against it is ``undeclared_scene``, never a clean result.
    """

    members: tuple[FixtureMember, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "members": [member.to_json() for member in self.members],
        }
        out.update(self.common_json())
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> FixtureEntry:
        refuse = _refuser("invalid_fixture")
        entry_id = _parse_id(data, refuse)
        _reject_unknown(
            entry_id,
            data,
            frozenset({"id", "members", "provenance", "note", "withdrawn", "withdrawn_reason"}),
            refuse,
        )
        raw_members = data.get("members")
        if not isinstance(raw_members, list):
            raise refuse(f"{entry_id}: members must be an array of placed parts")
        members: list[FixtureMember] = []
        for index, item in enumerate(cast("list[JSONValue]", raw_members)):
            if not isinstance(item, dict):
                raise refuse(f"{entry_id}: members[{index}] must be an object")
            member = cast("Mapping[str, JSONValue]", item)
            unknown = sorted(set(member) - {"part", "anchor", "offset_mm"})
            if unknown:
                raise refuse(f"{entry_id}: members[{index}] unknown field(s) {', '.join(unknown)}")
            part = member.get("part")
            if not isinstance(part, str) or not _ID_RE.match(part):
                raise refuse(f"{entry_id}: members[{index}].part must be a part name")
            anchor = _parse_anchor(
                entry_id, member.get("anchor"), fieldname=f"members[{index}].anchor", refuse=refuse
            )
            offset = _parse_triple(
                entry_id, member.get("offset_mm"), f"members[{index}].offset_mm", refuse, False
            )
            members.append(FixtureMember(part=part, anchor=anchor, offset_mm=offset))
        withdrawn, withdrawn_reason = _parse_withdrawal(entry_id, data, refuse)
        return cls(
            id=entry_id,
            members=tuple(members),
            provenance=_parse_provenance(entry_id, data.get("provenance"), refuse),
            note=_parse_note(entry_id, data, refuse),
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason,
        )


@dataclass(frozen=True)
class WcsEntry(CamEntry):
    """One declared work coordinate system (CAM.md §3.4)."""

    code: str = "G54"
    datum: str = ""
    z_zero: str = "stock_top"

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "code": self.code,
            "datum": self.datum,
            "z_zero": self.z_zero,
        }
        out.update(self.common_json())
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> WcsEntry:
        refuse = _refuser("invalid_wcs")
        entry_id = _parse_id(data, refuse)
        _reject_unknown(
            entry_id,
            data,
            frozenset(
                {
                    "id",
                    "code",
                    "datum",
                    "z_zero",
                    "provenance",
                    "note",
                    "withdrawn",
                    "withdrawn_reason",
                }
            ),
            refuse,
        )
        code = data.get("code")
        if not isinstance(code, str) or not code.strip():
            raise refuse(f"{entry_id}: code must be the controller work-offset code (e.g. 'G54')")
        datum = _parse_anchor(entry_id, data.get("datum"), fieldname="datum", refuse=refuse)
        z_zero = data.get("z_zero")
        if z_zero not in Z_ZERO_MODES:
            raise refuse(
                f"{entry_id}: z_zero must be one of {', '.join(Z_ZERO_MODES)} (got {z_zero!r}) "
                f"— declared, never guessed (CAM.md §3.4)"
            )
        withdrawn, withdrawn_reason = _parse_withdrawal(entry_id, data, refuse)
        return cls(
            id=entry_id,
            code=code,
            datum=datum,
            z_zero=cast("str", z_zero),
            provenance=_parse_provenance(entry_id, data.get("provenance"), refuse),
            note=_parse_note(entry_id, data, refuse),
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason,
        )


#: The explicit per-operation transported numbers (CAM.md §3.6 source 1).
_FEED_FIELDS: Final[tuple[str, ...]] = ("feed_mm_min", "rpm", "plunge_mm_min", "doc_mm", "woc_mm")


@dataclass(frozen=True)
class OperationEntry(CamEntry):
    """One declared operation (CAM.md §3.7): a tag, a tool, declared numbers."""

    setup: str = ""
    kind: str = "pocket"
    feature: str = ""
    tool: str = ""
    depth_mm: float = 0.0
    stepdown_mm: float | None = None
    stepover_mm: float | None = None
    climb: bool = True
    tabs: Mapping[str, JSONValue] | None = None
    feeds: Mapping[str, float] = field(default_factory=dict[str, float])

    @property
    def feature_parts(self) -> tuple[str, str]:
        part, _, selector = self.feature.partition(ANCHOR_SEPARATOR)
        return part, selector

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "setup": self.setup,
            "kind": self.kind,
            "feature": self.feature,
            "tool": self.tool,
            "depth_mm": self.depth_mm,
            "climb": self.climb,
        }
        if self.stepdown_mm is not None:
            out["stepdown_mm"] = self.stepdown_mm
        if self.stepover_mm is not None:
            out["stepover_mm"] = self.stepover_mm
        if self.tabs is not None:
            out["tabs"] = {name: self.tabs[name] for name in sorted(self.tabs)}
        for name in _FEED_FIELDS:
            if name in self.feeds:
                out[name] = self.feeds[name]
        out.update(self.common_json())
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> OperationEntry:
        refuse = _refuser("invalid_operation")
        entry_id = _parse_id(data, refuse)
        _reject_unknown(
            entry_id,
            data,
            frozenset(
                {
                    "id",
                    "setup",
                    "kind",
                    "feature",
                    "tool",
                    "depth_mm",
                    "stepdown_mm",
                    "stepover_mm",
                    "climb",
                    "tabs",
                    *_FEED_FIELDS,
                    "provenance",
                    "note",
                    "withdrawn",
                    "withdrawn_reason",
                }
            ),
            refuse,
        )
        setup = data.get("setup")
        if not isinstance(setup, str) or not _ID_RE.match(setup):
            raise refuse(f"{entry_id}: setup must name a declared setup id")
        kind = data.get("kind")
        if kind not in OPERATION_KINDS:
            raise refuse(
                f"{entry_id}: kind must be one of {', '.join(OPERATION_KINDS)} (got {kind!r}); "
                f"each later kind is a contract amendment (CAM.md §3.7)"
            )
        feature = _parse_anchor(entry_id, data.get("feature"), fieldname="feature", refuse=refuse)
        _part, _sep, selector = feature.partition(ANCHOR_SEPARATOR)
        if not _sep:
            raise refuse(
                f"{entry_id}: feature must be 'part{ANCHOR_SEPARATOR}tag' — an operation "
                f"references a §5.3 tag, and only a tag (CAM.md §3.7)"
            )
        validate_feature_tag(entry_id, cast("str", kind), selector)
        tool = data.get("tool")
        if not isinstance(tool, str) or not _ID_RE.match(tool):
            raise CamError(
                f"{entry_id}: tool must be a tools-registry record id (got {tool!r})",
                reason="invalid_tool_ref",
                data={"operation": entry_id},
            )
        depth = _parse_number(entry_id, data, "depth_mm", refuse, required=True)
        assert depth is not None
        stepdown = _parse_number(entry_id, data, "stepdown_mm", refuse, required=kind != "drill")
        stepover = _parse_number(
            entry_id, data, "stepover_mm", refuse, required=kind in ("pocket", "face")
        )
        climb = data.get("climb", True)
        if not isinstance(climb, bool):
            raise refuse(f"{entry_id}: climb is declared true or false — never inferred")
        tabs = _parse_tabs(entry_id, data.get("tabs"), cast("str", kind), refuse)
        feeds: dict[str, float] = {}
        for name in _FEED_FIELDS:
            value = _parse_number(entry_id, data, name, refuse, required=False)
            if value is not None:
                feeds[name] = value
        withdrawn, withdrawn_reason = _parse_withdrawal(entry_id, data, refuse)
        return cls(
            id=entry_id,
            setup=setup,
            kind=cast("str", kind),
            feature=feature,
            tool=tool,
            depth_mm=depth,
            stepdown_mm=stepdown,
            stepover_mm=stepover,
            climb=climb,
            tabs=tabs,
            feeds=feeds,
            provenance=_parse_provenance(entry_id, data.get("provenance"), refuse),
            note=_parse_note(entry_id, data, refuse),
            withdrawn=withdrawn,
            withdrawn_reason=withdrawn_reason,
        )


def _parse_tabs(
    entry_id: str,
    raw: JSONValue | None,
    kind: str,
    refuse: Callable[[str], CamError],
) -> dict[str, JSONValue] | None:
    if raw is None:
        return None
    if kind != "profile":
        raise refuse(f"{entry_id}: tabs are declared on profile operations only")
    if not isinstance(raw, dict):
        raise refuse(f"{entry_id}: tabs must be an object (count, width_mm, height_mm)")
    block = cast("Mapping[str, JSONValue]", raw)
    unknown = sorted(set(block) - {"count", "width_mm", "height_mm"})
    if unknown:
        raise refuse(f"{entry_id}: unknown tabs field(s) {', '.join(unknown)}")
    count = block.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise refuse(f"{entry_id}: tabs.count must be a positive integer")
    width = _parse_number(entry_id, block, "width_mm", refuse, required=True)
    height = _parse_number(entry_id, block, "height_mm", refuse, required=True)
    assert width is not None and height is not None
    return {"count": count, "width_mm": width, "height_mm": height}


def operation_pass_bound(
    entry: OperationEntry, stock_extents_mm: tuple[float, float, float]
) -> tuple[int, int, int]:
    """``(levels, loops_bound, passes)`` — the §4.3 closed-form sieve inputs.

    Pure arithmetic over the entry's own declared numbers and the named
    stock's extents; deliberately loose (the stock cross-section over-bounds
    any pocket footprint) and deliberately **not** the sample cap.
    """
    stepdown = entry.stepdown_mm if entry.stepdown_mm is not None else entry.depth_mm
    stepover = entry.stepover_mm if entry.stepover_mm is not None else entry.depth_mm
    levels = math.ceil(entry.depth_mm / stepdown)
    loops_bound = math.ceil(min(stock_extents_mm[0], stock_extents_mm[1]) / (2.0 * stepover))
    return levels, loops_bound, levels * loops_bound


# --------------------------------------------------------------------------
# the generic ledger (the constraints.py generation machinery, per kind)


@dataclass(frozen=True)
class CamChange:
    """What produced one generation: the act, the entry id, the stated reason."""

    kind: Literal["declare", "update", "withdraw"]
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
    def from_json(cls, data: JSONValue | None) -> CamChange | None:
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
class CamLedgerState:
    """One immutable generation of one CAM ledger."""

    kind_label: str
    artifact_kind: str
    generation: int
    entries: tuple[CamEntry, ...]
    blob: str | None
    parent: str | None = None
    change: CamChange | None = None

    @property
    def artifact_ref(self) -> str | None:
        if self.blob is None:
            return None
        return make_artifact_ref(self.artifact_kind, self.blob)

    @property
    def by_id(self) -> dict[str, CamEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def active(self) -> tuple[CamEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.withdrawn)

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "change": None if self.change is None else self.change.to_json(),
            "entries": [entry.to_json() for entry in self.entries],  # type: ignore[attr-defined]
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "change": None if self.change is None else cast("JSONValue", self.change.to_json()),
            "entries": [entry.to_json() for entry in self.entries],  # type: ignore[attr-defined]
        }


class CamLedger:
    """Declare / update / withdraw one CAM entry kind as immutable generations.

    The ``ConstraintSet`` machinery, parameterized by kind: CAS-swap under
    the project-config lock, WAL-idempotent on the invocation id, every
    generation pinned so "nothing is erased" survives GC.
    """

    KIND_LABEL: str = ""
    POINTER: str = ""
    ARTIFACT_KIND: str = ""
    UNKNOWN_REASON: str = ""
    INVALID_REASON: str = ""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store

    # -- per-kind seams ------------------------------------------------------

    def parse_entry(self, data: Mapping[str, JSONValue]) -> CamEntry:
        raise NotImplementedError

    def validate_declaration(self, entry: CamEntry, current: CamLedgerState) -> None:
        """Cross-entry declaration checks (duplicate claims, the pass sieve)."""

    # -- reads --------------------------------------------------------------

    def state(self) -> CamLedgerState:
        blob = self._store.blobs.read_pointer(self.POINTER)
        if blob is None:
            return CamLedgerState(
                kind_label=self.KIND_LABEL,
                artifact_kind=self.ARTIFACT_KIND,
                generation=0,
                entries=(),
                blob=None,
            )
        return self._state_from_blob(blob)

    def generation(self, artifact_ref: str) -> CamLedgerState:
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise CamError(
                f"{self.KIND_LABEL} generation {artifact_ref} is not stored",
                reason=self.UNKNOWN_REASON,
            )
        return self._state_from_blob(blob)

    def history(self) -> tuple[CamLedgerState, ...]:
        chain: list[CamLedgerState] = []
        current = self.state()
        while current.blob is not None:
            chain.append(current)
            parent = current.parent
            if parent is None or not self._store.blobs.has(parent):
                break
            current = self._state_from_blob(parent)
        return tuple(reversed(chain))

    def get(self, entry_id: str) -> CamEntry:
        entries = self.state().by_id
        entry = entries.get(entry_id)
        if entry is None:
            raise AddressingError(
                f"no {self.KIND_LABEL} {entry_id!r} is declared",
                selector=entry_id,
                candidates=tuple(sorted(entries)),
            )
        return entry

    def _state_from_blob(self, blob: str) -> CamLedgerState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise CamError(
                f"{self.KIND_LABEL} state document is malformed", reason=self.INVALID_REASON
            )
        data = cast("Mapping[str, JSONValue]", raw)
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise CamError(
                f"{self.KIND_LABEL} generation must be an integer", reason=self.INVALID_REASON
            )
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise CamError(
                f"{self.KIND_LABEL} entries must be an array", reason=self.INVALID_REASON
            )
        entries = tuple(
            self.parse_entry(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_entries)
            if isinstance(item, dict)
        )
        parent = data.get("parent")
        return CamLedgerState(
            kind_label=self.KIND_LABEL,
            artifact_kind=self.ARTIFACT_KIND,
            generation=generation,
            entries=entries,
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
            change=CamChange.from_json(data.get("change")),
        )

    # -- writes -------------------------------------------------------------

    def declare(
        self, entry: Mapping[str, JSONValue], *, op_id: str | None = None
    ) -> CamLedgerState:
        parsed = self.parse_entry(entry)

        def apply(current: CamLedgerState) -> tuple[CamEntry, ...]:
            if parsed.id in current.by_id:
                raise CamError(
                    f"{self.KIND_LABEL} {parsed.id} is already declared — revise it with the "
                    "update tool so the change records a reason",
                    reason=self.INVALID_REASON,
                )
            self.validate_declaration(parsed, current)
            return (*current.entries, parsed)

        return self._mutate(
            CamChange(kind="declare", id=parsed.id, patch=parsed.to_json()),  # type: ignore[attr-defined]
            apply,
            op_id=op_id,
        )

    def update(
        self,
        entry_id: str,
        patch: Mapping[str, JSONValue],
        reason: str,
        *,
        op_id: str | None = None,
    ) -> CamLedgerState:
        if not reason.strip():
            raise CamError(
                f"{self.KIND_LABEL} {entry_id}: update requires a reason",
                reason=self.INVALID_REASON,
            )
        cleaned = {name: value for name, value in patch.items() if value is not None}
        if not cleaned:
            raise CamError(
                f"{self.KIND_LABEL} {entry_id}: update patches nothing",
                reason=self.INVALID_REASON,
            )
        if "id" in cleaned:
            raise CamError(
                f"{self.KIND_LABEL} {entry_id}: id is not patchable — declare a new entry "
                "and withdraw this one",
                reason=self.INVALID_REASON,
            )
        if cleaned.get("withdrawn") is True and "withdrawn_reason" not in cleaned:
            cleaned["withdrawn_reason"] = reason

        def apply(current: CamLedgerState) -> tuple[CamEntry, ...]:
            existing = self._require(current, entry_id)
            merged: dict[str, JSONValue] = dict(existing.to_json())  # type: ignore[attr-defined]
            merged.update(cleaned)
            updated = self.parse_entry(merged)
            if not existing.withdrawn:
                self.validate_declaration(
                    updated,
                    replace(
                        current, entries=tuple(e for e in current.entries if e.id != entry_id)
                    ),
                )
            return tuple(updated if e.id == entry_id else e for e in current.entries)

        return self._mutate(
            CamChange(
                kind="update",
                id=entry_id,
                reason=reason,
                patch=cast("Mapping[str, JSONValue]", dict(sorted(cleaned.items()))),
            ),
            apply,
            op_id=op_id,
        )

    def withdraw(self, entry_id: str, reason: str, *, op_id: str | None = None) -> CamLedgerState:
        if not reason.strip():
            raise CamError(
                f"{self.KIND_LABEL} {entry_id}: withdrawal requires a reason",
                reason=self.INVALID_REASON,
            )

        def apply(current: CamLedgerState) -> tuple[CamEntry, ...]:
            existing = self._require(current, entry_id)
            if existing.withdrawn:
                raise CamError(
                    f"{self.KIND_LABEL} {entry_id} is already withdrawn",
                    reason=self.INVALID_REASON,
                )
            updated = replace(existing, withdrawn=True, withdrawn_reason=reason)
            return tuple(updated if e.id == entry_id else e for e in current.entries)

        return self._mutate(
            CamChange(kind="withdraw", id=entry_id, reason=reason), apply, op_id=op_id
        )

    # -- the one generation-advancing path ----------------------------------

    def _mutate(
        self,
        change: CamChange,
        apply: Callable[[CamLedgerState], tuple[CamEntry, ...]],
        *,
        op_id: str | None,
    ) -> CamLedgerState:
        if op_id is None:
            return self._publish(change, apply)
        payload: JSONValue = {
            "kind": f"cam_{self.KIND_LABEL}_write",
            "change": change.to_json(),
        }
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            return self._replayed(outcome.response)
        if not isinstance(outcome, Fresh):
            raise CamError(
                f"{self.KIND_LABEL} write {op_id!r} cannot proceed: prior state {outcome!r}",
                reason=self.INVALID_REASON,
            )
        locks = LockManager(self._store)
        try:
            with locks.holding(PROJECT_CONFIG_LOCK):
                current = self.state()
                candidate, new_blob = self._candidate(current, change, apply)
                self._store.wal.publish(
                    outcome,
                    self.POINTER,
                    current.blob,
                    new_blob,
                    intended_outcome=canonical_json(
                        {"generation": candidate.generation, "state": new_blob}
                    ),
                )
                return candidate
        except CamError:
            self._store.wal.recover(outcome.op_key)
            raise

    def _publish(
        self,
        change: CamChange,
        apply: Callable[[CamLedgerState], tuple[CamEntry, ...]],
    ) -> CamLedgerState:
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            candidate, new_blob = self._candidate(current, change, apply)
            self._store.blobs.cas_swap(self.POINTER, current.blob, new_blob)
            return candidate

    def _candidate(
        self,
        current: CamLedgerState,
        change: CamChange,
        apply: Callable[[CamLedgerState], tuple[CamEntry, ...]],
    ) -> tuple[CamLedgerState, str]:
        entries = apply(current)
        candidate = CamLedgerState(
            kind_label=self.KIND_LABEL,
            artifact_kind=self.ARTIFACT_KIND,
            generation=current.generation + 1,
            entries=entries,
            blob=None,
            parent=current.blob,
            change=change,
        )
        new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
        self._store.gc.pin(new_blob)
        if current.blob is not None:
            self._store.gc.link(new_blob, current.blob)
        return replace(candidate, blob=new_blob), new_blob

    def _replayed(self, response: str | None) -> CamLedgerState:
        if response is not None:
            decoded: Mapping[str, JSONValue] = {}
            try:
                decoded = cast("Mapping[str, JSONValue]", json.loads(response))
            except (ValueError, TypeError):  # pragma: no cover - responses are our own JSON
                pass
            recorded = decoded.get("state")
            if isinstance(recorded, str) and self._store.blobs.has(recorded):
                return self._state_from_blob(recorded)
        return self.state()

    def _require(self, current: CamLedgerState, entry_id: str) -> CamEntry:
        existing = current.by_id.get(entry_id)
        if existing is None:
            raise CamError(
                f"no {self.KIND_LABEL} {entry_id!r} is declared (known: {sorted(current.by_id)})",
                reason=self.UNKNOWN_REASON,
            )
        return existing


class SetupSet(CamLedger):
    KIND_LABEL = "setup"
    POINTER = "cam-setups-state"
    ARTIFACT_KIND = "cam_setups"
    UNKNOWN_REASON = "unknown_setup"
    INVALID_REASON = "invalid_setup"

    def parse_entry(self, data: Mapping[str, JSONValue]) -> SetupEntry:
        return SetupEntry.from_json(data)


class StockSet(CamLedger):
    KIND_LABEL = "stock"
    POINTER = "cam-stock-state"
    ARTIFACT_KIND = "cam_stock"
    UNKNOWN_REASON = "unknown_stock"
    INVALID_REASON = "invalid_stock"

    def parse_entry(self, data: Mapping[str, JSONValue]) -> StockEntry:
        return StockEntry.from_json(data)


class FixtureSet(CamLedger):
    KIND_LABEL = "fixture"
    POINTER = "cam-fixtures-state"
    ARTIFACT_KIND = "cam_fixtures"
    UNKNOWN_REASON = "unknown_fixture"
    INVALID_REASON = "invalid_fixture"

    def parse_entry(self, data: Mapping[str, JSONValue]) -> FixtureEntry:
        return FixtureEntry.from_json(data)


class WcsSet(CamLedger):
    KIND_LABEL = "wcs"
    POINTER = "cam-wcs-state"
    ARTIFACT_KIND = "cam_wcs"
    UNKNOWN_REASON = "unknown_wcs"
    INVALID_REASON = "invalid_wcs"

    def parse_entry(self, data: Mapping[str, JSONValue]) -> WcsEntry:
        return WcsEntry.from_json(data)


class OperationSet(CamLedger):
    """Operations carry the two cross-ledger declaration checks (CAM.md §3.7/§4.3).

    Constructed with the setup and stock sets (the ``PoseSet(…, joints)``
    precedent) because ``duplicate_feature_claim`` reads sibling operations
    and ``op_sample_bound_exceeded`` reads the named stock's ``extents_mm`` —
    entries the operation names, still with no geometry and no registry.
    """

    KIND_LABEL = "operation"
    POINTER = "cam-operations-state"
    ARTIFACT_KIND = "cam_operations"
    UNKNOWN_REASON = "unknown_operation"
    INVALID_REASON = "invalid_operation"

    def __init__(
        self, layout: ProjectLayout, store: OpStore, setups: SetupSet, stock: StockSet
    ) -> None:
        super().__init__(layout, store)
        self._setups = setups
        self._stock = stock

    def parse_entry(self, data: Mapping[str, JSONValue]) -> OperationEntry:
        return OperationEntry.from_json(data)

    def validate_declaration(self, entry: CamEntry, current: CamLedgerState) -> None:
        operation = cast("OperationEntry", entry)
        for sibling in current.active:
            other = cast("OperationEntry", sibling)
            if other.setup == operation.setup and other.feature == operation.feature:
                raise CamError(
                    f"operation {operation.id}: feature {operation.feature!r} in setup "
                    f"{operation.setup!r} is already claimed by operation {other.id!r} — "
                    f"roughing plus finishing on one feature is a Stage 14 exclusion "
                    f"(CAM.md §3.7)",
                    reason="duplicate_feature_claim",
                    data={
                        "operation": operation.id,
                        "claimed_by": other.id,
                        "feature": operation.feature,
                        "setup": operation.setup,
                    },
                )
        self._check_pass_bound(operation)

    def _check_pass_bound(self, operation: OperationEntry) -> None:
        """The §4.3 closed-form sieve: entry numbers and stock extents only.

        Runs against an **unbuilt** project by construction — nothing here
        opens an artifact, a registry or the kernel. When the named setup or
        its stock is not (yet) declared the sieve has no extents to read and
        passes; the reference is a resolution-time question, and the sieve is
        a deliberately loose early kill, not a gate.
        """
        setup = self._setups.state().by_id.get(operation.setup)
        if setup is None or setup.withdrawn:
            return
        stock = self._stock.state().by_id.get(cast("SetupEntry", setup).stock)
        if stock is None or stock.withdrawn:
            return
        extents = cast("StockEntry", stock).extents_mm
        levels, loops_bound, passes = operation_pass_bound(operation, extents)
        if passes > CAM_OP_PASS_BOUND_MAX:
            raise CamError(
                f"operation {operation.id}: {levels} levels x {loops_bound} bounded loops "
                f"= {passes} passes exceeds CAM_OP_PASS_BOUND_MAX = {CAM_OP_PASS_BOUND_MAX} "
                f"(CAM.md §4.3) — computed from the entry's own numbers and stock "
                f"{stock.id!r} extents, nothing else",
                reason="op_sample_bound_exceeded",
                data={
                    "operation": operation.id,
                    "levels": levels,
                    "loops_bound": loops_bound,
                    "passes": passes,
                    "bound": CAM_OP_PASS_BOUND_MAX,
                },
            )


class CamState:
    """The five CAM ledgers of one project, wired together once."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self.setups = SetupSet(layout, store)
        self.stock = StockSet(layout, store)
        self.fixtures = FixtureSet(layout, store)
        self.wcs = WcsSet(layout, store)
        self.operations = OperationSet(layout, store, self.setups, self.stock)

    def ledgers(self) -> tuple[CamLedger, ...]:
        return (self.setups, self.stock, self.fixtures, self.wcs, self.operations)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "setups": self.setups.state().to_json(),
            "stock": self.stock.state().to_json(),
            "fixtures": self.fixtures.state().to_json(),
            "wcs": self.wcs.state().to_json(),
            "operations": self.operations.state().to_json(),
        }


def entry_views(entries: Sequence[CamEntry]) -> list[dict[str, JSONValue]]:
    """Entries as plain JSON objects (the shape tools and the CLI emit)."""
    return [entry.to_json() for entry in entries]  # type: ignore[attr-defined]
