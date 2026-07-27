# Variant solution for enclosure-bosses — deliberately NOT the reference lid.
#
# The reference lip is a solid block filling the cavity mouth. This one is a
# 3 mm wide peripheral RIB — the way most printed lids are actually detailed,
# because a solid block is wasted plastic — and it registers with 0.3 mm of
# clearance per side rather than the 0.2 mm the reference chose, which is inside
# the fit window the task's checks declare.
#
# Both lids close the same box. They differ by roughly 6900 mm^3, which is why
# the audit deleted the lid-volume identity check: it was measuring which lid
# you drew, not whether the lid works.
_clear = 0.3
_rib_w = 3.0
_cav_x = hc.box_len - 2.0 * hc.wall_t
_cav_y = hc.box_width - 2.0 * hc.wall_t
_lip_z = hc.box_height - hc.lid_lip_h

_rib_outer = Pos(0, 0, _lip_z) * Box(
    _cav_x - 2.0 * _clear,
    _cav_y - 2.0 * _clear,
    hc.lid_lip_h,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
_rib_void = Pos(0, 0, _lip_z - 1.0) * Box(
    _cav_x - 2.0 * _clear - 2.0 * _rib_w,
    _cav_y - 2.0 * _clear - 2.0 * _rib_w,
    hc.lid_lip_h + 2.0,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
rib = _rib_outer - _rib_void

plate = Pos(0, 0, hc.box_height) * Box(
    hc.box_len, hc.box_width, hc.lid_t, align=(Align.CENTER, Align.CENTER, Align.MIN)
)

body = plate + rib
for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        body = body - Pos(_sx * hc.boss_x, _sy * hc.boss_y, _lip_z - 1.0) * Cylinder(
            radius=hc.lid_hole_d / 2.0,
            height=hc.lid_lip_h + hc.lid_t + 2.0,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
body.label = "lid_body"

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.box_len, hc.box_width, hc.lid_t + hc.lid_lip_h), abs=0.05),
    "four_screw_holes": lambda m: m.sealed("part") and m.genus("part") == 4,
}

part.description = "Enclosure lid (variant): plate with a peripheral register rib"
part.material_spec = "PETG, 3 perimeters"
part.process = "fdm"
