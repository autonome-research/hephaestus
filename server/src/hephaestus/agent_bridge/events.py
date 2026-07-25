"""Event pump: normalized sidecar events -> bounded per-client queues + terminals.

The pump consumes the sidecar's ``event`` and ``terminal`` notifications
(delivered via the supervisor's notification sink) and:

* fans ``event`` records into **per-client bounded queues** (``buffered_events``
  = 1024). Explicitly droppable **progress deltas** coalesce to the latest per
  key ``(run_id, event_kind, tool_call_id)``; never-dropped classes (audit, tool
  calls/results, questions/answers, terminals) always append. If the bounded
  queue still cannot make progress after coalescing, the affected run is
  **backpressure-cancelled** and its final error routed through the terminal
  channel (architecture §5 "Event coalescing").
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
from collections.abc import Callable
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
    "EventPump",
    "HephaestusEvent",
    "PerClientQueue",
    "coalesce_key",
]

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
    """A single client's bounded event queue with progress coalescing.

    Non-droppable events append and count against the bound. Droppable
    (progress) events coalesce to the latest per :func:`coalesce_key`, occupying
    at most one slot per key. ``overflow`` becomes true when, after coalescing,
    the durable (non-droppable) backlog still exceeds the bound — that is the
    backpressure-cancel trigger.
    """

    def __init__(self, bound: int = BUFFERED_EVENTS_MAX) -> None:
        self.bound = bound
        self._durable: list[HephaestusEvent] = []
        self._progress: OrderedDict[str, HephaestusEvent] = OrderedDict()

    def push(self, ev: HephaestusEvent) -> bool:
        """Enqueue ``ev``; return True if it fit, False on overflow (cancel signal)."""
        if ev.kind in DROPPABLE_KINDS:
            key = coalesce_key(ev)
            # Coalesce to the latest; move to the end to preserve arrival order.
            self._progress.pop(key, None)
            self._progress[key] = ev
            return True
        self._durable.append(ev)
        return len(self._durable) <= self.bound

    @property
    def overflowed(self) -> bool:
        return len(self._durable) > self.bound

    def drain(self) -> list[HephaestusEvent]:
        """Return buffered events in arrival order and clear the queue."""
        out = list(self._durable)
        out.extend(self._progress.values())
        out.sort(key=lambda e: e.seq)
        self._durable.clear()
        self._progress.clear()
        return out

    @property
    def size(self) -> int:
        return len(self._durable) + len(self._progress)


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
        self._cancelled_runs: set[str] = set()
        self.acked_terminals: dict[str, str] = {}

    # -- client registration ----------------------------------------------

    def add_client(self, client_id: str) -> PerClientQueue:
        """Register a client and return its bounded queue."""
        with self._lock:
            queue = self._clients.get(client_id)
            if queue is None:
                queue = PerClientQueue(bound=self._bound)
                self._clients[client_id] = queue
            return queue

    def remove_client(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)

    # -- notification entry point ------------------------------------------

    def on_notification(self, method: str, params: dict[str, Any]) -> None:
        """Supervisor notification sink: dispatch ``event`` / ``terminal``."""
        if method == "event":
            self.on_event(HephaestusEvent.from_params(params))
        elif method == "terminal":
            self.on_terminal(params)

    def on_event(self, ev: HephaestusEvent) -> None:
        """Fan one event to every client queue; backpressure-cancel on overflow."""
        overflow_runs: set[str] = set()
        with self._lock:
            for queue in self._clients.values():
                fit = queue.push(ev)
                if not fit:
                    overflow_runs.add(ev.run_id)
        for run_id in overflow_runs:
            self._backpressure_cancel(run_id)

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
        run_id = str(params["run_id"])
        terminal_id = str(params.get("terminal_id", f"terminal:{run_id}"))
        state = TerminalState(str(params["state"]))
        data = params.get("payload")
        return self._ingest_terminal(run_id=run_id, terminal_id=terminal_id, state=state, data=data)

    def _ingest_terminal(
        self,
        *,
        run_id: str,
        terminal_id: str,
        state: TerminalState,
        data: Any,
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
        if self._ack_terminal is not None:
            self._ack_terminal(run_id, record.terminal_id)
        # Emit a normalized terminal event to every client (never dropped).
        term_event = HephaestusEvent(
            run_id=run_id,
            seq=2**62,  # terminals sort last
            kind="terminal",
            payload={"state": str(state), "terminal_id": record.terminal_id},
        )
        with self._lock:
            for queue in self._clients.values():
                queue.push(term_event)
        return TerminalIngest(record=record, acked=acked, duplicate=duplicate)
