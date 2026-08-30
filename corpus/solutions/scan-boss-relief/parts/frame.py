# Reference solution for bench task scan-boss-relief — the relief frame.
#
# The scan is measurement data and the frame is authored geometry
# (MESH_INGEST.md §5.2). The opening is the scanned boss's declared size plus
# the relief parameter on each side — a number the acceptance then measures
# against the scan, rather than a shape derived from it.
_opening_x = hc.boss_x + 2 * hc.relief_mm
_opening_y = hc.boss_y + 2 * hc.relief_mm

frame = Box(hc.frame_x, hc.frame_y, hc.frame_z) - Box(_opening_x, _opening_y, hc.frame_z)
frame.label = "frame"
part.geometry = frame

part.description = "Rectangular relief frame standing 2 mm off the scanned boss on every side"
part.material_spec = "6061-T6"
part.process = "cnc_router"
