"""Selection-mode passes + bundle resolution on the assembly fixture (Gate G1).

Renders the public assembly ``primary`` part through the software rasterizer and
asserts the Stage 1 selection contract: three palette-exact non-antialiased
solid/face/edge passes whose decoded colours are all table IDs of the right
kind, a global table resolving every selectable ID to kind/solid/topology index
and the exact build ref, untagged faces present in the face pass, a non-empty
edge overlay, and per-view bundle + pass refs that still round-trip through
foundation resolution after a newer build is published.
"""

# Mirror of the kernel/render executionEnvironment relaxations for untyped
# build123d / OCP / pyrender / PIL surfaces; everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
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
from hephaestus.core.kernel.metrics import metrics
from hephaestus.core.project_store.store import artifact_ref, blob_hash_of_ref
from hephaestus.core.render.bundle import (
    RenderStore,
    SelectionBundle,
    StaleSelectionError,
    resolve_selection,
)
from hephaestus.core.render.cameras import camera_framing, parse_view
from hephaestus.core.render.offscreen import OffscreenSession, RenderUnavailableError
from hephaestus.core.render.palette import SelectionEntry, rgb_to_id
from hephaestus.core.render.selection import (
    SelectionCatalog,
    SelectionPassArrays,
    build_selection_catalog,
    encode_png,
    render_selection_view,
    solid_labels,
)
from hephaestus.core.render.tessellate import Tessellation, tessellate
from numpy.typing import NDArray

from opstore import OpStore

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"

_VIEWS = ("iso", "+X")
_WIDTH = 240
_HEIGHT = 180


def _build_primary() -> tuple[Any, TagRegistry]:
    """Execute the assembly ``primary`` part in-process -> (shape, tag registry)."""
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


def _decode_ids(image: NDArray[np.uint8]) -> set[int]:
    """Every non-background selection ID painted in a flat pass."""
    pixels = image.reshape(-1, 3)
    ids: set[int] = set()
    for row in np.unique(pixels, axis=0):
        rgb = (int(row[0]), int(row[1]), int(row[2]))
        if rgb == (0, 0, 0):
            continue
        ids.add(rgb_to_id(rgb))
    return ids


@dataclass(frozen=True)
class RenderedFixture:
    store: OpStore
    source_ref: str
    shape: object
    tess: Tessellation
    placements: dict[str, TagPlacement]
    labels: dict[int, str]
    catalog: SelectionCatalog
    arrays: dict[str, SelectionPassArrays]
    bundles: dict[str, SelectionBundle]
    solid_count: int


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> RenderedFixture:
    """Build + render the assembly primary once and publish its per-view bundles."""
    shape, registry = _build_primary()
    tess = tessellate(shape)
    placements = resolve_placements(registry, shape)
    labels = solid_labels(shape)
    catalog = build_selection_catalog(tess, placements=placements, labels=labels)

    store = OpStore.create(tmp_path_factory.mktemp("sel-store") / "store")
    source_ref = artifact_ref("build", store.blobs.put(b"BUILD-primary"))
    render_store = RenderStore(store)

    arrays: dict[str, SelectionPassArrays] = {}
    bundles: dict[str, SelectionBundle] = {}
    try:
        with OffscreenSession(_WIDTH, _HEIGHT) as session:
            bounds = tess.bounds()
            for view in _VIEWS:
                framing = camera_framing(*bounds, parse_view(view), width=_WIDTH, height=_HEIGHT)
                view_arrays = render_selection_view(session, tess, catalog, framing)
                arrays[view] = view_arrays
                preview = view_arrays.preview
                bundles[view] = render_store.publish_selection_bundle(
                    view=view,
                    source_artifact_ref=source_ref,
                    solid_png=encode_png(view_arrays.solid),
                    face_png=encode_png(view_arrays.face),
                    edge_png=encode_png(view_arrays.edge),
                    entries=catalog.entries,
                    preview_png=encode_png(preview) if preview is not None else None,
                )
    except RenderUnavailableError as exc:  # pragma: no cover - platform-tier guard
        pytest.skip(f"no software rasterizer on this host: {exc}")

    return RenderedFixture(
        store=store,
        source_ref=source_ref,
        shape=shape,
        tess=tess,
        placements=placements,
        labels=labels,
        catalog=catalog,
        arrays=arrays,
        bundles=bundles,
        solid_count=metrics(shape).solids,
    )


def test_catalog_covers_every_occurrence(rendered: RenderedFixture) -> None:
    catalog = rendered.catalog
    tess = rendered.tess
    # One ID per solid, per (solid, face), per (solid, edge) — no collisions.
    expected = (
        len(tess.solids)
        + sum(len(s.faces) for s in tess.solids)
        + sum(len(s.edges) for s in tess.solids)
    )
    assert len(catalog.entries) == expected
    assert len(set(catalog.entries)) == expected
    # Every entry resolves to a concrete kind + topology index within its solid.
    for selection_id, entry in catalog.entries.items():
        assert selection_id >= 1
        assert entry.kind in ("solid", "face", "edge")
        assert 0 <= entry.solid_index < len(tess.solids)
        solid = tess.solids[entry.solid_index]
        if entry.kind == "solid":
            assert entry.topology_index == entry.solid_index
        elif entry.kind == "face":
            assert 0 <= entry.topology_index < len(solid.faces)
        else:
            assert 0 <= entry.topology_index < len(solid.edges)


def test_tagged_faces_carry_tag_and_label(rendered: RenderedFixture) -> None:
    by_tag = {e.tag: e for e in rendered.catalog.entries.values() if e.tag is not None}
    assert set(by_tag) == {"deck_top", "base_bottom"}
    # Tag placement (solid, topo) matches the executor tag layer exactly.
    for name, entry in by_tag.items():
        placement = rendered.placements[name]
        assert entry.kind == placement.kind == "face"
        assert entry.solid_index == placement.solid_index
        assert entry.topology_index == placement.topo_index
        assert entry.label is not None  # owning solid is a labeled deck


def test_labeled_solids_have_labels(rendered: RenderedFixture) -> None:
    solids = {
        e.solid_index: e.label for e in rendered.catalog.entries.values() if e.kind == "solid"
    }
    # Every solid of the assembly carries its geometry-tree label.
    assert solids == {
        0: "bottom_deck",
        1: "top_deck",
        2: "post",
        3: "post",
        4: "post",
        5: "post",
    }


@pytest.mark.parametrize("view", _VIEWS)
def test_passes_are_palette_exact_and_kind_pure(view: str, rendered: RenderedFixture) -> None:
    catalog = rendered.catalog
    arrays = rendered.arrays[view]

    solid_ids = _decode_ids(arrays.solid)
    face_ids = _decode_ids(arrays.face)
    edge_ids = _decode_ids(arrays.edge)

    # Every decoded colour is a real table ID (palette-exact, non-antialiased).
    assert solid_ids <= set(catalog.entries)
    assert face_ids <= set(catalog.entries)
    assert edge_ids <= set(catalog.entries)

    # Pixels never mix kinds within a pass.
    assert all(catalog.entries[i].kind == "solid" for i in solid_ids)
    assert all(catalog.entries[i].kind == "face" for i in face_ids)
    assert all(catalog.entries[i].kind == "edge" for i in edge_ids)

    # Something visible in every layer.
    assert solid_ids and face_ids and edge_ids


@pytest.mark.parametrize("view", _VIEWS)
def test_untagged_faces_present_in_face_pass(view: str, rendered: RenderedFixture) -> None:
    catalog = rendered.catalog
    face_ids = _decode_ids(rendered.arrays[view].face)
    untagged = [i for i in face_ids if catalog.entries[i].tag is None]
    # The great majority of faces are untagged; the face pass must include them
    # (selection is not limited to tagged topology).
    assert untagged


@pytest.mark.parametrize("view", _VIEWS)
def test_edge_overlay_nonempty(view: str, rendered: RenderedFixture) -> None:
    edge_image = rendered.arrays[view].edge
    assert int(edge_image.any(axis=2).sum()) > 0


@pytest.mark.parametrize("view", _VIEWS)
def test_solid_pass_colours_faces_by_solid(view: str, rendered: RenderedFixture) -> None:
    # The solid pass paints a solid's faces with the solid's ID, so decoded IDs
    # are exactly a subset of the assigned solid IDs (never face/edge IDs).
    solid_ids = _decode_ids(rendered.arrays[view].solid)
    assert solid_ids <= set(rendered.catalog.solid_ids.values())


def test_preview_is_not_palette_decodable(rendered: RenderedFixture) -> None:
    # The composite preview is a lit RGBA render; resolving its ref is refused,
    # and it is deliberately excluded from the decodable pass set.
    bundle = rendered.bundles["iso"]
    assert bundle.preview_ref is not None
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(rendered.store, bundle.preview_ref)
    assert exc.value.stale.reason == "wrong_mode"


@pytest.mark.parametrize("view", _VIEWS)
def test_bundle_resolves_every_id_to_build(view: str, rendered: RenderedFixture) -> None:
    bundle = rendered.bundles[view]
    resolution = resolve_selection(rendered.store, bundle.bundle_ref)
    assert resolution.view == view
    assert resolution.source_artifact_ref == rendered.source_ref
    # The published table is exactly the global catalog: every selectable ID
    # resolves to kind/solid/topology index bound to the exact build ref.
    assert resolution.entries == rendered.catalog.entries
    # Legend colours are the palette colours of exactly those IDs.
    legend = resolution.legend()
    assert len(legend) == len(rendered.catalog.entries)


def _publish_newer_build(store: OpStore, entries: dict[int, SelectionEntry]) -> SelectionBundle:
    """A distinct later build's bundle (different source + distinct pass bytes)."""
    newer_source = artifact_ref("build", store.blobs.put(b"BUILD-primary-v2"))
    return RenderStore(store).publish_selection_bundle(
        view="iso",
        source_artifact_ref=newer_source,
        solid_png=b"SOLID-v2",
        face_png=b"FACE-v2",
        edge_png=b"EDGE-v2",
        entries=entries,
        preview_png=b"PREVIEW-v2",
    )


def test_bundle_and_passes_roundtrip_after_newer_build(rendered: RenderedFixture) -> None:
    bundle = rendered.bundles["iso"]
    # A newer build and bundle are published into the same store.
    newer = _publish_newer_build(rendered.store, rendered.catalog.entries)
    assert newer.bundle_ref != bundle.bundle_ref
    assert newer.source_artifact_ref != rendered.source_ref

    # The original per-view bundle still resolves to its own build...
    resolution = resolve_selection(rendered.store, bundle.bundle_ref)
    assert resolution.source_artifact_ref == rendered.source_ref
    assert resolution.entries == rendered.catalog.entries
    # ...and so does each of its solid/face/edge pass refs.
    for pass_ref in bundle.pass_refs.as_tuple():
        via_pass = resolve_selection(rendered.store, pass_ref)
        assert via_pass.bundle_ref == bundle.bundle_ref
        assert via_pass.source_artifact_ref == rendered.source_ref


def test_pass_ref_binding_check_rejects_wrong_build(rendered: RenderedFixture) -> None:
    bundle = rendered.bundles["+X"]
    other_source = artifact_ref("build", rendered.store.blobs.put(b"UNRELATED-BUILD"))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(
            rendered.store, bundle.pass_refs.face, expected_source_artifact_ref=other_source
        )
    assert exc.value.stale.reason == "mismatched"


def test_png_encoding_is_deterministic(rendered: RenderedFixture) -> None:
    # The caller-side PNG encoder is metadata-free: identical arrays -> identical
    # bytes (the half of the determinism contract owned by this module).
    solid = rendered.arrays["iso"].solid
    assert encode_png(solid) == encode_png(np.array(solid))
    # And the published solid pass PNG is a stable re-encode of that array.
    bundle = rendered.bundles["iso"]
    solid_blob = blob_hash_of_ref(bundle.pass_refs.solid)
    assert rendered.store.blobs.get(solid_blob) == encode_png(solid)


def test_view_bundles_share_one_global_table(rendered: RenderedFixture) -> None:
    # The global selection table is shared across every view (one namespace).
    tables = {
        view: resolve_selection(rendered.store, bundle.bundle_ref).selection_table_ref
        for view, bundle in rendered.bundles.items()
    }
    assert len(set(tables.values())) == 1
