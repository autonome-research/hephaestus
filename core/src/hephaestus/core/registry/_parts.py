"""The ``parts`` registry's generator index.

Each store part is a directory holding ``part.json`` (metadata plus the declared
params schema) and ``generator.py`` (the *executable* content, run only under a
secure sandbox by :class:`~hephaestus.core.registry.RegistryOps`). This module
indexes and searches them; it never executes anything.

A part whose ``part.json`` carries a ``component`` block is a **component**
(``PARTS_STORE.md`` §1): its record is parsed and validated here, so a malformed
one is a named refusal at index time — and therefore at publish, since
``validate_content`` builds the index (``_publish.py:50-63``). A part without
the block is a **legacy store part** and behaves exactly as it did before,
which G11A clauses 1-3 pin.

Two ``PARTS_STORE.md`` §1 tightenings live here, both under mission rule 1:

* the declared ``params`` are cross-checked against the generator's ``PARAMS``
  (``param_schema_drift``). The *authoritative* parameter list at execution is
  the generator's — ``_coerce_overrides(params, generator.param_names)`` in
  ``_ops.py`` — so a record advertising a parameter the generator lacks used to
  publish cleanly and fail only when a model tried to set it; and
* the index parses the generator source to do it. That costs this module its
  "never executes anything" property? It does not: parsing is not executing,
  and ``parse_generator`` is a pure AST check. The property being preserved is
  that no untrusted registry source *runs* outside the sandbox.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

if TYPE_CHECKING:
    from ._generator import GeneratorSource

from ._component import ComponentRecord, parse_component
from ._errors import RegistryError, RegistryRefusal
from ._fields import opt_str, req_str, str_tuple
from ._layout import MANIFEST_FILENAME, Registry
from ._search import score

__all__ = ["QUALIFIER", "PartsIndex", "StorePart"]

_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

#: Separates a registry name from a part id in a federated address (§8). A part
#: id may not contain it (``_ID_RE``), so ``<registry>/<id>`` parses without
#: ambiguity and a bare id can never be mistaken for a qualified one.
QUALIFIER: Final[str] = "/"

#: Keys the pre-component ``part.json`` carried that nothing read. §1 resolves
#: them rather than preserving them: ``origin`` became the record's ``frame``
#: statement, ``simplifications`` became a required list on the validated
#: block, ``envelope`` folded into the generator that already owns those
#: numbers, and ``mating_features`` is *deleted* — a clearance hole the consumer
#: must retype is exactly what an emitted interface tag replaces. Leaving an
#: unread key beside a read one would teach the next author that either is fine.
RETIRED_KEYS: Final[tuple[str, ...]] = (
    "envelope",
    "mating_features",
    "origin",
    "simplifications",
)


@dataclass(frozen=True)
class StorePart:
    """One parts-store generator: metadata, params schema, and its script.

    ``component`` is ``None`` for a legacy store part. Everything downstream
    branches on that and on nothing else.
    """

    id: str
    name: str
    summary: str
    keywords: tuple[str, ...]
    params: Mapping[str, JSONValue]
    preview: str
    script_path: Path
    registry: str
    digest: str
    component: ComponentRecord | None = None

    @property
    def is_component(self) -> bool:
        return self.component is not None

    @property
    def qualified_id(self) -> str:
        """``<registry>/<id>`` — the address that is unique across federation (§8)."""
        return f"{self.registry}{QUALIFIER}{self.id}"

    def read_script(self) -> str:
        return self.script_path.read_text(encoding="utf-8")

    def search_result(self, address: str | None = None) -> dict[str, JSONValue]:
        """The ``search_parts_store`` row (§3).

        A legacy part's row is byte-identical to what it was before this stage;
        the component fields appear only for a component record, so "carries no
        component fields" is a property a test can assert (G11A clause 1).

        ``interfaces`` carries the names **as declared, unprefixed**: the
        instance prefix is not known until instantiation, so a search row cannot
        spell the anchor a constraint will name. It is returned only now that
        G11B's record ⇄ region set equality (item 11) holds, which is what makes
        a declared name evidence that the generator really emits a tag for it —
        before that it would have advertised anchors that may not exist.

        ``address`` is the id the caller must hand back to ``instance_store_part``
        — the bare id when it is unique across the federated ``parts`` registries
        and ``<registry>/<id>`` when it is not (§8). Returning the *addressable*
        id rather than always the bare one is what stops search advertising two
        indistinguishable rows the model cannot then instance; ``registry`` and
        ``registry_digest`` still name the tree either row came from, which is
        G11C clause 10.
        """
        row: dict[str, JSONValue] = {
            "id": self.id if address is None else address,
            "name": self.name,
            "params": dict(self.params),
            "preview": self.preview,
            "registry": self.registry,
            "registry_digest": self.digest,
        }
        component = self.component
        if component is None:
            return row
        row["component_class"] = component.component_class
        row["series"] = component.series.to_json()
        row["interfaces"] = [interface.to_json() for interface in component.interfaces]
        row["has_datasheet"] = component.datasheet is not None
        if component.mass is not None:
            row["mass_g"] = component.mass.value_g
        return row


class PartsIndex:
    """The ``parts`` registries' merged generator index (``search_parts_store``).

    **Merged federation** (``PARTS_STORE.md`` §8, G11C item 25). ``RegistrySet``
    used to keep one registry per kind, which silently discarded a second
    ``parts`` tree; G11A turned that into ``duplicate_registry_kind``, and this
    index is the repair the refusal was holding the place for: several ``parts``
    registries index *together*.

    Addressing follows from that, and the rule is a refusal rather than a
    precedence order. A part id unique across the resolved trees resolves bare,
    exactly as it did when there was only ever one tree. A id two trees both
    carry resolves only as ``<registry>/<id>``; addressed bare it is
    ``ambiguous_component_id``, naming both candidates. Choosing a winner by
    table order is the failure §8 opens with — the operator, not the index,
    decides which pack they meant.
    """

    def __init__(self, registries: Registry | Sequence[Registry] | None) -> None:
        resolved: tuple[Registry, ...]
        if registries is None:
            resolved = ()
        elif isinstance(registries, Registry):
            resolved = (registries,)
        else:
            resolved = tuple(registries)
        self._registries = resolved
        #: Every indexed part, keyed by its ``<registry>/<id>`` address — the one
        #: key that is unique by construction.
        self._parts: dict[str, StorePart] = {}
        #: Bare id -> the qualified addresses carrying it, in resolution order.
        #: Length > 1 is exactly the ambiguity ``get`` refuses on.
        self._bare: dict[str, list[str]] = {}
        for registry in resolved:
            self._index(registry)

    def _index(self, registry: Registry) -> None:
        for item in registry.manifest.parts:
            record = cast("Mapping[str, Any]", item)
            source = f"{registry.root / MANIFEST_FILENAME} [[parts]]"
            part_id = req_str(record, "id", source=source)
            if not _ID_RE.match(part_id):
                raise ValidationError(
                    f"{source}: part id {part_id!r} must match {_ID_RE.pattern}", kind="contract"
                )
            directory = registry.root / opt_str(record, "dir", part_id)
            metadata_path = directory / "part.json"
            script_path = directory / "generator.py"
            for path in (metadata_path, script_path):
                if not path.is_file():
                    raise ValidationError(f"{source}: {path} is missing", kind="contract")
            raw_meta: object = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(raw_meta, dict):
                raise ValidationError(f"{metadata_path}: must be a JSON object", kind="contract")
            meta = cast("Mapping[str, Any]", raw_meta)
            raw_params = meta.get("params")
            params: dict[str, JSONValue] = (
                cast("dict[str, JSONValue]", dict(cast("Mapping[str, Any]", raw_params)))
                if isinstance(raw_params, dict)
                else {}
            )
            generator = _parse_generator(script_path)
            _check_param_schema(params, generator, source=str(metadata_path))
            component = _parse_component_block(meta, part_id, source=str(metadata_path))
            _check_interface_declaration(component, generator, source=str(metadata_path))
            part = StorePart(
                id=part_id,
                name=opt_str(meta, "name", part_id),
                summary=opt_str(meta, "summary"),
                keywords=str_tuple(meta, "keywords"),
                params=params,
                preview=opt_str(meta, "preview") or opt_str(meta, "summary"),
                script_path=script_path,
                registry=registry.name,
                digest=registry.digest,
                component=component,
            )
            if part.qualified_id in self._parts:
                raise ValidationError(
                    f"{source}: part id {part_id!r} is declared twice in registry "
                    f"{registry.name!r}",
                    kind="contract",
                )
            self._parts[part.qualified_id] = part
            self._bare.setdefault(part_id, []).append(part.qualified_id)

    # -- addressing (§8) ----------------------------------------------------

    def address(self, part: StorePart) -> str:
        """The id a caller hands back: bare when unique, ``<registry>/<id>`` else."""
        return part.id if len(self._bare.get(part.id, ())) == 1 else part.qualified_id

    def ids(self) -> tuple[str, ...]:
        """Every *addressable* id, sorted.

        With one ``parts`` registry resolved — every project before federation,
        and every project after it that pins one pack — this is exactly the sorted
        bare ids it always was. A bare id two trees both carry never appears here,
        because addressing it bare is a refusal, not a choice of winner: only its
        two qualified forms are listed, which is also what makes the
        ``unknown_store_part`` candidate list a set of ids that actually resolve.
        """
        return tuple(sorted(self.address(part) for part in self._parts.values()))

    def component_ids(self) -> tuple[str, ...]:
        """Addressable ids of the parts carrying a validated ``component`` block."""
        return tuple(
            sorted(self.address(part) for part in self._parts.values() if part.is_component)
        )

    def get(self, part_id: str) -> StorePart:
        """Resolve one addressable id, refusing an ambiguous bare one by name."""
        if QUALIFIER in part_id:
            part = self._parts.get(part_id)
            if part is not None:
                return part
            raise self._unknown(part_id)
        candidates = self._bare.get(part_id, [])
        if len(candidates) == 1:
            return self._parts[candidates[0]]
        if not candidates:
            raise self._unknown(part_id)
        # §8: "a named ``ambiguous_component_id`` refusal rather than a
        # precedence rule". Which pack the operator meant is not derivable from
        # table order, and answering with either one is a silent wrong answer of
        # exactly the kind the federation work exists to remove.
        raise RegistryError(
            "ambiguous_component_id",
            f"store part id {part_id!r} is carried by {len(candidates)} pinned parts "
            f"registries; address it as one of {', '.join(candidates)} — which pack was "
            "meant is the operator's to say, not this index's to guess",
            data={"id": part_id, "candidates": cast("list[JSONValue]", list(candidates))},
        )

    def _unknown(self, part_id: str) -> RegistryError:
        return RegistryError(
            "unknown_store_part",
            f"no store part {part_id!r}; available ids: " + (", ".join(self.ids()) or "(none)"),
            data={"candidates": cast("list[JSONValue]", list(self.ids()))},
        )

    def search(self, query: str, max_results: int) -> list[dict[str, JSONValue]]:
        scored: list[tuple[int, str]] = []
        for qualified in sorted(self._parts):
            part = self._parts[qualified]
            matched = score(query, (part.id, part.name, part.summary, " ".join(part.keywords)))
            if matched:
                scored.append((matched, qualified))
        # Ties break on the *address*, so a federated result order is a property
        # of the ids and not of which tree happened to be pinned first.
        scored.sort(key=lambda pair: (-pair[0], self.address(self._parts[pair[1]])))
        return [
            self._parts[qualified].search_result(address=self.address(self._parts[qualified]))
            for _matched, qualified in scored[:max_results]
        ]


def _parse_generator(script_path: Path) -> GeneratorSource:
    """Parse and contract-check one generator, once, for every index-time rule."""
    # Imported here, not at module scope: ``_generator`` imports ``StorePart``
    # from this module, and one lazy import is cheaper than splitting the
    # fragment contract in two to break the cycle.
    from ._generator import parse_generator

    return parse_generator(script_path.read_text(encoding="utf-8"), source=str(script_path))


def _check_interface_declaration(
    component: ComponentRecord | None, generator: GeneratorSource, *, source: str
) -> None:
    """Record ⇄ region interface-name set equality (``PARTS_STORE.md`` §2.1).

    This is ``_dfm.py``'s "a predicate can therefore never read an undeclared
    number" generalised: a generator can never emit an undeclared interface, and
    a record can never declare one its generator does not implement. A surplus
    is ``undeclared_interface``, a shortfall ``unimplemented_interface``, and
    each names the offending interface rather than reporting that the sets
    differ.

    **The boundary, stated rather than left to be discovered.** The comparison
    runs for a *component record*. A store part with no ``component`` block
    declares no interfaces at all, and this check does not synthesise an empty
    declaration for it: G11B clause 6 scopes both refusals to "the same record",
    and the frozen pre-item-19 fixture G11A clause 3 rests on is exactly a
    pre-component ``part.json`` paired with the current generator — refusing
    that pairing here would break a clause of the preceding sub-gate to close a
    hole no shipped content can reach. What that leaves open is narrow and
    named: a *legacy* store part could add an interface region and emit tags no
    record declares. Nothing in the repository does, and a part gaining a region
    is a part gaining a record.
    """
    if component is None:
        return
    declared = set(component.interface_names)
    implemented = set(generator.interface_names)
    surplus = sorted(implemented - declared)
    shortfall = sorted(declared - implemented)
    if surplus:
        raise RegistryRefusal(
            "undeclared_interface",
            f"{source}: the generator's interface region tags {', '.join(surplus)}, which "
            "the component record does not declare; a model discovers interfaces through "
            "the record, so an undeclared emitted tag is an anchor nothing can find",
            detail={"interfaces": cast("list[JSONValue]", surplus)},
        )
    if shortfall:
        raise RegistryRefusal(
            "unimplemented_interface",
            f"{source}: the component record declares {', '.join(shortfall)}, which the "
            "generator's interface region never tags; a declared interface with no tag "
            "is exactly the 'mating_features' failure — metadata a consumer must retype "
            "because nothing emits it",
            detail={"interfaces": cast("list[JSONValue]", shortfall)},
        )


def _check_param_schema(
    params: Mapping[str, JSONValue], generator: GeneratorSource, *, source: str
) -> None:
    """``part.json.params`` ⇄ the generator's ``PARAMS``, named per parameter.

    Both directions: a record advertising a parameter the generator lacks is as
    wrong as one omitting a parameter the generator declares. The first makes a
    model set something that does not exist; the second hides a knob from
    search while the build path still accepts it.
    """
    declared = set(params)
    implemented = set(generator.param_names)
    surplus = sorted(declared - implemented)
    shortfall = sorted(implemented - declared)
    if not surplus and not shortfall:
        return
    parts: list[str] = []
    if surplus:
        parts.append(f"part.json declares {', '.join(surplus)} which PARAMS does not")
    if shortfall:
        parts.append(f"PARAMS declares {', '.join(shortfall)} which part.json does not")
    raise RegistryRefusal(
        "param_schema_drift",
        f"{source}: {'; '.join(parts)} (the generator's PARAMS is authoritative at "
        "execution — _ops.py passes it to _coerce_overrides)",
        detail={
            "surplus": cast("list[JSONValue]", surplus),
            "shortfall": cast("list[JSONValue]", shortfall),
        },
    )


def _parse_component_block(
    meta: Mapping[str, Any], part_id: str, *, source: str
) -> ComponentRecord | None:
    raw = meta.get("component")
    if raw is None:
        _refuse_retired_keys(meta, source=source, component=False)
        return None
    if not isinstance(raw, dict):
        raise RegistryRefusal(
            "malformed_component_record", f"{source}: 'component' must be a JSON object"
        )
    _refuse_retired_keys(meta, source=source, component=True)
    return parse_component(cast("Mapping[str, Any]", raw), source=f"{source} [{part_id}]")


def _refuse_retired_keys(meta: Mapping[str, Any], *, source: str, component: bool) -> None:
    """§1's "resolved, not preserved" rule, enforced on component records only.

    A legacy part keeps its old keys — that is what "behaves exactly as today"
    means, and refusing them would break the very compatibility G11A clause 1
    asserts. A *component* record may not carry them: they are either promoted
    into the validated block or deleted, and a component that kept both would
    be the ``mating_features`` mistake shipped twice.
    """
    if not component:
        return
    present = [key for key in RETIRED_KEYS if key in meta]
    if present:
        raise RegistryRefusal(
            "retired_metadata_key",
            f"{source}: a component record may not carry {', '.join(present)}; §1 promotes "
            "'origin' to component.frame and 'simplifications' to the validated block, "
            "folds 'envelope' into the generator, and deletes 'mating_features' — an "
            "emitted interface tag is what replaces a clearance hole the consumer retypes",
            detail={"keys": cast("list[JSONValue]", present)},
        )
