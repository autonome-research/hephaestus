# Reference solution for bench task dfm-repair.
#
# The repair is exactly the two placeholder sizes: the vent bore diameter and the
# notch corner radius now come from globals.py like every other dimension in the
# script. Nothing else about the design changes — same blank, same notch, same
# bore position — so the envelope check still passes and the volume check pins
# both repaired features (a 6 mm bore removes 169.65 mm^3 where the 0.5 mm one
# removed 1.18, and two R3 corners add 23.18 mm^3 of material where R0.3 added
# 0.23).
_t = hc.sheet_t

panel = Pos(0.0, 0.0, _t / 2.0) * Box(hc.panel_len, hc.panel_width, _t)

# Service notch, open at the +Y edge.
_notch_y = hc.panel_width / 2.0 - hc.notch_depth / 2.0
panel = panel - Pos(hc.notch_x, _notch_y, _t / 2.0) * Box(
    hc.notch_len, hc.notch_depth, 4.0 * _t
)

# The notch's two inner corners get the radius the shop signed off on: the beam
# cannot turn a corner tighter than its own kerf radius.
_inner_y = hc.panel_width / 2.0 - hc.notch_depth
_corners = [e for e in panel.edges().filter_by(Axis.Z) if abs(e.center().Y - _inner_y) < 1e-6]
panel = fillet(_corners, hc.notch_corner_radius)

# Vent bore, at the signed-off diameter: a bore near the kerf width fills with
# slag instead of cutting through.
panel = panel - Pos(hc.vent_x, 0.0, _t / 2.0) * Cylinder(hc.vent_bore_dia / 2.0, 4.0 * _t)
_bore = [
    f for f in panel.faces() if f.geom_type == GeomType.CYLINDER and abs(f.center().Y) < 1e-6
][0]
tag(_bore, "vent_bore")

part.geometry = panel

part.description = "Fan-shroud vent panel: notched blank with a single vent bore"
part.process = "laser_cut"
part.material_spec = "6 mm Baltic birch plywood"
part.stock_form = "sheet"
