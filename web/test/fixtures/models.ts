// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import type { ModelsDocument, ResolvedModel } from "../../src/api/providers";
import type { ExecutionSnapshot, SessionModelDocument, SessionModelState } from "../../src/api/sessions";
export const spark: ResolvedModel = { provider_id: "local/fake", model_id: "spark", name: "Spark", input: ["text"] };
export const vision: ResolvedModel = { provider_id: "local/fake", model_id: "vision/image", name: "Vision", input: ["text", "image"] };
export const modelState: SessionModelState = { revision: { epoch: "models-1", version: 0 }, current: spark,
  selected: { provider_id: spark.provider_id, model_id: spark.model_id }, pending_selection: null, state: "ready", reason: null };
export const createdModelState: SessionModelState = { ...modelState, current: vision,
  selected: { provider_id: vision.provider_id, model_id: vision.model_id } };
export const idleExecution: ExecutionSnapshot = { epoch: "test", version: 1, run_id: null, active_run_id: null,
  admission_available: true, terminal: null };
export const models: ModelsDocument = { status: "ok", providers: [{ provider_id: spark.provider_id, name: "Local fake",
  models: [...[vision, spark].map(m => ({ ...m, available: true, unavailable_reason: null })),
    { provider_id: spark.provider_id, model_id: "unknown", name: "Unknown declaration", input: null,
      available: false, unavailable_reason: "model_unknown" },
  ],
}], proposed_default: vision, default_policy: "first_available_declared" };
export function modelDoc(sid: string, state = modelState, execution = idleExecution): SessionModelDocument {
  return { status: "ok", session_id: sid, model_state: state, execution };
}
