"""Selection palette: bijectivity, background avoidance, legend round-trip."""

from __future__ import annotations

import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.render.palette import (
    BACKGROUND_RGB,
    MAX_SELECTION_ID,
    SelectionEntry,
    build_legend,
    hex_to_rgb,
    id_to_hex,
    id_to_rgb,
    legend_to_entries,
    rgb_to_hex,
    rgb_to_id,
)
from hypothesis import given, settings
from hypothesis import strategies as st


@given(st.integers(min_value=0, max_value=MAX_SELECTION_ID))
@settings(max_examples=2000)
def test_id_rgb_roundtrip(selection_id: int) -> None:
    rgb = id_to_rgb(selection_id)
    assert rgb != BACKGROUND_RGB
    assert all(0 <= channel <= 255 for channel in rgb)
    assert rgb_to_id(rgb) == selection_id


def test_bijective_and_collision_free_over_100k() -> None:
    seen: dict[tuple[int, int, int], int] = {}
    for selection_id in range(100_000):
        rgb = id_to_rgb(selection_id)
        assert rgb != BACKGROUND_RGB
        assert rgb not in seen, f"collision {rgb} for {selection_id} and {seen[rgb]}"
        seen[rgb] = selection_id
        assert rgb_to_id(rgb) == selection_id
    assert len(seen) == 100_000


def test_id_zero_is_not_black() -> None:
    assert id_to_rgb(0) == (0, 0, 1)


def test_background_has_no_id() -> None:
    with pytest.raises(ValidationError):
        rgb_to_id(BACKGROUND_RGB)


def test_out_of_range_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        id_to_rgb(-1)
    with pytest.raises(ValidationError):
        id_to_rgb(MAX_SELECTION_ID + 1)


def test_hex_helpers() -> None:
    assert rgb_to_hex((0, 0, 1)) == "#000001"
    assert hex_to_rgb("#0a141e") == (10, 20, 30)
    assert id_to_hex(0) == "#000001"
    with pytest.raises(ValidationError):
        hex_to_rgb("#123")
    with pytest.raises(ValidationError):
        hex_to_rgb("#gggggg")


def test_legend_roundtrip() -> None:
    entries = {
        0: SelectionEntry(kind="solid", solid_index=0, topology_index=0, label="deck"),
        7: SelectionEntry(
            kind="face", solid_index=0, topology_index=5, tag="deck_top", label="deck"
        ),
        99999: SelectionEntry(kind="edge", solid_index=1, topology_index=3),
    }
    legend = build_legend(entries)
    # One row per id, keyed by that id's palette colour.
    assert set(legend) == {id_to_hex(i) for i in entries}
    assert legend[id_to_hex(7)] == {
        "kind": "face",
        "solid_index": 0,
        "topology_index": 5,
        "tag": "deck_top",
        "label": "deck",
    }
    assert legend_to_entries(legend) == entries


def test_entry_json_roundtrip() -> None:
    entry = SelectionEntry(kind="edge", solid_index=2, topology_index=9, tag="rim")
    assert SelectionEntry.from_json(entry.to_json()) == entry
