# sheet-box acceptance checks (project scope: whole-part measurements only — a
# reloaded build artifact resolves the "<part>/part" selector, so joints are
# measured between parts and feature-level facts are pinned by exact material
# volumes).
#
# - assembly: the tabs must pass through the base's slots without overlapping it
#   (zero interference) while the walls actually seat on the base (contact);
# - envelopes: the assembled wall box and the base blank;
# - material: exact volumes. The walls' volume pins the wall sizes and the eight
#   tabs; the base's volume pins the eight slots *including the kerf* (a kerfless
#   slot set leaves 175 mm^3 more material, well outside the window);
# - topology: the base is one sealed panel with eight through slots (genus 8);
# - layout: the cut layout is one sheet thick and holds exactly the same five
#   panels (its volume is the sum of the two assemblies).
_WALLS_VOLUME = 84096.0
_BASE_VOLUME = 55769.28
_LAYOUT_VOLUME = _WALLS_VOLUME + _BASE_VOLUME

CHECKS = {
    "assembled_no_interference": lambda m: m.interference("walls/part", "base/part")
    == approx(0.0, abs=1e-6),
    "walls_seat_on_base": lambda m: m.clearance("walls/part", "base/part")
    == approx(0.0, abs=1e-6),
    "wall_box_envelope": lambda m: m.bbox("walls/part") == approx((100.0, 80.0, 46.0), abs=0.05),
    "base_blank_envelope": lambda m: m.bbox("base/part") == approx((110.0, 90.0, 6.0), abs=0.05),
    "wall_material": lambda m: m.volume("walls/part") == approx(_WALLS_VOLUME, abs=30.0),
    "base_slots_kerf_compensated": lambda m: m.volume("base/part")
    == approx(_BASE_VOLUME, abs=15.0),
    "base_slots_are_through": lambda m: m.sealed("base/part") and m.genus("base/part") == 8,
    "layout_is_one_sheet_thick": lambda m: m.bbox("flat_layout/part")[2] == approx(6.0, abs=0.05),
    "layout_holds_every_panel": lambda m: m.volume("flat_layout/part")
    == approx(_LAYOUT_VOLUME, abs=40.0),
}
