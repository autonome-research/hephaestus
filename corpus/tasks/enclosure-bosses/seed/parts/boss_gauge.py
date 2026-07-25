# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). Four go-pins, 0.1 mm under the pilot-hole
# diameter, standing on the boss pattern and reaching up to the boss tops.
#
# A correct set of bosses admits all four pins with a 0.05 mm radial gap and no
# interference, which is how the acceptance checks measure that the bosses are
# where the drawing says they are, tall enough, and bored deep enough.
_pin_r = (hc.pilot_d - 0.1) / 2.0
_pin_z0 = hc.boss_top_z - hc.pilot_depth + 1.0

pins = []
for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        _pin = Pos(_sx * hc.boss_x, _sy * hc.boss_y, _pin_z0) * Cylinder(
            radius=_pin_r,
            height=hc.boss_top_z - _pin_z0,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        _pin.label = "pin"
        pins.append(_pin)

part.geometry = Compound(children=pins)

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part")
    == approx((2.0 * hc.boss_x + 2.0 * _pin_r, 2.0 * hc.boss_y + 2.0 * _pin_r, 14.0), abs=0.01),
}

part.description = "Boss go-gauge: four pins on the pilot-hole pattern"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
