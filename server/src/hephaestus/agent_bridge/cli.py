"""``heph agent`` — the interactive agent verb over the private bridge.

Registered on the engine CLI through the same dispatch pattern as
``hephaestus.core.cli_render`` (:func:`add_subparsers`), so importing the engine
CLI never pulls the sidecar/Node stack in unless ``heph agent`` actually runs.

What the verb does (architecture §4.1/§5, digest §1/§6):

* spawns and supervises the packaged Node sidecar through
  :class:`~hephaestus.agent_bridge.app.BridgeRuntime` (minimal environment; only
  credential variables named in the provider config's allowlist are forwarded);
* creates or resumes one Pi session for the project and runs a prompt REPL;
* renders the **normalized Hephaestus event stream** — streamed text deltas,
  one-line tool chips, and save-to-file notices for returned images. The private
  bridge frames are never printed: the renderer only ever sees
  ``{run_id, seq, kind, tool_call_id?, payload?}`` records;
* answers ``ask_user`` questions interactively (numbered options, optional free
  text) and delivers the selection back through the bridge;
* cancels the in-flight run on Ctrl-C (the run's own abort controller — other
  sessions are untouched); a second Ctrl-C at an idle prompt exits.

Provider configuration is explicit and app-owned. ``--providers FILE`` (or
``HEPHAESTUS_AGENT_PROVIDERS``, else ``<project>/.heph/providers.json``) holds::

    {"providers": [ …runtime.configure provider specs… ],
     "credential_allowlist": ["ANTHROPIC_API_KEY"],
     "auth_source": "/home/you/.pi/agent/auth.json"}

Only allowlisted variables are read from the environment and handed to the
sidecar; an ambient key that is not named is never forwarded.

``auth_source`` is optional and opt-in: when present, ``<project>/.heph/agent/
auth.json`` is made a **symlink** to it so providers of kind ``pi_native`` (Pi's
built-in catalog, e.g. ``openai-codex``) can use Pi's own stored OAuth
credential. Absent it, nothing outside the project is visible to the sidecar.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any, Protocol, TextIO, cast

from hephaestus.core.project_store.layout import find_project_root
from opstore.types import JSONValue

from .app import AskUserAnswerer, AuthLinkError, BridgeRuntime, PromptResult
from .cad_ops import option_display, option_label
from .client_mode import ClientModeError, ServerAgentClient, attach_client
from .sidecar import SidecarError
from .supervisor import SupervisorError

__all__ = [
    "PROVIDER_CONFIG_ENV",
    "PROVIDER_CONFIG_RELPATH",
    "AgentConsole",
    "AgentDriver",
    "ProviderConfig",
    "add_subparsers",
    "load_provider_config",
    "main",
    "resolve_config_path",
]

#: Default location of the provider config inside a project.
PROVIDER_CONFIG_RELPATH = Path(".heph") / "providers.json"

#: The standing override for that location, honoured by every verb that opens a
#: provider config (``heph agent`` and ``heph serve --web``).
PROVIDER_CONFIG_ENV = "HEPHAESTUS_AGENT_PROVIDERS"

#: Where image blocks returned by tools are written for the operator to open.
IMAGE_DIR_RELPATH = Path(".heph") / "agent_images"

_PROFILES = ("orchestrator", "part", "quick_edit")


class ConfigError(Exception):
    """A user-facing configuration problem (missing/invalid provider config)."""


class AgentDriver(Protocol):
    """What the REPL needs from whichever runtime is driving the session.

    Two implementations, one loop: :class:`~hephaestus.agent_bridge.app.
    BridgeRuntime` in-process, and :class:`~hephaestus.agent_bridge.client_mode.
    ServerAgentClient` against the process that owns the leases (§2.1). The
    Protocol is what keeps the second from becoming a second renderer.
    """

    def new_run_id(self) -> str: ...

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = ...,
        answerer: AskUserAnswerer | None = ...,
        on_event: Callable[[dict[str, Any]], None] | None = ...,
        timeout: float | None = ...,
    ) -> PromptResult: ...

    def cancel(self, run_id: str) -> None: ...


@dataclass(frozen=True)
class ProviderConfig:
    """Provider specs plus the credential variables approved for forwarding."""

    providers: list[dict[str, Any]]
    credential_allowlist: tuple[str, ...] = ()
    #: Optional absolute path to an existing Pi ``auth.json``; when set the
    #: supervisor symlinks it into ``<project>/.heph/agent/auth.json`` so
    #: ``pi_native`` providers can use Pi's own stored (OAuth) credential.
    auth_source: Path | None = None

    def credentials(self, env: dict[str, str] | None = None) -> dict[str, str]:
        """Values for the allowlisted credential names present in the environment."""
        source = os.environ if env is None else env
        return {name: source[name] for name in self.credential_allowlist if name in source}


def load_provider_config(path: Path) -> ProviderConfig:
    """Parse a provider config file; raises :class:`ConfigError` when unusable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read provider config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"provider config {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"provider config {path} must be a JSON object")
    obj = cast("dict[str, Any]", raw)
    providers_raw = obj.get("providers")
    if not isinstance(providers_raw, list) or not providers_raw:
        raise ConfigError(f"provider config {path} needs a non-empty 'providers' array")
    providers = [cast("dict[str, Any]", p) for p in cast("list[Any]", providers_raw)]
    allow_raw = obj.get("credential_allowlist", [])
    allowlist: tuple[str, ...] = ()
    if isinstance(allow_raw, list):
        allowlist = tuple(str(name) for name in cast("list[Any]", allow_raw))
    auth_raw = obj.get("auth_source")
    auth_source = Path(str(auth_raw)).expanduser() if auth_raw else None
    return ProviderConfig(
        providers=providers,
        credential_allowlist=allowlist,
        auth_source=auth_source,
    )


def resolve_config_path(project_root: Path, explicit: str | None = None) -> Path:
    """Where this process looks for ``providers.json`` (`--providers`, env, default).

    Public because ``heph serve --web`` looks in exactly the same place, and
    §23.0's attach capability has to *report* the path it checked to a browser
    that cannot see stderr. Two derivations of "which file is the provider
    config" would be two answers the moment one of them grew a case, which is
    the duplication mission rule 6 forbids.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    from_env = os.environ.get(PROVIDER_CONFIG_ENV)
    if from_env:
        return Path(from_env).expanduser()
    return project_root / PROVIDER_CONFIG_RELPATH


# --------------------------------------------------------------------------
# rendering


@dataclass
class AgentConsole:
    """Renders one run's normalized event stream to a terminal.

    Deliberately narrow: it consumes only the public event vocabulary, so no
    bridge frame, Pi session record, or provider payload can reach the operator.
    """

    image_dir: Path
    out: Any = field(default_factory=lambda: sys.stdout)
    #: Files written for ``image`` events during this console's lifetime.
    saved_images: list[Path] = field(default_factory=list[Path])
    _in_text: bool = False

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def _end_text(self) -> None:
        if self._in_text:
            self._write("\n")
            self._in_text = False

    def on_event(self, event: dict[str, Any]) -> None:
        """Render one normalized event (never a raw frame)."""
        kind = str(event.get("kind", ""))
        payload_raw = event.get("payload")
        payload: dict[str, Any] = (
            cast("dict[str, Any]", payload_raw) if isinstance(payload_raw, dict) else {}
        )
        if kind == "text_delta":
            self._in_text = True
            self._write(str(payload.get("text", "")))
        elif kind == "thought":
            self._end_text()
            self._write(f"  · {payload.get('text', '')}\n")
        elif kind == "tool_call":
            self._end_text()
            name = payload.get("name", "?")
            self._write(f"  [tool] {name} {self._args(payload.get('arguments'))}\n")
        elif kind == "tool_result":
            self._end_text()
            marker = "!" if payload.get("isError") else "ok"
            name = payload.get("toolName", "?")
            self._write(f"  [{marker}] {name} {self._summary(payload.get('text'))}\n")
        elif kind == "image":
            self._end_text()
            self._write(f"  [image] {self._save_image(event, payload)}\n")
        elif kind == "question":
            self._end_text()
        elif kind == "audit":
            self._end_text()
            self._write(f"  [audit] {payload.get('event', 'event')}\n")
        elif kind == "terminal":
            self._end_text()

    def finish(self, result: PromptResult) -> None:
        """Close the streamed line and print the run's outcome."""
        self._end_text()
        self._write(f"  [run {result.status}]\n")

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _args(arguments: Any) -> str:
        if not isinstance(arguments, dict):
            return ""
        items = cast("dict[str, Any]", arguments)
        parts = [f"{k}={json.dumps(v)}" for k, v in sorted(items.items())]
        text = " ".join(parts)
        return text if len(text) <= 120 else text[:117] + "..."

    @staticmethod
    def _summary(text: Any) -> str:
        if not isinstance(text, str):
            return ""
        single = " ".join(text.split())
        return single if len(single) <= 120 else single[:117] + "..."

    def _save_image(self, event: dict[str, Any], payload: dict[str, Any]) -> str:
        data = payload.get("data")
        mime = str(payload.get("mimeType", "image/png"))
        suffix = ".png" if mime.endswith("png") else ".jpg"
        run_id = str(event.get("run_id", "run"))
        seq = int(event.get("seq", 0))
        if not isinstance(data, str) or not data:
            return f"{mime} (no inline data)"
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return f"{mime} (undecodable payload discarded)"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        path = self.image_dir / f"{run_id}-{seq}{suffix}"
        path.write_bytes(raw)
        self.saved_images.append(path)
        return f"saved {path} ({len(raw)} bytes)"


def interactive_answerer(
    console_out: TextIO | None = None, console_in: TextIO | None = None
) -> AskUserAnswerer:
    """Build an ``ask_user`` answerer that prompts the operator on a terminal.

    THE ANSWER NAMESPACE IS THE OPTION'S ``label`` (INTERFACE.md §7A.7, §19.29).
    This function used to flatten options with ``str(o)``, so an object option
    — ``_CLARIFICATION_OPTION`` is ``{label, consequence}``, which the schema
    admits alongside a bare string — was resolved to its **Python dict repr**
    and that repr became the selection the model received. The web widget sends
    the label, the MCP elicitation sends the label, and this surface sent
    ``"{'label': 'Keep 2 mm', 'consequence': '…'}"``: two surfaces answering one
    question handed the model two different values. :func:`option_label` is the
    one definition of that namespace and is shared with the MCP path, so the
    answer cannot drift again; :func:`option_display` is the one definition of
    what a human is *shown*, which is a different string on purpose.
    """
    out = console_out if console_out is not None else sys.stdout
    src = console_in if console_in is not None else sys.stdin

    def answer(params: dict[str, Any]) -> Any:
        question = str(params.get("question", ""))
        options_raw = params.get("options")
        raw = cast("list[Any]", options_raw) if isinstance(options_raw, list) else []
        options = [option_label(cast("JSONValue", o)) for o in raw]
        # §7.3: an option renders label **and** geometric consequence. The
        # numbered prompt is the CLI's rendering of the same widget, so the
        # consequence is printed here too — an operator picking between two
        # options with the consequences hidden is choosing blind.
        displayed = [option_display(cast("JSONValue", o)) for o in raw]
        # `allow_free_text` / `multi` come from the params the sidecar carries,
        # and in §2.1 client mode those params are the `question` event payload
        # (`agent/src/main.ts`) — which is why that payload carries both fields.
        allow_free_text = bool(params.get("allow_free_text", True))
        multi = bool(params.get("multi", False))
        out.write(f"\n  [question] {question}\n")
        for index, option in enumerate(displayed, start=1):
            out.write(f"    {index}) {option}\n")
        hint = "number" + ("s (comma-separated)" if multi else "")
        if allow_free_text:
            hint += " or free text"
        out.write(f"  answer ({hint}): ")
        out.flush()
        raw = src.readline()
        if not raw:
            return options[0] if options else ""
        text = raw.strip()
        selection = _resolve_selection(text, options, multi=multi, allow_free_text=allow_free_text)
        return selection

    return answer


def _resolve_selection(text: str, options: list[str], *, multi: bool, allow_free_text: bool) -> Any:
    """Map typed input onto option indices, falling back to free text."""
    tokens = [t.strip() for t in text.split(",")] if multi else [text]
    resolved: list[str] = []
    for token in tokens:
        if token.isdigit() and 1 <= int(token) <= len(options):
            resolved.append(options[int(token) - 1])
        elif token in options or allow_free_text:
            resolved.append(token)
        elif options:
            resolved.append(options[0])
    if not resolved:
        return options[0] if options else text
    return resolved if multi else resolved[0]


# --------------------------------------------------------------------------
# the verb


def _cmd_agent(args: argparse.Namespace) -> int:
    start = Path(cast("str | None", args.project) or Path.cwd()).expanduser()
    try:
        project_root = find_project_root(start)
    except Exception as exc:
        print(f"heph: not a Hephaestus project ({exc})", file=sys.stderr)
        return 2

    # INTERFACE.md §2.1: **no new flag**. If a live server already owns this
    # project's leases, this verb runs in CLIENT MODE against it rather than
    # opening a second in-process bridge — a second bridge would be two writers
    # on one Pi JSONL, which architecture.md §4.2 forbids outright. Discovery is
    # `.heph/serve.json`; a recorded-but-unreachable server refuses `session_busy`.
    try:
        client = attach_client(project_root)
    except ClientModeError as exc:
        print(f"heph: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    if client is not None:
        return _cmd_agent_client(args, project_root, client)

    config_path = resolve_config_path(project_root, cast("str | None", args.providers))
    try:
        config = load_provider_config(config_path)
    except ConfigError as exc:
        print(f"heph: {exc}", file=sys.stderr)
        print(
            "heph: write a provider config (see 'heph agent --help') or set "
            "HEPHAESTUS_AGENT_PROVIDERS",
            file=sys.stderr,
        )
        return 2

    profile = str(args.profile)
    session_name = cast("str | None", args.session)
    resume = bool(args.resume)
    console = AgentConsole(image_dir=project_root / IMAGE_DIR_RELPATH)
    answerer = interactive_answerer()

    try:
        runtime = BridgeRuntime(
            project_root=project_root,
            providers=config.providers,
            credentials=config.credentials(),
            credential_allowlist=config.credential_allowlist,
            answerer=answerer,
            auth_source=config.auth_source,
        )
    except AuthLinkError as exc:
        print(f"heph: {exc}", file=sys.stderr)
        return 2
    except SidecarError as exc:
        # The packaged sidecar is missing, tampered, or Node is absent/too old.
        # `repo_conventions.md` requires this to be a named refusal — the
        # constructor already declined to spawn anything, and there is
        # deliberately no fallback to a global `pi`/`thread-phase` to suggest.
        # The code is printed so an operator (or a CI lane) can distinguish
        # "rebuild the wheel" from "install a newer Node".
        print(f"heph: {exc.code}: {exc}", file=sys.stderr)
        return 2
    try:
        runtime.start()
    except (SupervisorError, RuntimeError) as exc:
        print(f"heph: cannot start the agent sidecar: {exc}", file=sys.stderr)
        return 1

    exit_code = 0
    try:
        session_id = runtime.create_session(
            profile,
            part=cast("str | None", args.part),
            session_id=session_name,
            resume=resume,
        )
        print(f"heph agent · project {project_root} · session {session_id} ({profile})")
        print("type a prompt, or Ctrl-D to leave; Ctrl-C cancels the running turn.")
        exit_code = _repl(runtime, session_id, console)
    except SupervisorError as exc:
        print(f"heph: bridge failure: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        runtime.close()
    return exit_code


def _cmd_agent_client(
    args: argparse.Namespace, project_root: Path, client: ServerAgentClient
) -> int:
    """The §2.1 client-mode half of ``heph agent``.

    Deliberately the *same* REPL. A session started here is the one the browser
    attaches to because there is only ever one runtime — the server's — so there
    is no event forwarding to get wrong, and no second rendering path to keep in
    step with the first.

    No provider config is read: the owning server configured the sidecar when it
    started, and re-reading providers here would suggest this process could
    change them, which it cannot.
    """
    console = AgentConsole(image_dir=project_root / IMAGE_DIR_RELPATH)
    answerer = interactive_answerer()
    exit_code = 0
    try:
        session_id = client.create_session(
            str(args.profile),
            part=cast("str | None", args.part),
            session_id=cast("str | None", args.session),
            resume=bool(args.resume),
        )
        print(
            f"heph agent · project {project_root} · session {session_id} "
            f"({args.profile}) · client of pid {client.record.pid} at {client.record.http}"
        )
        print("type a prompt, or Ctrl-D to leave; Ctrl-C cancels the running turn.")
        exit_code = _repl(client, session_id, console, answerer=answerer)
    except ClientModeError as exc:
        print(f"heph: {exc.code}: {exc.message}", file=sys.stderr)
        exit_code = 1
    finally:
        client.close()
    return exit_code


def _repl(
    runtime: AgentDriver,
    session_id: str,
    console: AgentConsole,
    *,
    answerer: AskUserAnswerer | None = None,
) -> int:
    """Prompt loop with per-run Ctrl-C cancellation.

    Written against :class:`AgentDriver` rather than against ``BridgeRuntime`` so
    the in-process runtime and the §2.1 client-mode driver share ONE loop: two
    REPLs would be two renderings of one event vocabulary, and they would drift.
    """
    while True:
        try:
            line = input("\n> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0
        prompt_text = line.strip()
        if not prompt_text:
            continue
        if prompt_text in {"/quit", "/exit"}:
            return 0
        run_id = runtime.new_run_id()
        result = _run_turn(runtime, session_id, prompt_text, run_id, console, answerer=answerer)
        if result is None:
            return 1
        console.finish(result)


def _run_turn(
    runtime: AgentDriver,
    session_id: str,
    prompt_text: str,
    run_id: str,
    console: AgentConsole,
    *,
    answerer: AskUserAnswerer | None = None,
) -> PromptResult | None:
    """Run one prompt with a SIGINT handler bound to *this* run's cancellation."""
    cancelled = threading.Event()

    def on_sigint(_signum: int, _frame: FrameType | None) -> None:
        if cancelled.is_set():
            return
        cancelled.set()
        console.out.write("\n  [cancelling run]\n")
        console.out.flush()
        runtime.cancel(run_id)

    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, on_sigint)
    try:
        return runtime.prompt(
            session_id,
            prompt_text,
            run_id=run_id,
            on_event=console.on_event,
            answerer=answerer,
        )
    except SupervisorError as exc:
        print(f"\nheph: run failed: {exc}", file=sys.stderr)
        return None
    except ClientModeError as exc:
        # Client mode: the owning server refused or went away mid-turn. Named,
        # never degraded into "the model stopped".
        print(f"\nheph: {exc.code}: {exc.message}", file=sys.stderr)
        return None
    finally:
        signal.signal(signal.SIGINT, previous)


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``agent`` verb on an existing subparser set."""
    agent = sub.add_parser(
        "agent",
        help="interactive CAD agent session (requires Node and a provider config)",
        description=(
            "Run an interactive Hephaestus agent session. Provider configuration is "
            "read from --providers, else $HEPHAESTUS_AGENT_PROVIDERS, else "
            "<project>/.heph/providers.json: "
            '{"providers": [...], "credential_allowlist": ["ANTHROPIC_API_KEY"]}. '
            "Only allowlisted environment variables are forwarded to the sidecar."
        ),
    )
    agent.add_argument(
        "--project", default=None, metavar="DIR", help="project directory (default: cwd)"
    )
    agent.add_argument(
        "--session", default=None, metavar="NAME", help="session id to create or resume"
    )
    agent.add_argument(
        "--resume", action="store_true", help="resume the named session's transcript"
    )
    agent.add_argument(
        "--profile",
        choices=list(_PROFILES),
        default="orchestrator",
        help="session profile (default: orchestrator)",
    )
    agent.add_argument(
        "--part", default=None, metavar="PART", help="bound part for a part/quick_edit session"
    )
    agent.add_argument(
        "--providers", default=None, metavar="FILE", help="provider config JSON path"
    )
    agent.set_defaults(func=_cmd_agent)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point (``python -m hephaestus.agent_bridge.cli``)."""
    parser = argparse.ArgumentParser(prog="heph")
    sub = parser.add_subparsers(dest="command", required=True)
    add_subparsers(sub)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    command = cast("Callable[[argparse.Namespace], int]", args.func)
    return int(command(args))


if __name__ == "__main__":  # pragma: no cover - manual entry
    sys.exit(main())
