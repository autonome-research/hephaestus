# Reference solution for bench task leadscrew-actuator — the frame plate.
#
# A square plate centred on the origin with the screw bore straight through it
# on the Z axis. Every interface number comes from globals.py through hc.
plate = Box(hc.frame_w, hc.frame_w, hc.frame_t)
body = plate - Cylinder(radius=hc.screw_bore_d / 2.0, height=hc.frame_t + 4.0)
body.label = "frame_body"

# The bore wall is the only cylindrical face; the travel face is the plate top.
tag(body.faces().filter_by(GeomType.CYLINDER)[0], "screw_bore")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "travel_face")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.frame_w, hc.frame_w, hc.frame_t), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 1,
}

part.description = "Actuator frame: 60 x 60 x 8 plate with the Ø10 screw bore through it"
part.material_spec = "8 mm 6061 aluminium plate"
part.process = "cnc_router"
