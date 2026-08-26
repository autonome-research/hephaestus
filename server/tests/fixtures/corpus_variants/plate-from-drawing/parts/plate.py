# Independent second implementation of plate-from-drawing (corpus meta-test).
#
# Same drawing, different construction: the reference subtracts cylinders from
# a box in 3D; this one draws the plate as a 2D sketch - rectangle minus five
# circles - and extrudes it to thickness, then eases the top face's outer edges
# with a 0.4 mm chamfer, which is what a shop actually does to a plate nobody
# asked to leave sharp. The chamfer is the point: ~48 mm^3 of unrequested but
# correct detailing that an identity window would reject and the material
# budget must accept.
_w = 90.0
_d = 60.0
_t = 6.0
_hole_r = 5.5 / 2.0
_bore_r = 22.0 / 2.0
_hx = _w / 2.0 - 8.0
_hy = _d / 2.0 - 8.0

_profile = Rectangle(_w, _d)
for _x, _y in ((-_hx, -_hy), (_hx, -_hy), (-_hx, _hy), (_hx, _hy)):
    _profile = _profile - Pos(_x, _y) * Circle(_hole_r)
_profile = _profile - Circle(_bore_r)

body = extrude(_profile, amount=_t)

# Ease the top outer edges: the four straight edges of the top face.
_top_edges = body.faces().sort_by(Axis.Z)[-1].edges().filter_by(GeomType.LINE)
body = chamfer(_top_edges, length=0.4)
body.label = "plate_body"

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part") == approx((90.0, 60.0, 6.0), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 5,
}

part.description = "Mounting plate per drawing, edges eased 0.4 mm"
part.material_spec = "Aluminium 6061 plate, 6 mm"
part.process = "cnc_router"
