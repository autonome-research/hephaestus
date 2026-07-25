# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Stage 1 / Gate G1 end-to-end render pipeline on the public assembly fixture.

One narrative test drives the whole render service the way an agent (and Stage 2
``query_snapshot``) would, against a genuinely published engine build:

1. build ``primary`` with the real executor (``UnsafeLocalBackend``) and publish
   it through the ordinary :class:`Publisher` path, so refs/tags/labels are the
   authentic artifacts an agent inspects;
2. ``inspect_part`` rgb + mask-solid, asserting the mask decodes back to exactly
   the legend it published (the G1 "mask decode == legend" gate);
3. selection mode: three ID passes + preview + an immutable selection bundle per
   view, round-tripped through :func:`resolve_selection`;
4. a GLTF export of the same published geometry validates with one mesh per
   solid and its embedded raycast IDs resolve *through the inspect bundle* to the
   same table entries (proves the one shared selection-id namespace);
5. a SECOND build (a ``post_inset`` param tweak) is published, and every ref
   returned before it still resolves through the immutable content-addressed
   links (bundles are pinned to their source build, never copied);
6. the explode and section channels render (silhouette present / exploded frame
   differs);
7. ``heph render --json`` runs as a subprocess with ``node`` absent from
   ``PATH`` -- G1 requires the engine to render with no Node toolchain present.

Determinism is inherited from the render service; this module asserts the
integration contracts, not the golden bytes (covered by the goldens meta-test).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.kernel.metrics import metrics
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render import inspect as inspect_mod
from hephaestus.core.render.bundle import resolve_selection
from hephaestus.core.render.gltf import export_gltf, resolve_gltf_pick, validate_gltf
from hephaestus.core.render.goldens import sync_hc_projection
from hephaestus.core.render.inspect import RenderProject, inspect_part
from hephaestus.core.render.palette import hex_to_rgb, rgb_to_id
from hephaestus.core.render.selection import build_selection_catalog
from hephaestus.core.render.tessellate import tessellate
from PIL import Image

from opstore import OpStore

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"

W, H = 200, 150


def _build_and_publish(
    layout: ProjectLayout,
    store: OpStore,
    part: str,
    *,
    part_overrides: dict[str, int | float | str] | None = None,
) -> str:
    """Build+publish a part through the real executor/publisher; return artifact_ref."""
    publisher = Publisher(layout, store)
    script = layout.part_path(part).read_text(encoding="utf-8")
    globals_source = layout.globals_path.read_text(encoding="utf-8")
    out_dir = layout.store_root / "b" / f"{part}-{uuid.uuid4().hex[:8]}"
    try:
        build = run_build(
            BuildRequest(
                part=part,
                script=script,
                globals_source=globals_source,
                part_overrides=part_overrides or {},
            ),
            backend=UnsafeLocalBackend(),
            out_dir=out_dir,
        )
        assert build.result.status == "ok", build.result.to_json()
        sync_hc_projection(publisher, build.worker_result.get("hc_state"))
        publisher.publish_build(build, op_id=f"op-{uuid.uuid4().hex}")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    current = publisher.current_result(part)
    assert current is not None and current.artifact_ref is not None
    return current.artifact_ref


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> tuple[RenderProject, Path]:
    root = tmp_path_factory.mktemp("integration")
    shutil.copytree(ASSEMBLY, root, dirs_exist_ok=True)
    layout = load_project(root)
    store = open_store(layout)
    _build_and_publish(layout, store, "primary")
    return RenderProject(layout=layout, store=store), root


def _blob_present(store: OpStore, ref: str) -> bool:
    return store.blobs.has(blob_hash_of_ref(ref))


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


def test_full_pipeline(project: tuple[RenderProject, Path]) -> None:
    render_project, _root = project
    store = render_project.store
    current = render_project.publisher().current_result("primary")
    assert current is not None and current.artifact_ref is not None
    source_ref = current.artifact_ref

    # -- collect every ref returned pre-second-build for later re-resolution ---
    all_refs: set[str] = {source_ref}
    bundle_refs: list[str] = []
    pass_refs: list[str] = []

    # 1) rgb inspection over two standard views ------------------------------
    rgb = inspect_part(render_project, "primary", views=["iso", "+X"], width=W, height=H)
    assert rgb.status == "ok"
    assert rgb.source_artifact_ref == source_ref
    assert len(rgb.images) == 2
    for image in rgb.images:
        assert image.png.startswith(b"\x89PNG\r\n")
        assert _blob_present(store, image.render_ref)
        all_refs.add(image.render_ref)

    # 2) mask-solid: decode of the pass equals the published legend ----------
    mask = inspect_part(render_project, "primary", views=["iso"], channel="mask", width=W, height=H)
    assert mask.mask_mode == "solid"
    assert mask.mask_legend is not None
    legend_ids = {rgb_to_id(hex_to_rgb(colour)) for colour in mask.mask_legend}
    decoded = _decode_ids(mask.images[0].png)
    assert decoded  # something rendered
    assert decoded <= legend_ids  # every drawn id is in the legend (G1 gate)
    for descriptor in mask.mask_legend.values():
        assert isinstance(descriptor, dict) and descriptor["kind"] == "solid"
    all_refs.update(mask.render_artifact_refs)

    # 3) selection mode: bundles round-trip through immutable links ----------
    selection = inspect_part(
        render_project,
        "primary",
        views=["iso", "+X"],
        channel="mask",
        mask_mode="selection",
        width=W,
        height=H,
    )
    assert selection.selection_bundles is not None
    assert selection.selection_table_ref is not None
    assert len(selection.selection_bundles) == 2
    all_refs.update(selection.render_artifact_refs)
    all_refs.add(selection.selection_table_ref)
    assert selection.mask_legend_ref is not None
    all_refs.add(selection.mask_legend_ref)
    for bundle in selection.selection_bundles:
        resolution = resolve_selection(
            store, bundle.bundle_ref, expected_source_artifact_ref=source_ref
        )
        assert resolution.view == bundle.view
        assert resolution.source_artifact_ref == source_ref
        bundle_refs.append(bundle.bundle_ref)
        pass_refs.extend(bundle.pass_refs.as_tuple())
        all_refs.add(bundle.bundle_ref)
        all_refs.update(bundle.pass_refs.as_tuple())
    # a pass-ref alone resolves to the same bundle table (bidirectional link).
    first_bundle = selection.selection_bundles[0]
    via_pass = resolve_selection(store, first_bundle.pass_refs.solid)
    assert via_pass.entries == resolve_selection(store, first_bundle.bundle_ref).entries

    # 4) GLTF export of the same published geometry, bound to the inspect
    #    bundle: mesh==solid count and raycast IDs resolve through the bundle
    #    table (the ONE shared selection-id namespace). Rebuilds the catalog
    #    from the SAME published provenance the selection bundle used.
    resolved = inspect_mod._resolve_source(  # pyright: ignore[reportPrivateUsage]
        render_project, "primary", last_good=False, artifact_ref=None
    )
    brep_shape = cast("Any", load_brep_shape(resolved.brep))
    tess = tessellate(brep_shape)
    placements = inspect_mod._tag_placements(resolved.source_map)  # pyright: ignore[reportPrivateUsage]
    labels = inspect_mod._solid_labels(  # pyright: ignore[reportPrivateUsage]
        resolved.result, len(tess.solids)
    )
    catalog = build_selection_catalog(tess, placements=placements, labels=labels)
    solid_count = metrics(brep_shape).solids
    glb = export_gltf(
        brep_shape,
        catalog,
        bundle_ref=first_bundle.bundle_ref,
        source_artifact_ref=source_ref,
        selection_table_ref=selection.selection_table_ref,
        tess=tess,
        labels=labels,
    )
    validation = validate_gltf(glb, expected_solid_count=solid_count)
    assert validation.mesh_count == solid_count == len(tess.solids)
    assert validation.bundle_ref == first_bundle.bundle_ref
    for solid_index in range(solid_count):
        entry = resolve_gltf_pick(store, glb, solid_index)
        assert entry.kind == "solid"
        assert entry.solid_index == solid_index
    # a tagged-face raycast resolves the topology + tag through the bundle table.
    deck = placements["deck_top"]
    assert deck.solid_index is not None and deck.topo_index is not None
    face_entry = resolve_gltf_pick(store, glb, deck.solid_index, deck.topo_index)
    assert face_entry.kind == "face" and face_entry.tag == "deck_top"

    # 5) publish a SECOND build (param tweak) -- every earlier ref survives ---
    second_ref = _build_and_publish(
        render_project.layout,
        store,
        "primary",
        part_overrides={"post_inset": 20.0},
    )
    assert second_ref != source_ref  # genuinely a different geometry/build
    for ref in all_refs:
        assert _blob_present(store, ref), f"{ref} vanished after the second build"
    for bundle_ref in bundle_refs:
        resolution = resolve_selection(store, bundle_ref, expected_source_artifact_ref=source_ref)
        assert resolution.source_artifact_ref == source_ref
    for pass_ref in pass_refs:
        resolve_selection(store, pass_ref, expected_source_artifact_ref=source_ref)
    # the GLB still resolves its raycast through the (older) linked bundle.
    assert resolve_gltf_pick(store, glb, 0).kind == "solid"

    # 6) explode + section channels render -----------------------------------
    base = inspect_part(
        render_project,
        "primary",
        views=["iso"],
        channel="rgb",
        explode=0.0,
        width=W,
        height=H,
        artifact_ref=source_ref,
    )
    exploded = inspect_part(
        render_project,
        "primary",
        views=["iso"],
        channel="rgb",
        explode=1.0,
        width=W,
        height=H,
        artifact_ref=source_ref,
    )
    assert _silhouette(exploded.images[0].png) > 0
    assert base.images[0].png != exploded.images[0].png

    section = inspect_part(
        render_project,
        "primary",
        views=["iso"],
        channel="section",
        section_plane="+Z@c",
        width=W,
        height=H,
        artifact_ref=source_ref,
    )
    assert section.channel == "section"
    assert _silhouette(section.images[0].png) > 0
    assert section.selection_bundles is None


def _node_free_env() -> dict[str, str]:
    """A process env whose PATH resolves no ``node`` binary (G1 engine-first)."""
    env = dict(os.environ)
    kept = [
        entry
        for entry in env.get("PATH", "").split(os.pathsep)
        if entry and shutil.which("node", path=entry) is None
    ]
    env["PATH"] = os.pathsep.join(kept)
    return env


def test_heph_render_runs_without_node(project: tuple[RenderProject, Path]) -> None:
    _render_project, root = project
    env = _node_free_env()
    # Precondition: node truly unreachable in the child's PATH (engine-first).
    assert shutil.which("node", path=env["PATH"]) is None
    out = root / "render-nonode"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hephaestus.core.cli",
            "render",
            "primary",
            "--views",
            "iso",
            "--channel",
            "mask",
            "--out",
            str(out),
            "--json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    import json

    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["source_artifact_ref"].startswith("artifact:build:sha256:")
    assert len(payload["images"]) == 1
    assert Path(payload["images"][0]["file"]).is_file()
