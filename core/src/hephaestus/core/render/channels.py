"""The four render channels over the foundation renderer (arch §3.3).

Each channel turns a built build123d shape into per-view images (and, for
``mask``, a palette legend), reusing the foundation primitives:
:mod:`~hephaestus.core.render.tessellate` (topology-preserving triangles/edges,
indexed exactly like the executor tags and kernel metrics),
:mod:`~hephaestus.core.render.cameras` (named/az-el framing) and
:mod:`~hephaestus.core.render.offscreen` (software-EGL, byte-deterministic).

Channels
--------
- ``rgb`` — shaded render honouring each solid's ``.color`` (script contract
  §5.1) under a fixed lighting rig. Deterministic; ``legend`` is ``None``.
- ``mask`` — one flat, unlit, non-antialiased **solid-ID** pass. Every solid is
  painted its palette colour and the returned ``legend`` maps every colour to a
  ``{kind: "solid", solid_index, topology_index, label?}`` descriptor. Decoding
  any pixel with :func:`~hephaestus.core.render.palette.rgb_to_id` and looking
  it up in the legend is exact (the gate's *mask decode == legend* criterion).
- ``section`` — a shaded render of the assembly **cut** by a named plane. Each
  solid is intersected with the kept half-space, the kernel's section faces are
  overlaid as a distinct cut-cap colour, so the image is always distinguishable
  from ``rgb``. The plane grammar is documented on :func:`parse_section_plane`.
- ``explode`` — a shaded render of the assembly with every solid pushed
  radially outward from the assembly centroid by ``(solid_centroid -
  assembly_centroid) · t · EXPLODE_SCALE``. ``t = 0`` is the identity; because
  the camera is framed once to the fully-exploded (``t = 1``) extent, the
  projected scale is constant across ``t`` and separating overlapping solids can
  only *grow* the silhouette — so :func:`explode_silhouette` (a flat solid mask,
  nonzero-pixel count) is structurally non-decreasing and strictly increases
  whenever solids overlap at ``t = 0`` (the G1 explode gate).

Determinism
-----------
All passes go through the software (llvmpipe) EGL device; the same build + view +
channel yields byte-identical framebuffers, and :func:`encode_png` writes PNGs
with no timestamp/metadata so byte goldens hold across processes.
"""

# trimesh / pyrender / build123d / OCP ship no type stubs; the reportUnknown*
# relaxations for this package are declared in root pyproject
# executionEnvironments (see interface notes), matching offscreen.py/tessellate.py.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import io
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import numpy as np
from hephaestus.core.errors import ValidationError
from hephaestus.core.render.cameras import (
    DEFAULT_MARGIN,
    CameraFraming,
    ViewSpec,
    camera_framing,
    parse_view,
)
from hephaestus.core.render.offscreen import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ColoredMesh,
    OffscreenSession,
)
from hephaestus.core.render.palette import SelectionEntry, build_legend, id_to_rgb
from hephaestus.core.render.tessellate import SolidTessellation, tessellate
from numpy.typing import NDArray
from opstore.types import JSONValue

__all__ = [
    "CHANNELS",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "EXPLODE_SCALE",
    "RGB_BACKGROUND",
    "SECTION_CUT_RGBA",
    "Channel",
    "ChannelView",
    "RenderOptions",
    "RenderScene",
    "RenderSolid",
    "SectionPlane",
    "encode_png",
    "explode_silhouette",
    "parse_section_plane",
    "render_channel",
    "scene_from_shape",
]

Channel = Literal["rgb", "mask", "section", "explode"]

#: The four render channels, in canonical order.
CHANNELS: tuple[Channel, ...] = ("rgb", "mask", "section", "explode")

#: Neutral material applied to a solid whose script sets no ``.color`` (§5.1).
DEFAULT_SOLID_RGBA: tuple[int, int, int, int] = (176, 176, 176, 255)

#: Distinct flat colour for the section cut cap (kernel section faces), chosen so
#: a ``section`` render is never mistaken for an ``rgb`` render.
SECTION_CUT_RGBA: tuple[int, int, int, int] = (220, 60, 60, 255)

#: White background for shaded channels (rgb/section/explode).
RGB_BACKGROUND: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)

#: Explode displacement multiplier (per unit ``t``): a solid whose centroid sits
#: at distance ``d`` from the assembly centroid moves ``d · EXPLODE_SCALE`` at
#: ``t = 1``. Geometry-derived and deterministic; part of the golden contract.
EXPLODE_SCALE = 1.0

_RGBA = tuple[int, int, int, int]


# --------------------------------------------------------------------------- #
# Scene model                                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, eq=False)
class RenderSolid:
    """One selectable solid: its global index, label/colour, and tessellation.

    ``solid_index`` is the position in ``shape.solids()`` — the same index the
    executor tag placements and kernel metrics use. ``color`` is the resolved
    RGBA (the script ``.color`` when set, else :data:`DEFAULT_SOLID_RGBA`);
    ``color_explicit`` records whether the script set it.
    """

    solid_index: int
    label: str | None
    color: _RGBA
    color_explicit: bool
    tessellation: SolidTessellation

    def centroid(self) -> NDArray[np.float64]:
        """Bounding-box centre of this solid (deterministic, tessellation-stable)."""
        lo, hi = _solid_bounds(self.tessellation)
        return (lo + hi) / 2.0


@dataclass(frozen=True, eq=False)
class RenderScene:
    """A built assembly ready to render: per-solid geometry + the source shape.

    ``shape`` is retained because the ``section`` channel cuts it with a boolean
    and reads the kernel's planar section faces. ``bbox_min``/``bbox_max`` are the
    tessellated bounds (the framing target for rgb/mask/section).
    """

    solids: tuple[RenderSolid, ...]
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    shape: Any

    def centroid(self) -> NDArray[np.float64]:
        """Assembly centroid = bounding-box centre (deterministic)."""
        lo = np.array(self.bbox_min, dtype=np.float64)
        hi = np.array(self.bbox_max, dtype=np.float64)
        return (lo + hi) / 2.0

    def solid_selection_entries(self) -> dict[int, SelectionEntry]:
        """The ``{selection_id: SelectionEntry}`` for the solid-ID namespace.

        One entry per solid, keyed by ``solid_index`` (so the mask palette colour
        of solid ``s`` is ``id_to_rgb(s)``). ``kind`` is ``"solid"`` and
        ``topology_index`` repeats the solid index (a solid *is* its own topology
        occurrence), matching :mod:`hephaestus.core.render.palette`.
        """
        return {
            solid.solid_index: SelectionEntry(
                kind="solid",
                solid_index=solid.solid_index,
                topology_index=solid.solid_index,
                tag=None,
                label=solid.label,
            )
            for solid in self.solids
        }

    def legend(self) -> dict[str, dict[str, JSONValue]]:
        """The mask legend ``{colour_hex: descriptor}`` over every solid."""
        return build_legend(self.solid_selection_entries())


def _iter_nodes(shape: Any) -> list[Any]:
    """Every node of the geometry tree, pre-order (root included)."""
    out: list[Any] = []

    def walk(node: Any) -> None:
        out.append(node)
        for child in getattr(node, "children", ()) or ():
            walk(child)

    walk(shape)
    return out


def _is_same(a: Any, b: Any) -> bool:
    wa = getattr(a, "wrapped", None)
    wb = getattr(b, "wrapped", None)
    if wa is None or wb is None:
        return False
    return bool(wa.IsSame(wb))


def _color_to_rgba(color: Any) -> _RGBA:
    """Convert a build123d ``Color`` to an 8-bit RGBA tuple."""
    channels = [float(c) for c in tuple(color)]
    while len(channels) < 4:
        channels.append(1.0)
    r, g, b, a = channels[:4]
    return (
        max(0, min(255, round(r * 255))),
        max(0, min(255, round(g * 255))),
        max(0, min(255, round(b * 255))),
        max(0, min(255, round(a * 255))),
    )


def _attribute_solids(shape: Any) -> list[tuple[str | None, _RGBA, bool]]:
    """For each global solid, its ``(label, rgba, color_explicit)``.

    The label comes from the most specific (fewest-solids) *labelled* ancestor
    node; the colour from the most specific node that sets ``.color``. Solids
    enumerate in ``shape.solids()`` order — identical to the tessellation, tag
    placement, and metrics indexing.
    """
    solids = list(shape.solids())
    nodes = _iter_nodes(shape)
    node_solids: list[tuple[Any, list[Any], int]] = []
    for node in nodes:
        try:
            ns = list(node.solids())
        except Exception:  # pragma: no cover - defensive on odd nodes
            ns = []
        node_solids.append((node, ns, len(ns)))

    out: list[tuple[str | None, _RGBA, bool]] = []
    for solid in solids:
        label: str | None = None
        label_span = math.inf
        color: _RGBA = DEFAULT_SOLID_RGBA
        color_explicit = False
        color_span = math.inf
        for node, ns, span in node_solids:
            if span == 0 or not any(_is_same(solid, s) for s in ns):
                continue
            node_label = getattr(node, "label", "") or ""
            if node_label and span < label_span:
                label = node_label
                label_span = span
            node_color = getattr(node, "color", None)
            if node_color is not None and span < color_span:
                color = _color_to_rgba(node_color)
                color_explicit = True
                color_span = span
        out.append((label, color, color_explicit))
    return out


def scene_from_shape(shape: Any) -> RenderScene:
    """Build a :class:`RenderScene` from a built build123d shape/compound.

    Tessellates the shape once (fixed deflection constants) and attributes each
    solid its label and ``.color``. Accepts the part's final geometry compound;
    the returned scene drives every channel.
    """
    tess = tessellate(shape)
    attribution = _attribute_solids(shape)
    solids: list[RenderSolid] = []
    for solid_tess, (label, color, explicit) in zip(tess.solids, attribution, strict=True):
        solids.append(
            RenderSolid(
                solid_index=solid_tess.solid_index,
                label=label,
                color=color,
                color_explicit=explicit,
                tessellation=solid_tess,
            )
        )
    lo, hi = tess.bounds()
    return RenderScene(solids=tuple(solids), bbox_min=lo, bbox_max=hi, shape=shape)


def _coerce_scene(geometry: RenderScene | Any) -> RenderScene:
    return geometry if isinstance(geometry, RenderScene) else scene_from_shape(geometry)


# --------------------------------------------------------------------------- #
# Trimesh construction                                                         #
# --------------------------------------------------------------------------- #


def _solid_bounds(
    solid: SolidTessellation,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    mins: list[NDArray[np.float64]] = []
    maxs: list[NDArray[np.float64]] = []
    for face in solid.faces:
        if face.vertices.size:
            mins.append(face.vertices.min(axis=0))
            maxs.append(face.vertices.max(axis=0))
    if not mins:
        zero = np.zeros(3, dtype=np.float64)
        return zero, zero
    return np.min(np.vstack(mins), axis=0), np.max(np.vstack(maxs), axis=0)


def _solid_vertices_triangles(
    solid: SolidTessellation,
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Concatenate a solid's face groups into one ``(V, T)`` mesh."""
    verts: list[NDArray[np.float64]] = []
    tris: list[NDArray[np.int64]] = []
    offset = 0
    for face in solid.faces:
        if face.vertices.size == 0:
            continue
        verts.append(face.vertices)
        tris.append(face.triangles + offset)
        offset += face.vertices.shape[0]
    if not verts:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int64)
    return np.vstack(verts), np.vstack(tris)


def _trimesh(
    vertices: NDArray[np.float64],
    triangles: NDArray[np.int64],
    color: _RGBA | None,
) -> Any:
    import trimesh

    mesh: Any = trimesh.Trimesh(vertices=vertices, faces=triangles, process=False)
    if color is not None and vertices.shape[0]:
        mesh.visual.vertex_colors = np.tile(np.array(color, dtype=np.uint8), (vertices.shape[0], 1))
    return mesh


def _solid_trimesh(
    solid: SolidTessellation,
    color: _RGBA | None,
    offset: NDArray[np.float64] | None = None,
) -> Any:
    vertices, triangles = _solid_vertices_triangles(solid)
    if offset is not None and vertices.shape[0]:
        vertices = vertices + offset
    return _trimesh(vertices, triangles, color)


def _face_trimesh_from_ocp(face: Any, color: _RGBA, nudge: NDArray[np.float64]) -> Any | None:
    """Triangulate a single build123d ``Face`` into a double-sided coloured mesh.

    Standalone faces (the kernel's planar section) are meshed on demand; the
    section-cap winding is unknown, so both windings are emitted (double-sided)
    and the vertices are nudged toward the camera so the cap wins the depth test
    over the coplanar cut face.
    """
    from OCP.BRep import BRep_Tool  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepMesh import BRepMesh_IncrementalMesh  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopLoc import TopLoc_Location  # pyright: ignore[reportAttributeAccessIssue]

    BRepMesh_IncrementalMesh(face.wrapped, 0.1, False, 0.5, True)
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face.wrapped, location)
    if triangulation is None:
        return None
    transform = location.Transformation()
    node_count = triangulation.NbNodes()
    if node_count == 0:
        return None
    vertices = np.empty((node_count, 3), dtype=np.float64)
    for i in range(1, node_count + 1):
        point = triangulation.Node(i).Transformed(transform)
        vertices[i - 1] = (point.X(), point.Y(), point.Z())
    triangle_count = triangulation.NbTriangles()
    if triangle_count == 0:
        return None
    forward = np.empty((triangle_count, 3), dtype=np.int64)
    for i in range(1, triangle_count + 1):
        a, b, c = triangulation.Triangle(i).Get()
        forward[i - 1] = (a - 1, b - 1, c - 1)
    triangles = np.vstack([forward, forward[:, ::-1]])
    return _trimesh(vertices + nudge, triangles, color)


# --------------------------------------------------------------------------- #
# Section plane grammar                                                        #
# --------------------------------------------------------------------------- #

_SECTION_RE = re.compile(r"\A(?P<sign>[+-]?)(?P<axis>[XYZxyz])@(?P<offset>.+)\Z")
_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


@dataclass(frozen=True)
class SectionPlane:
    """A resolved cutting plane: an axis-aligned normal, sign, and offset (mm).

    ``axis`` is 0/1/2 for X/Y/Z; ``sign`` is +1/-1. Material on the ``sign`` side
    of the plane (``sign · (coord - offset) > 0``) is removed, exposing the
    cross-section; the retained half is the opposite side.
    """

    axis: int
    sign: int
    offset: float
    spec: str

    def normal(self) -> NDArray[np.float64]:
        vec = np.zeros(3, dtype=np.float64)
        vec[self.axis] = float(self.sign)
        return vec

    def bd_plane(self) -> Any:
        from build123d import Plane

        origin = [0.0, 0.0, 0.0]
        origin[self.axis] = self.offset
        z_dir = [0.0, 0.0, 0.0]
        z_dir[self.axis] = float(self.sign)
        return Plane(origin=tuple(origin), z_dir=tuple(z_dir))

    def keep_box(self, bbox_min: tuple[float, ...], bbox_max: tuple[float, ...]) -> Any:
        """A large box covering the retained half-space (the ``-sign`` side)."""
        from build123d import Box, Pos

        span = max(float(hi - lo) for lo, hi in zip(bbox_min, bbox_max, strict=True))
        big = span * 8.0 + 100.0
        centre = [0.0, 0.0, 0.0]
        for i in range(3):
            centre[i] = (bbox_min[i] + bbox_max[i]) / 2.0
        # Kept side is opposite the normal: shift the box off the plane so its
        # near face lands exactly on the plane offset.
        centre[self.axis] = self.offset - self.sign * (big / 2.0)
        return Pos(*centre) * Box(big, big, big)


def parse_section_plane(
    spec: str | None,
    bbox_min: tuple[float, float, float],
    bbox_max: tuple[float, float, float],
) -> SectionPlane:
    """Parse a section-plane spec against the assembly bounds.

    Grammar — ``[±]AXIS@OFFSET``:

    - ``AXIS`` is ``X``/``Y``/``Z`` (case-insensitive): the plane's normal axis.
    - leading ``+`` (default) / ``-`` chooses which half is *removed*: ``+Z@…``
      cuts away the ``+Z`` half and shows the top-down cross-section; ``-Z@…``
      cuts away the ``-Z`` half.
    - ``OFFSET`` is the plane position along the axis in mm, either a number
      (e.g. ``+Z@30``) or one of ``c`` / ``center`` / ``mid`` / ``h`` for the
      bounding-box midpoint along that axis (e.g. ``+Z@c``, the default plane).

    ``None`` resolves to the default ``+Z@c``.
    """
    if spec is None:
        spec = "+Z@c"
    match = _SECTION_RE.match(spec.strip())
    if match is None:
        raise ValidationError(
            f"unknown section plane {spec!r}; grammar is '[+-]AXIS@OFFSET' where AXIS is "
            f"X/Y/Z and OFFSET is a number or a centre keyword (c/center/mid/h), "
            f"e.g. '+Z@c', '+Z@30', '-X@0'",
            kind="contract",
        )
    axis = _AXIS_INDEX[match.group("axis").upper()]
    sign = -1 if match.group("sign") == "-" else 1
    offset_raw = match.group("offset").strip().lower()
    if offset_raw in ("c", "center", "centre", "mid", "h"):
        offset = (bbox_min[axis] + bbox_max[axis]) / 2.0
    else:
        try:
            offset = float(offset_raw)
        except ValueError as exc:
            raise ValidationError(
                f"section plane {spec!r}: offset {match.group('offset')!r} is not a number "
                f"or a centre keyword (c/center/mid/h)",
                kind="contract",
            ) from exc
    return SectionPlane(axis=axis, sign=sign, offset=offset, spec=spec)


# --------------------------------------------------------------------------- #
# Options + view result                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RenderOptions:
    """Per-call render options (all channels share width/height/margin)."""

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    margin: float = DEFAULT_MARGIN
    #: ``explode`` channel displacement fraction (``t`` in ``[0, 1]``).
    explode_t: float = 1.0
    #: ``section`` channel plane spec (see :func:`parse_section_plane`); ``None``
    #: resolves to the default ``+Z@c``.
    section: str | None = None


@dataclass(frozen=True, eq=False)
class ChannelView:
    """One rendered channel for one view: the RGBA image and optional legend."""

    channel: str
    view: str
    rgba: NDArray[np.uint8]
    legend: dict[str, dict[str, JSONValue]] | None = field(default=None)

    def png(self) -> bytes:
        """Deterministic PNG bytes of :attr:`rgba` (no timestamp/metadata)."""
        return encode_png(self.rgba)


def encode_png(image: NDArray[np.uint8]) -> bytes:
    """Encode an ``(H, W, 3|4)`` uint8 array as deterministic PNG bytes.

    Uses a fixed Pillow encoder with no ancillary time/text chunks, so the same
    framebuffer yields byte-identical PNGs across processes (the golden/two-run
    determinism contract; raw framebuffer determinism is proven in offscreen.py).
    """
    from PIL import Image

    array = np.ascontiguousarray(image, dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValidationError(
            f"encode_png expects (H, W, 3|4) uint8, got shape {array.shape}", kind="contract"
        )
    mode = "RGBA" if array.shape[2] == 4 else "RGB"
    buffer = io.BytesIO()
    Image.fromarray(array, mode=mode).save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def _to_rgba(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Ensure an ``(H, W, 4)`` uint8 image (opaque alpha for 3-channel input)."""
    if image.shape[2] == 4:
        return np.ascontiguousarray(image, dtype=np.uint8)
    height, width = image.shape[:2]
    alpha = np.full((height, width, 1), 255, dtype=np.uint8)
    return np.ascontiguousarray(np.concatenate([image, alpha], axis=2), dtype=np.uint8)


# --------------------------------------------------------------------------- #
# Explode transform                                                            #
# --------------------------------------------------------------------------- #


def _explode_offset(scene: RenderScene, solid: RenderSolid, t: float) -> NDArray[np.float64]:
    """Outward displacement of ``solid`` at explode parameter ``t`` (never inward)."""
    if t <= 0.0:
        return np.zeros(3, dtype=np.float64)
    return (solid.centroid() - scene.centroid()) * (t * EXPLODE_SCALE)


def _exploded_bounds(
    scene: RenderScene, t: float
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Axis-aligned bounds of the assembly exploded at ``t`` (framing target)."""
    mins: list[NDArray[np.float64]] = []
    maxs: list[NDArray[np.float64]] = []
    for solid in scene.solids:
        lo, hi = _solid_bounds(solid.tessellation)
        offset = _explode_offset(scene, solid, t)
        mins.append(lo + offset)
        maxs.append(hi + offset)
    if not mins:
        return scene.bbox_min, scene.bbox_max
    lo = np.min(np.vstack(mins), axis=0)
    hi = np.max(np.vstack(maxs), axis=0)
    return (
        (float(lo[0]), float(lo[1]), float(lo[2])),
        (float(hi[0]), float(hi[1]), float(hi[2])),
    )


# --------------------------------------------------------------------------- #
# Per-channel renderers                                                        #
# --------------------------------------------------------------------------- #


def _framing(
    scene: RenderScene, view: ViewSpec, opts: RenderOptions, channel: Channel
) -> CameraFraming:
    if channel == "explode":
        # Frame ONCE to the fully-exploded extent so the projected scale is
        # constant across t and the silhouette can only grow as solids separate.
        lo, hi = _exploded_bounds(scene, 1.0)
    else:
        lo, hi = scene.bbox_min, scene.bbox_max
    return camera_framing(lo, hi, view, width=opts.width, height=opts.height, margin=opts.margin)


def _render_rgb(
    session: OffscreenSession, scene: RenderScene, framing: CameraFraming
) -> NDArray[np.uint8]:
    meshes = [_solid_trimesh(s.tessellation, s.color) for s in scene.solids]
    return _to_rgba(session.render_shaded(meshes, framing, background=RGB_BACKGROUND))


def _render_mask(
    session: OffscreenSession, scene: RenderScene, framing: CameraFraming
) -> NDArray[np.uint8]:
    items = [
        ColoredMesh(_solid_trimesh(s.tessellation, None), id_to_rgb(s.solid_index))
        for s in scene.solids
    ]
    return _to_rgba(session.render_flat(items, framing))


def _render_explode(
    session: OffscreenSession, scene: RenderScene, framing: CameraFraming, t: float
) -> NDArray[np.uint8]:
    meshes = [
        _solid_trimesh(s.tessellation, s.color, offset=_explode_offset(scene, s, t))
        for s in scene.solids
    ]
    return _to_rgba(session.render_shaded(meshes, framing, background=RGB_BACKGROUND))


def _render_section(
    session: OffscreenSession,
    scene: RenderScene,
    framing: CameraFraming,
    view: ViewSpec,
    plane: SectionPlane,
) -> NDArray[np.uint8]:
    from hephaestus.core.kernel.measure import section as kernel_section

    keep = plane.keep_box(scene.bbox_min, scene.bbox_max)
    meshes: list[Any] = []
    for solid in scene.solids:
        source = scene.shape.solids()[solid.solid_index]
        cut = source & keep
        if cut is None or not cut.solids():
            continue
        cut_tess = tessellate(cut)
        for cut_solid in cut_tess.solids:
            meshes.append(_solid_trimesh(cut_solid, solid.color))

    # Cap the cut with the kernel's planar section faces in a distinct colour,
    # nudged toward the camera so they win the depth test over the coplanar cut.
    diagonal = float(np.linalg.norm(np.array(scene.bbox_max) - np.array(scene.bbox_min)))
    nudge = view.eye_direction() * max(diagonal * 1e-3, 1e-3)
    for face in kernel_section(scene.shape, plane.bd_plane()):
        cap = _face_trimesh_from_ocp(face, SECTION_CUT_RGBA, nudge)
        if cap is not None:
            meshes.append(cap)
    return _to_rgba(session.render_shaded(meshes, framing, background=RGB_BACKGROUND))


def render_channel(
    geometry: RenderScene | Any,
    view_names: Sequence[str],
    channel: Channel,
    options: RenderOptions | None = None,
) -> dict[str, ChannelView]:
    """Render ``channel`` for every view over one built shape / :class:`RenderScene`.

    ``geometry`` is a :class:`RenderScene` (built via :func:`scene_from_shape`) or
    a raw built build123d shape (coerced). ``view_names`` are camera names or the
    ``az{A}_el{E}`` grammar (:func:`~hephaestus.core.render.cameras.parse_view`).
    Returns ``{view_name: ChannelView}``; only ``mask`` populates ``legend``.
    """
    if channel not in CHANNELS:
        raise ValidationError(
            f"unknown channel {channel!r}; valid channels: {', '.join(CHANNELS)}",
            kind="contract",
        )
    if not view_names:
        raise ValidationError("render_channel requires at least one view", kind="contract")
    scene = _coerce_scene(geometry)
    opts = options or RenderOptions()
    views = [parse_view(name) for name in view_names]

    plane: SectionPlane | None = None
    if channel == "section":
        plane = parse_section_plane(opts.section, scene.bbox_min, scene.bbox_max)

    legend = scene.legend() if channel == "mask" else None
    results: dict[str, ChannelView] = {}
    with OffscreenSession(opts.width, opts.height) as session:
        for name, view in zip(view_names, views, strict=True):
            framing = _framing(scene, view, opts, channel)
            if channel == "rgb":
                rgba = _render_rgb(session, scene, framing)
            elif channel == "mask":
                rgba = _render_mask(session, scene, framing)
            elif channel == "explode":
                rgba = _render_explode(session, scene, framing, opts.explode_t)
            else:  # section
                rgba = _render_section(session, scene, framing, view, cast("SectionPlane", plane))
            results[name] = ChannelView(
                channel=channel,
                view=name,
                rgba=rgba,
                legend=dict(legend) if legend is not None else None,
            )
    return results


def explode_silhouette(
    geometry: RenderScene | Any,
    view_name: str,
    *,
    t: float,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    margin: float = DEFAULT_MARGIN,
) -> int:
    """Silhouette area of the exploded assembly: nonzero-pixel count of a solid mask.

    Renders a flat (unlit, non-antialiased) solid-ID mask of the assembly exploded
    at ``t``, framed to the fully-exploded (``t = 1``) extent, and counts pixels
    that are not the background. Because the framing is fixed across ``t``, this
    is non-decreasing in ``t`` and strictly increases whenever solids overlap at
    ``t = 0`` — the structural basis of the G1 explode gate.
    """
    scene = _coerce_scene(geometry)
    view = parse_view(view_name)
    lo, hi = _exploded_bounds(scene, 1.0)
    framing = camera_framing(lo, hi, view, width=width, height=height, margin=margin)
    items = [
        ColoredMesh(
            _solid_trimesh(s.tessellation, None, offset=_explode_offset(scene, s, t)),
            id_to_rgb(s.solid_index),
        )
        for s in scene.solids
    ]
    with OffscreenSession(width, height) as session:
        mask = session.render_flat(items, framing)
    return int(np.count_nonzero(np.any(mask > 0, axis=2)))
