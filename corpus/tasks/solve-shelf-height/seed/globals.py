# Project-shared namespace (script contract §4). The shelf's height above the
# base is a declared, bounded knob: it is the thing this task is about, so it
# is a Param and not a literal buried in a part.
PARAMS = {
    "shelf_z": Param(10.0, min=0.0, max=60.0),
}

# Derived interface constants, read from the parts as hc.<name>.
plate_t = 6.0
shelf_w = 50.0
post_w = 12.0
