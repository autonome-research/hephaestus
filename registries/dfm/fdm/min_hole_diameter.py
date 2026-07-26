# fdm.min_hole_diameter — a bore narrower than a couple of extrusions prints solid.
#
# The perimeters walking around a small bore overlap each other and the hole
# closes. The practical limit is the larger of an absolute floor and two
# extrusion widths; below it the modelled hole is a dimple that has to be
# drilled, which is a different part from the one that was checked.
#
# Reads: min_hole_diameter_mm, nozzle_mm.


def evaluate(ctx):
    nozzle = ctx.param("nozzle_mm")
    bound = max(ctx.param("min_hole_diameter_mm"), nozzle * 2.0)

    for hole in ctx.holes():
        diameter = 2.0 * hole.radius
        if diameter >= bound:
            continue
        ctx.report(
            f"bore of {diameter:.3f} mm diameter is below the {bound:.3f} mm printable "
            f"minimum for a {nozzle:.2f} mm nozzle and will close up",
            refs=[hole.ref],
            measured={
                "diameter_mm": diameter,
                "nozzle_mm": nozzle,
                "minimum_diameter_mm": bound,
            },
            suggested_bound=bound,
        )
