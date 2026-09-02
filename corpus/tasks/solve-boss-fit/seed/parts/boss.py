# The housing: a square boss with a through bore of hc.bore_r. Nothing here is
# adjustable - the bore is the interface the cap has to fit.
block = Pos(0.0, 0.0, hc.boss_h / 2) * Box(hc.boss_w, hc.boss_w, hc.boss_h)
block = block - Pos(0.0, 0.0, hc.boss_h / 2) * Cylinder(radius=hc.bore_r, height=hc.boss_h * 3)
tag(block.faces().filter_by(GeomType.CYLINDER)[0], "boss_bore")
tag(block.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "boss_top")
part.geometry = block
