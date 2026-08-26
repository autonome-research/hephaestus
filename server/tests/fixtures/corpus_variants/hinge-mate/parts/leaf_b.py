# Independent second implementation of hinge-mate leaf_b — see leaf_a.py for
# what deliberately differs from the reference solution.
_tube = Cylinder(radius=hc.knuckle_d / 2.0, height=hc.knuckle_len) - Cylinder(
    radius=hc.pin_bore_d / 2.0, height=hc.knuckle_len + 4.0
)
knuckle = Pos(hc.knuckle_len / 2.0, 0.0, hc.axis_z) * Rot(0.0, 90.0, 0.0) * _tube

plate = Pos(0.0, hc.plate_standoff, 0.0) * Box(
    hc.knuckle_len, hc.plate_w, hc.plate_t, align=(Align.MIN, Align.MIN, Align.MIN)
)
body = knuckle + plate
# Break the two outer plate corners (the vertical edges at the plate's +Y edge).
_outer_corners = body.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1]
body = chamfer(_outer_corners, length=2.0)
body.label = "leaf_b_body"

tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.AREA)[0], "pin_bore")
tag(body.faces().filter_by(Axis.X).sort_by_distance((0.0, 0.0, hc.axis_z))[0], "mate_face")
tag(body.faces().filter_by(Axis.Y).sort_by(Axis.Y)[0], "swing_edge")

part.geometry = body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 1,
}

part.description = "Hinge leaf B (variant build): tube-first knuckle, chamfered corners"
part.material_spec = "4 mm 304 stainless plate"
part.process = "cnc_router"
