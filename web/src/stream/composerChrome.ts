// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Presentation of server model facts only. Never derive identity from declarations.
import type { ModelRef, ModelsDocument, ResolvedModel } from "../api/providers";
import { copy } from "../copy";

export function sameModel(a: ModelRef | null, b: ModelRef | null): boolean {
  return a !== null && b !== null && a.provider_id === b.provider_id && a.model_id === b.model_id;
}
export function modelIdentity(model: ModelRef): string {
  return `${model.provider_id}/${model.model_id}`;
}
export function modelCapability(input: ResolvedModel["input"] | null | undefined): string {
  return input == null ? copy.models.unknownCapability
    : input.includes("image") ? copy.models.images : copy.models.text;
}
export function modelUnavailableReason(reason: string | null): string {
  if (reason === null) return copy.models.unavailable;
  const explanation = copy.models.reasons[reason];
  return explanation ? `${explanation} (${reason})` : `${copy.models.unavailable}: ${reason}`;
}
export function filterModels(document: ModelsDocument | null, search: string) {
  const query = search.trim().toLocaleLowerCase();
  return (document?.providers ?? []).map(p => ({ ...p, models: p.models.filter(m =>
    [p.provider_id, p.name, m.provider_id, m.model_id, m.name].some(s => s.toLocaleLowerCase().includes(query)),
  ) })).filter(p => p.models.length > 0);
}
