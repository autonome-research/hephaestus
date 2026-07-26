# fdm.overhang_angle — plastic laid past the layer below it droops.
#
# The angle is measured from vertical: a vertical wall is 0 deg and prints
# perfectly, a horizontal downward face is 90 deg and is a bridge. Past roughly
# 45 deg each layer overhangs the previous one by more than half an extrusion
# width and the surface degrades.
#
# Faces resting on the build plate are supported by definition and excluded, as
# are slivers below the area floor — a 0.3 mm^2 chamfer relief is not a print
# problem and reporting it would train the reader to ignore the rule.
#
# Reads: max_overhang_deg, min_overhang_area_mm2.


def evaluate(ctx):
    limit = ctx.param("max_overhang_deg")
    min_area = ctx.param("min_overhang_area_mm2")

    for overhang in ctx.overhangs():
        if overhang.on_build_plate or overhang.area < min_area:
            continue
        if overhang.angle_deg <= limit:
            continue
        ctx.report(
            f"unsupported face leans {overhang.angle_deg:.1f} deg from vertical, past "
            f"the {limit:.1f} deg limit, over {overhang.area:.1f} mm^2",
            refs=[overhang.ref],
            measured={
                "overhang_deg": overhang.angle_deg,
                "limit_deg": limit,
                "area_mm2": overhang.area,
                "normal": list(overhang.normal),
            },
            suggested_bound=limit,
        )
