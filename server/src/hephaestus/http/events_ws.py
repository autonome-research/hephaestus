# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``GET /events`` — the live event stream (``INTERFACE.md`` §2.7).

One WebSocket per attached client, registered through the existing
:class:`~hephaestus.agent_bridge.events.EventPump` client API as a **non-durable
observer** (:class:`~hephaestus.agent_bridge.events.ObserverClient`). The socket
emits the **normalized public vocabulary only** — ``text_delta, thought,
tool_call, tool_result, image, question, answer, audit, progress, terminal``.
Bridge frames are never surfaced, no web-specific event kind is minted, and no
field is added to ``HephaestusEvent``: the wire shape is the Python-side shape
verbatim plus exactly one envelope field, ``session_id``.

**The 4409 protocol, and why it is this and not shared fate.** ``EventPump``'s
durable-overflow policy cancels the affected *run*. A stalled browser tab must
not kill an agent's work, and making the web client droppable is illegal — only
``progress`` is droppable. So an observer that overflows is dropped: its socket
closes with code ``4409`` / reason ``resync_required`` and the run continues
untouched. The client reconnects, replays whatever the live buffer still holds,
and renders anything the buffer dropped as a **labelled break** (§7.4's
``resyncing`` state). **The break is never healed from history** — the live and
historical identity namespaces are disjoint (see
:mod:`hephaestus.http.event_identity`), so a dedupe across them would never
match and every "refilled" event would render twice.

Honest cost, stated as the surface actually supports it: of the ten kinds,
``normalizeEntries`` can reconstruct five (``text_delta``, ``thought``,
``tool_call``, ``tool_result``, ``audit``), ``image`` as **metadata only**, and
``question`` / ``answer`` / ``terminal`` / ``progress`` **not at all**. Those
four are on the never-dropped list *within a live run*; that is a statement about
the pump's backpressure policy, not a claim that history can replay them.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Final, cast

from hephaestus.agent_bridge.events import (
    RESYNC_CLOSE_CODE,
    RESYNC_CLOSE_REASON,
    HephaestusEvent,
    ObserverClient,
)
from starlette.websockets import WebSocket, WebSocketDisconnect

from .principal import verify_token
from .sessions import WorkspaceSessions, passes_filter

__all__ = [
    "BEARER_SUBPROTOCOL",
    "CONTROL_FRAME_KEYS",
    "INVALID_FRAME_CLOSE_CODE",
    "UNAUTHORIZED_CLOSE_CODE",
    "serve_events",
]

#: The closed set of client→server control frames. A frame carrying anything
#: else is refused rather than ignored: §0.1's closed vocabularies apply to the
#: socket exactly as they apply to the route table, and a silently-ignored
#: ``{"subscibe": …}`` is a client that believes it filtered and did not.
CONTROL_FRAME_KEYS: Final[frozenset[str]] = frozenset({"subscribe", "resume"})

#: Standard policy-violation close for a malformed or unknown control frame.
INVALID_FRAME_CLOSE_CODE: Final[int] = 1008

#: …and for a socket that never presented a usable bearer.
UNAUTHORIZED_CLOSE_CODE: Final[int] = 1008

#: DEVIATION, recorded rather than smuggled (see the module note in ``app.py``).
#: §2.2 says the app "sends ``Authorization: Bearer …`` on every request
#: including the WS upgrade". A browser **cannot** set a header on a WebSocket
#: upgrade — the API has no place to put one — so the header alone would make the
#: normative auth unimplementable by the one client this exists for. The standard
#: technique is used instead: the token rides as a second subprotocol value. It
#: preserves the property §2.2 actually argues for — the token never enters an
#: access log or a ``Referer``, which is why the fragment was chosen over a query
#: string — and the header remains accepted and is what non-browser clients (the
#: ``heph agent`` client mode) use.
BEARER_SUBPROTOCOL: Final[str] = "hephaestus.bearer"


def _bearer(websocket: WebSocket) -> tuple[str, bool] | None:
    """The presented bearer and whether it arrived as a subprotocol.

    The header is checked first — it is §2.2's normative form and what a
    non-browser client uses. The second element decides what is echoed back on
    ``accept``: a subprotocol a server does not echo is one the browser treats as
    unnegotiated, so the two halves must agree exactly.
    """
    header = websocket.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip(), False
    offered = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    if len(offered) >= 2 and offered[0] == BEARER_SUBPROTOCOL and offered[1]:
        return offered[1], True
    return None


class _Subscription:
    """One socket's filter and resume state, mutated only by the writer task."""

    def __init__(self) -> None:
        self.session_ids: list[str] = []
        self.run_ids: list[str] = []
        #: Identities already sent by a ``resume`` replay, so the drain that
        #: follows cannot send the same event twice. Bounded by the live
        #: buffer's own bound.
        self.replayed: set[tuple[str, int]] = set()


async def serve_events(websocket: WebSocket, sessions: WorkspaceSessions, token: str) -> None:
    """Serve one ``GET /events`` socket for its whole lifetime."""
    presented = _bearer(websocket)
    if presented is None or not verify_token(presented[0], token):
        # Refused **before** ``accept``: an unauthenticated upgrade is denied at
        # the handshake (the client sees an HTTP rejection), never accepted and
        # then closed, which would leak the existence of a valid stream.
        await websocket.close(code=UNAUTHORIZED_CLOSE_CODE, reason="unauthorized")
        return
    _presented_token, via_subprotocol = presented

    loop = asyncio.get_running_loop()
    ready = asyncio.Event()

    def notify() -> None:
        loop.call_soon_threadsafe(ready.set)

    # Registered BEFORE the handshake completes, so a client that has seen its
    # connection succeed is already attached: an observer registered after
    # ``accept`` would silently miss every event of a run started in the window
    # between the two, which is precisely G4.8's round trip.
    observer = sessions.attach_observer(notify)
    await websocket.accept(subprotocol=BEARER_SUBPROTOCOL if via_subprotocol else None)

    subscription = _Subscription()
    control: list[dict[str, Any]] = []
    control_lock = asyncio.Lock()
    closed = asyncio.Event()

    async def reader() -> None:
        """Receive control frames; never sends, so all sends stay ordered."""
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    parsed: Any = json.loads(raw)
                except ValueError:
                    await _refuse(websocket, "frame is not valid JSON")
                    return
                if not isinstance(parsed, dict):
                    await _refuse(websocket, "frame must be a JSON object")
                    return
                frame = cast("dict[str, Any]", parsed)
                unknown = set(frame) - CONTROL_FRAME_KEYS
                if unknown or not frame:
                    await _refuse(
                        websocket,
                        f"unknown control frame keys {sorted(unknown)}; "
                        f"expected one of {sorted(CONTROL_FRAME_KEYS)}",
                    )
                    return
                async with control_lock:
                    control.append(frame)
                ready.set()
        except WebSocketDisconnect:
            return
        finally:
            closed.set()
            ready.set()

    async def writer() -> None:
        """The ONLY task that sends: control effects, then buffered events."""
        while not closed.is_set():
            await ready.wait()
            ready.clear()
            if closed.is_set():
                # Woken by the reader's own teardown, not by an event: the peer
                # is gone and a send would raise instead of reaching anyone.
                return
            async with control_lock:
                pending, control[:] = list(control), []
            for frame in pending:
                await _apply_control(websocket, sessions, subscription, frame)
            for wire in _drain(sessions, observer, subscription):
                await websocket.send_json(wire)
            if observer.resync_required:
                # Everything that FIT has been delivered first; only then is the
                # socket closed. The run is untouched and no other client is
                # affected — that is the whole of §2.7's second decision.
                await websocket.close(code=RESYNC_CLOSE_CODE, reason=RESYNC_CLOSE_REASON)
                return

    reader_task = asyncio.create_task(reader())
    writer_task = asyncio.create_task(writer())
    try:
        done, pending_tasks = await asyncio.wait(
            {reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending_tasks:
            task.cancel()
        for task in done:
            task.result()
    except (WebSocketDisconnect, RuntimeError):
        # The peer went away mid-send. Nothing to report: the observer is
        # non-durable by construction and its disappearance costs the run
        # nothing, which is the entire point of §2.7's client class. Starlette
        # raises ``RuntimeError`` for a send that races the close it just sent,
        # which is the same event seen from the other side.
        pass
    finally:
        sessions.detach_observer(observer)


def _drain(
    sessions: WorkspaceSessions, observer: ObserverClient, subscription: _Subscription
) -> list[dict[str, Any]]:
    """Buffered events → filtered wire frames, minus anything already replayed."""
    out: list[dict[str, Any]] = []
    for event in observer.drain():
        identity = (event.run_id, event.seq)
        if identity in subscription.replayed:
            continue
        frame = sessions.wire_frame(event)
        if passes_filter(frame, session_ids=subscription.session_ids, run_ids=subscription.run_ids):
            out.append(frame)
    return out


async def _apply_control(
    websocket: WebSocket,
    sessions: WorkspaceSessions,
    subscription: _Subscription,
    frame: dict[str, Any],
) -> None:
    """Apply one ``subscribe`` / ``resume`` frame."""
    subscribe = frame.get("subscribe")
    if isinstance(subscribe, dict):
        body = cast("dict[str, Any]", subscribe)
        subscription.session_ids = _string_list(body.get("sessions"))
        subscription.run_ids = _string_list(body.get("runs"))
    resume = frame.get("resume")
    if isinstance(resume, dict):
        await _replay(websocket, sessions, subscription, cast("dict[str, Any]", resume))


async def _replay(
    websocket: WebSocket,
    sessions: WorkspaceSessions,
    subscription: _Subscription,
    resume: dict[str, Any],
) -> None:
    """Replay what the **live buffer** still holds after the client's cursor.

    Never more than that, and never from history: §2.7's tightening is that
    history is pre-attach backfill only. A cursor that has already fallen out of
    the ring returns the suffix the buffer *does* hold; the client sees the seq
    jump and renders §7.4's labelled break itself, which is the honest branch the
    spec chose over pricing an engine change.
    """
    session_id = resume.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        await _refuse(websocket, "resume requires a session_id")
        return
    after_raw = resume.get("after")
    after: tuple[str, int] | None = None
    if isinstance(after_raw, dict):
        cursor = cast("dict[str, Any]", after_raw)
        run_id = cursor.get("run_id")
        seq = cursor.get("seq")
        if isinstance(run_id, str) and isinstance(seq, int) and not isinstance(seq, bool):
            after = (run_id, seq)
    if session_id not in subscription.session_ids:
        subscription.session_ids = [*subscription.session_ids, session_id]
    # Only the drain that FOLLOWS this replay can duplicate it — every later
    # drain holds strictly newer events — so the set is reset per replay rather
    # than accumulated, which also bounds it at the live buffer's own bound
    # however many times a client resumes.
    subscription.replayed.clear()
    buffered, _contiguous = sessions.buffer.replay(session_id, after)
    for item in buffered:
        event: HephaestusEvent = item.event
        subscription.replayed.add((event.run_id, event.seq))
        await websocket.send_json(sessions.wire_frame(event, session_id=item.session_id))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in cast("list[Any]", value) if isinstance(item, str) and item]


async def _refuse(websocket: WebSocket, message: str) -> None:
    """Close a socket that sent a frame outside the closed control vocabulary."""
    await websocket.close(code=INVALID_FRAME_CLOSE_CODE, reason=message[:120])
