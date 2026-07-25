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

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.admission import BridgeAdmission
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.delegation import DelegationService
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.agent_bridge.jobstore import JobStore
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
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
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
    "completing_prompter",
    "request_for",
    "scaffold_workflow_project",
]

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

    def __init__(self, root: Path, *, prompter: Callable[[str, str, str], PartPromptOutcome]):
        self.root = root
        self.layout: ProjectLayout = load_project(root)
        self.store: OpStore = open_store(self.layout)
        self.cad = CadOps(self.layout, self.store)
        self.jobs = JobStore(self.store.db)
        self.admission = BridgeAdmission(self.store.admission)
        self.delegation = DelegationService(self.store.admission, self.store.db)
        self.prompts = PromptRegistry()
        self.dispatcher = ToolDispatcher(
            ProjectStore(self.layout, self.store),
            cad=self.cad,
            delegation=self.delegation,
            delegation_runner=SessionDelegationRunner(prompter, self.prompts),
        )

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
