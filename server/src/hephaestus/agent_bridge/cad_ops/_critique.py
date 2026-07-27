"""The unrequested post-build critique (``VALIDATION.md`` §4).

Every *successful* ``build_part`` carries a ``critique`` block nobody asked
for. It exists because the reference product volunteers interference unasked
and because waiting for a confident model to choose to measure is waiting
forever: each rung below fires **by rule** in this module, so no prompt
instruction can be "followed carefully" instead.

Three rungs, all computed from data the build already produced:

``interference``
    Pairwise overlap volume across the built compound's solids (kernel
    measure, on the published artifact). A non-zero overlap is a warning with
    the pair and the volume *unless* the build declared it intentional —
    ``part.feature(<name>).intentional_overlap = True`` in the script, or a
    ledger entry that says so (``applies_to: "intentional_overlap"`` or an
    intentional-overlap phrase in its text/rationale). Pair evaluation is
    capped (:data:`MAX_INTERFERENCE_PAIRS`) so a compound of many solids
    cannot eat the 300 s CAD budget; hitting the cap is itself reported.

``manifold``
    ``sealed``/``genus``/solid count surfaced from the build metrics, with a
    warning when the geometry is not watertight.

``dfm``
    The process rule pack's findings against the artifact this build just
    published — present only when the project turns DFM mode on
    (``[dfm] auto_run = true`` in ``hephaestus.toml``) and the part declares a
    ``part.process``. Unrequested by the same rule as the rungs above: a shop
    limit the model never thought to check is exactly the one that bites. Every
    ``error``/``warning`` finding becomes a critique warning carrying its rule
    id, its offending tags and the artifact it was measured against; the block
    records ``unavailable`` instead of a clean sheet when the run could not
    happen (no secure sandbox, no pack for the process), because silence must
    never read as a pass.

``prompt_number_diff``
    Numeric values with units extracted from the **original request** and
    compared with the built dimensions. An axis-tagged request number
    (``40 mm (Y)``, "overall height is 40 mm") is compared against the bbox
    extent on that axis: disagreement is ``dimension_mismatch`` carrying both
    values, and no agreeing dimension on that axis is
    ``unmatched_request_number``. An axis-less number is matched against every
    known dimension — bbox extents, tagged edge lengths, ``CHECKS`` thresholds
    — and warns when nothing corresponds. Matching is deliberately crude
    (regex + unit normalization + a tolerance): false positives are
    acceptable, silence on a real mismatch is not. With no request text in
    hand the block is **omitted entirely** rather than faked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Final, cast

from hephaestus.core.dfm import DfmEvaluation, findings_by_severity
from hephaestus.core.types import Metrics
from opstore.types import JSONValue

from ._findings import DimensionFindingState

__all__ = [
    "DFM_WARNING_SEVERITIES",
    "MAX_INTERFERENCE_PAIRS",
    "RequestNumber",
    "critique_block",
    "dfm_report",
    "intentional_overlap_declarations",
    "interference_report",
    "manifold_report",
    "prompt_number_diff",
    "request_numbers",
    "with_dimension_findings",
]

#: Most solid pairs one critique will evaluate. Interference is a boolean
#: intersection per pair — O(n^2) in the compound's solids — and ``build_part``
#: shares one 300 s CAD budget with the build itself, so the pass is bounded
#: and says so in the block when the bound bites.
MAX_INTERFERENCE_PAIRS: Final[int] = 64

#: Overlap volumes at or below this (mm^3) are numerical noise, not a warning
#: (the same epsilon ``kernel.measure.clearance`` uses for its overlap test).
OVERLAP_EPS_MM3: Final[float] = 1e-9

#: A request number agrees with a dimension within ``max(abs, rel * value)``.
MATCH_ABS_TOL_MM: Final[float] = 0.05
MATCH_REL_TOL: Final[float] = 0.005


def _tolerance(value_mm: float) -> float:
    return max(MATCH_ABS_TOL_MM, MATCH_REL_TOL * abs(value_mm))


# --------------------------------------------------------------------------
# request-number extraction


#: Unit token -> millimetres. Angles and bare counts are deliberately absent:
#: a number without a length unit is not a dimension claim.
_UNIT_MM: Final[dict[str, float]] = {
    "mm": 1.0,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "millimetre": 1.0,
    "millimetres": 1.0,
    "cm": 10.0,
    "centimeter": 10.0,
    "centimeters": 10.0,
    "centimetre": 10.0,
    "centimetres": 10.0,
    "m": 1000.0,
    "meter": 1000.0,
    "meters": 1000.0,
    "metre": 1000.0,
    "metres": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "inches": 25.4,
    '"': 25.4,
}

_NUMBER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|metres?|meters?|m"
    r"|inches|inch|in|\")"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)

#: ``40 mm (Y)`` / ``40 mm [Y]`` immediately after the unit.
_AXIS_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"\A\s*[(\[]\s*([xyz])\s*[)\]]", re.IGNORECASE)
#: ``60 mm in X`` / ``60 mm along the Y axis``.
_AXIS_PREP_RE: Final[re.Pattern[str]] = re.compile(
    r"\A\s*(?:in|along|on)\s+(?:the\s+)?([xyz])\b", re.IGNORECASE
)
#: Dimension words that name an axis by convention (X long, Y wide/deep, Z tall).
_AXIS_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(height|heights|tall|high|width|widths|wide|length|lengths|long|depth|deep)\b",
    re.IGNORECASE,
)
_AXIS_BY_WORD: Final[dict[str, str]] = {
    "height": "z",
    "heights": "z",
    "tall": "z",
    "high": "z",
    "width": "y",
    "widths": "y",
    "wide": "y",
    "length": "x",
    "lengths": "x",
    "long": "x",
    "depth": "y",
    "deep": "y",
}
#: How far either side of a number an axis word is still taken to describe it.
_AXIS_WINDOW_AFTER: Final[int] = 24
_AXIS_WINDOW_BEFORE: Final[int] = 48

_AXES: Final[tuple[str, ...]] = ("x", "y", "z")


@dataclass(frozen=True)
class RequestNumber:
    """One dimensioned number lifted out of the original request text."""

    value_mm: float
    unit: str
    text: str
    axis: str | None
    offset: int

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "value_mm": self.value_mm,
            "unit": self.unit,
            "text": self.text,
            "axis": self.axis,
        }


def _axis_for(request: str, start: int, end: int) -> str | None:
    """Axis this number is tagged with, or None (marker > after word > before)."""
    after = request[end : end + _AXIS_WINDOW_AFTER]
    marker = _AXIS_MARKER_RE.match(after) or _AXIS_PREP_RE.match(after)
    if marker is not None:
        return marker.group(1).lower()
    word_after = _AXIS_WORD_RE.search(after)
    if word_after is not None:
        return _AXIS_BY_WORD[word_after.group(1).lower()]
    before = request[max(0, start - _AXIS_WINDOW_BEFORE) : start]
    matches = list(_AXIS_WORD_RE.finditer(before))
    if matches:
        return _AXIS_BY_WORD[matches[-1].group(1).lower()]
    return None


def request_numbers(request: str) -> tuple[RequestNumber, ...]:
    """Every dimensioned number in ``request``, normalized to mm, deduplicated.

    Deduplication is on ``(value_mm, axis)`` keeping the first occurrence, so a
    request that states the same dimension twice warns once.
    """
    seen: set[tuple[float, str | None]] = set()
    out: list[RequestNumber] = []
    for match in _NUMBER_RE.finditer(request):
        unit = match.group("unit").lower()
        factor = _UNIT_MM.get(unit)
        if factor is None:  # pragma: no cover - the pattern only matches known units
            continue
        value_mm = float(match.group("value")) * factor
        axis = _axis_for(request, match.start(), match.end())
        key = (round(value_mm, 6), axis)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            RequestNumber(
                value_mm=value_mm,
                unit=unit,
                text=match.group(0).strip(),
                axis=axis,
                offset=match.start(),
            )
        )
    return tuple(out)


# --------------------------------------------------------------------------
# prompt_number_diff


def _axis_dimensions(bbox_mm: Sequence[float]) -> dict[str, tuple[str, float]]:
    """``axis -> (dimension name, value)`` for the built compound's extents."""
    return {
        axis: (f"bbox.{axis}", float(bbox_mm[i]))
        for i, axis in enumerate(_AXES)
        if i < len(bbox_mm)
    }


def prompt_number_diff(
    request: str,
    *,
    bbox_mm: Sequence[float],
    dimensions: Mapping[str, float],
) -> dict[str, JSONValue]:
    """Compare the request's dimensioned numbers with the built dimensions.

    ``dimensions`` are the axis-less named dimensions (tagged edge lengths,
    ``CHECKS`` thresholds); the bbox extents are added under ``bbox.x|y|z`` and
    are the only axis-resolved dimensions, because an axis-tagged request
    number names an overall extent along that axis.
    """
    axis_dims = _axis_dimensions(bbox_mm)
    pool: dict[str, float] = {name: float(value) for name, value in dimensions.items()}
    for name, value in axis_dims.values():
        pool[name] = value

    numbers: list[JSONValue] = []
    warnings: list[dict[str, JSONValue]] = []
    for number in request_numbers(request):
        tol = _tolerance(number.value_mm)
        entry = number.to_json()
        if number.axis is not None:
            named = axis_dims.get(number.axis)
            if named is None:  # pragma: no cover - metrics always carry 3 extents
                numbers.append(entry)
                continue
            dim_name, dim_value = named
            entry["compared_to"] = dim_name
            entry["dimension_mm"] = dim_value
            if abs(dim_value - number.value_mm) <= tol:
                entry["matched"] = True
            else:
                entry["matched"] = False
                warnings.append(
                    {
                        "kind": "dimension_mismatch",
                        "request_value_mm": number.value_mm,
                        "request_text": number.text,
                        "axis": number.axis,
                        "dimension": dim_name,
                        "dimension_value_mm": dim_value,
                        "message": (
                            f"request says {number.text} on {number.axis.upper()} "
                            f"but {dim_name} measures {dim_value:g} mm"
                        ),
                    }
                )
                warnings.append(
                    {
                        "kind": "unmatched_request_number",
                        "request_value_mm": number.value_mm,
                        "request_text": number.text,
                        "axis": number.axis,
                        "message": (
                            f"nothing in the built geometry measures {number.value_mm:g} mm "
                            f"on {number.axis.upper()}"
                        ),
                    }
                )
            numbers.append(entry)
            continue
        match = _nearest(pool, number.value_mm, tol)
        if match is None:
            entry["matched"] = False
            warnings.append(
                {
                    "kind": "unmatched_request_number",
                    "request_value_mm": number.value_mm,
                    "request_text": number.text,
                    "axis": None,
                    "message": (
                        f"no bbox extent, tagged dimension or CHECKS threshold "
                        f"corresponds to {number.text}"
                    ),
                }
            )
        else:
            entry["matched"] = True
            entry["compared_to"] = match[0]
            entry["dimension_mm"] = match[1]
        numbers.append(entry)
    return {
        "numbers": numbers,
        "dimensions": {name: pool[name] for name in sorted(pool)},
        "warnings": cast("list[JSONValue]", list(warnings)),
    }


def _nearest(pool: Mapping[str, float], value_mm: float, tol: float) -> tuple[str, float] | None:
    """The closest dimension within ``tol`` (name-sorted for determinism)."""
    best: tuple[str, float] | None = None
    best_delta = tol
    for name in sorted(pool):
        delta = abs(pool[name] - value_mm)
        if delta <= best_delta:
            best = (name, pool[name])
            best_delta = delta
    return best


# --------------------------------------------------------------------------
# interference


#: Ledger entries whose text/rationale says the overlap is on purpose.
_INTENTIONAL_RE: Final[re.Pattern[str]] = re.compile(
    r"intentional(?:ly)?\s+overlap|overlap\s+is\s+intentional|interference\s+fit|press[-\s]fit",
    re.IGNORECASE,
)
#: The ``part.feature(<name>).<field>`` that declares an overlap intentional.
INTENTIONAL_OVERLAP_FIELD: Final[str] = "intentional_overlap"


def intentional_overlap_declarations(
    feature_metadata: Mapping[str, JSONValue],
    ledger_entries: Iterable[Mapping[str, JSONValue]] = (),
) -> tuple[str, ...]:
    """Sources declaring solid overlap intentional (empty = nothing declared)."""
    found: list[str] = []
    for name in sorted(feature_metadata):
        fields = feature_metadata[name]
        if not isinstance(fields, dict):
            continue
        value = cast("Mapping[str, JSONValue]", fields).get(INTENTIONAL_OVERLAP_FIELD)
        if value is None or value is False or value == "":
            continue
        found.append(f"feature:{name}")
    for entry in ledger_entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, str):
            continue
        applies_to = entry.get("applies_to")
        text = " ".join(
            value for value in (entry.get("text"), entry.get("rationale")) if isinstance(value, str)
        )
        if applies_to == INTENTIONAL_OVERLAP_FIELD or _INTENTIONAL_RE.search(text):
            found.append(f"requirement:{entry_id}")
    return tuple(found)


def _solid_sort_key(solid: object) -> tuple[float, float, float, float]:
    box = cast("Any", solid).bounding_box()
    return (
        round(float(box.min.X), 6),
        round(float(box.min.Y), 6),
        round(float(box.min.Z), 6),
        round(float(cast("Any", solid).volume), 6),
    )


def named_solids(shape: object) -> list[tuple[str, object]]:
    """The compound's solids in a deterministic order, named ``solid#k``."""
    solids = cast("list[object]", list(cast("Any", shape).solids()))
    ordered = sorted(solids, key=_solid_sort_key)
    return [(f"solid#{index}", solid) for index, solid in enumerate(ordered, start=1)]


def interference_report(
    solids: Sequence[tuple[str, object]],
    *,
    declared_intentional: Sequence[str] = (),
    max_pairs: int | None = None,
    solid_count: int | None = None,
    unavailable: str | None = None,
) -> dict[str, JSONValue]:
    """Pairwise overlap across ``solids``, bounded and self-reporting the bound.

    ``solid_count`` overrides the reported solid count for the callers that
    know it from the build metrics without enumerating the compound (a single
    solid has no pairs, so its geometry is never reloaded). ``unavailable``
    records why the solids could not be enumerated — an unmeasured compound
    says so instead of reporting a clean sheet.
    """
    from hephaestus.geom.measure import interference

    cap = MAX_INTERFERENCE_PAIRS if max_pairs is None else max_pairs
    pairs = list(combinations(range(len(solids)), 2))
    measured = pairs[:cap]
    capped = len(measured) < len(pairs)
    warnings: list[dict[str, JSONValue]] = []
    overlaps: list[JSONValue] = []
    for left, right in measured:
        name_a, shape_a = solids[left]
        name_b, shape_b = solids[right]
        volume = float(interference(cast("Any", shape_a), cast("Any", shape_b)))
        if volume <= OVERLAP_EPS_MM3:
            continue
        overlaps.append({"a": name_a, "b": name_b, "volume_mm3": volume})
        if declared_intentional:
            continue
        warnings.append(
            {
                "kind": "interference",
                "a": name_a,
                "b": name_b,
                "volume_mm3": volume,
                "message": (
                    f"{name_a} and {name_b} overlap by {volume:g} mm^3 with no "
                    "intentional_overlap declaration"
                ),
            }
        )
    if capped:
        warnings.append(
            {
                "kind": "interference_pairs_capped",
                "pairs_total": len(pairs),
                "pairs_measured": len(measured),
                "message": (
                    f"only {len(measured)} of {len(pairs)} solid pairs were measured "
                    f"(cap {cap}); overlap in the remaining pairs is unknown"
                ),
            }
        )
    if unavailable is not None:
        warnings.append(
            {
                "kind": "interference_unavailable",
                "message": f"solid overlap was not measured: {unavailable}",
            }
        )
    return {
        "solids": len(solids) if solid_count is None else solid_count,
        "pairs_total": len(pairs),
        "pairs_measured": len(measured),
        "pairs_capped": capped,
        "declared_intentional": list(declared_intentional),
        "overlaps": overlaps,
        "warnings": cast("list[JSONValue]", list(warnings)),
    }


# --------------------------------------------------------------------------
# manifold


def manifold_report(metrics: Metrics | None) -> dict[str, JSONValue]:
    """§4 ``manifold``: sealed/genus surfaced from the build metrics."""
    if metrics is None:
        return {"available": False, "warnings": []}
    warnings: list[JSONValue] = []
    if not metrics.sealed:
        warnings.append(
            {
                "kind": "not_sealed",
                "message": "the built compound is not watertight (sealed=false)",
            }
        )
    return {
        "available": True,
        "sealed": metrics.sealed,
        "genus": metrics.genus,
        "solids": metrics.solids,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# dfm


#: Finding severities that become §4 warnings. ``info`` findings stay in the
#: block's ``findings`` list: they are context, not a call to act.
DFM_WARNING_SEVERITIES: Final[frozenset[str]] = frozenset({"error", "warning"})


def dfm_report(
    evaluation: DfmEvaluation | None, *, process: str | None = None, unavailable: str | None = None
) -> dict[str, JSONValue]:
    """§4 ``dfm``: one auto-run pack evaluation, or why it did not happen.

    ``unavailable`` (no secure sandbox, no declared process, a pack that failed
    to load) is reported as a warning of its own — a DFM block that could not
    run says so rather than presenting an empty findings list as a clean sheet.
    """
    if evaluation is None:
        return {
            "available": False,
            "process": process,
            "findings": [],
            "warnings": [
                {
                    "kind": "dfm_unavailable",
                    "message": f"DFM findings were not computed: {unavailable}",
                }
            ]
            if unavailable is not None
            else [],
        }
    warnings: list[JSONValue] = []
    for finding in findings_by_severity(evaluation.findings):
        if finding.severity not in DFM_WARNING_SEVERITIES:
            continue
        warnings.append(
            {
                "kind": "dfm_finding",
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "process": finding.process,
                "tags": list(finding.tags),
                "source_artifact_ref": finding.source_artifact_ref,
                "message": f"{finding.rule_id}: {finding.message}",
            }
        )
    for rule_id in evaluation.errored_rules():
        warnings.append(
            {
                "kind": "dfm_rule_error",
                "rule_id": rule_id,
                "message": f"DFM rule {rule_id} failed to evaluate; its limit was not checked",
            }
        )
    return {
        "available": True,
        "process": evaluation.process,
        "source_artifact_ref": evaluation.source_artifact_ref,
        "pack": {
            "name": evaluation.pack_name,
            "version": evaluation.pack_version,
            "registry": evaluation.registry,
            "registry_digest": evaluation.registry_digest,
        },
        "findings": [finding.to_json() for finding in findings_by_severity(evaluation.findings)],
        "severity_counts": cast("dict[str, JSONValue]", dict(evaluation.severity_counts())),
        "errored_rules": list(evaluation.errored_rules()),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# assembly


def critique_block(
    *,
    metrics: Metrics | None,
    interference: dict[str, JSONValue],
    request: str | None,
    dimensions: Mapping[str, float],
    dfm: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    """Assemble the whole §4 block, including the flattened warning list.

    ``dfm`` is omitted entirely when the project's DFM mode is off — an absent
    section means "not asked for", which is why the auto-run wiring passes a
    report (possibly an ``unavailable`` one) whenever the mode *is* on.
    """
    manifold = manifold_report(metrics)
    block: dict[str, JSONValue] = {
        "interference": interference,
        "manifold": manifold,
    }
    if dfm is not None:
        block["dfm"] = dfm
    if request is not None and metrics is not None:
        block["prompt_number_diff"] = prompt_number_diff(
            request, bbox_mm=metrics.bbox_mm, dimensions=dimensions
        )
    block["warnings"] = _flatten_warnings(block)
    return block


#: The critique sections whose ``warnings`` are flattened into ``critique.warnings``.
_WARNING_SECTIONS: Final[tuple[str, ...]] = (
    "interference",
    "manifold",
    "dfm",
    "prompt_number_diff",
    "dimension_findings",
)


def _flatten_warnings(block: Mapping[str, JSONValue]) -> list[JSONValue]:
    warnings: list[JSONValue] = []
    for section in _WARNING_SECTIONS:
        part = block.get(section)
        if not isinstance(part, dict):
            continue
        found = cast("Mapping[str, JSONValue]", part).get("warnings")
        if isinstance(found, list):
            warnings.extend(cast("list[JSONValue]", found))
    return warnings


def with_dimension_findings(
    block: dict[str, JSONValue],
    state: DimensionFindingState | None,
    *,
    unavailable: str | None = None,
) -> dict[str, JSONValue]:
    """Attach the **binding** view of this build's number diff (§4/§6).

    ``prompt_number_diff`` above is the advisory measurement; this section is the
    obligation it now carries. Every still-open finding is restated as a warning
    of its own — carrying the finding id, because that id is what an ``ask_user``
    question must name for a user to dismiss it — so the model reads, in the same
    result, both what does not match and that it cannot finish while it does not.

    ``None`` (a preview build, no request text, no store) leaves the block exactly
    as it was: an absent section means "nothing was bound here", never "clean".
    ``unavailable`` is the one case where the section appears without a state: the
    binding record could not be written, which must never read as a clean sheet.
    """
    if state is None:
        if unavailable is None:
            return block
        block["dimension_findings"] = {
            "open": [],
            "cleared": [],
            "warnings": [
                {
                    "kind": "dimension_findings_unavailable",
                    "message": (
                        "the binding record of this build's number diff was not written: "
                        f"{unavailable}. Nothing here says the dimensions agree."
                    ),
                }
            ],
        }
        block["warnings"] = _flatten_warnings(block)
        return block
    open_findings = state.open
    block["dimension_findings"] = {
        "generation": state.generation,
        "artifact_ref": state.artifact_ref,
        "open": [finding.to_json() for finding in open_findings],
        "cleared": [
            finding.to_json() for finding in state.findings if finding.closed_by is not None
        ],
        "warnings": [
            {
                "kind": "open_dimension_finding",
                "id": finding.id,
                "part": finding.part,
                "axis": finding.axis,
                "request_value_mm": finding.request_value_mm,
                "message": (
                    f"{finding.message}. This finding is BINDING (VALIDATION.md §4): the run "
                    "cannot finish while it is open. Clear it by rebuilding so the geometry "
                    f"matches the request, or ask the user to dismiss it with "
                    f'ask_user(requirement_ids=["{finding.id}"], …) — you cannot clear it '
                    "yourself, and asserting the number in CHECKS does not clear it."
                ),
            }
            for finding in open_findings
        ],
    }
    block["warnings"] = _flatten_warnings(block)
    return block
