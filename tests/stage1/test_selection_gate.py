# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Gate G1 — selection-mode artifacts, ID namespace, and immutable resolution.

Covers, clause by clause, the Gate G1 selection criteria (mission_plan §Stage 1):

* selection-mode artifacts use **separate palette-exact non-antialiased**
  solid/face/edge passes (``pixels never combine kinds``);
* every selectable ID maps to ``{kind, solid_index, topology_index}`` and the
  **exact source build ref**;
* untagged faces and edge overlays are included;
* every per-view bundle and every solid/face/edge pass ref **round-trips through
  selection resolution after a newer build is published**;
* an RGB render ref, the non-decodable preview (wrong mode), a mismatched build
  ref, and an aged-out ref each resolve to a structured ``stale_selection``.

Everything is driven against the public ``assembly`` fixture built+published
through the ordinary executor/publisher path.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from _render_gate import (
    PRIMARY_SOLIDS,
    PRIMARY_TAGS,
    H,
    W,
    assembly_project,
    blob_present,
    build_and_publish,
    decode_ids,
    pass_png,
)
from hephaestus.core.project_store.store import artifact_ref
from hephaestus.core.render.bundle import (
    RenderStore,
    StaleSelectionError,
    resolve_selection,
)
from hephaestus.core.render.inspect import InspectResult, RenderProject, inspect_part
from hephaestus.core.render.palette import build_legend

from opstore import OpStore


@dataclass(frozen=True)
class Gate:
    project: RenderProject
    selection: InspectResult
    source_ref: str


@pytest.fixture(scope="module")
def gate(tmp_path_factory: pytest.TempPathFactory) -> Gate:
    project = assembly_project(tmp_path_factory.mktemp("assembly"))
    current = project.publisher().current_result("primary")
    assert current is not None and current.artifact_ref is not None
    selection = inspect_part(
        project,
        "primary",
        views=["iso", "+X"],
        channel="mask",
        mask_mode="selection",
        width=W,
        height=H,
    )
    return Gate(project=project, selection=selection, source_ref=current.artifact_ref)


# -- shape of a successful selection result --------------------------------


def test_selection_result_has_bundle_table_and_legend_ref(gate: Gate) -> None:
    result = gate.selection
    assert result.status == "ok"
    assert result.mask_mode == "selection"
    # tool_schema: a selection result requires table + legend ref + one bundle/view.
    assert result.selection_table_ref is not None
    assert result.mask_legend_ref is not None
    assert result.selection_bundles is not None
    assert len(result.selection_bundles) == 2  # one per requested view
    assert len(result.images) == 2
    for bundle, image in zip(result.selection_bundles, result.images, strict=True):
        assert bundle.view == image.view
        assert bundle.pass_refs.solid and bundle.pass_refs.face and bundle.pass_refs.edge
        # the single inline composite preview is explicitly NOT palette-decodable
        assert image.palette_decodable is False


# -- separate palette-exact non-antialiased passes; kinds never combine -----


def test_passes_are_separate_and_kinds_never_combine(gate: Gate) -> None:
    result = gate.selection
    assert result.selection_bundles is not None
    bundle = result.selection_bundles[0]
    resolution = resolve_selection(gate.project.store, bundle.bundle_ref)

    kinds_by_pass = {
        "solid": bundle.pass_refs.solid,
        "face": bundle.pass_refs.face,
        "edge": bundle.pass_refs.edge,
    }
    for expected_kind, ref in kinds_by_pass.items():
        # decode_ids raises on any anti-aliased/blended pixel (palette-exact gate).
        decoded = decode_ids(pass_png(gate.project.store, ref))
        assert decoded, f"{expected_kind} pass drew nothing"
        for selection_id in decoded:
            entry = resolution.entries.get(selection_id)
            assert entry is not None, f"{selection_id} not in table"
            # A pass paints ONLY its own kind — kinds never combine in one pass.
            assert entry.kind == expected_kind


def test_solid_pass_paints_distinct_per_solid_colours(gate: Gate) -> None:
    # Each solid is painted its own single palette colour; a view may occlude a
    # solid, but every drawn colour is a distinct, decodable, in-range solid ID.
    result = gate.selection
    assert result.selection_bundles is not None
    bundle = result.selection_bundles[0]
    resolution = resolve_selection(gate.project.store, bundle.bundle_ref)
    solid_ids = decode_ids(pass_png(gate.project.store, bundle.pass_refs.solid))
    assert len(solid_ids) > 1  # several solids visible in this view
    solids_drawn = {resolution.entries[i].solid_index for i in solid_ids}
    # bijection: distinct IDs => distinct solids, all within the build's range.
    assert len(solids_drawn) == len(solid_ids)
    assert solids_drawn <= set(range(PRIMARY_SOLIDS))


# -- every selectable ID -> kind/solid/topology + exact build ref -----------


def test_every_id_maps_to_kind_solid_topo_and_exact_build_ref(gate: Gate) -> None:
    result = gate.selection
    assert result.selection_bundles is not None
    for bundle in result.selection_bundles:
        resolution = resolve_selection(gate.project.store, bundle.bundle_ref)
        # Each bundle/table is cryptographically bound to the EXACT source build.
        assert resolution.source_artifact_ref == gate.source_ref
        assert resolution.entries  # non-empty namespace
        for selection_id, entry in resolution.entries.items():
            assert selection_id >= 1
            assert entry.kind in ("solid", "face", "edge")
            assert isinstance(entry.solid_index, int) and entry.solid_index >= 0
            assert isinstance(entry.topology_index, int) and entry.topology_index >= 0
            assert entry.solid_index < PRIMARY_SOLIDS


def test_table_covers_all_three_kinds(gate: Gate) -> None:
    result = gate.selection
    assert result.selection_bundles is not None
    resolution = resolve_selection(gate.project.store, result.selection_bundles[0].bundle_ref)
    kinds = {entry.kind for entry in resolution.entries.values()}
    assert kinds == {"solid", "face", "edge"}


# -- untagged faces + edge overlays included --------------------------------


def test_untagged_faces_and_edges_are_in_the_namespace(gate: Gate) -> None:
    result = gate.selection
    assert result.selection_bundles is not None
    resolution = resolve_selection(gate.project.store, result.selection_bundles[0].bundle_ref)
    faces = [e for e in resolution.entries.values() if e.kind == "face"]
    edges = [e for e in resolution.entries.values() if e.kind == "edge"]
    # The vast majority of faces carry no tag: untagged faces are selectable too.
    assert any(e.tag is None for e in faces)
    # Edge overlays are present as their own selectable occurrences.
    assert edges
    assert all(e.tag is None or isinstance(e.tag, str) for e in edges)
    # The two authored face tags survive into the table.
    tagged = {e.tag for e in resolution.entries.values() if e.tag is not None}
    assert tagged >= PRIMARY_TAGS


# -- round-trip after a newer build is published ----------------------------


def test_refs_round_trip_after_newer_build(gate: Gate) -> None:
    result = gate.selection
    assert result.selection_bundles is not None
    store = gate.project.store
    source = gate.source_ref

    # Publish a genuinely different, newer build of the same part.
    newer = build_and_publish(
        gate.project.layout, store, "primary", part_overrides={"post_inset": 22.0}
    )
    assert newer != source

    for bundle in result.selection_bundles:
        # bundle ref resolves to its ORIGINAL immutable source build.
        resolution = resolve_selection(
            store, bundle.bundle_ref, expected_source_artifact_ref=source
        )
        assert resolution.source_artifact_ref == source
        assert resolution.view == bundle.view
        assert resolution.pass_refs == bundle.pass_refs
        assert blob_present(store, bundle.bundle_ref)
        # every solid/face/edge pass ref also round-trips to the same build.
        for pass_ref in bundle.pass_refs.as_tuple():
            via_pass = resolve_selection(store, pass_ref, expected_source_artifact_ref=source)
            assert via_pass.source_artifact_ref == source
            assert via_pass.entries == resolution.entries
            assert blob_present(store, pass_ref)


# -- stale_selection: rgb / wrong-mode / mismatched -------------------------


def test_rgb_render_ref_is_stale(gate: Gate) -> None:
    rgb = inspect_part(gate.project, "primary", views=["iso"], channel="rgb", width=W, height=H)
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(gate.project.store, rgb.images[0].render_ref)
    assert exc.value.stale.reason == "rgb_ref"


def test_preview_ref_is_wrong_mode(gate: Gate) -> None:
    # The inline selection image is the non-decodable composite preview.
    preview_ref = gate.selection.images[0].render_ref
    assert preview_ref.startswith("artifact:selection-preview:")
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(gate.project.store, preview_ref)
    assert exc.value.stale.reason == "wrong_mode"


def test_mismatched_build_ref_is_stale(gate: Gate) -> None:
    result = gate.selection
    assert result.selection_bundles is not None
    other_build = artifact_ref("build", gate.project.store.blobs.put(b"SOME-OTHER-BUILD"))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(
            gate.project.store,
            result.selection_bundles[0].bundle_ref,
            expected_source_artifact_ref=other_build,
        )
    assert exc.value.stale.reason == "mismatched"


def test_malformed_ref_is_stale(gate: Gate) -> None:
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(gate.project.store, "not-an-artifact-ref")
    assert exc.value.stale.reason == "malformed"


# -- stale_selection: expired (independent store so aging is isolated) ------


def test_expired_ref_is_stale(tmp_path_factory: pytest.TempPathFactory) -> None:
    from hephaestus.core.project_store.store import blob_hash_of_ref
    from hephaestus.core.render.palette import SelectionEntry

    store = OpStore.create(tmp_path_factory.mktemp("expire") / "store")
    source_ref = artifact_ref("build", store.blobs.put(b"BUILD-X"))
    entries = {1: SelectionEntry(kind="solid", solid_index=0, topology_index=0)}
    bundle = RenderStore(store).publish_selection_bundle(
        view="iso",
        source_artifact_ref=source_ref,
        solid_png=b"S",
        face_png=b"F",
        edge_png=b"E",
        entries=entries,
    )
    # Aging out the source build blob makes the linked bundle undecodable.
    store.blobs.remove(blob_hash_of_ref(source_ref))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(store, bundle.bundle_ref)
    assert exc.value.stale.reason == "expired"
    # sanity: build_legend over the entries is what a readable table decodes to.
    assert build_legend(entries)
