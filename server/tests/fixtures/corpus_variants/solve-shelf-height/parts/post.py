# Second independent solution: the post's height is authored as the Param's own
# default, and the column is built from the top face down rather than from the
# base up - different construction, same delivered geometry.
PARAMS = {
    "post_h": Param(40.0, min=5.0, max=60.0),
}

column = Box(hc.post_w, hc.post_w, p.post_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
tag(column.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "post_top")
tag(column.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "post_bottom")
part.geometry = column
