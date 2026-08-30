# scan-socket-cuff acceptance checks (project scope: whole-part measurements).
#
# The graded engineering is the CLEARANCE, and the clearance is measured against
# the scan itself by the task's `scan_requirements` entry (MESH_INGEST.md §7.5),
# through the same `compare_to_scan` path the model calls. What CHECKS pin here
# is everything a distance cannot see: that the cuff is a cuff — one sealed
# tube of the declared height, with a bore rather than a solid slug.
#
# Windows are budgets. The volume window is ~4x below the smallest modelling
# error it must reject: a wall 1 mm thicker adds 13087 mm^3, a bore 1 mm smaller
# adds 11876 mm^3 (and is caught by the clearance requirement anyway), while the
# window admits only tessellation-scale differences in how the tube was built.
_CUFF_VOLUME = 51019.46
_CUFF_WINDOW = 200.0

CHECKS = {
    "cuff_envelope": lambda m: m.bbox("cuff/part") == approx((62.0, 62.0, 70.0), abs=0.05),
    "cuff_is_a_tube": lambda m: m.volume("cuff/part") == approx(_CUFF_VOLUME, abs=_CUFF_WINDOW),
    # A cuff has a through bore: genus 1 is the bore, and sealed is the tube.
    "cuff_sealed_with_a_bore": lambda m: m.sealed("cuff/part") and m.genus("cuff/part") == 1,
}
