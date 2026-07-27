"""Kerf compensation: the path a beam of finite width must actually follow.

A cutter removes material as it travels. Drive it along the nominal boundary and
it takes **half a kerf off the part on every edge**: a 40 mm finger comes out
39.8 mm on a 0.2 mm kerf, a slot cut to nominal is 0.2 mm wide of its drawing,
and a finger joint dimensioned from the model does not assemble. The fix is a
century old and entirely mechanical — offset every closed contour onto the
*waste* side by half the kerf, so the beam's near edge rides the nominal line
and the finished piece lands on size.

"Waste side" is the whole of it, and it is not the same direction everywhere:

* the **outer boundary** offsets **outward** (waste is outside the part), and
* every **hole** offsets **inward** (waste is inside the hole), so the finished
  opening lands on its nominal diameter rather than a kerf oversize.

:func:`kerf_compensated_shape` does that on the geometry rather than on a
polyline the exporter happened to discretise: each solid's flat pattern is its
largest planar face, its boundaries are offset in that face's own plane with the
kernel's 2D offset (OCC ``BRepOffsetAPI``, reached through build123d's
``Wire.offset_2d``), and the compensated face is re-extruded to the solid's
thickness. Everything downstream — profile extraction, nesting, the DXF/SVG
writers, the as-built projection — then sees the compensated path without
knowing anything about kerf.

Two refusals rather than a quiet wrong answer, both :class:`KerfRefusal`:

* ``kerf_offset_failed`` — the kernel could not offset a boundary cleanly, or
  the offset collapsed it (a hole narrower than the kerf has no compensated path
  at all). The refusal names the profile and the ring. Emitting an
  uncompensated path here would ship a part that measures wrong with nothing in
  the file to say so.
* ``not_a_sheet_profile`` / ``no_profiles`` — there is no flat pattern to
  compensate. A cut layout refuses; the as-built projection of a part that was
  never a sheet may fall back, and says so with a
  :data:`KERF_UNCOMPENSATED` note.

:func:`resolve_kerf` fixes the **source order**, which matters as much as the
arithmetic: an explicit argument, else the process DFM pack's ``kerf_mm``, else
*no compensation at all* plus a :data:`KERF_UNCOMPENSATED` note. A default kerf
is never invented — a wrong compensation is worse than none, because none is
visible with a caliper and a wrong one looks correct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final, Literal

from hephaestus.core.errors import ValidationError
from hephaestus.core.kernel.topology import planar_faces
from opstore.types import JSONValue

__all__ = [
    "KERF_UNCOMPENSATED",
    "KerfDecision",
    "KerfRefusal",
    "KerfSource",
    "kerf_compensated_shape",
    "resolve_kerf",
]

#: Result note: the emitted path is the nominal boundary, uncompensated.
KERF_UNCOMPENSATED: Final[str] = "kerf_uncompensated"

#: Where the applied kerf came from. ``"none"`` is not a failure — it is the
#: honest report that nothing declared one and nothing was invented.
KerfSource = Literal["explicit", "dfm", "none"]

#: Decimals every compensated coordinate keeps (matches the cut-file writers).
_COORD_DECIMALS: Final[int] = 6
#: A compensated face below this area (mm^2) collapsed under the offset.
_MIN_FACE_AREA_MM2: Final[float] = 1e-6


class KerfRefusal(Exception):
    """Compensation could not be applied; ``data`` names the profile and ring."""

    def __init__(self, reason: str, message: str, *, data: dict[str, JSONValue]) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.data = data


# --------------------------------------------------------------------------
# source resolution


@dataclass(frozen=True)
class KerfDecision:
    """Which kerf was applied, where it came from, and why not when it was not.

    ``applied_mm`` is ``None`` exactly when nothing was compensated. A zero
    ``applied_mm`` with ``source="explicit"`` is the caller deliberately asking
    for the nominal path; both carry the :data:`KERF_UNCOMPENSATED` note, so a
    downstream reader never has to infer the difference between "compensated by
    0" and "compensated".
    """

    applied_mm: float | None
    source: KerfSource
    process: str | None = None
    note: str | None = None
    reason: str | None = None

    @property
    def compensates(self) -> bool:
        """True when geometry must actually move."""
        return self.applied_mm is not None and self.applied_mm > 0.0

    def uncompensated(self, reason: str) -> KerfDecision:
        """This decision, downgraded because the geometry had no flat pattern."""
        return KerfDecision(
            applied_mm=None,
            source=self.source,
            process=self.process,
            note=KERF_UNCOMPENSATED,
            reason=reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "applied_mm": self.applied_mm,
            "source": self.source,
            "process": self.process,
        }
        if self.note is not None:
            out["note"] = self.note
        if self.reason is not None:
            out["reason"] = self.reason
        return out


def resolve_kerf(
    *,
    explicit_mm: float | None = None,
    process: str | None = None,
    pack_kerf_mm: float | None = None,
    unavailable: str | None = None,
) -> KerfDecision:
    """The kerf to apply, by fixed source order, never by invented default.

    ``explicit_mm`` (the caller's argument) wins; otherwise ``pack_kerf_mm`` —
    the ``kerf_mm`` parameter of the DFM pack for the part's declared
    ``process`` — is used and reported as such; otherwise nothing is applied and
    the decision carries :data:`KERF_UNCOMPENSATED` with ``unavailable`` (or a
    derived reason) saying which link was missing.

    A negative or non-finite explicit kerf is a contract error: it is a machine
    parameter, and there is no reading of it that produces a real cut path.
    """
    if explicit_mm is not None:
        if not math.isfinite(explicit_mm) or explicit_mm < 0.0:
            raise ValidationError(
                f"kerf_mm must be a finite, non-negative width in millimetres (got {explicit_mm})",
                kind="contract",
            )
        if explicit_mm == 0.0:
            return KerfDecision(
                applied_mm=0.0,
                source="explicit",
                process=process,
                note=KERF_UNCOMPENSATED,
                reason="explicit_zero",
            )
        return KerfDecision(applied_mm=float(explicit_mm), source="explicit", process=process)
    if process and pack_kerf_mm is not None and pack_kerf_mm > 0.0:
        return KerfDecision(applied_mm=float(pack_kerf_mm), source="dfm", process=process)
    reason = unavailable or ("no_process" if not process else "pack_declares_no_kerf")
    return KerfDecision(
        applied_mm=None,
        source="none",
        process=process or None,
        note=KERF_UNCOMPENSATED,
        reason=reason,
    )


# --------------------------------------------------------------------------
# geometry


def _solid_sort_key(solid: Any) -> tuple[float, float, float, float]:
    """Bounding-box minimum then descending volume.

    Deliberately the same ordering ``nesting.flat_profiles`` uses, so the
    ``<prefix>_<n>`` name a refusal reports here is the same profile name the
    cut file and every other refusal report for that solid. A uniform outward
    offset shifts every bounding-box minimum by the same amount, so compensating
    never reorders the profiles either.
    """
    box = solid.bounding_box()
    return (
        round(float(box.min.X), _COORD_DECIMALS),
        round(float(box.min.Y), _COORD_DECIMALS),
        round(float(box.min.Z), _COORD_DECIMALS),
        -round(float(solid.volume), _COORD_DECIMALS),
    )


def _offset_ring(wire: Any, distance: float, *, profile: str, ring: str, kerf_mm: float) -> Any:
    """One closed boundary offset by ``distance`` in its own plane.

    ``Kind.INTERSECTION`` extends the offset segments to their intersection
    rather than rounding the corner: a compensated square stays a square, so the
    part measures nominal at its corners instead of losing them to an arc of the
    beam radius.
    """
    from build123d import Face, Kind

    def refuse(detail: str) -> KerfRefusal:
        return KerfRefusal(
            "kerf_offset_failed",
            f"the {ring} boundary of profile {profile!r} cannot be offset by "
            f"{distance:+.4f} mm for a {kerf_mm:.4f} mm kerf: {detail}",
            data={
                "profile": profile,
                "ring": ring,
                "kerf_mm": kerf_mm,
                "offset_mm": distance,
                "detail": detail,
            },
        )

    try:
        offset: Any = wire.offset_2d(distance, kind=Kind.INTERSECTION)
    except Exception as exc:  # OCC raises a bare RuntimeError on a failed offset
        raise refuse("the kernel could not build an offset boundary") from exc
    try:
        area = float(Face(offset).area)
    except Exception as exc:
        raise refuse("the offset boundary does not bound a face") from exc
    if area < _MIN_FACE_AREA_MM2:
        raise refuse("the offset collapsed the boundary (the feature is narrower than the kerf)")
    return offset


def kerf_compensated_shape(shape: Any, kerf_mm: float, *, prefix: str = "profile") -> Any:
    """``shape`` with every solid's flat pattern grown onto the waste side.

    The returned compound is a **cut-path shape**, not the part: each solid is
    replaced by its largest planar face — outer boundary offset outward by
    ``kerf_mm / 2``, every hole offset inward by the same — re-extruded to the
    solid's own thickness. It is used to write DXF/SVG and is never published,
    measured against a check, or handed back as geometry.

    A non-positive ``kerf_mm`` returns ``shape`` unchanged and untouched, which
    is what makes an uncompensated export byte-identical to one from before this
    module existed.
    """
    if kerf_mm <= 0.0:
        return shape
    from build123d import Compound, Face, extrude

    half = kerf_mm / 2.0
    solids: list[Any] = sorted(shape.solids(), key=_solid_sort_key)
    if not solids:
        raise KerfRefusal(
            "no_profiles",
            "the artifact contains no solids to compensate",
            data={"profiles": [], "kerf_mm": kerf_mm},
        )
    grown: list[Any] = []
    for index, solid in enumerate(solids, start=1):
        name = f"{prefix}_{index}"
        records = planar_faces(solid)
        if not records:
            raise KerfRefusal(
                "not_a_sheet_profile",
                f"{name} has no planar face: it has no flat pattern to compensate",
                data={"profile": name, "kerf_mm": kerf_mm},
            )
        best = min(records, key=lambda record: (-record.area, record.index))
        face: Any = list(solid.faces())[best.index]
        area = float(face.area)
        if area <= _MIN_FACE_AREA_MM2:  # pragma: no cover - a planar face has area
            raise KerfRefusal(
                "not_a_sheet_profile",
                f"{name} has a degenerate flat pattern",
                data={"profile": name, "kerf_mm": kerf_mm},
            )
        outer = _offset_ring(face.outer_wire(), half, profile=name, ring="outer", kerf_mm=kerf_mm)
        inners = [
            _offset_ring(inner, -half, profile=name, ring=f"hole_{n}", kerf_mm=kerf_mm)
            for n, inner in enumerate(face.inner_wires(), start=1)
        ]
        # A prism's thickness is exactly volume / flat-pattern area, and the
        # flat-pattern area already excludes the holes.
        thickness = float(solid.volume) / area
        try:
            compensated: Any = extrude(Face(outer, inners), amount=thickness, dir=-face.normal_at())
        except Exception as exc:
            raise KerfRefusal(
                "kerf_offset_failed",
                f"profile {name!r} could not be rebuilt from its compensated boundaries",
                data={"profile": name, "kerf_mm": kerf_mm, "detail": f"{type(exc).__name__}"},
            ) from exc
        grown.append(compensated)
    return Compound(children=grown)
