"""Materializing the project a run works in, and restoring what it may not touch.

Seeding guarantees a well-formed project (manifest, ``globals.py``, ``parts/``,
``checks/``) whether or not the task ships a ``seed/`` tree. Protected paths are
task-owned evidence — inspection gauges, broken fixtures — restored from the
seed before grading, so a run that rewrites a gauge to make itself pass changes
nothing. Reference solutions are overlaid through the same real ``CadOps`` paths
a run would use.

A fixture may also ship ``INGEST.md`` §2 ``references/`` and §1 ``imports/``.
Imports are just files the build resolves; references become project state only
once registered, and registration is operator-side — here
(:func:`seed_references`), never through anything the run can call.
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
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.project_store.layout import GLOBALS_FILENAME, load_project, open_store

from ._tasks import BenchTask, solution_dir

__all__ = [
    "apply_solution",
    "open_cad",
    "restore_protected",
    "seed_project",
    "seed_references",
]


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
    seed_references(project_root)
    return project_root


def seed_references(project_root: Path) -> tuple[str, ...]:
    """Register every file a task fixture shipped in ``references/`` (INGEST.md §2).

    A fixture seeds ``references/`` (and ``imports/``) as plain files in its seed
    tree; those files are only *project state* once they are registered, which is
    an operator-side act. The bench is the operator here, so this is where it
    happens — the run itself still has no way to add one.

    ``imports/`` needs no counterpart: an import is resolved from the file at
    build time, so copying it in is the whole seeding step.
    """
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.references import ReferenceRegistry

    references_dir = project_root / "references"
    if not references_dir.is_dir() or not any(references_dir.iterdir()):
        return ()
    extractor = _reference_extractor()
    layout = load_project(project_root)
    store = open_store(layout)
    try:
        registered = ReferenceRegistry(layout, store).seed_directory(extractor=extractor)
    finally:
        store.close()
    return tuple(entry.name for entry in registered)


def _reference_extractor() -> Any:
    """The server's pypdf extractor when installed (bench always has it)."""
    try:
        from hephaestus.agent_bridge.references_pdf import pdf_extractor
    except ImportError:  # pragma: no cover - bench depends on the server package
        return None
    return pdf_extractor()


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
def open_cad(project_root: Path, *, backend: ExecBackend | None = None) -> Generator[CadOps]:
    """Open the project's store and yield a :class:`CadOps` bound to it.

    ``backend`` is the executor the ops object runs scripts and registry content
    on. Left unset, ``CadOps`` picks its own default; grading passes a probed
    secure backend for the paths that require one (DFM predicates).
    """
    layout = load_project(project_root)
    store = open_store(layout)
    try:
        yield CadOps(layout, store, backend=backend)
    finally:
        store.close()


def apply_solution(
    task: BenchTask, project_root: Path, *, solutions_dir: Path | None = None
) -> dict[str, Any]:
    """Overlay ``corpus/solutions/<task>`` onto a seeded project.

    The overlay is an ordinary partial project tree (``globals.py``,
    ``parts/*.py``, ``checks/*.py``) plus two optional declaration files applied
    through the same real ``CadOps`` paths a run's tool calls take:

    ``params.json``
        ``{"project": {...}, "part": {"<name>": {...}}}`` through ``set_params``
        (that is the whole solution for ``param-retune``).
    ``kinematics.json``
        ``{"joints": [...], "couplings": [...], "poses": [...],
        "motion_checks": [...]}`` through the ``KINEMATICS.md`` §6 declare
        tools (Stage 9C, corpus v3). Joints and couplings are generational
        ledger state, not files, so a mechanism task's reference solution can
        only declare them the way a run would — and a coupling is deliberately
        declarable HERE and not by the task's acceptance: the acceptance
        sweeps only free parameters, so whether the run's own transmission
        claim really moves the driven part is exactly what its motion checks
        measure (a solution that declares no coupling fails the reach).
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
        if rel.name in ("params.json", "kinematics.json"):
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
    kinematics_path = source / "kinematics.json"
    if kinematics_path.is_file():
        raw_kinematics = json.loads(kinematics_path.read_text(encoding="utf-8"))
        if not isinstance(raw_kinematics, dict):
            raise ValueError(f"{kinematics_path}: kinematics must be a JSON object")
        applied["kinematics"] = _apply_kinematics(
            project_root, cast("dict[str, Any]", raw_kinematics)
        )
    return applied


#: ``kinematics.json`` sections in declaration order: joints before the
#: couplings that reference them, both before any pose or motion check that
#: would be validated against the coupled-child rule (``KINEMATICS.md`` §5).
_KINEMATIC_SECTIONS: tuple[str, ...] = ("joints", "couplings", "poses", "motion_checks")


def _apply_kinematics(project_root: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a ``kinematics.json`` overlay through the real declare tools.

    ``KINEMATICS.md`` §6 (Stage 9C, corpus v3): a mechanism task's reference
    solution declares joints, couplings, poses and motion checks exactly as a
    run would — through ``CadOps.declare_joint`` / ``declare_coupling`` /
    ``declare_pose`` / ``declare_motion_check``, with the set's own validation
    (compelled provenance, the forest rule, the one-driver and cycle rules)
    refusing a malformed solution loudly at apply time rather than as a
    mysterious grade. The section set is closed: an unknown key is an error,
    never silently skipped.
    """
    unknown = sorted(set(spec) - set(_KINEMATIC_SECTIONS))
    if unknown:
        raise ValueError(
            f"kinematics.json: unknown section(s) {unknown} "
            f"(it takes: {', '.join(_KINEMATIC_SECTIONS)})"
        )
    outcome: dict[str, Any] = {}
    with open_cad(project_root) as cad:
        declare: Mapping[str, Any] = {
            "joints": cad.declare_joint,
            "couplings": cad.declare_coupling,
            "poses": cad.declare_pose,
            "motion_checks": cad.declare_motion_check,
        }
        for section in _KINEMATIC_SECTIONS:
            entries = spec.get(section)
            if entries is None:
                continue
            if not isinstance(entries, list):
                raise ValueError(f"kinematics.json: {section} must be a list of entries")
            declared: list[str] = []
            for entry in cast("list[Any]", entries):
                if not isinstance(entry, dict):
                    raise ValueError(f"kinematics.json: {section} entries must be objects")
                entry_map = cast("Mapping[str, Any]", entry)
                declare[section](entry_map, op_id=f"bench-kinematics-{uuid.uuid4().hex}")
                declared.append(str(entry_map.get("id")))
            outcome[section] = declared
    return outcome


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
