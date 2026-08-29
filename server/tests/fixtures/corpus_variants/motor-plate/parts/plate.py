# Independent second implementation for bench task motor-plate — the plate.
#
# Every hole is cut in the SKETCH and extruded once, instead of being subtracted
# from a solid one at a time, and the pilot recess is the only boolean left. The
# seat face is found by distance to the mount plane rather than by a Z sort, and
# the bolt hole is found by distance to the point the bolt circle puts it at.
# Same interface, different construction.
PARAMS = {
    "sketch_scale": Param(1.0, min=1.0, max=1.0, doc="unused; the profile is drawn at size"),
}

_t = hc.plate_t
_side = hc.plate_side
_z0 = hc.mount_z
_r = hc.bolt_radius

_holes = [
    Pos(_x, _y) * Circle(hc.bolt_clearance_d / 2.0)
    for _x, _y in ((_r, 0.0), (0.0, _r), (-_r, 0.0), (0.0, -_r))
]
_profile = Rectangle(_side, _side) - Circle(hc.shaft_clearance_d / 2.0)
for _hole in _holes:
    _profile = _profile - _hole

plate = extrude(Plane.XY.offset(_z0) * _profile, amount=_t)
plate = plate - (
    Pos(0, 0, _z0)
    * Cylinder(
        hc.pilot_recess_d / 2.0, hc.pilot_recess_depth, align=(Align.CENTER, Align.CENTER, Align.MIN)
    )
)
plate.label = "plate"
part.geometry = plate

tag(plate.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-2], "seat_face")
tag(
    plate.faces()
    .filter_by(GeomType.CYLINDER)
    .sort_by_distance((_r, 0.0, _z0 + _t / 2.0))[0],
    "bolt_e",
)

CHECKS = {
    "four_bolt_holes": lambda m: len(_holes) == 4,
}

part.description = "60 mm square motor plate: one extruded profile plus the pilot recess"
part.material_spec = "6061 aluminium plate, 8 mm"
part.process = "cnc_mill"
part.assembly_method = "Bolted onto the motor's mount face through the 31 mm square pattern"
