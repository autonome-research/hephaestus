# Vent panel for the fan shroud, cut from one sheet of 6 mm ply.
#
# The blank, the notch and the bore position all come from globals.py. The two
# feature *sizes* were typed straight into this script while the shop's numbers
# were still being confirmed, and were never replaced.
_t = hc.sheet_t

panel = Pos(0.0, 0.0, _t / 2.0) * Box(hc.panel_len, hc.panel_width, _t)

# Service notch, open at the +Y edge.
_notch_y = hc.panel_width / 2.0 - hc.notch_depth / 2.0
panel = panel - Pos(hc.notch_x, _notch_y, _t / 2.0) * Box(
    hc.notch_len, hc.notch_depth, 4.0 * _t
)

# The notch's two inner corners get a radius so the beam does not have to stop.
_inner_y = hc.panel_width / 2.0 - hc.notch_depth
_corners = [e for e in panel.edges().filter_by(Axis.Z) if abs(e.center().Y - _inner_y) < 1e-6]
panel = fillet(_corners, 0.3)

# Vent bore.
panel = panel - Pos(hc.vent_x, 0.0, _t / 2.0) * Cylinder(0.25, 4.0 * _t)
_bore = [
    f for f in panel.faces() if f.geom_type == GeomType.CYLINDER and abs(f.center().Y) < 1e-6
][0]
tag(_bore, "vent_bore")

part.geometry = panel

part.description = "Fan-shroud vent panel: notched blank with a single vent bore"
part.process = "laser_cut"
part.material_spec = "6 mm Baltic birch plywood"
part.stock_form = "sheet"
