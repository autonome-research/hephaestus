"""Named standard cameras + the ``az{A}_el{E}`` grammar (arch §3.3).

A view is an azimuth/elevation pair fixing the direction from the geometry's
centre toward the camera eye. Framing is orthographic-style: the camera looks
along its own ``-Z`` at the bounding-box centre from far enough that the whole
box is in front of it, and the orthographic half-extents (``xmag``/``ymag``)
are fitted to the box's silhouette plus a fixed margin, respecting the output
aspect ratio so nothing is stretched.

All pose maths is pure, deterministic, and free of wall-clock/random input:
the same bbox + view + viewport give byte-identical camera parameters, which is
part of the render determinism contract. An unknown view name raises an error
listing the valid names and the grammar.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
from hephaestus.core.errors import ValidationError
from numpy.typing import NDArray

__all__ = [
    "DEFAULT_MARGIN",
    "STANDARD_VIEWS",
    "CameraFraming",
    "ViewSpec",
    "camera_framing",
    "parse_view",
    "standard_view_names",
]

#: Fixed framing margin: the fitted half-extents are grown by this fraction so
#: the silhouette never touches the image border. Part of the determinism /
#: golden contract — changing it invalidates goldens.
DEFAULT_MARGIN = 0.05

#: Classic isometric elevation ``atan(1/sqrt(2))`` in degrees (~35.264°).
_ISO_ELEVATION = math.degrees(math.atan(1.0 / math.sqrt(2.0)))

#: Named standard views: name -> (azimuth°, elevation°). Azimuth rotates about
#: +Z from +X toward +Y; elevation lifts from the XY plane toward +Z. The eye
#: sits on the +side named by the axis views (``+X`` looks back along -X, etc.).
STANDARD_VIEWS: dict[str, tuple[float, float]] = {
    "iso": (45.0, _ISO_ELEVATION),
    "+X": (0.0, 0.0),
    "-X": (180.0, 0.0),
    "+Y": (90.0, 0.0),
    "-Y": (270.0, 0.0),
    "+Z": (0.0, 90.0),
    "-Z": (0.0, -90.0),
    "front": (270.0, 0.0),
}

_GRAMMAR_RE = re.compile(r"\Aaz(?P<az>-?\d+(?:\.\d+)?)_el(?P<el>-?\d+(?:\.\d+)?)\Z")


@dataclass(frozen=True)
class ViewSpec:
    """A resolved view: azimuth/elevation in degrees plus its canonical name."""

    name: str
    azimuth_deg: float
    elevation_deg: float

    def eye_direction(self) -> NDArray[np.float64]:
        """Unit vector from the geometry centre toward the camera eye."""
        az = math.radians(self.azimuth_deg)
        el = math.radians(self.elevation_deg)
        cos_el = math.cos(el)
        return np.array(
            [cos_el * math.cos(az), cos_el * math.sin(az), math.sin(el)],
            dtype=np.float64,
        )


def standard_view_names() -> tuple[str, ...]:
    """The named standard views, in declaration order."""
    return tuple(STANDARD_VIEWS)


def parse_view(name: str) -> ViewSpec:
    """Resolve a view name or ``az{A}_el{E}`` string to a :class:`ViewSpec`.

    Raises ``validation_error`` listing the valid names and the grammar when
    ``name`` matches neither a standard view nor the azimuth/elevation grammar.
    """
    if name in STANDARD_VIEWS:
        az, el = STANDARD_VIEWS[name]
        return ViewSpec(name=name, azimuth_deg=az, elevation_deg=el)
    match = _GRAMMAR_RE.match(name)
    if match is not None:
        az = float(match.group("az"))
        el = float(match.group("el"))
        if not (-90.0 <= el <= 90.0):
            raise ValidationError(
                f"view {name!r}: elevation {el} out of range [-90, 90]", kind="contract"
            )
        return ViewSpec(name=name, azimuth_deg=az, elevation_deg=el)
    valid = ", ".join(STANDARD_VIEWS)
    raise ValidationError(
        f"unknown view {name!r}; valid names: {valid}; or the grammar 'az<deg>_el<deg>' "
        f"(e.g. 'az45_el30')",
        kind="contract",
    )


@dataclass(frozen=True)
class CameraFraming:
    """Orthographic camera parameters fitting one bbox for one view.

    ``pose`` is the 4x4 camera-to-world matrix (pyrender convention: the camera
    looks down its local ``-Z``). ``xmag``/``ymag`` are the orthographic
    half-extents. ``znear``/``zfar`` bracket the box along the view axis.
    """

    pose: NDArray[np.float64]
    xmag: float
    ymag: float
    znear: float
    zfar: float


def _look_at_pose(
    eye: NDArray[np.float64],
    target: NDArray[np.float64],
    up_hint: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Camera-to-world pose whose local -Z points from ``eye`` to ``target``."""
    forward_z = eye - target  # camera +Z points from target back toward the eye
    forward_z = forward_z / np.linalg.norm(forward_z)
    right_x = np.cross(up_hint, forward_z)
    right_x = right_x / np.linalg.norm(right_x)
    up_y = np.cross(forward_z, right_x)
    pose = np.eye(4, dtype=np.float64)
    pose[:3, 0] = right_x
    pose[:3, 1] = up_y
    pose[:3, 2] = forward_z
    pose[:3, 3] = eye
    return pose


def camera_framing(
    bbox_min: tuple[float, float, float],
    bbox_max: tuple[float, float, float],
    view: ViewSpec,
    *,
    width: int,
    height: int,
    margin: float = DEFAULT_MARGIN,
) -> CameraFraming:
    """Fit an orthographic camera to ``[bbox_min, bbox_max]`` for ``view``.

    The half-extents are the projected silhouette radius (grown by ``margin``)
    fitted to the ``width:height`` aspect so the image is never stretched. A
    degenerate (zero-size) box is given a unit fallback extent so framing is
    always well defined and deterministic.
    """
    if width <= 0 or height <= 0:
        raise ValidationError("viewport dimensions must be positive", kind="contract")
    lo = np.array(bbox_min, dtype=np.float64)
    hi = np.array(bbox_max, dtype=np.float64)
    centre = (lo + hi) / 2.0
    corners = np.array(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])],
        dtype=np.float64,
    )

    direction = view.eye_direction()
    # Choose a stable up hint: world +Z, except top/bottom views where the view
    # axis is (anti)parallel to +Z, then use +Y.
    if abs(float(direction[2])) > 0.999:
        up_hint = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    else:
        up_hint = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    diagonal = float(np.linalg.norm(hi - lo))
    distance = diagonal + 1.0  # any distance clearing the box works for ortho
    eye = centre + direction * distance
    pose = _look_at_pose(eye, centre, up_hint)

    right_x = pose[:3, 0]
    up_y = pose[:3, 1]
    forward_z = pose[:3, 2]

    rel = corners - centre
    half_u = float(np.max(np.abs(rel @ right_x)))
    half_v = float(np.max(np.abs(rel @ up_y)))
    half_w = float(np.max(np.abs(rel @ forward_z)))
    if half_u <= 0.0:
        half_u = 1.0
    if half_v <= 0.0:
        half_v = 1.0

    aspect = width / height
    # Grow one axis so xmag/ymag matches the viewport aspect (no stretch), then
    # apply the margin.
    xmag = max(half_u, half_v * aspect)
    ymag = xmag / aspect
    xmag *= 1.0 + margin
    ymag *= 1.0 + margin

    znear = max(distance - half_w - 1.0, 0.001)
    zfar = distance + half_w + 1.0
    return CameraFraming(pose=pose, xmag=xmag, ymag=ymag, znear=znear, zfar=zfar)
