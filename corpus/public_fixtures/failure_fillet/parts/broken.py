# Deliberately broken: the fillet at line 9 asks for a radius the notched
# plate cannot accept; every statement above it builds cleanly.
_w = 50.0
_d = 30.0
_t = 6.0
plate = Box(_w, _d, _t)
slot = Box(20.0, 8.0, _t)
notched = plate - slot
bad = fillet(notched.edges().filter_by(Axis.Z), radius=40.0)
part.geometry = bad
part.description = "Failure fixture: oversized fillet on a notched plate"
part.process = "cnc_router"
