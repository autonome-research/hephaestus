# Reference solution for bench task hinge-travel — the lid.
#
# One solid: the plate resting on the deck top, two hinge straps reaching the
# hinge line, and two lug barrels centred on the X-axis hinge line at z = 15
# with the 6 mm pin bore through both. Every interface number comes from
# globals.py through hc.
_lug_r = hc.lug_d / 2.0
_lug_lx = hc.lid_x0 + hc.lug_len / 2.0
_lug_rx = hc.lid_x1 - hc.lug_len / 2.0
_plate_z = hc.deck_t + hc.lid_t / 2.0

plate = Pos(
    (hc.lid_x0 + hc.lid_x1) / 2.0, (hc.lid_y0 + hc.lid_y1) / 2.0, _plate_z
) * Box(hc.lid_x1 - hc.lid_x0, hc.lid_y1 - hc.lid_y0, hc.lid_t)
strap_l = Pos(_lug_lx, (hc.strap_y0 + hc.strap_y1) / 2.0, _plate_z) * Box(
    hc.lug_len, hc.strap_y1 - hc.strap_y0, hc.lid_t
)
strap_r = Pos(_lug_rx, (hc.strap_y0 + hc.strap_y1) / 2.0, _plate_z) * Box(
    hc.lug_len, hc.strap_y1 - hc.strap_y0, hc.lid_t
)
lug_l = (
    Pos(_lug_lx, 0.0, hc.axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=_lug_r, height=hc.lug_len)
)
lug_r = (
    Pos(_lug_rx, 0.0, hc.axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=_lug_r, height=hc.lug_len)
)
body = plate + strap_l + strap_r + lug_l + lug_r
bore = (
    Pos((hc.lid_x0 + hc.lid_x1) / 2.0, 0.0, hc.axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=hc.pin_bore_d / 2.0, height=hc.lid_x1 - hc.lid_x0 + 2.0)
)
body = body - bore
body.label = "lid_body"

# The pin bore walls are the smallest cylindrical faces (the lug barrels are
# the others); one bore wall names the axis.
tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.AREA)[0], "hinge_bore")
# The plate's outer edge face at y = 38, facing away from the hinge.
tag(body.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1], "front_face")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx(
        (
            hc.lid_x1 - hc.lid_x0,
            hc.lid_y1 + hc.lug_d / 2.0,
            hc.axis_z + hc.lug_d / 2.0 - hc.deck_t,
        ),
        abs=0.05,
    ),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 2,
}

part.description = "Hinge lid: plate with two straps and two bored lug barrels"
part.material_spec = "6061 aluminium plate"
part.process = "cnc_router"
