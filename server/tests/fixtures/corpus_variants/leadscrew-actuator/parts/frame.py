# Independent second solution for bench task leadscrew-actuator — the frame.
#
# Deliberately a different construction from the reference (KINEMATICS.md §6,
# corpus v3 dual-solution rule): the plate is an extruded sketch located by
# its underside, and the bore is an extruded circle cut through it — same
# interface, different modelling path.
_underside = -hc.frame_t / 2.0
blank = Pos(0.0, 0.0, _underside) * extrude(
    Rectangle(hc.frame_w, hc.frame_w), amount=hc.frame_t
)
bore = Pos(0.0, 0.0, _underside - 1.0) * extrude(
    Circle(hc.screw_bore_d / 2.0), amount=hc.frame_t + 2.0
)
body = blank - bore
body.label = "frame_body"

tag(body.faces().filter_by(GeomType.CYLINDER)[0], "screw_bore")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "travel_face")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.frame_w, hc.frame_w, hc.frame_t), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 1,
}

part.description = "Actuator frame: extruded 60 x 60 x 8 plate, Ø10 bore cut through"
part.material_spec = "8 mm 5083 aluminium tooling plate"
part.process = "cnc_router"
