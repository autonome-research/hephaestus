"""The corpus task model: what one ``corpus/tasks/<id>/`` declares.

A task is a prompt, a tool-call budget, the CHECKS grading installs, the exports
and renders grading must be able to produce, and the seeded files a run may not
edit its way past. Loading is strict — a task whose id, spec or required check
source is wrong fails here rather than mid-run.

``VALIDATION.md`` §1: every public task ships in **two spec variants**, and they
are never collapsed.

``prose`` (the default, and what every committed ``task.json`` declares)
    seeds without ``checks/``; the agent must infer the spec from the request.
    Measures *interpretation*.
``seeded`` (``<id>@seeded``, derived here — no duplicated task directory)
    installs the task's own acceptance checks into ``checks/`` at seed time as
    an independent spec, and lists them as protected paths so a run cannot edit
    its way to green. Measures *iterate-to-green*.

Deriving the seeded variant rather than committing a second task directory is
deliberate: the prompt, budget and acceptance checks have exactly one home, so
the two splits can never drift apart into different tasks — the only difference
between them is whether the spec was handed over.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.app import repo_root
from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS

__all__ = [
    "PROMPT_SUFFIXES",
    "SEEDED_SUFFIX",
    "SPECS",
    "SPEC_PROSE",
    "SPEC_SEEDED",
    "BenchTask",
    "ExportRequirement",
    "RenderRequirement",
    "base_task_id",
    "corpus_solutions_dir",
    "corpus_tasks_dir",
    "load_tasks",
    "seeded_prompt",
    "seeded_variant",
    "seeded_variant_id",
    "solution_dir",
    "task_ids",
]

#: ``task.json`` ``spec`` values (VALIDATION.md §1). Existing files omit the
#: field and are therefore ``prose`` — the historically baselined split.
SPEC_PROSE: str = "prose"
SPEC_SEEDED: str = "seeded"
SPECS: tuple[str, ...] = (SPEC_PROSE, SPEC_SEEDED)

#: Id suffix of the seeded variant of a public task (``bracket-101@seeded``).
SEEDED_SUFFIX: str = "@seeded"


def seeded_variant_id(task_id: str) -> str:
    """The seeded variant's id for a prose task id (idempotent)."""
    return task_id if task_id.endswith(SEEDED_SUFFIX) else task_id + SEEDED_SUFFIX


def base_task_id(task_id: str) -> str:
    """The prose id behind any variant id (``bracket-101@seeded`` -> ``bracket-101``)."""
    return task_id.split(SEEDED_SUFFIX, 1)[0]


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


def corpus_tasks_dir(root: Path | None = None) -> Path:
    """``corpus/tasks`` (the public split's task specs)."""
    return (root or repo_root()) / "corpus" / "tasks"


def corpus_solutions_dir(root: Path | None = None) -> Path:
    """``corpus/solutions`` (one reference implementation per task)."""
    return (root or repo_root()) / "corpus" / "solutions"


def solution_dir(task_id: str, *, solutions_dir: Path | None = None) -> Path:
    return (solutions_dir or corpus_solutions_dir()) / task_id


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
    #: ``VALIDATION.md`` §1 spec variant: ``prose`` (infer it) or ``seeded``
    #: (the acceptance checks are installed as an independent spec).
    spec: str = SPEC_PROSE

    @property
    def seed_dir(self) -> Path:
        return self.directory / "seed"

    @property
    def checks_dir(self) -> Path:
        return self.directory / "checks"

    @property
    def base_id(self) -> str:
        """The prose id this task is a variant of (its own id when prose)."""
        return base_task_id(self.id)

    @property
    def is_seeded(self) -> bool:
        return self.spec == SPEC_SEEDED

    @property
    def seeded_check_paths(self) -> tuple[str, ...]:
        """Project-relative paths of the acceptance checks seeded as the spec."""
        if not self.is_seeded:
            return ()
        return tuple(f"checks/{name}.py" for name in self.required_checks)

    def check_sources(self) -> dict[str, str]:
        """``{check file stem: source}`` for every required CHECKS file."""
        sources: dict[str, str] = {}
        for name in self.required_checks:
            path = self.checks_dir / f"{name}.py"
            if not path.is_file():
                raise FileNotFoundError(f"task {self.id}: required check source {path} is missing")
            sources[name] = path.read_text(encoding="utf-8")
        return sources

    def protected_sources(self) -> dict[str, bytes]:
        """``{project-relative path: canonical bytes}`` for every protected path.

        Ordinary protected paths (gauges, broken fixtures) come from ``seed/``.
        A seeded variant's acceptance checks come from the task's own
        ``checks/`` tree — the same bytes grading installs — so the restore path
        is one mechanism for both, and the spec a seeded run was given is the
        spec it is graded against.
        """
        seeded_checks = set(self.seeded_check_paths)
        sources: dict[str, bytes] = {}
        check_sources = self.check_sources() if seeded_checks else {}
        for rel in self.protected_paths:
            if rel in seeded_checks:
                sources[rel] = check_sources[Path(rel).stem].encode("utf-8")
                continue
            path = self.seed_dir / rel
            if not path.is_file():
                raise FileNotFoundError(
                    f"task {self.id}: protected path {rel!r} is not in {self.seed_dir}"
                )
            sources[rel] = path.read_bytes()
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
        spec = str(data.get("spec", SPEC_PROSE))
        if spec not in SPECS:
            raise ValueError(f"{spec_path}: spec must be one of {list(SPECS)}, got {spec!r}")
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
            spec=spec,
        )
        task.check_sources()  # fail fast on a task whose check source is missing
        return task

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec": self.spec,
            "prompt": self.prompt,
            "budget_tool_calls": self.budget_tool_calls,
            "required_checks": list(self.required_checks),
            "export_requirements": [e.to_json() for e in self.exports],
            "render_requirements": [r.to_json() for r in self.renders],
            "protected_paths": list(self.protected_paths),
        }


def seeded_variant(task: BenchTask) -> BenchTask:
    """The ``<id>@seeded`` variant of a prose task (VALIDATION.md §1).

    Same directory, same prompt, same budget and the same acceptance checks —
    the only difference is that the checks are installed into ``checks/`` at
    seed time (see :func:`~._seed.seed_project`) and are protected, so the run
    iterates against an independent spec instead of inventing one.
    """
    if task.is_seeded:
        return task
    if not task.required_checks:
        raise ValueError(f"task {task.id}: a seeded variant needs acceptance checks to install")
    task.check_sources()  # fail fast: the spec a seeded run is given must exist
    checks = tuple(f"checks/{name}.py" for name in task.required_checks)
    return replace(
        task,
        id=seeded_variant_id(task.id),
        spec=SPEC_SEEDED,
        protected_paths=task.protected_paths + checks,
    )


def task_ids(*, tasks_dir: Path | None = None, specs: Sequence[str] = SPECS) -> tuple[str, ...]:
    """Corpus task ids in lexical order, for the requested spec variants.

    Defaults to **both** splits: ``VALIDATION.md`` §1 ships every public task as
    prose *and* seeded. Pass ``specs=("prose",)`` for the historically
    baselined split alone (the corpus-v0 aggregate gate names that one).
    """
    directory = tasks_dir or corpus_tasks_dir()
    prose = sorted(p.name for p in directory.iterdir() if (p / "task.json").is_file())
    ids: list[str] = []
    if SPEC_PROSE in specs:
        ids.extend(prose)
    if SPEC_SEEDED in specs:
        ids.extend(seeded_variant_id(task_id) for task_id in prose)
    return tuple(ids)


def load_tasks(
    ids: Sequence[str] | None = None,
    *,
    tasks_dir: Path | None = None,
    specs: Sequence[str] = SPECS,
) -> tuple[BenchTask, ...]:
    """Load the named tasks (default: the whole corpus, both spec variants).

    Ids are stable: ``bracket-101`` is the prose task it has always been, and
    ``bracket-101@seeded`` is its seeded variant, derived from the same
    directory.
    """
    directory = tasks_dir or corpus_tasks_dir()
    wanted = list(ids) if ids else list(task_ids(tasks_dir=directory, specs=specs))
    tasks: list[BenchTask] = []
    for task_id in wanted:
        base = base_task_id(task_id)
        task_dir = directory / base
        if not (task_dir / "task.json").is_file():
            raise FileNotFoundError(f"no corpus task {task_id!r} under {directory}")
        task = BenchTask.load(task_dir)
        tasks.append(seeded_variant(task) if task_id.endswith(SEEDED_SUFFIX) else task)
    return tuple(tasks)


def budget_disclosure(task: BenchTask) -> str:
    """The tool-call budget, stated to the model.

    A run is cancelled once the budget is spent, so an agent that cannot see the
    number cannot ration it — every observed overrun was verification spending
    past a correct result. Disclosing the ceiling (never the pass criteria)
    makes the stop/verify tradeoff decidable. Not a gate relaxation: the budget
    value and the pass criteria are unchanged.
    """
    return (
        f"Tool-call budget: {task.budget_tool_calls} calls for this task. "
        "The run is cancelled when the budget is spent, so spend calls on "
        "building the geometry correctly, not on re-verifying it: one final "
        "run_checks is enough confirmation, and build results already report "
        "bbox/volume/sealed. Stop and summarise as soon as the work is done "
        "and its checks pass."
    )


def seeded_prompt(task: BenchTask, seed: int) -> str:
    """The task prompt plus the budget disclosure and a per-seed suffix."""
    digest = hashlib.sha256(f"{task.id}:{seed}".encode()).digest()
    suffix = PROMPT_SUFFIXES[digest[0] % len(PROMPT_SUFFIXES)]
    return f"{task.prompt.rstrip()}\n\n{budget_disclosure(task)}\n\n{suffix}"
