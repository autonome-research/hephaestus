# Independent second solution for bench task leadscrew-actuator — the carriage.
#
# The block located by its UNDERSIDE (align MIN on Z at the float gap), not by
# its centre as the reference does — same envelope, same interfaces.
body = Pos(hc.carriage_x, 0.0, hc.frame_t / 2.0 + hc.float_gap) * Box(
    hc.carriage_w,
    hc.carriage_w,
    hc.carriage_t,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
body.label = "carriage_body"

tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "guide_foot")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "nose")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.carriage_w, hc.carriage_w, hc.carriage_t), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Actuator carriage: 12 x 12 x 6 block seated on the float gap, nose up"
part.material_spec = "12 mm 6082 aluminium bar"
part.process = "cnc_router"
