# Independent second implementation of hinge-travel lid (VALIDATION.md §1:
# every task ships a second solution so its checks provably grade the
# engineering, not the reference geometry back).
#
# Different construction: the lug barrels are turned as finished tubes
# *before* the union (the reference bores the assembled lid), the plate and
# straps are laid out with align= instead of centred positioning, and the
# plate's two outer corners carry a 2 mm corner chamfer the reference does
# not. The plate's front-bottom EDGE — the governing point of the swept
# wire-channel clearance — keeps its full nominal position between the
# chamfered corners, so the declared mechanism grades identically.
_lug_r = hc.lug_d / 2.0
_tube = Cylinder(radius=_lug_r, height=hc.lug_len) - Cylinder(
    radius=hc.pin_bore_d / 2.0, height=hc.lug_len + 4.0
)
lug_l = Pos(hc.lid_x0 + hc.lug_len / 2.0, 0.0, hc.axis_z) * Rot(0.0, 90.0, 0.0) * _tube
lug_r = Pos(hc.lid_x1 - hc.lug_len / 2.0, 0.0, hc.axis_z) * Rot(0.0, 90.0, 0.0) * _tube

plate = Pos(hc.lid_x0, hc.lid_y0, hc.deck_t) * Box(
    hc.lid_x1 - hc.lid_x0, hc.lid_y1 - hc.lid_y0, hc.lid_t,
    align=(Align.MIN, Align.MIN, Align.MIN),
)
# Break the plate's two outer corners (the vertical edges at the +Y edge).
_outer_corners = plate.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1]
plate = chamfer(_outer_corners, length=2.0)

strap_l = Pos(hc.lid_x0, hc.strap_y0, hc.deck_t) * Box(
    hc.lug_len, hc.strap_y1 - hc.strap_y0, hc.lid_t,
    align=(Align.MIN, Align.MIN, Align.MIN),
)
strap_r = Pos(hc.lid_x1 - hc.lug_len, hc.strap_y0, hc.deck_t) * Box(
    hc.lug_len, hc.strap_y1 - hc.strap_y0, hc.lid_t,
    align=(Align.MIN, Align.MIN, Align.MIN),
)
body = plate + strap_l + strap_r + lug_l + lug_r
body.label = "lid_body"

tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.AREA)[0], "hinge_bore")
tag(body.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1], "front_face")

part.geometry = body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 2,
}

part.description = "Hinge lid (variant build): tube-first lugs, chamfered corners"
part.material_spec = "6061 aluminium plate"
part.process = "cnc_router"
