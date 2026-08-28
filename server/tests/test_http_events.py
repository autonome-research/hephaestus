# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``GET /events`` — the non-durable observer and its 4409 protocol (§2.7).

Every assertion here is about a decision the spec makes explicitly, and each is
written so that reversing the decision breaks the test rather than merely
changing a number:

* the wire shape is the Python-side shape **verbatim**, plus exactly one
  envelope field (``session_id``);
* only the normalized public vocabulary crosses; bridge frames never do;
* an observer that overflows is **dropped**, not backpressure-cancelled — the
  run survives and a durable client attached to the same pump is untouched;
* ``progress`` coalesces (it is the only droppable kind) and durable kinds never
  do;
* ``resume`` replays what the **live buffer** still holds, and nothing more —
  history never closes a live gap.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.events import BUFFERED_EVENTS_MAX, EVENT_KINDS
from hephaestus.http.events_ws import CONTROL_FRAME_KEYS
from hephaestus.testing.workspace import workspace
from starlette.websockets import WebSocketDisconnect


def _drain(socket: Any, count: int) -> list[dict[str, Any]]:
    return [dict(socket.receive_json()) for _ in range(count)]


def test_the_upgrade_requires_a_bearer_and_is_refused_before_accept(tmp_path: Path) -> None:
    """§2.2: the bearer rides on every request **including the WS upgrade**.

    Refused at the handshake rather than accepted-then-closed: an accepted socket
    would confirm to an unauthenticated caller that a stream exists here.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        with pytest.raises(WebSocketDisconnect), web.events(token=None) as socket:
            socket.receive_json()
        with pytest.raises(WebSocketDisconnect), web.events(token="not-the-token") as socket:
            socket.receive_json()


def test_a_browser_may_present_the_bearer_as_a_subprotocol(tmp_path: Path) -> None:
    """The recorded deviation, tested in both directions.

    A browser cannot set a header on a WebSocket upgrade, so the token rides as
    the second subprotocol value; the property §2.2 argues for — the token never
    enters an access log or a ``Referer`` — is preserved either way. The header
    form still works and is what the ``heph agent`` client uses.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        with web.events(subprotocol=True) as socket:
            socket.send_json({"subscribe": {"sessions": [session], "runs": []}})
            agent.prompt(session, "hi", run_id="run-sub")
            agent.emit("run-sub", 0, "text_delta", payload={"text": "hello"})
            frame = socket.receive_json()
        assert frame["session_id"] == session


def test_the_wire_frame_is_the_python_shape_plus_exactly_one_envelope_field(
    tmp_path: Path,
) -> None:
    """§2.7: ``{run_id, seq, kind, tool_call_id?, payload?}`` + ``session_id``.

    Set equality on the key set, not containment: a web-specific field added
    "just for the panel" is exactly what this row of the spec forbids, and it
    would pass a containment check.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        with web.events() as socket:
            agent.prompt(session, "go", run_id="run-1")
            agent.emit("run-1", 0, "text_delta", payload={"text": "hi"})
            agent.emit("run-1", 1, "tool_call", payload={"name": "build_part"}, tool_call_id="c0")
            agent.emit("run-1", 2, "audit")
            frames = _drain(socket, 3)

    assert set(frames[0]) == {"run_id", "seq", "kind", "session_id", "payload"}
    assert set(frames[1]) == {"run_id", "seq", "kind", "session_id", "payload", "tool_call_id"}
    # An event with neither a payload nor a tool_call_id carries neither key —
    # the Python-side shape omits them rather than sending nulls.
    assert set(frames[2]) == {"run_id", "seq", "kind", "session_id"}
    assert [f["kind"] for f in frames] == ["text_delta", "tool_call", "audit"]
    assert {f["session_id"] for f in frames} == {session}
    assert all(f["kind"] in EVENT_KINDS for f in frames)


def test_an_unroutable_run_carries_a_null_session_id_not_a_guess(tmp_path: Path) -> None:
    """The envelope field is a *named absence* when the binding is unknown.

    Attributing an unrouted event to whichever session the panel happens to be
    rendering would put one run's output in another's transcript.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        with web.events() as socket:
            agent.emit("run-orphan", 0, "audit", payload={"event": "compaction"})
            frame = socket.receive_json()
    assert frame["session_id"] is None


def test_subscribe_filters_by_session_and_by_run(tmp_path: Path) -> None:
    """§2.7's ``subscribe`` frame; the two lists are a union, not an intersection."""
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        watched = agent.create_session("orchestrator")
        other = agent.create_session("part", part="widget")
        agent.prompt(watched, "a", run_id="run-watched")
        agent.prompt(other, "b", run_id="run-other")
        with web.events() as socket:
            socket.send_json({"subscribe": {"sessions": [watched], "runs": []}})
            # Wake the writer so the subscribe is applied before anything is
            # emitted: control frames and events are processed by one task, in
            # order, so a frame emitted after this one cannot outrun it.
            agent.emit("run-watched", 0, "text_delta", payload={"text": "kept"})
            first = socket.receive_json()
            agent.emit("run-other", 0, "text_delta", payload={"text": "dropped"})
            agent.emit("run-watched", 1, "text_delta", payload={"text": "kept too"})
            second = socket.receive_json()
    assert [first["seq"], second["seq"]] == [0, 1]
    assert {first["session_id"], second["session_id"]} == {watched}


def test_progress_coalesces_and_durable_kinds_do_not(tmp_path: Path) -> None:
    """Only ``progress`` is droppable; the observer gets the pump's own policy.

    ``progress`` collapses to the latest per ``(run_id, kind, tool_call_id)`` —
    treating it as durable in the DOM would misrepresent the stream (§7.3) — and
    every other kind arrives whole.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.prompt(session, "x", run_id="run-p")
        observer = agent.add_observer("unit")
        for seq in range(5):
            agent.emit("run-p", seq, "progress", payload={"n": seq}, tool_call_id="c0")
        agent.emit("run-p", 5, "tool_result", payload={"toolName": "build_part"}, tool_call_id="c0")
        drained = observer.drain()
    kinds = [event.kind for event in drained]
    assert kinds.count("progress") == 1, "progress must coalesce to the latest"
    assert kinds.count("tool_result") == 1
    latest = next(event for event in drained if event.kind == "progress")
    assert latest.payload == {"n": 4}


def test_overflow_drops_the_observer_with_4409_and_never_cancels_the_run(
    tmp_path: Path,
) -> None:
    """§2.7's whole second decision, asserted as a difference between clients.

    A *durable* client's overflow backpressure-cancels the run; an **observer**'s
    overflow drops the observer. Both are attached to the same pump here, and
    only one of them is a cancel signal — which is the property that keeps a
    stalled browser tab from killing an agent's work.
    """
    cancelled: list[str] = []
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        agent.pump._cancel_run = cancelled.append  # pyright: ignore[reportPrivateUsage]
        session = agent.create_session("orchestrator")
        agent.prompt(session, "flood", run_id="run-flood")
        observer = agent.add_observer("greedy")
        for seq in range(BUFFERED_EVENTS_MAX + 5):
            agent.emit("run-flood", seq, "text_delta", payload={"text": "x"})

        assert observer.resync_required is True
        assert cancelled == [], "an observer's overflow must never cancel the run"
        # Dropped from the pump: a further event does not reach it at all.
        before = observer.queue.size
        agent.emit("run-flood", 9999, "text_delta", payload={"text": "after"})
        assert observer.queue.size == before

        # Everything buffered is still deliverable — the socket drains before it
        # closes, so a resync loses only what arrived AFTER the drop. The count
        # is the bound plus the one event that tipped it: ``PerClientQueue.push``
        # appends first and reports the overflow, so the tipping event is kept
        # rather than discarded. Keeping it is the right half of the tradeoff —
        # it is a durable kind, and the client is about to be told to resync.
        assert len(observer.drain()) == BUFFERED_EVENTS_MAX + 1


class _StalledSocket:
    """A WebSocket whose ``send`` blocks — a browser tab that stopped reading.

    This is the shape backpressure actually takes on a live socket, and getting
    it right is the difference between testing §2.7 and testing nothing. An
    observer whose transport keeps up **never overflows**: the writer drains the
    1024-slot queue into the socket faster than the pump fills it, so no flood,
    however large, trips the bound. The queue only fills when the transport
    itself stops consuming — which is exactly the stalled tab §2.7 is about.
    """

    def __init__(self, token: str) -> None:
        self.headers = {"authorization": f"Bearer {token}"}
        self.sent: list[dict[str, Any]] = []
        self.closed: tuple[int, str | None] | None = None
        self.gate = asyncio.Event()
        self.first_send = asyncio.Event()

    async def accept(self, subprotocol: str | None = None) -> None:
        return None

    async def receive_text(self) -> str:
        await asyncio.Event().wait()  # the client never sends a control frame
        raise AssertionError("unreachable")

    async def send_json(self, data: dict[str, Any]) -> None:
        self.first_send.set()
        await self.gate.wait()
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = (code, reason)


def test_the_socket_closes_4409_resync_required_when_the_transport_stalls(
    tmp_path: Path,
) -> None:
    """The transport half of §2.7's second decision, driven deterministically."""
    from hephaestus.agent_bridge.events import RESYNC_CLOSE_CODE, RESYNC_CLOSE_REASON
    from hephaestus.http.events_ws import serve_events
    from hephaestus.testing.workspace import WORKSPACE_TOKEN

    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        sessions = web.runtime.sessions
        assert agent is not None and sessions is not None
        session = agent.create_session("orchestrator")
        agent.prompt(session, "flood", run_id="run-stall")
        socket = _StalledSocket(WORKSPACE_TOKEN)
        cancelled: list[str] = []
        agent.pump._cancel_run = cancelled.append  # pyright: ignore[reportPrivateUsage]

        async def scenario() -> None:
            served = asyncio.create_task(
                serve_events(cast("Any", socket), sessions, WORKSPACE_TOKEN)
            )
            # The handler registers its observer before it accepts, so waiting
            # for the registration — rather than for a sleep — is what makes the
            # rest of this deterministic.
            while agent.pump.observer_count() == 0:
                await asyncio.sleep(0)
            # One event gets the writer into `send_json`, where it now blocks.
            agent.emit("run-stall", 0, "text_delta", payload={"text": "first"})
            await asyncio.wait_for(socket.first_send.wait(), timeout=5)
            # The tab is stalled; the pump keeps fanning. Past the bound the
            # observer is dropped — and the RUN is untouched.
            for seq in range(1, BUFFERED_EVENTS_MAX + 3):
                agent.emit("run-stall", seq, "text_delta", payload={"text": "x"})
            socket.gate.set()
            await asyncio.wait_for(served, timeout=5)

        asyncio.run(scenario())

    assert socket.closed == (RESYNC_CLOSE_CODE, RESYNC_CLOSE_REASON)
    assert cancelled == [], "a stalled observer must not cancel the run"
    # Everything that fit was delivered before the close: a resync loses only
    # what overflowed, and the client is told, not left guessing.
    assert socket.sent, "the observer must be drained before its socket closes"


def test_resume_replays_the_live_buffer_and_never_history(tmp_path: Path) -> None:
    """§2.7: "replays whatever the live buffer still holds" — and only that.

    The session's *history* here is deliberately non-empty and disjoint from the
    live events; a resume that reached into it would show up as historical
    identities on a live socket, which is the merge §2.8 forbids.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.seed_history(session, 10)
        agent.prompt(session, "go", run_id="run-r")
        for seq in range(4):
            agent.emit("run-r", seq, "text_delta", payload={"text": f"live {seq}"})

        with web.events() as socket:
            socket.send_json(
                {"resume": {"session_id": session, "after": {"run_id": "run-r", "seq": 1}}}
            )
            replayed = _drain(socket, 2)

    assert [f["seq"] for f in replayed] == [2, 3]
    # Live identities only: every replayed frame names the RUN, never the session
    # id that a historical event would carry in `run_id`.
    assert {f["run_id"] for f in replayed} == {"run-r"}


def test_resume_with_a_cursor_the_buffer_lost_returns_a_suffix_not_a_repair(
    tmp_path: Path,
) -> None:
    """The honest branch: a gap is a gap, and the client labels it.

    Nothing is fabricated to bridge it and nothing is pulled from history; the
    client sees the seq jump and renders §7.4's ``resyncing`` break.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.prompt(session, "go", run_id="run-gap")
        for seq in range(3):
            agent.emit("run-gap", seq, "text_delta", payload={"text": str(seq)})
        buffered, contiguous = web.runtime.sessions.buffer.replay(  # type: ignore[union-attr]
            session, ("run-gap", 999)
        )
    assert contiguous is False
    assert [item.event.seq for item in buffered] == [0, 1, 2]


def test_the_live_buffer_is_bounded_and_survives_an_observer_being_dropped(
    tmp_path: Path,
) -> None:
    """The buffer is process-owned, fed by a tap, and cannot itself be dropped.

    Built as a pump *client* it would overflow and be dropped by the very event
    storm a reconnecting observer needs it to have survived.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        sessions = web.runtime.sessions
        assert sessions is not None
        session = agent.create_session("orchestrator")
        agent.prompt(session, "flood", run_id="run-buf")
        observer = agent.add_observer("doomed")
        for seq in range(BUFFERED_EVENTS_MAX + 50):
            agent.emit("run-buf", seq, "text_delta", payload={"text": "x"})
        assert observer.resync_required is True
        replay, _ = sessions.buffer.replay(session, None)
    assert len(replay) == sessions.buffer.bound
    assert replay[-1].event.seq == BUFFERED_EVENTS_MAX + 49


@pytest.mark.parametrize(
    "frame",
    [
        {"subscibe": {"sessions": []}},  # codespell:ignore subscibe
        {"subscribe": {}, "extra": 1},
        {},
    ],
)
def test_an_unknown_control_frame_is_refused_not_ignored(
    tmp_path: Path, frame: dict[str, Any]
) -> None:
    """§0.1's closed vocabularies reach the socket too.

    A silently-ignored ``{"subscibe": …}`` is a client that believes it filtered
    and did not — it would then render another session's transcript as its own.
    """
    with (
        workspace(tmp_path / "proj", agent=True) as web,
        pytest.raises(WebSocketDisconnect) as excinfo,
        web.events() as socket,
    ):
        socket.send_json(frame)
        socket.receive_json()
    assert excinfo.value.code == 1008


def test_a_non_json_frame_is_refused(tmp_path: Path) -> None:
    with (
        workspace(tmp_path / "proj", agent=True) as web,
        pytest.raises(WebSocketDisconnect) as excinfo,
        web.events() as socket,
    ):
        socket.send_text("not json")
        socket.receive_json()
    assert excinfo.value.code == 1008


def test_the_control_vocabulary_is_the_two_frames_the_spec_names() -> None:
    assert {"subscribe", "resume"} == CONTROL_FRAME_KEYS


def test_the_socket_refuses_when_no_agent_runtime_is_attached(tmp_path: Path) -> None:
    """A serve with no sidecar has no sessions, and says so by name."""
    with workspace(tmp_path / "proj") as web:
        with pytest.raises(WebSocketDisconnect), web.events() as socket:
            socket.receive_json()
        refused = web.get("/sessions")
    assert refused.status_code == 503
    assert refused.json()["reason"] == "agent_unavailable"
