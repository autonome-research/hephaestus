"""The run loop: provider selection, the live budget guard, and archiving.

One run seeds a project, opens a real orchestrator session against a configured
provider, and sends the seeded prompt. Normalized ``tool_call`` events are
counted *live*: exceeding the task's budget cancels the run rather than letting
it spend unbounded. Whatever happens — completion, cancellation, a runtime error,
even a grading crash — the run is graded and archived, and the bench continues.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.agent_bridge.app import BridgeRuntime, ProviderSpec
from hephaestus.agent_bridge.cad_ops import RequirementEntry, material_class

from ..metrics import ledger_snapshot
from ..scoring import RUNS_FILENAME
from ._archive import (
    ARCHIVE_EVENTS_FILENAME,
    ARCHIVE_RESULT_FILENAME,
    BenchRun,
    RunRecord,
    results_root,
    session_transcript_dir,
    today,
)
from ._grade import GradeReport, grade
from ._seed import seed_project
from ._tasks import BenchTask, seeded_prompt

__all__ = [
    "BENCH_ANSWER",
    "COMPELLED_TOOLS",
    "DEFAULT_PROMPT_TIMEOUT",
    "DEFAULT_SEEDS",
    "OBSERVE_CEILING_FACTOR",
    "OBSERVE_CEILING_FLOOR",
    "ProviderConfig",
    "ReviewHook",
    "RunContext",
    "RuntimeFactory",
    "annotate_requirements",
    "bench_answerer",
    "default_review_hook",
    "default_runtime_factory",
    "dry_run",
    "observe_ceiling",
    "run_bench",
    "run_task",
]

#: Seeds per task; the gate needs S >= 3 (8 tasks x 3 seeds => n >= 24).
DEFAULT_SEEDS = 3

#: Wall-clock cap for one prompt run (CAD builds are minutes, not seconds).
DEFAULT_PROMPT_TIMEOUT = 1800.0

#: ``VALIDATION.md`` §7, verbatim: the only answer the bench ever gives.
#:
#: The wording is load-bearing — ``cad_ops._gate._NON_COMMITTAL`` must classify
#: it as non-committal, or the bench would start silently *resolving* ledger
#: entries and the clarification gate would open on a question nobody answered.
#: ``test_bench_validation_metrics`` pins that coupling.
BENCH_ANSWER: Final[str] = (
    "unspecified — use your engineering judgment and record it as an assumption."
)


@dataclass(frozen=True)
class ProviderConfig:
    """A resolved provider list plus the selected model id.

    Loaded from a JSON file so no credential or endpoint is hard-coded::

        {"providers": [{"id": "...", "kind": "anthropic"|"openai_compatible",
                        "baseUrl": "...", "credential": "ENV_NAME",
                        "models": [{"id": "...", "contextWindow": 200000,
                                    "maxTokens": 8192, "input": ["text","image"]}]}],
         "credentials": {"ENV_NAME": "literal-secret"},
         "credential_env": ["ENV_NAME"],
         "auth_source": "/home/you/.pi/agent/auth.json"}

    ``credential_env`` names are read from the ambient environment at load time;
    the supervisor forwards only the resulting allowlist to the sidecar.

    ``auth_source`` is the opt-in hook for providers of kind ``pi_native``: an
    absolute path to an existing Pi ``auth.json`` that the supervisor *symlinks*
    into the project's agent dir (see
    :func:`~hephaestus.agent_bridge.app.link_auth_source`). Omitted by default,
    and omitting it means the sidecar has no credential but the explicit ones.
    """

    providers: tuple[ProviderSpec, ...]
    model_id: str
    credentials: Mapping[str, str] = field(default_factory=dict[str, str])
    credential_allowlist: tuple[str, ...] = ()
    auth_source: Path | None = None

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
        auth_raw = data.get("auth_source")
        auth_source = Path(str(auth_raw)).expanduser() if auth_raw else None
        ordered, model_id = cls._select_model(providers, model)
        return cls(
            providers=tuple(ordered),
            model_id=model_id,
            credentials=credentials,
            credential_allowlist=tuple(allowlist),
            auth_source=auth_source,
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
        auth_source=provider.auth_source,
    )


def bench_answerer(params: Mapping[str, Any]) -> Any:
    """The §7 answerer: **non-committal, always** — the same sentence every time.

    ``VALIDATION.md`` §7 is explicit that the bench must not do the
    disambiguation production ``ask_user`` exists to obtain. The previous policy
    ("take the first option") answered helpfully and therefore deleted the very
    mechanism under test: an agent that guessed and asked got a free correct
    answer, so asking cost nothing and measured nothing.

    What the answer *does* is enforced elsewhere and by rule:
    :func:`~hephaestus.agent_bridge.cad_ops.record_answers` classifies this
    sentence as non-committal (it matches the ``_NON_COMMITTAL`` markers
    "unspecified" and "engineering judgment"), so the named requirement is
    recorded ``asked: true`` and **stays** ``assumed`` — the clarification gate
    stays shut and §5 still sees an unconfirmed assumption. Asking is scored (§8
    ``clarification_rate``); guessing right by luck is not.

    ``params`` is ignored on purpose: an answer that varied with the question
    would be a policy the agent could steer.
    """
    del params
    return BENCH_ANSWER


def annotate_requirements(
    events: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """The run's final ledger, each entry tagged with its §3 material class.

    The classification is the *harness's* second opinion on the model's own
    ``material`` flag (``cad_ops.material_class``), and it is written down here —
    at archive time, where the bridge is already imported — precisely so
    :mod:`hephaestus.bench.metrics` can compute ``clarification_rate`` over the
    §3 gate's wider set without importing the CAD stack. An entry the classifier
    cannot parse keeps a ``None`` class and still counts by its own flag.
    """
    annotated: list[Mapping[str, Any]] = []
    for entry in ledger_snapshot(events):
        row = dict(entry)
        try:
            row["material_class"] = material_class(RequirementEntry.from_json(entry))
        except Exception:
            row["material_class"] = None
        annotated.append(row)
    return tuple(annotated)


@dataclass(frozen=True)
class RunContext:
    """Handed to the ``before_prompt``/``review`` hooks around the prompt.

    ``status`` and ``events`` are the finished prompt run's, so a ``review`` hook
    can decide for itself whether §5's stop state was actually reached. They are
    empty when the context is handed to ``before_prompt`` — nothing has run yet.
    """

    task: BenchTask
    seed: int
    prompt: str
    project_root: Path
    runtime: BridgeRuntime
    session_id: str
    run_id: str = ""
    status: str = ""
    events: tuple[Mapping[str, Any], ...] = ()


#: ``VALIDATION.md`` §5/§6 seam: run the termination-review ladder for a finished
#: run and return its ``LadderOutcome.to_json()`` for the archive (``None`` to
#: record no review). ``run_task``/``run_bench`` still default to *no* hook so a
#: unit test can drive the loop without a reviewer child; ``heph bench run``
#: supplies :func:`default_review_hook` unless ``--no-review`` is passed, which
#: is what makes §5/§6 fire — and §8's ``requirement_coverage`` /
#: ``review_catch_rate`` real numbers — on every bench run.
ReviewHook = Callable[[RunContext], Mapping[str, Any] | None]


def default_review_hook(context: RunContext) -> Mapping[str, Any] | None:
    """Run the real §5 review + §6 continuation ladder over a finished run.

    This is the production wiring, and it is deliberately the *default* for
    ``heph bench run``: §5 says the agent may not self-declare done, so a bench
    that never reviewed measured only what the agent was willing to claim. Before
    it existed the §8 table reported ``requirement_coverage`` and
    ``review_catch_rate`` as *unmeasured* on every run.

    What it wires together is exactly what ``tests/stage2v`` exercises:

    * :class:`~hephaestus.agent_bridge.review.SessionReviewer` — an independent
      Pi child on the read-only ``reviewer`` profile, with its own budget;
    * :class:`~hephaestus.agent_bridge.review.TerminationReviewService` — the §5
      context (the verbatim *task prompt*, the ledger the run actually wrote,
      renders — never the agent's ``CHECKS``) and the by-rule normalization that
      records a ``channel`` on every finding and fails an unconfirmed assumption
      however confidently the reviewer passed it;
    * :func:`~hephaestus.agent_bridge.review.run_review_ladder` — §6's bounded
      continuation: findings re-enter *the agent's own session* as a tool result
      it must resolve, capped at
      :data:`~hephaestus.agent_bridge.review.MAX_REVIEW_CYCLES` cycles, and the
      terminal can never be green with an open requirement.

    Returns ``None`` when the run never reached §5's stop state (cancelled, over
    budget, errored): there is no finished work to review and the agent's session
    is not in a state to receive a continuation, so "no review ran" is the honest
    record rather than a fabricated empty one.
    """
    from hephaestus.agent_bridge.review import (
        PromptContinuation,
        SessionReviewer,
        TerminationReviewService,
        is_stop_state,
        run_review_ladder,
    )

    if not is_stop_state(context.events, context.status):
        return None
    cad = context.runtime.cad
    outcome = run_review_ladder(
        TerminationReviewService(cad, SessionReviewer(context.runtime)),
        PromptContinuation(context.runtime, context.session_id, timeout_s=DEFAULT_PROMPT_TIMEOUT),
        # The corpus prompt verbatim — never the agent's paraphrase of it.
        request=context.prompt,
        run_id=context.run_id or f"{context.task.id}-s{context.seed}",
        cad=cad,
    )
    return outcome.to_json()


#: Tools the VALIDATION.md ladder COMPELS, which therefore do not spend budget.
#:
#: The budget measures the agent's own design efficiency — how economically it
#: reaches correct geometry. The ladder's rungs are not the agent's choices:
#: §2 requires a ledger before geometry, §3 blocks ``build_part`` until a
#: material assumption has been asked about, and §6 hands review findings back
#: as work the agent MUST resolve. Charging those against a budget calibrated
#: before the ladder existed would silently tighten every task by several calls
#: and make the bench measure harness ceremony instead of agent competence.
#:
#: They cannot be gamed precisely because they are compelled: an agent cannot
#: spend them on anything else, and the gate rules decide when they fire. They
#: are still counted and reported separately as ``compelled_tool_calls``, so the
#: exemption is visible in every archived run rather than hidden.
COMPELLED_TOOLS: frozenset[str] = frozenset(
    {"record_requirements", "read_requirements", "update_requirement", "ask_user"}
)


#: Hard ceiling on an observed (non-enforcing) run, as a multiple of the budget.
#: Generous enough that "how many calls does this actually take?" is answered,
#: bounded so a non-converging run cannot spin forever. A run that hits it did
#: not converge, which is itself the measurement.
OBSERVE_CEILING_FACTOR: Final[int] = 4
OBSERVE_CEILING_FLOOR: Final[int] = 24


def observe_ceiling(budget: int) -> int:
    """The hard call ceiling for an observed run."""
    return max(budget * OBSERVE_CEILING_FACTOR, budget + OBSERVE_CEILING_FLOOR)


class _BudgetGuard:
    """Counts chargeable ``tool_call`` events and bounds the run.

    Two modes, and the distinction is a *measurement* choice, never a grading
    one — ``grade`` computes ``within_budget`` from the recorded count either
    way, so the pass criteria of ``verification.md`` are identical:

    ``observe`` (default)
        The run continues past its budget to a hard ceiling
        (:func:`observe_ceiling`) or the wall-clock timeout. Cancelling AT the
        budget censors the data: every over-budget run records exactly
        ``budget + 1`` and "needs one more call" is indistinguishable from
        "needs triple". Worse, a cancelled run never reaches a stop state, so
        the §5 termination reviewer and the §6 continuation ladder never run —
        measured 2026-07-26, when seven consecutive cancellations meant the
        reviewer had never executed in a bench at all.
    ``enforce``
        Cancels on the call that exceeds the budget (the original behaviour),
        for cost-bounded runs where the uncensored number is not worth paying
        for.

    Harness-compelled ladder calls (:data:`COMPELLED_TOOLS`) are tallied into
    ``compelled_tool_calls`` and never charged in either mode.
    """

    def __init__(
        self, runtime: BridgeRuntime, run_id: str, budget: int, *, enforce: bool = False
    ) -> None:
        self._runtime = runtime
        self._run_id = run_id
        self._budget = budget
        self._enforce = enforce
        self._ceiling = budget if enforce else observe_ceiling(budget)
        self._cancelled = False
        self.tool_calls = 0
        self.compelled_tool_calls = 0
        #: Calls spent when the budget was first exceeded (None if never).
        self.budget_exceeded_at: int | None = None
        #: True when the run was stopped by the observe ceiling, not the budget.
        self.hit_ceiling = False
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
        payload = event.get("payload")
        name = ""
        if isinstance(payload, dict):
            name = str(cast("Mapping[str, Any]", payload).get("name", ""))
        if name in COMPELLED_TOOLS:
            self.compelled_tool_calls += 1
            return
        self.tool_calls += 1
        if self.tool_calls > self._budget and self.budget_exceeded_at is None:
            self.budget_exceeded_at = self.tool_calls
        if self.tool_calls > self._ceiling and not self._cancelled:
            self._cancelled = True
            self.hit_ceiling = not self._enforce
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
    review: ReviewHook | None = None,
    prompt_timeout: float = DEFAULT_PROMPT_TIMEOUT,
    enforce_budget: bool = False,
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
    review_outcome: Mapping[str, Any] | None = None
    try:
        runtime.start()
        session_id = runtime.create_session("orchestrator", session_id=f"bench-{task.id}-s{seed}")
        run_id = runtime.new_run_id()
        guard = _BudgetGuard(runtime, run_id, task.budget_tool_calls, enforce=enforce_budget)

        def on_event(event: dict[str, Any]) -> None:
            events.append(event)
            assert guard is not None
            guard.on_event(event)

        context = RunContext(
            task=task,
            seed=seed,
            prompt=prompt,
            project_root=project,
            runtime=runtime,
            session_id=session_id,
            run_id=run_id,
        )
        if before_prompt is not None:
            before_prompt(context)
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
        if review is not None:
            # The stop state is where §5 fires. A review that raises fails THIS
            # run (below, as a graded reason) and never the bench: the archive
            # still has to be written, and the next (task, seed) still runs.
            try:
                review_outcome = review(replace(context, status=status, events=tuple(events)))
            except Exception as exc:  # recorded, never raised
                review_outcome = {"error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        with contextlib.suppress(Exception):
            runtime.close()

    tool_calls = guard.tool_calls if guard is not None else 0
    compelled_calls = guard.compelled_tool_calls if guard is not None else 0
    exceeded_at = guard.budget_exceeded_at if guard is not None else None
    hit_ceiling = guard.hit_ceiling if guard is not None else False
    questions = tuple(guard.questions) if guard is not None else ()
    with (run_dir / ARCHIVE_EVENTS_FILENAME).open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    extra: list[str] = []
    if status != "completed":
        extra.append(f"run_{status}")
    if error is not None:
        extra.append("run_error")
    # A review that could not be carried out verified nothing — but that is the
    # *harness* failing, not the model, so the reason is recorded here (and in
    # `harness_error_rate`) without being charged to the run's verdict; see
    # `metrics.UNCHARGED_REASON_PREFIXES`. The bench itself is untouched either
    # way: this run is graded and archived like any other, and the next starts.
    review_error = None if review_outcome is None else review_outcome.get("error")
    if isinstance(review_error, str) and review_error:
        extra.append(f"review_error:{review_error}")
    try:
        report = grade(task, project, tool_calls=tool_calls, extra_reasons=extra)
    except Exception as exc:  # a grading crash fails THIS run, never the bench
        report = GradeReport(
            task_id=task.id,
            passed=False,
            reasons=tuple([*extra, f"harness_error:{type(exc).__name__}:{exc}"]),
            builds={},
            check_status="not_run",
            checks={},
            other_checks={},
            exports=(),
            renders=(),
            tool_calls=tool_calls,
            budget_tool_calls=task.budget_tool_calls,
            within_budget=tool_calls <= task.budget_tool_calls,
            restored_protected=(),
        )
    (run_dir / "grade.json").write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    requirements = annotate_requirements(events)
    if review_outcome is not None:
        (run_dir / "review.json").write_text(
            json.dumps(dict(review_outcome), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    record = RunRecord(
        task_id=task.id,
        spec=task.spec,
        seed=seed,
        model=provider.model_id,
        date=date or today(),
        passed=report.passed,
        status=status,
        tool_calls=tool_calls,
        compelled_tool_calls=compelled_calls,
        budget_exceeded_at=exceeded_at,
        hit_observe_ceiling=hit_ceiling,
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
        protected_paths=task.protected_paths,
        requirements=requirements,
        review=review_outcome,
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
    review: ReviewHook | None = None,
    prompt_timeout: float = DEFAULT_PROMPT_TIMEOUT,
    enforce_budget: bool = False,
    on_record: Callable[[RunRecord], None] | None = None,
    parallel: int = 1,
) -> BenchRun:
    """Run every (task, seed) pair, archiving each run and the ``runs.jsonl`` index.

    ``parallel`` runs that many (task, seed) pairs concurrently. Each run is
    fully isolated (its own scratch project, BridgeRuntime, sidecar, and store),
    so concurrency is safe; against a local vLLM endpoint continuous batching
    turns the extra in-flight requests into real throughput. The ``runs.jsonl``
    index and ``on_record`` callback are serialized under a lock; the returned
    ``BenchRun.records`` keep deterministic (task, seed) order regardless of
    completion order.
    """
    if seeds < 1:
        raise ValueError(f"seeds must be >= 1, got {seeds}")
    if parallel < 1:
        raise ValueError(f"parallel must be >= 1, got {parallel}")
    run_date = date or today()
    root = results_dir or results_root()
    archive_dir = root / provider.model_slug / run_date
    archive_dir.mkdir(parents=True, exist_ok=True)
    index = archive_dir / RUNS_FILENAME
    pairs = [(task, seed) for task in tasks for seed in range(1, seeds + 1)]

    emit_lock = threading.Lock()

    def execute(pair: tuple[BenchTask, int]) -> RunRecord:
        task, seed = pair
        record = run_task(
            task,
            seed,
            provider=provider,
            archive_dir=archive_dir,
            runtime_factory=runtime_factory,
            before_prompt=before_prompt,
            review=review,
            prompt_timeout=prompt_timeout,
            enforce_budget=enforce_budget,
            date=run_date,
        )
        with emit_lock:
            with index.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.to_json(), sort_keys=True) + "\n")
            if on_record is not None:
                on_record(record)
        return record

    if parallel == 1:
        records = [execute(pair) for pair in pairs]
    else:
        with ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="bench") as pool:
            records = list(pool.map(execute, pairs))
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
                    "dfm_requirements": [d.to_json() for d in task.dfm],
                    "drawing_requirements": [d.to_json() for d in task.drawings],
                    "prompt": seeded_prompt(task, seed),
                }
            )
    return plan
