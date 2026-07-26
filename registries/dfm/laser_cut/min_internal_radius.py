# laser_cut.min_internal_radius — a beam cannot turn a corner tighter than itself.
#
# A concave corner round is a partial cylindrical face whose outward normal
# points towards its own axis: material on the outside, air on the inside. The
# beam sweeps a circle of kerf/2, so a modelled internal radius below that is
# cut larger than drawn, and any fit that depends on the corner loses its
# interference.
#
# Reads: min_internal_radius_mm, kerf_mm.


def evaluate(ctx):
    kerf = ctx.param("kerf_mm")
    bound = max(ctx.param("min_internal_radius_mm"), kerf / 2.0)

    for corner in ctx.internal_rounds():
        if corner.radius >= bound:
            continue
        ctx.report(
            f"internal corner radius {corner.radius:.3f} mm is tighter than the "
            f"{bound:.3f} mm the beam can cut; it will come out at least "
            f"{bound:.3f} mm",
            refs=[corner.ref],
            measured={
                "radius_mm": corner.radius,
                "kerf_mm": kerf,
                "minimum_radius_mm": bound,
                "sweep_deg": math.degrees(corner.sweep_rad),
            },
            suggested_bound=bound,
        )
