# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph serve --web`` — the workspace half of the serve verb (§2.1).

**DECISION (binds G4.8).** ``--web [HOST:PORT]`` is **orthogonal to** ``--mcp``:
``--mcp`` remains required for the MCP transport and is not required for
``--web``. What survives unchanged is the invariant that matters — both force
``serve_mode=True``, so the secure backend is probed and
``--unsafe-local-executor`` remains absent from this verb. **The web never has an
unsandboxed path.**

The serving process **owns the session leases** under ``.heph/locks/`` and writes
``<project>/.heph/serve.json`` (``0600``). ``heph agent`` gains **no new flag**:
at startup it reads that file and, if a live server owns the project, runs in
client mode against the loopback API instead of spawning its own
``BridgeRuntime``. :func:`owning_server` is the discovery half of that handshake
— the client-mode driving half is §2.1's separate named new work (§19 item 3).

*Rejected alternative:* a ``--server URL`` flag on ``heph agent``. Rejected as an
added surface with no gate behind it; ``serve.json`` is discovery enough, and a
flag invites pointing the CLI at a server that does not own the project's locks.

The token is printed (and on a TTY opened) as
``http://127.0.0.1:PORT/#t=<token>`` — in the **fragment**, never a query
string, so it never enters an access log or a ``Referer``.
"""

from __future__ import annotations

import os
import signal
import sys
import webbrowser
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Final

from hephaestus.agent_bridge.serve_record import owning_server
from hephaestus.core.project_store.layout import find_project_root
from starlette.types import ASGIApp, Receive, Scope, Send

from .app import build_app
from .principal import clear_serve_record, mint_token, write_serve_record
from .runtime import WorkspaceRuntime

if TYPE_CHECKING:
    from hephaestus.agent_bridge.app import BridgeRuntime

__all__ = [
    "DEFAULT_WEB_HOST",
    "DEFAULT_WEB_PORT",
    "owning_server",
    "parse_web_address",
    "serve_web",
    "web_bundle",
    "with_bundle",
]

#: Loopback only. ``architecture.md`` §7: no TLS, no real authn, no
#: multi-tenancy, no hosted posture. A bind address is not a deployment story.
DEFAULT_WEB_HOST: Final[str] = "127.0.0.1"
DEFAULT_WEB_PORT: Final[int] = 8760


def parse_web_address(value: str | None) -> tuple[str, int]:
    """Parse ``--web``'s optional ``HOST:PORT`` (or a bare ``PORT``)."""
    if value is None or not value.strip():
        return DEFAULT_WEB_HOST, DEFAULT_WEB_PORT
    text = value.strip()
    if ":" not in text:
        return DEFAULT_WEB_HOST, int(text)
    host, _, port = text.rpartition(":")
    return (host or DEFAULT_WEB_HOST), int(port)


def serve_web(
    *, web: str | None = None, root: Path | None = None, open_browser: bool = True
) -> int:
    """Run the workspace API on loopback until interrupted.

    Refuses rather than racing when another live process already owns the
    project: ``architecture.md`` §4.2 already says a second process must route
    through the owning server or fail ``session_busy``, and two servers on one
    project would put two writers on one Pi JSONL.
    """
    import uvicorn

    project_root = find_project_root(Path.cwd() if root is None else root)
    existing = owning_server(project_root)
    if existing is not None:
        print(
            f"heph: serve: pid {existing.pid} already serves this project at {existing.http}",
            file=sys.stderr,
        )
        return 1

    host, port = parse_web_address(web)
    token, token_path = mint_token(project_root / ".heph")
    runtime = WorkspaceRuntime.open(project_root, token=token, serve_mode=True)
    bridge = _attach_agent(runtime)
    url = f"http://{host}:{port}"
    try:
        write_serve_record(project_root / ".heph", http=url, token_path=token_path)
        entry = f"{url}/#t={token}"
        # Flushed explicitly: stdout is block-buffered when it is not a TTY, and
        # a `heph serve --web > log` whose URL only appears at shutdown is a URL
        # the operator never gets. This is the one line the command exists to
        # emit.
        print(entry, flush=True)
        if open_browser and sys.stdout.isatty():
            webbrowser.open(entry)
        _install_shutdown_handlers()
        uvicorn.run(with_bundle(build_app(runtime)), host=host, port=port, log_level="warning")
    finally:
        # Best effort. A hard kill (SIGKILL, a power cut) leaves the record
        # behind, and that is *safe* rather than merely tolerated:
        # :func:`owning_server` probes the recorded pid, so a stale record reads
        # as "no owner" instead of wedging the project permanently.
        clear_serve_record(project_root / ".heph")
        if runtime.sessions is not None:
            runtime.sessions.close()
        if bridge is not None:
            bridge.close()
        runtime.close()
    return 0


def _attach_agent(runtime: WorkspaceRuntime) -> BridgeRuntime | None:
    """Start the one agent runtime this process owns, if it can (§2.1, §2.7).

    **The store, project store, CadOps and dispatcher are injected**, not opened
    again: two opstore handles in one process would be two ``LockManager`` owners
    over one project's ``.heph/locks/``, which is precisely what "one process owns
    the leases" exists to prevent.

    Absence is a **named** state, not a degraded one. A project with no provider
    config has nothing to configure a sidecar with, and a machine with no (or too
    old a) Node has nothing to spawn; in either case the workspace still serves
    every read, mutation, artifact and git route, and the session routes refuse
    by name (``agent_unavailable``). Failing the whole serve because an agent
    could not start would make the panels that need no agent unreachable too.
    """
    from hephaestus.agent_bridge.app import AuthLinkError, BridgeRuntime
    from hephaestus.agent_bridge.cli import ConfigError, load_provider_config
    from hephaestus.agent_bridge.sidecar import SidecarError
    from hephaestus.agent_bridge.supervisor import SupervisorError

    config_path = runtime.root / ".heph" / "providers.json"
    env_path = os.environ.get("HEPHAESTUS_AGENT_PROVIDERS")
    if env_path:
        config_path = Path(env_path).expanduser()
    if not config_path.is_file():
        print(
            f"heph: serve: no provider config at {config_path}; "
            "serving without an agent runtime (session routes refuse agent_unavailable)",
            file=sys.stderr,
            flush=True,
        )
        return None
    try:
        config = load_provider_config(config_path)
        bridge = BridgeRuntime(
            project_root=runtime.root,
            providers=config.providers,
            credentials=config.credentials(),
            credential_allowlist=config.credential_allowlist,
            auth_source=config.auth_source,
            store=runtime.store,
            project_store=runtime.project_store,
            cad=runtime.cad,
            dispatcher=runtime.dispatcher,
        )
        bridge.start()
    except (ConfigError, AuthLinkError, SidecarError, SupervisorError, RuntimeError) as exc:
        print(f"heph: serve: agent runtime unavailable ({exc})", file=sys.stderr, flush=True)
        return None
    runtime.attach_sessions(bridge)
    return bridge


def _install_shutdown_handlers() -> None:
    """Turn SIGTERM/SIGINT into a normal unwind so ``finally`` actually runs.

    Without this the process dies where it stands and ``serve.json`` outlives
    it. The record would still be harmless (see above), but a server that tidies
    up after itself when asked politely is the difference between "stale records
    are handled" and "stale records are normal".
    """

    def _exit(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(ValueError):  # not the main thread: uvicorn handles it
            signal.signal(sig, _exit)


# --------------------------------------------------------------------------
# the built client bundle (§3)
# --------------------------------------------------------------------------

#: Everything under this prefix is the API; everything else is the bundle.
_API_ROOT: Final[str] = "/api/"

#: Where a wheel carries the built client, staged at build time.
_PACKAGED_BUNDLE: Final[str] = "_web"


def web_bundle() -> Path | None:
    """The built ``web/`` bundle this installation would serve, or ``None``.

    §3: "built assets ship inside the wheel, served by ``--web`` from
    ``importlib.resources``". Two locations, in order, because a source checkout
    is the case the browser gate runs in:

    1. ``hephaestus/http/_web/`` — the wheel-staged bundle;
    2. ``<repo>/web/dist`` — what ``pnpm --dir web build`` writes.

    ``None`` means no bundle was built. That is a **named** state, not a failure:
    the API still serves every route, and an operator who has not built the
    client gets a sentence saying so rather than a blank page.
    """
    packaged = Path(__file__).resolve().parent / _PACKAGED_BUNDLE
    if (packaged / "index.html").is_file():
        return packaged
    try:
        from hephaestus.agent_bridge.app import repo_root

        candidate = repo_root() / "web" / "dist"
    except Exception:  # pragma: no cover - installed wheel, no repo above us
        return None
    return candidate if (candidate / "index.html").is_file() else None


def with_bundle(api: ASGIApp, bundle: Path | None = None) -> ASGIApp:
    """Serve ``api`` under ``/api/`` and the built client everywhere else.

    **The API application's own route surface is untouched**, and that is the
    point. ``server/tests/test_http_boundary.py`` asserts the served surface *is*
    §2.3's closed route table in both directions; mounting static files inside
    :func:`build_app` would have made that test fail, and weakening it to admit a
    mount would have weakened the check that the API serves nothing else. So the
    bundle is composed **around** the application at the process boundary, where
    it belongs: one origin for the operator, one closed table for the API.

    With no bundle built, the wrapper is not applied at all — the API is served
    alone, which is exactly what it was before this existed.
    """
    resolved = bundle if bundle is not None else web_bundle()
    if resolved is not None and not (resolved / "index.html").is_file():
        # A directory with no entry point is not a bundle. Serving it would give
        # the operator a 404 at `/` with no explanation; saying so is better.
        resolved = None
    if resolved is None:
        print(
            "heph: serve: no built web bundle found (run `pnpm --dir web build`); "
            "serving the API only",
            file=sys.stderr,
            flush=True,
        )
        return api
    from starlette.staticfiles import StaticFiles

    static = StaticFiles(directory=resolved, html=True)

    async def dispatch(scope: Scope, receive: Receive, send: Send) -> None:
        target = api if scope["type"] == "lifespan" or _is_api(scope.get("path")) else static
        await target(scope, receive, send)

    return dispatch


def _is_api(path: object) -> bool:
    """Whether a request path belongs to the API rather than to the bundle."""
    return isinstance(path, str) and (path.startswith(_API_ROOT) or path == _API_ROOT.rstrip("/"))
