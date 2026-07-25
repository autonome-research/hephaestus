"""Shared helpers for the Gate G2 delegation / bridge-bounds / thread-phase suite.

This module is the single seam between ``tests/stage2`` and the package-local
harnesses under ``server/tests``: it appends that directory to ``sys.path`` so
the gate suite can *reuse* (never re-implement) the fixtures Stage 2A already
proved — ``tools_fixture.Project`` (a real project + real
:class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher`), ``fake_openai`` (the
scripted OpenAI-compatible provider) and ``test_workflows.Wiring`` /
``RunnerHarness`` (the supervised ``agent/dist/workflows/runner.js`` process).

The clock/liveness doubles are defined here rather than imported from
``server/tests/conftest.py`` on purpose: two ``conftest`` modules with the same
basename cannot both be imported under pytest's default ``prepend`` import mode,
so the gate suite never imports that file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SERVER_TESTS: Final[Path] = REPO_ROOT / "server" / "tests"
AGENT_DIR: Final[Path] = REPO_ROOT / "agent"
LIMITS_PATH: Final[Path] = REPO_ROOT / "schemas" / "bridge_limits.json"
TOOL_SCHEMAS: Final[Path] = REPO_ROOT / "schemas" / "tools"
REGISTRIES: Final[Path] = REPO_ROOT / "registries"

# Appended (never prepended) so a combined ``pytest server/tests tests/stage2``
# session still resolves ``server/tests``' own sibling imports first.
if str(SERVER_TESTS) not in sys.path:
    sys.path.append(str(SERVER_TESTS))

from hephaestus.agent_bridge.admission import bridge_store_config  # noqa: E402
from hephaestus.agent_bridge.delegation import DelegationService  # noqa: E402
from opstore.types import OwnerId  # noqa: E402

from opstore import OpStore  # noqa: E402

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
# clock / liveness doubles


class FakeClock:
    """A manually advanced unix-seconds clock."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class FakeLiveness:
    """A liveness oracle whose per-owner verdicts the test sets."""

    def __init__(self, *, default: bool = True) -> None:
        self._default = default
        self._dead: set[tuple[int, int]] = set()

    def kill(self, who: OwnerId) -> None:
        self._dead.add((who.pid, who.pid_start_ns))

    def revive(self, who: OwnerId) -> None:
        self._dead.discard((who.pid, who.pid_start_ns))

    def is_alive(self, who: OwnerId) -> bool:
        if (who.pid, who.pid_start_ns) in self._dead:
            return False
        return self._default


def owner(pid: int, start: int = 1) -> OwnerId:
    return OwnerId(pid=pid, pid_start_ns=start)


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


# ---------------------------------------------------------------------------
# the packaged Node sidecar


def node_executable() -> str | None:
    return os.environ.get("HEPHAESTUS_NODE") or shutil.which("node")


def sidecar_main() -> Path:
    return AGENT_DIR / "dist" / "main.js"


def workflow_runner_main() -> Path:
    return AGENT_DIR / "dist" / "workflows" / "runner.js"


_DIST_CACHE: list[tuple[Path, Path] | None] = []


def build_agent_dist() -> tuple[Path, Path] | None:
    """Build ``agent/dist`` once and return ``(main.js, workflows/runner.js)``.

    Returns ``None`` when Node or pnpm is unavailable (the caller skips), and
    fails loudly when the build itself is broken — a gate suite must never pass
    by silently skipping a broken sidecar. The result is cached for the process
    so the whole gate suite pays for at most one ``pnpm build``.
    """
    if _DIST_CACHE:
        return _DIST_CACHE[0]
    result = _build_agent_dist()
    _DIST_CACHE.append(result)
    return result


def _build_agent_dist() -> tuple[Path, Path] | None:
    if node_executable() is None:
        return None
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        return None
    build = subprocess.run(
        [pnpm, "--dir", str(AGENT_DIR), "build"],
        capture_output=True,
        text=True,
        check=False,
    )
    main = sidecar_main()
    runner = workflow_runner_main()
    if build.returncode != 0 or not main.exists() or not runner.exists():
        raise AssertionError(f"sidecar build failed:\n{build.stdout}\n{build.stderr}")
    return main, runner


def scaffold_project(root: Path, *, name: str = "g2b") -> Path:
    """A minimal but real Hephaestus project (manifest + globals + parts/checks)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    return root
