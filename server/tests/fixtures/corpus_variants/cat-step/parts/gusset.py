# Variant solution for cat-step — deliberately NOT the reference gusset.
#
# The reference extrudes a Polygon symmetrically about x = 0. This one builds the
# same right triangle by cutting a rectangular blank with a rotated slab (the way
# a gusset is drawn when the hypotenuse is the thing being controlled), and
# extrudes it one-sided from x = -t/2 instead of both ways from the origin.
#
# Same triangle, same 18 mm of ply, different construction: a check that grades
# how the solid was made rather than what it is fails here.
_t = hc.panel_t
_reach = 140.0
_drop = 160.0

_blank = Pos(-_t / 2.0, hc.wall_face_y, -_drop) * Box(
    _t, _reach, _drop, align=(Align.MIN, Align.MIN, Align.MIN)
)

# The hypotenuse: from (y = reach, z = 0) down to (y = 0, z = -drop). Everything
# below that line is waste, removed by a slab whose top face lies on it.
_angle = math.degrees(math.atan2(_drop, _reach))
_waste = (
    Pos(0.0, hc.wall_face_y + _reach, 0.0)
    * Rotation(_angle, 0.0, 0.0)
    * Box(4.0 * _t, 4.0 * _reach, 4.0 * _drop, align=(Align.CENTER, Align.CENTER, Align.MAX))
)

bracket = _blank - _waste
bracket.label = "gusset"

tag(bracket.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "bearing_face")
tag(bracket.faces().filter_by(Axis.Y).sort_by(Axis.Y)[0], "wall_face")

part.geometry = bracket

CHECKS = {
    "envelope": lambda m: m.bbox("part") == approx((_t, _reach, _drop), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Cat step gusset (variant): blank cut to the hypotenuse"
part.material_spec = "Baltic birch plywood, 18 mm"
part.process = "cnc_router"
part.joint = "Glued and screwed to the tread underside and to the wall"
