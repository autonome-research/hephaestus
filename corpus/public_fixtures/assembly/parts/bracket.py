# Corner bracket that seats against the shelf frame's +X face, one
# joint_clear gap away. Modeled in shared assembly coordinates so the
# cross-part fit checks in checks/fit.py can measure real clearances.
PARAMS = {
    "wing": Param(48.0, min=30.0, max=60.0),
}

_t = hc.sheet_t
_slot_w = hc.post_side + hc.joint_clear

# L-section: a base pad with an upstanding wall along its inner edge, then a
# post-clearing notch cut into the top of the wall.
base_pad = Pos(0, 0, _t / 2.0) * Box(p.wing, p.wing, _t)
wall = Pos(0, -p.wing / 2.0 + _t / 2.0, _t + 20.0) * Box(p.wing, _t, 40.0)
body = base_pad + wall
notch = Pos(0, -p.wing / 2.0 + _t / 2.0, _t + 35.0) * Box(_slot_w, _t, 10.0)
body = body - notch

# Seat the bracket one joint_clear off the frame's +X face.
body = Pos(hc.shelf_w / 2.0 + hc.joint_clear + p.wing / 2.0, 0, 0) * body
body.label = "bracket_body"
part.geometry = body

_body_volume = p.wing * p.wing * _t + p.wing * _t * 40.0 - _slot_w * _t * 10.0
_env = (p.wing + 0.5, p.wing + 0.5, 46.5)
CHECKS = {
    "envelope": lambda m: m.bbox("part") <= _env,
    "body_volume": lambda m: m.volume("part") == approx(_body_volume, abs=1e-6),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

tag(body.faces().sort_by(Axis.X)[0], "frame_face")

part.description = "Corner bracket seating against the shelf frame with joint clearance"
part.material_spec = "6 mm aluminium plate, brake-formed equivalent shown as machined L"
part.process = "cnc_router"
part.feature("frame_face").surface_finish = "Deburr; this face registers against the frame"
