# Bracket 101: L-profile bracket. All stock/envelope numbers come from the
# project namespace (hc.*) so this part never restates them.
_t = hc.plate_t              # plate + wall thickness
_len = hc.bracket_len        # X extent of both plate and wall
_width = hc.bracket_width    # Y extent of the base plate
_height = hc.bracket_height  # overall height, plate underside to wall top

_fillet_r = 4.0
_hole_d = 6.0
_hole_inset_x = 12.0   # from each end of the plate
_hole_inset_y = 14.0   # from the plate's +Y edge

_hx = _len / 2.0 - _hole_inset_x
_hy = _width / 2.0 - _hole_inset_y

# Base plate: footprint centred on the origin, underside on z = 0.
base = Pos(0, 0, _t / 2.0) * Box(_len, _width, _t)

# Wall standing on the plate's -Y edge, rising to the overall height.
_wall_y = -_width / 2.0 + _t / 2.0
wall = Pos(0, _wall_y, _height / 2.0) * Box(_len, _t, _height)

body = base + wall

# Blend the inner corner: the along-X edge where the wall's inner face
# (y = -width/2 + t) meets the top of the base plate (z = t).
_inner_y = -_width / 2.0 + _t
_inner_edge = (
    body.edges()
    .filter_by(Axis.X)
    .filter_by_position(Axis.Y, _inner_y - 0.01, _inner_y + 0.01)
    .filter_by_position(Axis.Z, _t - 0.01, _t + 0.01)
)
body = fillet(_inner_edge, radius=_fillet_r)

# Two through-holes in the base plate.
_drill = Cylinder(radius=_hole_d / 2.0, height=4.0 * _t)
body -= Pos(-_hx, _hy, _t / 2.0) * _drill
body -= Pos(_hx, _hy, _t / 2.0) * _drill

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (_len + 0.01, _width + 0.01, _height + 0.01),
    "through_holes": lambda m: m.genus("part") == 2,
    "solid_sealed": lambda m: m.sealed("part"),
}

part.description = "L-bracket 101: 60x40x6 base plate, 6 mm wall to 40 mm, 4 mm inner fillet, two 6 mm holes"
part.material_spec = "Aluminium 6061-T6"
part.process = "cnc_router"
