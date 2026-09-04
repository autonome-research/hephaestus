"""Two concurrent turns on two DIFFERENT sessions -> REAL Node sidecar -> Python core.

W5 (workflow handoff): the sidecar used to resolve every tool call's
``{session_id, run_id}`` through one module-global "current run" slot in
``agent/src/main.ts``, assigned at the top of the ``session.prompt`` handler and
cleared in that same call's ``finally``. ``BridgeRuntime._admit_turn`` (this
file's ``dispatch`` module) refuses a second live turn on the SAME session but
explicitly admits one on any OTHER session — INTERFACE.md §19.23: "a part
session and the orchestrator may now think at the same time" — so two
``session.prompt`` calls can be live on the one sidecar process together, and a
shared slot cannot survive that: whichever run's tool call happened to read the
slot got whichever OTHER run's identity was sitting in it.

This is the one place that failure is externally observable end to end: a
``py.tool_dispatch`` call is authorized by ``ToolDispatcher._authorize``
(``dispatch.py``) against the ``Principal`` named by ``params["session_id"]`` —
so a tool dispatch carrying the wrong session's id is not just a bookkeeping
error, it is authorized (or refused) as the WRONG SESSION. Concretely: a "part"
session is bound to one part and may not address another (``scope_denied``,
digest §2); the orchestrator may address every part. If a part turn's dispatch
ever carried the orchestrator's session id, its cross-part read would wrongly
SUCCEED instead of being refused — the sharpest, most production-real signal
this file can check for, so it is asserted alongside the raw identity check.

Drives the packaged sidecar exactly like ``test_e2e_fake_model.py`` (same
``Harness`` shape, same scripted ``FakeOpenAI``); the two turns run on real
threads, overlapped with a barrier the way ``test_request_binding.py`` overlaps
its two builds — this file's own regression is in the Node sidecar the other
file's is not exercising, not in the request-text binding that file already
covers.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, PromptResult
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.sidecar import build_agent_dist
from hephaestus.testing.stream_assertions import (
    assert_stream_shape,
    events_of,
    payload_of,
    text,
    tool_call,
)

#: session/profiles.ts PROFILE_PROMPT_NOTE — distinctive substrings that tell
#: the two sessions' model requests apart. FakeOpenAI's script is one shared
#: cursor consumed by BOTH sessions' HTTP calls in arrival order (mirrored
#: exactly by the agent-side FakeModel), so a resolver must identify its own
#: session from the request body rather than from its position in the script.
PART_MARKER = "You own exactly one part."
ORCH_MARKER = "You are the project orchestrator."

#: Readable by `read_part` without being buildable — this test never builds.
OTHER_PART_SRC = """PARAMS = {}

part.description = "the other part, addressed only by the orchestrator"
"""


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; the concurrency e2e needs the packaged sidecar")
    return built[0]


class Harness:
    """A started :class:`BridgeRuntime` plus its scripted fake provider."""

    def __init__(self, project_root: Path, dist_main: Path) -> None:
        self.project_root = project_root
        self.fake: FakeOpenAI = start_fake_openai([])
        self.runtime = BridgeRuntime(
            project_root=project_root,
            providers=[self.fake.provider_spec()],
            dist_main=dist_main,
        )
        self.runtime.start()
        self.child_pids: list[int] = [self.runtime.child_pid]

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.fake.close()

    def assert_no_orphans(self) -> None:
        for pid in self.child_pids:
            assert not pid_alive(pid), f"sidecar pid {pid} outlived the supervisor"


@pytest.fixture
def harness(tmp_path: Path, sidecar_dist: Path) -> Iterator[Harness]:
    project = scaffold_project(
        tmp_path / "proj",
        name="concurrency",
        globals_src="# Project-shared namespace for the concurrency e2e project.\nPARAMS = {}\n",
    )
    h = Harness(project, sidecar_dist)
    try:
        yield h
    finally:
        h.close()
        h.assert_no_orphans()


def test_two_concurrent_turns_keep_dispatch_identity_and_scope_per_session(
    harness: Harness,
) -> None:
    """Part and orchestrator prompt at once; neither's tool calls leak into the other's.

    The part session is bound to ``widget_a`` and both turns address the SAME
    third part, ``other`` — planted directly on disk (never built; ``read_part``
    only reads bytes) so the orchestrator's read has something real to succeed
    against. Object-scope authorization runs before existence is even checked
    (``dispatch.py`` ``_authorize``), so the part session is refused
    ``scope_denied`` regardless of whether ``other`` is there.
    """
    (harness.project_root / "parts" / "other.py").write_text(OTHER_PART_SRC, encoding="utf-8")

    # Spy on the dispatcher's own authorization entry point rather than reading
    # results back out of a rendered transcript: `_handle_tool_dispatch` is
    # exactly where `params["session_id"]` — whatever the sidecar attributed the
    # call to — becomes the `Principal` every scope check runs against
    # (INTERFACE.md's own reasoning for why this file's regression is
    # authorization-visible, not just a bookkeeping mismatch).
    observed: list[dict[str, Any]] = []
    original_handle = harness.runtime._handle_tool_dispatch  # pyright: ignore[reportPrivateUsage]

    def spying_handle(params: dict[str, Any]) -> Any:
        observed.append(
            {
                "session_id": params.get("session_id"),
                "run_id": params.get("run_id"),
                "tool": params.get("tool"),
            }
        )
        return original_handle(params)

    harness.runtime._handle_tool_dispatch = spying_handle  # type: ignore[method-assign] # pyright: ignore[reportPrivateUsage]

    def resolver(info: RequestInfo) -> dict[str, Any]:
        is_part = PART_MARKER in info.body_text
        is_orch = ORCH_MARKER in info.body_text
        assert is_part != is_orch, "resolver could not tell the two sessions' requests apart"
        if not info.has_tool_result:
            call_id = "part-read" if is_part else "orch-read"
            return tool_call("read_part", {"name": "other"}, call_id)
        # `scope_denied` is checked before existence (dispatch.py `_authorize`
        # runs ahead of `_route`), so this single substring tells the two
        # outcomes apart regardless of session ordering.
        denied = "scope_denied" in info.body_text
        label = "part_result" if is_part else "orch_result"
        return text(f"{label}:{'denied' if denied else 'ok'}")

    harness.fake.set_script([resolver] * 8)

    part_session = harness.runtime.create_session("part", part="widget_a", session_id="conc-part")
    orch_session = harness.runtime.create_session("orchestrator", session_id="conc-orch")
    part_run = harness.runtime.new_run_id()
    orch_run = harness.runtime.new_run_id()

    results: dict[str, PromptResult] = {}
    errors: list[BaseException] = []
    both_in = threading.Barrier(2, timeout=60)

    def turn(key: str, session_id: str, run_id: str) -> None:
        try:
            both_in.wait()  # neither turn starts until both threads are here
            results[key] = harness.runtime.prompt(
                session_id, "read the other part", run_id=run_id, timeout=300
            )
        except BaseException as exc:  # pragma: no cover - the regression itself
            errors.append(exc)

    threads = [
        threading.Thread(target=turn, args=("part", part_session, part_run)),
        threading.Thread(target=turn, args=("orch", orch_session, orch_run)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)
    assert errors == [], f"a concurrent turn crashed: {errors[0]!r}\n" + "".join(
        traceback.format_exception(errors[0])
    )

    assert results["part"].status == "completed"
    assert results["orch"].status == "completed"
    assert_stream_shape(results["part"])
    assert_stream_shape(results["orch"])

    # -- every observed tool dispatch names the session that started that run --
    expected_session = {part_run: part_session, orch_run: orch_session}
    assert len(observed) >= 2, observed
    for call in observed:
        assert call["run_id"] in expected_session, call
        assert call["session_id"] == expected_session[call["run_id"]], (
            f"py.tool_dispatch for run {call['run_id']} carried session "
            f"{call['session_id']!r}, expected {expected_session[call['run_id']]!r}: {call}"
        )

    # -- the same call, denied for the part session and allowed for the orchestrator --
    part_text = "".join(payload_of(ev)["text"] for ev in events_of(results["part"], "text_delta"))
    orch_text = "".join(payload_of(ev)["text"] for ev in events_of(results["orch"], "text_delta"))
    assert "part_result:denied" in part_text, part_text
    assert "orch_result:ok" in orch_text, orch_text

    # -- every streamed frame is still named by the run that actually produced it --
    for key, run_id in (("part", part_run), ("orch", orch_run)):
        for ev in results[key].events:
            assert ev["run_id"] == run_id, (key, ev)
