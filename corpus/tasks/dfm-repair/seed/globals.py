# Project-shared namespace (script contract §4): the sheet stock and the two
# feature sizes the shop signed off on. Parts read every name as hc.<name>
# instead of repeating the numbers.
PARAMS = {
    "sheet_t": Param(6.0, min=3.0, max=12.0, doc="sheet stock thickness, mm"),
}

# Panel blank.
panel_len = 80.0
panel_width = 50.0

# Service notch, cut in from the +Y edge.
notch_len = 16.0
notch_depth = 10.0
notch_x = -20.0

# The two sizes the laser shop signed off on: the vent bore diameter and the
# radius the notch's two inner corners must carry.
vent_bore_dia = 6.0
vent_x = 20.0
notch_corner_radius = 3.0
