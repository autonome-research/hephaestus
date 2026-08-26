# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). Go-pins on the drawing's five hole centres: four
# 5.4 mm pins on the mounting-hole pattern (centres 8 mm in from each adjacent
# edge of the 90 x 60 footprint) and one 21.9 mm pin on the central bore. A
# correct plate admits all five with a 0.05 mm radial gap and no interference,
# which is how the acceptance checks measure the drawing's hole callouts.
_pin_len = 20.0
_small_d = 5.4
_big_d = 21.9
_hx = 90.0 / 2.0 - 8.0
_hy = 60.0 / 2.0 - 8.0

_pins = []
for _i, (_x, _y) in enumerate(((-_hx, -_hy), (_hx, -_hy), (-_hx, _hy), (_hx, _hy))):
    _pin = Pos(_x, _y, 3.0) * Cylinder(radius=_small_d / 2.0, height=_pin_len)
    _pin.label = f"pin_{_i}"
    _pins.append(_pin)
_centre = Pos(0, 0, 3.0) * Cylinder(radius=_big_d / 2.0, height=_pin_len)
_centre.label = "pin_centre"
_pins.append(_centre)

part.geometry = Compound(children=_pins)

CHECKS = {
    "gauge_pins_intact": lambda m: m.bbox("part")
    == approx((2.0 * _hx + _small_d, 2.0 * _hy + _small_d, _pin_len), abs=0.05),
}

part.description = "Go-gauge: five pins on the plate-from-drawing hole centres"
part.material_spec = "Hardened gauge pins"
part.process = "cnc_router"
