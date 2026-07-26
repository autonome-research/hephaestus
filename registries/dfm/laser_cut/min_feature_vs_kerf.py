# laser_cut.min_feature_vs_kerf — the smallest thing a beam of finite width can cut.
#
# The beam removes a kerf of material as it travels, so a bore whose diameter
# approaches the kerf has no material left to define it: it either fails to cut
# through or fills with slag. The limit is the larger of an absolute floor and a
# multiple of the kerf, because a very fine beam still has a practical minimum.
#
# Reads: kerf_mm, min_feature_kerf_multiple, min_feature_mm.


def evaluate(ctx):
    kerf = ctx.param("kerf_mm")
    multiple = ctx.param("min_feature_kerf_multiple")
    floor = ctx.param("min_feature_mm")
    bound = max(floor, kerf * multiple)

    for hole in ctx.holes():
        diameter = 2.0 * hole.radius
        if diameter >= bound:
            continue
        ctx.report(
            f"bore of {diameter:.3f} mm diameter is below the {bound:.3f} mm minimum "
            f"cut feature for a {kerf:.2f} mm kerf",
            refs=[hole.ref],
            measured={
                "diameter_mm": diameter,
                "kerf_mm": kerf,
                "minimum_feature_mm": bound,
            },
            suggested_bound=bound,
        )
