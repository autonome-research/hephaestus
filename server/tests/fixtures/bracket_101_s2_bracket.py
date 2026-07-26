PARAMS = {
    "wall_thick": Param(6.0, min=2.0, max=10.0),
    "hole_d": Param(6.0, min=4.0, max=10.0),
}

# Base plate: 60 x 40 x 6, centered on origin, underside at z=0
base = Box(hc.bracket_len, hc.bracket_width, hc.plate_t,
           align=(Align.CENTER, Align.CENTER, Align.MIN))

# Wall: 60mm long (X), wall_thick thick (Y), rises to bracket_height
# Positioned flush against base -Y face; extends outward in -Y
wall = Box(hc.bracket_len, p.wall_thick, hc.bracket_height,
           align=(Align.CENTER, Align.MIN, Align.MIN))
wall = Pos(0, -hc.bracket_width / 2 - p.wall_thick, 0) * wall

# Fuse base and wall
bracket = base + wall

# Fillet the inner corner where wall meets top of base plate
# Edge runs along X at Y = -20, Z = 6 (wall outer face / base top junction)
inner_edges = bracket.edges().filter_by(
    lambda e: abs(e.center().Y + hc.bracket_width / 2) < 1
    and abs(e.center().Z - hc.plate_t) < 1
)
bracket = fillet(inner_edges, radius=4)

# Drill two through-holes in the base plate
# Centres: 12mm in from each X end => x = ±(30-12) = ±18
#          14mm in from the +Y edge  => y = 20-14 = 6
_hole_r = p.hole_d / 2
_hole_y = hc.bracket_width / 2 - 14
_hole_x = hc.bracket_len / 2 - 12

hole1 = Pos(-_hole_x, _hole_y, 0) * Cylinder(
    radius=_hole_r, height=hc.plate_t + 1,
    align=(Align.CENTER, Align.CENTER, Align.MIN))
hole2 = Pos(_hole_x, _hole_y, 0) * Cylinder(
    radius=_hole_r, height=hc.plate_t + 1,
    align=(Align.CENTER, Align.CENTER, Align.MIN))

bracket = bracket - hole1 - hole2

# Tag top and bottom faces
tag(bracket.faces().sort_by(Axis.Z)[-1], "top_face")
tag(bracket.faces().sort_by(Axis.Z)[0], "bottom_face")

part.geometry = bracket

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (60.1, 46.1, 40.1),
    "sealed": lambda m: m.sealed("part"),
}

part.description = "L-bracket 60x40x40 with 2x M6 holes"
part.material_spec = "Al 6082-T6 sheet"
part.process = "laser_cut_bend"