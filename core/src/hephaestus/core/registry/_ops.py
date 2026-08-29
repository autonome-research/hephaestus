"""The five registry tools, backed by one verified :class:`RegistrySet`.

This is the only module that *acts*: it pages skill markdown into provenance-
delimited results with snapshot-bound cursors, searches materials and store
parts, and executes a store generator through the ordinary build pipeline with
``origin="registry"`` — under a probed secure sandbox or not at all.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hephaestus.core.errors import HephaestusError
from hephaestus.core.executor.fingerprint import rel_delta
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.tags import INTERFACE_TAG_INFIX
from opstore.types import JSONValue

from opstore import OpStore

from ._component import INTERFACE_TOPOLOGY, ComponentMass, ComponentRecord
from ._errors import RegistryError
from ._generator import (
    GeneratorSource,
    instance_prefix_for,
    is_placed,
    parse_generator,
    render_fragment,
)
from ._parts import StorePart
from ._reference import (
    TEXT_MAX_BYTES,
    TEXT_MAX_LINES,
    Page,
    paginate,
    wrap_reference,
    wrapper_overhead,
)
from ._set import RegistrySet
from ._skills import SKILL_ARTIFACT_KIND

if TYPE_CHECKING:
    from hephaestus.core.executor.runner import UnpublishedBuild
    from hephaestus.core.types import ErrorRecord, Metrics

__all__ = ["RegistryOps"]


class RegistryOps:
    """Backs the five registry tools over a verified :class:`RegistrySet`.

    ``store`` supplies the CAS the skill-page snapshot is registered in, so a
    truncated ``load_skill`` continues through ``read_artifact(artifact_ref,
    next_offset_bytes)`` against immutable bytes. ``backend`` is the *secure*
    execution backend generators run under; without one ``instance_store_part``
    reports ``capability_not_available`` rather than degrading to an unsandboxed
    run.
    """

    def __init__(
        self,
        registries: RegistrySet,
        store: OpStore,
        *,
        backend: ExecBackend | None = None,
        scratch_root: Path | None = None,
        wall_clock_s: float = 120.0,
    ) -> None:
        self._registries = registries
        self._store = store
        self._backend = backend
        self._scratch_root = scratch_root
        self._wall_clock_s = wall_clock_s

    @property
    def registries(self) -> RegistrySet:
        return self._registries

    # -- contextual content ------------------------------------------------

    def list_skills(self) -> list[dict[str, JSONValue]]:
        """``[{name, summary, tokens, registry, registry_digest}]``, name-sorted."""
        return self._registries.skills.listing()

    def load_skill(
        self, name: str, offset_line: int = 1, limit_lines: int = TEXT_MAX_LINES
    ) -> dict[str, JSONValue]:
        """One bounded skill page inside provenance delimiters.

        The whole file is registered as an immutable artifact first, so every
        cursor this returns is absolute and snapshot-bound. Truncation — a full
        page, a byte-budget stop, or a single line too large to ever fit — is
        always reported, never silently swallowed.
        """
        entry = self._registries.skills.get(name)
        data = entry.read_bytes()
        blob = self._store.blobs.put(data)
        self._store.gc.pin(blob)
        artifact_ref = f"artifact:{SKILL_ARTIFACT_KIND}:{blob}"

        raw_lines = data.splitlines(keepends=True)
        starts: list[int] = []
        cursor = 0
        for line in raw_lines:
            starts.append(cursor)
            cursor += len(line)
        starts.append(len(data))

        total_lines = len(raw_lines)
        first = max(0, int(offset_line) - 1)
        limit = max(1, min(int(limit_lines), TEXT_MAX_LINES))
        if first >= total_lines:
            page = Page(
                body="",
                end_line=total_lines,
                truncated=False,
                oversized_line=False,
                next_offset_bytes=None,
                oversized_line_offset_bytes=None,
            )
        else:
            budget = TEXT_MAX_BYTES - wrapper_overhead(entry, total_lines)
            page = paginate(raw_lines, starts, first, limit, max(1, budget))
        lines_label = (
            f"{first + 1}-{page.end_line}/{total_lines}"
            if page.end_line > first
            else f"none-of-{total_lines}"
        )
        result: dict[str, JSONValue] = {
            "content": wrap_reference(
                page.body,
                kind="skill",
                name=entry.name,
                registry=entry.registry,
                digest=entry.digest,
                lines=lines_label,
            ),
            "artifact_ref": artifact_ref,
            "truncated": page.truncated,
            "oversized_line": page.oversized_line,
            "total_lines": total_lines,
            "total_bytes": len(data),
            "first_line": first + 1,
            "last_line": page.end_line,
        }
        if page.truncated:
            result["next_offset_line"] = page.end_line + 1
        if page.next_offset_bytes is not None:
            result["next_offset_bytes"] = page.next_offset_bytes
        if page.oversized_line_offset_bytes is not None:
            result["oversized_line_offset_bytes"] = page.oversized_line_offset_bytes
        return result

    def search_materials(self, query: str) -> list[dict[str, JSONValue]]:
        """``[{id, name, density, forms, thicknesses, notes}]`` best-match first."""
        return self._registries.materials.search(query)

    # -- executable content ------------------------------------------------

    def search_parts_store(self, query: str, max_results: int = 5) -> list[dict[str, JSONValue]]:
        """``[{id, name, params, preview}]`` for generators matching ``query``."""
        return self._registries.parts.search(query, max(1, int(max_results)))

    def instance_store_part(
        self,
        part_id: str,
        params: Mapping[str, Any],
        pos: Mapping[str, Any] | None = None,
        instance: str | None = None,
    ) -> dict[str, JSONValue]:
        """Execute a generator under the secure sandbox and return a placed fragment.

        The generator runs as an ordinary part script with ``origin="registry"``:
        the injected-namespace whitelist is its API surface, the OS sandbox is
        its boundary, and the unsafe local backend refuses the job outright. Only
        after the geometry actually builds with the requested parameters is a
        fragment emitted — an instance the model pastes is one that works.

        For a **component** with declared interfaces that promise is extended to
        the interfaces themselves (``PARTS_STORE.md`` §2.3): every declared class
        is checked against the topology that actually built, and — when the
        caller places the instance — against the topology that builds *at the
        caller's placement*, because §2.1 evaluates selectors post-placement and
        verifying only the generator's pos-free frame would verify the wrong
        thing. This is what stops the interface block becoming the next
        ``mating_features``: a declared interface is checked against real
        geometry on every instantiation, not on the day it was authored.
        """
        part = self._registries.parts.get(part_id)
        generator = parse_generator(part.read_script(), source=str(part.script_path))
        overrides = _coerce_overrides(params, generator.param_names)
        build = self._build_generator(part, generator.script, overrides)
        result = build.result
        effective = dict(result.params)
        # Validated before anything expensive uses it, and before the fragment
        # spells it into a tag literal or a local name.
        prefix = instance_prefix_for(part.id, effective, pos, instance)
        scope = prefix[1:]
        metrics = result.metrics
        fragment = render_fragment(generator, part, effective, pos, instance)
        payload: dict[str, JSONValue] = {
            "script_fragment": fragment,
            # The *addressable* id (§8): bare when unique across the federated
            # `parts` registries, `<registry>/<id>` when two trees carry it. A
            # result that echoed the bare id under federation would hand back a
            # string that no longer resolves.
            "id": self._registries.parts.address(part),
            "params": cast("dict[str, JSONValue]", dict(effective)),
            "registry": part.registry,
            "registry_digest": part.digest,
            "metrics": {} if metrics is None else cast("JSONValue", metrics.to_json()),
        }
        component = part.component
        if component is not None:
            # PARTS_STORE.md §3, the G11A half of the result extension. Both
            # blocks are returned **verbatim as declared**: a declared mass is
            # data, not a measurement (§5), and a datasheet pointer is an audit
            # trail naming exactly which document to obtain (§7.4) — neither is
            # a claim that the harness verified anything.
            if component.mass is not None:
                self._check_computed_mass(part, component.mass, metrics)
                payload["mass"] = component.mass.to_json()
            if component.datasheet is not None:
                payload["datasheet"] = component.datasheet.to_json()
            claims = _wrapped_claims(part, component)
            if claims is not None:
                payload["claims"] = claims
            emitted = self._verify_interfaces(
                part=part,
                component=component,
                generator=generator,
                build=build,
                fragment=fragment,
                pos=pos,
                prefix=prefix,
                scope=scope,
            )
            payload["interfaces"] = cast("list[JSONValue]", list(emitted))
        return payload

    # -- computed mass (§5) -------------------------------------------------

    def _check_computed_mass(
        self, part: StorePart, mass: ComponentMass, metrics: Metrics | None
    ) -> None:
        """``source: "computed"`` agrees with the built envelope, or is refused.

        §5 admits a computed mass only for a *homogeneous* component, and only
        against a materials-registry density: "the value is then reproducible
        from the built envelope and is checked against it at instantiation to a
        declared tolerance". This is that check, and it is the one place in this
        stage where a declared number is graded against geometry rather than
        merely carried — the datasheet and standard sources are provenance, not
        predictions, so nothing can grade them.

        A disagreement is a refusal and never a repair: §5 is explicit that a
        declared and a computed mass "are never reconciled or averaged", so
        returning the measured value, or the mean, or the declared value with a
        warning, are all excluded. The record is wrong or the envelope is, and
        both are the author's to fix.
        """
        if mass.source != "computed":
            return
        material = self._registries.materials.get(mass.material)
        if material is None:
            raise RegistryError(
                "unsourced_component_datum",
                f"store component {part.id!r}: mass.source is 'computed' against material "
                f"{mass.material!r}, which this project's materials registry does not carry "
                f"(known: {', '.join(self._registries.materials.ids()) or '(none)'}) — the "
                "density the value is reproducible from is not here, so nothing can check it",
                data={"material": mass.material},
            )
        if metrics is None:
            raise RegistryError(
                "unsourced_component_datum",
                f"store component {part.id!r}: mass.source is 'computed' but the build "
                "reported no volume to compute it from",
                data={"material": mass.material},
            )
        # density is kg/m^3; 1 mm^3 = 1e-9 m^3 and 1 kg = 1e3 g, so the factor
        # between (mm^3 x kg/m^3) and grams is exactly 1e-6.
        expected_g = metrics.volume_mm3 * material.density * 1e-6
        allowed = abs(mass.value_g) * mass.tolerance_pct / 100.0
        if abs(expected_g - mass.value_g) <= allowed:
            return
        raise RegistryError(
            "computed_mass_disagreement",
            f"store component {part.id!r}: mass declares {mass.value_g} g as 'computed' from "
            f"{material.id} at {material.density} kg/m^3, but the built envelope's "
            f"{metrics.volume_mm3} mm^3 gives {expected_g} g — outside the declared "
            f"+/-{mass.tolerance_pct}% ({allowed} g). A declared and a computed mass are "
            "never reconciled or averaged (§5): fix the record or fix the envelope",
            data={
                "declared_g": mass.value_g,
                "computed_g": expected_g,
                "volume_mm3": metrics.volume_mm3,
                "density": material.density,
                "material": material.id,
                "tolerance_pct": mass.tolerance_pct,
            },
        )

    # -- interface verification (§2.3) --------------------------------------

    def _verify_interfaces(
        self,
        *,
        part: StorePart,
        component: ComponentRecord,
        generator: GeneratorSource,
        build: UnpublishedBuild,
        fragment: str,
        pos: Mapping[str, Any] | None,
        prefix: str,
        scope: str,
    ) -> tuple[str, ...]:
        """Check every declared interface against built topology; return the emitted names.

        Two builds' worth of evidence, and the second one is the point. The
        generator's own build tags the *unplaced* body, which is the frame the
        record's classes were authored in. The consumer instances at a ``pos``,
        and §2.1 evaluates the selectors after that placement — so a
        pos-dependent selector can pick a different face under a ``Rot`` than it
        picked at the origin. The second build runs the rendered fragment
        itself, so its tag placements are the *caller's*.
        """
        observed = _interface_evidence(build)
        emitted = tuple(f"{scope}{INTERFACE_TAG_INFIX}{name}" for name in generator.interface_names)
        self._check_declared(part, component, observed, at="the generator's own build")
        if not is_placed(pos):
            # `{prefix}` aliases the root when the placement expression is empty
            # (`_generator.py:262`), so the first build's placements ARE the
            # caller's and a second build would verify the same shape twice.
            # Rule 4 makes the cost gated, not merely disclosed: the origin case
            # pays nothing.
            return emitted
        placed = self._build_generator(
            part,
            f"{fragment}\npart.geometry = {prefix}\n",
            {},
            what="placement verification",
        )
        marker = f"{scope}{INTERFACE_TAG_INFIX}"
        scoped = {
            name[len(marker) :]: evidence
            for name, evidence in _interface_evidence(placed).items()
            if name.startswith(marker)
        }
        self._check_declared(part, component, scoped, at="the caller's placement")
        _check_placement_drift(part, component, unplaced=observed, placed=scoped)
        return emitted

    def _check_declared(
        self,
        part: StorePart,
        component: ComponentRecord,
        observed: Mapping[str, _Evidence],
        *,
        at: str,
    ) -> None:
        """§2.3's two of three verdicts, in the order that keeps each one reachable.

        The class check runs **before** the placement check, and that ordering is
        load-bearing rather than incidental: ``resolve_placements`` only locates
        solids, faces and edges, so a tag naming a wire or a vertex has
        ``solid_index=None`` and would otherwise be reported as
        ``interface_not_placed`` — "your anchor is dead" — when the truth is
        ``interface_class_mismatch``: an interface may not name one at all. The
        two refusals call for different fixes, so they are not allowed to
        collapse into whichever check happened to run first.
        """
        for interface in component.interfaces:
            evidence = observed.get(interface.name)
            if evidence is None:
                raise RegistryError(
                    "interface_not_placed",
                    f"store component {part.id!r}: interface {interface.name!r} was not "
                    f"tagged in {at}",
                    data={"interface": interface.name},
                )
            expected = INTERFACE_TOPOLOGY[interface.interface_class]
            if (evidence.kind, evidence.geom_type) != expected:
                raise RegistryError(
                    "interface_class_mismatch",
                    f"store component {part.id!r}: interface {interface.name!r} declares "
                    f"class {interface.interface_class!r}, whose one admissible topology is "
                    f"{expected}; {at} built {(evidence.kind, evidence.geom_type)}",
                    data={
                        "interface": interface.name,
                        "declared": interface.interface_class,
                        "observed_kind": evidence.kind,
                        "observed_geom_type": evidence.geom_type,
                    },
                )
            if evidence.solid_index is None:
                raise RegistryError(
                    "interface_not_placed",
                    f"store component {part.id!r}: interface {interface.name!r} tags "
                    f"topology that is not part of the final compound in {at}, so an "
                    "anchor naming it would be unaddressable",
                    data={"interface": interface.name},
                )

    def _build_generator(
        self,
        part: StorePart,
        script: str,
        overrides: Mapping[str, int | float],
        *,
        what: str = "generator",
    ) -> UnpublishedBuild:
        from hephaestus.core.executor.runner import BuildRequest, run_build

        backend = self._backend
        if backend is None:
            raise RegistryError(
                "capability_not_available",
                "no secure execution backend is configured; registry generators never "
                "run unsandboxed",
                data={"code": "capability_not_available"},
            )
        request = BuildRequest(
            part=part.id,
            script=script,
            globals_source=None,
            part_overrides=dict(overrides),
            origin="registry",
            wall_clock_s=self._wall_clock_s,
        )
        scratch_parent = self._scratch_root or Path(tempfile.gettempdir())
        scratch_parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="heph-store-", dir=scratch_parent))
        try:
            build = run_build(request, backend=backend, out_dir=scratch / "out")
        except RegistryError:
            raise
        except HephaestusError as exc:
            raise RegistryError(exc.code, f"store generator {part.id!r}: {exc.message}") from exc
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        result = build.result
        if result.status != "ok":
            error = result.error
            detail = "unknown failure" if error is None else f"{error.type}: {error.message}"
            raise RegistryError(
                _failure_reason(error),
                f"store generator {part.id!r} failed to build ({what}) — {detail}",
            )
        return build


#: What the ``claims`` result field says it is, in its own provenance header
#: (§6.3). Not ``performance`` and not ``specs``: a vocabulary that says "the
#: vendor asserts" is not the vocabulary that says "the harness verified".
CLAIMS_REFERENCE_KIND: str = "component-claims"


def _wrapped_claims(part: StorePart, component: ComponentRecord) -> str | None:
    """A component's ``claims`` as reference material, or ``None`` when it has none.

    §6.3's first enforcement point, and the reason the field is a *string* rather
    than a JSON array: **nothing in Hephaestus can evaluate a torque-speed curve**
    (§6 opens with that sentence), so a claim is reference material and reaches
    the model through the same provenance delimiters registry text already uses
    (``wrap_reference``) — header naming the component, the registry and its
    verified digest, footer restating that the enclosed bytes are reference
    material and not instructions. Returning the samples as a bare JSON array
    beside ``metrics`` would have put a vendor assertion in the same shape, and
    therefore the same standing, as something the harness measured.

    The body is ``sort_keys`` JSON so two processes produce identical bytes (§9:
    "declared data is copied, not computed").
    """
    if not component.claims:
        return None
    body = json.dumps(
        [claim.to_json() for claim in component.claims],
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    total = len(body.splitlines())
    return wrap_reference(
        body,
        kind=CLAIMS_REFERENCE_KIND,
        name=part.id,
        registry=part.registry,
        digest=part.digest,
        lines=f"1-{total}/{total}",
    )


#: A refusal the worker raises inside the sandbox, spelled as its own token at
#: the front of the message (``worker.py``'s ``_raise_unplaced_interface_tags``,
#: ``tags.py``'s scoped duplicate rule). The worker is a subprocess, so the only
#: channel is the §8 error record; reading the token back is what keeps the
#: refusal named end to end instead of collapsing into ``generator_failed``.
_WORKER_REFUSALS: tuple[str, ...] = ("interface_not_placed", "duplicate_tag")

#: §2.3: the descriptor's ``scalar`` must agree between the unplaced and the
#: placed build "to 1e-9 relative". The same ``rel_delta`` the §5.3 fingerprint
#: comparison uses, so drift is measured by one definition rather than two.
_DRIFT_REL_EPS: float = 1e-9


def _failure_reason(error: ErrorRecord | None) -> str:
    """Which named refusal a failed generator build is.

    A sandbox denial arrives as a *failed build record*, not as an exception —
    the worker is a subprocess, so ``SandboxDeniedError`` is caught there and
    reported through the §8 error record. It therefore missed the
    ``except HephaestusError`` arm above, which is the only path that ever
    produced ``sandbox_denied``, and every denial surfaced as the generic
    ``generator_failed``. ``RegistryError``'s own docstring lists
    ``sandbox_denied`` as one of its reasons, and ``PARTS_STORE.md`` G11A
    clause 22 requires a denied generator to be refused *with that reason*, so
    the record's type is read here rather than left unnamed. Discriminating it
    is what lets a caller tell "this generator asked for something the boundary
    forbids" from "this geometry did not build".
    """
    if error is None:
        return "generator_failed"
    if error.type in {"SandboxDeniedError", "sandbox_denied"}:
        return "sandbox_denied"
    for reason in _WORKER_REFUSALS:
        if error.message.startswith(f"{reason}:"):
            return reason
    if "arameter" in error.message:
        return "invalid_params"
    return "generator_failed"


@dataclass(frozen=True)
class _Evidence:
    """What one build observed about one tagged topology.

    ``kind`` is the three-way-plus classifier the source map records
    (``tags.py``'s ``_classify``, which is where ``wire`` and ``vertex`` are
    visible at all); ``geom_type`` and ``scalar`` come from the worker-computed
    descriptor, because nothing else crosses the sandbox boundary carrying a
    surface or curve type. One record from two channels, so §2.3's verdict is
    read off a single object rather than by zipping two dicts at each use.
    """

    kind: str
    geom_type: str
    scalar: float
    solid_index: int | None


def _interface_evidence(build: UnpublishedBuild) -> dict[str, _Evidence]:
    """Merge the in-memory source map and fingerprints into ``{tag: evidence}``.

    ``_build_generator`` deletes its scratch tree in a ``finally``, so the BRep
    and the source-map *file* are gone before the caller sees anything — but
    ``UnpublishedBuild`` carries ``source_map`` and ``tag_fingerprints`` in
    memory (``runner.py:126-131``), which is why §2.3 is computable at all
    without a new channel.
    """
    source_map = build.source_map or {}
    raw = source_map.get("tags")
    tags = cast("dict[str, JSONValue]", raw) if isinstance(raw, dict) else {}
    out: dict[str, _Evidence] = {}
    for name, descriptor in build.tag_fingerprints.items():
        entry = tags.get(name)
        row = cast("dict[str, JSONValue]", entry) if isinstance(entry, dict) else {}
        kind = row.get("kind")
        solid = row.get("solid")
        out[name] = _Evidence(
            kind=kind if isinstance(kind, str) else descriptor.kind,
            geom_type=descriptor.geom_type,
            scalar=descriptor.scalar,
            solid_index=solid if isinstance(solid, int) and not isinstance(solid, bool) else None,
        )
    return out


def _check_placement_drift(
    part: StorePart,
    component: ComponentRecord,
    *,
    unplaced: Mapping[str, _Evidence],
    placed: Mapping[str, _Evidence],
) -> None:
    """``interface_placement_drift`` — and its exact limit, stated not glossed.

    Area, length and volume are invariant under rigid motion, so for every
    interface tag the descriptor's ``geom_type`` and ``scalar`` must agree
    between the generator's pos-free build and the build at the caller's
    placement. A ``sort_by(Axis.Z)[-1]`` that picks a different face under a
    ``Rot`` almost always picks one of a *different measure*, and is caught.

    Two faces of **equal** measure are indistinguishable this way, so the check
    is a *necessary, not sufficient* condition for selector pos-invariance. That
    is why it reports drift and never certifies invariance: forbidding
    pos-dependent selectors is not decidable by a parser, and this spec does not
    pretend otherwise (§2.1).
    """
    for interface in component.interfaces:
        before = unplaced.get(interface.name)
        after = placed.get(interface.name)
        if before is None or after is None:
            continue
        if (
            before.geom_type != after.geom_type
            or rel_delta(after.scalar, before.scalar) > _DRIFT_REL_EPS
        ):
            raise RegistryError(
                "interface_placement_drift",
                f"store component {part.id!r}: interface {interface.name!r} selects "
                f"different topology at the caller's placement than at the origin "
                f"(geom_type {before.geom_type} -> {after.geom_type}, measure "
                f"{before.scalar!r} -> {after.scalar!r}). Order interface selectors by a "
                "MEASURE, which is invariant under the placement the consumer applies, "
                "not by a world axis, which is not",
                data={
                    "interface": interface.name,
                    "unplaced_geom_type": before.geom_type,
                    "placed_geom_type": after.geom_type,
                    "unplaced_scalar": before.scalar,
                    "placed_scalar": after.scalar,
                },
            )


def _coerce_overrides(params: Mapping[str, Any], declared: Sequence[str]) -> dict[str, int | float]:
    """Validate tool-supplied generator parameters (bounds are the worker's job)."""
    unknown = sorted(name for name in params if name not in declared)
    if unknown:
        raise RegistryError(
            "invalid_params",
            f"unknown parameter(s) {', '.join(unknown)}; declared: "
            + (", ".join(declared) or "(none)"),
            data={"declared": list(declared)},
        )
    out: dict[str, int | float] = {}
    for name, value in params.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RegistryError("invalid_params", f"parameter {name!r} must be a number")
        if not math.isfinite(float(value)):
            raise RegistryError("invalid_params", f"parameter {name!r} must be finite")
        out[name] = value
    return out
