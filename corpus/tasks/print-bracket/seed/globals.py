# Project-shared namespace (script contract §4): the printed bracket's
# dimensions. Parts read every name as hc.<name>.
PARAMS = {
    "wall_t": Param(6.0, min=1.5, max=10.0, doc="printed wall thickness, mm"),
}

# Overall.
bracket_width = 30.0
upright_height = 40.0
arm_reach = 30.0

# The ramp under the arm: it starts on the upright at this height and reaches the
# arm's underside at the tip at ramp_top_z.
ramp_base_z = 4.0
ramp_top_z = 34.0

# Fixing bore through the arm.
bore_dia = 4.0
bore_y = 27.0
