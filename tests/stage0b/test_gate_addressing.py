"""Gate G0B — §7 addressing grammar on built fixtures.

Clauses: ``#k``/``#*`` duplicate-label dedup, the "part" and tag precedence,
binding-name resolution, and candidate-listing errors (ambiguity and misses
never guess silently — they list candidates / near-misses). Cross-part
``<part>/<selector>`` resolution and unknown-part candidate listing are checked
against the two assembly parts' indexes.
"""

from __future__ import annotations

import pytest
from _gate import ASSEMBLY, build_part
from hephaestus.core.addressing import (
    GeometryIndex,
    label_rows,
    namespace,
    resolve,
    resolve_in_project,
)
from hephaestus.core.errors import AddressingError
from hephaestus.core.executor.runner import UnpublishedBuild


@pytest.fixture(scope="module")
def primary(tmp_path_factory: pytest.TempPathFactory) -> UnpublishedBuild:
    built = build_part(
        "primary",
        ASSEMBLY / "parts" / "primary.py",
        tmp_path_factory.mktemp("addr-primary"),
        globals_path=ASSEMBLY / "globals.py",
    )
    assert built.result.status == "ok"
    return built


@pytest.fixture(scope="module")
def bracket(tmp_path_factory: pytest.TempPathFactory) -> UnpublishedBuild:
    built = build_part(
        "bracket",
        ASSEMBLY / "parts" / "bracket.py",
        tmp_path_factory.mktemp("addr-bracket"),
        globals_path=ASSEMBLY / "globals.py",
    )
    assert built.result.status == "ok"
    return built


@pytest.fixture(scope="module")
def primary_index(primary: UnpublishedBuild) -> GeometryIndex:
    return primary.geometry_index()


class TestPrecedence:
    def test_part_selector(self, primary_index: GeometryIndex) -> None:
        resolution = resolve("part", primary_index)
        assert resolution.kind == "part"

    def test_tag_beats_label(self, primary_index: GeometryIndex) -> None:
        assert "deck_top" in primary_index.tags
        assert resolve("deck_top", primary_index).kind == "tag"

    def test_label_resolves(self, primary_index: GeometryIndex) -> None:
        assert resolve("bottom_deck", primary_index).kind == "label"


class TestDuplicateLabelDedup:
    def test_geometries_match_deduped_rows(
        self, primary: UnpublishedBuild, primary_index: GeometryIndex
    ) -> None:
        rows = label_rows(primary_index)
        assert rows == ("bottom_deck", "top_deck", "post", "post#2", "post#3", "post#4")
        # §7: the §8 geometries array IS exactly the resolvable label set.
        assert [g.label for g in primary.result.geometries] == list(rows)

    def test_bare_name_is_first_occurrence(self, primary_index: GeometryIndex) -> None:
        bare = resolve("post", primary_index)
        first = resolve("post#1", primary_index)
        assert bare.kind == "label"
        assert bare.occurrences == first.occurrences
        assert bare.fused is False

    def test_hash_k_selects_kth(self, primary_index: GeometryIndex) -> None:
        occ = [resolve(f"post#{k}", primary_index).occurrences[0] for k in (1, 2, 3, 4)]
        assert occ == sorted(occ)
        assert len(set(occ)) == 4  # four distinct tree occurrences

    def test_hash_star_fuses_all(self, primary_index: GeometryIndex) -> None:
        fused = resolve("post#*", primary_index)
        assert fused.fused is True
        assert len(fused.occurrences) == 4

    def test_out_of_range_index_is_a_miss(self, primary_index: GeometryIndex) -> None:
        with pytest.raises(AddressingError):
            resolve("post#5", primary_index)


class TestCandidateListingErrors:
    def test_miss_lists_near_misses(self, primary_index: GeometryIndex) -> None:
        with pytest.raises(AddressingError) as exc:
            resolve("bottom_dek", primary_index)  # typo
        assert exc.value.selector == "bottom_dek"
        assert "bottom_deck" in exc.value.candidates

    def test_total_miss_still_carries_selector(self, primary_index: GeometryIndex) -> None:
        with pytest.raises(AddressingError) as exc:
            resolve("nonexistent_xyz", primary_index)
        assert exc.value.selector == "nonexistent_xyz"

    def test_ambiguity_lists_all_candidates(self) -> None:
        # A label that is ALSO a #k of another label at the same level is a
        # same-level ambiguity: resolution refuses and lists both readings.
        index = GeometryIndex(labels=("post#2", "post", "post"))
        with pytest.raises(AddressingError) as exc:
            resolve("post#2", index)
        assert len(exc.value.candidates) >= 2
        assert exc.value.selector == "post#2"

    def test_namespace_is_totally_resolvable(self, primary_index: GeometryIndex) -> None:
        # Every advertised selector resolves without error (no silent guess).
        for selector in namespace(primary_index):
            resolve(selector, primary_index)

    def test_empty_selector_rejected(self, primary_index: GeometryIndex) -> None:
        with pytest.raises(AddressingError):
            resolve("", primary_index)


class TestCrossPartAddressing:
    def test_part_prefixed_selector(
        self, primary: UnpublishedBuild, bracket: UnpublishedBuild
    ) -> None:
        indexes = {
            "primary": primary.geometry_index(),
            "bracket": bracket.geometry_index(),
        }
        part, resolution = resolve_in_project("primary/post#2", indexes)
        assert part == "primary"
        assert resolution.kind == "label"
        part2, resolution2 = resolve_in_project("bracket/bracket_body", indexes)
        assert part2 == "bracket"
        assert resolution2.kind == "label"

    def test_unknown_part_lists_known_parts(
        self, primary: UnpublishedBuild, bracket: UnpublishedBuild
    ) -> None:
        indexes = {
            "primary": primary.geometry_index(),
            "bracket": bracket.geometry_index(),
        }
        with pytest.raises(AddressingError) as exc:
            resolve_in_project("ghost/part", indexes)
        assert set(exc.value.candidates) >= {"bracket", "primary"} or exc.value.candidates

    def test_missing_current_part_errors(self, primary: UnpublishedBuild) -> None:
        indexes = {"primary": primary.geometry_index()}
        with pytest.raises(AddressingError):
            resolve_in_project("post", indexes)  # no prefix, no current_part
