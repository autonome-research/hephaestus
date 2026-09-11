// Selector projections and private durable intent. No discovery or credential writes.
import { randomUUID } from "node:crypto";
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { ErrorCode, RpcError } from "../rpc.js";
import type { PiModel, ProviderAvailability, ProviderSpec } from "./runtime.js";

export type ModelRef = { provider_id: string; model_id: string };
export type ModelRevision = { epoch: string; version: number };
export type ResolvedModel = ModelRef & { name: string; input: ("text" | "image")[] };
export type ModelOption = ModelRef & { name: string; input: ("text" | "image")[] | null; available: boolean; unavailable_reason: string | null };
export type ModelsDocument = { status: "ok"; providers: { provider_id: string; name: string; models: ModelOption[] }[]; proposed_default: ResolvedModel | null; default_policy: "first_available_declared" };
export type SessionModelState = {
  revision: ModelRevision; current: ResolvedModel | null; selected: ModelRef | null;
  pending_selection: ModelRef | null; state: "ready" | "changing" | "unavailable" | "uncertain"; reason: string | null;
};
export type SelectionRecord = { schema_version: 1; selected: ModelRef | null; pending_selection: ModelRef | null };

export function modelError(reason: string, extra: Record<string, import("../framing.js").JsonValue> = {}): RpcError {
  return new RpcError(ErrorCode.INVALID_PARAMS, reason === "model_changed" ? "The session model changed. Review it before sending." : reason.replaceAll("_", " "), { reason, ...extra });
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw modelError("invalid_params");
  return value as Record<string, unknown>;
}
export function readModelRef(value: unknown): ModelRef {
  const v = object(value);
  if (Object.keys(v).length !== 2 || typeof v.provider_id !== "string" || !v.provider_id.trim() || typeof v.model_id !== "string" || !v.model_id.trim()) throw modelError("invalid_params");
  return { provider_id: v.provider_id, model_id: v.model_id };
}
export function readRevision(value: unknown): ModelRevision {
  if (value === undefined) throw modelError("model_revision_required");
  const v = object(value);
  if (Object.keys(v).length !== 2 || typeof v.epoch !== "string" || !v.epoch || typeof v.version !== "number" || !Number.isSafeInteger(v.version) || v.version < 0) throw modelError("invalid_params");
  return { epoch: v.epoch, version: v.version };
}
export function modelRef(model: PiModel): ModelRef { return { provider_id: model.provider, model_id: model.id }; }
export function resolvedModel(model: PiModel): ResolvedModel { return { ...modelRef(model), name: model.name, input: [...model.input] }; }
export function sameModel(a: ModelRef | null, b: ModelRef | null): boolean { return a?.provider_id === b?.provider_id && a?.model_id === b?.model_id; }

export class ModelResolver {
  constructor(readonly runtime: ModelRuntime, readonly declarations: readonly ProviderSpec[], readonly availability: readonly ProviderAvailability[]) {}
  resolve(ref: ModelRef): PiModel {
    const provider = this.declarations.find(p => p.id === ref.provider_id);
    if (!provider && !this.runtime.getProvider(ref.provider_id)) throw modelError("provider_unknown");
    const declared = provider?.models.some(m => m.id === ref.model_id);
    // A failed keyed registration is a provider failure, not an invented
    // unknown-model result. Native eligibility is re-read locally after auth changes.
    const failed = this.availability.find(p => p.id === ref.provider_id);
    if (declared && provider?.kind !== "pi_native" && failed?.available === false) throw modelError("model_unavailable", { unavailable_reason: failed.unavailable_reason ?? "provider_unknown" });
    if (!this.runtime.getProvider(ref.provider_id)) throw modelError("provider_unknown");
    const model = this.runtime.getModel(ref.provider_id, ref.model_id);
    if (!model) throw modelError("model_unknown");
    if (!declared) throw modelError("model_not_configured");
    if (!this.runtime.hasConfiguredAuth(ref.provider_id)) throw modelError("model_unavailable", { unavailable_reason: "provider_not_authenticated" });
    return model;
  }
  document(): ModelsDocument {
    let proposed: ResolvedModel | null = null;
    const providers = this.declarations.map(provider => ({
      provider_id: provider.id,
      name: this.runtime.getProvider(provider.id)?.name ?? ("name" in provider ? provider.name : undefined) ?? provider.id,
      models: provider.models.map(declared => {
        const ref = { provider_id: provider.id, model_id: declared.id };
        const model = this.runtime.getModel(provider.id, declared.id);
        let reason: string | null = null;
        try { const eligible = this.resolve(ref); proposed ??= resolvedModel(eligible); }
        catch (err) { const data = err instanceof RpcError ? err.data as Record<string, unknown> : {}; reason = String(data.unavailable_reason ?? data.reason ?? "model_unavailable"); }
        return { ...ref, name: model?.name ?? ("name" in declared ? declared.name : declared.id), input: model ? [...model.input] : null, available: reason === null, unavailable_reason: reason };
      }),
    }));
    return { status: "ok", providers, proposed_default: proposed, default_policy: "first_available_declared" };
  }
  defaultModel(): PiModel {
    const proposed = this.document().proposed_default;
    if (!proposed) throw modelError("selection_required");
    return this.resolve(proposed);
  }
}

export function loadSelection(dir: string | undefined): SelectionRecord | null {
  if (!dir || !existsSync(path.join(dir, "model-selection.json"))) return null;
  const raw = object(JSON.parse(readFileSync(path.join(dir, "model-selection.json"), "utf8")));
  if (raw.schema_version !== 1 || Object.keys(raw).length !== 3) throw modelError("model_selection_uncertain");
  return { schema_version: 1, selected: raw.selected === null ? null : readModelRef(raw.selected), pending_selection: raw.pending_selection === null ? null : readModelRef(raw.pending_selection) };
}
export function saveSelection(dir: string | undefined, record: SelectionRecord): void {
  if (!dir) return;
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const temp = path.join(dir, `.model-selection-${randomUUID()}.tmp`);
  try {
    const fd = openSync(temp, "wx", 0o600);
    try { writeFileSync(fd, JSON.stringify(record) + "\n"); fsyncSync(fd); } finally { closeSync(fd); }
    renameSync(temp, path.join(dir, "model-selection.json"));
    const directory = openSync(dir, "r");
    try { fsyncSync(directory); } finally { closeSync(directory); }
  } finally { if (existsSync(temp)) unlinkSync(temp); }
}
