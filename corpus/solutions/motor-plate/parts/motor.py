# Reference solution for bench task motor-plate — the motor itself.
#
# A `stepper_nema17_frame` instance from the pinned parts store, pasted exactly
# as `instance_store_part` rendered it: the store's own body, its placement, and
# its interface region — which is what emits the `motor__mount_face` and
# `motor__bolt_1` tags the task's two constraints anchor on. The store's
# convention puts the origin on the mount face on the shaft axis with the body
# hanging into -Z, so an instance placed at the plate's underside seats where the
# geometry says it does.
#
# The 45 degree rz is not decoration: it puts the 31 mm square bolt pattern on
# the plate's own axes, and it is the placement that proves the store's
# interface selectors are ordered by a measure rather than by a world axis
# (PARTS_STORE.md §2.1) — a selector that used `sort_by(Axis.Z)` would pick a
# different face here and the declared classes would stop matching.

# NEMA 17 stepper motor (frame envelope) — parts-store instance at (0, 0, 8) mm, rotated (0, 0, 45)deg.
# registry: hephaestus-parts @ sha256:ff9e43925bfcf7a868e630fa322018664e416e48726cdd28d077a60e5f0ed780   id: stepper_nema17_frame
# Reference geometry from a pinned registry: review it, then compose
#   _motor into part.geometry (e.g. Compound(children=[..., _motor])).

_motor_body_length = 39.0
_motor_frame = 42.3
_motor_bolt_pitch = 31.0
_motor_bolt_d = 3.0
_motor_bolt_depth = 4.5
_motor_boss_d = 22.0
_motor_boss_h = 2.0
_motor_shaft_d = 5.0
_motor_shaft_len = 24.0
_motor_cable_d = 8.0
_motor_cable_len = 6.0
_motor_cable_y = -9.0

_motor_stack = Box(_motor_frame, _motor_frame, _motor_body_length, align=(Align.CENTER, Align.CENTER, Align.MAX))
_motor_boss = Cylinder(_motor_boss_d / 2, _motor_boss_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_motor_shaft = Cylinder(_motor_shaft_d / 2, _motor_shaft_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
# The lead exit: a stub on the +X flank, deliberately off the Y centreline so
# exactly one mounting hole is nearest to it.
_motor_cable = Pos(_motor_frame / 2, _motor_cable_y, -_motor_body_length + 8.0) * Rot(0, 90, 0) * Cylinder(
    _motor_cable_d / 2, _motor_cable_len, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_motor_holes = Compound(
    [
        Pos(_x, _y, 0) * Cylinder(_motor_bolt_d / 2, _motor_bolt_depth, align=(Align.CENTER, Align.CENTER, Align.MAX))
        for _x in (-_motor_bolt_pitch / 2, _motor_bolt_pitch / 2)
        for _y in (-_motor_bolt_pitch / 2, _motor_bolt_pitch / 2)
    ]
)
_motor_motor = (_motor_stack + _motor_boss + _motor_shaft + _motor_cable) - _motor_holes
_motor_motor.color = Color(0.28, 0.3, 0.33)
_motor_motor.label = "stepper_nema17_frame"
_motor = Pos(0.0, 0.0, 8.0) * Rot(0.0, 0.0, 45.0) * _motor_motor
_motor.label = "stepper_nema17_frame"
# PARTS_STORE.md §2.1: every selector is rooted at the published shape and is
# ordered by a MEASURE — radius, area, distance between two pieces of the same
# placed shape — never by a world axis. A measure survives the Pos/Rot the
# consumer applies; `sort_by(Axis.Z)[-1]` does not, and would silently pick a
# different face once the motor is instanced under a rotation.
#
# The cylinders separate by radius at every declared body length, because no
# radius here depends on `body_length`: four bolt holes at 1.5, the shaft at
# 2.5, the lead exit at 4.0, the pilot boss at 11.0.
#
# The MOUNT FACE cannot be named by area — a 42.3 x body_length flank overtakes
# it above about 33 mm of stack — so it is named the way the insert's top face
# is: exactly two planar faces touch the pilot boss cylinder, the mount face
# and the boss's own top annulus, and the mount face is by far the larger of
# the two at every body length. Both operands come from the placed shape.
#
# BOLT_1 is the hole nearest the lead exit. The four holes are congruent and a
# square pattern is four-fold symmetric, so the lead exit is the only thing in
# this geometry that can distinguish them — which is why it is modelled.
tag(
    _motor.faces()
    .filter_by(GeomType.PLANE)
    .sort_by_distance(
        _motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1]
    )[0:2]
    .sort_by(SortBy.AREA)[-1],
    "motor__mount_face",
)
tag(_motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "motor__pilot_boss")
tag(_motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-3], "motor__shaft")
tag(
    _motor.faces()
    .filter_by(GeomType.CYLINDER)
    .sort_by(SortBy.RADIUS)[0:4]
    .sort_by_distance(
        _motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-2]
    )[0],
    "motor__bolt_1",
)

part.geometry = _motor

CHECKS = {
    "shaft_stands_clear": lambda m: m.bbox("part")[2] == approx(63.0, abs=0.05),
}

part.description = "A NEMA 17 stepper motor seated under the plate, rotated 45 degrees"
part.material_spec = "Store part stepper_nema17_frame (NEMA ICS 16 frame envelope)"
part.process = "purchased"
part.assembly_method = "Bolted to the plate through the 31 mm square pattern"
