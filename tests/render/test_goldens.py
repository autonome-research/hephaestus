# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Gate G1 render goldens (mission_plan Gate G1 / verification.md Tier 2).

This is the meta-test that protects the committed golden corpus under
``tests/render/goldens/``. Every golden is regenerated *only* through
``heph goldens --update`` (``hephaestus.core.render.goldens.update_goldens``);
here we prove that the committed bytes reproduce on this pinned software
rasterizer (llvmpipe) and satisfy every Gate G1 render criterion:

* each golden matches a fresh in-process render with ``SSIM >= 0.995``
  (determinism is machine-pinned, so on this rasterizer the match is in fact
  byte-identical — SSIM = 1.0 — but the gate tolerance is 0.995);
* a fresh render is byte-identical across two consecutive in-test renders
  (determinism is itself part of the gate);
* the provenance sidecar fields are exact (renderer string, deflection
  constants, image size, generator hash, and the ``png_sha256`` of the bytes),
  and the recorded ``source_artifact_ref`` reproduces from a fresh build;
* the ``mask`` channel decodes exactly to its legend — every non-background
  pixel colour is a legend colour and every legend colour appears across the
  standard views;
* every labeled solid has positive mask area in at least one standard view;
* ``explode(1.0)`` strictly increases the silhouette area over ``explode(0.0)``
  and the exploded golden differs from the unexploded one.

The renders are driven through the real executor -> publisher -> render service
path against the public ``assembly`` clean-room fixture, so the bytes under
test are the genuine engine artifacts an agent would observe.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.cameras import standard_view_names
from hephaestus.core.render.channels import explode_silhouette, scene_from_shape
from hephaestus.core.render.goldens import (
    DEFAULT_GOLDEN_DIR,
    GOLDEN_HEIGHT,
    GOLDEN_SPECS,
    GOLDEN_WIDTH,
    GoldenSpec,
    render_golden,
    renderer_string,
    script_hash,
    sync_hc_projection,
)
from hephaestus.core.render.inspect import InspectResult, RenderProject, inspect_part
from hephaestus.core.render.palette import hex_to_rgb, rgb_to_id
from hephaestus.core.render.tessellate import ANGULAR_DEFLECTION, LINEAR_DEFLECTION
from PIL import Image
from skimage.metrics import structural_similarity

from opstore import OpStore

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"
GOLDEN_DIR = REPO_ROOT / DEFAULT_GOLDEN_DIR

#: Gate G1 SSIM tolerance (mission_plan / verification.md Tier 2).
SSIM_FLOOR = 0.995
#: The two standard views goldens are generated for.
STANDARD_VIEWS: tuple[str, ...] = ("iso", "+X")

_SPECS: dict[str, GoldenSpec] = {spec.name: spec for spec in GOLDEN_SPECS}
#: Every (spec, view) golden the gate covers.
CASES: tuple[tuple[GoldenSpec, str], ...] = tuple(
    (spec, view) for spec in GOLDEN_SPECS for view in spec.views
)


def _case_id(case: tuple[GoldenSpec, str]) -> str:
    spec, view = case
    return f"{spec.name}-{view}"


def _slug(view: str) -> str:
    return view.replace("+", "p").replace("-", "m")


def _golden_path(spec: GoldenSpec, view: str) -> Path:
    return GOLDEN_DIR / f"{spec.name}_{_slug(view)}_{spec.channel}.png"


def _sidecar_path(spec: GoldenSpec, view: str) -> Path:
    return GOLDEN_DIR / f"{spec.name}_{_slug(view)}_{spec.channel}.json"


def _rgb(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def _decode_area(png: bytes) -> dict[int, int]:
    """``{selection_id: pixel_count}`` for every non-background colour in a mask."""
    arr = _rgb(png).reshape(-1, 3)
    colours, counts = np.unique(arr, axis=0, return_counts=True)
    out: dict[int, int] = {}
    for colour, count in zip(colours, counts, strict=True):
        triple = (int(colour[0]), int(colour[1]), int(colour[2]))
        if triple != (0, 0, 0):
            out[rgb_to_id(triple)] = int(count)
    return out


def _image_png(result: InspectResult, view: str) -> bytes:
    for image in result.images:
        if image.view == view:
            return image.png
    raise KeyError(f"view {view!r} not in result ({[i.view for i in result.images]})")


# --------------------------------------------------------------------------- #
# Fixtures: build+publish the assembly once, render every golden spec once.    #
# --------------------------------------------------------------------------- #


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
    root = tmp_path_factory.mktemp("goldens_assembly")
    shutil.copytree(ASSEMBLY, root, dirs_exist_ok=True)
    layout = load_project(root)
    store = open_store(layout)
    globals_source = layout.globals_path.read_text(encoding="utf-8")
    _build_and_publish(layout, store, "primary", globals_source)
    return RenderProject(layout=layout, store=store)


@pytest.fixture(scope="module")
def fresh(project: RenderProject) -> dict[str, InspectResult]:
    """One fresh render per golden spec (same path ``heph goldens`` uses)."""
    return {spec.name: render_golden(project, spec) for spec in GOLDEN_SPECS}


@pytest.fixture(scope="module")
def live_renderer() -> str:
    return renderer_string()


# --------------------------------------------------------------------------- #
# Corpus presence                                                              #
# --------------------------------------------------------------------------- #


def test_all_expected_goldens_present() -> None:
    assert GOLDEN_SPECS, "no golden specs declared"
    for spec, view in CASES:
        assert _golden_path(spec, view).is_file(), f"missing golden PNG for {spec.name} {view}"
        assert _sidecar_path(spec, view).is_file(), f"missing sidecar for {spec.name} {view}"


# --------------------------------------------------------------------------- #
# SSIM: committed golden vs a fresh render                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_golden_matches_fresh_render(
    case: tuple[GoldenSpec, str], fresh: dict[str, InspectResult]
) -> None:
    spec, view = case
    golden = _rgb(_golden_path(spec, view).read_bytes())
    rendered = _rgb(_image_png(fresh[spec.name], view))
    assert golden.shape == (GOLDEN_HEIGHT, GOLDEN_WIDTH, 3)
    assert rendered.shape == golden.shape
    score = cast("float", structural_similarity(golden, rendered, channel_axis=2, data_range=255))
    assert score >= SSIM_FLOOR, f"{spec.name} {view}: SSIM {score} < {SSIM_FLOOR}"


# --------------------------------------------------------------------------- #
# Determinism: two consecutive in-test renders are byte-identical              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", GOLDEN_SPECS, ids=lambda s: s.name)
def test_fresh_render_byte_identical_across_two_runs(
    spec: GoldenSpec, project: RenderProject, fresh: dict[str, InspectResult]
) -> None:
    again = render_golden(project, spec)
    for view in spec.views:
        assert _image_png(fresh[spec.name], view) == _image_png(again, view), (
            f"{spec.name} {view}: render is not byte-deterministic"
        )


# --------------------------------------------------------------------------- #
# Provenance sidecar                                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_provenance_sidecar_fields(
    case: tuple[GoldenSpec, str],
    fresh: dict[str, InspectResult],
    live_renderer: str,
) -> None:
    spec, view = case
    sidecar_raw: object = json.loads(_sidecar_path(spec, view).read_text(encoding="utf-8"))
    assert isinstance(sidecar_raw, dict)
    sidecar: Mapping[str, object] = sidecar_raw
    golden_png = _golden_path(spec, view).read_bytes()

    assert sidecar["golden"] == spec.name
    assert sidecar["fixture"] == spec.fixture
    assert sidecar["part"] == spec.part
    assert sidecar["view"] == view
    assert sidecar["channel"] == spec.channel
    assert sidecar["mask_mode"] == spec.mask_mode
    assert sidecar["section_plane"] == spec.section_plane
    assert sidecar["explode"] == spec.explode
    assert sidecar["width"] == GOLDEN_WIDTH
    assert sidecar["height"] == GOLDEN_HEIGHT
    assert sidecar["linear_deflection_mm"] == LINEAR_DEFLECTION
    assert sidecar["angular_deflection_rad"] == ANGULAR_DEFLECTION
    assert sidecar["gl_renderer"] == live_renderer
    assert sidecar["goldens_script_sha256"] == script_hash()
    assert sidecar["png_sha256"] == "sha256:" + hashlib.sha256(golden_png).hexdigest()

    # The recorded source ref must reproduce from a fresh deterministic build.
    source_ref = sidecar["source_artifact_ref"]
    assert isinstance(source_ref, str) and source_ref.startswith("artifact:")
    assert source_ref == fresh[spec.name].source_artifact_ref


# --------------------------------------------------------------------------- #
# Mask decode == legend, and every labeled solid visible                       #
# --------------------------------------------------------------------------- #


def _mask_spec() -> GoldenSpec:
    spec = _SPECS["assembly_primary_mask"]
    assert spec.channel == "mask"
    return spec


def _build_solid_labels(project: RenderProject) -> dict[int, str]:
    """Authoritative ``{solid_index: label}`` from the published build result.

    The solid-mask legend itself carries no labels (``inspect_part`` renders from
    a reloaded BRep, which drops build123d labels — see interface_notes), so the
    label<->solid association comes from the build's ``geometries`` in solid order.
    """
    result = project.publisher().current_result("primary")
    assert result is not None
    labels: dict[int, str] = {}
    index = 0
    for entry in result.geometries:
        for _ in range(max(entry.solids, 0)):
            labels[index] = entry.label
            index += 1
    return labels


def test_mask_decode_equals_legend(fresh: dict[str, InspectResult], project: RenderProject) -> None:
    """Every non-background mask pixel decodes to a legend colour, and the legend
    is exactly the build's solid-index domain (bijective + complete)."""
    spec = _mask_spec()
    result = fresh[spec.name]
    assert result.mask_mode == "solid"
    legend = result.mask_legend
    assert legend is not None, "solid mask must carry an inline legend"
    legend_ids = {rgb_to_id(hex_to_rgb(colour)) for colour in legend}
    for descriptor in legend.values():
        assert isinstance(descriptor, dict)
        assert descriptor["kind"] == "solid"

    # No stray colours: every decoded pixel colour is a legend colour.
    for view in spec.views:
        decoded = set(_decode_area(_golden_path(spec, view).read_bytes()))
        assert decoded, f"{view}: mask rendered nothing"
        assert decoded <= legend_ids, (
            f"{view}: pixel colours outside the legend: {decoded - legend_ids}"
        )

    # The legend is exactly the build's solid domain (one colour per solid).
    assert legend_ids == set(_build_solid_labels(project))


def test_every_labeled_solid_visible_in_some_standard_view(project: RenderProject) -> None:
    """Gate G1: every labeled solid has positive mask area in >= 1 standard view.

    iso and +X alone occlude some solids (a rear post hides behind its pair), so
    completeness is asserted across the full named standard-view set, which is
    what the gate's "standard view" refers to.
    """
    labels = _build_solid_labels(project)
    # The four congruent posts are disambiguated as post#1..post#4 in the build.
    base_labels = {label.split("#", 1)[0] for label in labels.values()}
    assert base_labels == {"bottom_deck", "top_deck", "post"}
    assert len(labels) == 6  # two decks + four posts

    views = [name for name in standard_view_names() if name != "front"]  # front == -Y
    visible: set[int] = set()
    for view in views:
        result = inspect_part(
            project, "primary", views=[view], channel="mask", width=240, height=180
        )
        visible |= {
            selection_id
            for selection_id, area in _decode_area(result.images[0].png).items()
            if area > 0
        }

    for selection_id, label in labels.items():
        assert selection_id in visible, (
            f"labeled solid {selection_id} ({label}) is not visible in any standard view"
        )


# --------------------------------------------------------------------------- #
# Explode strictly increases the silhouette                                    #
# --------------------------------------------------------------------------- #


def test_explode_strictly_increases_silhouette(project: RenderProject) -> None:
    """Gate G1: explode(1.0) strictly increases the silhouette over explode(0.0).

    Asserted on ``iso`` -- the standard view whose solids overlap in projection at
    ``t = 0`` (posts hidden between the full-footprint decks), which is where the
    ``explode_silhouette`` gate (fixed t=1 orthographic framing) strictly grows as
    solids separate. Views whose solids already project to disjoint regions
    (e.g. ``+X``: decks and posts occupy separate Z-bands) reveal no new area and
    move only by sub-pixel rasterisation -- see interface_notes.
    """
    ref = project.publisher().current_result("primary")
    assert ref is not None and ref.artifact_ref is not None
    shape = load_brep_shape(project.store.blobs.get(blob_hash_of_ref(ref.artifact_ref)))
    scene = scene_from_shape(shape)
    at_zero = explode_silhouette(scene, "iso", t=0.0, width=GOLDEN_WIDTH, height=GOLDEN_HEIGHT)
    at_one = explode_silhouette(scene, "iso", t=1.0, width=GOLDEN_WIDTH, height=GOLDEN_HEIGHT)
    assert at_one > at_zero, f"iso: explode(1.0) silhouette {at_one} !> explode(0.0) {at_zero}"


def test_explode_golden_differs_from_unexploded() -> None:
    rgb_spec = _SPECS["assembly_primary_rgb"]
    explode_spec = _SPECS["assembly_primary_explode"]
    for view in STANDARD_VIEWS:
        unexploded = _golden_path(rgb_spec, view).read_bytes()
        exploded = _golden_path(explode_spec, view).read_bytes()
        assert unexploded != exploded, f"{view}: exploded golden equals the unexploded golden"
