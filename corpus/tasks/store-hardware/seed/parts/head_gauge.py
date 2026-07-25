# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). Two 12 mm columns standing on the base plate's
# top face, directly over the mounting holes: they are the space a mating part
# will occupy. Nothing may stick up into them, so a screw head that is proud of
# the plate — instead of buried in its counterbore — interferes with this gauge
# and the acceptance check fails.
_hx = hc.bracket_len / 2.0 - 12.0
_hy = hc.bracket_width / 2.0 - 14.0
_clear_h = 20.0

column_a = Pos(-_hx, _hy, hc.plate_t) * Cylinder(
    radius=6.0, height=_clear_h, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
column_a.label = "column_a"
column_b = Pos(_hx, _hy, hc.plate_t) * Cylinder(
    radius=6.0, height=_clear_h, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
column_b.label = "column_b"

part.geometry = Compound(children=[column_a, column_b])

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part") == approx((2.0 * _hx + 12.0, 12.0, _clear_h), abs=0.01),
}

part.description = "Head-clearance gauge: the space above the bracket's mounting holes"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
