# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The credential relay between ``server/http`` and the sidecar (``INTERFACE.md`` §23).

Every credential route is a **relay to Pi**, and this module is the whole of the
translation: which routes need a sidecar, how a sidecar refusal becomes one of
§23.11's named reasons with a §2.4 status, and how a restart is applied when a
credential changes. Nothing here stores, derives, validates or transports a
secret beyond handing one value straight through on its way to
``ModelRuntime.setRuntimeApiKey`` (§23.2's second permitted place).

Two boundaries are drawn here on purpose.

**The dependency split of §23.0's table.** ``GET /providers`` and
``PUT /providers/specs`` read and write a *file* and must stay serviceable with
no sidecar — refusing those in the zero-config case is what made an earlier
draft of the section unusable in the only state it exists to fix.
:func:`credentials_or_refuse` is therefore called by the third row's routes
only, and it is the single place ``agent_unavailable`` is raised for a
credential route.

**A sidecar refusal keeps its own name.** The sidecar reduces an OAuth failure
to ``{code, http_status}`` before anything logs it (§23.6), and :func:`relay`
carries exactly those two across — never the message, which is the channel a
provider's response body would arrive on. A code the closed vocabulary does not
contain is refused as ``provider_unreachable`` rather than passed through, so a
future sidecar cannot widen this surface's vocabulary by answering with a new
string.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from hephaestus.agent_bridge.supervisor import SupervisorError

from .errors import HttpRefusal
from .providers import PROVIDER_REFUSALS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from .runtime import WorkspaceRuntime

__all__ = [
    "CREDENTIAL_STATUS_DEFAULT",
    "CredentialBackend",
    "apply_credential_change",
    "credentials_or_refuse",
    "relay",
    "relay_async",
    "runs_in_flight_or_refuse",
]

#: The status a relayed refusal takes when the sidecar named a reason but no
#: status. 409 rather than 500: these are conflicts on live credential state.
_DEFAULT_RELAY_STATUS: Final[int] = 409

#: What ``GET /providers`` reports for a provider before anything has been
#: observed about it. Health is **last observed**, never current (§23.8), and
#: "nothing has been observed" is a state with a name rather than a green dot.
CREDENTIAL_STATUS_DEFAULT: Final[dict[str, Any]] = {
    "state": "none",
    "health": "unused",
    "last_observed_at": None,
}


@runtime_checkable
class CredentialBackend(Protocol):
    """The sidecar surface the credential routes drive (``BridgeRuntime`` satisfies it).

    A Protocol rather than the concrete class for the same reason
    ``SessionBackend`` is one: the HTTP layer must be exercisable without a Node
    sidecar, and the dependency must point one way — ``server/http`` uses the
    bridge, and the bridge knows nothing of it.

    ``runtime_checkable`` so :meth:`WorkspaceRuntime.attach_sessions` can decide
    whether the backend it was handed is *also* a credential store. A session
    backend that is not one is a legitimate state — the §2.7 test double is
    exactly that — and it must leave the credential routes refusing by name
    rather than half-answering.
    """

    def provider_catalog(self) -> dict[str, Any]: ...

    def provider_status(self) -> list[dict[str, Any]]: ...

    def credential_status(self, provider_id: str) -> dict[str, Any]: ...

    def set_api_key(self, provider_id: str, key: str, *, scope: str) -> dict[str, Any]: ...

    def sign_out(self, provider_id: str) -> dict[str, Any]: ...

    def login_begin(self, provider_id: str, flow_type: str) -> dict[str, Any]: ...

    def login_status(self, provider_id: str) -> dict[str, Any]: ...

    def login_complete(self, provider_id: str, text: str) -> dict[str, Any]: ...

    def login_cancel(self, provider_id: str) -> dict[str, Any]: ...

    def live_run_ids(self) -> list[str]: ...

    def restart(self, *, reason: str = ...) -> None: ...


def credentials_or_refuse(runtime: WorkspaceRuntime) -> CredentialBackend:
    """The attached credential backend, or ``503 agent_unavailable`` **by name**.

    §23.0's third row and only that row: ``GET /providers/catalog`` and every
    ``auth/*`` route need a sidecar, because Pi is the credential store. The
    first two rows deliberately do not come through here — a serve with no
    ``providers.json`` must still be able to read and write one, or the section
    cannot be used in the state it exists to fix.
    """
    backend = runtime.credentials
    if backend is None:
        state = runtime.agent_attach_state()
        raise HttpRefusal(
            503,
            "agent_unavailable",
            "this credential route is a relay to the agent runtime, and this server has "
            "none attached; write provider specs and attach one (POST /providers/attach) "
            "first",
            data=state.projection() if state is not None else None,
        )
    return backend


def relay(backend_call: Callable[[], dict[str, Any]], *, provider_id: str) -> dict[str, Any]:
    """Run a bridge credential call, turning a sidecar refusal into a named one.

    The sidecar's error ``data`` carries ``{code, http_status}`` and **no
    message** (§23.6): the reduction happens where the bytes are, in the process
    that holds them, because the framed JSON-RPC channel this call rides is not
    the only channel — the sidecar's stderr is a second, independent pipe. This
    function therefore constructs its own operator-facing sentence from the
    code, and never echoes what came back.
    """
    try:
        return backend_call()
    except SupervisorError as exc:
        code, status = _reason_of(exc)
        raise HttpRefusal(
            status,
            code,
            _MESSAGES.get(code, f"the provider refused: {code}"),
            data={"provider_id": provider_id},
        ) from exc


async def relay_async(
    backend_call: Callable[[], dict[str, Any]], *, provider_id: str
) -> dict[str, Any]:
    """:func:`relay`, off the event loop.

    Every call below this boundary is a **blocking** request to another process
    over a pipe. Running one on the event loop would stall every other request
    the serve is handling — including the ``GET /events`` socket, which is the
    one surface an operator is watching while they sign in. The credential
    routes are not hot, so this costs a thread and buys a serve that does not
    freeze mid-login.
    """
    return await asyncio.to_thread(relay, backend_call, provider_id=provider_id)


def _reason_of(exc: SupervisorError) -> tuple[str, int]:
    """The named reason and status inside a sidecar error, or a safe default.

    A code outside §23.11's closed vocabulary is **not** passed through: it
    becomes ``provider_unreachable``. A vocabulary a downstream process can add
    members to by answering with a new string is not closed, and the whole value
    of a closed vocabulary is that it is testable by enumeration.
    """
    data = exc.error.get("data")
    if isinstance(data, dict):
        fields: dict[str, Any] = {str(k): v for k, v in data.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        code = fields.get("code")
        status = fields.get("http_status")
        if isinstance(code, str) and code in PROVIDER_REFUSALS:
            return code, int(status) if isinstance(status, int) else _DEFAULT_RELAY_STATUS
    return "provider_unreachable", 502


#: One sentence per reason, written here rather than at a call site so a refusal
#: cannot acquire a bespoke phrasing per route (§23.14 item 15's rule, applied
#: to the server half of the same vocabulary).
_MESSAGES: Final[dict[str, str]] = {
    "authorization_expired": "that authorization is no longer valid; begin the sign-in again",
    "authorization_input_malformed": (
        "that does not look like a redirect URL, a code#state pair, or an authorization code"
    ),
    "authorization_state_mismatch": (
        "the authorization did not match the request this server started; nothing was changed"
    ),
    "credential_expired": "the stored credential has expired; sign in again",
    "credential_rejected": "the provider rejected the credential",
    "login_already_in_progress": "a sign-in for this provider is already under way",
    "model_unknown": "the provider does not offer that model",
    "provider_rate_limited": "the provider is rate limiting this account",
    "provider_unknown": "no such provider",
    "provider_unreachable": "the provider could not be reached",
    "unsupported_auth_type": "the provider does not offer that sign-in flow",
}


def runs_in_flight_or_refuse(
    backend: CredentialBackend, *, confirm: bool, action: str
) -> list[str]:
    """Refuse ``409 runs_in_flight`` unless the operator confirmed (§23.7).

    **The cost is real and is surfaced, not swallowed.** Applying a credential
    restarts the sidecar, and a restart kills every in-flight run in every
    session. The refusal lists the run ids so the dialog can name the count; a
    credential change is not a hot swap and the UI never implies it is.
    """
    live = backend.live_run_ids()
    if live and not confirm:
        raise HttpRefusal(
            409,
            "runs_in_flight",
            f"{action} restarts the agent runtime, which ends {len(live)} run(s) now in "
            "flight; re-send with confirm:true to accept that",
            data={"run_ids": live, "count": len(live)},
        )
    return live


async def apply_credential_change(runtime: WorkspaceRuntime, backend: CredentialBackend) -> None:
    """Make a credential change take effect (§23.7's attach-or-restart).

    ``runtime.configure`` runs once per sidecar process, so a credential change
    **restarts** the sidecar with the spawn hook replaying the new configure.
    *Rejected:* making ``configure`` idempotently re-runnable — that would be a
    second configure path obliged to stay behaviourally identical to the first
    forever, when the restart path already exists and is already exercised.

    **Where the other half of §23.7's sentence lives, stated so this does not
    read as a missing branch.** §23.7 says a credential change "attaches a
    runtime if there is none and otherwise restarts". This function is only ever
    reached with one, because every route that calls it went through
    :func:`credentials_or_refuse` first — §23.0's third row makes a credential
    mutation a relay to Pi, and there is nothing to relay to without a sidecar.
    The attach half is ``POST /providers/attach``, which the panel offers
    exactly when the attach projection says nothing is attached. Two operator
    acts rather than one implicit one: attaching starts a process, and §23.0
    made that its own route precisely so it is not a side effect of something
    that reads as "save my key".

    The restart goes through the runtime's own single spawn thread, because the
    orphan-free death signal is bound to the **spawning thread** and a pooled
    worker's exit would kill a perfectly healthy sidecar (see
    ``WorkspaceRuntime.spawn_executor``).
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        runtime.spawn_executor(), lambda: backend.restart(reason="credentials")
    )
