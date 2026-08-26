# Project-shared namespace (script contract §4): the hinge interface both
# leaves (and the seeded pin gauge) build against lives here, so parts never
# repeat the numbers.
PARAMS = {}

# The hinge line is the X axis at z = axis_z: the knuckle barrel sits above
# the plate (a formed hinge), its underside 2 mm above the table the plate
# lies on, and the plate merges into the barrel's flank.
axis_z = 7.0
plate_t = 4.0
# Each leaf: one knuckle_len (X) of hinge line, a plate plate_w deep in Y.
knuckle_len = 20.0
plate_w = 30.0
# Knuckle barrel and pin bore, both centred on the hinge axis.
knuckle_d = 10.0
pin_bore_d = 6.0
# Each plate's inner edge stops this far short of the axis, so the two plates
# keep a 2 x plate_standoff swing gap across the joint.
plate_standoff = 3.5
