# Project-shared namespace (script contract §4). The shop only stocks one panel
# thickness for this job, and the mounting wall is the y = 0 plane: everything
# the shelf is made of lives at y >= 0, with +Z up.
PARAMS = {
    "panel_t": Param(18.0, min=9.0, max=30.0, doc="plywood panel thickness, mm"),
}

# The wall face. Parts read this instead of assuming where the wall is.
wall_face_y = 0.0
