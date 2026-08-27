# Reference solution for bench task leadscrew-actuator — the carriage block.
#
# A square block riding beside the screw at x = 18, floating 0.5 mm above the
# plate top at the zero configuration. The underside is the prismatic guide
# interface; the top face is the nose the reach acceptance measures to.
_z_mid = hc.frame_t / 2.0 + hc.float_gap + hc.carriage_t / 2.0
body = Pos(hc.carriage_x, 0.0, _z_mid) * Box(hc.carriage_w, hc.carriage_w, hc.carriage_t)
body.label = "carriage_body"

tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "guide_foot")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "nose")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.carriage_w, hc.carriage_w, hc.carriage_t), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Actuator carriage: 12 x 12 x 6 block on the guide, nose up"
part.material_spec = "12 mm acetal bar"
part.process = "cnc_router"
