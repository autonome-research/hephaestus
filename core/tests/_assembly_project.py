"""Shared builders for the Stage 8C assembly tests (not a test module).

Builds a real two-part project whose parts mate: ``base`` is a bored plate,
``pin`` is a shaft that sits in the bore with a 0.1 mm radial clearance. That
one pair is enough to exercise every anchor form (whole part, tag, label,
binding) and both sides of a declared ``fit`` window, and it is REAL geometry
published through the ordinary build path — an assembly status computed from a
synthetic artifact would prove nothing about anchor resolution against a
reloaded BRep, which is the part of ``ASSEMBLY.md`` §2 with something to get
wrong.
"""

from __future__ import annotations

from pathlib import Path

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import PublicationOutcome, Publisher
from opstore.types import JSONValue
from test_project_store_helpers import make_project

from opstore import OpStore

#: A bored plate. One cylindrical face (the bore, tagged) so the whole part is
#: also a usable ``fit`` anchor.
BASE_SCRIPT = (
    "plate = Box(40, 40, 10)\n"
    "bored = plate - Cylinder(radius=5.0, height=40)\n"
    'tag(bored.faces().filter_by(GeomType.CYLINDER)[0], "bore_face")\n'
    "part.geometry = bored\n"
)

#: The mating shaft. ``spare`` is bound but never reaches ``part.geometry``: it
#: is the binding-with-no-geometry case the unresolvable taxonomy must name.
PIN_SCRIPT = (
    "shaft_body = Cylinder(radius={radius}, height=30)\n"
    'tag(shaft_body.faces().filter_by(GeomType.CYLINDER)[0], "shaft_face")\n'
    "spare = Box(1, 1, 1)\n"
    "part.geometry = shaft_body\n"
)

#: Declared but never built: the ``no_current_build`` case.
UNBUILT_SCRIPT = "part.geometry = Box(2, 2, 2)\n"

#: Radial clearance of the default pair: 5.0 - 4.9.
NOMINAL_CLEARANCE_MM = 0.1


def pin_script(radius: float = 4.9) -> str:
    """The pin script at a given shaft radius (the edit staleness turns on)."""
    return PIN_SCRIPT.format(radius=radius)


def make_assembly_project(root: Path, *, radius: float = 4.9) -> ProjectLayout:
    """A project with ``base``, ``pin`` (unbuilt) and ``never_built``."""
    return make_project(
        root,
        parts={
            "base": BASE_SCRIPT,
            "pin": pin_script(radius),
            "never_built": UNBUILT_SCRIPT,
        },
    )


def build_part(publisher: Publisher, layout: ProjectLayout, part: str) -> PublicationOutcome:
    """Freeze, build and publish one part through the ordinary pipeline."""
    frozen = publisher.freeze_inputs(part)
    build = run_build(
        BuildRequest(
            part=part,
            script=frozen.script,
            globals_source=frozen.globals_source,
        ),
        backend=UnsafeLocalBackend(),
        out_dir=layout.store_root / "builds" / f"{part}-{len(part)}",
    )
    assert build.result.status == "ok", build.result.error
    outcome = publisher.publish_build(build, op_id=f"build-{part}-{build.result.artifact_ref}")
    assert outcome.kind == "current", outcome.details
    return outcome


def open_project(root: Path, *, radius: float = 4.9) -> tuple[ProjectLayout, OpStore]:
    """A built project: ``base`` and ``pin`` published, ``never_built`` untouched."""
    layout = make_assembly_project(root, radius=radius)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in ("base", "pin"):
        build_part(publisher, layout, part)
    return layout, store


def fit_entry(**overrides: JSONValue) -> dict[str, JSONValue]:
    """The canonical ``fit`` entry of ``ASSEMBLY.md`` §1, tag-anchored."""
    entry: dict[str, JSONValue] = {
        "id": "c-pin-fit",
        "kind": "fit",
        "a": "base:bore_face",
        "b": "pin:shaft_face",
        "min_mm": 0.05,
        "max_mm": 0.2,
        "provenance": {"requirement": "r-1"},
        "note": "slip fit per datasheet",
    }
    entry.update(overrides)
    return entry


def assumed(reason: str = "no requirement covers this interface yet") -> dict[str, JSONValue]:
    """The `assumed` provenance every test entry that cites no requirement carries."""
    return {"assumed": True, "reason": reason}
