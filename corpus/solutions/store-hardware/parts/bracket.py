# Reference solution for bench task store-hardware — the re-detailed bracket.
#
# bracket-101 with its two mounting holes re-cut for store-sourced M5
# socket-head cap screws: a 5.5 mm clearance hole through the plate and a 10 mm
# counterbore 5 mm deep from the top face, which buries the 8.5 x 5 mm head
# below the mounting surface.
PARAMS = {
    "hole_d": Param(5.5, min=3.0, max=10.0),
    "counterbore_d": Param(10.0, min=6.0, max=16.0),
    "counterbore_depth": Param(5.0, min=1.0, max=8.0),
    "fillet_r": Param(4.0, min=1.0, max=8.0),
    "hole_inset_x": Param(12.0, min=8.0, max=20.0),
    "hole_inset_y": Param(14.0, min=8.0, max=20.0),
}

_t = hc.plate_t
_len = hc.bracket_len
_wide = hc.bracket_width
_high = hc.bracket_height

base = Pos(0, 0, _t / 2.0) * Box(_len, _wide, _t)
wall = Pos(0, -_wide / 2.0 + _t / 2.0, _high / 2.0) * Box(_len, _t, _high)
body = base + wall

# Blend the inner corner: the X-parallel edge where the wall's inner face meets
# the top of the base plate.
_inner_edge = body.edges().filter_by(Axis.X).sort_by_distance((0, -_wide / 2.0 + _t, _t))[0]
body = fillet(_inner_edge, radius=p.fillet_r)

# Two counterbored through-holes. The clearance hole runs the full plate
# thickness; the counterbore is cut down from the top face.
_hx = _len / 2.0 - p.hole_inset_x
_hy = _wide / 2.0 - p.hole_inset_y
for _sx in (-1.0, 1.0):
    _clearance = Pos(_sx * _hx, _hy, _t / 2.0) * Cylinder(radius=p.hole_d / 2.0, height=_t)
    _counterbore = Pos(_sx * _hx, _hy, _t - p.counterbore_depth) * Cylinder(
        radius=p.counterbore_d / 2.0,
        height=p.counterbore_depth,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    body = body - _clearance - _counterbore
body.label = "bracket_body"

_cylinders = body.faces().filter_by(GeomType.CYLINDER)
tag(_cylinders.sort_by_distance((-_hx, _hy, 0.0))[0], "hole_a")
tag(_cylinders.sort_by_distance((_hx, _hy, 0.0))[0], "hole_b")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "mount_top")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (_len + 0.05, _wide + 0.05, _high + 0.05),
    "counterbore_floor_is_thin": lambda m: m.bbox("hole_a")
    == approx((p.hole_d, p.hole_d, _t - p.counterbore_depth), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 2,
}

part.description = "L-bracket with counterbored M5 mounting holes"
part.material_spec = "6 mm 6061-T6 aluminium plate"
part.process = "cnc_router"
part.general_tolerance = "+/-0.1 mm on hole centres"
part.feature("mount_top").surface_finish = "Deburr; the mating part seats on this face"
