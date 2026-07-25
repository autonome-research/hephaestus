# Triangular support gusset under the tread. Every dimension comes from the
# project parameters in globals.py, so the bracket is re-sized by retuning
# params — never by editing this script.
_t = hc.panel_t
_reach = hc.gusset_reach
_drop = hc.gusset_drop

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

part.description = "Parametric triangular wall bracket under the tread"
part.material_spec = "18 mm Baltic birch plywood"
part.process = "cnc_router"
part.joint = "Glued and screwed to the tread underside and to the wall cleat"
part.feature("bearing_face").surface_finish = "Flat and square: the tread seats on this face"
