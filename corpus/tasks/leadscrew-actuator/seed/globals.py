# Project-shared namespace (script contract §4): the actuator interface all
# three parts (and the acceptance) build against lives here, so parts never
# repeat the numbers.
PARAMS = {}

# Frame plate, square in plan, centred on the origin: z in [-frame_t/2, +frame_t/2].
frame_w = 60.0
frame_t = 8.0
# Screw pilot bore through the plate on the Z axis, and the pilot that rides it
# (0.1 mm radial air).
screw_bore_d = 10.0
screw_pilot_d = 9.8
# The screw stands this long on the bore axis, its lower end flush with the
# plate underside: z in [-frame_t/2, screw_len - frame_t/2].
screw_len = 30.0
# Carriage block beside the screw (+X), floating float_gap above the plate top
# at the zero configuration.
carriage_w = 12.0
carriage_t = 6.0
carriage_x = 18.0
float_gap = 0.5
# The transmission: a metric Tr-style lead of 2 mm carriage travel per screw
# revolution (2/360 mm per degree), ten turns of motor travel end to end.
lead_mm = 2.0
motor_travel_deg = 3600.0
# Declared carriage travel window: the 20 mm working stroke plus overtravel
# margin to the hard stop.
stroke_mm = 20.0
carriage_travel_mm = 24.0
