# The cap: a flange with a spigot that drops into the boss's bore. The spigot's
# radius is the declared, bounded knob this task is about.
PARAMS = {
    "spigot_r": Param(8.0, min=6.0, max=8.0),
}

flange = Pos(0.0, 0.0, hc.boss_h + hc.cap_t / 2) * Cylinder(radius=hc.cap_r, height=hc.cap_t)
spigot = Pos(0.0, 0.0, hc.boss_h - hc.spigot_len / 2) * Cylinder(
    radius=p.spigot_r, height=hc.spigot_len
)
body = flange + spigot
tag(
    body.faces()
    .filter_by(GeomType.CYLINDER)
    .sort_by(SortBy.RADIUS)[0],
    "cap_spigot",
)
part.geometry = body
