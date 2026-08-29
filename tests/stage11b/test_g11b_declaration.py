"""G11B clause 6: record ⇄ region interface-name set equality (item 11).

This is ``_dfm.py``'s "a predicate can therefore never read an undeclared
number" generalised: a generator can never emit an undeclared interface, and a
record can never declare one its generator does not implement. It lands here
and not in G11A because there is no region to compare against until clause 1's
parser exists — and binding it to G11A would have made every G11A clause that
indexes a component record depend on G11B, which is the ordering bug in its
purest form (the Gates preamble decides this in writing).

Both directions, on the same record, in the same suite, each naming the
offending interface — because "the sets differ" is not a fix instruction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from _g11b import (
    _RIG_BODY,
    RIG_INTERFACES,
    RIG_REGION,
    RIG_SRC,
    component_tree,
    index_of,
    rig,
)
from hephaestus.core.registry import (
    INTERFACE_MARKER,
    RegistryRefusal,
    publish_registry,
)


def _tree(tmp_path: Path, *, generator: str = RIG_SRC, **record: Any) -> Path:
    return component_tree(
        tmp_path / "reg", component=rig(**record) if record else None, generator=generator
    )


# ==========================================================================
# the equality holds for a well-formed pair


def test_a_matching_record_and_region_index_and_publish(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    index = index_of(root)
    part = index.get("rig")
    assert part.component is not None
    assert part.component.interface_names == tuple(name for name, _c, _r in RIG_INTERFACES)
    record = publish_registry(root)
    assert record.counts["components"] == 1


# ==========================================================================
# surplus — the region tags a name the record omits


def test_undeclared_interface_names_the_surplus(tmp_path: Path) -> None:
    surplus = (
        RIG_SRC + 'tag(_rig.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[0], "spare")\n'
    )
    root = _tree(tmp_path, generator=surplus)
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    assert caught.value.reason == "undeclared_interface"
    assert cast("list[Any]", caught.value.detail["interfaces"]) == ["spare"]
    assert "spare" in caught.value.message


def test_undeclared_interface_refuses_publication_too(tmp_path: Path) -> None:
    """``validate_content`` builds the index, so an index refusal is a publish refusal."""
    surplus = RIG_SRC + 'tag(_rig.solids().sort_by(SortBy.VOLUME)[0], "spare")\n'
    root = _tree(tmp_path, generator=surplus)
    with pytest.raises(RegistryRefusal) as caught:
        publish_registry(root)
    assert caught.value.reason == "undeclared_interface"


# ==========================================================================
# shortfall — the record declares a name the region never tags


def test_unimplemented_interface_names_the_shortfall(tmp_path: Path) -> None:
    trimmed = _RIG_BODY + INTERFACE_MARKER + "\n" + "\n".join(RIG_REGION.splitlines()[1:3]) + "\n"
    root = _tree(tmp_path, generator=trimmed)
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    assert caught.value.reason == "unimplemented_interface"
    assert cast("list[Any]", caught.value.detail["interfaces"]) == [
        "envelope",
        "rail",
        "shaft_ring",
    ]


def test_a_component_with_no_region_at_all_is_a_shortfall(tmp_path: Path) -> None:
    """The ``mating_features`` failure in its purest form: metadata nothing emits."""
    root = _tree(tmp_path, generator=_RIG_BODY)
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    assert caught.value.reason == "unimplemented_interface"
    assert set(cast("list[Any]", caught.value.detail["interfaces"])) == {
        name for name, _c, _r in RIG_INTERFACES
    }


def test_both_directions_on_the_same_record(tmp_path: Path) -> None:
    """One edit renames an interface, which is a surplus AND a shortfall at once."""
    renamed = RIG_SRC.replace('"rail"', '"beam"')
    root = _tree(tmp_path, generator=renamed)
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    # Surplus is reported first because an emitted tag nothing declares is the
    # one a model could already be anchoring against.
    assert caught.value.reason == "undeclared_interface"
    assert cast("list[Any]", caught.value.detail["interfaces"]) == ["beam"]

    dropped_surplus = RIG_SRC.replace(
        'tag(_rig.edges().filter_by(GeomType.LINE).sort_by(SortBy.LENGTH)[-1], "rail")\n', ""
    )
    root2 = component_tree(tmp_path / "reg2", generator=dropped_surplus)
    with pytest.raises(RegistryRefusal) as second:
        index_of(root2)
    assert second.value.reason == "unimplemented_interface"
    assert cast("list[Any]", second.value.detail["interfaces"]) == ["rail"]


# ==========================================================================
# the boundary, asserted rather than left to be discovered


def test_a_legacy_part_with_no_component_block_is_out_of_scope(tmp_path: Path) -> None:
    """Named, not hidden: the comparison runs for a *record*.

    G11B clause 6 scopes both refusals to "the same record", and the frozen
    pre-item-19 fixture G11A clause 3 rests on is exactly a pre-component
    ``part.json`` paired with the current generator — refusing that pairing
    would break a clause of the preceding sub-gate to close a hole no shipped
    content can reach. What it leaves open is narrow and stated in
    ``_parts.py``: a legacy store part could add a region and emit tags no
    record declares. Nothing in the repository does, and a part gaining a
    region is a part gaining a record.
    """
    root = component_tree(tmp_path / "legacy", component=None, generator=RIG_SRC)
    meta_path = root / "rig" / "part.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["component"]
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    index = index_of(root)
    part = index.get("rig")
    assert part.component is None
    assert index.component_ids() == ()
    # The row grows nothing, `interfaces` included.
    assert "interfaces" not in part.search_result()


# ==========================================================================
# clause 17's search half — the declared names, unprefixed


def test_the_search_row_carries_the_declared_interfaces_unprefixed(tmp_path: Path) -> None:
    """§3: the instance prefix is not known until instantiation, so a row cannot spell it."""
    root = _tree(tmp_path)
    rows = index_of(root).search("rig motor", 5)
    assert rows and rows[0]["id"] == "rig"
    interfaces = cast("list[dict[str, Any]]", rows[0]["interfaces"])
    assert [entry["name"] for entry in interfaces] == [name for name, _c, _r in RIG_INTERFACES]
    assert [entry["class"] for entry in interfaces] == [klass for _n, klass, _r in RIG_INTERFACES]
    assert [entry["role"] for entry in interfaces] == [role for _n, _c, role in RIG_INTERFACES]
    for entry in interfaces:
        assert "__" not in entry["name"]
