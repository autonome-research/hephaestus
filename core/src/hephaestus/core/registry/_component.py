"""The validated component record a ``parts`` entry may carry (PARTS_STORE.md §1).

A *component* is a store part whose ``part.json`` carries a ``component``
block. A part without one is a **legacy store part** and is untouched by
everything here — that compatibility is the point of the split, and G11A
clauses 1-3 are its evidence.

Why a validated record rather than the opaque metadata blob that shipped
before: ``envelope`` / ``mating_features`` / ``origin`` / ``simplifications``
were read by *no* code and reached *no* tool result, so a
``clearance_hole_mm`` reached a design only by a model retyping it out of
prose. §Design premise names the failure and names the trap in fixing it —
"data that nothing can consume is decoration" — so every field parsed here is
either consumed by a tool result, checked by a rule, or refused. There is no
third category.

The vocabularies are **closed** on purpose. ``class`` drives the
required-interface table, so an open string would make that table
unenforceable; an interface ``class`` drives §2.3's built-topology
verification, so a class the 8C/Stage-9 consumers cannot use is refused rather
than stored (the ``mating_features`` mistake, one level up). Each later member
is a contract amendment, the ``ASSEMBLY.md:45`` / ``KINEMATICS.md:95``
convention.

Refusals raised here are :class:`RegistryRefusal`, i.e. contract
``ValidationError``\\ s carrying a machine token, so they refuse the index —
and therefore refuse ``heph registry publish``, which builds the index
(``_publish.py:50-63``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from opstore.types import JSONValue

from ._errors import RegistryRefusal

__all__ = [
    "CLAIM_KINDS",
    "COMPONENT_CLASSES",
    "INTERFACE_CLASSES",
    "INTERFACE_NAME_RE",
    "INTERFACE_TOPOLOGY",
    "MASS_SOURCES",
    "REQUIRED_INTERFACE_ROLES",
    "TRADEMARK_DENY_LIST",
    "UNIT_X",
    "UNIT_Y",
    "ComponentClaim",
    "ComponentDatasheet",
    "ComponentInterface",
    "ComponentMass",
    "ComponentRecord",
    "ComponentSeries",
    "parse_component",
]

#: The closed component ``class`` set (§1). A value outside it is
#: ``unknown_component_kind``.
COMPONENT_CLASSES: Final[tuple[str, ...]] = (
    "motor",
    "bearing",
    "gear",
    "encoder",
    "fastener",
    "insert",
    "coupling_hw",
    "pulley",
    "leadscrew",
)

#: The closed interface ``class`` set (§2.3). Exactly what 8C ``coincident`` /
#: ``concentric`` / ``fit`` and Stage 9 ``revolute`` / ``prismatic`` can use,
#: and no more.
INTERFACE_CLASSES: Final[tuple[str, ...]] = (
    "planar_face",
    "cylindrical_face",
    "circular_edge",
    "linear_edge",
    "solid",
)

#: §2.3's decision table, written out as the total function it is: declared
#: interface class -> the one admissible ``(kind, geom_type)`` pair. Every other
#: pair is ``interface_class_mismatch``, and three consequences are meant.
#:
#: ``geom_type`` is ``OTHER`` for a solid **by definition**, not by failure — a
#: solid has no single adaptor, the worker writes ``OTHER``, and the table admits
#: exactly that pair, so ``("solid", "OTHER")`` is a positive verification of the
#: declared ``solid`` class rather than a fallthrough. A face whose surface is a
#: torus, a cone or a B-spline classifies ``("face", "OTHER")`` and matches no
#: row: that is a refusal, because this stage's consumers (8C ``coincident`` /
#: ``concentric`` / ``fit``, Stage 9 ``revolute`` / ``prismatic``) accept none of
#: them, and admitting a class the consumers cannot use is how ``mating_features``
#: happened. And ``wire`` / ``vertex`` appear in no row at all.
INTERFACE_TOPOLOGY: Final[Mapping[str, tuple[str, str]]] = {
    "planar_face": ("face", "PLANE"),
    "cylindrical_face": ("face", "CYLINDER"),
    "circular_edge": ("edge", "CIRCLE"),
    "linear_edge": ("edge", "LINE"),
    "solid": ("solid", "OTHER"),
}

#: Required interface *roles* per component class (§1). A ``bearing`` without a
#: ``bore`` and an ``outer`` is not a bearing record. This is what stops the
#: block degenerating into the optional prose ``mating_features`` was.
REQUIRED_INTERFACE_ROLES: Final[Mapping[str, tuple[str, ...]]] = {
    "motor": ("shaft", "mount_face"),
    "bearing": ("bore", "outer"),
    "gear": ("bore",),
    "encoder": ("mount_face",),
    "fastener": ("shank",),
    "insert": ("bore",),
    "coupling_hw": ("bore",),
    "pulley": ("bore",),
    "leadscrew": ("shaft",),
}

#: Closed ``mass.source`` set (§5).
MASS_SOURCES: Final[tuple[str, ...]] = ("datasheet", "standard", "computed")

#: Closed ``claims[].kind`` set (§6.1).
CLAIM_KINDS: Final[tuple[str, ...]] = (
    "torque_speed_curve",
    "load_rating",
    "speed_limit",
    "resolution",
    "backlash",
    "efficiency_curve",
)

#: Closed declared-unit sets for a claim's two axes (§6.2 "declared units from
#: a closed unit set"). Open units would make ``malformed_performance_curve``
#: unable to say what it validated.
UNIT_X: Final[tuple[str, ...]] = ("rpm", "rad/s", "mm", "N", "deg", "count", "Hz")
UNIT_Y: Final[tuple[str, ...]] = ("N*m", "N", "mm", "deg", "rpm", "ratio", "percent")

#: An interface name, a claim id: the same grammar (§2.1, §6.1). ``__`` is
#: reserved for the emitted ``<instance>__<name>`` form (§2.2), so a declared
#: name may not contain it.
INTERFACE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

#: Vendor marks that may not appear in a component id (§7.2). Ids are generic
#: or standard-derived (``bearing_608``, ``stepper_nema17_frame``), never
#: ``<vendor>_<sku>``. Deliberately a *maintained* list and deliberately not the
#: only control: ``docs/registry-contributions.md:27-31``'s human review is.
TRADEMARK_DENY_LIST: Final[tuple[str, ...]] = (
    "bosch",
    "delrin",
    "dyson",
    "fanuc",
    "festo",
    "igus",
    "loctite",
    "makita",
    "maxon",
    "misumi",
    "nema23hs",  # a vendor SKU shape, not the NEMA standard's frame size
    "nsk",
    "nvidia",
    "oriental",
    "parker",
    "rexroth",
    "schneider",
    "skf",
    "smc",
    "teflon",
    "thk",
    "timken",
    "trinamic",
    "velcro",
    "yaskawa",
)

_SHA256_PREFIX: Final[str] = "sha256:"
_DATASHEET_FIELDS: Final[tuple[str, ...]] = (
    "publisher",
    "document_title",
    "revision",
    "url",
    "sha256",
    "retrieved",
)

#: Field names that carry an inertia tensor under any spelling. §5 refuses them
#: by name: ``Metrics`` has no mass/COM/inertia slot and ``KINEMATICS.md:51-54``
#: puts configuration-level inertia out of scope, so storing one silently would
#: be "Finding A1 with more decimal places".
_INERTIA_FIELDS: Final[tuple[str, ...]] = ("inertia", "inertia_tensor", "moi", "inertia_kg_mm2")


def _mapping(value: object) -> Mapping[str, Any] | None:
    return cast("Mapping[str, Any]", value) if isinstance(value, dict) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


@dataclass(frozen=True)
class ComponentSeries:
    """``{family, size, standard}`` — §4's answer to the enumerated parameter.

    A NEMA 17 and a NEMA 23 are two part ids sharing ``family``; search groups
    them. ``Param`` is ``int | float`` only, so an enum parameter would have
    been a core parameter-system change this stage does not need (§4).
    """

    family: str = ""
    size: str = ""
    standard: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {"family": self.family, "size": self.size, "standard": self.standard}


@dataclass(frozen=True)
class ComponentInterface:
    """One declared mounting interface: ``{name, class, role}`` (§2)."""

    name: str
    interface_class: str
    role: str

    def to_json(self) -> dict[str, JSONValue]:
        return {"name": self.name, "class": self.interface_class, "role": self.role}


@dataclass(frozen=True)
class ComponentMass:
    """A declared mass (§5). ``com_mm`` is *data*: nothing computes or checks it."""

    value_g: float
    source: str
    com_mm: tuple[float, float, float] | None = None
    material: str = ""
    tolerance_pct: float = 0.0

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {"value_g": self.value_g, "source": self.source}
        if self.com_mm is not None:
            out["com_mm"] = list(self.com_mm)
        if self.material:
            out["material"] = self.material
        if self.tolerance_pct:
            out["tolerance_pct"] = self.tolerance_pct
        return out


@dataclass(frozen=True)
class ComponentDatasheet:
    """A pointer that redistributes nothing (§7.3): all six fields required.

    The URL is provenance, **not a fetch target** — nothing in Hephaestus
    retrieves it, and a registry that fetched at load would break the offline,
    content-addressed determinism the trust model rests on.
    """

    publisher: str
    document_title: str
    revision: str
    url: str
    sha256: str
    retrieved: str

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "publisher": self.publisher,
            "document_title": self.document_title,
            "revision": self.revision,
            "url": self.url,
            "sha256": self.sha256,
            "retrieved": self.retrieved,
        }


@dataclass(frozen=True)
class ComponentClaim:
    """Declared, provenance-bearing datasheet data (§6.1).

    Named ``claims`` and not ``performance`` or ``specs`` on purpose: a
    vocabulary that says "the vendor asserts" is not the vocabulary that says
    "the harness verified". Nothing in Hephaestus can evaluate a torque-speed
    curve today (§6.3), so a claim is reference material, never an input to a
    verdict.
    """

    id: str
    kind: str
    unit_x: str
    unit_y: str
    samples: tuple[tuple[float, float], ...]
    page: int
    quote: str

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "kind": self.kind,
            "unit_x": self.unit_x,
            "unit_y": self.unit_y,
            "samples": [[x, y] for x, y in self.samples],
            "cite": {"page": self.page, "quote": self.quote},
        }


@dataclass(frozen=True)
class ComponentRecord:
    """The validated ``component`` block of one store part (§1)."""

    component_class: str
    series: ComponentSeries
    license: str
    data_license: str
    interfaces: tuple[ComponentInterface, ...]
    simplifications: tuple[str, ...] = ()
    frame: str = ""
    mass: ComponentMass | None = None
    datasheet: ComponentDatasheet | None = None
    claims: tuple[ComponentClaim, ...] = ()

    @property
    def interface_names(self) -> tuple[str, ...]:
        return tuple(interface.name for interface in self.interfaces)

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "class": self.component_class,
            "series": self.series.to_json(),
            "license": self.license,
            "data_license": self.data_license,
            "interfaces": [interface.to_json() for interface in self.interfaces],
            "simplifications": list(self.simplifications),
            "frame": self.frame,
        }
        if self.mass is not None:
            out["mass"] = self.mass.to_json()
        if self.datasheet is not None:
            out["datasheet"] = self.datasheet.to_json()
        if self.claims:
            out["claims"] = [claim.to_json() for claim in self.claims]
        return out


def parse_component(raw: Mapping[str, Any], *, source: str) -> ComponentRecord:
    """Parse and validate one ``component`` block; every failure is named.

    Order matters only where a later rule presupposes an earlier one: the class
    is checked before the required-interface table it selects, and the
    datasheet block before the claims whose ``cite`` must land in it.
    """
    component_class = _parse_class(raw, source=source)
    interfaces = _parse_interfaces(raw, source=source)
    _check_required_interfaces(component_class, interfaces, source=source)
    _refuse_inertia(raw, source=source)
    series = _parse_series(raw, source=source)
    datasheet = _parse_datasheet(raw, source=source)
    mass = _parse_mass(raw, series=series, datasheet=datasheet, source=source)
    claims = _parse_claims(raw, datasheet=datasheet, source=source)
    simplifications = _parse_simplifications(raw, source=source)
    return ComponentRecord(
        component_class=component_class,
        series=series,
        license=_req_text(raw, "license", source=source),
        data_license=_opt_text(raw, "data_license"),
        interfaces=interfaces,
        simplifications=simplifications,
        frame=_opt_text(raw, "frame"),
        mass=mass,
        datasheet=datasheet,
        claims=claims,
    )


def _req_text(raw: Mapping[str, Any], key: str, *, source: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise RegistryRefusal(
            "malformed_component_record",
            f"{source}: component.{key} is required and must be a non-empty string",
            detail={"field": key},
        )
    return value


def _opt_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _parse_class(raw: Mapping[str, Any], *, source: str) -> str:
    value = raw.get("class")
    if not isinstance(value, str) or value not in COMPONENT_CLASSES:
        raise RegistryRefusal(
            "unknown_component_kind",
            f"{source}: component.class {value!r} is not one of {', '.join(COMPONENT_CLASSES)}",
            detail={
                "observed": value if isinstance(value, str) else None,
                "valid": list(COMPONENT_CLASSES),
            },
        )
    return value


def _parse_series(raw: Mapping[str, Any], *, source: str) -> ComponentSeries:
    block = _mapping(raw.get("series"))
    if block is None:
        return ComponentSeries()
    return ComponentSeries(
        family=_opt_text(block, "family"),
        size=_opt_text(block, "size"),
        standard=_opt_text(block, "standard"),
    )


def _parse_interfaces(raw: Mapping[str, Any], *, source: str) -> tuple[ComponentInterface, ...]:
    listed = raw.get("interfaces")
    if not isinstance(listed, list) or not listed:
        raise RegistryRefusal(
            "malformed_component_record",
            f"{source}: component.interfaces must be a non-empty list",
        )
    out: list[ComponentInterface] = []
    seen: set[str] = set()
    for index, item in enumerate(cast("list[Any]", listed)):
        entry = _mapping(item)
        if entry is None:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: component.interfaces[{index}] must be an object",
            )
        name = entry.get("name")
        if not isinstance(name, str) or not INTERFACE_NAME_RE.match(name) or "__" in name:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: interface name {name!r} must match "
                f"{INTERFACE_NAME_RE.pattern} and contain no '__'",
                detail={"index": index},
            )
        if name in seen:
            raise RegistryRefusal(
                "duplicate_interface_name",
                f"{source}: interface name {name!r} is declared twice; an emitted "
                "'<instance>__<name>' tag must resolve to exactly one thing",
                detail={"name": name},
            )
        seen.add(name)
        interface_class = entry.get("class")
        if not isinstance(interface_class, str) or interface_class not in INTERFACE_CLASSES:
            raise RegistryRefusal(
                "unknown_interface_class",
                f"{source}: interface {name!r} declares class {interface_class!r}; "
                f"valid classes are {', '.join(INTERFACE_CLASSES)}",
                detail={"name": name, "valid": list(INTERFACE_CLASSES)},
            )
        role = entry.get("role")
        if not isinstance(role, str) or not role:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: interface {name!r} must declare a non-empty role",
                detail={"name": name},
            )
        out.append(ComponentInterface(name=name, interface_class=interface_class, role=role))
    return tuple(out)


def _check_required_interfaces(
    component_class: str, interfaces: Sequence[ComponentInterface], *, source: str
) -> None:
    required = REQUIRED_INTERFACE_ROLES.get(component_class, ())
    present = {interface.role for interface in interfaces}
    missing = [role for role in required if role not in present]
    if missing:
        raise RegistryRefusal(
            "missing_required_interface",
            f"{source}: a {component_class!r} record must declare an interface with role "
            f"{', '.join(missing)}; declared roles: " + (", ".join(sorted(present)) or "(none)"),
            detail={"component_class": component_class, "missing": list(missing)},
        )


def _refuse_inertia(raw: Mapping[str, Any], *, source: str) -> None:
    for field in _INERTIA_FIELDS:
        if field in raw:
            raise RegistryRefusal(
                "inertia_out_of_scope",
                f"{source}: component.{field} is refused — Metrics carries no mass, centre "
                "of mass or inertia, nothing consumes a tensor, and configuration-level "
                "inertia is deliberately out of scope (KINEMATICS.md:51-54)",
                detail={"field": field},
            )
    mass_block = _mapping(raw.get("mass"))
    if mass_block is not None:
        for field in _INERTIA_FIELDS:
            if field in mass_block:
                raise RegistryRefusal(
                    "inertia_out_of_scope",
                    f"{source}: component.mass.{field} is refused — nothing consumes an "
                    "inertia tensor (KINEMATICS.md:51-54)",
                    detail={"field": f"mass.{field}"},
                )


def _parse_datasheet(raw: Mapping[str, Any], *, source: str) -> ComponentDatasheet | None:
    block = _mapping(raw.get("datasheet"))
    if block is None:
        if "datasheet" in raw:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: component.datasheet must be an object",
            )
        return None
    values: dict[str, str] = {}
    for field in _DATASHEET_FIELDS:
        value = block.get(field)
        if not isinstance(value, str) or not value:
            raise RegistryRefusal(
                "malformed_datasheet_pointer",
                f"{source}: component.datasheet.{field} is required (all six pointer "
                "fields are, §7.3) and must be a non-empty string",
                detail={"field": field},
            )
        values[field] = value
    if not values["sha256"].startswith(_SHA256_PREFIX):
        raise RegistryRefusal(
            "malformed_datasheet_pointer",
            f"{source}: component.datasheet.sha256 must carry the {_SHA256_PREFIX!r} prefix "
            "the rest of the system uses (_publish.py:132-133)",
            detail={"field": "sha256", "observed": values["sha256"]},
        )
    return ComponentDatasheet(
        publisher=values["publisher"],
        document_title=values["document_title"],
        revision=values["revision"],
        url=values["url"],
        sha256=values["sha256"],
        retrieved=values["retrieved"],
    )


def _parse_mass(
    raw: Mapping[str, Any],
    *,
    series: ComponentSeries,
    datasheet: ComponentDatasheet | None,
    source: str,
) -> ComponentMass | None:
    block = _mapping(raw.get("mass"))
    if block is None:
        if "mass" in raw:
            raise RegistryRefusal(
                "malformed_component_record", f"{source}: component.mass must be an object"
            )
        return None
    value_g = _number(block.get("value_g"))
    if value_g is None or not math.isfinite(value_g) or value_g <= 0.0:
        raise RegistryRefusal(
            "malformed_component_record",
            f"{source}: component.mass.value_g must be a finite positive number (grams)",
        )
    mass_source = block.get("source")
    if not isinstance(mass_source, str) or mass_source not in MASS_SOURCES:
        raise RegistryRefusal(
            "malformed_component_record",
            f"{source}: component.mass.source {mass_source!r} is not one of "
            f"{', '.join(MASS_SOURCES)}",
        )
    material = _opt_text(block, "material")
    if mass_source == "datasheet" and material:
        raise RegistryRefusal(
            "mass_source_conflict",
            f"{source}: component.mass declares source 'datasheet' and a computed-mass "
            f"material id {material!r}; a declared and a computed mass are never reconciled "
            "or averaged (§5)",
            detail={"material": material},
        )
    if mass_source == "datasheet" and datasheet is None:
        raise RegistryRefusal(
            "unsourced_component_datum",
            f"{source}: component.mass.source is 'datasheet' but the record carries no "
            "datasheet block; a recalled number is a rumour with units on it (§5)",
            detail={"field": "mass"},
        )
    if mass_source == "standard" and not series.standard:
        raise RegistryRefusal(
            "unsourced_component_datum",
            f"{source}: component.mass.source is 'standard' but the record declares no "
            "series.standard to source it from (§5)",
            detail={"field": "mass"},
        )
    if mass_source == "computed" and not material:
        raise RegistryRefusal(
            "unsourced_component_datum",
            f"{source}: component.mass.source is 'computed' but no materials-registry id "
            "is named; a computed mass is reproducible only from a declared density (§5)",
            detail={"field": "mass"},
        )
    if mass_source == "computed" and not (_number(block.get("tolerance_pct")) or 0.0) > 0.0:
        # §5: a computed mass "is checked against [the built envelope] at
        # instantiation to a declared tolerance". Zero is the dataclass default,
        # and a zero tolerance makes that check unsatisfiable by construction —
        # so the record would ship a field whose only possible verdict is
        # failure. Refusing here is what keeps G11C clause 2 a real check rather
        # than a decorative one; the tolerance is the author's honest statement
        # of how far their envelope is from the real part.
        raise RegistryRefusal(
            "malformed_component_record",
            f"{source}: component.mass.source is 'computed' but no positive tolerance_pct "
            "is declared; §5 checks a computed value against the built envelope's "
            "volume x density to a *declared* tolerance, and an undeclared one can only "
            "ever fail",
            detail={"field": "mass.tolerance_pct"},
        )
    com_raw = block.get("com_mm")
    com: tuple[float, float, float] | None = None
    if com_raw is not None:
        if not isinstance(com_raw, list) or len(cast("list[Any]", com_raw)) != 3:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: component.mass.com_mm must be [x, y, z] in the component frame",
            )
        coords: list[float] = []
        for value in cast("list[Any]", com_raw):
            number = _number(value)
            if number is None or not math.isfinite(number):
                raise RegistryRefusal(
                    "malformed_component_record",
                    f"{source}: component.mass.com_mm must be three finite numbers",
                )
            coords.append(number)
        com = (coords[0], coords[1], coords[2])
    tolerance = _number(block.get("tolerance_pct")) or 0.0
    return ComponentMass(
        value_g=value_g,
        source=mass_source,
        com_mm=com,
        material=material,
        tolerance_pct=tolerance,
    )


def _parse_claims(
    raw: Mapping[str, Any], *, datasheet: ComponentDatasheet | None, source: str
) -> tuple[ComponentClaim, ...]:
    listed = raw.get("claims")
    if listed is None:
        return ()
    if not isinstance(listed, list):
        raise RegistryRefusal(
            "malformed_component_record", f"{source}: component.claims must be a list"
        )
    items = cast("list[Any]", listed)
    if items and datasheet is None:
        # §6.1's first closure rule: without it a `cite` could name a page and
        # quote in a block that is not there, and §7.4's join would have no
        # right-hand side at all.
        raise RegistryRefusal(
            "unsourced_component_datum",
            f"{source}: component.claims is non-empty but the record carries no datasheet "
            "block; a cite naming a page and quote in a block that is not there cites "
            "nothing (§6.1)",
            detail={"field": "claims"},
        )
    out: list[ComponentClaim] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        entry = _mapping(item)
        if entry is None:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: component.claims[{index}] must be an object",
            )
        claim_id = entry.get("id")
        if not isinstance(claim_id, str) or not INTERFACE_NAME_RE.match(claim_id):
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: claims[{index}].id {claim_id!r} must match {INTERFACE_NAME_RE.pattern}",
            )
        if claim_id in seen:
            raise RegistryRefusal(
                "duplicate_claim_id",
                f"{source}: claim id {claim_id!r} is declared twice; a ledger "
                "cite.claim must resolve to exactly one claim (§6.1)",
                detail={"claim": claim_id},
            )
        seen.add(claim_id)
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in CLAIM_KINDS:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: claims[{index}].kind {kind!r} is not one of {', '.join(CLAIM_KINDS)}",
            )
        cite = _mapping(entry.get("cite"))
        page = None if cite is None else cite.get("page")
        quote = None if cite is None else cite.get("quote")
        if (
            cite is None
            or isinstance(page, bool)
            or not isinstance(page, int)
            or page < 1
            or not isinstance(quote, str)
            or not quote
        ):
            raise RegistryRefusal(
                "unsourced_component_datum",
                f"{source}: claim {claim_id!r} must carry a cite naming a page (>= 1) and a "
                "quote in the record's datasheet block (§6.1)",
                detail={"claim": claim_id},
            )
        unit_x = entry.get("unit_x")
        unit_y = entry.get("unit_y")
        if not isinstance(unit_x, str) or unit_x not in UNIT_X:
            raise RegistryRefusal(
                "malformed_performance_curve",
                f"{source}: claim {claim_id!r} declares unit_x {unit_x!r}; declared units "
                f"come from the closed set {', '.join(UNIT_X)}",
                detail={"claim": claim_id, "axis": "x"},
            )
        if not isinstance(unit_y, str) or unit_y not in UNIT_Y:
            raise RegistryRefusal(
                "malformed_performance_curve",
                f"{source}: claim {claim_id!r} declares unit_y {unit_y!r}; declared units "
                f"come from the closed set {', '.join(UNIT_Y)}",
                detail={"claim": claim_id, "axis": "y"},
            )
        samples = _parse_samples(entry.get("samples"), claim_id=claim_id, kind=kind, source=source)
        out.append(
            ComponentClaim(
                id=claim_id,
                kind=kind,
                unit_x=unit_x,
                unit_y=unit_y,
                samples=samples,
                page=page,
                quote=quote,
            )
        )
    return tuple(out)


def _parse_samples(
    raw: object, *, claim_id: str, kind: str, source: str
) -> tuple[tuple[float, float], ...]:
    """§6.2 well-formedness, and *only* well-formedness.

    This turns a transcription error into a load-time contract error instead of
    a plausible-looking number, which is the entire honest benefit available at
    this stage — nothing here evaluates a curve, and §6.3 says why.
    """

    def refuse(index: int, detail: str) -> RegistryRefusal:
        return RegistryRefusal(
            "malformed_performance_curve",
            f"{source}: claim {claim_id!r} sample {index}: {detail}",
            detail={"claim": claim_id, "sample": index},
        )

    if not isinstance(raw, list):
        raise refuse(0, "samples must be a list of [x, y] pairs")
    items = cast("list[Any]", raw)
    if len(items) < 2:
        raise refuse(
            len(items),
            f"a {kind} needs at least two samples; a one-point curve states nothing",
        )
    pairs: list[tuple[float, float]] = []
    for index, item in enumerate(items):
        if not isinstance(item, list) or len(cast("list[Any]", item)) != 2:
            raise refuse(index, "each sample must be an [x, y] pair")
        x = _number(cast("list[Any]", item)[0])
        y = _number(cast("list[Any]", item)[1])
        if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
            raise refuse(index, "both values must be finite numbers")
        if index and x <= pairs[-1][0]:
            raise refuse(index, f"x must strictly increase (got {x} after {pairs[-1][0]})")
        if y < 0.0:
            raise refuse(index, f"y must be non-negative (got {y})")
        if index and y > pairs[-1][1]:
            raise refuse(
                index, f"y must be non-increasing across the range (got {y} after {pairs[-1][1]})"
            )
        pairs.append((x, y))
    return tuple(pairs)


def _parse_simplifications(raw: Mapping[str, Any], *, source: str) -> tuple[str, ...]:
    """§1: a required non-empty list on any component whose geometry is an envelope.

    Store geometry *is* an envelope — the shipped M3 screw already documents
    itself as a "DIN 912 envelope" — so the list is required outright rather
    than conditioned on a flag nothing sets.
    """
    listed = raw.get("simplifications")
    if not isinstance(listed, list) or not listed:
        raise RegistryRefusal(
            "malformed_component_record",
            f"{source}: component.simplifications must be a non-empty list; a component's "
            "geometry is clean-room envelope geometry and must say how it is simplified",
        )
    out: list[str] = []
    for item in cast("list[Any]", listed):
        if not isinstance(item, str) or not item:
            raise RegistryRefusal(
                "malformed_component_record",
                f"{source}: component.simplifications entries must be non-empty strings",
            )
        out.append(item)
    return tuple(out)
