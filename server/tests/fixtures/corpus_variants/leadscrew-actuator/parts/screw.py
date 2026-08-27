# Independent second solution for bench task leadscrew-actuator — the screw.
#
# The pilot as a turned part: its half-section revolved about the Z axis
# (the way a lathe sees it), rather than the reference's positioned Cylinder.
_bottom = -hc.frame_t / 2.0
_section = (
    Plane.XZ
    * Pos(hc.screw_pilot_d / 4.0, _bottom + hc.screw_len / 2.0)
    * Rectangle(hc.screw_pilot_d / 2.0, hc.screw_len)
)
body = revolve(_section, Axis.Z)
body.label = "screw_body"

tag(body.faces().filter_by(GeomType.CYLINDER)[0], "screw_pilot")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.screw_pilot_d, hc.screw_pilot_d, hc.screw_len), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Lead screw pilot, revolved half-section: Ø9.8 x 30 on the bore axis"
part.material_spec = "10 mm 303 stainless bar"
part.process = "cnc_router"
