# motor-plate acceptance checks (project scope: whole-part measurements only).
#
# The graded engineering is the MOUNT, and the mount is declared: a `coincident`
# between the store motor's own `motor__mount_face` tag and the plate's seat
# face, and a `concentric` between the motor's `motor__bolt_1` tag and the plate
# clearance hole that must line up with it. Both anchors on the motor side are
# tags the store's interface region emitted at a non-zero pos - the run never
# retyped a bolt coordinate, which is the whole difference from the retired
# `mating_features` field.
#
# What CHECKS pins is everything the two constraints cannot see: that the plate
# is the plate they were declared about, that the motor is the store's envelope
# and not a hand-drawn block, and that the assembly does not overlap or float.
#
# Windows are budgets. The plate window is ~3x below the smallest detailing
# error it must reject: omitting the pilot recess is 789 mm^3 and leaving the
# shaft clearance hole out is 226 mm^3, both far outside it. The motor window
# rejects any body length other than the 39 mm stack the prompt names (1791
# mm^3 per millimetre).
_PLATE_VOLUME = 27493.91
_PLATE_WINDOW = 70.0
_MOTOR_VOLUME = 71148.90
_MOTOR_WINDOW = 400.0

CHECKS = {
    "plate_envelope": lambda m: m.bbox("plate/part") == approx((60.0, 60.0, 8.0), abs=0.05),
    "plate_detailed": lambda m: m.volume("plate/part") == approx(_PLATE_VOLUME, abs=_PLATE_WINDOW),
    "plate_sealed": lambda m: m.sealed("plate/part") and m.genus("plate/part") == 5,
    "motor_is_the_store_envelope": lambda m: m.volume("motor/part")
    == approx(_MOTOR_VOLUME, abs=_MOTOR_WINDOW),
    "motor_stands_off_the_plate": lambda m: m.bbox("motor/part")
    == approx((59.82, 59.82, 63.0), abs=0.1),
    "motor_does_not_interfere": lambda m: m.interference("motor/part", "plate/part")
    == approx(0.0, abs=1e-6),
    "motor_is_seated": lambda m: m.clearance("motor/part", "plate/part")
    == approx(0.0, abs=1e-6),
}
