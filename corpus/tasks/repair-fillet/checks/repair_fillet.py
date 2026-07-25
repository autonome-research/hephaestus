# repair-fillet acceptance checks (project scope: whole-part measurements).
#
# The repair must leave the blank and the notch alone and blend the inner corner
# with the specified radius. The volume is the measurement that proves the blend:
# a notched 50 x 30 x 6 L-plate is exactly 6600 mm^3, and a concave R5 corner
# blend adds r^2 (1 - pi/4) t = 32.19 mm^3 of material. A missing blend (6600),
# a smaller radius or a larger one all land outside the window, so "the fillet is
# applied and its radius is right" is measured, not assumed.
_ENVELOPE = (50.0, 30.0, 6.0)
_VOLUME_MM3 = 6632.19

CHECKS = {
    "builds_sealed": lambda m: m.sealed("plate/part") and m.genus("plate/part") == 0,
    "envelope_unchanged": lambda m: m.bbox("plate/part") == approx(_ENVELOPE, abs=0.05),
    "inner_corner_blended_r5": lambda m: m.volume("plate/part") == approx(_VOLUME_MM3, abs=1.0),
}
