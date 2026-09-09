"""The two-part cross-check project and the supervised workflow-runner harness.

The thread-phase clauses are exercised from two suites, and both need the same
subject: a real project with two parts whose placement one cross-part check can
reject (:func:`scaffold_workflow_project`), every Python half the runner process
talks to (:class:`Wiring`, whose bridge records the admission capacities it
reported), and the supervised ``agent/dist/workflows/runner.js`` process wired to
that project (:class:`RunnerHarness`).

The check name carries ``shelf``, so a failure attributes the repair to the shelf
alone — that is what ``cad_workflow.ts``'s ``repairTargets`` keys off, and what
makes a repair round observable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.admission import BridgeAdmission
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.delegation import DelegationService
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.agent_bridge.jobstore import JobStore
from hephaestus.agent_bridge.session_edges import SessionEdgeStore
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.agent_bridge.workflows import (
    CadWorkflowRequest,
    PartPromptOutcome,
    PromptRegistry,
    SessionDelegationRunner,
    WorkflowBridge,
    WorkflowRunnerProcess,
    WorkflowService,
)
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.delegation_gates import AllowAllGate
from opstore.types import TerminalState

from opstore import OpStore

from .sidecar import node_executable

__all__ = [
    "BRACKET_SRC",
    "CROSS_CHECK_SRC",
    "ORCH",
    "SHELF_CLEAR_SRC",
    "SHELF_INTERFERING_SRC",
    "RecordingBridge",
    "RunnerHarness",
    "Wiring",
    "assert_slots_drain_to",
    "completing_prompter",
    "request_for",
    "scaffold_workflow_project",
]

#: Bound on "the branch slots are back". Generous on purpose: every caller has
#: already observed the run's durable terminal, so the releases are in flight
#: and not pending work. A leak tripwire, not a performance ceiling.
SLOT_DRAIN_DEADLINE_S = 30.0


def assert_slots_drain_to(
    admission: BridgeAdmission,
    expected: int,
    *,
    holders: frozenset[str] = frozenset(),
    label: str,
) -> None:
    """Bounded "drains to N", naming the runs that kept their slots.

    audit-2026-09-04 J-mirrors-and-dx-24. Every caller used to SAMPLE
    ``active_count()`` once, immediately after the run's terminal was observed.
    Releasing a branch slot is not part of observing that terminal, so under
    load the sample landed before the release and the assertion failed as
    ``assert 1 == 0`` or ``assert 14 == 12`` — a coin flip naming neither which
    runs were still holding nor whether they ever let go. A negative ("no slot
    is leaked") has to wait on a positive edge; here the edge is occupancy
    reaching its floor, which polling can see and one sample cannot.

    Right in EITHER reading of a failure: if the slots genuinely leak this still
    fails, after ``SLOT_DRAIN_DEADLINE_S`` and with the leaking run ids in the
    message — a bug report rather than a retry.

    ``holders`` is the set of run ids legitimately still holding a slot (an
    empty set when the expectation is a fully drained store); it is used only to
    make the failure message say which ids are the leak.
    """
    deadline = time.monotonic() + SLOT_DRAIN_DEADLINE_S
    count = admission.active_count()
    while count != expected:
        if time.monotonic() >= deadline:
            occupied = admission.occupancy()
            raise AssertionError(
                f"{label}: {count} admission slot(s) still occupied after "
                f"{SLOT_DRAIN_DEADLINE_S}s, expected {expected}. Occupied: "
                f"{sorted(occupied)}; expected only {sorted(holders)}; "
                f"leaked: {sorted(occupied - holders)}"
            )
        time.sleep(0.01)
        count = admission.active_count()


ORCH = Principal(session_id="wf-orch", profile="orchestrator", part=None)

BRACKET_SRC = """body = Box(40.0, 20.0, 6.0)
body.label = "bracket_body"
part.geometry = body
part.description = "Base bracket"
"""

#: The shelf as first authored: it sits inside the bracket's envelope.
SHELF_INTERFERING_SRC = """body = Box(30.0, 10.0, 4.0)
body.label = "shelf_body"
part.geometry = body
part.description = "Shelf (interfering placement)"
"""

#: The repaired shelf: lifted clear of the bracket.
SHELF_CLEAR_SRC = """body = Pos(0.0, 0.0, 20.0) * Box(30.0, 10.0, 4.0)
body.label = "shelf_body"
part.geometry = body
part.description = "Shelf (clear of the bracket)"
"""

#: A cross-part check. Its name carries "shelf", so a failure attributes the
#: repair to the shelf alone (cad_workflow.ts `repairTargets`).
CROSS_CHECK_SRC = """CHECKS = {
    "shelf_placement": lambda m: m.interference("bracket/part", "shelf/part")
    == approx(0.0, abs=1e-6),
}
"""


def scaffold_workflow_project(root: Path, *, shelf: str = SHELF_CLEAR_SRC) -> Path:
    """A real two-part project with one cross-part check."""
    (root / "parts").mkdir(parents=True, exist_ok=True)
    (root / "checks").mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "wf"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    (root / "parts" / "bracket.py").write_text(BRACKET_SRC, encoding="utf-8")
    (root / "parts" / "shelf.py").write_text(shelf, encoding="utf-8")
    (root / "checks" / "assembly.py").write_text(CROSS_CHECK_SRC, encoding="utf-8")
    return root


class Wiring:
    """One project's opstore plus every Python half the workflow layer needs."""

    def __init__(
        self,
        root: Path,
        *,
        prompter: Callable[[str, str, str], PartPromptOutcome],
        seed_ledger: bool = True,
    ):
        self.root = root
        self.layout: ProjectLayout = load_project(root)
        self.store: OpStore = open_store(self.layout)
        self.cad = CadOps(self.layout, self.store, backend=UnsafeLocalBackend())
        self.jobs = JobStore(self.store.db)
        self.admission = BridgeAdmission(self.store.admission)
        # INTERFACE.md §2.8: the delegation WAL's PREPARED transition is one of
        # the two writers of the durable session edge, so the harness wires the
        # store — a delegation exercised here threads the same way it will in a
        # served project.
        self.edges = SessionEdgeStore(self.store.db)
        self.delegation = DelegationService(
            self.store.admission, self.store.db, gate=AllowAllGate(), edges=self.edges
        )
        self.prompts = PromptRegistry()
        self.dispatcher = ToolDispatcher(
            ProjectStore(self.layout, self.store),
            cad=self.cad,
            delegation=self.delegation,
            delegation_runner=SessionDelegationRunner(prompter, self.prompts),
        )
        if seed_ledger:
            # VALIDATION.md §2 is enforced by the dispatcher: an empty requirement
            # ledger refuses every build_part. A workflow test's subject is the
            # workflow, so the ledger is a precondition here, not a subject.
            from hephaestus.testing.ledger import seed_minimal_ledger

            seed_minimal_ledger(self.cad)

    def bridge(self) -> RecordingBridge:
        return RecordingBridge(
            self.jobs,
            self.admission,
            dispatcher=self.dispatcher,
            principal=ORCH,
            prompts=self.prompts,
        )

    def build(self, *parts: str) -> None:
        """Build parts directly (the pre-state a workflow run starts from)."""
        for index, name in enumerate(parts):
            out = self.dispatcher.dispatch(
                ORCH,
                {
                    "session_id": ORCH.session_id,
                    "run_id": "setup",
                    "tool": "build_part",
                    "arguments": {"name": name},
                    "invocation": {
                        "session_id": ORCH.session_id,
                        "entry_id": f"setup-{index}",
                        "ordinal": 1,
                        "provider_call_id": "c0",
                    },
                },
            )
            assert out["status"] == "ok", out

    def close(self) -> None:
        self.store.close()


class RecordingBridge(WorkflowBridge):
    """The real bridge plus a log of the capacities it reported.

    The fan-out bound is derived from ``py.admission_capacity`` *at fan-out time*
    (digest §5); recording each answer is what lets a test prove the bound never
    exceeded the capacity that produced it.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.capacities: list[int] = []
        self.methods: list[str] = []

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        self.methods.append(method)
        result = super().handle(method, params)
        if method == "py.admission_capacity":
            self.capacities.append(int(cast("dict[str, Any]", result)["capacity"]))
        return result


def completing_prompter(artifact: str = "artifact:build:sha256:" + "b" * 64) -> Any:
    """A part prompter that completes immediately (no session, no geometry)."""

    def prompt(part: str, text: str, child_run_id: str) -> PartPromptOutcome:
        return PartPromptOutcome(TerminalState.COMPLETED, result_artifact_ref=artifact)

    return prompt


class RunnerHarness:
    """A supervised workflow-runner process over one wired project."""

    def __init__(self, root: Path, runner_main: Path, prompter: Any) -> None:
        node = node_executable()
        assert node is not None
        self.wiring = Wiring(root, prompter=prompter)
        self.bridge = self.wiring.bridge()
        self.process = WorkflowRunnerProcess(
            self.bridge,
            node=node,
            runner_main=runner_main,
            cwd=root,
            default_timeout_s=900.0,
        )
        self.process.start()
        self.pids = [self.process.child_pid]
        self.service = WorkflowService(self.wiring.jobs, self.process, self.wiring.admission)

    def restart(self) -> None:
        self.process.supervisor.restart(reason="test")
        self.pids.append(self.process.child_pid)

    def close(self) -> None:
        try:
            self.process.close()
        finally:
            self.wiring.close()

    def assert_no_orphans(self) -> None:
        for pid in self.pids:
            assert not pid_alive(pid), f"workflow runner pid {pid} outlived its supervisor"


def request_for(root: Path, **overrides: Any) -> dict[str, Any]:
    """The runner payload for the two-part bracket/shelf workflow."""
    base: dict[str, Any] = {
        "project_root": str(root),
        "session_id": ORCH.session_id,
        "parts": [
            ("bracket", "PART bracket: build the bracket.", "REPAIR PART bracket: fix it."),
            ("shelf", "PART shelf: build the shelf.", "REPAIR PART shelf: move it clear."),
        ],
        "max_repair_rounds": 2,
        "max_concurrency": 2,
    }
    base.update(overrides)
    return CadWorkflowRequest(**base).payload()
