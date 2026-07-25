# Project-shared namespace (script contract §4): the enclosure's outer envelope,
# its print-process wall rules, and the boss/lid interface. The box stands on
# z = 0 and opens upwards.
PARAMS = {
    "wall_t": Param(2.0, min=1.6, max=4.0, doc="side wall thickness, mm"),
    "floor_t": Param(2.5, min=1.6, max=5.0, doc="floor thickness, mm"),
    "lid_clearance": Param(0.2, min=0.0, max=0.6, doc="lip-to-cavity clearance per side, mm"),
}

# Outer envelope of the box.
box_len = 80.0
box_width = 60.0
box_height = 30.0

# Minimum printable wall for this process — the DFM limit the checks measure.
min_wall = 1.6

# Screw bosses: four of them, on this rectangular pattern, standing on the floor.
boss_x = 30.0
boss_y = 20.0
boss_d = 8.0
boss_top_z = 24.0
pilot_d = 3.2
pilot_depth = 15.0

# Lid.
lid_t = 3.0
lid_lip_h = 2.0
lid_hole_d = 3.4
