# Reference solution for bench task print-bracket.
#
# One solid, printed standing on the plate in +Z. The arm's underside is a single
# straight ramp from the upright at z = 4 out to the tip at z = 34: it rises
# 30 mm over 24 mm of reach, so the unsupported face leans 38.7 deg from vertical
# — inside the 45 deg the fdm pack allows — where a flat-bottomed arm would be a
# 90 deg bridge. The fixing bore is vertical so its walls are vertical too.
_w = hc.bracket_width
_t = hc.wall_t

_upright = Box(_w, _t, hc.upright_height, align=(Align.CENTER, Align.MIN, Align.MIN))
_arm = Pos(0.0, _t, hc.ramp_base_z) * Box(
    _w,
    hc.arm_reach - _t,
    hc.upright_height - hc.ramp_base_z,
    align=(Align.CENTER, Align.MIN, Align.MIN),
)

# Cut everything below the ramp away from the arm.
_ramp = extrude(
    Plane.YZ
    * make_face(
        Polyline(
            (_t, hc.ramp_base_z),
            (hc.arm_reach, hc.ramp_base_z),
            (hc.arm_reach, hc.ramp_top_z),
            close=True,
        )
    ),
    amount=_w,
    both=True,
)

body = (_upright + _arm) - _ramp
body = body - Pos(0.0, hc.bore_y, hc.upright_height / 2.0) * Cylinder(
    hc.bore_dia / 2.0, 4.0 * hc.upright_height
)

part.geometry = body

part.description = "Printed cantilever bracket with a ramped arm and one fixing bore"
part.process = "fdm"
part.material_spec = "PLA filament"
part.stock_form = "filament"
