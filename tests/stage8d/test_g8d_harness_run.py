# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8D addendum (``EXTERNAL_EVAL.md`` §5): the harness fixes, through real runs.

The 2026-07-29 sweep's autopsy said the harness — not the models — lost the
editing split: 13 of 14 failed editing runs had built a correct-status
candidate, and five of six infrastructure deaths ended on an unanswered
``compare_solids``. The unit halves of the fixes are proven next to the code
they live in (``test_g8d_audit_fixes.py``, ``server/tests``); what this module
proves is the §5 gate addendum *end to end* — each fix observed on a real
:func:`hephaestus.bench.harness.run_task` run against the packaged Node sidecar
and a scripted fake model:

* a broken scratch part beside an ok deliverable is a recorded fact, and the
  run PASSES;
* a ``compare_timeout`` harness fault is visible — and uncharged — in the run
  record the archive keeps;
* a forced supervisor restart leaves its evidence (``restarts.json`` /
  ``sidecar.log``) beside the run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g8d import DATASET
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.bench import harness
from hephaestus.bench.cadgenbench import PART_NAME, convert_samples
from hephaestus.bench.harness import (
    ARCHIVE_RESTARTS_FILENAME,
    ARCHIVE_SIDECAR_LOG_FILENAME,
    BenchTask,
    ProviderConfig,
)
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai
from test_g8d_run import (
    EDITING_SRC,
    GENERATION_SRC,
    PROMPT_TIMEOUT,
    last_tool_result,
    tool_call,
)

SCRATCH_SRC = '# A probe the model used and abandoned.\nraise RuntimeError("scratch probe")\n'

#: The VALIDATION.md §2 ledger seed each script opens with — an empty ledger
#: refuses ``build_part`` by rule, and ``record_requirements`` is a compelled
#: (never charged) tool, so the charged counts below stay exact.
GENERATION_RECORD: dict[str, Any] = {
    "entries": [
        {
            "id": "R1",
            "text": "the plate is 20 x 10 x 4 mm",
            "source": "specified",
            "cite": {"reference": "input.png", "quote": "20 x 10 x 4"},
        }
    ]
}
EDITING_RECORD: dict[str, Any] = {
    "entries": [
        {
            "id": "R1",
            "text": "the two long walls move inward by 2 mm",
            "source": "specified",
            "quote": "Bring the two long walls of the plate inward by 2mm.",
            "value": 2.0,
            "unit": "mm",
        }
    ]
}


@pytest.fixture
def fake_model() -> Iterator[FakeOpenAI]:
    fake = start_fake_openai([])
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def provider(fake_model: FakeOpenAI) -> ProviderConfig:
    return ProviderConfig(providers=(fake_model.provider_spec(),), model_id=fake_model.model_id)


@pytest.fixture
def runtime_factory(sidecar_dist: Path) -> harness.RuntimeFactory:
    def factory(project_root: Path, config: ProviderConfig) -> BridgeRuntime:
        return BridgeRuntime(
            project_root=project_root, providers=config.providers, dist_main=sidecar_dist
        )

    return factory


@pytest.fixture
def converted(tmp_path: Path) -> dict[str, BenchTask]:
    report = convert_samples(DATASET, tmp_path / "tasks", ids=["101", "201"])
    assert report.ok, [error.to_json() for error in report.refusals]
    return {task.id: task for task in report.tasks}


def _run(
    task: BenchTask,
    *,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
    archive: Path,
) -> harness.RunRecord:
    record = harness.run_task(
        task,
        1,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-08-02",
    )
    assert record.error is None, record.error
    return record


def _grade(record: harness.RunRecord) -> dict[str, Any]:
    assert record.grade is not None
    return dict(record.grade)


def _candidate_steps(source: str) -> list[Any]:
    """The shared tail: create the deliverable, write it, build it."""

    def create(info: RequestInfo) -> dict[str, Any]:
        _ = info
        return tool_call("create_part", {"name": PART_NAME, "template": "blank"}, "d1")

    def write(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": PART_NAME, "expected_hash": created["content_hash"], "script": source},
            "d2",
        )

    def build(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("applied") is True
        return tool_call("build_part", {"name": PART_NAME}, "d3")

    return [create, write, build]


# ==========================================================================
# deliverable-scoped grading, through a real run


def test_a_broken_scratch_part_beside_an_ok_candidate_passes_the_run(
    tmp_path: Path,
    converted: dict[str, BenchTask],
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    """§5 gate clause, end to end: the model probes geometry with a scratch
    part whose build FAILS, then authors and builds the deliverable. The run
    passes on the deliverable's build/export alone; the scratch failure is
    archived as a fact under ``other_build_failures``, never a fail reason."""

    def probe_write(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": "scratch", "expected_hash": created["content_hash"], "script": SCRATCH_SRC},
            "s2",
        )

    def probe_build(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("applied") is True
        return tool_call("build_part", {"name": "scratch"}, "s3")

    def after_probe(info: RequestInfo) -> dict[str, Any]:
        # The probe's failure is the model's signal, not a session death.
        assert last_tool_result(info).get("status") == "error"
        return tool_call("create_part", {"name": PART_NAME, "template": "blank"}, "d1")

    create_tail = _candidate_steps(GENERATION_SRC)

    def finish(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("status") == "ok"
        return {"kind": "text", "chunks": ["probed with scratch, then built the candidate"]}

    fake_model.set_script(
        [
            tool_call("record_requirements", GENERATION_RECORD, "r1"),
            lambda _info: tool_call("create_part", {"name": "scratch", "template": "blank"}, "s1"),
            probe_write,
            probe_build,
            after_probe,
            *create_tail[1:],  # write + build of the deliverable
            finish,
        ]
    )

    record = _run(
        converted["cadgenbench-101"],
        provider=provider,
        runtime_factory=runtime_factory,
        archive=tmp_path / "archive",
    )

    assert record.passed, record.reasons
    grade = _grade(record)
    assert grade["other_build_failures"] == ["build_failed:scratch"]
    assert not any("scratch" in reason for reason in record.reasons)
    # The deliverable's export came out of the graded geometry.
    export = cast("dict[str, Any]", cast("list[Any]", grade["exports"])[0])
    assert "invalid" not in export and "error" not in export


# ==========================================================================
# a harness fault is visible — and uncharged — in the run record


def test_a_compare_timeout_is_an_uncharged_call_in_the_run_record(
    tmp_path: Path,
    converted: dict[str, BenchTask],
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5 gate clause, end to end: the model's ``compare_solids`` hits the
    bounded-diff ceiling (COMPARE.md §5) mid-run. The refusal reaches the model
    as a result — not a dead session — and the call is refunded: the run record
    names it under ``uncharged_calls`` and the charged count excludes it."""
    import hephaestus.core.project_compare as project_compare
    from _g8d_grind import grinding_child

    monkeypatch.setattr(project_compare, "_diff_child", grinding_child)
    monkeypatch.setenv(project_compare.COMPARE_TIMEOUT_ENV, "3.0")

    def compare(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("status") == "ok"
        return tool_call("compare_solids", {"part": PART_NAME, "target": "import:input.step"}, "d4")

    def finish(info: RequestInfo) -> dict[str, Any]:
        _ = info  # the compare came back as an error result; the model moves on
        return {"kind": "text", "chunks": ["compare timed out; the build stands"]}

    fake_model.set_script(
        [
            tool_call("record_requirements", EDITING_RECORD, "r1"),
            *_candidate_steps(EDITING_SRC),
            compare,
            finish,
        ]
    )

    record = _run(
        converted["cadgenbench-201"],
        provider=provider,
        runtime_factory=runtime_factory,
        archive=tmp_path / "archive",
    )

    assert record.passed, record.reasons
    # create + write + build are charged; the timed-out compare is not.
    assert record.tool_calls == 3
    assert record.uncharged_tool_calls == 1
    (uncharged,) = record.uncharged_calls
    assert uncharged["name"] == "compare_solids"
    assert uncharged["fault"] == "compare_timeout"
    assert record.budget_exceeded_at is None
    # …and the archived record carries the same split for the audit.
    archived = cast(
        "dict[str, Any]",
        json.loads((Path(record.archive_dir) / "result.json").read_text(encoding="utf-8")),
    )
    assert archived["uncharged_tool_calls"] == 1
    assert cast("list[Any]", archived["uncharged_calls"])[0] == dict(uncharged)


# ==========================================================================
# a forced supervisor restart leaves its evidence in the archive


class _RestartOnceRuntime(BridgeRuntime):
    """A real runtime whose sidecar is forcibly restarted once, at startup.

    The restart is the supervisor's own (kill + respawn + replayed
    ``runtime.configure``); only the trigger is scripted, so what the test
    observes is the real evidence path: supervisor -> ``sidecar_evidence()``
    after ``close()`` -> the run's archive.
    """

    def start(self) -> None:
        super().start()
        self.restart()


def test_a_forced_restart_is_archived_with_its_reason_beside_the_run(
    tmp_path: Path,
    converted: dict[str, BenchTask],
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    sidecar_dist: Path,
) -> None:
    """§5 gate clause, end to end: after a forced supervisor restart the run's
    archive carries ``restarts.json`` (every restart with its reason, plus the
    spawn accounting) and the bounded ``sidecar.log`` tail — the sweep's
    restarts were diagnosable only by inference from event-stream shape."""

    def factory(project_root: Path, config: ProviderConfig) -> BridgeRuntime:
        return _RestartOnceRuntime(
            project_root=project_root, providers=config.providers, dist_main=sidecar_dist
        )

    def finish(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("status") == "ok"
        return {"kind": "text", "chunks": ["built the part the sample asks for"]}

    fake_model.set_script(
        [
            tool_call("record_requirements", GENERATION_RECORD, "r1"),
            *_candidate_steps(GENERATION_SRC),
            finish,
        ]
    )

    record = _run(
        converted["cadgenbench-101"],
        provider=provider,
        runtime_factory=factory,
        archive=tmp_path / "archive",
    )

    # The respawned sidecar was re-configured and served the whole run.
    assert record.passed, record.reasons
    run_dir = Path(record.archive_dir)
    restarts = cast(
        "dict[str, Any]",
        json.loads((run_dir / ARCHIVE_RESTARTS_FILENAME).read_text(encoding="utf-8")),
    )
    (event,) = cast("list[Any]", restarts["restarts"])
    entry = cast("dict[str, Any]", event)
    assert entry["reason"] == "manual"
    assert entry["restart_generation"] == 1
    assert isinstance(entry["at"], str) and entry["at"]
    assert restarts["spawn_count"] == 2
    assert restarts["auto_respawns"] == 0
    assert restarts["spawn_errors"] == []
    assert (run_dir / ARCHIVE_SIDECAR_LOG_FILENAME).is_file()
