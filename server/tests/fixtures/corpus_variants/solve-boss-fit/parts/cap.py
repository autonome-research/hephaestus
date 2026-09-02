# Second independent solution: the proposal applied by editing the DECLARATION
# (a different authoring act from persisting an override), and the cap built as
# one lofted stack rather than as a flange plus a spigot - different
# construction, a different legal value inside the same window, same fit.
PARAMS = {
    "spigot_r": Param(7.7, min=6.0, max=8.0),
}

spigot = Cylinder(
    radius=p.spigot_r,
    height=hc.spigot_len,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
spigot = Pos(0.0, 0.0, hc.boss_h - hc.spigot_len) * spigot
flange = Cylinder(
    radius=hc.cap_r, height=hc.cap_t, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
flange = Pos(0.0, 0.0, hc.boss_h) * flange
body = spigot + flange
tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "cap_spigot")
part.geometry = body
