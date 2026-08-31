# cnc_router.bore_aspect_ratio — a hole much deeper than it is wide wanders.
#
# A closed internal cylinder's depth is its area divided by the circumference:
# the face is 2πr tall, so h = A / (2πr). The ratio h / (2r) is the shop's
# "don't drill more than N diameters deep" rule, made measurable without a
# new kernel.
#
# Reads: max_bore_aspect.


def evaluate(ctx):
    cap = ctx.param("max_bore_aspect")

    for hole in ctx.holes():
        if hole.radius <= 0.0:
            continue
        diameter = 2.0 * hole.radius
        depth = hole.area / (2.0 * math.pi * hole.radius)
        aspect = depth / diameter
        if aspect <= cap:
            continue
        ctx.report(
            f"bore of {diameter:.3f} mm diameter is {depth:.3f} mm deep "
            f"({aspect:.1f}x diameter, limit {cap:g}x) and will wander",
            refs=[hole.ref],
            measured={
                "diameter_mm": diameter,
                "depth_mm": depth,
                "aspect": aspect,
                "limit_aspect": cap,
            },
            suggested_bound=cap,
        )
