"""Shared helpers for the Gate G2 delegation / bridge-bounds / thread-phase suite.

Only what is specific to *these* clauses lives here: the opstore/delegation
wiring at the bridge's 16-slot admission config, the ``schemas/bridge_limits.json``
leaf introspection the bounds clauses enumerate, and the repo-relative paths the
suite asserts against. Everything reusable — the scripted provider, the real
project + dispatcher fixture, the clock/liveness doubles and the one-per-process
``agent/dist`` build — comes from :mod:`hephaestus.testing`, which this module
re-exports so the gate modules keep a single import seam.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.agent_bridge.delegation import DelegationService
from hephaestus.testing.doubles import FakeClock, FakeLiveness, owner
from hephaestus.testing.projects import scaffold_project as _scaffold_project
from hephaestus.testing.sidecar import (
    build_agent_dist,
    node_executable,
    sidecar_main,
    workflow_runner_main,
)

from opstore import OpStore

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SERVER_TESTS: Final[Path] = REPO_ROOT / "server" / "tests"
AGENT_DIR: Final[Path] = REPO_ROOT / "agent"
LIMITS_PATH: Final[Path] = REPO_ROOT / "schemas" / "bridge_limits.json"
TOOL_SCHEMAS: Final[Path] = REPO_ROOT / "schemas" / "tools"
REGISTRIES: Final[Path] = REPO_ROOT / "registries"

__all__ = [
    "AGENT_DIR",
    "LIMITS",
    "LIMITS_PATH",
    "REGISTRIES",
    "REPO_ROOT",
    "SERVER_TESTS",
    "TOOL_SCHEMAS",
    "FakeClock",
    "FakeLiveness",
    "build_agent_dist",
    "delegation_service",
    "limit_leaves",
    "node_executable",
    "open_bridge_store",
    "owner",
    "scaffold_project",
    "sidecar_main",
    "workflow_runner_main",
]

with LIMITS_PATH.open("r", encoding="utf-8") as _fh:
    LIMITS: Final[dict[str, Any]] = json.load(_fh)


# ---------------------------------------------------------------------------
# opstore / delegation wiring


def open_bridge_store(
    root: Path,
    *,
    clock: FakeClock | None = None,
    liveness: FakeLiveness | None = None,
) -> OpStore:
    """Create-or-open an opstore whose ``run_slots`` is the bridge's 16."""
    if (root / "state.db").exists():
        return OpStore.open(root, bridge_store_config(), clock=clock, liveness=liveness)
    return OpStore.create(root, bridge_store_config(), clock=clock, liveness=liveness)


def delegation_service(
    store: OpStore, clock: FakeClock | None = None, gate: Any = None
) -> DelegationService:
    """The real delegation state machine over ``store``."""
    return DelegationService(store.admission, store.db, gate=gate, clock=clock)


# ---------------------------------------------------------------------------
# limits introspection


def limit_leaves() -> dict[str, float]:
    """Every numeric leaf of ``schemas/bridge_limits.json`` as a dotted path.

    ``_about`` (prose) and the document ``version`` are not §5 limits and are
    excluded; everything else must be exercised at its boundary by the gate.
    """
    leaves: dict[str, float] = {}

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():  # pyright: ignore[reportUnknownVariableType]
                name = str(key)
                if name.startswith("_"):
                    continue
                walk(value, f"{path}.{name}" if path else name)
        elif isinstance(node, bool):
            return
        elif isinstance(node, int | float):
            leaves[path] = float(node)

    walk(LIMITS, "")
    leaves.pop("version", None)
    return leaves


def scaffold_project(root: Path, *, name: str = "g2b") -> Path:
    """A minimal but real Hephaestus project (manifest + globals + parts/checks)."""
    return _scaffold_project(root, name=name)
