# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§2.1/§2.2 — one process owns the leases, and how a client finds it.

``INTERFACE.md`` §2.1 and §2.2. The serving process owns the session leases under
``.heph/locks/`` and writes ``<project>/.heph/serve.json`` (``0600``). ``heph
agent`` gains **no new flag**: it reads that file and, if a live server owns the
project, runs in client mode instead of opening a second in-process bridge. The
rejected alternative — a ``--server URL`` flag — is an added surface with no gate
behind it, and it invites pointing the CLI at a server that does not own the
project's locks.

The token is minted per serve into ``.heph/serve.token`` (``0600``) and rides in
the URL **fragment**, never a query string, so it never enters an access log or a
``Referer``.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import cast

import pytest
from hephaestus.agent_bridge.serve_record import ServeRecord
from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.layout import find_project_root
from hephaestus.http.agent_attach import AttachRefused
from hephaestus.http.principal import (
    SERVE_JSON_NAME,
    SERVE_TOKEN_NAME,
    clear_serve_record,
    mint_token,
    read_serve_record,
    token_id,
    verify_token,
    write_serve_record,
)
from hephaestus.http.serve import (
    DEFAULT_WEB_HOST,
    DEFAULT_WEB_PORT,
    owning_server,
    parse_web_address,
    serve_web,
)


def test_the_token_and_serve_record_are_owner_only_files(tmp_path: Path) -> None:
    """Both are ``0600``: same-user secrets on a loopback box, and nothing more.

    Created with ``O_CREAT|O_TRUNC`` at mode ``0600`` rather than written and
    then chmod'ed — the window between those two is exactly when another local
    user could open the file.
    """
    store = tmp_path / ".heph"
    token, token_path = mint_token(store)
    write_serve_record(store, http="http://127.0.0.1:8760", token_path=token_path)

    assert token_path.name == SERVE_TOKEN_NAME
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((store / SERVE_JSON_NAME).stat().st_mode) == 0o600
    assert len(token) >= 32


def test_the_serve_record_carries_exactly_the_five_documented_fields(
    tmp_path: Path,
) -> None:
    """§2.1 pins the shape: ``{pid, http, started_at, token_path, started_by}``."""
    store = tmp_path / ".heph"
    _, token_path = mint_token(store)
    record = write_serve_record(store, http="http://127.0.0.1:8760", token_path=token_path)

    on_disk = json.loads((store / SERVE_JSON_NAME).read_text(encoding="utf-8"))
    assert set(on_disk) == {"pid", "http", "started_at", "token_path", "started_by"}
    assert on_disk["pid"] == os.getpid() == record.pid
    assert read_serve_record(store) == record


def test_a_record_naming_a_dead_process_is_not_an_owner(tmp_path: Path) -> None:
    """A crashed serve must not wedge the project permanently.

    "Live" is checked, not assumed: a ``serve.json`` left behind by a hard kill
    names a pid that no longer exists, and treating that as an owner would make
    the project unserveable until a human deleted a file they have never heard
    of. A stale record reads as **no owner**.
    """
    store = tmp_path / ".heph"
    _, token_path = mint_token(store)
    record = write_serve_record(store, http="http://127.0.0.1:8760", token_path=token_path)
    assert owning_server(tmp_path) == record

    (store / SERVE_JSON_NAME).write_text(
        json.dumps({**record.to_json(), "pid": 2**22 - 1}), encoding="utf-8"
    )
    assert owning_server(tmp_path) is None


def test_an_unreadable_or_malformed_record_reads_as_no_owner(tmp_path: Path) -> None:
    """The question is "does a server own this project"; an unreadable answer is none."""
    store = tmp_path / ".heph"
    store.mkdir(parents=True)
    assert read_serve_record(store) is None  # absent

    (store / SERVE_JSON_NAME).write_text("{not json", encoding="utf-8")
    assert read_serve_record(store) is None  # malformed

    (store / SERVE_JSON_NAME).write_text('{"pid": 1}', encoding="utf-8")
    assert read_serve_record(store) is None  # incomplete


def test_clearing_the_record_is_idempotent(tmp_path: Path) -> None:
    """Shutdown must not fail because it already ran, or never wrote one."""
    store = tmp_path / ".heph"
    store.mkdir(parents=True)
    clear_serve_record(store)
    _, token_path = mint_token(store)
    write_serve_record(store, http="http://127.0.0.1:1", token_path=token_path)
    clear_serve_record(store)
    clear_serve_record(store)
    assert read_serve_record(store) is None


def test_tokens_are_compared_in_constant_time_and_distinguish(tmp_path: Path) -> None:
    """One bearer, and the only authentication this surface has."""
    minted, _ = mint_token(tmp_path / "a")
    other, _ = mint_token(tmp_path / "b")
    assert verify_token(minted, minted)
    assert not verify_token(other, minted)
    assert not verify_token("", minted)


def test_the_token_id_is_short_stable_and_not_the_token(tmp_path: Path) -> None:
    """The ledger and the principal carry a label, never the secret itself."""
    token, _ = mint_token(tmp_path / ".heph")
    label = token_id(token)
    assert label == token_id(token)
    assert token not in label
    assert len(label) == 16


def test_the_web_address_defaults_to_loopback(tmp_path: Path) -> None:
    """``architecture.md`` §7: loopback plus a bearer token. Not a deployment."""
    assert parse_web_address(None) == (DEFAULT_WEB_HOST, DEFAULT_WEB_PORT)
    assert parse_web_address("") == (DEFAULT_WEB_HOST, DEFAULT_WEB_PORT)
    assert parse_web_address("9000") == (DEFAULT_WEB_HOST, 9000)
    assert parse_web_address("127.0.0.1:9000") == ("127.0.0.1", 9000)
    assert DEFAULT_WEB_HOST == "127.0.0.1"


def test_the_serve_verb_carries_both_flags_and_neither_requires_the_other() -> None:
    """§2.1 DECISION (binds G4.8): ``--web`` is orthogonal to ``--mcp``.

    Asserted on the real parser, because the two halves are registered by two
    modules (``mcp.cli_serve`` owns ``--mcp``, ``http.cli_web`` owns ``--web``)
    and the thing that could break is the assembly, not either half.
    """
    from hephaestus.core.cli import build_parser

    parsed = build_parser().parse_args(["serve", "--web", "--web-address", "127.0.0.1:9"])
    assert parsed.web is True
    assert parsed.mcp is False
    assert parsed.web_address == "127.0.0.1:9"

    mcp_only = build_parser().parse_args(["serve", "--mcp"])
    assert mcp_only.mcp is True
    assert mcp_only.web is False


def test_serve_with_neither_flag_is_a_usage_error() -> None:
    """Neither flag serves nothing, and says so rather than idling."""
    from hephaestus.core.cli import build_parser

    args = build_parser().parse_args(["serve"])
    assert args.func(args) == 2


def test_mcp_and_web_in_one_process_is_refused_by_name() -> None:
    """The combination is the intended end state and is **not** built yet.

    Refused by name rather than silently serving one of them and leaving the
    operator to discover which. What is missing is the single event loop that
    would run FastMCP's transport and the workspace app together — not the
    policy, which §2.1 already settles.
    """
    from hephaestus.core.cli import build_parser

    args = build_parser().parse_args(["serve", "--mcp", "--web"])
    assert args.func(args) == 2


# --------------------------------------------------------------------------
# §3 — the built bundle is composed AROUND the API, never inside it


def test_the_bundle_is_served_beside_the_api_without_widening_the_route_table(
    tmp_path: Path,
) -> None:
    """§3's wheel-embedded bundle, and §1's closed table, at the same time.

    ``heph serve --web`` serves the built client at ``/`` and the API under
    ``/api/`` so the browser loads the app from the origin that answers its
    requests — the topology a wheel-installed operator gets, and the one the
    Gate G4 browser suite runs against.

    The composition happens **outside** :func:`build_app`. That is not a style
    choice: ``test_http_boundary.py`` asserts the served surface *is* §2.3's
    closed route table in both directions, so a static mount added to the
    application would either fail that test or force it to be weakened into
    admitting mounts — and the check that the API serves nothing else is the
    whole point of having it. This test pins both halves at once: the wrapper
    routes, and the wrapped application's own routes are untouched.
    """
    from typing import cast

    import httpx
    from hephaestus.http.serve import with_bundle
    from hephaestus.testing.workspace import WORKSPACE_TOKEN, workspace
    from starlette.testclient import TestClient

    bundle = tmp_path / "dist"
    bundle.mkdir()
    (bundle / "index.html").write_text("<!doctype html><title>workspace</title>", encoding="utf-8")

    with workspace(tmp_path / "proj") as web:
        before = len(web.app.routes)
        # ``TestClient`` *is* an ``httpx.Client``; narrowing to the base is what
        # makes `.get` and `.close` typed, since starlette's lazy httpx import
        # leaves the subclass's inherited members unresolved (the same narrowing
        # `hephaestus.testing.workspace.Workspace` makes, for the same reason).
        client = cast("httpx.Client", TestClient(with_bundle(web.app, bundle)))
        try:
            page = client.get("/")
            assert page.status_code == 200
            assert "workspace" in page.text

            # The API is unchanged, bearer and all.
            assert client.get("/api/v1/project").status_code == 401
            authed = client.get(
                "/api/v1/project", headers={"Authorization": f"Bearer {WORKSPACE_TOKEN}"}
            )
            assert authed.status_code == 200

            # A path the table does not carry is a 404, not a new route.
            missing = client.get(
                "/api/v1/nope", headers={"Authorization": f"Bearer {WORKSPACE_TOKEN}"}
            )
            assert missing.status_code == 404
        finally:
            client.close()
        assert len(web.app.routes) == before, "with_bundle must not add routes to the API app"


def test_no_built_bundle_is_a_named_absence_that_still_serves_the_api(tmp_path: Path) -> None:
    """A missing (or entry-point-less) ``web/dist`` degrades to the API alone.

    An operator who has not run ``pnpm --dir web build`` gets a sentence on
    stderr and a working API, rather than a blank page or a failed serve. A
    directory with no ``index.html`` is not a bundle either: serving it would
    answer ``/`` with an unexplained 404.
    """
    from hephaestus.http.serve import with_bundle
    from hephaestus.testing.workspace import workspace

    empty = tmp_path / "no-dist"
    empty.mkdir()
    with workspace(tmp_path / "proj") as web:
        assert with_bundle(web.app, empty) is web.app


# --------------------------------------------------------------------------
# §2.1 — `--project DIR`: the serve verb, run from anywhere


def _bare_project(root: Path) -> Path:
    """The smallest thing ``find_project_root`` will accept, and nothing more."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    return root


class _StubRuntime:
    """Stands in for :class:`WorkspaceRuntime` so no sandbox is probed.

    ``serve_web`` opens the real runtime with ``serve_mode=True``, which probes a
    secure executor backend; that probe is a property of the machine, not of the
    flag under test. What these tests need from the runtime is the one thing the
    flag decides — **which root it was opened on** — so that is what the stub
    records.
    """

    opened_on: Path | None = None

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def open(cls, root: Path, **_: object) -> _StubRuntime:
        cls.opened_on = root
        return cls(root)

    def attach_agent(self) -> object:
        raise AttachRefused("no_provider_config", self.root / ".heph", "stubbed")

    def detach_agent(self) -> None:
        return None

    def close(self) -> None:
        return None


def _stub_serve(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Neuter everything ``serve_web`` does *except* project resolution."""
    import uvicorn
    from hephaestus.http import serve as serve_module

    seen: dict[str, object] = {}
    _StubRuntime.opened_on = None
    monkeypatch.setattr(serve_module, "WorkspaceRuntime", _StubRuntime)

    def _identity(app: object) -> object:
        return app

    monkeypatch.setattr(serve_module, "build_app", _identity)
    monkeypatch.setattr(serve_module, "with_bundle", _identity)

    def _run(_app: object, **kwargs: object) -> None:
        # Called where the real server would block: the serve record still
        # exists here, and is deleted by the `finally` that follows.
        seen["record"] = read_serve_record(cast("Path", seen["store"]))
        seen["bind"] = (kwargs.get("host"), kwargs.get("port"))

    monkeypatch.setattr(uvicorn, "run", _run)
    return seen


def test_serve_project_dir_is_resolved_from_that_dir_not_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``heph serve --web --project DIR`` serves DIR's project from anywhere.

    The flag exists so the workspace can be started without ``cd`` — which is
    only true if *everything* the serve derives moves with it. So this asserts
    the whole set at once: the runtime is opened on the resolved root, the token
    and the ``serve.json`` record are written under **that** root's ``.heph/``,
    and the unrelated working directory is left without a ``.heph/`` at all.
    """
    project = _bare_project(tmp_path / "proj")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    seen = _stub_serve(monkeypatch)
    seen["store"] = project / ".heph"

    assert serve_web(root=project, open_browser=False) == 0

    assert _StubRuntime.opened_on == project.resolve()
    assert (project / ".heph" / SERVE_TOKEN_NAME).is_file()
    record = cast("ServeRecord | None", seen["record"])
    assert record is not None and record.http == f"http://{DEFAULT_WEB_HOST}:{DEFAULT_WEB_PORT}"
    assert not (elsewhere / ".heph").exists()


def test_serve_project_dir_walks_up_to_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DIR *inside* a project resolves to the project, exactly as cwd would.

    ``--project`` is a starting point for ``find_project_root``, not a claim that
    the directory named is itself the root — the same rule every other verb
    follows, so ``--project parts/`` is not a surprise.
    """
    project = _bare_project(tmp_path / "proj")
    nested = project / "parts" / "deeper"
    nested.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    seen = _stub_serve(monkeypatch)
    seen["store"] = project / ".heph"

    assert serve_web(root=nested, open_browser=False) == 0
    assert _StubRuntime.opened_on == project.resolve()


def test_serve_and_agent_agree_on_the_project_a_dir_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record ``--project`` writes is the one ``heph agent --project`` finds.

    §2.1 gives ``heph agent`` **no new flag**: it discovers a live serve by
    reading ``<root>/.heph/serve.json``. That handshake only holds if both verbs
    resolve the same DIR to the same root, so the discovery half is run here
    against the record the serve half actually wrote — from a *third* directory,
    so neither side can be right by accident.
    """
    project = _bare_project(tmp_path / "proj")
    nested = project / "parts"
    nested.mkdir()
    monkeypatch.chdir(tmp_path)
    seen = _stub_serve(monkeypatch)
    seen["store"] = project / ".heph"

    found: dict[str, object] = {}

    def _run(_app: object, **_kwargs: object) -> None:
        # `heph agent --project <nested>` does exactly this: resolve the root,
        # then ask whether a live server owns it.
        found["owner"] = owning_server(find_project_root(nested))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", _run)
    assert serve_web(root=project, open_browser=False) == 0

    owner = cast("ServeRecord | None", found["owner"])
    assert owner is not None
    assert owner.pid == os.getpid()


def test_serve_project_dir_outside_a_project_refuses_like_the_cwd_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad ``--project`` is the same refusal a bad working directory is.

    Same exception, same ``validation_error`` code, same kind — because it is
    the same call, given a different starting point. A separate refusal for the
    flag would be a second thing to keep in step with the first.
    """
    outside = tmp_path / "not-a-project"
    outside.mkdir()
    monkeypatch.chdir(outside)
    _stub_serve(monkeypatch)

    with pytest.raises(ValidationError) as flag_exc:
        serve_web(root=outside, open_browser=False)
    with pytest.raises(ValidationError) as cwd_exc:
        serve_web(open_browser=False)

    assert flag_exc.value.code == cwd_exc.value.code == "validation_error"
    assert flag_exc.value.kind == cwd_exc.value.kind == "contract"
    assert str(flag_exc.value) == str(cwd_exc.value)


def test_the_no_project_refusal_says_what_a_project_is_and_how_to_make_one(
    tmp_path: Path,
) -> None:
    """The first refusal a new operator meets has to be actionable.

    The **code** is deliberately unchanged (``validation_error``) and so is the
    leading ``no hephaestus.toml found`` clause that other tests and callers
    match on; what the message gained is the two facts a stranded operator is
    missing — what a project is, and the verb that makes one.
    """
    outside = tmp_path / "nowhere"
    outside.mkdir()
    with pytest.raises(ValidationError) as exc_info:
        find_project_root(outside)

    message = str(exc_info.value)
    assert exc_info.value.code == "validation_error"
    assert message.startswith("no hephaestus.toml found at or above ")
    assert str(outside) in message
    assert "heph init DIR" in message
    assert "--project DIR" in message


# --------------------------------------------------------------------------
# the flag on the real parser


def test_the_serve_verb_carries_project_beside_the_web_flags() -> None:
    """``--project DIR`` is spelled exactly as ``heph agent --project`` is."""
    from hephaestus.core.cli import build_parser

    parsed = build_parser().parse_args(["serve", "--web", "--project", "/tmp/x"])
    assert parsed.web is True
    assert parsed.project == "/tmp/x"
    assert build_parser().parse_args(["serve", "--web"]).project is None


def test_serve_project_is_expanded_and_handed_to_the_web_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~`` is expanded at the CLI boundary, where the string came from."""
    from hephaestus.core.cli import build_parser
    from hephaestus.http import serve as serve_module

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "proj").mkdir()
    seen: dict[str, object] = {}

    def _serve_web(*, web: str | None = None, root: Path | None = None) -> int:
        seen["web"] = web
        seen["root"] = root
        return 0

    monkeypatch.setattr(serve_module, "serve_web", _serve_web)
    args = build_parser().parse_args(["serve", "--web", "--project", "~/proj"])
    assert args.func(args) == 0
    assert seen["root"] == tmp_path / "proj"


def test_serve_project_that_is_not_a_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo'd or file-shaped ``--project`` must not walk up into another project.

    ``find_project_root`` resolves non-strictly and then climbs, so both a
    missing directory *inside* a project and the project's own
    ``hephaestus.toml`` used to resolve to that project and serve it — minting a
    token and a serve record under a root the operator never named.
    """
    from hephaestus.core.cli import build_parser
    from hephaestus.http import serve as serve_module

    (tmp_path / "hephaestus.toml").write_text("", encoding="utf-8")

    def _unreachable(**_kwargs: object) -> int:  # pragma: no cover - must not run
        raise AssertionError("serve_web must not be reached")

    monkeypatch.setattr(serve_module, "serve_web", _unreachable)

    for target in (tmp_path / "typoo", tmp_path / "hephaestus.toml"):
        args = build_parser().parse_args(["serve", "--web", "--project", str(target)])
        assert args.func(args) == 2
        assert f"--project {target}: not a directory" in capsys.readouterr().err


def test_serve_project_that_is_a_directory_still_walks_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard refuses non-directories only; a real subdirectory still resolves."""
    from hephaestus.core.cli import build_parser
    from hephaestus.http import serve as serve_module

    nested = tmp_path / "parts"
    nested.mkdir()
    seen: dict[str, object] = {}

    def _serve_web(*, web: str | None = None, root: Path | None = None) -> int:
        seen["root"] = root
        return 0

    monkeypatch.setattr(serve_module, "serve_web", _serve_web)
    args = build_parser().parse_args(["serve", "--web", "--project", str(nested)])
    assert args.func(args) == 0
    assert seen["root"] == nested


def test_serve_project_without_web_is_refused_by_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The MCP half resolves the project from the cwd; ignoring the flag would lie.

    An accepted-and-ignored ``--project`` would leave the operator believing the
    MCP transport had been aimed somewhere it never looked — the one failure a
    usage error costs nothing to prevent.
    """
    from hephaestus.core.cli import build_parser

    args = build_parser().parse_args(["serve", "--mcp", "--project", "/tmp/x"])
    assert args.func(args) == 2
    assert "--project applies to --web" in capsys.readouterr().err
