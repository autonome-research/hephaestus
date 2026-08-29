"""Shared scaffolding for Gate G11C (provenance, federation, and the corpus).

G11C is the sub-stage where the component store stops being a self-contained
thing and joins the rest of the system: a datasheet becomes a *citable*
provenance record through ``INGEST.md``'s reference registry and the
``VALIDATION.md`` §2 ledger, several ``parts`` registries index together, and
the component-bearing corpus family lands.

Three fixtures carry it.

:func:`motor_component` is a record that really does carry the whole provenance
chain — a ``datasheet`` pointer with all six §7.3 fields and a ``claims`` entry
citing a page and quote in it — which nothing in ``registries/parts`` does and
nothing in it may do. The operator's D3 decision is REFERENCE, DO NOT VENDOR,
and the pointer's ``sha256`` must be the digest of *the exact document the
numbers were transcribed from*. No such document was obtained for this stage, so
inventing a hash for a shipped record would have been fabricating provenance:
the shipped packs carry no ``datasheet`` and no ``claims`` at all, and every
clause about them is asserted against this fixture, whose document is written
here, in this file, and whose digest is therefore real.

:func:`make_project` builds a project that pins that fixture registry, so the
ledger's ``cite.component`` has something to resolve against. It pins the
bundled ``registries/parts`` too — which is federation happening for real rather
than being simulated, and is why the fixture's part id is deliberately unlike
any shipped one.

:func:`register_reference` is the operator's side of §7.4 step 1, through the
same :class:`ReferenceRegistry` ``heph reference add`` drives.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

import pytest
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.core.executor.sandbox.bwrap import find_bwrap
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.references import ReferenceEntry, ReferenceRegistry
from hephaestus.core.registry import MANIFEST_FILENAME, RegistryOps, RegistrySet, load_registry

from opstore import OpStore

__all__ = [
    "CLAIM_ID",
    "DATASHEET_BYTES",
    "DATASHEET_NAME",
    "DATASHEET_QUOTE",
    "DATASHEET_SHA256",
    "HOLDING_TORQUE_NM",
    "OTHER_BYTES",
    "PART_ID",
    "SHIPPED_PARTS",
    "component_tree",
    "datasheet_block",
    "make_project",
    "motor_component",
    "ops_for",
    "register_reference",
    "requires_bwrap",
    "sha256_of",
]

#: The shipped bundled tree, for the federation and search clauses.
SHIPPED_PARTS: Final[Path] = Path(__file__).resolve().parents[2] / "registries" / "parts"

#: Registry content executes only under a probed OS sandbox; a machine without
#: one cannot produce the instantiation half of the evidence, and must not fake
#: it (the rule ``tests/stage11a/_g11a.py`` and ``tests/stage11b/_g11b.py``
#: state, and G11C inherits rather than restates).
requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="store generators execute only under a probed bwrap sandbox",
)

#: The fixture datasheet's own bytes. Written here so its digest is a fact this
#: suite can compute rather than a constant it has to trust — which is exactly
#: what ``datasheet_digest_mismatch`` is about, so the fixture may not cheat on
#: it. Plain text, so a core-only install registers it with no extractor
#: (``references.py`` decodes ``text/markdown`` itself); clause 8 covers the
#: PDF path that needs one.
DATASHEET_BYTES: Final[bytes] = (
    b"# Fixture stepper datasheet, revision C\n"
    b"\n"
    b"Frame size 17 (NEMA ICS 16). Step angle 1.8 degrees.\n"
    b"Holding torque 0.44 N*m at 1.5 A per phase.\n"
    b"Rated current 1.5 A per phase. Winding resistance 2.3 ohm.\n"
)

#: A DIFFERENT revision of the same document: same subject, different bytes,
#: therefore a different digest. This is the revision-drift case §7.4 names.
OTHER_BYTES: Final[bytes] = DATASHEET_BYTES.replace(b"revision C", b"revision D")

DATASHEET_NAME: Final[str] = "fixture-stepper.md"
DATASHEET_QUOTE: Final[str] = "Holding torque 0.44 N*m"
#: The claim's declared value, and the number a ``CHECKS`` threshold retypes.
HOLDING_TORQUE_NM: Final[float] = 0.44
CLAIM_ID: Final[str] = "torque_speed"
#: Deliberately unlike every shipped id, so pinning this tree beside the bundled
#: one federates without colliding — the collision is its own clause, staged on
#: purpose rather than by accident.
PART_ID: Final[str] = "fixture_stepper_frame"


def sha256_of(data: bytes) -> str:
    """``sha256:<hex>`` — the digest form the whole system uses."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


DATASHEET_SHA256: Final[str] = sha256_of(DATASHEET_BYTES)


def datasheet_block(sha256: str | None = None) -> dict[str, Any]:
    """The §7.3 pointer, all six fields, redistributing nothing."""
    return {
        "publisher": "Fixture Motion Components",
        "document_title": "Fixture stepper datasheet",
        "revision": "Rev C",
        "url": "https://example.invalid/fixture-stepper.md",
        "sha256": DATASHEET_SHA256 if sha256 is None else sha256,
        "retrieved": "2026-08-29",
    }


def motor_component(**overrides: Any) -> dict[str, Any]:
    """A motor record carrying the whole §5/§6/§7 chain; ``None`` deletes a key."""
    record: dict[str, Any] = {
        "class": "motor",
        "series": {"family": "fixture", "size": "17", "standard": "NEMA ICS 16"},
        "license": "Apache-2.0",
        "data_license": "reference-by-citation",
        "frame": "mount face on the shaft axis; body into -Z",
        "simplifications": ["a provenance fixture, not a motor"],
        "interfaces": [
            {"name": "mount_face", "class": "planar_face", "role": "mount_face"},
            {"name": "shaft", "class": "cylindrical_face", "role": "shaft"},
        ],
        "mass": {"value_g": 280.0, "source": "datasheet", "com_mm": [0.0, 0.0, -19.5]},
        "datasheet": datasheet_block(),
        "claims": [
            {
                "id": CLAIM_ID,
                "kind": "torque_speed_curve",
                "unit_x": "rpm",
                "unit_y": "N*m",
                "samples": [[0.0, HOLDING_TORQUE_NM], [200.0, 0.42], [600.0, 0.28]],
                "cite": {"page": 1, "quote": DATASHEET_QUOTE},
            }
        ],
    }
    for key, value in overrides.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    return record


#: A generator whose geometry offers exactly the two declared interfaces, each
#: selected by a measure so it survives the consumer's placement (§2.1).
GENERATOR_SRC: Final[str] = """# A provenance fixture: a plate with a boss, not a motor.
# --- hephaestus-store: params ---
PARAMS = {
    "boss_h": Param(4.0, min=2.0, max=10.0, doc="boss height above the plate, mm"),
}
# --- hephaestus-store: bind ---
_boss_h = p.boss_h
# --- hephaestus-store: body ---
_plate = Box(30.0, 20.0, 6.0)
_boss = Pos(0.0, 0.0, 3.0 + _boss_h / 2) * Cylinder(4.0, _boss_h)
_rig = _plate + _boss
_rig.label = "fixture_stepper_frame"
part.geometry = _rig

# --- hephaestus-store: interface ---
tag(_rig.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")
tag(_rig.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "shaft")
"""


def component_tree(
    root: Path,
    *,
    part_id: str = PART_ID,
    component: Mapping[str, Any] | None = None,
    generator: str = GENERATOR_SRC,
    registry_name: str = "fixture-parts",
    params: Mapping[str, Any] | None = None,
) -> Path:
    """Write a one-part ``parts`` registry at ``root`` and return it.

    Built here rather than imported from ``tests/stage11a`` or ``stage11b``: a
    gate assertion must not be satisfiable by an edit to another sub-gate's
    fixture.
    """
    directory = root / part_id
    directory.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_FILENAME).write_text(
        "\n".join(
            [
                "[registry]",
                f'name = "{registry_name}"',
                'kind = "parts"',
                'version = "0.0.1"',
                'license = "Apache-2.0"',
                "",
                "[[parts]]",
                f'id = "{part_id}"',
                f'dir = "{part_id}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    declared = (
        {"boss_h": {"type": "float", "default": 4.0, "min": 2.0, "max": 10.0, "unit": "mm"}}
        if params is None
        else dict(params)
    )
    meta: dict[str, Any] = {
        "id": part_id,
        "name": "Fixture stepper frame",
        "summary": "A provenance fixture carrying a datasheet pointer and a claim.",
        "keywords": ["fixture", "stepper", "motor", "provenance"],
        "params": declared,
    }
    record = motor_component() if component is None else component
    if record is not None:
        meta["component"] = dict(record)
    (directory / "part.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (directory / "generator.py").write_text(generator, encoding="utf-8")
    return root


def ops_for(tmp_path: Path, *roots: Path, backend: Any = None) -> RegistryOps:
    """A :class:`RegistryOps` over ``roots`` (federated), sandboxed by default."""
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

    registries = {f"parts-{index}": load_registry(root) for index, root in enumerate(roots)}
    materials = SHIPPED_PARTS.parent / "materials"
    registries["materials"] = load_registry(materials)
    store = OpStore.create(tmp_path / "ops-store")
    return RegistryOps(
        RegistrySet(registries),
        store,
        backend=BwrapBackend() if backend is None else backend,
        scratch_root=tmp_path / "scratch",
        wall_clock_s=180.0,
    )


class ProjectFixture:
    """A project on disk plus the handles the ledger and lint clauses need."""

    def __init__(self, root: Path, layout: ProjectLayout, store: OpStore, cad: CadOps) -> None:
        self.root = root
        self.layout = layout
        self.store = store
        self.cad = cad
        self._n = 0

    def op_id(self) -> str:
        self._n += 1
        return f"g11c-{self._n:04d}"

    def references(self) -> ReferenceRegistry:
        return ReferenceRegistry(self.layout, self.store)


def make_project(
    root: Path,
    *,
    registries: Mapping[str, Path] | None = None,
    parts: Mapping[str, str] | None = None,
) -> ProjectFixture:
    """A project pinning ``registries`` by name, with ``parts`` written out.

    The pins go straight into ``hephaestus.toml``'s ``[registries]`` table, the
    one path ``RegistrySet.open`` reads. Pinned by path with no digest, exactly
    as ``bundled_pins()`` does, because a digest pinned in a fixture would have
    to be re-recorded every time the tree it names moves — and moving it is what
    several of this stage's own clauses do.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    lines = ["[project]", 'name = "g11c"', ""]
    for name, path in (registries or {}).items():
        lines += [f"[registries.{name}]", f'path = "{path}"', ""]
    (root / "hephaestus.toml").write_text("\n".join(lines), encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    for name, script in (parts or {}).items():
        (root / "parts" / f"{name}.py").write_text(script, encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    return ProjectFixture(root, layout, store, CadOps(layout, store))


def register_reference(
    project: ProjectFixture, data: bytes, *, name: str = DATASHEET_NAME
) -> ReferenceEntry:
    """The operator's side of §7.4 step 1 (what ``heph reference add`` drives)."""
    return project.references().add_bytes(data, name=name)


def entries(state: Any) -> list[dict[str, Any]]:
    """A ledger state's entries as the plain JSON objects ``heph lint`` consumes."""
    return [cast("dict[str, Any]", entry.to_json()) for entry in state.entries]
