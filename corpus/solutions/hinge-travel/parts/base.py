# Reference solution for bench task hinge-travel — the deck-and-boss base.
#
# One solid: the deck plate, the pedestal carrying the hinge boss on the
# X-axis hinge line at z = 15, a 6 mm pin bore through boss and pedestal, and
# the wire-channel rib on the deck top. Every interface number comes from
# globals.py through hc.
_boss_len = hc.boss_x1 - hc.boss_x0
_boss_x_mid = (hc.boss_x0 + hc.boss_x1) / 2.0

deck = Pos(hc.deck_l / 2.0, hc.deck_y0 + hc.deck_w / 2.0, hc.deck_t / 2.0) * Box(
    hc.deck_l, hc.deck_w, hc.deck_t
)
pedestal = Pos(_boss_x_mid, 0.0, (hc.deck_t + hc.axis_z) / 2.0) * Box(
    _boss_len, hc.ped_w, hc.axis_z - hc.deck_t
)
boss = (
    Pos(_boss_x_mid, 0.0, hc.axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=hc.boss_d / 2.0, height=_boss_len)
)
rib = Pos(
    hc.chan_x0 + hc.chan_len / 2.0,
    hc.chan_y0 + hc.chan_w / 2.0,
    hc.deck_t + hc.chan_h / 2.0,
) * Box(hc.chan_len, hc.chan_w, hc.chan_h)
body = deck + pedestal + boss + rib
bore = (
    Pos(_boss_x_mid, 0.0, hc.axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=hc.pin_bore_d / 2.0, height=_boss_len + 2.0)
)
body = body - bore
body.label = "base_body"

# The pin bore is the smaller of the two cylindrical faces (the boss is the other).
tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.AREA)[0], "hinge_bore")
# The wire-channel rib's face toward the hinge (the vertical face at y = 40).
tag(
    body.faces()
    .filter_by(Axis.Y)
    .sort_by_distance(
        (hc.chan_x0 + hc.chan_len / 2.0, hc.chan_y0, hc.deck_t + hc.chan_h / 2.0)
    )[0],
    "wire_channel",
)

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.deck_l, hc.deck_w, hc.axis_z + hc.boss_d / 2.0), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 1,
}

part.description = "Hinge base: deck, pedestal-mounted bored boss, wire-channel rib"
part.material_spec = "6061 aluminium plate"
part.process = "cnc_router"
