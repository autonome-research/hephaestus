# The wall the shelf mounts to: reference geometry for the acceptance checks.
# The wall face is the plane y = 0 and the wall itself lies behind it (negative
# Y). Do not change this part.
wall = Pos(0.0, -10.0, -100.0) * Box(700.0, 20.0, 400.0)
part.geometry = wall
part.description = "Wall plane the shelf mounts against (reference geometry)"
