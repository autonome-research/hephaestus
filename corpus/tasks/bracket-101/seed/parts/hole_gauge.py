# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). Two 5.9 mm go-pins standing on the specified hole
# centres: a correct bracket admits both with a 0.05 mm radial gap and no
# interference, which is how the acceptance checks measure the hole pattern.
_pin_d = 5.9
_pin_len = 20.0
_hx = hc.bracket_len / 2.0 - 12.0
_hy = hc.bracket_width / 2.0 - 14.0

pin_a = Pos(-_hx, _hy, hc.plate_t / 2.0) * Cylinder(radius=_pin_d / 2.0, height=_pin_len)
pin_a.label = "pin_a"
pin_b = Pos(_hx, _hy, hc.plate_t / 2.0) * Cylinder(radius=_pin_d / 2.0, height=_pin_len)
pin_b.label = "pin_b"

part.geometry = Compound(children=[pin_a, pin_b])

CHECKS = {
    "gauge_pins_intact": lambda m: m.bbox("part") <= (2.0 * _hx + 6.0, 6.0, _pin_len + 0.05),
}

part.description = "Go-gauge: two 5.9 mm pins on the bracket-101 hole centres"
part.material_spec = "Hardened gauge pins"
part.process = "cnc_router"
