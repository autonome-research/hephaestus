# NEMA 17 stepper motor — mounting-frame envelope, no internals.
#
# Coordinate convention: the ORIGIN sits on the MOUNT FACE, on the shaft axis.
# The body hangs into -Z; the pilot boss and the shaft stand up into +Z. Bolt a
# plate onto the mount face at z = 0 and everything lands where the geometry
# says it does.
#
# Deliberately simplified: this is the frame a bracket has to fit, and nothing
# else. There are no laminations, no windings, no end bells, no corner radii
# and no shaft flat. The mounting holes are blind tapped-hole envelopes, not
# threads. Do not use it to reason about heat, magnetics or torque.
#
# The CABLE BOSS is here for two reasons and both are real. Every NEMA 17 has a
# lead exit, and — this is the load-bearing one — a four-hole square bolt
# pattern has a four-fold symmetry, so no measure can name one hole rather than
# another. The lead exit is the feature that breaks it, which is what lets
# `bolt_1` be selected by a MEASURE (nearest hole to the lead exit) instead of
# by a world axis. It is declared in the record's simplifications as the
# envelope feature it is.
#
# Every frame number is NEMA ICS 16's standard 17-frame interface: 42.3 mm
# square body, 31 mm square bolt pattern, M3 mounting holes, 22 mm pilot boss
# 2 mm proud, 5 mm shaft. A public interface standard's nominal dimensions are
# what PARTS_STORE.md §7.1 admits; no vendor drawing was consulted and no
# vendor document is redistributed. Body length is the one continuous axis a
# 17-frame really varies along, so it is the one parameter.
#
# Suggested mating features:
#   pilot recess     22.2 mm dia, >= 2.2 mm deep (registers the bolt circle)
#   clearance holes   3.4 mm dia on a 31 mm square pattern
#   shaft bore        5 mm dia, or a 5 mm coupling

# --- hephaestus-store: params ---
PARAMS = {
    "body_length": Param(39.0, min=20.0, max=60.0, doc="stack length behind the mount face, mm"),
}
# --- hephaestus-store: bind ---
_body_length = p.body_length
# --- hephaestus-store: body ---
_frame = 42.3
_bolt_pitch = 31.0
_bolt_d = 3.0
_bolt_depth = 4.5
_boss_d = 22.0
_boss_h = 2.0
_shaft_d = 5.0
_shaft_len = 24.0
_cable_d = 8.0
_cable_len = 6.0
_cable_y = -9.0

_stack = Box(_frame, _frame, _body_length, align=(Align.CENTER, Align.CENTER, Align.MAX))
_boss = Cylinder(_boss_d / 2, _boss_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_shaft = Cylinder(_shaft_d / 2, _shaft_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
# The lead exit: a stub on the +X flank, deliberately off the Y centreline so
# exactly one mounting hole is nearest to it.
_cable = Pos(_frame / 2, _cable_y, -_body_length + 8.0) * Rot(0, 90, 0) * Cylinder(
    _cable_d / 2, _cable_len, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_holes = Compound(
    [
        Pos(_x, _y, 0) * Cylinder(_bolt_d / 2, _bolt_depth, align=(Align.CENTER, Align.CENTER, Align.MAX))
        for _x in (-_bolt_pitch / 2, _bolt_pitch / 2)
        for _y in (-_bolt_pitch / 2, _bolt_pitch / 2)
    ]
)
_motor = (_stack + _boss + _shaft + _cable) - _holes
_motor.color = Color(0.28, 0.3, 0.33)
_motor.label = "stepper_nema17_frame"
part.geometry = _motor

# --- hephaestus-store: interface ---
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
    "mount_face",
)
tag(_motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "pilot_boss")
tag(_motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-3], "shaft")
tag(
    _motor.faces()
    .filter_by(GeomType.CYLINDER)
    .sort_by(SortBy.RADIUS)[0:4]
    .sort_by_distance(
        _motor.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-2]
    )[0],
    "bolt_1",
)
