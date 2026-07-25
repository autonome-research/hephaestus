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

from _g2 import G2Harness, RequestInfo, text, tool_call

#: Enough bulk per turn that a handful of turns crosses Pi's keep-recent window.
FILLER = "Consider the shelf load path and the gusset stiffness carefully. " * 200

DECISION = "the gusset is 4 mm thick"

WIDGET = """PARAMS = {"w": Param(20.0, min=5.0, max=50.0)}

body = Box(p.w, 10.0, 4.0)
body.label = "body"
part.geometry = body
"""

#: The five sections STAGE2_DIGEST §1 requires in the pinned CAD summary.
PINNED_SECTIONS = (
    "Design intent:",
    "Decisions:",
    "Open problems:",
    "Current params:",
    "Check status:",
)


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
        assert "<</HEPHAESTUS_PINNED_SUMMARY>>" in body, "pinned summary is not delimited"
        # It is a *pinned* summary: the summarizer sees the decision it must keep.
        assert DECISION in body

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
