# cnc_router.single_axis_accessibility — one spindle, one setup, +Z.
#
# A 3-axis router holds the sheet on the table. Every closed bore must share
# that spindle axis (within the declared lean), and a downward-facing planar
# face that is not the stock sitting on the table is an undercut no end mill
# approaching from +Z can see. Envelope faces of a simple plate therefore do
# not fire: a box has one downward face, and it is the table.
#
# Written from holes() and planar_faces() only — no accessibility kernel.
#
# Reads: approach_axis_tol_deg.

_TABLE_EPS_MM = 1e-6


def evaluate(ctx):
    tol = ctx.param("approach_axis_tol_deg")
    cos_tol = math.cos(math.radians(tol))
    approach = (0.0, 0.0, 1.0)

    for hole in ctx.holes():
        alignment = abs(
            hole.axis[0] * approach[0] + hole.axis[1] * approach[1] + hole.axis[2] * approach[2]
        )
        if alignment >= cos_tol:
            continue
        lean = math.degrees(math.acos(min(1.0, alignment)))
        ctx.report(
            f"bore axis leans {lean:.1f} deg from the +Z spindle "
            f"(limit {tol:g} deg) and is not reachable in one setup",
            refs=[hole.ref],
            measured={
                "axis": list(hole.axis),
                "lean_deg": lean,
                "limit_deg": tol,
            },
            suggested_bound=tol,
        )

    down = [face for face in ctx.planar_faces() if face.normal[2] < -cos_tol]
    if not down:
        return
    table_z = min(face.center[2] for face in down)
    for face in down:
        if face.center[2] <= table_z + _TABLE_EPS_MM:
            continue
        ctx.report(
            f"downward-facing surface at z={face.center[2]:.3f} mm is an undercut "
            f"from +Z (table is z={table_z:.3f} mm) and is not reachable in one setup",
            refs=[face.ref],
            measured={
                "normal": list(face.normal),
                "center_z_mm": face.center[2],
                "table_z_mm": table_z,
                "limit_deg": tol,
            },
            suggested_bound=tol,
        )
