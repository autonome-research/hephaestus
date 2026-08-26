# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). One 29.9 mm go-pin on the flange's axis: a
# correctly enlarged Ø30 bore admits it with a 0.05 mm radial gap and no
# interference, which is how the acceptance checks measure the new bore.
_pin_d = 29.9
_pin_len = 40.0

pin = Pos(0, 0, hc.flange_t / 2.0) * Cylinder(radius=_pin_d / 2.0, height=_pin_len)
pin.label = "go_pin"
part.geometry = pin

CHECKS = {
    "gauge_pin_intact": lambda m: m.bbox("part") == approx((_pin_d, _pin_d, _pin_len), abs=0.05),
}

part.description = "Go-gauge: one 29.9 mm pin on the flange-edit bore axis"
part.material_spec = "Hardened gauge pin"
part.process = "cnc_router"
