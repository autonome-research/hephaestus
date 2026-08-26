# Reference solution for bench task plate-from-drawing.
#
# Modelled to the registered shop drawing (references/plate-drawing.png):
# 90 x 60 x 6 plate, four Ø5.5 mounting holes with centres 8 mm in from each
# adjacent edge, one Ø22 central bore. Built the plain way: a box, then the
# holes subtracted as cylinders.
PARAMS = {
    "hole_d": Param(5.5, min=3.0, max=8.0),
    "bore_d": Param(22.0, min=10.0, max=30.0),
    "hole_inset": Param(8.0, min=5.0, max=15.0),
}

_w = 90.0
_d = 60.0
_t = 6.0
_hx = _w / 2.0 - p.hole_inset
_hy = _d / 2.0 - p.hole_inset

body = Pos(0, 0, _t / 2.0) * Box(_w, _d, _t)
for _x, _y in ((-_hx, -_hy), (_hx, -_hy), (-_hx, _hy), (_hx, _hy)):
    body = body - Pos(_x, _y, _t / 2.0) * Cylinder(radius=p.hole_d / 2.0, height=2.0 * _t)
body = body - Pos(0, 0, _t / 2.0) * Cylinder(radius=p.bore_d / 2.0, height=2.0 * _t)
body.label = "plate_body"

# The central bore wall is the cylindrical face nearest the axis.
_bore = body.faces().filter_by(GeomType.CYLINDER).sort_by_distance((0, 0, _t / 2.0))[0]
tag(_bore, "bore_wall")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "mount_top")

part.geometry = body

CHECKS = {
    # The drawing's numbers: 90 x 60 footprint, 6 thick; five through holes.
    "envelope": lambda m: m.bbox("part") == approx((90.0, 60.0, 6.0), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 5,
}

part.description = "Mounting plate to the shop drawing: 90 x 60 x 6, four Ø5.5 holes, Ø22 bore"
part.material_spec = "6 mm 6061-T6 aluminium plate"
part.process = "cnc_router"
part.general_tolerance = "+/-0.1 mm on hole centres"
part.feature("mount_top").surface_finish = "Deburr; fasteners seat on this face"
