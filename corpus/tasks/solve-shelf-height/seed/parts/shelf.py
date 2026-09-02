# The plate the post carries. Its underside sits at hc.shelf_z.
plate = Pos(0.0, 0.0, hc.shelf_z + hc.plate_t / 2) * Box(hc.shelf_w, hc.shelf_w, hc.plate_t)
tag(plate.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "shelf_under")
tag(plate.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "shelf_top")
part.geometry = plate
