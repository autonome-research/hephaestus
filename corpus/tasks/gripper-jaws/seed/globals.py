# Project-shared namespace (script contract §4): the gripper interface both
# parts (and the declared mechanism) build against lives here, so parts never
# repeat the numbers.
PARAMS = {}

# The body: a rectangular base resting on the XY plane with a corner at the
# origin, carrying the fixed jaw at its +X end.
base_l = 60.0
base_w = 30.0
base_t = 10.0

# Both jaws share one block size: jaw_w thick in X, the full base_w wide,
# jaw_h tall above the base top.
jaw_w = 10.0
jaw_h = 20.0

# The fixed jaw's gripping face lies on the plane x = fixed_face_x (the block
# spans fixed_face_x .. base_l). The sliding jaw is authored fully OPEN with
# its gripping face at x = jaw_face_x, and closes by sliding +X.
fixed_face_x = 50.0
jaw_face_x = 22.0

# The declared jaw travel (mm) and the gaps between the gripping faces at the
# ends of it: open_gap as built (travel 0), closed_gap at full travel — the
# gripping envelope for the flat stock this gripper handles.
travel = 25.0
open_gap = 28.0
closed_gap = 3.0
