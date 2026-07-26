"""G2V: the whole validation ladder, end to end, on the failure it was built for.

One scripted model. One real Node sidecar. One real project holding the
**verbatim recorded** ``bracket-101`` seed-2 script — 46 mm in Y against a
request that says 40 mm, with a self-authored ``CHECKS`` envelope that encodes
the misreading and passes. The run is prompted with the **verbatim corpus
request** and then walks every rung of ``VALIDATION.md``:

1. §2 — it records a ledger, including a *material* wall-direction assumption;
2. §3 — ``build_part`` is refused with the discriminated
   ``clarification_required`` result, by rule, before any geometry exists;
3. §7 — the clarification is put with concrete options and the bench answers it
   non-committally; the entry keeps ``asked: true`` and stays ``assumed``, so the
   gate has had its question and opens, but nothing was resolved;
4. §4 — the build then succeeds and hands back a critique nobody asked for,
   naming 40 mm against the 46 mm it just built;
5. §5 — the stop state triggers an independent reviewer child (a real Pi session
   on the read-only ``reviewer`` profile) which never sees the agent's ``CHECKS``
   — asserted against the bytes the reviewer's model actually received — and
   whose confident pass on an unconfirmed assumption is overruled by rule;
6. §6 — the findings re-enter the agent's own session as a tool result it must
   resolve, the same failure twice escalates to a mandatory question, and the
   ladder is capped;
7. §6 — the run cannot terminate green: it ends ``unresolved_requirements``,
   listing every open item.

Nothing here is asked of the model in a prompt. Every rung fires from the
harness: the model's script is free to be as confident and as wrong as the
recorded run was.

What the script deliberately does **not** contain is a way for the run to answer
its own question. ``asked`` and ``resolution`` are refused on every model-facing
ledger write, so the agent cannot type a ``resolution`` onto ``R9`` to open the
gate and buy itself a §5 pass on the same guess. The two rungs therefore divide
the labour the way §3's closing clause describes: the gate compels the *question*
and opens once it has been put, and §5 is fail-unless-*confirmed*, so all three
of ``R1`` (a stated 40 mm measured at 46 mm), ``R7`` and ``R9`` (assumptions
nobody confirmed) are still open at the end and the run cannot finish green.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, PromptResult
from hephaestus.agent_bridge.cad_ops import CadOps, clarification_gate, ledger_state
from hephaestus.agent_bridge.review import (
    MAX_REVIEW_CYCLES,
    REVIEW_TOOL,
    REVIEWER_TOOLS,
    PromptContinuation,
    SessionReviewer,
    TerminationReviewService,
    is_stop_state,
    run_review_ladder,
)
from hephaestus.bench.harness import BENCH_ANSWER, bench_answerer, load_tasks
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.sidecar import build_agent_dist
from hephaestus.testing.stream_assertions import last_tool_result, text, tool_call

FIXTURES = Path(__file__).resolve().parents[2] / "server" / "tests" / "fixtures"

#: The first line of the reviewer's prompt — how the shared fake provider tells a
#: reviewer child's request apart from the agent's.
REVIEWER_MARKER = "Review this finished CAD run"

#: The ledger the scripted run records before it builds anything.
#:
#: ``R9`` is the recorded misreading: the request never says which side of the
#: stated 40 mm the wall stands on, and the answer is 6 mm of geometry. ``R7`` is
#: an ordinary unconfirmed assumption in no §3 material class — it never blocks a
#: build, and §5 must fail it anyway.
LEDGER: list[dict[str, Any]] = [
    {
        "id": "R1",
        "text": "base plate is 40 mm in Y",
        "source": "specified",
        "quote": "60 mm (X) by 40 mm (Y) base plate",
        "value": 40.0,
        "unit": "mm",
        "applies_to": "bracket",
    },
    {
        "id": "R7",
        "text": "the bracket is 3D printed rather than laser cut",
        "source": "assumed",
        "rationale": "the request does not name a process",
        "material": False,
        "applies_to": "bracket",
    },
    {
        "id": "R9",
        "text": "the wall stands outside the stated footprint",
        "source": "assumed",
        "rationale": "the request does not say which side of the stated Y the wall is on",
        "material": True,
        "applies_to": "bracket",
    },
]

CLARIFICATION: dict[str, Any] = {
    "question": "Which side of the stated 40 mm (Y) does the wall stand on?",
    "options": [
        {"label": "inside", "consequence": "40 mm overall in Y, 34 mm internal"},
        {"label": "outside", "consequence": "46 mm overall in Y, 40 mm internal"},
    ],
    "requirement_ids": ["R9"],
    "allow_free_text": True,
}

#: What the reviewer child returns, every cycle, word for word — so the §6
#: "same failure twice" rule sees the same failure twice.
REVIEWER_FINDINGS: list[dict[str, Any]] = [
    {
        "id": "R1",
        "verdict": "fail",
        "evidence": "the Y extent of the delivered bracket measures 46 mm",
        "channel": "numeric",
        "expected": "40 mm",
        "observed": "46 mm",
    },
    {
        "id": "R7",
        "verdict": "pass",
        "evidence": "the surfaces look printed to me",
        "channel": "vision",
    },
    {
        "id": "R9",
        "verdict": "pass",
        "evidence": "the wall is where the ledger says it is",
        "channel": "vision",
    },
]


@dataclass
class Script:
    """The scripted model, shared by the agent session and the reviewer children.

    One callable serves every completion request the sidecar makes. It routes on
    the transcript it is handed — the reviewer's prompt is unmistakable, and so is
    a continuation envelope — so the agent's chain, the reviewer's verdicts and
    the agent's answers to the continuation are all one deterministic script.
    """

    steps: list[tuple[str, dict[str, Any]]]
    index: int = 0
    #: ``(tool, result)`` for every tool result the agent read, in order.
    results: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    #: Verbatim request bodies the reviewer children's model received.
    reviewer_bodies: list[str] = field(default_factory=list[str])
    #: The tool names each reviewer child was actually offered.
    reviewer_tools: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    #: Continuation payloads the agent's model actually read, in order.
    continuations: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def __call__(self, info: RequestInfo) -> dict[str, Any]:
        if REVIEWER_MARKER in info.body_text:
            self.reviewer_bodies.append(info.body_text)
            self.reviewer_tools.append(tuple(sorted(info.tool_names)))
            return text(json.dumps({"findings": REVIEWER_FINDINGS}))
        payload = self._continuation(info)
        if payload is not None:
            self.continuations.append(payload)
            return text("Understood — recording that the review is still open.")
        if self.index > 0 and info.has_tool_result:
            self.results.append((self.steps[self.index - 1][0], last_tool_result(info)))
        if self.index >= len(self.steps):
            return text("BRACKET BUILT")
        name, arguments = self.steps[self.index]
        self.index += 1
        return tool_call(name, arguments, f"call_{self.index}")

    @staticmethod
    def _continuation(info: RequestInfo) -> dict[str, Any] | None:
        """The §6 payload, parsed out of the newest user turn (not a tool result).

        The ladder delivers it as an ordinary turn in the agent's own session, so
        this is the model reading exactly what the reviewer produced.
        """
        body = cast("dict[str, Any]", json.loads(info.body_text))
        messages = cast("list[Any]", body.get("messages", []))
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            entry = cast("dict[str, Any]", message)
            if entry.get("role") != "user":
                continue
            raw = _message_text(entry)
            if f'tool_result tool="{REVIEW_TOOL}"' not in raw:
                return None
            start, end = raw.index("{"), raw.rindex("}")
            return cast("dict[str, Any]", json.loads(raw[start : end + 1]))
        return None


def _message_text(message: dict[str, Any]) -> str:
    """The text of a chat message in either the string or content-block form."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks = cast("list[Any]", content)
        return "".join(
            str(cast("dict[str, Any]", block).get("text", ""))
            for block in blocks
            if isinstance(block, dict)
        )
    return ""


def steps() -> list[tuple[str, dict[str, Any]]]:
    """The agent's turns: exactly the run VALIDATION.md describes, in order."""
    return [
        ("record_requirements", {"entries": LEDGER}),
        # Refused: R9 is a material assumption nobody has answered.
        ("build_part", {"name": "bracket"}),
        ("ask_user", dict(CLARIFICATION)),
        # The question was put, so the gate opens — but the bench declined to
        # decide, so R9 is still an unconfirmed assumption when §5 gets it. The
        # run cannot shortcut that: it may not write the resolution itself.
        ("build_part", {"name": "bracket"}),
    ]


@dataclass
class Harness:
    """A started bridge over the recorded s2 project, plus its scripted model."""

    runtime: BridgeRuntime
    fake: FakeOpenAI
    script: Script
    request: str
    root: Path

    @property
    def cad(self) -> CadOps:
        # The seam the ladder is wired at: the runtime's own CadOps, so the
        # review reads the ledger the run wrote rather than a second handle.
        return self.runtime._cad

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.fake.close()


@pytest.fixture(scope="module")
def sidecar_dist() -> Path:
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; the G2V ladder gate needs the packaged sidecar")
    return built[0]


@pytest.fixture
def harness(tmp_path: Path, sidecar_dist: Path) -> Iterator[Harness]:
    request = load_tasks(["bracket-101"], specs=("prose",))[0].prompt
    root = scaffold_project(
        tmp_path / "bracket",
        name="bracket-101",
        globals_src=(FIXTURES / "bracket_101_s2_globals.py").read_text(encoding="utf-8"),
    )
    (root / "parts" / "bracket.py").write_text(
        (FIXTURES / "bracket_101_s2_bracket.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = Script(steps=steps())
    fake = start_fake_openai([script] * 64)
    runtime = BridgeRuntime(
        project_root=root,
        providers=[fake.provider_spec()],
        dist_main=sidecar_dist,
        # §7: the bench answers every question the same way, and never decides.
        answerer=bench_answerer,
    )
    runtime.start()
    harness = Harness(runtime=runtime, fake=fake, script=script, request=request, root=root)
    try:
        yield harness
    finally:
        harness.close()


def result_for(script: Script, tool: str, occurrence: int = 0) -> dict[str, Any]:
    """The ``occurrence``-th result the model actually read for ``tool``."""
    seen = [result for name, result in script.results if name == tool]
    assert len(seen) > occurrence, f"no result #{occurrence} for {tool}: {script.results}"
    return seen[occurrence]


def test_the_whole_ladder_runs_on_the_recorded_misread(harness: Harness) -> None:
    session = harness.runtime.create_session("orchestrator", session_id="g2v-ladder")

    result: PromptResult = harness.runtime.prompt(session, harness.request, timeout=1800)

    # ---- the agent's own run ------------------------------------------------
    assert result.status == "completed"
    assert is_stop_state(result.events, result.status), "the ladder fires at a stop state"

    assert [name for name, _ in harness.script.results] == [name for name, _ in steps()]

    # §3: the first build is refused, with the discriminated result, naming R9.
    first_build = result_for(harness.script, "build_part", 0)
    assert first_build["status"] == "clarification_required"
    assert [e["id"] for e in cast("list[Any]", first_build["entries"])] == ["R9"]
    assert first_build["message"]

    # §7: the bench answered non-committally, and the answer was written back.
    answered = result_for(harness.script, "ask_user")
    assert answered["selection"] == BENCH_ANSWER
    assert [entry["id"] for entry in cast("list[Any]", answered["recorded"])] == ["R9"]
    assert cast("list[Any]", answered["recorded"])[0]["committal"] is False

    # …and asking is not answering: the gate opens, the assumption does not close.
    # §4: the build lands, and volunteers the critique.
    final_build = result_for(harness.script, "build_part", 1)
    assert final_build["status"] == "ok"
    critique = cast("dict[str, Any]", final_build["critique"])
    raised = cast("list[Any]", critique["warnings"])
    kinds = {str(cast("dict[str, Any]", warning)["kind"]) for warning in raised}
    assert {"dimension_mismatch", "unmatched_request_number"} <= kinds

    # The ledger the later rungs read is the one the run actually wrote.
    state = ledger_state(harness.cad)
    assert state.by_id["R9"].asked is True
    assert clarification_gate(state).blocked is False  # the question was put
    assert state.by_id["R9"].resolution is None  # …and declined, so nothing closed
    assert state.by_id["R7"].resolution is None  # nobody ever confirmed this one

    # ---- §5/§6: the harness reviews at the stop state, the agent does not ----
    service = TerminationReviewService(harness.cad, SessionReviewer(harness.runtime))
    outcome = run_review_ladder(
        service,
        PromptContinuation(harness.runtime, session, timeout_s=1800),
        request=harness.request,  # verbatim, never the agent's paraphrase
        run_id="g2v-ladder",
        cad=harness.cad,
        parts=["bracket"],
    )

    # §5: an independent child really ran, and never saw the agent's CHECKS.
    assert len(harness.script.reviewer_bodies) == MAX_REVIEW_CYCLES == 3
    on_disk = (harness.root / "parts" / "bracket.py").read_text(encoding="utf-8")
    assert "CHECKS" in on_disk and "46.1" in on_disk
    # It is a child with no way to change anything it judges.
    assert set(harness.script.reviewer_tools) == {tuple(sorted(REVIEWER_TOOLS))}
    for body in harness.script.reviewer_bodies:
        assert "CHECKS" not in body
        assert "46.1" not in body
        assert harness.request.splitlines()[0] in body  # the request, verbatim

    # §5: the reviewer passed R7; the rule fails it anyway, and records a channel.
    first_report = outcome.reports[0]
    assert first_report.by_id["R1"].verdict == "fail"
    assert first_report.by_id["R7"].verdict == "fail"
    assert first_report.by_id["R7"].forced_assumption is True
    # …and R9 too: the bench declined, so the assumption was never confirmed and
    # the run had no way to confirm it for itself.
    assert first_report.by_id["R9"].verdict == "fail"
    assert first_report.by_id["R9"].forced_assumption is True
    assert first_report.green is False
    assert all(finding.channel in {"vision", "numeric"} for finding in first_report.findings)

    # §6: the findings re-entered the agent's own session as a tool result …
    assert len(harness.script.continuations) >= 2
    assert [p["tool"] for p in harness.script.continuations] == [REVIEW_TOOL] * len(
        harness.script.continuations
    )
    assert harness.script.continuations[0]["status"] == "changes_required"
    delivered = cast("list[Any]", harness.script.continuations[0]["findings"])
    assert {cast("dict[str, Any]", f)["id"] for f in delivered} == {"R1", "R7", "R9"}
    assert set(cast("list[Any]", harness.script.continuations[0]["unresolved_requirements"])) == {
        "R1",
        "R7",
        "R9",
    }

    # … the same failure twice escalated to a mandatory concrete question …
    escalations = [p for p in harness.script.continuations if p["status"] == "ask_user_required"]
    assert escalations, "R1 failed identically twice and must escalate"
    questions = cast("list[Any]", escalations[0]["questions"])
    assert questions
    for raw in questions:
        options = cast("list[Any]", cast("dict[str, Any]", raw)["options"])
        assert 2 <= len(options) <= 4
        for option in options:
            entry = cast("dict[str, Any]", option)
            assert entry["option"] and entry["consequence"]

    # … the ladder was capped …
    assert len(outcome.reports) == MAX_REVIEW_CYCLES

    # … and the run could not terminate green with requirements open.
    assert outcome.green is False
    assert outcome.terminal.status == "unresolved_requirements"
    assert {item.id for item in outcome.terminal.unresolved} == {"R1", "R7", "R9"}
    assert all(item.evidence for item in outcome.terminal.unresolved)
