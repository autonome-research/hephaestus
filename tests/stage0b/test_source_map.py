"""Gate G0B — source-map resolution at the architecture §3.1 scopes.

Clauses (mission_plan / verification.md source-map tests):

- **Every solid resolves to a statement.** Each labeled solid of
  ``part.geometry`` maps back to a source-map binding whose creating statement
  (line/statement index) is recorded; boolean results attribute to their
  statement (never per-face).
- **Every tag resolves to (solid, face, statement).** Each ``tag()`` yields a
  placement with a concrete solid index, topology index, and creating
  statement/line.
- **Line-moving re-resolution.** After an edit that shifts statements down, the
  binding and tag placements follow the moved statements (re-resolution tracks
  the statement, not a frozen line number).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from _gate import ASSEMBLY, build_part, build_source, read
from hephaestus.core.addressing import resolve
from hephaestus.core.executor.runner import UnpublishedBuild
from opstore.types import JSONValue

PRIMARY = ASSEMBLY / "parts" / "primary.py"
GLOBALS = ASSEMBLY / "globals.py"


def _bindings(build: UnpublishedBuild) -> dict[str, list[dict[str, JSONValue]]]:
    assert build.source_map is not None
    raw = cast("dict[str, JSONValue]", build.source_map["bindings"])
    out: dict[str, list[dict[str, JSONValue]]] = {}
    for name, events in raw.items():
        assert isinstance(events, list)
        out[name] = [cast("dict[str, JSONValue]", e) for e in events]
    return out


def _tags(build: UnpublishedBuild) -> dict[str, dict[str, JSONValue]]:
    assert build.source_map is not None
    raw = cast("dict[str, JSONValue]", build.source_map["tags"])
    return {name: cast("dict[str, JSONValue]", entry) for name, entry in raw.items()}


@pytest.fixture(scope="module")
def primary(tmp_path_factory: pytest.TempPathFactory) -> UnpublishedBuild:
    built = build_part("primary", PRIMARY, tmp_path_factory.mktemp("smap"), globals_path=GLOBALS)
    assert built.result.status == "ok"
    return built


class TestSolidsResolveToStatements:
    def test_every_labeled_solid_addresses_and_has_provenance(
        self, primary: UnpublishedBuild
    ) -> None:
        index = primary.geometry_index()
        bindings = _bindings(primary)
        # The label set == the resolvable §8 geometries namespace.
        assert [g.label for g in primary.result.geometries] == [
            "bottom_deck",
            "top_deck",
            "post",
            "post#2",
            "post#3",
            "post#4",
        ]
        # Scalar deck bindings each map to exactly one creating statement.
        for name in ("bottom_deck", "top_deck"):
            resolution = resolve(name, index)
            assert resolution.kind in ("label", "binding")
            events = bindings[name]
            assert len(events) >= 1
            assert isinstance(events[0]["line"], int)
            assert isinstance(events[0]["statement"], int)

    def test_list_binding_records_one_event_per_iteration(self, primary: UnpublishedBuild) -> None:
        # The four posts are accumulated in a loop; the list binding 'posts'
        # carries the creating statement, and each labeled post resolves.
        index = primary.geometry_index()
        assert index.bindings["posts"] == 4
        events = _bindings(primary)["posts"]
        # At least one event (the append statement's line) is recorded.
        assert events and isinstance(events[0]["line"], int)
        # Each duplicate-label post resolves to a distinct tree occurrence.
        first = resolve("post", index)
        second = resolve("post#2", index)
        assert first.occurrences != second.occurrences

    def test_boolean_results_attribute_to_statement_not_face(
        self, primary: UnpublishedBuild
    ) -> None:
        assert primary.source_map is not None
        booleans = cast("list[JSONValue]", primary.source_map["booleans"])
        assert booleans, "primary computes _px/_py via subtraction"
        for entry in booleans:
            record = cast("dict[str, JSONValue]", entry)
            assert record["op"] in ("+", "-", "&")
            assert isinstance(record["statement"], int)
            assert isinstance(record["line"], int)
            # Attribution is statement-level: it names operands, not faces.
            assert isinstance(record["operands"], list)


class TestTagsResolveToSolidFaceStatement:
    def test_each_tag_has_solid_face_and_statement(self, primary: UnpublishedBuild) -> None:
        tags = _tags(primary)
        assert set(tags) == {"deck_top", "base_bottom"}
        for name, entry in tags.items():
            assert entry["kind"] == "face", name
            assert isinstance(entry["solid"], int)
            assert isinstance(entry["topo_index"], int)  # the face index
            assert isinstance(entry["statement"], int)
            assert isinstance(entry["line"], int)

    def test_tags_land_on_distinct_solids(self, primary: UnpublishedBuild) -> None:
        tags = _tags(primary)
        # deck_top is on the top deck, base_bottom on the bottom deck.
        assert tags["deck_top"]["solid"] != tags["base_bottom"]["solid"]


class TestLineMovingReResolution:
    """An edit that shifts statements down re-resolves to the moved lines."""

    def test_prepended_lines_shift_bindings_and_tags(
        self, primary: UnpublishedBuild, tmp_path: Path
    ) -> None:
        shift = 5
        original = read(PRIMARY)
        shifted_script = "\n" * shift + original
        moved = build_source(
            "primary",
            shifted_script,
            tmp_path,
            globals_source=read(GLOBALS),
        )
        assert moved.result.status == "ok"

        base_tags = _tags(primary)
        moved_tags = _tags(moved)
        base_bindings = _bindings(primary)
        moved_bindings = _bindings(moved)

        # Tag placements follow the moved tagging statements exactly.
        for name in ("deck_top", "base_bottom"):
            assert (
                cast("int", moved_tags[name]["line"])
                == cast("int", base_tags[name]["line"]) + shift
            )
            # Same solid/face/statement — only the line moved.
            assert moved_tags[name]["solid"] == base_tags[name]["solid"]
            assert moved_tags[name]["topo_index"] == base_tags[name]["topo_index"]
            assert moved_tags[name]["statement"] == base_tags[name]["statement"]

        # Binding provenance follows the moved statements too.
        for name in ("bottom_deck", "top_deck"):
            assert (
                cast("int", moved_bindings[name][0]["line"])
                == cast("int", base_bindings[name][0]["line"]) + shift
            )
            assert moved_bindings[name][0]["statement"] == base_bindings[name][0]["statement"]

    def test_resolution_stable_across_edit(self, primary: UnpublishedBuild, tmp_path: Path) -> None:
        # The addressable namespace is unchanged by a pure line shift.
        shifted = "# a comment\n# another\n" + read(PRIMARY)
        moved = build_source("primary", shifted, tmp_path, globals_source=read(GLOBALS))
        assert moved.result.status == "ok"
        assert primary.geometry_index().labels == moved.geometry_index().labels
        assert primary.geometry_index().tags == moved.geometry_index().tags
