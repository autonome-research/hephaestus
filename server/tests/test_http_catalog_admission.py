"""Offline catalog registration: key admission, error vocabulary and replay.

Uses the ordinary HTTP fixture and an explicitly synthetic catalog/credential
backend. No sidecar, provider contact, credential or CAD workload is permitted.
The workspace fixture's native initialization belongs in Linux CI.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.http import app, providers
from hephaestus.http.errors import HttpRefusal
from hephaestus.http.idempotency import FRESHNESS_SKEW_S
from hephaestus.testing.fake_agent import FakeAgent
from hephaestus.testing.workspace import Workspace, uuid7, workspace

ROW: dict[str, Any] = {
    "id": "offline-catalog-provider",
    "auth_methods": [{"type": "api_key"}],
    "models": [{"id": "offline-model"}],
}
BODY = {"provider_id": ROW["id"], "auth_type": "api_key"}


@pytest.fixture(params=[False, True], ids=["detached", "attached-fake"])
def catalog_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[tuple[Workspace, list[str], list[dict[str, Any]]]]:
    calls: list[str] = []
    synced: list[dict[str, Any]] = []

    def catalog() -> dict[str, Any]:
        calls.append("catalog")
        return {"catalog": [ROW]}

    def detached(root: Path) -> dict[str, Any]:
        return catalog()

    def attached(self: FakeAgent) -> dict[str, Any]:
        return catalog()

    def sync(self: FakeAgent, spec: dict[str, Any]) -> dict[str, Any]:
        calls.append("credential-sync")
        synced.append(spec)
        return {"status": "ok"}

    original_write = providers.register_catalog_provider

    def write(
        path: Path, *, catalog_entry: dict[str, Any], auth_type: object
    ) -> tuple[providers.ProvidersFile, dict[str, Any]]:
        calls.append("write")
        return original_write(path, catalog_entry=catalog_entry, auth_type=auth_type)

    monkeypatch.setattr(app, "native_provider_catalog", detached)
    monkeypatch.setattr(FakeAgent, "provider_catalog", attached)
    monkeypatch.setattr(FakeAgent, "register_provider", sync)
    monkeypatch.setattr(providers, "register_catalog_provider", write)
    with workspace(tmp_path / "project", agent=bool(request.param)) as web:
        yield web, calls, synced


def config_bytes(web: Workspace) -> bytes | None:
    path = web.root / ".heph/providers.json"
    return path.read_bytes() if path.exists() else None


@pytest.mark.parametrize(
    "key_kind,status,reason",
    [
        ("missing", 400, "idempotency_key_required"),
        ("malformed", 400, "idempotency_key_malformed"),
        ("stale", 409, "key_timestamp_skew"),
    ],
)
def test_key_refusal_precedes_catalog_credentials_and_write(
    catalog_workspace: tuple[Workspace, list[str], list[dict[str, Any]]],
    key_kind: str,
    status: int,
    reason: str,
) -> None:
    web, calls, synced = catalog_workspace
    key = None if key_kind == "missing" else "not-a-uuid"
    if key_kind == "stale":
        key = uuid7(time.time() - FRESHNESS_SKEW_S - 60)
    before = config_bytes(web)
    response = web.request("POST", "/providers/register", json=BODY, key=key)
    assert response.status_code == status, response.text
    assert response.json()["reason"] == reason
    assert config_bytes(web) == before
    assert calls == [] and synced == []


@pytest.mark.parametrize(
    "fields,status,reason",
    [
        ({}, 400, "invalid_params"),
        ({"auth_type": None}, 400, "invalid_params"),
        ({"auth_type": 7}, 400, "invalid_params"),
        ({"auth_type": []}, 400, "invalid_params"),
        ({"auth_type": ""}, 422, "unsupported_auth_type"),
        ({"auth_type": "unknown"}, 422, "unsupported_auth_type"),
        ({"auth_type": "subscription"}, 422, "unsupported_auth_type"),
    ],
)
def test_registration_auth_vocabulary(
    catalog_workspace: tuple[Workspace, list[str], list[dict[str, Any]]],
    fields: dict[str, Any],
    status: int,
    reason: str,
) -> None:
    web, calls, synced = catalog_workspace
    before = config_bytes(web)
    response = web.request(
        "POST", "/providers/register", json={"provider_id": ROW["id"], **fields}, key=uuid7()
    )
    assert response.status_code == status, response.text
    assert response.json()["reason"] == reason
    assert config_bytes(web) == before and synced == []
    assert calls == (["catalog", "write"] if fields.get("auth_type") == "subscription" else [])


def test_offered_registration_replays_without_catalog_or_second_write_and_conflicts(
    catalog_workspace: tuple[Workspace, list[str], list[dict[str, Any]]],
) -> None:
    web, calls, synced = catalog_workspace
    key = uuid7()
    first = web.request("POST", "/providers/register", json=BODY, key=key)
    assert first.status_code == 200, first.text
    expected_sync = ["credential-sync"] if web.agent is not None else []
    assert calls == ["catalog", "write", *expected_sync]
    before = config_bytes(web)
    assert before is not None
    calls.clear()
    replay = web.request("POST", "/providers/register", json=BODY, key=key)
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body.pop("replayed") is True
    assert body == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert config_bytes(web) == before
    assert calls == expected_sync
    if web.agent is not None:
        declaration = json.loads(before)["providers"][0]
        assert synced == [declaration, declaration]
    calls.clear()
    conflict = web.request(
        "POST", "/providers/register", json={**BODY, "auth_type": "subscription"}, key=key
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["reason"] == "key_payload_mismatch"
    assert config_bytes(web) == before and calls == []


@pytest.mark.parametrize(
    "auth,status,reason",
    [
        (None, 400, "invalid_params"),
        ([], 400, "invalid_params"),
        ("unknown", 422, "unsupported_auth_type"),
        ("subscription", 422, "unsupported_auth_type"),
    ],
)
def test_registration_helper_has_same_refusal_vocabulary(
    tmp_path: Path, auth: object, status: int, reason: str
) -> None:
    path = tmp_path / "providers.json"
    with pytest.raises(HttpRefusal) as caught:
        providers.register_catalog_provider(path, catalog_entry=ROW, auth_type=auth)
    assert caught.value.status == status
    assert caught.value.reason == reason
    assert not path.exists()
