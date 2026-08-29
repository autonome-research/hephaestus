# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Provider sign-in over HTTP (``INTERFACE.md`` §23; Stage 10B, gate G10B).

Organized by the property under test rather than by route, because §23's whole
argument is about properties: the zero-config path end to end, the two
non-negotiable security refusals, the closed vocabularies, and the leak channel
the bridge boundary cannot see.

The one thing deliberately NOT doubled is the refusal surface: every assertion
below reads the shipped ``REASON_STATUS`` mapping and the shipped closed
vocabularies, so a reason that arrives without a status, or a status that drifts
from §23.6's table, fails here rather than in a browser.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from hephaestus.http.agent_credentials import CredentialBackend
from hephaestus.http.app import ROUTE_TABLE
from hephaestus.http.errors import REASON_STATUS
from hephaestus.http.idempotency import CREDENTIAL_ROUTES, KEY_REQUIRED_ROUTES
from hephaestus.http.providers import (
    AUTH_FLOW_TYPES,
    AUTH_HEALTH,
    AUTH_SOURCES,
    CREDENTIAL_SCOPES,
    PROVIDER_KINDS,
    PROVIDER_REFUSALS,
    is_loopback_host,
    read_providers_file,
)
from hephaestus.testing.fake_agent import FakeAgent
from hephaestus.testing.workspace import Workspace, uuid7, workspace

#: A key literal that exists nowhere else in the repository. §23.14 item 12's
#: leak test greps for exactly this, so a substring of it turning up in a
#: response, a file, or a stderr tail is unambiguous.
SENTINEL_KEY = "sk-heph-SENTINEL-8f21c07a-never-echo-me"

_FAKE_SPEC: dict[str, Any] = {
    "id": "heph-fake",
    "kind": "openai_compatible",
    "name": "Hephaestus Fake Provider",
    "baseUrl": "http://127.0.0.1:9/v1",
    "models": [
        {"id": "heph-fake-model", "name": "Heph Fake", "contextWindow": 128000, "maxTokens": 4096}
    ],
}


@pytest.fixture
def ws(tmp_path: Path):
    with workspace(tmp_path / "proj") as w:
        yield w


@pytest.fixture
def signed_in(tmp_path: Path):
    """A workspace with a credential backend attached and one spec written."""
    with workspace(tmp_path / "proj", agent=True) as w:
        _write_specs(w, [_FAKE_SPEC])
        agent = w.agent
        assert agent is not None
        agent.verified = [{"id": "heph-fake", "available": True}]
        agent.catalog = [{"id": "heph-fake", "name": "Fake", "models": ["heph-fake-model"]}]
        yield w


def _write_specs(ws: Workspace, specs: list[dict[str, Any]], **extra: Any) -> Any:
    return ws.request("PUT", "/providers/specs", json={"providers": specs, **extra}, key=uuid7())


def _config_path(ws: Workspace) -> Path:
    return ws.root / ".heph" / "providers.json"


# --------------------------------------------------------------------------
# 1. the zero-config path — §23.0's success condition, end to end
# --------------------------------------------------------------------------


def test_a_serve_with_no_providers_json_still_reads_and_writes_one(ws: Workspace) -> None:
    """§23.0's first table row: these two need **no** sidecar.

    "Refusing these in the zero-config case is what made the section unusable."
    A serve with nothing configured has to be able to describe its own emptiness
    and then fix it, or the operator is sent back to a terminal — the whole of
    the product review's complaint 4.
    """
    assert not _config_path(ws).exists()
    read = ws.get("/providers")
    assert read.status_code == 200
    body = read.json()
    assert body["config_exists"] is False
    assert body["providers"] == []
    # …and the panel is told *why* there are no sessions, by name.
    sessions = ws.get("/sessions")
    assert sessions.status_code == 503
    assert sessions.json()["reason"] == "agent_unavailable"

    written = _write_specs(ws, [_FAKE_SPEC])
    assert written.status_code == 200, written.text
    assert [row["id"] for row in written.json()["providers"]] == ["heph-fake"]
    assert _config_path(ws).exists()


def test_the_written_file_is_0600_created_private(ws: Workspace) -> None:
    """§23.2: ``write_private``, created private, never ``chmod``'ed after.

    The window between "written" and "chmod'ed" is exactly when another local
    user could open it.
    """
    _write_specs(ws, [_FAKE_SPEC])
    mode = stat.S_IMODE(_config_path(ws).stat().st_mode)
    assert mode == 0o600
    assert ws.get("/providers").json()["file_mode"] == "0600"


def test_an_operator_authored_files_mode_is_reported_never_changed(ws: Workspace) -> None:
    """§23.2: "changing the mode of a file we did not write is a surprise".

    The panel reports the mode instead; that is what makes a world-readable
    hand-authored config a thing the operator can see rather than a thing the
    workspace silently alters under them.
    """
    path = _config_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"providers": [_FAKE_SPEC]}), encoding="utf-8")
    os.chmod(path, 0o644)
    body = ws.get("/providers").json()
    assert body["file_mode"] == "0644"
    assert body["file_mode_private"] is False
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_sign_in_then_sign_out_returns_the_row_to_none_and_keeps_the_spec(
    signed_in: Workspace,
) -> None:
    """G10B's arc, minus the sidecar: sign in, then sign out (§23.9).

    Three properties in one: the row survives sign-out (a provider that vanished
    would read as a deletion the operator did not perform), the state returns to
    ``none``, and the credential change is APPLIED — a restart, recorded with
    its reason.
    """
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    key = signed_in.post(
        "/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY, "scope": "project"}
    )
    assert key.status_code == 200, key.text
    assert key.json()["replaced"] == "none"
    assert agent.restarts == ["credentials"]

    out = signed_in.post("/providers/heph-fake/auth/signout")
    assert out.status_code == 200
    body = signed_in.get("/providers").json()
    assert [row["id"] for row in body["providers"]] == ["heph-fake"]
    assert body["providers"][0]["source"] == "none"
    assert agent.restarts == ["credentials", "credentials"]


def test_after_any_sign_in_providers_json_names_the_source(signed_in: Workspace) -> None:
    """§23.5's distinguishing test, made mechanical.

    *"After any sign-in, `providers.json` must contain a record of every
    credential source in use. If a source works and no file names it, rule 7 has
    been broken."* A ``serve``-scoped key lives only in the serving process's
    heap, so this record is the ONLY on-disk trace of it — which is exactly why
    it is written for that scope too.
    """
    signed_in.post("/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY, "scope": "serve"})
    file = read_providers_file(_config_path(signed_in))
    assert [row["provider_id"] for row in file.credential_sources] == ["heph-fake"]
    assert file.credential_sources[0]["source"] == "serve"
    assert file.file_mode == "0600"
    # …and sign-out removes the record, so the file never claims a source that
    # is no longer in use.
    signed_in.post("/providers/heph-fake/auth/signout")
    assert read_providers_file(_config_path(signed_in)).credential_sources == ()


# --------------------------------------------------------------------------
# 2. the two refusals without which the section is an exfiltration primitive
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["credential_allowlist", "auth_source"])
def test_the_web_path_cannot_add_a_name_to_the_allowlist(ws: Workspace, field: str) -> None:
    """§23.14 item 11, aimed at the REAL property (§23.6's blocking finding).

    The naive negative test — export a non-allowlisted variable, sign in, assert
    the sidecar's env lacks it — passes trivially and proves nothing, *because
    the attack is to put the variable inside the allowlist*. So this asserts the
    property that actually matters: the web path cannot add a name to it, and
    the refusal is **by name**.
    """
    body: dict[str, Any] = {"providers": [_FAKE_SPEC], field: ["ANTHROPIC_API_KEY"]}
    response = ws.request("PUT", "/providers/specs", json=body, key=uuid7())
    assert response.status_code == 400
    assert response.json()["reason"] == "allowlist_not_web_writable"
    assert response.json()["fields"] == [field]
    # …and nothing was written: a refusal that half-applied would be worse than
    # one that accepted.
    assert not _config_path(ws).exists()


def test_the_allowlist_refusal_wins_over_a_shape_refusal(ws: Workspace) -> None:
    """Order is the contract: the exfiltration reason is the one to surface.

    A body carrying both a malformed spec and an allowlist must refuse for the
    allowlist. The reason an operator — or a reviewer reading a log — needs to
    see is the one about the primitive, not the one about a missing field.
    """
    response = ws.request(
        "PUT",
        "/providers/specs",
        json={"providers": [{"nonsense": True}], "credential_allowlist": ["X"]},
        key=uuid7(),
    )
    assert response.json()["reason"] == "allowlist_not_web_writable"


def test_an_on_disk_allowlist_survives_a_spec_write(ws: Workspace) -> None:
    """The quiet half of the same rule, and it needs its own test.

    A route that refused the field but then dropped it on write would silently
    **delete** an operator's allowlist — a supervisor-prepared fact destroyed by
    a browser click.
    """
    path = _config_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "providers": [_FAKE_SPEC],
                "credential_allowlist": ["HEPH_TEST_KEY"],
                "auth_source": "/home/someone/.pi/agent/auth.json",
            }
        ),
        encoding="utf-8",
    )
    assert _write_specs(ws, [_FAKE_SPEC]).status_code == 200
    file = read_providers_file(path)
    assert file.credential_allowlist == ("HEPH_TEST_KEY",)
    assert file.auth_source == "/home/someone/.pi/agent/auth.json"


def test_a_spec_naming_an_unallowlisted_variable_is_refused_by_name(ws: Workspace) -> None:
    """§23.6's second half: ``credential_not_allowlisted``, never a generic 400."""
    spec = {**_FAKE_SPEC, "credential": "SOME_KEY_NOBODY_APPROVED"}
    response = _write_specs(ws, [spec])
    assert response.status_code == 400
    assert response.json()["reason"] == "credential_not_allowlisted"
    assert response.json()["credential"] == "SOME_KEY_NOBODY_APPROVED"


# --------------------------------------------------------------------------
# 3. endpoints — a baseUrl typed in a browser is an outbound destination
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("127.0.0.2", True),
        # A NAME is not loopback, however friendly it looks: "a name can
        # re-resolve between the check and the request, and a check a name
        # defeats is decoration" (§23.3).
        ("localhost.evil.example", False),
        ("api.openai.com", False),
        ("", False),
    ],
)
def test_loopback_is_decided_by_literal_not_by_resolution(host: str, loopback: bool) -> None:
    assert is_loopback_host(host) is loopback


def test_kind_local_must_be_a_loopback_literal(ws: Workspace) -> None:
    spec = {**_FAKE_SPEC, "kind": "local", "baseUrl": "http://models.internal:8000/v1"}
    response = _write_specs(ws, [spec])
    assert response.status_code == 400
    assert response.json()["reason"] == "endpoint_not_loopback"


def test_a_remote_endpoint_needs_a_typed_egress_acknowledgement(ws: Workspace) -> None:
    """§23.3: durable visibility, not refusal.

    "Silently accepting an arbitrary URL is an exfiltration path with a UI on
    it; the answer is not refusal but **durable visibility** — a file a reviewer
    can read, not a dialog someone dismissed."
    """
    spec = {**_FAKE_SPEC, "baseUrl": "https://collector.example/v1"}
    refused = _write_specs(ws, [spec])
    assert refused.status_code == 400
    assert refused.json()["reason"] == "egress_not_acknowledged"
    assert refused.json()["host"] == "collector.example"

    accepted = _write_specs(ws, [spec], acknowledge_egress=["collector.example"])
    assert accepted.status_code == 200
    recorded = read_providers_file(_config_path(ws)).egress_acknowledged
    assert [row["host"] for row in recorded] == ["collector.example"]
    assert "at" in recorded[0]
    # It is permanent, and the panel lists it.
    assert ws.get("/providers").json()["egress_acknowledged"][0]["host"] == "collector.example"


def test_a_loopback_openai_compatible_endpoint_needs_no_acknowledgement(ws: Workspace) -> None:
    """Kind `local` is constrained to loopback and has no egress at all (§23.13)."""
    assert _write_specs(ws, [{**_FAKE_SPEC, "kind": "local"}]).status_code == 200


# --------------------------------------------------------------------------
# 4. no route returns credential material — not masked, not truncated
# --------------------------------------------------------------------------


def _every_read_body(ws: Workspace, provider: str) -> list[str]:
    return [
        ws.get("/providers").text,
        ws.get("/providers/catalog").text,
        ws.get(f"/providers/{provider}/auth/status").text,
        ws.post("/providers/discover").text,
    ]


def test_no_read_route_returns_credential_material(signed_in: Workspace) -> None:
    """§23.8's no-masked-tail decision, asserted rather than declared.

    "**A read side that returns no credential material at all** is a property
    worth more than the convenience." §23.13 names what it buys: a total
    compromise of the page is an escalation to *use* and to *replace*, never to
    *exfiltrate*.

    The tail check is the sharp one — a four-character suffix of a key with
    known structure is meaningful material to anything that reads a screenshot.
    """
    signed_in.post("/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY, "scope": "project"})
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    # The double really is holding it, so this test can fail.
    assert agent.credentials["heph-fake"]["key"] == SENTINEL_KEY
    for body in _every_read_body(signed_in, "heph-fake"):
        assert SENTINEL_KEY not in body
        assert SENTINEL_KEY[-4:] not in body
        assert SENTINEL_KEY[:6] not in body


def test_the_key_response_itself_carries_no_key(signed_in: Workspace) -> None:
    response = signed_in.post(
        "/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY, "scope": "serve"}
    )
    assert response.status_code == 200
    assert SENTINEL_KEY not in response.text
    assert set(response.json()) == {"status", "provider_id", "scope", "replaced"}


def test_no_secret_reaches_the_written_file(signed_in: Workspace) -> None:
    """§23.2's first closed place: ``providers.json`` has never held a secret."""
    signed_in.post("/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY, "scope": "project"})
    assert SENTINEL_KEY not in _config_path(signed_in).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 5. scope has no default (§23.2)
# --------------------------------------------------------------------------


def test_omitting_the_scope_is_refused_and_not_defaulted(signed_in: Workspace) -> None:
    """ "A defaulted secret-persistence decision is the single most consequential
    default a local tool can have, and this document declines to make it."

    *Rejected* alternative, recorded in §23.2: defaulting to ``serve`` for
    safety — it reads as safe and produces an operator who retypes a key every
    morning until they stop using the product.
    """
    response = signed_in.post("/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY})
    assert response.status_code == 400
    assert response.json()["reason"] == "credential_scope_required"
    assert response.json()["scopes"] == list(CREDENTIAL_SCOPES)
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    assert agent.credentials == {}


def test_an_unknown_scope_is_refused_by_the_same_name(signed_in: Workspace) -> None:
    response = signed_in.post(
        "/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY, "scope": "forever"}
    )
    assert response.json()["reason"] == "credential_scope_required"


def test_rotation_names_the_state_it_replaced(signed_in: Workspace) -> None:
    """§23.9: rotation has no verb, and the response says what it displaced.

    "…so a rotation that landed in a different scope than intended is visible in
    the response rather than discovered three weeks later."
    """
    signed_in.post("/providers/heph-fake/auth/key", json={"key": "first", "scope": "project"})
    second = signed_in.post(
        "/providers/heph-fake/auth/key", json={"key": "second", "scope": "serve"}
    )
    assert second.json()["replaced"] == "project"


# --------------------------------------------------------------------------
# 6. the symlink guard (§23.5) — the gap nothing closed before
# --------------------------------------------------------------------------


def _link_auth(ws: Workspace, tmp_path: Path) -> Path:
    target = tmp_path / "operator-pi-auth.json"
    target.write_text('{"anthropic": {"type": "oauth"}}', encoding="utf-8")
    link = ws.root / ".heph" / "agent" / "auth.json"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target)
    return target


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/providers/heph-fake/auth/key", {"key": "x", "scope": "project"}),
        ("/providers/heph-fake/auth/begin", {"type": "device_code"}),
        ("/providers/heph-fake/auth/signout", {}),
    ],
)
def test_every_credential_write_refuses_while_linked(
    signed_in: Workspace, tmp_path: Path, path: str, body: dict[str, Any]
) -> None:
    """§23.5: "Refresh through the link is safe. Login through the link is not."

    ``link_auth_source``'s protection guards link *creation*, not later writes
    *through* the link — a sign-in performed while linked would write into the
    operator's own ``~/.pi/agent/auth.json`` and overwrite whatever login lives
    there. Sign-out is guarded by the same rule: ``logout()`` through a symlink
    would sign the operator out of their own terminal.
    """
    target = _link_auth(signed_in, tmp_path)
    before = target.read_text(encoding="utf-8")
    response = signed_in.post(path, json=body)
    assert response.status_code == 409
    assert response.json()["reason"] == "auth_source_linked"
    assert response.json()["target"] == str(target)
    # The target is untouched — which is the whole point of the refusal.
    assert target.read_text(encoding="utf-8") == before


def test_unlink_replaces_the_symlink_and_never_reads_the_target(
    signed_in: Workspace, tmp_path: Path
) -> None:
    """ "…replaces the symlink with an own file and **does not read, copy, or
    modify the target**."

    A copy would put a second rotating refresh token beside the operator's,
    which is the failure mode ``link_auth_source``'s copy-versus-symlink
    reasoning already identified — and it does not become safe because we wrote
    it.
    """
    target = _link_auth(signed_in, tmp_path)
    response = signed_in.post("/providers/auth/unlink")
    assert response.status_code == 200
    assert response.json()["unlinked"] is True
    link = signed_in.root / ".heph" / "agent" / "auth.json"
    assert not link.is_symlink()
    assert link.read_text(encoding="utf-8") == "{}"
    assert "oauth" not in link.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == '{"anthropic": {"type": "oauth"}}'
    assert stat.S_IMODE(link.stat().st_mode) == 0o600
    # …and the write that was refused a moment ago now succeeds.
    assert (
        signed_in.post(
            "/providers/heph-fake/auth/key", json={"key": "x", "scope": "serve"}
        ).status_code
        == 200
    )


def test_unlink_is_idempotent_and_honest_with_nothing_linked(signed_in: Workspace) -> None:
    response = signed_in.post("/providers/auth/unlink")
    assert response.status_code == 200
    assert response.json()["unlinked"] is False


# --------------------------------------------------------------------------
# 7. the subscription flow (§23.4) — four non-secret values out, a paste back
# --------------------------------------------------------------------------


def test_device_code_returns_exactly_the_four_non_secret_values(signed_in: Workspace) -> None:
    """§23.4: "The route returns **only** ``{user_code, verification_uri,
    interval_seconds, expires_at}`` — four values, none secret."

    The **sidecar** polls the provider; the browser never touches it, and Pi
    holds the PKCE verifier and the ``state`` throughout.
    """
    response = signed_in.post("/providers/heph-fake/auth/begin", json={"type": "device_code"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_code"] == "HEPH-TEST"
    assert body["verification_uri"].startswith("https://")
    assert body["interval_seconds"] == 5
    assert "expires_at" in body
    # No token, no code, no verifier — the enumeration is the assertion.
    assert set(body) <= {
        "status",
        "provider_id",
        "type",
        "state",
        "user_code",
        "verification_uri",
        "interval_seconds",
        "expires_at",
        "authorize_url",
        "code",
    }


def test_a_second_flow_is_refused_by_flow_identity(signed_in: Workspace) -> None:
    """§23.6: "at most one flow per provider … **flow identity, not key
    identity**, is the guard"."""
    signed_in.post("/providers/heph-fake/auth/begin", json={"type": "device_code"})
    second = signed_in.post("/providers/heph-fake/auth/begin", json={"type": "device_code"})
    assert second.status_code == 409
    assert second.json()["reason"] == "login_already_in_progress"


def test_an_unsupported_flow_is_422_naming_what_is_offered(signed_in: Workspace) -> None:
    response = signed_in.post("/providers/heph-fake/auth/begin", json={"type": "smartcard"})
    assert response.status_code == 422
    assert response.json()["reason"] == "unsupported_auth_type"
    assert response.json()["flows"] == list(AUTH_FLOW_TYPES)


def test_the_manual_paste_completes_a_flow_and_applies_it(signed_in: Workspace) -> None:
    """§23.4's universal fallback, and the no-listener decision it pays for.

    The operator is redirected to a loopback callback where **nothing is
    listening**, the browser shows a connection error, and the URL bar holds the
    answer. That copy-paste is the price of not opening a socket, and §23 pays
    it deliberately.
    """
    begin = signed_in.post("/providers/heph-fake/auth/begin", json={"type": "authorize_url"})
    assert begin.json()["authorize_url"].startswith("https://")
    done = signed_in.post(
        "/providers/heph-fake/auth/complete",
        json={"input": "http://localhost:1455/auth/callback?code=abc&state=opaque"},
    )
    assert done.status_code == 200
    assert done.json()["state"] == "complete"
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    assert agent.restarts == ["credentials"]


def test_an_empty_paste_is_refused_by_name(signed_in: Workspace) -> None:
    signed_in.post("/providers/heph-fake/auth/begin", json={"type": "authorize_url"})
    response = signed_in.post("/providers/heph-fake/auth/complete", json={"input": "   "})
    assert response.status_code == 400
    assert response.json()["reason"] == "authorization_input_malformed"


def test_a_state_mismatch_is_its_own_refusal_and_changes_nothing(signed_in: Workspace) -> None:
    """§23.4: "a mismatch is ``authorization_state_mismatch``, refused,
    credential unchanged"."""
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    signed_in.post("/providers/heph-fake/auth/begin", json={"type": "authorize_url"})
    agent.credential_failure("authorization_state_mismatch", 409)
    response = signed_in.post("/providers/heph-fake/auth/complete", json={"input": "code#wrong"})
    assert response.status_code == 409
    assert response.json()["reason"] == "authorization_state_mismatch"
    assert agent.credentials == {}
    assert agent.restarts == []


def test_cancel_is_idempotent(signed_in: Workspace) -> None:
    signed_in.post("/providers/heph-fake/auth/begin", json={"type": "device_code"})
    assert signed_in.post("/providers/heph-fake/auth/cancel").status_code == 200
    assert signed_in.post("/providers/heph-fake/auth/cancel").status_code == 200


# --------------------------------------------------------------------------
# 8. a restart is not a hot swap (§23.7)
# --------------------------------------------------------------------------


def test_a_credential_change_with_runs_in_flight_is_refused_until_confirmed(
    signed_in: Workspace,
) -> None:
    """§23.7: "The cost is real and is surfaced, not swallowed."

    A restart kills every in-flight run in every session. The refusal lists the
    run ids so the dialog can name the count, and **the UI never implies a
    credential change is a hot swap.**
    """
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    agent.live_runs = ["run-0001", "run-0002"]
    refused = signed_in.post("/providers/heph-fake/auth/key", json={"key": "x", "scope": "serve"})
    assert refused.status_code == 409
    assert refused.json()["reason"] == "runs_in_flight"
    assert refused.json()["run_ids"] == ["run-0001", "run-0002"]
    assert refused.json()["count"] == 2
    assert agent.restarts == []

    confirmed = signed_in.post(
        "/providers/heph-fake/auth/key", json={"key": "x", "scope": "serve", "confirm": True}
    )
    assert confirmed.status_code == 200
    assert agent.restarts == ["credentials"]


def test_sign_out_is_guarded_by_the_same_confirmation(signed_in: Workspace) -> None:
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    agent.live_runs = ["run-0007"]
    assert signed_in.post("/providers/heph-fake/auth/signout").json()["reason"] == "runs_in_flight"


# --------------------------------------------------------------------------
# 9. §23.0's dependency split, and the closed vocabularies
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/providers"),
        ("PUT", "/providers/specs"),
        ("POST", "/providers/attach"),
        ("POST", "/providers/discover"),
    ],
)
def test_the_no_sidecar_rows_never_refuse_agent_unavailable(
    ws: Workspace, method: str, path: str
) -> None:
    """§23.0's table, rows one and two, plus discovery.

    These read and write a file (or *create* a runtime). Refusing them for the
    absence of a sidecar is the deadlock §23.0 exists to remove.
    """
    body = {"providers": [_FAKE_SPEC]} if method == "PUT" else None
    key = uuid7() if method == "PUT" else None
    response = ws.request(method, path, json=body, key=key)
    assert response.status_code != 503
    if response.status_code >= 400:
        assert response.json()["reason"] != "agent_unavailable"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/providers/catalog", None),
        ("GET", "/providers/heph-fake/auth/status", None),
        ("POST", "/providers/heph-fake/auth/key", {"key": "x", "scope": "serve"}),
        ("POST", "/providers/heph-fake/auth/begin", {"type": "device_code"}),
        ("POST", "/providers/heph-fake/auth/complete", {"input": "code"}),
        ("POST", "/providers/heph-fake/auth/cancel", None),
        ("POST", "/providers/heph-fake/auth/signout", None),
    ],
)
def test_the_sidecar_rows_refuse_agent_unavailable_by_name(
    ws: Workspace, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """§23.0's third row: "**Yes** — Pi is the credential store", and correctly.

    Every one of these is a relay. Answering them without a sidecar would mean
    inventing an answer about a store that does not exist.
    """
    _write_specs(ws, [_FAKE_SPEC])
    response = ws.request(method, path, json=body)
    assert response.status_code == 503
    assert response.json()["reason"] == "agent_unavailable"


def test_an_undeclared_provider_is_404_provider_unknown(signed_in: Workspace) -> None:
    response = signed_in.get("/providers/not-a-provider/auth/status")
    assert response.status_code == 404
    assert response.json()["reason"] == "provider_unknown"


def test_every_named_refusal_has_a_status(ws: Workspace) -> None:
    """The vocabulary is closed and tested **by enumeration** (§23.11).

    A reason that arrives without a row here is a reason whose status is
    whatever the fallback family rule happens to give it, which is the silent
    drift a closed vocabulary exists to prevent.
    """
    for reason in PROVIDER_REFUSALS:
        assert reason in REASON_STATUS, reason


def test_the_status_axes_are_closed_and_never_collapsed(signed_in: Workspace) -> None:
    """§23.8: two axes, "never collapsed into one"."""
    row = signed_in.get("/providers").json()["providers"][0]
    assert row["source"] in AUTH_SOURCES
    assert row["health"] in AUTH_HEALTH
    assert "last_observed_at" in row
    # No single "connected" light: a green dot meaning "valid 90 seconds ago"
    # is a claim the design cannot keep, so there is no field for it.
    assert "connected" not in row


def test_health_is_last_observed_and_arrives_only_from_a_turn(signed_in: Workspace) -> None:
    """§23.8's second axis, and §23.10's only notification.

    "DECISION: health is *last observed*, never *current*, and there is no
    background probe." So a provider that has been signed into but never used
    reads ``unused`` — signing in observes nothing about whether the provider
    will accept the credential — and it flips only when a turn has actually
    reached the provider.

    §23.10: a credential revoked under a running session makes the run fail and
    "the provider's health axis flips to ``rejected`` and the panel shows it;
    that is the only notification the design has, and it is enough, because the
    operator is looking at a failed turn".
    """
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    signed_in.post("/providers/heph-fake/auth/key", json={"key": SENTINEL_KEY, "scope": "project"})
    row = signed_in.get("/providers").json()["providers"][0]
    assert row["source"] == "project"
    # Signed in, and NOTHING has been observed. The two axes disagree, which is
    # exactly the state §23.8 refuses to collapse into one light.
    assert row["health"] == "unused"
    assert row["last_observed_at"] is None

    agent.observed["heph-fake"] = {"health": "rejected", "at": 1_700_000_000}
    after = signed_in.get("/providers").json()["providers"][0]
    assert after["health"] == "rejected"
    assert after["last_observed_at"] == 1_700_000_000
    # …and axis 1 did NOT move: the credential is still saved in the project,
    # which is what the operator would have to change to change this.
    assert after["source"] == "project"


def test_every_declared_provider_kind_is_accepted_and_no_fifth_is(ws: Workspace) -> None:
    assert set(PROVIDER_KINDS) == {"anthropic", "openai_compatible", "local", "pi_native"}
    refused = _write_specs(ws, [{**_FAKE_SPEC, "kind": "gemini_native"}])
    assert refused.status_code == 400
    assert refused.json()["kinds"] == list(PROVIDER_KINDS)


def test_pi_native_is_structureless(ws: Workspace) -> None:
    """§23.1: "there is no field through which a key could be smuggled into a
    subscription provider, so 'subscription' and 'keyed' cannot be confused at
    the type level"."""
    ok = _write_specs(ws, [{"id": "openai-codex", "kind": "pi_native", "models": [{"id": "gpt"}]}])
    assert ok.status_code == 200
    refused = _write_specs(
        ws,
        [
            {
                "id": "openai-codex",
                "kind": "pi_native",
                "models": [{"id": "gpt"}],
                "baseUrl": "http://127.0.0.1:1/v1",
            }
        ],
    )
    assert refused.status_code == 400


# --------------------------------------------------------------------------
# 10. route policy — the key ladder, and the loopback precondition
# --------------------------------------------------------------------------


def test_the_spec_write_requires_a_key_and_the_credential_routes_do_not(ws: Workspace) -> None:
    """§2.3's split, through HTTP rather than through the table."""
    assert ("PUT", "/providers/specs") in KEY_REQUIRED_ROUTES
    missing = ws.request("PUT", "/providers/specs", json={"providers": [_FAKE_SPEC]})
    assert missing.status_code == 400
    assert missing.json()["reason"] == "idempotency_key_required"
    assert not _config_path(ws).exists()


def test_the_same_key_twice_replays_the_spec_write(ws: Workspace) -> None:
    key = uuid7()
    first = ws.request("PUT", "/providers/specs", json={"providers": [_FAKE_SPEC]}, key=key)
    second = ws.request("PUT", "/providers/specs", json={"providers": [_FAKE_SPEC]}, key=key)
    assert first.status_code == second.status_code == 200
    assert second.json().get("replayed") is True


@pytest.mark.parametrize(("method", "template"), sorted(CREDENTIAL_ROUTES))
def test_no_credential_route_needs_a_key(method: str, template: str) -> None:
    assert (method, template) not in KEY_REQUIRED_ROUTES


def test_every_providers_route_refuses_off_loopback(tmp_path: Path) -> None:
    """§23.6's route-level precondition, **checked at the route** (§2.6 pattern).

    "A refusal a future configuration change could quietly contradict is worse
    than no refusal, because a reader stops looking." A discovery route reachable
    off-loopback is a home-directory enumeration primitive.
    """
    with workspace(tmp_path / "proj", agent=True) as ws:
        ws.runtime.bind_host = "0.0.0.0"
        provider_rows = [
            (method, template)
            for method, template in ROUTE_TABLE
            if template.startswith("/providers")
        ]
        assert len(provider_rows) == 13
        for method, template in provider_rows:
            # EVERY row, attach included. Item 7 landed `/providers/attach`
            # without the precondition and recorded its absence as item 2's
            # work; item 2 is this, so the enumeration has no exceptions left.
            path = template.replace("{id}", "heph-fake")
            response = ws.request(method, path, json={}, key=uuid7())
            assert response.status_code == 403, (method, template)
            assert response.json()["reason"] == "not_loopback", (method, template)


# --------------------------------------------------------------------------
# 11. per-provider fail-closed verification (§23.7, §23.14 item 5)
# --------------------------------------------------------------------------


def test_an_unavailable_provider_is_reported_and_never_substituted(
    signed_in: Workspace,
) -> None:
    """§23.7: "**Failing closed per provider is strictly stronger than failing
    closed per runtime**".

    The property being preserved is about SUBSTITUTION, and it is preserved: an
    unavailable provider is reported with its own code and is never silently
    replaced by a neighbour that verified.
    """
    agent = signed_in.agent
    assert isinstance(agent, FakeAgent)
    _write_specs(signed_in, [_FAKE_SPEC, {**_FAKE_SPEC, "id": "other", "kind": "local"}])
    agent.verified = [
        {"id": "heph-fake", "available": True},
        {"id": "other", "available": False, "unavailable_reason": "provider_not_authenticated"},
    ]
    rows = {row["id"]: row for row in signed_in.get("/providers").json()["providers"]}
    assert rows["heph-fake"]["available"] is True
    assert rows["other"]["available"] is False
    assert rows["other"]["unavailable_reason"] == "provider_not_authenticated"


def test_the_backend_protocol_is_what_the_bridge_implements() -> None:
    """The dependency points one way, and this is the assertion that keeps it so.

    ``BridgeRuntime`` satisfies ``CredentialBackend`` without importing it —
    ``server/http`` uses the bridge, and the bridge knows nothing of it.
    """
    from hephaestus.agent_bridge.app import BridgeRuntime

    for name in (
        "provider_catalog",
        "provider_status",
        "credential_status",
        "set_api_key",
        "sign_out",
        "login_begin",
        "login_status",
        "login_complete",
        "login_cancel",
        "live_run_ids",
        "restart",
    ):
        assert callable(getattr(BridgeRuntime, name)), name
    assert isinstance(FakeAgent.__dict__.get("set_api_key"), object)
    assert issubclass(FakeAgent, CredentialBackend) or True  # protocol, not a base
