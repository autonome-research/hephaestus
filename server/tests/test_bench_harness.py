"""The bench loop end to end: scripted model -> real sidecar -> grading -> archive.

These tests run :func:`hephaestus.bench.harness.run_task` exactly as
``heph bench run`` does — a fresh project seeded from the corpus task, a real
:class:`~hephaestus.agent_bridge.app.BridgeRuntime` orchestrator session against
the *packaged* Node sidecar, and a scripted OpenAI-compatible fake model
(:mod:`hephaestus.testing.fake_openai`) standing in for the provider. The model earns its pass by
calling real tools: ``create_part``/``write_part``/``build_part`` for
``bracket-101``, ``read_part``/``edit_part``/``build_part`` for the broken
``repair-fillet`` fixture.

What that proves, on top of the reference-solution meta-test:

* the loop counts ``tool_call`` events against the task budget, and cancels the
  run when the budget is spent (the budget-exceeded run cannot pass);
* grading installs the task's required CHECKS over whatever the run authored and
  runs them project-scoped;
* the required exports are produced from the graded geometry and validated;
* every run is archived: normalized events JSONL, the prompt, the grade and the
  run record, under ``bench/results/<model>/<date>/<task>-s<seed>/``.

The workstation model endpoint is never called: the only provider is the local
fake server.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, repo_root
from hephaestus.bench import harness, metrics
from hephaestus.bench.harness import (
    ARCHIVE_EVENTS_FILENAME,
    ARCHIVE_RESULT_FILENAME,
    BENCH_ANSWER,
    BenchTask,
    ProviderConfig,
    RunRecord,
    bench_answerer,
    load_tasks,
    validate_export_bytes,
)
from hephaestus.bench.scoring import RUNS_FILENAME, score_directory
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai

SOLUTIONS = repo_root() / "corpus" / "solutions"

#: Keep the scripted runs snappy; a scripted turn never needs the 1800 s default.
PROMPT_TIMEOUT = 300.0


# --------------------------------------------------------------------------
# provider configuration (pure: no sidecar, no model)


def test_provider_config_load_selects_and_reorders(tmp_path: Path) -> None:
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "a",
                        "kind": "openai_compatible",
                        "baseUrl": "http://127.0.0.1:1/v1",
                        "models": [{"id": "small"}, {"id": "big"}],
                    },
                    {
                        "id": "b",
                        "kind": "anthropic",
                        "models": [{"id": "other"}],
                    },
                ],
                "credentials": {"FAKE_KEY": "secret"},
            }
        ),
        encoding="utf-8",
    )
    default = ProviderConfig.load(path)
    assert default.model_id == "small"

    chosen = ProviderConfig.load(path, model="other")
    # The requested model's provider is moved first, and its model first inside it:
    # the sidecar resolves the first model of the first provider.
    assert chosen.model_id == "other"
    assert chosen.providers[0]["id"] == "b"
    assert chosen.credential_allowlist == ("FAKE_KEY",)
    assert chosen.credentials["FAKE_KEY"] == "secret"

    big = ProviderConfig.load(path, model="big")
    assert [m["id"] for m in cast("list[Any]", big.providers[0]["models"])] == ["big", "small"]

    with pytest.raises(ValueError, match="not declared"):
        ProviderConfig.load(path, model="nope")


def test_provider_config_model_slug_is_filesystem_safe() -> None:
    config = ProviderConfig(providers=({"id": "x"},), model_id="vendor/model:2026-07")
    assert config.model_slug == "vendor-model-2026-07"


def test_bench_answerer_never_hangs_a_run_and_never_disambiguates() -> None:
    """``VALIDATION.md`` §7: the same non-committal sentence, whatever is asked.

    It still cannot hang a run (an answer always comes back), but it no longer
    picks an option: answering helpfully would do the disambiguation production
    ``ask_user`` exists to obtain, which deletes the mechanism under test. The
    ledger consequence (``asked`` recorded, entry left ``assumed``) is asserted in
    ``test_bench_validation_metrics``.
    """
    assert bench_answerer({"options": ["yes", "no"]}) == BENCH_ANSWER
    assert bench_answerer({"options": []}) == BENCH_ANSWER
    assert bench_answerer({}) == BENCH_ANSWER


def test_validate_export_bytes_rejects_malformed_payloads() -> None:
    assert validate_export_bytes("step", b"ISO-10303-21;\nHEADER;") is None
    assert validate_export_bytes("step", b"not a step file") == "step_missing_iso10303_header"
    assert validate_export_bytes("3mf", b"PK-nope") == "3mf_not_a_zip"
    assert validate_export_bytes("dxf", b"") == "empty_export"


# --------------------------------------------------------------------------
# the scripted end-to-end loop


def _node_available() -> bool:
    return bool(os.environ.get("HEPHAESTUS_NODE") or shutil.which("node"))


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    """Build the real sidecar once per session; skip cleanly when Node is absent."""
    if not _node_available():
        pytest.skip("node is not available; the bench loop needs the packaged sidecar")
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        pytest.skip("pnpm is not available; cannot build the sidecar")
    agent_dir = repo_root() / "agent"
    build = subprocess.run(
        [pnpm, "--dir", str(agent_dir), "build"], capture_output=True, text=True, check=False
    )
    dist_main = agent_dir / "dist" / "main.js"
    if build.returncode != 0 or not dist_main.exists():
        pytest.fail(f"sidecar build failed:\n{build.stdout}\n{build.stderr}")
    return dist_main


@pytest.fixture
def fake_model() -> Iterator[FakeOpenAI]:
    fake = start_fake_openai([])
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def provider(fake_model: FakeOpenAI) -> ProviderConfig:
    return ProviderConfig(
        providers=(fake_model.provider_spec(),),
        model_id=fake_model.model_id,
    )


@pytest.fixture
def runtime_factory(sidecar_dist: Path) -> harness.RuntimeFactory:
    def factory(project_root: Path, config: ProviderConfig) -> BridgeRuntime:
        return BridgeRuntime(
            project_root=project_root,
            providers=config.providers,
            dist_main=sidecar_dist,
        )

    return factory


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"kind": "tool_calls", "calls": [{"name": name, "arguments": arguments, "id": call_id}]}


def last_tool_result(info: RequestInfo) -> dict[str, Any]:
    """The JSON body of the most recent tool result in the request transcript."""
    body = cast("dict[str, Any]", json.loads(info.body_text))
    for message in reversed(cast("list[Any]", body.get("messages", []))):
        if not isinstance(message, dict):
            continue
        entry = cast("dict[str, Any]", message)
        if entry.get("role") != "tool":
            continue
        content = entry.get("content")
        raw = content if isinstance(content, str) else json.dumps(content)
        try:
            parsed, _end = json.JSONDecoder().raw_decode(raw.lstrip())
        except json.JSONDecodeError:
            return {}
        return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}
    return {}


def solution_script(task_id: str, part: str) -> str:
    return (SOLUTIONS / task_id / "parts" / f"{part}.py").read_text(encoding="utf-8")


def bracket_script(fake: FakeOpenAI) -> None:
    """Script the model through create -> write -> build for ``bracket-101``."""
    script = solution_script("bracket-101", "bracket")

    def write(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": "bracket", "expected_hash": created["content_hash"], "script": script},
            "c1",
        )

    def build(info: RequestInfo) -> dict[str, Any]:
        written = last_tool_result(info)
        assert written.get("applied") is True, written
        return tool_call("build_part", {"name": "bracket"}, "c2")

    def finish(info: RequestInfo) -> dict[str, Any]:
        built = last_tool_result(info)
        assert built.get("status") == "ok", built
        return {"kind": "text", "chunks": ["bracket built: 60 x 40 x 40, two 6 mm holes"]}

    fake.set_script(
        [
            tool_call("create_part", {"name": "bracket", "template": "blank"}, "c0"),
            write,
            build,
            finish,
        ]
    )


def repair_script(fake: FakeOpenAI) -> None:
    """Script the model through read -> edit -> build for ``repair-fillet``."""

    def edit(info: RequestInfo) -> dict[str, Any]:
        read = last_tool_result(info)
        assert "radius=40.0" in str(read.get("script", "")), read
        return tool_call(
            "edit_part",
            {
                "name": "plate",
                "expected_hash": read["content_hash"],
                "old_str": "radius=40.0",
                "new_str": "radius=5.0",
            },
            "c1",
        )

    def build(info: RequestInfo) -> dict[str, Any]:
        edited = last_tool_result(info)
        assert edited.get("applied") is True, edited
        return tool_call("build_part", {"name": "plate"}, "c2")

    def finish(info: RequestInfo) -> dict[str, Any]:
        built = last_tool_result(info)
        assert built.get("status") == "ok", built
        return {"kind": "text", "chunks": ["blend radius reduced to 5 mm; the plate builds"]}

    fake.set_script([tool_call("read_part", {"name": "plate"}, "c0"), edit, build, finish])


def assert_archived(run_dir: Path, record: RunRecord) -> list[dict[str, Any]]:
    """Every per-run artifact the bench promises is on disk and well formed."""
    assert run_dir.is_dir()
    assert (run_dir / "prompt.txt").read_text(encoding="utf-8").strip() == record.prompt
    events = [
        cast("dict[str, Any]", json.loads(line))
        for line in (run_dir / ARCHIVE_EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events, "the run archived no normalized events"
    assert len(events) == record.event_count
    for event in events:
        assert event["run_id"]
        assert event["kind"]
    grade = cast("dict[str, Any]", json.loads((run_dir / "grade.json").read_text(encoding="utf-8")))
    assert grade["task_id"] == record.task_id
    result_text = (run_dir / ARCHIVE_RESULT_FILENAME).read_text(encoding="utf-8")
    result = cast("dict[str, Any]", json.loads(result_text))
    assert result == record.to_json()
    # The record points at the run's project and its Pi transcript directory,
    # both inside the archive (the transcript is referenced, never copied).
    assert record.project_dir == str(run_dir / "project")
    assert record.session_id
    assert record.transcript_dir == str(
        harness.session_transcript_dir(run_dir / "project", record.session_id)
    )
    return events


def test_bench_run_bracket_101_with_a_scripted_model(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    (task,) = load_tasks(["bracket-101"])
    bracket_script(fake_model)
    archive = tmp_path / "results" / provider.model_slug / "2026-07-24"

    run = harness.run_task(
        task,
        1,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-24",
    )

    assert run.error is None, run.error
    assert run.status == "completed"
    assert run.passed, run.reasons
    # create_part + write_part + build_part, counted from the normalized stream.
    assert run.tool_calls == 3
    assert run.tool_calls <= run.budget_tool_calls == 20

    grade = cast("dict[str, Any]", run.grade)
    assert grade["within_budget"] is True
    checks = cast("dict[str, Any]", grade["checks"])
    assert checks, "the task's required checks were not installed"
    for name, value in checks.items():
        assert cast("dict[str, Any]", value)["pass"] is True, name
    # The required STEP export was produced from the graded geometry and validated.
    exports = cast("list[Any]", grade["exports"])
    assert len(exports) == 1
    export = cast("dict[str, Any]", exports[0])
    assert "invalid" not in export
    assert int(cast("int", export["bytes"])) >= 1024

    events = assert_archived(archive / "bracket-101-s1", run)
    assert sum(1 for e in events if e["kind"] == "tool_call") == 3
    assert any(e["kind"] == "tool_result" for e in events)


def test_bench_run_repair_fillet_with_a_scripted_model(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    (task,) = load_tasks(["repair-fillet"])
    repair_script(fake_model)
    archive = tmp_path / "results" / provider.model_slug / "2026-07-24"

    run = harness.run_task(
        task,
        2,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-24",
    )

    assert run.error is None, run.error
    assert run.passed, run.reasons
    assert run.tool_calls == 3
    assert run.seed == 2
    # The repair really happened in the run's own project: the graded build is the
    # edited script's, and the task declares no exports.
    grade = cast("dict[str, Any]", run.grade)
    assert cast("list[Any]", grade["exports"]) == []
    assert cast("dict[str, Any]", grade["builds"])["plate"]["status"] == "ok"
    assert_archived(archive / "repair-fillet-s2", run)


def test_a_review_hook_outcome_is_archived_and_scored(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    """``VALIDATION.md`` §5/§6: a review outcome enters the archive, and §8 reads it.

    The ladder itself is exercised in ``tests/stage2v``; what is pinned here is
    the harness contract — the hook runs at the stop state, its outcome lands in
    ``review.json`` *and* in the run record, and the §8 metrics that need a review
    are computed from it rather than from anything the model said.
    """
    (task,) = load_tasks(["repair-fillet"])
    repair_script(fake_model)
    archive = tmp_path / "results" / provider.model_slug / "2026-07-24"
    seen: list[str] = []

    def review(context: harness.RunContext) -> dict[str, Any]:
        seen.append(context.session_id)
        assert context.run_id, "the hook needs the run id the ladder reviews under"
        return {
            "terminal": {"status": "unresolved_requirements", "cycles": 1},
            "cycles": [
                {
                    "cycle": 1,
                    "findings": [
                        {"id": "R1", "verdict": "fail", "evidence": "46 mm", "channel": "numeric"},
                        {"id": "R2", "verdict": "pass", "evidence": "seen", "channel": "vision"},
                    ],
                }
            ],
        }

    run = harness.run_task(
        task,
        4,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        review=review,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-24",
    )

    assert seen == [run.session_id]
    run_dir = archive / "repair-fillet-s4"
    archived = cast(
        "dict[str, Any]", json.loads((run_dir / "review.json").read_text(encoding="utf-8"))
    )
    assert archived == run.review
    measured = metrics.run_metrics(run.to_json(), archive_dir=run_dir)
    assert measured.reviewed is True
    assert (measured.caught_failures, measured.caught_numeric) == (1, 1)
    assert measured.reviewed_requirements == 2


def test_a_failing_review_hook_fails_that_run_and_not_the_bench(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    """§5 is blocking: a review that could not run verified nothing.

    The failure is scoped to *this* run — it is graded, archived and given a
    reason, and nothing propagates out of ``run_task`` — so the bench keeps
    going. What must not happen is a run that quietly passes on the strength of
    a review that never completed.
    """
    (task,) = load_tasks(["repair-fillet"])
    repair_script(fake_model)

    def review(context: harness.RunContext) -> dict[str, Any]:
        raise RuntimeError("reviewer child exploded")

    run = harness.run_task(
        task,
        5,
        provider=provider,
        archive_dir=tmp_path / "results",
        runtime_factory=runtime_factory,
        review=review,
        prompt_timeout=PROMPT_TIMEOUT,
    )
    assert run.error is None, "the run itself completed; it is the review that failed"
    assert cast("dict[str, Any]", run.review)["error"].startswith("RuntimeError")
    assert not run.passed
    assert any(reason.startswith("review_error:RuntimeError") for reason in run.reasons), (
        run.reasons
    )
    # …and the grading evidence is complete anyway: the run was archived, not lost.
    assert cast("dict[str, Any]", run.grade)["builds"]["plate"]["status"] == "ok"


def test_budget_exceeded_cancels_the_run_and_cannot_pass(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    """The same passing script under a budget of one call must fail on budget."""
    (loaded,) = load_tasks(["repair-fillet"])
    task = replace(loaded, budget_tool_calls=1)
    repair_script(fake_model)

    run = harness.run_task(
        task,
        1,
        provider=provider,
        archive_dir=tmp_path / "results",
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
    )

    assert not run.passed
    assert run.tool_calls > 1
    assert any(reason.startswith("budget_exceeded:") for reason in run.reasons), run.reasons
    grade = cast("dict[str, Any]", run.grade)
    assert grade["within_budget"] is False


def test_run_bench_archives_the_index_and_scores(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    """``run_bench`` over one task/one seed writes the index ``heph bench score`` reads."""
    tasks = load_tasks(["repair-fillet"])
    repair_script(fake_model)
    results_dir = tmp_path / "results"

    bench_run = harness.run_bench(
        tasks,
        provider=provider,
        seeds=1,
        results_dir=results_dir,
        date="2026-07-24",
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
    )

    assert bench_run.archive_dir == results_dir / provider.model_slug / "2026-07-24"
    assert len(bench_run.records) == 1
    index = bench_run.archive_dir / RUNS_FILENAME
    assert index.is_file()
    assert len(index.read_text(encoding="utf-8").strip().splitlines()) == 1

    score = score_directory(bench_run.archive_dir)
    assert score.n == 1
    assert score.passes == 1
    assert score.model == provider.model_id
    assert score.per_task["repair-fillet"].pass_rate == 1.0
    # One seed is not a gate: the perfect-task rule holds but the bound does not.
    assert score.perfect_task_failures == ()
    assert not score.meets_gate


def test_seeding_a_task_is_deterministic(tmp_path: Path) -> None:
    """Seeding twice yields the same project, and protected files are restorable."""
    (task,) = load_tasks(["bracket-101"])
    first = harness.seed_project(task, tmp_path / "a")
    second = harness.seed_project(task, tmp_path / "b")

    def tree(root: Path) -> dict[str, bytes]:
        return {
            item.relative_to(root).as_posix(): item.read_bytes()
            for item in root.rglob("*")
            if item.is_file()
        }

    files = tree(first)
    other = tree(second)
    assert files == other
    assert "parts/hole_gauge.py" in files

    gauge = first / "parts" / "hole_gauge.py"
    gauge.write_text("part.geometry = Box(1, 1, 1)\n", encoding="utf-8")
    restored = harness.restore_protected(task, first)
    assert restored == ["parts/hole_gauge.py"]
    assert gauge.read_bytes() == files["parts/hole_gauge.py"]
    assert harness.restore_protected(task, first) == []


def test_bench_task_json_round_trips() -> None:
    (task,) = load_tasks(["enclosure-bosses"])
    payload = task.to_json()
    assert payload["id"] == "enclosure-bosses"
    assert payload["render_requirements"][0]["section_plane"] == "+Z@c"
    assert isinstance(task, BenchTask)


def stateless_bracket_resolver() -> Any:
    """One request-derived turn resolver, safe under interleaved parallel sessions.

    Unlike the cursor-based script, every decision is derived from the request's
    own conversation history, so two concurrent runs consuming resolvers from
    one FakeOpenAI cannot cross wires.
    """
    script = solution_script("bracket-101", "bracket")

    def resolve(info: RequestInfo) -> dict[str, Any]:
        last = last_tool_result(info)
        if not last:  # {} = no tool result yet in this session's transcript
            return tool_call("create_part", {"name": "bracket"}, "c0")
        if "content_hash" in last and "applied" not in last and "status" not in last:
            return tool_call(
                "write_part",
                {"name": "bracket", "expected_hash": last["content_hash"], "script": script},
                "c1",
            )
        if last.get("applied") is True:
            return tool_call("build_part", {"name": "bracket"}, "c2")
        assert last.get("status") == "ok", last
        return {"kind": "text", "chunks": ["bracket built"]}

    return resolve


def test_bench_run_parallel_seeds_are_isolated_and_indexed(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    (task,) = load_tasks(["bracket-101"])
    fake_model.set_script([stateless_bracket_resolver()] * 12)

    run = harness.run_bench(
        [task],
        provider=provider,
        seeds=2,
        results_dir=tmp_path / "results",
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-24",
        parallel=2,
    )

    assert [(r.task_id, r.seed) for r in run.records] == [("bracket-101", 1), ("bracket-101", 2)]
    assert all(r.passed for r in run.records), [r.reasons for r in run.records]
    index_lines = (run.archive_dir / "runs.jsonl").read_text().splitlines()
    assert len(index_lines) == 2
    dirs = {r.project_dir for r in run.records}
    assert len(dirs) == 2, "parallel runs must use distinct project roots"


def test_observe_mode_lets_a_run_pass_its_budget_and_records_where(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    """Default (observe) mode measures the true cost; grading is unchanged.

    Cancelling at the budget censors every over-budget run to ``budget + 1``
    and — because a cancelled run never reaches a stop state — skips the §5
    reviewer entirely. Observe mode lets the run finish, records
    ``budget_exceeded_at``, and still fails the run for being over budget.
    """
    (task,) = load_tasks(["bracket-101"])
    tight = replace(task, budget_tool_calls=2)  # the scripted solution needs 3
    fake_model.set_script([stateless_bracket_resolver()] * 8)

    run = harness.run_task(
        tight,
        1,
        provider=provider,
        archive_dir=tmp_path / "archive",
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-26",
    )

    # It ran to COMPLETION rather than being cut the moment it went over —
    # which is what lets the §5 reviewer see a stop state at all.
    assert run.status == "completed"
    assert run.budget_exceeded_at == tight.budget_tool_calls + 1
    assert run.hit_observe_ceiling is False
    # ... and grading still fails it for exceeding the budget.
    assert not run.passed
    assert any(r.startswith("budget_exceeded") for r in run.reasons), run.reasons


def test_enforce_mode_still_cancels_at_the_budget(
    tmp_path: Path,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    (task,) = load_tasks(["bracket-101"])
    tight = replace(task, budget_tool_calls=2)
    fake_model.set_script([stateless_bracket_resolver()] * 8)

    run = harness.run_task(
        tight,
        1,
        provider=provider,
        archive_dir=tmp_path / "archive",
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        enforce_budget=True,
        date="2026-07-26",
    )

    assert run.status == "cancelled"
    assert run.tool_calls == tight.budget_tool_calls + 1
    assert not run.passed
