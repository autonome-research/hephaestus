# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8A: provenance honesty and drift across a re-import.

Gate clauses: *source-map attribution of imported solids + the
no-per-face-statement rule*; *tag + drift fingerprint across a re-import that
moves a tagged face (warns with baseline ref, no-op re-import silent)*.

Both are asserted over **published** state — the source map and the warnings in
the §8 build record the model's own ``build_part`` produced — because that is
what a later reader (the reviewer, the DFM pass, a human) actually gets. The
drift fingerprint is the ONLY warning a moved face produces when a vendor file
is replaced, so the silent half matters as much as the loud one: a re-import of
identical bytes must say nothing at all, or the signal is worthless.
"""

from __future__ import annotations

import json

import pytest
from _g8a import StepFixtures, build_ok, install_import, source_map_of, write_script
from hephaestus.testing.tools_fixture import Project

PART = "vendor_plate"

TAGGED_SRC = """# the vendor's plate, with its top face named for later work
base = import_step("plate.step")
tag(base.faces().sort_by(Axis.Z)[-1], "plate_top")
part.geometry = base
"""

MIXED_SRC = """base = import_step("plate.step")
body = base - Cylinder(3, 20)
part.geometry = body
"""


@pytest.fixture
def with_plate(project: Project, steps: StepFixtures) -> Project:
    install_import(project.root, "plate.step", steps.plate)
    return project


def test_an_imported_solid_attributes_to_its_import_statement(with_plate: Project) -> None:
    """Binding scope: the solid points at the line that named the file."""
    write_script(with_plate, PART, TAGGED_SRC)
    build_ok(with_plate, PART)

    source_map = source_map_of(with_plate.cad, with_plate.store, PART)

    events = source_map["bindings"]["base"]
    assert events[0]["line"] == 2, source_map
    assert events[0]["call_site"] is None


def test_imported_topology_has_no_per_face_creating_statement(with_plate: Project) -> None:
    """The boolean honesty rule: no face of an import gets a statement."""
    write_script(with_plate, PART, MIXED_SRC)
    build_ok(with_plate, PART)

    source_map = source_map_of(with_plate.cad, with_plate.store, PART)

    assert set(source_map) == {"version", "bindings", "booleans", "tags"}
    assert "face" not in json.dumps(source_map)


def test_a_tag_on_imported_topology_survives_and_is_silent(with_plate: Project) -> None:
    write_script(with_plate, PART, TAGGED_SRC)
    build_ok(with_plate, PART)

    current = with_plate.cad.current_build(PART)
    assert current is not None
    assert current.warnings == ()
    source_map = source_map_of(with_plate.cad, with_plate.store, PART)
    assert "plate_top" in source_map["tags"]


def test_a_replacement_that_moves_a_tagged_face_warns(
    with_plate: Project, steps: StepFixtures
) -> None:
    """§5.3 drift is load-bearing here: it is the only warning a re-import gets."""
    write_script(with_plate, PART, TAGGED_SRC)
    build_ok(with_plate, PART)

    # The operator drops in a revision of the same vendor part, 3 mm thicker:
    # the script is untouched, and the face `plate_top` names has moved.
    install_import(with_plate.root, "plate.step", steps.plate_taller)
    build_ok(with_plate, PART)

    current = with_plate.cad.current_build(PART)
    assert current is not None
    drift = [w for w in current.warnings if w.kind == "tag_descriptor_changed"]
    assert [w.tag for w in drift] == ["plate_top"]
    assert drift[0].detail, "the warning must say what moved"


def test_a_reimport_of_identical_bytes_is_silent(with_plate: Project, steps: StepFixtures) -> None:
    write_script(with_plate, PART, TAGGED_SRC)
    build_ok(with_plate, PART)

    # Same file re-delivered: identical bytes, identical geometry, nothing to say.
    install_import(with_plate.root, "plate.step", steps.plate)
    build_ok(with_plate, PART)

    current = with_plate.cad.current_build(PART)
    assert current is not None
    assert current.warnings == ()
