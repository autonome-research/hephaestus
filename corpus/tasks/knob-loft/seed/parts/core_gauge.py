# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). A solid go-plug over the grip's cylindrical band
# (z = 16 .. 23), 0.025 mm UNDER the nominal grip radius.
#
# The knob must contain this plug completely — the acceptance check compares the
# overlap volume against the plug's own volume — so the grip's radius is never
# short, at any angle. Paired with `sleeve_gauge`, which stops it being long,
# the grip surface is held inside a 0.05 mm radial band all the way round: the
# measured form of "a body of revolution about Z".
_band_z0 = 16.0
_band_h = 7.0

plug = Pos(0, 0, _band_z0) * Cylinder(
    radius=hc.grip_d / 2.0 - 0.025,
    height=_band_h,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
plug.label = "plug"

part.geometry = plug

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part") == approx((23.95, 23.95, _band_h), abs=0.005),
}

part.description = "Grip go-plug gauge: nominal grip radius less 0.025 mm"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
