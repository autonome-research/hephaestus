# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). One 5.9 mm go-pin lying on the hinge axis and
# running past both knuckles: a correct hinge admits it through both pin bores
# with a 0.05 mm radial gap and no interference, which is how the acceptance
# checks measure the bores as bores. Concentricity, the flush knuckle mate and
# the swing gap are graded separately, as the task's declared constraints.
_pin_d = hc.pin_bore_d - 0.1
_pin_len = 2.0 * hc.knuckle_len + 4.0

pin = Pos(0.0, 0.0, hc.axis_z) * Rot(0.0, 90.0, 0.0) * Cylinder(
    radius=_pin_d / 2.0, height=_pin_len
)
pin.label = "pin"

part.geometry = pin

CHECKS = {
    "gauge_pin_intact": lambda m: m.bbox("part") == approx((_pin_len, _pin_d, _pin_d), abs=0.01),
}

part.description = "Go-gauge: a 5.9 mm pin on the hinge axis, spanning both knuckles"
part.material_spec = "Hardened gauge pin"
part.process = "reference"
