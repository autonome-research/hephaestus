"""Event pump: normalized sidecar events -> bounded per-client queues + terminals.

The pump consumes the sidecar's ``event`` and ``terminal`` notifications
(delivered via the supervisor's notification sink) and:

* fans ``event`` records into **strictly bounded per-client queues**
  (``buffered_events`` = 1024). Explicitly droppable **progress deltas**
  coalesce by ``(run_id, event_kind, tool_call_id)`` and evict the oldest
  progress key at capacity. A non-droppable overflow is explicit: durable
  owners are backpressure-cancelled and detached after their reserved terminal;
  observers are dropped with ``resync_required`` and never cancel the run.
* ingests ``terminal`` records into the opstore admission terminal channel in
  **one transaction**, then acknowledges back to the sidecar **only after the
  terminal is durable** (``terminal.ack`` names the terminal id). Exactly one
  durable terminal per run; a duplicate terminal replays the same durable state.

The pump is transport-agnostic: it calls injected callbacks to send the
``cancel`` and ``terminal.ack`` notifications, so it composes with the real
:class:`~hephaestus.agent_bridge.supervisor.Supervisor` or a test double.
"""

from __future__ import annotations

import contextlib
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from opstore.admission import AdmissionControl, TerminalRecord
from opstore.errors import NotFoundError, TerminalConflictError
from opstore.types import TerminalState

from .limits import LIMITS

__all__ = [
    "BUFFERED_EVENTS_MAX",
    "DROPPABLE_KINDS",
    "EVENT_KINDS",
    "RESYNC_CLOSE_CODE",
    "RESYNC_CLOSE_REASON",
    "EventPump",
    "HephaestusEvent",
    "ObserverClient",
    "PerClientQueue",
    "coalesce_key",
]

#: ``INTERFACE.md`` §2.7: the WebSocket close code a dropped observer gets.
#: Named here, beside the policy that produces it, so the transport cannot mint
#: a second number for the same condition.
RESYNC_CLOSE_CODE: int = 4409

#: …and its close reason, the whole of the client-visible vocabulary for it.
RESYNC_CLOSE_REASON: str = "resync_required"

#: The stable Hephaestus event vocabulary (mirrors ``agent/src/events.ts``).
EVENT_KINDS: frozenset[str] = frozenset(
    {
        "text_delta",
        "thought",
        "tool_call",
        "tool_result",
        "image",
        "question",
        "answer",
        "audit",
        "progress",
        "terminal",
    }
)

#: Only ``progress`` deltas are droppable / coalescible.
DROPPABLE_KINDS: frozenset[str] = frozenset({"progress"})

BUFFERED_EVENTS_MAX: int = int(LIMITS["events"]["buffered_events"])


@dataclass(frozen=True)
class HephaestusEvent:
    """One normalized event; ``run_id`` is always present."""

    run_id: str
    seq: int
    kind: str
    tool_call_id: str | None = None
    payload: dict[str, Any] | None = None

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> HephaestusEvent:
        kind = str(params.get("kind", ""))
        tool_call_id = params.get("tool_call_id") or params.get("toolCallId")
        return cls(
            run_id=str(params["run_id"]),
            seq=int(params.get("seq", 0)),
            kind=kind,
            tool_call_id=None if tool_call_id is None else str(tool_call_id),
            payload=params.get("payload"),
        )


def coalesce_key(ev: HephaestusEvent) -> str:
    """Coalescing key ``run_id\\0kind\\0tool_call_id`` (NUL-separated)."""
    return f"{ev.run_id}\x00{ev.kind}\x00{ev.tool_call_id or ''}"


class PerClientQueue:
    """A strictly bounded event queue with progress coalescing.

    At most ``bound - 1`` non-terminal events are retained, reserving one slot
    for the authoritative terminal if a durable backlog overflows. Distinct
    progress keys cannot defeat the bound: the oldest progress key is evicted.
    Once a non-droppable event cannot fit, overflow latches and later
    non-terminal events are refused; the owner must cancel/drop and resync.
    """

    def __init__(self, bound: int = BUFFERED_EVENTS_MAX) -> None:
        if bound < 1:
            raise ValueError("event queue bound must be positive")
        self.bound = bound
        self._durable: list[HephaestusEvent] = []
        self._progress: OrderedDict[str, HephaestusEvent] = OrderedDict()
        self._overflowed = False

    def push(self, ev: HephaestusEvent) -> bool:
        """Enqueue ``ev`` when it fits; never let total storage exceed ``bound``."""
        if ev.kind == "terminal":
            # One durable terminal exists per run. Replayed sidecar terminals do
            # not consume another slot in a stalled client's finite queue.
            if any(item.kind == "terminal" and item.run_id == ev.run_id for item in self._durable):
                return True
            if self.size >= self.bound:
                self._overflowed = True
                return False
            self._durable.append(ev)
            return True

        if self._overflowed:
            return False

        regular_limit = self.bound - 1
        if ev.kind in DROPPABLE_KINDS:
            key = coalesce_key(ev)
            if key in self._progress:
                self._progress.pop(key)
                self._progress[key] = ev
                return True
            if regular_limit == 0:
                return True  # progress is explicitly droppable
            if self.size >= regular_limit:
                if self._progress:
                    self._progress.popitem(last=False)
                else:
                    return True  # a progress delta need not displace durable evidence
            self._progress[key] = ev
            return True

        # Durable evidence displaces droppable progress before declaring the
        # client unable to keep up.
        while self.size >= regular_limit and self._progress:
            self._progress.popitem(last=False)
        if self.size >= regular_limit:
            self._overflowed = True
            return False
        self._durable.append(ev)
        return True

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    def drain(self) -> list[HephaestusEvent]:
        """Return buffered events in arrival order and clear stored entries.

        Overflow intentionally remains latched: the pump has already dropped
        the observer or cancelled and detached the durable client.
        """
        out = list(self._durable)
        out.extend(self._progress.values())
        out.sort(key=lambda e: e.seq)
        self._durable.clear()
        self._progress.clear()
        return out

    @property
    def size(self) -> int:
        return len(self._durable) + len(self._progress)


class ObserverClient:
    """A **non-durable observer** of the event stream (``INTERFACE.md`` §2.7).

    A browser tab — and the ``heph agent`` client attached to a running server —
    registers as one of these rather than as an ordinary pump client. It gets the
    same 1024-slot :class:`PerClientQueue` bound and the same coalescing of
    ``progress`` (the only :data:`DROPPABLE_KINDS` member), but it **never
    participates in** :meth:`EventPump._backpressure_cancel`.

    WHY, and this is the whole justification: the pump's durable-overflow policy
    cancels the affected *run*. A stalled browser tab would otherwise kill an
    agent's work — an unacceptable coupling between a UI's frame budget and a
    design's progress. The alternative, making the web client droppable, is
    illegal: only ``progress`` is droppable, and ``audit`` / ``tool_call`` /
    ``tool_result`` / ``question`` / ``answer`` / ``terminal`` are never dropped.
    Disconnect-and-resync is the only policy that is both run-preserving and, for
    the kinds history can replay, recoverable.

    On overflow the observer is marked :attr:`resync_required`, dropped from the
    pump, and woken one last time; the transport then closes its socket with
    :data:`RESYNC_CLOSE_CODE` / :data:`RESYNC_CLOSE_REASON`. **The run is not
    cancelled and no other client is affected.**

    ``notify`` is the transport's wakeup — for a WebSocket handler, a
    ``loop.call_soon_threadsafe`` closure — because the pump is driven from the
    supervisor's reader thread, not from an event loop. It must never raise and
    never block; a transport that has gone away is dropped by the reader loop it
    wakes, not here.
    """

    def __init__(
        self,
        client_id: str,
        *,
        notify: Callable[[], None] | None = None,
        bound: int = BUFFERED_EVENTS_MAX,
    ) -> None:
        self.client_id = client_id
        self.queue = PerClientQueue(bound=bound)
        self.notify = notify
        self.resync_required = False
        # An observer is the one client class whose push and drain provably run
        # on DIFFERENT threads: the pump fans from the supervisor's reader
        # thread, and the socket drains from the event loop. ``PerClientQueue``
        # is a plain list plus a dict; a drain interleaved with a push is a
        # mutation race, so the queue is guarded here rather than relying on the
        # pump's lock, which the drain side does not hold.
        self._queue_lock = threading.Lock()

    def push(self, ev: HephaestusEvent) -> bool:
        """Buffer ``ev``; return False once the durable backlog has overflowed."""
        with self._queue_lock:
            fit = self.queue.push(ev)
            if not fit:
                self.resync_required = True
            return fit

    def drain(self) -> list[HephaestusEvent]:
        with self._queue_lock:
            return self.queue.drain()

    def wake(self) -> None:
        if self.notify is not None:
            self.notify()


@dataclass(frozen=True)
class TerminalIngest:
    """Result of ingesting one terminal record."""

    record: TerminalRecord
    acked: bool
    duplicate: bool


class EventPump:
    """Routes sidecar event/terminal notifications to queues and the opstore."""

    def __init__(
        self,
        admission: AdmissionControl,
        *,
        ack_terminal: Callable[[str, str], None] | None = None,
        cancel_run: Callable[[str], None] | None = None,
        project_terminal: Callable[[Any, TerminalRecord], None] | None = None,
        bound: int = BUFFERED_EVENTS_MAX,
    ) -> None:
        self._admission = admission
        self._ack_terminal = ack_terminal
        self._cancel_run = cancel_run
        self._project_terminal = project_terminal
        self._bound = bound
        self._lock = threading.RLock()
        self._clients: dict[str, PerClientQueue] = {}
        self._observers: dict[str, ObserverClient] = {}
        self._taps: list[Callable[[HephaestusEvent], None]] = []
        self._cancelled_runs: set[str] = set()
        self.acked_terminals: dict[str, str] = {}

    # -- client registration ----------------------------------------------

    def add_client(self, client_id: str) -> PerClientQueue:
        """Register a **durable** client and return its bounded queue.

        A durable client's overflow backpressure-cancels the run. That is the
        right policy for the owner of a run (the CLI holding the session, the
        bench harness); it is the wrong policy for an observer, which registers
        through :meth:`add_observer` instead (§2.7).
        """
        with self._lock:
            queue = self._clients.get(client_id)
            if queue is None:
                queue = PerClientQueue(bound=self._bound)
                self._clients[client_id] = queue
            return queue

    def add_observer(
        self, client_id: str, *, notify: Callable[[], None] | None = None
    ) -> ObserverClient:
        """Register a **non-durable observer** (§2.7); see :class:`ObserverClient`."""
        with self._lock:
            observer = ObserverClient(client_id, notify=notify, bound=self._bound)
            self._observers[client_id] = observer
            return observer

    def remove_client(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)
            self._observers.pop(client_id, None)

    def observer_count(self) -> int:
        """How many non-durable observers are attached right now.

        An operational read — "how many clients are watching" — and the only way
        to know an observer has actually been registered without reaching into
        the pump's internals.
        """
        with self._lock:
            return len(self._observers)

    def add_tap(self, tap: Callable[[HephaestusEvent], None]) -> None:
        """Register a **process-owned** synchronous hook on every fanned event.

        A tap is not a client: it has no queue, no bound, and cannot overflow, so
        it can neither backpressure-cancel a run nor be dropped. It exists for
        the serving process's own bounded **live buffer** (``INTERFACE.md`` §2.7
        — "replays whatever the live buffer still holds"), which must survive the
        disconnect of the observer that is reconnecting; a buffer built as a
        client would be dropped by the same overflow it exists to recover from.

        It runs on the supervisor's reader thread under the pump lock, so it must
        be O(1) and must not block. Exceptions are suppressed: a broken tap must
        not stop the stream.
        """
        with self._lock:
            self._taps.append(tap)

    # -- notification entry point ------------------------------------------

    def on_notification(self, method: str, params: dict[str, Any]) -> None:
        """Supervisor notification sink: dispatch ``event`` / ``terminal``."""
        if method == "event":
            self.on_event(HephaestusEvent.from_params(params))
        elif method == "terminal":
            self.on_terminal(params)

    def on_event(self, ev: HephaestusEvent) -> None:
        """Fan one event to every client queue; backpressure-cancel on overflow.

        Two classes, two policies (§2.7). A **durable** client's overflow cancels
        the run. An **observer**'s overflow drops the observer — it is removed
        here and woken once more so its transport can close ``4409
        resync_required`` — and leaves the run untouched.
        """
        overflow_runs: set[str] = set()
        overflow_clients: list[tuple[str, PerClientQueue]] = []
        dropped: list[ObserverClient] = []
        with self._lock:
            for tap in self._taps:
                with contextlib.suppress(Exception):
                    tap(ev)
            for client_id, queue in self._clients.items():
                fit = queue.push(ev)
                if not fit:
                    overflow_runs.add(ev.run_id)
                    overflow_clients.append((client_id, queue))
            for observer in list(self._observers.values()):
                if not observer.push(ev):
                    dropped.append(observer)
                    self._observers.pop(observer.client_id, None)
        self._wake(dropped)
        for run_id in overflow_runs:
            # The synthetic terminal uses the queue's reserved final slot.
            self._backpressure_cancel(run_id)
        # A client that forced cancellation is no longer a stream consumer.
        # Detach only after terminal synthesis so it can drain that final truth,
        # and identity-check in case the id was concurrently re-registered.
        with self._lock:
            for client_id, queue in overflow_clients:
                if self._clients.get(client_id) is queue:
                    self._clients.pop(client_id, None)

    def _wake(self, dropped: Sequence[ObserverClient]) -> None:
        """Wake every attached observer, plus the ones just dropped.

        Outside the lock: a transport's wakeup is not ours to run under a lock
        the reader thread also needs, and a raising transport must not take the
        pump down with it.
        """
        with self._lock:
            attached = list(self._observers.values())
        for observer in (*attached, *dropped):
            with contextlib.suppress(Exception):
                observer.wake()

    def _backpressure_cancel(self, run_id: str) -> None:
        with self._lock:
            if run_id in self._cancelled_runs:
                return
            self._cancelled_runs.add(run_id)
        if self._cancel_run is not None:
            self._cancel_run(run_id)
        # Route the final error through the terminal channel (idempotent). A
        # run without an admission row has nothing to terminate — ignore.
        with contextlib.suppress(NotFoundError):
            self._ingest_terminal(
                run_id=run_id,
                terminal_id=f"backpressure:{run_id}",
                state=TerminalState.FAILED,
                data={"reason": "backpressure_cancel"},
            )

    def on_terminal(self, params: dict[str, Any]) -> TerminalIngest:
        """Durably record a terminal, then ack it back to the sidecar."""
        return self._terminal_from_params(params, acknowledge_peer=True)

    def reconcile_terminal(self, params: dict[str, Any]) -> TerminalIngest:
        """Settle a terminal after sidecar loss without writing to the dead peer."""
        return self._terminal_from_params(params, acknowledge_peer=False)

    def _terminal_from_params(
        self, params: dict[str, Any], *, acknowledge_peer: bool
    ) -> TerminalIngest:
        run_id = str(params["run_id"])
        terminal_id = str(params.get("terminal_id", f"terminal:{run_id}"))
        state = TerminalState(str(params["state"]))
        data = params.get("payload")
        return self._ingest_terminal(
            run_id=run_id,
            terminal_id=terminal_id,
            state=state,
            data=data,
            acknowledge_peer=acknowledge_peer,
        )

    def _ingest_terminal(
        self,
        *,
        run_id: str,
        terminal_id: str,
        state: TerminalState,
        data: Any,
        acknowledge_peer: bool = True,
    ) -> TerminalIngest:
        existing = self._admission.get_terminal(run_id)
        duplicate = existing is not None
        # Insert the terminal and project caller state in ONE transaction.
        try:
            if self._project_terminal is not None:
                with self._admission.terminal_transaction(run_id, terminal_id, state, data) as conn:
                    record = self._admission.get_terminal(run_id)
                    assert record is not None
                    self._project_terminal(conn, record)
            else:
                record = self._admission.insert_terminal(run_id, terminal_id, state, data)
        except TerminalConflictError:
            # A distinct terminal already won; the existing one is authoritative.
            record = self._admission.get_terminal(run_id)
            assert record is not None
            duplicate = True
        else:
            if self._project_terminal is not None:
                record = self._admission.get_terminal(run_id)
                assert record is not None
        # Durable now: acknowledge (idempotent) and release the slot.
        self._admission.acknowledge_terminal(record.run_id, record.terminal_id)
        acked = True
        with self._lock:
            self.acked_terminals[run_id] = record.terminal_id
        if acknowledge_peer and self._ack_terminal is not None:
            self._ack_terminal(run_id, record.terminal_id)
        # Emit a normalized terminal event. A queue reserves capacity for this
        # after ordinary-event overflow. A backlog made entirely of terminals
        # can still fill the finite queue; in that case the client is detached
        # and its latched queue explicitly requires resync rather than silently
        # remaining registered after losing authoritative truth.
        term_event = HephaestusEvent(
            run_id=run_id,
            seq=2**62,  # terminals sort last
            kind="terminal",
            payload={
                "state": str(record.state),
                "terminal_id": record.terminal_id,
                "payload": record.data,
            },
        )
        dropped: list[ObserverClient] = []
        with self._lock:
            for tap in self._taps:
                with contextlib.suppress(Exception):
                    tap(term_event)
            for client_id, queue in list(self._clients.items()):
                if not queue.push(term_event):
                    self._clients.pop(client_id, None)
            # Observers see terminals too — a run-terminal band the browser never
            # received would leave a transcript implying the run is still open
            # (§7.3). An observer that overflows on the terminal is dropped like
            # any other overflow; the run is already over either way.
            for observer in list(self._observers.values()):
                if not observer.push(term_event):
                    dropped.append(observer)
                    self._observers.pop(observer.client_id, None)
        self._wake(dropped)
        return TerminalIngest(record=record, acked=acked, duplicate=duplicate)
