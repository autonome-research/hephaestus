"""CADGenBench adapter (``EXTERNAL_EVAL.md`` §2) — an adapter, not capability.

The premise of the stage: a corpus we did not author cannot fall into the
reproduction trap the 2026-07-26 audit closed, so the external benchmark is the
honest gate — and Stages 8A/8B exist precisely so that meeting it requires no
new engine capability. Generation samples ride ``INGEST.md`` §2 references,
editing samples ride §1 ``imports/``, scoring rides ``COMPARE.md`` §3.

**Boundary.** This package lives entirely in ``bench``; nothing in the engine
imports it, and it imports ``hephaestus.geom`` and the rest of ``bench`` freely.
That direction is asserted by the gate suite: the adapter is allowed to know
about the engine, the engine is never allowed to know about a benchmark.

Five steps, one per verb:

``fetch``    the public dataset into a cache **outside** the repository, with
             the revision recorded — no external data is ever committed.
``convert``  one sample folder -> one bench task, a pure function; the sample's
             text is quoted verbatim inside provenance delimiters, and a
             malformed sample is refused by name rather than skipped.
``run``      converted tasks through the standard session harness (budgets,
             observe mode, ``--parallel``, ``--samples``), the part exported to
             STEP through the normal export path.
``package``  the submission ZIP the leaderboard really accepts, then the
             benchmark's own ``sanity_check_submission.py`` over every
             candidate; any failure means no ZIP.
``score``    the local floor — validity plus ``score_step_files`` facts where
             the public dataset ships reference geometry — labelled, literally,
             "local floor". The leaderboard's number cannot be computed here and
             is never claimed.
"""

from __future__ import annotations

from ._convert import (
    DEFAULT_BUDGET_TOOL_CALLS,
    EDITING_BUDGET_TOOL_CALLS,
    PART_NAME,
    SAMPLE_PROVENANCE_FILENAME,
    TASK_ID_PREFIX,
    ConversionReport,
    convert_sample,
    convert_samples,
    default_budget,
    sample_id_for_task,
    sample_prompt,
    task_id_for_sample,
)
from ._fetch import (
    ATTRIBUTION,
    CACHE_ENV_VAR,
    DATASET_REPO_ID,
    FETCH_RECORD_FILENAME,
    SANITY_CHECK_FILENAME,
    FetchRecord,
    default_cache_dir,
    fetch_dataset,
    read_fetch_record,
    resolve_dataset_root,
)
from ._package import (
    CANDIDATE_NAMES,
    META_FILENAME,
    NOTES_MAX_CHARS,
    REQUIRED_META_KEYS,
    SUBMISSION_CANDIDATE,
    PackageReport,
    PackagingError,
    SubmissionMeta,
    package_submission,
    resolve_sanity_check,
    run_sanity_check,
)
from ._run import RunOutcome, collect_outputs, exported_step_path, run_converted
from ._salvage import (
    SALVAGE_REPORT_FILENAME,
    SalvageEntry,
    SalvageReport,
    salvage_from_archive,
)
from ._samples import (
    DESCRIPTION_FILENAME,
    EDITING,
    GENERATION,
    TASK_TYPES,
    CadGenSample,
    SampleError,
    discover_samples,
    load_sample,
)
from ._score import LOCAL_FLOOR_LABEL, SampleFloor, SubmissionFloor, score_outputs
from ._validity import ValidityFacts, step_validity

__all__ = [
    "ATTRIBUTION",
    "CACHE_ENV_VAR",
    "CANDIDATE_NAMES",
    "DATASET_REPO_ID",
    "DEFAULT_BUDGET_TOOL_CALLS",
    "DESCRIPTION_FILENAME",
    "EDITING",
    "EDITING_BUDGET_TOOL_CALLS",
    "FETCH_RECORD_FILENAME",
    "GENERATION",
    "LOCAL_FLOOR_LABEL",
    "META_FILENAME",
    "NOTES_MAX_CHARS",
    "PART_NAME",
    "REQUIRED_META_KEYS",
    "SALVAGE_REPORT_FILENAME",
    "SAMPLE_PROVENANCE_FILENAME",
    "SANITY_CHECK_FILENAME",
    "SUBMISSION_CANDIDATE",
    "TASK_ID_PREFIX",
    "TASK_TYPES",
    "CadGenSample",
    "ConversionReport",
    "FetchRecord",
    "PackageReport",
    "PackagingError",
    "RunOutcome",
    "SalvageEntry",
    "SalvageReport",
    "SampleError",
    "SampleFloor",
    "SubmissionFloor",
    "SubmissionMeta",
    "ValidityFacts",
    "collect_outputs",
    "convert_sample",
    "convert_samples",
    "default_budget",
    "default_cache_dir",
    "discover_samples",
    "exported_step_path",
    "fetch_dataset",
    "load_sample",
    "package_submission",
    "read_fetch_record",
    "resolve_dataset_root",
    "resolve_sanity_check",
    "run_converted",
    "run_sanity_check",
    "salvage_from_archive",
    "sample_id_for_task",
    "sample_prompt",
    "score_outputs",
    "step_validity",
    "task_id_for_sample",
]
