# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). It is the mounting wall itself — an 8 mm slab of
# drywall filling y = -8 .. 0 over the whole working area.
#
# A correctly mounted shelf touches this face (clearance 0) and never cuts into
# it (interference 0), which is how the acceptance checks measure that the parts
# sit against the wall instead of floating in front of it or sinking into it.
_wall = Pos(0, -4.0, 0) * Box(500.0, 8.0, 520.0)
_wall.label = "wall_face"

part.geometry = _wall

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part") == approx((500.0, 8.0, 520.0), abs=0.01),
}

part.description = "Mounting-wall gauge: the y = 0 wall face"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
