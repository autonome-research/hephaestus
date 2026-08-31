# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Provider sign-in, local first (``INTERFACE.md`` §23; Stages 10B and 10C).

This module owns everything about a provider credential that is **not** the
credential: the ``providers.json`` projection and its spec-only writer, the
closed status axes, the symlink guard, the discovery offer, the adoption record,
and the named refusal for each way any of it can fail. The secret itself never
passes through here — §23.2 closes the list of places one may live to Pi's
``auth.json``, the serving process's heap en route to ``runtime.configure``, and
the sidecar's heap, and this module is on none of them.

Four properties are load-bearing, each asserted by ``test_http_providers.py`` /
``test_provider_discovery.py`` rather than merely described here:

* **The read side returns no credential material at all** (§23.8) — not masked,
  not truncated, not four characters. :func:`providers_projection` builds its
  body out of specs, variable *names*, paths and file modes; there is no branch
  in it that can reach a secret, which is what makes §23.13's "a total
  compromise of the page is an escalation to *use*, never to *exfiltrate*" true
  rather than aspirational.
* **`credential_allowlist` and `auth_source` are not web-writable** (§23.6).
  They compose into an arbitrary-environment-variable-to-arbitrary-host
  primitive, so :func:`validate_spec_write` refuses a body carrying either **by
  name** — ``allowlist_not_web_writable`` — before it looks at anything else,
  and :func:`write_specs` preserves the on-disk values rather than accepting
  submitted ones.
* **Everything this module writes is `0600`, created private** (§23.2), through
  ``write_private``; a file the *operator* hand-authored has its mode
  **reported, never changed**.
* **No credential path outside ``<project>/.heph`` is read except on the two
  routes that are allowed to** (§23.5, G10C's Tier 1). That is not a claim about
  the code's shape: every such read goes through :func:`read_outside_project`,
  which records it, and the test asserts the recorded reasons.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import stat
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast
from urllib.parse import urlsplit

from hephaestus.agent_bridge.serve_record import write_private

from .errors import HttpRefusal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

__all__ = [
    "ADOPTION_KINDS",
    "AUTH_FLOW_TYPES",
    "AUTH_HEALTH",
    "AUTH_SOURCES",
    "CREDENTIAL_READ_REASONS",
    "CREDENTIAL_SCOPES",
    "DISCOVERY_MAX_OFFERS",
    "DISCOVERY_TTL_SECONDS",
    "PROVIDER_KINDS",
    "PROVIDER_REFUSALS",
    "CredentialRead",
    "DiscoveryOffer",
    "DiscoveryRegistry",
    "ProvidersFile",
    "acknowledge_hosts",
    "adopt_offer",
    "credential_reads",
    "discover_sources",
    "guard_unlinked",
    "is_loopback_host",
    "looks_like_path",
    "loopback_or_refuse",
    "provider_specs_of",
    "providers_projection",
    "read_outside_project",
    "read_providers_file",
    "record_credential_source",
    "reset_credential_reads",
    "unlink_auth_source",
    "validate_spec_write",
    "write_specs",
]

# --------------------------------------------------------------------------
# closed vocabularies (§23.1, §23.8, §23.11)
# --------------------------------------------------------------------------

#: The four provider kinds the runtime has (§23.1). §23 "supports all three
#: mechanisms and adds no fourth" — the list is the sidecar's ``ProviderKind``
#: and is repeated here only so a spec write can be refused before it reaches a
#: sidecar that may not exist yet.
PROVIDER_KINDS: Final[tuple[str, ...]] = ("anthropic", "openai_compatible", "local", "pi_native")

#: §23.2's persistence decision, which **has no default**: omitting it is
#: refused ``credential_scope_required`` rather than defaulted, because a
#: defaulted secret-persistence decision is the single most consequential
#: default a local tool can have.
CREDENTIAL_SCOPES: Final[tuple[str, ...]] = ("serve", "project")

#: §23.8 axis 1 — *what would I have to change to change this?*
AUTH_SOURCES: Final[tuple[str, ...]] = ("none", "env", "serve", "project", "linked")

#: §23.8 axis 2 — *does it work?* Never collapsed into axis 1, and always **last
#: observed** rather than current: there is no background probe (§15.41).
AUTH_HEALTH: Final[tuple[str, ...]] = (
    "unused",
    "accepted",
    "rejected",
    "expired",
    "unreachable",
    "rate_limited",
)

#: §23.4's two mechanically distinct subscription flows. Both exist in the
#: pinned dependency; §23 supports both and adds neither.
AUTH_FLOW_TYPES: Final[tuple[str, ...]] = ("device_code", "authorize_url")

#: What §23.5's offer may enumerate. Closed, because §19's rule that a closed
#: list may not silently acquire members applies to this one too.
ADOPTION_KINDS: Final[tuple[str, ...]] = ("pi_auth", "providers_json", "local_endpoint")

#: Every refusal §23.11 introduces, plus the engine codes it reuses. Enumerated
#: so ``test_http_providers.py`` can test the vocabulary **by enumeration** and a
#: reason cannot arrive without a status, a test, and a copy string.
PROVIDER_REFUSALS: Final[tuple[str, ...]] = (
    "agent_unavailable",
    "allowlist_not_web_writable",
    "auth_source_linked",
    "authorization_expired",
    "authorization_input_malformed",
    "authorization_state_mismatch",
    "credential_expired",
    "credential_not_allowlisted",
    "credential_rejected",
    "credential_scope_required",
    "discovery_source_unknown",
    "egress_not_acknowledged",
    "endpoint_not_loopback",
    "login_already_in_progress",
    "model_unknown",
    "not_loopback",
    "path_not_web_writable",
    "provider_not_authenticated",
    "provider_rate_limited",
    "provider_unknown",
    "provider_unreachable",
    "runs_in_flight",
    "unsupported_auth_type",
)

#: Why a path outside ``<project>/.heph`` was opened. Closed: G10C's Tier 1
#: clause is *"no credential path outside `<project>/.heph` is read unless
#: `providers.json` names it or the adoption request named it"*, and a closed
#: reason set is what turns that sentence into an assertion.
CREDENTIAL_READ_REASONS: Final[tuple[str, ...]] = ("discover", "adopt", "config_auth_source")

#: Offers are handles, not leases: they expire so a page cannot hold one across
#: a session and adopt a file the operator has since moved.
DISCOVERY_TTL_SECONDS: Final[float] = 900.0

#: Bound on the live offer table. A discovery route that grew memory per call
#: would be a denial-of-service primitive on a loopback listener.
DISCOVERY_MAX_OFFERS: Final[int] = 64

#: Loopback candidates probed by :func:`discover_sources` for a local
#: OpenAI-compatible endpoint. **Operator-supplied**, comma-separated; there is
#: no built-in list of ports to knock on, because a tool that scans the
#: operator's own machine unasked is the shape §15.41 refuses.
LOCAL_ENDPOINT_ENV: Final[str] = "HEPHAESTUS_LOCAL_ENDPOINTS"

#: Where a Pi installation keeps its app-owned credential file. Read only by
#: :func:`discover_sources` and only on the explicit route.
PI_AUTH_RELPATH: Final[Path] = Path(".pi") / "agent" / "auth.json"

#: The name of the providers file, wherever it is found.
PROVIDERS_FILE_NAME: Final[str] = "providers.json"

_PRIVATE_MODE: Final[int] = 0o600


# --------------------------------------------------------------------------
# the credential-read ledger (§23.5, G10C Tier 1)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CredentialRead:
    """One read of a credential-bearing path outside the project."""

    path: str
    reason: str
    at: float


_READS: list[CredentialRead] = []


def record_credential_read(path: Path, reason: str) -> None:
    """Record that a path outside the project was opened, and why."""
    if reason not in CREDENTIAL_READ_REASONS:  # pragma: no cover - guarded at call sites
        raise ValueError(f"credential read reason {reason!r} is outside the closed vocabulary")
    _READS.append(CredentialRead(path=str(path), reason=reason, at=time.time()))


def credential_reads() -> tuple[CredentialRead, ...]:
    """Every recorded read, oldest first. The G10C Tier 1 assertion reads this."""
    return tuple(_READS)


def reset_credential_reads() -> None:
    """Clear the ledger (tests only; a serve never needs to forget)."""
    _READS.clear()


def read_outside_project(path: Path, reason: str) -> str | None:
    """Read a credential-bearing file outside the project, recording the read.

    **The one door.** Every read of a path the project does not own goes through
    here, so G10C's *"no credential path outside `<project>/.heph` is read
    unless…"* is a property a test can check against the ledger rather than a
    claim about how carefully the module was written. Returns ``None`` when the
    file is absent or unreadable — a missing source is not an error, it is
    simply not an offer.
    """
    record_credential_read(path, reason)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# --------------------------------------------------------------------------
# endpoints (§23.3)
# --------------------------------------------------------------------------


def is_loopback_host(host: str) -> bool:
    """Whether ``host`` is a loopback **literal** or the literal ``localhost``.

    §23.3: *"A hostname is refused ``endpoint_not_loopback`` — a name can
    re-resolve between the check and the request, and a check a name defeats is
    decoration."* ``localhost`` is the single named exception the spec grants,
    and it is granted by exact match rather than by resolution.
    """
    text = host.strip().strip("[]").lower()
    if not text:
        return False
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _host_of(base_url: str) -> str:
    parsed = urlsplit(base_url if "//" in base_url else f"//{base_url}")
    return parsed.hostname or ""


def loopback_or_refuse(bind_host: str) -> None:
    """The route-level ``not_loopback`` precondition (§23.6), checked per route.

    §15.6 already says the serve is loopback-only; §23 re-checks it **at the
    route** on the §2.6 pattern, because a refusal a future configuration change
    could quietly contradict is worse than no refusal — a reader stops looking.
    """
    if not is_loopback_host(bind_host):
        raise HttpRefusal(
            403,
            "not_loopback",
            f"provider routes are served on loopback only; this serve is bound to {bind_host}",
            data={"bind_host": bind_host},
        )


# --------------------------------------------------------------------------
# providers.json
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProvidersFile:
    """The parsed ``providers.json``, plus how the file itself is stored.

    Parsed permissively and reported exactly: an operator hand-authors this file
    and a workspace that refused to *read* a file it can describe would send
    them back to the terminal, which is the whole of complaint 4.
    """

    path: Path
    exists: bool
    providers: tuple[dict[str, Any], ...] = ()
    credential_allowlist: tuple[str, ...] = ()
    auth_source: str | None = None
    egress_acknowledged: tuple[dict[str, Any], ...] = ()
    adopted_sources: tuple[dict[str, Any], ...] = ()
    credential_sources: tuple[dict[str, Any], ...] = ()
    #: Everything else the operator wrote, preserved verbatim across a write.
    extra: dict[str, Any] = field(default_factory=dict[str, Any])
    #: ``"0600"``-style, or ``None`` when the file does not exist.
    file_mode: str | None = None
    malformed: bool = False

    @property
    def mode_is_private(self) -> bool:
        return self.file_mode == "0600"

    def acknowledged_hosts(self) -> frozenset[str]:
        return frozenset(
            str(row.get("host", "")).lower() for row in self.egress_acknowledged if row.get("host")
        )

    def document(self) -> dict[str, Any]:
        """The file's JSON, rebuilt. Unknown members ride through unchanged."""
        body: dict[str, Any] = dict(self.extra)
        body["providers"] = [dict(spec) for spec in self.providers]
        if self.credential_allowlist:
            body["credential_allowlist"] = list(self.credential_allowlist)
        if self.auth_source is not None:
            body["auth_source"] = self.auth_source
        if self.egress_acknowledged:
            body["egress_acknowledged"] = [dict(row) for row in self.egress_acknowledged]
        if self.adopted_sources:
            body["adopted_sources"] = [dict(row) for row in self.adopted_sources]
        if self.credential_sources:
            body["credential_sources"] = [dict(row) for row in self.credential_sources]
        return body


def _obj(value: Any) -> dict[str, Any]:
    """Narrow a parsed-JSON value to an object, or an empty one.

    ``json.loads`` answers ``Any``, and an ``isinstance`` narrowing leaves
    pyright with ``dict[Unknown, Unknown]``. One cast here beats one at each of
    the dozen places this module reads an operator-authored file, and it is the
    same idiom ``project_projections`` and ``git_projection`` already use.
    """
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _mode_of(path: Path) -> str | None:
    try:
        return f"0{stat.S_IMODE(path.stat().st_mode):o}"
    except OSError:
        return None


def _dicts(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    rows: list[dict[str, Any]] = []
    for item in cast("list[Any]", value):
        if isinstance(item, dict):
            rows.append(_obj(item))
    return tuple(rows)


def read_providers_file(path: Path) -> ProvidersFile:
    """Read and project ``providers.json``; a malformed file is *reported*.

    ``load_provider_config`` refuses a malformed file, and it is right to — it
    is about to hand the contents to a sidecar. This projection is for a panel
    that has to *render* the problem, so it degrades to
    ``malformed=True`` with the mode still reported instead of raising.
    """
    if not path.is_file():
        return ProvidersFile(path=path, exists=False)
    mode = _mode_of(path)
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ProvidersFile(path=path, exists=True, file_mode=mode, malformed=True)
    if not isinstance(raw, dict):
        return ProvidersFile(path=path, exists=True, file_mode=mode, malformed=True)
    doc = _obj(raw)
    known = {
        "providers",
        "credential_allowlist",
        "auth_source",
        "egress_acknowledged",
        "adopted_sources",
        "credential_sources",
    }
    allow_raw = doc.get("credential_allowlist")
    allowlist = (
        tuple(str(name) for name in cast("list[Any]", allow_raw))
        if isinstance(allow_raw, list)
        else ()
    )
    auth_raw = doc.get("auth_source")
    return ProvidersFile(
        path=path,
        exists=True,
        providers=_dicts(doc.get("providers")),
        credential_allowlist=allowlist,
        auth_source=str(auth_raw) if isinstance(auth_raw, str) and auth_raw else None,
        egress_acknowledged=_dicts(doc.get("egress_acknowledged")),
        adopted_sources=_dicts(doc.get("adopted_sources")),
        credential_sources=_dicts(doc.get("credential_sources")),
        extra={k: v for k, v in doc.items() if k not in known},
        file_mode=mode,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_document(path: Path, document: dict[str, Any]) -> None:
    """Persist ``providers.json`` at ``0600``, **created** private (§23.2).

    Never ``chmod``'ed after the fact: the window between written and chmod'ed
    is exactly when another local user could open it. A file the operator
    hand-authored keeps whatever mode they gave it until *we* rewrite it, and
    the panel reports the mode rather than silently changing it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    write_private(path, json.dumps(document, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# the spec-only write (§23.6, §23.14 item 7)
# --------------------------------------------------------------------------

#: The two fields whose presence in a request body is refused **by name**. They
#: are read-only projections; §23.6 explains at length why the two compose into
#: an exfiltration primitive, and §23.5 lists exactly this as something the
#: implementation must demonstrate it cannot perform.
FORBIDDEN_SPEC_FIELDS: Final[tuple[str, ...]] = ("credential_allowlist", "auth_source")

#: Keys a *provider spec* may carry. Closed, so a spec cannot smuggle a field
#: the runtime would honour and this layer never looked at.
SPEC_FIELDS: Final[frozenset[str]] = frozenset(
    {"id", "kind", "name", "baseUrl", "credential", "models"}
)

#: Keys a model entry may carry (``runtime.ts``'s ``ProviderModelSpec`` /
#: ``PiNativeModelSpec``).
MODEL_FIELDS: Final[frozenset[str]] = frozenset(
    {"id", "name", "contextWindow", "maxTokens", "input", "reasoning"}
)


def _refuse(status: int, reason: str, message: str, **data: Any) -> HttpRefusal:
    return HttpRefusal(status, reason, message, data=data or None)


def validate_spec_write(body: dict[str, Any], current: ProvidersFile) -> list[dict[str, Any]]:
    """Validate a ``PUT /providers/specs`` body; return the specs to persist.

    The order of the checks is itself the contract. The allowlist refusal comes
    **first**, before shape validation, so a body that carries both a malformed
    spec and a ``credential_allowlist`` is refused for the allowlist — the
    reason an operator (or a reviewer reading a log) needs to see is the one
    about the exfiltration primitive, not the one about a missing field.
    """
    present = [name for name in FORBIDDEN_SPEC_FIELDS if name in body]
    if present:
        raise _refuse(
            400,
            "allowlist_not_web_writable",
            "credential_allowlist and auth_source are read-only projections and are "
            "prepared outside the workspace; this route writes provider specs only",
            fields=present,
        )
    raw = body.get("providers")
    if not isinstance(raw, list) or not raw:
        raise _refuse(400, "invalid_params", "providers must be a non-empty array of specs")
    acknowledged = set(current.acknowledged_hosts())
    for host in acknowledge_hosts(body):
        acknowledged.add(host)
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(cast("list[Any]", raw)):
        if not isinstance(item, dict):
            raise _refuse(400, "invalid_params", f"providers[{index}] must be an object")
        spec = _validate_spec(
            _obj(item),
            index=index,
            allowlist=current.credential_allowlist,
            acknowledged=acknowledged,
        )
        if spec["id"] in seen:
            raise _refuse(400, "invalid_params", f"duplicate provider id {spec['id']!r}")
        seen.add(str(spec["id"]))
        specs.append(spec)
    return specs


def _validate_spec(
    spec: dict[str, Any],
    *,
    index: int,
    allowlist: Sequence[str],
    acknowledged: set[str],
) -> dict[str, Any]:
    unexpected = sorted(set(spec) - SPEC_FIELDS)
    if unexpected:
        # A path under ANY key is its own refusal (§23.6): a client-supplied
        # filesystem path is what turns a credential route into a traversal
        # primitive, and it must not degrade to `invalid_params`.
        if any(looks_like_path(spec[name]) for name in unexpected):
            raise _refuse(
                400,
                "path_not_web_writable",
                "no provider route accepts a filesystem path in a request body",
                fields=unexpected,
            )
        raise _refuse(
            400, "invalid_params", f"providers[{index}] has unknown fields", fields=unexpected
        )
    provider_id = spec.get("id")
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise _refuse(400, "invalid_params", f"providers[{index}].id must be a non-empty string")
    kind = spec.get("kind")
    if kind not in PROVIDER_KINDS:
        raise _refuse(
            400,
            "invalid_params",
            f"providers[{index}].kind must be one of {', '.join(PROVIDER_KINDS)}",
            kinds=list(PROVIDER_KINDS),
        )
    models = _validate_models(spec.get("models"), index=index)
    out: dict[str, Any] = {"id": provider_id, "kind": kind, "models": models}
    name = spec.get("name")
    if isinstance(name, str) and name:
        out["name"] = name
    credential = spec.get("credential")
    if credential is not None:
        if not isinstance(credential, str) or not credential:
            raise _refuse(
                400, "invalid_params", f"providers[{index}].credential must be a variable name"
            )
        if credential not in allowlist:
            # The existing runtime refusal, hoisted to the route so the operator
            # learns it before a sidecar restart rather than after one. Rule 7's
            # approval mechanism is the on-disk allowlist and the web path
            # cannot add to it (§23.14 item 11).
            raise _refuse(
                400,
                "credential_not_allowlisted",
                f"provider {provider_id!r} references credential {credential!r}, which is not "
                "in this project's credential_allowlist; the allowlist is prepared outside "
                "the workspace",
                provider_id=provider_id,
                credential=credential,
                allowlist=list(allowlist),
            )
        out["credential"] = credential
    base_url = spec.get("baseUrl")
    if kind == "pi_native":
        # §23.1: pi_native is structureless on purpose — there is no field
        # through which a key could be smuggled into a subscription provider, so
        # "subscription" and "keyed" cannot be confused at the type level.
        if base_url is not None or credential is not None:
            raise _refuse(
                400,
                "invalid_params",
                f"providers[{index}] of kind pi_native carries no baseUrl and no credential",
            )
        return out
    if kind in {"openai_compatible", "local"}:
        if not isinstance(base_url, str) or not base_url:
            raise _refuse(
                400, "invalid_params", f"providers[{index}].baseUrl is required for kind {kind}"
            )
        host = _host_of(base_url)
        if kind == "local" and not is_loopback_host(host):
            raise _refuse(
                400,
                "endpoint_not_loopback",
                f"kind 'local' must resolve to a loopback literal or 'localhost'; {host!r} is "
                "a name that can re-resolve between the check and the request. A non-loopback "
                "endpoint is kind 'openai_compatible' and needs an egress acknowledgement",
                provider_id=provider_id,
                host=host,
            )
        if (
            kind == "openai_compatible"
            and not is_loopback_host(host)
            and host.lower() not in acknowledged
        ):
            raise _refuse(
                400,
                "egress_not_acknowledged",
                f"every turn against {host} sends project geometry, script source and "
                "transcripts to it; acknowledge the host by typing it before this "
                "endpoint is written",
                provider_id=provider_id,
                host=host,
            )
        out["baseUrl"] = base_url
    return out


def _validate_models(value: Any, *, index: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise _refuse(400, "invalid_params", f"providers[{index}].models must be a non-empty array")
    models: list[dict[str, Any]] = []
    for position, item in enumerate(cast("list[Any]", value)):
        if not isinstance(item, dict):
            raise _refuse(
                400, "invalid_params", f"providers[{index}].models[{position}] must be an object"
            )
        model = _obj(item)
        unexpected = sorted(set(model) - MODEL_FIELDS)
        if unexpected:
            raise _refuse(
                400,
                "invalid_params",
                f"providers[{index}].models[{position}] has unknown fields",
                fields=unexpected,
            )
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise _refuse(
                400,
                "invalid_params",
                f"providers[{index}].models[{position}].id must be a non-empty string",
            )
        models.append(model)
    return models


def looks_like_path(value: Any) -> bool:
    """Whether a submitted value reads as a filesystem path.

    Deliberately coarse and deliberately on the *refusal* side: a value that
    might be a path is refused by name rather than admitted with a shrug. It
    only ever runs over fields the closed spec vocabulary already rejected, so a
    false positive costs a caller a better-named refusal, never a working
    request.
    """
    if not isinstance(value, str) or not value:
        return False
    return value.startswith(("/", "~", "./", "../")) or "auth.json" in value


def acknowledge_hosts(body: dict[str, Any]) -> list[str]:
    """Hosts the operator re-affirmed **by typing** (§23.3)."""
    raw = body.get("acknowledge_egress")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _refuse(400, "invalid_params", "acknowledge_egress must be an array of host names")
    hosts: list[str] = []
    for item in cast("list[Any]", raw):
        if not isinstance(item, str) or not item.strip():
            raise _refuse(
                400, "invalid_params", "acknowledge_egress entries must be non-empty host names"
            )
        hosts.append(_host_of(item).lower() or item.strip().lower())
    return hosts


def write_specs(
    current: ProvidersFile, specs: Sequence[dict[str, Any]], *, acknowledge: Iterable[str] = ()
) -> ProvidersFile:
    """Persist provider specs, preserving everything the web may not write.

    ``credential_allowlist`` and ``auth_source`` are carried over from the file
    on disk, never from the request: the refusal in :func:`validate_spec_write`
    is the loud half of that rule and this is the quiet half, and both are
    needed — a route that refused the field but then dropped it on write would
    silently *delete* an operator's allowlist.
    """
    acknowledged = {
        str(row.get("host", "")).lower(): dict(row) for row in current.egress_acknowledged
    }
    for host in acknowledge:
        acknowledged[host.lower()] = {"host": host.lower(), "at": _now_iso()}
    updated = ProvidersFile(
        path=current.path,
        exists=True,
        providers=tuple(dict(spec) for spec in specs),
        credential_allowlist=current.credential_allowlist,
        auth_source=current.auth_source,
        egress_acknowledged=tuple(acknowledged.values()),
        adopted_sources=current.adopted_sources,
        credential_sources=current.credential_sources,
        extra=dict(current.extra),
        file_mode=f"0{_PRIVATE_MODE:o}",
    )
    _write_document(current.path, updated.document())
    return read_providers_file(current.path)


def record_credential_source(path: Path, *, provider_id: str, source: str) -> ProvidersFile:
    """Record on disk that a credential source is in use (§23.5's mechanical test).

    *"After any sign-in, ``providers.json`` must contain a record of every
    credential source in use. If a source works and no file names it, rule 7 has
    been broken."* This is that record, and it is why every credential mutation
    writes here even when the credential itself is held only in the serving
    process's heap.
    """
    current = read_providers_file(path)
    rows = [row for row in current.credential_sources if row.get("provider_id") != provider_id]
    if source != "none":
        rows.append({"provider_id": provider_id, "source": source, "at": _now_iso()})
    updated = ProvidersFile(
        path=path,
        exists=True,
        providers=current.providers,
        credential_allowlist=current.credential_allowlist,
        auth_source=current.auth_source,
        egress_acknowledged=current.egress_acknowledged,
        adopted_sources=current.adopted_sources,
        credential_sources=tuple(rows),
        extra=dict(current.extra),
    )
    _write_document(path, updated.document())
    return read_providers_file(path)


# --------------------------------------------------------------------------
# the symlink guard (§23.5, §23.14 item 9)
# --------------------------------------------------------------------------


def auth_json_path(project_root: Path) -> Path:
    """``<project>/.heph/agent/auth.json`` — the app-owned credential file."""
    return project_root / ".heph" / "agent" / "auth.json"


def guard_unlinked(project_root: Path) -> None:
    """Refuse every credential **write** while the auth file is a symlink.

    §23.5: ``link_auth_source``'s protection guards link *creation*, not later
    writes *through* the link. A sign-in performed while linked would write into
    the operator's own ``~/.pi/agent/auth.json`` and overwrite whatever login
    lives there. Refresh through the link is safe; login through it is not, and
    nothing in the codebase distinguished them until this.

    Sign-out is guarded by the same rule and for the same reason: unlinking is
    how you stop borrowing, and ``logout()`` through a symlink would sign the
    operator out of their own terminal.
    """
    link = auth_json_path(project_root)
    if not link.is_symlink():
        return
    try:
        target = str(link.readlink())
    except OSError:  # pragma: no cover - a symlink we just stat'ed
        target = "(unreadable)"
    raise _refuse(
        409,
        "auth_source_linked",
        f"{link} is a symlink to {target}; a credential write would land in that file. "
        "Unlink first (POST /providers/auth/unlink), which replaces the symlink with an "
        "own file and does not read, copy, or modify the target",
        link=str(link),
        target=target,
    )


def unlink_auth_source(project_root: Path) -> dict[str, Any]:
    """Replace the symlink with an own file. **Never** reads or copies the target.

    Idempotent by construction: with nothing linked it reports the state that is
    already true rather than inventing a transition.
    """
    link = auth_json_path(project_root)
    if not link.is_symlink():
        return {"unlinked": False, "target": None, "path": str(link)}
    try:
        target = str(link.readlink())
    except OSError:  # pragma: no cover
        target = None
    link.unlink()
    # An EMPTY auth file, not a copy. Copying would put a second rotating
    # refresh token beside the operator's, which is the failure mode
    # `link_auth_source`'s copy-versus-symlink reasoning already identified.
    write_private(link, "{}")
    return {"unlinked": True, "target": target, "path": str(link)}


# --------------------------------------------------------------------------
# the read projection (§23.8)
# --------------------------------------------------------------------------


def provider_specs_of(file: ProvidersFile) -> list[dict[str, Any]]:
    """The declared specs, normalized for display. **No credential material.**"""
    rows: list[dict[str, Any]] = []
    for spec in file.providers:
        models: list[dict[str, Any]] = []
        for model in _dicts(spec.get("models")):
            entry: dict[str, Any] = {
                "id": str(model.get("id", "")),
                "name": str(model.get("name", model.get("id", ""))),
            }
            # Projected only when the spec declared it. Absence is the named
            # "this model has no thinking levels" — the composer maps effort
            # from this field and must not invent one.
            if model.get("reasoning") is True:
                entry["reasoning"] = True
            models.append(entry)
        row: dict[str, Any] = {
            "id": str(spec.get("id", "")),
            "kind": str(spec.get("kind", "")),
            "name": str(spec.get("name", spec.get("id", ""))),
            "models": models,
        }
        base_url = spec.get("baseUrl")
        if isinstance(base_url, str) and base_url:
            row["base_url"] = base_url
            row["egress_host"] = _host_of(base_url)
        credential = spec.get("credential")
        if isinstance(credential, str) and credential:
            # The variable NAME. §23.2: providers.json holds specs, variable
            # names, a path and endpoint acknowledgements — it has never held a
            # secret and §23 does not make it one.
            row["credential"] = credential
        rows.append(row)
    return rows


def providers_projection(
    file: ProvidersFile,
    *,
    project_root: Path,
    attach: dict[str, Any],
    availability: dict[str, dict[str, Any]] | None = None,
    auth_states: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``GET /providers`` — everything but the secret (§23.8).

    Two axes, **never collapsed into one**: ``source`` answers *what would I
    have to change to change this?* and ``health`` answers *does it work?* A
    single "connected" light would answer neither and would claim a currency the
    design cannot keep — health is **last observed**, and the timestamp is on
    screen rather than in a footnote.
    """
    link = auth_json_path(project_root)
    linked = link.is_symlink()
    rows: list[dict[str, Any]] = []
    for spec in provider_specs_of(file):
        provider_id = spec["id"]
        verify = (availability or {}).get(provider_id, {})
        auth = (auth_states or {}).get(provider_id, {})
        default_source = "linked" if linked and spec["kind"] == "pi_native" else "none"
        source = str(auth.get("state", default_source))
        if source not in AUTH_SOURCES:  # pragma: no cover - the sidecar's vocabulary is closed too
            source = "none"
        health = str(auth.get("health", "unused"))
        if health not in AUTH_HEALTH:  # pragma: no cover
            health = "unused"
        rows.append(
            {
                **spec,
                "source": source,
                "health": health,
                "last_observed_at": auth.get("last_observed_at"),
                "available": verify.get("available"),
                "unavailable_reason": verify.get("unavailable_reason"),
            }
        )
    return {
        "status": "ok",
        "config_path": str(file.path),
        "config_exists": file.exists,
        "config_malformed": file.malformed,
        "file_mode": file.file_mode,
        "file_mode_private": file.mode_is_private,
        "credential_allowlist": list(file.credential_allowlist),
        "auth_source": file.auth_source,
        "auth_source_linked": linked,
        "egress_acknowledged": [dict(row) for row in file.egress_acknowledged],
        "adopted_sources": [dict(row) for row in file.adopted_sources],
        "credential_sources": [dict(row) for row in file.credential_sources],
        "attach": attach,
        "providers": rows,
    }


# --------------------------------------------------------------------------
# discovery and adoption — Stage 10C (§23.5, §23.6)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveryOffer:
    """One thing found on this machine, described **without its secret**.

    Four fields and nothing else (§23.5 constraint 2). The operator's ruling
    permits "a masked hint at most"; that is a **ceiling**, and §15.41's *no
    masked key tail* is stricter and stands unrelaxed — so there is no field
    here derived from a secret, not even a truncated one.
    """

    discovery_id: str
    kind: str
    provider_id: str
    model_ids: tuple[str, ...]
    source_path: str
    #: How the offer is turned into a spec. Never sent to the client — it is the
    #: server's own note about the file it may later touch.
    spec: dict[str, Any] = field(default_factory=dict[str, Any])
    minted_at: float = 0.0

    def projection(self) -> dict[str, Any]:
        return {
            "discovery_id": self.discovery_id,
            "kind": self.kind,
            "provider_id": self.provider_id,
            "model_ids": list(self.model_ids),
            "source_path": self.source_path,
        }


class DiscoveryRegistry:
    """The live offer table. Handles are opaque, server-minted and expiring.

    §23.6's *"why the handle and not the path"*: the offer already told the
    operator the path, so a path in the adopt body would add no information the
    operator lacks — it would only add a **client-chosen** path to a credential
    route, which is the one shape §23.5 forbids by name.
    """

    def __init__(self, *, ttl: float = DISCOVERY_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._offers: OrderedDict[str, DiscoveryOffer] = OrderedDict()

    def mint(
        self,
        *,
        kind: str,
        provider_id: str,
        model_ids: Sequence[str],
        source_path: str,
        spec: dict[str, Any],
    ) -> DiscoveryOffer:
        if kind not in ADOPTION_KINDS:  # pragma: no cover - guarded at call sites
            raise ValueError(f"discovery kind {kind!r} is outside the closed vocabulary")
        offer = DiscoveryOffer(
            discovery_id=f"disc-{secrets.token_urlsafe(16)}",
            kind=kind,
            provider_id=provider_id,
            model_ids=tuple(model_ids),
            source_path=source_path,
            spec=spec,
            minted_at=time.monotonic(),
        )
        self._offers[offer.discovery_id] = offer
        while len(self._offers) > DISCOVERY_MAX_OFFERS:
            self._offers.popitem(last=False)
        return offer

    def resolve(self, discovery_id: str) -> DiscoveryOffer:
        offer = self._offers.get(discovery_id)
        if offer is None or (time.monotonic() - offer.minted_at) > self._ttl:
            self._offers.pop(discovery_id, None)
            raise _refuse(
                400,
                "discovery_source_unknown",
                "that handle names no current discovery offer; run POST /providers/discover "
                "again and adopt from the fresh list",
            )
        return offer

    def clear(self) -> None:
        self._offers.clear()


def _pi_auth_candidates(env: dict[str, str], home: Path) -> list[Path]:
    """Where a Pi ``auth.json`` lives, in the order Pi itself looks."""
    candidates: list[Path] = []
    configured = env.get("PI_CONFIG_DIR")
    if configured:
        candidates.append(Path(configured).expanduser() / "agent" / "auth.json")
    candidates.append(home / PI_AUTH_RELPATH)
    return candidates


def _model_ids_beside(auth_path: Path, provider_id: str) -> tuple[str, ...]:
    """Model ids for a provider, from the **non-secret** files beside ``auth.json``.

    Pi caches its resolved catalog in ``models-store.json``; reading it is how
    the offer can say *which models* without a sidecar and without touching the
    credential. §23.5's superseded draft clause said the offer reads nothing;
    the ruling directs the opposite and says why — *"an offer that has read
    nothing cannot say what provider or which models, and is not an offer"* — so
    the read is narrowed to non-secret fields rather than struck.
    """
    for name in ("models-store.json", "models.json"):
        text = read_outside_project(auth_path.parent / name, "discover")
        if text is None:
            continue
        try:
            doc: Any = json.loads(text)
        except json.JSONDecodeError:
            continue
        ids = _model_ids_in(doc, provider_id)
        if ids:
            return ids
    return ()


def _model_ids_in(doc: Any, provider_id: str) -> tuple[str, ...]:
    if not isinstance(doc, dict):
        return ()
    body = _obj(doc)
    section: Any = body.get(provider_id)
    if section is None:
        section = _obj(body.get("providers")).get(provider_id)
    models = _obj(section).get("models")
    if not isinstance(models, list):
        return ()
    out: list[str] = []
    for entry in cast("list[Any]", models):
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict):
            ident = _obj(entry).get("id")
            if isinstance(ident, str):
                out.append(ident)
    return tuple(out)


def _discover_pi_auth(
    registry: DiscoveryRegistry, env: dict[str, str], home: Path
) -> list[DiscoveryOffer]:
    offers: list[DiscoveryOffer] = []
    for path in _pi_auth_candidates(env, home):
        text = read_outside_project(path, "discover")
        if text is None:
            continue
        try:
            doc: Any = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict):
            continue
        for provider_id, entry in sorted(_obj(doc).items()):
            if not isinstance(entry, dict):
                continue
            # ONLY the type tag is read out of a credential record. `key`,
            # `access` and `refresh` are never touched, never compared, and
            # never counted — this loop has no branch that can reach one.
            model_ids = _model_ids_beside(path, provider_id)
            offers.append(
                registry.mint(
                    kind="pi_auth",
                    provider_id=provider_id,
                    model_ids=model_ids,
                    source_path=str(path),
                    spec={
                        "auth_source": str(path),
                        "provider": {
                            "id": provider_id,
                            "kind": "pi_native",
                            "models": [{"id": mid} for mid in model_ids],
                        },
                    },
                )
            )
        break
    return offers


def _discover_providers_json(
    registry: DiscoveryRegistry, env: dict[str, str], home: Path, project_root: Path
) -> list[DiscoveryOffer]:
    offers: list[DiscoveryOffer] = []
    project_file = (project_root / ".heph" / PROVIDERS_FILE_NAME).resolve()
    candidates = (
        home / ".heph" / PROVIDERS_FILE_NAME,
        home / ".config" / "heph" / PROVIDERS_FILE_NAME,
    )
    for path in candidates:
        if path.resolve() == project_file:
            continue
        text = read_outside_project(path, "discover")
        if text is None:
            continue
        try:
            doc: Any = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict):
            continue
        for spec in _dicts(_obj(doc).get("providers")):
            provider_id = str(spec.get("id", ""))
            if not provider_id:
                continue
            model_ids = tuple(str(m.get("id", "")) for m in _dicts(spec.get("models")))
            offers.append(
                registry.mint(
                    kind="providers_json",
                    provider_id=provider_id,
                    model_ids=model_ids,
                    source_path=str(path),
                    spec={"provider": dict(spec)},
                )
            )
    return offers


def _discover_local_endpoints(
    registry: DiscoveryRegistry, env: dict[str, str]
) -> list[DiscoveryOffer]:
    """Offer an OpenAI-compatible endpoint the operator has already named.

    **Nothing is scanned.** The candidate list comes from an environment
    variable the operator sets in a terminal, and each candidate is asked for
    its own model list over loopback. A local tool that knocked on its
    operator's ports unasked is the shape §15.41 refuses, and "it is only
    loopback" is not a reason to do it.
    """
    raw = env.get(LOCAL_ENDPOINT_ENV, "")
    offers: list[DiscoveryOffer] = []
    for candidate in (part.strip() for part in raw.split(",")):
        if not candidate:
            continue
        host = _host_of(candidate)
        if not is_loopback_host(host):
            continue
        model_ids = _probe_openai_models(candidate)
        if not model_ids:
            continue
        provider_id = f"local-{host}-{urlsplit(candidate).port or 80}"
        offers.append(
            registry.mint(
                kind="local_endpoint",
                provider_id=provider_id,
                model_ids=model_ids,
                source_path=candidate,
                spec={
                    "provider": {
                        "id": provider_id,
                        "kind": "local",
                        "name": f"Local endpoint at {host}",
                        "baseUrl": candidate,
                        "models": [
                            {
                                "id": mid,
                                "name": mid,
                                "contextWindow": 32768,
                                "maxTokens": 4096,
                            }
                            for mid in model_ids
                        ],
                    }
                },
            )
        )
    return offers


def _probe_openai_models(base_url: str) -> tuple[str, ...]:
    """Ask a loopback endpoint for its model ids. No credential is sent."""
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            doc: Any = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return ()
    if not isinstance(doc, dict):
        return ()
    data = _obj(doc).get("data")
    if not isinstance(data, list):
        return ()
    ids: list[str] = []
    for entry in cast("list[Any]", data):
        if isinstance(entry, dict):
            ident = _obj(entry).get("id")
            if isinstance(ident, str) and ident:
                ids.append(ident)
    return tuple(ids)


def discover_sources(
    registry: DiscoveryRegistry,
    *,
    project_root: Path,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> list[DiscoveryOffer]:
    """Enumerate what already exists on this machine, and **offer** it (§23.5).

    Runs **only** when called: never on panel mount, never on a timer, never as
    a side effect of another route (§15.41's *no background credential probe* is
    unrelaxed, and G10C asserts it by grepping the credential-read ledger after
    every other route in the table has been exercised).

    Nothing here is configured, linked, read into a runtime, or written to
    ``providers.json``. Adoption is one explicit request naming the source.
    """
    source_env = dict(os.environ) if env is None else dict(env)
    resolved_home = Path(source_env.get("HOME", str(Path.home()))) if home is None else home
    registry.clear()
    offers = _discover_pi_auth(registry, source_env, resolved_home)
    offers.extend(_discover_providers_json(registry, source_env, resolved_home, project_root))
    offers.extend(_discover_local_endpoints(registry, source_env))
    return offers


def adopt_offer(offer: DiscoveryOffer, *, config_path: Path) -> ProvidersFile:
    """The one explicit act (§23.5 constraint 1), recorded on disk at ``0600``.

    Three things happen and no fourth: the discovered provider spec is written
    into ``providers.json``; a ``pi_auth`` adoption additionally records
    ``auth_source`` — which is the **only** way that field is ever written, and
    it is written because the operator's request named the source, not because a
    body carried a path; and an ``adopted_sources`` row names what was taken
    from where, which is what makes §23.5's distinguishing test mechanical.

    **Rule 7 is untouched.** A discovered spec naming a credential *variable*
    outside the project's on-disk allowlist is refused
    ``credential_not_allowlisted``: adoption may not add a name to the
    allowlist, so a source that needs one is a source the supervisor has to
    approve in a terminal, exactly as before.
    """
    current = read_providers_file(config_path)
    spec = _obj(offer.spec.get("provider"))
    credential = spec.get("credential")
    allowlisted = credential in current.credential_allowlist
    if isinstance(credential, str) and credential and not allowlisted:
        raise _refuse(
            400,
            "credential_not_allowlisted",
            f"the discovered provider {offer.provider_id!r} reads its key from {credential!r}, "
            "which this project's credential_allowlist does not name. Adoption cannot add a "
            "name to the allowlist — that is prepared outside the workspace",
            provider_id=offer.provider_id,
            credential=credential,
            allowlist=list(current.credential_allowlist),
        )
    if offer.kind == "adopt":  # pragma: no cover - defensive; kinds are closed
        raise ValueError("unreachable")
    # The read that the adoption request *named*. Recorded like every other.
    if offer.kind == "pi_auth":
        record_credential_read(Path(offer.source_path), "adopt")
    providers = [row for row in current.providers if row.get("id") != spec.get("id")]
    if spec:
        providers.append(spec)
    adopted = [
        row
        for row in current.adopted_sources
        if not (row.get("kind") == offer.kind and row.get("provider_id") == offer.provider_id)
    ]
    adopted.append(
        {
            "kind": offer.kind,
            "provider_id": offer.provider_id,
            "source_path": offer.source_path,
            "at": _now_iso(),
        }
    )
    auth_source = current.auth_source
    if offer.kind == "pi_auth":
        linked = offer.spec.get("auth_source")
        if isinstance(linked, str) and linked:
            auth_source = linked
    updated = ProvidersFile(
        path=config_path,
        exists=True,
        providers=tuple(providers),
        credential_allowlist=current.credential_allowlist,
        auth_source=auth_source,
        egress_acknowledged=current.egress_acknowledged,
        adopted_sources=tuple(adopted),
        credential_sources=current.credential_sources,
        extra=dict(current.extra),
    )
    _write_document(config_path, updated.document())
    return read_providers_file(config_path)
