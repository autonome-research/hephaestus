# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§2.5's ladder, §2.3's two key tables, and the non-tool ledger extension.

``INTERFACE.md`` §2.3, §2.5, §19 item 7. G5.19 requires REST mutation
idempotency tested **independently of MCP-over-HTTP**, and §2.3 names the
subject exactly:

    The missing-key test enumerates the seven routes of the first table and
    asserts ``400 idempotency_key_required`` with **no execution** on each; the
    replay test enumerates the same seven. It asserts on the five
    session-control routes that a missing key is **accepted**, so the policy is
    tested in both directions and cannot rot into "whatever the implementation
    happens to check".

The freshness asymmetry is the documented trap and is honoured here: the replay
tests **do not re-assert freshness**, because a recognized key replays for the
full 30-day horizon without the check being re-run.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from hephaestus.http.idempotency import (
    FRESHNESS_SKEW_S,
    KEY_REQUIRED_ROUTES,
    NON_TOOL_KEY_ROUTES,
    SESSION_CONTROL_ROUTES,
)
from hephaestus.testing.workspace import Workspace, uuid7, workspace

#: One concrete request per key-required route: the path, and a body that would
#: actually mutate if it were allowed to execute. A body that could not mutate
#: would make "no execution" unfalsifiable.
KEY_REQUIRED_CASES: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {
    ("PUT", "/parts/{part}/script"): (
        "/parts/widget/script",
        {"script": "part.geometry = Box(1.0, 1.0, 1.0)\n", "expected_hash": "sha256:0" * 1},
    ),
    ("PATCH", "/parts/{part}/script"): (
        "/parts/widget/script",
        {"expected_hash": "sha256:0", "old_str": "20.0", "new_str": "21.0"},
    ),
    ("POST", "/parts/{part}/params"): (
        "/parts/widget/params",
        {"values": {"width": 45.0}, "expected_state_hash": "sha256:0"},
    ),
    ("POST", "/parts/{part}/build"): ("/parts/widget/build", {}),
    ("POST", "/parts/{part}/dfm"): ("/parts/widget/dfm", {}),
    ("POST", "/project/config/dfm"): ("/project/config/dfm", {"auto_run": True}),
    ("POST", "/git/tag"): ("/git/tag", {"name": "v0.0.1", "message": "release"}),
}


def _widget_script(root: Path) -> str:
    return (root / "parts" / "widget.py").read_text(encoding="utf-8")


def _project_state(web: Workspace) -> tuple[str, bool, list[str]]:
    """Everything the seven routes could change, as one comparable tuple."""
    return (
        _widget_script(web.root),
        bool(web.runtime.layout.manifest.dfm_auto_run),
        sorted(p["content_hash"] for p in web.get("/parts").json()["parts"]),
    )


def test_the_key_required_table_is_the_seven_routes_the_spec_enumerates() -> None:
    """§2.3's first table, as data — and its two non-tool rows, named.

    Enumerated, never derived from ``MUTATION_TOOLS``: that rule was **withdrawn**
    because ``ToolDecl.idempotent`` decides nothing for a route with no
    ``ToolDecl``, and a rule that silently exempts the routes a reader most
    expects it to cover is worse than no rule.
    """
    assert len(KEY_REQUIRED_ROUTES) == 7
    assert set(KEY_REQUIRED_CASES) == set(KEY_REQUIRED_ROUTES)
    assert set(NON_TOOL_KEY_ROUTES) == {
        ("POST", "/project/config/dfm"),
        ("POST", "/git/tag"),
    }
    assert set(NON_TOOL_KEY_ROUTES) < set(KEY_REQUIRED_ROUTES)


@pytest.mark.parametrize("route", list(KEY_REQUIRED_ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_a_missing_key_is_refused_with_no_execution(tmp_path: Path, route: tuple[str, str]) -> None:
    """§2.5 rung 1: **400** ``idempotency_key_required``, **no execution**.

    "No execution" is the half that matters and the half a status-code assertion
    would miss, so the whole mutable project state is captured before and after
    and compared.
    """
    method, template = route
    path, body = KEY_REQUIRED_CASES[(method, template)]
    with workspace(tmp_path / "proj") as web:
        before = _project_state(web)
        response = web.request(method, path, json=body)
        after = _project_state(web)
    assert response.status_code == 400
    assert response.json()["reason"] == "idempotency_key_required"
    assert before == after, f"{method} {path} executed without a key"


@pytest.mark.parametrize("route", list(KEY_REQUIRED_ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_a_malformed_key_is_refused_with_no_execution(
    tmp_path: Path, route: tuple[str, str]
) -> None:
    """§2.5 rung 3: present but not a UUIDv7 → 400 ``idempotency_key_malformed``."""
    method, template = route
    path, body = KEY_REQUIRED_CASES[(method, template)]
    with workspace(tmp_path / "proj") as web:
        before = _project_state(web)
        response = web.request(method, path, json=body, key="0123-not-a-uuid7")
        after = _project_state(web)
    assert response.status_code == 400
    assert response.json()["reason"] == "idempotency_key_malformed"
    assert before == after


@pytest.mark.parametrize("route", list(KEY_REQUIRED_ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_a_stale_first_sight_key_is_key_timestamp_skew_with_no_execution(
    tmp_path: Path, route: tuple[str, str]
) -> None:
    """§2.5 rung 4: first sight outside ±300 s → **409** ``key_timestamp_skew``.

    ``key_timestamp_skew`` and ``key_expired`` are **not** interchangeable: this
    is the first-sight freshness refusal, and the post-horizon one has its own
    reason. Collapsing them would lose the distinction the engine already makes.
    """
    method, template = route
    path, body = KEY_REQUIRED_CASES[(method, template)]
    stale = uuid7(time.time() - FRESHNESS_SKEW_S - 60.0)
    with workspace(tmp_path / "proj") as web:
        before = _project_state(web)
        response = web.request(method, path, json=body, key=stale)
        after = _project_state(web)
    assert response.status_code == 409
    assert response.json()["reason"] == "key_timestamp_skew"
    assert before == after


@pytest.mark.parametrize(
    "route",
    [("POST", "/parts/{part}/build"), ("POST", "/project/config/dfm"), ("POST", "/git/tag")],
    ids=lambda r: f"{r[0]} {r[1]}",
)
def test_a_recognized_key_replays_the_stored_body_byte_for_byte(
    tmp_path: Path, route: tuple[str, str], git_project: Any
) -> None:
    """§2.5's pinned REST shape — the third transport's own.

    The stored body **byte-for-byte**, plus ``"replayed": true`` (normative) and
    ``Idempotency-Replayed: true`` (advisory). It does **not** degrade to the
    bridge's ``{applied: false, conflict:{current_hash}}`` shape: that shape
    exists because the retrying principal is a *model* being told a live hash it
    does not hold, while a REST replay is the same operator client re-sending its
    own committed call.

    One tool-backed row and both non-tool rows, so §19 item 7's extension is
    covered by the same assertion as the rows that already had a ledger.

    Freshness is deliberately NOT re-asserted here (§2.5's documented trap).
    """
    method, template = route
    path, body = KEY_REQUIRED_CASES[(method, template)]
    with workspace(git_project) as web:
        key = uuid7()
        first = web.request(method, path, json=body, key=key)
        assert first.status_code == 200, first.text
        assert "replayed" not in first.json()

        second = web.request(method, path, json=body, key=key)
    assert second.status_code == 200, second.text
    assert second.headers.get("Idempotency-Replayed") == "true"
    replayed = second.json()
    assert replayed.pop("replayed") is True
    assert replayed == first.json()


@pytest.mark.parametrize(
    "route",
    [("POST", "/parts/{part}/build"), ("POST", "/project/config/dfm")],
    ids=lambda r: f"{r[0]} {r[1]}",
)
def test_the_same_key_with_a_different_payload_is_key_payload_mismatch(
    tmp_path: Path, route: tuple[str, str]
) -> None:
    """§2.5: same key, different payload → **409** ``key_payload_mismatch``.

    This row is only reachable because the key is **payload-independent**. An
    earlier draft folded the canonical body into the key, which would give two
    payloads two keys, execute both as first sights, and make this refusal
    structurally dead — taking the lost-response guarantee with it.
    """
    method, template = route
    path, body = KEY_REQUIRED_CASES[(method, template)]
    other: dict[str, Any] = (
        {"auto_run": False} if template == "/project/config/dfm" else {"params": {"width": 55.0}}
    )
    with workspace(tmp_path / "proj") as web:
        key = uuid7()
        assert web.request(method, path, json=body, key=key).status_code == 200
        clash = web.request(method, path, json=other, key=key)
    assert clash.status_code == 409
    assert clash.json()["reason"] == "key_payload_mismatch"


def test_the_key_is_derived_from_the_route_and_header_and_never_from_the_body() -> None:
    """§2.5 TIGHTENING: ``Invocation.op_id`` stays **derived**, not assigned.

    ``op_id`` is a ``@property`` over ``session_id|entry_id|ordinal|
    provider_call_id`` and cannot be handed anything; a REST caller supplies
    ``entry_id`` and the property does the rest. The body appears in the separate
    payload digest and nowhere in the key — asserted here as a string-level fact
    so a future "simplification" that folds the body in fails loudly.
    """
    from hephaestus.http.idempotency import rest_invocation, rest_payload_hash

    key = uuid7()
    invocation = rest_invocation("web:abc", key, method="POST", template="/parts/{part}/build")
    assert invocation.entry_id == f"rest:POST /parts/{{part}}/build:{key}"
    assert invocation.op_id == f"web:abc|{invocation.entry_id}|0|rest"

    # Two different bodies under one header value: two payload digests, ONE key.
    # That is the whole tightening — and it is what makes `key_payload_mismatch`
    # reachable, because both presentations land on the same ledger row.
    one = rest_payload_hash(
        project="/p", method="POST", template="/parts/{part}/build", body={"name": "a"}
    )
    two = rest_payload_hash(
        project="/p", method="POST", template="/parts/{part}/build", body={"name": "b"}
    )
    assert one != two
    other = rest_invocation("web:abc", key, method="POST", template="/parts/{part}/build")
    assert other.op_id == invocation.op_id


def test_payload_hashing_is_byte_faithful_and_never_unicode_normalizes() -> None:
    """§2.5: NFC ≠ NFD. Two spellings of one grapheme are two payloads.

    A hash that normalized would let a client's NFD retry replay an NFC commit,
    which is a *different* write silently swallowed.
    """
    from hephaestus.http.idempotency import rest_payload_hash

    nfc = rest_payload_hash(
        project="/p", method="PUT", template="/parts/{part}/script", body={"script": "é"}
    )
    nfd = rest_payload_hash(
        project="/p", method="PUT", template="/parts/{part}/script", body={"script": "é"}
    )
    assert nfc != nfd


def test_an_unpaired_surrogate_in_a_body_is_refused_before_sizing_or_hashing(
    tmp_path: Path,
) -> None:
    """§2.5: unpaired surrogates → ``invalid_unicode_scalar``, never U+FFFD.

    JSON permits a ``\\uD800`` escape that decodes to a lone surrogate in Python.
    Letting a JSON runtime substitute the replacement character would silently
    break the Stage 3 parity suite, so the layer parses bytes and validates
    scalars itself.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.raw(
            "POST", "/parts/widget/build", content=b'{"params": {"a": "\\ud800"}}', key=uuid7()
        )
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_unicode_scalar"


def test_session_control_routes_are_declared_key_free_in_both_directions() -> None:
    """§2.3's second table: five routes, a key **not required** and one **ignored**.

    The two tables are disjoint by construction, and the second is not a weaker
    version of the first — it is a different contract. ``answer`` is governed by
    question-id idempotency (first answer wins), ``cancel`` is idempotent by
    construction, and ``create``/``prompt``/``quick_edit`` are at-least-once with
    the consequence stated.

    The routes themselves are §2.7/§2.8 work and are not served yet; what is
    asserted here is the **policy**, which this module owns and which must not
    rot into "whatever the implementation happens to check".
    """
    from hephaestus.http.idempotency import requires_key, validate_key

    assert len(SESSION_CONTROL_ROUTES) == 5
    assert set(SESSION_CONTROL_ROUTES) & set(KEY_REQUIRED_ROUTES) == set()
    for method, template in SESSION_CONTROL_ROUTES:
        assert not requires_key(method, template)
        # absent: accepted
        assert validate_key(None, method=method, template=template) is None
        # supplied: IGNORED rather than honoured
        assert validate_key(uuid7(), method=method, template=template) is None


def test_a_key_required_route_actually_requires_its_key() -> None:
    """The mirror of the assertion above, so neither table can drift alone."""
    from hephaestus.http.idempotency import RestKeyError, requires_key, validate_key

    for method, template in KEY_REQUIRED_ROUTES:
        assert requires_key(method, template)
        with pytest.raises(RestKeyError) as caught:
            validate_key(None, method=method, template=template)
        assert caught.value.reason == "idempotency_key_required"
        assert validate_key(uuid7(), method=method, template=template) is not None


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A project root that is also a git work tree, so ``POST /git/tag`` can run."""
    import subprocess

    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["init", "-q"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "test"],
    ):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "seed.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"], check=True, capture_output=True
    )
    return root
