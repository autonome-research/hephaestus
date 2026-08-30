# scan-boss-relief acceptance checks (project scope: whole-part measurements).
#
# The graded engineering is the RELIEF - how far the frame's opening stands off
# the scanned boss on every side - and it is measured against the scan itself by
# the task's `scan_requirements` entries (MESH_INGEST.md §7.5), through the same
# `compare_to_scan` path the model calls. Both directions of that requirement
# matter here: too little relief binds, and too much relief is not a frame that
# locates anything, which is why the acceptance carries a clearance floor AND a
# deviation ceiling rather than one bar.
#
# What CHECKS pin is what a distance cannot see: that the frame is a frame -
# one sealed ring of the declared envelope with an opening through it.
_FRAME_VOLUME = 30080.0
_FRAME_WINDOW = 150.0

CHECKS = {
    "frame_envelope": lambda m: m.bbox("frame/part") == approx((60.0, 50.0, 20.0), abs=0.05),
    "frame_is_a_ring": lambda m: m.volume("frame/part") == approx(_FRAME_VOLUME, abs=_FRAME_WINDOW),
    "frame_sealed_with_an_opening": lambda m: m.sealed("frame/part")
    and m.genus("frame/part") == 1,
}
