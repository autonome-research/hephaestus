# Reference solution for bench task leadscrew-actuator — the screw pilot.
#
# A plain Ø9.8 pilot cylinder standing in the frame's Ø10 bore (0.1 mm radial
# air), its lower end flush with the plate underside. The thread itself is not
# modelled: the transmission is the declared coupling (KINEMATICS.md §5), and
# whether a physical thread could carry it is out of the mechanism's scope.
body = Pos(0.0, 0.0, (hc.screw_len - hc.frame_t) / 2.0) * Cylinder(
    radius=hc.screw_pilot_d / 2.0, height=hc.screw_len
)
body.label = "screw_body"

tag(body.faces().filter_by(GeomType.CYLINDER)[0], "screw_pilot")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.screw_pilot_d, hc.screw_pilot_d, hc.screw_len), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Lead screw pilot: Ø9.8 x 30, lower end flush with the frame underside"
part.material_spec = "10 mm 1045 steel bar"
part.process = "cnc_router"
