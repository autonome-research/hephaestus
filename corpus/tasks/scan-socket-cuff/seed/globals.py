# Project-shared namespace (script contract §4): the cuff's interface numbers
# live here so the part does not repeat them.
PARAMS = {
    "wall_mm": Param(4.0, min=3.0, max=6.0),
}

# Derived interface constants, read from the part as hc.<name>.
cuff_bore_r = 27.0
# 70 mm: the cuff runs PAST both ends of the 60 mm scan on purpose. The
# tessellated scan carries its vertices at the two rims (z = +/-30), and a cuff
# that stopped short of them would be measured against the rim corner rather
# than against its own bore — a clearance number that is real but is not the
# clearance the task is about.
cuff_height = 70.0
