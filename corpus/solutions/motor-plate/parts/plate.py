# Reference solution for bench task motor-plate — the mounting plate.
#
# A 60 mm square plate sitting on top of the motor's mount face: a pilot recess
# that registers on the motor's 22 mm boss, a shaft clearance hole, and four
# bolt clearance holes on the motor's own bolt circle. Every interface number
# comes from globals.py through hc, including the bolt radius the 45 degree
# motor placement puts the pattern on.
PARAMS = {
    "corner_relief": Param(0.0, min=0.0, max=2.0, doc="unused stock allowance, mm"),
}

_t = hc.plate_t
_side = hc.plate_side
_z0 = hc.mount_z

_body = Pos(0, 0, _z0) * Box(_side, _side, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))
_recess = Pos(0, 0, _z0) * Cylinder(
    hc.pilot_recess_d / 2.0, hc.pilot_recess_depth, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_shaft_hole = Pos(0, 0, _z0) * Cylinder(
    hc.shaft_clearance_d / 2.0, _t, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_bolts = Compound(
    [
        Pos(_x, _y, _z0)
        * Cylinder(hc.bolt_clearance_d / 2.0, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))
        for _x, _y in (
            (hc.bolt_radius, 0.0),
            (-hc.bolt_radius, 0.0),
            (0.0, hc.bolt_radius),
            (0.0, -hc.bolt_radius),
        )
    ]
)
plate = _body - _recess - _shaft_hole - _bolts
plate.label = "plate"
part.geometry = plate

# The seat face is the plate's underside: the largest planar face whose area is
# reduced by the recess and the holes, and the only one the motor touches.
tag(plate.faces().filter_by(GeomType.PLANE).sort_by(Axis.Z)[0], "seat_face")
# The +X bolt hole: the one the motor's `bolt_1` (its lead-exit hole, rotated
# onto +X by the 45 degree placement) must be concentric with.
tag(
    plate.faces()
    .filter_by(GeomType.CYLINDER)
    .filter_by(lambda f: f.radius == approx(hc.bolt_clearance_d / 2.0, abs=1e-6))
    .sort_by_distance((hc.bolt_radius, 0.0, _z0))[0],
    "bolt_e",
)

CHECKS = {
    "plate_sits_on_the_mount_face": lambda m: m.bbox("part")[2] == approx(_t, abs=1e-6),
}

part.description = "60 mm square motor mounting plate with a pilot recess and four bolt holes"
part.material_spec = "6061 aluminium plate, 8 mm"
part.process = "cnc_mill"
part.assembly_method = "Bolted onto the motor's mount face through the 31 mm square pattern"
