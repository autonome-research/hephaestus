# Independent second implementation of hinge-travel base (VALIDATION.md §1:
# every task ships a second solution so its checks provably grade the
# engineering, not the reference geometry back).
#
# Different construction: the deck and rib are laid out with align= instead of
# centred positioning, the union runs deck-first with the boss last, and the
# deck's two outer corners at the wire-channel end carry a 2 mm corner chamfer
# the reference does not — in-spec detailing a correct shop part may well
# have, which the acceptance (envelopes, the declared mechanism's clearances)
# must not punish. The rib itself is left sharp: its near top corner is the
# governing point of the swept clearance.
_boss_len = hc.boss_x1 - hc.boss_x0

deck = Pos(0.0, hc.deck_y0, 0.0) * Box(
    hc.deck_l, hc.deck_w, hc.deck_t, align=(Align.MIN, Align.MIN, Align.MIN)
)
# Break the deck's two outer corners at the +Y edge (the vertical edges).
_outer_corners = deck.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1]
deck = chamfer(_outer_corners, length=2.0)

rib = Pos(hc.chan_x0, hc.chan_y0, hc.deck_t) * Box(
    hc.chan_len, hc.chan_w, hc.chan_h, align=(Align.MIN, Align.MIN, Align.MIN)
)
pedestal = Pos(hc.boss_x0, -hc.ped_w / 2.0, hc.deck_t) * Box(
    _boss_len, hc.ped_w, hc.axis_z - hc.deck_t, align=(Align.MIN, Align.MIN, Align.MIN)
)
boss = (
    Pos((hc.boss_x0 + hc.boss_x1) / 2.0, 0.0, hc.axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=hc.boss_d / 2.0, height=_boss_len)
)
body = deck + rib + pedestal + boss
body = body - (
    Pos((hc.boss_x0 + hc.boss_x1) / 2.0, 0.0, hc.axis_z)
    * Rot(0.0, 90.0, 0.0)
    * Cylinder(radius=hc.pin_bore_d / 2.0, height=_boss_len + 4.0)
)
body.label = "base_body"

tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.AREA)[0], "hinge_bore")
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
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 1,
}

part.description = "Hinge base (variant build): align-laid deck, chamfered corners"
part.material_spec = "6061 aluminium plate"
part.process = "cnc_router"
