# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Gate G14B clause 23: ``heph cam`` human and ``--json``.

The verb reads the five ledgers and nothing else; the prior-claim 2D ``heph
cam emit`` contract is untouched (its parser still requires ``<part>`` and
still owns the DXF path — CAM.md §1.4's reconciliation note).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from _g14b import (
    BENCH_PARTS,
    declare_baseline,
    make_project,
    operation_entry,
)
from hephaestus.core.cli import main as heph_main
from hephaestus.core.project_store.cam import CamState
from hephaestus.core.project_store.layout import open_store


@pytest.fixture
def project_cwd(tmp_path: Path) -> Any:
    layout = make_project(tmp_path / "proj", BENCH_PARTS)
    store = open_store(layout)
    cam = CamState(layout, store)
    declare_baseline(cam)
    cam.operations.declare(operation_entry())
    cam.operations.withdraw("op-rect", "withdrawn so the tables show a reason")
    store.close()
    previous = Path.cwd()
    os.chdir(layout.root)
    try:
        yield layout.root
    finally:
        os.chdir(previous)


def test_heph_cam_human_tables(
    project_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert heph_main(["cam"]) == 0
    out = capsys.readouterr().out
    for section in ("setups:", "stock:", "fixtures:", "wcs:", "operations:"):
        assert section in out
    assert "s-op1" in out and "st-plate" in out and "fx-vise" in out and "w-g54" in out
    # withdrawn entries are shown WITH their reasons, never hidden.
    assert "withdrawn so the tables show a reason" in out


def test_heph_cam_json(project_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert heph_main(["cam", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"setups", "stock", "fixtures", "wcs", "operations"}
    assert payload["setups"]["generation"] == 1
    ops = payload["operations"]["entries"]
    assert ops[0]["id"] == "op-rect" and ops[0]["withdrawn"] is True


def test_heph_cam_outside_a_project_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        assert heph_main(["cam"]) == 2
    finally:
        os.chdir(previous)
    assert "heph:" in capsys.readouterr().err


def test_the_2d_emit_verb_keeps_its_shipped_contract(project_cwd: Path) -> None:
    """Prior claim (CAM.md §1.4): ``heph cam emit`` still takes ``<part>``,
    still refuses without one, and gained no consent flags or setup form."""
    with pytest.raises(SystemExit):
        heph_main(["cam", "emit"])  # argparse: part is required, exactly as shipped
    import argparse

    from hephaestus.core import cli_cam

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    cli_cam.add_subparsers(sub)
    args = parser.parse_args(["cam", "emit", "bracket", "--kerf-mm", "0.2"])
    assert args.part == "bracket" and args.kerf_mm == 0.2
    with pytest.raises(SystemExit):
        parser.parse_args(["cam", "emit", "bracket", "--consent"])
