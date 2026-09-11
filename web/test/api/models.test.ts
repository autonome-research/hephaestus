// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiJson } from "../../src/api/client";
import { createSession, fetchSessionModel, selectSessionModel, sendPrompt } from "../../src/api/sessions";
import { loadModels } from "../../src/api/providers";
import { modelDoc, models, modelState, vision } from "../fixtures/models";
vi.mock("../../src/api/client", () => ({ apiJson: vi.fn() }));
beforeEach(() => { vi.mocked(apiJson).mockReset(); });
function request() {
  const call = vi.mocked(apiJson).mock.calls.at(-1)!;
  const init = call[1]!;
  return { path: call[0], method: init.method, headers: new Headers(init.headers), body: JSON.parse(String(init.body)) as unknown };
}
describe("model HTTP contract", () => {
  it("uses the selector projection without reading declarations or the sign-in catalog", async () => {
    vi.mocked(apiJson).mockResolvedValue(models); expect(await loadModels()).toEqual(models);
    expect(apiJson).toHaveBeenCalledExactlyOnceWith("/providers/models", { cache: "no-store" });
  });
  it("rejects a missing capability, availability, or revision field", async () => {
    vi.mocked(apiJson).mockResolvedValue({ ...models, proposed_default: undefined });
    await expect(loadModels()).rejects.toThrow("Invalid models");
    vi.mocked(apiJson).mockResolvedValue({ ...modelDoc("a"), model_state: { ...modelState, revision: { epoch: "e", version: true } } });
    await expect(fetchSessionModel("a")).rejects.toThrow("Invalid session model");
    vi.mocked(apiJson).mockResolvedValue(modelDoc("wrong-session"));
    await expect(fetchSessionModel("a")).rejects.toThrow("Invalid session model");
  });
  it("selects a separate pair and revision, keylessly, exactly once", async () => {
    vi.mocked(apiJson).mockResolvedValue(modelDoc("a/b"));
    const selection = { model: { provider_id: "provider/with/slashes", model_id: "model/with/slashes" }, expected_model_revision: modelState.revision };
    await selectSessionModel("a/b", selection);
    expect(request()).toMatchObject({ path: "/sessions/a%2Fb/model", method: "PUT", body: selection });
    expect(request().headers.has("Idempotency-Key")).toBe(false);
    vi.mocked(apiJson).mockRejectedValue(new Error("lost write"));
    await expect(selectSessionModel("a/b", selection)).rejects.toThrow("lost write");
    expect(apiJson).toHaveBeenCalledTimes(2);
  });
  it("fresh create submits the exact explicit choice; prompt carries only a concurrency precondition", async () => {
    vi.mocked(apiJson).mockResolvedValue({ ...modelDoc("new"), profile: "part", part: "part", resumed: false });
    await createSession("part", "part", vision);
    expect(request().body).toEqual({ profile: "part", part: "part", model: { provider_id: vision.provider_id, model_id: vision.model_id } });
    expect(request().headers.has("Idempotency-Key")).toBe(false);
    await sendPrompt("new", "explicit text", null, modelState.revision);
    expect(request().body).toEqual({ text: "explicit text", context: null, expected_model_revision: modelState.revision });
    expect(request().headers.has("Idempotency-Key")).toBe(false);
  });
});
