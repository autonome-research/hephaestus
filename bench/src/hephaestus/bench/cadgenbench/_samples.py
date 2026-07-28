# pyright: reportMissingTypeStubs=false
"""One CADGenBench sample folder, read strictly (``EXTERNAL_EVAL.md`` §2).

The dataset is somebody else's, so this module is written against what the
dataset really contains (``bench/CADGENBENCH_FACTS.md``, recon 2026-07-28) and
not against a documentation summary:

- ``description.yaml`` has exactly four keys and ``task_type`` is **absent on
  every generation sample** — it defaults to ``"generation"`` rather than
  raising, which is what the benchmark's own readers do;
- ``description`` is authored as a YAML folded block, so it arrives with a
  trailing newline that must be stripped before it is quoted anywhere;
- sample ids are non-contiguous (``144`` does not exist, and the 2xx range skips
  fourteen ids), so they are always *enumerated*, never generated;
- the input files are named by ``input_files``, not by convention: three
  generation samples ship a second drawing.

Every way a sample can be wrong raises :class:`SampleError`, which carries a
machine-readable ``reason``. ``EXTERNAL_EVAL.md`` §2 requires a malformed sample
to be refused **by name** — a benchmark adapter that silently drops the samples
it could not parse reports a score over a corpus nobody chose.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

__all__ = [
    "DESCRIPTION_FILENAME",
    "EDITING",
    "EDIT_DESCRIPTION_FILENAME",
    "GENERATION",
    "IMAGE_SUFFIXES",
    "SAMPLE_MARKERS",
    "STEP_SUFFIXES",
    "TASK_TYPES",
    "CadGenSample",
    "SampleError",
    "discover_samples",
    "load_sample",
]

#: The per-sample spec file. Four keys: description, task_type, input_files,
#: input_type (``CADGENBENCH_FACTS.md`` — "description.yaml schema").
DESCRIPTION_FILENAME = "description.yaml"

#: The editing instruction, duplicated verbatim from ``description``. Read for
#: cross-checking only: ``description.yaml`` is the source of truth.
EDIT_DESCRIPTION_FILENAME = "edit_description.txt"

GENERATION = "generation"
EDITING = "editing"
TASK_TYPES: tuple[str, ...] = (GENERATION, EDITING)

#: Suffixes the reference registry accepts as ``kind="image"`` (INGEST.md §2).
IMAGE_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg")
STEP_SUFFIXES: tuple[str, ...] = (".step", ".stp")

#: A directory carrying any of these *is* a sample and must therefore load. A
#: directory carrying none of them (``.git``, a stray cache) is not a sample and
#: is not a refusal either — the distinction is what keeps "malformed" and
#: "not a sample" from collapsing into one silent skip.
SAMPLE_MARKERS: tuple[str, ...] = (
    DESCRIPTION_FILENAME,
    EDIT_DESCRIPTION_FILENAME,
    "input.png",
    "input.step",
)

#: An ``input_files`` entry names a file *inside* the sample folder: no
#: separators, no traversal, no leading dot.
_INPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SampleError(ValueError):
    """A CADGenBench sample this adapter refuses to convert, named.

    ``reason`` is the machine-readable code (``missing_description``,
    ``unknown_task_type``, …); ``detail`` is the human half. Both travel into
    the conversion report, so a refused sample is visible in the artifact rather
    than only in a log line.
    """

    def __init__(self, sample_id: str, reason: str, detail: str = "") -> None:
        self.sample_id = sample_id
        self.reason = reason
        self.detail = detail
        suffix = f": {detail}" if detail else ""
        super().__init__(f"cadgenbench sample {sample_id!r}: {reason}{suffix}")

    def to_json(self) -> dict[str, Any]:
        return {"sample_id": self.sample_id, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class CadGenSample:
    """One validated sample folder: the spec, verbatim, plus its input files."""

    id: str
    directory: Path
    #: ``description`` with the folded block's trailing newline stripped.
    description: str
    task_type: str
    input_files: tuple[str, ...]
    input_type: str

    @property
    def is_editing(self) -> bool:
        return self.task_type == EDITING

    @property
    def images(self) -> tuple[str, ...]:
        """Drawing inputs, in ``input_files`` order (a sample may ship two)."""
        return tuple(n for n in self.input_files if Path(n).suffix.lower() in IMAGE_SUFFIXES)

    @property
    def step_inputs(self) -> tuple[str, ...]:
        return tuple(n for n in self.input_files if Path(n).suffix.lower() in STEP_SUFFIXES)

    def input_path(self, name: str) -> Path:
        return self.directory / name

    def to_json(self) -> dict[str, Any]:
        return {
            "sample_id": self.id,
            "task_type": self.task_type,
            "input_type": self.input_type,
            "input_files": list(self.input_files),
            "description": self.description,
        }


def _load_yaml(path: Path, sample_id: str) -> dict[str, Any]:
    import yaml

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SampleError(sample_id, "unreadable_description", str(exc)) from exc
    except yaml.YAMLError as exc:
        raise SampleError(sample_id, "malformed_description", str(exc)) from exc
    if not isinstance(raw, dict):
        raise SampleError(
            sample_id, "malformed_description", f"{DESCRIPTION_FILENAME} is not a mapping"
        )
    return cast("dict[str, Any]", raw)


def _input_files(data: dict[str, Any], sample: str, directory: Path) -> tuple[str, ...]:
    raw = data.get("input_files")
    if not isinstance(raw, list) or not raw:
        raise SampleError(sample, "missing_input_files", "input_files must be a non-empty list")
    names: list[str] = []
    for item in cast("Sequence[Any]", raw):
        if not isinstance(item, str) or not _INPUT_NAME_RE.match(item):
            raise SampleError(sample, "unsafe_input_file", repr(item))
        if not (directory / item).is_file():
            raise SampleError(sample, "missing_input_file", item)
        names.append(item)
    return tuple(names)


def load_sample(directory: Path) -> CadGenSample:
    """Read and validate one sample folder, or refuse it by name.

    Pure with respect to the dataset: nothing is written, nothing is fetched,
    and the only thing read is the sample folder itself.
    """
    sample_id = directory.name
    if not directory.is_dir():
        raise SampleError(sample_id, "missing_sample_directory", str(directory))
    spec_path = directory / DESCRIPTION_FILENAME
    if not spec_path.is_file():
        raise SampleError(sample_id, "missing_description", DESCRIPTION_FILENAME)
    data = _load_yaml(spec_path, sample_id)

    raw_description = data.get("description")
    if not isinstance(raw_description, str) or not raw_description.strip():
        raise SampleError(sample_id, "empty_description", "description must be a non-empty string")
    # The folded block (`description: >`) always arrives with a trailing
    # newline; the text is quoted verbatim downstream, so it is stripped once,
    # here, rather than by each consumer.
    description = raw_description.strip()

    # Absent on all 49 generation samples: defaulting is the documented reader
    # behaviour, not a leniency of ours.
    task_type = str(data.get("task_type") or GENERATION)
    if task_type not in TASK_TYPES:
        raise SampleError(sample_id, "unknown_task_type", task_type)

    input_files = _input_files(data, sample_id, directory)
    input_type = str(data.get("input_type") or "")

    sample = CadGenSample(
        id=sample_id,
        directory=directory,
        description=description,
        task_type=task_type,
        input_files=input_files,
        input_type=input_type,
    )
    if task_type == GENERATION and not sample.images:
        raise SampleError(sample_id, "no_drawing_input", ", ".join(input_files))
    if task_type == EDITING:
        steps = sample.step_inputs
        if not steps:
            raise SampleError(sample_id, "no_step_input", ", ".join(input_files))
        if len(steps) > 1:
            raise SampleError(sample_id, "ambiguous_step_input", ", ".join(steps))
    return sample


def _sort_key(name: str) -> tuple[int, int, str]:
    """Numeric ids sort numerically; anything else sorts after them, lexically."""
    return (0, int(name), "") if name.isdigit() else (1, 0, name)


def discover_samples(root: Path) -> tuple[str, ...]:
    """Sample ids under a dataset snapshot root, in stable order.

    Enumerated, never generated: the id set has holes (``144``, and fourteen of
    the 2xx ids), so any ``range()`` over it is wrong by construction.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"cadgenbench dataset root {root} does not exist")
    ids = [
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and any((entry / marker).exists() for marker in SAMPLE_MARKERS)
    ]
    return tuple(sorted(ids, key=_sort_key))
