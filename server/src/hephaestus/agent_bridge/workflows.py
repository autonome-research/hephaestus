"""Python entry to the thread-phase workflow layer (arch §4.5, digest §5).

The deterministic orchestration layer runs *in Node*, in a **second supervised
entry** — ``agent/dist/workflows/runner.js`` — whose only outbound traffic is
``py.*``: jobstore persistence, live admission capacity, part delegation, and
project-scoped tool dispatch. It owns no Pi session; part agents live in the main
sidecar and are reached through the delegation service, which is exactly digest
§3's rule that *thread-phase calls the session service directly and never
recursively invokes the model-visible tool*.

This module supplies the Python half:

* :class:`WorkflowBridge` — the ``py_handler`` for the workflow runner process.
  ``py.jobstore_*`` goes to :class:`~hephaestus.agent_bridge.jobstore.JobStore`,
  ``py.admission_capacity`` to
  :class:`~hephaestus.agent_bridge.admission.BridgeAdmission`, and
  ``py.delegate`` / ``py.tool_dispatch`` through the *already tested*
  :class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher` under an orchestrator
  principal — no delegation logic is duplicated here.
* :class:`WorkflowRunnerProcess` — the supervised runner (minimal env, watchdog,
  orphan-free shutdown) reusing :class:`~hephaestus.agent_bridge.supervisor.Supervisor`.
* :class:`WorkflowService` — ``launch`` / ``start`` / ``resume`` / ``cancel``,
  durable **event replay** straight out of ``state.db`` (so replay survives a
  restart of both processes), resumable-checkpoint reads, and the startup
  projection of orphaned ``RUNNING`` jobs as terminal failures with
  ``failureClass="interrupted"``.
* :class:`SessionDelegationRunner` — executes an admitted child by prompting its
  part session, then writing the single durable terminal.

**Run accounting.** A launch transactionally admits a stable workflow run id
*before* the sidecar is asked to do anything, and its terminal is durably
recorded and acknowledged before the slot is released (digest §6). Each
concurrent delegation branch (``<run>:<part>:<round>``) is admitted before the
delegation and settled after it, because a synchronous ``delivery="prompt"``
delegation trades its parent's slot for the child's and one run can hold only one
suspension.

**Cross-language contract.** The durable job/event/checkpoint layout is defined in
``agent/src/workflows/jobstore.ts``: namespaces ``tp:jobs`` / ``tp:events`` /
``tp:checkpoints`` / ``tp:meta`` with camelCase JSON fields and ISO-8601 dates.
The constants below are the Python mirror; changing either side is a wire break.
"""

from __future__ import annotations

import asyncio
import dataclasses
import socket
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol, cast, runtime_checkable

from opstore.errors import BusyError, NotFoundError
from opstore.types import JSONValue, TerminalState

from .admission import BridgeAdmission
from .delegation import DelegationPhase, DelegationRow, DelegationService
from .dispatch import DispatchError, Invocation, Principal, ToolDispatcher
from .jobstore import CheckpointRecord, JobStore
from .protocol import ErrorCode, ProtocolError
from .supervisor import Supervisor, SupervisorConfig, SupervisorError

__all__ = [
    "CHECKPOINTS_NAMESPACE",
    "EVENTS_NAMESPACE",
    "INTERRUPTED_FAILURE_CLASS",
    "JOBS_NAMESPACE",
    "META_NAMESPACE",
    "WORKFLOW_CANCEL",
    "WORKFLOW_RESUME",
    "WORKFLOW_RUN",
    "WORKFLOW_STATUS",
    "CadWorkflowRequest",
    "JobEvent",
    "JobRow",
    "PartPromptOutcome",
    "PartPrompter",
    "PromptRegistry",
    "SessionDelegationRunner",
    "WorkflowBridge",
    "WorkflowError",
    "WorkflowHandle",
    "WorkflowRun",
    "WorkflowRunnerProcess",
    "WorkflowService",
    "WorkflowTransport",
    "default_workflow_runner_main",
]

#: Durable namespaces (mirror of ``agent/src/workflows/jobstore.ts``).
JOBS_NAMESPACE: Final[str] = "tp:jobs"
EVENTS_NAMESPACE: Final[str] = "tp:events"
CHECKPOINTS_NAMESPACE: Final[str] = "tp:checkpoints"
META_NAMESPACE: Final[str] = "tp:meta"
_EVENT_SEQ_KEY: Final[str] = "event_seq"

#: Private request methods the workflow-runner process serves.
WORKFLOW_RUN: Final[str] = "workflow.run"
WORKFLOW_RESUME: Final[str] = "workflow.resume"
WORKFLOW_CANCEL: Final[str] = "workflow.cancel"
WORKFLOW_STATUS: Final[str] = "workflow.status"

#: The registered deterministic CAD workflow (``agent/src/workflows/cad_workflow.ts``).
CAD_WORKFLOW: Final[str] = "cad_project"

#: thread-phase carries no ``interrupted`` status; owner loss is a FAILED
#: terminal tagged with this failure class and projected as ``interrupted``.
INTERRUPTED_FAILURE_CLASS: Final[str] = "interrupted"

_LIVE_STATUSES: Final[frozenset[str]] = frozenset({"PENDING", "RUNNING"})


class WorkflowError(Exception):
    """A workflow-layer failure with a stable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def default_workflow_runner_main() -> Path:
    """The packaged workflow runner entry (``agent/dist/workflows/runner.js``)."""
    return Path(__file__).resolve().parents[4] / "agent" / "dist" / "workflows" / "runner.js"


# ---------------------------------------------------------------------------
# durable record projections


def _as_dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


@dataclass(frozen=True, slots=True)
class JobRow:
    """One durable thread-phase job row, as stored by the sidecar."""

    id: str
    name: str
    status: str
    input: Any
    result: Any
    error: str | None
    event_count: int
    created_at: str
    started_at: str | None
    completed_at: str | None
    owner_id: str | None
    pid: int | None
    hostname: str | None
    session_id: str | None
    heartbeat_at: str | None
    failure_class: str | None

    @property
    def live(self) -> bool:
        """``True`` while the row is ``PENDING``/``RUNNING`` (never terminal)."""
        return self.status in _LIVE_STATUSES

    def projected_status(self) -> str:
        """The public status clients see (digest §5 orphan projection).

        ``ABANDONED`` and a ``FAILED`` row tagged ``failureClass="interrupted"``
        are both owner loss, so both project as ``interrupted`` — an unowned job
        never appears live and partial output is never reported as success.
        """
        if self.status == "COMPLETED":
            return "completed"
        if self.status == "CANCELLED":
            return "cancelled"
        if self.status == "ABANDONED":
            return "interrupted"
        if self.status == "FAILED":
            return "interrupted" if self.failure_class == INTERRUPTED_FAILURE_CLASS else "failed"
        return "running" if self.status == "RUNNING" else "queued"

    @classmethod
    def from_json(cls, raw: object) -> JobRow | None:
        data = _as_dict(raw)
        job_id = _opt_str(data.get("id"))
        if job_id is None:
            return None
        pid_raw = data.get("pid")
        return cls(
            id=job_id,
            name=str(data.get("name", "")),
            status=str(data.get("status", "")),
            input=data.get("input"),
            result=data.get("result"),
            error=_opt_str(data.get("error")),
            event_count=_as_int(data.get("eventCount")),
            created_at=str(data.get("createdAt", "")),
            started_at=_opt_str(data.get("startedAt")),
            completed_at=_opt_str(data.get("completedAt")),
            owner_id=_opt_str(data.get("ownerId")),
            pid=pid_raw if isinstance(pid_raw, int) else None,
            hostname=_opt_str(data.get("hostname")),
            session_id=_opt_str(data.get("sessionId")),
            heartbeat_at=_opt_str(data.get("heartbeatAt")),
            failure_class=_opt_str(data.get("failureClass")),
        )


@dataclass(frozen=True, slots=True)
class JobEvent:
    """One durable orchestration event from a job's replayable log."""

    id: int
    job_id: str
    event_type: str
    data: Any
    created_at: str

    @classmethod
    def from_json(cls, raw: object) -> JobEvent | None:
        data = _as_dict(raw)
        event_id = data.get("id")
        if not isinstance(event_id, int):
            return None
        return cls(
            id=event_id,
            job_id=str(data.get("jobId", "")),
            event_type=str(data.get("eventType", "")),
            data=data.get("data"),
            created_at=str(data.get("createdAt", "")),
        )


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    """The outcome of one ``workflow.run`` / ``workflow.resume`` request."""

    job_id: str
    run_id: str
    status: str
    summary: dict[str, Any]
    resumed_from: str | None
    skipped_phases: tuple[str, ...]

    @property
    def terminal_state(self) -> TerminalState:
        """The bridge terminal state for this outcome.

        ``stopped`` is a *clean halt* in thread-phase (a phase set ``ctx.stop``),
        so the run completed — the workflow result carries ``verified: false``.
        """
        if self.status in {"completed", "stopped"}:
            return TerminalState.COMPLETED
        if self.status == "cancelled":
            return TerminalState.CANCELLED
        if self.status == "interrupted":
            return TerminalState.INTERRUPTED
        return TerminalState.FAILED

    @classmethod
    def from_result(cls, raw: object, run_id: str, fallback_job_id: str) -> WorkflowRun:
        data = _as_dict(raw)
        skipped_raw = data.get("skipped_phases")
        skipped = (
            tuple(str(entry) for entry in cast("list[Any]", skipped_raw))
            if isinstance(skipped_raw, list)
            else ()
        )
        return cls(
            job_id=_opt_str(data.get("job_id")) or fallback_job_id,
            run_id=run_id,
            status=str(data.get("status", "failed")),
            summary=_as_dict(data.get("summary")),
            resumed_from=_opt_str(data.get("resumed_from")),
            skipped_phases=skipped,
        )


@dataclass(frozen=True, slots=True)
class CadWorkflowRequest:
    """Typed builder for the ``cad_project`` workflow input payload."""

    project_root: str
    session_id: str
    parts: Sequence[tuple[str, str, str | None]]
    max_parts: int | None = None
    max_repair_rounds: int | None = None
    deadline_seconds: int | None = None
    max_concurrency: int | None = None

    def payload(self) -> dict[str, Any]:
        """The JSON payload ``parseCadWorkflowInput`` expects."""
        parts: list[dict[str, Any]] = []
        for part, prompt, repair in self.parts:
            entry: dict[str, Any] = {"part": part, "prompt": prompt}
            if repair is not None:
                entry["repair_prompt"] = repair
            parts.append(entry)
        payload: dict[str, Any] = {
            "project_root": self.project_root,
            "session_id": self.session_id,
            "parts": parts,
        }
        if self.max_parts is not None:
            payload["max_parts"] = self.max_parts
        if self.max_repair_rounds is not None:
            payload["max_repair_rounds"] = self.max_repair_rounds
        if self.deadline_seconds is not None:
            payload["deadline_seconds"] = self.deadline_seconds
        if self.max_concurrency is not None:
            payload["max_concurrency"] = self.max_concurrency
        return payload


# ---------------------------------------------------------------------------
# delegation execution


@dataclass(frozen=True, slots=True)
class PartPromptOutcome:
    """What running one child part agent produced."""

    state: TerminalState
    result_artifact_ref: str | None = None
    error: str | None = None


#: ``(part, prompt, child_run_id) -> PartPromptOutcome``. Injected by the caller
#: (``heph agent`` / tests) so this module never owns a Pi session.
PartPrompter = Callable[[str, str, str], PartPromptOutcome]


class PromptRegistry:
    """Invocation key → prompt text, shared with :class:`SessionDelegationRunner`.

    :class:`~hephaestus.agent_bridge.dispatch.DelegationRunner` receives only the
    durable :class:`~hephaestus.agent_bridge.delegation.DelegationRow`, which
    stores the prompt *hash* (payload bytes are never duplicated into the WAL) —
    so the runner cannot know what to prompt. The bridge records the prompt
    against the row's ``invocation_key`` (the trusted invocation's ``op_id``,
    which the bridge computes before delegating and the row carries verbatim),
    and the runner reads it back. Thread-safe: the supervisor's reader thread
    registers while a runner thread may be reading.
    """

    def __init__(self) -> None:
        self._prompts: dict[str, str] = {}
        self._lock = threading.Lock()

    def remember(self, invocation_key: str, prompt: str) -> None:
        with self._lock:
            self._prompts[invocation_key] = prompt

    def get(self, invocation_key: str) -> str | None:
        with self._lock:
            return self._prompts.get(invocation_key)

    def forget(self, invocation_key: str) -> None:
        with self._lock:
            self._prompts.pop(invocation_key, None)


class SessionDelegationRunner:
    """Executes an admitted child delegation to its single durable terminal.

    Satisfies :class:`~hephaestus.agent_bridge.dispatch.DelegationRunner`. The
    child is CAS'd ``ADMITTED → DISPATCHED``, its part session is prompted, and
    exactly one terminal is written — a prompter fault becomes a ``failed``
    terminal rather than a lost run.
    """

    def __init__(self, prompter: PartPrompter, prompts: PromptRegistry) -> None:
        self._prompter = prompter
        self._prompts = prompts

    def run(self, service: DelegationService, row: DelegationRow) -> None:
        service.dispatch(row.delegation_ref)
        prompt = self._prompts.get(row.invocation_key)
        if prompt is None:
            service.ingest_terminal(
                row.delegation_ref,
                TerminalState.INTERRUPTED,
                error="delegation prompt was not registered",
            )
            return
        try:
            outcome = self._prompter(row.part, prompt, row.child_run_id)
        except Exception as exc:  # a prompter fault is a child failure, not a hang
            service.ingest_terminal(
                row.delegation_ref,
                TerminalState.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        finally:
            self._prompts.forget(row.invocation_key)
        current = service.get(row.delegation_ref)
        if current.phase is DelegationPhase.TERMINAL:
            return  # a terminal already won (cancellation / deadline)
        service.ingest_terminal(
            row.delegation_ref,
            outcome.state,
            result_artifact_ref=outcome.result_artifact_ref,
            error=outcome.error,
        )


# ---------------------------------------------------------------------------
# the py.* handler for the workflow runner process


class WorkflowBridge:
    """Answers every ``py.*`` request the workflow-runner process originates."""

    def __init__(
        self,
        store: JobStore,
        admission: BridgeAdmission,
        *,
        dispatcher: ToolDispatcher | None = None,
        principal: Principal | None = None,
        prompts: PromptRegistry | None = None,
    ) -> None:
        self._store = store
        self._admission = admission
        self._dispatcher = dispatcher
        self._principal = principal
        self._prompts = prompts or PromptRegistry()
        self.branch_runs: list[str] = []

    @property
    def prompts(self) -> PromptRegistry:
        """The prompt registry to share with the delegation runner."""
        return self._prompts

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        """The :class:`~hephaestus.agent_bridge.supervisor.Supervisor` py handler."""
        if method.startswith("py.jobstore_"):
            # ``JobStore.dispatch`` is the single mapping from bridge method to
            # durable operation; it awaits nothing, so a per-call loop is free.
            return asyncio.run(self._store.dispatch(method, params))
        if method == "py.admission_capacity":
            return {"capacity": self._admission.capacity()}
        if method == "py.delegate":
            return self._delegate(params)
        if method == "py.tool_dispatch":
            return self._tool_dispatch(params)
        raise ProtocolError(ErrorCode.METHOD_NOT_FOUND, f"unhandled py request: {method}")

    # -- delegation ---------------------------------------------------------

    def _delegate(self, params: dict[str, Any]) -> Any:
        dispatcher, principal = self._require_dispatcher()
        part = str(params.get("part", ""))
        prompt = str(params.get("prompt", ""))
        branch_run_id = str(params.get("parent_run_id", ""))
        if not branch_run_id:
            raise DispatchError("invalid_params", "py.delegate requires parent_run_id")
        arguments: dict[str, Any] = {
            "part": part,
            "prompt": prompt,
            "delivery": str(params.get("delivery", "prompt")),
        }
        deadline = params.get("deadline_seconds")
        if isinstance(deadline, int):
            arguments["deadline_seconds"] = deadline
        try:
            self._admission.admit_run(branch_run_id)
        except BusyError:
            # A pre-admission rejection has no child run/ref (digest §3).
            return {"status": "rejected", "reason": "no_run_slot", "part_session_id": None}
        self.branch_runs.append(branch_run_id)
        # The delegation row stores only the prompt hash, so register the prompt
        # under the same key the row will carry (the trusted invocation's op id)
        # BEFORE dispatching, so the runner can find it.
        invocation = _as_dict(params.get("invocation"))
        self._prompts.remember(
            Invocation.from_params(principal.session_id, invocation).op_id, prompt
        )
        try:
            return dispatcher.dispatch(
                principal,
                {
                    "tool": "delegate_part_agent",
                    "arguments": arguments,
                    "invocation": invocation,
                    "run_id": branch_run_id,
                },
            )
        finally:
            self._settle_branch(branch_run_id)

    def _settle_branch(self, branch_run_id: str) -> None:
        """Terminate + acknowledge a delegation branch run, releasing its slot."""
        try:
            if self._admission.get_terminal(branch_run_id) is None:
                self._admission.ingest_terminal(
                    branch_run_id,
                    f"workflow-branch:{branch_run_id}",
                    TerminalState.COMPLETED,
                    {"reason": "delegation_branch_settled"},
                )
            self._admission.acknowledge(branch_run_id, f"workflow-branch:{branch_run_id}")
        except (NotFoundError, ValueError):
            return

    # -- project-scoped tool dispatch --------------------------------------

    def _tool_dispatch(self, params: dict[str, Any]) -> Any:
        dispatcher, principal = self._require_dispatcher()
        session_id = str(params.get("session_id", principal.session_id))
        if session_id != principal.session_id:
            raise DispatchError(
                "scope_denied",
                f"workflow may only dispatch as {principal.session_id!r}",
            )
        return dispatcher.dispatch(principal, params)

    def _require_dispatcher(self) -> tuple[ToolDispatcher, Principal]:
        if self._dispatcher is None or self._principal is None:
            raise DispatchError(
                "not_implemented",
                "the workflow bridge has no tool dispatcher wired",
                code=ErrorCode.METHOD_NOT_FOUND,
            )
        return self._dispatcher, self._principal


# ---------------------------------------------------------------------------
# the supervised runner process


@runtime_checkable
class WorkflowTransport(Protocol):
    """The request/notify surface :class:`WorkflowService` needs.

    :class:`~hephaestus.agent_bridge.supervisor.Supervisor` satisfies it, and so
    does a scripted in-process peer in tests.
    """

    def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any: ...

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None: ...


class WorkflowRunnerProcess:
    """The supervised ``agent/dist/workflows/runner.js`` process."""

    def __init__(
        self,
        bridge: WorkflowBridge,
        *,
        node: str,
        runner_main: Path | None = None,
        cwd: Path | None = None,
        credential_allowlist: Sequence[str] = (),
        extra_env: dict[str, str] | None = None,
        default_timeout_s: float | None = None,
    ) -> None:
        argv = [node, str(runner_main or default_workflow_runner_main())]
        config = SupervisorConfig(
            argv=argv,
            credential_allowlist=frozenset(credential_allowlist),
            extra_env=dict(extra_env or {}),
            cwd=None if cwd is None else str(cwd),
        )
        if default_timeout_s is not None:
            config = dataclasses.replace(config, default_timeout_s=default_timeout_s)
        self._sup = Supervisor(config, py_handler=bridge.handle)

    @property
    def supervisor(self) -> Supervisor:
        return self._sup

    @property
    def child_pid(self) -> int:
        return self._sup.child_pid

    def start(self) -> None:
        self._sup.start()

    def close(self) -> int | None:
        return self._sup.close()

    def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        return self._sup.call(method, params, timeout=timeout)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._sup.notify(method, params)

    def __enter__(self) -> WorkflowRunnerProcess:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# the service


class WorkflowHandle:
    """An in-flight workflow run: cancellable, with a joinable outcome."""

    def __init__(
        self,
        service: WorkflowService,
        job_id: str,
        run_id: str,
        body: Callable[[], WorkflowRun],
    ) -> None:
        self._service = service
        self.job_id = job_id
        self.run_id = run_id
        self._outcome: WorkflowRun | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(body,), daemon=True)
        self._thread.start()

    def _run(self, body: Callable[[], WorkflowRun]) -> None:
        try:
            self._outcome = body()
        except BaseException as exc:  # surfaced to the joining caller
            self._error = exc

    def cancel(self, reason: str = "cancelled") -> bool:
        """Cooperatively cancel the run (idempotent; safe after completion)."""
        return self._service.cancel(self.job_id, reason=reason)

    def result(self, timeout: float | None = None) -> WorkflowRun:
        """Block for the outcome; re-raises whatever the launch raised."""
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise WorkflowError("timeout", f"workflow {self.job_id} did not finish in {timeout}s")
        if self._error is not None:
            raise self._error
        if self._outcome is None:  # pragma: no cover - defensive
            raise WorkflowError("internal", f"workflow {self.job_id} produced no outcome")
        return self._outcome


class WorkflowService:
    """Launch/resume/cancel workflow runs and read their durable history."""

    def __init__(
        self,
        store: JobStore,
        transport: WorkflowTransport,
        admission: BridgeAdmission,
        *,
        workflow: str = CAD_WORKFLOW,
        default_timeout_s: float | None = None,
    ) -> None:
        self._store = store
        self._transport = transport
        self._admission = admission
        self._workflow = workflow
        self._timeout = default_timeout_s

    # -- launching ----------------------------------------------------------

    def new_job_id(self) -> str:
        return f"wf-job-{uuid.uuid4().hex[:12]}"

    def new_run_id(self) -> str:
        return f"wf-{uuid.uuid4().hex[:12]}"

    def launch(
        self,
        payload: dict[str, Any],
        *,
        workflow: str | None = None,
        job_id: str | None = None,
        run_id: str | None = None,
        timeout: float | None = None,
    ) -> WorkflowRun:
        """Run a workflow to its terminal state (blocking).

        The run id and job id are minted and durably admitted **before** the
        sidecar is asked to do anything, and the terminal is recorded and
        acknowledged before the slot is released.
        """
        job_id = job_id or self.new_job_id()
        run_id = run_id or self.new_run_id()
        return self._execute(
            WORKFLOW_RUN,
            {
                "workflow": workflow or self._workflow,
                "job_id": job_id,
                "input": {**payload, "parent_run_id": run_id},
            },
            job_id=job_id,
            run_id=run_id,
            timeout=timeout,
        )

    def start(
        self,
        payload: dict[str, Any],
        *,
        workflow: str | None = None,
        job_id: str | None = None,
        run_id: str | None = None,
        timeout: float | None = None,
    ) -> WorkflowHandle:
        """Launch on a worker thread so the caller can cancel mid-run."""
        job_id = job_id or self.new_job_id()
        run_id = run_id or self.new_run_id()
        return WorkflowHandle(
            self,
            job_id,
            run_id,
            lambda: self.launch(
                payload,
                workflow=workflow,
                job_id=job_id,
                run_id=run_id,
                timeout=timeout,
            ),
        )

    def resume(
        self,
        prior_job_id: str,
        *,
        payload: dict[str, Any] | None = None,
        workflow: str | None = None,
        job_id: str | None = None,
        run_id: str | None = None,
        timeout: float | None = None,
    ) -> WorkflowRun:
        """Resume an interrupted run from its **verified** checkpoints.

        Phases whose checkpoint matches the current workflow version and input
        hash are skipped; anything else re-runs. A resumed run is a new job row
        that points back at ``prior_job_id`` (the interrupted row keeps its
        terminal), so success is never claimed for partial output.

        Omitting ``payload`` resumes from the prior job's stored input — the
        workflow's own re-parsable input projection. Either way the *new* run id
        is threaded in: the run id is orchestration identity, never part of the
        checkpoint input hash, so a fresh one cannot invalidate a checkpoint.
        """
        job_id = job_id or self.new_job_id()
        run_id = run_id or self.new_run_id()
        if payload is None:
            prior = self.status(prior_job_id)
            stored = prior.input if prior is not None else None
            payload = dict(cast("dict[str, Any]", stored)) if isinstance(stored, dict) else {}
        params: dict[str, Any] = {
            "workflow": workflow or self._workflow,
            "job_id": prior_job_id,
            "resume_job_id": job_id,
            "input": {**payload, "parent_run_id": run_id},
        }
        return self._execute(WORKFLOW_RESUME, params, job_id=job_id, run_id=run_id, timeout=timeout)

    def _execute(
        self,
        method: str,
        params: dict[str, Any],
        *,
        job_id: str,
        run_id: str,
        timeout: float | None,
    ) -> WorkflowRun:
        self._admission.admit_run(run_id)
        try:
            raw = self._transport.call(method, params, timeout=timeout or self._timeout)
        except SupervisorError as exc:
            # Confirmed process/transport loss: exactly one interrupted terminal.
            self._finish(run_id, TerminalState.INTERRUPTED, {"error": str(exc)})
            self.mark_interrupted(job_id, reason=str(exc))
            raise WorkflowError("process_down", f"{method} failed: {exc}") from exc
        run = WorkflowRun.from_result(raw, run_id, job_id)
        self._finish(run_id, run.terminal_state, {"job_id": run.job_id, "status": run.status})
        return run

    def _finish(self, run_id: str, state: TerminalState, data: dict[str, Any]) -> None:
        terminal_id = f"workflow:{run_id}"
        try:
            if self._admission.get_terminal(run_id) is None:
                self._admission.ingest_terminal(run_id, terminal_id, state, cast("JSONValue", data))
            self._admission.acknowledge(run_id, terminal_id)
        except (NotFoundError, ValueError):
            return

    def cancel(self, job_id: str, *, reason: str = "cancelled") -> bool:
        """Ask the runner to cancel a job cooperatively (idempotent)."""
        try:
            raw = self._transport.call(WORKFLOW_CANCEL, {"job_id": job_id, "reason": reason})
        except SupervisorError:
            return False
        return _as_dict(raw).get("cancelled") is True

    # -- durable reads ------------------------------------------------------

    def status(self, job_id: str) -> JobRow | None:
        """The durable job row (read straight from ``state.db``)."""
        return JobRow.from_json(self._store.get(JOBS_NAMESPACE, job_id))

    def jobs(self, *, name: str | None = None) -> list[JobRow]:
        """Every durable job row, newest first, optionally filtered by name."""
        rows: list[JobRow] = []
        for record in self._store.list(JOBS_NAMESPACE):
            row = JobRow.from_json(record.value)
            if row is None or (name is not None and row.name != name):
                continue
            rows.append(row)
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows

    def replay(self, job_id: str, *, after_id: int = 0) -> list[JobEvent]:
        """Replay a job's durable orchestration events in id order.

        The log lives in ``state.db``, so replay is identical before and after a
        restart of the runner process, the supervisor, or both.
        """
        events: list[JobEvent] = []
        for record in self._store.list(EVENTS_NAMESPACE, prefix=f"{job_id}#"):
            event = JobEvent.from_json(record.value)
            if event is None or event.id <= after_id:
                continue
            events.append(event)
        events.sort(key=lambda event: event.id)
        return events

    def checkpoints(self, job_id: str) -> list[CheckpointRecord]:
        """The job's resumable phase checkpoints (version + input/output hashes)."""
        return self._store.list_checkpoints(job_id)

    # -- startup orphan projection -----------------------------------------

    def reconcile_orphans(
        self,
        *,
        live_pids: frozenset[int] = frozenset(),
        reason: str = "workflow runner lost before completion",
    ) -> list[str]:
        """Project orphaned ``RUNNING`` jobs as interrupted terminal failures.

        Call once at startup, before admitting new work. Every ``RUNNING`` row
        whose owning process is not in ``live_pids`` (or ran on another host) is
        recorded as ``FAILED`` with ``failureClass="interrupted"`` plus a durable
        ``error`` event, and therefore projects as ``interrupted`` to clients — an
        unowned job never keeps appearing live.
        """
        host = socket.gethostname()
        interrupted: list[str] = []
        for row in self.jobs():
            if row.status != "RUNNING":
                continue
            if row.pid is not None and row.pid in live_pids and (row.hostname or host) == host:
                continue
            self.mark_interrupted(row.id, reason=reason)
            interrupted.append(row.id)
        return interrupted

    def mark_interrupted(self, job_id: str, *, reason: str) -> JobRow | None:
        """Record one interrupted terminal for a live job row (idempotent)."""
        raw = self._store.get(JOBS_NAMESPACE, job_id)
        data = _as_dict(raw)
        if not data or str(data.get("status", "")) not in _LIVE_STATUSES:
            return JobRow.from_json(raw)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        updated: dict[str, Any] = {
            **data,
            "status": "FAILED",
            "error": reason,
            "failureClass": INTERRUPTED_FAILURE_CLASS,
            "completedAt": now,
            "eventCount": int(cast("int", data.get("eventCount", 0) or 0)) + 1,
        }
        self._store.put(JOBS_NAMESPACE, job_id, cast("JSONValue", updated))
        self._append_event(job_id, {"type": "error", "message": reason}, now)
        return JobRow.from_json(updated)

    def _append_event(self, job_id: str, event: dict[str, Any], created_at: str) -> int:
        """Append one durable event, sharing the sidecar's id counter."""
        raw = self._store.get(META_NAMESPACE, _EVENT_SEQ_KEY)
        event_id = (raw + 1) if isinstance(raw, int) else 1
        self._store.put(META_NAMESPACE, _EVENT_SEQ_KEY, event_id)
        record: dict[str, Any] = {
            "id": event_id,
            "jobId": job_id,
            "eventType": str(event.get("type", "unknown")),
            "data": event,
            "createdAt": created_at,
        }
        self._store.put(EVENTS_NAMESPACE, f"{job_id}#{event_id:012d}", cast("JSONValue", record))
        return event_id
