# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""A ``SessionBackend`` with a **real** event pump and no Node sidecar.

``INTERFACE.md`` §14's Tier 1 half is pytest against ``server/http``, and §2.7's
subject — the non-durable observer, its 1024-slot bound, its ``progress``
coalescing, and the ``4409`` drop — is a property of
:class:`~hephaestus.agent_bridge.events.EventPump`, not of Node. So the pump here
is the shipped one, over the project's own admission control; what is doubled is
only the *source* of events: a scripted callback instead of a Pi session.

This is the seam that keeps §2.7's tests honest. A double that reimplemented
queueing would test the double; this one exercises the same ``add_observer`` /
``on_event`` / overflow path a real run drives, so a change to the pump's policy
breaks these tests exactly as it should.

What it does **not** double is history: :meth:`FakeAgent.history_page` pages a
list the test provides, minting the same opaque ``{hw, offset}`` base64url cursor
shape ``agent/src/session/history.ts`` mints, so the route can be asserted to
forward it **unmodified** and to expose no page-size parameter (§2.8).
"""

from __future__ import annotations

import base64
import itertools
import json
import threading
from collections.abc import Callable
from typing import Any, Final

from hephaestus.agent_bridge.app import PromptResult
from hephaestus.agent_bridge.events import EventPump, HephaestusEvent, ObserverClient
from opstore.admission import AdmissionControl

__all__ = ["HISTORY_PAGE_SIZE", "FakeAgent", "decode_cursor", "encode_cursor"]

#: Mirrors ``HISTORY_PAGE_SIZE`` in ``agent/src/session/history.ts``. Duplicated
#: as a *test* constant only — the route deliberately exposes no page size, so
#: nothing in the shipped Python reads this.
HISTORY_PAGE_SIZE: Final[int] = 250


def encode_cursor(hw: str, offset: int) -> str:
    """The sidecar's opaque cursor shape: base64url of ``{hw, offset}``."""
    raw = json.dumps({"hw": hw, "offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> dict[str, Any]:
    padded = token + "=" * (-len(token) % 4)
    loaded: Any = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    return dict(loaded)


class FakeAgent:
    """A scripted agent runtime satisfying ``hephaestus.http.sessions.SessionBackend``."""

    def __init__(self, admission: AdmissionControl) -> None:
        self.pump = EventPump(admission)
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._run_sessions: dict[str, str] = {}
        # Mirrors ``BridgeRuntime``'s per-run buffer: the synchronous prompt
        # caller gets the run's events back as well as the pump fanning them, so
        # a client with no socket still has something to render.
        self._run_events: dict[str, list[dict[str, Any]]] = {}
        self._runs = itertools.count(1)
        self._session_seq = itertools.count(1)
        #: ``(agent, session_id, run_id, text, answerer) -> None`` — the scripted
        #: body of one turn. Emit through :meth:`emit`; call ``answerer`` to
        #: exercise the suspended-``ask_user`` path.
        self.on_prompt: Callable[[FakeAgent, str, str, str, Any], None] | None = None
        #: Normalized historical events per session, as ``history.page`` would
        #: return them: identity ``(session_id, ordinal)``, ordinal from 0.
        self.history: dict[str, list[dict[str, Any]]] = {}
        #: Every cursor value this backend was handed, in order — so a test can
        #: assert the route forwarded it byte-for-byte.
        self.seen_cursors: list[str | None] = []
        self.cancelled: list[str] = []
        self.rebinds = 0
        self.closed = False

    # -- sessions ----------------------------------------------------------

    def create_session(
        self,
        profile: str,
        *,
        part: str | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> str:
        with self._lock:
            sid = session_id or f"sess-{next(self._session_seq)}"
            self._sessions[sid] = {"session_id": sid, "profile": profile, "part": part}
            return sid

    def sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._sessions.values()]

    def session_for_run(self, run_id: str) -> str | None:
        with self._lock:
            return self._run_sessions.get(run_id)

    # -- runs --------------------------------------------------------------

    def new_run_id(self) -> str:
        return f"run-{next(self._runs):04d}"

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = None,
        answerer: Callable[[dict[str, Any]], Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        timeout: float | None = None,
    ) -> PromptResult:
        run = run_id or self.new_run_id()
        with self._lock:
            self._run_sessions[run] = session_id
        script = self.on_prompt
        if script is not None:
            script(self, session_id, run, text, answerer)
        with self._lock:
            events = list(self._run_events.get(run, []))
        return PromptResult(run_id=run, status="completed", events=events, terminal=None)

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)

    # -- events ------------------------------------------------------------

    def emit(
        self,
        run_id: str,
        seq: int,
        kind: str,
        *,
        payload: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
    ) -> HephaestusEvent:
        """Fan one normalized event through the **real** pump."""
        event = HephaestusEvent(
            run_id=run_id, seq=seq, kind=kind, tool_call_id=tool_call_id, payload=payload
        )
        with self._lock:
            self._run_events.setdefault(run_id, []).append(
                {
                    "run_id": run_id,
                    "seq": seq,
                    "kind": kind,
                    **({} if tool_call_id is None else {"tool_call_id": tool_call_id}),
                    **({} if payload is None else {"payload": payload}),
                }
            )
        self.pump.on_event(event)
        return event

    def add_observer(
        self, client_id: str, *, notify: Callable[[], None] | None = None
    ) -> ObserverClient:
        return self.pump.add_observer(client_id, notify=notify)

    def drop_client(self, client_id: str) -> None:
        self.pump.remove_client(client_id)

    def add_event_tap(self, tap: Callable[[HephaestusEvent], None]) -> None:
        self.pump.add_tap(tap)

    # -- history -----------------------------------------------------------

    def history_page(self, session_id: str, cursor: str | None = None) -> dict[str, Any]:
        """One page over a frozen high-water mark, cursor shape and all.

        The high-water mark is frozen on page 1 and later pages never cross it,
        which is what makes the cursor restart-stable; the page size is the
        sidecar's and is **not** selectable by the caller (§2.8).
        """
        self.seen_cursors.append(cursor)
        events = self.history.get(session_id, [])
        if not events:
            return {"events": [], "cursor": None, "done": True}
        if cursor is None:
            hw, offset = f"e{len(events) - 1}", 0
        else:
            decoded = decode_cursor(cursor)
            hw, offset = str(decoded["hw"]), int(decoded["offset"])
        frozen = events[: int(str(hw).removeprefix("e")) + 1]
        page = frozen[offset : offset + HISTORY_PAGE_SIZE]
        next_offset = offset + len(page)
        done = next_offset >= len(frozen)
        return {
            "events": page,
            "cursor": None if done else encode_cursor(hw, next_offset),
            "done": done,
        }

    def seed_history(self, session_id: str, count: int) -> list[dict[str, Any]]:
        """Seed ``count`` normalized historical events with §2.8's identity.

        The identity is ``(session_id, ordinal)``: ``run_id`` carries the SESSION
        id — which is what ``main.ts`` passes into the parameter ``history.ts``
        names ``runId`` — and the ordinal restarts at 0. Nothing here mints a
        live-comparable ``(run_id, seq)``, because the two namespaces are
        disjoint and must never be merged.
        """
        events = [
            {
                "run_id": session_id,
                "seq": ordinal,
                "kind": "text_delta" if ordinal % 2 else "thought",
                "payload": {"text": f"entry {ordinal}"},
            }
            for ordinal in range(count)
        ]
        self.history[session_id] = events
        return events

    # -- the rest of the protocol -----------------------------------------

    def rebind_project(self, *, layout: Any, project_store: Any, cad: Any, dispatcher: Any) -> None:
        self.rebinds += 1

    def close(self) -> None:
        self.closed = True
