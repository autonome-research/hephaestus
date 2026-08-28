# The kerf test card: a scrap-sheet coupon carrying one through-slot per test
# width, cut before the tread so the operator can measure what the beam actually
# removes.
#
# It is also the fixture's OVERSIZED-LEGEND operand (INTERFACE.md §14: "a
# selection legend exceeding INLINE_LEGEND_CAP_BYTES (50 KiB) so
# mask_legend_truncated + mask_legend_ref paging is actually exercised", G5.8).
# A selection-mode legend carries one entry per addressable face and edge, so
# the requirement is a requirement about topology COUNT, and the honest way to
# meet it is a part that genuinely has that many features rather than a
# synthesized legend. `slot_count` is the knob: at 90 slots the legend clears the
# cap with margin.
#
# NOT built by the Gate G4 browser harness. G4 asks nothing of this part, and 90
# boolean cuts on every e2e run would be time the gate does not need to spend.
PARAMS = {
    "slot_count": Param(90, min=8, max=140),
}

_card_w = 240.0
_card_d = 120.0
_slot_len = 14.0

card = Box(_card_w, _card_d, hc.sheet_t)

# The slots march across the card in a serpentine so a long card is not needed:
# ten per row, as many rows as the count requires.
_per_row = 10
_pitch_x = _card_w / (_per_row + 1)
_rows = (p.slot_count + _per_row - 1) // _per_row
_pitch_y = _card_d / (_rows + 1)
for _i in range(p.slot_count):
    _col = _i % _per_row
    _row = _i // _per_row
    _x = -_card_w / 2.0 + _pitch_x * (_col + 1)
    _y = -_card_d / 2.0 + _pitch_y * (_row + 1)
    # Each slot is one test width, stepping up in tenths of a millimetre.
    _width = 0.6 + 0.1 * float(_i % 12)
    card = card - Pos(_x, _y, 0.0) * Box(_width, _slot_len, hc.sheet_t * 3.0)

card.label = "kerf_card"
part.geometry = card

part.description = "Kerf test card: one through-slot per test width, cut from the offcut"
part.material_spec = "Baltic birch plywood (BB/BB) sheet"
part.process = "laser_cut"
part.stock_form = "sheet"
part.general_tolerance = "+/-0.25 mm cut profile"
