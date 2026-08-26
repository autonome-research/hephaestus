# Project-shared namespace (script contract §4): the shaft/coupler interface
# lives here so both parts build against the same numbers.
PARAMS = {}

# The shaft stands on the XY plane, axis +Z.
hub_d = 20.0
hub_h = 8.0
spindle_d = 12.0
shaft_len = 58.0
# The coupler sleeve, and where its lower end face seats above z = 0
# (12 mm above the hub shoulder at z = hub_h).
coupler_od = 22.0
coupler_len = 30.0
coupler_seat_z = 20.0
setscrew_d = 4.0
# The sliding fit the coupler is bored for: radial clearance window on the
# spindle, in mm (min, max).
fit_clearance_min = 0.02
fit_clearance_max = 0.08
