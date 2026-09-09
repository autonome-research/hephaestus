"""The ``measure`` tool: geometry resolution, the ``m`` facade, resolved refs.

Measurement always runs over *artifact-reloaded* geometry, never a live build, so
what is measured is exactly what a ref names. Resolution has three modes: an
explicit ``artifact_ref`` (single part only), an explicit ``project_snapshot_ref``,
or the implicit path — one part's current successful build when a single part is
addressed, otherwise one coherent project snapshot assembled on the spot (an
incoherent project is the discriminated ``incoherent_project_snapshot`` refusal).

The result reports the units for the kind and every artifact ref that was
actually read, so a caller can re-measure the identical geometry later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.addressing import PART_SELECTOR, namespace
from hephaestus.core.checks.facade import (
    DENSITY_KGM3_TO_GMM3,
    GeometrySource,
    MassDensityUnboundError,
    project_measurement,
)
from hephaestus.core.errors import AddressingError
from hephaestus.core.executor.artifact_geometry import ArtifactGeometry
from hephaestus.core.executor.published_geometry import (
    UnresolvableAnchorError,
    addressable_namespace,
)
from hephaestus.core.project_store.projections import SnapshotRejectedError
from hephaestus.core.registry import Material
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState
from ._dfm import script_metadata

_MEASURE_UNITS: Final[dict[str, str]] = {
    "interference": "mm^3",
    "clearance": "mm",
    "distance": "mm",
    "bbox": "mm",
    "volume": "mm^3",
    "mass": "g",
    "sealed": "bool",
    "genus": "count",
}

_BINARY_MEASURE_KINDS: Final[frozenset[str]] = frozenset({"interference", "clearance", "distance"})

#: How many resolvable names an addressing refusal lists when the §7 near-miss
#: search finds none. A refusal with no alternatives is the shape B-1 hid behind
#: for fourteen months; a capped namespace is an answer the model can act on.
_CANDIDATE_LIMIT: Final[int] = 12

#: How ``core/addressing.py``'s ``resolve`` introduces its near misses inside
#: the refusal prose. Mirrored here so the sentence can be narrowed alongside
#: the structured candidate list it duplicates.
_NEAR_MISS_CLAUSE: Final[str] = "; near misses: "


@dataclass(frozen=True)
class _MassDensity:
    """One part's bound density, and the provenance that makes it checkable."""

    part: str
    spec: str = ""
    material: Material | None = None
    explicit: float | None = None

    @property
    def density_g_mm3(self) -> float:
        """The density actually multiplied, in the facade's g/mm^3.

        The registry stores kg/m^3 and :data:`DENSITY_KGM3_TO_GMM3` is the one
        boundary that converts it (``PHYSICS.md`` §1); an explicit argument is
        already in the facade's unit and is passed through untouched.
        """
        if self.explicit is not None:
            return self.explicit
        if self.material is None:  # pragma: no cover - one of the two is always set
            raise CadOpError("mass_density_unbound", f"no density bound for part {self.part!r}")
        return self.material.density * DENSITY_KGM3_TO_GMM3

    def to_json(self) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "part": self.part,
            "g_per_mm3": self.density_g_mm3,
            "source": "explicit" if self.explicit is not None else "materials_registry",
        }
        if self.material is not None:
            payload["material"] = {
                "id": self.material.id,
                "name": self.material.name,
                "density_kg_m3": self.material.density,
                "registry": self.material.registry,
                "registry_digest": self.material.digest,
                "spec": self.spec,
            }
        return payload


class MeasureOps(CadOpsState):
    """Resolve the geometry a measurement addresses and evaluate it."""

    def measure(
        self,
        kind: str,
        a: str,
        b: str | None,
        *,
        part: str | None,
        artifact_ref: str | None,
        project_snapshot_ref: str | None,
        density: float | None = None,
    ) -> dict[str, Any]:
        """The ``m`` facade as a tool: resolve geometry, measure, report refs."""
        if kind not in _MEASURE_UNITS:
            raise CadOpError("invalid_params", f"unknown measure kind {kind!r}")
        if (kind in _BINARY_MEASURE_KINDS) != (b is not None):
            raise CadOpError(
                "invalid_params",
                f"measure kind {kind!r} "
                + ("requires" if kind in _BINARY_MEASURE_KINDS else "forbids")
                + " selector 'b'",
            )
        if artifact_ref is not None and project_snapshot_ref is not None:
            raise CadOpError(
                "invalid_params", "artifact_ref and project_snapshot_ref are mutually exclusive"
            )
        selectors = [a] + ([b] if b is not None else [])
        qualified = {s.split("/", 1)[0] for s in selectors if "/" in s}
        current = part or (sorted(qualified)[0] if qualified else None)
        with self._scratch("heph-measure-") as scratch:
            sources, refs = self._measure_sources(
                selectors,
                qualified,
                current,
                artifact_ref=artifact_ref,
                project_snapshot_ref=project_snapshot_ref,
                scratch=Path(scratch),
            )
            _refuse_unrecorded_namespace(selectors, sources, current)
            # ``PHYSICS.md`` §1 / ledger J-agent-results-1: bind every addressed
            # part's registry density BEFORE measuring, converted at the one
            # named boundary. Only ``mass`` consumes it, and only ``mass`` pays
            # for it: opening and matching the materials registry for a bbox
            # would be work no caller asked for.
            bindings = self._mass_densities(sources, density) if kind == "mass" else {}
            measurement = project_measurement(
                sources,
                current_part=current,
                densities={name: binding.density_g_mm3 for name, binding in bindings.items()},
            )
            value: JSONValue
            try:
                if kind == "interference":
                    value = measurement.interference(a, cast("str", b))
                elif kind == "clearance":
                    value = measurement.clearance(a, cast("str", b))
                elif kind == "distance":
                    value = measurement.distance(a, cast("str", b))
                elif kind == "bbox":
                    triple = measurement.bbox(a)
                    value = [triple[0], triple[1], triple[2]]
                elif kind == "volume":
                    value = measurement.volume(a)
                elif kind == "mass":
                    value = measurement.mass(a)
                elif kind == "sealed":
                    value = measurement.sealed(a)
                else:
                    value = measurement.genus(a)
            except MassDensityUnboundError as exc:
                # The facade refuses by name; the tool surface speaks the same
                # name, with the part and the registry's own vocabulary attached
                # so the model can fix it in one step rather than guess.
                spec = self._material_spec(exc.part)
                raise CadOpError(
                    exc.code,
                    exc.message,
                    data={
                        "part": exc.part,
                        "material_spec": spec,
                        "known_materials": list(self.registries().materials.ids()),
                    },
                ) from exc
            except UnresolvableAnchorError as exc:
                # The selector IS in the build's §7 namespace but the published
                # artifact cannot supply that geometry (a tag placed outside
                # ``part.geometry``, a vertex/wire tag, a §7 rule-4 binding —
                # publication records no binding-to-solid mapping). Constraint
                # anchors report this as ``unaddressable_anchor``; a tool
                # refusal speaks the §7 vocabulary instead, and lists what IS
                # addressable.
                raise AddressingError(
                    exc.detail,
                    selector=a,
                    candidates=_namespace_candidates(sources, current, selectors),
                ) from exc
            except AddressingError as exc:
                # ``addressing.py`` draws its difflib near misses from one
                # part's whole recorded namespace — empty for a selector that
                # resembles nothing in it, and free to name a §7 rule-4 binding
                # this side cannot answer (publication records no
                # binding-to-solid mapping). tool_schema's ``measure`` entry
                # promises candidates, so the unanswerable ones come out and an
                # emptied list falls back to the addressable namespace.
                near = _answerable_candidates(exc, selectors, sources, current)
                if near and near == exc.candidates:
                    raise
                raise AddressingError(
                    # The names are stated TWICE by ``resolve``: in
                    # ``candidates`` and verbatim in the prose. A model reads
                    # the prose, so correcting only the field would swap one
                    # wrong answer for another.
                    _restate(exc.message, exc.candidates, near),
                    selector=exc.selector,
                    candidates=near or _namespace_candidates(sources, current, selectors),
                    reason=exc.reason,
                ) from exc
        detail: dict[str, Any] = {
            "kind": kind,
            "args": selectors,
            "measured": measurement.measured_json(),
            "parts": sorted(sources),
        }
        if kind == "mass":
            # Structural disclosure, not prose, and beside the measurement it
            # explains: the number is a product of a volume and a density, and
            # a reader that cannot see WHICH density cannot tell a measurement
            # from a placeholder (J-agent-results-1).
            binding = bindings.get(_local_part(a, current)[0] or "")
            if binding is not None:
                detail["density"] = binding.to_json()
        return {
            "value": value,
            "units": _MEASURE_UNITS[kind],
            "detail": detail,
            "resolved_artifact_refs": refs,
        }

    # -- density binding (``PHYSICS.md`` §1) --------------------------------

    def _mass_densities(
        self, sources: Mapping[str, GeometrySource], explicit: float | None
    ) -> dict[str, _MassDensity]:
        """Every addressed part's density in the facade's g/mm^3, with provenance.

        An explicit ``density`` argument wins for every addressed part, exactly
        as ``m.mass(selector, density=...)`` does inside a check. Otherwise a
        part with no ``material_spec``, or one the pinned materials registry
        does not carry, simply gets no binding: the facade then refuses
        ``mass_density_unbound`` naming that part, which is a better answer
        than a density guessed here. Registry resolution is the same one the
        DFM and bill-of-materials paths use — the free-text spec matched
        against the verified registry — so a part cannot have one density on a
        drawing and another in a measurement.
        """
        if explicit is not None:
            return {name: _MassDensity(part=name, explicit=explicit) for name in sources}
        materials = self.registries().materials
        bound: dict[str, _MassDensity] = {}
        for name in sources:
            spec = self._material_spec(name)
            if not spec:
                continue
            material = materials.match(spec)
            if material is None:
                continue
            bound[name] = _MassDensity(part=name, spec=spec, material=material)
        return bound

    def _material_spec(self, part: str) -> str:
        """``part.material_spec`` as the build evaluated it, else as written.

        The build record wins where there is one, on ``part_properties``'s
        precedent: a computed ``part.material_spec`` is a declared one, and the
        static parse recovers string literals only.
        """
        publisher = self._publisher()
        result = publisher.current_result(part)
        if result is not None:
            recorded = result.metadata.get("material_spec", "")
            if recorded:
                return recorded
        try:
            snapshot = publisher.parts.read_part(part)
        except AddressingError:  # pragma: no cover - the part was just measured
            return ""
        return script_metadata(snapshot.content).get("material_spec", "")

    def _measure_sources(
        self,
        selectors: Sequence[str],
        qualified: set[str],
        current: str | None,
        *,
        artifact_ref: str | None,
        project_snapshot_ref: str | None,
        scratch: Path,
    ) -> tuple[dict[str, GeometrySource], list[str]]:
        """Resolve the geometry each selector needs, plus the exact refs used."""
        publisher = self._publisher()
        unqualified = any("/" not in s for s in selectors)
        addressed: set[str] = set(qualified)
        if unqualified and current is not None:
            addressed.add(current)
        if artifact_ref is not None:
            if len(addressed) > 1:
                raise CadOpError(
                    "invalid_params",
                    "artifact_ref selects one part; cross-part selectors need a snapshot",
                )
            name = current or (sorted(addressed)[0] if addressed else None)
            if name is None:
                raise CadOpError("invalid_params", "artifact_ref requires a part context")
            return (
                {name: self._artifact_geometry(artifact_ref, scratch, part=name)},
                [artifact_ref],
            )
        if project_snapshot_ref is not None:
            return self._snapshot_sources(project_snapshot_ref, scratch)
        if len(addressed) <= 1:
            name = current or (sorted(addressed)[0] if addressed else None)
            if name is None:
                raise CadOpError("invalid_params", "measure requires a part context")
            result = publisher.current_result(name)
            if result is None or result.artifact_ref is None:
                raise AddressingError(
                    f"part {name!r} has no current successful build to measure",
                    selector=name,
                    candidates=self._layout.part_names(),
                )
            return (
                {name: self._artifact_geometry(result.artifact_ref, scratch, part=name)},
                [result.artifact_ref],
            )
        # Cross-part: one coherent project-snapshot manifest.
        try:
            snapshot = publisher.projections.assemble_snapshot(self._layout.part_names())
        except SnapshotRejectedError as exc:
            raise CadOpError(
                "incoherent_project_snapshot",
                exc.message,
                data={"issues": [issue.to_json() for issue in exc.issues]},
            ) from exc
        return self._snapshot_sources(snapshot.ref, scratch)


def _local_part(selector: str, current: str | None) -> tuple[str | None, str]:
    """``(part, selector-within-part)`` for a possibly ``"<part>/…"`` selector."""
    name, separator, rest = selector.partition("/")
    if separator:
        return name, rest
    return current, selector


def _refuse_unrecorded_namespace(
    selectors: Sequence[str], sources: Mapping[str, GeometrySource], current: str | None
) -> None:
    """Refuse ``namespace_unrecorded`` rather than "resolves to nothing" (B-1).

    An artifact whose build bundle was never stored — published before bundles
    were durable, or collected with its retention class — genuinely has no
    recorded §7 namespace. Every selector but ``"part"`` is unanswerable against
    it, and saying *that* is a different fact from saying the name matches
    nothing: the second is what the empty candidate set said for fourteen
    months, and it sent the model looking for a typo that was not there.
    """
    for selector in selectors:
        part, local = _local_part(selector, current)
        if part is None or local == PART_SELECTOR:
            continue
        source = sources.get(part)
        if isinstance(source, ArtifactGeometry) and not source.namespace_recorded:
            raise CadOpError(
                "namespace_unrecorded",
                f"the build behind {part!r}'s artifact recorded no §7 selector namespace, "
                f"so {selector!r} cannot be resolved against it; only 'part' is addressable "
                "on that artifact",
                data={"part": part, "selector": selector},
            )


def _namespace_candidates(
    sources: Mapping[str, GeometrySource],
    current: str | None,
    selectors: Sequence[str],
) -> tuple[str, ...]:
    """Every selector the addressed geometry can actually answer, qualified.

    ``addressable_namespace`` rather than the raw §7 namespace: a published
    artifact records no binding-to-solid mapping, so advertising a rule-4
    binding name here would hand back a selector guaranteed to refuse. The
    empty candidate tuple was B-1's own symptom; replacing it with a name that
    cannot work would be the same failure wearing help's clothes.

    The parts the failing selectors actually named come first, because the list
    is capped: a project-wide alphabetical walk can spend the whole cap on
    parts the caller never mentioned and never reach the one it did.
    """
    named = [
        part
        for part, _ in (_local_part(s, current) for s in selectors)
        if part is not None and part in sources
    ]
    names: list[str] = []
    for part in dict.fromkeys([*named, *sorted(sources)]):
        source = sources[part]
        for name in _answerable(source):
            names.append(name if len(sources) == 1 and part == current else f"{part}/{name}")
    return tuple(names[:_CANDIDATE_LIMIT])


def _answerable(source: GeometrySource) -> tuple[str, ...]:
    """The selectors ``source`` resolves AND can supply geometry for."""
    if isinstance(source, ArtifactGeometry):
        return addressable_namespace(source.index)
    return namespace(source.index)  # pragma: no cover - measure builds only artifact sources


def _candidate_part(
    exc: AddressingError,
    selectors: Sequence[str],
    sources: Mapping[str, GeometrySource],
    current: str | None,
) -> str | None:
    """The part whose recorded §7 namespace ``exc.candidates`` was drawn from.

    ``resolve_in_project`` strips the ``"<part>/"`` prefix before resolving, so
    the error names the *local* selector; matching that back identifies the one
    namespace the near misses came from. ``None`` means the refusal came from
    project-level resolution instead (an unknown part prefix, a missing part
    context), whose candidates are part names and are answerable as they stand.
    """
    for selector in selectors:
        part, local = _local_part(selector, current)
        if local == exc.selector and part in sources:
            return part
    return None


def _answerable_candidates(
    exc: AddressingError,
    selectors: Sequence[str],
    sources: Mapping[str, GeometrySource],
    current: str | None,
) -> tuple[str, ...]:
    """``exc.candidates`` minus what this side cannot answer, as the tool spells it.

    Two corrections, both against names drawn from the recorded namespace of a
    single part. A §7 rule-4 binding is dropped: a published artifact records
    no binding-to-solid mapping, so offering one hands back a selector
    guaranteed to refuse again. And the survivors are part-qualified whenever
    the candidate list is (``_namespace_candidates``' own rule), because a bare
    name in a cross-part call resolves against whichever part is *current* —
    not the part its namespace came from.
    """
    part = _candidate_part(exc, selectors, sources, current)
    if part is None:
        return exc.candidates
    source = sources[part]
    answerable = frozenset(_answerable(source))
    recorded = frozenset(namespace(source.index))
    qualify = not (len(sources) == 1 and part == current)
    kept: list[str] = []
    for candidate in exc.candidates:
        if candidate not in recorded:
            # Not a §7 name: an ambiguity's ``_describe`` prose. Left alone.
            kept.append(candidate)
        elif candidate in answerable:
            kept.append(f"{part}/{candidate}" if qualify else candidate)
    return tuple(kept)


def _restate(message: str, listed: Sequence[str], kept: Sequence[str]) -> str:
    """``message`` with ``resolve``'s near-miss clause narrowed to ``kept``.

    ``addressing.py`` bakes its candidate list into the sentence
    (``core/addressing.py``'s ``"; near misses: …"``), so a filtered
    ``candidates`` field alone would leave the prose advertising exactly the
    names the filter removed. Rewritten only when the message provably ends
    with the listed names, which leaves every other refusal shape untouched and
    degrades to the unnarrowed sentence — never a wrong one — if that clause is
    ever reworded.
    """
    clause = _NEAR_MISS_CLAUSE + ", ".join(listed)
    if not listed or not message.endswith(clause):
        return message
    return message[: -len(clause)] + (_NEAR_MISS_CLAUSE + ", ".join(kept) if kept else "")
