# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph agent`` client mode against a running server (§2.1, §19 item 3).

The topology decision this asserts is the whole of G4.8: **one process owns the
leases**, so a second ``heph agent`` in the same project does not open a second
in-process bridge — it drives the owner over loopback. A session created that way
is the same session object the browser attaches to, because there is only ever
one runtime and no event forwarding exists to get wrong.

The server here is a real ``uvicorn`` on a real loopback port, because the thing
under test is a *client* and a client that never opened a socket would prove
nothing about ``serve.json``, the ``0600`` token file, or the bearer.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.client_mode import ClientModeError, attach_client
from hephaestus.agent_bridge.serve_record import (
    ServeRecord,
    owning_server,
    write_private,
    write_serve_record,
)
from hephaestus.http.app import build_app
from hephaestus.http.principal import mint_token
from hephaestus.http.runtime import WorkspaceRuntime
from hephaestus.testing.fake_agent import FakeAgent
from hephaestus.testing.tools_fixture import scaffold as scaffold_tools_project


class _Server:
    """A real workspace API on a loopback port, with a fake agent attached."""

    def __init__(self, root: Path) -> None:
        import uvicorn

        self.root = root
        self.token, self.token_path = mint_token(root / ".heph")
        self.runtime = WorkspaceRuntime.open(root, token=self.token, serve_mode=False)
        self.agent = FakeAgent(self.runtime.store.admission)
        self.runtime.attach_sessions(self.agent)
        self.port = _free_port()
        config = uvicorn.Config(
            build_app(self.runtime), host="127.0.0.1", port=self.port, log_level="error"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> ServeRecord:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert self.server.started, "uvicorn did not start"
        return write_serve_record(
            self.root / ".heph",
            http=f"http://127.0.0.1:{self.port}",
            token_path=self.token_path,
        )

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        if self.runtime.sessions is not None:
            self.runtime.sessions.close()
        self.runtime.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def server(tmp_path: Path) -> Any:
    root = tmp_path / "proj"
    scaffold_tools_project(root)
    running = _Server(root)
    running.start()
    try:
        yield running
    finally:
        running.stop()


def test_no_server_means_no_client_and_the_verb_is_unchanged(tmp_path: Path) -> None:
    """ "If no server is running it behaves exactly as today" (§2.1).

    ``None`` — not an error, not a degraded client — is what tells ``heph agent``
    to open its own bridge exactly as it always has.
    """
    root = tmp_path / "proj"
    scaffold_tools_project(root)
    assert owning_server(root) is None
    assert attach_client(root) is None


def test_a_stale_serve_record_is_not_an_owner(tmp_path: Path) -> None:
    """A record naming a dead pid must not wedge the project permanently."""
    root = tmp_path / "proj"
    scaffold_tools_project(root)
    (root / ".heph").mkdir(parents=True, exist_ok=True)
    write_private(
        root / ".heph" / "serve.json",
        json.dumps(
            {
                "pid": 2**30,  # a pid that cannot be running
                "http": "http://127.0.0.1:1",
                "started_at": 0.0,
                "token_path": str(root / ".heph" / "serve.token"),
                "started_by": "nobody",
            }
        ),
    )
    assert owning_server(root) is None
    assert attach_client(root) is None


def test_a_live_server_is_driven_as_a_client_over_loopback(server: Any) -> None:
    """The §2.1 handshake end to end: discover, read the ``0600`` token, drive.

    The assertion that matters is the last one: the session the CLI created lives
    on the **server's** runtime, which is what makes it the same object a browser
    attaching to that server sees.
    """
    import os

    client = attach_client(server.root)
    assert client is not None
    # The record names THIS process, which is the one holding the leases.
    assert client.record.pid == os.getpid()
    assert client.token == server.token
    try:
        session_id = client.create_session("orchestrator")
        listed = {row["session_id"] for row in client.sessions()}
        assert session_id in listed
        # The session exists on the SERVER's runtime, not in this process.
        assert session_id in {row["session_id"] for row in server.agent.sessions()}
    finally:
        client.close()


def test_a_prompt_runs_on_the_server_and_its_events_come_back(server: Any) -> None:
    """A turn driven from the CLI is a turn on the one runtime that exists."""
    seen: list[dict[str, Any]] = []

    def script(agent: FakeAgent, sid: str, run: str, text: str, answerer: Any) -> None:
        agent.emit(run, 0, "text_delta", payload={"text": f"echo {text}"})

    server.agent.on_prompt = script
    client = attach_client(server.root)
    assert client is not None
    try:
        session_id = client.create_session("orchestrator")
        result = client.prompt(session_id, "hello", on_event=seen.append)
        # The live socket really attached: this is the §2.7 observer path, not
        # the render-from-the-response fallback, and the two must not both fire.
        assert client._stream is not None  # pyright: ignore[reportPrivateUsage]
    finally:
        client.close()

    assert result.status == "completed"
    kinds = [str(event.get("kind")) for event in result.events]
    assert "text_delta" in kinds
    # Rendered exactly once: either live off the socket or from the returned
    # events, never both. The socket is asynchronous, so the render is awaited
    # rather than assumed.
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len([e for e in seen if str(e.get("kind")) == "text_delta"]) == 1


def test_client_mode_refuses_session_and_resume_by_name(server: Any) -> None:
    """Silently ignoring ``--session foo --resume`` would let an operator believe
    they had reopened a transcript they had not."""
    client = attach_client(server.root)
    assert client is not None
    try:
        with pytest.raises(ClientModeError) as excinfo:
            client.create_session("orchestrator", session_id="old", resume=True)
    finally:
        client.close()
    assert excinfo.value.code == "invalid_params"


def test_an_unreachable_owner_refuses_session_busy_rather_than_opening_a_bridge(
    tmp_path: Path,
) -> None:
    """§2.1: "If a server is running but unreachable, it refuses with structured
    ``session_busy`` rather than opening a second in-process bridge."

    A second bridge would be two writers on one Pi JSONL (architecture.md §4.2),
    which is worse than a refusal in every case.
    """
    import os

    root = tmp_path / "proj"
    scaffold_tools_project(root)
    token, token_path = mint_token(root / ".heph")
    # A live pid (this process) with a port nothing listens on.
    write_private(
        root / ".heph" / "serve.json",
        json.dumps(
            {
                "pid": os.getpid(),
                "http": f"http://127.0.0.1:{_free_port()}",
                "started_at": time.time(),
                "token_path": str(token_path),
                "started_by": "test",
            }
        ),
    )
    client = attach_client(root)
    assert client is not None, "a live pid is an owner"
    assert client.token == token
    with pytest.raises(ClientModeError) as excinfo:
        client.create_session("orchestrator")
    assert excinfo.value.code == "session_busy"


def test_an_owner_whose_token_file_is_unreadable_refuses_rather_than_falls_back(
    tmp_path: Path,
) -> None:
    """The server holds the leases either way; opening a bridge beside it is the
    one outcome §2.1 forbids."""
    import os

    root = tmp_path / "proj"
    scaffold_tools_project(root)
    (root / ".heph").mkdir(parents=True, exist_ok=True)
    write_private(
        root / ".heph" / "serve.json",
        json.dumps(
            {
                "pid": os.getpid(),
                "http": "http://127.0.0.1:1",
                "started_at": time.time(),
                "token_path": str(root / ".heph" / "absent.token"),
                "started_by": "test",
            }
        ),
    )
    with pytest.raises(ClientModeError) as excinfo:
        attach_client(root)
    assert excinfo.value.code == "session_busy"
