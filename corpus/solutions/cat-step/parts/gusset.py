# Reference solution for bench task cat-step — the triangular support gusset.
#
# A right triangle in the y/z plane, extruded 18 mm and centred on x = 0: the
# vertical leg is against the wall (y = 0), the horizontal leg carries the
# shelf's underside (z = 0), and the hypotenuse runs from the shelf's far
# support point down to the wall.
_t = hc.panel_t
_reach = 140.0
_drop = 160.0

_profile = Plane.YZ * Polygon(
    (hc.wall_face_y, 0.0),
    (hc.wall_face_y + _reach, 0.0),
    (hc.wall_face_y, -_drop),
    align=None,
)
bracket = extrude(_profile, amount=_t / 2.0, both=True)
bracket.label = "gusset"

tag(bracket.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "bearing_face")
tag(bracket.faces().filter_by(Axis.Y).sort_by(Axis.Y)[0], "wall_face")

part.geometry = bracket

CHECKS = {
    "envelope": lambda m: m.bbox("part") == approx((_t, _reach, _drop), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Cat-step gusset: triangular wall bracket under the tread"
part.material_spec = "18 mm Baltic birch plywood"
part.process = "cnc_router"
part.joint = "Glued and screwed to the tread underside and to the wall cleat"
part.feature("bearing_face").surface_finish = "Flat and square: the tread seats on this face"
