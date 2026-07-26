# fdm.min_wall_thickness — a wall is built from whole extrusions or not at all.
#
# The slicer fills a wall with perimeters one nozzle width each. Below two or
# three of them there is nothing to print: the wall becomes a single wavering
# bead, or disappears. The measurement is the distance between two anti-parallel
# planar faces that actually face each other — the material between them.
#
# Only the thinnest wall per solid is reported: it is the one that governs, and
# naming every pair buries it.
#
# Reads: nozzle_mm, min_wall_mm, wall_nozzle_multiple.


def evaluate(ctx):
    nozzle = ctx.param("nozzle_mm")
    bound = max(ctx.param("min_wall_mm"), nozzle * ctx.param("wall_nozzle_multiple"))

    for solid in ctx.solids():
        walls = ctx.opposing_faces(solid.solid_id)
        if not walls:
            continue
        thinnest = min(walls, key=lambda wall: wall.thickness_mm)
        if thinnest.thickness_mm >= bound:
            continue
        ctx.report(
            f"thinnest wall of solid {solid.solid_id} is {thinnest.thickness_mm:.3f} mm, "
            f"below the {bound:.3f} mm printable minimum for a {nozzle:.2f} mm nozzle",
            refs=[thinnest.a, thinnest.b],
            measured={
                "thickness_mm": thinnest.thickness_mm,
                "nozzle_mm": nozzle,
                "minimum_wall_mm": bound,
                "solid_id": solid.solid_id,
            },
            suggested_bound=bound,
        )
