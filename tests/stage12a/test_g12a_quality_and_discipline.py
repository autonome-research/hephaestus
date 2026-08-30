# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""G12A clauses 10-16: measured quality, and the field names that do the work.

Clause 12 is the mechanism this whole stage rests on and it is one assertion
long: ``MeshAsset`` and ``PointCloudAsset`` expose **no** attribute named
``volume``, ``sealed``, ``genus``, ``chamfer_mm`` or ``iou``. ``KINEMATICS.md``
is the precedent — a sweep emits ``holds_at_samples`` and never ``holds``,
because "the verdict name says so" is stronger than a note asking the reader to
remember. A rename that reintroduced one of those five would let a mesh's weak
fact borrow a solid's strong name, and a reader downstream would have no way to
tell. So the gate fails on the rename, not on its consequences three stages
later.

Clause 11's ``None`` is the same discipline applied to a defect COUNT. A
``None`` self-intersection count means *not measured* and the method field says
which; it never means zero. The test asserts both halves, because "absent" and
"zero" are the two readings a careless implementation makes
indistinguishable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import pytest
from _g12a import (
    HOLE_PERIMETER_MM,
    MeshFixtures,
    build_error,
    build_ok,
    install_import,
    scan_facts,
    write_script,
)
from hephaestus.geom.mesh import (
    MeshAsset,
    PointCloudAsset,
    canonicalize_mesh,
    canonicalize_points,
    point_cloud_asset_from_staged,
)
from hephaestus.testing.tools_fixture import Project

#: The names a mesh record may never carry (§2.2). Each is a B-rep word whose
#: mesh counterpart is a *different, weaker* fact.
FORBIDDEN_FIELDS = ("volume", "sealed", "genus", "chamfer_mm", "iou")


# ==========================================================================
# clause 10: MeshQuality against hand-computable fixtures


def test_a_closed_cube_has_no_boundary_and_euler_two(meshes: MeshFixtures) -> None:
    """8 - 18 + 12 = 2. Arithmetic a reader can redo, not a captured golden."""
    quality = canonicalize_mesh("cube.ply", meshes.cube_ply_binary, "mm").quality
    assert quality.boundary_edge_count == 0
    assert quality.boundary_loop_count == 0
    assert quality.largest_hole_perimeter_mm == 0.0
    assert quality.nonmanifold_edge_count == 0
    assert quality.nonmanifold_vertex_count == 0
    assert quality.connected_component_count == 1
    assert quality.inverted_normal_triangles == 0
    assert scan_facts("cube.ply", meshes.cube_ply_binary, "mm").euler_characteristic == 2


def test_a_cube_missing_one_triangle_has_three_boundary_edges_in_one_loop(
    meshes: MeshFixtures,
) -> None:
    """The hole is one loop of exactly ``10 + 10 + 10√2`` mm — checkable by hand."""
    asset = scan_facts("holed.ply", meshes.holed_ply, "mm")
    assert asset.triangle_count == 11
    assert asset.quality.boundary_edge_count == 3
    assert asset.quality.boundary_loop_count == 1
    assert asset.quality.largest_hole_perimeter_mm == pytest.approx(HOLE_PERIMETER_MM, rel=1e-12)
    assert asset.watertight_at_weld_tol is False
    # 8 - 18 + 11: one fewer face and the same edges, because the deleted
    # triangle's three edges are all still used by its neighbours.
    assert asset.euler_characteristic == 1


def test_a_non_manifold_fin_is_reported_and_never_repaired(meshes: MeshFixtures) -> None:
    """One edge used by three triangles, and the two vertices on it.

    Nothing is cut, split or removed. A scan that arrives non-manifold is
    ADMITTED with the defect recorded (§3) — refusal is for what makes the file
    unreadable, not for what makes the scan imperfect.
    """
    quality = canonicalize_mesh("fin.ply", meshes.nonmanifold_fin_ply, "mm").quality
    assert quality.nonmanifold_edge_count == 1
    assert quality.nonmanifold_vertex_count == 2
    assert quality.boundary_edge_count == 6


def test_two_cubes_in_one_file_are_two_components(meshes: MeshFixtures) -> None:
    quality = canonicalize_mesh("two.ply", meshes.two_components_ply, "mm").quality
    assert quality.connected_component_count == 2
    assert quality.boundary_edge_count == 0


def test_one_reversed_triangle_is_counted_and_not_flipped(meshes: MeshFixtures) -> None:
    """The minority winding is reported; which majority is "right" is not a fact.

    Reorienting it would be a silent repair, and §3 forbids exactly that. The
    canonical ordering rotates each triangle onto its smallest index precisely
    so that winding survives the reorder untouched.
    """
    quality = canonicalize_mesh("rev.ply", meshes.reversed_winding_ply, "mm").quality
    assert quality.inverted_normal_triangles == 1
    assert quality.nonmanifold_edge_count == 0


def test_degenerate_triangles_are_dropped_with_an_exact_count(
    meshes: MeshFixtures,
) -> None:
    asset = scan_facts("degen.ply", meshes.degenerate_ply, "mm")
    assert asset.quality.degenerate_triangles_dropped == 1
    assert asset.triangle_count == 12


# ==========================================================================
# clause 11: self-intersection is a SAMPLED fact, and None is not zero


def test_a_known_crossing_pair_is_found_by_the_exact_method(
    meshes: MeshFixtures,
) -> None:
    quality = canonicalize_mesh("x.ply", meshes.crossing_ply, "mm").quality
    assert quality.self_intersection_method == "uniform_grid_exact_pairs"
    assert quality.self_intersecting_pairs == 1


def test_over_the_ceiling_the_count_is_none_and_does_not_read_as_zero(
    meshes: MeshFixtures, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``None`` means NOT MEASURED, and the method field is what says so.

    The two readings a careless record makes indistinguishable are "we looked
    and found none" and "we did not look". Asserting ``is None`` *and*
    ``!= 0`` pins the difference the record is required to carry: the absence of
    a found intersection is evidence, not proof.
    """
    monkeypatch.setitem(os.environ, "HEPHAESTUS_MESH_SELFX_PAIR_MAX", "0")
    quality = canonicalize_mesh("x.ply", meshes.crossing_ply, "mm").quality

    assert quality.self_intersecting_pairs is None
    assert quality.self_intersecting_pairs != 0
    assert quality.self_intersection_method == "not_evaluated_ceiling"


# ==========================================================================
# clause 12: field-name discipline, asserted over the record classes


@pytest.mark.parametrize("record", [MeshAsset, PointCloudAsset])
@pytest.mark.parametrize("forbidden", FORBIDDEN_FIELDS)
def test_no_mesh_record_carries_a_brep_field_name(record: type, forbidden: str) -> None:
    """A rename that reintroduces one of the five fails the gate, by name.

    ``volume`` is the polyhedron's and is systematically low; ``sealed`` is a
    B-rep predicate that measured True on a shape whose ``IsValid()`` was False;
    ``genus`` on a scan counts the *scanner's* bridged folds, not the limb's
    handles; ``chamfer_mm`` and ``iou`` are comparison fields a scan target
    cannot honestly fill. Each has a replacement whose NAME carries the caveat.
    """
    fields = {field.name for field in record.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    assert forbidden not in fields
    assert not hasattr(record, forbidden)


def test_the_replacement_fields_exist_and_carry_their_caveat_in_the_name() -> None:
    """The other half of clause 12: the weaker facts are present, named weakly."""
    fields = set(MeshAsset.__dataclass_fields__)
    assert {
        "tessellated_volume_mm3",
        "tessellated_area_mm2",
        "watertight_at_weld_tol",
        "euler_characteristic",
        "weld_tol_mm",
    } <= fields
    # And a point cloud borrows none of them: it has no volume, no area, no
    # watertightness and no topology, so the record carries none of the names.
    assert set(PointCloudAsset.__dataclass_fields__) == {
        "source_path",
        "units_declared",
        "canonical_hash",
        "point_count",
        "bbox_mm",
    }


# ==========================================================================
# clause 13: a volume from an open surface is not a small error


def test_tessellated_volume_is_none_when_not_watertight(meshes: MeshFixtures) -> None:
    """``None`` — not zero, not a number. The distinction is the whole field."""
    asset = scan_facts("holed.ply", meshes.holed_ply, "mm")
    assert asset.watertight_at_weld_tol is False
    assert asset.tessellated_volume_mm3 is None


def test_tessellated_volume_equals_the_hand_computed_polyhedron(
    meshes: MeshFixtures,
) -> None:
    """A 10 mm cube is 1000 mm³ exactly — the one shape with zero facet bias."""
    asset = scan_facts("cube.ply", meshes.cube_ply_binary, "mm")
    assert asset.watertight_at_weld_tol is True
    assert asset.tessellated_volume_mm3 == pytest.approx(1000.0, rel=1e-12)


# ==========================================================================
# clause 14: a point cloud never reaches a shape parameter


def test_a_point_cloud_at_a_shape_parameter_is_refused_by_name(
    project: Project, meshes: MeshFixtures
) -> None:
    """``point_cloud_not_a_shape``, at the boundary, never sampled to zeros."""
    install_import(project.root, "marks.xyz", meshes.points_xyz)
    error = build_error(
        project,
        "cloud_as_geometry",
        'cloud = import_point_cloud("marks.xyz", units="mm")\npart.geometry = cloud\n',
    )
    assert error["line"] == 2
    # The code in the DERIVED form, so the assertion binds ``reason=`` and not
    # prose a raise site could keep after the vocabulary moved: this site used
    # to hand-write the code into a bare ValidationError with no reason behind
    # it, and this substring was its only cover (third repair pass).
    assert "[point_cloud_not_a_shape]" in error["message"]


def test_the_point_cloud_refusal_carries_a_reason_a_caller_can_branch_on(
    meshes: MeshFixtures,
) -> None:
    """The §10 code exists as a value, not only as text in a message.

    A refusal whose code lives only in its prose is a refusal no caller can act
    on except by matching strings — and the message-substring assertion above
    cannot tell the difference. Both places a point cloud can reach a shape are
    exercised at the layer that decides, where the ``reason`` is still an object.
    """
    from hephaestus.core.executor.namespace import PartOutput
    from hephaestus.geom.mesh import MESH_TYPE_REFUSALS, MeshTypeError

    canonical = canonicalize_points("marks.xyz", meshes.points_xyz, "mm")
    cloud = point_cloud_asset_from_staged(canonical.blob, source_path="marks.xyz", units="mm")

    with pytest.raises(MeshTypeError) as at_geometry:
        PartOutput().geometry = cloud  # pyright: ignore[reportAttributeAccessIssue]
    assert at_geometry.value.reason == "point_cloud_not_a_shape"
    assert at_geometry.value.reason in MESH_TYPE_REFUSALS


def test_a_point_cloud_never_reaches_surface_distance(meshes: MeshFixtures) -> None:
    """The regression half: the zeros-with-zero-counts result stays unreachable.

    ``geom.compare.surface_distance`` on a shape with no faces returns zeros
    with zero sample counts rather than refusing — honest only because the
    counts are in the record, and not honest enough for something that will be
    handed a point cloud by mistake. A ``PointCloudAsset`` has no ``wrapped``,
    so it cannot even be passed; the assertion pins that rather than trusting
    that nobody will try.
    """
    canonical = canonicalize_points("marks.xyz", meshes.points_xyz, "mm")
    cloud = point_cloud_asset_from_staged(canonical.blob, source_path="marks.xyz", units="mm")

    assert not hasattr(cloud, "wrapped")
    assert not hasattr(cloud, "faces")
    from hephaestus.geom.compare import surface_distance

    with pytest.raises((AttributeError, TypeError)):
        surface_distance(cloud, cloud)  # pyright: ignore[reportArgumentType]


def test_a_mesh_asset_at_a_shape_parameter_names_its_12b_route(
    project: Project, meshes: MeshFixtures
) -> None:
    """A mesh is a measurement target, not geometry — and the refusal says so."""
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    error = build_error(
        project,
        "mesh_as_geometry",
        'scan = import_mesh("limb.ply", units="mm")\npart.geometry = scan\n',
    )
    assert error["line"] == 2
    assert "mesh_to_solid" in error["message"]


# ==========================================================================
# clause 15: tag() on mesh topology is refused by name


def test_tag_on_a_mesh_asset_refuses_mesh_topology_not_taggable(
    project: Project, meshes: MeshFixtures
) -> None:
    """No selector grammar addresses a triangle, and the refusal explains why.

    Triangle indices are an artifact of the file's order, which
    canonicalization deliberately replaces; the §5.3 drift fingerprint compares
    descriptors of tagged faces and every triangle is a discretization artifact.
    There is nothing stable to name.
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    error = build_error(
        project,
        "tagged_mesh",
        'scan = import_mesh("limb.ply", units="mm")\n'
        'tag(scan, "limb_surface")\n'
        "part.geometry = Box(1, 1, 1)\n",
    )
    assert error["line"] == 2
    assert "[mesh_topology_not_taggable]" in error["message"]


def test_the_tag_refusal_carries_a_reason_a_caller_can_branch_on(
    project: Project, meshes: MeshFixtures
) -> None:
    """As above, at the layer that decides: the code is a value, not only prose."""
    from hephaestus.core.executor.tags import TagRegistry
    from hephaestus.geom.mesh import (
        MESH_TYPE_REFUSALS,
        MeshTypeError,
        facts_to_json,
        mesh_asset_from_staged,
    )

    canonical = canonicalize_mesh("limb.ply", meshes.cube_ply_binary, "mm")
    asset = mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path="limb.ply", units="mm"
    )
    with pytest.raises(MeshTypeError) as caught:
        TagRegistry().tag(asset, "limb_surface")
    assert caught.value.reason == "mesh_topology_not_taggable"
    assert caught.value.reason in MESH_TYPE_REFUSALS


def test_the_two_mesh_terms_are_not_selector_vocabulary() -> None:
    """A selector addresses topology; mesh topology carries no identity (§2.4).

    Both terms join ``import_step`` among the harness handles a store
    generator's ``interface`` region may not read, so ``SELECTOR_NAMES`` is
    unchanged by this stage.
    """
    from hephaestus.core.executor.namespace import SELECTOR_NAMES

    assert "import_mesh" not in SELECTOR_NAMES
    assert "import_point_cloud" not in SELECTOR_NAMES
    assert "import_step" not in SELECTOR_NAMES


# ==========================================================================
# clause 16: mixed builds


MIXED_SRC = """base = import_step("plate.step")
scan = import_mesh("limb.ply", units="mm")
boss = Cylinder(4, 6).moved(Location((0, 0, 4)))
part.geometry = base + boss
part.description = "a vendor plate, a native boss, and a scan measured against them"
print(scan.triangle_count, scan.watertight_at_weld_tol)
"""


def test_a_script_may_import_a_mesh_and_a_step_and_author_native_geometry(
    project: Project, meshes: MeshFixtures, tmp_path: Path
) -> None:
    """Both kinds ride the same freeze, the same input hashes, the same record.

    That is the design premise: mesh ingest lands INSIDE the existing contract
    rather than against it. ``INGEST.md`` §1's shape — take this file, apply
    these operations, the script remains the source of truth — needed no
    modification to hold for a scan.
    """
    from build123d import Box
    from hephaestus.geom.step_io import write_step

    step_path = project.root / "imports" / "plate.step"
    step_path.parent.mkdir(parents=True, exist_ok=True)
    write_step(Box(40, 20, 5), step_path)
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    write_script(project, "mixed", MIXED_SRC)

    build_ok(project, "mixed")

    current = project.cad.current_build("mixed")
    assert current is not None
    assert set(current.input_hashes.imports) == {"plate.step", "limb.ply"}
    assert current.metrics is not None
    assert current.metrics.volume_mm3 > 0.0

    # …MEASURES **and EXPORTS**. The export is not decoration: it is the step
    # that reads the published geometry back out of the store and writes a file
    # an operator can hand to a machinist, and it carries the build's own input
    # hashes with it — so a mixed build that measured but could not be exported
    # would have opened the door and left the room locked.
    exported = cast(
        "dict[str, Any]",
        project.call("export_part", {"name": "mixed", "format": "step", "target": "mixed.step"}),
    )
    assert exported["paths"]
    assert exported["source_input_hashes"]["imports"] == dict(current.input_hashes.imports)
    written = project.root / cast("list[str]", exported["paths"])[0]
    assert written.exists() and written.stat().st_size > 0

    # …and BOTH kinds in ``imports_used``, which is the worker's own record of
    # what the *script* built with. It is asserted at the layer that produces it
    # because it does not ride the published bundle: the bundle carries the two
    # hashes (identity), and this is a statement about the script's behaviour.
    # The same frozen inputs the tool build used are re-run here rather than a
    # second authoring, so the two halves are one build's facts.
    from hephaestus.core.executor.runner import BuildRequest, run_build
    from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
    from hephaestus.core.project_store.publication import Publisher

    frozen = Publisher(project.layout, project.store).freeze_inputs("mixed")
    built = run_build(
        BuildRequest(
            part="mixed",
            script=frozen.script,
            globals_source=frozen.globals_source,
            imports=dict(frozen.imports),
            import_errors=dict(frozen.import_errors),
        ),
        backend=UnsafeLocalBackend(),
        out_dir=tmp_path / "mixed-out",
    )
    assert built.result.status == "ok", built.result.error
    assert set(cast("list[str]", built.worker_result["imports_used"])) == {
        "plate.step",
        "limb.ply",
    }
