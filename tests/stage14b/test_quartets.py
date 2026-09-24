# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Gate G14B clauses 6-7: the five ledger quartets, and the anchor grammar.

Every assertion here runs against an **unbuilt** project on purpose: the
ledger pattern's whole point is that declaring needs no geometry, and clause
18's sieve depends on that staying true. Nothing in this module opens the
kernel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _g14b import (
    BENCH_PARTS,
    declare_baseline,
    fixture_entry,
    make_project,
    operation_entry,
    provenance,
    setup_entry,
    stock_entry,
    wcs_entry,
)
from hephaestus.core.project_store.cam import CamError, CamLedger, CamState
from hephaestus.core.project_store.layout import open_store


@pytest.fixture
def cam(tmp_path: Path) -> Any:
    layout = make_project(tmp_path / "proj", BENCH_PARTS)
    store = open_store(layout)
    try:
        yield CamState(layout, store)
    finally:
        store.close()


_DECLARATIONS: list[tuple[str, dict[str, Any]]] = [
    ("stock", {}),
    ("fixtures", {}),
    ("wcs", {}),
    ("setups", {}),
    ("operations", {}),
]


def _entry_for(kind: str) -> dict[str, Any]:
    return {
        "setups": setup_entry(),
        "stock": stock_entry(),
        "fixtures": fixture_entry(),
        "wcs": wcs_entry(),
        "operations": operation_entry(),
    }[kind]


def _ledger(cam: CamState, kind: str) -> CamLedger:
    return {
        "setups": cam.setups,
        "stock": cam.stock,
        "fixtures": cam.fixtures,
        "wcs": cam.wcs,
        "operations": cam.operations,
    }[kind]


# -- clause 6: declare -> update -> withdraw, replayable, nothing erased ----


@pytest.mark.parametrize("kind", ["setups", "stock", "fixtures", "wcs", "operations"])
def test_quartet_lifecycle_is_generational_and_erases_nothing(cam: CamState, kind: str) -> None:
    ledger = _ledger(cam, kind)
    entry = _entry_for(kind)
    entry_id = str(entry["id"])

    declared = ledger.declare(entry)
    assert declared.generation == 1
    assert declared.artifact_ref is not None

    updated = ledger.update(entry_id, {"note": "revised by the gate"}, "the gate revises it")
    assert updated.generation == 2
    assert updated.change is not None and updated.change.reason == "the gate revises it"

    withdrawn = ledger.withdraw(entry_id, "the gate withdraws it")
    assert withdrawn.generation == 3

    # read returns the withdrawn entry WITH its reason — never an erasure.
    state = ledger.state()
    row = state.by_id[entry_id]
    assert row.withdrawn is True
    assert row.withdrawn_reason == "the gate withdraws it"
    assert state.active == ()

    # every generation replayable, oldest first, each act recorded.
    history = ledger.history()
    assert [gen.generation for gen in history] == [1, 2, 3]
    assert [gen.change.kind for gen in history if gen.change] == [
        "declare",
        "update",
        "withdraw",
    ]
    # generation 1 still reads back the pre-update entry, byte-preserved.
    first = ledger.generation(history[0].artifact_ref or "")
    assert first.by_id[entry_id].withdrawn is False


@pytest.mark.parametrize("kind", ["setups", "stock", "fixtures", "wcs", "operations"])
def test_provenance_compulsion_refuses_by_the_owning_kind_name(cam: CamState, kind: str) -> None:
    """No requirement and not assumed => the kind's own ``invalid_*`` token."""
    ledger = _ledger(cam, kind)
    expected = {
        "setups": "invalid_setup",
        "stock": "invalid_stock",
        "fixtures": "invalid_fixture",
        "wcs": "invalid_wcs",
        "operations": "invalid_operation",
    }[kind]
    for broken in ({}, {"assumed": True}, {"requirement": "r-1", "assumed": True}):
        entry = _entry_for(kind)
        entry["provenance"] = broken
        with pytest.raises(CamError) as caught:
            ledger.declare(entry)
        assert caught.value.reason == expected
    # absent entirely:
    entry = _entry_for(kind)
    del entry["provenance"]
    with pytest.raises(CamError) as caught:
        ledger.declare(entry)
    assert caught.value.reason == expected
    assert _ledger(cam, kind).state().generation == 0, "nothing was written on refusal"


def test_update_requires_a_reason_and_never_patches_id(cam: CamState) -> None:
    cam.stock.declare(stock_entry())
    with pytest.raises(CamError):
        cam.stock.update("st-plate", {"note": "x"}, "  ")
    with pytest.raises(CamError):
        cam.stock.update("st-plate", {"id": "st-other"}, "rename attempt")
    with pytest.raises(CamError) as caught:
        cam.stock.update("st-missing", {"note": "x"}, "reason")
    assert caught.value.reason == "unknown_stock"


# -- clause 7: the anchor grammar ------------------------------------------


def test_slash_bearing_stock_anchor_is_refused_invalid_stock(cam: CamState) -> None:
    with pytest.raises(CamError) as caught:
        cam.stock.declare(stock_entry(origin_anchor="bracket/datum_corner"))
    assert caught.value.reason == "invalid_stock"
    assert "ANCHOR" in caught.value.message or "matching" in caught.value.message


def test_slash_bearing_wcs_anchor_is_refused_invalid_wcs(cam: CamState) -> None:
    with pytest.raises(CamError) as caught:
        cam.wcs.declare(wcs_entry(datum="bracket/face_top"))
    assert caught.value.reason == "invalid_wcs"


def test_the_anchor_pattern_is_the_8c_pattern_verbatim(cam: CamState) -> None:
    """One grammar, no new naming scheme (CAM.md §3.2)."""
    from hephaestus.core.project_store import cam as cam_module
    from hephaestus.core.project_store.constraints import ANCHOR_PATTERN

    assert cam_module.ANCHOR_PATTERN is ANCHOR_PATTERN
    # colon-selector and whole-part forms both declare.
    cam.stock.declare(stock_entry(id="st-a", origin_anchor="bracket:face_top"))
    cam.stock.declare(stock_entry(id="st-b", origin_anchor="bracket"))


def test_baseline_declares_cleanly_on_an_unbuilt_project(cam: CamState) -> None:
    """The whole five-ledger baseline needs no build (the constraints rule)."""
    declare_baseline(cam)
    cam.operations.declare(operation_entry())
    assert cam.operations.state().generation == 1
    state = cam.to_json()
    assert {"setups", "stock", "fixtures", "wcs", "operations"} <= set(state)


def test_operation_provenance_reason_required_when_assumed(cam: CamState) -> None:
    entry = operation_entry()
    entry["provenance"] = {"assumed": True}
    with pytest.raises(CamError) as caught:
        cam.operations.declare(entry)
    assert caught.value.reason == "invalid_operation"
    assert provenance()["assumed"] is True  # the helper itself carries a reason
