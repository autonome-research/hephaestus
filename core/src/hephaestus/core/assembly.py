"""Assembly evaluation: declared mates measured against current build artifacts.

``ASSEMBLY.md`` §2, second bullet — the engine half of Stage 8C.
:mod:`hephaestus.geom.constraints` answers "what does this geometry measure?"
for two shapes a caller already holds; this module answers the two questions
geometry cannot: *which* shapes a ``part[:selector]`` anchor names, and what a
measurement that could not be taken is called.

The pipeline is one pass per constraint:

1. **Resolve** each anchor through the existing §7 addressing layer
   (:mod:`hephaestus.core.addressing`) against the part's CURRENT successful
   build artifact — the same "never a live build" rule ``measure`` and
   ``compare_solids`` follow, so what a status reports is exactly what a
   published ref names.
2. **Evaluate** the residual through :func:`hephaestus.geom.evaluate_residual`.
3. **Name the outcome**: ``satisfied`` | ``violated`` (carrying the residual) |
   ``unresolvable`` (carrying a reason from :data:`UNRESOLVABLE_REASONS`).

``unresolvable`` is its own state, never silently skipped and never conflated
with ``violated``. A constraint whose part was deleted, whose part has never
built, whose tag disappeared in an edit, or whose anchors are the wrong class of
shape for the kind has NOT been checked — and reporting "not checked" as
"violated" would be as dishonest as reporting it as "satisfied". Every reason is
named separately for the same reason: they call for different fixes.

**No solver, no verdict.** Nothing here moves geometry (``ASSEMBLY.md`` §1) and
nothing here decides what an unsatisfied constraint *means*: "a violated or
unresolvable constraint at termination review is blocking" is the
``VALIDATION.md`` §5 rule, applied by the reviewer over the
:class:`AssemblyStatus` this module produces. :meth:`AssemblyStatus.blocking`
lists the ids that rule would fire on; calling it a finding is the reviewer's
act, not this module's.

Anchoring against a *reloaded* artifact is what makes this module more than a
loop. A published BRep carries topology and nothing else — no labels, no tags,
no bindings — so the namespace comes from what publication recorded beside it:
the build's §7 ``geometry_index`` for which selectors exist, the source map's
tag placements and the §8 ``geometries`` solid runs for where they are. A
selector that resolves in the namespace but cannot be located in the published
artifact is ``unaddressable_anchor``: a named refusal, never a guessed face.
That resolution layer lives in the public :class:`AnchorResolver` /
:class:`PartGeometry` pair, because ``KINEMATICS.md`` §2 requires joint anchors
(:mod:`hephaestus.core.motion`) to ride the SAME path — one implementation of
"§7 against a published artifact", not two that could disagree.

**Pose-bound evaluation** (``KINEMATICS.md`` §3): a constraint entry may name
poses. Absent, evaluation is at zero and the outcome wire shape is
byte-for-byte the 8C one — a gate clause, pinned against recorded evidence.
Present, the anchors are resolved ONCE, the pose's forward-kinematics
transforms are applied as placed copies, and the residual is taken per pose:
the row's singular ``residual`` slot carries the WORST pose's residual (least
slack) and the new ``pose_residuals`` table carries one
``(pose_id, verdict, residual)`` entry per bound pose. Violated at ANY bound
pose is violated; an unresolvable pose makes the row ``unresolvable``
(``unresolvable_pose``, the detail naming the pose and its own reason).
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from hephaestus.core.addressing import GeometryIndex, Resolution, resolve
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.executor.runner import geometry_index_from_json
from hephaestus.core.executor.tags import TagPlacement
from hephaestus.core.project_store.constraints import (
    ConstraintEntry,
    ConstraintSet,
    ConstraintState,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.projections import AssemblyProjection
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

if TYPE_CHECKING:
    # Runtime imports of the motion engine stay lazy (it needs the kernel and,
    # module-to-module, would be circular: motion rides this module's resolver).
    from hephaestus.core.motion import MotionResolution

__all__ = [
    "ASSEMBLY_ARTIFACT_KIND",
    "OUTCOME_STATES",
    "POSE_VERDICTS",
    "UNRESOLVABLE_REASONS",
    "AnchorRef",
    "AnchorResolver",
    "AssemblyEvaluator",
    "AssemblyStatus",
    "ConstraintOutcome",
    "OutcomeState",
    "PartGeometry",
    "PoseResidual",
    "PoseVerdict",
    "UnresolvableAnchorError",
    "UnresolvableReason",
    "addressing_refusal",
]

#: Artifact kind of a stored (projected) assembly-status document.
ASSEMBLY_ARTIFACT_KIND: Final[str] = "assembly-status"

OutcomeState = Literal["satisfied", "violated", "unresolvable"]

#: The three per-constraint states (``ASSEMBLY.md`` §2). Closed on purpose:
#: "not checked" has exactly one spelling, and it is not a pass.
OUTCOME_STATES: Final[tuple[OutcomeState, ...]] = ("satisfied", "violated", "unresolvable")

UnresolvableReason = Literal[
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "shape_refused",
    "invalid_constraint",
    "unresolvable_pose",
]

#: Why a constraint could not be evaluated. Each names a different fix:
#:
#: * ``missing_part`` — the anchor names a part this project does not have.
#: * ``no_current_build`` — the part exists but has no current successful build
#:   (never built, or its last build failed): build it.
#: * ``missing_artifact`` — a current build is recorded but its artifact bytes
#:   are not durably stored: the evidence is gone, which is not the same as
#:   never having existed.
#: * ``dangling_selector`` — the selector resolves to nothing in that build's §7
#:   namespace: the tag or label the constraint was written against is gone,
#:   typically because the script was edited.
#: * ``ambiguous_selector`` — the selector matches several interpretations at
#:   one precedence level; §7 forbids guessing, so does this.
#: * ``unaddressable_anchor`` — the selector exists in the namespace but the
#:   published artifact cannot supply that geometry (an unplaced tag, a
#:   vertex/wire tag, a binding that contributed no node).
#: * ``shape_refused`` — geometry was resolved but is the wrong class for the
#:   kind (``geom``'s :class:`~hephaestus.geom.ConstraintShapeError`, whose own
#:   reason is carried in the detail): concentricity between two boxes has no
#:   answer, and a plausible number for it would be worse than none.
#: * ``invalid_constraint`` — the stored entry is malformed for its kind. The
#:   declaration path refuses these, so reaching it here means a generation was
#:   written by an older or foreign writer; it is reported, never evaluated.
#: * ``unresolvable_pose`` — the entry binds a pose (``KINEMATICS.md`` §3) that
#:   could not be evaluated: unknown or withdrawn, orphaned by a withdrawn
#:   joint, out of a joint's declared limits, or riding an unresolvable joint.
#:   The detail names the pose and its own reason; the row is NOT checked, and
#:   the ``pose_residuals`` table says which poses were.
UNRESOLVABLE_REASONS: Final[tuple[UnresolvableReason, ...]] = (
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "shape_refused",
    "invalid_constraint",
    "unresolvable_pose",
)


class UnresolvableAnchorError(Exception):
    """An anchor could not be turned into geometry — a named reason plus detail.

    Public because ``KINEMATICS.md`` §2 makes joint-anchor resolution
    (:mod:`hephaestus.core.motion`) ride this module's anchoring path: the
    engine that shares :class:`AnchorResolver` also has to catch its refusals.
    """

    def __init__(self, reason: UnresolvableReason, detail: str) -> None:
        super().__init__(detail)
        self.reason: UnresolvableReason = reason
        self.detail = detail


# --------------------------------------------------------------------------
# the record


@dataclass(frozen=True)
class AnchorRef:
    """How one ``part[:selector]`` anchor resolved (or how far it got)."""

    anchor: str
    part: str
    selector: str
    #: The §7 rule that matched (``part``/``tag``/``label``/``binding``), or
    #: ``None`` when resolution never got that far.
    rule: str | None = None
    #: The artifact ref the geometry was read from, when one was reached.
    artifact_ref: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "anchor": self.anchor,
            "part": self.part,
            "selector": self.selector,
            "rule": self.rule,
            "artifact_ref": self.artifact_ref,
        }


PoseVerdict = Literal["satisfied", "violated", "unresolvable"]

#: Per-pose verdicts inside a pose-bound row (``KINEMATICS.md`` §3): the same
#: three spellings as :data:`OUTCOME_STATES`, restated as its own alias so the
#: pose table cannot silently grow a fourth state the row vocabulary lacks.
POSE_VERDICTS: Final[tuple[PoseVerdict, ...]] = ("satisfied", "violated", "unresolvable")


@dataclass(frozen=True)
class PoseResidual:
    """One bound pose's verdict for one constraint (``KINEMATICS.md`` §3).

    The ``(pose_id, verdict, residual)`` row of the ``pose_residuals`` table.
    A measured pose carries its :attr:`residual`; an unresolvable one carries
    the pose-level :attr:`reason` and :attr:`detail` instead — the same
    "evidence never crosses states" rule the parent outcome keeps.
    """

    pose_id: str
    verdict: PoseVerdict
    residual: Mapping[str, JSONValue] | None = None
    reason: str | None = None
    detail: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "pose_id": self.pose_id,
            "verdict": self.verdict,
            "residual": None if self.residual is None else cast("JSONValue", dict(self.residual)),
            "reason": self.reason,
            "detail": self.detail,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> PoseResidual:
        verdict = data.get("verdict")
        if verdict not in POSE_VERDICTS:
            raise ValidationError(f"invalid pose verdict {verdict!r}", kind="contract")
        residual = data.get("residual")
        return cls(
            pose_id=str(data.get("pose_id", "")),
            verdict=verdict,
            residual=(
                cast("Mapping[str, JSONValue]", residual) if isinstance(residual, dict) else None
            ),
            reason=_opt_str(data.get("reason")),
            detail=_opt_str(data.get("detail")),
        )


@dataclass(frozen=True)
class ConstraintOutcome:
    """One constraint's state, with the evidence behind it.

    A ``violated`` outcome always carries a :attr:`residual` (the measured
    number next to the declared one); an ``unresolvable`` one always carries a
    :attr:`reason` and a human-readable :attr:`detail`. Neither ever carries the
    other's evidence, which is what keeps "not checked" from reading like a
    measurement.

    A pose-bound entry (``KINEMATICS.md`` §3) additionally carries
    :attr:`pose_residuals` — one row per bound pose — and its singular
    :attr:`residual` is the worst pose's. The field serializes ONLY when the
    entry binds poses, so an unbound outcome's wire shape stays byte-for-byte
    the 8C one (a gate clause).
    """

    id: str
    kind: str
    a: AnchorRef
    b: AnchorRef
    state: OutcomeState
    #: ``dataclasses.asdict(ConstraintResidual)`` — geom's own record shape, so
    #: the wire form cannot drift from ``ASSEMBLY.md`` §2. For a pose-bound
    #: entry: the WORST pose's residual (least slack).
    residual: Mapping[str, JSONValue] | None = None
    reason: UnresolvableReason | None = None
    detail: str | None = None
    provenance: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    note: str | None = None
    #: ``KINEMATICS.md`` §3: one entry per bound pose; empty for unbound entries.
    pose_residuals: tuple[PoseResidual, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "id": self.id,
            "kind": self.kind,
            "a": cast("JSONValue", self.a.to_json()),
            "b": cast("JSONValue", self.b.to_json()),
            "state": self.state,
            "residual": None if self.residual is None else cast("JSONValue", dict(self.residual)),
            "reason": self.reason,
            "detail": self.detail,
            "provenance": cast("JSONValue", dict(self.provenance)),
            "note": self.note,
        }
        if self.pose_residuals:
            out["pose_residuals"] = [row.to_json() for row in self.pose_residuals]
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> ConstraintOutcome:
        state = data.get("state")
        if state not in OUTCOME_STATES:
            raise ValidationError(f"invalid constraint state {state!r}", kind="contract")
        residual = data.get("residual")
        provenance = data.get("provenance")
        reason = data.get("reason")
        raw_poses = data.get("pose_residuals")
        pose_residuals: tuple[PoseResidual, ...] = ()
        if isinstance(raw_poses, list):
            pose_residuals = tuple(
                PoseResidual.from_json(cast("Mapping[str, JSONValue]", item))
                for item in cast("list[JSONValue]", raw_poses)
                if isinstance(item, dict)
            )
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", "")),
            a=_anchor_from_json(data.get("a")),
            b=_anchor_from_json(data.get("b")),
            state=state,
            residual=(
                cast("Mapping[str, JSONValue]", residual) if isinstance(residual, dict) else None
            ),
            reason=reason if reason in UNRESOLVABLE_REASONS else None,
            detail=_opt_str(data.get("detail")),
            provenance=(
                cast("Mapping[str, JSONValue]", provenance) if isinstance(provenance, dict) else {}
            ),
            note=_opt_str(data.get("note")),
            pose_residuals=pose_residuals,
        )

    @property
    def measured(self) -> float | None:
        """The residual's primary measured quantity, when one was taken."""
        if self.residual is None:
            return None
        value = self.residual.get("measured")
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    @property
    def unit(self) -> str | None:
        unit = None if self.residual is None else self.residual.get("unit")
        return unit if isinstance(unit, str) else None


def _opt_str(value: JSONValue | None) -> str | None:
    return value if isinstance(value, str) else None


def _anchor_from_json(data: JSONValue | None) -> AnchorRef:
    if not isinstance(data, dict):
        return AnchorRef(anchor="", part="", selector="")
    raw = cast("Mapping[str, JSONValue]", data)
    rule = raw.get("rule")
    ref = raw.get("artifact_ref")
    return AnchorRef(
        anchor=str(raw.get("anchor", "")),
        part=str(raw.get("part", "")),
        selector=str(raw.get("selector", "")),
        rule=rule if isinstance(rule, str) else None,
        artifact_ref=ref if isinstance(ref, str) else None,
    )


@dataclass(frozen=True)
class AssemblyStatus:
    """Every declared constraint's state at one evaluation (``ASSEMBLY.md`` §2)."""

    generation: int
    constraints: tuple[ConstraintOutcome, ...]
    #: ``{part: artifact_ref}`` actually read, ``""`` for an anchored part that
    #: had no current build — recorded so the projection can tell later whether
    #: a rebuild invalidated this status.
    artifact_refs: Mapping[str, str] = field(default_factory=dict[str, str])
    #: Parts whose current build has moved since this status was computed. Empty
    #: at evaluation time; publication fills it in.
    stale: tuple[str, ...] = ()

    def _ids(self, state: OutcomeState) -> tuple[str, ...]:
        return tuple(outcome.id for outcome in self.constraints if outcome.state == state)

    @property
    def satisfied(self) -> tuple[str, ...]:
        return self._ids("satisfied")

    @property
    def violated(self) -> tuple[str, ...]:
        return self._ids("violated")

    @property
    def unresolvable(self) -> tuple[str, ...]:
        return self._ids("unresolvable")

    def blocking(self) -> tuple[str, ...]:
        """Ids the ``VALIDATION.md`` §5 never-green rule fires on, in order.

        A fact about this status — violated **and** unresolvable, because an
        unchecked constraint is not a passing one. Whether that becomes a
        blocking finding is the reviewer's act; this module only says which ids
        the rule would name.
        """
        return tuple(
            outcome.id
            for outcome in self.constraints
            if outcome.state in ("violated", "unresolvable")
        )

    @property
    def counts(self) -> dict[str, int]:
        return {state: len(self._ids(state)) for state in OUTCOME_STATES}

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "generation": self.generation,
            "constraints": [outcome.to_json() for outcome in self.constraints],
            "artifact_refs": {
                name: self.artifact_refs[name] for name in sorted(self.artifact_refs)
            },
            "stale": list(self.stale),
            "counts": cast("JSONValue", self.counts),
            "blocking": list(self.blocking()),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> AssemblyStatus:
        generation = data.get("generation")
        raw = data.get("constraints")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ValidationError("assembly status generation must be an integer", kind="contract")
        if not isinstance(raw, list):
            raise ValidationError("assembly status constraints must be an array", kind="contract")
        outcomes = tuple(
            ConstraintOutcome.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw)
            if isinstance(item, dict)
        )
        refs_raw = data.get("artifact_refs", {})
        refs: dict[str, str] = {}
        if isinstance(refs_raw, dict):
            for name, value in cast("Mapping[str, JSONValue]", refs_raw).items():
                if isinstance(value, str):
                    refs[name] = value
        stale_raw = data.get("stale", [])
        stale: tuple[str, ...] = ()
        if isinstance(stale_raw, list):
            stale = tuple(
                item for item in cast("list[JSONValue]", stale_raw) if isinstance(item, str)
            )
        return cls(generation=generation, constraints=outcomes, artifact_refs=refs, stale=stale)


# --------------------------------------------------------------------------
# resolved geometry of one part's current artifact


@dataclass(frozen=True)
class PartGeometry:
    """One part's current artifact, plus everything needed to address into it."""

    part: str
    artifact_ref: str
    shape: Any
    index: GeometryIndex
    solids: tuple[Any, ...]
    #: ``(label, first solid index, solid count)`` runs in geometry-tree order.
    runs: tuple[tuple[str, int, int], ...]
    placements: Mapping[str, TagPlacement]
    #: False when the label rows do not partition the artifact's solids (nested
    #: labels double-count). Label/binding anchors are then unaddressable rather
    #: than resolved to a run that may not be the addressed node's.
    runs_partition: bool

    def shape_for(self, resolution: Resolution) -> Any:
        """The concrete geometry one resolution names, or ``UnresolvableAnchorError``."""
        if resolution.kind == "part":
            return self.shape
        if resolution.kind == "tag":
            return self._tag_shape(resolution.name)
        return self._run_shape(resolution)

    def _tag_shape(self, name: str) -> Any:
        placement = self.placements.get(name)
        if placement is None or placement.solid_index is None or placement.topo_index is None:
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"tag {name!r} is in {self.part}'s namespace but was not placed in the "
                "published artifact (it referenced topology outside part.geometry)",
            )
        if placement.solid_index >= len(self.solids):
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"tag {name!r} names solid {placement.solid_index} of {self.part}, which the "
                f"published artifact does not have ({len(self.solids)} solids)",
            )
        solid = self.solids[placement.solid_index]
        if placement.kind == "solid":
            return solid
        if placement.kind in ("face", "edge"):
            topologies = list(solid.faces() if placement.kind == "face" else solid.edges())
            if placement.topo_index >= len(topologies):
                raise UnresolvableAnchorError(
                    "unaddressable_anchor",
                    f"tag {name!r} names {placement.kind} {placement.topo_index} of solid "
                    f"{placement.solid_index}, which the published artifact does not have",
                )
            return topologies[placement.topo_index]
        raise UnresolvableAnchorError(
            "unaddressable_anchor",
            f"tag {name!r} is a {placement.kind}, which a published artifact cannot address "
            "(only solids, faces and edges are relocatable in reloaded BRep)",
        )

    def _run_shape(self, resolution: Resolution) -> Any:
        if resolution.kind == "binding":
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"binding {resolution.name!r} contributed no labeled node to {self.part}'s "
                "published geometry, so there is nothing to measure (§5.1 label-fill gives a "
                "geometry-bearing binding a label; this one has none)",
            )
        if not self.runs_partition:
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"{self.part}'s published label rows do not partition its solids (nested "
                "labels), so a label anchor cannot be mapped to geometry without guessing",
            )
        picked: list[Any] = []
        for occurrence in resolution.occurrences:
            if occurrence >= len(self.runs):
                raise UnresolvableAnchorError(
                    "unaddressable_anchor",
                    f"label {resolution.name!r} occurrence {occurrence} is outside "
                    f"{self.part}'s published label rows",
                )
            _, start, count = self.runs[occurrence]
            picked.extend(self.solids[start : start + count])
        if not picked:
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"label {resolution.name!r} contributed no solid to {self.part}'s published "
                "geometry",
            )
        if len(picked) == 1:
            return picked[0]
        from build123d import Compound

        return Compound(children=picked)


# --------------------------------------------------------------------------
# shared anchor resolution


class AnchorResolver:
    """One evaluation's addressable view of the project's CURRENT artifacts.

    Extracted from :class:`AssemblyEvaluator` because ``KINEMATICS.md`` §2
    requires joint anchors to resolve "through the 8C anchoring path" — this
    class IS that path, so constraint and joint resolution cannot drift apart.
    Each part's published artifact is loaded and indexed at most once per
    evaluation (the cache), and every failure is an
    :class:`UnresolvableAnchorError` carrying a reason from
    :data:`UNRESOLVABLE_REASONS` — a part that failed to load stays failed for
    every anchor that names it, with the same reason each time.
    """

    def __init__(
        self, layout: ProjectLayout, store: OpStore, publisher: Publisher, scratch: Path
    ) -> None:
        self.layout = layout
        self._store = store
        self._publisher = publisher
        self._scratch = scratch
        self._cache: dict[str, PartGeometry | UnresolvableAnchorError] = {}

    def locate(self, part: str, selector: str) -> tuple[PartGeometry, Resolution]:
        """The part's geometry and the §7 resolution one anchor names.

        The caller takes ``shape_for(resolution)`` when it wants the concrete
        geometry — split so it can record the rule and artifact ref that
        matched even when the published artifact cannot supply the shape.
        """
        geometry = self._cache.get(part)
        if geometry is None:
            try:
                geometry = self._load_part(part)
            except UnresolvableAnchorError as exc:
                geometry = exc
            self._cache[part] = geometry
        if isinstance(geometry, UnresolvableAnchorError):
            raise geometry
        try:
            resolution = resolve(selector, geometry.index)
        except AddressingError as exc:
            reason, detail = addressing_refusal(exc)
            raise UnresolvableAnchorError(reason, detail) from exc
        return geometry, resolution

    def artifact_refs(self) -> dict[str, str]:
        """``{part: artifact_ref}`` actually read, ``""`` for a failed load.

        Lexically sorted — the :attr:`AssemblyStatus.artifact_refs` shape the
        projection compares against on later publications.
        """
        return {
            part: geometry.artifact_ref if isinstance(geometry, PartGeometry) else ""
            for part, geometry in sorted(self._cache.items())
        }

    def _load_part(self, part: str) -> PartGeometry:
        """The part's current artifact as addressable geometry, or a named refusal."""
        from hephaestus.core.executor.artifact_geometry import load_brep_shape

        known = self.layout.part_names()
        if part not in known:
            raise UnresolvableAnchorError(
                "missing_part",
                f"no part {part!r} in this project (parts: {', '.join(known) or 'none'})",
            )
        result = self._publisher.current_result(part)
        if result is None or result.artifact_ref is None:
            raise UnresolvableAnchorError(
                "no_current_build",
                f"part {part!r} has no current successful build to measure",
            )
        blob = blob_hash_of_ref(result.artifact_ref)
        if not self._store.blobs.has(blob):
            raise UnresolvableAnchorError(
                "missing_artifact",
                f"artifact {result.artifact_ref} of part {part!r} is not durably stored",
            )
        shape = cast("Any", load_brep_shape(self._store.blobs.get(blob), scratch_dir=self._scratch))
        solids = tuple(cast("list[Any]", shape.solids()))
        bundle = self._publisher.current_bundle(part) or {}
        index = _published_index(bundle, result)
        runs, partition = _solid_runs(index, result, len(solids))
        return PartGeometry(
            part=part,
            artifact_ref=result.artifact_ref,
            shape=shape,
            index=index,
            solids=solids,
            runs=runs,
            placements=self._placements(result),
            runs_partition=partition,
        )

    def _placements(self, result: BuildResult) -> dict[str, TagPlacement]:
        """Tag placements from the build's stored source map (§5.3)."""
        ref = result.source_map_ref
        if ref is None:
            return {}
        blob = blob_hash_of_ref(ref)
        if not self._store.blobs.has(blob):
            return {}
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own JSON
            return {}
        tags = cast("Mapping[str, JSONValue]", raw).get("tags")
        if not isinstance(tags, dict):
            return {}
        out: dict[str, TagPlacement] = {}
        for name, entry in cast("Mapping[str, JSONValue]", tags).items():
            if not isinstance(entry, dict):
                continue
            placement = cast("Mapping[str, JSONValue]", entry)
            kind = placement.get("kind")
            solid = placement.get("solid")
            topo = placement.get("topo_index")
            if not isinstance(kind, str):
                continue
            out[name] = TagPlacement(
                kind=kind,
                solid_index=(
                    solid if isinstance(solid, int) and not isinstance(solid, bool) else None
                ),
                topo_index=topo if isinstance(topo, int) and not isinstance(topo, bool) else None,
                statement_index=-1,
                line=0,
            )
        return out


# --------------------------------------------------------------------------
# the evaluator


class AssemblyEvaluator:
    """Evaluates one project's constraint set against its current builds."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store
        self.constraints = ConstraintSet(layout, store)
        self._publisher = Publisher(layout, store)

    # -- reads --------------------------------------------------------------

    def projected(self) -> AssemblyStatus | None:
        """The last projected status, with its live staleness, or ``None``.

        ``None`` means *never evaluated* — which is not the same as "nothing to
        check", and the CLI says so rather than printing an empty table.
        """
        projection = self._publisher.projections.state().assembly
        if projection is None:
            return None
        blob = projection.status_blob
        if not self._store.blobs.has(blob):  # pragma: no cover - GC-linked to the state blob
            return None
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            return None
        status = AssemblyStatus.from_json(cast("Mapping[str, JSONValue]", raw))
        return dataclasses.replace(status, stale=tuple(projection.stale))

    def projected_ref(self) -> str | None:
        """``artifact:assembly-status:sha256:…`` of the projected status, if any.

        The immutable handle for the status document itself, so a reviewer
        finding or a bench score can cite the exact measurement it read rather
        than "the assembly status at the time".
        """
        projection = self._publisher.projections.state().assembly
        if projection is None:
            return None
        return make_artifact_ref(ASSEMBLY_ARTIFACT_KIND, projection.status_blob)

    # -- evaluation ---------------------------------------------------------

    def evaluate(
        self,
        ids: Sequence[str] | None = None,
        *,
        record: bool = True,
        scratch: Path | None = None,
    ) -> AssemblyStatus:
        """Evaluate now (``ASSEMBLY.md`` §2: status is recomputed on demand).

        ``ids`` restricts evaluation to those constraints — an unknown id is an
        ``addressing_error`` listing the declared ones, never a silently empty
        result. Withdrawn entries are never evaluated: the project stopped
        claiming them, and a withdrawal is not a failure.

        With ``record`` the status is stored and projected, so a later read
        (``heph assembly``, the §5 reviewer's context) sees this evaluation and
        can be told when a rebuild has since invalidated it. A partial
        evaluation (``ids`` given) is deliberately NOT projected: a projection
        that covered only some constraints would report a set the project does
        not have.
        """
        state = self.constraints.state()
        entries = _select(state, ids)
        if scratch is not None:
            status = self._evaluate_in(entries, state.generation, scratch)
        else:
            self.layout.store_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="heph-assembly-", dir=self.layout.store_root
            ) as tmp:
                status = self._evaluate_in(entries, state.generation, Path(tmp))
        if record and ids is None:
            self._project(status)
        return status

    def _evaluate_in(
        self, entries: Sequence[ConstraintEntry], generation: int, scratch: Path
    ) -> AssemblyStatus:
        resolver = AnchorResolver(self.layout, self._store, self._publisher, scratch)
        posed: MotionResolution | None = None
        if any(entry.poses for entry in entries):
            # Lazy on purpose, and only when a pose-bound entry exists: the
            # motion engine resolves EVERY active joint's anchors (KINEMATICS.md
            # §2), and an unbound-only project must not pay for — or record —
            # geometry its constraints never asked about.
            from hephaestus.core.motion import motion_resolution

            posed = motion_resolution(self.layout, self._store, resolver)
        outcomes = [self._evaluate_one(entry, resolver, posed) for entry in entries]
        return AssemblyStatus(
            generation=generation,
            constraints=tuple(outcomes),
            artifact_refs=resolver.artifact_refs(),
        )

    def _evaluate_one(
        self,
        entry: ConstraintEntry,
        resolver: AnchorResolver,
        posed: MotionResolution | None,
    ) -> ConstraintOutcome:
        refs, shapes, failed = self._resolve_pair(entry, resolver)
        if failed is not None:
            return failed
        if entry.poses:
            assert posed is not None  # _evaluate_in resolves motion when any entry binds
            return self._measure_posed(entry, refs, shapes[0], shapes[1], posed)
        return self._measure(entry, refs, shapes[0], shapes[1])

    def _resolve_pair(
        self, entry: ConstraintEntry, resolver: AnchorResolver
    ) -> tuple[list[AnchorRef], list[Any], ConstraintOutcome | None]:
        """Both anchors as geometry — resolved ONCE, whatever the entry binds."""
        anchor_a, anchor_b = entry.anchors
        refs = [
            AnchorRef(anchor=anchor.text, part=anchor.part, selector=anchor.selector)
            for anchor in (anchor_a, anchor_b)
        ]
        shapes: list[Any] = []
        for position, anchor in enumerate((anchor_a, anchor_b)):
            try:
                geometry, resolution = resolver.locate(anchor.part, anchor.selector)
            except UnresolvableAnchorError as exc:
                failed = _unresolvable(
                    entry, refs, exc.reason, f"anchor {'ab'[position]}: {exc.detail}"
                )
                return refs, shapes, failed
            refs[position] = dataclasses.replace(
                refs[position], rule=resolution.kind, artifact_ref=geometry.artifact_ref
            )
            try:
                shapes.append(geometry.shape_for(resolution))
            except UnresolvableAnchorError as exc:
                failed = _unresolvable(
                    entry, refs, exc.reason, f"anchor {'ab'[position]}: {exc.detail}"
                )
                return refs, shapes, failed
        return refs, shapes, None

    def _measure_posed(
        self,
        entry: ConstraintEntry,
        refs: Sequence[AnchorRef],
        a: Any,
        b: Any,
        posed: MotionResolution,
    ) -> ConstraintOutcome:
        """One residual per bound pose (``KINEMATICS.md`` §3).

        The anchors were resolved once by the caller; each pose contributes a
        forward-kinematics placement applied as a *placed copy* of the same
        shapes. The row's singular residual is the worst pose's (least slack,
        first bound wins a tie); violated at any pose is violated; a pose that
        cannot be evaluated makes the row ``unresolvable_pose``, the detail
        naming the first failing pose — while the ``pose_residuals`` table
        still records every bound pose's own verdict, so partial evidence is
        never discarded.

        A shape-class refusal is pose-invariant (a rigid placement changes no
        face's class), so it is reported row-level exactly as the unbound path
        reports it, not once per pose.
        """
        from hephaestus.core.motion import BoundPoseError
        from hephaestus.geom import (
            ConstraintDeclarationError,
            ConstraintShapeError,
            evaluate_residual,
            transformed_shape,
        )

        part_a, part_b = entry.anchors[0].part, entry.anchors[1].part
        rows: list[PoseResidual] = []
        worst: Mapping[str, JSONValue] | None = None
        worst_slack = 0.0
        violated = False
        failure: tuple[str, str, str] | None = None
        for pose_id in entry.poses:
            try:
                placed = posed.transforms(pose_id, (part_a, part_b))
            except BoundPoseError as exc:
                rows.append(
                    PoseResidual(
                        pose_id=pose_id,
                        verdict="unresolvable",
                        reason=exc.reason,
                        detail=exc.detail,
                    )
                )
                if failure is None:
                    failure = (pose_id, exc.reason, exc.detail)
                continue
            try:
                residual = evaluate_residual(
                    entry.kind,
                    transformed_shape(a, placed[part_a]),
                    transformed_shape(b, placed[part_b]),
                    dict(entry.values),
                )
            except ConstraintShapeError as exc:
                return _unresolvable(
                    entry,
                    refs,
                    "shape_refused",
                    f"anchor {exc.side}: {exc.reason} — {exc.message}",
                )
            except ConstraintDeclarationError as exc:  # pragma: no cover - declaration validates
                return _unresolvable(entry, refs, "invalid_constraint", exc.message)
            record = cast("Mapping[str, JSONValue]", dataclasses.asdict(cast("Any", residual)))
            rows.append(
                PoseResidual(
                    pose_id=pose_id,
                    verdict="satisfied" if residual.satisfied else "violated",
                    residual=record,
                )
            )
            violated = violated or not residual.satisfied
            if worst is None or residual.slack < worst_slack:
                worst, worst_slack = record, residual.slack
        if failure is not None:
            pose_id, reason, detail = failure
            return ConstraintOutcome(
                id=entry.id,
                kind=entry.kind,
                a=refs[0],
                b=refs[1],
                state="unresolvable",
                reason="unresolvable_pose",
                detail=f"pose {pose_id}: {reason} — {detail}",
                provenance=entry.provenance.to_json(),
                note=entry.note,
                pose_residuals=tuple(rows),
            )
        return ConstraintOutcome(
            id=entry.id,
            kind=entry.kind,
            a=refs[0],
            b=refs[1],
            state="violated" if violated else "satisfied",
            residual=worst,
            provenance=entry.provenance.to_json(),
            note=entry.note,
            pose_residuals=tuple(rows),
        )

    def _measure(
        self, entry: ConstraintEntry, refs: Sequence[AnchorRef], a: Any, b: Any
    ) -> ConstraintOutcome:
        """Residual evaluation, with geom's two refusals mapped to named states."""
        from hephaestus.geom import (
            ConstraintDeclarationError,
            ConstraintShapeError,
            evaluate_residual,
        )

        try:
            residual = evaluate_residual(entry.kind, a, b, dict(entry.values))
        except ConstraintShapeError as exc:
            return _unresolvable(
                entry,
                refs,
                "shape_refused",
                f"anchor {exc.side}: {exc.reason} — {exc.message}",
            )
        except ConstraintDeclarationError as exc:  # pragma: no cover - declaration validates
            return _unresolvable(entry, refs, "invalid_constraint", exc.message)
        record = cast("Mapping[str, JSONValue]", dataclasses.asdict(cast("Any", residual)))
        return ConstraintOutcome(
            id=entry.id,
            kind=entry.kind,
            a=refs[0],
            b=refs[1],
            state="satisfied" if residual.satisfied else "violated",
            residual=record,
            provenance=entry.provenance.to_json(),
            note=entry.note,
        )

    # -- projection ---------------------------------------------------------

    def _project(self, status: AssemblyStatus) -> AssemblyProjection:
        """Store the status document and point the projection at it."""
        blob = self._store.blobs.put(canonical_json(status.to_json()).encode("utf-8"))
        projections = self._publisher.projections
        projection = AssemblyProjection(
            status_blob=blob,
            generation=status.generation,
            audit_revision=projections.state().audit_revision,
            parts=dict(status.artifact_refs),
        )
        projections.record_assembly(projection)
        return projection


# --------------------------------------------------------------------------
# helpers


def addressing_refusal(exc: AddressingError) -> tuple[UnresolvableReason, str]:
    """The named unresolvable state one §7 addressing failure maps to.

    The two ways a selector can fail are two different facts about the project —
    "that tag is gone" and "that name means two things" — and ``ASSEMBLY.md`` §2
    requires them reported apart. The distinction comes from the addressing
    layer's own ``reason``, never from reading its message.
    """
    reason: UnresolvableReason = (
        "ambiguous_selector" if exc.reason == "ambiguous" else "dangling_selector"
    )
    candidates = f" (candidates: {', '.join(exc.candidates)})" if exc.candidates else ""
    return reason, f"{exc.message}{candidates}"


def _select(state: ConstraintState, ids: Sequence[str] | None) -> tuple[ConstraintEntry, ...]:
    """The active entries to evaluate, in declaration order."""
    active = state.active
    if ids is None:
        return active
    by_id = {entry.id: entry for entry in state.entries}
    unknown = [name for name in ids if name not in by_id]
    if unknown:
        raise AddressingError(
            f"no constraint(s) {', '.join(unknown)} declared",
            selector=unknown[0],
            candidates=tuple(sorted(by_id)),
        )
    wanted = set(ids)
    return tuple(entry for entry in active if entry.id in wanted)


def _unresolvable(
    entry: ConstraintEntry,
    refs: Sequence[AnchorRef],
    reason: UnresolvableReason,
    detail: str,
) -> ConstraintOutcome:
    return ConstraintOutcome(
        id=entry.id,
        kind=entry.kind,
        a=refs[0],
        b=refs[1],
        state="unresolvable",
        reason=reason,
        detail=detail,
        provenance=entry.provenance.to_json(),
        note=entry.note,
    )


def _published_index(bundle: Mapping[str, JSONValue], result: BuildResult) -> GeometryIndex:
    """The §7 namespace of a published build.

    Publication records the worker's own ``geometry_index``; a bundle written
    before that (``ASSEMBLY.md`` §2 added it) falls back to the §8 ``geometries``
    rows, which are the same label set in the same order with the display
    dedup suffix applied — enough to address labels and to report a dangling
    tag honestly, rather than pretending an old build has no namespace at all.
    """
    raw = bundle.get("geometry_index")
    if isinstance(raw, dict):
        index = geometry_index_from_json(cast("Mapping[str, JSONValue]", raw))
        if index.labels or index.tags or index.bindings:
            return index
    return GeometryIndex(labels=tuple(_raw_labels(result)), bindings={}, tags=frozenset())


def _raw_labels(result: BuildResult) -> Iterable[str]:
    """Undo the §7 display dedup (``name#2`` -> ``name``) on ``geometries`` rows."""
    for entry in result.geometries:
        base, separator, suffix = entry.label.rpartition("#")
        yield base if separator and suffix.isdigit() else entry.label


def _solid_runs(
    index: GeometryIndex, result: BuildResult, solid_count: int
) -> tuple[tuple[tuple[str, int, int], ...], bool]:
    """Map each label row to its run of solids (tree order == solid order).

    The §3.3 selection table (:mod:`hephaestus.core.render.inspect`) reads a
    published artifact the same way: rows are consecutive runs of solids in
    tree order. That mapping only holds when the rows PARTITION the artifact's
    solids; a label on a compound *and* on its children counts the same solids
    twice, and the second return value says so, because guessing which run a
    nested label meant is exactly what §7 forbids.
    """
    counts = [max(entry.solids, 0) for entry in result.geometries]
    labels = list(index.labels)
    runs: list[tuple[str, int, int]] = []
    start = 0
    for position, label in enumerate(labels):
        count = counts[position] if position < len(counts) else 0
        runs.append((label, start, count))
        start += count
    return tuple(runs), start == solid_count and len(counts) == len(labels)
