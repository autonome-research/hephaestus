// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Composer session chrome, projected from existing routes (issue #13).
//
// The composer is still a thin client of `server/`. This module owns the
// *decisions* about what the chrome may show, so a component cannot invent a
// house model name or a thinking level the wire never offered:
//
// * **Model identifiers come from `GET /providers`.** The identifier is the
//   provider's own `models[].id`, qualified by the provider id so two rows
//   cannot collide. Nothing here mints a product name, and nothing here is
//   used as an identifier except those two server fields. The composer
//   *projects* the first declared id; it does not offer a Select, because
//   `POST /sessions/{id}/prompt` admits `{text, context?}` and no model field
//   (INTERFACE.md §7A.3).
// * **Effort is not a session field.** The levels below are Pi's closed
//   thinking vocabulary, recorded so a later route can name them without
//   inventing a house scale. A picker over them today would write nothing.
// * **There is no Plan mode in the engine.** `[dfm] auto_run` / `run_dfm` is
//   the manufacturability equivalent, and it is a *project setting* plus a
//   tool — not a per-message flag (INTERFACE.md §6.4). The chrome therefore
//   does not grow a Plan toggle that would imply a tool argument that does
//   not exist.
// * **No providers.json / no runtime is a named absence**, not a signed-in
//   agent. `modelsFrom` returns nothing when the file does not exist, so the
//   composer cannot render a picker of models nobody configured.

import type { ProviderRow, ProvidersDocument } from "../api/providers";

/**
 * One model the composer may name, as `GET /providers` declared it.
 *
 * `id` is the **identifier** — the provider's own model id. `name` is display
 * text the server already sent; this module never substitutes a house name
 * for either field.
 */
export interface ComposerModel {
  readonly providerId: string;
  readonly id: string;
  readonly name: string;
  readonly reasoning: boolean;
}

/**
 * Pi thinking levels. Closed, and offered only for a model that declared
 * `reasoning: true` on the providers document.
 */
export const EFFORT_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh"] as const;
export type EffortLevel = (typeof EFFORT_LEVELS)[number];

const EFFORT_SET: ReadonlySet<string> = new Set<string>(EFFORT_LEVELS);

/** Whether a value is inside the closed effort vocabulary. */
export function isEffortLevel(value: unknown): value is EffortLevel {
  return typeof value === "string" && EFFORT_SET.has(value);
}

/**
 * The wire key for one model: `providerId/modelId`.
 *
 * The model id alone is the identifier the provider declared; the provider
 * id qualifies it so two rows cannot share one option. Neither half is a
 * house name.
 */
export function modelKey(model: ComposerModel): string {
  return `${model.providerId}/${model.id}`;
}

/** Parse a `modelKey` back into its two server fields. */
export function parseModelKey(key: string): { readonly providerId: string; readonly id: string } | null {
  const split = key.indexOf("/");
  if (split <= 0 || split === key.length - 1) return null;
  return { providerId: key.slice(0, split), id: key.slice(split + 1) };
}

/**
 * The models `GET /providers` declared, in document order.
 *
 * Returns `[]` when the configuration file does not exist, is malformed, or
 * lists no models — the named absence, not a defaulted house model. A provider
 * marked `available: false` is still listed: unavailability is a fact the
 * row already carries, and dropping it here would silently substitute a
 * neighbour.
 */
export function modelsFrom(document: ProvidersDocument | null | undefined): readonly ComposerModel[] {
  if (document === undefined || document === null) return [];
  if (!document.config_exists || document.config_malformed) return [];
  const out: ComposerModel[] = [];
  for (const row of document.providers) {
    for (const model of row.models) {
      if (model.id === "") continue;
      out.push({
        providerId: row.id,
        id: model.id,
        name: model.name === "" ? model.id : model.name,
        reasoning: model.reasoning === true,
      });
    }
  }
  return out;
}

/** The first declared model, or `null` when there is nobody to pick. */
export function defaultModel(models: readonly ComposerModel[]): ComposerModel | null {
  return models[0] ?? null;
}

/** The effort options a given model actually supports. */
export function effortOptionsFor(model: ComposerModel | null): readonly EffortLevel[] {
  if (model === null || !model.reasoning) return ["off"];
  return EFFORT_LEVELS;
}

/**
 * Whether the composer may render the model/effort projection.
 *
 * False when the runtime is missing (`agent_unavailable`) or when the
 * providers document names no models. A chip over an empty set — or a
 * Select that wrote nothing — would read as a signed-in agent that is
 * not there.
 */
export function showModelChrome(
  agentUnavailable: boolean,
  models: readonly ComposerModel[],
): boolean {
  return !agentUnavailable && models.length > 0;
}

/**
 * The DFM chrome state. Closed at three:
 *
 * * `chip` — a part is selected and `GET /parts/{part}/dfm` answered, so the
 *   two §6.4 controls (auto_run toggle + Run DFM) can project that document;
 * * `absent` — no part is selected, and the chrome says so rather than
 *   offering a control that writes nothing;
 * * `hidden` — the runtime is missing, or the document has not arrived. The
 *   composer does not invent a DFM setting, and it does not put DFM chrome
 *   on the `agent_unavailable` refusal.
 */
export const DFM_CHROME = ["chip", "absent", "hidden"] as const;
export type DfmChrome = (typeof DFM_CHROME)[number];

export function showDfmChrome(
  agentUnavailable: boolean,
  part: string | null,
  hasDfm: boolean,
): DfmChrome {
  if (agentUnavailable) return "hidden";
  if (part === null) return "absent";
  return hasDfm ? "chip" : "hidden";
}

/** A provider row's models, for tests that build a document by hand. */
export function modelsOf(row: ProviderRow): readonly ComposerModel[] {
  return row.models.map((model) => ({
    providerId: row.id,
    id: model.id,
    name: model.name === "" ? model.id : model.name,
    reasoning: model.reasoning === true,
  }));
}
