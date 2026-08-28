# The riser board that closes the gap under a tread. One solid, no tags, no
# grooves: the project's second part exists so the workspace's project tree, its
# part switcher and `GET /parts` are never a one-row list, and so the cross-part
# check in checks/ has a second operand.
riser = Box(hc.tread_w, 140.0, hc.sheet_t)
riser.label = "riser"
part.geometry = riser

part.description = "Riser board, cut from the same sheet as the tread"
part.material_spec = "Baltic birch plywood (BB/BB) sheet"
part.process = "laser_cut"
part.stock_form = "sheet"
part.general_tolerance = "+/-0.25 mm cut profile"
