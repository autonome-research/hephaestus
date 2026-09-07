# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Sessions, the live buffer, and pending questions (``INTERFACE.md`` §2.7/§2.8).

Everything the workspace needs to *drive* and *watch* sessions, sitting on the
one runtime the serving process owns. There is no second session mechanism here:
`session.create`, `prompt`, `cancel`, and `history.page` are the bridge's own,
reached through :class:`SessionBackend`, which :class:`~hephaestus.agent_bridge.
app.BridgeRuntime` satisfies structurally.

Three things are genuinely new, and each is here because §2.7/§2.8 names it:

* **the live buffer** — a bounded, process-owned ring of recent events, fed by a
  pump *tap* rather than by a client queue. It is what a reconnecting observer's
  ``resume`` replays; built as a client it would be dropped by the very overflow
  it exists to recover from;
* **the run→session binding**, so the wire frame can carry §2.7's one envelope
  field (``session_id``) without a client inspecting payloads;
* **pending questions**, so ``ask_user`` can broadcast to every attached client
  and ``POST /sessions/{id}/answer`` can be idempotent on the question id with
  the first answer winning — the guarantee §2.3 says stands in for a key on that
  route.

What is *not* here: any parsing of Pi's session format (``STAGE2_DIGEST`` §2 —
nothing outside the sidecar ever does), any event kind or ``HephaestusEvent``
field of its own (§2.7 forbids both), and any inference of threading from the
event stream (§2.8 — the durable edge table is the only source).
"""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from hephaestus.agent_bridge.app import PromptResult
from hephaestus.agent_bridge.events import BUFFERED_EVENTS_MAX, HephaestusEvent, ObserverClient
from hephaestus.agent_bridge.session_edges import (
    THREAD_LINKED,
    THREAD_UNLINKED,
    SessionEdgeStore,
)
from opstore.errors import NotFoundError

from .errors import HttpRefusal

__all__ = [
    "CREATABLE_PROFILES",
    "LIVE_BUFFER_MAX",
    "PROMPT_EVENTS_MAX",
    "QUICK_EDIT_PROFILE",
    "SESSION_PROFILES",
    "SETTLED_QUESTIONS_MAX",
    "AskAbandoned",
    "LiveBuffer",
    "PendingQuestion",
    "PendingQuestions",
    "SessionBackend",
    "WorkspaceSessions",
    "in_thread",
    "profiles_projection",
    "thread_projection",
]

#: The live buffer's bound, deliberately the pump's own per-client bound. A
#: client that cannot fall more than 1024 events behind before being dropped
#: cannot need more than 1024 events replayed when it comes back, so a larger
#: ring would buy nothing and a smaller one would make ``resume`` weaker than
#: the drop policy it answers.
LIVE_BUFFER_MAX: Final[int] = BUFFERED_EVENTS_MAX

#: How many of a turn's events ``POST /sessions/{id}/prompt`` carries back
#: (audit-2026-09-04 J-http-limits-4). The *same* number the live socket path is
#: already bounded by, and deliberately so: the response list exists for a
#: client with no socket, so the two delivery paths of one event stream must
#: have one memory discipline, not two. Before this the list was unbounded on
#: both ends — every event of a long tool-heavy run accumulated in the serving
#: process and was then serialized whole into one response.
PROMPT_EVENTS_MAX: Final[int] = BUFFERED_EVENTS_MAX

#: How many settled ``ask_user`` questions are retained so a second answerer can
#: be told what the run was actually told (§2.7, audit-2026-09-04
#: J-agent-wiring-7). Bounded by count with oldest-first eviction: an answer
#: arriving after this many further questions degrades to the 404 the route gave
#: before, which is the pre-existing behaviour rather than a new failure, and
#: nothing in a long-running serve grows without limit. Sized well above any
#: plausible number of questions a human is answering at once and far below
#: anything that matters for memory — each record is a question, its options and
#: one selection.
SETTLED_QUESTIONS_MAX: Final[int] = 256

#: ``POST /sessions`` — "profile from a closed set" (§2.3). These are the three
#: profiles a *human operator* may open a session as; ``query_snapshot`` and
#: ``reviewer`` are runtime-internal (ephemeral, own budget, empty or read-only
#: tool allowlists) and are not offered to a client that could then prompt them.
SESSION_PROFILES: Final[tuple[str, ...]] = ("orchestrator", "part", "quick_edit")

#: The one profile ``POST /sessions`` may not **create** (§7A.2, §19.26). Named
#: here rather than spelled as a literal at the route, so the route's refusal
#: and this list cannot drift apart. It stays in :data:`SESSION_PROFILES`
#: because it is still a profile a session may *have* — a quick-edit session
#: exists, it is simply born at ``POST /parts/{part}/quick_edit``, which is the
#: only place its seeding happens (§12.5).
QUICK_EDIT_PROFILE: Final[str] = "quick_edit"

#: The two profiles the web create affordance may offer, in the order §7A.2's
#: table lists them. Served to the client as a **server projection** so the
#: composer names the profile it will use and what that profile can do without
#: keeping a client-side copy of the table (§7A.2: "the profile is never chosen
#: silently … not from a client-side copy").
CREATABLE_PROFILES: Final[tuple[str, ...]] = ("orchestrator", "part")


class SessionBackend(Protocol):
    """The bridge surface the workspace drives (``BridgeRuntime`` satisfies it).

    A Protocol rather than the concrete class so the HTTP layer can be exercised
    without a Node sidecar — and so the direction of the dependency stays
    honest: ``server/http`` uses the bridge, and the bridge knows nothing of it.
    """

    def create_session(
        self,
        profile: str,
        *,
        part: str | None = ...,
        session_id: str | None = ...,
        resume: bool = ...,
    ) -> str: ...

    def new_run_id(self) -> str: ...

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = ...,
        context: str | None = ...,
        answerer: Callable[[dict[str, Any]], Any] | None = ...,
        on_event: Callable[[dict[str, Any]], None] | None = ...,
        timeout: float | None = ...,
    ) -> PromptResult: ...

    def cancel(self, run_id: str) -> None: ...

    def history_page(
        self, session_id: str, cursor: str | None = ..., after: str | None = ...
    ) -> dict[str, Any]: ...

    def sessions(self) -> list[dict[str, Any]]: ...

    def session_for_run(self, run_id: str) -> str | None: ...

    def add_observer(
        self, client_id: str, *, notify: Callable[[], None] | None = ...
    ) -> ObserverClient: ...

    def drop_client(self, client_id: str) -> None: ...

    def add_event_tap(self, tap: Callable[[HephaestusEvent], None]) -> None: ...

    def rebind_project(
        self,
        *,
        layout: Any,
        project_store: Any,
        cad: Any,
        dispatcher: Any,
    ) -> None: ...


# --------------------------------------------------------------------------
# the live buffer
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BufferedEvent:
    """One buffered event plus the session it was routed to."""

    session_id: str | None
    event: HephaestusEvent


class LiveBuffer:
    """A bounded ring of recently-fanned events, for §2.7's ``resume``.

    **What it is not.** It is not history, it is not durable, and it makes no
    promise that a gap can be closed. §2.7 is explicit that a resync replays
    "whatever the live buffer still holds" and renders the rest as a *labelled
    break*; this class is that buffer and nothing more. Of the ten normalized
    kinds, ``question`` / ``answer`` / ``terminal`` are minted live and exist in
    no history page at all, so for those a buffer miss is unrecoverable by
    construction — which is exactly why the break is labelled rather than healed.

    Thread-safe: written from the supervisor's reader thread (via the pump tap),
    read from the event loop.
    """

    def __init__(self, bound: int = LIVE_BUFFER_MAX) -> None:
        self._events: deque[BufferedEvent] = deque(maxlen=bound)
        self._lock = threading.Lock()

    @property
    def bound(self) -> int:
        return self._events.maxlen or 0

    def append(self, session_id: str | None, event: HephaestusEvent) -> None:
        with self._lock:
            self._events.append(BufferedEvent(session_id=session_id, event=event))

    def snapshot(self) -> list[BufferedEvent]:
        with self._lock:
            return list(self._events)

    def replay(
        self, session_id: str, after: tuple[str, int] | None
    ) -> tuple[list[BufferedEvent], bool]:
        """Buffered events for ``session_id`` after the cursor, and whether the
        cursor itself was still in the buffer.

        The second element is the honest half. ``False`` means the client's last
        seen event has already fallen out of the ring, so what is returned is
        *some* suffix rather than *the* continuation: the client has a gap it
        must render as §7.4's ``resyncing`` break. It is never repaired from
        history — the two identity namespaces do not compare (see
        :mod:`hephaestus.http.event_identity`).
        """
        buffered = [item for item in self.snapshot() if item.session_id == session_id]
        if after is None:
            return buffered, True
        run_id, seq = after
        for index, item in enumerate(buffered):
            if item.event.run_id == run_id and item.event.seq == seq:
                return buffered[index + 1 :], True
        return buffered, False


# --------------------------------------------------------------------------
# pending questions
# --------------------------------------------------------------------------


class AskAbandoned(Exception):
    """A suspended ``ask_user`` was released without an answer (run cancelled)."""


@dataclass
class PendingQuestion:
    """One suspended ``ask_user``, waiting for the first answer to win."""

    question_id: str
    session_id: str
    run_id: str
    params: dict[str, Any]
    ready: threading.Event = field(default_factory=threading.Event)
    selection: Any = None
    answered: bool = False
    abandoned: bool = False

    def projection(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "question": self.params.get("question"),
            "options": self.params.get("options", []),
            "answered": self.answered,
        }


class PendingQuestions:
    """The ``ask_user`` registry: broadcast to all, **first answer wins** (§2.7).

    Idempotent **on the question id**, which is why ``POST /sessions/{id}/answer``
    carries no ``Idempotency-Key``: that would be a second idempotency mechanism
    over a stronger, already-existing one, which mission rule 6 forbids. A second
    answer is not an error and does not overwrite — it is told, in its own
    response, that another client answered first, so each widget can disable
    itself with ``data-answered-by="self"|"other"``.

    Neither the CLI's numbered prompt nor the web widget is privileged; both go
    through this registry. Inventing a web-side lock over a suspended question
    would be a second session-ownership mechanism (§2.7).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, PendingQuestion] = {}
        #: Questions whose suspension has ended, newest last, bounded by
        #: :data:`SETTLED_QUESTIONS_MAX`. See :meth:`answer` for why the record
        #: has to outlive the suspension.
        self._settled: OrderedDict[str, PendingQuestion] = OrderedDict()
        self._minted = 0

    def answerer(self, session_id: str) -> Callable[[dict[str, Any]], Any]:
        """An :data:`AskUserAnswerer` bound to ``session_id``.

        Handed to ``BridgeRuntime.prompt`` so a question raised by *this* run
        suspends here instead of on a terminal that no longer exists — the
        serving process has no stdin to prompt on.
        """

        def answer(params: dict[str, Any]) -> Any:
            return self.ask(session_id, params)

        return answer

    def ask(self, session_id: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        """Suspend until someone answers; return the selection.

        The question id is the sidecar's (``main.ts`` mints it around the
        ``py.ask_user`` suspension and puts the same value in the ``question``
        event's payload, so a client that saw the event can answer it). A request
        without one still suspends — under a locally-minted id — rather than
        failing the tool call: an older sidecar must degrade to "nobody can find
        this question", not to "the model's question crashed the run".
        """
        run_id = str(params.get("run_id", ""))
        with self._lock:
            raw = params.get("question_id")
            if isinstance(raw, str) and raw:
                question_id = raw
            else:
                self._minted += 1
                question_id = f"q-{run_id}-local-{self._minted}"
            pending = PendingQuestion(
                question_id=question_id,
                session_id=session_id,
                run_id=run_id,
                params=dict(params),
            )
            self._by_id[question_id] = pending
        try:
            pending.ready.wait(timeout)
            if pending.abandoned:
                raise AskAbandoned(f"question {question_id} was abandoned before it was answered")
            if not pending.answered:
                raise AskAbandoned(f"question {question_id} timed out without an answer")
            return pending.selection
        finally:
            with self._lock:
                settled = self._by_id.pop(question_id, None)
                # ONLY an answered question is retained. An abandoned one keeps
                # today's 404 on purpose: §7A.6 reads that refusal as "answered,
                # abandoned, or never asked", and a 200 for an abandoned
                # question would need a discriminated *abandoned* response the
                # client does not have yet. Retaining it here with a flag is the
                # named second step, not this fix.
                if settled is not None and settled.answered:
                    # The SUSPENSION is over; the RECORD is not (audit-2026-09-04
                    # J-agent-wiring-7). Dropping it here is what made the
                    # `accepted: false` branch unreachable: the loser's answer
                    # arrived microseconds after this `finally` and found an
                    # empty map, so it got the 404 that means "abandoned or
                    # never asked" and its widget rendered as abandoned — about
                    # a question that had in fact been answered.
                    self._settled[question_id] = settled
                    self._settled.move_to_end(question_id)
                    while len(self._settled) > SETTLED_QUESTIONS_MAX:
                        self._settled.popitem(last=False)

    def answer(self, question_id: str, selection: Any) -> tuple[PendingQuestion, bool]:
        """Answer a question. Returns ``(question, accepted)``.

        Three outcomes, and the middle one is the point (audit-2026-09-04
        J-agent-wiring-7):

        * **live and unanswered** — record, wake the suspended tool call, and
          return ``accepted=True``;
        * **settled** — someone already answered (or the run was cancelled and
          the question abandoned). The **winner's** selection comes back
          unchanged with ``accepted=False``, so both clients agree on what the
          run was told and the loser's widget can render "answered by someone
          else" instead of "abandoned";
        * **neither** — ``KeyError``, which the route maps to 404
          ``unknown_question``. Its meaning is unchanged and §7A.6 depends on
          that: an id nobody ever asked about is still a 404.

        The separation is between the *suspension's* lifetime and the *record's*.
        The live map is exactly what it was; the asker's ``finally`` now moves
        the entry into a bounded settled map instead of dropping it. Eviction
        past :data:`SETTLED_QUESTIONS_MAX` degrades an ancient loser to today's
        404 and nothing grows without limit.
        """
        with self._lock:
            pending = self._by_id.get(question_id)
            if pending is None:
                settled = self._settled.get(question_id)
                if settled is None:
                    raise KeyError(question_id)
                return settled, False
            if pending.answered:
                return pending, False
            pending.selection = selection
            pending.answered = True
        pending.ready.set()
        return pending, True

    def get(self, question_id: str) -> PendingQuestion | None:
        """The live question, or the settled record if its suspension has ended."""
        with self._lock:
            return self._by_id.get(question_id) or self._settled.get(question_id)

    def open_questions(self, session_id: str | None = None) -> list[PendingQuestion]:
        with self._lock:
            return [
                q for q in self._by_id.values() if session_id is None or q.session_id == session_id
            ]

    def abandon_run(self, run_id: str) -> int:
        """Release every question suspended on ``run_id`` (it was cancelled).

        The tool call fails with :class:`AskAbandoned` rather than receiving a
        fabricated selection. A cancelled run whose question silently "answered
        itself" would put an answer the operator never gave into the ledger.
        """
        with self._lock:
            doomed = [q for q in self._by_id.values() if q.run_id == run_id and not q.answered]
            for pending in doomed:
                pending.abandoned = True
        for pending in doomed:
            pending.ready.set()
        return len(doomed)

    def abandon_all(self) -> int:
        with self._lock:
            doomed = [q for q in self._by_id.values() if not q.answered]
            for pending in doomed:
                pending.abandoned = True
        for pending in doomed:
            pending.ready.set()
        return len(doomed)


# --------------------------------------------------------------------------
# the thread projection
# --------------------------------------------------------------------------


def profiles_projection() -> list[dict[str, Any]]:
    """What each creatable profile *is*, from the runtime's own authority.

    §7A.2: "**The profile is never chosen silently.** The create affordance
    shows the profile it will use and what that profile can do, in one line,
    **from a server projection** — not from a client-side copy of the table
    above. A user who does not know their session cannot delegate reads
    ``scope_denied`` as a broken product."

    So the capability facts are read from ``agent_bridge.sessions._SPECS``, the
    same table :meth:`ToolDispatcher._authorize` enforces, rather than
    transcribed. ``part_scoped`` is dispatch's own rule stated as a field:
    ``_authorize`` returns early for an orchestrator principal ("orchestrator
    addresses every part / project scope") and object-scope-checks everyone
    else, so a ``part`` session's every out-of-binding call is ``scope_denied``.

    **NAMED BOUNDARY.** This is facts, not prose. The *sentence* the affordance
    renders is composed in ``web/src/copy.ts`` from these booleans, because
    house style keeps every workspace string in one file and a server that
    shipped English would be a second copy deck. What §7A.2 forbids — the client
    keeping its own table of which profile can delegate — is what this
    projection removes.
    """
    from hephaestus.agent_bridge.sessions import SessionProfile, profile_for

    rows: list[dict[str, Any]] = []
    for name in CREATABLE_PROFILES:
        spec = profile_for(SessionProfile(name))
        rows.append(
            {
                "profile": name,
                "can_delegate": spec.can_delegate,
                # An orchestrator is exempt from object scope; everything else
                # is bound to the object it names (`dispatch.py::_authorize`).
                "part_scoped": name != SessionProfile.ORCHESTRATOR.value,
                "requires_part": name != SessionProfile.ORCHESTRATOR.value,
            }
        )
    return rows


def in_thread(edges: SessionEdgeStore, session_id: str) -> bool:
    """Whether ``session_id`` **participates in a thread** — parent or children.

    THE definition of §2.8's ``linked``/``unlinked`` axis (audit-2026-09-04
    J-http-envelope-7). There were two: the listing set the state from the
    presence of a *parent* edge alone, the thread route from a parent **or** any
    children, and a session that is a parent and not a child satisfied the
    second and not the first — so one session was labelled ``unlinked`` in the
    tab strip and ``linked`` in the panel, on one screen, for the same id.
    Neither site carried a note that the other existed.

    The parent-or-children reading is the right one because it is what the state
    is *used* for: a session with children is manifestly not isolated, and
    telling an orchestrator with a quick-edit child that it is unlinked is
    exactly the copy §2.8's honest-limit clause exists to avoid. The
    specification defines the two values and never defined the predicate, which
    is why both readings survived; the amendment naming this one is in the
    lane's hand-off.

    COST, stated: the session listing now performs two edge reads per row rather
    than one. Both are indexed local SQLite reads on the same open connection —
    the rule that the listing never probes the runtime is untouched — and a
    listing large enough for that to matter wants a grouped query, not a second
    definition of the field.
    """
    return edges.get(session_id) is not None or bool(edges.children(session_id))


def thread_projection(
    edges: SessionEdgeStore, session_id: str, *, listed: Collection[str] = ()
) -> dict[str, Any]:
    """``GET /sessions/{id}/thread`` — the transitive tree rooted at ``id`` (§2.8).

    ``thread_state`` is the honest half, and it is :func:`in_thread`'s answer —
    the one definition, called from here and from the listing.  ``unlinked``
    means this session has no recorded parent *and* no recorded children: either
    it genuinely is a root with no delegations yet, or it is a transcript that
    predates the edge table and whose parent **cannot be recovered**. The UI
    renders that state (``data-thread-state="unlinked"``) rather than guessing a
    parent, which is what §2.8's "honest limit" requires.

    **The id must name something** (audit-2026-09-04 J-http-envelope-8). The
    store below synthesises a depth-0 root for a session with no edges, which is
    correct and deliberate — a session with no edges *is* a one-node tree, and
    that is the honest answer for a transcript predating the table — but it is
    correct only for a session that **exists**. The route used to pass its path
    parameter straight through, so any string at all came back 200 with a
    one-node tree naming it: content the server invented about nothing, and a
    client with no way to tell "this session is a root" from "this session does
    not exist".

    Existence is established against the **durable** record, never against an
    attached runtime: threading is a fact in ``state.db``, readable long after
    the process that created it is gone, and refusing to answer "what was this a
    child of" because no model is configured today would make a durable record
    unreadable for an unrelated reason. So a session exists here when it appears
    in the edge table (as parent or child) or when the caller supplies it in
    ``listed``.

    **HONEST LIMIT, recorded rather than left implicit.** ``listed`` is what the
    runtime currently holds, so with no runtime attached — or for a persisted
    transcript no live runtime has open — a session that never wrote an edge
    answers 404. Closing that needs a "has this id a persisted transcript?"
    question no surface answers today; the narrower rule is the one implemented,
    and this paragraph is the record of what it costs.
    """
    if not in_thread(edges, session_id) and session_id not in listed:
        raise HttpRefusal(
            404,
            "unknown_session",
            f"no session {session_id!r} is known to this project",
            data={"session_id": session_id},
        )
    nodes = edges.thread(session_id)
    root = nodes[0]
    return {
        "status": "ok",
        "session_id": session_id,
        "thread_state": THREAD_LINKED if in_thread(edges, session_id) else THREAD_UNLINKED,
        "parent_session_id": root.parent_session_id,
        "nodes": [node.as_dict() for node in nodes],
    }


# --------------------------------------------------------------------------
# the workspace's session layer
# --------------------------------------------------------------------------


class WorkspaceSessions:
    """The serving process's view of its sessions, runs, observers, questions."""

    def __init__(self, backend: SessionBackend, edges: SessionEdgeStore) -> None:
        self.backend = backend
        self.edges = edges
        self.buffer = LiveBuffer()
        self.questions = PendingQuestions()
        self._lock = threading.Lock()
        self._observer_seq = 0
        # The tap, not a client queue: see LiveBuffer's docstring.
        backend.add_event_tap(self._tap)

    # -- event routing -----------------------------------------------------

    def _tap(self, event: HephaestusEvent) -> None:
        self.buffer.append(self.backend.session_for_run(event.run_id), event)

    def wire_frame(self, event: HephaestusEvent, session_id: str | None = None) -> dict[str, Any]:
        """§2.7's wire shape: the Python-side shape **verbatim**, plus ``session_id``.

        Exactly one envelope field is added and no web-specific kind is minted.
        ``tool_call_id`` and ``payload`` are omitted when absent rather than sent
        as ``null``, because that is what the Python-side shape is; ``session_id``
        is always present, and is ``null`` when the run→session binding has been
        evicted — a named absence a client must render unrouted rather than
        attribute to whatever session it happens to be showing.
        """
        frame: dict[str, Any] = {
            "run_id": event.run_id,
            "seq": event.seq,
            "kind": event.kind,
            "session_id": (
                session_id if session_id is not None else self.backend.session_for_run(event.run_id)
            ),
        }
        if event.tool_call_id is not None:
            frame["tool_call_id"] = event.tool_call_id
        if event.payload is not None:
            frame["payload"] = event.payload
        return frame

    # -- observers ---------------------------------------------------------

    def attach_observer(self, notify: Callable[[], None]) -> ObserverClient:
        """Register one socket as a §2.7 non-durable observer."""
        with self._lock:
            self._observer_seq += 1
            client_id = f"web-observer-{self._observer_seq}"
        return self.backend.add_observer(client_id, notify=notify)

    def detach_observer(self, observer: ObserverClient) -> None:
        self.backend.drop_client(observer.client_id)

    # -- session control ---------------------------------------------------

    def create(
        self,
        profile: str,
        *,
        part: str | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """``session.create``, optionally naming or **resuming** a session.

        DEVIATION, recorded rather than reinterpreted (§2.3, §14, G4.9/G4.11).
        §2.3's row for this route says ``session.create`` (profile from a closed
        set) and names no body; an earlier implementation therefore accepted only
        ``{profile, part}`` and every session id was a fresh sidecar UUID. Two
        gate clauses are unreachable under that:

        * §14 makes a **committed** >250-event transcript a fixture requirement,
          and a committed transcript is a persisted Pi session with a fixed id.
          ``history.page`` serves only sessions the sidecar has open
          (``agent/src/main.ts``), so the only way to read one back is to resume
          it by name.
        * §2.8 puts G4.11's archive over ``(session_id, ordinal)`` pairs. With a
          server-minted UUID the session half changes every run, so the archive
          would record identities the reopened transcript can never re-emit.

        Both arguments were already on the :class:`SessionBackend` Protocol and
        on ``BridgeRuntime.create_session``; nothing new is invented here, and no
        route is added.

        **AMENDED 2026-09-04 (§2.3/§2.4/§2.8).** The concession this docstring
        used to record — "``resume`` on an id with no persisted transcript is a
        fresh session under that name, which is the sidecar's own behaviour" —
        was an accurate description of the manager and an incorrect conclusion:
        it treated the sidecar's silence as a decision. A ``resume`` for an id
        the runtime holds no transcript for is now **404 ``unknown_session``**,
        refused in the one layer that can answer the question (the sidecar owns
        the session directories), and this method does not re-ask it here — a
        second, independent existence check above the runtime would be a second
        answer that could disagree with the first.
        """
        opened = self.backend.create_session(
            profile, part=part, session_id=session_id, resume=resume
        )
        return {
            "status": "ok",
            "session_id": opened,
            "profile": profile,
            "part": part,
            # `resumed` is a FACT about the transcript, not an echo of the
            # request (§2.8, amended 2026-09-04). It may be reported from the
            # request flag *only because* the runtime now refuses a resume it
            # cannot honour: a `create_session` that returned at all is a resume
            # that found something to continue. Before that refusal existed this
            # same expression was a lie — the request's own flag handed back as
            # if it were an outcome — and the panel opened an empty tab labelled
            # as resumed.
            "resumed": resume,
        }

    def list_sessions(self) -> dict[str, Any]:
        """``GET /sessions``, amended 2026-09-03: each row also says whether it
        can currently be read (§2.3).

        ``readable`` / ``unreadable_reason`` are the bridge's own fields — a
        mark with the same lifetime as the retained principal it describes,
        held beside the principal map in ``BridgeRuntime``
        (``agent_bridge/app.py``, the ``_unreadable`` dict) rather than as a
        field on ``Principal`` itself — that dataclass is frozen and is the
        authz identity ``py.tool_dispatch`` resolves against, so a cache of a
        read failure does not belong on it (see the ``_unreadable`` comment
        there for why). In memory either way: written only when a call for
        that session actually failed after §2.8(6)'s single re-adoption
        attempt, cleared the moment a call for it next succeeds. **The listing
        never probes**: this method does not call the bridge again to find
        out, it only reads what ``self.backend.sessions()`` already carried
        back.

        ``setdefault`` rather than an unconditional overwrite, so a backend that
        has not been updated to carry the mark (a test double, most saliently)
        still yields the full §2.3 row shape — with `readable: true` exactly the
        default the spec asks for: "a serving process that restarts starts with
        every row `readable: true`, and that is correct rather than a
        shortcut". A backend that *has* been updated keeps whatever it wrote.
        """
        rows = self.backend.sessions()
        for row in rows:
            session_id = str(row["session_id"])
            edge = self.edges.get(session_id)
            row["parent_session_id"] = None if edge is None else edge.parent_session_id
            # `in_thread`, not `edge is not None`: see that function for the two
            # definitions this row used to disagree with the thread route about.
            row["thread_state"] = (
                THREAD_LINKED if in_thread(self.edges, session_id) else THREAD_UNLINKED
            )
            row.setdefault("readable", True)
            row.setdefault("unreadable_reason", None)
        return {"status": "ok", "sessions": rows, "profiles": profiles_projection()}

    def run_prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = None,
        context: str | None = None,
        include_events: bool = True,
    ) -> dict[str, Any]:
        """One prompt turn, blocking, projected onto the wire.

        **At-least-once, stated** (§2.3): a prompt carries no idempotency key
        because the same words twice are two turns, and a replay that swallowed a
        deliberate re-ask would be worse than a duplicate.

        The turn's events are returned as well as streamed, and **that
        duplication is by design**: the socket is the live surface, and this list
        is what a client with no socket (the ``heph agent`` client-mode CLI on a
        machine where the upgrade failed) renders instead, so a run is never
        invisible.

        **Bounded, and declinable** (audit-2026-09-04 J-http-limits-4). The list
        carries at most :data:`PROMPT_EVENTS_MAX` events — the same bound the
        live path already has, from the same key — and says so with
        ``events_truncated`` and ``events_dropped`` when it had to cut. The
        surviving end is the **tail**: the newest events, because this list is
        read as a live transcript of a turn that has just ended, and a client
        that needs the run's opening reads history.

        The cut happens **twice, at one number**. The backend's own per-run
        buffer is a bounded deque of the same size, so a long orchestrator run
        never accumulates in the serving process either — the half of the item
        the response bound alone would have left open — and
        ``PromptResult.events_dropped`` carries what *it* discarded up to here,
        so the ``events_dropped`` on the wire counts the whole turn rather than
        only this layer's share of it. ``include_events=False`` is
        for the client that already holds the socket (the web client does), which
        also removes one source from its dedupe window; the default is today's
        behaviour, so every run shorter than the bound is byte-identical.

        ``context`` is §7A.3's composed block and travels **beside** ``text``,
        never inside it: ``BridgeRuntime.prompt`` forwards it to the sidecar and
        does not bind it, so ``VALIDATION.md`` §4's request diff still measures
        the operator's own words against the geometry (§7A.4).
        """
        run = run_id or self.backend.new_run_id()
        result = self.backend.prompt(
            session_id,
            text,
            run_id=run,
            context=context,
            answerer=self.questions.answerer(session_id),
        )
        # What the turn EMITTED, not what survived: the backend's own buffer is
        # bounded by the same key (J-http-limits-4's memory half), so
        # ``len(result.events)`` is already a tail and adding what it dropped is
        # the only way this layer can still say how long the run really was.
        produced = len(result.events) + result.events_dropped
        kept: list[dict[str, Any]] = []
        if include_events:
            tail = (
                result.events[-PROMPT_EVENTS_MAX:]
                if produced > PROMPT_EVENTS_MAX
                else (result.events)
            )
            kept = [dict(event, session_id=session_id) for event in tail]
        return {
            "status": "ok",
            "session_id": session_id,
            "run_id": result.run_id,
            "run_status": result.status,
            "events": kept,
            # Named absences, both of them: a client that asked for no events
            # must be able to tell that from a turn that emitted none, and a
            # truncated tail must never read as a complete one (§6.3).
            "events_included": include_events,
            "events_truncated": include_events and produced > PROMPT_EVENTS_MAX,
            "events_dropped": max(0, produced - len(kept)) if include_events else produced,
            "terminal": result.terminal,
        }

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        """Cancel a run. **Idempotent by construction** (§2.3), not by a key.

        A repeated ``request_cancel`` on an already-cancelled run changes
        nothing, and after close it is a quiet no-op; a key here would record a
        replay of a no-op. Questions suspended on the run are released so the
        tool call fails honestly instead of hanging on an operator who has left.

        **Idempotence is a property of a run's lifecycle, not a licence to
        accept an unknown address** (audit-2026-09-04 J-http-envelope-12). A run
        that existed and has finished is still 200 — that is what the clause is
        about. An id this server never issued is a client bug, and a quiet
        no-op would hide it, so the admission miss is refused ``unknown_run``
        with the id, where it used to surface as the generic ``not_found``
        carrying a message about an internal table and no run id at all. The
        fake backend is taught the same refusal, without which the two backends
        disagree and only the sidecar-backed lane can see the truth.
        """
        try:
            self.backend.cancel(run_id)
        except NotFoundError as exc:
            raise HttpRefusal(
                404,
                "unknown_run",
                f"this server never issued run {run_id!r}",
                data={"run_id": run_id},
            ) from exc
        abandoned = self.questions.abandon_run(run_id)
        return {
            "status": "ok",
            "run_id": run_id,
            "session_id": self.backend.session_for_run(run_id),
            "abandoned_questions": abandoned,
        }

    def answer_question(self, session_id: str, question_id: str, selection: Any) -> dict[str, Any]:
        pending, accepted = self.questions.answer(question_id, selection)
        return {
            "status": "ok",
            "question_id": question_id,
            "session_id": pending.session_id,
            "run_id": pending.run_id,
            "answer": pending.selection,
            "accepted": accepted,
            # §7.3: each widget disables itself with data-answered-by.
            "answered_by": "self" if accepted else "other",
            "requested_session_id": session_id,
        }

    def history(
        self, session_id: str, cursor: str | None, after: str | None = None
    ) -> dict[str, Any]:
        """``history.page`` passthrough; the opaque cursor is never rewritten.

        **No page-size parameter** (§2.8): ``HISTORY_PAGE_SIZE`` lives in
        ``agent/src/session/history.ts`` and page 1 freezes a high-water mark, so
        a client-selectable size would break both restart-stability and the
        frozen-mark guarantee.

        ``after`` is §2.8(5)'s **tail read**, additive to (never a replacement
        for) ``cursor``: it freezes a *new* high-water mark now and starts at
        the ordinal it names, rather than continuing inside a snapshot already
        frozen. Sending both is refused ``invalid_cursor`` (400, §2.4) here —
        at the one seam through which every caller of this method passes —
        rather than letting one silently win; the route itself
        (``server/src/hephaestus/http/app.py``) still has to *read* `?after=`
        off the query string and reach this method with it, which is a change
        to a file this module does not own (see the workflow's open concerns).
        """
        if cursor is not None and after is not None:
            raise HttpRefusal(
                400,
                "invalid_cursor",
                "history.page accepts either `cursor` or `after`, never both",
                data={"session_id": session_id},
            )
        # `after` is forwarded only when actually asked for, so a
        # `SessionBackend` that has not yet grown the §2.8(5) parameter (a test
        # double, most saliently `hephaestus.testing.fake_agent.FakeAgent`,
        # which this module does not own) keeps working unchanged for every
        # caller that never passes it — the ordinary `cursor` walk this method
        # served before this amendment.
        page = (
            self.backend.history_page(session_id, cursor, after)
            if after is not None
            else self.backend.history_page(session_id, cursor)
        )
        return {"status": "ok", "session_id": session_id, **page}

    def listed_session_ids(self) -> tuple[str, ...]:
        """The ids this runtime currently holds, for the thread route's existence
        check. Reads what ``backend.sessions()`` already carried back — it never
        probes, exactly as :meth:`list_sessions` does not."""
        return tuple(str(row["session_id"]) for row in self.backend.sessions())

    def thread(self, session_id: str) -> dict[str, Any]:
        return thread_projection(self.edges, session_id, listed=self.listed_session_ids())

    def close(self) -> None:
        self.questions.abandon_all()


def frames_for(
    sessions: WorkspaceSessions, events: Iterable[HephaestusEvent]
) -> list[dict[str, Any]]:
    """Wire frames for a batch of events (one binding lookup per event)."""
    return [sessions.wire_frame(event) for event in events]


def passes_filter(
    frame: dict[str, Any], *, session_ids: Sequence[str], run_ids: Sequence[str]
) -> bool:
    """§2.7's ``subscribe`` filter: no selection means everything.

    A socket that named nothing is watching the whole project — there is exactly
    one project per serving process (§2.1), and the bearer is scoped to it, so
    "everything" is not a widening. A socket that named sessions or runs sees an
    event matching either list; the two are a union rather than an intersection
    because a run and its session are the same subscription seen from two sides.
    """
    if not session_ids and not run_ids:
        return True
    if frame.get("session_id") in session_ids:
        return True
    return frame.get("run_id") in run_ids
