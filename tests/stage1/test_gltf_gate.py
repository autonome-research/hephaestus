# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Gate G1 — GLTF export: structural validity, solid count, bundle-bound picks.

Gate G1 clauses covered here:

* the exported GLB **validates structurally** with **mesh count == solid count
  of the build result**;
* embedded raycast selection IDs **bind to the immutable linked selection
  bundle** and a pick is authorized **only through that bundle** (a mismatched
  or aged-out bundle yields ``stale_selection``);
* whole-solid and tagged-face picks resolve to the same table entries the
  selection namespace assigned (one shared selection-id namespace).

The GLTF is built from the live, tagged compound (labels/tags survive only on
the live shape); the build-result solid count is taken from the genuine
published :class:`BuildResult`, and the selection bundle is a real rendered
bundle published through the render service.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from _render_gate import H, W, assembly_project
from hephaestus.core.executor.globals_exec import execute_globals
from hephaestus.core.executor.namespace import (
    CheckRegistry,
    ParamState,
    PartOutput,
    build_namespace,
)
from hephaestus.core.executor.splitter import (
    PART_FILENAME,
    compile_statement,
    parse_module,
    split_statements,
)
from hephaestus.core.executor.tags import TagRegistry, resolve_placements
from hephaestus.core.project_store.store import artifact_ref
from hephaestus.core.render.bundle import StaleSelectionError
from hephaestus.core.render.gltf import (
    BUNDLE_REF_KEY,
    SOURCE_REF_KEY,
    export_gltf,
    resolve_gltf_pick,
    validate_gltf,
)
from hephaestus.core.render.inspect import RenderProject
from hephaestus.core.render.selection import (
    build_selection_catalog,
    publish_selection_bundles,
    solid_labels,
)
from hephaestus.core.render.tessellate import tessellate
from hephaestus.geom.metrics import metrics

ASSEMBLY = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures" / "assembly"


def _build_primary_live() -> tuple[Any, TagRegistry]:
    """Execute ``assembly/primary`` in-process to recover the live tagged shape."""
    globals_source = (ASSEMBLY / "globals.py").read_text(encoding="utf-8")
    script = (ASSEMBLY / "parts" / "primary.py").read_text(encoding="utf-8")
    globals_result = execute_globals(globals_source)
    param_state = ParamState(scope="part", overrides={})
    part = PartOutput()
    registry = TagRegistry()
    namespace = build_namespace(
        param_state=param_state,
        hc=globals_result.hc_namespace(),
        part=part,
        tag_registry=registry,
        check_registry=CheckRegistry(),
    )
    module = parse_module(script, filename=PART_FILENAME)
    statements = split_statements(script, filename=PART_FILENAME)
    for statement, node in zip(statements, module.body, strict=True):
        registry.set_statement(statement.index, statement.lineno)
        exec(compile_statement(node, filename=PART_FILENAME), namespace)
        if not param_state.published and "PARAMS" in namespace:
            param_state.publish(namespace)
    param_state.finalize()
    geometry = part.geometry_value
    assert geometry is not None
    return geometry, registry


@dataclass(frozen=True)
class GltfGate:
    project: RenderProject
    source_ref: str
    build_result_solids: int
    glb: bytes
    bundle_ref: str
    solid_count: int
    tagged_solid: int
    tagged_face: int


@pytest.fixture(scope="module")
def gltf_gate(tmp_path_factory: pytest.TempPathFactory) -> GltfGate:
    project = assembly_project(tmp_path_factory.mktemp("gltf-assembly"))
    current = project.publisher().current_result("primary")
    assert current is not None and current.artifact_ref is not None
    source_ref = current.artifact_ref
    build_result_solids = sum(g.solids for g in current.geometries)

    shape, registry = _build_primary_live()
    tess = tessellate(shape)
    placements = resolve_placements(registry, shape)
    labels = solid_labels(shape)
    catalog = build_selection_catalog(tess, placements=placements, labels=labels)

    # Publish a REAL rendered selection bundle bound to the exact build ref.
    bundles = publish_selection_bundles(
        project.store,
        shape,
        source_artifact_ref=source_ref,
        views=["iso"],
        placements=placements,
        labels=labels,
        width=W,
        height=H,
    )
    bundle = bundles[0]

    glb = export_gltf(
        shape,
        catalog,
        bundle_ref=bundle.bundle_ref,
        source_artifact_ref=source_ref,
        selection_table_ref=bundle.selection_table_ref,
        tess=tess,
        labels=labels,
    )
    deck = placements["deck_top"]
    assert deck.solid_index is not None and deck.topo_index is not None
    return GltfGate(
        project=project,
        source_ref=source_ref,
        build_result_solids=build_result_solids,
        glb=glb,
        bundle_ref=bundle.bundle_ref,
        solid_count=metrics(shape).solids,
        tagged_solid=deck.solid_index,
        tagged_face=deck.topo_index,
    )


def test_gltf_is_a_glb(gltf_gate: GltfGate) -> None:
    assert gltf_gate.glb[:4] == b"glTF"


def test_mesh_count_equals_build_result_solid_count(gltf_gate: GltfGate) -> None:
    # The gate: gltf validates AND mesh count == the build result's solid count.
    validation = validate_gltf(gltf_gate.glb, expected_solid_count=gltf_gate.build_result_solids)
    assert validation.mesh_count == gltf_gate.build_result_solids
    assert validation.mesh_count == gltf_gate.solid_count
    assert validation.primitive_count > 0
    assert validation.buffer_length > 0


def test_asset_extras_bind_the_immutable_bundle(gltf_gate: GltfGate) -> None:
    validation = validate_gltf(gltf_gate.glb)
    assert validation.bundle_ref == gltf_gate.bundle_ref
    assert validation.source_artifact_ref == gltf_gate.source_ref
    from pygltflib import GLTF2

    gltf = GLTF2.load_from_bytes(gltf_gate.glb)
    extras = gltf.asset.extras
    assert extras[BUNDLE_REF_KEY] == gltf_gate.bundle_ref
    assert extras[SOURCE_REF_KEY] == gltf_gate.source_ref


def test_wrong_solid_count_rejected(gltf_gate: GltfGate) -> None:
    from hephaestus.core.errors import ValidationError

    with pytest.raises(ValidationError):
        validate_gltf(gltf_gate.glb, expected_solid_count=gltf_gate.build_result_solids + 1)


def test_every_solid_pick_resolves_through_bundle(gltf_gate: GltfGate) -> None:
    for solid_index in range(gltf_gate.solid_count):
        entry = resolve_gltf_pick(gltf_gate.project.store, gltf_gate.glb, solid_index)
        assert entry.kind == "solid"
        assert entry.solid_index == solid_index


def test_tagged_face_pick_resolves_topology_and_tag(gltf_gate: GltfGate) -> None:
    entry = resolve_gltf_pick(
        gltf_gate.project.store,
        gltf_gate.glb,
        gltf_gate.tagged_solid,
        gltf_gate.tagged_face,
    )
    assert entry.kind == "face"
    assert entry.solid_index == gltf_gate.tagged_solid
    assert entry.topology_index == gltf_gate.tagged_face
    assert entry.tag == "deck_top"


def test_pick_accepted_only_through_matching_bundle(gltf_gate: GltfGate) -> None:
    # A pick offered against a DIFFERENT expected build is refused as mismatched:
    # the GLTF alone never authorizes a selection.
    other_build = artifact_ref("build", gltf_gate.project.store.blobs.put(b"OTHER"))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_gltf_pick(
            gltf_gate.project.store,
            gltf_gate.glb,
            0,
            expected_source_artifact_ref=other_build,
        )
    assert exc.value.stale.reason == "mismatched"


def test_pick_out_of_range_mesh_is_rejected(gltf_gate: GltfGate) -> None:
    with pytest.raises(StaleSelectionError):
        resolve_gltf_pick(gltf_gate.project.store, gltf_gate.glb, gltf_gate.solid_count + 5)


def test_pick_with_expired_bundle_is_stale(tmp_path_factory: pytest.TempPathFactory) -> None:
    from hephaestus.core.project_store.store import blob_hash_of_ref
    from hephaestus.core.render.bundle import RenderStore

    from opstore import OpStore

    shape, registry = _build_primary_live()
    tess = tessellate(shape)
    catalog = build_selection_catalog(
        tess, placements=resolve_placements(registry, shape), labels=solid_labels(shape)
    )
    store = OpStore.create(tmp_path_factory.mktemp("gltf-expire") / "store")
    source_ref = artifact_ref("build", store.blobs.put(b"BUILD"))
    bundle = RenderStore(store).publish_selection_bundle(
        view="iso",
        source_artifact_ref=source_ref,
        solid_png=b"S",
        face_png=b"F",
        edge_png=b"E",
        entries=catalog.entries,
    )
    glb = export_gltf(
        shape,
        catalog,
        bundle_ref=bundle.bundle_ref,
        source_artifact_ref=source_ref,
        selection_table_ref=bundle.selection_table_ref,
        tess=tess,
    )
    store.blobs.remove(blob_hash_of_ref(source_ref))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_gltf_pick(store, glb, 0)
    assert exc.value.stale.reason == "expired"
