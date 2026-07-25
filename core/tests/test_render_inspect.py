# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""``inspect_part`` library: resolution matrix, schema rules, selection, explode.

Every test drives the real render stack (OCP tessellation + llvmpipe offscreen)
against the public assembly fixture built and published through the ordinary
executor/publisher path, so IDs, tags, and source refs are the genuine engine
artifacts an agent would inspect.
"""

from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path

import numpy as np
import pytest
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import resolve_selection
from hephaestus.core.render.channels import explode_silhouette, scene_from_shape
from hephaestus.core.render.goldens import sync_hc_projection
from hephaestus.core.render.inspect import (
    InspectResult,
    RenderProject,
    inspect_part,
    prepare_render_bundle,
)
from hephaestus.core.render.palette import hex_to_rgb, rgb_to_id
from PIL import Image

from opstore import OpStore

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"
FAILURE = FIXTURES / "failure_fillet"

W, H = 200, 150


def _build_and_publish(
    layout: ProjectLayout, store: OpStore, part: str, globals_source: str | None
) -> None:
    publisher = Publisher(layout, store)
    script = layout.part_path(part).read_text(encoding="utf-8")
    out_dir = layout.store_root / "b" / f"{part}-{uuid.uuid4().hex[:8]}"
    try:
        build = run_build(
            BuildRequest(part=part, script=script, globals_source=globals_source),
            backend=UnsafeLocalBackend(),
            out_dir=out_dir,
        )
        sync_hc_projection(publisher, build.worker_result.get("hc_state"))
        publisher.publish_build(build, op_id=f"op-{uuid.uuid4().hex}")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> RenderProject:
    root = tmp_path_factory.mktemp("assembly")
    shutil.copytree(ASSEMBLY, root, dirs_exist_ok=True)
    layout = load_project(root)
    store = open_store(layout)
    globals_source = layout.globals_path.read_text(encoding="utf-8")
    for part in ("primary", "bracket"):
        _build_and_publish(layout, store, part, globals_source)
    return RenderProject(layout=layout, store=store)


@pytest.fixture(scope="module")
def current_ref(project: RenderProject) -> str:
    ref = project.publisher().current_result("primary")
    assert ref is not None and ref.artifact_ref is not None
    return ref.artifact_ref


@pytest.fixture(scope="module")
def failed_project(tmp_path_factory: pytest.TempPathFactory) -> RenderProject:
    root = tmp_path_factory.mktemp("failure")
    (root / "hephaestus.toml").write_text('name = "failure"\n', encoding="utf-8")
    (root / "parts").mkdir()
    shutil.copy(FAILURE / "parts" / "broken.py", root / "parts" / "broken.py")
    layout = load_project(root)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    out_dir = layout.store_root / "b" / "broken"
    build = run_build(
        BuildRequest(part="broken", script=(root / "parts" / "broken.py").read_text()),
        backend=UnsafeLocalBackend(),
        out_dir=out_dir,
    )
    assert build.result.status == "failed"
    publisher.publish_build(build, op_id=f"op-{uuid.uuid4().hex}")
    return RenderProject(layout=layout, store=store)


def _decode_ids(png: bytes) -> set[int]:
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    ids: set[int] = set()
    for pixel in np.unique(arr.reshape(-1, 3), axis=0):
        triple = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        if triple != (0, 0, 0):
            ids.add(rgb_to_id(triple))
    return ids


def _silhouette(png: bytes) -> int:
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    return int((arr != 0).any(axis=2).sum())


def _pass_png(store: OpStore, ref: str) -> bytes:
    return store.blobs.get(blob_hash_of_ref(ref))


# -- resolution matrix ------------------------------------------------------


def test_current_build_resolution(project: RenderProject, current_ref: str) -> None:
    result = inspect_part(project, "primary", views=["iso", "+X"], width=W, height=H)
    assert result.status == "ok"
    assert result.source_artifact_ref == current_ref
    assert len(result.images) == 2
    assert set(result.render_artifact_refs) == {img.render_ref for img in result.images}


def test_explicit_artifact_ref_resolution(project: RenderProject, current_ref: str) -> None:
    result = inspect_part(
        project, "primary", views=["iso"], artifact_ref=current_ref, width=W, height=H
    )
    assert result.source_artifact_ref == current_ref


def test_last_good_renders_failed_checkpoint(failed_project: RenderProject) -> None:
    result = inspect_part(
        failed_project, "broken", views=["iso"], last_good=True, width=W, height=H
    )
    assert result.status == "ok"
    assert result.source_artifact_ref.startswith("artifact:build-checkpoint:sha256:")
    # The checkpoint is a real solid: something is drawn.
    assert _silhouette(result.images[0].png) > 0


def test_last_good_checkpoint_matches_explicit_artifact_ref(failed_project: RenderProject) -> None:
    by_flag = inspect_part(
        failed_project, "broken", views=["iso"], last_good=True, width=W, height=H
    )
    checkpoint = by_flag.source_artifact_ref
    by_ref = inspect_part(
        failed_project, "broken", views=["iso"], artifact_ref=checkpoint, width=W, height=H
    )
    assert by_ref.source_artifact_ref == checkpoint


def test_artifact_ref_and_last_good_mutually_exclusive(
    project: RenderProject, current_ref: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        inspect_part(
            project, "primary", artifact_ref=current_ref, last_good=True, width=W, height=H
        )
    assert "mutually exclusive" in exc.value.message


def test_no_current_build_is_addressing_error(project: RenderProject) -> None:
    with pytest.raises(AddressingError):
        inspect_part(project, "nonexistent_part", width=W, height=H)


# -- conditional schema rules ----------------------------------------------


def test_fifth_view_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError) as exc:
        inspect_part(project, "primary", views=["iso", "+X", "+Y", "+Z", "-Z"], width=W, height=H)
    assert "maxItems" in exc.value.message


def test_empty_views_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", views=[], width=W, height=H)


def test_section_requires_section_plane(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="section", width=W, height=H)


def test_section_plane_rejected_outside_section(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="rgb", section_plane="Z", width=W, height=H)


def test_selection_requires_mask_channel(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="rgb", mask_mode="selection", width=W, height=H)


def test_section_channel_renders(project: RenderProject) -> None:
    result = inspect_part(
        project,
        "primary",
        views=["iso"],
        channel="section",
        section_plane="+Z@c",
        width=W,
        height=H,
    )
    assert result.channel == "section"
    assert _silhouette(result.images[0].png) > 0
    assert result.selection_bundles is None


# -- mask solid + decode == legend -----------------------------------------


def test_mask_solid_decode_equals_legend(project: RenderProject) -> None:
    result = inspect_part(project, "primary", views=["iso"], channel="mask", width=W, height=H)
    assert result.mask_mode == "solid"
    assert result.mask_legend is not None
    legend = result.mask_legend
    legend_ids = {rgb_to_id(hex_to_rgb(colour)) for colour in legend}
    decoded = _decode_ids(result.images[0].png)
    assert decoded  # something rendered
    assert decoded <= legend_ids
    for colour, descriptor in legend.items():
        assert isinstance(descriptor, dict)
        assert descriptor["kind"] == "solid"
        # every solid-legend colour is decodable back to its id
        rgb_to_id(hex_to_rgb(colour))
    assert result.selection_table_ref is None
    assert result.selection_bundles is None


# -- selection mode completeness + round-trip ------------------------------


def _selection(project: RenderProject, **kwargs: object) -> InspectResult:
    return inspect_part(
        project,
        "primary",
        views=["iso", "+X"],
        channel="mask",
        mask_mode="selection",
        width=W,
        height=H,
        **kwargs,  # type: ignore[arg-type]
    )


def test_selection_mode_result_complete(project: RenderProject) -> None:
    result = _selection(project)
    assert result.mask_mode == "selection"
    assert result.selection_table_ref is not None
    assert result.mask_legend_ref is not None
    assert result.selection_bundles is not None
    assert len(result.selection_bundles) == 2  # one per view
    assert len(result.images) == 2
    for bundle, image in zip(result.selection_bundles, result.images, strict=True):
        assert bundle.view == image.view
        assert bundle.pass_refs.solid and bundle.pass_refs.face and bundle.pass_refs.edge
        # the inline preview is explicitly not palette-decodable
        assert image.palette_decodable is False


def test_selection_bundles_absent_outside_selection(project: RenderProject) -> None:
    for channel, mode in (("rgb", "solid"), ("mask", "solid")):
        result = inspect_part(
            project, "primary", views=["iso"], channel=channel, mask_mode=mode, width=W, height=H
        )
        assert result.selection_bundles is None
        assert result.selection_table_ref is None


def test_selection_passes_round_trip_after_newer_build(project: RenderProject) -> None:
    result = _selection(project)
    source = result.source_artifact_ref
    assert result.selection_bundles is not None
    # Publish a newer build of the same part; old bundles must still resolve.
    _build_and_publish(
        project.layout,
        project.store,
        "bracket",
        project.layout.globals_path.read_text(encoding="utf-8"),
    )
    for bundle in result.selection_bundles:
        resolution = resolve_selection(
            project.store, bundle.bundle_ref, expected_source_artifact_ref=source
        )
        assert resolution.view == bundle.view
        assert resolution.pass_refs == bundle.pass_refs
        for pass_ref in bundle.pass_refs.as_tuple():
            resolve_selection(project.store, pass_ref, expected_source_artifact_ref=source)


def test_selection_pass_decode_maps_to_table(project: RenderProject) -> None:
    result = _selection(project)
    assert result.selection_bundles is not None
    bundle = result.selection_bundles[0]
    resolution = resolve_selection(project.store, bundle.bundle_ref)
    decoded = _decode_ids(_pass_png(project.store, bundle.pass_refs.solid))
    assert decoded
    for selection_id in decoded:
        assert selection_id in resolution.entries
        assert resolution.entries[selection_id].kind == "solid"


def test_selection_entries_carry_tags_and_labels(project: RenderProject) -> None:
    result = _selection(project)
    assert result.selection_bundles is not None
    resolution = resolve_selection(project.store, result.selection_bundles[0].bundle_ref)
    tagged = {e.tag: e for e in resolution.entries.values() if e.tag is not None}
    assert set(tagged) == {"deck_top", "base_bottom"}
    assert tagged["deck_top"].kind == "face"
    # every entry has the owning solid's label (from result.geometries)
    labels = {e.label for e in resolution.entries.values()}
    assert {"bottom_deck", "top_deck", "post"} <= labels


# -- focus framing invariance ----------------------------------------------


def test_focus_preserves_legend_and_table(project: RenderProject) -> None:
    plain = inspect_part(
        project, "primary", views=["iso"], channel="mask", mask_mode="selection", width=W, height=H
    )
    focused = inspect_part(
        project,
        "primary",
        views=["iso"],
        channel="mask",
        mask_mode="selection",
        focus="post",
        width=W,
        height=H,
    )
    assert plain.selection_table_ref == focused.selection_table_ref
    assert plain.mask_legend == focused.mask_legend
    assert plain.mask_legend_ref == focused.mask_legend_ref


def test_focus_changes_framing(project: RenderProject) -> None:
    plain = inspect_part(project, "primary", views=["iso"], channel="mask", width=W, height=H)
    focused = inspect_part(
        project, "primary", views=["iso"], channel="mask", focus="post", width=W, height=H
    )
    # Same legend/ids, but a different camera => different pixels.
    assert plain.images[0].png != focused.images[0].png


def test_focus_unknown_target_is_addressing_error(project: RenderProject) -> None:
    with pytest.raises(AddressingError):
        inspect_part(project, "primary", views=["iso"], focus="not_a_label", width=W, height=H)


# -- explode ----------------------------------------------------------------


def test_explode_channel_differs_from_unexploded(project: RenderProject) -> None:
    # inspect_part maps rgb+explode>0 onto the shaded "explode" channel.
    base = inspect_part(
        project, "primary", views=["iso"], channel="rgb", explode=0.0, width=W, height=H
    )
    exploded = inspect_part(
        project, "primary", views=["iso"], channel="rgb", explode=1.0, width=W, height=H
    )
    assert base.images[0].png != exploded.images[0].png


def test_explode_strictly_increases_silhouette(project: RenderProject) -> None:
    # The canonical G1 explode measure (channels.explode_silhouette): fixed
    # framing to the exploded extent, so separating solids can only grow the mask.
    ref = project.publisher().current_result("primary")
    assert ref is not None and ref.artifact_ref is not None
    data = project.store.blobs.get(blob_hash_of_ref(ref.artifact_ref))
    from hephaestus.core.executor.artifact_geometry import load_brep_shape

    scene = scene_from_shape(load_brep_shape(data))
    at_zero = explode_silhouette(scene, "iso", t=0.0, width=W, height=H)
    at_one = explode_silhouette(scene, "iso", t=1.0, width=W, height=H)
    assert at_one > at_zero


def test_negative_explode_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", explode=-1.0, width=W, height=H)


# -- determinism ------------------------------------------------------------


def test_renders_are_deterministic(project: RenderProject) -> None:
    first = inspect_part(project, "primary", views=["iso"], channel="mask", width=W, height=H)
    second = inspect_part(project, "primary", views=["iso"], channel="mask", width=W, height=H)
    assert first.images[0].png == second.images[0].png
    assert first.images[0].render_ref == second.images[0].render_ref


# -- Stage 2 prepare_render_bundle helper ----------------------------------


def test_prepare_render_bundle_shape(project: RenderProject, current_ref: str) -> None:
    bundle = prepare_render_bundle(project, "primary", views=["iso", "+X"], width=W, height=H)
    assert bundle["source_artifact_ref"] == current_ref
    images = bundle["images"]
    assert isinstance(images, list) and len(images) == 2
    first = images[0]
    assert isinstance(first, dict)
    assert first["view"] == "iso"
    assert isinstance(first["png"], str) and first["png"]  # hex-encoded PNG
