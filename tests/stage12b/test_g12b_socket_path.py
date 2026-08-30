# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12B clauses 28-29: the §5.2 socket path, run for real, and the closed surface.

> **Do not offset the scan. Author geometry against the scan, and offset that.**

Clause 28 writes that sentence as a part script and runs it through the
executor, in the sandbox, as a model would. That is not a stylistic choice: it
is the only way to prove the terms are REACHABLE, because ``__import__`` is
absent and the §2 namespace is closed, so an injected name that was never
injected shows up as a ``NameError`` at its own line rather than as a passing
unit test.

Clause 29 closes the surface from the other side: the injected set is asserted
to be EXACTLY the documented one, so an undocumented addition fails the gate
just as a missing one does, and four OCP/vendor names are asserted unreachable
from a script.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from _g12b import (
    CYLINDER_HEIGHT_MM,
    CYLINDER_RADIUS_MM,
    Fixtures,
    build_error,
    build_ok,
    install_import,
    write_script,
)
from hephaestus.core.project_store.publication import Publisher
from hephaestus.testing.tools_fixture import Project

# The §5.2 chain, verbatim, as a part script. Every name in it is either
# build123d or one of the five injected terms — the distinction §5.2 says is
# not cosmetic, made checkable by running it.
SOCKET_SCRIPT = """
part.description = "socket sleeve authored against a limb scan"
part.process = "additive"

scan = import_mesh("limb.stl", units="mm")

lower = section_polylines(scan, Plane(origin=(0, 0, -10), z_dir=(0, 0, 1)), spacing=2.0)
upper = section_polylines(scan, Plane(origin=(0, 0, 10), z_dir=(0, 0, 1)), spacing=2.0)

core = loft_sections([lower[0], upper[0]])
grown = offset(core, amount=2.0)
sleeve = grown - core
eased = fillet(core.edges(), radius=2.0)
lid = thicken(core.faces().sort_by(Axis.Z)[-1], amount=1.5)

part.geometry = sleeve
"""


def test_clause28_the_section_loft_offset_path_runs_end_to_end_through_the_executor(
    project: Project, meshes: Fixtures
) -> None:
    """``import_mesh`` -> ``section_polylines`` -> ``loft_sections`` -> build123d
    ``offset`` / ``thicken`` / ``fillet``, all succeeding, built and measured.

    The volumes are checkable against the fixture rather than captured from the
    run: the scan is a tessellated R15 x 40 cylinder, the two planes are 20 mm
    apart, so the lofted core is π·15²·20 = 14137 mm³ up to the inscribed-facet
    deficit, and offsetting it by 2 mm and subtracting gives the sleeve.

    The clause it is really guarding is the last assertion: this build's
    ``geometry_source`` is **authored**. The scan was measurement data, not
    geometry, and §5.2 exists precisely so that stays true — a path that quietly
    reported ``mesh_derived`` here would have made the field meaningless.
    """
    import math

    install_import(project.root, "limb.stl", meshes.cylinder_stl)
    build_ok(project, "socket", SOCKET_SCRIPT)

    # The expected number is DERIVED, not captured: the sleeve is the 2 mm
    # offset of a 20 mm tall R15 core minus the core, so it is
    # pi*17^2*24 - pi*15^2*20 = 7653 mm3. The tolerance covers the inscribed-facet
    # deficit and nothing else — 5%, where the §4.2 failure mode this stage
    # exists to catch was five ORDERS OF MAGNITUDE.
    section_span_mm = 20.0
    wall_mm = 2.0
    exact_core = math.pi * CYLINDER_RADIUS_MM**2 * section_span_mm
    exact_grown = math.pi * (CYLINDER_RADIUS_MM + wall_mm) ** 2 * (section_span_mm + 2 * wall_mm)
    current = project.cad.current_build("socket")
    assert current is not None and current.metrics is not None
    assert current.metrics.volume_mm3 == pytest.approx(exact_grown - exact_core, rel=0.05)
    # …and it is inscribed, so it is under rather than merely near.
    assert current.metrics.volume_mm3 < exact_grown - exact_core
    assert current.metrics.bbox_mm[2] == pytest.approx(section_span_mm + 2 * wall_mm, abs=1e-6)

    bundle = Publisher(project.layout, project.store).current_bundle("socket")
    assert bundle is not None
    # The scan's canonical geometry hash rode the build record (§1.4, 12A) …
    assert list(cast("dict[str, Any]", bundle["mesh_canonical_hashes"])) == ["limb.stl\x00mm"]
    # … and the part is AUTHORED, because nothing sewed the scan into geometry.
    assert bundle["geometry_source"] == "authored"


def test_clause28_the_scan_is_measured_at_the_height_the_socket_is_built_at(
    project: Project, meshes: Fixtures
) -> None:
    """A second, sharper reading of the same path: the authored solid follows the
    scan it was sectioned from, which is the entire claim of §5.2.

    Nothing in the harness enforces this — it is a property of the arithmetic —
    so it is asserted rather than assumed, and it is what makes ``compare_to_scan``
    (12C) a measurement of a gap rather than of a mistake.
    """
    install_import(project.root, "limb.stl", meshes.cylinder_stl)
    write_script(
        project,
        "core_only",
        'scan = import_mesh("limb.stl", units="mm")\n'
        "lo = section_polylines(scan, ((0, 0, -10), (0, 0, 1)), spacing=2.0)\n"
        "hi = section_polylines(scan, ((0, 0, 10), (0, 0, 1)), spacing=2.0)\n"
        "part.geometry = loft_sections([lo[0], hi[0]])\n"
        'part.description = "the lofted core alone"\n'
        'part.process = "additive"\n',
    )
    build_ok(project, "core_only")
    current = project.cad.current_build("core_only")
    assert current is not None and current.metrics is not None
    bbox = current.metrics.bbox_mm
    # The loft spans the two planes and nothing else …
    assert bbox[2] == pytest.approx(20.0, abs=1e-6)
    # … and its cross-section is the scan's, inscribed inside the true radius
    # because the facets are chords.
    assert bbox[0] == pytest.approx(2 * CYLINDER_RADIUS_MM, rel=0.02)
    assert bbox[0] <= 2 * CYLINDER_RADIUS_MM
    assert CYLINDER_HEIGHT_MM > 20.0  # the fixture is taller than the section span


def test_clause28_a_dense_section_that_lofts_to_an_uncapped_shell_is_refused(
    project: Project, meshes: Fixtures
) -> None:
    """The measured hazard inside the *safe* workflow, refused by name.

    At the mesh's own crossing density (78 points, 81 B-spline poles) OCCT's
    ThruSections returns a ONE-FACE lateral shell that build123d still hands
    back as a ``Solid`` and whose ``.volume`` reads 9423 mm³ where the answer is
    14137. That is the §4.2 failure mode arriving through §5.2, and the gate
    §4.3 mandates for the sew is applied here for the same reason. The message
    names the fix, because the fix is in the caller's hands.
    """
    install_import(project.root, "limb.stl", meshes.cylinder_stl)
    error = build_error(
        project,
        "dense_loft",
        'scan = import_mesh("limb.stl", units="mm")\n'
        "lo = section_polylines(scan, ((0, 0, -10), (0, 0, 1)))\n"
        "hi = section_polylines(scan, ((0, 0, 10), (0, 0, 1)))\n"
        "part.geometry = loft_sections([lo[0], hi[0]])\n",
    )
    assert error["line"] == 4
    assert "mesh_solid_invalid" in error["message"]
    assert "spacing" in error["message"]


def test_clause28_an_open_contour_is_never_lofted_through(
    project: Project, meshes: Fixtures
) -> None:
    """A hole in the scan does not become socket wall by passing through a fitter."""
    install_import(project.root, "limb.stl", meshes.side_holed_stl)
    error = build_error(
        project,
        "holed_loft",
        'scan = import_mesh("limb.stl", units="mm")\n'
        "lo = section_polylines(scan, ((0, 0, 3), (0, 0, 1)))\n"
        "hi = section_polylines(scan, ((0, 0, 7), (0, 0, 1)))\n"
        "part.geometry = loft_sections([lo[0], hi[0]])\n",
    )
    assert error["line"] == 4
    assert "open_section_contour" in error["message"]


# ==========================================================================
# clause 29 — the injected surface is closed and EXACTLY the documented set


#: The §2 list of ``script_contract.md``, as this stage leaves it. Transcribed
#: here on purpose: the gate must compare the namespace against the DOCUMENT,
#: not against a constant the namespace also builds itself from, or it would be
#: asserting that a thing equals itself.
DOCUMENTED_INJECTED = frozenset(
    {
        "Param",
        "p",
        "math",
        "hc",
        "part",
        "tag",
        "check",
        "approx",
        "import_step",
        "import_mesh",
        "import_point_cloud",
        "mesh_to_solid",
        "section_polylines",
        "loft_sections",
    }
)


def test_clause29_the_injected_namespace_is_exactly_the_documented_set() -> None:
    """Set EQUALITY, so an undocumented addition fails just as a missing one does.

    ``import_step`` is the subtle one: build123d exports a name of its own by
    that spelling, and the harness's term shadows it. That is asserted
    separately, because "the name is present" and "the name is the harness's"
    are different facts and only the second one is the contract.
    """
    import build123d
    from hephaestus.core.executor.namespace import _DUNDERS as DUNDERS
    from hephaestus.core.executor.namespace import (
        MESH_INJECTED_NAMES,
        CheckRegistry,
        HcNamespace,
        ImportRegistry,
        ParamState,
        PartOutput,
        build_namespace,
        injected_names,
    )
    from hephaestus.core.executor.tags import TagRegistry

    imports = ImportRegistry({})
    namespace = build_namespace(
        param_state=ParamState(scope="part", overrides={}),
        hc=HcNamespace({}),
        part=PartOutput(),
        tag_registry=TagRegistry(),
        check_registry=CheckRegistry(),
        imports=imports,
    )
    assert injected_names(namespace) == (
        frozenset(build123d.__all__) | DOCUMENTED_INJECTED | DUNDERS
    )
    # The five this stage's manifest names, and no sixth.
    assert set(MESH_INJECTED_NAMES) == {
        "import_mesh",
        "import_point_cloud",
        "mesh_to_solid",
        "section_polylines",
        "loft_sections",
    }
    assert set(MESH_INJECTED_NAMES) <= DOCUMENTED_INJECTED
    # Each of the three new ones is the registry's own bound method, not a
    # build123d name that happens to collide.
    assert namespace["mesh_to_solid"] == imports.mesh_to_solid
    assert namespace["section_polylines"] == imports.section_polylines
    assert namespace["loft_sections"] == imports.loft_sections
    assert namespace["import_step"] == imports.import_step
    assert namespace["import_step"] is not build123d.import_step


def test_clause29_the_selector_whitelist_is_unchanged_by_the_three_new_terms() -> None:
    """``PARTS_STORE.md`` §2.1's derived set does not move.

    All three new names are harness HANDLES, not geometry vocabulary — each of
    them MAKES geometry, and a selector addresses a region of geometry already
    built. Adding them to the namespace without adding them to the handle list
    would silently widen what an interface selector may name.
    """
    from hephaestus.core.executor import namespace as ns

    selector_names = cast("frozenset[str]", ns.SELECTOR_NAMES)
    for name in ("mesh_to_solid", "section_polylines", "loft_sections"):
        assert name not in selector_names
    assert "Box" in selector_names  # …and real geometry vocabulary still is


@pytest.mark.parametrize(
    ("name", "call"),
    [
        ("GeomAPI_PointsToBSpline", "GeomAPI_PointsToBSpline(None)"),
        ("BRepBuilderAPI_Sewing", "BRepBuilderAPI_Sewing(1e-6)"),
        ("OCP", "OCP.gp.gp_Pnt(0, 0, 0)"),
        ("trimesh", "trimesh.Trimesh()"),
    ],
)
def test_clause29_no_ocp_or_vendor_name_is_reachable_from_a_part_script(
    project: Project, name: str, call: str
) -> None:
    """The closure of ``script_contract.md``:44-45 is PROVEN at this stage rather
    than assumed while three new terms were added underneath it."""
    error = build_error(
        project,
        "reach_" + name.lower().replace("_", ""),
        f"part.geometry = Box(1, 1, 1)\nsneaky = {call}\n",
    )
    assert error["line"] == 2
    assert name.split(".")[0] in error["message"]


@pytest.mark.parametrize("denied", ["open", "__import__"])
def test_clause29_open_and_dunder_import_remain_absent(project: Project, denied: str) -> None:
    """The two the namespace has always denied are still denied."""
    error = build_error(
        project,
        "denied_" + denied.strip("_"),
        f"part.geometry = Box(1, 1, 1)\nsneaky = {denied}('x')\n",
    )
    assert error["line"] == 2
    assert denied in error["message"]
