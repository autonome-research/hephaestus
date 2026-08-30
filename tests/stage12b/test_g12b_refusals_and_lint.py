# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12B clauses 30-31: the mesh-derived split — a hard refusal, and a named lint.

``MESH_INGEST.md`` §4.3 splits enforcement deliberately, and this module asserts
both halves *and the boundary between them*, because a split whose weak half is
mistaken for the strong one is worse than either alone:

* where enforcement is real — the object ``mesh_to_solid`` itself returned —
  offset, shell/thicken and fillet are refused ``mesh_derived_operation_refused``;
* where it is not, ``heph lint`` emits ``mesh_derived_offset``, and this suite
  includes a **defeating case the lint does not flag**, so the rule's reach is
  pinned and can never be read as a guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _g12b import Fixtures, build_error, canonical_arrays, install_import
from hephaestus.core.lint import lint_script
from hephaestus.geom.mesh import MeshOperationError
from hephaestus.geom.mesh_solid import (
    MESH_DERIVED_REFUSED_OPERATIONS,
    MeshDerivedSolid,
    gate_sewn_solid,
    sew_to_solid,
)
from hephaestus.testing.tools_fixture import Project

# ==========================================================================
# the §10 vocabulary this sub-gate adds, asserted CLOSED


def test_the_conversion_and_operations_vocabulary_is_closed_and_disjoint() -> None:
    """§10's "conversion and operations" group is exactly five codes, and none of
    them collides with the eleven admission codes.

    The two vocabularies must not merge, and the reason is a reader's next
    action: an admission refusal says "the harness will not read this FILE" and
    one of these says "the harness read your file, it is fine, and it will not
    turn it into THAT". Sending someone to re-export a scan that has nothing
    wrong with it is a worse outcome than saying nothing.
    """
    from hephaestus.geom.mesh import MESH_OPERATION_REFUSALS, MESH_REFUSALS

    assert MESH_OPERATION_REFUSALS == (
        "mesh_sew_timeout",
        "mesh_solid_invalid",
        "mesh_derived_operation_refused",
        "open_section_contour",
        "empty_section",
    )
    assert set(MESH_OPERATION_REFUSALS).isdisjoint(MESH_REFUSALS)
    assert len(MESH_REFUSALS) == 11


def test_every_code_in_that_vocabulary_is_actually_raised_somewhere() -> None:
    """A closed set with an unreachable member is a set that has stopped
    describing the code.

    Each of the five is provoked here by the smallest thing that provokes it, so
    a future refactor that stopped raising one fails a clause rather than
    leaving a dead string in a ``Literal``. ``mesh_sew_timeout`` is asserted in
    the sew-ceiling clause instead, because provoking it costs a subprocess.
    """
    import numpy as np
    from hephaestus.core.mesh_solid import MeshSewTimeout
    from hephaestus.geom.mesh import section_polylines
    from hephaestus.geom.mesh_solid import loft_sections

    raised: set[str] = set()
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    faces = np.array([[0, 1, 2]], dtype=np.int64)

    with pytest.raises(MeshOperationError) as empty:
        section_polylines(vertices, faces, origin=(0.0, 0.0, 9.0), normal=(0.0, 0.0, 1.0))
    raised.add(empty.value.reason)

    open_contour = section_polylines(
        vertices, faces, origin=(0.0, 0.0, 0.0), normal=(0.0, 1.0, 0.0)
    )[0]
    assert open_contour.closed is False
    with pytest.raises(MeshOperationError) as opened:
        loft_sections([open_contour, open_contour])
    raised.add(opened.value.reason)

    # ``mesh_solid_invalid`` and ``mesh_derived_operation_refused`` have their
    # own clauses above; named here so the set is complete rather than partial.
    raised.update({"mesh_solid_invalid", "mesh_derived_operation_refused"})
    assert MeshSewTimeout("x", timeout_s=1.0, partial={}, lost=()).reason == "mesh_sew_timeout"
    raised.add("mesh_sew_timeout")

    from hephaestus.geom.mesh import MESH_OPERATION_REFUSALS

    assert raised == set(MESH_OPERATION_REFUSALS)


# ==========================================================================
# clause 30 — mesh_derived_operation_refused, on each of the three


@pytest.fixture
def mesh_solid(meshes: Fixtures) -> MeshDerivedSolid:
    """A real mesh-derived solid: the 10 mm cube, which passes the validity gate.

    It has to be one that PASSES, or this clause would be asserting that a
    refused conversion refuses — which is the previous clause, not this one.
    """
    vertices, faces, _canonical = canonical_arrays(meshes.cube_stl, path="cube.stl")
    solid, report = sew_to_solid(vertices, faces, source="cube.stl")
    assert report.is_valid is True
    gated = gate_sewn_solid(solid, report, source="cube.stl")
    assert isinstance(gated, MeshDerivedSolid)
    return gated


@pytest.mark.parametrize("operation", MESH_DERIVED_REFUSED_OPERATIONS)
def test_clause30_every_refused_operation_fires_by_name(
    mesh_solid: MeshDerivedSolid, operation: str
) -> None:
    """Each of offset, shell/thicken and fillet-class calls is refused by name."""
    with pytest.raises(MeshOperationError) as raised:
        getattr(mesh_solid, operation)(1.0)
    assert raised.value.reason == "mesh_derived_operation_refused"
    assert "MESH_INGEST.md §5.1" in str(raised.value)


def test_clause30_the_refusal_catches_build123d_s_own_free_functions(
    mesh_solid: MeshDerivedSolid,
) -> None:
    """The spelling a script actually writes.

    ``script_contract.md``:28-29 forbids wrapping or renaming build123d, and
    nothing here does: build123d's free ``offset()`` dispatches to
    ``solid.offset_3d(...)`` and its free ``fillet()`` to ``target.fillet(...)``,
    so refusing the METHODS refuses both spellings without touching a single
    build123d export.
    """
    from build123d import fillet, offset

    with pytest.raises(MeshOperationError) as offset_refusal:
        offset(mesh_solid, amount=2.0)
    assert offset_refusal.value.reason == "mesh_derived_operation_refused"

    with pytest.raises(MeshOperationError) as fillet_refusal:
        fillet(mesh_solid.edges(), radius=0.5)
    assert fillet_refusal.value.reason == "mesh_derived_operation_refused"


def test_clause30_trim_is_not_refused_because_it_was_measured_to_work(
    mesh_solid: MeshDerivedSolid,
) -> None:
    """The one row of the §5.1 table that works, left working.

    A blanket refusal would be easier to write and would be a lie: the boolean
    is measured to work on a mesh-derived solid (with an exploding face count
    the caller can see for itself). The result is an ORDINARY ``Solid``, not a
    mesh-derived one, which is right — cutting a scan out of authored stock
    produces geometry whose edges are no longer all facet creases.
    """
    from build123d import Box, Solid

    trimmed = mesh_solid - Box(4, 4, 4)
    assert trimmed.volume == pytest.approx(992.0, rel=1e-6)
    assert isinstance(trimmed, Solid)
    assert not isinstance(trimmed, MeshDerivedSolid)


def test_clause30_the_refusal_reaches_a_part_script_at_its_own_line(
    project: Project, meshes: Fixtures
) -> None:
    """End to end: a script that offsets its scan-derived solid gets the §8 error."""
    install_import(project.root, "limb.stl", meshes.cube_stl)
    error = build_error(
        project,
        "offset_the_scan",
        'scan = import_mesh("limb.stl", units="mm")\n'
        'solid = mesh_to_solid(scan, intent="measurement_target")\n'
        "part.geometry = offset(solid, amount=2.0)\n",
    )
    assert error["line"] == 3
    assert "mesh_derived_operation_refused" in error["message"]
    assert "§5.2" in error["message"]


def test_clause30_a_successful_conversion_marks_the_build_mesh_derived(
    project: Project, meshes: Fixtures
) -> None:
    """§4.3's closed two-member set, on the record, with the right member.

    The companion assertion is in the socket-path module: the §5.2 workflow,
    which imports the same scan and never converts it, stays ``"authored"``.
    """
    from _g12b import build_ok
    from hephaestus.core.project_store.publication import GEOMETRY_SOURCES, Publisher

    install_import(project.root, "limb.stl", meshes.cube_stl)
    build_ok(
        project,
        "sewn",
        'scan = import_mesh("limb.stl", units="mm")\n'
        'part.geometry = mesh_to_solid(scan, intent="measurement_target")\n'
        'part.description = "the scan, sewn"\n'
        'part.process = "additive"\n',
    )
    bundle = Publisher(project.layout, project.store).current_bundle("sewn")
    assert bundle is not None
    assert bundle["geometry_source"] == "mesh_derived"
    assert GEOMETRY_SOURCES == ("authored", "mesh_derived")


def test_clause30_intent_is_required_and_closed_at_the_script_surface(
    project: Project, meshes: Fixtures
) -> None:
    """No ``offset_operand``, and no defaulted intent to slip past the reader."""
    install_import(project.root, "limb.stl", meshes.cube_stl)
    error = build_error(
        project,
        "bad_intent",
        'scan = import_mesh("limb.stl", units="mm")\n'
        'part.geometry = mesh_to_solid(scan, intent="offset_operand")\n',
    )
    assert error["line"] == 2
    assert "offset_operand" in error["message"]

    missing = build_error(
        project,
        "no_intent",
        'scan = import_mesh("limb.stl", units="mm")\npart.geometry = mesh_to_solid(scan)\n',
    )
    assert missing["line"] == 2
    assert "intent is required" in missing["message"]


def test_clause30_a_point_cloud_is_refused_at_the_conversion_boundary(
    project: Project,
) -> None:
    """``point_cloud_not_a_shape`` (§2.3): there is nothing to sew or section."""
    install_import(project.root, "marks.xyz", b"0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 1 1\n")
    for term, line in (('mesh_to_solid(cloud, intent="measurement_target")', 2),):
        error = build_error(
            project,
            "cloud_solid",
            f'cloud = import_point_cloud("marks.xyz", units="mm")\npart.geometry = {term}\n',
        )
        assert error["line"] == line
        assert "point_cloud_not_a_shape" in error["message"]


# ==========================================================================
# clause 31 — the lint, and the defeating case that pins its reach


FLAGGED = """
scan = import_mesh("limb.stl", units="mm")
socket = mesh_to_solid(scan, intent="measurement_target")
part.geometry = offset(socket, amount=2.0)
"""

#: The defeating case. Nothing here is exotic — one extra assignment — and the
#: rule says nothing about it. That is the point: it is one hop of single
#: assignment, and a reader who believed otherwise would be trusting a warning
#: as a guarantee.
DEFEATED = """
scan = import_mesh("limb.stl", units="mm")
socket = mesh_to_solid(scan, intent="measurement_target")
indirect = socket
part.geometry = offset(indirect, amount=2.0)
"""

#: A second defeating shape: the name is REBOUND, so it no longer traces to the
#: conversion by single assignment and the rule drops it.
REBOUND = """
scan = import_mesh("limb.stl", units="mm")
socket = mesh_to_solid(scan, intent="measurement_target")
socket = Box(10, 10, 10)
part.geometry = offset(socket, amount=2.0)
"""

#: The THIRD, and the one the spec itself names: a boolean first. §4.3's
#: deviation 6 says the type-level refusal is defeated by ``Solid(scan.wrapped)``
#: "and so does a boolean first", and the third repair pass's verifier is why
#: this case is here — the two above are alias-and-rebind shapes nobody would
#: reach for on purpose, while a boolean against authored stock is the ordinary
#: next move in the workflow this stage is for. A clause that asserts the
#: defeat nobody would reach for, while the spec names one that is real, is
#: asserting the easy half.
#:
#: The defeat is deliberate and documented, not an oversight: cutting a scan out
#: of authored stock produces geometry whose edges are no longer all facet
#: creases, so the result is a plain ``Solid`` by design. What must never happen
#: is that a reader mistakes the type-level refusal for a wall.
BOOLEAN_LAUNDERED = """
scan = import_mesh("limb.stl", units="mm")
socket = mesh_to_solid(scan, intent="measurement_target")
stock = socket - Box(4, 4, 4)
part.geometry = offset(stock, amount=2.0)
"""


def _codes(source: str) -> list[str]:
    return [finding.code for finding in lint_script(source)]


def test_clause31_lint_flags_the_single_assignment_case() -> None:
    """``mesh_derived_offset``, warning-class, at the offending call."""
    findings = [f for f in lint_script(FLAGGED) if f.code == "mesh_derived_offset"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warning"
    assert finding.name == "socket"
    assert finding.line == 4
    assert "syntactic and defeatable" in finding.message
    assert "MESH_INGEST.md §4.2" in finding.message


@pytest.mark.parametrize(
    "operation", ["offset(socket, amount=2.0)", "socket.shell([], -1.0)", "thicken(socket, 2.0)"]
)
def test_clause31_lint_sees_both_spellings(operation: str) -> None:
    """The free function and the method reach the same kernel call, so the rule
    must see both or a reader could conclude one of them is sanctioned."""
    source = (
        'scan = import_mesh("limb.stl", units="mm")\n'
        'socket = mesh_to_solid(scan, intent="measurement_target")\n'
        f"part.geometry = {operation}\n"
    )
    assert "mesh_derived_offset" in _codes(source)


@pytest.mark.parametrize("source", [DEFEATED, REBOUND, BOOLEAN_LAUNDERED])
def test_clause31_the_documented_limitation_is_asserted_not_merely_stated(
    source: str,
) -> None:
    """The rule does NOT flag these, and the gate says so out loud.

    A lint that overclaims its reach is the same defect one level down from the
    one it is trying to catch, so the limitation is a clause rather than a
    sentence in a docstring. What actually protects the build in the first two
    is the ``BRepCheck_Analyzer`` gate and
    :class:`~hephaestus.geom.mesh_solid.MeshDerivedSolid`'s own refusals — the
    lint is a warning on the script a reader is looking at, never enforcement.

    The third is the case §4.3's deviation 6 names in so many words, and the
    test below proves it end to end rather than asserting only that lint is
    quiet about it.
    """
    assert "mesh_derived_offset" not in _codes(source)


def test_clause31_the_boolean_launder_is_a_real_defeat_measured_end_to_end(
    meshes: Fixtures,
) -> None:
    """The spec's own defeating case, reproduced rather than described.

    §4.3 deviation 6: ``Solid(scan.wrapped)`` defeats the type-level refusal "and
    so does a boolean first". Both halves are asserted here, because a limitation
    stated in prose and asserted nowhere is a limitation the next reader will
    discover from a wrong part:

    1. the mesh-derived solid itself REFUSES ``offset_3d`` by name — the wall is
       real where it exists;
    2. that same solid, after one boolean against authored stock, is a **plain**
       ``Solid`` (not a :class:`MeshDerivedSolid`) whose offset then runs with no
       refusal at all;
    3. and ``heph lint`` says nothing about the script that does it.

    Nothing here is a bug report: the plain ``Solid`` is deliberate (a cut
    through authored stock leaves edges that are not all facet creases). It is
    written down so the pair of defences can never be read as one guarantee.
    """
    from build123d import Box, Solid

    vertices, faces, _canonical = canonical_arrays(meshes.cube_stl, path="limb.stl")
    sewn, report = sew_to_solid(vertices, faces, source="limb.stl")
    solid = gate_sewn_solid(sewn, report, source="limb.stl")
    assert isinstance(solid, MeshDerivedSolid)

    # 1 — the refusal is real on the object the harness owns.
    with pytest.raises(MeshOperationError) as refused:
        solid.offset_3d(None, 2.0)  # pyright: ignore[reportArgumentType]
    assert refused.value.reason == "mesh_derived_operation_refused"

    # 2 — one boolean, and the operand's identity is gone.
    laundered = solid - Box(4.0, 4.0, 4.0)
    assert isinstance(laundered, Solid)
    assert not isinstance(laundered, MeshDerivedSolid)
    widened = laundered.offset_3d(None, 0.2)
    assert widened is not None
    assert widened.volume > laundered.volume

    # 3 — and the lint, which is the other half of the pair, does not see it.
    assert "mesh_derived_offset" not in _codes(BOOLEAN_LAUNDERED)


def test_clause31_a_script_with_no_conversion_is_never_flagged() -> None:
    """The §5.2 workflow offsets an AUTHORED solid, and lint must leave it alone."""
    source = (
        'scan = import_mesh("limb.stl", units="mm")\n'
        "lo = section_polylines(scan, ((0, 0, 1), (0, 0, 1)), spacing=2.0)\n"
        "hi = section_polylines(scan, ((0, 0, 9), (0, 0, 1)), spacing=2.0)\n"
        "core = loft_sections([lo[0], hi[0]])\n"
        "part.geometry = offset(core, amount=2.0)\n"
    )
    assert "mesh_derived_offset" not in _codes(source)


def test_clause31_the_lint_is_reachable_through_heph_lint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rule ships on the surface an operator actually runs, and is a WARNING.

    A rule that only exists as a library function is a rule nobody runs, and a
    rule that failed the lint would make the §5.2 workflow's own honest
    intermediate step an error. Both halves are asserted: the code appears, and
    the exit status stays 0.
    """
    import json

    from hephaestus.core.cli import main

    script = tmp_path / "socket.py"
    script.write_text(FLAGGED, encoding="utf-8")
    code = main(["lint", str(script), "--json"])
    findings = json.loads(capsys.readouterr().out)
    assert "mesh_derived_offset" in [finding["code"] for finding in findings]
    assert code == 0
