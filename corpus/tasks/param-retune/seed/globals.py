# Project-shared namespace (script contract §4). Every dimension of this shelf
# is a project parameter: the part scripts only combine them, so re-sizing the
# shelf is a parameter change, never a geometry edit.
PARAMS = {
    "panel_t": Param(18.0, min=9.0, max=30.0, doc="plywood panel thickness, mm"),
    "shelf_w": Param(300.0, min=150.0, max=600.0, doc="tread width along X, mm"),
    "shelf_d": Param(200.0, min=100.0, max=400.0, doc="tread depth out from the wall, mm"),
    "corner_r": Param(25.0, min=5.0, max=60.0, doc="front corner radius, mm"),
    "gusset_reach": Param(140.0, min=60.0, max=380.0, doc="gusset reach out from the wall, mm"),
    "gusset_drop": Param(160.0, min=60.0, max=400.0, doc="gusset drop below the tread, mm"),
}

# The wall face. Parts read this instead of assuming where the wall is.
wall_face_y = 0.0
