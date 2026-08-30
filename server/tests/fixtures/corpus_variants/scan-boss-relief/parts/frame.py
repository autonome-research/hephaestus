# Independent second implementation of the scan-boss-relief deliverable.
#
# A builder-mode extrusion of a ring sketch rather than a box minus a box. Same
# interface, different route: the acceptance grades the relief against the scan
# and the frame's own facts, so this must pass exactly the same way
# (VALIDATION.md §1 — acceptance checks are functional, never reproductive).
with BuildPart() as builder:
    with BuildSketch():
        Rectangle(hc.frame_x, hc.frame_y)
        Rectangle(hc.boss_x + 2 * hc.relief_mm, hc.boss_y + 2 * hc.relief_mm, mode=Mode.SUBTRACT)
    extrude(amount=hc.frame_z / 2.0, both=True)

frame = builder.part
frame.label = "frame"
part.geometry = frame

part.description = "Rectangular relief frame, extruded from a ring sketch"
part.material_spec = "6061-T6"
part.process = "cnc_router"
