# Variant solution for cat-step — deliberately NOT the reference tread.
#
# Same 300 x 200 x 18 tread with R25 front corners, but built the other way
# round: the profile is rounded in 2D and then extruded, where the reference
# extrudes a box and fillets its vertical edges in 3D.
#
# The point of the fixture is the second difference: this tread's top edges are
# eased with a 1 mm break, which is what anyone actually cutting a cat step out
# of ply would do and which the task never asks for either way. That removes
# ~490 mm^3 — outside the +/-400 window the check carried before the 2026-07-26
# audit, inside the +/-600 material budget it carries now. A correct tread with
# a sanded edge used to fail this task.
_w = 300.0
_d = 200.0
_t = hc.panel_t
_r = 25.0
_break = 1.0

_profile = Rectangle(_w, _d)
_profile = fillet(_profile.vertices().sort_by(Axis.Y)[-2:], radius=_r)

tread = extrude(_profile, amount=_t)
tread = chamfer(tread.faces().sort_by(Axis.Z)[-1].edges(), length=_break)
tread = Pos(0.0, hc.wall_face_y + _d / 2.0, 0.0) * tread
tread.label = "tread"

tag(tread.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "tread_top")
tag(tread.faces().filter_by(Axis.Y).sort_by(Axis.Y)[0], "wall_face")

part.geometry = tread

CHECKS = {
    "envelope": lambda m: m.bbox("part") == approx((_w, _d, _t), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Cat step tread (variant): rounded-profile extrusion, edges eased"
part.material_spec = "Baltic birch plywood, 18 mm"
part.process = "cnc_router"
part.general_tolerance = "ISO 2768-m"
