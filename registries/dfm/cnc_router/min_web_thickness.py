# cnc_router.min_web_thickness — a wall thinner than about a millimetre moves.
#
# The measurement is the distance between two anti-parallel planar faces that
# actually face each other — the material between them. Only the thinnest wall
# per solid is reported: it is the one that governs, and naming every pair
# buries it.
#
# Reads: min_web_mm.


def evaluate(ctx):
    bound = ctx.param("min_web_mm")

    for solid in ctx.solids():
        walls = ctx.opposing_faces(solid.solid_id)
        if not walls:
            continue
        thinnest = min(walls, key=lambda wall: wall.thickness_mm)
        if thinnest.thickness_mm >= bound:
            continue
        ctx.report(
            f"thinnest wall of solid {solid.solid_id} is {thinnest.thickness_mm:.3f} mm, "
            f"below the {bound:.3f} mm web that will hold still under the cut",
            refs=[thinnest.a, thinnest.b],
            measured={
                "thickness_mm": thinnest.thickness_mm,
                "minimum_web_mm": bound,
                "solid_id": solid.solid_id,
            },
            suggested_bound=bound,
        )
