# Project-shared namespace (script contract §4): the hinge interface both the
# base and the lid build against lives here, so parts never repeat the numbers.
PARAMS = {}

# The hinge line is the X axis at y = 0, z = axis_z: the lid lies closed on
# the deck top and swings up and over the pedestal-mounted boss.
axis_z = 15.0

# Base deck: x = 0..deck_l, y = deck_y0..deck_y0 + deck_w, underside on z = 0.
deck_l = 60.0
deck_w = 68.0
deck_y0 = -20.0
deck_t = 8.0

# Hinge boss on its pedestal, both spanning x = boss_x0..boss_x1 on the axis.
boss_x0 = 20.0
boss_x1 = 40.0
ped_w = 10.0
boss_d = 12.0
pin_bore_d = 6.0

# Wire-channel rib on the deck top at y = chan_y0..chan_y0 + chan_w: the run
# of the deck the swinging lid must never crowd. Its clearance numbers are
# graded through the declared mechanism (KINEMATICS.md), not through CHECKS.
chan_x0 = 15.0
chan_len = 30.0
chan_y0 = 40.0
chan_w = 4.0
chan_h = 3.0

# Lid: a plate on the deck top, two hinge straps, two bored lug barrels on
# the hinge axis. The lug barrels ride 1 mm clear of the deck (their radius
# is boss_d / 2 = 6 mm about the axis at z = 15, over the deck top at z = 8).
lid_x0 = 5.0
lid_x1 = 55.0
lid_y0 = 8.0
lid_y1 = 38.0
lid_t = 4.0
strap_y0 = 0.0
strap_y1 = 10.0
lug_len = 13.0
lug_d = 12.0

# Declared travel: closed flat (0 deg) to full open.
travel_deg = 110.0
