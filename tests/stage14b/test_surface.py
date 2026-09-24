# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Gate G14B clause 22: the tool surface through dispatch, on both profiles.

Fifteen tools — the five declare/update/read quartet families — through the
**real dispatcher**, as the orchestrator and as a bound part session, with
the reviewer refused; plus the contract-drift half: the generated artifacts
reproduce the committed bytes, the pin sits at the current surface count in
both pinned suites (57 -> 72 at 14B, repointed 72 -> 73 by 14C's
`check_program` landing per the per-sub-stage pin discipline), and both cite
their stages.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g14b import (
    BENCH_PARTS,
    fixture_entry,
    make_project,
    operation_entry,
    setup_entry,
    stock_entry,
    wcs_entry,
)
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import (
    CAD_TOOLS,
    DispatchError,
    Principal,
    ToolDispatcher,
)
from hephaestus.contract import toolgen, tools_decl
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.tools_fixture import Project

REPO = Path(__file__).resolve().parents[2]

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)
PART = Principal(session_id="p1", profile="part", part="bracket")
REVIEWER = Principal(session_id="rv", profile="reviewer", part=None)

CAM_TOOLS = (
    "declare_setup",
    "update_setup",
    "read_setups",
    "declare_stock",
    "update_stock",
    "read_stock",
    "declare_fixture",
    "update_fixture",
    "read_fixtures",
    "declare_wcs",
    "update_wcs",
    "read_wcs",
    "declare_operation",
    "update_operation",
    "read_operations",
)


@pytest.fixture(scope="module")
def wired(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    root = tmp_path_factory.mktemp("g14b-surface") / "proj"
    make_project(root, BENCH_PARTS)
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    project = Project(
        root=root,
        layout=layout,
        store=store,
        cad=cad,
        dispatcher=ToolDispatcher(ProjectStore(layout, store), cad=cad),
        _n=[0],
    )
    try:
        yield project
    finally:
        project.close()


def _declare_all(project: Project, principal: Principal, suffix: str) -> None:
    entries = {
        "declare_stock": stock_entry(id=f"st-{suffix}"),
        "declare_fixture": fixture_entry(id=f"fx-{suffix}"),
        "declare_wcs": wcs_entry(id=f"w-{suffix}"),
        "declare_setup": setup_entry(
            id=f"s-{suffix}",
            order={"orch": 1, "part": 2}[suffix],
            stock=f"st-{suffix}",
            fixture=f"fx-{suffix}",
            wcs=f"w-{suffix}",
        ),
        "declare_operation": operation_entry(
            id=f"op-{suffix}", setup=f"s-{suffix}", feature=f"bracket:pocket_{suffix}_x"
        ),
    }
    order = (
        "declare_stock",
        "declare_fixture",
        "declare_wcs",
        "declare_setup",
        "declare_operation",
    )
    for tool in order:
        result = cast(
            "dict[str, Any]", project.call(tool, dict(entries[tool]), principal=principal)
        )
        assert result["status"] == "ok"
        assert result["generation"] >= 1


def test_both_profiles_dispatch_the_whole_quartet_surface(wired: Project) -> None:
    """Declare, update and read through the dispatcher as ORCH and as a part."""
    _declare_all(wired, ORCH, "orch")
    _declare_all(wired, PART, "part")
    for kind, entry_id in (
        ("setup", "s-orch"),
        ("stock", "st-orch"),
        ("fixture", "fx-orch"),
        ("wcs", "w-orch"),
        ("operation", "op-orch"),
    ):
        updated = cast(
            "dict[str, Any]",
            wired.call(
                f"update_{kind}",
                {"id": entry_id, "patch": {"note": "revised"}, "reason": "the gate revises"},
                principal=PART,
            ),
        )
        assert updated["status"] == "ok"
    for tool in ("read_setups", "read_stock", "read_fixtures", "read_wcs", "read_operations"):
        for principal in (ORCH, PART):
            result = cast("dict[str, Any]", wired.call(tool, {}, principal=principal))
            assert result["status"] == "ok"
            assert isinstance(result["entries"], list) and result["entries"]
    # withdrawal through the surface stays readable with its reason.
    wired.call(
        "update_operation",
        {"id": "op-part", "patch": {"withdrawn": True}, "reason": "the gate withdraws"},
    )
    rows = cast("dict[str, Any]", wired.call("read_operations", {}))
    withdrawn = [row for row in rows["entries"] if row.get("withdrawn")]
    assert withdrawn and withdrawn[0]["withdrawn_reason"] == "the gate withdraws"


def test_the_reviewer_profile_is_refused(wired: Project) -> None:
    for tool in CAM_TOOLS:
        with pytest.raises(DispatchError) as caught:
            wired.call(tool, {}, principal=REVIEWER)
        assert caught.value.reason == "scope_denied", tool


def test_refusals_cross_the_surface_with_their_ledger_tokens(wired: Project) -> None:
    """The ledger's stable token IS the dispatch refusal's reason, unchanged."""
    with pytest.raises(DispatchError) as caught:
        wired.call("declare_stock", stock_entry(id="st-bad", origin_anchor="a/b"))
    assert caught.value.reason == "invalid_stock"
    with pytest.raises(DispatchError) as caught:
        wired.call(
            "update_setup", {"id": "s-none", "patch": {"note": "x"}, "reason": "r"}
        )
    assert caught.value.reason == "unknown_setup"


# -- the contract-drift half ------------------------------------------------


def test_declared_surface_is_73_and_every_cam_tool_is_declared() -> None:
    # Repointed 72 -> 73 by 14C's `check_program` landing (2026-09-02), per
    # the per-sub-stage pin discipline this stage's plan block records: the
    # pin moves WITH the sub-stage that adds the tool, and 14B's own claims
    # (the quartet families, their profiles, no emission tool) stand.
    names = tools_decl.tool_names()
    assert len(names) == 73
    assert set(CAM_TOOLS) <= set(names)
    assert set(CAM_TOOLS) <= CAD_TOOLS
    for tool in CAM_TOOLS:
        decl = tools_decl.get_tool(tool)
        assert set(decl.profiles) == {"part", "orchestrator"}, tool
        if tool.startswith("read_"):
            assert not decl.sequential
        else:
            assert decl.sequential and decl.idempotent
    # No emission tool, structurally; 14C's one addition measures, never emits.
    assert "emit_program" not in names
    assert "check_program" in names


def test_contract_drift_artifacts_regenerate_clean() -> None:
    """The committed artifacts are byte-equal to a fresh generation."""
    for rel, text in toolgen.generate_json_schemas().items():
        assert (REPO / rel).read_text(encoding="utf-8") == text, f"{rel} is stale"
    ts = (REPO / "agent" / "src" / "tools" / "schema.gen.ts").read_text(encoding="utf-8")
    assert ts == toolgen.generate_typebox_module()


def test_both_pins_sit_at_73_citing_both_sub_stages() -> None:
    # 57 -> 72 at 14B, 72 -> 73 at 14C: both movements stay CITED in the
    # pinned suites, and the literal pin sits at the current surface.
    toolgen_pin = (REPO / "contract" / "tests" / "test_toolgen.py").read_text(encoding="utf-8")
    assert "assert len(tools_decl.tool_names()) == 73" in toolgen_pin
    assert "57 -> 72" in toolgen_pin and "Stage 14B" in toolgen_pin
    assert "72 -> 73" in toolgen_pin and "Stage 14C" in toolgen_pin
    drift_pin = (REPO / "tests" / "stage2" / "test_g2_contract_drift.py").read_text(
        encoding="utf-8"
    )
    assert "assert len(TOOL_NAMES) == 73" in drift_pin
    assert "Stage 14B" in drift_pin and "Stage 14C" in drift_pin
    agent_pin = (REPO / "agent" / "test" / "schema_gen.test.ts").read_text(encoding="utf-8")
    assert "toHaveLength(73)" in agent_pin and "Stage 14B" in agent_pin
