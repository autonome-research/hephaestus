"""The archive layout and the records written into it.

Every run leaves a directory under ``bench/results/<model>/<date>/<task>-s<seed>/``
holding the prompt, the normalized event JSONL, the grade and the run record.
:class:`RunRecord` is the unit :mod:`hephaestus.bench.scoring` aggregates; it
points at the run's Pi transcript inside the archived project rather than copying
it, because the project is what CI uploads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hephaestus.agent_bridge.app import repo_root

__all__ = [
    "ARCHIVE_EVENTS_FILENAME",
    "ARCHIVE_RESULT_FILENAME",
    "BENCH_RESULTS_DIRNAME",
    "BenchRun",
    "RunRecord",
    "results_root",
    "session_transcript_dir",
    "today",
]

#: Results/archive root relative to the repository root (``bench/results``).
BENCH_RESULTS_DIRNAME = "bench"

ARCHIVE_EVENTS_FILENAME = "events.jsonl"
ARCHIVE_RESULT_FILENAME = "result.json"


def results_root(root: Path | None = None) -> Path:
    """``bench/results`` — the archive + leaderboard artifact root."""
    return (root or repo_root()) / BENCH_RESULTS_DIRNAME / "results"


def session_transcript_dir(project_root: Path, session_id: str) -> Path:
    """Where a run's Pi session transcript lives (``.heph/sessions/<id>``).

    The archived run record points at it rather than copying it: the transcript
    is inside the archived project, which is what CI uploads as the run artifact.
    """
    return project_root / ".heph" / "sessions" / session_id


def today() -> str:
    """Today's UTC date, the ``<date>`` component of an archive path."""
    return datetime.now(UTC).date().isoformat()


@dataclass(frozen=True)
class RunRecord:
    """One archived (task, seed) run — the unit :mod:`..scoring` aggregates."""

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
    #: ``VALIDATION.md`` §1 corpus split (``prose``/``seeded``). Scoring never
    #: averages the two, so every record states which one it belongs to rather
    #: than leaving it to be inferred from the task id.
    #: Harness-compelled ladder calls, counted but never charged against the
    #: budget (see ``COMPELLED_TOOLS``): the exemption stays visible per run.
    compelled_tool_calls: int = 0
    #: Calls spent when the budget was first exceeded — ``None`` when the run
    #: stayed inside it. Recorded because cancelling AT the budget censors the
    #: number: "needed one more" and "needed triple" both look like budget+1.
    budget_exceeded_at: int | None = None
    #: The run was stopped by the observe ceiling rather than finishing.
    hit_observe_ceiling: bool = False
    spec: str = "prose"
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
    #: The task's protected paths — the denominator of §8's spec-tampering rate
    #: (a run with nothing protected cannot tamper, and must not dilute the rate).
    protected_paths: tuple[str, ...] = ()
    #: The run's final requirement ledger, each entry annotated with the §3
    #: material class the harness assigned it (``VALIDATION.md`` §2/§8).
    requirements: tuple[Mapping[str, Any], ...] = ()
    #: ``LadderOutcome.to_json()`` when the §5/§6 review ladder ran for this run.
    review: Mapping[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "spec": self.spec,
            "seed": self.seed,
            "model": self.model,
            "date": self.date,
            "passed": self.passed,
            "status": self.status,
            "tool_calls": self.tool_calls,
            "budget_tool_calls": self.budget_tool_calls,
            "compelled_tool_calls": self.compelled_tool_calls,
            "budget_exceeded_at": self.budget_exceeded_at,
            "hit_observe_ceiling": self.hit_observe_ceiling,
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
            "protected_paths": list(self.protected_paths),
            "requirements": [dict(entry) for entry in self.requirements],
            "review": None if self.review is None else dict(self.review),
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
