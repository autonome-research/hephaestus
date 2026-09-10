// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import type { ModelRef, ModelsDocument, ModelRevision } from "../../src/api/providers";
import type { SessionModelDocument } from "../../src/api/sessions";
import { api } from "../harness/world";
/** Explicit test choice from the local fake runtime; no provider probe. */
export async function proposedModel(): Promise<ModelRef> {
  const doc = await api<ModelsDocument>("/providers/models");
  if (doc.proposed_default === null) throw new Error("Local fixture has no proposed model");
  return { provider_id: doc.proposed_default.provider_id, model_id: doc.proposed_default.model_id };
}
export async function modelRevision(sid: string): Promise<ModelRevision> {
  const doc = await api<SessionModelDocument>(`/sessions/${encodeURIComponent(sid)}/model`);
  if (doc.model_state.state !== "ready") throw new Error("Local fixture model is not ready");
  return doc.model_state.revision;
}
