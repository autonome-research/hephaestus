# Independent second implementation of gripper-jaws jaw (VALIDATION.md §1).
#
# Different construction: the block is laid out with align= from its own back
# corner, carries a shallow blind lightening pocket in its back face (sealed,
# genus 0, envelope unchanged) and a 1 mm chamfer on its top back edge — a
# correct jaw a different engineer would ship. The gripping face lands on
# exactly the same plane as the reference's.
_back_x = hc.jaw_face_x - hc.jaw_w

block = Pos(_back_x, 0.0, hc.base_t) * Box(
    hc.jaw_w, hc.base_w, hc.jaw_h, align=(Align.MIN, Align.MIN, Align.MIN)
)
pocket = Pos(_back_x + 1.0, hc.base_w / 2.0, hc.base_t + hc.jaw_h / 2.0) * Box(
    2.0, 20.0, 10.0
)
jaw_body = block - pocket
# Break the top back edge (the Y-parallel edge at x = 12, z = 30).
_top_back = jaw_body.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1].sort_by(Axis.X)[0]
jaw_body = chamfer(_top_back, length=1.0)
jaw_body.label = "sliding_jaw_variant"

tag(jaw_body.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "grip_face")

part.geometry = jaw_body

CHECKS = {
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Sliding jaw (variant build): pocketed back, chamfered crown, same grip plane"
