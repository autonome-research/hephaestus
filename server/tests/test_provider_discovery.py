# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Credential discovery and adoption (``INTERFACE.md`` §23.5; Stage 10C, G10C).

The operator's ruling is *"the server should be able to work locally, the same
way that Claude for science works"*, approved **with binding constraints**. Every
one of those constraints is a refusal the implementation must demonstrate it
cannot violate, so this file is organized by constraint rather than by route:

1. an offer, never a silent adoption;
2. a secret never echoed, logged, or placed in a URL, an event, or an artifact;
3. loopback only;
4. ``0600`` on anything written;
5. mission rule 7 intact — the web path adopts no ambient environment variable
   and cannot add a name to ``credential_allowlist``.

Plus §23.5's own negative half, which matters as much as the positive: **a
discovered-but-unadopted login behaves identically to no login at all.**
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from hephaestus.http.providers import (
    ADOPTION_KINDS,
    DiscoveryRegistry,
    credential_reads,
    discover_sources,
    read_providers_file,
    reset_credential_reads,
)
from hephaestus.testing.workspace import Workspace, uuid7, workspace

#: The secret inside the *discovered* file. §23.14 item 18 extends item 12's
#: sentinel grep to exactly this value: the offer reads the file, so a slip that
#: carried a credential field through would be caught here and nowhere else.
DISCOVERED_SECRET = "oauth-refresh-DISCOVERED-3f9a11-never-echo-me"


def _home_with_pi_auth(home: Path) -> Path:
    """A Pi installation with one OAuth login and a cached model list."""
    agent = home / ".pi" / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    (agent / "auth.json").write_text(
        json.dumps(
            {
                "openai-codex": {
                    "type": "oauth",
                    "access": DISCOVERED_SECRET,
                    "refresh": DISCOVERED_SECRET,
                    "expires": 4102444800,
                }
            }
        ),
        encoding="utf-8",
    )
    (agent / "models-store.json").write_text(
        json.dumps({"openai-codex": {"models": [{"id": "gpt-5-codex"}, {"id": "gpt-5-mini"}]}}),
        encoding="utf-8",
    )
    return agent / "auth.json"


def _home_with_providers_json(home: Path) -> Path:
    path = home / ".heph" / "providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "workstation",
                        "kind": "local",
                        "name": "Workstation vLLM",
                        "baseUrl": "http://127.0.0.1:30008/v1",
                        "models": [
                            {
                                "id": "qwen3",
                                "name": "Qwen 3",
                                "contextWindow": 32768,
                                "maxTokens": 4096,
                            }
                        ],
                    }
                ],
                "credential_allowlist": ["SOMEONE_ELSES_KEY"],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def discovering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A workspace whose "home directory" is a scripted temporary tree."""
    home = tmp_path / "home"
    home.mkdir()
    _home_with_pi_auth(home)
    _home_with_providers_json(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PI_CONFIG_DIR", raising=False)
    monkeypatch.delenv("HEPHAESTUS_LOCAL_ENDPOINTS", raising=False)
    reset_credential_reads()
    with workspace(tmp_path / "proj") as w:
        yield w


def _offers(ws: Workspace) -> list[dict[str, Any]]:
    response = ws.post("/providers/discover")
    assert response.status_code == 200, response.text
    return list(response.json()["sources"])


# --------------------------------------------------------------------------
# constraint 1 — an offer, never a silent adoption
# --------------------------------------------------------------------------


def test_discovery_enumerates_the_three_kinds_it_is_approved_for(
    discovering: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§23.14 item 17: a Pi ``auth.json``, an existing ``providers.json``, and a
    local OpenAI-compatible endpoint.

    Each is described by ``{kind, provider_id, model_ids, source_path}`` and by
    nothing else — the projection is the assertion.
    """
    offers = _offers(discovering)
    kinds = {offer["kind"] for offer in offers}
    assert kinds <= set(ADOPTION_KINDS)
    assert {"pi_auth", "providers_json"} <= kinds
    pi = next(offer for offer in offers if offer["kind"] == "pi_auth")
    assert pi["provider_id"] == "openai-codex"
    # The model ids come from the NON-SECRET file beside auth.json. §23.5's
    # superseded draft clause said the offer reads nothing; the ruling directs
    # the opposite and says why — "an offer that has read nothing cannot say
    # what provider or which models, and is not an offer".
    assert pi["model_ids"] == ["gpt-5-codex", "gpt-5-mini"]
    assert pi["source_path"].endswith(".pi/agent/auth.json")
    assert set(pi) == {"discovery_id", "kind", "provider_id", "model_ids", "source_path"}


def test_discovery_configures_nothing(discovering: Workspace) -> None:
    """Constraint 1, stated as the absence it is.

    "Discovery returns a list. Nothing is configured, linked, read into a
    runtime, or written to ``providers.json`` by it."
    """
    _offers(discovering)
    assert not (discovering.root / ".heph" / "providers.json").exists()
    assert not (discovering.root / ".heph" / "agent" / "auth.json").exists()
    assert discovering.runtime.sessions is None


def test_a_discovered_but_unadopted_source_leaves_sessions_refusing_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§23.5's negative half, and G10C's Tier 2 clause: **byte-identical.**

    "A discovered-but-**unadopted** login behaves **identically** to no login at
    all — the session routes to ``agent_unavailable``, byte for byte." Asserted
    as an equality between two runs rather than as two separate shape checks,
    because that is the claim.
    """
    empty_home = tmp_path / "empty"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    with workspace(tmp_path / "bare") as bare:
        nothing_discovered = bare.get("/sessions")
        assert nothing_discovered.status_code == 503
        baseline = nothing_discovered.json()

    rich_home = tmp_path / "home"
    rich_home.mkdir()
    _home_with_pi_auth(rich_home)
    monkeypatch.setenv("HOME", str(rich_home))
    with workspace(tmp_path / "proj") as ws:
        assert _offers(ws)  # something WAS found
        after = ws.get("/sessions")
        assert after.status_code == 503
        body = after.json()

    # `config_path` names each project's own file, so it is the one field that
    # legitimately differs; everything that says *what state the serve is in* is
    # identical.
    baseline.pop("config_path", None)
    body.pop("config_path", None)
    assert body == baseline


def test_adoption_is_the_one_explicit_act_and_it_names_the_source(
    discovering: Workspace,
) -> None:
    """Constraint 1's positive half, and §23.5's distinguishing test.

    "…the adoption recorded on disk. …If a source works and no file names it,
    rule 7 has been broken."
    """
    offers = _offers(discovering)
    pi = next(offer for offer in offers if offer["kind"] == "pi_auth")
    response = discovering.post("/providers/adopt", json={"discovery_id": pi["discovery_id"]})
    assert response.status_code == 200, response.text
    file = read_providers_file(discovering.root / ".heph" / "providers.json")
    assert [row["id"] for row in file.providers] == ["openai-codex"]
    assert file.providers[0]["kind"] == "pi_native"
    assert [row["kind"] for row in file.adopted_sources] == ["pi_auth"]
    assert file.adopted_sources[0]["source_path"].endswith(".pi/agent/auth.json")
    # `auth_source` is written HERE and only here: the operator's request named
    # the source, which is the whole difference between an adoption and the
    # client-supplied path §23.6 refuses.
    assert file.auth_source is not None
    assert file.auth_source.endswith(".pi/agent/auth.json")


def test_no_other_route_adopts_as_a_side_effect(discovering: Workspace) -> None:
    """ "No other route adopts as a side effect." (§23.5 constraint 1.)"""
    _offers(discovering)
    for method, path, body in [
        ("GET", "/providers", None),
        ("POST", "/providers/attach", None),
        ("POST", "/providers/auth/unlink", None),
        ("GET", "/project", None),
        ("GET", "/parts", None),
    ]:
        discovering.request(method, path, json=body)
    file = read_providers_file(discovering.root / ".heph" / "providers.json")
    assert file.adopted_sources == ()
    assert file.auth_source is None


# --------------------------------------------------------------------------
# constraint 2 — the secret never leaves the file
# --------------------------------------------------------------------------


def test_no_response_or_written_file_carries_the_discovered_secret(
    discovering: Workspace,
) -> None:
    """§23.14 item 18's fourth clause: item 12's grep, extended to the discovered
    file's secret.

    The offer READS the credential file — the ruling directs that — so this is
    the test that keeps the read narrow. A slip that carried ``access`` or
    ``refresh`` through would be invisible to §23.14 item 12's own grep, because
    no key-shaped sentinel is ever planted in this channel.
    """
    offers = _offers(discovering)
    pi = next(offer for offer in offers if offer["kind"] == "pi_auth")
    adopted = discovering.post("/providers/adopt", json={"discovery_id": pi["discovery_id"]})
    surfaces = [
        discovering.post("/providers/discover").text,
        adopted.text,
        discovering.get("/providers").text,
        (discovering.root / ".heph" / "providers.json").read_text(encoding="utf-8"),
    ]
    for surface in surfaces:
        assert DISCOVERED_SECRET not in surface
        # …and no masked tail either. §15.41 is stricter than the ruling's
        # "a masked hint at most" ceiling and stands unrelaxed (§0.2a).
        assert DISCOVERED_SECRET[-4:] not in surface


def test_the_offer_carries_no_field_derived_from_a_secret(discovering: Workspace) -> None:
    """§0.2a: "An approval that permits *at most* X does not oblige X".

    The four fields are the whole projection. A ``masked``, ``hint``, ``tail``
    or ``type`` field would each be a step toward the thing §23.8 rejected by
    name, so the assertion is on the key set rather than on any one value.
    """
    for offer in _offers(discovering):
        assert set(offer) == {"discovery_id", "kind", "provider_id", "model_ids", "source_path"}


def test_the_discovery_handle_is_opaque_and_carries_no_path(discovering: Workspace) -> None:
    """§23.6: server-minted and opaque, so it encodes nothing a client could
    decode into a filesystem address."""
    for offer in _offers(discovering):
        handle = offer["discovery_id"]
        assert handle.startswith("disc-")
        assert "/" not in handle
        assert ".pi" not in handle
        assert "auth" not in handle.removeprefix("disc-")


# --------------------------------------------------------------------------
# constraint 3 and the reachability rules
# --------------------------------------------------------------------------


def test_discovery_and_adoption_refuse_off_loopback(discovering: Workspace) -> None:
    """ "A discovery route reachable off-loopback is a home-directory enumeration
    primitive." (§23.5 constraint 3.)"""
    discovering.runtime.bind_host = "0.0.0.0"
    for path in ("/providers/discover", "/providers/adopt"):
        response = discovering.post(path, json={})
        assert response.status_code == 403
        assert response.json()["reason"] == "not_loopback"


def test_discovery_never_runs_on_any_other_code_path(discovering: Workspace) -> None:
    """§23.14 item 18's third clause, and §15.41's *no background credential
    probe*, asserted against the credential-read ledger.

    "…it runs **only** when called — never on panel mount, never on a timer,
    never as a side effect of another route." Every read of a path outside the
    project goes through one recorded door, so this exercises the rest of the
    table and asserts the ledger stayed empty.
    """
    reset_credential_reads()
    for method, path in [
        ("GET", "/project"),
        ("GET", "/parts"),
        ("GET", "/providers"),
        ("GET", "/sessions"),
        ("GET", "/git/status"),
        ("POST", "/providers/attach"),
        ("POST", "/providers/auth/unlink"),
    ]:
        discovering.request(method, path)
    assert credential_reads() == ()
    # …and the explicit call is the one thing that does read.
    _offers(discovering)
    assert {read.reason for read in credential_reads()} == {"discover"}


def test_every_credential_read_outside_the_project_is_recorded_with_its_reason(
    discovering: Workspace,
) -> None:
    """G10C Tier 1: "no credential path outside ``<project>/.heph`` is read
    unless ``providers.json`` names it or the adoption request named it".

    The closed reason set is what turns that sentence into an assertion.
    """
    reset_credential_reads()
    offers = _offers(discovering)
    pi = next(offer for offer in offers if offer["kind"] == "pi_auth")
    discovering.post("/providers/adopt", json={"discovery_id": pi["discovery_id"]})
    reasons = {read.reason for read in credential_reads()}
    assert reasons == {"discover", "adopt"}
    adopt_reads = [read for read in credential_reads() if read.reason == "adopt"]
    assert [read.path for read in adopt_reads] == [pi["source_path"]]


# --------------------------------------------------------------------------
# constraint 4 — 0600, and constraint 5 — rule 7 intact
# --------------------------------------------------------------------------


def test_the_adoption_record_is_written_private(discovering: Workspace) -> None:
    offers = _offers(discovering)
    discovering.post("/providers/adopt", json={"discovery_id": offers[0]["discovery_id"]})
    path = discovering.root / ".heph" / "providers.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_adoption_cannot_add_a_name_to_the_credential_allowlist(
    discovering: Workspace,
) -> None:
    """Constraint 5, and it is the sharpest test in this file.

    The discovered ``providers.json`` declares ``credential_allowlist:
    ["SOMEONE_ELSES_KEY"]``. Adoption may copy the SPEC, never the allowlist:
    ``credential_allowlist`` stays supervisor-prepared, so a discovered source
    that needs an approval the operator has not made in a terminal is refused by
    name rather than quietly granted one.
    """
    home_spec = {
        "id": "keyed",
        "kind": "openai_compatible",
        "baseUrl": "http://127.0.0.1:9/v1",
        "credential": "SOMEONE_ELSES_KEY",
        "models": [{"id": "m", "name": "m", "contextWindow": 8192, "maxTokens": 512}],
    }
    home = Path(discovering.root).parent / "home"
    path = home / ".heph" / "providers.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["providers"].append(home_spec)
    path.write_text(json.dumps(doc), encoding="utf-8")

    offers = _offers(discovering)
    keyed = next(offer for offer in offers if offer["provider_id"] == "keyed")
    response = discovering.post("/providers/adopt", json={"discovery_id": keyed["discovery_id"]})
    assert response.status_code == 400
    assert response.json()["reason"] == "credential_not_allowlisted"
    assert response.json()["credential"] == "SOMEONE_ELSES_KEY"
    project = read_providers_file(discovering.root / ".heph" / "providers.json")
    assert project.credential_allowlist == ()


def test_discovery_adopts_no_ambient_environment_variable(
    discovering: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§23.5's "what is still forbidden": *forwarding ``ANTHROPIC_API_KEY``
    because it happens to be exported*."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ambient-should-never-be-adopted")
    offers = _offers(discovering)
    for offer in offers:
        assert "ANTHROPIC_API_KEY" not in json.dumps(offer)
    discovering.post("/providers/adopt", json={"discovery_id": offers[0]["discovery_id"]})
    file = read_providers_file(discovering.root / ".heph" / "providers.json")
    assert file.credential_allowlist == ()
    assert "sk-ambient" not in json.dumps(file.document())


# --------------------------------------------------------------------------
# the two new named refusals (§23.11)
# --------------------------------------------------------------------------


def test_an_unknown_handle_is_refused_by_its_own_name(discovering: Workspace) -> None:
    response = discovering.post("/providers/adopt", json={"discovery_id": "disc-not-a-thing"})
    assert response.status_code == 400
    assert response.json()["reason"] == "discovery_source_unknown"


def test_a_stale_handle_is_refused_rather_than_honoured(discovering: Workspace) -> None:
    """Offers are handles, not leases: a fresh ``discover`` retires the old set,
    so a page holding an old handle cannot adopt a file that has since moved."""
    first = _offers(discovering)
    _offers(discovering)  # a second call re-mints the table
    response = discovering.post("/providers/adopt", json={"discovery_id": first[0]["discovery_id"]})
    assert response.json()["reason"] == "discovery_source_unknown"


@pytest.mark.parametrize(
    "body",
    [
        {"discovery_id": "d", "source_path": "/home/someone/.pi/agent/auth.json"},
        {"discovery_id": "d", "auth_source": "~/.pi/agent/auth.json"},
        {"discovery_id": "d", "anything": "./relative/auth.json"},
    ],
)
def test_a_body_carrying_a_path_under_any_key_is_refused_by_name(
    discovering: Workspace, body: dict[str, Any]
) -> None:
    """§23.6: "A body carrying a filesystem path under any key is refused
    ``path_not_web_writable``", on the ``allowlist_not_web_writable`` pattern.

    "The direction that matters is inbound: a client-supplied path is what turns
    a credential route into a traversal primitive, and no route accepts one."
    And it does **not** degrade to ``invalid_params``.
    """
    response = discovering.post("/providers/adopt", json=body)
    assert response.status_code == 400
    assert response.json()["reason"] == "path_not_web_writable"


def test_an_unknown_non_path_field_is_a_plain_invalid_params(
    discovering: Workspace,
) -> None:
    """The two refusals stay distinguishable: a stray flag is not a traversal
    attempt, and calling it one would make the sharper reason meaningless."""
    response = discovering.post("/providers/adopt", json={"discovery_id": "d", "force": True})
    assert response.json()["reason"] == "invalid_params"


# --------------------------------------------------------------------------
# the local endpoint, and the unit-level surface
# --------------------------------------------------------------------------


def test_a_local_endpoint_is_offered_only_when_the_operator_named_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No port scan, ever.

    The candidate list comes from an environment variable the operator sets **in
    a terminal**. A local tool that knocked on its operator's ports unasked is
    the shape §15.41 refuses, and "it is only loopback" is not a reason to do it.
    """
    import http.server
    import threading

    class Models(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"data": [{"id": "qwen3.6:27b"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Models)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        home = tmp_path / "home"
        home.mkdir()
        registry = DiscoveryRegistry()
        # Not named: no offer, and no request was made to find that out.
        assert discover_sources(registry, project_root=tmp_path, env={}, home=home) == []
        offers = discover_sources(
            registry,
            project_root=tmp_path,
            env={"HEPHAESTUS_LOCAL_ENDPOINTS": base},
            home=home,
        )
        assert [offer.kind for offer in offers] == ["local_endpoint"]
        assert offers[0].model_ids == ("qwen3.6:27b",)
        assert offers[0].source_path == base
    finally:
        server.shutdown()


def test_a_non_loopback_candidate_is_never_probed(tmp_path: Path) -> None:
    """A named endpoint that is not loopback is dropped without a request.

    Kind ``local`` is loopback-only by §23.3, and a discovery route that made an
    outbound request to an arbitrary host would be the exfiltration channel §23
    spends §23.3 preventing on the *write* side.
    """
    home = tmp_path / "home"
    home.mkdir()
    offers = discover_sources(
        DiscoveryRegistry(),
        project_root=tmp_path,
        env={"HEPHAESTUS_LOCAL_ENDPOINTS": "https://collector.example/v1"},
        home=home,
    )
    assert offers == []


def test_the_projects_own_providers_json_is_not_offered_back_to_it(
    tmp_path: Path,
) -> None:
    """A project cannot discover itself: an offer to adopt the file the serve is
    already reading is noise at best and a loop at worst."""
    project = tmp_path / "proj"
    (project / ".heph").mkdir(parents=True)
    (project / ".heph" / "providers.json").write_text(
        json.dumps({"providers": [{"id": "x", "kind": "local", "models": [{"id": "m"}]}]}),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    (home / ".heph").mkdir(parents=True)
    (home / ".heph" / "providers.json").symlink_to(project / ".heph" / "providers.json")
    offers = discover_sources(DiscoveryRegistry(), project_root=project, env={}, home=home)
    assert offers == []


def test_a_missing_home_directory_is_no_offer_rather_than_an_error(tmp_path: Path) -> None:
    """ "A missing source is not an error, it is simply not an offer."""
    assert (
        discover_sources(
            DiscoveryRegistry(), project_root=tmp_path, env={}, home=tmp_path / "nowhere"
        )
        == []
    )


def test_adoption_of_a_providers_json_source_copies_the_spec(
    discovering: Workspace,
) -> None:
    offers = _offers(discovering)
    ws_offer = next(offer for offer in offers if offer["provider_id"] == "workstation")
    response = discovering.post("/providers/adopt", json={"discovery_id": ws_offer["discovery_id"]})
    assert response.status_code == 200
    file = read_providers_file(discovering.root / ".heph" / "providers.json")
    spec = next(row for row in file.providers if row["id"] == "workstation")
    assert spec["baseUrl"] == "http://127.0.0.1:30008/v1"
    # …and the source file's allowlist did NOT come with it.
    assert file.credential_allowlist == ()


def test_adopting_twice_replaces_rather_than_duplicates(discovering: Workspace) -> None:
    offers = _offers(discovering)
    handle = offers[0]["discovery_id"]
    discovering.post("/providers/adopt", json={"discovery_id": handle})
    again = _offers(discovering)
    same_kind = next(o["discovery_id"] for o in again if o["kind"] == offers[0]["kind"])
    discovering.post("/providers/adopt", json={"discovery_id": same_kind})
    file = read_providers_file(discovering.root / ".heph" / "providers.json")
    assert len(file.adopted_sources) == 1
    assert len({row["id"] for row in file.providers}) == len(file.providers)


def test_the_spec_write_still_works_after_an_adoption(discovering: Workspace) -> None:
    """Adoption writes the same file ``PUT /providers/specs`` writes, so the two
    must compose: an adopted ``auth_source`` survives a later spec write exactly
    as a hand-authored one does."""
    offers = _offers(discovering)
    pi = next(offer for offer in offers if offer["kind"] == "pi_auth")
    discovering.post("/providers/adopt", json={"discovery_id": pi["discovery_id"]})
    written = discovering.request(
        "PUT",
        "/providers/specs",
        json={
            "providers": [
                {
                    "id": "local-x",
                    "kind": "local",
                    "baseUrl": "http://127.0.0.1:9/v1",
                    "models": [{"id": "m", "name": "m", "contextWindow": 8, "maxTokens": 8}],
                }
            ]
        },
        key=uuid7(),
    )
    assert written.status_code == 200
    file = read_providers_file(discovering.root / ".heph" / "providers.json")
    assert file.auth_source is not None
    assert [row["kind"] for row in file.adopted_sources] == ["pi_auth"]
