"""Bench harness: run one ``corpus/`` task end to end and grade it.

The Tier 3 loop (verification.md §Tier 3, digest §8), one run at a time:

1. **seed** a fresh project from the task spec (``corpus/tasks/<id>/seed/`` copied
   into a scratch root; manifest/``globals.py``/``parts``/``checks`` guaranteed);
2. **prompt** a real orchestrator session — the packaged Node sidecar driven by
   :class:`~hephaestus.agent_bridge.app.BridgeRuntime` against a configurable
   provider — with the task's natural-language prompt plus a deterministic
   per-seed suffix. Normalized ``tool_call`` events are counted against the
   task's budget *live*: exceeding it cancels the run;
3. **grade** after the terminal: build every part in the project, install the
   task's required CHECKS as project checks, run them project-scoped, then
   validate the required exports (bytes sniffed per format, ``as_built`` DXF
   profile count where declared) and required renders. Pass = every required
   check passes AND every export/render validates AND the run stayed within
   budget;
4. **archive** normalized events (JSONL), the run record, the prompt and the
   grading evidence under ``bench/results/<model>/<date>/<task>-s<seed>/``.

The same grading path validates the ``corpus/solutions/`` reference
implementations (:func:`grade_reference_solution`) — a task no reference solution
passes is a broken task, not a hard task.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import itertools
import json
import os
import shutil
import struct
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.app import BridgeRuntime, ProviderSpec, repo_root
from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS, CadOps
from hephaestus.core.project_store.layout import (
    GLOBALS_FILENAME,
    ProjectLayout,
    load_project,
    open_store,
)

from .scoring import RUNS_FILENAME

__all__ = [
    "ARCHIVE_EVENTS_FILENAME",
    "ARCHIVE_RESULT_FILENAME",
    "BENCH_RESULTS_DIRNAME",
    "DEFAULT_PROMPT_TIMEOUT",
    "DEFAULT_SEEDS",
    "PROMPT_SUFFIXES",
    "BenchRun",
    "BenchTask",
    "ExportRequirement",
    "GradeReport",
    "ProviderConfig",
    "RenderRequirement",
    "RunContext",
    "RunRecord",
    "RuntimeFactory",
    "apply_solution",
    "bench_answerer",
    "corpus_solutions_dir",
    "corpus_tasks_dir",
    "default_runtime_factory",
    "dry_run",
    "dxf_profile_count",
    "grade",
    "grade_reference_solution",
    "load_tasks",
    "open_cad",
    "restore_protected",
    "results_root",
    "run_bench",
    "run_task",
    "seed_project",
    "seeded_prompt",
    "session_transcript_dir",
    "solution_dir",
    "task_ids",
    "validate_export_bytes",
]

#: Results/archive root relative to the repository root (``bench/results``).
BENCH_RESULTS_DIRNAME = "bench"

ARCHIVE_EVENTS_FILENAME = "events.jsonl"
ARCHIVE_RESULT_FILENAME = "result.json"

#: Seeds per task; the gate needs S >= 3 (8 tasks x 3 seeds => n >= 24).
DEFAULT_SEEDS = 3

#: Wall-clock cap for one prompt run (CAD builds are minutes, not seconds).
DEFAULT_PROMPT_TIMEOUT = 1800.0

#: Deterministic per-seed prompt suffixes. The seed varies *only* the closing
#: instruction, never the task requirements, so seeds measure run-to-run
#: variance rather than different tasks.
PROMPT_SUFFIXES: tuple[str, ...] = (
    "Work in millimetres. When you are done, summarise what you built and the "
    "checks you relied on.",
    "All dimensions are millimetres. Build the geometry before you report, and "
    "say which measurements you verified.",
    "Units are millimetres throughout. Verify your work with the tools before "
    "you finish, then summarise the result.",
    "Millimetres everywhere. Finish by stating the final dimensions you measured.",
)


# --------------------------------------------------------------------------
# corpus locations


def corpus_tasks_dir(root: Path | None = None) -> Path:
    """``corpus/tasks`` (the public split's task specs)."""
    return (root or repo_root()) / "corpus" / "tasks"


def corpus_solutions_dir(root: Path | None = None) -> Path:
    """``corpus/solutions`` (one reference implementation per task)."""
    return (root or repo_root()) / "corpus" / "solutions"


def results_root(root: Path | None = None) -> Path:
    """``bench/results`` — the archive + leaderboard artifact root."""
    return (root or repo_root()) / BENCH_RESULTS_DIRNAME / "results"


def solution_dir(task_id: str, *, solutions_dir: Path | None = None) -> Path:
    return (solutions_dir or corpus_solutions_dir()) / task_id


def session_transcript_dir(project_root: Path, session_id: str) -> Path:
    """Where a run's Pi session transcript lives (``.heph/sessions/<id>``).

    The archived run record points at it rather than copying it: the transcript
    is inside the archived project, which is what CI uploads as the run artifact.
    """
    return project_root / ".heph" / "sessions" / session_id


# --------------------------------------------------------------------------
# task model


@dataclass(frozen=True)
class ExportRequirement:
    """One required export: format, layout and the byte-level acceptance test."""

    part: str
    fmt: str
    layout: str = "as_built"
    #: Required count of outermost closed profiles (DXF/SVG cut layouts only).
    profile_count: int | None = None
    min_bytes: int = 64

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ExportRequirement:
        fmt = str(data["format"])
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"unknown export format {fmt!r}")
        raw_count = data.get("profile_count")
        return cls(
            part=str(data["part"]),
            fmt=fmt,
            layout=str(data.get("layout", "as_built")),
            profile_count=None if raw_count is None else int(cast("int", raw_count)),
            min_bytes=int(cast("int", data.get("min_bytes", 64))),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "format": self.fmt,
            "layout": self.layout,
            "profile_count": self.profile_count,
            "min_bytes": self.min_bytes,
        }


@dataclass(frozen=True)
class RenderRequirement:
    """One required render (e.g. the ``+Z`` midplane section of an enclosure)."""

    part: str
    channel: str = "rgb"
    section_plane: str | None = None
    views: tuple[str, ...] = ("iso",)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> RenderRequirement:
        raw_views = data.get("views")
        views = (
            tuple(str(v) for v in cast("Sequence[Any]", raw_views))
            if isinstance(raw_views, list)
            else ("iso",)
        )
        plane = data.get("section_plane")
        return cls(
            part=str(data["part"]),
            channel=str(data.get("channel", "rgb")),
            section_plane=None if plane is None else str(plane),
            views=views,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "channel": self.channel,
            "section_plane": self.section_plane,
            "views": list(self.views),
        }


@dataclass(frozen=True)
class BenchTask:
    """One ``corpus/tasks/<id>/`` specification."""

    id: str
    directory: Path
    prompt: str
    budget_tool_calls: int
    required_checks: tuple[str, ...] = ()
    exports: tuple[ExportRequirement, ...] = ()
    renders: tuple[RenderRequirement, ...] = ()
    #: Seeded, task-owned files (inspection gauges, broken fixtures) restored
    #: from ``seed/`` before grading, so a run cannot pass by editing them.
    protected_paths: tuple[str, ...] = ()
    #: Free-text note kept in the archive (never shown to the model).
    notes: str = ""

    @property
    def seed_dir(self) -> Path:
        return self.directory / "seed"

    @property
    def checks_dir(self) -> Path:
        return self.directory / "checks"

    def check_sources(self) -> dict[str, str]:
        """``{check file stem: source}`` for every required CHECKS file."""
        sources: dict[str, str] = {}
        for name in self.required_checks:
            path = self.checks_dir / f"{name}.py"
            if not path.is_file():
                raise FileNotFoundError(f"task {self.id}: required check source {path} is missing")
            sources[name] = path.read_text(encoding="utf-8")
        return sources

    @classmethod
    def load(cls, directory: Path) -> BenchTask:
        spec_path = directory / "task.json"
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{spec_path}: task spec must be a JSON object")
        data = cast("dict[str, Any]", raw)
        task_id = str(data["id"])
        if task_id != directory.name:
            raise ValueError(
                f"{spec_path}: id {task_id!r} does not match directory {directory.name!r}"
            )
        checks_raw = data.get("required_checks", [])
        exports_raw = data.get("export_requirements", [])
        renders_raw = data.get("render_requirements", [])
        task = cls(
            id=task_id,
            directory=directory,
            prompt=str(data["prompt"]),
            budget_tool_calls=int(cast("int", data["budget_tool_calls"])),
            required_checks=tuple(str(name) for name in cast("Sequence[Any]", checks_raw)),
            exports=tuple(
                ExportRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", exports_raw)
            ),
            renders=tuple(
                RenderRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", renders_raw)
            ),
            protected_paths=tuple(
                str(item) for item in cast("Sequence[Any]", data.get("protected_paths", []))
            ),
            notes=str(data.get("notes", "")),
        )
        task.check_sources()  # fail fast on a task whose check source is missing
        return task

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "budget_tool_calls": self.budget_tool_calls,
            "required_checks": list(self.required_checks),
            "export_requirements": [e.to_json() for e in self.exports],
            "render_requirements": [r.to_json() for r in self.renders],
            "protected_paths": list(self.protected_paths),
        }


def task_ids(*, tasks_dir: Path | None = None) -> tuple[str, ...]:
    """Every task id in the corpus, in lexical order."""
    directory = tasks_dir or corpus_tasks_dir()
    return tuple(sorted(p.name for p in directory.iterdir() if (p / "task.json").is_file()))


def load_tasks(
    ids: Sequence[str] | None = None, *, tasks_dir: Path | None = None
) -> tuple[BenchTask, ...]:
    """Load the named tasks (default: the whole corpus, lexically ordered)."""
    directory = tasks_dir or corpus_tasks_dir()
    wanted = list(ids) if ids else list(task_ids(tasks_dir=directory))
    tasks: list[BenchTask] = []
    for task_id in wanted:
        task_dir = directory / task_id
        if not (task_dir / "task.json").is_file():
            raise FileNotFoundError(f"no corpus task {task_id!r} under {directory}")
        tasks.append(BenchTask.load(task_dir))
    return tuple(tasks)


def seeded_prompt(task: BenchTask, seed: int) -> str:
    """The task prompt plus a deterministic, requirement-free per-seed suffix."""
    digest = hashlib.sha256(f"{task.id}:{seed}".encode()).digest()
    suffix = PROMPT_SUFFIXES[digest[0] % len(PROMPT_SUFFIXES)]
    return f"{task.prompt.rstrip()}\n\n{suffix}"


# --------------------------------------------------------------------------
# project seeding + reference solutions


def seed_project(task: BenchTask, project_root: Path) -> Path:
    """Materialize a fresh project for ``task`` at ``project_root``."""
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
    (project_root / "checks").mkdir(exist_ok=True)
    return project_root


def restore_protected(task: BenchTask, project_root: Path) -> list[str]:
    """Restore the task's protected seed files; returns the paths that changed.

    Inspection gauges and broken fixtures are task-owned evidence: grading always
    measures against the seeded originals, so a run that rewrites a gauge to make
    itself pass changes nothing.
    """
    restored: list[str] = []
    for rel in task.protected_paths:
        source = task.seed_dir / rel
        if not source.is_file():
            raise FileNotFoundError(
                f"task {task.id}: protected path {rel!r} is not in {task.seed_dir}"
            )
        target = project_root / rel
        original = source.read_bytes()
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
    source = solution_dir(task.id, solutions_dir=solutions_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"no reference solution for task {task.id!r} at {source}")
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


# --------------------------------------------------------------------------
# export/render validation


def _closed_loop_components(
    segments: Sequence[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[float, float, float, float]]:
    """Connected components of a 2D segment soup, as ``(xmin, ymin, xmax, ymax)``."""
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def find(node: tuple[float, float]) -> tuple[float, float]:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for start, end in segments:
        union(start, end)
    groups: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    boxes: list[tuple[float, float, float, float]] = []
    for points in groups.values():
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def dxf_profile_count(data: bytes) -> int:
    """Count outermost closed profiles in a DXF cut layout.

    The ``as_built`` DXF of a flat sheet layout is a hidden-line projection: each
    panel outline becomes one connected component of line/arc segments. Components
    fully contained in another component's bounding box (mortises, holes) are
    *interior* loops and are not counted, so the number returned is the number of
    cut profiles a nesting/CAM step would see.
    """
    # Imported lazily (only DXF exports need ezdxf) and through an Any-typed
    # module handle: ezdxf ships no complete public typing surface.
    ezdxf: Any = importlib.import_module("ezdxf")
    dxf_error: type[Exception] = cast(
        "type[Exception]", importlib.import_module("ezdxf.lldxf.const").DXFStructureError
    )

    def key(x: float, y: float) -> tuple[float, float]:
        return (round(float(x), 3), round(float(y), 3))

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    with tempfile.TemporaryDirectory(prefix="heph-bench-dxf-") as scratch:
        path = Path(scratch) / "layout.dxf"
        path.write_bytes(data)
        try:
            doc: Any = ezdxf.readfile(str(path))
        except (dxf_error, OSError) as exc:  # pragma: no cover - malformed export
            raise ValueError(f"unreadable DXF export: {exc}") from exc
        for entity in doc.modelspace():
            kind = str(entity.dxftype())
            points: list[tuple[float, float]] = []
            if kind == "LINE":
                start = entity.dxf.start
                end = entity.dxf.end
                points = [key(start.x, start.y), key(end.x, end.y)]
            elif kind in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
                points = [key(p[0], p[1]) for p in entity.flattening(0.05)]
            elif kind == "LWPOLYLINE":
                points = [key(p[0], p[1]) for p in entity.get_points()]
            elif kind == "POLYLINE":
                points = [key(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            else:  # pragma: no cover - exporters emit only the geometry above
                continue
            segments.extend(itertools.pairwise(points))
            closed = kind in ("CIRCLE", "ELLIPSE") or bool(getattr(entity, "closed", False))
            if closed and len(points) > 2:
                segments.append((points[-1], points[0]))
    boxes = _closed_loop_components(segments)
    outer = 0
    for index, box in enumerate(boxes):
        nested = any(
            other[0] <= box[0]
            and other[1] <= box[1]
            and other[2] >= box[2]
            and other[3] >= box[3]
            and (other[2] - other[0], other[3] - other[1]) != (box[2] - box[0], box[3] - box[1])
            for j, other in enumerate(boxes)
            if j != index
        )
        if not nested:
            outer += 1
    return outer


def validate_export_bytes(fmt: str, data: bytes) -> str | None:
    """``None`` when ``data`` is a well-formed ``fmt`` payload, else the reason."""
    if not data:
        return "empty_export"
    if fmt == "step":
        head = data[:256]
        if b"ISO-10303-21" not in head:
            return "step_missing_iso10303_header"
    elif fmt == "stl":
        if len(data) < 84:
            return "stl_truncated"
        (count,) = struct.unpack_from("<I", data, 80)
        if count == 0 or len(data) < 84 + count * 50:
            return "stl_triangle_count_mismatch"
    elif fmt == "gltf":
        if data[:4] != b"glTF":
            return "gltf_missing_magic"
    elif fmt == "3mf":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            return "3mf_not_a_zip"
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "3D/3dmodel.model" not in names:
                return "3mf_missing_model_part"
            model = zf.read("3D/3dmodel.model")
        if b"<triangle" not in model:
            return "3mf_model_has_no_triangles"
    elif fmt == "dxf":
        if b"SECTION" not in data or b"ENTITIES" not in data:
            return "dxf_missing_entities_section"
    elif fmt == "svg":
        if b"<svg" not in data[:2048]:
            return "svg_missing_root_element"
    return None


# --------------------------------------------------------------------------
# grading


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


def _build_all(cad: CadOps, layout: ProjectLayout) -> tuple[dict[str, Any], list[str]]:
    """Build every part; return the per-part results and failure reasons."""
    builds: dict[str, Any] = {}
    reasons: list[str] = []
    parts = layout.part_names()
    if not parts:
        return builds, ["no_parts_authored"]
    for part in parts:
        result = cad.build_part(part, op_id=f"bench-build-{uuid.uuid4().hex}")
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


# --------------------------------------------------------------------------
# provider configuration + the run loop


@dataclass(frozen=True)
class ProviderConfig:
    """A resolved provider list plus the selected model id.

    Loaded from a JSON file so no credential or endpoint is hard-coded::

        {"providers": [{"id": "...", "kind": "anthropic"|"openai_compatible",
                        "baseUrl": "...", "credential": "ENV_NAME",
                        "models": [{"id": "...", "contextWindow": 200000,
                                    "maxTokens": 8192, "input": ["text","image"]}]}],
         "credentials": {"ENV_NAME": "literal-secret"},
         "credential_env": ["ENV_NAME"]}

    ``credential_env`` names are read from the ambient environment at load time;
    the supervisor forwards only the resulting allowlist to the sidecar.
    """

    providers: tuple[ProviderSpec, ...]
    model_id: str
    credentials: Mapping[str, str] = field(default_factory=dict[str, str])
    credential_allowlist: tuple[str, ...] = ()

    @property
    def model_slug(self) -> str:
        """Filesystem-safe model id for the ``bench/results/<model>/`` archive."""
        return "".join(c if (c.isalnum() or c in "-._") else "-" for c in self.model_id)

    @classmethod
    def load(cls, path: Path, *, model: str | None = None) -> ProviderConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: provider config must be a JSON object")
        data = cast("dict[str, Any]", raw)
        providers: list[ProviderSpec] = [
            dict(cast("Mapping[str, Any]", spec))
            for spec in cast("Sequence[Any]", data.get("providers", []))
        ]
        if not providers:
            raise ValueError(f"{path}: no providers declared")
        credentials: dict[str, str] = {
            str(k): str(v)
            for k, v in cast("Mapping[str, Any]", data.get("credentials", {})).items()
        }
        allowlist: list[str] = [str(name) for name in credentials]
        for name in cast("Sequence[Any]", data.get("credential_env", [])):
            env_name = str(name)
            value = os.environ.get(env_name)
            if value is None:
                raise ValueError(
                    f"{path}: credential_env {env_name!r} is not set in the environment"
                )
            credentials[env_name] = value
            if env_name not in allowlist:
                allowlist.append(env_name)
        ordered, model_id = cls._select_model(providers, model)
        return cls(
            providers=tuple(ordered),
            model_id=model_id,
            credentials=credentials,
            credential_allowlist=tuple(allowlist),
        )

    @staticmethod
    def _select_model(
        providers: Sequence[ProviderSpec], model: str | None
    ) -> tuple[list[ProviderSpec], str]:
        """Order providers/models so the requested model is the one the sidecar picks.

        The sidecar resolves the *first* model of the *first* provider, so the
        selection is expressed by reordering rather than by a new wire field.
        """
        available: list[tuple[int, str]] = []
        for index, provider in enumerate(providers):
            for spec in cast("Sequence[Any]", provider.get("models", [])):
                model_id = str(cast("Mapping[str, Any]", spec).get("id", ""))
                if model_id:
                    available.append((index, model_id))
        if not available:
            raise ValueError("provider config declares no models")
        if model is None:
            index, model_id = available[0]
        else:
            match = next(((i, m) for i, m in available if m == model), None)
            if match is None:
                raise ValueError(
                    f"model {model!r} is not declared by the provider config "
                    f"(available: {sorted(m for _, m in available)})"
                )
            index, model_id = match
        chosen = dict(cast("Mapping[str, Any]", providers[index]))
        models = [
            dict(cast("Mapping[str, Any]", spec))
            for spec in cast("Sequence[Any]", chosen.get("models", []))
        ]
        models.sort(key=lambda spec: 0 if str(spec.get("id")) == model_id else 1)
        chosen["models"] = models
        ordered: list[ProviderSpec] = [chosen]
        ordered.extend(p for i, p in enumerate(providers) if i != index)
        return ordered, model_id


#: ``(project_root, provider) -> BridgeRuntime`` — the test seam for the sidecar.
RuntimeFactory = Callable[[Path, ProviderConfig], BridgeRuntime]


def default_runtime_factory(project_root: Path, provider: ProviderConfig) -> BridgeRuntime:
    """Production factory: the packaged sidecar over the configured providers."""
    return BridgeRuntime(
        project_root=project_root,
        providers=provider.providers,
        credentials=dict(provider.credentials),
        credential_allowlist=provider.credential_allowlist,
    )


def bench_answerer(params: Mapping[str, Any]) -> Any:
    """Unattended ``ask_user`` policy: take the first option, else defer to the model.

    Bench runs have no human; questions are archived as run evidence and answered
    deterministically so a run cannot hang on a suspension.
    """
    options = params.get("options")
    if isinstance(options, list) and options:
        return cast("list[Any]", options)[0]
    return "Use your best engineering judgement and continue; do not ask again."


@dataclass(frozen=True)
class RunContext:
    """Handed to a ``before_prompt`` hook just before the prompt is sent."""

    task: BenchTask
    seed: int
    prompt: str
    project_root: Path
    runtime: BridgeRuntime
    session_id: str


@dataclass(frozen=True)
class RunRecord:
    """One archived (task, seed) run — the unit :mod:`.scoring` aggregates."""

    task_id: str
    seed: int
    model: str
    date: str
    passed: bool
    status: str
    tool_calls: int
    budget_tool_calls: int
    reasons: tuple[str, ...]
    prompt: str
    archive_dir: str
    event_count: int
    #: The orchestrator session the run used; its Pi JSONL transcript lives at
    #: ``<project>/.heph/sessions/<session_id>`` inside the archived project.
    session_id: str | None = None
    transcript_dir: str | None = None
    project_dir: str | None = None
    terminal_state: str | None = None
    #: Total tokens charged to the run. The sidecar does not report usage on the
    #: wire in Stage 2, so this stays ``None`` (and ``mean_tokens`` with it) until
    #: it does; nothing in the gate depends on it.
    tokens: float | None = None
    error: str | None = None
    grade: Mapping[str, Any] = field(default_factory=dict[str, Any])
    questions: tuple[Mapping[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "seed": self.seed,
            "model": self.model,
            "date": self.date,
            "passed": self.passed,
            "status": self.status,
            "tool_calls": self.tool_calls,
            "budget_tool_calls": self.budget_tool_calls,
            "reasons": list(self.reasons),
            "prompt": self.prompt,
            "archive_dir": self.archive_dir,
            "event_count": self.event_count,
            "session_id": self.session_id,
            "transcript_dir": self.transcript_dir,
            "project_dir": self.project_dir,
            "terminal_state": self.terminal_state,
            "tokens": self.tokens,
            "error": self.error,
            "grade": dict(self.grade),
            "questions": [dict(q) for q in self.questions],
        }


@dataclass(frozen=True)
class BenchRun:
    """The result of one ``heph bench run`` invocation."""

    model: str
    date: str
    archive_dir: Path
    records: tuple[RunRecord, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "date": self.date,
            "archive_dir": str(self.archive_dir),
            "records": [record.to_json() for record in self.records],
        }


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class _BudgetGuard:
    """Counts ``tool_call`` events and cancels the run once the budget is spent."""

    def __init__(self, runtime: BridgeRuntime, run_id: str, budget: int) -> None:
        self._runtime = runtime
        self._run_id = run_id
        self._budget = budget
        self._cancelled = False
        self.tool_calls = 0
        self.questions: list[Mapping[str, Any]] = []

    def on_event(self, event: Mapping[str, Any]) -> None:
        kind = event.get("kind")
        if kind == "question":
            payload = event.get("payload")
            if isinstance(payload, dict):
                self.questions.append(cast("Mapping[str, Any]", payload))
            return
        if kind != "tool_call":
            return
        self.tool_calls += 1
        if self.tool_calls > self._budget and not self._cancelled:
            self._cancelled = True
            # Cancel off the reader thread: the notification sink must not block
            # on the supervisor's stdin writer.
            threading.Thread(target=self._runtime.cancel, args=(self._run_id,), daemon=True).start()

    @property
    def cancelled_for_budget(self) -> bool:
        return self._cancelled


def run_task(
    task: BenchTask,
    seed: int,
    *,
    provider: ProviderConfig,
    archive_dir: Path,
    runtime_factory: RuntimeFactory | None = None,
    before_prompt: Callable[[RunContext], None] | None = None,
    prompt_timeout: float = DEFAULT_PROMPT_TIMEOUT,
    date: str | None = None,
    project_root: Path | None = None,
) -> RunRecord:
    """Run one (task, seed) pair end to end and archive it under ``archive_dir``."""
    run_dir = archive_dir / f"{task.id}-s{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    project = project_root or (run_dir / "project")
    seed_project(task, project)
    prompt = seeded_prompt(task, seed)
    (run_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    events: list[Mapping[str, Any]] = []
    factory = runtime_factory or default_runtime_factory
    runtime = factory(project, provider)
    status = "error"
    error: str | None = None
    terminal_state: str | None = None
    session_id: str | None = None
    guard: _BudgetGuard | None = None
    try:
        runtime.start()
        session_id = runtime.create_session("orchestrator", session_id=f"bench-{task.id}-s{seed}")
        run_id = runtime.new_run_id()
        guard = _BudgetGuard(runtime, run_id, task.budget_tool_calls)

        def on_event(event: dict[str, Any]) -> None:
            events.append(event)
            assert guard is not None
            guard.on_event(event)

        if before_prompt is not None:
            before_prompt(
                RunContext(
                    task=task,
                    seed=seed,
                    prompt=prompt,
                    project_root=project,
                    runtime=runtime,
                    session_id=session_id,
                )
            )
        result = runtime.prompt(
            session_id,
            prompt,
            run_id=run_id,
            answerer=bench_answerer,
            on_event=on_event,
            timeout=prompt_timeout,
        )
        status = result.status
        if result.terminal is not None:
            terminal_state = str(result.terminal.get("state"))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        with contextlib.suppress(Exception):
            runtime.close()

    tool_calls = guard.tool_calls if guard is not None else 0
    questions = tuple(guard.questions) if guard is not None else ()
    with (run_dir / ARCHIVE_EVENTS_FILENAME).open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    extra: list[str] = []
    if status != "completed":
        extra.append(f"run_{status}")
    if error is not None:
        extra.append("run_error")
    report = grade(task, project, tool_calls=tool_calls, extra_reasons=extra)
    (run_dir / "grade.json").write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    record = RunRecord(
        task_id=task.id,
        seed=seed,
        model=provider.model_id,
        date=date or _today(),
        passed=report.passed,
        status=status,
        tool_calls=tool_calls,
        budget_tool_calls=task.budget_tool_calls,
        reasons=report.reasons,
        prompt=prompt,
        archive_dir=str(run_dir),
        event_count=len(events),
        session_id=session_id,
        transcript_dir=None
        if session_id is None
        else str(session_transcript_dir(project, session_id)),
        project_dir=str(project),
        terminal_state=terminal_state,
        error=error,
        grade=report.to_json(),
        questions=questions,
    )
    (run_dir / ARCHIVE_RESULT_FILENAME).write_text(
        json.dumps(record.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def run_bench(
    tasks: Sequence[BenchTask],
    *,
    provider: ProviderConfig,
    seeds: int = DEFAULT_SEEDS,
    results_dir: Path | None = None,
    date: str | None = None,
    runtime_factory: RuntimeFactory | None = None,
    before_prompt: Callable[[RunContext], None] | None = None,
    prompt_timeout: float = DEFAULT_PROMPT_TIMEOUT,
    on_record: Callable[[RunRecord], None] | None = None,
) -> BenchRun:
    """Run every (task, seed) pair, archiving each run and the ``runs.jsonl`` index."""
    if seeds < 1:
        raise ValueError(f"seeds must be >= 1, got {seeds}")
    run_date = date or _today()
    root = results_dir or results_root()
    archive_dir = root / provider.model_slug / run_date
    archive_dir.mkdir(parents=True, exist_ok=True)
    index = archive_dir / RUNS_FILENAME
    records: list[RunRecord] = []
    for task in tasks:
        for seed in range(1, seeds + 1):
            record = run_task(
                task,
                seed,
                provider=provider,
                archive_dir=archive_dir,
                runtime_factory=runtime_factory,
                before_prompt=before_prompt,
                prompt_timeout=prompt_timeout,
                date=run_date,
            )
            records.append(record)
            with index.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.to_json(), sort_keys=True) + "\n")
            if on_record is not None:
                on_record(record)
    return BenchRun(
        model=provider.model_id, date=run_date, archive_dir=archive_dir, records=tuple(records)
    )


def dry_run(tasks: Sequence[BenchTask], *, seeds: int = DEFAULT_SEEDS) -> list[dict[str, Any]]:
    """Enumerate the planned (task, seed) runs and prompts without any model call."""
    plan: list[dict[str, Any]] = []
    for task in tasks:
        for seed in range(1, seeds + 1):
            plan.append(
                {
                    "task_id": task.id,
                    "seed": seed,
                    "budget_tool_calls": task.budget_tool_calls,
                    "required_checks": list(task.required_checks),
                    "export_requirements": [e.to_json() for e in task.exports],
                    "render_requirements": [r.to_json() for r in task.renders],
                    "prompt": seeded_prompt(task, seed),
                }
            )
    return plan
