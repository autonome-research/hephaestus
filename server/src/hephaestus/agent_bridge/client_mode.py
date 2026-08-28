# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph agent`` in **client mode** (``INTERFACE.md`` §2.1, §19 item 3).

**The decision, and why it changes a shipped verb's topology.** One process owns
the project's ``.heph/locks/`` session leases. ``heph agent`` therefore gains
**no new flag**: at startup it reads ``.heph/serve.json``, and if a live server
owns the project it drives ``session.create`` / ``prompt`` / ``cancel`` over the
loopback API — reading the same-user ``0600`` token file that record names —
instead of spawning its own :class:`~hephaestus.agent_bridge.app.BridgeRuntime`.
If no server is running it behaves exactly as it always has. If a server is
running but unreachable it refuses with structured ``session_busy`` rather than
opening a second in-process bridge.

*Rejected alternative:* a ``--server URL`` flag. Rejected as an added surface
with no gate behind it; ``serve.json`` is discovery enough, and a flag invites
pointing the CLI at a server that does not own the project's locks.

The visible consequence — and it is the whole of G4.8 — is that a session
started in a terminal is *the same session object* the browser attaches to,
because there is only ever one runtime. No event forwarding exists to get wrong.

**Live rendering.** The client attaches to ``GET /events`` as a §2.7 non-durable
observer and renders the stream as it arrives, exactly as the in-process REPL
does. That attach is best-effort: if the upgrade fails (no ``websockets``
package, a proxy that will not upgrade), the turn is still run and its events are
rendered from the prompt response when it returns. A run must never be invisible
just because a socket could not be opened.

**Answering a question.** A suspended ``ask_user`` reaches this process as a
``question`` event, not as a blocking callback — the *server* holds the runtime.
The operator answers at the same numbered prompt as ever and the selection is
POSTed to ``/sessions/{id}/answer``, where the first answer wins (§2.7). Both the
CLI's prompt and a browser widget may answer; neither is privileged.
"""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .app import AskUserAnswerer, PromptResult
from .serve_record import (
    WORKSPACE_API_PREFIX,
    ServeRecord,
    owning_server,
    read_token,
)

__all__ = [
    "ClientModeError",
    "ServerAgentClient",
    "attach_client",
]


class ClientModeError(Exception):
    """The owning server could not be driven. ``code`` is the machine reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ServerAgentClient:
    """Drives one project's sessions through the server that owns its leases.

    The surface is deliberately the subset of ``BridgeRuntime`` the ``heph
    agent`` REPL uses — ``create_session``, ``new_run_id``, ``prompt``,
    ``cancel``, ``close`` — so the REPL is written once against a driver rather
    than twice against two runtimes.
    """

    base_url: str
    token: str
    record: ServeRecord
    timeout: float = 600.0
    #: Opened lazily on the first prompt; ``None`` when the upgrade is
    #: unavailable, in which case events are rendered from the prompt response.
    _stream: _EventStream | None = None

    # -- transport ---------------------------------------------------------

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """One call against ``/api/v1/…`` with the bearer attached."""
        url = f"{self.base_url}{WORKSPACE_API_PREFIX}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload: Any = json.loads(response.read().decode("utf-8"))
                return payload
        except urllib.error.HTTPError as exc:
            # §2.4's structured taxonomy survives the wire, so the CLI reports the
            # ENGINE's reason rather than an HTTP status: "session_busy" and
            # "agent_unavailable" are different problems with different fixes.
            parsed: Any = None
            try:
                parsed = json.loads(exc.read().decode("utf-8"))
            except Exception:  # pragma: no cover - a non-JSON error body
                parsed = None
            detail: dict[str, Any] = (
                cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}
            )
            reason = str(detail.get("reason", "http_error"))
            message = str(detail.get("message", exc.reason))
            raise ClientModeError(reason, f"{method} {path}: {message}") from exc
        except OSError as exc:
            # A server that is recorded but unreachable is `session_busy`, never a
            # silent fallback to a second in-process bridge: that would put two
            # writers on one Pi JSONL (architecture.md §4.2).
            raise ClientModeError(
                "session_busy",
                f"pid {self.record.pid} owns this project at {self.record.http} "
                f"but is not reachable ({exc})",
            ) from exc

    # -- the driver surface ------------------------------------------------

    def create_session(
        self,
        profile: str,
        *,
        part: str | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> str:
        """Create a session **on the server**.

        ``session_id`` / ``resume`` are accepted for signature parity with
        ``BridgeRuntime`` and refused when used: ``POST /sessions`` names no such
        arguments, and silently ignoring ``--session foo --resume`` would let an
        operator believe they had reopened a transcript they had not.
        """
        if session_id is not None or resume:
            raise ClientModeError(
                "invalid_params",
                "--session/--resume are not available in client mode: the owning "
                "server creates sessions, and `GET /sessions` lists what it holds",
            )
        body = cast(
            "dict[str, Any]", self.request("POST", "/sessions", {"profile": profile, "part": part})
        )
        return str(body["session_id"])

    def sessions(self) -> list[dict[str, Any]]:
        body = cast("dict[str, Any]", self.request("GET", "/sessions"))
        return cast("list[dict[str, Any]]", body.get("sessions", []))

    def new_run_id(self) -> str:
        """A client-minted run id, so Ctrl-C can cancel before the turn returns.

        The same reason ``BridgeRuntime.new_run_id`` exists: the id has to be
        known *before* the call blocks or there is nothing to cancel.
        """
        import uuid

        return f"run-{uuid.uuid4().hex[:12]}"

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = None,
        answerer: AskUserAnswerer | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        timeout: float | None = None,
    ) -> PromptResult:
        """Run one turn on the server, rendering its events as they arrive."""
        run = run_id or self.new_run_id()
        stream = self._ensure_stream(session_id, on_event=on_event, answerer=answerer)
        body = cast(
            "dict[str, Any]",
            self.request("POST", f"/sessions/{session_id}/prompt", {"text": text, "run_id": run}),
        )
        events = cast("list[dict[str, Any]]", body.get("events", []))
        if stream is None and on_event is not None:
            # No socket: render what the turn returned, so a run is never
            # invisible merely because the upgrade failed.
            for event in events:
                on_event(event)
        return PromptResult(
            run_id=str(body.get("run_id", run)),
            status=str(body.get("run_status", "completed")),
            events=events,
            terminal=cast("dict[str, Any] | None", body.get("terminal")),
        )

    def cancel(self, run_id: str) -> None:
        try:
            self.request("POST", f"/runs/{run_id}/cancel")
        except ClientModeError:
            # Cancellation is idempotent by construction and best-effort from a
            # signal handler; a failed cancel must not replace the run's own
            # outcome with a transport error.
            return

    def answer(self, session_id: str, question_id: str, selection: Any) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.request(
                "POST",
                f"/sessions/{session_id}/answer",
                {"question_id": question_id, "answer": selection},
            ),
        )

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    # -- the live socket ---------------------------------------------------

    def _ensure_stream(
        self,
        session_id: str,
        *,
        on_event: Callable[[dict[str, Any]], None] | None,
        answerer: AskUserAnswerer | None,
    ) -> _EventStream | None:
        if on_event is None:
            return None
        if self._stream is not None:
            return self._stream
        try:
            stream = _EventStream(self, session_id, on_event=on_event, answerer=answerer)
        except Exception:
            # Best effort by design: see the module docstring. The turn still
            # runs and still renders.
            return None
        self._stream = stream
        return stream


class _EventStream:
    """A ``GET /events`` observer, rendering on a daemon thread."""

    def __init__(
        self,
        client: ServerAgentClient,
        session_id: str,
        *,
        on_event: Callable[[dict[str, Any]], None],
        answerer: AskUserAnswerer | None,
    ) -> None:
        from websockets.sync.client import connect

        url = client.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        self._socket = connect(
            f"{url}{WORKSPACE_API_PREFIX}/events",
            additional_headers={"Authorization": f"Bearer {client.token}"},
        )
        self._client = client
        self._session_id = session_id
        self._on_event = on_event
        self._answerer = answerer
        self._closed = threading.Event()
        self._socket.send(json.dumps({"subscribe": {"sessions": [session_id], "runs": []}}))
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while not self._closed.is_set():
            try:
                raw = self._socket.recv()
            except Exception:
                return
            try:
                frame = cast("dict[str, Any]", json.loads(raw))
            except ValueError:  # pragma: no cover - the server sends JSON
                continue
            self._on_event(frame)
            if str(frame.get("kind")) == "question":
                self._answer(frame)

    def _answer(self, frame: dict[str, Any]) -> None:
        """Put the question to the operator and POST the selection.

        The CLI is one attached client among possibly several; the first answer
        wins and the rest are told so (§2.7). A failure to answer is swallowed
        rather than raised — the browser, or another terminal, may already have.
        """
        if self._answerer is None:
            return
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return
        params = cast("dict[str, Any]", payload)
        question_id = params.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            return
        try:
            selection = self._answerer(params)
            self._client.answer(self._session_id, question_id, selection)
        except Exception:
            return

    def close(self) -> None:
        self._closed.set()
        with contextlib.suppress(Exception):  # already gone
            self._socket.close()


def attach_client(project_root: Path, *, timeout: float = 600.0) -> ServerAgentClient | None:
    """The §2.1 handshake: the client for the live owner, or ``None``.

    ``None`` means no live server owns this project and ``heph agent`` behaves
    exactly as it always has. A record naming a live pid whose token file cannot
    be read is a :class:`ClientModeError`, not a fallback: the server holds the
    leases either way, and opening a second bridge beside it is the one outcome
    §2.1 forbids.
    """
    record = owning_server(project_root)
    if record is None:
        return None
    try:
        token = read_token(Path(record.token_path))
    except OSError as exc:
        raise ClientModeError(
            "session_busy",
            f"pid {record.pid} owns this project but its token file "
            f"{record.token_path} is unreadable ({exc})",
        ) from exc
    return ServerAgentClient(
        base_url=record.http.rstrip("/"), token=token, record=record, timeout=timeout
    )
