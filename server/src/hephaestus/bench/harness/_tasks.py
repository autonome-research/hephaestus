"""The corpus task model: what one ``corpus/tasks/<id>/`` declares.

A task is a prompt, a tool-call budget, the CHECKS grading installs, the exports
and renders grading must be able to produce, and the seeded files a run may not
edit its way past. Loading is strict — a task whose id, spec or required check
source is wrong fails here rather than mid-run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.app import repo_root
from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS

__all__ = [
    "PROMPT_SUFFIXES",
    "BenchTask",
    "ExportRequirement",
    "RenderRequirement",
    "corpus_solutions_dir",
    "corpus_tasks_dir",
    "load_tasks",
    "seeded_prompt",
    "solution_dir",
    "task_ids",
]

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
