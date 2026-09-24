# cnc_mill.pocket_depth_vs_tool_diameter — a buried flute chatters.
#
# From +Z, a pocket floor is a planar face whose outward normal points up and
# whose plane sits below the stock top. The depth of the deepest such face,
# compared with the tool diameter, is the "pockets deeper than about 4x the
# tool diameter chatter" note from the aluminium record, now a number: the
# material's DECLARED machining.max_depth_diameter_ratio when the resolved
# record carries one (CAM.md §6.2), else the pack parameter. The declared
# chipload and feed travel with the finding so the shop question is named,
# not simulated — DFM has no toolpath, and this is not a feeds model.
#
# Reads: tool_diameter_mm, max_depth_diameter_ratio, chipload_mm, feed_mm_min.

_UP_DOT = 0.9
_DEPTH_EPS_MM = 1e-6


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
    declared = _declared(ctx, "max_depth_diameter_ratio")
    ratio = declared if declared is not None else ctx.param("max_depth_diameter_ratio")
    source = "material" if declared is not None else "pack"
    chipload = ctx.param("chipload_mm")
    feed = ctx.param("feed_mm_min")
    bound = tool * ratio

    floors = [face for face in ctx.planar_faces() if face.normal[2] > _UP_DOT]
    if not floors:
        return
    top = max(face.center[2] for face in floors)
    deepest = None
    for face in floors:
        depth = top - face.center[2]
        if deepest is None or depth > deepest[0]:
            deepest = (depth, face)
    depth, face = deepest
    if depth <= _DEPTH_EPS_MM or depth <= bound:
        return
    ctx.report(
        f"pocket {depth:.3f} mm deep is {depth / tool:.1f}x a {tool:.2f} mm bit "
        f"(limit {ratio:g}x); at the pack's {chipload:.2f} mm chipload / "
        f"{feed:g} mm/min feed this will chatter",
        refs=[face.ref],
        measured={
            "depth_mm": depth,
            "tool_diameter_mm": tool,
            "depth_diameter_ratio": depth / tool,
            "limit_ratio": ratio,
            "limit_ratio_source": source,
            "chipload_mm": chipload,
            "feed_mm_min": feed,
        },
        suggested_bound=bound,
    )
