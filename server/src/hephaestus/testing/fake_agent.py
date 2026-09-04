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
from hephaestus.agent_bridge.supervisor import SupervisorError
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
        #: Every ``(text, context)`` pair this backend was prompted with, in
        #: order. §7A.4's invariant is **about the split**, so a test that could
        #: only see the joined string could not tell a compliant caller from one
        #: that prepended the block — this records the two halves as the route
        #: passed them.
        self.prompts: list[tuple[str, str | None]] = []
        self.rebinds = 0
        self.closed = False
        # -- §23 credential state ------------------------------------------
        #: What a signed-in provider holds, keyed by provider id. The literal
        #: key is retained on purpose: the §23.14 item 12 leak test needs a
        #: double that *has* a secret, or a read side that started echoing one
        #: would still pass.
        self.credentials: dict[str, dict[str, str]] = {}
        #: Live login flows, in the sidecar's own projection shape.
        self.flows: dict[str, dict[str, Any]] = {}
        #: Pi's built-in catalog, as ``providers.list`` reports it.
        self.catalog: list[dict[str, Any]] = []
        #: §23.7's per-provider verification from the last configure.
        self.verified: list[dict[str, Any]] = []
        #: Run ids the ``runs_in_flight`` refusal should name.
        self.live_runs: list[str] = []
        #: Every ``restart(reason=…)`` this backend was asked for, in order.
        self.restarts: list[str] = []
        #: Every ``login_complete`` paste, so a leak grep can see where it went.
        self.completions: list[tuple[str, str]] = []
        #: §23.8's axis 2 per provider: ``{"health": …, "at": …}``. Written by a
        #: test standing in for a turn that actually reached the provider.
        self.observed: dict[str, dict[str, Any]] = {}
        self._credential_failure: tuple[str, int] | None = None

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
        context: str | None = None,
        answerer: Callable[[dict[str, Any]], Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        timeout: float | None = None,
    ) -> PromptResult:
        run = run_id or self.new_run_id()
        with self._lock:
            self._run_sessions[run] = session_id
            self.prompts.append((text, context))
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

    def history_page(
        self, session_id: str, cursor: str | None = None, after: str | None = None
    ) -> dict[str, Any]:
        """One page over a frozen high-water mark, cursor shape and all.

        The high-water mark is frozen on page 1 and later pages never cross it,
        which is what makes the cursor restart-stable; the page size is the
        sidecar's and is **not** selectable by the caller (§2.8).

        ``after`` is §2.8(5)'s tail read: it freezes a *new* mark at the current
        last entry and starts at the ordinal the token names, and ``end_cursor``
        is always present and never null — even on the last page and on an
        empty session — so a client can always hand it back. An ``after`` at or
        beyond the current end returns no events, ``done``, and the same
        ``end_cursor`` it was given, which is what makes polling the tail cheap.
        """
        self.seen_cursors.append(cursor)
        events = self.history.get(session_id, [])
        if after is not None:
            decoded = decode_cursor(after)
            offset = int(decoded["offset"])
            if offset >= len(events):
                return {
                    "events": [],
                    "user_prompts": [],
                    "cursor": None,
                    "done": True,
                    "end_cursor": after,
                }
            hw = f"e{len(events) - 1}"
        elif not events:
            return {
                "events": [],
                "user_prompts": [],
                "cursor": None,
                "done": True,
                "end_cursor": encode_cursor("e0", 0),
            }
        elif cursor is None:
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
            # The real sidecar's page always carries the additive prompt list
            # (§2.8(2)); the fake seeds no prompts, so it is empty but present,
            # which keeps the fake's page shape the real page's shape.
            "user_prompts": [],
            "cursor": None if done else encode_cursor(hw, next_offset),
            "done": done,
            "end_cursor": encode_cursor(hw, next_offset),
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

    # -- credentials (§23), satisfying ``http.agent_credentials.CredentialBackend``
    #
    # A scripted Pi, not a reimplemented one. What it doubles is the *store*: a
    # dict where ``AuthStorage`` would be, and a flow object where Pi's login
    # conversation would be. What it does NOT double is the shape of anything
    # that crosses the bridge — the projections below are the sidecar's own,
    # field for field, so a route asserted against this double is asserted
    # against the wire the real sidecar speaks.
    #
    # **The double holds a secret and the tests rely on that.** §23.14 item 12's
    # leak test signs in with a sentinel literal and greps for it; a double that
    # discarded the key could not fail that test if the read side started
    # echoing one.

    def credential_failure(self, code: str, http_status: int) -> None:
        """Script the next credential relay to refuse with a named code."""
        self._credential_failure = (code, http_status)

    def _maybe_fail(self) -> None:
        failure = self._credential_failure
        if failure is None:
            return
        self._credential_failure = None
        code, http_status = failure
        raise SupervisorError(
            f"scripted credential refusal: {code}",
            error={
                "code": -32600,
                "message": code,
                "data": {"code": code, "http_status": http_status},
            },
        )

    def provider_catalog(self) -> dict[str, Any]:
        self._maybe_fail()
        return {"catalog": list(self.catalog), "verified": self.provider_status()}

    def provider_status(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.verified]

    def credential_status(self, provider_id: str) -> dict[str, Any]:
        self._maybe_fail()
        held = self.credentials.get(provider_id)
        observed = self.observed.get(provider_id)
        return {
            "provider_id": provider_id,
            "state": "none" if held is None else held["scope"],
            # §23.8's axis 2, and it is a MEMORY of a turn rather than a probe:
            # the double never asks a provider anything either, so a test that
            # sees a health here saw one a scripted turn recorded.
            "health": "unused" if observed is None else observed["health"],
            "last_observed_at": None if observed is None else observed["at"],
            "configured": held is not None,
            **({} if held is None else {"type": "api_key"}),
            **({} if provider_id not in self.flows else {"flow": dict(self.flows[provider_id])}),
        }

    def set_api_key(self, provider_id: str, key: str, *, scope: str) -> dict[str, Any]:
        self._maybe_fail()
        previous = self.credentials.get(provider_id)
        self.credentials[provider_id] = {"key": key, "scope": scope}
        return {
            "ok": True,
            "provider_id": provider_id,
            "scope": scope,
            "replaced": "none" if previous is None else str(previous["scope"]),
        }

    def sign_out(self, provider_id: str) -> dict[str, Any]:
        self._maybe_fail()
        self.credentials.pop(provider_id, None)
        self.flows.pop(provider_id, None)
        return {"ok": True, "provider_id": provider_id, "state": "none"}

    def login_begin(self, provider_id: str, flow_type: str) -> dict[str, Any]:
        self._maybe_fail()
        live = self.flows.get(provider_id)
        if live is not None and str(live.get("state")) not in {"complete", "failed", "cancelled"}:
            raise SupervisorError(
                "login_already_in_progress",
                error={
                    "code": -32600,
                    "message": "login_already_in_progress",
                    "data": {"code": "login_already_in_progress", "http_status": 409},
                },
            )
        flow: dict[str, Any] = {"provider_id": provider_id, "type": flow_type}
        if flow_type == "device_code":
            flow.update(
                state="authorization_pending",
                user_code="HEPH-TEST",
                verification_uri="https://provider.example/device",
                interval_seconds=5,
                expires_at=2_000_000_000,
            )
        else:
            flow.update(
                state="awaiting_input",
                authorize_url="https://provider.example/authorize?state=opaque",
                expires_at=2_000_000_000,
            )
        self.flows[provider_id] = flow
        return dict(flow)

    def login_status(self, provider_id: str) -> dict[str, Any]:
        self._maybe_fail()
        flow = self.flows.get(provider_id)
        return {"ok": True, "flow": None if flow is None else dict(flow)}

    def login_complete(self, provider_id: str, text: str) -> dict[str, Any]:
        self._maybe_fail()
        flow = self.flows.get(provider_id)
        if flow is None:
            raise SupervisorError(
                "authorization_expired",
                error={
                    "code": -32600,
                    "message": "authorization_expired",
                    "data": {"code": "authorization_expired", "http_status": 409},
                },
            )
        # The double verifies nothing about the paste: Pi does that, and a
        # double that re-implemented `state` verification would be testing the
        # double. It records the text so a leak grep can see it never escaped.
        self.completions.append((provider_id, text))
        flow["state"] = "complete"
        self.credentials[provider_id] = {"key": "oauth-token-held-by-pi", "scope": "project"}
        return dict(flow)

    def login_cancel(self, provider_id: str) -> dict[str, Any]:
        flow = self.flows.get(provider_id)
        if flow is not None:
            flow["state"] = "cancelled"
        return {"ok": True, "flow": None if flow is None else dict(flow)}

    def live_run_ids(self) -> list[str]:
        return list(self.live_runs)

    def restart(self, *, reason: str = "manual") -> None:
        self.restarts.append(reason)

    # -- the rest of the protocol -----------------------------------------

    def rebind_project(self, *, layout: Any, project_store: Any, cad: Any, dispatcher: Any) -> None:
        self.rebinds += 1

    def close(self) -> None:
        self.closed = True
