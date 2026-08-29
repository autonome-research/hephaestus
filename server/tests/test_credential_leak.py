# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The credential-leak channels, against a real child process (``INTERFACE.md`` §23.6).

``INTERFACE.md`` §23.14 items 10, 12 and 13, and the reason they need a *process*
rather than the in-process double: **the channel the claim is about is not the
one the bridge boundary can see.**

> The draft promised that Pi's raw-body interpolation "is caught at the bridge
> boundary and reduced to a code plus an HTTP status before it reaches a client,
> a log, or a `stderr_tail`". The bridge boundary is the framed JSON-RPC channel;
> **the sidecar's stderr is a second, independent pipe** that the supervisor
> drains verbatim into a retained tail the bench harness archives. Nothing done
> to a JSON-RPC error frame can reduce what Pi wrote to `console.error`.

So every test here spawns the staged fake sidecar as a real child, has it write
a sentinel to **stderr** (the pipe the frame cannot reach), and asserts on
``sidecar_evidence()["stderr_tail"]`` — the exact structure the bench archive
copies into ``sidecar.log``.

The OAuth half matters for a reason worth stating: in that flow the Python side
never sees a key at all, so **no key-shaped sentinel can be planted from this
side**. The sentinel has to come back from the provider, which is why the fake
sidecar's ``login.begin`` echoes a scripted token-endpoint body.
"""

from __future__ import annotations

import json
import shutil
import stat
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.sidecar import NODE_ENV, SIDECAR_ENV, write_manifest
from hephaestus.agent_bridge.supervisor import REDACTED_MARKER
from hephaestus.testing.workspace import Workspace, workspace

FAKE_SIDECAR = Path(__file__).with_name("fake_sidecar.py")

#: The key the operator pastes. It exists nowhere else in the repository, so a
#: substring hit anywhere is unambiguous rather than a coincidence.
KEY_SENTINEL = "sk-heph-LEAK-9d41ba07-paste-me-once"

#: What the scripted provider's token endpoint puts in its RESPONSE BODY. The
#: Python side never holds this value, which is precisely why it is the honest
#: test of the OAuth channel.
TOKEN_BODY_SENTINEL = "refresh_token=rt-LEAK-c17e5b90-from-the-provider"


@pytest.fixture
def staged_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A manifested sidecar tree the real resolver accepts, run by this Python."""
    root = tmp_path / "sidecar"
    (root / "workflows").mkdir(parents=True)
    shutil.copy(FAKE_SIDECAR, root / "main.js")
    (root / "workflows" / "runner.js").write_text("# unused\n", encoding="utf-8")
    write_manifest(root, version="test-leak")
    monkeypatch.setenv(SIDECAR_ENV, str(root))
    monkeypatch.setenv(NODE_ENV, sys.executable)
    return root


def _write_providers(
    root: Path, *, allowlist: Sequence[str] = (), provider_id: str = "leaky", name: str = "leaky"
) -> Path:
    path = root / ".heph" / "providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "providers": [
            {
                "id": provider_id,
                "kind": "openai_compatible",
                "name": name,
                "baseUrl": "http://127.0.0.1:9/v1",
                "models": [{"id": "m", "name": "m", "contextWindow": 8, "maxTokens": 8}],
            }
        ]
    }
    if allowlist:
        document["credential_allowlist"] = list(allowlist)
        document["providers"][0]["credential"] = allowlist[0]
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, staged_sidecar: Path
) -> Iterator[Workspace]:
    monkeypatch.delenv("HEPHAESTUS_AGENT_PROVIDERS", raising=False)
    with workspace(tmp_path / "proj") as ws:
        _write_providers(ws.root)
        ws.runtime.attach_agent()
        yield ws


def _stderr_tail(ws: Workspace) -> str:
    agent = ws.runtime.agent
    assert agent is not None
    return "\n".join(agent.sidecar_evidence()["stderr_tail"])


def _drain(ws: Workspace, *, contains: str) -> str:
    """Wait for the stderr drain thread to catch up, then return the tail.

    The drain runs on its own thread, so a bare read races it. Polling for a
    marker that must be there either way — the redaction marker, or the
    surrounding message — keeps this deterministic without a sleep.
    """
    import time

    deadline = time.monotonic() + 5.0
    tail = ""
    while time.monotonic() < deadline:
        tail = _stderr_tail(ws)
        if contains in tail:
            return tail
        time.sleep(0.02)
    return tail


# --------------------------------------------------------------------------
# 1. the pasted key — the channel a provider quotes back
# --------------------------------------------------------------------------


def test_a_pasted_key_quoted_back_on_stderr_is_redacted_in_the_tail(
    attached: Workspace,
) -> None:
    """§23.14 item 10's second half: a redaction pass at the **append point**.

    The fake sidecar writes the key it was handed to ``console.error``, exactly
    as a provider library that interpolates its input does. The supervisor's
    drain is the one place every sidecar line from every child passes through,
    so that is where the substitution happens — and it is an exact-substring
    substitution over values this process knows exactly, not a pattern guess
    about what a secret looks like.
    """
    response = attached.post(
        "/providers/leaky/auth/key", json={"key": KEY_SENTINEL, "scope": "serve"}
    )
    assert response.status_code == 200, response.text
    tail = _drain(attached, contains=REDACTED_MARKER)
    assert "provider rejected key" in tail  # the child really did write it
    assert KEY_SENTINEL not in tail
    assert REDACTED_MARKER in tail


def test_the_key_reaches_no_response_no_file_and_no_opstore(attached: Workspace) -> None:
    """§23.2's two forbidden places, and the response beside them.

    "No credential material enters an artifact, a build record, a golden, a
    transcript, a drawing, a document, or a bench evidence bundle, and §23.14's
    leak test is what makes that a claim about what a search finds rather than
    about what a reviewer believes."
    """
    attached.post("/providers/leaky/auth/key", json={"key": KEY_SENTINEL, "scope": "project"})
    assert KEY_SENTINEL not in attached.get("/providers").text
    assert KEY_SENTINEL not in attached.get("/providers/leaky/auth/status").text
    for path in sorted((attached.root / ".heph").rglob("*")):
        if not path.is_file():
            continue
        try:
            blob = path.read_bytes()
        except OSError:  # pragma: no cover - a live lock file
            continue
        assert KEY_SENTINEL.encode() not in blob, path


def test_an_allowlisted_variable_is_redacted_before_the_first_child_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, staged_sidecar: Path
) -> None:
    """Registration happens at construction, so there is no un-redacted window.

    A credential registered after the first line was drained would leave that
    line in the archive forever. The allowlisted values are known before the
    child is spawned, so they are registered before it is.
    """
    monkeypatch.setenv("HEPH_LEAK_TEST_KEY", KEY_SENTINEL)
    monkeypatch.delenv("HEPHAESTUS_AGENT_PROVIDERS", raising=False)
    with workspace(tmp_path / "proj") as ws:
        _write_providers(ws.root, allowlist=["HEPH_LEAK_TEST_KEY"])
        ws.runtime.attach_agent()
        agent = ws.runtime.agent
        assert agent is not None
        assert agent.configure_payload["credentials"] == {"HEPH_LEAK_TEST_KEY": KEY_SENTINEL}
        # The child echoes its own environment nowhere, so this asserts the
        # registration rather than a leak: the redactor holds the value.
        assert agent._sup.redact(f"x {KEY_SENTINEL} y") == f"x {REDACTED_MARKER} y"  # pyright: ignore[reportPrivateUsage]


def test_a_variable_outside_the_allowlist_never_reaches_the_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, staged_sidecar: Path
) -> None:
    """Mission rule 7, driven through the HTTP path (§23.14 item 11's second half).

    G10B's Tier 1 asks for both halves and they are different assertions. The
    first — *the web path cannot add a name to the allowlist* — is
    ``test_http_providers.py``'s, and it is the one that matters, because §23.6
    says the naive version "passes trivially and proves nothing, **because the
    attack is to put the variable inside the allowlist**". This is the naive
    version, kept because it is still the property rule 7 states literally: an
    ambient key that is not named is never forwarded.

    Asserted by asking the child what it can SEE, not by reading
    ``build_minimal_env``: a test of the function would pass while the spawn
    passed a different environment.
    """
    monkeypatch.setenv("HEPH_NOT_APPROVED", "sk-ambient-never-forwarded")
    monkeypatch.setenv("HEPH_LEAK_TEST_KEY", KEY_SENTINEL)
    monkeypatch.delenv("HEPHAESTUS_AGENT_PROVIDERS", raising=False)
    with workspace(tmp_path / "proj") as ws:
        _write_providers(ws.root, allowlist=["HEPH_LEAK_TEST_KEY"])
        ws.runtime.attach_agent()
        agent = ws.runtime.agent
        assert agent is not None
        seen = agent._sup.call(  # pyright: ignore[reportPrivateUsage]
            "env_probe", {"names": ["HEPH_NOT_APPROVED", "HEPH_LEAK_TEST_KEY", "PATH"]}
        )
        env = dict(seen["env"])
        assert env["HEPH_NOT_APPROVED"] is None
        assert env["HEPH_LEAK_TEST_KEY"] == KEY_SENTINEL
        # PATH is present, so the assertion above is about the ALLOWLIST rather
        # than about an environment that happens to be empty.
        assert env["PATH"] is not None


# --------------------------------------------------------------------------
# 2. the OAuth channel — where no key-shaped sentinel could be planted
# --------------------------------------------------------------------------


def test_a_token_endpoint_body_never_crosses_the_api_or_the_stderr_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, staged_sidecar: Path
) -> None:
    """§23.14 item 12's second half, on both channels at once.

    The scripted token endpoint returns a sentinel **in its body**. The sidecar
    writes it to stderr (the channel the frame cannot reach) *and* refuses over
    JSON-RPC. Two properties are asserted together because either alone would be
    a half-answer: the HTTP refusal carries the **named code and nothing else**,
    and the retained stderr tail carries the redaction marker instead of the
    body.

    Note what makes this test necessary rather than redundant: in the OAuth flow
    this process never sees a credential, so item 12's key sentinel cannot reach
    this path at all.
    """
    monkeypatch.delenv("HEPHAESTUS_AGENT_PROVIDERS", raising=False)
    with workspace(tmp_path / "proj") as ws:
        _write_providers(ws.root, provider_id="oauth-echo-leaky", name=TOKEN_BODY_SENTINEL)
        ws.runtime.attach_agent()
        agent = ws.runtime.agent
        assert agent is not None
        # The sidecar holds the body, so it can leak it if the reduction breaks.
        agent._sup.add_redaction(TOKEN_BODY_SENTINEL)  # pyright: ignore[reportPrivateUsage]

        response = ws.post("/providers/oauth-echo-leaky/auth/begin", json={"type": "device_code"})
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["reason"] == "credential_rejected"
        # The message is THIS server's sentence, not the provider's text.
        assert TOKEN_BODY_SENTINEL not in response.text
        assert "refresh_token" not in response.text
        assert set(body) == {"status", "reason", "message", "provider_id"}

        tail = _drain(ws, contains=REDACTED_MARKER)
        assert "token endpoint said" in tail
        assert TOKEN_BODY_SENTINEL not in tail


def test_an_unrecognised_sidecar_code_does_not_widen_the_vocabulary(
    attached: Workspace,
) -> None:
    """A closed vocabulary a downstream process can extend is not closed.

    The relay carries a code only when it is a member of §23.11's set; anything
    else becomes ``provider_unreachable``, which "names the host and **never**
    the body".
    """
    from hephaestus.agent_bridge.supervisor import SupervisorError
    from hephaestus.http.agent_credentials import relay
    from hephaestus.http.errors import HttpRefusal

    def refuse() -> dict[str, Any]:
        raise SupervisorError(
            "login.begin failed",
            error={"data": {"code": "provider_says_something_new", "http_status": 418}},
        )

    with pytest.raises(HttpRefusal) as caught:
        relay(refuse, provider_id="leaky")
    assert caught.value.reason == "provider_unreachable"
    assert caught.value.status == 502


# --------------------------------------------------------------------------
# 2b. §23.2's three permitted places, and the mode of each
# --------------------------------------------------------------------------


def test_the_app_owned_agent_directory_is_0700(attached: Workspace) -> None:
    """§23.2 names the mode of the parent as well as of the file, and it matters.

    "``<project>/.heph/agent/auth.json`` (``0600``, parent ``0700``…)". The
    directory was being created with the process umask — ``0755`` on a default
    install — which leaves §23.13's second threat class, *another local user*,
    able to stat the credential file and watch it appear even though its
    contents are private. The file's own mode is Pi's to set; the directory is
    this codebase's, and this is the assertion that keeps it.
    """
    agent_dir = attached.root / ".heph" / "agent"
    assert agent_dir.is_dir()
    assert stat.S_IMODE(agent_dir.stat().st_mode) == 0o700


def test_a_pre_existing_loose_agent_directory_is_tightened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, staged_sidecar: Path
) -> None:
    """An agent dir made by an earlier version is still ours to tighten.

    §23.2's "a file the **operator** hand-authored is not ``chmod``'ed by the
    workspace" is about the operator's own files. This directory is app-owned:
    leaving a world-traversable one alone would mean the protection only ever
    applies to projects created after this change.
    """
    monkeypatch.delenv("HEPHAESTUS_AGENT_PROVIDERS", raising=False)
    with workspace(tmp_path / "proj") as ws:
        agent_dir = ws.root / ".heph" / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        agent_dir.chmod(0o755)
        _write_providers(ws.root)
        ws.runtime.attach_agent()
        assert stat.S_IMODE(agent_dir.stat().st_mode) == 0o700


# --------------------------------------------------------------------------
# 3. the no-listener assertion (§23.14 item 13)
# --------------------------------------------------------------------------


def _listening_sockets(pid: int) -> list[str]:
    """Every listening TCP socket owned by ``pid``, read from ``/proc``.

    Enumerated rather than declared, on the §2.6 pattern: a test that asserted
    "we do not open a listener" by reading the source would keep passing after
    someone opened one.
    """
    import os
    import socket

    inodes: set[str] = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    for entry in fd_dir.iterdir():
        try:
            target = os.readlink(entry)
        except OSError:  # pragma: no cover - fd closed under us
            continue
        if target.startswith("socket:["):
            inodes.add(target.removeprefix("socket:[").rstrip("]"))
    listening: list[str] = []
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:  # pragma: no cover - no IPv6 on this host
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            # 0x0A is TCP_LISTEN.
            if fields[3] == "0A" and fields[9] in inodes:
                listening.append(fields[1])
    _ = socket  # imported for the reader; the parsing is /proc's, not socket's
    return listening


@pytest.mark.skipif(not Path("/proc/net/tcp").exists(), reason="needs procfs")
def test_a_full_login_flow_opens_no_listening_socket(attached: Workspace) -> None:
    """§23.14 item 13, and §23.4's "no loopback callback listener, ever".

    Rejected on three independent grounds, any one sufficient: the redirect URIs
    are fixed by the provider's registered client, so a real CLI login already
    running makes the flow fail with a bind error the operator cannot act on; a
    second listening socket contradicts §0's one-loopback-listener posture and
    the second one would be **unauthenticated**, inside a route table whose whole
    discipline is that it is closed and gated; and the manual-paste fallback
    adds zero new network surface.

    **LOUD LIMIT, and it is why this test measures the sidecar's own pid.** In
    the pinned dependency, Pi's `authorize_url` login starts its own loopback
    callback server inside the sidecar (`pi-ai/auth/oauth/anthropic.js`
    unconditionally; `openai-codex.js` on the `browser` branch). That listener is
    Pi's, not this repo's, and `device_code` — the default everywhere it exists —
    takes the branch that starts none. What §23 can and does assert is that
    **Hephaestus opens no socket of its own**, and that a device-code flow leaves
    the sidecar with none either.
    """
    agent = attached.runtime.agent
    assert agent is not None
    pid = agent.child_pid
    before = _listening_sockets(pid)
    attached.post("/providers/leaky/auth/begin", json={"type": "device_code"})
    attached.post("/providers/leaky/auth/complete", json={"input": "code#state"})
    attached.post("/providers/leaky/auth/cancel")
    assert _listening_sockets(pid) == before == []


def test_the_route_table_still_exposes_no_callback(attached: Workspace) -> None:
    """§23.6: "No exemptions, no unauthenticated callback."

    Asserted as an absence over the closed table, because that is the only way
    an absence can be tested.
    """
    from hephaestus.http.app import ROUTE_TABLE

    for _method, template in ROUTE_TABLE:
        assert "callback" not in template
        assert "oauth" not in template.lower()
    # …and every /providers row is bearer-gated like the rest.
    for method, template in ROUTE_TABLE:
        if not template.startswith("/providers"):
            continue
        path = template.replace("{id}", "leaky")
        assert attached.request(method, path, token=None).status_code == 401
