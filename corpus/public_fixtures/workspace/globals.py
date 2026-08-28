# Project-shared namespace for the workspace fixture (script contract §4).
#
# One sheet, one thickness: every part in this project is a profile nested in the
# SAME sheet, so the stock thickness is a project-scope parameter and no part
# carries its own copy of it. Parts read every public name here as hc.<name>.
PARAMS = {
    # 5.5 mm is DELIBERATELY off the Baltic-birch stock ladder (3/6/12/18 mm in
    # registries/materials/plywood-baltic-birch.json). It is the fixture's
    # `laser_cut.sheet_thickness_match` violation, and it is a *parameter* so the
    # violation can be cleared by moving a slider rather than by editing a
    # script — which is what makes it a usable DFM demonstration.
    "sheet_t": Param(5.5, min=3.0, max=12.0),
}

# Derived constants — one home per number.
tread_w = 250.0
tread_d = 90.0

# Anti-slip grooves: blind pockets, inset from both long edges so the walking
# surface stays ONE face (the face `tread_top` tags).
groove_w = 3.0
groove_depth = 1.5
groove_margin = 20.0

# A drainage bore 0.5 mm across: below the pack's 0.8 mm minimum cut feature.
drain_r = 0.25

# The service notch and the internal corner radius the beam cannot turn.
notch_w = 20.0
notch_d = 14.0
notch_radius = 0.3

# Cleat blanks, nested beside the tread in the same sheet.
cleat_w = 40.0
cleat_d = 25.0
sheet_gap = 8.0
