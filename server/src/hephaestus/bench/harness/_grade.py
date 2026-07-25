"""Grading a finished project against its task, independently of how it got there.

The verdict is deterministic: protected files are restored, every part is
rebuilt, the task's required CHECKS are installed over whatever the run authored
and run project-scoped, and the required exports and renders are produced from
that graded geometry. Pass means every required check passed, every export and
render validated, and the run stayed inside its tool-call budget.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS, CadOpError, CadOps
from hephaestus.core.project_store.layout import ProjectLayout

from ._exports import dxf_profile_count, validate_export_bytes
from ._seed import apply_solution, open_cad, restore_protected, seed_project
from ._tasks import BenchTask

__all__ = ["GradeReport", "grade", "grade_reference_solution"]

_LEASE_RETRY_ATTEMPTS = 18
_LEASE_RETRY_DELAY_S = 5.0


@dataclass(frozen=True)
class GradeReport:
    """The verdict for one finished run (or one reference solution)."""

    task_id: str
    passed: bool
    reasons: tuple[str, ...]
    builds: Mapping[str, Any] = field(default_factory=dict[str, Any])
    check_status: str = "not_run"
    checks: Mapping[str, Any] = field(default_factory=dict[str, Any])
    other_checks: Mapping[str, Any] = field(default_factory=dict[str, Any])
    exports: tuple[Mapping[str, Any], ...] = ()
    renders: tuple[Mapping[str, Any], ...] = ()
    tool_calls: int | None = None
    budget_tool_calls: int | None = None
    within_budget: bool = True
    #: Protected task files the run had modified (restored before grading).
    restored_protected: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "builds": dict(self.builds),
            "check_status": self.check_status,
            "checks": dict(self.checks),
            "other_checks": dict(self.other_checks),
            "exports": [dict(e) for e in self.exports],
            "renders": [dict(r) for r in self.renders],
            "tool_calls": self.tool_calls,
            "budget_tool_calls": self.budget_tool_calls,
            "within_budget": self.within_budget,
            "restored_protected": list(self.restored_protected),
        }


def _build_with_lease_retry(cad: CadOps, part: str) -> dict[str, Any] | None:
    """Build one part for grading, waiting out a live part lock.

    A run cancelled at its budget can leave its build worker tearing down with
    the part lock still heartbeat-live; grading starts immediately after. Wait
    for the lease to clear (liveness reclaim covers a dead owner) instead of
    failing the grade on a transient. Returns None when the lock never clears.
    """
    for attempt in range(_LEASE_RETRY_ATTEMPTS):
        try:
            return cad.build_part(part, op_id=f"bench-build-{uuid.uuid4().hex}")
        except CadOpError as exc:
            if exc.reason != "part_busy" or attempt == _LEASE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_LEASE_RETRY_DELAY_S)
    return None


def _build_all(cad: CadOps, layout: ProjectLayout) -> tuple[dict[str, Any], list[str]]:
    """Build every part; return the per-part results and failure reasons."""
    builds: dict[str, Any] = {}
    reasons: list[str] = []
    parts = layout.part_names()
    if not parts:
        return builds, ["no_parts_authored"]
    for part in parts:
        result = _build_with_lease_retry(cad, part)
        if result is None:
            reasons.append(f"build_lease_busy:{part}")
            continue
        builds[part] = result
        if result.get("status") != "ok":
            reasons.append(f"build_failed:{part}")
        elif not bool(result.get("current")):
            reasons.append(f"build_not_current:{part}")
    return builds, reasons


def _run_required_checks(
    cad: CadOps, task: BenchTask
) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
    """Install the task's CHECKS, run them project-scoped, split the results."""
    reasons: list[str] = []
    for name, source in task.check_sources().items():
        cad.write_check(name, source, op_id=f"bench-check-{uuid.uuid4().hex}")
    report = cad.run_project_checks(None)
    status = str(report.get("status", "error"))
    required: dict[str, Any] = {}
    other: dict[str, Any] = {}
    if status != "ok":
        return status, required, other, [f"project_checks_{status}"]
    raw = report.get("checks")
    results = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    wanted = set(task.required_checks)
    for name, value in results.items():
        stem = name.split(":", 1)[0]
        if stem in wanted:
            required[name] = value
        else:
            other[name] = value
    for stem in sorted(wanted):
        if not any(key.split(":", 1)[0] == stem for key in required):
            reasons.append(f"required_check_missing:{stem}")
    for name, value in sorted(required.items()):
        entry: Mapping[str, Any] = (
            cast("Mapping[str, Any]", value) if isinstance(value, dict) else {}
        )
        if not bool(entry.get("pass")):
            reasons.append(f"check_failed:{name}")
    return status, required, other, reasons


def _validate_exports(
    cad: CadOps, task: BenchTask, layout: ProjectLayout
) -> tuple[list[dict[str, Any]], list[str]]:
    """Perform + validate every required export from the graded geometry."""
    records: list[dict[str, Any]] = []
    reasons: list[str] = []
    for index, requirement in enumerate(task.exports):
        record: dict[str, Any] = {"requirement": requirement.to_json()}
        target = f"bench-{requirement.part}-{index}.{EXPORT_FORMATS[requirement.fmt]}"
        try:
            result = cad.export_part(
                requirement.part,
                requirement.fmt,
                artifact_ref=None,
                target=target,
                layout=requirement.layout,
                op_id=f"bench-export-{uuid.uuid4().hex}",
            )
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            reasons.append(f"export_failed:{requirement.part}:{requirement.fmt}")
            records.append(record)
            continue
        record["result"] = result
        paths = cast("list[Any]", result.get("paths", []))
        data = b""
        if paths:
            path = layout.root / str(paths[0])
            record["path"] = str(path)
            if path.is_file():
                data = path.read_bytes()
        record["bytes"] = len(data)
        reason = validate_export_bytes(requirement.fmt, data)
        if reason is None and len(data) < requirement.min_bytes:
            reason = "export_too_small"
        if reason is not None:
            record["invalid"] = reason
            reasons.append(f"export_invalid:{requirement.part}:{requirement.fmt}:{reason}")
            records.append(record)
            continue
        if requirement.profile_count is not None:
            try:
                count = dxf_profile_count(data)
            except Exception as exc:
                record["invalid"] = f"{type(exc).__name__}: {exc}"
                reasons.append(f"export_unparsable:{requirement.part}:{requirement.fmt}")
                records.append(record)
                continue
            record["profile_count"] = count
            if count != requirement.profile_count:
                reasons.append(
                    f"export_profile_count:{requirement.part}:{count}!={requirement.profile_count}"
                )
        records.append(record)
    return records, reasons


def _validate_renders(cad: CadOps, task: BenchTask) -> tuple[list[dict[str, Any]], list[str]]:
    """Produce + record every required render (e.g. a ``+Z`` midplane section)."""
    records: list[dict[str, Any]] = []
    reasons: list[str] = []
    for requirement in task.renders:
        record: dict[str, Any] = {"requirement": requirement.to_json()}
        try:
            result = cad.inspect_part(
                requirement.part,
                views=list(requirement.views),
                channel=requirement.channel,
                section_plane=requirement.section_plane,
            )
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            reasons.append(f"render_failed:{requirement.part}:{requirement.channel}")
            records.append(record)
            continue
        refs = cast("list[Any]", result.get("render_artifact_refs", []))
        record["render_artifact_refs"] = [str(ref) for ref in refs]
        record["status"] = str(result.get("status", ""))
        if record["status"] != "ok" or not refs:
            reasons.append(f"render_missing:{requirement.part}:{requirement.channel}")
        records.append(record)
    return records, reasons


def grade(
    task: BenchTask,
    project_root: Path,
    *,
    tool_calls: int | None = None,
    extra_reasons: Sequence[str] = (),
) -> GradeReport:
    """Grade the project's final state against ``task``.

    Deterministic and independent of how the state was reached: the task's
    protected files are restored, every part is rebuilt, the task's required
    CHECKS are installed over whatever the run authored, and the exports/renders
    are produced from the graded geometry.
    """
    reasons: list[str] = list(extra_reasons)
    within_budget = tool_calls is None or tool_calls <= task.budget_tool_calls
    if not within_budget:
        reasons.append(f"budget_exceeded:{tool_calls}>{task.budget_tool_calls}")
    tampered = restore_protected(task, project_root)
    builds: dict[str, Any] = {}
    check_status = "not_run"
    required: dict[str, Any] = {}
    other: dict[str, Any] = {}
    exports: list[dict[str, Any]] = []
    renders: list[dict[str, Any]] = []
    with open_cad(project_root) as cad:
        layout = cad.layout
        builds, build_reasons = _build_all(cad, layout)
        reasons.extend(build_reasons)
        if not build_reasons:
            check_status, required, other, check_reasons = _run_required_checks(cad, task)
            reasons.extend(check_reasons)
            export_records, export_reasons = _validate_exports(cad, task, layout)
            exports = export_records
            reasons.extend(export_reasons)
            render_records, render_reasons = _validate_renders(cad, task)
            renders = render_records
            reasons.extend(render_reasons)
    return GradeReport(
        task_id=task.id,
        passed=not reasons,
        reasons=tuple(reasons),
        builds=builds,
        check_status=check_status,
        checks=required,
        other_checks=other,
        exports=tuple(exports),
        renders=tuple(renders),
        tool_calls=tool_calls,
        budget_tool_calls=task.budget_tool_calls,
        within_budget=within_budget,
        restored_protected=tuple(tampered),
    )


def grade_reference_solution(
    task: BenchTask,
    project_root: Path,
    *,
    solutions_dir: Path | None = None,
) -> GradeReport:
    """Seed a project, overlay the reference solution, and grade it.

    This is the CI meta-test behind every task: a task no reference solution
    passes is a broken task.
    """
    seed_project(task, project_root)
    apply_solution(task, project_root, solutions_dir=solutions_dir)
    return grade(task, project_root)
