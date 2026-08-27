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
from hephaestus.core.motion import MotionTimeout
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
    #: ``ASSEMBLY.md`` §3: one record per declared constraint, with its residual.
    constraints: tuple[Mapping[str, Any], ...] = ()
    #: ``KINEMATICS.md`` §6 (Stage 9C): one record per declared joint / pose /
    #: motion check, each carrying the engine outcome it was judged on.
    joints: tuple[Mapping[str, Any], ...] = ()
    poses: tuple[Mapping[str, Any], ...] = ()
    motion_checks: tuple[Mapping[str, Any], ...] = ()
    tool_calls: int | None = None
    budget_tool_calls: int | None = None
    within_budget: bool = True
    #: Protected task files the run had modified (restored before grading).
    restored_protected: tuple[str, ...] = ()
    #: ``EXTERNAL_EVAL.md`` §5 (deliverable-scoped grading): build failures of
    #: parts *other than* the task's declared deliverable. Facts, never fail
    #: reasons — they are recorded here, outside :attr:`reasons`, so they can
    #: never reach the verdict. Empty on every corpus task (no deliverable).
    other_build_failures: tuple[str, ...] = ()

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
            "constraints": [dict(c) for c in self.constraints],
            "joints": [dict(j) for j in self.joints],
            "poses": [dict(p) for p in self.poses],
            "motion_checks": [dict(m) for m in self.motion_checks],
            "tool_calls": self.tool_calls,
            "budget_tool_calls": self.budget_tool_calls,
            "within_budget": self.within_budget,
            "restored_protected": list(self.restored_protected),
            "other_build_failures": list(self.other_build_failures),
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


def _build_deliverable_scoped(
    cad: CadOps, layout: ProjectLayout, deliverable: str
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build every part; only the deliverable's failures are fail reasons.

    ``EXTERNAL_EVAL.md`` §5 (deliverable-scoped grading, converted CADGenBench
    tasks): other parts' failures land in the third element — recorded facts
    that never charge the verdict, because a scratch part a model probed
    geometry with is good work, not a failure. A deliverable that was never
    authored fails under its own name: it is the one part the task is about.
    Corpus tasks never come here — :func:`_build_all` is their unchanged path.
    """
    builds: dict[str, Any] = {}
    reasons: list[str] = []
    facts: list[str] = []
    parts = layout.part_names()
    if not parts:
        return builds, ["no_parts_authored"], facts
    if deliverable not in parts:
        reasons.append(f"deliverable_not_authored:{deliverable}")
    for part in parts:
        sink = reasons if part == deliverable else facts
        result = _build_with_lease_retry(cad, part)
        if result is None:
            sink.append(f"build_lease_busy:{part}")
            continue
        builds[part] = result
        if result.get("status") != "ok":
            sink.append(f"build_failed:{part}")
        elif not bool(result.get("current")):
            sink.append(f"build_not_current:{part}")
    return builds, reasons, facts


def _build_declared_scoped(
    cad: CadOps, layout: ProjectLayout, declared: frozenset[str]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build every part; only task-declared parts' failures are fail reasons.

    Corpus grading scoped to :meth:`BenchTask.declared_parts` (2026-08-02
    autopsy): the task's own acceptance names its deliverable set, so an
    undeclared scratch part a model probed geometry with lands in the facts,
    exactly as the adapter's deliverable-scoped path treats it. A DECLARED
    part that was never authored fails by name — the acceptance would fail
    on it downstream anyway, but here the reason says what is actually wrong.
    """
    builds: dict[str, Any] = {}
    reasons: list[str] = []
    facts: list[str] = []
    parts = layout.part_names()
    if not parts:
        return builds, ["no_parts_authored"], facts
    for part in sorted(declared - set(parts)):
        reasons.append(f"declared_part_missing:{part}")
    for part in parts:
        sink = reasons if part in declared else facts
        result = _build_with_lease_retry(cad, part)
        if result is None:
            sink.append(f"build_lease_busy:{part}")
            continue
        builds[part] = result
        if result.get("status") != "ok":
            sink.append(f"build_failed:{part}")
        elif not bool(result.get("current")):
            sink.append(f"build_not_current:{part}")
    return builds, reasons, facts


def _run_required_checks(
    cad: CadOps,
    task: BenchTask,
    *,
    parts: frozenset[str] | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
    """Install the task's CHECKS, run them over the graded parts' snapshot.

    ``parts`` (the task's declared set, or the deliverable) scopes the
    snapshot: the acceptance checks measure the parts the task names, and an
    undeclared scratch part with no successful build must not veto them
    through an incoherent whole-project snapshot.
    """
    reasons: list[str] = []
    for name, source in task.check_sources().items():
        cad.write_check(name, source, op_id=f"bench-check-{uuid.uuid4().hex}")
    report = cad.run_project_checks(None, parts=sorted(parts) if parts else None)
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
        # Unique per grade: export targets are O_EXCL/never-overwritten by
        # design, so a deterministic name made RE-grading the same project
        # fail as export_failed (2026-08-13: three false failures on a
        # nest-gusset diagnostic re-run into reused dirs). The uuid mirrors
        # the op_id every other grader operation already carries.
        target = (
            f"bench-{requirement.part}-{index}-{uuid.uuid4().hex[:8]}"
            f".{EXPORT_FORMATS[requirement.fmt]}"
        )
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


def _install_kinematic_entry(
    declare: Any, update: Any, declared: Mapping[str, Any], entry: Mapping[str, Any]
) -> None:
    """Declare one task-owned kinematic entry, replacing a same-id run entry.

    The ``_validate_constraints`` dance verbatim: a run that declared the
    task's id gets the task's version of it (``withdrawn: False`` included, so
    a withdraw-then-pass paperwork escape stays closed), and a fresh id is a
    plain declaration. The op ids mirror every other grader write.
    """
    entry_id = str(entry["id"])
    if entry_id in declared:
        patch = {key: value for key, value in entry.items() if key != "id"}
        patch["withdrawn"] = False
        update(
            entry_id,
            patch,
            "replaced by the bench task's acceptance spec",
            op_id=f"bench-motion-{uuid.uuid4().hex}",
        )
    else:
        declare(entry, op_id=f"bench-motion-{uuid.uuid4().hex}")


def _withdraw_conflicting_mechanism(cad: CadOps, task: BenchTask) -> None:
    """Clear run-declared state the task's mechanism cannot coexist with.

    The joint graph is a forest (one parent joint per part) and a coupled
    child is not a free parameter — both are *write-time* rules, so a run's
    own declarations could otherwise make the task's acceptance entries
    undeclarable: a run joint riding the same child part under a different
    id, or a run coupling driving a joint id the task's poses and sweeps
    assign. The task owns the acceptance mechanism exactly as it owns its
    constraints and CHECKS, so the conflicting run entries are withdrawn —
    a recorded generation with a recorded reason, never an erasure — before
    the task's are installed.
    """
    task_ids = {joint.id for joint in task.joints}
    child_parts = {
        str(joint.entry["child"]).split(":", 1)[0]
        for joint in task.joints
        if joint.entry.get("child")
    }
    joints = cad.joint_set()
    for entry in joints.state().active:
        if entry.id in task_ids:
            continue
        if entry.anchors[1].part in child_parts:
            joints.withdraw(
                entry.id,
                "superseded by the bench task's acceptance joint over the same part",
                op_id=f"bench-motion-{uuid.uuid4().hex}",
            )
    bound: set[str] = set()
    for pose in task.poses:
        bound |= set(cast("Mapping[str, Any]", pose.entry.get("joints", {})))
    for check in task.motion_checks:
        bound |= set(cast("Mapping[str, Any]", check.entry.get("sweep", {})))
    if not bound:
        return
    couplings = cad.coupling_set()
    for coupling in couplings.state().active:
        if coupling.child in bound:
            couplings.withdraw(
                coupling.id,
                "superseded by the bench task's acceptance spec, which assigns "
                f"joint {coupling.child} as a free parameter",
                op_id=f"bench-motion-{uuid.uuid4().hex}",
            )


def _validate_motion(
    cad: CadOps, task: BenchTask
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Install the task's declared mechanism and evaluate it through the engine.

    ``KINEMATICS.md`` §6 (bench): joints, named poses and motion checks in
    ``task.json`` are graded *through the same engine path* ``check_motion``
    uses — :class:`~hephaestus.core.motion.MotionEvaluator` for the status'
    per-joint/per-pose outcomes and
    :class:`~hephaestus.core.motion.SweepEvaluator` for the sampled checks —
    never from anything the run reported about its own mechanism. The entries
    are the task's own, installed over whatever the run declared, exactly as
    ``_validate_constraints`` installs the task's mates (and BEFORE it runs,
    because a pose-bound constraint evaluates at the pose ids installed
    here).

    Every judged state gets its own reason token (``VALIDATION.md`` §1: a
    check fails under the name of what actually failed): an unresolvable
    joint or pose names the engine's reason, a falsified sweep carries the
    worst sample's measured value, an off-expect verdict names both
    spellings, and a §4 wall-clock ceiling is ``motion_timeout`` with the
    evaluated-sample count — partial evidence, never a silent pass. An entry
    the project refuses to accept is ``motion_undeclarable``, charged to the
    run: the Tier 1 meta-test proves every task's entries declare cleanly on
    a fresh project, so a live refusal reflects run-declared state the
    withdrawal pass above could not clear, which the run owns.
    """
    if not (task.joints or task.poses or task.motion_checks):
        return [], [], [], []
    reasons: list[str] = []
    joint_records: list[dict[str, Any]] = []
    pose_records: list[dict[str, Any]] = []
    check_records: list[dict[str, Any]] = []
    _withdraw_conflicting_mechanism(cad, task)

    installed_joints: list[str] = []
    installed_poses: list[str] = []
    installed_checks: list[str] = []
    installs = (
        (task.joints, cad.joint_set(), "joint", joint_records, installed_joints),
        (task.poses, cad.pose_set(), "pose", pose_records, installed_poses),
        (
            task.motion_checks,
            cad.motion_check_set(),
            "motion_check",
            check_records,
            installed_checks,
        ),
    )
    for requirements, entry_set, noun, records, installed in installs:
        declared = entry_set.state().by_id
        for requirement in requirements:
            record: dict[str, Any] = {"requirement": requirement.to_json()}
            try:
                _install_kinematic_entry(
                    entry_set.declare, entry_set.update, declared, requirement.declaration()
                )
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                reasons.append(f"motion_undeclarable:{noun}:{requirement.id}")
                records.append(record)
                continue
            installed.append(requirement.id)
            records.append(record)

    status = cad.motion_evaluator().evaluate(record=False)
    joint_outcomes = {outcome.id: outcome for outcome in status.joints}
    pose_outcomes = {outcome.id: outcome for outcome in status.poses}
    for record in joint_records:
        requirement_id = str(cast("Mapping[str, Any]", record["requirement"])["entry"]["id"])
        outcome = joint_outcomes.get(requirement_id)
        if requirement_id not in installed_joints or outcome is None:
            continue  # already charged as motion_undeclarable above
        record["outcome"] = outcome.to_json()
        if outcome.state != "resolved":
            reasons.append(f"motion_joint_unresolvable:{requirement_id}:{outcome.reason}")
    for record in pose_records:
        requirement_id = str(cast("Mapping[str, Any]", record["requirement"])["entry"]["id"])
        outcome = pose_outcomes.get(requirement_id)
        if requirement_id not in installed_poses or outcome is None:
            continue
        record["outcome"] = outcome.to_json()
        if outcome.state != "resolved":
            reasons.append(f"motion_pose_unresolvable:{requirement_id}:{outcome.reason}")

    if installed_checks:
        try:
            results = cad.sweep_evaluator().evaluate(installed_checks)
        except MotionTimeout as exc:
            reasons.append(
                f"motion_timeout:{exc.check_id}:{exc.samples_evaluated}/{exc.grid_total}_samples"
            )
            return joint_records, pose_records, check_records, reasons
        by_id = {result.id: result for result in results}
        expected = {requirement.id: requirement.expect for requirement in task.motion_checks}
        for record in check_records:
            requirement_id = str(cast("Mapping[str, Any]", record["requirement"])["entry"]["id"])
            result = by_id.get(requirement_id)
            if requirement_id not in installed_checks or result is None:
                continue
            record["result"] = result.to_json()
            want = expected[requirement_id]
            if result.verdict == want:
                continue
            if result.verdict == "unresolvable":
                # Never conflated with a violation: nothing was measured at all.
                reasons.append(f"motion_check_unresolvable:{requirement_id}:{result.reason}")
            elif result.verdict == "violated":
                measured = None if result.worst is None else result.worst.measured
                reasons.append(f"motion_check_violated:{requirement_id}:{measured}")
            else:
                reasons.append(f"motion_check_state:{requirement_id}:{result.verdict}!={want}")
    return joint_records, pose_records, check_records, reasons


def _validate_constraints(cad: CadOps, task: BenchTask) -> tuple[list[dict[str, Any]], list[str]]:
    """Declare the task's constraints and evaluate them through the engine path.

    ``ASSEMBLY.md`` §3. The task's entries are installed over whatever the run
    declared — the same rule the required CHECKS follow, and for the same reason:
    the acceptance spec is the task's, so a run cannot pass by declaring a weaker
    mate (or by declaring none). Evaluation goes through
    :class:`~hephaestus.core.assembly.AssemblyEvaluator` with the ids named, so
    the numbers here are the numbers ``check_assembly`` reports and the partial
    evaluation is deliberately not projected over the run's own status.

    Each of the three states gets its own reason token, because they call for
    different fixes and ``VALIDATION.md`` §1 requires a check to fail under the
    name of what actually failed.
    """
    if not task.constraints:
        return [], []
    records: list[dict[str, Any]] = []
    reasons: list[str] = []
    constraints = cad.constraint_set()
    declared = constraints.state().by_id
    for requirement in task.constraints:
        entry = requirement.declaration()
        try:
            if requirement.id in declared:
                # The run declared this id too: the task's version replaces it,
                # with the substitution recorded as the generation's reason.
                # ``withdrawn: False`` is part of the replacement, not decoration:
                # a withdrawn entry is never evaluated, so a run that declared the
                # task's id and then withdrew it would otherwise leave the
                # acceptance constraint unmeasurable — the run escaping the mate by
                # paperwork, which is exactly what "the task owns it" forbids.
                patch = {key: value for key, value in entry.items() if key != "id"}
                patch["withdrawn"] = False
                constraints.update(
                    requirement.id,
                    patch,
                    "replaced by the bench task's acceptance constraint",
                    op_id=f"bench-constraint-{uuid.uuid4().hex}",
                )
            else:
                constraints.declare(entry, op_id=f"bench-constraint-{uuid.uuid4().hex}")
        except Exception as exc:
            records.append(
                {"requirement": requirement.to_json(), "error": f"{type(exc).__name__}: {exc}"}
            )
            # The entry is the TASK's, so a refusal here is our bug, not the
            # agent's: named as a harness error so it does not charge the run.
            reasons.append(f"harness_error:constraint_undeclarable:{requirement.id}")
            continue
        records.append({"requirement": requirement.to_json()})
    wanted = [
        requirement.id for requirement in task.constraints if not _errored(records, requirement.id)
    ]
    if not wanted:
        return records, reasons
    try:
        status = cad.assembly_evaluator().evaluate(wanted, record=False)
    except Exception as exc:  # pragma: no cover - a broken store, not a verdict
        reasons.append(f"harness_error:assembly_evaluation_failed:{type(exc).__name__}")
        return records, reasons
    outcomes = {outcome.id: outcome for outcome in status.constraints}
    expected = {requirement.id: requirement.expect for requirement in task.constraints}
    for record in records:
        requirement_id = str(cast("Mapping[str, Any]", record["requirement"])["entry"]["id"])
        outcome = outcomes.get(requirement_id)
        if outcome is None:
            if "error" not in record:  # pragma: no cover - evaluate() covers every id
                reasons.append(f"harness_error:constraint_not_evaluated:{requirement_id}")
            continue
        record["outcome"] = outcome.to_json()
        want = expected[requirement_id]
        if outcome.state == want:
            continue
        if outcome.state == "unresolvable":
            # Never conflated with a violation: nothing was measured at all.
            reasons.append(f"constraint_unresolvable:{requirement_id}:{outcome.reason}")
        elif outcome.state == "violated":
            reasons.append(f"constraint_violated:{requirement_id}:{outcome.measured}")
        else:
            reasons.append(f"constraint_state:{requirement_id}:{outcome.state}!={want}")
    return records, reasons


def _errored(records: Sequence[Mapping[str, Any]], constraint_id: str) -> bool:
    """True when declaring this constraint already failed (nothing to evaluate)."""
    for record in records:
        entry = cast("Mapping[str, Any]", record["requirement"])["entry"]
        if str(cast("Mapping[str, Any]", entry)["id"]) == constraint_id:
            return "error" in record
    return False


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
    constraints: list[dict[str, Any]] = []
    joints: list[dict[str, Any]] = []
    poses: list[dict[str, Any]] = []
    motion_checks: list[dict[str, Any]] = []
    graded = False
    with open_cad(project_root) as cad:
        layout = cad.layout
        declared = task.declared_parts()
        if task.deliverable is not None:
            builds, build_reasons, build_facts = _build_deliverable_scoped(
                cad, layout, task.deliverable
            )
        elif declared:
            builds, build_reasons, build_facts = _build_declared_scoped(cad, layout, declared)
        else:
            # A task that names no parts anywhere keeps the original
            # every-part rule — there is nothing to scope to.
            builds, build_reasons = _build_all(cad, layout)
            build_facts = []
        reasons.extend(build_reasons)
        if not build_reasons:
            graded = True
            if task.deliverable is not None and not task.required_checks:
                # Deliverable-scoped task with no required checks: running the
                # project-scoped check bundle anyway would assemble a snapshot
                # over EVERY part, and a broken scratch part makes that snapshot
                # incoherent — failing the run on the scratch part through the
                # back door, which §5 exists to forbid. Nothing to run, so
                # nothing is run.
                check_reasons: list[str] = []
            else:
                scope = (
                    frozenset({task.deliverable})
                    if task.deliverable is not None
                    else (declared or None)
                )
                check_status, required, other, check_reasons = _run_required_checks(
                    cad, task, parts=scope
                )
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
            # Motion BEFORE constraints on purpose: a pose-bound constraint
            # (KINEMATICS.md §3) evaluates at pose ids the motion pass installs.
            joints, poses, motion_checks, motion_reasons = _validate_motion(cad, task)
            reasons.extend(motion_reasons)
            constraint_records, constraint_reasons = _validate_constraints(cad, task)
            constraints = constraint_records
            reasons.extend(constraint_reasons)
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
        constraints=tuple(constraints),
        joints=tuple(joints),
        poses=tuple(poses),
        motion_checks=tuple(motion_checks),
        tool_calls=tool_calls,
        budget_tool_calls=task.budget_tool_calls,
        within_budget=within_budget,
        restored_protected=tuple(tampered),
        other_build_failures=tuple(build_facts),
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
