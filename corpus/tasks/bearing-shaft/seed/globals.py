# Project-shared namespace (script contract §4): the shaft's interface numbers
# live here so neither part repeats them.
PARAMS = {
    "journal_d": Param(7.98, min=7.9, max=8.0),
}

# Derived interface constants, read from parts as hc.<name>.
shaft_len = 60.0
collar_d = 12.0
collar_from = 13.0
collar_to = 47.0
bearing_a_z = 6.0
bearing_b_z = 47.0
