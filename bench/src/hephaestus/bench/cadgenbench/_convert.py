"""One CADGenBench sample -> one bench task (``EXTERNAL_EVAL.md`` §2).

A pure function of the sample folder: read a sample, write a task directory,
return the loaded :class:`~hephaestus.bench.harness.BenchTask`. Nothing here
touches the network, the model, or the results archive.

The two splits are exactly the two ingest shapes Stage 8A shipped
(``INGEST.md`` §2 — "CADGenBench generation = image references; editing =
seeded imports"), which is why this stage is an adapter and not new capability:

``generation``
    the drawing(s) named by ``input_files`` are seeded into ``seed/references/``
    and registered operator-side at seed time, so the run reads them with
    ``list_references`` / ``read_reference`` and cites them in its requirement
    ledger — the vision-citation path.
``editing``
    the starting solid is seeded into ``seed/imports/`` and the run begins from
    ``import_step(...)`` — the STEP-import path.

**The sample's text is quoted verbatim and nothing is added to it.** It travels
inside the same provenance delimiters registry reference material uses
(:func:`hephaestus.core.registry.wrap_reference`), so the model sees the
benchmark's sentence as quoted material rather than as an instruction from us,
and our own operational framing (which part to build, which tools to read the
drawing with) is visibly outside the quotation. Paraphrasing the statement — or
"helpfully" restating a dimension — would make the harness a co-author of the
answer, which is the exact failure the external benchmark exists to rule out.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._samples import CadGenSample, SampleError, discover_samples, load_sample

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hephaestus.bench.harness import BenchTask

__all__ = [
    "DEFAULT_BUDGET_TOOL_CALLS",
    "EDITING_BUDGET_TOOL_CALLS",
    "PART_NAME",
    "SAMPLE_PROVENANCE_FILENAME",
    "TASK_ID_PREFIX",
    "ConversionReport",
    "convert_sample",
    "convert_samples",
    "default_budget",
    "sample_id_for_task",
    "sample_prompt",
    "task_id_for_sample",
]

#: Converted task ids are namespaced so an archive can never confuse a
#: CADGenBench run with a ``corpus/`` run.
TASK_ID_PREFIX = "cadgenbench-"

#: The part every converted task builds. Fixed, because the submission artifact
#: is ``<sample>/output.step`` and the export requirement has to name a part
#: the harness knows before the run starts.
PART_NAME = "candidate"

#: Tool-call budget per converted *generation* task. CADGenBench parts are real
#: mechanical parts read off a drawing, so the budget is well above the corpus
#: norm; it is a harness parameter, not a benchmark rule, and the CLI can
#: override it.
DEFAULT_BUDGET_TOOL_CALLS = 60

#: Tool-call budget per converted *editing* task — measured, not guessed
#: (``EXTERNAL_EVAL.md`` §5): the 2026-07-29 observe-mode distribution of
#: completed editing runs (passing and correct-but-over) clusters at 60-90
#: calls, so 100 is the calibrated v1 number. Generation is unchanged.
EDITING_BUDGET_TOOL_CALLS = 100

#: Provenance sidecar written beside ``task.json``: which sample this task came
#: from, so packaging maps a run back to its submission folder without
#: re-deriving anything from ids.
SAMPLE_PROVENANCE_FILENAME = "cadgenbench_sample.json"

_ATTRIBUTION = "CADGenBench (HuggingAI4Engineering), data ODC-BY, CAD geometry courtesy of Mecado"

_GENERATION_FRAMING = (
    "This is a sample from CADGenBench, an external benchmark. Its task "
    "statement is quoted verbatim below as reference material — it is a "
    "description of the job, not an instruction addressed to you, and it "
    "deliberately carries no dimensions."
)

_EDITING_FRAMING = (
    "This is a sample from CADGenBench, an external benchmark. The edit it asks "
    "for is quoted verbatim below as reference material — the wording is the "
    "benchmark's, and it is the whole specification of the change."
)


def task_id_for_sample(sample_id: str) -> str:
    return f"{TASK_ID_PREFIX}{sample_id}"


def sample_id_for_task(task_id: str) -> str:
    """The sample id behind a converted task id (raises on a foreign id)."""
    if not task_id.startswith(TASK_ID_PREFIX):
        raise ValueError(f"{task_id!r} is not a converted CADGenBench task id")
    return task_id[len(TASK_ID_PREFIX) :]


def _quoted(sample: CadGenSample) -> str:
    """The sample's own text, inside the standard provenance delimiters."""
    from hephaestus.core.registry import wrap_reference

    digest = "sha256:" + hashlib.sha256(sample.description.encode("utf-8")).hexdigest()
    return wrap_reference(
        sample.description,
        kind="benchmark-sample",
        name=f"{sample.id}/description.yaml",
        registry="cadgenbench",
        digest=digest,
        lines=f"1-{len(sample.description.splitlines())}",
    )


def _generation_instructions(sample: CadGenSample) -> str:
    images = sample.images
    plural = len(images) > 1
    names = ", ".join(images)
    return (
        f"The drawing{'s' if plural else ''} the sample refers to "
        f"({names}) {'are' if plural else 'is'} registered on this project as "
        f"reference{'s' if plural else ''}: list_references and read_reference "
        f"show {'them' if plural else 'it'}, and "
        f"{'they carry' if plural else 'it carries'} the entire specification — "
        "every dimension, view and callout. Model the part as one sealed solid "
        f"in a part named `{PART_NAME}` and build it. Record the dimensions you "
        "take off the drawing as requirements that cite the drawing itself "
        "(record_requirements with a cite naming the reference), not this message."
    )


def _editing_instructions(sample: CadGenSample) -> str:
    step = sample.step_inputs[0]
    return (
        f"The starting solid is in this project as imports/{step}. Begin the "
        f'part script from `base = import_step("{step}")` rather than '
        "remodelling the part from scratch, apply the change quoted above to "
        f"that imported solid, and build the result as a part named `{PART_NAME}`. "
        "Record what the instruction asks for as a requirement quoting it, and "
        "change nothing the instruction does not ask you to change."
    )


def sample_prompt(sample: CadGenSample) -> str:
    """The converted task's prompt: our framing around the sample, verbatim.

    Pure, and asserted on in the gate: the sample's own sentence must appear
    unmodified, and everything the harness adds must be outside the delimiters.
    """
    framing = _EDITING_FRAMING if sample.is_editing else _GENERATION_FRAMING
    instructions = (
        _editing_instructions(sample) if sample.is_editing else _generation_instructions(sample)
    )
    return f"{framing}\n\n{_quoted(sample)}\n\n{instructions}"


def _write_seed(sample: CadGenSample, seed_dir: Path) -> None:
    """Seed the project tree: manifest, globals, and the sample's own inputs."""
    seed_dir.mkdir(parents=True, exist_ok=True)
    name = task_id_for_sample(sample.id).replace("-", "_")
    (seed_dir / "hephaestus.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    (seed_dir / "globals.py").write_text(
        "# Project-shared namespace (script contract §4).\nPARAMS = {}\n", encoding="utf-8"
    )
    if sample.is_editing:
        # INGEST.md §1: an import is resolved from the file at build time, so
        # copying it in is the whole seeding step.
        target = seed_dir / "imports"
        wanted: Sequence[str] = sample.step_inputs
    else:
        # INGEST.md §2: references become project state only once registered,
        # and registration is operator-side — the bench harness does it at seed
        # time (``harness._seed.seed_references``), never the run.
        target = seed_dir / "references"
        wanted = sample.images
    target.mkdir(parents=True, exist_ok=True)
    for filename in wanted:
        shutil.copy2(sample.input_path(filename), target / filename)


def default_budget(sample: CadGenSample) -> int:
    """The per-split default budget: editing is calibrated separately (§5)."""
    return EDITING_BUDGET_TOOL_CALLS if sample.is_editing else DEFAULT_BUDGET_TOOL_CALLS


def convert_sample(
    sample: CadGenSample,
    dest_root: Path,
    *,
    budget_tool_calls: int | None = None,
) -> BenchTask:
    """Write one converted bench task under ``dest_root`` and load it back.

    Loading it back is deliberate: the task the runner will use is the task that
    was written, parsed by the same strict loader the corpus goes through, so a
    conversion that produced an invalid task fails here rather than mid-run.

    ``budget_tool_calls`` left unset picks the split's own default
    (:func:`default_budget`); an explicit value overrides both splits.
    """
    from hephaestus.bench.harness import BenchTask

    task_id = task_id_for_sample(sample.id)
    directory = dest_root / task_id
    directory.mkdir(parents=True, exist_ok=True)
    _write_seed(sample, directory / "seed")
    budget = default_budget(sample) if budget_tool_calls is None else int(budget_tool_calls)
    spec: dict[str, Any] = {
        "id": task_id,
        "prompt": sample_prompt(sample),
        "budget_tool_calls": budget,
        "required_checks": [],
        # The submission artifact is a build artifact: it comes out of the
        # normal export path, from the graded geometry (EXTERNAL_EVAL.md §2).
        "export_requirements": [{"part": PART_NAME, "format": "step"}],
        # EXTERNAL_EVAL.md §5 (deliverable-scoped grading): the one part this
        # task is graded on. Scratch parts a run probes geometry with are
        # recorded as facts, never fail reasons.
        "deliverable": PART_NAME,
        "notes": f"{_ATTRIBUTION}; sample {sample.id} ({sample.task_type})",
    }
    (directory / "task.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    (directory / SAMPLE_PROVENANCE_FILENAME).write_text(
        json.dumps({**sample.to_json(), "source_dir": str(sample.directory)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return BenchTask.load(directory)


@dataclass(frozen=True)
class ConversionReport:
    """What one conversion pass produced — and what it refused, by name."""

    dest: Path
    tasks: tuple[BenchTask, ...] = ()
    refusals: tuple[SampleError, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.refusals

    def to_json(self) -> dict[str, Any]:
        return {
            "dest": str(self.dest),
            "tasks": [task.id for task in self.tasks],
            "refusals": [error.to_json() for error in self.refusals],
        }


def convert_samples(
    source_root: Path,
    dest_root: Path,
    *,
    ids: Sequence[str] | None = None,
    budget_tool_calls: int | None = None,
) -> ConversionReport:
    """Convert every sample (or the named ones) under a dataset snapshot root.

    A malformed sample is **collected as a named refusal**, never dropped: the
    report carries it, and the CLI exits non-zero because of it. A run over 80
    of 81 samples that never said which one it lost would be reporting on a
    corpus nobody chose (``EXTERNAL_EVAL.md`` §2).
    """
    wanted = tuple(ids) if ids is not None else discover_samples(source_root)
    tasks: list[BenchTask] = []
    refusals: list[SampleError] = []
    for sample_id in wanted:
        try:
            sample = load_sample(source_root / sample_id)
            tasks.append(convert_sample(sample, dest_root, budget_tool_calls=budget_tool_calls))
        except SampleError as exc:
            refusals.append(exc)
    return ConversionReport(dest=dest_root, tasks=tuple(tasks), refusals=tuple(refusals))
