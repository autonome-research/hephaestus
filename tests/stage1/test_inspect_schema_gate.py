# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Gate G1 — inspect_part conditional-schema rejections, explode, legend paging.

Gate G1 clauses covered here:

* ``inspect_part`` conditional-schema rejections (every canonical-schema rule of
  tool_schema §inspect_part: ``views`` bounds, section/selection channel rules,
  ``artifact_ref``/``last_good`` mutual exclusion, explode domain);
* explode **monotonicity across t = 0 / 0.5 / 1.0** (non-decreasing silhouette,
  strictly increasing between 0 and 1) plus a shaded render that differs;
* **mask legend paging boundary**: an oversized legend is not inlined, sets
  ``mask_legend_truncated`` and an opaque **readable** ``mask_legend_ref``; an
  under-cap legend inlines.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from _render_gate import H, W, assembly_project, current_artifact_ref
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.channels import explode_silhouette, scene_from_shape
from hephaestus.core.render.inspect import (
    INLINE_LEGEND_CAP_BYTES,
    RenderProject,
    _publish_legend,
    inspect_part,
)
from hephaestus.core.render.palette import SelectionEntry, build_legend
from opstore.types import JSONValue

from opstore import canonical_json


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> RenderProject:
    return assembly_project(tmp_path_factory.mktemp("assembly-schema"))


# -- conditional-schema rejections (tool_schema §inspect_part) ---------------


def test_fifth_view_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError) as exc:
        inspect_part(project, "primary", views=["iso", "+X", "+Y", "+Z", "-Z"], width=W, height=H)
    assert "maxItems" in exc.value.message


def test_empty_views_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError) as exc:
        inspect_part(project, "primary", views=[], width=W, height=H)
    assert "minItems" in exc.value.message


def test_unknown_view_name_rejected(project: RenderProject) -> None:
    with pytest.raises((ValidationError, AddressingError)):
        inspect_part(project, "primary", views=["nope"], width=W, height=H)


def test_unknown_channel_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="hologram", width=W, height=H)


def test_unknown_mask_mode_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="mask", mask_mode="wireframe", width=W, height=H)


def test_section_requires_section_plane(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="section", width=W, height=H)


def test_section_plane_forbidden_outside_section(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="rgb", section_plane="+Z@c", width=W, height=H)


def test_selection_mode_requires_mask_channel(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", channel="rgb", mask_mode="selection", width=W, height=H)


def test_artifact_ref_and_last_good_mutually_exclusive(project: RenderProject) -> None:
    ref = current_artifact_ref(project, "primary")
    with pytest.raises(ValidationError) as exc:
        inspect_part(project, "primary", artifact_ref=ref, last_good=True, width=W, height=H)
    assert "mutually exclusive" in exc.value.message


def test_negative_explode_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", explode=-0.5, width=W, height=H)


def test_non_finite_explode_rejected(project: RenderProject) -> None:
    with pytest.raises(ValidationError):
        inspect_part(project, "primary", explode=float("inf"), width=W, height=H)


# -- explode monotonicity across 0 / 0.5 / 1.0 ------------------------------


def test_explode_silhouette_monotonic_across_thirds(project: RenderProject) -> None:
    ref = current_artifact_ref(project, "primary")
    scene = scene_from_shape(load_brep_shape(project.store.blobs.get(blob_hash_of_ref(ref))))
    at_zero = explode_silhouette(scene, "iso", t=0.0, width=W, height=H)
    at_half = explode_silhouette(scene, "iso", t=0.5, width=W, height=H)
    at_one = explode_silhouette(scene, "iso", t=1.0, width=W, height=H)
    # Fixed framing to the t=1 extent => non-decreasing; overlapping solids at
    # t=0 => strictly larger silhouette once fully exploded.
    assert at_zero <= at_half <= at_one
    assert at_one > at_zero


def test_exploded_shaded_render_differs(project: RenderProject) -> None:
    ref = current_artifact_ref(project, "primary")
    base = inspect_part(
        project,
        "primary",
        views=["iso"],
        channel="rgb",
        explode=0.0,
        artifact_ref=ref,
        width=W,
        height=H,
    )
    exploded = inspect_part(
        project,
        "primary",
        views=["iso"],
        channel="rgb",
        explode=1.0,
        artifact_ref=ref,
        width=W,
        height=H,
    )
    assert base.images[0].png != exploded.images[0].png


# -- mask legend paging boundary --------------------------------------------


def test_selection_legend_ref_present_and_readable(project: RenderProject) -> None:
    result = inspect_part(
        project,
        "primary",
        views=["iso"],
        channel="mask",
        mask_mode="selection",
        width=W,
        height=H,
    )
    # selection mode always publishes an opaque, readable legend ref.
    assert result.mask_legend_ref is not None
    blob = project.store.blobs.get(blob_hash_of_ref(result.mask_legend_ref))
    assert blob  # readable
    # It decodes to a JSON legend keyed by palette-colour hex strings.
    import json

    legend = json.loads(blob.decode("utf-8"))
    assert isinstance(legend, dict) and legend
    assert all(k.startswith("#") for k in legend)


def test_solid_mask_legend_inlines_below_cap(project: RenderProject) -> None:
    result = inspect_part(project, "primary", views=["iso"], channel="mask", width=W, height=H)
    # The 6-solid legend is tiny: inline present, not truncated.
    assert result.mask_legend is not None
    assert result.mask_legend_truncated is False


def _big_legend(n: int) -> Mapping[str, JSONValue]:
    entries = {
        i: SelectionEntry(kind="face", solid_index=i % 8, topology_index=i, tag=f"tag_{i:05d}")
        for i in range(1, n + 1)
    }
    return build_legend(entries)


def test_oversized_legend_pages_through_readable_ref(project: RenderProject) -> None:
    big = _big_legend(4000)
    payload = canonical_json(big).encode("utf-8")
    assert len(payload) > INLINE_LEGEND_CAP_BYTES  # genuinely over the cap

    inline, ref, truncated = _publish_legend(project.store, big, force_ref=False)
    assert truncated is True
    assert inline is None  # over the cap => not inlined
    assert ref is not None
    # The opaque ref is READABLE and losslessly reconstructs the full legend.
    stored = project.store.blobs.get(blob_hash_of_ref(ref))
    assert stored == payload


def test_under_cap_legend_inlines_without_forced_ref(project: RenderProject) -> None:
    small = _big_legend(3)
    inline, ref, truncated = _publish_legend(project.store, small, force_ref=False)
    assert truncated is False
    assert inline == small
    assert ref is None
