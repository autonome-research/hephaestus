# Reference solution for bench task enclosure-bosses — the lid.
#
# A flat plate the size of the box's footprint, seating on the box's rim, with a
# lip dropping into the cavity one lid_clearance short of the cavity walls on
# every side, and four screw clearance holes on the boss pattern.
_wall = hc.wall_t
_clear = hc.lid_clearance
_plate_z = hc.box_height
_lip_z = hc.box_height - hc.lid_lip_h

plate = Pos(0, 0, _plate_z) * Box(
    hc.box_len, hc.box_width, hc.lid_t, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
lip = Pos(0, 0, _lip_z) * Box(
    hc.box_len - 2.0 * _wall - 2.0 * _clear,
    hc.box_width - 2.0 * _wall - 2.0 * _clear,
    hc.lid_lip_h,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
body = plate + lip

for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        body = body - Pos(_sx * hc.boss_x, _sy * hc.boss_y, _lip_z) * Cylinder(
            radius=hc.lid_hole_d / 2.0,
            height=hc.lid_lip_h + hc.lid_t,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
body.label = "lid_body"

tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "lid_top")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.box_len, hc.box_width, hc.lid_t + hc.lid_lip_h), abs=0.05),
    "four_screw_holes": lambda m: m.sealed("part") and m.genus("part") == 4,
}

part.description = "Enclosure lid: seating plate, register lip, four screw holes"
part.material_spec = "PETG, 3 perimeters"
part.process = "fdm"
part.assembly_method = "Four self-tapping screws into the box bosses"
part.feature("lid_top").surface_finish = "Top surface; label goes here"
