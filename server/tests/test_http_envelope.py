# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""B-6 — the application boundary, not just the per-endpoint guard (§2.4).

``build_app`` **used to** return ``Starlette(routes=routes)`` with no
``exception_handlers``: a route miss (404) and a wrong method (405) were decided
by the router *before* any endpoint's own ``guarded`` wrapper ran, and an
exception no branch of ``refusal_for`` mapped ended in a bare ``raise exc`` that
reached the same defaultless middleware. All three answered ``text/plain`` with
no ``status``/``reason``/``message`` — exactly the condition INTERFACE.md §2.4's
2026-09-03 amendment exists to make impossible everywhere else. That is the tree
these tests were written against, and it is not the tree they run against now.

This lane's application-boundary fix (``build_app``'s two ``exception_handlers``,
§2.4's three new reason rows) landed while this file was authored, so most of the
tests below are GREEN against the tree they now sit in — verified by re-running
them after the fix, not asserted by hand. The static bundle is composed
**around** the API application in ``http/serve.py``'s ``with_bundle``, outside
``build_app``'s handlers, which is why ``test_a_missing_bundle_file_is_a_404_not_a_server_error``
exists: ``with_bundle`` now wraps the static branch in the same
``with_error_envelope`` the API uses, and this test is what keeps a missing
bundle file a 404 envelope rather than a raw ASGI 500.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from hephaestus.http.serve import with_bundle
from hephaestus.testing.workspace import WORKSPACE_TOKEN, uuid7, workspace
from starlette.testclient import TestClient
from starlette.types import ASGIApp


def _lenient_client(app: ASGIApp) -> httpx.Client:
    """A client that returns a 500 response instead of raising the exception.

    Mirrors ``test_session_readopt.py``'s own construction
    (``TestClient(self.app, raise_server_exceptions=False)``) — the only way to
    observe what an *unhandled* exception does to the wire, since the default
    ``TestClient`` re-raises it into the test itself.
    """
    return cast("httpx.Client", TestClient(app, raise_server_exceptions=False))


# --------------------------------------------------------------------------
# 404 — a route the table does not carry


def test_a_route_miss_carries_the_error_envelope(tmp_path: Path) -> None:
    """No route matches → 404, ``application/json``, ``reason == "unknown_route"``.

    Today this is Starlette's default HTTP-exception handler: ``text/plain``,
    body ``Not Found``, no ``status``/``reason``/``message`` at all.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.get("/nosuchroute")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["status"] == "error"
    assert body["reason"] == "unknown_route"
    assert isinstance(body["message"], str) and body["message"]


def test_a_route_miss_under_an_unknown_prefix_is_still_the_envelope(
    tmp_path: Path,
) -> None:
    """Not just a near-miss on a real path — anything outside the table."""
    with workspace(tmp_path / "proj") as web:
        response = web.get("/completely/made/up/path")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["reason"] == "unknown_route"


# --------------------------------------------------------------------------
# 405 — a route the table carries, for a method it does not serve


def test_a_wrong_method_carries_the_envelope_and_keeps_allow(tmp_path: Path) -> None:
    """``GET /project`` is served; ``POST /project`` is not.

    The fix must preserve the ``Allow`` header Starlette attaches to its own
    405 — losing it while repairing the body would regress a correct behaviour
    while fixing an incorrect one (the ledger's own condition on this fix).
    """
    with workspace(tmp_path / "proj") as web:
        response = web.post("/project")
    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["status"] == "error"
    assert body["reason"] == "method_not_allowed"
    allow = response.headers.get("allow", "")
    assert "GET" in [m.strip() for m in allow.split(",")]


# --------------------------------------------------------------------------
# 500 — an exception no branch of `refusal_for` maps


def test_an_unmapped_exception_reaches_the_client_as_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bug nobody classified still gets a name, a status, and an incident id.

    ``refusal_for`` deliberately ends in a bare ``raise exc`` for anything it
    does not recognise (an unclassified exception must never be guessed into a
    plausible-looking refusal), and today nothing above it in the ASGI stack
    catches that raise: it becomes Starlette's default ``text/plain``
    ``Internal Server Error``, with no ``incident`` id an operator's log could
    join back to the traceback uvicorn printed.

    The exception's own text must NOT reach the client: this path is reached by
    exceptions nobody has classified, and therefore nobody has redacted.
    """
    import hephaestus.http.app as app_module

    secret_detail = "disk exploded, credential=do-not-leak-this-9f3c"

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise OSError(secret_detail)

    monkeypatch.setattr(app_module, "open_project_projection", _boom)

    with workspace(tmp_path / "proj") as web:
        client = _lenient_client(web.app)
        response = client.get(
            "/api/v1/project", headers={"Authorization": f"Bearer {WORKSPACE_TOKEN}"}
        )
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["status"] == "error"
    assert body["reason"] == "internal_error"
    assert isinstance(body.get("incident"), str) and body["incident"]
    assert secret_detail not in response.text


def test_the_internal_error_message_is_fixed_not_the_exceptions_own_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two different unmapped exceptions get the SAME message.

    If the handler ever formatted ``str(exc)`` into ``message`` this would fail
    the moment the two bodies differed — the fixed-sentence-plus-incident-id
    design the ledger specifies, pinned by behaviour rather than by reading the
    handler's source.
    """
    import hephaestus.http.app as app_module

    def _boom_one(*_args: object, **_kwargs: object) -> object:
        raise OSError("first distinct failure text")

    def _boom_two(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("second, completely different failure text")

    with workspace(tmp_path / "proj") as web:
        client = _lenient_client(web.app)
        monkeypatch.setattr(app_module, "open_project_projection", _boom_one)
        first = client.get(
            "/api/v1/project", headers={"Authorization": f"Bearer {WORKSPACE_TOKEN}"}
        )
        monkeypatch.setattr(app_module, "open_project_projection", _boom_two)
        second = client.get(
            "/api/v1/project", headers={"Authorization": f"Bearer {WORKSPACE_TOKEN}"}
        )
    assert first.status_code == second.status_code == 500
    assert first.json()["message"] == second.json()["message"]
    # And the incident ids still tell the two apart.
    assert first.json()["incident"] != second.json()["incident"]


# --------------------------------------------------------------------------
# The standing guard: nothing this process serves for an unrouted path is text


def test_every_response_for_an_unrouted_or_unauthenticated_path_is_json(
    tmp_path: Path,
) -> None:
    """A future middleware addition cannot silently reopen this hole.

    Covers the shapes §2.4's amendment names explicitly: a route miss, a wrong
    method, and (per the verification focus) the websocket route hit as a plain
    GET with no ``Upgrade`` header, which is a route miss by the same mechanism.
    """
    with workspace(tmp_path / "proj") as web:
        probes = [
            ("GET", "/nosuchroute"),
            ("POST", "/project"),
            ("GET", "/events"),  # no Upgrade header: not a websocket handshake
            ("DELETE", "/sessions"),
        ]
        for method, path in probes:
            response = web.request(method, path)
            assert response.headers["content-type"].startswith("application/json"), (
                method,
                path,
                response.headers.get("content-type"),
            )
            body = response.json()
            assert body["status"] == "error", (method, path)


# --------------------------------------------------------------------------
# The static-bundle sibling: composed AROUND the API, so it has no middleware
# of its own today either.


def test_a_missing_bundle_file_is_a_404_not_a_server_error(tmp_path: Path) -> None:
    """A path the bundle does not contain is a 404, never a 500.

    ``with_bundle`` composes the built client's static files around the API
    application as a bare ASGI callable with no exception middleware between it
    and the server — today a missing file (``/favicon.ico``, most visibly)
    raises straight through and every page load logs a traceback. The client
    keeps its navigation state in the URL fragment, so a path the bundle does
    not contain must be a named 404, never a single-page fallback and never an
    unhandled fault.
    """
    bundle = tmp_path / "dist"
    bundle.mkdir()
    (bundle / "index.html").write_text("<!doctype html><title>workspace</title>", encoding="utf-8")
    with workspace(tmp_path / "proj") as web:
        client = _lenient_client(with_bundle(web.app, bundle))

        favicon = client.get("/favicon.ico")
        assert favicon.status_code == 404
        # TIGHTENED: B-6/B-11 landed while this file was authored (see the
        # module docstring), so the static branch's 404 is the §2.4 envelope
        # now, not the plain-text default the surrounding prose describes.
        assert favicon.headers.get("content-type", "").startswith("application/json")
        assert favicon.json()["reason"] == "unknown_route"

        root = client.get("/")
        assert root.status_code == 200
        assert "workspace" in root.text

        index = client.get("/index.html")
        assert index.status_code == 200
        assert "workspace" in index.text


# --------------------------------------------------------------------------
# J-http-envelope-19 — the unauthorized WebSocket close code was dead


def test_an_unauthenticated_upgrade_is_refused_at_the_handshake(tmp_path: Path) -> None:
    """A form that does not mention a close code — because none is delivered.

    Under ASGI a close sent in the connect phase (before ``accept``) arrives as
    an HTTP rejection, so the fix deletes the dead ``UNAUTHORIZED_CLOSE_CODE``
    constant rather than keep exporting a code no client ever receives. This is
    the assertion the ledger says the auth case needs: the handshake is
    refused, and nothing here asserts a code exists to see.
    """
    with (
        workspace(tmp_path / "proj") as web,
        pytest.raises(Exception) as caught,
        web.events(token=None),
    ):
        pass
    # Different starlette/httpx versions surface this as a WebSocketDenialResponse
    # or a bare disconnect; the shape that must NOT appear is a successful
    # accept, and no assertion here inspects a close code.
    assert caught.value is not None


def test_events_ws_no_longer_exports_a_close_code_for_the_dead_path() -> None:
    """The structural half: the constant is gone, not just unused."""
    from hephaestus.http import events_ws

    assert not hasattr(events_ws, "UNAUTHORIZED_CLOSE_CODE")
    assert "UNAUTHORIZED_CLOSE_CODE" not in events_ws.__all__


# --------------------------------------------------------------------------
# J-http-envelope-20 — the script route was the only 200 body with no `status`


def test_the_script_route_carries_status_alongside_every_other_field(
    tmp_path: Path,
) -> None:
    """``GET /parts/{part}/script`` is a verbatim tool result plus one added
    field — asserted as "every pre-existing field, unchanged, plus status" so
    "verbatim" is pinned as well as the addition.
    """
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/widget/script").json()
    assert body["status"] == "ok"
    for field in ("content_hash", "script", "line_count", "truncated"):
        assert field in body, f"missing pre-existing field {field!r}"


def test_every_200_document_this_api_can_return_carries_a_status(
    tmp_path: Path,
) -> None:
    """The boundary assertion the ledger asks for: derived from the route
    table itself so a future route inherits the rule rather than needing to be
    added to a hand-picked list. GET-only, key-free, no-argument routes —
    every route this walk can drive with nothing but a part name and no
    mutation.
    """
    from hephaestus.http.app import ROUTE_TABLE

    with workspace(tmp_path / "proj") as web:
        web.post("/parts/widget/build", json={}, key=uuid7())
        for method, template in ROUTE_TABLE:
            if method != "GET" or "{ref}" in template or "{export_blob}" in template:
                continue
            path = template.replace("{part}", "widget").replace("{id}", "sess-none")
            response = web.get(path)
            if response.status_code != 200:
                continue  # a refusal is asserted elsewhere; this walk is 200-only
            body = cast("dict[str, Any]", response.json())
            assert isinstance(body, dict) and body.get("status") == "ok", (
                f"{method} {template} returned 200 with no status field: {body}"
            )
