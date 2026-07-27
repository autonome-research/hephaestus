# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). The cavity OPENING, made measurable: a 1 mm wide
# rectangular frame whose *inner* face lies exactly on the nominal cavity wall,
# standing in the register lip's z band and stopping well short of the rim.
#
# It is a fit gauge, not a shape gauge. Because its inner face is the cavity
# wall, the minimum separation between the lid and this frame IS the register
# clearance the lid actually achieves, per side, whatever shape the lip is:
# solid block, peripheral rib, stepped, chamfered. Overlap means the lip is
# larger than the opening somewhere — a press fit, which the task forbids.
#
# The frame stops 0.6 mm below the rim on purpose: the lid's seating plate
# overhangs it, and if the frame reached the rim that vertical gap, not the
# register clearance, would be the closest approach.
_cav_x = hc.box_len - 2.0 * hc.wall_t
_cav_y = hc.box_width - 2.0 * hc.wall_t
_z0 = hc.box_height - hc.lid_lip_h + 0.2
_z1 = hc.box_height - 0.6
_frame_w = 1.0

_outer = Pos(0, 0, _z0) * Box(
    _cav_x + 2.0 * _frame_w,
    _cav_y + 2.0 * _frame_w,
    _z1 - _z0,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
_opening = Pos(0, 0, _z0 - 1.0) * Box(
    _cav_x,
    _cav_y,
    (_z1 - _z0) + 2.0,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
frame = _outer - _opening
frame.label = "cavity_opening_frame"

part.geometry = frame

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part")
    == approx((_cav_x + 2.0 * _frame_w, _cav_y + 2.0 * _frame_w, _z1 - _z0), abs=0.01),
}

part.description = "Cavity-opening gauge: the register clearance, measured per side"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
