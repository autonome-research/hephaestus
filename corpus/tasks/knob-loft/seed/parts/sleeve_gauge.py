# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). A no-go sleeve over the grip's cylindrical band
# (z = 16 .. 23) whose bore is 0.025 mm OVER the nominal grip radius.
#
# The knob must not reach into this sleeve, so the grip's radius is never long,
# at any angle. Paired with `core_gauge`, which stops it being short, the grip
# surface is held inside a 0.05 mm radial band all the way round.
_band_z0 = 16.0
_band_h = 7.0

_blank = Pos(0, 0, _band_z0) * Cylinder(
    radius=20.0, height=_band_h, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_bore = Pos(0, 0, _band_z0) * Cylinder(
    radius=hc.grip_d / 2.0 + 0.025,
    height=_band_h,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
sleeve = _blank - _bore
sleeve.label = "sleeve"

part.geometry = sleeve

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part") == approx((40.0, 40.0, _band_h), abs=0.005),
    "bore_is_open": lambda m: m.sealed("part") and m.genus("part") == 1,
}

part.description = "Grip no-go sleeve gauge: nominal grip radius plus 0.025 mm"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
