# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Attaching an agent runtime to a **running** serve (``INTERFACE.md`` §23.0).

§23.0 records the finding this module answers, and it is a deadlock rather than
a missing convenience: a project with no ``providers.json`` had **no**
``BridgeRuntime``, no ``Supervisor`` and no sidecar process at all, because
``serve.py``'s ``_attach_agent`` returned ``None`` and ``attach_sessions`` was
called from one place, once, during ``serve``. Every credential route of §23 is
a relay to the sidecar, so sign-in was unreachable in exactly the zero-config
state it exists to fix, and the operator was sent back to a terminal — which is
the whole of the product review's complaint 4.

The fix is one code path, not two. This module owns the *construction* half —
resolve the config, build the ``BridgeRuntime`` over the runtime's already-open
objects, start it, and turn every failure into a **named** refusal — and
:meth:`hephaestus.http.runtime.WorkspaceRuntime.attach_agent` owns the *binding*
half. ``heph serve --web`` calls the same method at start-up that
``POST /providers/attach`` calls an hour later; there is no start-up-only branch
left to drift.

Three properties are load-bearing and are asserted by ``test_http_attach.py``
rather than merely described here:

* **A failed attach leaves the server in its prior state.** The runtime is only
  bound after ``start()`` returns, so a refusal cannot half-attach a serve.
* **A failed attach leaves no sidecar behind.** ``Supervisor.start`` fires the
  spawn hook (``runtime.configure``) *after* the child exists, so a provider
  that fails verification raises with a **live** child. Every failure path here
  closes the partially-started runtime before it re-raises. The pre-existing
  code caught the same exceptions and dropped the object on the floor, which
  orphaned that child for the life of the serve.
* **No secret enters the refusal.** §23.2 closes the list of places a provider
  secret may live, and a ``detail`` string carried to a browser is not on it.
  The values this attach is about to hand the sidecar are known here exactly, so
  the reduction is an exact-substring redaction rather than a pattern guess
  (§23.6's "reduced at the boundary" — the reduction happens where the bytes
  are).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from hephaestus.agent_bridge.app import BridgeRuntime

    from .runtime import WorkspaceRuntime

__all__ = [
    "ATTACH_CAUSES",
    "DETACHED_CAUSE",
    "DETAIL_MAX_CHARS",
    "REDACTED",
    "AgentAlreadyAttached",
    "AgentAttachState",
    "AttachRefused",
    "provider_config_path",
    "reduce_detail",
    "start_agent_runtime",
]

#: The closed cause vocabulary an unattached serve reports.
#:
#: The first six are ``INTERFACE.md`` §7A.8's list verbatim (§19 item 25): the
#: serve records why ``_attach_agent`` produced nothing instead of printing it to
#: a stderr no browser will read, and ``agent_unavailable`` carries it.
#:
#: DEVIATION, recorded rather than silently reinterpreted: the seventh,
#: ``detached``, is **not** in §7A.8's list, because §7A.8 was written when the
#: only way to have no runtime was to have started without one. §23.14 item 1
#: adds detach/re-attach to a *running* serve, and a serve whose operator
#: detached a runtime is not a serve with ``no_provider_config`` — reporting it
#: as one would be the silent reinterpretation the house rules forbid. It is
#: added here, named, and reported; §7A.8's own list is left for the amendment
#: that owns that section to extend.
ATTACH_CAUSES: Final[tuple[str, ...]] = (
    "no_provider_config",
    "provider_config_invalid",
    "node_missing",
    "node_too_old",
    "sidecar_failed",
    "auth_link_refused",
    "detached",
)

#: The seventh value above, named so no call site spells it as a literal.
DETACHED_CAUSE: Final[str] = "detached"

#: What replaces a credential value that turned up inside a failure message.
REDACTED: Final[str] = "[redacted]"

#: Bound on ``detail``. A refusal is a sentence for an operator, not a log.
DETAIL_MAX_CHARS: Final[int] = 300


@dataclass(frozen=True, slots=True)
class AgentAttachState:
    """Whether this process has an agent runtime, and — if not — **why**.

    One projection, used by both surfaces that report the fact: the
    ``POST /providers/attach`` response body and the ``data`` of §2.4's
    ``agent_unavailable`` refusal (§7A.8). Two shapes for one fact would drift
    the moment one of them gained a field.
    """

    #: Whether a session backend is bound right now.
    attached: bool
    #: The ``providers.json`` this process checks — reported even when attached,
    #: because "which file am I configured by" is the operator's first question.
    config_path: str
    #: Closed to :data:`ATTACH_CAUSES`; ``None`` exactly when attached.
    cause: str | None = None
    #: A reduced, redacted sentence. Never a credential, a token, or a
    #: provider's response body (§23.2, §23.6).
    detail: str | None = None
    #: How many times this process has successfully attached. A re-attach after
    #: a detach is a *different* state from the first attach, and a client that
    #: cannot tell them apart cannot render an honest transition.
    generation: int = 0

    def __post_init__(self) -> None:
        if self.cause is not None and self.cause not in ATTACH_CAUSES:
            raise ValueError(f"attach cause {self.cause!r} is outside the closed vocabulary")
        if self.attached is (self.cause is not None):
            raise ValueError("an attached runtime has no cause, and an unattached one has one")

    def projection(self) -> dict[str, Any]:
        """The wire shape. Absent fields are omitted, never sent as ``null``."""
        body: dict[str, Any] = {
            "attached": self.attached,
            "config_path": self.config_path,
            "generation": self.generation,
        }
        if self.cause is not None:
            body["cause"] = self.cause
        if self.detail is not None:
            body["detail"] = self.detail
        return body


class AttachRefused(Exception):
    """An attach that could not be performed, named by its closed cause."""

    def __init__(self, cause: str, config_path: Path, detail: str) -> None:
        super().__init__(f"{cause}: {detail}")
        if cause not in ATTACH_CAUSES:  # pragma: no cover - guarded at every raise
            raise ValueError(f"attach cause {cause!r} is outside the closed vocabulary")
        self.cause = cause
        self.config_path = config_path
        self.detail = detail

    def state(self, *, generation: int) -> AgentAttachState:
        """The state a serve is left in by this refusal — the prior one, named."""
        return AgentAttachState(
            attached=False,
            config_path=str(self.config_path),
            cause=self.cause,
            detail=self.detail,
            generation=generation,
        )


class AgentAlreadyAttached(Exception):
    """Attach was asked of a serve that already has a runtime.

    Refused rather than silently replaced: replacing one would kill every
    in-flight run in every session, which §23.7 makes an *explicit*, confirmed
    act (``runs_in_flight`` + ``confirm``) and never a side effect of a request
    that read as "make sure there is a runtime".
    """


def provider_config_path(project_root: Path) -> Path:
    """The ``providers.json`` this serve reads, honouring the standing override.

    Delegates to ``agent_bridge.cli`` rather than re-deriving the path: the CLI
    and the server must look in the same place or an operator's ``heph agent``
    and their browser disagree about what is configured.
    """
    from hephaestus.agent_bridge.cli import resolve_config_path

    return resolve_config_path(project_root)


def reduce_detail(exc: BaseException, secrets: Sequence[str] = ()) -> str:
    """A bounded, secret-free sentence for a failure that crosses to a browser.

    Exact-substring redaction over the values this attach was about to forward,
    **before** truncation: the threat §23.6 names is a provider's error text
    quoting back what it was sent, and the one place that value is known exactly
    is here, in the process that holds it. A pattern-matching redactor would be
    a guess about what a secret looks like; this is not.
    """
    text = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text[:DETAIL_MAX_CHARS]


def start_agent_runtime(
    runtime: WorkspaceRuntime,
    *,
    config_path: Path,
    dist_main: Path | None = None,
) -> BridgeRuntime:
    """Build and start the one agent runtime this process owns, or refuse by name.

    **The store, project store, CadOps and dispatcher are injected**, not opened
    again: two opstore handles in one process would be two ``LockManager`` owners
    over one project's ``.heph/locks/``, which is precisely what §2.1's "one
    process owns the leases" exists to prevent.

    ``dist_main`` is ``BridgeRuntime``'s own documented harness escape hatch —
    one exact entry file, bypassing sidecar resolution — threaded through so the
    attach tests can drive a real child process without Node. **No route passes
    it**: §2.3 has no route that takes a raw filesystem path, and this parameter
    is reachable only in-process.
    """
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.agent_bridge.cli import ConfigError, load_provider_config

    if not config_path.is_file():
        raise AttachRefused(
            "no_provider_config",
            config_path,
            f"no provider config at {config_path}",
        )
    try:
        config = load_provider_config(config_path)
    except ConfigError as exc:
        raise AttachRefused("provider_config_invalid", config_path, reduce_detail(exc)) from exc
    except OSError as exc:  # pragma: no cover - load_provider_config maps the common ones
        raise AttachRefused("provider_config_invalid", config_path, reduce_detail(exc)) from exc

    # Read once, here: these are the exact values about to be handed to the
    # sidecar, and therefore the exact values a failure message could quote back.
    credentials = config.credentials()
    secrets = tuple(credentials.values())

    bridge: BridgeRuntime | None = None
    try:
        bridge = BridgeRuntime(
            project_root=runtime.root,
            providers=config.providers,
            credentials=credentials,
            credential_allowlist=config.credential_allowlist,
            auth_source=config.auth_source,
            dist_main=dist_main,
            store=runtime.store,
            project_store=runtime.project_store,
            cad=runtime.cad,
            dispatcher=runtime.dispatcher,
        )
        bridge.start()
    except BaseException as exc:
        # ORPHAN-FREE, and this is the reason the clause is `BaseException` and
        # not the tidy tuple below it: `Supervisor.start` spawns the child and
        # *then* replays `runtime.configure`, so a provider that fails
        # verification — §23.7's whole subject — raises with a live sidecar. Any
        # exception at all, including a KeyboardInterrupt landing between the
        # two, has to take that child with it.
        if bridge is not None:
            with contextlib.suppress(Exception):
                bridge.close()
        cause = _cause_for(exc)
        if cause is None:
            raise
        raise AttachRefused(cause, config_path, reduce_detail(exc, secrets)) from exc
    return bridge


def _cause_for(exc: BaseException) -> str | None:
    """The closed cause for a start failure, or ``None`` for "not ours to name".

    The mapped set is exactly what ``serve.py``'s ``_attach_agent`` already
    caught — ``AuthLinkError | SidecarError | SupervisorError | RuntimeError``,
    plus ``OSError`` for a spawn that never reached the supervisor — so an
    attach refuses in precisely the cases a serve used to survive, and a serve
    that used to survive one still does.

    Anything else is re-raised unchanged rather than folded into
    ``sidecar_failed``: a refusal vocabulary that absorbs every exception stops
    being a vocabulary, and a programming error must not read to an operator as
    a provider problem.
    """
    from hephaestus.agent_bridge.app import AuthLinkError
    from hephaestus.agent_bridge.sidecar import NodeMissingError, NodeTooOldError, SidecarError
    from hephaestus.agent_bridge.supervisor import SupervisorError

    if isinstance(exc, NodeMissingError):
        return "node_missing"
    if isinstance(exc, NodeTooOldError):
        return "node_too_old"
    if isinstance(exc, AuthLinkError):
        return "auth_link_refused"
    if isinstance(exc, SidecarError | SupervisorError | OSError | RuntimeError):
        return "sidecar_failed"
    return None
