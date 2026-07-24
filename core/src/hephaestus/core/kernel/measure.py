"""Kernel measurement services: pure functions over built build123d geometry.

Architecture §3.2: ``interference`` (boolean-intersection overlap volume,
with a per-pair breakdown helper), ``clearance`` (minimum separation),
``distance`` (between resolved topology), ``mass`` (volume x density) and
``section`` (section faces on a plane). All functions accept any build123d
``Shape`` (solid, compound, face, edge) unless documented otherwise and
never mutate their inputs.

Semantics fixed here:

- ``interference(a, b)`` is the volume of ``a ∩ b`` in mm³ (0.0 when
  disjoint or when either operand has no volume). Only meaningful for
  shapes with solids.
- ``clearance(a, b)`` is the minimum separation between the shapes: 0.0
  when they touch **or overlap** (including the strict-containment case,
  where raw boundary distance would be misleadingly positive), else the
  minimum boundary distance. Overlap is detected by intersection volume
  when both operands carry solids, else by zero boundary distance.
- ``distance(a, b)`` is the raw minimum distance between the two
  topologies (faces, edges, solids, compounds) — for resolved/tagged
  features; unlike ``clearance`` it performs no overlap correction.
- ``mass(shape, density)`` is ``volume * density`` — unit-agnostic; with
  mm³ volumes and density in g/mm³ the result is grams (the §6
  ``one_cat_static`` convention).
- ``section(shape, plane)`` returns the planar section faces of the
  shape's solids on ``plane`` as a tuple of ``Face``.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations

from build123d import Face, Plane
from build123d import section as _bd_section
from build123d.topology import Shape
from hephaestus.core.kernel.metrics import AnyShape, shape_volume

__all__ = [
    "OVERLAP_EPS_MM3",
    "clearance",
    "distance",
    "interference",
    "interference_pairs",
    "mass",
    "section",
]

#: Overlap volumes at or below this (mm³) count as numerical noise, not
#: interference — used by :func:`clearance` for its overlap test.
OVERLAP_EPS_MM3 = 1e-9


def interference(a: AnyShape, b: AnyShape) -> float:
    """Overlap volume (mm³) of the boolean intersection ``a ∩ b``."""
    common = a.intersect(b)
    if common is None:
        return 0.0
    if isinstance(common, Shape):
        return max(0.0, shape_volume(common))
    # build123d may return a ShapeList of intersection pieces.
    return max(0.0, sum(shape_volume(piece) for piece in common))


def interference_pairs(shapes: Mapping[str, AnyShape]) -> dict[tuple[str, str], float]:
    """Per-pair interference breakdown over a named shape set.

    Returns every unordered pair exactly once as ``(name_a, name_b) ->
    overlap volume`` with each key tuple sorted lexically and keys emitted
    in deterministic sorted order (zero-overlap pairs included, so callers
    can distinguish "measured clear" from "not measured").
    """
    out: dict[tuple[str, str], float] = {}
    for name_a, name_b in combinations(sorted(shapes), 2):
        out[(name_a, name_b)] = interference(shapes[name_a], shapes[name_b])
    return out


def distance(a: AnyShape, b: AnyShape) -> float:
    """Raw minimum distance (mm) between two topologies (no overlap check)."""
    return float(a.distance_to(b))


def clearance(a: AnyShape, b: AnyShape) -> float:
    """Minimum separation (mm): 0.0 when touching or overlapping.

    When both operands contain solids, overlap is decided by intersection
    volume (catching strict containment, where boundary distance is
    positive); otherwise a zero boundary distance is the touch test.
    """
    if a.solids() and b.solids() and interference(a, b) > OVERLAP_EPS_MM3:
        return 0.0
    return max(0.0, distance(a, b))


def mass(shape: AnyShape, density: float) -> float:
    """Mass = volume x density (grams when density is g/mm³)."""
    return shape_volume(shape) * density


def section(shape: AnyShape, plane: Plane) -> tuple[Face, ...]:
    """Section faces of the shape's solids on ``plane`` (empty when disjoint).

    Only solids are sectioned; a shape without solids yields ``()``.
    """
    if not shape.solids():
        return ()
    sketch = _bd_section(shape, section_by=plane)  # type: ignore[arg-type]
    return tuple(sketch.faces())
