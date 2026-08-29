"""Shared fixtures and helpers for Gate G11A (``PARTS_STORE.md``, Stage 11).

G11A is the *component record*: the validated block, its closed vocabularies,
the two rule-1 tightenings that ride with it, the publish-time provenance
scanners, the ``geom_type`` protocol field, and the operator listing. What it
deliberately is **not** is the interface region — that is G11B's parser, and the
Gates preamble records why item 11 (record ⇄ region set equality) had to move
there rather than stay here.

Two helper shapes carry most of the suite:

* :func:`component_tree` builds a one-part ``parts`` registry in ``tmp_path``
  around a component block, so a refusal clause is one dict edit rather than a
  fixture tree; and
* :func:`elide_digest_line` / :func:`header_digest` implement §1's split. The
  fragment header's second line carries the tree's Merkle root, which this
  stage moves *by construction* (item 19 edits six ``part.json`` files), so a
  gate asserting whole-fragment byte identity would be unsatisfiable. Body
  invariance is asserted under the elision; digest honesty is asserted
  separately against a recomputed root.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import pytest
from hephaestus.core.executor.sandbox.bwrap import find_bwrap
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    PartsIndex,
    Registry,
    load_registry,
)

REPO: Final[Path] = Path(__file__).resolve().parents[2]
REGISTRIES: Final[Path] = REPO / "registries"
SHIPPED_PARTS: Final[Path] = REGISTRIES / "parts"

#: The frozen legacy tree of named new work item 20. Edited by nothing in this
#: stage, which is the whole reason it exists.
LEGACY_PARTS: Final[Path] = Path(__file__).resolve().parent / "fixtures" / "legacy_parts"

GOLDENS: Final[Path] = Path(__file__).resolve().parent / "goldens"

#: Registry content executes only under a probed OS sandbox; a machine without
#: one cannot produce the instantiation half of the evidence, and must not fake
#: it (the same rule ``tests/stage6/_g6.py`` states).
requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="store generators execute only under a probed bwrap sandbox",
)

#: The header line whose digest §1 elides, replaced by a fixed sentinel.
DIGEST_SENTINEL: Final[str] = "# registry: <elided: the tree's Merkle root>"

_HEADER_PREFIX: Final[str] = "# registry: "


def elide_digest_line(fragment: str) -> str:
    """Replace the ``# registry: … @ <digest> …`` line with a fixed sentinel.

    §1: ``render_fragment``'s second header line embeds ``part.digest``, which
    is the Merkle root over the *whole* tree. Item 19's deliverable **is** a
    change to that root, so it moves the header of every fragment the tree
    produces — including parts item 19 never touched. That is what a Merkle root
    is for; the repair is to pin the body under an elision and assert digest
    honesty separately (clause 2), not to pin bytes that cannot hold still.
    """
    lines = fragment.splitlines(keepends=True)
    out: list[str] = []
    replaced = 0
    for line in lines:
        if line.startswith(_HEADER_PREFIX):
            out.append(DIGEST_SENTINEL + "\n")
            replaced += 1
            continue
        out.append(line)
    assert replaced == 1, f"expected exactly one {_HEADER_PREFIX!r} line, found {replaced}"
    return "".join(out)


def header_digest(fragment: str) -> str:
    """The ``sha256:…`` the fragment's provenance header states."""
    for line in fragment.splitlines():
        if line.startswith(_HEADER_PREFIX):
            rest = line[len(_HEADER_PREFIX) :]
            return rest.split(" @ ", 1)[1].split("  ", 1)[0].strip()
    raise AssertionError("fragment carries no registry provenance header")


def index_of(root: Path) -> PartsIndex:
    return PartsIndex(load_registry(root))


def registry_of(root: Path) -> Registry:
    return load_registry(root)


# --------------------------------------------------------------------------
# a component tree in one call


#: A generator whose PARAMS match :data:`BASE_PARAMS`. Deliberately trivial:
#: G11A never executes it except where a clause says so, and a simpler body
#: makes a refusal clause's failure unambiguous.
#:
#: The ``interface`` region is G11B's (``PARTS_STORE.md`` §2.1), and it is here
#: for the reason the Gates preamble names in writing: item 11 makes the record's
#: declared interface-name set and the region's emitted set equal at **index**
#: time, so once G11B lands a record declaring ``mount_face`` and ``shaft``
#: whose generator tags neither is ``unimplemented_interface`` and this fixture
#: would stop indexing. Nothing about G11A's own assertions changes — the
#: refusal clauses below still refuse for their own reasons, which run before
#: the equality check.
#:
#: Both selectors are ordered by a MEASURE, per §2.1's authoring rule: the shaft
#: is the only cylinder, and the mount face is the planar face nearest it once
#: the shaft's own end disc (always the smallest planar face) is dropped —
#: which holds across the whole declared ``body_length`` range, where "the
#: largest planar face" would not.
GENERATOR_SRC: Final[str] = (
    "# --- hephaestus-store: params ---\n"
    'PARAMS = {\n    "body_length": Param(39.0, min=20.0, max=60.0, doc="frame length, mm"),\n}\n'
    "# --- hephaestus-store: bind ---\n"
    "_body_length = p.body_length\n"
    "# --- hephaestus-store: body ---\n"
    "_frame = Box(42.3, 42.3, _body_length)\n"
    "_shaft = Pos(0, 0, _body_length / 2 + 12.0) * Cylinder(2.5, 24.0)\n"
    "_motor = _frame + _shaft\n"
    '_motor.label = "stepper_nema17_frame"\n'
    "part.geometry = _motor\n"
    "# --- hephaestus-store: interface ---\n"
    "tag(\n"
    "    _motor.faces()\n"
    "    .filter_by(GeomType.PLANE)\n"
    "    .sort_by(SortBy.AREA)[1:]\n"
    "    .sort_by_distance(\n"
    "        _motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0]\n"
    "    )[0],\n"
    '    "mount_face",\n'
    ")\n"
    "tag(_motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "
    '"shaft")\n'
)

BASE_PARAMS: Final[dict[str, Any]] = {
    "body_length": {"type": "float", "default": 39.0, "min": 20.0, "max": 60.0, "unit": "mm"}
}

DATASHEET: Final[dict[str, Any]] = {
    "publisher": "Standards Body (fixture)",
    "document_title": "Hybrid stepper motor, size 17 — datasheet (fixture)",
    "revision": "Rev C",
    "url": "https://example.invalid/nema17.pdf",
    "sha256": "sha256:" + "9f" * 32,
    "retrieved": "2026-08-20",
}


def motor_component(**overrides: Any) -> dict[str, Any]:
    """A valid ``motor`` record; ``overrides`` replace or add top-level keys.

    Passing ``None`` for a key deletes it, so a clause that must remove a block
    reads as ``motor_component(datasheet=None)`` rather than as a dict copy.
    """
    record: dict[str, Any] = {
        "class": "motor",
        "series": {"family": "nema", "size": "17", "standard": "NEMA ICS 16-2001"},
        "license": "Apache-2.0",
        "data_license": "facts-only",
        "frame": "mount face at Z=0; shaft along +Z",
        "simplifications": ["no winding detail", "shaft envelope only, no flat"],
        "interfaces": [
            {"name": "mount_face", "class": "planar_face", "role": "mount_face"},
            {"name": "shaft", "class": "cylindrical_face", "role": "shaft"},
        ],
    }
    for key, value in overrides.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    return record


#: The body of :data:`GENERATOR_SRC`, without its interface region.
GENERATOR_BODY: Final[str] = GENERATOR_SRC.split("# --- hephaestus-store: interface ---")[0]


def interface_region_for(names: Sequence[str]) -> str:
    """An interface region tagging exactly ``names``, for a fixture record.

    Item 11 makes the record's declared set and the region's emitted set equal
    at index time, so a fixture record declaring anything other than
    ``mount_face`` / ``shaft`` needs a generator that implements *its* names —
    otherwise every such fixture stops indexing for a reason that has nothing to
    do with the clause under test. The selectors are all rooted at ``_motor``
    and ordered by a measure, so they satisfy §2.1; which topology each one
    picks does not matter here, because the class check is §2.3's and runs at
    instantiation, which these record-schema clauses never reach.
    """
    lines = ["# --- hephaestus-store: interface ---"]
    # De-duplicated on purpose: a record declaring one name twice is
    # `duplicate_interface_name`, which the record parser raises BEFORE the
    # record ⇄ region comparison. Emitting the repeat here would make the region
    # itself invalid and the clause would then be pinning the wrong refusal.
    lines += [
        f'tag(_motor.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "{name}")'
        for name in dict.fromkeys(names)
    ]
    return "\n".join(lines) + "\n"


def component_tree(
    root: Path,
    component: Mapping[str, Any] | None,
    *,
    part_id: str = "stepper_nema17_frame",
    params: Mapping[str, Any] | None = None,
    generator: str | None = None,
    license_line: str | None = 'license = "Apache-2.0"',
    extra_meta: Mapping[str, Any] | None = None,
) -> Path:
    """Write a one-part ``parts`` registry at ``root`` and return it.

    When ``generator`` is not given, the fixture generator implements exactly
    the interfaces ``component`` declares (see :func:`interface_region_for`).
    """
    if generator is None:
        declared = [
            str(entry.get("name", ""))
            for entry in cast("list[dict[str, Any]]", (component or {}).get("interfaces") or [])
        ]
        generator = (
            GENERATOR_SRC
            if component is None or declared == ["mount_face", "shaft"]
            else GENERATOR_BODY + interface_region_for(declared)
        )
    directory = root / part_id
    directory.mkdir(parents=True, exist_ok=True)
    header = [
        "[registry]",
        'name = "fixture-parts"',
        'kind = "parts"',
        'version = "0.0.1"',
    ]
    if license_line is not None:
        header.append(license_line)
    header += ["", "[[parts]]", f'id = "{part_id}"', f'dir = "{part_id}"', ""]
    (root / MANIFEST_FILENAME).write_text("\n".join(header), encoding="utf-8")
    meta: dict[str, Any] = {
        "id": part_id,
        "name": "Fixture component",
        "summary": "A fixture component record.",
        "keywords": ["fixture"],
        "params": dict(BASE_PARAMS if params is None else params),
    }
    if component is not None:
        meta["component"] = dict(component)
    if extra_meta:
        meta.update(extra_meta)
    (directory / "part.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (directory / "generator.py").write_text(generator, encoding="utf-8")
    return root
