# Reference solution for bench task scan-socket-cuff — the cuff itself.
#
# MESH_INGEST.md §5.2 is the whole point of this task: the scan is MEASUREMENT
# DATA and the cuff is AUTHORED geometry. Nothing here converts the mesh to a
# solid and nothing offsets it — the bore is a declared number, and the gap
# between that number and the scan is what the acceptance measures.
_bore = hc.cuff_bore_r
_height = hc.cuff_height

cuff = Cylinder(_bore + hc.wall_mm, _height) - Cylinder(_bore, _height)
cuff.label = "cuff"
part.geometry = cuff

part.description = "Circular limb cuff with a 27 mm bore, authored against the scan"
part.material_spec = "PETG"
part.process = "fdm"
