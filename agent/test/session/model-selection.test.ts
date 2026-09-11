import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { FakeModel, createModelRuntime, type ProviderSpec } from "../../src/session/runtime.js";
import { SessionService } from "../../src/session/manager.js";
import { ModelResolver, loadSelection, readRevision, saveSelection } from "../../src/session/model-selection.js";
import * as selection from "../../src/session/model-selection.js";

const cleanup: (() => Promise<void> | void)[] = [];
afterEach(async () => { vi.restoreAllMocks(); for (const fn of cleanup.splice(0).reverse()) await fn(); });
async function fixture() {
  const dir = mkdtempSync(path.join(tmpdir(), "model-selection-"));
  cleanup.push(() => rmSync(dir, { recursive: true, force: true }));
  const fake = await FakeModel.start([]);
  cleanup.push(() => fake.close());
  const spec = fake.providerSpec();
  if (spec.kind === "pi_native") throw new Error("fake must be local");
  const provider: ProviderSpec = { ...spec, models: [
    { id: "text", name: "Text", input: ["text"], contextWindow: 128000, maxTokens: 4096 },
    { id: "vision/with/slashes", name: "Vision", input: ["text", "image"], contextWindow: 128000, maxTokens: 4096 },
  ] };
  const configured = await createModelRuntime({ providers: [provider] }, { agentDir: dir });
  const resolver = new ModelResolver(configured.runtime, [provider], configured.providers);
  const makeService = () => {
    const service = new SessionService({ runtime: configured.runtime, agentDir: dir, resolver, model: () => resolver.defaultModel() });
    cleanup.push(() => service.disposeAll());
    return service;
  };
  const text = { provider_id: provider.id, model_id: "text" };
  const vision = { provider_id: provider.id, model_id: "vision/with/slashes" };
  const service = makeService();
  const session = await service.create({ profile: "orchestrator", projectRoot: dir, sessionId: "test", model: text });
  return { dir, fake, configured, resolver, service, session, text, vision, makeService };
}

describe("model selection", () => {
  it("projects resolved capabilities, keeps unknown declarations disabled, and does not probe", async () => {
    const f = await fixture();
    const original = f.resolver.declarations[0]!;
    const resolver = new ModelResolver(f.configured.runtime, [{ ...original, models: [...original.models, { id: "absent" }] } as ProviderSpec], f.configured.providers);
    const document = resolver.document();
    expect(document.proposed_default).toMatchObject({ ...f.text, input: ["text"] });
    expect(document.providers[0]?.models[1]).toMatchObject({ ...f.vision, input: ["text", "image"], available: true });
    expect(document.providers[0]?.models[2]).toMatchObject({ model_id: "absent", input: null, available: false, unavailable_reason: "model_unknown" });
    expect(f.fake.requests).toHaveLength(0);
  });

  it("switches the same live agent, persists before a first turn, and resumes exact choice", async () => {
    const f = await fixture();
    const originalAgent = f.session.session;
    const initial = f.service.modelState("test");
    const result = await f.service.selectModel("test", f.vision, initial.revision);
    expect(f.session.session).toBe(originalAgent);
    expect(result).toMatchObject({ state: "ready", current: { ...f.vision, input: ["text", "image"] }, selected: f.vision, pending_selection: null });
    expect(result.revision.version).toBe(initial.revision.version + 2);
    expect(f.session.session.model?.input).toContain("image");
    expect(loadSelection(f.session.sessionDir)).toEqual({ schema_version: 1, selected: f.vision, pending_selection: null });
    expect(statSync(path.join(f.session.sessionDir!, "model-selection.json")).mode & 0o777).toBe(0o600);
    expect(f.fake.requests).toHaveLength(0);
    await f.service.dispose("test");
    const next = f.makeService();
    const reopened = await next.resume({ profile: "orchestrator", projectRoot: f.dir, sessionId: "test" });
    expect(reopened.session.model?.id).toBe(f.vision.model_id);
    expect(next.modelState("test").revision.epoch).not.toBe(initial.revision.epoch);
  });

  it("refuses run-in-flight before mutation, including a registered idle-looking run", async () => {
    const f = await fixture();
    const state = f.service.modelState("test");
    f.service.beginRun("test", "holding", state.revision);
    expect(f.session.session.isIdle).toBe(true);
    await expect(f.service.selectModel("test", f.vision, state.revision)).rejects.toMatchObject({ data: { reason: "run_in_flight", run_id: "holding", scope: "session" } });
    expect(f.service.modelState("test")).toEqual(state);
    f.service.endRun("holding");
  });

  it("reserves before the first await; GET describes changing; other sessions stay usable", async () => {
    const f = await fixture();
    const other = await f.service.create({ profile: "orchestrator", projectRoot: f.dir, sessionId: "other", model: f.text });
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const actual = f.session.session.setModel.bind(f.session.session);
    vi.spyOn(f.session.session, "setModel").mockImplementation(async model => { await gate; await actual(model); });
    const revision = f.service.modelState("test").revision;
    const pending = f.service.selectModel("test", f.vision, revision);
    expect(f.service.modelState("test")).toMatchObject({ state: "changing", pending_selection: f.vision, current: f.text });
    expect(() => f.service.beginRun("test", "loser", revision)).toThrow("model change in progress");
    await expect(f.service.selectModel("test", f.text, revision)).rejects.toMatchObject({ data: { reason: "model_change_in_progress" } });
    f.service.beginRun(other.id, "other-run");
    f.service.endRun("other-run");
    release();
    await pending;
    expect(() => f.service.beginRun("test", "stale", revision)).toThrow("Review it before sending");
  });

  it("A-B-A never revives an old revision and reads don't bump versions", async () => {
    const f = await fixture();
    const initial = f.service.modelState("test");
    const b = await f.service.selectModel("test", f.vision, initial.revision);
    const a = await f.service.selectModel("test", f.text, b.revision);
    expect(a.current).toEqual(initial.current);
    expect(f.service.modelState("test").revision).toEqual(a.revision);
    await expect(f.service.selectModel("test", f.vision, initial.revision)).rejects.toMatchObject({ data: { reason: "model_changed" } });
  });

  it("unknown/undeclared choices refuse and never change the default or persisted selection", async () => {
    const f = await fixture();
    const before = readFileSync(path.join(f.session.sessionDir!, "model-selection.json"), "utf8");
    await expect(f.service.selectModel("test", { ...f.text, model_id: "absent" }, f.service.modelState("test").revision)).rejects.toMatchObject({ data: { reason: "model_unknown" } });
    expect(readFileSync(path.join(f.session.sessionDir!, "model-selection.json"), "utf8")).toBe(before);
    await f.service.selectModel("test", f.vision, f.service.modelState("test").revision);
    expect(f.resolver.document().proposed_default).toMatchObject(f.text);
  });

  it("pending intent resumes uncertain without instantiating either choice; explicit selection reconciles", async () => {
    const f = await fixture();
    saveSelection(f.session.sessionDir, { schema_version: 1, selected: f.text, pending_selection: f.vision });
    await f.service.dispose("test");
    const next = f.makeService();
    const restored = await next.resume({ profile: "orchestrator", projectRoot: f.dir, sessionId: "test" });
    expect(restored.liveSession).toBeUndefined();
    expect(next.modelState("test")).toMatchObject({ state: "uncertain", current: null, selected: f.text, pending_selection: f.vision });
    expect(() => next.beginRun("test", "nope")).toThrow();
    await next.selectModel("test", f.vision, next.modelState("test").revision);
    expect(next.modelState("test")).toMatchObject({ state: "ready", current: f.vision });
  });

  it("unavailable persisted choice retains history handle without fallback", async () => {
    const f = await fixture();
    const unavailable = { ...f.text, model_id: "removed" };
    saveSelection(f.session.sessionDir, { schema_version: 1, selected: unavailable, pending_selection: null });
    await f.service.dispose("test");
    const next = f.makeService();
    const restored = await next.resume({ profile: "orchestrator", projectRoot: f.dir, sessionId: "test" });
    expect(restored.liveSession).toBeUndefined();
    expect(restored.piSessionManager.getEntries()).toEqual([]);
    expect(next.modelState("test")).toMatchObject({ current: null, selected: unavailable, state: "unavailable", reason: "model_unknown" });
    await next.selectModel("test", f.vision, next.modelState("test").revision);
    expect(restored.session.model?.id).toBe(f.vision.model_id);
  });

  it("a partial SDK failure reports the changed live identity, not rollback, and blocks sending", async () => {
    const f = await fixture();
    const actual = f.session.session.setModel.bind(f.session.session);
    vi.spyOn(f.session.session, "setModel").mockImplementation(async model => { await actual(model); throw new Error("SECRET provider response"); });
    await expect(f.service.selectModel("test", f.vision, f.service.modelState("test").revision)).rejects.toMatchObject({ message: "model selection failed", data: { model_state: { state: "uncertain", current: f.vision, selected: f.text } } });
    expect(() => f.service.beginRun("test", "unsafe")).toThrow();
    expect(loadSelection(f.session.sessionDir)?.pending_selection).toEqual(f.vision);
    expect(JSON.stringify(f.service.modelState("test"))).not.toContain("SECRET");
  });

  it("a failed final persistence commit blocks Send and restart until explicit reconciliation", async () => {
    const f = await fixture();
    const save = selection.saveSelection;
    vi.spyOn(selection, "saveSelection").mockImplementation((dir, record) => {
      if (record.pending_selection === null) throw new Error("disk commit failed");
      save(dir, record);
    });
    await expect(f.service.selectModel("test", f.vision, f.service.modelState("test").revision))
      .rejects.toMatchObject({ data: { reason: "model_selection_failed", model_state: { state: "uncertain", current: f.vision, selected: f.text } } });
    expect(() => f.service.beginRun("test", "unsafe")).toThrow("model selection uncertain");
    expect(loadSelection(f.session.sessionDir)).toMatchObject({ selected: f.text, pending_selection: f.vision });
    vi.restoreAllMocks();
    await f.service.dispose("test");
    const next = f.makeService();
    const restored = await next.resume({ profile: "orchestrator", projectRoot: f.dir, sessionId: "test" });
    expect(restored.liveSession).toBeUndefined();
    expect(() => next.beginRun("test", "still-unsafe")).toThrow("model selection uncertain");
    await next.selectModel("test", f.vision, next.modelState("test").revision);
    expect(next.modelState("test")).toMatchObject({ state: "ready", current: f.vision });
  });

  it("unavailable re-adoption and explicit replacement retain the recorded transcript", async () => {
    const f = await fixture();
    await f.session.session.prompt("Recorded before model removal");
    const entries = f.session.piSessionManager.getEntries();
    expect(entries.some(e => e.type === "message" && e.message.role === "assistant")).toBe(true);
    saveSelection(f.session.sessionDir, { schema_version: 1, selected: { ...f.text, model_id: "removed" }, pending_selection: null });
    await f.service.dispose("test");
    const next = f.makeService();
    const restored = await next.resume({ profile: "orchestrator", projectRoot: f.dir, sessionId: "test" });
    expect(restored.liveSession).toBeUndefined();
    expect(restored.piSessionManager.getEntries()).toEqual(entries);
    await next.selectModel("test", f.vision, next.modelState("test").revision);
    expect(restored.piSessionManager.getEntries().slice(0, entries.length)).toEqual(entries);
    expect(restored.session.model?.id).toBe(f.vision.model_id);
  });

  it("malformed persisted metadata blocks rather than choosing a startup model", async () => {
    const f = await fixture();
    writeFileSync(path.join(f.session.sessionDir!, "model-selection.json"), "broken");
    await f.service.dispose("test");
    const next = f.makeService();
    await next.resume({ profile: "orchestrator", projectRoot: f.dir, sessionId: "test" });
    expect(next.modelState("test")).toMatchObject({ current: null, state: "uncertain" });
  });

  it("revalidates auth on selection and prompt, never using startup availability as authority", async () => {
    const f = await fixture();
    vi.spyOn(f.configured.runtime, "hasConfiguredAuth").mockReturnValue(false);
    expect(f.resolver.document().proposed_default).toBeNull();
    expect(() => f.service.beginRun("test", "no-auth")).toThrow();
    await expect(f.service.selectModel("test", f.vision, f.service.modelState("test").revision)).rejects.toMatchObject({ data: { reason: "model_unavailable", unavailable_reason: "provider_not_authenticated" } });
    expect(f.fake.requests).toHaveLength(0);
  });

  it.each([true, -1, 1.5, Number.MAX_SAFE_INTEGER + 1])("strictly refuses revision version %s", version => {
    expect(() => readRevision({ epoch: "test", version })).toThrow("invalid params");
  });
});
