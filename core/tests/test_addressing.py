"""§7 addressing grammar tests: every rule, plus hypothesis property tests."""

from __future__ import annotations

import pytest
from hephaestus.core.addressing import (
    GeometryIndex,
    Resolution,
    label_rows,
    namespace,
    resolve,
    resolve_in_project,
)
from hephaestus.core.errors import AddressingError
from hypothesis import given, settings
from hypothesis import strategies as st

SHELF = GeometryIndex(
    labels=(
        "outer_top_panel",
        "corner_splines",
        "corner_splines",
        "corner_splines",
        "corner_splines",
        "corner_splines",
        "collar",
    ),
    bindings={"slotted_shelf": 1, "corner_splines": 5, "_placed_spline": 1, "cutters": 0},
    tags=frozenset({"tread_top", "front_edge"}),
)

GUSSET = GeometryIndex(
    labels=("center_lamination", "side_lamination", "side_lamination"),
    bindings={"center_lamination": 1},
    tags=frozenset({"joint_face"}),
)

PROJECT = {"cat_step_shelf": SHELF, "cat_step_gusset": GUSSET}


class TestPartRule:
    def test_part_resolves_whole_compound(self) -> None:
        assert resolve("part", SHELF) == Resolution(kind="part", name="part")

    def test_part_wins_over_tag_label_binding(self) -> None:
        index = GeometryIndex(labels=("part",), bindings={"part": 1}, tags=frozenset({"part"}))
        assert resolve("part", index).kind == "part"


class TestTagRule:
    def test_tag_resolves(self) -> None:
        assert resolve("tread_top", SHELF) == Resolution(kind="tag", name="tread_top")

    def test_tag_wins_over_label_and_binding(self) -> None:
        index = GeometryIndex(labels=("thing",), bindings={"thing": 2}, tags=frozenset({"thing"}))
        assert resolve("thing", index).kind == "tag"


class TestLabelRule:
    def test_unique_label(self) -> None:
        assert resolve("collar", SHELF) == Resolution(kind="label", name="collar", occurrences=(6,))

    def test_bare_duplicate_label_is_first_occurrence(self) -> None:
        assert resolve("corner_splines", SHELF) == Resolution(
            kind="label", name="corner_splines", occurrences=(1,)
        )

    @pytest.mark.parametrize(("k", "index"), [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)])
    def test_hash_k_selects_kth_in_tree_order(self, k: int, index: int) -> None:
        assert resolve(f"corner_splines#{k}", SHELF) == Resolution(
            kind="label", name="corner_splines", occurrences=(index,)
        )

    def test_hash_star_fuses_all_occurrences(self) -> None:
        assert resolve("corner_splines#*", SHELF) == Resolution(
            kind="label", name="corner_splines", occurrences=(1, 2, 3, 4, 5), fused=True
        )

    def test_hash_k_out_of_range_is_error(self) -> None:
        with pytest.raises(AddressingError) as exc_info:
            resolve("corner_splines#6", SHELF)
        assert exc_info.value.code == "addressing_error"

    def test_label_wins_over_binding(self) -> None:
        # "corner_splines" is both a label (5 occurrences) and a list binding.
        assert resolve("corner_splines", SHELF).kind == "label"

    def test_label_on_compound_addresses_subtree(self) -> None:
        # Flattened tree: a compound label is just another tree node.
        index = GeometryIndex(labels=("assembly", "left", "right"))
        assert resolve("assembly", index) == Resolution(
            kind="label", name="assembly", occurrences=(0,)
        )


class TestBindingRule:
    def test_scalar_binding(self) -> None:
        assert resolve("slotted_shelf", SHELF) == Resolution(
            kind="binding", name="slotted_shelf", occurrences=(0,)
        )

    def test_underscore_private_binding(self) -> None:
        assert resolve("_placed_spline", SHELF).kind == "binding"

    def test_list_binding_bare_name_fuses_members(self) -> None:
        index = GeometryIndex(bindings={"ribs": 3})
        assert resolve("ribs", index) == Resolution(
            kind="binding", name="ribs", occurrences=(0, 1, 2), fused=True
        )

    def test_list_binding_hash_k_selects_append_order(self) -> None:
        index = GeometryIndex(bindings={"ribs": 3})
        assert resolve("ribs#2", index) == Resolution(kind="binding", name="ribs", occurrences=(1,))

    def test_list_binding_hash_star(self) -> None:
        index = GeometryIndex(bindings={"ribs": 3})
        assert resolve("ribs#*", index) == Resolution(
            kind="binding", name="ribs", occurrences=(0, 1, 2), fused=True
        )

    def test_list_binding_hash_k_out_of_range(self) -> None:
        index = GeometryIndex(bindings={"ribs": 3})
        with pytest.raises(AddressingError):
            resolve("ribs#4", index)

    def test_empty_list_binding_resolves_empty_fused(self) -> None:
        assert resolve("cutters", SHELF) == Resolution(
            kind="binding", name="cutters", occurrences=(), fused=True
        )


class TestErrors:
    def test_no_match_lists_near_misses(self) -> None:
        with pytest.raises(AddressingError) as exc_info:
            resolve("corner_spline", SHELF)
        error = exc_info.value
        assert error.code == "addressing_error"
        assert any("corner_splines" in c for c in error.candidates)
        assert "corner_spline" in error.message

    def test_no_match_no_silent_guess(self) -> None:
        with pytest.raises(AddressingError):
            resolve("totally_unknown_name_xyz", SHELF)

    def test_empty_selector_is_error(self) -> None:
        with pytest.raises(AddressingError):
            resolve("", SHELF)

    def test_same_level_label_ambiguity_lists_candidates(self) -> None:
        # A literal label "x#2" AND a duplicated label "x" both claim "x#2".
        index = GeometryIndex(labels=("x", "x", "x#2"))
        with pytest.raises(AddressingError) as exc_info:
            resolve("x#2", index)
        assert len(exc_info.value.candidates) == 2

    def test_same_level_binding_ambiguity_lists_candidates(self) -> None:
        index = GeometryIndex(bindings={"y": 3, "y#2": 1})
        with pytest.raises(AddressingError) as exc_info:
            resolve("y#2", index)
        assert len(exc_info.value.candidates) == 2


class TestCrossPart:
    def test_prefixed_selector(self) -> None:
        part, res = resolve_in_project("cat_step_gusset/center_lamination", PROJECT)
        assert part == "cat_step_gusset"
        assert res == Resolution(kind="label", name="center_lamination", occurrences=(0,))

    def test_prefixed_dedup_selector(self) -> None:
        part, res = resolve_in_project("cat_step_gusset/side_lamination#2", PROJECT)
        assert part == "cat_step_gusset"
        assert res.occurrences == (2,)

    def test_unprefixed_uses_current_part(self) -> None:
        part, res = resolve_in_project("collar", PROJECT, current_part="cat_step_shelf")
        assert part == "cat_step_shelf"
        assert res.kind == "label"

    def test_unknown_part_lists_known_parts(self) -> None:
        with pytest.raises(AddressingError) as exc_info:
            resolve_in_project("cat_step_gussett/center_lamination", PROJECT)
        assert "cat_step_gusset" in exc_info.value.candidates

    def test_unprefixed_without_current_part_is_error(self) -> None:
        with pytest.raises(AddressingError):
            resolve_in_project("collar", PROJECT)


class TestNamespace:
    def test_advertised_namespace_contents(self) -> None:
        names = namespace(SHELF)
        assert "part" in names
        assert "tread_top" in names
        assert "corner_splines" in names
        assert "corner_splines#2" in names
        assert "corner_splines#5" in names
        assert "corner_splines#*" in names
        assert "slotted_shelf" in names
        assert "cutters" in names

    def test_label_rows_match_observed_display(self) -> None:
        assert label_rows(SHELF) == (
            "outer_top_panel",
            "corner_splines",
            "corner_splines#2",
            "corner_splines#3",
            "corner_splines#4",
            "corner_splines#5",
            "collar",
        )


# --- Hypothesis property tests over random label trees -----------------------

_names = st.text(alphabet="abcxyz_", min_size=1, max_size=4)


@st.composite
def indexes(draw: st.DrawFn) -> GeometryIndex:
    labels = tuple(draw(st.lists(_names, max_size=12)))
    bindings = draw(st.dictionaries(_names, st.integers(min_value=0, max_value=5), max_size=6))
    tags = frozenset(draw(st.sets(_names, max_size=6)))
    return GeometryIndex(labels=labels, bindings=bindings, tags=tags)


@settings(max_examples=200)
@given(indexes())
def test_resolution_total_and_deterministic_over_namespace(index: GeometryIndex) -> None:
    for name in namespace(index):
        first = resolve(name, index)
        second = resolve(name, index)
        assert first == second, name


@settings(max_examples=200)
@given(indexes())
def test_namespace_is_deterministic(index: GeometryIndex) -> None:
    assert namespace(index) == namespace(index)


@settings(max_examples=200)
@given(indexes())
def test_hash_k_stability(index: GeometryIndex) -> None:
    """name#k always selects the k-th tree-order occurrence of the label."""
    counts: dict[str, int] = {}
    for label in index.labels:
        counts[label] = counts.get(label, 0) + 1
    for label, count in counts.items():
        occurrences = index.label_occurrences(label)
        assert len(occurrences) == count
        for k in range(1, count + 1):
            res = resolve(f"{label}#{k}", index)
            assert res.kind == "label"
            assert res.occurrences == (occurrences[k - 1],)
            assert index.labels[res.occurrences[0]] == label


@settings(max_examples=200)
@given(indexes())
def test_bare_label_is_first_occurrence_and_star_is_all(index: GeometryIndex) -> None:
    for label in set(index.labels):
        occurrences = index.label_occurrences(label)
        if label == "part" or label in index.tags:
            continue  # higher-precedence rules own the bare name
        bare = resolve(label, index)
        assert bare.kind == "label"
        assert bare.occurrences == (occurrences[0],)
        star = resolve(f"{label}#*", index)
        assert star.occurrences == occurrences
        assert star.fused


@settings(max_examples=200)
@given(indexes(), _names)
def test_unresolvable_names_raise_never_guess(index: GeometryIndex, name: str) -> None:
    advertised = set(namespace(index))
    probe = name + "#7#nope"
    assert probe not in advertised
    with pytest.raises(AddressingError):
        resolve(probe, index)
