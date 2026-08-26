# Reference solution for bench task shaft-coupler — the stepped shaft.
#
# A Ø20 hub standing on the XY plane with a Ø12 spindle rising coaxially from
# its top face to 58 mm overall. Every interface number comes from globals.py.
hub = Cylinder(
    radius=hc.hub_d / 2.0, height=hc.hub_h, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
spindle = Pos(0.0, 0.0, hc.hub_h) * Cylinder(
    radius=hc.spindle_d / 2.0,
    height=hc.shaft_len - hc.hub_h,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
body = hub + spindle
body.label = "shaft_body"

# The spindle is the smaller-radius cylindrical face; the hub wall the larger.
tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "spindle")
# Z-normal planar faces bottom-up: hub base, hub shoulder, spindle top.
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[1], "shoulder")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part") == approx((hc.hub_d, hc.hub_d, hc.shaft_len), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Stepped shaft: Ø20 x 8 hub under a Ø12 spindle, 58 mm overall"
part.material_spec = "12 mm 1045 steel bar"
part.process = "cnc_router"
