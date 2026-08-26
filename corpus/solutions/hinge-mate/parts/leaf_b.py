# Reference solution for bench task hinge-mate — the +Y leaf.
#
# The mirror of leaf_a: plate and knuckle spanning x = 0..20 on the +Y side of
# the hinge line, so the two knuckle end faces meet flush at x = 0.
_axis_z = hc.axis_z
_x_mid = hc.knuckle_len / 2.0

plate = Pos(_x_mid, hc.plate_standoff + hc.plate_w / 2.0, hc.plate_t / 2.0) * Box(
    hc.knuckle_len, hc.plate_w, hc.plate_t
)
knuckle = (
    Pos(_x_mid, 0.0, _axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=hc.knuckle_d / 2.0, height=hc.knuckle_len)
)
body = plate + knuckle
bore = (
    Pos(_x_mid, 0.0, _axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=hc.pin_bore_d / 2.0, height=hc.knuckle_len + 2.0)
)
body = body - bore
body.label = "leaf_b_body"

tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.AREA)[0], "pin_bore")
tag(body.faces().filter_by(Axis.X).sort_by_distance((0.0, 0.0, _axis_z))[0], "mate_face")
# The plate's inner edge on this side is the *minimum* Y face.
tag(body.faces().filter_by(Axis.Y).sort_by(Axis.Y)[0], "swing_edge")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.knuckle_len, hc.plate_standoff + hc.plate_w + hc.knuckle_d / 2.0, hc.axis_z + hc.knuckle_d / 2.0), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 1,
}

part.description = "Hinge leaf B: +Y plate with one knuckle, x = 0..20"
part.material_spec = "4 mm 304 stainless plate"
part.process = "cnc_router"
