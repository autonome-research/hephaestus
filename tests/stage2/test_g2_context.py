"""G2 context policy: image eviction and compaction over the real sidecar.

Gate clause: *"Context tests prove image eviction and Pi compaction preserve the
pinned CAD summary and that a post-compaction fake model can answer a
pre-compaction decision."*

Both halves are asserted against the transcript the **model actually receives**
(the fake provider records every request body), because that is the only place
where "the context policy worked" is observable:

* compaction — a real Pi compaction is driven over the bridge once the session
  is large enough to have a cut point. The summarization request must carry the
  Hephaestus **pinned CAD summary** (its delimiters and its five normative
  sections), and the *next* prompt after compaction must let the model answer a
  decision that was taken before the compaction boundary, even though the raw
  turn that recorded it is no longer in context;
* image eviction — after four ``inspect_part`` results, only the most recent
  K=3 may still carry image blocks; the evicted render must be replaced by its
  exact text stub while the immutable artifact stays on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from _g2 import G2Harness, RequestInfo, last_tool_result, text, tool_call

#: Enough bulk per turn that a handful of turns crosses Pi's keep-recent window.
FILLER = "Consider the shelf load path and the gusset stiffness carefully. " * 200

DECISION = "the gusset is 4 mm thick"

#: The question/answer pair the CAD-aware test puts to the operator. The pinned
#: summary records the pair as one decision (§B-12: "the question and the
#: selected label, which is a stable server-sent label").
QUESTION = "How wide should the widget be?"
ANSWER = "9.5 mm"

WIDGET = """PARAMS = {"w": Param(20.0, min=5.0, max=50.0)}

body = Box(p.w, 10.0, 4.0)
body.label = "body"
part.geometry = body
"""

#: A second widget carrying a CHECKS entry that fails at every width this suite
#: uses (bbox x < 25), so `run_checks` always reports a real failing check name
#: without depending on the param value chosen.
WIDGET2 = """PARAMS = {"w": Param(20.0, min=5.0, max=50.0)}

body = Box(p.w, 10.0, 4.0)
body.label = "body"
part.geometry = body

CHECKS = {
    "min_width": lambda m: m.bbox("part")[0] >= 25.0,
}
"""

#: The five sections STAGE2_DIGEST §1 requires in the pinned CAD summary.
PINNED_SECTIONS = (
    "Design intent:",
    "Decisions:",
    "Open problems:",
    "Current params:",
    "Check status:",
)

#: audit-2026-09-04-broken.md §B-12 delimiters (`agent/src/session/context.ts`).
PINNED_OPEN = "<<HEPHAESTUS_PINNED_SUMMARY>>"
PINNED_CLOSE = "<</HEPHAESTUS_PINNED_SUMMARY>>"


def _pinned_span(body: str) -> str:
    """The pinned-summary substring of a summarization request body.

    §B-12's gate fix: the old assertion (`DECISION in body`) passed on a
    completely empty pinned summary, because `body` is the WHOLE
    summarization request — which always contains the raw pre-compaction
    transcript the summarizer is compressing. Only a decision found INSIDE
    these delimiters proves the pinned summary itself carried it.
    """
    start = body.index(PINNED_OPEN)
    end = body.index(PINNED_CLOSE, start)
    return body[start:end]


def test_compaction_preserves_the_pinned_summary_and_a_prior_decision(
    tmp_path: Path, sidecar_dist: Path
) -> None:
    from _g2 import scaffold_project

    summarizations: list[RequestInfo] = []

    def summarize(info: RequestInfo) -> str:
        """Stand in for a model asked to compact under Hephaestus's instructions."""
        summarizations.append(info)
        decision = DECISION if DECISION in info.body_text else "no decision recorded"
        return f"## Goal\nBuild the shelf assembly.\n## Decisions\n- {decision}\n"

    project = scaffold_project(tmp_path / "context")
    harness = G2Harness(project, sidecar_dist, summarizer=summarize)
    try:
        session_id = harness.create_session("orchestrator", session_id="g2-context")

        # 1. a decision, taken early, in its own small turn…
        harness.set_script([text(f"Recorded: {DECISION}.")])
        first = harness.prompt(session_id, f"decide the gusset thickness: {DECISION}", timeout=300)
        assert first.status == "completed"

        # 2. …then enough bulk that the early turn falls outside the keep-recent window.
        for i in range(14):
            harness.set_script([text(f"turn {i}: " + FILLER)])
            assert harness.prompt(session_id, f"context {i}: " + FILLER, timeout=300).status == (
                "completed"
            )

        # 3. compaction over the bridge (the sidecar owns the pinned summary).
        result = harness.runtime.sidecar_call(
            "session.compact", {"session_id": session_id}, timeout=300
        )
        assert result["summary"], "compaction produced no summary"

        # -- the pinned CAD summary reached the summarizing model --------------
        assert summarizations, "no summarization request was issued"
        instructed = [
            info for info in summarizations if "HEPHAESTUS_PINNED_SUMMARY" in info.body_text
        ]
        assert instructed, "the compaction request carried no pinned CAD summary"
        body = instructed[0].body_text
        for section in PINNED_SECTIONS:
            assert section in body, f"pinned summary is missing its {section!r} section"
        assert PINNED_CLOSE in body, "pinned summary is not delimited"
        # It is a *pinned* summary: the decision must be INSIDE the pinned span,
        # not merely somewhere in the summarization request (which also carries
        # the raw pre-compaction transcript — §B-12's gate fix). `stubSummary`
        # emits all five section headings with nothing under them, so the old
        # `DECISION in body` assertion passed on an empty summary; this is the
        # assertion the gate clause actually requires and it fails today.
        span = _pinned_span(body)
        assert DECISION in span, (
            "the pinned summary span does not carry the pre-compaction decision"
        )

        # -- post-compaction: the decision is answerable, the raw turn is gone --
        seen: dict[str, Any] = {}

        def after(info: RequestInfo) -> dict[str, Any]:
            seen["body"] = info.body_text
            answer = DECISION if DECISION in info.body_text else "I do not know"
            return text(f"decision: {answer}")

        harness.set_script([after])
        post = harness.prompt(session_id, "what gusset thickness did we settle on?", timeout=300)
        assert post.status == "completed"
        transcript = str(seen["body"])
        assert f"Recorded: {DECISION}." not in transcript, (
            "compaction did not actually discard the pre-boundary turn"
        )
        assert DECISION in transcript, "the compacted context lost the pinned decision"
        streamed = "".join(
            ev["payload"]["text"] for ev in post.events if ev["kind"] == "text_delta"
        )
        assert f"decision: {DECISION}" in streamed
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_pinned_summary_is_cad_aware_not_merely_prompt_aware(
    tmp_path: Path, sidecar_dist: Path
) -> None:
    """§B-12: after an answered question, a `set_params` and a failing
    `run_checks`, the pinned span carries the decision, the new parameter value
    and the failing check's name — proving the producer reads the session's own
    recorded ANSWERS AND TOOL RESULTS, not just the operator's prompt (which is
    all `stubSummary`'s "design intent" fallback ever saw).
    """
    from _g2 import scaffold_project

    NEW_WIDTH = 9.5  # within widget2's [5, 50] bound; bbox stays < 25 either way

    summarizations: list[RequestInfo] = []

    def summarize(info: RequestInfo) -> str:
        summarizations.append(info)
        return "## Goal\nBuild the widget.\n"

    project = scaffold_project(tmp_path / "context-cad-aware")
    (project / "parts" / "widget2.py").write_text(WIDGET2, encoding="utf-8")

    def answer(params: dict[str, Any]) -> str:
        """The operator at the other end of `ask_user`.

        Its return is the stable, server-sent label the pinned summary records
        as a decision (§B-12: "the question and the selected label").
        """
        assert params["question"] == QUESTION
        return ANSWER

    harness = G2Harness(project, sidecar_dist, summarizer=summarize, answerer=answer)
    seen: dict[str, dict[str, Any]] = {}

    def set_params_step(info: RequestInfo) -> dict[str, Any]:
        # The previous tool result in context is `read_part`'s.
        seen["read_part"] = last_tool_result(info)
        state_hash = str(seen["read_part"]["part_param_state_hash"])
        return tool_call(
            "set_params",
            {"name": "widget2", "values": {"w": NEW_WIDTH}, "expected_state_hash": state_hash},
            "call_set",
        )

    def run_checks_step(info: RequestInfo) -> dict[str, Any]:
        seen["set_params"] = last_tool_result(info)
        return tool_call("run_checks", {"scope": "part", "name": "widget2"}, "call_checks")

    def done_step(info: RequestInfo) -> dict[str, Any]:
        seen["run_checks"] = last_tool_result(info)
        return text("done")

    try:
        session_id = harness.create_session("orchestrator", session_id="g2-context-cad-aware")
        harness.set_script(
            [
                tool_call(
                    "ask_user",
                    {"question": QUESTION, "options": ["9.5 mm", "20 mm"]},
                    "call_ask",
                ),
                tool_call("read_part", {"name": "widget2"}, "call_read"),
                set_params_step,
                run_checks_step,
                done_step,
            ]
        )
        result = harness.prompt(session_id, "set the width and re-run checks", timeout=600)
        assert result.status == "completed"

        assert seen["set_params"]["effective"]["w"] == NEW_WIDTH, (
            "set_params did not apply — test setup bug"
        )
        assert seen["run_checks"]["checks"]["min_width"]["pass"] is False, (
            "min_width did not fail — test setup bug"
        )

        # Pi's own `compact()` refuses a session with no cut point ("Nothing to
        # compact") — the same reason the first test in this file pads with
        # bulk turns before compacting. This test cares about CONTENT, not the
        # keep-recent boundary, so any bulk that clears Pi's cut-point floor
        # will do.
        for i in range(14):
            harness.set_script([text(f"turn {i}: " + FILLER)])
            assert harness.prompt(session_id, f"context {i}: " + FILLER, timeout=300).status == (
                "completed"
            )

        compact = harness.runtime.sidecar_call(
            "session.compact", {"session_id": session_id}, timeout=300
        )
        assert compact["summary"], "compaction produced no summary"

        assert summarizations, "no summarization request was issued"
        instructed = [info for info in summarizations if PINNED_OPEN in info.body_text]
        assert instructed, "the compaction request carried no pinned CAD summary"
        span = _pinned_span(instructed[0].body_text)
        # A decision the OPERATOR took, recorded from the answered question —
        # not readable from the prompt at all, and the section `stubSummary`
        # always rendered as "- (none)".
        decisions = span.split("Decisions:", 1)[1].split("Open problems:", 1)[0]
        assert "(none)" not in decisions, "the pinned summary records no decision"
        assert QUESTION in decisions and ANSWER in decisions, (
            "the pinned decision does not name the question and the selected label"
        )
        assert str(NEW_WIDTH) in span, (
            "pinned span is missing the parameter value set_params applied "
            "— the summary is not tracking current params"
        )
        assert "min_width" in span, (
            "pinned span is missing the failing check name — the summary is "
            "not tracking check status/open problems"
        )
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_image_eviction_keeps_only_the_three_most_recent_renders(harness: G2Harness) -> None:
    (harness.project_root / "parts" / "widget.py").write_text(WIDGET, encoding="utf-8")
    bodies: list[str] = []

    def inspect(index: int) -> Any:
        def turn(info: RequestInfo) -> dict[str, Any]:
            bodies.append(info.body_text)
            return tool_call("inspect_part", {"name": "widget", "views": ["iso"]}, f"call_{index}")

        return turn

    harness.set_script(
        [
            tool_call("build_part", {"name": "widget"}, "call_b"),
            inspect(1),
            inspect(2),
            inspect(3),
            inspect(4),
            lambda info: (bodies.append(info.body_text), text("done"))[1],
        ]
    )
    session_id = harness.create_session("orchestrator", session_id="g2-eviction")
    result = harness.prompt(session_id, "inspect the widget four times", timeout=1200)
    assert result.status == "completed"

    inspections = harness.recorder.by_tool("inspect_part")
    assert len(inspections) == 4
    final = bodies[-1]

    # K=3: only the three most recent inspect results keep their image blocks…
    # One image content block renders as a single {"type":"image_url", …} entry.
    live_renders = final.count('"type":"image_url"')
    assert live_renders == 3, f"expected 3 live renders in context, found {live_renders}"
    # …and the evicted one is replaced by its exact text stub.
    assert "superseded — re-run inspect_part to view" in final
    assert "[render: widget iso/rgb, superseded" in final

    # The immutable artifacts stay on disk regardless of context eviction.
    renders = harness.project_root / ".heph"
    assert renders.is_dir()
