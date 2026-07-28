"""Shared scaffolding for the Gate G8D (external evaluation) evidence suite.

The fixtures are **committed synthetic mini-samples in the real CADGenBench
layout**, authored here — never dataset content. ``EXTERNAL_EVAL.md`` §4 forbids
committing external data, and the gate forbids network access in tests, so the
suite proves the adapter against a corpus it owns:

``dataset/101``  generation, one drawing (``task_type`` absent, as it is on all
                 49 real generation samples).
``dataset/102``  generation with a second drawing (``input2.png``), the shape
                 three real samples have.
``dataset/201``  editing: a starting solid, ``task_type: editing``, and the
                 ``edit_description.txt`` duplicate the real samples carry.
``dataset/301``  malformed: ``input_files`` names a file that is not there.
``dataset/302``  malformed: an unknown ``task_type``.

``steps/`` holds candidate STEPs for the packaging and floor clauses: a sealed
plate, a sealed edited plate, an unsealed lone face, and a file that is not
STEP at all.
"""

from __future__ import annotations

import shutil
from pathlib import Path

__all__ = [
    "DATASET",
    "EDIT_INSTRUCTION",
    "FIXTURES",
    "GENERATION_DESCRIPTION",
    "STEPS",
    "outputs_with",
]

FIXTURES = Path(__file__).parent / "fixtures"
DATASET = FIXTURES / "dataset"
STEPS = FIXTURES / "steps"

#: The sample text, byte-exact, as the fixtures declare it. Conversion must
#: carry these through untouched — that is the whole honesty claim of §2.
GENERATION_DESCRIPTION = "Reproduce the geometry as accurately as possible from the drawing."
EDIT_INSTRUCTION = "Bring the two long walls of the plate inward by 2mm."


def outputs_with(root: Path, candidates: dict[str, Path | None]) -> Path:
    """Build a submission outputs tree: ``{sample_id: candidate or None}``.

    ``None`` makes the folder and leaves it empty — the legal "did not solve
    this one" submission, which must survive packaging as a scored zero rather
    than as a missing sample.
    """
    root.mkdir(parents=True, exist_ok=True)
    for sample_id, source in candidates.items():
        directory = root / sample_id
        directory.mkdir(parents=True, exist_ok=True)
        if source is not None:
            shutil.copy2(source, directory / "output.step")
    return root
