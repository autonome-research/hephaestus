"""G11A clauses 1-3: legacy compatibility, digest honesty, and item 19's move.

The three clauses are one argument in three parts, and the split is the point.
``PARTS_STORE.md`` §10's earlier draft claimed legacy parts behave "byte-for-byte
as today, **including their fragments**". That was false: ``render_fragment``'s
second header line embeds ``part.digest``, which is ``registry.digest`` — the
Merkle root over the whole tree — and item 19 edits six ``part.json`` files, so
the root moves and with it the header of *every* fragment the tree produces,
including parts item 19 never touched.

So: clause 1 pins the fragment **body** under a fixed sentinel in place of that
line; clause 2 pins the elided line's digest to a root recomputed in the test,
so the header still cannot drift silently; clause 3 asserts item 19's digest
change as the deliverable it is, with ``publication_drift`` naming exactly the
edited files.

Clause 3's evidence was **repaired 2026-08-29** and the clause tightened with it
(``PARTS_STORE.md`` G11A clause 3, "Amended 2026-08-29"). The pre-edit fixture
recorded only ``part.json`` and the reconstruction read ``generator.py`` from the
*current* tree, so the "before" tree was a hybrid the moment item 31 appended an
``interface`` region to those same six generators — and the fragment-body
assertion compared one generator against itself, which cannot fail. Both files
are recorded now; item 19's drift is isolated with generators held constant on
both sides; the whole stage's drift is asserted in full beside it; and the six
shipped fragments have recorded goldens, which they never had.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest
from _g11a import (
    DIGEST_SENTINEL,
    GOLDENS,
    LEGACY_PARTS,
    SHIPPED_PARTS,
    elide_digest_line,
    header_digest,
    index_of,
    requires_bwrap,
)
from hephaestus.core.registry import (
    INTERFACE_MARKER,
    MANIFEST_FILENAME,
    merkle_digest,
    parse_generator,
    publication_drift,
    publish_registry,
    render_fragment,
)

PRE_ITEM19: Path = Path(__file__).resolve().parent / "fixtures" / "pre_item19_parts"

#: The recorded cases of clause 1: origin and placed, both parts.
LEGACY_CASES = [
    ("legacy_spacer", {"length": 10.0}, None, "legacy_spacer_origin.fragment.txt"),
    (
        "legacy_spacer",
        {"length": 25.0},
        {"x": 10.0, "y": 0.0, "z": 4.0},
        "legacy_spacer_placed.fragment.txt",
    ),
    (
        "legacy_washer",
        {"thickness": 0.8},
        {"x": 3.0, "y": -2.0, "z": 0.0, "rz": 45.0},
        "legacy_washer_placed.fragment.txt",
    ),
]


def _fragment(root: Path, part_id: str, params: dict[str, float], pos: dict[str, float] | None):
    index = index_of(root)
    part = index.get(part_id)
    generator = parse_generator(part.read_script(), source=str(part.script_path))
    return render_fragment(generator, part, params, pos)


# ==========================================================================
# clause 1 — legacy fragment-body invariance


@pytest.mark.parametrize(("part_id", "params", "pos", "golden"), LEGACY_CASES)
def test_a_legacy_fragment_body_matches_its_recorded_golden(
    part_id: str, params: dict[str, float], pos: dict[str, float] | None, golden: str
) -> None:
    """Binds, renamed locals, kept body lines, placement and `.label`, pinned."""
    rendered = elide_digest_line(_fragment(LEGACY_PARTS, part_id, params, pos))
    recorded = (GOLDENS / golden).read_text(encoding="utf-8")
    assert rendered == recorded
    assert DIGEST_SENTINEL in rendered, "the elision must actually have fired"


def test_a_legacy_part_indexes_and_searches_with_no_component_fields() -> None:
    """The §3 result grows *only* for a component record."""
    index = index_of(LEGACY_PARTS)
    assert index.ids() == ("legacy_spacer", "legacy_washer")
    assert index.component_ids() == ()
    for part_id in index.ids():
        part = index.get(part_id)
        assert part.component is None
        assert part.is_component is False
        row = part.search_result()
        assert set(row) == {"id", "name", "params", "preview", "registry", "registry_digest"}
    rows = index.search("spacer standoff", 5)
    assert rows and rows[0]["id"] == "legacy_spacer"
    for row in rows:
        for absent in ("component_class", "series", "mass_g", "has_datasheet", "interfaces"):
            assert absent not in row


def test_a_legacy_part_still_carries_the_pre_component_metadata_keys() -> None:
    """ "Behaves exactly as today" includes keeping keys a component may not keep.

    §1 retires ``envelope`` / ``mating_features`` / ``origin`` /
    ``simplifications`` *from component records*. Refusing them on a legacy part
    would break the very compatibility clause 1 asserts, so the fixture carries
    them and the index reads it clean.
    """
    meta = json.loads((LEGACY_PARTS / "legacy_spacer" / "part.json").read_text(encoding="utf-8"))
    assert {"envelope", "mating_features", "origin", "simplifications"} <= set(meta)
    assert "component" not in meta
    assert index_of(LEGACY_PARTS).get("legacy_spacer").component is None


@requires_bwrap
def test_a_legacy_part_instantiates_through_the_real_tool(tmp_path: Path) -> None:
    """Clause 1's "instantiates" leg: the tool, the sandbox, the same body."""
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend
    from hephaestus.core.registry import RegistryOps, RegistrySet, load_registry

    from opstore import OpStore

    store = OpStore.create(tmp_path / "store")
    try:
        ops = RegistryOps(
            RegistrySet({"parts": load_registry(LEGACY_PARTS)}),
            store,
            backend=BwrapBackend(),
            scratch_root=tmp_path / "scratch",
        )
        # The same `pos` dict as the recorded case: `instance_prefix` hashes the
        # dict as given, so `{"x": 10.0, "z": 4.0}` and `{"x": 10.0, "y": 0.0,
        # "z": 4.0}` are different instances even though they place identically.
        result = ops.instance_store_part(
            "legacy_spacer", {"length": 25.0}, {"x": 10.0, "y": 0.0, "z": 4.0}
        )
        fragment = result["script_fragment"]
        assert isinstance(fragment, str)
        recorded = (GOLDENS / "legacy_spacer_placed.fragment.txt").read_text(encoding="utf-8")
        assert elide_digest_line(fragment) == recorded
        # A legacy part's result grows nothing: no mass, no datasheet.
        assert "mass" not in result
        assert "datasheet" not in result
    finally:
        store.close()


# ==========================================================================
# clause 2 — digest honesty


@pytest.mark.parametrize(("part_id", "params", "pos", "golden"), LEGACY_CASES)
def test_the_elided_header_line_states_the_recomputed_merkle_root(
    part_id: str, params: dict[str, float], pos: dict[str, float] | None, golden: str
) -> None:
    """What the elision hides is still checked — just checked separately."""
    fragment = _fragment(LEGACY_PARTS, part_id, params, pos)
    assert header_digest(fragment) == merkle_digest(LEGACY_PARTS)


def test_the_header_digest_equals_the_publication_record_digest(tmp_path: Path) -> None:
    tree = tmp_path / "legacy"
    shutil.copytree(LEGACY_PARTS, tree)
    record = publish_registry(tree)
    fragment = _fragment(tree, "legacy_spacer", {"length": 10.0}, None)
    assert header_digest(fragment) == record.digest == merkle_digest(tree)


def test_a_moved_byte_moves_the_header_digest(tmp_path: Path) -> None:
    """The elision is not a licence for the header to drift silently."""
    tree = tmp_path / "legacy"
    shutil.copytree(LEGACY_PARTS, tree)
    before = header_digest(_fragment(tree, "legacy_spacer", {"length": 10.0}, None))
    readme = tree / "NOTE.md"
    readme.write_text("# a byte moved\n", encoding="utf-8")
    after = header_digest(_fragment(tree, "legacy_spacer", {"length": 10.0}, None))
    assert after != before
    assert after == merkle_digest(tree)


# ==========================================================================
# clause 3 — the shipped six and the digest change item 19 delivers


#: The files a reconstructed pre-stage tree is built from. Every one is read from
#: the frozen fixture — **including ``generator.py``**, which is the correction
#: this repair makes. An earlier form read ``generator.py`` from the *current*
#: shipped tree, so the reconstruction was a hybrid: this stage's item 31 added
#: an ``interface`` region to all six shipped generators, and a "before" tree
#: carrying "after" generators is not the tree that existed. Two things went
#: wrong because of it — the fixture README claimed only ``part.json`` differed
#: from the shipped tree, which had stopped being true, and the fragment-body
#: clause compared the *same* generator on both sides, so it structurally could
#: not detect a generator edit, and one had been made.
RECORDED_FILES = ("part.json", "generator.py")


def _pre_item19_tree(tmp_path: Path, *, name: str = "pre-item19") -> Path:
    """The shipped tree as it stood before item 19: recorded bytes, not arithmetic.

    Pre-item-19 and pre-Stage-11 are the same bytes for this tree, because item
    19 is the only edit the stage made to these ``part.json`` files and item 31
    the only edit to these ``generator.py`` files; both sets are recorded here as
    they stood before either ran.
    """
    tree = tmp_path / name
    tree.mkdir()
    (tree / MANIFEST_FILENAME).write_bytes((PRE_ITEM19 / MANIFEST_FILENAME).read_bytes())
    for directory in sorted(p for p in PRE_ITEM19.iterdir() if p.is_dir()):
        target = tree / directory.name
        target.mkdir()
        for filename in RECORDED_FILES:
            (target / filename).write_bytes((directory / filename).read_bytes())
    return tree


def _item19_only_tree(tmp_path: Path) -> Path:
    """The pre-stage tree with **only** item 19's edit applied.

    Item 19 edited six ``part.json`` files; item 31 later edited the same six
    directories' ``generator.py``. Clause 3's "names exactly the edited
    ``part.json`` files and no others" is a statement about *item 19*, so it is
    asserted against a tree where item 19 is the only difference — generators
    held at their recorded pre-stage bytes on both sides. The whole-stage drift,
    generator edits included, is asserted separately and in full below, so
    nothing is hidden by the isolation.

    This tree is deliberately never indexed: the post-item-19 records declare
    interfaces the pre-item-31 generators do not emit, which item 11 refuses as
    ``unimplemented_interface``. That refusal is correct and is G11B clause 6's;
    ``publication_drift`` reads leaves, not records, so the isolation is still
    computable.
    """
    tree = _pre_item19_tree(tmp_path, name="item19-only")
    for part_id in SHIPPED_IDS:
        (tree / part_id / "part.json").write_bytes(
            (SHIPPED_PARTS / part_id / "part.json").read_bytes()
        )
    return tree


SHIPPED_IDS = (
    "heatset_insert_m3",
    "heatset_insert_m4",
    "heatset_insert_m5",
    "screw_socket_head_m3",
    "screw_socket_head_m4",
    "screw_socket_head_m5",
)

#: The packs G11C's half of item 31 adds beside the six.
ADDED_PACKS = ("bearing_608", "gear_module1_z20", "stepper_nema17_frame")


@pytest.mark.parametrize("part_id", SHIPPED_IDS)
def test_the_recorded_pre_tree_is_recorded_and_not_a_hybrid(part_id: str, tmp_path: Path) -> None:
    """Fixture integrity, asserted rather than described in a README.

    Both recorded files must differ from the shipped tree's — ``part.json``
    because item 19 edited it, ``generator.py`` because item 31 added its
    interface region. If a future stage stops editing one of them, this fails and
    the author has to decide deliberately, rather than a "before" fixture
    silently becoming a copy of "after".
    """
    tree = _pre_item19_tree(tmp_path)
    for filename in RECORDED_FILES:
        recorded = (tree / part_id / filename).read_bytes()
        assert recorded == (PRE_ITEM19 / part_id / filename).read_bytes(), "read from the fixture"
        assert recorded != (SHIPPED_PARTS / part_id / filename).read_bytes(), (
            f"{part_id}/{filename}: the recorded 'before' must not be the current 'after'"
        )
    assert "interface" not in (tree / part_id / "generator.py").read_text(encoding="utf-8")
    assert INTERFACE_MARKER in (SHIPPED_PARTS / part_id / "generator.py").read_text(
        encoding="utf-8"
    )


def test_item19_moved_the_tree_root(tmp_path: Path) -> None:
    before = merkle_digest(_pre_item19_tree(tmp_path))
    after = merkle_digest(SHIPPED_PARTS)
    assert before != after, "item 19's stated deliverable IS a Merkle-root change (§1)"
    # And item 19 alone moves it: the isolation tree differs from the pre tree in
    # nothing but those six records, and its root already differs.
    assert merkle_digest(_item19_only_tree(tmp_path)) != before


#: The parts item 19 edited, and the whole of what A shipped. Named separately
#: from the tree's current contents because clause 3 is about *those six files*
#: and their edit, which is a fact that does not change when a later sub-stage
#: adds parts beside them.
ITEM19_PART_COUNT = 6

#: What the bundled tree holds now. **Repointed 2026-08-29** by PARTS_STORE.md's
#: Named new work item 31, assigned in the Gates sub-stage table as "item 31 for
#: the completed packs" — G11C — which adds ``bearing_608``,
#: ``gear_module1_z20`` and ``stepper_nema17_frame``. Clause 3's own subject is
#: unchanged: item 19's digest change, and ``publication_drift`` naming exactly
#: the ``part.json`` files item 19 edited. The added packs appear as ``added``
#: below, which is what a Merkle leaf list is for.
SHIPPED_PART_COUNT = 9


def test_the_new_root_republishes_and_repins(tmp_path: Path) -> None:
    tree = tmp_path / "shipped"
    shutil.copytree(SHIPPED_PARTS, tree)
    record = publish_registry(tree)
    assert record.digest == merkle_digest(tree)
    assert publication_drift(tree, record) == ()
    assert record.counts["parts"] == SHIPPED_PART_COUNT
    assert record.counts["components"] == SHIPPED_PART_COUNT


def test_publication_drift_names_exactly_the_edited_part_json_files(tmp_path: Path) -> None:
    """Not "the hash changed" — *which* files. The whole point of the leaf list.

    Item 19 in isolation, against a tree whose generators are held at their
    recorded pre-stage bytes on both sides, so the clause's "exactly the edited
    ``part.json`` files **and no others**" is asserted over the *whole* drift set
    rather than over a filtered view of it. The earlier form filtered, and it had
    to: its "before" tree carried the current generators, so a generator edit was
    invisible to it by construction.
    """
    record = publish_registry(_pre_item19_tree(tmp_path))
    isolated = publication_drift(_item19_only_tree(tmp_path), record)
    drift = {item.path: item.status for item in isolated}
    assert drift == {f"{part_id}/part.json": "modified" for part_id in SHIPPED_IDS}


def test_publication_drift_accounts_for_every_file_the_whole_stage_touched(
    tmp_path: Path,
) -> None:
    """And the whole stage, with each file attributed to the item that moved it.

    Nothing is filtered out here. The six ``part.json`` are item 19's; the six
    ``generator.py`` are item 31's interface regions (G11B); ``registry.toml``
    indexes the packs G11C's half of item 31 adds; those three packs are
    ``added``. If a later edit touches a seventh file in this tree, the equality
    fails and it has to be named.
    """
    record = publish_registry(_pre_item19_tree(tmp_path))
    post = tmp_path / "shipped"
    shutil.copytree(SHIPPED_PARTS, post)
    drift = {item.path: item.status for item in publication_drift(post, record)}

    item19 = {f"{part_id}/part.json": "modified" for part_id in SHIPPED_IDS}
    item31_regions = {f"{part_id}/generator.py": "modified" for part_id in SHIPPED_IDS}
    added = {f"{pack}/{filename}": "added" for pack in ADDED_PACKS for filename in RECORDED_FILES}
    assert drift == {**item19, **item31_regions, **added, MANIFEST_FILENAME: "modified"}


@pytest.mark.parametrize("part_id", SHIPPED_IDS)
def test_every_shipped_fragment_body_survived_item19_unchanged(
    part_id: str, tmp_path: Path
) -> None:
    """Item 19's edits were metadata, not source — asserted so a *generator* edit
    cannot hide inside the claim.

    The pre-stage fragment must be a strict **prefix** of the shipped one, and
    the remainder must be exactly the rendered ``interface`` region: every line a
    ``tag`` call or one of the region's own comments, and every tag literal
    instance-scoped. That is a stronger statement than the equality this replaced
    — which compared the same generator against itself and so could not fail —
    and it is the true one: item 19 moved no body line, and the only thing that
    was appended is item 31's region, below the placement tail where §2.1 puts
    it.
    """
    pre = _pre_item19_tree(tmp_path)
    params = {"length": 12.0} if part_id.startswith("screw") else {"clearance": 0.1}
    pos = {"x": 4.0, "y": -1.5, "z": 2.0, "rz": 30.0}
    before = elide_digest_line(_fragment(pre, part_id, params, pos))
    after = elide_digest_line(_fragment(SHIPPED_PARTS, part_id, params, pos))
    assert after.startswith(before), "item 19 moved a fragment body line"
    remainder = after[len(before) :]
    assert remainder, "the shipped generator must emit an interface region (item 31)"
    # Parsed, not line-matched: three of the six regions wrap a `tag` call across
    # several lines, and a line-level check would call the continuation lines
    # unexpected statements.
    statements = ast.parse(remainder).body
    assert statements, "the remainder is not only prose"
    for statement in statements:
        assert isinstance(statement, ast.Expr), f"unexpected appended statement: {statement!r}"
        call = statement.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Name) and call.func.id == "tag"
        name = call.args[1]
        assert isinstance(name, ast.Constant) and isinstance(name.value, str)
        assert "__" in name.value, "every emitted tag literal is instance-scoped (§2.2)"


#: The shipped six's fragment goldens, recorded this stage. The pre-stage body is
#: pinned by the prefix relation above — it is these bytes minus the appended
#: region — so one recording covers both halves of clause 3's "pinned under the
#: clause-1 elision", for the six parts that previously had no golden at all.
SHIPPED_FRAGMENT_CASE = (
    {"x": 4.0, "y": -1.5, "z": 2.0, "rz": 30.0},
    {"screw": {"length": 12.0}, "heatset": {"clearance": 0.1}},
)


@pytest.mark.parametrize("part_id", SHIPPED_IDS)
def test_every_shipped_fragment_matches_its_recorded_golden(part_id: str) -> None:
    """The recorded pin clause 3's own words ask for, for the shipped six.

    Pre-vs-post equality alone is not a pin: it says the two sides agree, not
    what either says. A recorded golden is what makes an unintended edit to a
    shipped generator's *body* — as opposed to the region item 31 appended —
    fail here rather than pass silently on both sides.
    """
    pos, params_by_family = SHIPPED_FRAGMENT_CASE
    params = params_by_family[part_id.split("_")[0]]
    rendered = elide_digest_line(_fragment(SHIPPED_PARTS, part_id, params, pos))
    recorded = (GOLDENS / f"{part_id}.fragment.txt").read_text(encoding="utf-8")
    assert rendered == recorded
    assert DIGEST_SENTINEL in rendered, "the elision must actually have fired"
