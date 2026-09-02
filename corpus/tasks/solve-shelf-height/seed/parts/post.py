# The column the shelf seats on. Its height is a declared, bounded knob.
PARAMS = {
    "post_h": Param(20.0, min=5.0, max=60.0),
}

column = Pos(0.0, 0.0, p.post_h / 2) * Box(hc.post_w, hc.post_w, p.post_h)
tag(column.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "post_top")
tag(column.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "post_bottom")
part.geometry = column
