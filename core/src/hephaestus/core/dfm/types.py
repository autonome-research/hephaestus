"""The typed DFM result vocabulary: descriptors, findings, per-rule outcomes.

Every value a DFM run reports is *artifact-bound*. A finding never names a mask
id or any other mutable handle: it carries the ``source_artifact_ref`` it was
measured against plus :class:`TopologyDescriptor` records — ``{kind, solid_id,
topology_index, tag?}`` — which address topology inside that immutable artifact
exactly the way the source map's tag placements do (§5.3). A viewer, a drawing,
or a follow-up ``inspect_part`` can therefore resolve a finding months later
against the same bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast, get_args

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

__all__ = [
    "TOPOLOGY_KINDS",
    "DfmEvaluation",
    "DfmFinding",
    "DfmRuleOutcome",
    "TopologyDescriptor",
    "TopologyKind",
    "descriptors_from_source_map",
    "findings_by_severity",
]

TopologyKind = Literal["solid", "face", "edge", "wire", "vertex", "other"]

#: Topology kinds a descriptor may name (source-map ``tags`` uses the same set).
TOPOLOGY_KINDS: tuple[TopologyKind, ...] = get_args(TopologyKind)

RuleStatus = Literal["ok", "violations", "error"]


@dataclass(frozen=True)
class TopologyDescriptor:
    """Artifact-bound address of one topology: ``{kind, solid_id, topology_index}``.

    ``solid_id`` is the index of the owning solid in the artifact compound's
    ``solids()`` order and ``topology_index`` the index within that solid's
    ``faces()``/``edges()`` list — the same deterministic enumeration the source
    map records for tags. ``tag`` is the §5.3 tag name when the topology is
    tagged, so a finding reads as a name where one exists and as a stable
    address where one does not.
    """

    kind: TopologyKind
    solid_id: int
    topology_index: int
    tag: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in TOPOLOGY_KINDS:
            raise ValidationError(
                f"topology descriptor kind {self.kind!r} is not one of "
                + ", ".join(TOPOLOGY_KINDS),
                kind="contract",
            )
        if self.solid_id < 0 or self.topology_index < 0:
            raise ValidationError(
                "topology descriptor indices must be non-negative", kind="contract"
            )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind,
            "solid_id": self.solid_id,
            "topology_index": self.topology_index,
            "tag": self.tag,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> TopologyDescriptor:
        kind = data.get("kind")
        solid_id = data.get("solid_id")
        topology_index = data.get("topology_index")
        if not isinstance(kind, str) or kind not in TOPOLOGY_KINDS:
            raise ValidationError(
                f"topology descriptor 'kind' must be one of {', '.join(TOPOLOGY_KINDS)}",
                kind="contract",
            )
        if isinstance(solid_id, bool) or not isinstance(solid_id, int):
            raise ValidationError("topology descriptor 'solid_id' must be an int", kind="contract")
        if isinstance(topology_index, bool) or not isinstance(topology_index, int):
            raise ValidationError(
                "topology descriptor 'topology_index' must be an int", kind="contract"
            )
        tag = data.get("tag")
        return cls(
            kind=kind,
            solid_id=solid_id,
            topology_index=topology_index,
            tag=tag if isinstance(tag, str) and tag else None,
        )


def descriptors_from_source_map(
    source_map: Mapping[str, JSONValue],
) -> dict[str, TopologyDescriptor]:
    """Tag name -> descriptor, read from a build's stored source map.

    The source map's ``tags`` table is the only place a published artifact's
    tag names survive (BRep bytes carry no labels), so this is how a DFM run
    over an artifact recovers tagged topology. Tags whose placement did not
    resolve at build time (``solid: null``) are skipped — an unresolved tag has
    no artifact-bound address to report.
    """
    raw = source_map.get("tags")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, TopologyDescriptor] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        record = cast("Mapping[str, JSONValue]", entry)
        solid = record.get("solid")
        topo = record.get("topo_index")
        kind = record.get("kind")
        if isinstance(solid, bool) or not isinstance(solid, int):
            continue
        if isinstance(topo, bool) or not isinstance(topo, int):
            continue
        if not isinstance(kind, str) or kind not in TOPOLOGY_KINDS:
            continue
        out[str(name)] = TopologyDescriptor(
            kind=kind,
            solid_id=solid,
            topology_index=topo,
            tag=str(name),
        )
    return out


@dataclass(frozen=True)
class DfmFinding:
    """One rule violation, bound to the artifact it was measured against.

    ``rule_id``/``severity``/``title`` come from the rule *declaration*, never
    from the predicate, so registry content cannot understate its own severity.
    ``tags`` are the offending §5.3 tag names; ``topology`` the artifact-bound
    descriptors; ``suggested_bound`` the value the measured quantity would have
    to reach, in ``bound_unit``.
    """

    rule_id: str
    severity: str
    title: str
    message: str
    process: str
    source_artifact_ref: str
    tags: tuple[str, ...] = ()
    topology: tuple[TopologyDescriptor, ...] = ()
    measured: JSONValue = None
    suggested_bound: float | None = None
    bound_unit: str = "mm"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "process": self.process,
            "source_artifact_ref": self.source_artifact_ref,
            "tags": list(self.tags),
            "topology": [descriptor.to_json() for descriptor in self.topology],
            "measured": self.measured,
            "suggested_bound": self.suggested_bound,
            "bound_unit": self.bound_unit,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> DfmFinding:
        topology_raw = data.get("topology", [])
        topology: list[TopologyDescriptor] = []
        if isinstance(topology_raw, list):
            for item in cast("list[JSONValue]", topology_raw):
                if isinstance(item, dict):
                    topology.append(
                        TopologyDescriptor.from_json(cast("Mapping[str, JSONValue]", item))
                    )
        tags_raw = data.get("tags", [])
        tags = (
            tuple(str(tag) for tag in cast("list[JSONValue]", tags_raw))
            if isinstance(tags_raw, list)
            else ()
        )
        bound = data.get("suggested_bound")
        return cls(
            rule_id=_text(data, "rule_id"),
            severity=_text(data, "severity"),
            title=_text(data, "title"),
            message=_text(data, "message"),
            process=_text(data, "process"),
            source_artifact_ref=_text(data, "source_artifact_ref"),
            tags=tags,
            topology=tuple(topology),
            measured=data.get("measured"),
            suggested_bound=(
                float(bound)
                if isinstance(bound, int | float) and not isinstance(bound, bool)
                else None
            ),
            bound_unit=_text(data, "bound_unit") or "mm",
        )


def _text(data: Mapping[str, JSONValue], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class DfmRuleOutcome:
    """What one rule did: clean, violated, or failed to evaluate.

    ``error`` is set exactly when ``status == "error"`` — a predicate that
    raises never silently reads as a pass, and never fails the whole run.
    """

    rule_id: str
    title: str
    severity: str
    status: RuleStatus
    findings: tuple[DfmFinding, ...] = ()
    params: Mapping[str, float] = field(default_factory=dict[str, float])
    error: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "status": self.status,
            "findings": [finding.to_json() for finding in self.findings],
            "params": {name: value for name, value in sorted(self.params.items())},
            "error": self.error,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> DfmRuleOutcome:
        status = data.get("status")
        if status not in get_args(RuleStatus):
            raise ValidationError(f"rule outcome: invalid status {status!r}", kind="contract")
        findings_raw = data.get("findings", [])
        findings: list[DfmFinding] = []
        if isinstance(findings_raw, list):
            for item in cast("list[JSONValue]", findings_raw):
                if isinstance(item, dict):
                    findings.append(DfmFinding.from_json(cast("Mapping[str, JSONValue]", item)))
        params_raw = data.get("params", {})
        params: dict[str, float] = {}
        if isinstance(params_raw, dict):
            for name, value in params_raw.items():
                if isinstance(value, int | float) and not isinstance(value, bool):
                    params[str(name)] = float(value)
        error = data.get("error")
        return cls(
            rule_id=_text(data, "rule_id"),
            title=_text(data, "title"),
            severity=_text(data, "severity"),
            status=cast("RuleStatus", status),
            findings=tuple(findings),
            params=params,
            error=error if isinstance(error, str) else None,
        )


@dataclass(frozen=True)
class DfmEvaluation:
    """One pack run over one artifact: every rule's outcome, in pack order."""

    part: str
    process: str
    source_artifact_ref: str
    pack_name: str
    pack_version: str
    registry: str
    registry_digest: str
    outcomes: tuple[DfmRuleOutcome, ...] = ()
    truncated: bool = False

    @property
    def findings(self) -> tuple[DfmFinding, ...]:
        """Every finding, in pack rule order (severity is on each finding)."""
        out: list[DfmFinding] = []
        for outcome in self.outcomes:
            out.extend(outcome.findings)
        return tuple(out)

    def severity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    def errored_rules(self) -> tuple[str, ...]:
        return tuple(o.rule_id for o in self.outcomes if o.status == "error")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "part": self.part,
            "process": self.process,
            "source_artifact_ref": self.source_artifact_ref,
            "pack": {
                "name": self.pack_name,
                "version": self.pack_version,
                "registry": self.registry,
                "registry_digest": self.registry_digest,
            },
            "rules": [outcome.to_json() for outcome in self.outcomes],
            "findings": [finding.to_json() for finding in self.findings],
            "severity_counts": cast("dict[str, JSONValue]", dict(self.severity_counts())),
            "errored_rules": list(self.errored_rules()),
            "truncated": self.truncated,
        }


def findings_by_severity(
    findings: Sequence[DfmFinding], order: Sequence[str] = ("error", "warning", "info")
) -> tuple[DfmFinding, ...]:
    """Findings sorted most severe first, ties keeping their original order."""
    rank = {severity: index for index, severity in enumerate(order)}
    return tuple(sorted(findings, key=lambda f: (rank.get(f.severity, len(order)), f.rule_id)))
