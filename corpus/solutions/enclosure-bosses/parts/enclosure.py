# Reference solution for bench task enclosure-bosses — the printed box.
#
# A shelled project box, open at the top, with four internal screw bosses
# standing on the floor. Wall and floor thicknesses come from the project
# params, so the DFM minimum-wall rule is a parameter, not a magic number.
_wall = hc.wall_t
_floor = hc.floor_t

_outer = Box(
    hc.box_len, hc.box_width, hc.box_height, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_cavity = Pos(0, 0, _floor) * Box(
    hc.box_len - 2.0 * _wall,
    hc.box_width - 2.0 * _wall,
    hc.box_height - _floor,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
shell = _outer - _cavity

# Four bosses on the floor, each bored for a self-tapping screw.
bosses = []
for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        _boss = Pos(_sx * hc.boss_x, _sy * hc.boss_y, _floor) * Cylinder(
            radius=hc.boss_d / 2.0,
            height=hc.boss_top_z - _floor,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        _pilot = Pos(_sx * hc.boss_x, _sy * hc.boss_y, hc.boss_top_z - hc.pilot_depth) * Cylinder(
            radius=hc.pilot_d / 2.0,
            height=hc.pilot_depth,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        bosses.append(_boss - _pilot)

body = shell
for _boss in bosses:
    body = body + _boss
body.label = "enclosure_body"

tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "print_bed_face")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.box_len, hc.box_width, hc.box_height), abs=0.05),
    "one_sealed_solid": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "FDM project box: shelled enclosure with four screw bosses"
part.material_spec = "PETG, 3 perimeters"
part.process = "fdm"
part.general_tolerance = "+/-0.3 mm as printed"
part.feature("print_bed_face").surface_finish = "First layer; keep flat, no elephant foot"
