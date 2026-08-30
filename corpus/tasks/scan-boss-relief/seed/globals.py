# Project-shared namespace (script contract §4): the frame's interface numbers
# live here so the part does not repeat them.
PARAMS = {
    "relief_mm": Param(2.0, min=1.5, max=4.0),
}

# Derived interface constants, read from the part as hc.<name>.
boss_x = 40.0
boss_y = 30.0
frame_x = 60.0
frame_y = 50.0
frame_z = 20.0
