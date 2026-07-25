# Reference solution for bench task cat-step — the shelf plate.
#
# A 300 x 200 tread in 18 mm ply, its back edge against the wall (y = 0), its
# underside on z = 0 so the gusset can carry it, and the two outer front corners
# rounded R25 so a cat landing on the step cannot catch a sharp corner.
_w = 300.0
_d = 200.0
_t = hc.panel_t
_r = 25.0

tread = Pos(0, hc.wall_face_y + _d / 2.0, _t / 2.0) * Box(_w, _d, _t)

# Round the two front vertical corners (the pair furthest from the wall).
_front_corners = tread.edges().filter_by(Axis.Z).sort_by(Axis.Y)[-2:]
tread = fillet(_front_corners, radius=_r)
tread.label = "tread"

tag(tread.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "tread_top")
tag(tread.faces().filter_by(Axis.Y).sort_by(Axis.Y)[0], "wall_face")

part.geometry = tread

CHECKS = {
    "envelope": lambda m: m.bbox("part") == approx((_w, _d, _t), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Cat-step tread: 300 x 200 shelf with rounded front corners"
part.material_spec = "18 mm Baltic birch plywood"
part.process = "cnc_router"
part.general_tolerance = "+/-0.25 mm cut profile"
part.feature("tread_top").surface_finish = "Sand to 180 grit; the cat lands here"
