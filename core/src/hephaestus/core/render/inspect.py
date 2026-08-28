"""``inspect_part`` library implementation (tool_schema §inspect_part, arch §3.3).

The grounded-observation entry point. It *resolves* which geometry to render and
*assembles* the typed :class:`InspectResult`, delegating all actual rendering to
the shared render service so the whole engine agrees on one namespace and one
set of golden bytes:

* channel rendering (``rgb`` / ``mask`` solid-ID / ``section`` / exploded shaded)
  goes through :mod:`hephaestus.core.render.channels`;
* ``channel="mask", mask_mode="selection"`` uses
  :mod:`hephaestus.core.render.selection` — the same
  :func:`~hephaestus.core.render.selection.build_selection_catalog` namespace
  that :mod:`hephaestus.core.render.gltf` embeds, so a bundle's IDs and a GLB's
  raycast IDs are identical;
* immutable artifacts are published through
  :class:`hephaestus.core.render.bundle.RenderStore`.

Resolution (mine): the part's current successful build, an explicit immutable
``artifact_ref`` (mutually exclusive with ``last_good``), or the most-recent
failed attempt's last-good checkpoint (``last_good=True``). Labels and tags for
the selection table are recovered from the published build result's
``geometries`` and its source-map artifact, because a reloaded BRep artifact
carries neither.

No Pi session, vision call, or bridge coupling lives here (Stage 2).
:func:`prepare_render_bundle` is the tool-free helper ``query_snapshot`` builds
on. Determinism is inherited from the render service (fixed deflection, llvmpipe
flat/shaded passes, metadata-free PNG encoder). ``focus`` changes only camera
framing and never the ID namespace or legend; ``explode`` is honoured on the
shaded ``rgb`` channel.
"""

# trimesh / pyrender / PIL ship no (or partial) type stubs; the reportUnknown*
# relaxations are declared for this package's render/ executionEnvironment in
# root pyproject (see interface notes), mirroring offscreen.py / tessellate.py.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.executor.tags import TagPlacement
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.retention import last_failure_pointer
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import PassRefs, RenderStore, SelectionBundle
from hephaestus.core.render.cameras import camera_framing, parse_view
from hephaestus.core.render.channels import (
    RenderOptions,
    RenderScene,
    render_channel,
    scene_from_shape,
)
from hephaestus.core.render.offscreen import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ColoredMesh,
    OffscreenSession,
)
from hephaestus.core.render.palette import build_legend, id_to_rgb
from hephaestus.core.render.selection import (
    SelectionCatalog,
    build_selection_catalog,
    encode_png,
    render_selection_view,
)
from hephaestus.core.render.tessellate import Tessellation, face_trimesh
from hephaestus.core.types import BuildResult
from numpy.typing import NDArray
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

__all__ = [
    "CHANNELS",
    "DEFAULT_VIEWS",
    "INLINE_LEGEND_CAP_BYTES",
    "MASK_LEGEND_KIND",
    "MASK_MODES",
    "MAX_VIEWS",
    "Channel",
    "InspectImage",
    "InspectResult",
    "MaskMode",
    "RenderProject",
    "RenderSource",
    "SelectionBundleView",
    "build_solid_labels",
    "current_part_for_ref",
    "inspect_part",
    "prepare_render_bundle",
    "resolve_build_artifact",
    "resolve_render_source",
    "scene_tessellation",
    "tag_placements_from_source_map",
]

Channel = Literal["rgb", "mask", "section"]
MaskMode = Literal["solid", "selection"]

CHANNELS: tuple[Channel, ...] = ("rgb", "mask", "section")
MASK_MODES: tuple[MaskMode, ...] = ("solid", "selection")

#: Default requested views (tool_schema default).
DEFAULT_VIEWS: tuple[str, ...] = ("iso", "+X")
#: Canonical-schema ``maxItems`` for ``views``; a 5th view is rejected here.
MAX_VIEWS = 4
#: Inline legend cap (tool_schema): larger legends page through ``read_artifact``.
INLINE_LEGEND_CAP_BYTES = 50 * 1024
#: Artifact kind for a published (opaque, readable) mask legend.
MASK_LEGEND_KIND = "mask-legend"


# --------------------------------------------------------------------------
# public types


@dataclass(frozen=True)
class RenderProject:
    """A project handle for the render service: its layout + opstore."""

    layout: ProjectLayout
    store: OpStore

    def publisher(self) -> Publisher:
        """A :class:`Publisher` for lock-free current/last-good reads."""
        return Publisher(self.layout, self.store)


@dataclass(frozen=True)
class InspectImage:
    """One rendered image for one view of the requested channel."""

    view: str
    channel: Channel
    render_ref: str
    png: bytes
    palette_decodable: bool

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "view": self.view,
            "channel": self.channel,
            "render_artifact_ref": self.render_ref,
            "palette_decodable": self.palette_decodable,
            "size_bytes": len(self.png),
        }


@dataclass(frozen=True)
class SelectionBundleView:
    """A per-view selection bundle reference (tool_schema ``selection_bundles``)."""

    view: str
    bundle_ref: str
    pass_refs: PassRefs

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "view": self.view,
            "bundle_ref": self.bundle_ref,
            "pass_refs": self.pass_refs.to_json(),
        }


@dataclass(frozen=True)
class InspectResult:
    """The typed ``inspect_part`` result, mirroring the tool-schema fields."""

    status: Literal["ok"]
    source_artifact_ref: str
    channel: Channel
    mask_mode: MaskMode
    images: tuple[InspectImage, ...]
    render_artifact_refs: tuple[str, ...]
    mask_legend_truncated: bool
    mask_legend: Mapping[str, JSONValue] | None = None
    mask_legend_ref: str | None = None
    selection_table_ref: str | None = None
    selection_bundles: tuple[SelectionBundleView, ...] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "status": self.status,
            "source_artifact_ref": self.source_artifact_ref,
            "images": [image.to_json() for image in self.images],
            "render_artifact_refs": list(self.render_artifact_refs),
            "mask_legend_truncated": self.mask_legend_truncated,
        }
        if self.mask_legend is not None:
            out["mask_legend"] = dict(self.mask_legend)
        if self.mask_legend_ref is not None:
            out["mask_legend_ref"] = self.mask_legend_ref
        if self.selection_table_ref is not None:
            out["selection_table_ref"] = self.selection_table_ref
        if self.selection_bundles is not None:
            out["selection_bundles"] = [bundle.to_json() for bundle in self.selection_bundles]
        return out


# --------------------------------------------------------------------------
# validation


def _validate(
    views: Sequence[str],
    channel: str,
    mask_mode: str,
    section_plane: str | None,
    explode: float,
    last_good: bool,
    artifact_ref: str | None,
) -> tuple[tuple[str, ...], Channel, MaskMode]:
    """Enforce every conditional canonical-schema rule (raises ``validation_error``)."""
    if channel not in CHANNELS:
        raise ValidationError(
            f"channel must be one of {', '.join(CHANNELS)}, got {channel!r}", kind="contract"
        )
    if mask_mode not in MASK_MODES:
        raise ValidationError(
            f"mask_mode must be one of {', '.join(MASK_MODES)}, got {mask_mode!r}", kind="contract"
        )
    if not views:
        raise ValidationError(
            "views has minItems=1; at least one view is required", kind="contract"
        )
    if len(views) > MAX_VIEWS:
        raise ValidationError(
            f"views has maxItems={MAX_VIEWS}; {len(views)} requested (a 5th view is rejected)",
            kind="contract",
        )
    resolved_views = tuple(dict.fromkeys(views))
    for view in resolved_views:
        parse_view(view)  # rejects unknown names with candidates/grammar
    if mask_mode != "solid" and channel != "mask":
        raise ValidationError(
            f"mask_mode={mask_mode!r} requires channel='mask' (got {channel!r})", kind="contract"
        )
    if channel == "section" and section_plane is None:
        raise ValidationError("channel='section' requires section_plane", kind="contract")
    if channel != "section" and section_plane is not None:
        raise ValidationError(
            f"section_plane is only valid with channel='section' (got {channel!r})", kind="contract"
        )
    if last_good and artifact_ref is not None:
        raise ValidationError(
            "artifact_ref and last_good=true are mutually exclusive", kind="contract"
        )
    if not np.isfinite(explode) or explode < 0.0:
        raise ValidationError(
            f"explode must be a finite value >= 0.0, got {explode!r}", kind="contract"
        )
    return resolved_views, channel, mask_mode


# --------------------------------------------------------------------------
# source resolution


@dataclass(frozen=True)
class RenderSource:
    """The geometry one render/export reads, plus the provenance joined to it.

    ``result`` and ``source_map`` are the *joins*, not the geometry: a reloaded
    BRep artifact carries neither solid labels nor tag placements, so they are
    recovered from the published build result and its source-map artifact and are
    ``None`` whenever the ref is not some part's current build. Public because
    :mod:`hephaestus.core.render.gltf_publish` resolves the same three things for
    the same ref (``INTERFACE.md`` §5.1) and mission rule 6 forbids a second
    resolver.
    """

    source_artifact_ref: str
    brep: bytes
    result: BuildResult | None
    source_map: Mapping[str, JSONValue] | None


def _load_blob(store: OpStore, ref: str, *, what: str) -> bytes:
    blob = blob_hash_of_ref(ref)
    if not store.blobs.has(blob):
        raise ValidationError(f"{what} {ref} is not a durably stored artifact", kind="contract")
    return store.blobs.get(blob)


def _load_source_map(store: OpStore, ref: str | None) -> Mapping[str, JSONValue] | None:
    if ref is None:
        return None
    blob = blob_hash_of_ref(ref)
    if not store.blobs.has(blob):
        return None
    loaded: object = json.loads(store.blobs.get(blob).decode("utf-8"))
    return cast("Mapping[str, JSONValue]", loaded) if isinstance(loaded, dict) else None


def current_part_for_ref(project: RenderProject, artifact_ref: str) -> str | None:
    """The part whose **current** build is ``artifact_ref``, or ``None``.

    ``GET /artifacts/{ref}/gltf`` (§2.3) is addressed by ref, not by part, so the
    producer has to find the part before it can join the build result's labels
    and the source map's tags. A ref that is nobody's current build simply has no
    part to join, and the caller renders without labels rather than guessing one
    — the same degradation :func:`resolve_render_source` already applies to a
    non-current ``artifact_ref``.
    """
    publisher = project.publisher()
    for name in project.layout.part_names():
        current = publisher.current_result(name)
        if current is not None and current.artifact_ref == artifact_ref:
            return name
    return None


def resolve_build_artifact(project: RenderProject, artifact_ref: str) -> RenderSource:
    """Resolve an explicit immutable build ref, joining its part's provenance.

    The by-ref entry point :func:`resolve_render_source` cannot be: that one is
    keyed by part name, because ``inspect_part`` always has one. Here the ref is
    the whole request, so the part is *derived* (:func:`current_part_for_ref`)
    and the same resolver runs; when no part claims the ref, the non-current
    branch's answer is returned directly — geometry, no result, no source map.
    """
    part = current_part_for_ref(project, artifact_ref)
    if part is not None:
        return resolve_render_source(project, part, last_good=False, artifact_ref=artifact_ref)
    return RenderSource(
        source_artifact_ref=artifact_ref,
        brep=_load_blob(project.store, artifact_ref, what="artifact_ref"),
        result=None,
        source_map=None,
    )


def resolve_render_source(
    project: RenderProject,
    name: str,
    *,
    last_good: bool,
    artifact_ref: str | None,
) -> RenderSource:
    """Resolve the geometry to render (current / artifact_ref / last-good)."""
    store = project.store
    publisher = project.publisher()
    if artifact_ref is not None:
        data = _load_blob(store, artifact_ref, what="artifact_ref")
        current = publisher.current_result(name)
        if current is not None and current.artifact_ref == artifact_ref:
            return RenderSource(
                source_artifact_ref=artifact_ref,
                brep=data,
                result=current,
                source_map=_load_source_map(store, current.source_map_ref),
            )
        return RenderSource(
            source_artifact_ref=artifact_ref, brep=data, result=None, source_map=None
        )
    if last_good:
        pointer = store.blobs.read_pointer(last_failure_pointer(name))
        if pointer is None:
            raise AddressingError(
                f"part {name!r} has no recorded failed build to inspect (last_good)",
                selector=name,
                candidates=project.layout.part_names(),
            )
        record = json.loads(store.blobs.get(pointer).decode("utf-8"))
        failed = BuildResult.from_json(cast("Mapping[str, JSONValue]", record))
        checkpoint_ref = failed.error.last_good_artifact_ref if failed.error is not None else None
        if checkpoint_ref is None:
            raise ValidationError(
                f"part {name!r}'s most recent failure has no last-good checkpoint to render",
                kind="contract",
            )
        data = _load_blob(store, checkpoint_ref, what="last_good_artifact_ref")
        return RenderSource(
            source_artifact_ref=checkpoint_ref, brep=data, result=None, source_map=None
        )
    current = publisher.current_result(name)
    if current is None or current.artifact_ref is None:
        raise AddressingError(
            f"part {name!r} has no current successful build to inspect",
            selector=name,
            candidates=project.layout.part_names(),
        )
    return RenderSource(
        source_artifact_ref=current.artifact_ref,
        brep=_load_blob(store, current.artifact_ref, what="artifact_ref"),
        result=current,
        source_map=_load_source_map(store, current.source_map_ref),
    )


# --------------------------------------------------------------------------
# selection namespace inputs (labels + tag placements from published provenance)


def build_solid_labels(result: BuildResult | None, solid_count: int) -> dict[int, str]:
    """Map each solid index to its geometry-tree label (tree order == solid order)."""
    labels: dict[int, str] = {}
    if result is None:
        return labels
    index = 0
    for entry in result.geometries:
        for _ in range(max(entry.solids, 0)):
            if index < solid_count:
                labels[index] = entry.label
                index += 1
    return labels


def tag_placements_from_source_map(
    source_map: Mapping[str, JSONValue] | None,
) -> dict[str, TagPlacement]:
    """Reconstruct ``{tag: TagPlacement}`` from a published source-map artifact."""
    out: dict[str, TagPlacement] = {}
    if source_map is None:
        return out
    tags = source_map.get("tags")
    if not isinstance(tags, dict):
        return out
    for name, raw in cast("Mapping[str, JSONValue]", tags).items():
        if not isinstance(raw, dict):
            continue
        placement = cast("Mapping[str, JSONValue]", raw)
        kind = placement.get("kind")
        solid = placement.get("solid")
        topo = placement.get("topo_index")
        statement = placement.get("statement")
        line = placement.get("line")
        if not isinstance(kind, str):
            continue
        out[name] = TagPlacement(
            kind=kind,
            solid_index=solid if isinstance(solid, int) and not isinstance(solid, bool) else None,
            topo_index=topo if isinstance(topo, int) and not isinstance(topo, bool) else None,
            statement_index=(
                statement if isinstance(statement, int) and not isinstance(statement, bool) else -1
            ),
            line=line if isinstance(line, int) and not isinstance(line, bool) else 0,
        )
    return out


# --------------------------------------------------------------------------
# framing helpers (bounds over a focused solid subset)


def _tess_bounds(
    tess: Tessellation, solids: Sequence[int] | None
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if solids is None:
        return tess.bounds()
    mins: list[NDArray[np.float64]] = []
    maxs: list[NDArray[np.float64]] = []
    for s in solids:
        for face in tess.solids[s].faces:
            if face.vertices.size:
                mins.append(np.asarray(face.vertices.min(axis=0), dtype=np.float64))
                maxs.append(np.asarray(face.vertices.max(axis=0), dtype=np.float64))
    if not mins:
        return tess.bounds()
    lo = np.min(np.vstack(mins), axis=0)
    hi = np.max(np.vstack(maxs), axis=0)
    return (
        (float(lo[0]), float(lo[1]), float(lo[2])),
        (float(hi[0]), float(hi[1]), float(hi[2])),
    )


def _focus_solids(
    focus: str,
    labels: Mapping[int, str],
    placements: Mapping[str, TagPlacement],
) -> tuple[int, ...]:
    """Solids matched by a focus label or tag (raises ``addressing_error`` on miss).

    Labels come from the recovered build ``geometries`` (a reloaded BRep artifact
    carries none), tags from the recovered source map — the same provenance the
    selection table uses, so focus never depends on the mode.
    """
    by_label: dict[str, list[int]] = {}
    for index, label in labels.items():
        by_label.setdefault(label, []).append(index)
    if focus in by_label:
        return tuple(sorted(by_label[focus]))
    focus_placement = placements.get(focus)
    if focus_placement is not None and focus_placement.solid_index is not None:
        return (focus_placement.solid_index,)
    raise AddressingError(
        f"focus {focus!r} matches no labeled solid or tag",
        selector=focus,
        candidates=tuple(sorted(by_label) + sorted(placements)),
    )


# --------------------------------------------------------------------------
# legend publication


def _publish_legend(
    store: OpStore, legend: Mapping[str, JSONValue], *, force_ref: bool
) -> tuple[Mapping[str, JSONValue] | None, str | None, bool]:
    """Return ``(inline_legend | None, legend_ref | None, truncated)``."""
    payload = canonical_json(cast("JSONValue", legend)).encode("utf-8")
    truncated = len(payload) > INLINE_LEGEND_CAP_BYTES
    inline: Mapping[str, JSONValue] | None = None if truncated else legend
    ref: str | None = None
    if truncated or force_ref:
        ref = make_artifact_ref(MASK_LEGEND_KIND, store.blobs.put(payload))
    return inline, ref, truncated


# --------------------------------------------------------------------------
# entry point


def inspect_part(
    project: RenderProject,
    name: str,
    *,
    views: Sequence[str] = DEFAULT_VIEWS,
    channel: str = "rgb",
    mask_mode: str = "solid",
    section_plane: str | None = None,
    explode: float = 0.0,
    last_good: bool = False,
    artifact_ref: str | None = None,
    focus: str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> InspectResult:
    """Render a part's geometry per ``tool_schema.md`` §inspect_part.

    All schema conditionals (``views`` bounds, section/selection channel rules,
    ``artifact_ref``/``last_good`` mutual exclusion) are validated before any
    geometry is loaded. Rendering delegates to the shared render service; see the
    module docstring for the division of responsibilities.
    """
    resolved_views, channel_lit, mask_mode_lit = _validate(
        views, channel, mask_mode, section_plane, explode, last_good, artifact_ref
    )
    resolved = resolve_render_source(project, name, last_good=last_good, artifact_ref=artifact_ref)
    shape = load_brep_shape(resolved.brep)

    if channel_lit == "mask" and mask_mode_lit == "selection":
        return _render_selection(
            project, resolved, cast("Any", shape), resolved_views, focus, width, height
        )
    return _render_channel(
        project,
        resolved,
        cast("Any", shape),
        channel_lit,
        section_plane,
        explode,
        focus,
        resolved_views,
        width,
        height,
    )


def scene_tessellation(scene: RenderScene) -> Tessellation:
    """Reuse the scene's per-solid tessellation (avoids a second OCP meshing)."""
    return Tessellation(solids=tuple(solid.tessellation for solid in scene.solids))


def _render_channel(
    project: RenderProject,
    resolved: RenderSource,
    shape: Any,
    channel: Channel,
    section_plane: str | None,
    explode: float,
    focus: str | None,
    views: tuple[str, ...],
    width: int,
    height: int,
) -> InspectResult:
    """rgb / mask-solid / section (+ optional explode/focus) via channels.py."""
    scene = scene_from_shape(shape)
    render_store = RenderStore(project.store)

    if focus is not None:
        images, refs, legend = _render_channel_focused(
            project, resolved, scene, channel, focus, views, width, height
        )
    else:
        # channels.py treats explode as its own shaded channel; map rgb+explode.
        channel_name = "explode" if channel == "rgb" and explode > 0.0 else channel
        options = RenderOptions(
            width=width,
            height=height,
            explode_t=explode if explode > 0.0 else 1.0,
            section=section_plane,
        )
        rendered = render_channel(scene, list(views), channel_name, options)
        images = []
        refs = []
        legend = None
        for view in views:
            channel_view = rendered[view]
            png = channel_view.png()
            artifact = render_store.publish_render(png)
            images.append(
                InspectImage(
                    view=view,
                    channel=channel,
                    render_ref=artifact.ref,
                    png=png,
                    palette_decodable=channel == "mask",
                )
            )
            refs.append(artifact.ref)
            if channel == "mask" and channel_view.legend is not None:
                legend = cast("Mapping[str, JSONValue]", channel_view.legend)

    mask_legend: Mapping[str, JSONValue] | None = None
    mask_legend_ref: str | None = None
    truncated = False
    if channel == "mask" and legend is not None:
        mask_legend, mask_legend_ref, truncated = _publish_legend(
            project.store, legend, force_ref=False
        )

    return InspectResult(
        status="ok",
        source_artifact_ref=resolved.source_artifact_ref,
        channel=channel,
        mask_mode="solid",
        images=tuple(images),
        render_artifact_refs=tuple(refs),
        mask_legend=mask_legend,
        mask_legend_ref=mask_legend_ref,
        mask_legend_truncated=truncated,
    )


def _render_channel_focused(
    project: RenderProject,
    resolved: RenderSource,
    scene: RenderScene,
    channel: Channel,
    focus: str,
    views: tuple[str, ...],
    width: int,
    height: int,
) -> tuple[list[InspectImage], list[str], Mapping[str, JSONValue] | None]:
    """Focused rgb/mask/section: reframe on the focused subset, whole model drawn.

    ``focus`` changes only the camera; the ID namespace / legend are unchanged
    (the solid-ID mask legend is the scene's, keyed by ``solid_index``).
    """
    tess = scene_tessellation(scene)
    labels = build_solid_labels(resolved.result, len(tess.solids))
    placements = tag_placements_from_source_map(resolved.source_map)
    focus_solids = _focus_solids(focus, labels, placements)
    frame_lo, frame_hi = _tess_bounds(tess, focus_solids)
    render_store = RenderStore(project.store)
    shaded_meshes = [
        face_trimesh(face) for solid in tess.solids for face in solid.faces if face.triangles.size
    ]
    mask_items = [
        ColoredMesh(face_trimesh(face), id_to_rgb(solid.solid_index))
        for solid in tess.solids
        for face in solid.faces
        if face.triangles.size
    ]
    legend = scene.legend() if channel == "mask" else None

    images: list[InspectImage] = []
    refs: list[str] = []
    with OffscreenSession(width, height) as session:
        for view in views:
            framing = camera_framing(
                frame_lo, frame_hi, parse_view(view), width=width, height=height
            )
            if channel == "mask":
                array = session.render_flat(mask_items, framing)
                decodable = True
            else:  # rgb / section both fall back to a plain shaded focus preview
                array = session.render_shaded(shaded_meshes, framing)
                decodable = False
            png = encode_png(array)
            artifact = render_store.publish_render(png)
            images.append(
                InspectImage(
                    view=view,
                    channel=channel,
                    render_ref=artifact.ref,
                    png=png,
                    palette_decodable=decodable,
                )
            )
            refs.append(artifact.ref)
    return images, refs, cast("Mapping[str, JSONValue] | None", legend)


def _render_selection(
    project: RenderProject,
    resolved: RenderSource,
    shape: Any,
    views: tuple[str, ...],
    focus: str | None,
    width: int,
    height: int,
) -> InspectResult:
    """mask/selection: per view three ID passes + preview + immutable bundle.

    Uses the shared :func:`~hephaestus.core.render.selection.build_selection_catalog`
    namespace so the bundle's IDs match a GLTF export's embedded raycast IDs.
    """
    scene = scene_from_shape(shape)
    tess = scene_tessellation(scene)
    placements = tag_placements_from_source_map(resolved.source_map)
    labels = build_solid_labels(resolved.result, len(tess.solids))
    catalog: SelectionCatalog = build_selection_catalog(tess, placements=placements, labels=labels)

    focus_solids = _focus_solids(focus, labels, placements) if focus is not None else None
    frame_lo, frame_hi = _tess_bounds(tess, focus_solids)

    render_store = RenderStore(project.store)
    images: list[InspectImage] = []
    refs: list[str] = []
    bundles: list[SelectionBundleView] = []
    table_ref: str | None = None

    with OffscreenSession(width, height) as session:
        for view in views:
            framing = camera_framing(
                frame_lo, frame_hi, parse_view(view), width=width, height=height
            )
            arrays = render_selection_view(session, tess, catalog, framing, include_preview=True)
            preview_png = encode_png(arrays.preview) if arrays.preview is not None else None
            bundle: SelectionBundle = render_store.publish_selection_bundle(
                view=view,
                source_artifact_ref=resolved.source_artifact_ref,
                solid_png=encode_png(arrays.solid),
                face_png=encode_png(arrays.face),
                edge_png=encode_png(arrays.edge),
                entries=catalog.entries,
                preview_png=preview_png,
            )
            table_ref = bundle.selection_table_ref
            preview_ref = bundle.preview_ref
            assert preview_ref is not None  # include_preview=True always yields one
            assert preview_png is not None
            images.append(
                InspectImage(
                    view=view,
                    channel="mask",
                    render_ref=preview_ref,
                    png=preview_png,
                    palette_decodable=False,
                )
            )
            bundles.append(
                SelectionBundleView(
                    view=view, bundle_ref=bundle.bundle_ref, pass_refs=bundle.pass_refs
                )
            )
            refs.extend(
                [preview_ref, bundle.pass_refs.solid, bundle.pass_refs.face, bundle.pass_refs.edge]
            )

    legend = build_legend(catalog.entries)
    mask_legend, mask_legend_ref, truncated = _publish_legend(
        project.store, cast("Mapping[str, JSONValue]", legend), force_ref=True
    )
    return InspectResult(
        status="ok",
        source_artifact_ref=resolved.source_artifact_ref,
        channel="mask",
        mask_mode="selection",
        images=tuple(images),
        render_artifact_refs=tuple(refs),
        mask_legend=mask_legend,
        mask_legend_ref=mask_legend_ref,
        mask_legend_truncated=truncated,
        selection_table_ref=table_ref,
        selection_bundles=tuple(bundles),
    )


# --------------------------------------------------------------------------
# Stage 2 render-bundle preparation (tool-free)


def prepare_render_bundle(
    project: RenderProject,
    name: str,
    *,
    views: Sequence[str] = DEFAULT_VIEWS,
    artifact_ref: str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> dict[str, JSONValue]:
    """Tool-free render bundle for Stage 2 ``query_snapshot`` (no session/tool coupling).

    Renders the ``rgb`` channel for ``views`` of the current build (or an explicit
    immutable ``artifact_ref``) and returns the inline image payloads, their
    published render refs, and the exact resolved ``source_artifact_ref``. The
    ``images`` carry hex-encoded PNG bytes so the caller controls delivery.
    """
    result = inspect_part(
        project,
        name,
        views=views,
        channel="rgb",
        artifact_ref=artifact_ref,
        width=width,
        height=height,
    )
    images: list[JSONValue] = [
        {"view": image.view, "render_artifact_ref": image.render_ref, "png": image.png.hex()}
        for image in result.images
    ]
    return {
        "source_artifact_ref": result.source_artifact_ref,
        "images": images,
        "render_artifact_refs": list(result.render_artifact_refs),
    }
