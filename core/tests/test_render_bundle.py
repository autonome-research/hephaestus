"""Selection bundle: publish/resolve round-trip, immutability, GC links, stale."""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.core.project_store.store import artifact_ref, blob_hash_of_ref
from hephaestus.core.render.bundle import (
    RenderStore,
    SelectionBundle,
    StaleSelectionError,
    resolve_selection,
)
from hephaestus.core.render.palette import SelectionEntry

from opstore import OpStore


def _store(tmp_path: Path, name: str = "store") -> OpStore:
    return OpStore.create(tmp_path / name)


def _publish_source(store: OpStore, tag: bytes) -> str:
    """Store a fake build BRep blob and return its build artifact ref."""
    blob = store.blobs.put(b"BREP-" + tag)
    return artifact_ref("build", blob)


def _entries() -> dict[int, SelectionEntry]:
    return {
        1: SelectionEntry(kind="solid", solid_index=0, topology_index=0, label="deck"),
        2: SelectionEntry(
            kind="face", solid_index=0, topology_index=5, tag="deck_top", label="deck"
        ),
        3: SelectionEntry(kind="edge", solid_index=0, topology_index=2, label="deck"),
    }


def _publish_bundle(store: OpStore, source_ref: str, view: str = "iso") -> SelectionBundle:
    # Passes depend on the source build (as real per-build geometry renders do),
    # so distinct builds produce distinct, unambiguous pass blobs.
    tag = f"{view}-{source_ref}".encode()
    return RenderStore(store).publish_selection_bundle(
        view=view,
        source_artifact_ref=source_ref,
        solid_png=b"SOLID-" + tag,
        face_png=b"FACE-" + tag,
        edge_png=b"EDGE-" + tag,
        entries=_entries(),
        preview_png=b"PREVIEW-" + tag,
    )


def test_publish_and_resolve_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    bundle = _publish_bundle(store, source)

    res = resolve_selection(store, bundle.bundle_ref)
    assert res.view == "iso"
    assert res.source_artifact_ref == source
    assert res.pass_refs == bundle.pass_refs
    assert res.selection_table_ref == bundle.selection_table_ref
    assert res.entries == _entries()
    # Legend keys are the palette colours of the ids.
    assert set(res.legend()) == {
        "#000002",  # id 1
        "#000003",  # id 2
        "#000004",  # id 3
    }


def test_resolve_through_any_pass_ref(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    bundle = _publish_bundle(store, source)
    for pass_ref in bundle.pass_refs.as_tuple():
        res = resolve_selection(store, pass_ref)
        assert res.bundle_ref == bundle.bundle_ref
        assert res.source_artifact_ref == source
        assert res.pass_refs == bundle.pass_refs


def test_immutable_after_second_build_published(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source1 = _publish_source(store, b"1")
    bundle1 = _publish_bundle(store, source1, view="iso")

    # A newer build and its bundle are published; bundle1 must be untouched.
    source2 = _publish_source(store, b"2")
    bundle2 = _publish_bundle(store, source2, view="iso")
    assert bundle2.bundle_ref != bundle1.bundle_ref
    assert bundle2.source_artifact_ref == source2

    res1 = resolve_selection(store, bundle1.bundle_ref)
    assert res1.source_artifact_ref == source1
    assert res1.pass_refs == bundle1.pass_refs
    # And still reachable via its own pass ref.
    assert resolve_selection(store, bundle1.pass_refs.face).source_artifact_ref == source1


def test_gc_links_pin_transitivity_from_bundle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    bundle = _publish_bundle(store, source)
    bundle_blob = blob_hash_of_ref(bundle.bundle_ref)
    store.gc.pin(bundle_blob)
    reachable = store.gc.reachable()
    # Pinning the bundle retains every pass, the table, and the source build.
    assert blob_hash_of_ref(source) in reachable
    assert blob_hash_of_ref(bundle.selection_table_ref) in reachable
    for pass_ref in bundle.pass_refs.as_tuple():
        assert blob_hash_of_ref(pass_ref) in reachable
    assert bundle.preview_ref is not None
    assert blob_hash_of_ref(bundle.preview_ref) in reachable


def test_gc_links_pin_transitivity_from_pass(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    bundle = _publish_bundle(store, source)
    # Pinning one selection layer retains the bundle, table, and source build.
    store.gc.pin(blob_hash_of_ref(bundle.pass_refs.solid))
    reachable = store.gc.reachable()
    assert blob_hash_of_ref(bundle.bundle_ref) in reachable
    assert blob_hash_of_ref(bundle.selection_table_ref) in reachable
    assert blob_hash_of_ref(source) in reachable
    for pass_ref in bundle.pass_refs.as_tuple():
        assert blob_hash_of_ref(pass_ref) in reachable


def test_stale_rgb_ref(tmp_path: Path) -> None:
    store = _store(tmp_path)
    render = RenderStore(store).publish_render(b"PNGDATA")
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(store, render.ref)
    assert exc.value.stale.reason == "rgb_ref"
    assert exc.value.stale.to_json()["code"] == "stale_selection"


def test_stale_wrong_mode_preview(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    bundle = _publish_bundle(store, source)
    assert bundle.preview_ref is not None
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(store, bundle.preview_ref)
    assert exc.value.stale.reason == "wrong_mode"


def test_stale_mismatched_build(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    other = _publish_source(store, b"other")
    bundle = _publish_bundle(store, source)
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(store, bundle.pass_refs.edge, expected_source_artifact_ref=other)
    assert exc.value.stale.reason == "mismatched"


def test_stale_expired_source(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    bundle = _publish_bundle(store, source)
    # Source build blob ages out under GC; the bundle can no longer decode.
    store.blobs.remove(blob_hash_of_ref(source))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(store, bundle.bundle_ref)
    assert exc.value.stale.reason == "expired"


def test_stale_expired_pass(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _publish_source(store, b"1")
    bundle = _publish_bundle(store, source)
    store.blobs.remove(blob_hash_of_ref(bundle.pass_refs.solid))
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(store, bundle.pass_refs.solid)
    assert exc.value.stale.reason == "expired"


def test_stale_malformed_ref(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(StaleSelectionError) as exc:
        resolve_selection(store, "not-an-artifact-ref")
    assert exc.value.stale.reason == "malformed"
