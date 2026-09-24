# cnc_mill.min_web_thickness — a wall thinner than about a millimetre distorts.
#
# The measurement is the distance between two anti-parallel planar faces that
# actually face each other — the material between them. Only the thinnest wall
# per solid is reported: it is the one that governs, and naming every pair
# buries it. The web floor is the material's DECLARED machining.min_web_mm
# when the resolved record carries one (CAM.md §6.2), else the pack parameter.
#
# Reads: min_web_mm.


def _declared(ctx, key):
    material = ctx.material
    if material is None:
        return None
    block = material.get("machining")
    if not isinstance(block, dict):
        return None
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def evaluate(ctx):
    declared = _declared(ctx, "min_web_mm")
    bound = declared if declared is not None else ctx.param("min_web_mm")
    source = "material" if declared is not None else "pack"

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
                "web_floor_source": source,
                "solid_id": solid.solid_id,
            },
            suggested_bound=bound,
        )
