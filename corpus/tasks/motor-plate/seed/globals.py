# Project-shared namespace (script contract §4): the mounting interface lives
# here so the plate never repeats a number the motor already fixes.
PARAMS = {
    "plate_t": Param(8.0, min=6.0, max=12.0),
}

# Derived interface constants, read from parts as hc.<name>.
plate_side = 60.0
mount_z = 8.0
pilot_recess_d = 22.2
pilot_recess_depth = 2.2
shaft_clearance_d = 6.0
bolt_clearance_d = 3.4
# The motor is instanced at rz = 45, so its 31 mm square bolt pattern lands on
# the plate's axes at 15.5 * sqrt(2) from the shaft centre.
bolt_radius = 21.920310216783
