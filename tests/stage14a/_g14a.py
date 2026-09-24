# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G14A evidence suite (not a test module).

Stage 14A ships machining DFM packs and the ``tools`` registry kind, and **no
CAM code** (CAM.md §3.5, §6; mission_plan.md Stage 14). Everything here rides
existing machinery — the registry loader, the Merkle digest, the sandboxed DFM
worker — so this scaffolding is deliberately thin: fixture geometry with known
violations (authored here rather than imported from ``corpus/``, so a gate
assertion cannot be satisfied by a change to a bench task), and the in-process
worker driver every DFM gate suite uses for the namespace half of the sandbox
argument.

The mill fixture is one solid with five known violations, one per §6.2 rule:
0.3 mm internal corners (below the 1.5 mm floor), a 16 mm pocket under a 3 mm
bit (above 4x), a 0.5 mm web, a 1.5 mm bore 50 mm deep (above 6x), and a side
hole the +Z spindle cannot reach.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hephaestus.core.dfm import TopologyDescriptor
from hephaestus.core.dfm.types import DfmRuleOutcome
from hephaestus.core.dfm.worker import evaluate_job
from hephaestus.core.executor.sandbox.bwrap import find_bwrap
from hephaestus.core.registry import (
    DfmIndex,
    DfmPack,
    MaterialsIndex,
    load_registry,
)
from opstore.types import JSONValue

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"
DFM_ROOT = REGISTRIES / "dfm"
TOOLS_ROOT = REGISTRIES / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="DFM predicates execute only under a probed secure sandbox (bubblewrap)",
)


def brep_bytes(shape: object) -> bytes:
    """Serialize a build123d shape the way a published build artifact is stored."""
    import tempfile

    from OCP.BRepTools import BRepTools  # pyright: ignore[reportAttributeAccessIssue]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.brep"
        assert BRepTools.Write_s(shape.wrapped, str(path))  # pyright: ignore[reportAttributeAccessIssue]
        return path.read_bytes()


def mill_fixture() -> bytes:
    """A 20 mm block violating every cnc_mill rule at once (see module docstring)."""
    from build123d import Align, Axis, Box, Cylinder, Pos, Rot, fillet

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    body = Box(80, 50, 20, align=bottom)
    body = body - Pos(0, 12.5, 4) * Box(24, 24, 30, align=bottom)
    corners = [
        edge
        for edge in body.edges().filter_by(Axis.Z)
        if abs(abs(edge.center().X) - 12.0) < 0.2 and 0.0 < edge.center().Y < 25.0
    ]
    assert len(corners) == 4, "fixture must have four concave pocket corners"
    body = fillet(corners, 0.3)
    body = body - Pos(-25, 0, 0) * Cylinder(0.75, 50)
    body = body - Pos(0, -15, 10) * Rot(0.0, 90.0, 0.0) * Cylinder(3.0, 120)
    return brep_bytes(body)


def compliant_fixture() -> bytes:
    """The heph init example plate's geometry: fires nothing, by design."""
    from build123d import Box

    return brep_bytes(Box(40.0, 20.0, 6.0))


def dfm_index() -> DfmIndex:
    return DfmIndex(load_registry(DFM_ROOT))


def mill_pack() -> DfmPack:
    return dfm_index().get("cnc_mill")


def router_pack() -> DfmPack:
    return dfm_index().get("cnc_router")


def materials_index() -> MaterialsIndex:
    return MaterialsIndex(load_registry(REGISTRIES / "materials"))


def al6061_record() -> dict[str, JSONValue]:
    material = materials_index().get("al-6061")
    assert material is not None
    return dict(material.to_json())


def worker_job(
    pack: DfmPack,
    brep: bytes,
    out_dir: Path,
    *,
    part: str = "fixture",
    artifact_ref: str = "artifact:build:sha256:fixture",
    metadata: dict[str, str] | None = None,
    material: dict[str, JSONValue] | None = None,
    tags: dict[str, TopologyDescriptor] | None = None,
) -> dict[str, JSONValue]:
    """The worker job record ``evaluate_pack`` would ship for this evaluation."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source.brep").write_bytes(brep)
    return {
        "mode": "dfm",
        "origin": "registry",
        "part": part,
        "process": pack.process,
        "source_artifact_ref": artifact_ref,
        "brep": "source.brep",
        "out_dir": str(out_dir),
        "metadata": dict(metadata or {}),
        "material": material,
        "tags": {name: d.to_json() for name, d in (tags or {}).items()},
        "rules": [
            {
                "rule_id": rule.rule_id,
                "title": rule.title,
                "severity": rule.severity,
                "params": dict(rule.values),
                "source": rule.read_predicate(),
            }
            for rule in pack.rules
        ],
    }


def run_in_process(
    pack: DfmPack,
    brep: bytes,
    tmp_path: Path,
    *,
    part: str = "fixture",
    artifact_ref: str = "artifact:build:sha256:fixture",
    metadata: dict[str, str] | None = None,
    material: dict[str, JSONValue] | None = None,
    tags: dict[str, TopologyDescriptor] | None = None,
) -> dict[str, DfmRuleOutcome]:
    """Evaluate a pack through the worker entry point without a sandbox.

    The in-process path exercises the same worker and injected-namespace
    whitelist the sandboxed run wraps, which is how the namespace half of the
    denial is asserted on machines without bubblewrap (the
    ``core/tests/test_dfm_packs.py`` pattern).
    """
    job = worker_job(
        pack,
        brep,
        tmp_path / "out",
        part=part,
        artifact_ref=artifact_ref,
        metadata=metadata,
        material=material,
        tags=tags,
    )
    result = evaluate_job(job)
    assert result["status"] == "ok", result["error"]
    rules = result["rules"]
    assert isinstance(rules, list)
    outcomes = [DfmRuleOutcome.from_json(item) for item in rules if isinstance(item, dict)]
    return {outcome.rule_id: outcome for outcome in outcomes}
