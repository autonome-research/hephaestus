# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Placement proposals: a measurement artifact that nothing applies.

``SOLVER.md`` §8. A proposal is an immutable content-addressed document,
``artifact:placement-proposal:sha256:…``, held in generational state on the
requirement-ledger pattern the constraint set already copies
(``project_store/constraints.py:1-37``): every generation names its parent, a
withdrawal is a new generation rather than an erasure, and every older
generation stays readable forever.

**What a proposal is.** The serialised form of a solve record (``SOLVER.md``
§7.0): the request, the extracted frames the iteration consumed, the returned
transforms, and — the part that matters — the residuals an INDEPENDENT process
re-measured through the ordinary :mod:`hephaestus.core.assembly` path, each
beside the bound it was tested against. It binds every source part's
``artifact_ref`` at solve time, the constraint and joint generations, the
toolchain hash and the solver version, and compulsory provenance on the 8C
taxonomy — a requirement id, or ``assumed`` with a reason — because a solve is
an interpretation of intent for the same reason a constraint is.

**What a proposal may never do**, and how each is made structural rather than
promised:

* **It is never a verdict.** Nothing here writes an ``AssemblyStatus`` row, and
  no tool accepts a proposal id where a constraint id is expected. The row
  keeps saying ``violated`` until a rebuilt script measures otherwise.
* **It clears nothing.** The ``VALIDATION.md:285-296`` clearing rule verbatim:
  a violated constraint clears by a later successful build that measures
  otherwise, or by an explicit operator dismissal, and there is no
  model-facing write that clears one.
* **It carries no source text.** :data:`PROPOSAL_DOCUMENT_SCHEMA` is
  ``additionalProperties: false`` **at every level**, and
  :func:`validate_document` is applied to every document before it is stored —
  so a ``suggested_edit`` field is not refused at runtime by a name, it is
  unrepresentable. That is the whole of the writeback refusal on this side:
  there is no inverse from a transform to a script expression, a +0.42 mm X
  delta can be authored four different ways with three different consequences
  for other parts, and Stage 13 refuses to guess which. Applying a proposal is
  an authoring act through ``edit_part`` / ``set_params``, where it shows up in
  git as a diff a reviewer can read.
* **It is never an input to a build.** Not in ``input_hashes``, not readable
  from a part script, not readable from ``CHECKS``.

**Staleness has two faces and only one is a refusal** (``SOLVER.md`` §8).
``stale_proposal_inputs`` is a *solve-time* refusal raised by
:mod:`hephaestus.core.placement` when a concurrent build republishes geometry
underneath a running solve. ``stale: true`` is a *read-time fact* about a
proposal that was valid when written and whose bound refs have since moved:
:func:`proposal_views` computes it by comparing bound refs against current
ones, the proposal stays readable, and no verdict changes. **DECISION**: no new
``ProjectionState`` field — proposals are immutable and their inputs are
already bound, so freshness is a pure function of the current refs, and a
projection field would be a second cache-shaped copy of a fact that can be
recomputed exactly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal, cast

from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.artifact_kinds import record_artifact_kind
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

__all__ = [
    "PROPOSALS_POINTER",
    "PROPOSAL_ARTIFACT_KIND",
    "PROPOSAL_DOCUMENT_SCHEMA",
    "PROPOSAL_ID_PATTERN",
    "PROPOSAL_REF_PREFIX",
    "ProposalChange",
    "ProposalEntry",
    "ProposalError",
    "ProposalSet",
    "ProposalState",
    "proposal_views",
    "validate_document",
]

#: CAS pointer naming the current proposal-set generation's state blob.
PROPOSALS_POINTER: Final[str] = "proposals-state"

#: Artifact kind of one immutable proposal document.
PROPOSAL_ARTIFACT_KIND: Final[str] = "placement-proposal"
PROPOSAL_REF_PREFIX: Final[str] = f"artifact:{PROPOSAL_ARTIFACT_KIND}:"

#: Artifact kind of an immutable proposal-SET generation document (the index).
PROPOSAL_SET_ARTIFACT_KIND: Final[str] = "placement-proposals"

#: A proposal id is derived from its own document hash, so two solves that
#: computed the same thing are the same proposal rather than two.
PROPOSAL_ID_PATTERN: Final[str] = r"^p-[0-9a-f]{12}$"
_ID_RE: Final[re.Pattern[str]] = re.compile(PROPOSAL_ID_PATTERN)

ProposalRefusal = Literal["invalid_proposal", "unknown_proposal"]


class ProposalError(ValidationError):
    """A proposal write or read was refused; ``reason`` is the machine token."""

    def __init__(self, message: str, *, reason: ProposalRefusal = "invalid_proposal") -> None:
        super().__init__(message, kind="contract")
        self.reason: ProposalRefusal = reason


# --------------------------------------------------------------------------
# the document schema — closed at every level, which IS the guarantee


def _closed(properties: Mapping[str, JSONValue], required: Sequence[str]) -> dict[str, JSONValue]:
    """One object shape that cannot grow a field.

    ``additionalProperties: false`` everywhere, deliberately deviating from the
    repo's *tool result* convention where no result schema closes its shape
    (measured 2026-08-30: of the 55 ``schemas/tools/*.schema.json``, none
    closes its ``result``). The direction of the deviation is the point:
    results are open, this artifact is closed, because a content-addressed
    artifact document whose shape is open cannot be a closed vocabulary and
    "carries no source text" would be a promise instead of a fact.
    """
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


_NUM: Final[dict[str, JSONValue]] = {"type": "number"}
_STR: Final[dict[str, JSONValue]] = {"type": "string"}
_INT: Final[dict[str, JSONValue]] = {"type": "integer"}
_BOOL: Final[dict[str, JSONValue]] = {"type": "boolean"}
_VEC3: Final[dict[str, JSONValue]] = {
    "type": "array",
    "items": _NUM,
    "minItems": 3,
    "maxItems": 3,
}
_NUMS: Final[dict[str, JSONValue]] = {"type": "array", "items": _NUM}
_STRS: Final[dict[str, JSONValue]] = {"type": "array", "items": _STR}
#: ``{part: artifact_ref}``. The VALUE pattern is pinned to a ref rather than
#: left as a bare string: a map is the one place in a closed schema where a
#: string could otherwise be smuggled, and "the record carries no source text"
#: has to be true of every reachable slot or it is not true.
_REF_MAP: Final[dict[str, JSONValue]] = {
    "type": "object",
    "propertyNames": {"pattern": r"^[A-Za-z_][A-Za-z0-9_]*$"},
    "additionalProperties": {
        "anyOf": [
            {"type": "string", "pattern": r"^artifact:[a-z-]+:sha256:[0-9a-f]{64}$"},
            {"type": "string", "maxLength": 0},
        ]
    },
}
_NUM_MAP: Final[dict[str, JSONValue]] = {"type": "object", "additionalProperties": _NUM}
_NAMED_NUMBER: Final[dict[str, JSONValue]] = {
    "type": "array",
    "items": {"anyOf": [_STR, _NUM]},
    "minItems": 2,
    "maxItems": 2,
}

_PROVENANCE: Final[dict[str, JSONValue]] = _closed(
    {"requirement": _STR, "assumed": _BOOL, "reason": _STR}, []
)

_FRAME: Final[dict[str, JSONValue]] = _closed(
    {
        "id": _STR,
        "kind": _STR,
        "part_a": _STR,
        "part_b": _STR,
        "point_a": _VEC3,
        "dir_a": _VEC3,
        "u_a": _VEC3,
        "v_a": _VEC3,
        "point_b": _VEC3,
        "dir_b": _VEC3,
        "target": _VEC3,
    },
    ["id", "kind", "part_a", "part_b"],
)

_VARIABLE: Final[dict[str, JSONValue]] = _closed(
    {
        "name": _STR,
        "unit": _STR,
        "lower": {"anyOf": [_NUM, {"type": "null"}]},
        "upper": {"anyOf": [_NUM, {"type": "null"}]},
    },
    ["name", "unit"],
)

_WEIGHT: Final[dict[str, JSONValue]] = _closed(
    {"key": _STR, "unit": _STR, "weight": _NUM}, ["key", "unit", "weight"]
)

_NULL_DIRECTION: Final[dict[str, JSONValue]] = _closed(
    {"label": _STR, "components": {"type": "array", "items": _NAMED_NUMBER}},
    ["label", "components"],
)

_SOLVER_RESIDUAL: Final[dict[str, JSONValue]] = _closed(
    {"key": _STR, "measured": _NUM, "within_bound": _BOOL},
    ["key", "measured", "within_bound"],
)

_PART_TRANSFORM: Final[dict[str, JSONValue]] = _closed(
    {
        "part": _STR,
        # The transform itself, as three rows of [R | t] — the same plain-float
        # shape ``geom.kinematics.RigidTransform`` carries, so it can be
        # asserted against a hand-computed matrix without OCP in the loop.
        "rows": {"type": "array", "items": _NUMS, "minItems": 3, "maxItems": 3},
        # ``SOLVER.md`` §8: decomposed into translation (mm) plus axis-angle
        # (axis, degrees) FOR HUMAN LEGIBILITY, and saying nothing about which
        # statement to edit. Nobody reads a 3x4 matrix; nobody can author one
        # either, which is the same fact from the other side.
        "translation_mm": _VEC3,
        "axis": _VEC3,
        "angle_deg": _NUM,
    },
    ["part", "rows", "translation_mm", "axis", "angle_deg"],
)

#: One free ``Param``'s proposed value, beside the box it declared
#: (``SOLVER.md`` §2C). The parameter-space twin of :data:`_PART_TRANSFORM`,
#: and it says exactly as little about authoring: a name and a number, never
#: which statement to edit. ``integral`` is recorded rather than acted on — an
#: integer ``Param`` whose proposal is fractional says so instead of being
#: rounded to a value nothing verified.
_PARAM_VALUE: Final[dict[str, JSONValue]] = _closed(
    {
        "name": _STR,
        "scope": {"enum": ["part", "project"]},
        "part": _STR,
        "param": _STR,
        "value": _NUM,
        "min": _NUM,
        "max": _NUM,
        "integral": _BOOL,
    },
    ["name", "scope", "param", "value", "min", "max"],
)

_PLACEMENT: Final[dict[str, JSONValue]] = _closed(
    {
        "from_start": _STR,
        "parts": {"type": "array", "items": _PART_TRANSFORM},
        # Parameter space's answer, in its own coordinates. Exactly one of
        # ``parts`` and ``parameters`` is present, decided by the document's
        # ``space`` — a rule this schema cannot state (the validator's subset
        # has no ``if``/``then``, deliberately: a keyword it silently ignored
        # would make the schema a comment) and :func:`validate_document`
        # enforces in code, by name, right after the schema pass.
        "parameters": {"type": "array", "items": _PARAM_VALUE},
        "distance_from_as_built": _NUM,
        "iterations": _INT,
        "dof_remaining": _INT,
        "bounds_active": _STRS,
        # Always false. ``SOLVER.md`` §6.1 verdict 3: all solutions are
        # returned and NONE is chosen — the field exists so that the absence of
        # a choice is stated rather than inferred from a missing key.
        "chosen": _BOOL,
    },
    ["from_start", "chosen"],
)

_VERIFIED_COMPONENT: Final[dict[str, JSONValue]] = _closed(
    {
        "key": _STR,
        "role": _STR,
        "unit": _STR,
        "measured": _NUM,
        "bound": _NUM,
        "within_bound": _BOOL,
        "solver": _NUM,
    },
    ["key", "role", "unit", "measured", "bound", "within_bound", "solver"],
)

_VERIFIED_CONSTRAINT: Final[dict[str, JSONValue]] = _closed(
    {
        "id": _STR,
        "kind": _STR,
        "measured": _NUM,
        "unit": _STR,
        "slack": _NUM,
        # What the verdict is READ FROM (``SOLVER.md`` §7.4) — never the
        # residual number, because a same-facing ``coincident`` pair measures a
        # genuinely zero gap and is still not a mate.
        "satisfied": _BOOL,
        "declared": {"type": "array", "items": _NAMED_NUMBER},
        "values": {"type": "array", "items": _NAMED_NUMBER},
        "components": {"type": "array", "items": _VERIFIED_COMPONENT},
    },
    ["id", "kind", "measured", "unit", "slack", "satisfied"],
)

_POINT_RESULT: Final[dict[str, JSONValue]] = _closed(
    {
        "id": _STR,
        "error_mm": _NUM,
        "bound": _NUM,
        "within_bound": _BOOL,
        "solver": _NUM,
        "point_mm": _VEC3,
    },
    ["id", "error_mm", "bound", "within_bound"],
)

#: One preview build a solve or a verification pass issued (``SOLVER.md`` §2C).
#: ``current`` is publication's own answer and is asserted ``false`` by G13C
#: clause 46: every candidate is a preview, so a solve can measure geometry
#: without ever becoming the geometry.
_PREVIEW_BUILD: Final[dict[str, JSONValue]] = _closed(
    {
        "part": _STR,
        "params": _NUM_MAP,
        "project_params": _NUM_MAP,
        "status": _STR,
        "current": _BOOL,
        "artifact_ref": {
            "anyOf": [
                {"type": "string", "pattern": r"^artifact:[a-z-]+:sha256:[0-9a-f]{64}$"},
                {"type": "string", "maxLength": 0},
            ]
        },
    },
    ["part", "current"],
)

_VERIFICATION_FIELDS: Final[dict[str, JSONValue]] = {
    "constraints": {"type": "array", "items": _VERIFIED_CONSTRAINT},
    # Parameter space only: the builds the VERIFYING process issued, so the
    # preview guarantee is checkable on both sides rather than only on the
    # solver's.
    "preview_builds": {"type": "array", "items": _PREVIEW_BUILD},
    "points": {"type": "array", "items": _POINT_RESULT},
    # ``SOLVER.md`` §7.3: the plateau and pose-invariant kinds excluded from
    # the objective are EVALUATED here anyway. A proposal that satisfies four
    # mates and drives two parts into each other says so, in these rows.
    "collateral": {"type": "array", "items": _VERIFIED_CONSTRAINT},
    "import_closure_excludes_geom_solve": _BOOL,
    "worst_disagreement": _NUM,
    "determinism_tier": {"enum": ["D2"]},
}
_VERIFICATION_REQUIRED: Final[tuple[str, ...]] = (
    "constraints",
    "import_closure_excludes_geom_solve",
    "determinism_tier",
)

#: One returned solution's verification block. Closed like everything else —
#: a nested OPEN object would be a hole in the guarantee exactly where nobody
#: looks, which is where a hole would survive.
_VERIFIED_ONE: Final[dict[str, JSONValue]] = _closed(_VERIFICATION_FIELDS, _VERIFICATION_REQUIRED)

_VERIFICATION: Final[dict[str, JSONValue]] = _closed(
    {
        **_VERIFICATION_FIELDS,
        # The primary solution's block is inlined above; this carries EVERY
        # returned solution, because on ``multiple_solutions_from_starts`` all
        # of them are returned and none is chosen.
        "verified_placements": {"type": "array", "items": _VERIFIED_ONE},
    },
    _VERIFICATION_REQUIRED,
)

_SOLVER_CORE: Final[dict[str, JSONValue]] = _closed(
    {
        # ``SOLVER.md`` §9: the frames are INSIDE the block, because the D1
        # claim is conditional on them and a reader must be able to check the
        # condition instead of taking it on faith.
        "determinism_tier": {"enum": ["D1", "D2"]},
        "frames": {"type": "array", "items": _FRAME},
        "pivots": {"type": "object", "additionalProperties": _VEC3},
        "variables": {"type": "array", "items": _VARIABLE},
        "weights": {"type": "array", "items": _WEIGHT},
        "weighting": _STR,
        "characteristic_radius_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "regularization": _STR,
        "iteration_ceiling": _INT,
        "from_start": _STR,
        "iterations": _INT,
        "termination": _STR,
        "weighted_inf_norm": _NUM,
        "stationarity": _NUM,
        "rank": _INT,
        "dof_remaining": _INT,
        "kappa": _NUM,
        "limits_active": _STRS,
        "null_basis": {"type": "array", "items": _NULL_DIRECTION},
        "solver_residuals": {"type": "array", "items": _SOLVER_RESIDUAL},
        "x": _NUMS,
        # Parameter space only (``SOLVER.md`` §2C, §10).
        "preview_builds": {"type": "array", "items": _PREVIEW_BUILD},
        "builds_issued": _INT,
        "build_budget": _INT,
    },
    ["determinism_tier", "frames", "variables", "weights"],
)

_REQUEST: Final[dict[str, JSONValue]] = _closed(
    {
        "space": _STR,
        "constraints": _STRS,
        "free": _STRS,
        "ground": _STRS,
        "tol": _NUM,
        "weighting": _STR,
        "weights": {"anyOf": [_NUM_MAP, {"type": "null"}]},
        "regularization": _STR,
        "provenance": _PROVENANCE,
        "starts": {
            "type": "array",
            "items": _closed({"id": _STR, "values": _NUM_MAP}, ["id"]),
        },
        "ceiling": {"anyOf": [_INT, {"type": "null"}]},
        "build_budget": {"anyOf": [_INT, {"type": "null"}]},
        "box": {
            "anyOf": [
                {
                    "type": "object",
                    "propertyNames": {"pattern": r"^[A-Za-z_][A-Za-z0-9_]*\.(tx|ty|tz|rx|ry|rz)$"},
                    "additionalProperties": {
                        "type": "array",
                        "items": {"anyOf": [_NUM, {"type": "null"}]},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                {"type": "null"},
            ]
        },
    },
    ["space", "constraints", "free", "ground", "tol", "weighting", "regularization"],
)

#: The canonical placement-proposal document schema (``SOLVER.md`` §8).
#:
#: There is no ``suggested_edit`` here, no ``source``, no ``patch`` and no
#: ``script`` — and because every object in it is ``additionalProperties:
#: false`` and :func:`validate_document` runs before any write, there cannot be
#: one. That absence is the writeback refusal, made structural. ``SOLVER.md``
#: §6.3 records why the earlier draft's ``no_writeback_grammar`` refusal NAME
#: was removed rather than kept as decoration: a refusal nobody can trigger is
#: not a safeguard; a schema that cannot express the field is.
PROPOSAL_DOCUMENT_SCHEMA: Final[Mapping[str, JSONValue]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://hephaestus.dev/schemas/placement-proposal.schema.json",
    "title": "placement proposal",
    "description": (
        "An immutable, content-addressed measurement artifact: candidate placements "
        "with the residuals an independent process re-measured for them. Nothing "
        "applies it. It carries no source text and no suggested edit, and this "
        "schema is closed at every level so that it cannot."
    ),
    **_closed(
        {
            "space": {"enum": ["transform", "parameters"]},
            "verdict": _STR,
            "detail": _STR,
            "reason": _STR,
            "subject": _STR,
            "request": _REQUEST,
            "provenance": _PROVENANCE,
            "solver_core": _SOLVER_CORE,
            "verification": _VERIFICATION,
            "placements": {"type": "array", "items": _PLACEMENT},
            # ``SOLVER.md`` §8 binds ``nonsmooth_terms`` compulsorily, and §3.2
            # says what they cost: a ``distance`` term is a LOCAL model. Both
            # the list and the caveat live in the document, because a reader
            # who has only the proposal must be able to see which terms had a
            # kink in them without going back to the spec.
            "nonsmooth_terms": _STRS,
            "nonsmooth_caveat": _STR,
            "constraint_generation": _INT,
            "joint_generation": _INT,
            "artifact_refs": _REF_MAP,
            "toolchain": _STR,
            "solver_version": _STR,
            # ``SOLVER.md`` §9: replay evidence about the RUN, stored beside
            # this document rather than in it. A ref, never a payload, and
            # pattern-pinned like every other ref here so the slot cannot
            # carry text.
            "solver_trace_ref": {
                "type": "string",
                "pattern": r"^artifact:solve-trace:sha256:[0-9a-f]{64}$",
            },
        },
        [
            "space",
            "verdict",
            "request",
            "provenance",
            "solver_core",
            "verification",
            "placements",
            "constraint_generation",
            "artifact_refs",
            "toolchain",
            "solver_version",
        ],
    ),
}


def validate_document(document: Mapping[str, JSONValue]) -> None:
    """Refuse a proposal document that :data:`PROPOSAL_DOCUMENT_SCHEMA` does not admit.

    Hand-rolled rather than delegated to ``jsonschema``, which is a *dev*
    dependency of this workspace and not a runtime one — adding a runtime
    dependency to close a shape would be mission rule 7 territory for a job
    ninety lines of recursion already does. The subset understood here is
    exactly the subset the schema above uses: ``type``, ``properties``,
    ``required``, ``additionalProperties`` (``false`` or a sub-schema),
    ``propertyNames``, ``items``, ``minItems``/``maxItems``, ``pattern``,
    ``maxLength``, ``enum`` and ``anyOf`` — every keyword the schema actually
    states, because a validator that silently ignored one would make the
    schema a comment.
    """
    problem = _check(PROPOSAL_DOCUMENT_SCHEMA, cast("JSONValue", dict(document)), "$")
    if problem is None:
        problem = _check_space_shape(document)
    if problem is not None:
        raise ProposalError(
            f"the proposal document is not what SOLVER.md §8 declares: {problem}. "
            "The schema is additionalProperties: false at every level, which is how "
            '"carries no source text" is a structural fact rather than a promise'
        )


def _check_space_shape(document: Mapping[str, JSONValue]) -> str | None:
    """The one rule the schema states in code rather than in JSON Schema.

    A ``transform`` proposal's placements carry ``parts`` (a 3x4 per free part)
    and a ``parameters`` proposal's carry ``parameters`` (a value per free
    ``Param``) — never the other way round, and never both. That is a
    conditional on a sibling field, which the hand-rolled validator has no
    keyword for; adding ``if``/``then`` to it for one rule would be adding a
    keyword the rest of the schema does not use and that a later reader would
    have to verify is honoured. So the rule is enforced here, by name, and a
    gate clause asserts both directions.

    Enforcing it at all matters: a placement carrying neither would be a
    proposal that proposes nothing while still claiming a verdict.
    """
    space = document.get("space")
    wanted = "parts" if space == "transform" else "parameters"
    other = "parameters" if space == "transform" else "parts"
    for index, placement in enumerate(
        cast("Sequence[JSONValue]", document.get("placements") or ())
    ):
        body = cast("Mapping[str, JSONValue]", placement)
        if not body.get(wanted):
            return (
                f"$.placements[{index}]: a {space!r} proposal's placement must carry "
                f"a non-empty {wanted!r}"
            )
        if body.get(other) is not None:
            return (
                f"$.placements[{index}]: a {space!r} proposal's placement must not "
                f"carry {other!r} — that is the other space's answer"
            )
    return None


def _check(schema: Mapping[str, JSONValue], value: JSONValue, path: str) -> str | None:
    """``None`` when ``value`` satisfies ``schema``, else why it does not."""
    options = schema.get("anyOf")
    if isinstance(options, list):
        reasons = [
            _check(cast("Mapping[str, JSONValue]", option), value, path)
            for option in cast("list[JSONValue]", options)
        ]
        if all(reason is not None for reason in reasons):
            return f"{path}: matches none of the declared alternatives"
        return None
    allowed = schema.get("enum")
    if isinstance(allowed, list) and value not in cast("list[JSONValue]", allowed):
        return f"{path}: {value!r} is not one of {allowed!r}"
    declared = schema.get("type")
    if isinstance(declared, str) and not _is_type(declared, value):
        return f"{path}: expected {declared}, got {type(value).__name__}"
    if isinstance(value, str):
        problem = _check_string(schema, value, path)
        if problem is not None:
            return problem
    if declared == "object" or ("properties" in schema and isinstance(value, dict)):
        return _check_object(schema, value, path)
    if declared == "array" and isinstance(value, list):
        return _check_array(schema, cast("list[JSONValue]", value), path)
    return None


def _check_string(schema: Mapping[str, JSONValue], value: str, path: str) -> str | None:
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, value) is None:
        return f"{path}: {value!r} does not match {pattern}"
    longest = schema.get("maxLength")
    if isinstance(longest, int) and not isinstance(longest, bool) and len(value) > longest:
        return f"{path}: longer than the declared {longest} characters"
    return None


def _check_object(schema: Mapping[str, JSONValue], value: JSONValue, path: str) -> str | None:
    if not isinstance(value, dict):
        return f"{path}: expected an object"
    body = cast("Mapping[str, JSONValue]", value)
    properties = cast("Mapping[str, JSONValue]", schema.get("properties") or {})
    for name in cast("Sequence[str]", schema.get("required") or ()):
        if name not in body:
            return f"{path}.{name}: required and absent"
    names = schema.get("propertyNames")
    if isinstance(names, dict):
        for name in body:
            problem = _check_string(
                cast("Mapping[str, JSONValue]", names), name, f"{path}.{name} (key)"
            )
            if problem is not None:
                return problem
    extra = schema.get("additionalProperties", True)
    for name, entry in body.items():
        sub = properties.get(name)
        if sub is None:
            if extra is False:
                return (
                    f"{path}.{name}: not a declared field, and this shape is closed — "
                    "a proposal may not grow a field, source text least of all"
                )
            if isinstance(extra, dict):
                problem = _check(cast("Mapping[str, JSONValue]", extra), entry, f"{path}.{name}")
                if problem is not None:
                    return problem
            continue
        problem = _check(cast("Mapping[str, JSONValue]", sub), entry, f"{path}.{name}")
        if problem is not None:
            return problem
    return None


def _check_array(schema: Mapping[str, JSONValue], value: list[JSONValue], path: str) -> str | None:
    minimum = schema.get("minItems")
    maximum = schema.get("maxItems")
    if isinstance(minimum, int) and len(value) < minimum:
        return f"{path}: needs at least {minimum} items"
    if isinstance(maximum, int) and len(value) > maximum:
        return f"{path}: takes at most {maximum} items"
    items = schema.get("items")
    if isinstance(items, dict):
        for index, entry in enumerate(value):
            problem = _check(cast("Mapping[str, JSONValue]", items), entry, f"{path}[{index}]")
            if problem is not None:
                return problem
    return None


def _is_type(declared: str, value: JSONValue) -> bool:
    if declared == "object":
        return isinstance(value, dict)
    if declared == "array":
        return isinstance(value, list)
    if declared == "string":
        return isinstance(value, str)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if declared == "null":
        return value is None
    return True  # pragma: no cover - the schema above uses no other type


# --------------------------------------------------------------------------
# generations


@dataclass(frozen=True)
class ProposalChange:
    """What produced one generation: the act, the proposal, and the reason."""

    kind: Literal["record", "withdraw"]
    id: str
    reason: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {"kind": self.kind, "id": self.id}
        if self.reason is not None:
            out["reason"] = self.reason
        return out

    @classmethod
    def from_json(cls, data: JSONValue | None) -> ProposalChange | None:
        if not isinstance(data, dict):
            return None
        raw = cast("Mapping[str, JSONValue]", data)
        kind = raw.get("kind")
        entry_id = raw.get("id")
        if kind not in ("record", "withdraw") or not isinstance(entry_id, str):
            return None
        reason = raw.get("reason")
        return cls(kind=kind, id=entry_id, reason=reason if isinstance(reason, str) else None)


@dataclass(frozen=True)
class ProposalEntry:
    """One proposal's index row: what it is, what it bound, and whether it stands.

    The document itself is the immutable blob :attr:`ref` names. This row is
    what a reader needs before deciding to open it, and — crucially — it
    carries the **bound** artifact refs, so :func:`proposal_views` can compute
    staleness by comparison without loading anything.
    """

    id: str
    ref: str
    space: str
    verdict: str
    constraint_generation: int
    joint_generation: int
    artifact_refs: Mapping[str, str]
    parts: tuple[str, ...]
    constraints: tuple[str, ...]
    withdrawn: bool = False
    withdrawn_reason: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "ref": self.ref,
            "space": self.space,
            "verdict": self.verdict,
            "constraint_generation": self.constraint_generation,
            "joint_generation": self.joint_generation,
            "artifact_refs": {k: self.artifact_refs[k] for k in sorted(self.artifact_refs)},
            "parts": list(self.parts),
            "constraints": list(self.constraints),
        }
        if self.withdrawn:
            out["withdrawn"] = True
            out["withdrawn_reason"] = self.withdrawn_reason
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> ProposalEntry:
        entry_id = data.get("id")
        ref = data.get("ref")
        if not isinstance(entry_id, str) or not _ID_RE.match(entry_id):
            raise ProposalError(f"proposal id {entry_id!r} must match {PROPOSAL_ID_PATTERN}")
        if not isinstance(ref, str) or not ref.startswith(PROPOSAL_REF_PREFIX):
            raise ProposalError(f"proposal {entry_id}: ref must be a {PROPOSAL_REF_PREFIX}… ref")
        refs = data.get("artifact_refs")
        withdrawn = bool(data.get("withdrawn", False))
        return cls(
            id=entry_id,
            ref=ref,
            space=str(data.get("space") or "transform"),
            verdict=str(data.get("verdict") or ""),
            constraint_generation=int(cast("int", data.get("constraint_generation") or 0)),
            joint_generation=int(cast("int", data.get("joint_generation") or 0)),
            artifact_refs={
                str(part): str(value)
                for part, value in cast("Mapping[str, JSONValue]", refs or {}).items()
            },
            parts=tuple(str(part) for part in cast("Sequence[JSONValue]", data.get("parts") or ())),
            constraints=tuple(
                str(name) for name in cast("Sequence[JSONValue]", data.get("constraints") or ())
            ),
            withdrawn=withdrawn,
            withdrawn_reason=(
                str(data["withdrawn_reason"])
                if withdrawn and data.get("withdrawn_reason") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ProposalState:
    """One immutable proposal-set generation."""

    generation: int
    entries: tuple[ProposalEntry, ...]
    blob: str | None
    parent: str | None = None
    change: ProposalChange | None = None

    @property
    def artifact_ref(self) -> str | None:
        if self.blob is None:
            return None
        return make_artifact_ref(PROPOSAL_SET_ARTIFACT_KIND, self.blob)

    @property
    def by_id(self) -> dict[str, ProposalEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def open(self) -> tuple[ProposalEntry, ...]:
        """Proposals still standing. A withdrawn one stays stored and readable."""
        return tuple(entry for entry in self.entries if not entry.withdrawn)

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "change": None if self.change is None else self.change.to_json(),
            "entries": [entry.to_json() for entry in self.entries],
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "generation": self.generation,
            "artifact_ref": self.artifact_ref,
            "change": None if self.change is None else cast("JSONValue", self.change.to_json()),
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> ProposalState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ProposalError("proposal-set generation must be an integer")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise ProposalError("proposal-set entries must be an array")
        parent = data.get("parent")
        return cls(
            generation=generation,
            entries=tuple(
                ProposalEntry.from_json(cast("Mapping[str, JSONValue]", item))
                for item in cast("list[JSONValue]", raw_entries)
                if isinstance(item, dict)
            ),
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
            change=ProposalChange.from_json(data.get("change")),
        )


_EMPTY: Final[ProposalState] = ProposalState(
    generation=0, entries=(), blob=None, parent=None, change=None
)


class ProposalSet:
    """Record and withdraw placement proposals as immutable generations.

    The write surface is deliberately two verbs. There is no ``apply``, no
    ``patch`` and no ``accept``: applying a proposal is an authoring act
    performed through ``edit_part`` / ``set_params``, and a method here that
    turned a proposal into geometry would be the writeback ``SOLVER.md`` §1
    refuses, wearing a store's clothes.
    """

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store

    # -- reads --------------------------------------------------------------

    def state(self) -> ProposalState:
        blob = self._store.blobs.read_pointer(PROPOSALS_POINTER)
        if blob is None:
            return _EMPTY
        return self._state_from_blob(blob)

    def document(self, proposal_id: str) -> Mapping[str, JSONValue]:
        """The immutable document one proposal id names."""
        entry = self.state().by_id.get(proposal_id)
        if entry is None:
            raise ProposalError(
                f"no proposal {proposal_id!r} is recorded", reason="unknown_proposal"
            )
        blob = blob_hash_of_ref(entry.ref)
        if not self._store.blobs.has(blob):
            raise ProposalError(
                f"proposal {proposal_id} is indexed but its document blob is gone",
                reason="unknown_proposal",
            )
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise ProposalError(f"proposal {proposal_id}'s document is malformed")
        return cast("Mapping[str, JSONValue]", raw)

    def _state_from_blob(self, blob: str) -> ProposalState:
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise ProposalError("proposal-set state document is malformed")
        return ProposalState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    # -- writes -------------------------------------------------------------

    def record(self, document: Mapping[str, JSONValue]) -> tuple[ProposalState, ProposalEntry]:
        """Store one proposal document and index it; advances one generation.

        The document is validated against :data:`PROPOSAL_DOCUMENT_SCHEMA`
        first and refused rather than trimmed — a store that silently dropped
        an unknown field would make the closed shape a formatting convention
        instead of a guarantee.

        The id is derived from the document's own content hash, so re-running
        an identical solve records the identical proposal rather than a second
        one, and a proposal ref is a claim about bytes rather than about when
        somebody asked.
        """
        validate_document(document)
        payload = canonical_json(cast("JSONValue", document)).encode("utf-8")
        blob = self._store.blobs.put(payload)
        self._store.gc.pin(blob)
        record_artifact_kind(self._store, PROPOSAL_ARTIFACT_KIND, blob)
        entry = ProposalEntry(
            # The hex half of ``sha256:<hex>``: a short, stable, content-derived
            # handle. Deriving it from the digest rather than from a counter is
            # what makes "the same solve records the same proposal" true.
            id=f"p-{blob.rsplit(':', 1)[-1][:12]}",
            ref=make_artifact_ref(PROPOSAL_ARTIFACT_KIND, blob),
            space=str(document.get("space") or "transform"),
            verdict=str(document.get("verdict") or ""),
            constraint_generation=int(cast("int", document.get("constraint_generation") or 0)),
            joint_generation=int(cast("int", document.get("joint_generation") or 0)),
            artifact_refs={
                str(part): str(value)
                for part, value in cast(
                    "Mapping[str, JSONValue]", document.get("artifact_refs") or {}
                ).items()
            },
            # The parts this proposal is ABOUT: the ones it proposes a
            # transform for in transform space, and — in parameter space, where
            # no part moves — the ones whose geometry it bound and re-measured.
            # Left empty for 2C, an index row would say a parameter proposal
            # concerned no part, which is the opposite of true.
            parts=tuple(
                sorted(
                    {
                        str(cast("Mapping[str, JSONValue]", part)["part"])
                        for placement in cast(
                            "Sequence[JSONValue]", document.get("placements") or ()
                        )
                        for part in cast(
                            "Sequence[JSONValue]",
                            cast("Mapping[str, JSONValue]", placement).get("parts") or (),
                        )
                    }
                    or {
                        str(part)
                        for part in cast(
                            "Mapping[str, JSONValue]", document.get("artifact_refs") or {}
                        )
                    }
                )
            ),
            constraints=tuple(
                str(name)
                for name in cast(
                    "Sequence[JSONValue]",
                    cast("Mapping[str, JSONValue]", document.get("request") or {}).get(
                        "constraints"
                    )
                    or (),
                )
            ),
        )

        def apply(current: ProposalState) -> tuple[ProposalEntry, ...]:
            if entry.id in current.by_id:
                # Identical content, identical id: the same proposal, recorded
                # again. Replacing it with itself is the honest no-op; refusing
                # would make an idempotent solve look like a conflict.
                return current.entries
            return (*current.entries, entry)

        state = self._mutate(ProposalChange(kind="record", id=entry.id), apply)
        return state, state.by_id[entry.id]

    def withdraw(self, proposal_id: str, reason: str) -> ProposalState:
        """Stop standing behind one proposal; a new generation, never an erasure."""
        if not reason.strip():
            raise ProposalError(f"proposal {proposal_id}: withdrawal requires a reason")

        def apply(current: ProposalState) -> tuple[ProposalEntry, ...]:
            existing = current.by_id.get(proposal_id)
            if existing is None:
                raise ProposalError(
                    f"no proposal {proposal_id!r} is recorded", reason="unknown_proposal"
                )
            if existing.withdrawn:
                raise ProposalError(f"proposal {proposal_id} is already withdrawn")
            updated = replace(existing, withdrawn=True, withdrawn_reason=reason)
            return tuple(updated if e.id == proposal_id else e for e in current.entries)

        return self._mutate(ProposalChange(kind="withdraw", id=proposal_id, reason=reason), apply)

    def _mutate(
        self,
        change: ProposalChange,
        apply: Callable[[ProposalState], tuple[ProposalEntry, ...]],
    ) -> ProposalState:
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            entries = apply(current)
            candidate = ProposalState(
                generation=current.generation + 1,
                entries=entries,
                blob=None,
                parent=current.blob,
                change=change,
            )
            new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
            # Pinned, not merely pointer-protected: an older generation must
            # stay readable after the pointer has moved on, or "nothing is
            # erased" would be true only until the next GC pass.
            self._store.gc.pin(new_blob)
            if current.blob is not None:
                self._store.gc.link(new_blob, current.blob)
            self._store.blobs.cas_swap(PROPOSALS_POINTER, current.blob, new_blob)
            return replace(candidate, blob=new_blob)


def proposal_views(
    state: ProposalState,
    current_ref: Callable[[str], str | None],
    *,
    ids: Sequence[str] | None = None,
) -> list[dict[str, JSONValue]]:
    """Index rows with read-time staleness (``SOLVER.md`` §8).

    ``stale: true`` is a **fact, never a refusal**: a proposal that was valid
    when written and whose bound refs have since moved stays readable, and
    ``changed_refs`` names which parts moved so a reader knows what to re-run
    rather than being told only that something did. Computed by comparison
    against the parts' current refs — the ``AssemblyProjection`` staleness rule
    (``core/assembly.py:988-1000``) applied at read time rather than stored,
    because proposals are immutable and their inputs are already bound, so
    freshness is a pure function of the current refs.

    Withdrawn generations are included with their reasons, on the 8C read-tool
    shape (``KINEMATICS.md:283-288``): generational state is honest only if
    every generation stays readable.
    """
    wanted = None if ids is None else set(ids)
    if wanted is not None:
        # An id nobody recorded is REFUSED by name, never filtered away: a read
        # that silently returned nothing for a typo would look exactly like a
        # read of a project that has no proposals, and "nothing silently
        # skipped" is the rule this whole stage is written under.
        missing = sorted(wanted - set(state.by_id))
        if missing:
            raise ProposalError(
                f"no proposal(s) {', '.join(missing)} are recorded "
                f"(recorded: {', '.join(sorted(state.by_id)) or 'none'})",
                reason="unknown_proposal",
            )
    out: list[dict[str, JSONValue]] = []
    for entry in state.entries:
        if wanted is not None and entry.id not in wanted:
            continue
        changed = sorted(
            part for part, bound in entry.artifact_refs.items() if current_ref(part) != bound
        )
        view = entry.to_json()
        view["stale"] = bool(changed)
        view["changed_refs"] = list(changed)
        out.append(view)
    return out
