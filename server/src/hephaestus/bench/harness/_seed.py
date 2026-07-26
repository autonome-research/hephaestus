"""Materializing the project a run works in, and restoring what it may not touch.

Seeding guarantees a well-formed project (manifest, ``globals.py``, ``parts/``,
``checks/``) whether or not the task ships a ``seed/`` tree. Protected paths are
task-owned evidence — inspection gauges, broken fixtures — restored from the
seed before grading, so a run that rewrites a gauge to make itself pass changes
nothing. Reference solutions are overlaid through the same real ``CadOps`` paths
a run would use.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import uuid
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.core.project_store.layout import GLOBALS_FILENAME, load_project, open_store

from ._tasks import BenchTask, solution_dir

__all__ = ["apply_solution", "open_cad", "restore_protected", "seed_project"]


def seed_project(task: BenchTask, project_root: Path) -> Path:
    """Materialize a fresh project for ``task`` at ``project_root``.

    A **seeded**-spec task (``VALIDATION.md`` §1) additionally installs its own
    acceptance checks into ``checks/`` — the independent spec the run iterates
    against. They are protected paths, so the grader restores them before the
    final build and any edit is scored as spec tampering (§8).
    """
    project_root.mkdir(parents=True, exist_ok=True)
    if task.seed_dir.is_dir():
        shutil.copytree(task.seed_dir, project_root, dirs_exist_ok=True)
    manifest = project_root / "hephaestus.toml"
    if not manifest.exists():
        name = task.id.replace("-", "_")
        manifest.write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    globals_py = project_root / GLOBALS_FILENAME
    if not globals_py.exists():
        globals_py.write_text(
            "# Project-shared namespace (script contract §4).\nPARAMS = {}\n", encoding="utf-8"
        )
    (project_root / "parts").mkdir(exist_ok=True)
    checks_dir = project_root / "checks"
    checks_dir.mkdir(exist_ok=True)
    if task.is_seeded:
        for name, source in task.check_sources().items():
            (checks_dir / f"{name}.py").write_text(source, encoding="utf-8")
    return project_root


def restore_protected(task: BenchTask, project_root: Path) -> list[str]:
    """Restore the task's protected files; returns the paths that changed.

    Inspection gauges, broken fixtures and (for a seeded-spec task) the seeded
    acceptance checks are task-owned evidence: grading always measures against
    the originals, so a run that rewrites a gauge — or its own spec — to make
    itself pass changes nothing. The returned list is the spec-tampering
    evidence §8 scores.
    """
    restored: list[str] = []
    for rel, original in task.protected_sources().items():
        target = project_root / rel
        if not target.is_file() or target.read_bytes() != original:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)
            restored.append(rel)
    return restored


@contextlib.contextmanager
def open_cad(project_root: Path) -> Generator[CadOps]:
    """Open the project's store and yield a :class:`CadOps` bound to it."""
    layout = load_project(project_root)
    store = open_store(layout)
    try:
        yield CadOps(layout, store)
    finally:
        store.close()


def apply_solution(
    task: BenchTask, project_root: Path, *, solutions_dir: Path | None = None
) -> dict[str, Any]:
    """Overlay ``corpus/solutions/<task>`` onto a seeded project.

    The overlay is an ordinary partial project tree (``globals.py``,
    ``parts/*.py``, ``checks/*.py``) plus an optional ``params.json`` of the form
    ``{"project": {...}, "part": {"<name>": {...}}}`` applied through the real
    ``set_params`` path (that is the whole solution for ``param-retune``).
    """
    # Reference solutions are per *task*, not per spec variant: both splits of a
    # task are the same design and share one reference implementation.
    source = solution_dir(task.base_id, solutions_dir=solutions_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"no reference solution for task {task.base_id!r} at {source}")
    applied: dict[str, Any] = {"files": [], "params": {}}
    files = cast("list[str]", applied["files"])
    for item in sorted(source.rglob("*")):
        rel = item.relative_to(source)
        if item.is_dir():
            (project_root / rel).mkdir(parents=True, exist_ok=True)
            continue
        if rel.name == "params.json":
            continue
        (project_root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, project_root / rel)
        files.append(rel.as_posix())
    params_path = source / "params.json"
    if params_path.is_file():
        raw = json.loads(params_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{params_path}: params must be a JSON object")
        applied["params"] = _apply_params(project_root, cast("dict[str, Any]", raw))
    return applied


def _apply_params(project_root: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a ``params.json`` overlay through ``CadOps.set_params``."""
    outcome: dict[str, Any] = {}
    with open_cad(project_root) as cad:
        project_values = spec.get("project")
        if isinstance(project_values, dict):
            outcome["project"] = cad.set_params(
                "project",
                None,
                cast("Mapping[str, Any]", project_values),
                expected_state_hash=cad.param_state_hash("project", None),
                op_id=f"bench-setparams-{uuid.uuid4().hex}",
            )
        part_values = spec.get("part")
        if isinstance(part_values, dict):
            per_part: dict[str, Any] = {}
            for part, values in cast("dict[str, Any]", part_values).items():
                per_part[part] = cad.set_params(
                    "part",
                    part,
                    cast("Mapping[str, Any]", values),
                    expected_state_hash=cad.param_state_hash("part", part),
                    op_id=f"bench-setparams-{uuid.uuid4().hex}",
                )
            outcome["part"] = per_part
    return outcome
