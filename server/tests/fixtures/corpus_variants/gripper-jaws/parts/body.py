# Independent second implementation of gripper-jaws body (VALIDATION.md §1:
# every task ships a second solution so its checks provably grade the
# engineering, not the reference geometry back).
#
# Different construction: the base and the fixed jaw are laid out with align=
# from the origin corner instead of centred positioning, and the fixed jaw's
# top back corner carries a 1 mm chamfer — in-spec detailing a correct shop
# part may well have, which the acceptance must not punish. The gripping face
# and the travel datum land on exactly the same planes.
base = Box(hc.base_l, hc.base_w, hc.base_t, align=(Align.MIN, Align.MIN, Align.MIN))
jaw_block = Pos(hc.fixed_face_x, 0.0, hc.base_t) * Box(
    hc.jaw_w, hc.base_w, hc.jaw_h, align=(Align.MIN, Align.MIN, Align.MIN)
)
body = base + jaw_block
# Break the fixed jaw's top back corner (the Y-parallel edge at x = 60, z = 30).
_top_back = body.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1].sort_by(Axis.X)[-1]
body = chamfer(_top_back, length=1.0)
body.label = "gripper_body_variant"

tag(
    body.faces()
    .filter_by(Axis.X)
    .sort_by_distance((hc.fixed_face_x, hc.base_w / 2.0, hc.base_t + hc.jaw_h / 2.0))[0],
    "grip_face",
)
tag(body.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "travel_datum")

part.geometry = body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Gripper body (variant build): corner-aligned layout, chamfered jaw crown"
