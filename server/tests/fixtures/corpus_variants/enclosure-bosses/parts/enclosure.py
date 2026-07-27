# Variant solution for enclosure-bosses — deliberately NOT the reference.
#
# Same specification, different design decisions and a different construction
# order: the shell is *assembled* from a floor slab and four wall slabs instead
# of being a box with a cavity cut out of it, the bosses are placed from an
# explicit coordinate table, and the base carries a 0.3 mm elephant-foot chamfer
# — an ordinary FDM detail the task neither asks for nor forbids.
#
# This file exists to fail the corpus audit if a check ever demands the
# reference geometry back: it costs ~13 mm^3 of the minimum-wall shell (the old
# +/-5 mm^3 window would have failed it) and moves the box's material volume,
# while every functional property the task states still holds.
_w = hc.wall_t
_f = hc.floor_t
_inner_x = hc.box_len - 2.0 * _w
_inner_y = hc.box_width - 2.0 * _w

floor = Box(hc.box_len, hc.box_width, _f, align=(Align.CENTER, Align.CENTER, Align.MIN))

_wall_h = hc.box_height - _f
walls = []
for _sy in (-1.0, 1.0):
    walls.append(
        Pos(0.0, _sy * (hc.box_width - _w) / 2.0, _f)
        * Box(hc.box_len, _w, _wall_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    )
for _sx in (-1.0, 1.0):
    walls.append(
        Pos(_sx * (hc.box_len - _w) / 2.0, 0.0, _f)
        * Box(_w, _inner_y, _wall_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    )

body = floor
for _slab in walls:
    body = body + _slab

_boss_at = [
    (-hc.boss_x, -hc.boss_y),
    (-hc.boss_x, hc.boss_y),
    (hc.boss_x, -hc.boss_y),
    (hc.boss_x, hc.boss_y),
]
for _bx, _by in _boss_at:
    body = body + Pos(_bx, _by, _f) * Cylinder(
        radius=hc.boss_d / 2.0,
        height=hc.boss_top_z - _f,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
for _bx, _by in _boss_at:
    body = body - Pos(_bx, _by, hc.boss_top_z - hc.pilot_depth) * Cylinder(
        radius=hc.pilot_d / 2.0,
        height=hc.pilot_depth,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )

body = chamfer(body.edges().group_by(Axis.Z)[0], length=0.3)
body.label = "enclosure_body"

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.box_len, hc.box_width, hc.box_height), abs=0.05),
    "one_sealed_solid": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "FDM project box (variant): assembled shell, chamfered base"
part.material_spec = "PETG, 3 perimeters"
part.process = "fdm"
