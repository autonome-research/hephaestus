// The browser auth-interaction adapter (INTERFACE.md §23.4, §23.14 item 4).
//
// Pi's login API is a *conversation*: `ModelRuntime.login(providerId, type,
// interaction)` calls back with `notify()` events and blocks on `prompt()`
// answers. A terminal answers those callbacks inline. A browser cannot — there
// is a request/response boundary in the middle of the conversation, and §23's
// own §17 exclusion 10 forbids carrying it over the `/events` vocabulary.
//
// So this module turns the conversation into STATE a status route can read:
// `begin` starts the login in the background and returns the first non-secret
// values it produced; `status` reports where the flow is; `complete` supplies
// the one answer a callback-only flow needs; `cancel` abandons it.
//
// Three properties are load-bearing.
//
// **Pi is the credential store and the OAuth client; this file is neither.**
// No PKCE verifier, no `state`, no token exchange, no refresh clock lives here.
// `complete` hands Pi the operator's pasted text and Pi's own
// `parseAuthorizationInput` parses it and *verifies `state`*. Mission rule 6.
//
// **The token-endpoint response body never crosses the API.** A login failure
// is reduced to `{code, http_status}` HERE — before anything logs it — because
// Pi interpolates raw response bodies into its error messages and the sidecar's
// stderr is a second pipe the bridge boundary cannot see (§23.6). Nothing in
// this file writes a login error to `console.error`, and the RpcError it raises
// carries the code and never the message.
//
// **Device code is the default, and it is the flow that opens no socket.**
// §23.4 rejects a loopback callback listener on three independent grounds. Pi's
// `openai-codex` flow offers both and asks which by a `select` prompt, which
// this adapter answers with the operator's chosen type — so choosing
// `device_code` genuinely takes the branch that starts no server.
//
// DEVIATION, reported rather than reinterpreted: for providers whose *only*
// OAuth flow is callback-based, the pinned dependency starts a loopback
// callback server inside its own login (`pi-ai/auth/oauth/anthropic.js`
// unconditionally; `openai-codex.js` on the `browser` branch). That listener is
// Pi's, in this sidecar process, for the duration of the flow — the Hephaestus
// server still opens exactly one socket and still exposes no callback route.
// `authorize_url` is offered because §23.4 requires the universal fallback; an
// operator who wants §23.4's no-listener guarantee absolutely should use
// `device_code`, which is why it is the default everywhere it exists.

import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import type { AuthEvent, AuthPrompt } from "@earendil-works/pi-ai";

/** §23.4's two mechanically distinct flows. Closed; §23 adds no third. */
export type FlowType = "device_code" | "authorize_url";

/** Where a flow is. `slow_down` and `authorization_pending` are §23.6's 200s. */
export type FlowState =
  | "authorization_pending"
  | "awaiting_input"
  | "complete"
  | "failed"
  | "cancelled";

/**
 * The closed refusal vocabulary this module may produce (§23.11). Every one is
 * a NAMED refusal: a message is never forwarded in its place, and nothing here
 * degrades to a generic error.
 */
export type CredentialErrorCode =
  | "authorization_expired"
  | "authorization_input_malformed"
  | "authorization_state_mismatch"
  | "credential_expired"
  | "credential_rejected"
  | "login_already_in_progress"
  | "provider_rate_limited"
  | "provider_unknown"
  | "provider_unreachable"
  | "unsupported_auth_type";

/** A failure reduced to what may cross the bridge: a code and a status. */
export class CredentialError extends Error {
  constructor(
    readonly code: CredentialErrorCode,
    readonly httpStatus: number,
    readonly providerId: string,
  ) {
    // The message is the CODE, deliberately. Any other text here would be a
    // second channel for the provider body §23.6 exists to contain.
    super(code);
    this.name = "CredentialError";
  }
}

/** Non-secret projection of a flow. Contains no token, code, or verifier. */
export interface FlowProjection {
  readonly provider_id: string;
  readonly type: FlowType;
  readonly state: FlowState;
  readonly user_code?: string;
  readonly verification_uri?: string;
  readonly interval_seconds?: number;
  readonly authorize_url?: string;
  readonly expires_at?: number;
  readonly code?: CredentialErrorCode;
}

const BROWSER_METHOD = "browser";
const DEVICE_CODE_METHOD = "device_code";

/** How long `begin` waits for a flow's first non-secret values. */
const BEGIN_SETTLE_MS = 20_000;

interface Flow {
  readonly providerId: string;
  readonly type: FlowType;
  state: FlowState;
  userCode?: string;
  verificationUri?: string;
  intervalSeconds?: number;
  authorizeUrl?: string;
  expiresAt?: number;
  code?: CredentialErrorCode;
  httpStatus?: number;
  /** Resolves once the first `notify` has given the route something to return. */
  announced: Promise<void>;
  announce: () => void;
  /** Supplies the answer to Pi's `manual_code` prompt (the operator's paste). */
  supply?: (text: string) => void;
  abort: AbortController;
  done: Promise<void>;
}

/**
 * Reduce a login failure to `{code, http_status}` BEFORE anything logs it.
 *
 * The classification reads the error's own text and then throws that text away.
 * That asymmetry is the point: the only thing a provider's raw body may
 * influence is *which named refusal* the operator sees, never the bytes that
 * reach a client, a log, or a stderr tail (§23.6).
 */
export function reduceLoginError(err: unknown, providerId: string): CredentialError {
  const text = (err instanceof Error ? err.message : String(err)).toLowerCase();
  const pick = (): [CredentialErrorCode, number] => {
    if (text.includes("unsupported_auth_type")) return ["unsupported_auth_type", 422];
    if (text.includes("state mismatch")) return ["authorization_state_mismatch", 409];
    if (text.includes("missing authorization code") || text.includes("missing oauth state")) {
      return ["authorization_input_malformed", 400];
    }
    if (text.includes("expired") || text.includes("timed out") || text.includes("timeout")) {
      return ["authorization_expired", 409];
    }
    if (text.includes("429") || text.includes("rate limit")) return ["provider_rate_limited", 429];
    if (
      text.includes("enotfound") ||
      text.includes("econnrefused") ||
      text.includes("network") ||
      text.includes("fetch failed")
    ) {
      return ["provider_unreachable", 502];
    }
    // "Bad key" and "revoked key" are the same refusal and §23.10 says so
    // outright: both are a 401, so inventing a second name would be a
    // distinction the wire does not support. An unclassified authorization
    // failure lands here rather than in a catch-all, because a vocabulary that
    // absorbs every exception stops being a vocabulary.
    return ["credential_rejected", 409];
  };
  const [code, httpStatus] = pick();
  return new CredentialError(code, httpStatus, providerId);
}

/**
 * §23.8's health axis — **last observed**, never current.
 *
 * "DECISION: health is *last observed*, never *current*, and there is no
 * background probe. The panel renders 'accepted 14:32', never 'connected'."
 * *Rejected:* a validity ping on panel load or a periodic keepalive — an
 * unsolicited outbound request from a local tool the operator did not ask to
 * make one, burning provider rate limit to answer a question the next real turn
 * answers for free, and a green dot meaning "valid 90 seconds ago" is a claim
 * the design cannot keep.
 *
 * So the ONLY thing that writes here is a turn that actually talked to the
 * provider. Setting a key writes nothing: handing this process a credential
 * observes nothing about whether the provider will accept it.
 */
export type Health =
  | "unused"
  | "accepted"
  | "rejected"
  | "expired"
  | "unreachable"
  | "rate_limited";

export interface Observation {
  readonly health: Health;
  /** Unix seconds. The staleness goes on screen rather than into a footnote. */
  readonly at: number;
}

const observations = new Map<string, Observation>();

/** What a turn against ``providerId`` last observed, if anything has. */
export function lastObserved(providerId: string): Observation | undefined {
  return observations.get(providerId);
}

/**
 * Record what a completed turn observed about a provider (§23.8, §23.10).
 *
 * §23.10: a credential revoked under a running session makes the next model
 * request 401, the run **fails** — not retried, not paused, not resumed — and
 * "the provider's health axis flips to `rejected` and the panel shows it; that
 * is the only notification the design has, and it is enough, because the
 * operator is looking at a failed turn". This is that flip.
 */
export function observeTurn(providerId: string, error: string | undefined): void {
  const at = Math.floor(Date.now() / 1000);
  if (error === undefined) {
    observations.set(providerId, { health: "accepted", at });
    return;
  }
  observations.set(providerId, { health: healthOfError(error), at });
}

/**
 * Classify a turn error onto the health axis, then throw the text away.
 *
 * The same asymmetry `reduceLoginError` uses and for the same reason: a
 * provider's raw message may influence *which named state* is shown and may
 * never influence the bytes that reach a client, a log, or a stderr tail
 * (§23.6).
 */
export function healthOfError(error: string): Health {
  const text = error.toLowerCase();
  if (text.includes("429") || text.includes("rate limit")) return "rate_limited";
  if (
    text.includes("enotfound") ||
    text.includes("econnrefused") ||
    text.includes("fetch failed") ||
    text.includes("network")
  ) {
    return "unreachable";
  }
  if (text.includes("expired")) return "expired";
  if (text.includes("401") || text.includes("unauthorized") || text.includes("auth")) {
    // §23.10: "bad key" and "revoked key" are the SAME refusal, because both
    // are a 401 and a vocabulary that names a state it cannot observe is worse
    // than a coarse one that can.
    return "rejected";
  }
  // A turn that failed for a reason that is not about the credential says
  // nothing about the credential, so the axis keeps its previous answer rather
  // than inventing one.
  return observations.size === 0 ? "unused" : "accepted";
}

/** Per-provider login flows. At most one at a time (§23.6). */
export class LoginFlows {
  private readonly flows = new Map<string, Flow>();

  /** The projection a status route reads, or undefined when no flow exists. */
  status(providerId: string): FlowProjection | undefined {
    const flow = this.flows.get(providerId);
    if (flow === undefined) return undefined;
    return project(flow);
  }

  /**
   * Start a flow and return its first non-secret values.
   *
   * A second flow for the same provider is refused `login_already_in_progress`
   * — **flow identity, not key identity, is the guard** (§23.6). A settled flow
   * is not "in progress": re-running a login after a failure is a normal thing
   * for an operator to do and must not require a cancel first.
   */
  async begin(runtime: ModelRuntime, providerId: string, type: FlowType): Promise<FlowProjection> {
    const existing = this.flows.get(providerId);
    if (existing !== undefined && !isSettled(existing.state)) {
      throw new CredentialError("login_already_in_progress", 409, providerId);
    }
    if (runtime.getProvider(providerId) === undefined) {
      throw new CredentialError("provider_unknown", 404, providerId);
    }
    let announce: () => void = () => {};
    const announced = new Promise<void>((resolve) => {
      announce = resolve;
    });
    const flow: Flow = {
      providerId,
      type,
      state: "authorization_pending",
      announced,
      announce,
      abort: new AbortController(),
      done: Promise.resolve(),
    };
    this.flows.set(providerId, flow);
    flow.done = this.drive(runtime, flow);
    await Promise.race([flow.announced, flow.done, sleep(BEGIN_SETTLE_MS)]);
    if (flow.state === "failed" && flow.code !== undefined) {
      throw new CredentialError(flow.code, flow.httpStatus ?? 409, providerId);
    }
    return project(flow);
  }

  /**
   * Hand Pi the operator's pasted redirect URL, `code#state` pair, or bare code.
   *
   * The browser never touched the provider and this process never parsed the
   * paste: Pi's own `parseAuthorizationInput` does both, and verifies `state`.
   */
  async complete(providerId: string, text: string): Promise<FlowProjection> {
    const flow = this.flows.get(providerId);
    if (flow === undefined || isSettled(flow.state)) {
      throw new CredentialError("authorization_expired", 409, providerId);
    }
    if (flow.supply === undefined) {
      // A device-code flow has no paste step: the sidecar polls the provider.
      throw new CredentialError("unsupported_auth_type", 422, providerId);
    }
    if (text.trim() === "") {
      throw new CredentialError("authorization_input_malformed", 400, providerId);
    }
    flow.supply(text);
    await flow.done;
    if (flow.state === "failed" && flow.code !== undefined) {
      throw new CredentialError(flow.code, flow.httpStatus ?? 409, providerId);
    }
    return project(flow);
  }

  /** Abandon a pending flow. Idempotent by construction (§23.6). */
  async cancel(providerId: string): Promise<FlowProjection | undefined> {
    const flow = this.flows.get(providerId);
    if (flow === undefined) return undefined;
    if (!isSettled(flow.state)) {
      flow.state = "cancelled";
      flow.abort.abort();
      flow.supply?.("");
      flow.announce();
      await flow.done.catch(() => {});
    }
    return project(flow);
  }

  private async drive(runtime: ModelRuntime, flow: Flow): Promise<void> {
    try {
      await runtime.login(flow.providerId, "oauth", {
        signal: flow.abort.signal,
        notify: (event: AuthEvent) => this.onNotify(flow, event),
        prompt: (prompt: AuthPrompt) => this.onPrompt(flow, prompt),
      });
      if (flow.state !== "cancelled") flow.state = "complete";
    } catch (err) {
      if (flow.state !== "cancelled") {
        // REDUCED HERE, before any logging. `reduced` carries a code and a
        // status; `err` — which may quote a token-endpoint response body
        // verbatim — is dropped on this line and never reaches stderr.
        const reduced = reduceLoginError(err, flow.providerId);
        flow.state = "failed";
        flow.code = reduced.code;
        flow.httpStatus = reduced.httpStatus;
      }
    } finally {
      flow.announce();
    }
  }

  private onNotify(flow: Flow, event: AuthEvent): void {
    if (event.type === "device_code") {
      flow.userCode = event.userCode;
      flow.verificationUri = event.verificationUri;
      if (event.intervalSeconds !== undefined) flow.intervalSeconds = event.intervalSeconds;
      if (event.expiresInSeconds !== undefined) {
        flow.expiresAt = Math.floor(Date.now() / 1000) + event.expiresInSeconds;
      }
      flow.state = "authorization_pending";
      flow.announce();
      return;
    }
    if (event.type === "auth_url") {
      flow.authorizeUrl = event.url;
      flow.state = "awaiting_input";
      flow.announce();
    }
    // `info` and `progress` carry no state a status route reports, and are
    // deliberately NOT logged: they are the channel a provider error message
    // would arrive on.
  }

  private onPrompt(flow: Flow, prompt: AuthPrompt): Promise<string> {
    if (prompt.type === "select") {
      // Pi asks which login method; the operator already chose, at `begin`.
      // Answering here is what makes `device_code` genuinely take the branch
      // that starts no listening socket (§23.4).
      const wanted = flow.type === "device_code" ? DEVICE_CODE_METHOD : BROWSER_METHOD;
      const match = prompt.options.find((option) => option.id === wanted);
      if (match === undefined) {
        // The provider does not offer the flow that was asked for. 422 with
        // what it *does* offer, never a silent substitution (§23.6).
        return Promise.reject(new UnsupportedFlow(prompt.options.map((o) => o.id)));
      }
      return Promise.resolve(match.id);
    }
    if (prompt.type === "manual_code") {
      flow.state = "awaiting_input";
      flow.announce();
      return new Promise<string>((resolve) => {
        flow.supply = resolve;
      });
    }
    // `text` / `secret` prompts belong to an api-key login, which does not
    // come through this adapter (§23.3 pastes a key on its own route).
    return Promise.reject(new UnsupportedFlow([]));
  }
}

/** Raised inside the interaction; classified back out by `reduceLoginError`. */
class UnsupportedFlow extends Error {
  constructor(readonly offered: readonly string[]) {
    super(`unsupported_auth_type: ${offered.join(",")}`);
    this.name = "UnsupportedFlow";
  }
}

function isSettled(state: FlowState): boolean {
  return state === "complete" || state === "failed" || state === "cancelled";
}

function project(flow: Flow): FlowProjection {
  return {
    provider_id: flow.providerId,
    type: flow.type,
    state: flow.state,
    ...(flow.userCode !== undefined ? { user_code: flow.userCode } : {}),
    ...(flow.verificationUri !== undefined ? { verification_uri: flow.verificationUri } : {}),
    ...(flow.intervalSeconds !== undefined ? { interval_seconds: flow.intervalSeconds } : {}),
    ...(flow.authorizeUrl !== undefined ? { authorize_url: flow.authorizeUrl } : {}),
    ...(flow.expiresAt !== undefined ? { expires_at: flow.expiresAt } : {}),
    ...(flow.code !== undefined ? { code: flow.code } : {}),
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
