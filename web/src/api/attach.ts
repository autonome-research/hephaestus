// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `agent_unavailable`'s cause, and the one action that can change it
// (INTERFACE.md §7A.8, §19.25; §23.0's route, landed).
//
// §7A.8 keeps the refusal and adds content to it. "Today `sessions_or_refuse`
// raises `503 agent_unavailable` on every session route… **That refusal is right
// and does not change.**" What changed is that the serve used to know exactly
// why the attach produced nothing — a missing `providers.json` at a path it
// prints, or one of a handful of named failures — and wrote it to a **stderr no
// browser will ever read**, then discarded it. The panel was left rendering a
// state with its content missing, which §4.4 says reads as a bug rather than as
// a design.
//
// So the projection below rides in §2.4's `data` on every `agent_unavailable`,
// and the composer renders it. **No secret ever enters it** — not a credential,
// not a token, not a provider's response body; `detail` is reduced at the
// server's boundary before it is ever serialized.

import { apiJson, WorkspaceError } from "./client";

/**
 * §7A.8's closed `cause` vocabulary, plus the seventh value §23.0 added.
 *
 * `detached` is not in §7A.8's original six: those were written when the only
 * way to have no runtime was to start without one, and `POST /providers/attach`
 * made detaching a *running* serve reachable. Reporting a detached serve as
 * `no_provider_config` would be a lie the file on disk contradicts.
 */
export const ATTACH_CAUSES = [
  "no_provider_config",
  "provider_config_invalid",
  "node_missing",
  "node_too_old",
  "sidecar_failed",
  "auth_link_refused",
  "detached",
] as const;
export type AttachCause = (typeof ATTACH_CAUSES)[number];

/** `AgentAttachState.projection()` — the flat shape both surfaces carry. */
export interface AttachProjection {
  readonly attached: boolean;
  /** The path the server **looked at**. Display text; never sent back. */
  readonly config_path: string;
  readonly generation: number;
  readonly cause?: string;
  readonly detail?: string;
}

/** `POST /providers/attach`'s success body. */
export interface AttachedDocument {
  readonly status: "ok";
  readonly attached: true;
  readonly config_path: string;
  readonly generation: number;
}

const CAUSE_SET: ReadonlySet<string> = new Set<string>(ATTACH_CAUSES);

export function isAttachCause(value: unknown): value is AttachCause {
  return typeof value === "string" && CAUSE_SET.has(value);
}

/**
 * The attach projection carried in a refusal's `data`, or `null`.
 *
 * `null` covers two different states and neither is guessed at: a refusal that
 * is not `agent_unavailable`, and an `agent_unavailable` from a process that has
 * never *attempted* an attach (an in-process harness). §7A.8's vocabulary
 * answers "why did the attach produce nothing"; inventing an answer where there
 * was no attempt would be exactly the fabricated content §4.4 forbids.
 */
export function attachProjection(data: Readonly<Record<string, unknown>>): AttachProjection | null {
  if (typeof data["config_path"] !== "string") return null;
  const cause = data["cause"];
  const detail = data["detail"];
  return {
    attached: data["attached"] === true,
    config_path: data["config_path"],
    generation: typeof data["generation"] === "number" ? data["generation"] : 0,
    ...(typeof cause === "string" ? { cause } : {}),
    ...(typeof detail === "string" ? { detail } : {}),
  };
}

/**
 * The §7A.8 cause carried by an `agent_unavailable` / `attach_failed` refusal.
 *
 * `null` where there is none to read: a refusal that is not about the attach, a
 * refusal from a process that never attempted one, or a `cause` word this build
 * has never heard of. Every caller falls back to a mapped generic rather than
 * to the server's raw sentence, so an unrecognised cause degrades to the §2.4
 * title and never to `f"{cause}: {detail}"` in a reading surface (RC-5).
 *
 * A helper rather than a JSX condition because it is the join between the
 * server's structured refusal and the ONE mapped cause vocabulary both surfaces
 * render (`copy.attach.cause`), and a join spelled twice is the defect
 * J-web-stream-6 recorded: the composer mapped the cause, the rail did not.
 */
export function attachCauseOf(error: unknown): AttachCause | null {
  if (!(error instanceof WorkspaceError)) return null;
  const projection = attachProjection(error.data);
  if (projection === null) return null;
  return isAttachCause(projection.cause) ? projection.cause : null;
}

/**
 * Whether a cause's `detail` says anything its mapped sentence does not.
 *
 * §4.7's second empty-state rule — "a shared cause is detected once, one cause,
 * one sentence" — is why this is a predicate and not a `detail !== undefined`
 * in the markup. For five of the seven causes the server derives `detail` from
 * the same raise the `cause` word came from, so it restates the mapped sentence
 * and re-prints the path the refusal already names: four paragraphs and a
 * button in a ~380px column, which is the wall an operator reads as a broken
 * chat (J-web-stream-4).
 *
 * The two exceptions carry a REDUCED EXCEPTION from the server boundary — a
 * parse error's position, a sidecar's exit — which is information no mapped
 * sentence can hold, so those two render it, behind the disclosure §4.7
 * prescribes.
 */
export function attachDetailAdds(cause: AttachCause | null): boolean {
  return cause === "provider_config_invalid" || cause === "sidecar_failed";
}

/**
 * `POST /providers/attach` — start an agent runtime on a serve that has none.
 *
 * **It writes nothing.** §7A.8 is explicit that until §23 ships, the disabled
 * composer "names the file the server looked for and **does not offer to write
 * it**, because there is nothing behind such an offer but a text editor". This
 * offers the other half: re-reading a configuration the operator has *already*
 * fixed in a terminal, without restarting the serve. A path the server still
 * cannot use comes back as `409 attach_failed` carrying the same closed `cause`,
 * so a failed retry is as legible as the state it tried to leave.
 *
 * No `Idempotency-Key`: §2.3's third route group is keyless, and attaching twice
 * is refused `agent_already_attached` by name rather than replayed.
 */
export function attachAgent(): Promise<AttachedDocument> {
  return apiJson<AttachedDocument>("/providers/attach", { method: "POST" });
}
