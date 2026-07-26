# Project-shared namespace (script contract §4): the sheet stock, the blank the
# shop cuts each set from, and the three laminations' flat sizes. Parts read
# every name as hc.<name>.
PARAMS = {
    "sheet_t": Param(6.0, min=3.0, max=12.0, doc="sheet stock thickness, mm"),
}

# The blank one set of laminations is cut from.
blank_len = 210.0
blank_width = 125.0

# Web: a right triangle, legs along X and Y.
web_leg_x = 100.0
web_leg_y = 60.0

# Spacer and cleat: rectangles.
spacer_len = 60.0
spacer_width = 40.0
cleat_len = 90.0
cleat_width = 25.0
