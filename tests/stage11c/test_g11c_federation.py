"""G11C clauses 9-10: merged federation, and every row naming its own tree.

``PARTS_STORE.md`` §8 opens on a real defect: ``RegistrySet.__init__`` did
``by_kind.setdefault(registry.kind, registry)`` and built every index from
``by_kind.get(<kind>)``, so **a second ``parts`` registry was silently
discarded** — no warning, no error, and which one survived depended on
``hephaestus.toml`` table order plus the bundled fallback. Any story in which a
vendor component pack sits beside the bundled ``hephaestus-parts`` was broken,
and broke as a *missing part* rather than as a configuration error.

G11A shipped the fail-closed half (``duplicate_registry_kind``) and §8 said
plainly what it was holding the place for: "**G11C ships merged federation**:
several ``parts`` registries indexed together, ids addressed ``<registry>/<id>``
when ambiguous and bare when unique, with a named ``ambiguous_component_id``
refusal rather than a precedence rule". This module is that clause, and the
refusal is the load-bearing part: choosing a winner by pin order is the original
defect wearing a different hat.

Clause 10 is small and easy to lose: both federated registries' digests appear in
their *own* search results, so a component always names the tree it came from.
Under federation that is what makes a row auditable at all — two rows carrying
the same id and no digest would be indistinguishable.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from _g11c import PART_ID, SHIPPED_PARTS, component_tree
from hephaestus.core.registry import (
    PartsIndex,
    RegistryError,
    RegistryRefusal,
    RegistrySet,
    load_registry,
)

#: A second component in the vendor tree that the bundled tree also carries, so
#: the collision is staged deliberately rather than depending on shipped content.
COLLIDING_ID = "bearing_608"


@pytest.fixture
def vendor(tmp_path: Path) -> Path:
    """A second ``parts`` tree: one unique id and one that collides."""
    root = component_tree(tmp_path / "vendor", registry_name="vendor-parts")
    shutil.copytree(SHIPPED_PARTS / COLLIDING_ID, root / COLLIDING_ID)
    manifest = root / "registry.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + f'\n[[parts]]\nid = "{COLLIDING_ID}"\ndir = "{COLLIDING_ID}"\n',
        encoding="utf-8",
    )
    return root


@pytest.fixture
def federated(vendor: Path) -> RegistrySet:
    return RegistrySet(
        {"hephaestus-parts": load_registry(SHIPPED_PARTS), "vendor-parts": load_registry(vendor)}
    )


# ==========================================================================
# clause 9 — merged federation


def test_two_parts_registries_index_together(federated: RegistrySet) -> None:
    """The clause's first words, and the end of the silent drop.

    Both trees' unique ids resolve from one index. Before this, one whole tree
    was gone and the only symptom was ``unknown_store_part``.
    """
    ids = set(federated.parts.ids())
    assert PART_ID in ids, "the vendor tree's own component must be reachable"
    assert "screw_socket_head_m3" in ids, "and so must the bundled tree's"
    assert federated.by_kind_all("parts") != ()
    assert len(federated.by_kind_all("parts")) == 2


def test_a_unique_id_resolves_bare(federated: RegistrySet) -> None:
    """Unchanged behaviour for every id only one tree carries.

    This is the compatibility half: a project that pins one pack, or pins two
    that do not collide, addresses every part exactly as it always did.
    """
    part = federated.parts.get(PART_ID)
    assert part.registry == "vendor-parts"
    assert federated.parts.address(part) == PART_ID


def test_a_colliding_id_resolves_under_registry_slash_id(federated: RegistrySet) -> None:
    both = {
        f"hephaestus-parts/{COLLIDING_ID}": "hephaestus-parts",
        f"vendor-parts/{COLLIDING_ID}": "vendor-parts",
    }
    for address, registry in both.items():
        part = federated.parts.get(address)
        assert part.id == COLLIDING_ID
        assert part.registry == registry
        assert federated.parts.address(part) == address


def test_a_colliding_id_addressed_bare_is_ambiguous_component_id(
    federated: RegistrySet,
) -> None:
    """A refusal, never a precedence rule.

    Which pack the operator meant is not derivable from table order, and
    answering with either one is a silent wrong answer of exactly the kind §8
    exists to remove. The refusal must NAME both candidates, or the operator
    cannot act on it.
    """
    with pytest.raises(RegistryError) as caught:
        federated.parts.get(COLLIDING_ID)
    error = caught.value
    assert error.reason == "ambiguous_component_id"
    candidates = cast("list[Any]", error.data["candidates"])
    assert {str(c) for c in candidates} == {
        f"hephaestus-parts/{COLLIDING_ID}",
        f"vendor-parts/{COLLIDING_ID}",
    }
    for candidate in candidates:
        assert str(candidate) in error.message


def test_an_ambiguous_bare_id_is_not_listed_as_addressable(federated: RegistrySet) -> None:
    """``ids()`` lists what actually resolves, so the candidate list is honest.

    ``unknown_store_part`` reports ``ids()`` as "available ids". Listing a bare
    id that is a refusal would hand the caller a string that cannot work.
    """
    ids = set(federated.parts.ids())
    assert COLLIDING_ID not in ids
    assert {f"hephaestus-parts/{COLLIDING_ID}", f"vendor-parts/{COLLIDING_ID}"} <= ids


def test_component_ids_addresses_the_same_way(federated: RegistrySet) -> None:
    component_ids = set(federated.parts.component_ids())
    assert PART_ID in component_ids
    assert COLLIDING_ID not in component_ids
    assert f"vendor-parts/{COLLIDING_ID}" in component_ids


def test_one_registry_per_kind_still_behaves_exactly_as_before() -> None:
    """The single-tree case is byte-for-byte the old behaviour.

    Federation must not have changed what every existing project sees: bare
    ids, sorted, nothing qualified.
    """
    single = RegistrySet({"hephaestus-parts": load_registry(SHIPPED_PARTS)})
    assert single.parts.ids() == PartsIndex(load_registry(SHIPPED_PARTS)).ids()
    assert all("/" not in part_id for part_id in single.parts.ids())


def test_an_unfederated_kind_still_refuses_a_second_registry(tmp_path: Path) -> None:
    """``duplicate_registry_kind`` keeps its job where the merge does not exist.

    G11A's refusal is not deleted by this clause, it is *scoped*: ``parts`` is
    merged, and every other kind still reads one tree, where a second really
    would be dropped. Deleting the refusal outright would have re-opened §8's
    original defect for skills, materials and dfm.
    """
    materials = SHIPPED_PARTS.parent / "materials"
    second = tmp_path / "second-materials"
    shutil.copytree(materials, second)
    with pytest.raises(RegistryRefusal) as caught:
        RegistrySet({"a-materials": load_registry(materials), "b-materials": load_registry(second)})
    assert caught.value.reason == "duplicate_registry_kind"
    assert caught.value.detail["kind"] == "materials"
    assert "parts" in RegistrySet.FEDERATED_KINDS
    assert "materials" not in RegistrySet.FEDERATED_KINDS


def test_an_unknown_qualified_id_is_unknown_not_ambiguous(federated: RegistrySet) -> None:
    with pytest.raises(RegistryError) as caught:
        federated.parts.get("vendor-parts/no_such_part")
    assert caught.value.reason == "unknown_store_part"


# ==========================================================================
# clause 10 — a row always names the tree it came from


def test_both_registries_digests_appear_in_their_own_search_results(
    federated: RegistrySet, vendor: Path
) -> None:
    """Provenance per row, which under federation is the only thing separating them.

    Each row's ``registry_digest`` is the Merkle root of *its own* tree, so a
    search result is auditable back to bytes even when two rows share an id.
    """
    digests = {
        "hephaestus-parts": load_registry(SHIPPED_PARTS).digest,
        "vendor-parts": load_registry(vendor).digest,
    }
    assert digests["hephaestus-parts"] != digests["vendor-parts"]
    rows = federated.parts.search("bearing", max_results=10)
    seen = {str(row["registry"]) for row in rows}
    assert seen == {"hephaestus-parts", "vendor-parts"}
    for row in rows:
        assert row["registry_digest"] == digests[str(row["registry"])]


def test_a_search_row_returns_the_id_the_caller_must_hand_back(
    federated: RegistrySet,
) -> None:
    """Discovery has to produce an address, not a name that then refuses.

    A row whose ``id`` was the bare colliding one would advertise a string that
    ``instance_store_part`` refuses — search would be telling the model to do
    something the tool will not do.
    """
    rows = federated.parts.search(COLLIDING_ID, max_results=10)
    colliding = [row for row in rows if str(row["id"]).endswith(COLLIDING_ID)]
    assert len(colliding) == 2
    for row in colliding:
        assert str(row["id"]) == f"{row['registry']}/{COLLIDING_ID}"
        federated.parts.get(str(row["id"]))  # every advertised id resolves


def test_a_unique_rows_id_is_still_bare(federated: RegistrySet) -> None:
    (row,) = [r for r in federated.parts.search("provenance", max_results=10)]
    assert row["id"] == PART_ID


def test_search_result_order_is_stable_across_two_index_builds(vendor: Path) -> None:
    """Determinism support for clause 14: the order is a fact about the ids.

    Ties break on the *address*, not on which tree happened to be pinned first,
    so a federated result cannot reorder because a manifest was re-keyed.
    """
    forward = RegistrySet(
        {"a-hephaestus-parts": load_registry(SHIPPED_PARTS), "z-vendor": load_registry(vendor)}
    )
    reverse = RegistrySet(
        {"z-vendor": load_registry(vendor), "a-hephaestus-parts": load_registry(SHIPPED_PARTS)}
    )
    assert forward.parts.search("bearing", 10) == reverse.parts.search("bearing", 10)
