# Project-shared namespace (script contract §4): the plate stock and the
# bracket's overall envelope live here so parts never repeat the numbers.
PARAMS = {
    "plate_t": Param(6.0, min=3.0, max=12.0),
}

# Derived interface constants, read from parts as hc.<name>.
bracket_len = 60.0
bracket_width = 40.0
bracket_height = 40.0
