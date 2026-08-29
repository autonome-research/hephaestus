# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Attaching an agent runtime to a running serve (``INTERFACE.md`` §23.0).

The state under test is the one §23.0 says the section exists to fix: a project
with **no** ``providers.json``. Before this work that serve had no
``BridgeRuntime``, no ``Supervisor`` and no sidecar at all, and nothing in the
process could make one exist — so every credential route of §23, each a relay to
the sidecar, refused in exactly the zero-config case, and the operator was sent
back to a terminal.

Everything here drives a **real child process** through the **real** resolver:
the fixture stages a manifested sidecar tree whose ``main.js`` is the scripted
``fake_sidecar.py``, and points ``$HEPHAESTUS_NODE`` at this interpreter. So
``resolve_sidecar``, ``verify_sidecar``, ``Supervisor.start``, the spawn hook's
``runtime.configure`` replay and ``BridgeRuntime.close`` are all the shipped
code — with no Node, no built sidecar and no provider. The one thing that is a
double is what a model would have said.

Every scenario ends by asserting **no orphaned sidecar**, which is the property
the pre-existing code silently lost: ``Supervisor.start`` spawns the child and
*then* replays ``runtime.configure``, so a provider that fails verification
raised with a live child that ``_attach_agent`` dropped on the floor.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.sidecar import NODE_ENV, SIDECAR_ENV, write_manifest
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.http.agent_attach import (
    ATTACH_CAUSES,
    AgentAlreadyAttached,
    AgentAttachState,
    AttachRefused,
    reduce_detail,
)
from hephaestus.http.app import ROUTE_TABLE
from hephaestus.http.idempotency import (
    CREDENTIAL_ROUTES,
    KEY_REQUIRED_ROUTES,
    SESSION_CONTROL_ROUTES,
    requires_key,
    validate_key,
)
from hephaestus.testing.workspace import Workspace, uuid7, workspace

FAKE_SIDECAR = Path(__file__).with_name("fake_sidecar.py")

ATTACH_ROUTE = "/providers/attach"

#: The sentinel a credential-leak assertion looks for. Long and unmistakable:
#: a short value would be indistinguishable from ordinary message text.
SENTINEL = "sk-attach-sentinel-8f3d9a2c4b1e"


# --------------------------------------------------------------------------
# fixtures


@pytest.fixture
def staged_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A manifested sidecar tree the real resolver accepts, run by this Python.

    ``$HEPHAESTUS_SIDECAR`` + ``$HEPHAESTUS_NODE`` are the two documented
    overrides (``sidecar.py``: an operator who names a binary has already
    decided), so this exercises the ordered resolution policy and the integrity
    verification rather than routing around them with ``dist_main``.
    """
    root = tmp_path / "sidecar"
    (root / "workflows").mkdir(parents=True)
    shutil.copy(FAKE_SIDECAR, root / "main.js")
    (root / "workflows" / "runner.js").write_text("# unused by these tests\n", encoding="utf-8")
    write_manifest(root, version="test-attach")
    monkeypatch.setenv(SIDECAR_ENV, str(root))
    monkeypatch.setenv(NODE_ENV, sys.executable)
    return root


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Workspace]:
    """A workspace over a scaffolded project with **no** provider config.

    ``HEPHAESTUS_AGENT_PROVIDERS`` is cleared because it is a standing override:
    a developer who has one exported would otherwise be testing their own
    machine's configuration instead of the zero-config state.
    """
    monkeypatch.delenv("HEPHAESTUS_AGENT_PROVIDERS", raising=False)
    with workspace(tmp_path / "proj") as opened:
        yield opened


def write_providers(
    ws: Workspace, *, provider_id: str = "fake", allowlist: Sequence[str] = ()
) -> Path:
    """Write the project's ``providers.json`` — the file the operator lacks."""
    path = ws.root / ".heph" / "providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "providers": [
            {
                "id": provider_id,
                "kind": "openai_compatible",
                "baseUrl": "http://127.0.0.1:9/v1",
                "credential": "ATTACH_SENTINEL_KEY",
                "models": [{"id": "m"}],
            }
        ]
    }
    if allowlist:
        document["credential_allowlist"] = list(allowlist)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def child_pids(spawn_log: Path) -> list[int]:
    """Every pid the staged sidecar recorded for itself, in spawn order."""
    if not spawn_log.is_file():
        return []
    return [
        int(line.split()[0])
        for line in spawn_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------
# 1. the state §23.0 exists to fix


def test_a_serve_starts_with_no_provider_config_and_names_why(ws: Workspace) -> None:
    """Zero-config: reads serve, sessions refuse **by name and with a cause**.

    §7A.8/§19.25: the serve used to know exactly why the attach produced nothing
    and write it to a stderr no browser will ever read. The refusal now carries
    it, so the panel can render a state that reads as designed rather than as a
    blank one that reads as a bug (§4.4).
    """
    with pytest.raises(AttachRefused) as caught:
        ws.runtime.attach_agent()  # what `heph serve --web` does at start-up
    assert caught.value.cause == "no_provider_config"

    # Every route that needs no agent still serves.
    assert ws.get("/project").status_code == 200
    assert ws.get("/parts").status_code == 200

    refused = ws.get("/sessions")
    assert refused.status_code == 503
    body = refused.json()
    assert body["reason"] == "agent_unavailable"
    assert body["cause"] == "no_provider_config"
    assert body["attached"] is False
    assert body["config_path"].endswith("providers.json")
    assert body["generation"] == 0


def test_the_attach_route_refuses_the_missing_config_by_name(ws: Workspace) -> None:
    """``POST /providers/attach`` is a **named** refusal, not a 500 or a silence.

    And it is not ``agent_unavailable``: §23.0's route table puts this route in
    the row that *creates* a runtime, so refusing it for the absence of one
    would restore the deadlock it exists to remove.
    """
    response = ws.post(ATTACH_ROUTE)
    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "attach_failed"
    assert body["cause"] == "no_provider_config"
    assert body["reason"] != "agent_unavailable"
    assert ws.runtime.sessions is None


def test_the_attach_route_takes_no_arguments(ws: Workspace) -> None:
    """Closed rather than permissive: an unknown field is refused, not ignored."""
    response = ws.post(ATTACH_ROUTE, json={"providers": []})
    assert response.status_code == 400
    body = response.json()
    assert body["reason"] == "invalid_params"
    assert body["unexpected"] == ["providers"]


# --------------------------------------------------------------------------
# 2. attach, use, detach, re-attach


def test_attach_puts_the_session_routes_into_service(
    ws: Workspace, staged_sidecar: Path, tmp_path: Path
) -> None:
    """The §23.0 success path: the refusal disappears and a session runs.

    "The success path of sign-in is not *the panel says connected*" — it is
    ``agent_unavailable`` disappearing, ``GET /sessions`` returning, and the
    empty state becoming an action. This asserts exactly that sequence, in
    order, through HTTP.
    """
    assert ws.get("/sessions").status_code == 503
    write_providers(ws)

    attached = ws.post(ATTACH_ROUTE)
    assert attached.status_code == 200, attached.text
    body = attached.json()
    assert body == {
        "status": "ok",
        "attached": True,
        "config_path": str(ws.root / ".heph" / "providers.json"),
        "generation": 1,
    }

    listed = ws.get("/sessions")
    assert listed.status_code == 200
    assert listed.json()["sessions"] == []

    created = ws.post("/sessions", json={"profile": "orchestrator"})
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]

    prompted = ws.post(f"/sessions/{session_id}/prompt", json={"text": "hello"})
    assert prompted.status_code == 200, prompted.text
    assert prompted.json()["session_id"] == session_id

    # A real child, and it is this process's to reap.
    agent = ws.runtime.agent
    assert agent is not None
    pid = agent.child_pid
    assert pid_alive(pid)


def test_detach_is_an_honest_state_and_re_attach_works(ws: Workspace, staged_sidecar: Path) -> None:
    """Detach → refuse again, by its **own** cause → attach again, generation 2.

    A detached serve reported as ``no_provider_config`` would be a lie the file
    on disk contradicts, so detachment gets its own cause. And the re-attach is
    what makes detach a state rather than a one-way door.
    """
    write_providers(ws)
    assert ws.post(ATTACH_ROUTE).status_code == 200
    pid = ws.runtime.agent.child_pid if ws.runtime.agent is not None else 0
    assert pid_alive(pid)

    detached = ws.runtime.detach_agent()
    assert detached.attached is False
    assert detached.cause == "detached"
    assert detached.generation == 1
    # The sidecar went with it: a detach that left the child running would be a
    # label rather than a state.
    assert not pid_alive(pid), "sidecar survived detach"

    refused = ws.get("/sessions")
    assert refused.status_code == 503
    assert refused.json()["reason"] == "agent_unavailable"
    assert refused.json()["cause"] == "detached"

    # Idempotent: detaching twice does not invent a second transition.
    assert ws.runtime.detach_agent().generation == 1

    again = ws.post(ATTACH_ROUTE)
    assert again.status_code == 200
    assert again.json()["generation"] == 2
    assert ws.get("/sessions").status_code == 200
    second_pid = ws.runtime.agent.child_pid if ws.runtime.agent is not None else 0
    assert second_pid != pid
    assert pid_alive(second_pid)


def test_a_second_attach_is_refused_by_name_and_the_first_survives(
    ws: Workspace, staged_sidecar: Path
) -> None:
    """No silent replacement: §23.7 makes replacing a runtime an explicit act.

    A replacement kills every in-flight run in every session, which is never a
    side effect of a request that read as "make sure there is a runtime".
    """
    write_providers(ws)
    assert ws.post(ATTACH_ROUTE).status_code == 200
    agent = ws.runtime.agent
    assert agent is not None
    pid = agent.child_pid

    second = ws.post(ATTACH_ROUTE)
    assert second.status_code == 409
    assert second.json()["reason"] == "agent_already_attached"
    assert second.json()["attached"] is True

    # Untouched: same child, same generation, sessions still served.
    assert ws.runtime.agent is agent
    assert agent.child_pid == pid
    assert pid_alive(pid)
    assert ws.get("/sessions").status_code == 200

    with pytest.raises(AgentAlreadyAttached):
        ws.runtime.attach_agent()


def test_the_sidecar_outlives_the_request_that_spawned_it(
    ws: Workspace, staged_sidecar: Path
) -> None:
    """Regression, and the reason ``WorkspaceRuntime.spawn_executor`` exists.

    ``PR_SET_PDEATHSIG`` — the mechanism that makes the sidecar orphan-free — is
    delivered when the **spawning thread** exits, not the process. That was
    invisible while every spawn happened on the main thread during serve
    start-up; an attach served on a pooled worker died with that worker, which
    reads as a runtime that attached and then silently vanished. This drives
    enough traffic afterwards that any per-request worker is long gone.
    """
    write_providers(ws)
    assert ws.post(ATTACH_ROUTE).status_code == 200
    agent = ws.runtime.agent
    assert agent is not None
    pid = agent.child_pid

    for _ in range(8):
        assert ws.get("/project").status_code == 200

    assert pid_alive(pid), "the sidecar died with the thread that spawned it"
    assert ws.get("/sessions").status_code == 200
    assert ws.post("/sessions", json={"profile": "orchestrator"}).status_code == 200


# --------------------------------------------------------------------------
# 3. a failed attach: named, prior state, no orphan


def test_a_failed_attach_refuses_by_name_and_leaves_no_sidecar_behind(
    ws: Workspace, staged_sidecar: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this item exists to close, asserted end to end.

    ``Supervisor.start`` spawns the child and *then* replays
    ``runtime.configure``, so a provider that fails verification — §23.7's whole
    subject — raises with a **live** child. The pre-existing ``_attach_agent``
    caught that exception and returned ``None``, orphaning the sidecar for the
    life of the serve. Here the child must be gone and the server must still be
    usable, including for a later attach that succeeds.
    """
    spawn_log = tmp_path / "spawns.log"
    # The scripted sidecar's knobs travel through the credential allowlist
    # because the child's environment is minimal by design (`build_minimal_env`).
    monkeypatch.setenv("FAKE_SIDECAR_SPAWN_LOG", str(spawn_log))
    write_providers(ws, provider_id="configure-fails", allowlist=["FAKE_SIDECAR_SPAWN_LOG"])

    refused = ws.post(ATTACH_ROUTE)
    assert refused.status_code == 409
    body = refused.json()
    assert body["reason"] == "attach_failed"
    assert body["cause"] == "sidecar_failed"
    assert body["attached"] is False

    # The prior state, exactly: nothing bound, nothing half-bound.
    assert ws.runtime.sessions is None
    assert ws.runtime.agent is None
    assert ws.get("/sessions").status_code == 503
    assert ws.get("/sessions").json()["cause"] == "sidecar_failed"
    # ...and the rest of the server is not wedged.
    assert ws.get("/project").status_code == 200

    spawned = child_pids(spawn_log)
    assert spawned, "the scripted sidecar never recorded a spawn"
    for pid in spawned:
        assert not pid_alive(pid), f"sidecar pid {pid} outlived a failed attach"

    # Not wedged for attaching, either: fix the config and the serve recovers
    # without a restart, which is the whole product claim of this item.
    write_providers(ws)
    assert ws.post(ATTACH_ROUTE).status_code == 200
    assert ws.get("/sessions").status_code == 200


def test_a_provider_config_that_is_not_json_is_its_own_cause(ws: Workspace) -> None:
    """``provider_config_invalid`` is not folded into ``sidecar_failed``."""
    path = ws.root / ".heph" / "providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    refused = ws.post(ATTACH_ROUTE)
    assert refused.status_code == 409
    assert refused.json()["cause"] == "provider_config_invalid"


def test_a_missing_node_is_its_own_cause(
    ws: Workspace, staged_sidecar: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``node_missing`` and ``node_too_old`` are distinguished by **type**.

    §7A.8's vocabulary separates them because they need different sentences from
    an operator — install Node, or upgrade it — and deriving that from an
    exception *message* would put a machine-readable refusal at the mercy of a
    sentence edit.
    """

    def no_node(_name: str, *_args: object, **_kwargs: object) -> str | None:
        return None

    monkeypatch.delenv(NODE_ENV, raising=False)
    monkeypatch.setattr("shutil.which", no_node)
    write_providers(ws)

    refused = ws.post(ATTACH_ROUTE)
    assert refused.status_code == 409
    assert refused.json()["cause"] == "node_missing"
    assert ws.runtime.sessions is None


# --------------------------------------------------------------------------
# 4. no credential reaches the refusal


def test_no_credential_reaches_the_attach_refusal(
    ws: Workspace, staged_sidecar: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§23.2/§23.6: the reduction happens **where the bytes are**.

    The scripted provider answers ``runtime.configure`` by quoting the whole
    payload back — the provider-echoes-its-input channel §23.6 names, and the
    one no key-shaped sentinel could otherwise be planted in. The credential
    must appear in neither the refusal body nor the recorded attach state.
    """
    monkeypatch.setenv("ATTACH_SENTINEL_KEY", SENTINEL)
    write_providers(ws, provider_id="configure-echo", allowlist=["ATTACH_SENTINEL_KEY"])

    refused = ws.post(ATTACH_ROUTE)
    assert refused.status_code == 409
    assert refused.json()["cause"] == "sidecar_failed"
    assert SENTINEL not in refused.text
    assert "[redacted]" in refused.json()["detail"]

    state = ws.runtime.agent_attach_state()
    assert state is not None
    assert SENTINEL not in json.dumps(state.projection())


def test_reduce_detail_redacts_exactly_the_values_it_was_given() -> None:
    """Exact substrings, not a pattern guess — and bounded."""
    reduced = reduce_detail(RuntimeError(f"provider said {SENTINEL} loudly"), (SENTINEL,))
    assert SENTINEL not in reduced
    assert "[redacted]" in reduced
    assert reduced.startswith("RuntimeError: ")
    assert len(reduce_detail(RuntimeError("x" * 5000))) <= 300


# --------------------------------------------------------------------------
# 5. the closed surfaces this route joins


def test_the_attach_route_is_in_the_closed_table_and_needs_no_key() -> None:
    """§2.3: one row, in the credential group, with its own no-key argument.

    A byte-for-byte replay of a credential change would be a *silent security
    failure*, which is why this group exists rather than being folded into
    session control.
    """
    assert ("POST", ATTACH_ROUTE) in ROUTE_TABLE
    # REPOINTED, and the amendment is §2.3's own credential-mutation list. This
    # asserted `CREDENTIAL_ROUTES == (attach,)` when attach was the only row
    # SERVED — a statement about which stage had landed, not about a behaviour.
    # §23.6's routes have now landed (§23.14 item 2), so the pin becomes what it
    # was always for: the group is exactly §2.3's list, and no member of it
    # requires a key. Nothing is weakened — every property below is asserted for
    # every member, where it used to be asserted for one.
    assert set(CREDENTIAL_ROUTES) == {
        ("POST", ATTACH_ROUTE),
        ("POST", "/providers/discover"),
        ("POST", "/providers/adopt"),
        ("POST", "/providers/auth/unlink"),
        ("POST", "/providers/{id}/auth/key"),
        ("POST", "/providers/{id}/auth/begin"),
        ("POST", "/providers/{id}/auth/complete"),
        ("POST", "/providers/{id}/auth/cancel"),
        ("POST", "/providers/{id}/auth/signout"),
    }
    assert set(CREDENTIAL_ROUTES) & set(KEY_REQUIRED_ROUTES) == set()
    assert set(CREDENTIAL_ROUTES) & set(SESSION_CONTROL_ROUTES) == set()
    for method, template in CREDENTIAL_ROUTES:
        assert not requires_key(method, template)
        assert validate_key(None, method=method, template=template) is None
        # A supplied key is IGNORED rather than honoured.
        assert validate_key(uuid7(), method=method, template=template) is None


def test_a_supplied_key_is_ignored_by_the_attach_route(ws: Workspace) -> None:
    """The policy above, through HTTP: the key changes nothing about the answer."""
    keyed = ws.post(ATTACH_ROUTE, key=uuid7())
    assert keyed.status_code == 409
    assert keyed.json()["reason"] == "attach_failed"


def test_the_attach_cause_vocabulary_is_closed() -> None:
    """Nothing constructs a cause at a call site; an unknown one is refused."""
    assert ATTACH_CAUSES == (
        "no_provider_config",
        "provider_config_invalid",
        "node_missing",
        "node_too_old",
        "sidecar_failed",
        "auth_link_refused",
        "detached",
    )
    with pytest.raises(ValueError, match="closed vocabulary"):
        AgentAttachState(attached=False, config_path="/x", cause="made_up")
    with pytest.raises(ValueError, match="attached"):
        AgentAttachState(attached=True, config_path="/x", cause="detached")
    with pytest.raises(ValueError, match="attached"):
        AgentAttachState(attached=False, config_path="/x")
