# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clause 21: ``heph cam check`` human and ``--json``.

The verb simulates and verifies; it writes nothing and prints no program
text. The ``--json`` record surfaces the ``in_process_stock_not_modelled``
stamp (clause 11's third place: result, header, CLI), and the exit code says
whether anything blocks — 0 clean, 1 blocking, 2 usage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from _g14c import check_kwargs, declare_drill_setup, foul_members
from hephaestus.core.cli import main as heph_main
from hephaestus.core.project_store.cam import CamState
from hephaestus.core.project_store.layout import load_project, open_store


@pytest.fixture
def project_cwd(bench_copy: tuple[Any, Any]) -> Any:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    previous = Path.cwd()
    os.chdir(layout.root)
    try:
        yield layout, store
    finally:
        os.chdir(previous)


def test_heph_cam_check_human(project_cwd: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert heph_main(["cam", "check"]) == 0
    out = capsys.readouterr().out
    assert "s-op1: checked" in out
    assert "coverage: covered" in out
    assert "round_trip: round_trip_identical" in out
    assert "simulation: matches_at_samples" in out
    assert "collision: no_collision_at_samples_in_declared_scene" in out
    # The stamp rides the collision line — the CLI never claims more than the
    # engine measured (§5.5).
    assert "in_process_stock_not_modelled" in out


def test_heph_cam_check_json_surfaces_the_stamp(
    project_cwd: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert heph_main(["cam", "check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok" and payload["partial"] is False
    program = payload["programs"][0]
    assert program["setup"] == "s-op1"
    assert program["collision"]["in_process_stock_not_modelled"] is True
    assert program["simulation"]["verdict"] == "matches_at_samples"
    # No program text anywhere in the record (the D2 mandate, structurally):
    # no block-shaped word sequence survives into any serialized value.
    blob = json.dumps(payload)
    for block in ("G0 X", "G1 X", "G2 X", "G3 X"):
        assert block not in blob


def test_heph_cam_check_named_subset_is_partial(
    project_cwd: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert heph_main(["cam", "check", "s-op1", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["partial"] is True


def test_a_blocking_finding_exits_one(project_cwd: Any, capsys: pytest.CaptureFixture[str]) -> None:
    layout, store = project_cwd
    CamState(layout, store).fixtures.update(
        "fx-post", {"members": foul_members()}, "the fouling fixture"
    )
    assert heph_main(["cam", "check", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    program = payload["programs"][0]
    assert program["collision"]["verdict"] == "collision_at_samples"


def test_an_unknown_setup_is_usage(project_cwd: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert heph_main(["cam", "check", "s-nope"]) == 2
    err = capsys.readouterr().err
    assert "s-nope" in err


def test_the_check_verb_writes_no_exports(project_cwd: Any) -> None:
    """Gate G14B clause 24's filesystem assertion, extended over the 14C
    paths per the amendment: no `.heph/exports/` tree appears."""
    layout, _store = project_cwd
    assert heph_main(["cam", "check", "--json"]) in (0, 1)
    assert not (layout.root / ".heph" / "exports").exists()
