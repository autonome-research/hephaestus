# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Stand up the Gate G4 world and hold it up until Playwright is done.

``INTERFACE.md`` §14: "``pnpm test:e2e`` runs Playwright against a real
``heph serve --web`` on the fixture". This is the process that makes that
sentence true. It is deliberately **not** a second server, a mock, or a test
double of anything: it materializes the committed fixture, builds it through the
product's own ``CadOps``, starts the real ``heph serve --web`` as a child
process, and then does nothing but stay alive.

Started by ``web/e2e/global-setup.ts`` and stopped by ``global-teardown.ts``.
The handshake is one JSON file (path in ``argv[1]``) written when everything is
up::

    {"base_url", "token", "project_root", "sessions": [...], "model_base_url",
     "python"}

**The scripted provider lives here, not in the served process.** The workspace
process must be the shipped one; a fake model inside it would make the gate a
test of a modified server. So a loopback OpenAI-compatible server runs in *this*
process and ``.heph/providers.json`` points the real sidecar at it — the same
arrangement every other end-to-end suite in this repo uses (
``server/tests/test_e2e_fake_model.py``), and the "FakeModel per the harness
precedent" G4.8 asks for.

**The committed transcript is reopened, not recreated.** Two sessions are
resumed by name through ``POST /sessions {session_id, resume: true}`` before the
browser starts, because ``history.page`` serves only sessions the sidecar has
open. G4.8's live session is *not* opened here: it is created by ``heph agent``
from the command line, which is the whole subject of that clause.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

#: How long to wait for the server to print its entry URL and answer a read.
STARTUP_TIMEOUT_S = 180.0


def main(handshake_path: str) -> int:
    from hephaestus.testing.fake_openai import start_fake_openai
    from hephaestus.testing.workspace_fixture import (
        GATE_PARTS,
        ORCHESTRATOR_SESSION_ID,
        QUICK_EDIT_SESSION_ID,
        SUBJECT_PART,
        materialize_workspace_fixture,
    )

    scratch = Path(tempfile.mkdtemp(prefix="heph-g4-e2e-"))
    project_root = scratch / "workspace"
    log(f"materializing the fixture at {project_root}")
    materialize_workspace_fixture(project_root)
    build(project_root, GATE_PARTS)

    fake = start_fake_openai(scripted_turns(SUBJECT_PART))
    write_provider_config(project_root, fake.provider_spec())

    server = start_server(project_root)
    try:
        base_url, token = read_entry(server)
        await_ready(base_url, token)
        sessions = reopen(base_url, token, [ORCHESTRATOR_SESSION_ID, QUICK_EDIT_SESSION_ID])
        Path(handshake_path).write_text(
            json.dumps(
                {
                    "base_url": base_url,
                    "token": token,
                    "project_root": str(project_root),
                    "sessions": sessions,
                    "model_base_url": fake.base_url,
                    "pid": server.pid,
                    # §7A.7's spec needs the prompt that provokes a question and
                    # the labels the model will offer. They are published here
                    # rather than retyped in the spec: a spec that hard-coded the
                    # labels would assert its own copy of the fixture, and the
                    # one thing that clause is about is that the label the
                    # *server* sent is the value that comes back.
                    "ask": {
                        "sentinel": ASK_SENTINEL,
                        "options": ASK_OPTIONS,
                        "affordance": ASK_AFFORDANCE,
                    },
                    # §7A.12's composer cases. The sentinel and the part it
                    # creates are published for the same reason the ask block
                    # is: a spec that hard-coded them would assert its own copy
                    # of the fixture rather than the harness's.
                    "composer": {
                        "sentinel": COMPOSER_SENTINEL,
                        "part": COMPOSER_PART,
                    },
                    # The interpreter that runs the product here. A spec that
                    # shelled `uv run` from inside the materialized project
                    # would be outside this repository's uv workspace and would
                    # find no `hephaestus` at all; naming the interpreter is the
                    # honest way to run `heph` verbs against the fixture.
                    "python": sys.executable,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log(f"ready at {base_url}; sessions {sessions}")
        wait_forever(server)
    finally:
        stop(server)
        fake.close()
    return 0


def log(message: str) -> None:
    print(f"[g4-harness] {message}", file=sys.stderr, flush=True)


#: The token a spec puts in its prompt when it wants the model to ask a question.
#: Deliberately a sentinel and not a phrase: the dispatcher below is a *fake
#: model*, and keying it on plausible English would make one spec's prompt
#: wording silently change another spec's turn.
ASK_SENTINEL = "HEPH_ASK_USER"

#: The `ask_user` call the sentinel produces. Object options, because
#: `_CLARIFICATION_OPTION` is `{label, consequence}` and INTERFACE.md §7A.7's
#: answer namespace — the `label`, on every surface — is only testable against an
#: option whose label differs from its serialization.
ASK_OPTIONS = [
    {"label": "Keep 2 mm walls", "consequence": "the wall stays under one nozzle width"},
    {"label": "Go to 3 mm walls", "consequence": "the outer diameter grows by 2 mm"},
]

#: The scripted question, in one place because the handshake publishes what the
#: spec must expect and the script has to ask exactly that.
#:
#: ``allow_free_text`` is **false** on purpose. §7A.7 derives the affordance from
#: the question's own params, and a question that forbids free text must render
#: with no text field at all (§15.35). It is also the one param that proves the
#: sidecar carries it: the schema default is ``true``, so a `question` event
#: minted without the field renders a free-text box and the spec fails — which is
#: what makes `agent/src/main.ts`'s payload change end-to-end evidence rather
#: than a comment.
ASK_PARAMS: dict[str, Any] = {
    "question": "The tread wall is thinner than the nozzle can print. Which way?",
    "options": ASK_OPTIONS,
    "allow_free_text": False,
    "multi": False,
}

#: What §7A.7's mapping makes of :data:`ASK_PARAMS`. Published so the spec
#: asserts the harness's own answer instead of a second copy of the rule.
ASK_AFFORDANCE = "options"

#: The token a spec puts in its prompt when it wants the model to create a part.
#:
#: §7A.12's case 1 is the blank canvas, and its assertion is not about the
#: transcript: "assert the turn's events reach the transcript, ``run_status`` is
#: terminal, **and** the created part appears in the tree, is selectable, and
#: renders (§7A.11)". So the scripted turn has to make a real mutation through
#: the real dispatcher, and ``create_part`` is the one §7A.2 names as the only
#: way a part comes into existence from the browser: "the only way to bring a
#: part into existence from the browser is to **type English at an orchestrator
#: agent, which calls ``create_part``**".
COMPOSER_SENTINEL = "HEPH_CREATE_PART"

#: The part that turn creates. A name no fixture part uses, so its appearance in
#: the tree is unambiguously this turn's doing and not the fixture's.
COMPOSER_PART = "composer_probe"


def scripted_turns(subject_part: str) -> list[Any]:
    """The fake model's script, dispatched on the **request** rather than on order.

    A positional script (turn 1, turn 2, …) makes every spec's turns depend on
    which specs ran before it, so adding one spec silently re-aims another's
    model. Playwright runs this suite serially against one server, so that
    coupling is real: G4.8's `run_checks` round trip and §7A.7's `ask_user`
    suspension share one fake. Each resolver therefore reads the request and
    answers it:

    * a conversation that already contains a tool result gets the closing text
      turn — the tool call it was asked for has been answered;
    * a prompt carrying :data:`ASK_SENTINEL` gets the `ask_user` suspension;
    * anything else gets G4.8's `run_checks` call, unchanged.

    The list is resolvers rather than turns because `FakeOpenAI` consumes one
    entry per tool-enabled request; the entries are identical, so the *cursor*
    no longer decides anything. It is long enough for every spec in the suite,
    and an exhausted script still settles the loop with a terminal text turn.
    """
    from hephaestus.testing.fake_openai import RequestInfo
    from hephaestus.testing.stream_assertions import text, tool_call

    def resolve(info: RequestInfo) -> dict[str, Any]:
        if info.has_tool_result:
            return text(
                "The check set ran against the current tread: one passing, one failing, "
                "one that cannot be evaluated."
            )
        if ASK_SENTINEL in info.body_text:
            return tool_call("ask_user", dict(ASK_PARAMS), "c-live-ask")
        if COMPOSER_SENTINEL in info.body_text:
            # §7A.12 case 1. A REAL mutation through the real dispatcher: the
            # clause's assertion is that the part appears in the tree without a
            # manual reload, and a scripted text turn would leave nothing for
            # the read-refresh boundary to refresh.
            return tool_call(
                "create_part",
                {"name": COMPOSER_PART, "description": "a part the composer asked for"},
                "c-live-create",
            )
        return tool_call("run_checks", {"name": subject_part}, "c-live-checks")

    return [resolve] * 16


def build(root: Path, parts: tuple[str, ...]) -> None:
    """Build the gate's parts through ``CadOps`` — the product's own path.

    Done before the server starts so the browser never races a build, and so a
    fixture that stopped building fails the harness with the engine's own error
    rather than as a mysterious empty viewport.
    """
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.http.runtime import _backend_for  # pyright: ignore[reportPrivateUsage]

    layout = load_project(root)
    store = open_store(layout)
    try:
        cad = CadOps(layout, store, backend=_backend_for(layout, True))
        for part in parts:
            log(f"building {part}")
            result = cad.build_part(part, op_id=f"g4-e2e-{part}")
            if result.get("status") != "ok":
                raise SystemExit(f"fixture part {part!r} did not build: {result}")
    finally:
        store.close()


def write_provider_config(root: Path, spec: dict[str, Any]) -> None:
    """Point the served process's sidecar at the scripted provider.

    The spec is the fake's own ``provider_spec()`` — the same document every
    other end-to-end suite hands ``runtime.configure`` — so the served process
    configures its sidecar exactly as it would for a real provider and nothing
    about the model path is special-cased for the gate.
    """
    config = {"providers": [spec]}
    path = root / ".heph" / "providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def start_server(root: Path) -> subprocess.Popen[str]:
    """The **real** ``heph serve --web``, on an ephemeral loopback port."""
    port = free_port()
    argv = [
        sys.executable,
        "-m",
        "hephaestus.core.cli",
        "serve",
        "--web",
        "--web-address",
        f"127.0.0.1:{port}",
    ]
    log(f"starting {' '.join(argv)}")
    return subprocess.Popen(
        argv,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_entry(server: subprocess.Popen[str]) -> tuple[str, str]:
    """Parse ``http://HOST:PORT/#t=<token>`` off the server's stdout.

    The token is read from the line the verb exists to print, not from
    ``.heph/serve.token``: that is the handshake an operator gets, so it is the
    handshake the gate uses.
    """
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    assert server.stdout is not None
    while time.monotonic() < deadline:
        line = server.stdout.readline()
        if not line:
            if server.poll() is not None:
                raise SystemExit(
                    f"heph serve exited with {server.returncode} before printing a URL"
                )
            continue
        line = line.strip()
        log(f"serve: {line}")
        if "/#t=" in line:
            url, _, token = line.partition("/#t=")
            return url, token
    raise SystemExit("heph serve printed no entry URL within the startup timeout")


def await_ready(base_url: str, token: str) -> None:
    """Poll one authorized read until the app answers."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            get(base_url, token, "/project")
            return
        except (urllib.error.URLError, OSError) as exc:  # not up yet
            last = exc
            time.sleep(0.2)
    raise SystemExit(f"the workspace API never became ready: {last}")


def reopen(base_url: str, token: str, session_ids: list[str]) -> list[str]:
    """Resume the committed transcript's sessions so history has a subject.

    An agent runtime is required for this; if the sidecar could not start, the
    harness fails loudly rather than handing Playwright a world in which every
    transcript clause would report "no sessions" and pass vacuously.
    """
    profiles = {"sess-workspace-quickedit": ("quick_edit", "tread")}
    opened: list[str] = []
    for session_id in session_ids:
        profile, part = profiles.get(session_id, ("orchestrator", None))
        body: dict[str, Any] = {"profile": profile, "session_id": session_id, "resume": True}
        if part is not None:
            body["part"] = part
        answer = post(base_url, token, "/sessions", body)
        opened.append(str(answer["session_id"]))
    return opened


def get(base_url: str, token: str, path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}/api/v1{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return dict(json.loads(response.read().decode("utf-8")))


def post(base_url: str, token: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}/api/v1{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return dict(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"POST {path} refused: {exc.read().decode('utf-8', 'replace')}") from exc


def wait_forever(server: subprocess.Popen[str]) -> None:
    """Hold the world up until the runner stops us, or the server dies."""
    stopping = {"now": False}

    def _stop(_signum: int, _frame: object) -> None:
        stopping["now"] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _stop)
    while not stopping["now"]:
        if server.poll() is not None:
            raise SystemExit(f"heph serve exited unexpectedly with {server.returncode}")
        time.sleep(0.25)


def stop(server: subprocess.Popen[str]) -> None:
    if server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover - a wedged server
        server.kill()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: serve_fixture.py <handshake.json>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
