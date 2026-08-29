// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Provider sign-in, from the browser (INTERFACE.md §23; Stages 10B and 10C).
//
// Every type here is transcribed from `http/providers.py` and
// `http/agent_credentials.py`. Three properties of this surface are
// load-bearing, and they are stated here because a caller cannot infer them
// from the shapes alone:
//
// * **No response type below has a field that could hold credential material**
//   (§23.8). Not a key, not a token, not a masked tail — "not four characters".
//   That is not an accident of the transcription: it is what §23.13 buys, and a
//   field added here would be the first step in un-buying it. A total compromise
//   of this page is an escalation to *use* and to *replace*, never to
//   *exfiltrate*, and the read side is the whole reason.
// * **The key travels in the body, never in a path, a query, or a fragment**
//   (§23.3). §2.2's reasoning about the bearer does not transfer: the bearer
//   rides in a fragment because a fragment never reaches an access log or a
//   `Referer`, but a provider key is same-origin-visible to this page, does not
//   expire with the serve, and is worth more than the token. Body or nowhere.
// * **Discovery runs only when a person asks** (§15.41, §23.5). `discover()` is
//   never called on mount, on a timer, or from another call in this module.
//   `ProvidersPanel` calls it from a click handler and nowhere else.
//
// No idempotency key is minted here. §2.3 puts every credential route in the
// keyless group: a byte-for-byte replay of a credential rotation would swallow
// a deliberate change, which is a silent security failure. `PUT /providers/specs`
// is the one exception and takes one, because it is a config mutation.

import { apiJson } from "./client";
import { uuid7 } from "./idempotency";
import type { AttachProjection } from "./attach";

/** §23.1's four kinds, collapsing to three credential mechanisms. Closed. */
export const PROVIDER_KINDS = ["anthropic", "openai_compatible", "local", "pi_native"] as const;
export type ProviderKind = (typeof PROVIDER_KINDS)[number];

/**
 * §23.2's persistence decision, which **has no default**.
 *
 * "A defaulted secret-persistence decision is the single most consequential
 * default a local tool can have, and this document declines to make it." The
 * dialog therefore renders an explicit choice with nothing preselected; sending
 * no scope is `400 credential_scope_required`.
 */
export const CREDENTIAL_SCOPES = ["serve", "project"] as const;
export type CredentialScope = (typeof CREDENTIAL_SCOPES)[number];

/** §23.8 axis 1 — *what would I have to change to change this?* */
export const AUTH_SOURCES = ["none", "env", "serve", "project", "linked"] as const;
export type AuthSource = (typeof AUTH_SOURCES)[number];

/** §23.8 axis 2 — *does it work?* **Never** collapsed into axis 1. */
export const AUTH_HEALTH = [
  "unused",
  "accepted",
  "rejected",
  "expired",
  "unreachable",
  "rate_limited",
] as const;
export type AuthHealth = (typeof AUTH_HEALTH)[number];

/** §23.4's two flows. `device_code` is the default: it opens no socket. */
export const AUTH_FLOW_TYPES = ["device_code", "authorize_url"] as const;
export type AuthFlowType = (typeof AUTH_FLOW_TYPES)[number];

/** §23.5's three discoverable source kinds (Stage 10C). Closed. */
export const DISCOVERY_KINDS = ["pi_auth", "providers_json", "local_endpoint"] as const;
export type DiscoveryKind = (typeof DISCOVERY_KINDS)[number];

/** One declared model, as `GET /providers` projects it. */
export interface ProviderModel {
  readonly id: string;
  readonly name: string;
}

/**
 * One row of `ProvidersPanel`.
 *
 * `credential` is a **variable name**, not a value — §23.2: "It holds specs,
 * *variable names*, a path, and endpoint acknowledgements. It has never held a
 * secret and §23 does not make it one."
 */
export interface ProviderRow {
  readonly id: string;
  readonly kind: string;
  readonly name: string;
  readonly models: readonly ProviderModel[];
  readonly base_url?: string;
  readonly egress_host?: string;
  readonly credential?: string;
  readonly source: AuthSource;
  readonly health: AuthHealth;
  /** §23.8: health is **last observed**, never current. Null = never observed. */
  readonly last_observed_at: number | null;
  /** §23.7's per-provider verification. `null` when no sidecar has answered. */
  readonly available: boolean | null;
  readonly unavailable_reason: string | null;
}

/** One recorded egress acknowledgement (§23.3). Permanent, and listed. */
export interface EgressAcknowledgement {
  readonly host: string;
  readonly at: string;
}

/** One recorded adoption (§23.5). This is rule 7's on-disk evidence. */
export interface AdoptedSource {
  readonly kind: string;
  readonly provider_id: string;
  readonly source_path: string;
  readonly at: string;
}

/** One recorded credential source in use (§23.5's distinguishing test). */
export interface CredentialSource {
  readonly provider_id: string;
  readonly source: string;
  readonly at: string;
}

/** `GET /providers` — everything but the secret (§23.8). */
export interface ProvidersDocument {
  readonly status: "ok";
  readonly config_path: string;
  readonly config_exists: boolean;
  readonly config_malformed: boolean;
  /** `"0600"`-style, or null when the file does not exist. */
  readonly file_mode: string | null;
  readonly file_mode_private: boolean;
  /** Variable **names** only, and read-only: the web path cannot write these. */
  readonly credential_allowlist: readonly string[];
  readonly auth_source: string | null;
  readonly auth_source_linked: boolean;
  readonly egress_acknowledged: readonly EgressAcknowledgement[];
  readonly adopted_sources: readonly AdoptedSource[];
  readonly credential_sources: readonly CredentialSource[];
  readonly attach: AttachProjection;
  readonly providers: readonly ProviderRow[];
}

/** `GET /providers/catalog` — Pi's own catalog, live over the bridge (§23.1). */
export interface CatalogDocument {
  readonly status: "ok";
  readonly catalog?: readonly { readonly id: string; readonly name: string }[];
}

/** One provider spec, as `PUT /providers/specs` accepts it. */
export interface ProviderSpecInput {
  readonly id: string;
  readonly kind: ProviderKind;
  readonly name?: string;
  readonly baseUrl?: string;
  readonly credential?: string;
  readonly models: readonly {
    readonly id: string;
    readonly name?: string;
    readonly contextWindow?: number;
    readonly maxTokens?: number;
  }[];
}

/** `POST /providers/{id}/auth/begin` and `…/complete`'s flow projection. */
export interface FlowDocument {
  readonly status: "ok";
  readonly provider_id: string;
  readonly type: AuthFlowType;
  readonly state: string;
  /** The four non-secret device-code values (§23.4), when this is that flow. */
  readonly user_code?: string;
  readonly verification_uri?: string;
  readonly interval_seconds?: number;
  readonly expires_at?: number;
  /** The fallback's URL. Pi holds the PKCE verifier and the `state`, not us. */
  readonly authorize_url?: string;
}

/** `POST /providers/{id}/auth/key` — and it carries no key back (§23.8). */
export interface KeyAcceptedDocument {
  readonly status: "ok";
  readonly provider_id: string;
  readonly scope: CredentialScope;
  /** §23.9: rotation has no verb, so the response names what it displaced. */
  readonly replaced: string;
}

/** One entry of `POST /providers/discover`'s offer (§23.5). Four fields. */
export interface DiscoveryOffer {
  /** Server-minted and **opaque**: it encodes no path a client could decode. */
  readonly discovery_id: string;
  readonly kind: DiscoveryKind;
  readonly provider_id: string;
  readonly model_ids: readonly string[];
  /** Display text. The operator is being told where their own file is. */
  readonly source_path: string;
}

export interface DiscoveryDocument {
  readonly status: "ok";
  readonly sources: readonly DiscoveryOffer[];
}

export interface AdoptedDocument {
  readonly status: "ok";
  readonly adopted: DiscoveryOffer;
  readonly config_path: string;
  readonly file_mode: string | null;
  readonly adopted_sources: readonly AdoptedSource[];
}

function segment(value: string): string {
  return encodeURIComponent(value);
}

/** `GET /providers`. No sidecar needed — §23.0's first table row. */
export function loadProviders(): Promise<ProvidersDocument> {
  return apiJson<ProvidersDocument>("/providers");
}

/** `GET /providers/catalog`. Needs a sidecar: Pi *is* the catalog (§23.1). */
export function loadCatalog(): Promise<CatalogDocument> {
  return apiJson<CatalogDocument>("/providers/catalog");
}

/**
 * `PUT /providers/specs` — specs only, and a key, because it is a config write.
 *
 * `credential_allowlist` and `auth_source` are **absent from the argument list
 * by construction**, not filtered out later: they are read-only projections, and
 * a body carrying either is refused `allowlist_not_web_writable` by name. The
 * two compose into an arbitrary-environment-variable-to-arbitrary-host
 * exfiltration primitive (§23.6), which is why this function cannot express it.
 */
export function writeSpecs(
  providers: readonly ProviderSpecInput[],
  acknowledgeEgress: readonly string[] = [],
): Promise<{ readonly status: "ok"; readonly providers: readonly ProviderRow[] }> {
  const body: Record<string, unknown> = { providers };
  // §23.3: an egress host is re-affirmed **by typing the host**, not by
  // clicking a checkbox — so the caller passes the typed string through.
  if (acknowledgeEgress.length > 0) body["acknowledge_egress"] = acknowledgeEgress;
  return apiJson("/providers/specs", {
    method: "PUT",
    headers: { "Content-Type": "application/json", "Idempotency-Key": uuid7() },
    body: JSON.stringify(body),
  });
}

/**
 * `POST /providers/{id}/auth/key` — §23.3's paste.
 *
 * `scope` is required at the type level, which is this client's half of §23.2's
 * "API-key persistence has no default": there is no overload that omits it, so
 * a call site cannot pick one silently on the operator's behalf.
 */
export function submitKey(
  providerId: string,
  key: string,
  scope: CredentialScope,
  confirm = false,
): Promise<KeyAcceptedDocument> {
  return apiJson(`/providers/${segment(providerId)}/auth/key`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // The key is in the BODY. Never a path segment, a query parameter, or a
    // fragment (§23.3) — and never logged by this module either.
    body: JSON.stringify({ key, scope, ...(confirm ? { confirm: true } : {}) }),
  });
}

/** `POST /providers/{id}/auth/begin` (§23.4). */
export function beginLogin(providerId: string, type: AuthFlowType): Promise<FlowDocument> {
  return apiJson(`/providers/${segment(providerId)}/auth/begin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type }),
  });
}

/**
 * `GET /providers/{id}/auth/status` — metadata only.
 *
 * The client polls THIS; the **sidecar** polls the provider, honouring
 * `authorization_pending` and `slow_down`. The browser never touches the
 * provider, and this route never returns a token.
 */
export function loginStatus(providerId: string): Promise<Record<string, unknown>> {
  return apiJson(`/providers/${segment(providerId)}/auth/status`);
}

/** `POST /providers/{id}/auth/complete` — the operator's pasted text (§23.4). */
export function completeLogin(providerId: string, input: string): Promise<FlowDocument> {
  return apiJson(`/providers/${segment(providerId)}/auth/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
}

/** `POST /providers/{id}/auth/cancel`. Idempotent by construction. */
export function cancelLogin(providerId: string): Promise<{ readonly status: "ok" }> {
  return apiJson(`/providers/${segment(providerId)}/auth/cancel`, { method: "POST" });
}

/** `POST /providers/{id}/auth/signout` (§23.9). Keeps the spec; state → `none`. */
export function signOut(providerId: string, confirm = false): Promise<{ readonly status: "ok" }> {
  return apiJson(`/providers/${segment(providerId)}/auth/signout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(confirm ? { confirm: true } : {}),
  });
}

/**
 * `POST /providers/auth/unlink` — stop borrowing the operator's own login.
 *
 * §23.5: it replaces the symlink with an own file and does **not** read, copy,
 * or modify the target. Sign-out while linked is refused until this runs,
 * because `logout()` through a symlink would sign the operator out of their own
 * terminal.
 */
export function unlinkAuthSource(): Promise<{ readonly status: "ok"; readonly unlinked: boolean }> {
  return apiJson("/providers/auth/unlink", { method: "POST" });
}

/**
 * `POST /providers/discover` — Stage 10C's offer.
 *
 * **Call this from a person's click and from nowhere else.** §15.41's *no
 * background credential probe* is unrelaxed by the 2026-08-28 ruling, and
 * §23.6 makes the route a `POST` despite being a read precisely so that reading
 * the operator's home directory can never be something a page issues
 * incidentally.
 */
export function discover(): Promise<DiscoveryDocument> {
  return apiJson("/providers/discover", { method: "POST" });
}

/**
 * `POST /providers/adopt` — the one explicit act (§23.5 constraint 1).
 *
 * The body is the server-minted handle and nothing else. The offer already told
 * the operator the path, so a path here would add no information they lack — it
 * would only add a *client-chosen* path to a credential route, which is the one
 * shape §23.5 forbids by name.
 */
export function adopt(discoveryId: string): Promise<AdoptedDocument> {
  return apiJson("/providers/adopt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ discovery_id: discoveryId }),
  });
}

const SOURCE_SET: ReadonlySet<string> = new Set<string>(AUTH_SOURCES);
const HEALTH_SET: ReadonlySet<string> = new Set<string>(AUTH_HEALTH);

/** Whether a value is inside §23.8's axis-1 vocabulary. */
export function isAuthSource(value: unknown): value is AuthSource {
  return typeof value === "string" && SOURCE_SET.has(value);
}

/** Whether a value is inside §23.8's axis-2 vocabulary. */
export function isAuthHealth(value: unknown): value is AuthHealth {
  return typeof value === "string" && HEALTH_SET.has(value);
}
