# Project-shared namespace (script contract §4): the sheet stock, the cutting
# kerf and the tray's interface dimensions. Parts read every name as hc.<name>
# instead of repeating the numbers.
PARAMS = {
    "sheet_t": Param(6.0, min=3.0, max=12.0, doc="sheet stock thickness, mm"),
    "kerf": Param(0.2, min=0.0, max=1.0, doc="slot clearance added around every tab, mm"),
}

# Base panel blank.
base_len = 110.0
base_width = 90.0

# Assembled wall box (outer faces), and the wall height above the base.
box_len = 100.0
box_width = 80.0
wall_height = 40.0

# Tab-and-slot joint: each wall carries two tabs on its bottom edge, one sheet
# thickness deep, centred a quarter of the wall's length in from each end.
tab_len = 12.0
