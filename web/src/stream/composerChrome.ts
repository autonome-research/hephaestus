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
// * **Effort is not a session field, and is no longer a vocabulary here.**
//   §7A.10(e)(1) removed it: "no clause of §7A specifies a thinking-level
//   control, and a closed vocabulary with no surface is a spec claim by
//   implication". The provider/model join helpers went the same way — the
//   model selector they were minted for was never wired, and an exported
//   symbol nothing imports is a claim the codebase makes and cannot support.
//   The DFM chrome decision and the per-row model projection left for the same
//   reason: `DfmPanel` decides its own three states (§6.4) and never imported
//   the one written here.
// * **There is no Plan mode in the engine.** `[dfm] auto_run` / `run_dfm` is
//   the manufacturability equivalent, and it is a *project setting* plus a
//   tool — not a per-message flag (INTERFACE.md §6.4). Those two controls
//   live on the inspector DFM panel. The composer does not grow a Plan
//   toggle that would imply a tool argument that does not exist.
// * **No providers.json / no runtime is a named absence**, not a signed-in
//   agent. `modelsFrom` returns nothing when the file does not exist, so the
//   composer cannot render a picker of models nobody configured.

import type { ProvidersDocument } from "../api/providers";

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

/**
 * Whether a surface may name the model projection.
 *
 * False when the runtime is missing (`agent_unavailable`) or when the
 * providers document names no models. A chip over an empty set — or a
 * Select that wrote nothing — would read as a signed-in agent that is
 * not there.
 *
 * #114: the idle composer no longer mounts this projection. The helper
 * stays so a caller cannot invent a house name or a picker; the rail's
 * Model providers section is the resting place for the attached runtime.
 */
export function showModelChrome(
  agentUnavailable: boolean,
  models: readonly ComposerModel[],
): boolean {
  return !agentUnavailable && models.length > 0;
}
