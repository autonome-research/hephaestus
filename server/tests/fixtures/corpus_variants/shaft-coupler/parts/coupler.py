# Independent second implementation of the shaft-coupler coupler — see
# shaft.py for the rule this fixture exists to enforce.
#
# Different construction and different in-spec numbers: the sleeve is extruded
# from an annular sketch (the reference subtracts one cylinder from another),
# the bore runs 0.03 mm radial over the spindle (a different point inside the
# task's 0.02-0.08 sliding window), and the set-screw hole exits through the
# +X wall instead of +Y — the prompt asks for "a radial hole", not a heading.
_bore_r = hc.spindle_d / 2.0 + 0.03

_ring = Circle(hc.coupler_od / 2.0) - Circle(_bore_r)
sleeve = extrude(_ring, amount=hc.coupler_len)
_screw = Rot(0.0, 90.0, 0.0) * Cylinder(
    radius=hc.setscrew_d / 2.0,
    height=hc.coupler_od / 2.0 + 1.0,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
body = sleeve - Pos(0.0, 0.0, hc.coupler_len / 2.0) * _screw
body = Pos(0.0, 0.0, hc.coupler_seat_z) * body
body.label = "coupler_body"

tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[1], "bore")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "seat_end")

part.geometry = body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 2,
}

part.description = "Sleeve coupler (variant build): extruded ring, +X set-screw, 0.03 mm gap"
part.material_spec = "22 mm 6061-T6 aluminium bar"
part.process = "cnc_router"
