# Reference solution for bench task gripper-jaws — the body (base + fixed jaw).
#
# A rectangular base resting on the XY plane with a corner at the origin,
# merged with the fixed jaw block at the +X end so the body is one solid. The
# gripping face lies on the plane x = fixed_face_x facing the sliding jaw.
# Every interface number comes from globals.py through hc.
base = Pos(hc.base_l / 2.0, hc.base_w / 2.0, hc.base_t / 2.0) * Box(
    hc.base_l, hc.base_w, hc.base_t
)
jaw_block = Pos(
    hc.fixed_face_x + hc.jaw_w / 2.0, hc.base_w / 2.0, hc.base_t + hc.jaw_h / 2.0
) * Box(hc.jaw_w, hc.base_w, hc.jaw_h)
body = base + jaw_block
body.label = "gripper_body"

# The gripping face: the X-normal face on the x = fixed_face_x plane.
tag(
    body.faces()
    .filter_by(Axis.X)
    .sort_by_distance((hc.fixed_face_x, hc.base_w / 2.0, hc.base_t + hc.jaw_h / 2.0))[0],
    "grip_face",
)
# The travel datum: the flat back face at x = base_l. Its outward +X normal is
# the direction positive jaw travel closes along (KINEMATICS.md §1: a
# prismatic joint frame is the parent anchor's planar-face normal).
tag(body.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "travel_datum")

part.geometry = body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Gripper body: 60 x 30 x 10 base with the fixed jaw at x = 50..60"
