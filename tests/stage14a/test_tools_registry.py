# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14A clauses 1-4: the fifth registry kind, ``tools`` (CAM.md §3.5).

Clause 1 — the kind loads, validates, and is refused when malformed; an unknown
kind is refused naming the valid kinds (the ``registry/_layout.py:70-72``
shape). Clause 2 — the Merkle digest catches tamper AND rename, because path
is bound into every leaf (``_digest.py:53-71``). Clause 3 — a record with no
``holder`` block is refused at load, by name: the holder is load-bearing,
because without it there is no collision claim to make at all. Clause 4 — a
``feeds`` entry lacking ``source`` is refused at load, by name: a number that
commands a machine is never invented (CAM.md §1.2).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from _g14a import FIXTURES, REGISTRIES, TOOLS_ROOT
from hephaestus.core.errors import ValidationError
from hephaestus.core.registry import (
    BUNDLED_KINDS,
    RegistryIntegrityError,
    RegistryRefusal,
    RegistrySet,
    ToolsIndex,
    load_registry,
    merkle_digest,
    parse_manifest,
)

FIXTURE_TREE = FIXTURES / "tools_registry"


def _fixture_copy(tmp_path: Path) -> Path:
    root = tmp_path / "tools"
    shutil.copytree(FIXTURE_TREE, root)
    return root


def _record(root: Path) -> dict[str, Any]:
    return json.loads((root / "em_fixture.json").read_text(encoding="utf-8"))


def _write_record(root: Path, record: dict[str, Any]) -> None:
    (root / "em_fixture.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


# -- clause 1: the kind loads, validates, and refuses ------------------------


def test_tools_is_the_fifth_bundled_registry_kind() -> None:
    """CAM.md amendment manifest, architecture.md §3.6 row: landed at 14A."""
    assert BUNDLED_KINDS == ("skills", "parts", "materials", "dfm", "tools")


def test_the_bundled_tools_registry_loads_and_indexes() -> None:
    registry = load_registry(TOOLS_ROOT)
    assert registry.kind == "tools"
    assert registry.manifest.license
    index = ToolsIndex(registry)
    assert "em_6mm_3fl_carbide" in index.ids()
    record = index.get("em_6mm_3fl_carbide")
    # The §3.5 example record, byte for byte where it counts.
    assert record.diameter_mm == 6.0
    assert record.flutes == 3
    assert record.holder.kind == "er32_collet"
    assert record.holder.envelope == "cylinder"
    assert record.simplifications, "simplifications is safety content, not documentation"
    feed = record.feed_for("al-6061", "pocket")
    assert feed is not None and feed.source
    assert record.feed_for("al-6061", "profile") is None, "no matching entry is None, never a guess"
    assert record.registry == "hephaestus-tools"
    assert record.digest.startswith("sha256:")


def test_the_tools_registry_resolves_through_the_project_registry_set(tmp_path: Path) -> None:
    (tmp_path / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    registries = RegistrySet.open(tmp_path)
    assert registries.tools.has("em_6mm_3fl_carbide")
    assert all(entry["registry_digest"] for entry in registries.tools.listing())


def test_an_unknown_registry_kind_is_refused_naming_the_valid_kinds() -> None:
    manifest = (
        '[registry]\nname = "x"\nkind = "cutlery"\nversion = "0.0.1"\nlicense = "Apache-2.0"\n'
    )
    with pytest.raises(ValidationError) as caught:
        parse_manifest(manifest)
    message = caught.value.message
    assert "cutlery" in message
    for kind in BUNDLED_KINDS:
        assert kind in message, f"the refusal names every valid kind ({kind} missing)"


def test_a_malformed_tool_record_is_refused_at_load(tmp_path: Path) -> None:
    root = _fixture_copy(tmp_path)
    record = _record(root)
    record["diameter_mm"] = "six millimetres"
    _write_record(root, record)
    with pytest.raises(ValidationError, match="diameter_mm"):
        ToolsIndex(load_registry(root))


def test_a_manifest_listing_a_missing_record_file_is_refused(tmp_path: Path) -> None:
    root = _fixture_copy(tmp_path)
    (root / "em_fixture.json").unlink()
    with pytest.raises(ValidationError, match="missing"):
        ToolsIndex(load_registry(root))


def test_an_unknown_tool_id_lists_the_candidates() -> None:
    from hephaestus.core.registry import RegistryError

    index = ToolsIndex(load_registry(TOOLS_ROOT))
    with pytest.raises(RegistryError) as caught:
        index.get("em_99mm")
    assert caught.value.reason == "unknown_tool"
    assert "em_6mm_3fl_carbide" in caught.value.message


# -- clause 2: tamper AND rename fail the Merkle digest ----------------------


def test_a_tampered_tools_tree_fails_its_digest_and_refuses_to_load(tmp_path: Path) -> None:
    root = _fixture_copy(tmp_path)
    pin = merkle_digest(root)
    record_path = root / "em_fixture.json"
    record_path.write_text(
        record_path.read_text(encoding="utf-8").replace('"diameter_mm": 6.0', '"diameter_mm": 6.1'),
        encoding="utf-8",
    )
    assert merkle_digest(root) != pin
    with pytest.raises(RegistryIntegrityError) as caught:
        load_registry(root, expected_digest=pin)
    assert caught.value.expected == pin
    assert caught.value.actual == merkle_digest(root)


def test_a_renamed_file_fails_the_digest_too(tmp_path: Path) -> None:
    """Path is bound into the leaf (``_digest.py:53-71``): a rename is as
    detectable as an edit, with every byte of content unchanged."""
    root = _fixture_copy(tmp_path)
    pin = merkle_digest(root)
    (root / "em_fixture.json").rename(root / "em_renamed.json")
    assert merkle_digest(root) != pin, "identical bytes under a new name still move the root"
    with pytest.raises(RegistryIntegrityError):
        load_registry(root, expected_digest=pin)


def test_the_bundled_tools_tree_digest_is_stable_across_reads() -> None:
    assert merkle_digest(TOOLS_ROOT) == merkle_digest(TOOLS_ROOT)


# -- clause 3: no holder block, no record ------------------------------------


def test_a_tool_record_with_no_holder_block_is_refused_at_load_by_name(tmp_path: Path) -> None:
    root = _fixture_copy(tmp_path)
    record = _record(root)
    del record["holder"]
    _write_record(root, record)
    with pytest.raises(RegistryRefusal) as caught:
        ToolsIndex(load_registry(root))
    assert caught.value.reason == "tool_missing_holder"
    assert caught.value.detail["tool"] == "em_fixture"
    assert "collision" in caught.value.message, "the refusal states why the holder is load-bearing"


# -- clause 4: a feeds entry lacking source is refused at load ---------------


@pytest.mark.parametrize("broken", [None, ""], ids=["absent", "empty"])
def test_a_feeds_entry_lacking_source_is_refused_at_load_by_name(
    tmp_path: Path, broken: str | None
) -> None:
    root = _fixture_copy(tmp_path)
    record = _record(root)
    if broken is None:
        del record["feeds"][0]["source"]
    else:
        record["feeds"][0]["source"] = broken
    _write_record(root, record)
    with pytest.raises(RegistryRefusal) as caught:
        ToolsIndex(load_registry(root))
    assert caught.value.reason == "tool_feed_missing_source"
    assert caught.value.detail["tool"] == "em_fixture"


def test_every_bundled_tool_record_carries_a_holder_and_sourced_feeds() -> None:
    """The bundled content obeys the rules the loader enforces — asserted
    directly so the shipped tree can never regress ahead of its loader."""
    index = ToolsIndex(load_registry(TOOLS_ROOT))
    assert index.ids(), "the bundled registry carries the cutters the gate fixtures need"
    for tool_id in index.ids():
        record = index.get(tool_id)
        assert record.holder.diameter_mm > 0 and record.holder.length_mm > 0
        for entry in record.feeds:
            assert entry.source, f"{tool_id} feeds entry with no source survived load"
        assert record.simplifications


def test_the_tools_registry_carries_no_executable_content() -> None:
    """CAM.md §3.5: unlike parts (generators) and dfm (predicates), a tool
    record is pure data — no .py file anywhere in the tree."""
    assert not list(REGISTRIES.joinpath("tools").rglob("*.py"))
