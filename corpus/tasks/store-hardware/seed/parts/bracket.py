# Reference solution for bench task bracket-101.
#
# L-bracket: a base plate with an upstanding wall along its -Y edge, the inner
# corner blended, and two clearance holes through the plate. Every dimension of
# the interface (stock thickness, envelope) comes from globals.py through hc.
PARAMS = {
    "hole_d": Param(6.0, min=3.0, max=10.0),
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
# the top of the base plate. Selected by position rather than sort order so an
# edit that changes the edge count still picks the same corner.
_inner_edge = body.edges().filter_by(Axis.X).sort_by_distance((0, -_wide / 2.0 + _t, _t))[0]
body = fillet(_inner_edge, radius=p.fillet_r)

# Two through-holes, inset from the plate ends and from the front edge.
_hx = _len / 2.0 - p.hole_inset_x
_hy = _wide / 2.0 - p.hole_inset_y
hole_a = Pos(-_hx, _hy, _t / 2.0) * Cylinder(radius=p.hole_d / 2.0, height=_t)
hole_b = Pos(_hx, _hy, _t / 2.0) * Cylinder(radius=p.hole_d / 2.0, height=_t)
body = body - hole_a - hole_b
body.label = "bracket_body"

# The fillet also produces a cylindrical face, so the hole walls are picked by
# proximity to their own axis instead of by geometry type alone.
_cylinders = body.faces().filter_by(GeomType.CYLINDER)
tag(_cylinders.sort_by_distance((-_hx, _hy, _t / 2.0))[0], "hole_a")
tag(_cylinders.sort_by_distance((_hx, _hy, _t / 2.0))[0], "hole_b")
tag(body.faces().filter_by(Axis.X).sort_by(Axis.X)[0], "end_face_a")
tag(body.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "end_face_b")
tag(body.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1], "front_face")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[1], "mount_top")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (_len + 0.05, _wide + 0.05, _high + 0.05),
    "holes_are_through": lambda m: m.bbox("hole_a") == approx((6.0, 6.0, _t), abs=0.05)
    and m.bbox("hole_b") == approx((6.0, 6.0, _t), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 2,
}

part.description = "L-bracket, two 6 mm through-holes, filleted inner corner"
part.material_spec = "6 mm 6061-T6 aluminium plate"
part.process = "cnc_router"
part.general_tolerance = "+/-0.1 mm on hole centres"
part.feature("mount_top").surface_finish = "Deburr; fasteners seat on this face"
