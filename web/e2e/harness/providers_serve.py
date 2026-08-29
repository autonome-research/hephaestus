# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The Stage 10B/10C world: a serve with **no** ``providers.json`` (G10B, G10C).

G10B's clause opens with *"serve a project with **no** ``providers.json``"*, and
G10C's adds *"beside a scripted home-directory Pi ``auth.json`` and a scripted
local OpenAI-compatible endpoint"*. Both are properties of a **differently
configured serve**, not of a different page, so this is a third harness beside
``serve_fixture.py`` (which writes a provider config, because every G4 clause
needs a working sidecar) and ``no_agent_serve.py`` (which is §7A.12 case 6's and
must stay a bare zero-config serve, with nothing to discover).

What this one adds and why each piece is here rather than in a spec:

* **A scripted ``$HOME``** holding a Pi ``auth.json`` with a real-shaped OAuth
  record and a ``models-store.json`` beside it. The secret in that file is the
  sentinel G10C's Tier 1 grep is about: the offer *reads* this file — the
  2026-08-28 ruling directs that — so the thing worth proving is that the read
  is narrow.
* **A scripted local OpenAI-compatible endpoint**, named through
  ``HEPHAESTUS_LOCAL_ENDPOINTS``. Named, because nothing scans: §15.41 refuses a
  tool that knocks on its operator's ports unasked, and "it is only loopback" is
  not a reason to do it. The env var is a terminal act, which is exactly the
  shape mission rule 7 asks approvals to take.
* **The real ``heph serve --web``**, started by ``serve_fixture``'s own helper.
  Mission rule 6 applies to harnesses: a second definition of "start the shipped
  serve" would be a second thing to keep in step.

Prints one line — ``READY <base_url> <token> <project_root> <home> <model_url>``
— and then holds the world up until signalled.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serve_fixture import (  # the sys.path insert above is what makes this resolve
    await_ready,
    free_port,
    log,
    read_entry,
    stop,
)

#: The secret inside the scripted Pi ``auth.json``. It exists nowhere else, so a
#: substring of it anywhere in a response, a file, or a log is unambiguous.
DISCOVERED_SECRET = "oauth-refresh-E2E-71bc4a09-never-echo-me"

#: What the scripted endpoint replies with once a runtime is attached. The arc
#: test asserts this reaches the stream panel, so a turn that never ran cannot
#: be mistaken for one that did.
ARC_REPLY = "attached-and-streaming-9f3c1d"

#: The provider the scripted home directory is signed in to.
DISCOVERED_PROVIDER = "openai-codex"

#: The model ids the offer must be able to name **without** reading the secret.
DISCOVERED_MODELS = ["gpt-5-codex", "gpt-5-mini"]


def write_home(home: Path) -> Path:
    """A Pi installation with one OAuth login and a cached catalog beside it."""
    agent = home / ".pi" / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    auth = agent / "auth.json"
    auth.write_text(
        json.dumps(
            {
                DISCOVERED_PROVIDER: {
                    "type": "oauth",
                    "access": DISCOVERED_SECRET,
                    "refresh": DISCOVERED_SECRET,
                    "expires": 4102444800,
                }
            }
        ),
        encoding="utf-8",
    )
    os.chmod(auth, 0o600)
    # The NON-SECRET file the offer reads to say *which models*. §23.5's ruling
    # supersedes the draft's "no read before acceptance" precisely because an
    # offer that has read nothing cannot name a provider or its models.
    (agent / "models-store.json").write_text(
        json.dumps({DISCOVERED_PROVIDER: {"models": [{"id": m} for m in DISCOVERED_MODELS]}}),
        encoding="utf-8",
    )
    return auth


def start_local_endpoint() -> tuple[object, str]:
    """The shipped scripted OpenAI-compatible fake, on its own ephemeral port.

    Previously a twelve-line inline stub that answered only ``/v1/models``. That
    was enough for discovery — which asks a candidate endpoint what models it
    has — but it could not serve a completion, so the four G10B clauses that run
    a turn (attach without restart, configure against a scripted model, stream
    into the panel, sign out) had nothing to run against and were left to
    pytest. Using ``testing.fake_openai`` is mission rule 6 applied to harnesses:
    the suite that drives the shipped serve should drive the shipped fake, not a
    second definition of one. Its script answers any prompt with a terminal text
    turn, which is all the arc needs — the *tool* half of the loop is G4.8's
    fixture and is asserted there.
    """
    from hephaestus.testing.fake_openai import RequestInfo, start_fake_openai
    from hephaestus.testing.stream_assertions import text

    def resolve(_info: RequestInfo) -> dict[str, object]:
        return text(ARC_REPLY)

    fake = start_fake_openai([resolve] * 8)
    return fake, fake.base_url


def start_server(root: Path, *, home: Path, local_endpoint: str) -> subprocess.Popen[str]:
    """``heph serve --web`` with a scripted home directory and named endpoint.

    A copy of ``serve_fixture.start_server`` only in the sense that it spawns the
    same argv; what it adds is the environment G10C's clause is about, and that
    cannot ride on the shared helper without giving every other harness a
    discoverable home directory it does not want.
    """
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
    log(f"starting {' '.join(argv)} with HOME={home}")
    return subprocess.Popen(
        argv,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        env={
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "HOME": str(home),
            # The candidate list is OPERATOR-SUPPLIED. Nothing is scanned.
            "HEPHAESTUS_LOCAL_ENDPOINTS": local_endpoint,
            # A standing override would otherwise point the serve at the
            # developer's own config and remove the state under test.
            "HEPHAESTUS_AGENT_PROVIDERS": "",
        },
    )


def main() -> int:
    from hephaestus.testing.workspace_fixture import materialize_workspace_fixture

    scratch = Path(tempfile.mkdtemp(prefix="heph-providers-e2e-"))
    project_root = scratch / "workspace"
    home = scratch / "home"
    home.mkdir(parents=True, exist_ok=True)

    log(f"materializing a provider-less fixture at {project_root}")
    materialize_workspace_fixture(project_root)
    # DELIBERATELY NOT CONFIGURED: `.heph/providers.json` is the file G10B's
    # first clause says must not exist.
    write_home(home)
    endpoint, model_url = start_local_endpoint()

    server = start_server(project_root, home=home, local_endpoint=model_url)
    try:
        base_url, token = read_entry(server)
        await_ready(base_url, token)
        print(f"READY {base_url} {token} {project_root} {home} {model_url}", flush=True)
        stopping = {"now": False}

        def _stop(_signum: int, _frame: object) -> None:
            stopping["now"] = True

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, _stop)
        while not stopping["now"]:
            if server.poll() is not None:
                raise SystemExit(f"heph serve exited unexpectedly with {server.returncode}")
            time.sleep(0.25)
    finally:
        stop(server)
        endpoint.close()  # FakeOpenAI, not a Popen
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
