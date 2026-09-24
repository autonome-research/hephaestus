# cnc_mill.min_internal_radius_vs_tool — a bit cannot turn a corner tighter than itself.
#
# A concave corner round is a partial cylindrical face whose outward normal
# points towards its own axis: material on the outside, air on the inside. The
# cutter sweeps a circle of tool_diameter/2, so a modelled internal radius below
# that is cut larger than drawn, and any fit that depends on the corner loses
# its interference.
#
# The radius floor is the material's DECLARED machining.min_internal_radius_mm
# when the resolved record carries one (CAM.md §6.2 — the number, never the
# notes prose), else the pack parameter.
#
# Reads: tool_diameter_mm, min_internal_radius_mm.


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
    tool = ctx.param("tool_diameter_mm")
    declared = _declared(ctx, "min_internal_radius_mm")
    floor = declared if declared is not None else ctx.param("min_internal_radius_mm")
    source = "material" if declared is not None else "pack"
    bound = max(floor, tool / 2.0)

    for corner in ctx.internal_rounds():
        if corner.radius >= bound:
            continue
        ctx.report(
            f"internal corner radius {corner.radius:.3f} mm is tighter than the "
            f"{bound:.3f} mm a {tool:.2f} mm bit can cut; it will come out at least "
            f"{bound:.3f} mm",
            refs=[corner.ref],
            measured={
                "radius_mm": corner.radius,
                "tool_diameter_mm": tool,
                "minimum_radius_mm": bound,
                "radius_floor_mm": floor,
                "radius_floor_source": source,
                "sweep_deg": math.degrees(corner.sweep_rad),
            },
            suggested_bound=bound,
        )
