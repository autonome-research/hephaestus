# Independent second implementation of the scan-socket-cuff deliverable.
#
# A builder-mode extrusion of a ring sketch rather than a difference of two
# revolved cylinders, and the bore comes from the sketch instead of a boolean.
# Same interface, different route: the acceptance grades the clearance against
# the scan and the tube's own facts, so this must pass exactly the same way
# (VALIDATION.md §1 — acceptance checks are functional, never reproductive).
with BuildPart() as builder:
    with BuildSketch():
        Circle(hc.cuff_bore_r + hc.wall_mm)
        Circle(hc.cuff_bore_r, mode=Mode.SUBTRACT)
    extrude(amount=hc.cuff_height / 2.0, both=True)

cuff = builder.part
cuff.label = "cuff"
part.geometry = cuff

part.description = "Circular limb cuff, extruded from a ring sketch"
part.material_spec = "PETG"
part.process = "fdm"
