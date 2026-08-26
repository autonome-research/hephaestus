# Independent second implementation of the shaft-coupler shaft (VALIDATION.md
# §1: the second solution proves the checks grade correctness, not the
# reference construction back).
#
# Different decomposition: a full-length Ø12 rod with the Ø20 hub unioned
# around its base — the reference stacks a short spindle on top of the hub.
rod = Cylinder(
    radius=hc.spindle_d / 2.0,
    height=hc.shaft_len,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
hub = Cylinder(
    radius=hc.hub_d / 2.0, height=hc.hub_h, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
body = rod + hub
body.label = "shaft_body"

tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "spindle")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[1], "shoulder")

part.geometry = body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Stepped shaft (variant build): full-length rod with a hub around its base"
part.material_spec = "20 mm 1045 steel bar"
part.process = "cnc_router"
