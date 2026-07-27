"""Grading a finished project against its task, independently of how it got there.

The verdict is deterministic: protected files are restored, every part is
rebuilt, the task's required CHECKS are installed over whatever the run authored
and run project-scoped, and the required exports, renders, DFM verdicts and
drawing sheets are produced from that graded geometry. Pass means every required
check passed, every artifact validated, and the run stayed inside its tool-call
budget.

The Stage 6 halves are graded the same way as the rest: the grader *runs the
tool itself*. A DFM verdict is re-measured on a probed secure backend (rule
predicates are registry content and never run unsandboxed — architecture §3.6),
and a drawing's dimension strings are read out of the PDF text layer the grader
generated. Nothing in the verdict comes from what the run said it found.

Manufacturing metadata is judged the same way and deliberately *structurally*
(``_validate_metadata``): the material a run declares must resolve in the
materials registry, not match an author's sentence. A verdict that turns on
wording measures transcription, not engineering.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS, CadOpError, CadOps
from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox.probe import secure_backend
from hephaestus.core.project_store.layout import ProjectLayout, load_project
from hephaestus.geom.nesting import blank_from_metadata

from ..metrics import charged_reasons, harness_reasons
from ._exports import dxf_layer_extents, dxf_profile_count, pdf_text, validate_export_bytes
from ._seed import apply_solution, open_cad, restore_protected, seed_project
from ._tasks import BenchTask, DfmRequirement, ExportRequirement, MetadataRequirement

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
    #: Stage 6: one record per DFM requirement / drawing requirement.
    dfm: tuple[Mapping[str, Any], ...] = ()
    drawings: tuple[Mapping[str, Any], ...] = ()
    #: One record per §5.2 metadata requirement (material/process/fields).
    metadata: tuple[Mapping[str, Any], ...] = ()
    tool_calls: int | None = None
    budget_tool_calls: int | None = None
    within_budget: bool = True
    #: Protected task files the run had modified (restored before grading).
    restored_protected: tuple[str, ...] = ()

    @property
    def harness_errors(self) -> tuple[str, ...]:
        """Reasons this run carried that the *harness* owns, not the model.

        They stay in :attr:`reasons` and in the archive — they are just reported
        as a reliability number (``harness_error_rate``) instead of being charged
        to the agent. See :mod:`hephaestus.bench.metrics`.
        """
        return harness_reasons(self.reasons)

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "harness_errors": list(self.harness_errors),
            "builds": dict(self.builds),
            "check_status": self.check_status,
            "checks": dict(self.checks),
            "other_checks": dict(self.other_checks),
            "exports": [dict(e) for e in self.exports],
            "renders": [dict(r) for r in self.renders],
            "dfm": [dict(d) for d in self.dfm],
            "drawings": [dict(d) for d in self.drawings],
            "metadata": [dict(m) for m in self.metadata],
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
        blank = _required_blank(requirement)
        try:
            result = cad.export_part(
                requirement.part,
                requirement.fmt,
                artifact_ref=None,
                target=target,
                layout=requirement.layout,
                blank=blank,
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
                count = dxf_profile_count(data, layer=requirement.profile_layer)
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
        if requirement.blank_mm is not None:
            reasons.extend(_validate_blank(requirement, data, record))
        records.append(record)
    return records, reasons


def _required_blank(requirement: ExportRequirement) -> dict[str, Any] | None:
    """The stock the grader nests onto: the requirement's own declared blank.

    A ``nested_sheet`` export needs a blank, and ``export_part`` resolves it from
    the explicit argument first and the part's ``part.blank_size`` second. The
    grader *has* the blank — it is the requirement it is grading against — so it
    passes it, and the nesting happens on the stock the task names.

    Measured 2026-07-26 (``nest-gusset`` s1-s3, gpt-5.6-sol): omitting it graded
    against the part's own declaration instead, so a run whose nested export had
    itself succeeded was failed at grade time with ``export_failed`` carrying
    "declares no part.blank_size". That is an unnamed precondition wearing an
    export failure's name (``VALIDATION.md`` §1). Whether the part declares its
    stock is a *metadata* property and is gated as one, by name
    (``MetadataRequirement.blank_mm``), rather than by whether grading happened
    to need it.
    """
    if requirement.blank_mm is None:
        return None
    width, height = requirement.blank_mm
    return {"width_mm": width, "height_mm": height}


def _validate_blank(
    requirement: ExportRequirement, data: bytes, record: dict[str, Any]
) -> list[str]:
    """Check a nested layout's blank and that the profiles fit inside it.

    Two independent claims, both read off the exported bytes: the blank drawn on
    the layout really is the stock the task requires (the grader nests onto that
    stock — :func:`_required_blank` — so this reads back what the writer actually
    drew), and every profile lies inside it, which is the acceptance test that
    matters: a set that does not fit one blank cannot be nested onto one. That a
    *run* declared the right stock is judged separately and by name, as the
    metadata property it is (``metadata_blank_size``).
    """
    reasons: list[str] = []
    part = str(requirement.part)
    if requirement.blank_mm is None or requirement.profile_layer is None:
        # ``ExportRequirement.from_json`` refuses this pairing; a hand-built
        # requirement that reaches here has nothing to check rather than a
        # silently vacuous pass.
        return [f"export_blank_requirement_incomplete:{part}"]
    width, height = requirement.blank_mm
    try:
        blank = dxf_layer_extents(data, requirement.blank_layer)
        profiles = dxf_layer_extents(data, requirement.profile_layer)
    except Exception as exc:  # pragma: no cover - malformed export
        record["invalid"] = f"{type(exc).__name__}: {exc}"
        return [f"export_unparsable:{part}:{requirement.fmt}"]
    record["blank_extents"] = None if blank is None else list(blank)
    record["profile_extents"] = None if profiles is None else list(profiles)
    if blank is None:
        return [f"export_blank_missing:{part}"]
    drawn = (round(blank[2] - blank[0], 3), round(blank[3] - blank[1], 3))
    if abs(drawn[0] - width) > 0.05 or abs(drawn[1] - height) > 0.05:
        reasons.append(f"export_blank_size:{part}:{drawn[0]}x{drawn[1]}!={width}x{height}")
    if profiles is None:
        return [*reasons, f"export_profiles_missing:{part}"]
    inside = (
        profiles[0] >= blank[0] - 0.05
        and profiles[1] >= blank[1] - 0.05
        and profiles[2] <= blank[2] + 0.05
        and profiles[3] <= blank[3] + 0.05
    )
    if not inside:
        reasons.append(f"export_profiles_outside_blank:{part}")
    return reasons


def _dfm_record(cad: CadOps, requirement: DfmRequirement) -> tuple[dict[str, Any], list[str]]:
    """Re-run the process pack for one requirement and judge the named rules."""
    record: dict[str, Any] = {"requirement": requirement.to_json()}
    reasons: list[str] = []
    try:
        report = cad.run_dfm(requirement.part, process=requirement.process)
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record, [f"dfm_failed:{requirement.part}"]
    record["process"] = report.get("process")
    record["source_artifact_ref"] = report.get("source_artifact_ref")
    record["severity_counts"] = report.get("severity_counts")
    rules = {
        str(cast("Mapping[str, Any]", row).get("rule_id")): cast("Mapping[str, Any]", row)
        for row in cast("Sequence[Any]", report.get("rules", []))
    }
    record["findings"] = [
        {
            "rule_id": cast("Mapping[str, Any]", f).get("rule_id"),
            "severity": cast("Mapping[str, Any]", f).get("severity"),
            "message": cast("Mapping[str, Any]", f).get("message"),
            "tags": cast("Mapping[str, Any]", f).get("tags"),
        }
        for f in cast("Sequence[Any]", report.get("findings", []))
    ]
    for rule_id in requirement.clean_rules:
        row = rules.get(rule_id)
        if row is None:
            reasons.append(f"dfm_rule_missing:{requirement.part}:{rule_id}")
            continue
        status = str(row.get("status", "error"))
        count = len(cast("Sequence[Any]", row.get("findings", [])))
        if status == "error":
            reasons.append(f"dfm_rule_errored:{requirement.part}:{rule_id}")
        elif count:
            reasons.append(f"dfm_findings:{requirement.part}:{rule_id}:{count}")
    return record, reasons


def _validate_dfm(task: BenchTask, project_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every required DFM verdict, measured through a probed secure sandbox.

    Opened as its own ops object: builds are graded on the project's ordinary
    backend, but DFM predicates are untrusted registry content and run only
    under the probed secure backend — there is no fallback, so a machine without
    one fails the requirement loudly instead of grading it away.
    """
    if not task.dfm:
        return [], []
    layout = load_project(project_root)
    try:
        backend = secure_backend(layout.store_root)
    except SandboxDeniedError as exc:
        return [{"error": f"sandbox_denied: {exc}"}], [
            f"dfm_backend_unavailable:{req.part}" for req in task.dfm
        ]
    records: list[dict[str, Any]] = []
    reasons: list[str] = []
    with open_cad(project_root, backend=backend) as cad:
        for requirement in task.dfm:
            record, rule_reasons = _dfm_record(cad, requirement)
            records.append(record)
            reasons.extend(rule_reasons)
    return records, reasons


def _validate_drawings(
    cad: CadOps, task: BenchTask, layout: ProjectLayout
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate every required drawing and read its PDF text layer."""
    records: list[dict[str, Any]] = []
    reasons: list[str] = []
    for index, requirement in enumerate(task.drawings):
        record: dict[str, Any] = {"requirement": requirement.to_json()}
        try:
            result = cad.generate_drawing(
                requirement.part,
                requirement.kind,
                sheet=requirement.sheet,
                target=f"bench-{requirement.part}-{requirement.kind}-{index}",
                op_id=f"bench-drawing-{uuid.uuid4().hex}",
            )
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            reasons.append(f"drawing_failed:{requirement.part}:{requirement.kind}")
            records.append(record)
            continue
        record["result"] = {
            "paths": result.get("paths"),
            "source_artifact_ref": result.get("source_artifact_ref"),
            "dimensions": result.get("dimensions"),
        }
        pdf_rel = result.get("pdf")
        if not isinstance(pdf_rel, str) or not pdf_rel:
            reasons.append(f"drawing_no_pdf:{requirement.part}:{requirement.kind}")
            records.append(record)
            continue
        path = layout.root / pdf_rel
        data = path.read_bytes() if path.is_file() else b""
        record["bytes"] = len(data)
        if not data.startswith(b"%PDF"):
            record["invalid"] = "not_a_pdf"
            reasons.append(f"drawing_invalid:{requirement.part}:{requirement.kind}")
            records.append(record)
            continue
        text = pdf_text(data)
        missing = [want for want in requirement.required_texts if want not in text]
        record["missing_texts"] = missing
        if missing:
            reasons.append(f"drawing_text_missing:{requirement.part}:{','.join(missing)}")
        records.append(record)
    return records, reasons


def _validate_metadata(
    cad: CadOps, task: BenchTask, builds: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Judge each part's §5.2 manufacturing metadata, structurally.

    Read from the script that produced the graded artifact (``frozen_script_metadata``
    refuses to answer for a drifted source), so this is the metadata of the
    geometry actually being graded. What is gated is engineering content and not
    wording: a listed field is non-empty, the process token is the registry pack
    id the task names, and the free-text material spec *resolves* to the
    materials-registry record it has to. Two runs that word the material
    differently both pass; a run that never states one does not.
    """
    records: list[dict[str, Any]] = []
    reasons: list[str] = []
    for requirement in task.metadata:
        record: dict[str, Any] = {"requirement": requirement.to_json()}
        build = builds.get(requirement.part)
        ref = (
            str(cast("Mapping[str, Any]", build).get("artifact_ref", ""))
            if isinstance(build, dict)
            else ""
        )
        metadata: Mapping[str, str] = (
            cad.frozen_script_metadata(requirement.part, ref) if ref else {}
        )
        record["metadata"] = dict(metadata)
        missing = [
            field for field in requirement.required_fields if not metadata.get(field, "").strip()
        ]
        record["missing_fields"] = missing
        if missing:
            reasons.append(f"metadata_missing:{requirement.part}:{','.join(missing)}")
        if requirement.process is not None:
            process = metadata.get("process", "").strip()
            record["process"] = process
            if process != requirement.process:
                reasons.append(
                    f"metadata_process:{requirement.part}:{process or 'unstated'}"
                    f"!={requirement.process}"
                )
        if requirement.material_id is not None:
            spec = metadata.get("material_spec", "").strip()
            material = cad.registries().materials.match(spec) if spec else None
            resolved = None if material is None else material.id
            record["material_id"] = resolved
            if resolved != requirement.material_id:
                reasons.append(
                    f"metadata_material:{requirement.part}:{resolved or 'unresolved'}"
                    f"!={requirement.material_id}"
                )
        if requirement.blank_mm is not None:
            reasons.extend(_validate_declared_blank(requirement, metadata, record))
        records.append(record)
    return records, reasons


def _validate_declared_blank(
    requirement: MetadataRequirement, metadata: Mapping[str, str], record: dict[str, Any]
) -> list[str]:
    """Does ``part.blank_size`` name the stock the task requires?

    Structural, like every other metadata verdict: the field is free text by
    contract (§5.2), so what is gated is the ``W x H`` pair inside it and not the
    sentence around it — "210 x 125 mm blank, one set per blank" and "one set per
    210x125 laser blank" both pass. An absent field is *not* reported here: that
    is ``metadata_missing:<part>:blank_size``, a different failure with its own
    name.
    """
    if requirement.blank_mm is None:
        return []
    declared = metadata.get("blank_size", "").strip()
    if not declared:
        return []
    parsed = blank_from_metadata(declared)
    record["blank_mm"] = None if parsed is None else [parsed.width_mm, parsed.height_mm]
    width, height = requirement.blank_mm
    if parsed is None:
        return [f"metadata_blank_size:{requirement.part}:unparsed!={width}x{height}"]
    if abs(parsed.width_mm - width) > 0.05 or abs(parsed.height_mm - height) > 0.05:
        return [
            f"metadata_blank_size:{requirement.part}:"
            f"{parsed.width_mm}x{parsed.height_mm}!={width}x{height}"
        ]
    return []


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
    dfm: list[dict[str, Any]] = []
    drawings: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    graded = False
    with open_cad(project_root) as cad:
        layout = cad.layout
        builds, build_reasons = _build_all(cad, layout)
        reasons.extend(build_reasons)
        if not build_reasons:
            graded = True
            check_status, required, other, check_reasons = _run_required_checks(cad, task)
            reasons.extend(check_reasons)
            export_records, export_reasons = _validate_exports(cad, task, layout)
            exports = export_records
            reasons.extend(export_reasons)
            render_records, render_reasons = _validate_renders(cad, task)
            renders = render_records
            reasons.extend(render_reasons)
            drawing_records, drawing_reasons = _validate_drawings(cad, task, layout)
            drawings = drawing_records
            reasons.extend(drawing_reasons)
            metadata_records, metadata_reasons = _validate_metadata(cad, task, builds)
            metadata = metadata_records
            reasons.extend(metadata_reasons)
    if graded:
        # Outside the ops object above on purpose: DFM predicates run on a probed
        # secure backend, which the grading ops object deliberately is not.
        dfm, dfm_reasons = _validate_dfm(task, project_root)
        reasons.extend(dfm_reasons)
    return GradeReport(
        task_id=task.id,
        # A harness failure is our bug and is not evidence about the agent: it is
        # kept in `reasons` (and in the archive, and in harness_error_rate) but
        # left out of the verdict. Anything the model is answerable for still
        # fails the run, including a run that has both.
        passed=not charged_reasons(reasons),
        reasons=tuple(reasons),
        builds=builds,
        check_status=check_status,
        checks=required,
        other_checks=other,
        exports=tuple(exports),
        renders=tuple(renders),
        dfm=tuple(dfm),
        drawings=tuple(drawings),
        metadata=tuple(metadata),
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
