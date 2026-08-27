# Reference solution for bench task gripper-jaws — the sliding jaw.
#
# One jaw block resting flat on the base top, authored fully OPEN with its
# gripping face at x = jaw_face_x. The jaw closes by sliding +X; the joint,
# poses and travel are project state (declared through the motion tools), so
# the script authors only the zero configuration — the 8C rule: scripts
# position geometry, a pose exists only inside an evaluation.
_face_x = hc.jaw_face_x

jaw_body = Pos(_face_x - hc.jaw_w / 2.0, hc.base_w / 2.0, hc.base_t + hc.jaw_h / 2.0) * Box(
    hc.jaw_w, hc.base_w, hc.jaw_h
)
jaw_body.label = "sliding_jaw"

# The gripping face: the +X extreme face, facing the fixed jaw.
tag(jaw_body.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "grip_face")

part.geometry = jaw_body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Sliding jaw: 10 x 30 x 20 block riding the base top, open at x = 12..22"
