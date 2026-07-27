"""GLTF export: structural validity, mesh==solid count, bundle-bound raycast IDs.

On the assembly ``primary`` part: the exported GLB parses and passes structural
bounds checks with one mesh per solid; a raycast (mesh / mesh+primitive) resolves
the embedded selection ID to the same table entry only through the immutable
linked bundle; and wrong / expired bundle refs surface as ``stale_selection``.
The GLTF build needs no renderer, so these tests do not touch the rasterizer.
"""

# Untyped pygltflib / build123d surfaces (render executionEnvironment); strict otherwise.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.errors import ValidationError
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
from hephaestus.core.executor.tags import TagPlacement, TagRegistry, resolve_placements
from hephaestus.core.project_store.store import artifact_ref, blob_hash_of_ref
from hephaestus.core.render.bundle import RenderStore, SelectionBundle, StaleSelectionError
from hephaestus.core.render.gltf import (
    BUNDLE_REF_KEY,
    export_gltf,
    resolve_gltf_pick,
    validate_gltf,
)
from hephaestus.core.render.selection import (
    SelectionCatalog,
    build_selection_catalog,
    solid_labels,
)
from hephaestus.core.render.tessellate import Tessellation, tessellate
from hephaestus.geom.metrics import metrics

from opstore import OpStore

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"


def _build_primary() -> tuple[Any, TagRegistry]:
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
class GltfFixture:
    store: OpStore
    source_ref: str
    shape: object
    tess: Tessellation
    placements: dict[str, TagPlacement]
    labels: dict[int, str]
    catalog: SelectionCatalog
    bundle: SelectionBundle
    glb: bytes
    solid_count: int


def _fake_bundle(store: OpStore, source_ref: str, catalog: SelectionCatalog) -> SelectionBundle:
    """Publish a bundle with placeholder pass bytes (no renderer needed here)."""
    return RenderStore(store).publish_selection_bundle(
        view="iso",
        source_artifact_ref=source_ref,
        solid_png=b"SOLID",
        face_png=b"FACE",
        edge_png=b"EDGE",
        entries=catalog.entries,
        preview_png=b"PREVIEW",
    )


@pytest.fixture(scope="module")
def gltf_fixture(tmp_path_factory: pytest.TempPathFactory) -> GltfFixture:
    shape, registry = _build_primary()
    tess = tessellate(shape)
    placements = resolve_placements(registry, shape)
    labels = solid_labels(shape)
    catalog = build_selection_catalog(tess, placements=placements, labels=labels)

    store = OpStore.create(tmp_path_factory.mktemp("gltf-store") / "store")
    source_ref = artifact_ref("build", store.blobs.put(b"BUILD-primary"))
    bundle = _fake_bundle(store, source_ref, catalog)
    glb = export_gltf(
        shape,
        catalog,
        bundle_ref=bundle.bundle_ref,
        source_artifact_ref=source_ref,
        selection_table_ref=bundle.selection_table_ref,
        tess=tess,
        labels=labels,
    )
    return GltfFixture(
        store=store,
        source_ref=source_ref,
        shape=shape,
        tess=tess,
        placements=placements,
        labels=labels,
        catalog=catalog,
        bundle=bundle,
        glb=glb,
        solid_count=metrics(shape).solids,
    )


def test_gltf_validates_with_mesh_count_equal_solid_count(gltf_fixture: GltfFixture) -> None:
    validation = validate_gltf(gltf_fixture.glb, expected_solid_count=gltf_fixture.solid_count)
    assert validation.mesh_count == gltf_fixture.solid_count == len(gltf_fixture.tess.solids)
    assert validation.primitive_count > 0
    assert validation.buffer_length > 0
    assert validation.bundle_ref == gltf_fixture.bundle.bundle_ref
    assert validation.source_artifact_ref == gltf_fixture.source_ref


def test_gltf_starts_with_glb_magic(gltf_fixture: GltfFixture) -> None:
    assert gltf_fixture.glb[:4] == b"glTF"


def test_gltf_is_deterministic(gltf_fixture: GltfFixture) -> None:
    again = export_gltf(
        gltf_fixture.shape,
        gltf_fixture.catalog,
        bundle_ref=gltf_fixture.bundle.bundle_ref,
        source_artifact_ref=gltf_fixture.source_ref,
        selection_table_ref=gltf_fixture.bundle.selection_table_ref,
        tess=gltf_fixture.tess,
        labels=gltf_fixture.labels,
    )
    assert again == gltf_fixture.glb


def test_mesh_count_mismatch_rejected(gltf_fixture: GltfFixture) -> None:
    with pytest.raises(ValidationError):
        validate_gltf(gltf_fixture.glb, expected_solid_count=gltf_fixture.solid_count + 1)


def test_pick_solid_resolves_through_bundle(gltf_fixture: GltfFixture) -> None:
    # A whole-solid pick (mesh only) resolves the solid ID through the linked
    # bundle to the same table entry the catalog assigned.
    for solid_index in range(gltf_fixture.solid_count):
        entry = resolve_gltf_pick(gltf_fixture.store, gltf_fixture.glb, solid_index)
        assert entry.kind == "solid"
        assert entry.solid_index == solid_index
        expected_id = gltf_fixture.catalog.solid_ids[solid_index]
        assert entry == gltf_fixture.catalog.entries[expected_id]


def test_pick_face_resolves_tagged_topology(gltf_fixture: GltfFixture) -> None:
    # The tagged deck_top face is at (solid 1, face 5) in the executor layer.
    placement = gltf_fixture.placements["deck_top"]
    assert placement.solid_index is not None and placement.topo_index is not None
    # Its GLTF primitive index within the solid's mesh equals its face index
    # (primitives are emitted in face-topology order, skipping empty faces).
    entry = resolve_gltf_pick(
        gltf_fixture.store,
        gltf_fixture.glb,
        placement.solid_index,
        placement.topo_index,
    )
    assert entry.kind == "face"
    assert entry.solid_index == placement.solid_index
    assert entry.topology_index == placement.topo_index
    assert entry.tag == "deck_top"


def test_pick_matches_bundle_table_for_every_primitive(gltf_fixture: GltfFixture) -> None:
    # Exhaustively: every (mesh, primitive) pick resolves to a face entry whose
    # (solid, face) matches the catalog's face-ID assignment.
    from pygltflib import GLTF2

    gltf = GLTF2.load_from_bytes(gltf_fixture.glb)
    assert gltf is not None
    for mesh_index, mesh in enumerate(gltf.meshes):
        for primitive_index in range(len(mesh.primitives)):
            entry = resolve_gltf_pick(
                gltf_fixture.store, gltf_fixture.glb, mesh_index, primitive_index
            )
            assert entry.kind == "face"
            face_id = gltf_fixture.catalog.face_ids[(entry.solid_index, entry.topology_index)]
            assert entry == gltf_fixture.catalog.entries[face_id]
            assert entry.solid_index == mesh_index


def test_pick_wrong_build_is_stale(gltf_fixture: GltfFixture) -> None:
    other = artifact_ref("build", gltf_fixture.store.blobs.put(b"OTHER-BUILD"))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_gltf_pick(
            gltf_fixture.store,
            gltf_fixture.glb,
            0,
            expected_source_artifact_ref=other,
        )
    assert exc.value.stale.reason == "mismatched"


def test_pick_expired_bundle_is_stale(tmp_path_factory: pytest.TempPathFactory) -> None:
    # Build an independent store so ageing out the source does not disturb the
    # module fixture, then prove an expired linked bundle refuses the pick.
    shape, registry = _build_primary()
    tess = tessellate(shape)
    catalog = build_selection_catalog(
        tess, placements=resolve_placements(registry, shape), labels=solid_labels(shape)
    )
    store = OpStore.create(tmp_path_factory.mktemp("gltf-expire") / "store")
    source_ref = artifact_ref("build", store.blobs.put(b"BUILD-primary"))
    bundle = _fake_bundle(store, source_ref, catalog)
    glb = export_gltf(
        shape,
        catalog,
        bundle_ref=bundle.bundle_ref,
        source_artifact_ref=source_ref,
        selection_table_ref=bundle.selection_table_ref,
        tess=tess,
    )
    # The source build blob ages out; the linked bundle can no longer decode.
    store.blobs.remove(blob_hash_of_ref(source_ref))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_gltf_pick(store, glb, 0)
    assert exc.value.stale.reason == "expired"


def test_pick_out_of_range_mesh_is_rejected(gltf_fixture: GltfFixture) -> None:
    with pytest.raises(StaleSelectionError):
        resolve_gltf_pick(gltf_fixture.store, gltf_fixture.glb, gltf_fixture.solid_count + 10)


def test_asset_extras_bind_the_bundle(gltf_fixture: GltfFixture) -> None:
    from pygltflib import GLTF2

    gltf = GLTF2.load_from_bytes(gltf_fixture.glb)
    assert gltf is not None
    extras = gltf.asset.extras
    assert extras is not None
    assert extras[BUNDLE_REF_KEY] == gltf_fixture.bundle.bundle_ref


def test_malformed_bytes_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_gltf(b"not a glb at all")
