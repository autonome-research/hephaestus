# Project-shared namespace for the assembly fixture (script contract §4).
# Parts read every public name here as hc.<name>; the PARAMS below are the
# project's user-tunable knobs, everything else is derived from them.
PARAMS = {
    "sheet_t": Param(6.0, min=3, max=12),
    "joint_clear": Param(0.3, min=0, max=0.8),
}

# Derived constants — one home per number. They change when the params they
# derive from change; parts never duplicate these values.
shelf_w = 180.0
shelf_d = 120.0
post_h = 90.0
post_side = 3.0 * p.sheet_t
frame_h = post_h + 2.0 * p.sheet_t
