// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelPicker } from "../../src/components/stream/ModelPicker";
import { Composer } from "../../src/components/stream/Composer";
import { WorkspaceError } from "../../src/api/client";
import { fetchSessionModel, selectSessionModel, sendPrompt, createSession, isSessionModelState, type SessionModelDocument } from "../../src/api/sessions";
import type * as Sessions from "../../src/api/sessions";
import type * as Providers from "../../src/api/providers";
import { isModelRevision, loadCatalog, loadModels, loadProviders, registerProvider, submitKey, type ProviderRow, type ProvidersDocument } from "../../src/api/providers";
import { canSelectModel, changeSessionModel, conversationStore, createConversationStore, currentTurn, readSessionModel } from "../../src/stream/conversation";
import { filterModels, sameModel } from "../../src/stream/composerChrome";
import { idleExecution, modelDoc, models, modelState, spark, vision } from "../fixtures/models";

vi.mock("../../src/api/sessions", async original => ({ ...await original<typeof Sessions>(),
  fetchSessionModel: vi.fn(), selectSessionModel: vi.fn(), sendPrompt: vi.fn(), createSession: vi.fn(),
}));
vi.mock("../../src/api/providers", async original => ({
  ...await original<typeof Providers>(),
  loadModels: vi.fn(async () => models),
  loadProviders: vi.fn(),
  loadCatalog: vi.fn(),
  registerProvider: vi.fn(),
  submitKey: vi.fn(),
}));
let declaredProviders: ProviderRow[] = [];
const providerDocument = (): ProvidersDocument => ({
  status: "ok", config_path: "/project/.heph/providers.json", config_exists: declaredProviders.length > 0,
  config_malformed: false, file_mode: declaredProviders.length > 0 ? "0600" : null,
  file_mode_private: true, credential_allowlist: [], auth_source: null, auth_source_linked: false,
  egress_acknowledged: [], adopted_sources: [], credential_sources: [],
  attach: { attached: true, config_path: "/project/.heph/providers.json", generation: 1 },
  providers: declaredProviders,
});
let teardown = () => {};
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  conversationStore.reset();
  vi.mocked(fetchSessionModel).mockImplementation(async sid => modelDoc(sid));
  vi.mocked(selectSessionModel).mockReset();
  vi.mocked(sendPrompt).mockReset();
  vi.mocked(createSession).mockReset();
  declaredProviders = [];
  vi.mocked(loadModels).mockClear();
  vi.mocked(loadProviders).mockReset();
  vi.mocked(loadCatalog).mockReset();
  vi.mocked(registerProvider).mockReset();
  vi.mocked(submitKey).mockReset();
  vi.mocked(loadProviders).mockImplementation(async () => providerDocument());
  vi.mocked(loadCatalog).mockResolvedValue({ status: "ok", catalog: [
    { id: "anthropic", name: "Anthropic", auth_methods: [
      { type: "subscription", label: "Claude Pro/Max subscription" },
      { type: "api_key", label: "API key" },
    ], models: [{ id: "claude-sonnet", name: "Claude Sonnet", input: ["text", "image"], reasoning: true }] },
    { id: "xai", name: "xAI", auth_methods: [{ type: "api_key", label: "API key" }],
      models: [{ id: "grok", name: "Grok", input: ["text"], reasoning: false }] },
  ] });
  vi.mocked(submitKey).mockResolvedValue({ status: "ok", provider_id: "xai", scope: "serve", replaced: "none" });
  vi.mocked(registerProvider).mockImplementation(async (providerId, authType) => {
    const provider: ProviderRow = { id: providerId, kind: "pi_native", name: "Anthropic",
      models: [{ id: "claude-sonnet", name: "Claude Sonnet" }], source: "none", health: "unused",
      last_observed_at: null, available: false, unavailable_reason: "provider_not_authenticated" };
    declaredProviders = [...declaredProviders, provider];
    return { status: "ok", provider: { id: providerId, kind: "pi_native", models: [{ id: "claude-sonnet" }] }, auth_type: authType };
  });
});
afterEach(() => { act(teardown); document.body.replaceChildren(); conversationStore.reset(); });
function ready(sid = "a") { conversationStore.modelSnapshot(sid, modelState, idleExecution, conversationStore.ticket()); }
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
function mount(composer = false, sid: string | null = "a") {
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => root.render(<QueryClientProvider client={client}>{composer
    ? <Composer sessionId={sid} profile="orchestrator" attach={null} agentUnavailable={false} liveRunId={null} streamLive />
    : <ModelPicker sessionId={sid} />}</QueryClientProvider>));
  teardown = () => { root.unmount(); client.clear(); };
  return host;
}
function key(el: Element, value: string) {
  act(() => { el.dispatchEvent(new KeyboardEvent("keydown", { key: value, bubbles: true, cancelable: true })); });
}
function click(el: Element | null) { act(() => { (el as HTMLElement).click(); }); }
function input(el: HTMLInputElement, value: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const switched = modelDoc("a", { ...modelState, revision: { ...modelState.revision, version: 2 }, current: vision,
  selected: { provider_id: vision.provider_id, model_id: vision.model_id } });

describe("model wire and shared state", () => {
  it("requires every named absence and strict revision integers", () => {
    expect(isSessionModelState(modelState)).toBe(true);
    const { pending_selection: _pending, ...missing } = modelState;
    expect(isSessionModelState(missing)).toBe(false);
    for (const version of [true, false, -1, 1.1, "1", NaN, Infinity]) expect(isModelRevision({ epoch: "e", version })).toBe(false);
    expect(isModelRevision({ epoch: "e", version: 0 })).toBe(true);
  });
  it("preserves pair boundaries, unknown declarations, and search by name/provider/id", () => {
    expect(sameModel({ provider_id: "a/b", model_id: "c" }, { provider_id: "a", model_id: "b/c" })).toBe(false);
    expect(filterModels(models, "IMAGE")[0]?.models[0]?.model_id).toBe(vision.model_id);
    expect(filterModels(models, "Local fake")[0]?.models).toHaveLength(3);
    expect(filterModels(models, "unknown")[0]?.models[0]).toMatchObject({ available: false, input: null, unavailable_reason: "model_unknown" });
  });
  it("does not substitute a proposal on catalog refresh or existing-session changes", () => {
    const store = createConversationStore(); store.catalog(models);
    store.modelSnapshot("a", modelState, idleExecution, store.ticket());
    store.catalog({ ...models, proposed_default: spark, providers: [{ ...models.providers[0]!, models: [] }] });
    expect(store.get(null).proposal).toMatchObject({ model_id: vision.model_id, available: false });
    expect(store.get("a").model?.current).toEqual(spark);

    // First-provider success can turn null into a server default. A refresh
    // still cannot choose that model or consume the new-conversation draft.
    const firstProvider = createConversationStore();
    firstProvider.catalog({ ...models, providers: [], proposed_default: null });
    firstProvider.draft(null, "keep the new-session draft");
    firstProvider.catalog(models);
    expect(firstProvider.get(null).proposal).toBeNull();
    expect(firstProvider.get(null).draft.text).toBe("keep the new-session draft");
  });
  it("rejects pre-write, out-of-order, old-epoch reads and A→B→A old versions", () => {
    const store = createConversationStore();
    store.modelSnapshot("a", modelState, idleExecution, store.ticket());
    const old = store.ticket();
    expect(store.beginModel("a")).toEqual(modelState.revision);
    store.modelSnapshot("a", modelState, idleExecution, old);
    expect(store.get("a").modelPending).toBe(true);
    const newest = { ...modelState, revision: { epoch: "new", version: 0 } };
    store.modelSnapshot("a", newest, idleExecution, store.ticket());
    store.modelSnapshot("a", modelState, idleExecution, old);
    expect(store.get("a").model).toEqual(newest);
    store.modelSnapshot("a", { ...newest, revision: { epoch: "new", version: 4 } }, idleExecution, store.ticket());
    store.modelSnapshot("a", newest, idleExecution, store.ticket());
    expect(store.get("a").model?.revision.version).toBe(4);
  });
  it("reserves synchronously without settling attempts or losing history, drafts, or other sessions", async () => {
    ready(); ready("b"); conversationStore.draft("a", "keep me");
    const before = conversationStore.get("a"); const wait = deferred<SessionModelDocument>();
    vi.mocked(selectSessionModel).mockReturnValue(wait.promise);
    const change = changeSessionModel("a", vision);
    expect(conversationStore.begin("a")).toBeNull();
    expect(conversationStore.beginModel("a")).toBeNull();
    expect(currentTurn(conversationStore.get("b")).canSend).toBe(true);
    wait.resolve(switched); await change;
    const after = conversationStore.get("a");
    expect(after.draft).toBe(before.draft); expect(after.history).toBe(before.history);
    expect(after.live).toBe(before.live); expect(after.attempt).toBe(before.attempt);
    expect(after.model?.current).toEqual(vision); expect(currentTurn(after).canSend).toBe(true);
    expect(conversationStore.get("b").model?.current).toEqual(spark);
  });
  it("refuses switching during active/awaiting-answer, checking, and pending send evidence", () => {
    ready(); conversationStore.snapshot("a", { ...idleExecution, run_id: "run", active_run_id: "run", admission_available: false }, conversationStore.ticket());
    expect(canSelectModel(conversationStore.get("a"))).toBe(false);
    ready(); conversationStore.begin("a"); expect(conversationStore.beginModel("a")).toBeNull();
    ready("b"); conversationStore.transport("b", "reconnecting"); expect(conversationStore.beginModel("b")).toBeNull();
  });
  it("keeps saved unavailable identity, permits explicit repair, and never enables unsafe sends", () => {
    const state = { ...modelState, current: null, state: "unavailable" as const, reason: "model_unknown" };
    conversationStore.modelSnapshot("a", state, { ...idleExecution, admission_available: false }, conversationStore.ticket());
    expect(currentTurn(conversationStore.get("a")).canSend).toBe(false);
    expect(canSelectModel(conversationStore.get("a"))).toBe(true);
    const host = mount();
    const button = host.querySelector("[data-model-button]");
    expect(button?.getAttribute("title")).toContain("Saved selection (not active): local/fake/spark");
    expect(button?.getAttribute("title")).toContain("Capability unknown");
    expect(host.textContent).toContain("model_unknown");
  });
  it("does not confuse unavailable-model repair with unresolved execution ownership", () => {
    const unavailable = { ...modelState, current: null, state: "unavailable" as const, reason: "model_unknown" };
    const store = createConversationStore();
    const execution = { ...idleExecution, run_id: "unresolved", admission_available: false };
    store.modelSnapshot("a", unavailable, execution, store.ticket());
    expect(canSelectModel(store.get("a"))).toBe(false);
    store.modelSnapshot("a", unavailable, { ...execution, version: 2,
      terminal: { run_id: "other", terminal_id: "t", state: "completed", payload: {} } }, store.ticket());
    expect(canSelectModel(store.get("a"))).toBe(false);
    store.modelSnapshot("a", unavailable, { ...execution, version: 3,
      terminal: { run_id: "unresolved", terminal_id: "t2", state: "completed", payload: {} } }, store.ticket());
    expect(canSelectModel(store.get("a"))).toBe(true);
    expect(currentTurn(store.get("a")).canSend).toBe(false);
  });
  it("reads after lost mutation once, keeps changing/uncertain blocked, never retries the write", async () => {
    ready(); conversationStore.draft("a", "still here");
    vi.mocked(selectSessionModel).mockRejectedValue(new Error("lost response"));
    vi.mocked(fetchSessionModel).mockResolvedValue(modelDoc("a", { ...modelState, state: "changing", pending_selection: vision,
      revision: { ...modelState.revision, version: 1 } }, { ...idleExecution, admission_available: false }));
    await changeSessionModel("a", vision);
    expect(selectSessionModel).toHaveBeenCalledTimes(1); expect(fetchSessionModel).toHaveBeenCalledTimes(1);
    expect(currentTurn(conversationStore.get("a")).canSend).toBe(false);
    expect(conversationStore.get("a").draft.text).toBe("still here");
    vi.mocked(fetchSessionModel).mockResolvedValue(modelDoc("a", { ...switched.model_state, state: "uncertain", reason: "model_selection_uncertain" }, { ...idleExecution, admission_available: false }));
    await readSessionModel("a"); expect(currentTurn(conversationStore.get("a")).canSend).toBe(false);
    expect(canSelectModel(conversationStore.get("a"))).toBe(true);
  });
  it("keeps top-level conflict identity even if reconciliation fails and preserves the draft", async () => {
    ready(); conversationStore.draft("a", "do not resend");
    vi.mocked(selectSessionModel).mockRejectedValue(new WorkspaceError(409, "model_changed", "changed", {
      session_id: "a", model_state: switched.model_state, execution: switched.execution,
    }));
    vi.mocked(fetchSessionModel).mockRejectedValue(new Error("offline"));
    await changeSessionModel("a", vision);
    expect(conversationStore.get("a").model?.current).toEqual(vision);
    expect(conversationStore.get("a").draft.text).toBe("do not resend");
    expect(currentTurn(conversationStore.get("a")).canSend).toBe(false); expect(sendPrompt).not.toHaveBeenCalled();
  });
});

describe("model control interaction", () => {
  it("shows Spark even when vision is first; arrows do not mutate, Enter confirms, Escape restores focus", async () => {
    ready(); const host = mount(); await act(async () => {});
    const button = host.querySelector<HTMLElement>("[data-model-button]")!;
    expect(button.textContent).toContain("Spark");
    expect(button.getAttribute("title")).toContain("local/fake/spark");
    expect(button.getAttribute("title")).toContain("Text only");
    button.focus(); click(button); await act(async () => {});
    expect(document.activeElement?.getAttribute("role")).toBe("option");
    expect(host.querySelector('[role="option"][aria-selected="true"]')?.textContent).toContain("Spark");
    key(document.activeElement!, "ArrowDown"); expect(selectSessionModel).not.toHaveBeenCalled();
    key(document.activeElement!, "Escape"); expect(host.querySelector('[data-model-control] [role="group"]')).toBeNull(); expect(document.activeElement).toBe(button);
    click(button); await act(async () => {});
    vi.mocked(selectSessionModel).mockResolvedValue(switched);
    key(document.activeElement!, "Enter"); await act(async () => {});
    expect(selectSessionModel).toHaveBeenCalledWith("a", { model: { provider_id: vision.provider_id, model_id: vision.model_id }, expected_model_revision: modelState.revision });
    expect(button.getAttribute("title")).toContain("Text + images"); expect(createSession).not.toHaveBeenCalled(); expect(sendPrompt).not.toHaveBeenCalled();
  });
  it("stages auth method before provider and never changes the model automatically", async () => {
    ready(); const host = mount(); await act(async () => {});
    click(host.querySelector("[data-model-button]"));
    click(host.querySelector("[data-add-provider]"));
    await act(async () => {});
    expect(host.querySelector("[data-add-provider-methods]")).not.toBeNull();
    expect(host.querySelector("[data-add-provider-option]")).toBeNull();
    click(host.querySelector('[data-add-provider-method="subscription"]'));
    expect(host.querySelector('[data-add-provider-option="anthropic"]')).not.toBeNull();
    expect(host.querySelector('[data-add-provider-option="xai"]')).toBeNull();
    expect(document.activeElement).toBe(host.querySelector('[data-add-provider-option="anthropic"]'));
    click(host.querySelector('[data-add-provider-option="anthropic"]'));
    await act(async () => {});
    expect(registerProvider).toHaveBeenCalledWith("anthropic", "subscription");
    expect(host.querySelector('[data-signin-begin="auto"]')).not.toBeNull();
    expect(host.querySelector('[data-signin-mode="key"]')).toBeNull();
    expect(selectSessionModel).not.toHaveBeenCalled();
    expect(conversationStore.get("a").model?.current).toEqual(spark);
  });

  it("keeps model and draft on add failure; Back owns no auth flow", async () => {
    ready(); conversationStore.draft("a", "preserve me");
    vi.mocked(registerProvider).mockRejectedValueOnce(new WorkspaceError(409, "provider_already_registered", "collision"));
    const host = mount(); await act(async () => {});
    click(host.querySelector("[data-model-button]"));
    click(host.querySelector("[data-add-provider]")); await act(async () => {});
    click(host.querySelector('[data-add-provider-method="subscription"]'));
    click(host.querySelector("[data-add-provider-back]"));
    expect(host.querySelector("[data-add-provider-methods]")).not.toBeNull();
    expect(document.activeElement).toBe(host.querySelector('[data-add-provider-method="subscription"]'));
    expect(registerProvider).not.toHaveBeenCalled();
    click(host.querySelector('[data-add-provider-method="subscription"]'));
    click(host.querySelector('[data-add-provider-option="anthropic"]'));
    await act(async () => {});
    expect(host.querySelector("[data-add-provider-error]")).not.toBeNull();
    expect(conversationStore.get("a").model?.current).toEqual(spark);
    expect(conversationStore.get("a").draft.text).toBe("preserve me");
    expect(selectSessionModel).not.toHaveBeenCalled();
  });

  it("refreshes after fake API-key success without choosing a model or consuming the draft", async () => {
    ready(); conversationStore.draft("a", "still here");
    const host = mount(); await act(async () => {});
    const initialCatalogReads = vi.mocked(loadModels).mock.calls.length;
    click(host.querySelector("[data-model-button]"));
    click(host.querySelector("[data-add-provider]")); await act(async () => {});
    click(host.querySelector('[data-add-provider-method="api_key"]'));
    click(host.querySelector('[data-add-provider-option="xai"]'));
    await act(async () => {});
    input(host.querySelector<HTMLInputElement>("[data-signin-key]")!, "fake-loopback-key");
    click(host.querySelector('[data-signin-scope="serve"]'));
    click(host.querySelector("[data-signin-submit]"));
    await act(async () => {});
    expect(submitKey).toHaveBeenCalledWith("xai", "fake-loopback-key", "serve", false);
    expect(vi.mocked(loadModels).mock.calls.length).toBeGreaterThan(initialCatalogReads);
    expect(conversationStore.get("a").model?.current).toEqual(spark);
    expect(conversationStore.get("a").draft.text).toBe("still here");
    expect(selectSessionModel).not.toHaveBeenCalled();
  });

  it("blocks Enter and form submit synchronously during the selection without erasing text", async () => {
    ready(); conversationStore.draft("a", "retain draft"); const host = mount(true);
    const wait = deferred<SessionModelDocument>(); vi.mocked(selectSessionModel).mockReturnValue(wait.promise);
    let change!: Promise<void>; act(() => { change = changeSessionModel("a", vision); });
    key(host.querySelector("textarea")!, "Enter");
    act(() => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(sendPrompt).not.toHaveBeenCalled(); expect(host.querySelector("textarea")?.value).toBe("retain draft");
    await act(async () => { wait.resolve(switched); await change; });
    vi.mocked(sendPrompt).mockReturnValue(new Promise(() => {}));
    key(host.querySelector("textarea")!, "Enter");
    expect(sendPrompt).toHaveBeenCalledWith("a", "retain draft", null, switched.model_state.revision, {
      interaction_mode: "modeling", dfm_mode: "off", thinking_level: "medium",
    });
  });
  it("never first-sends under a creation response that substituted another model", async () => {
    conversationStore.catalog(models); conversationStore.draft(null, "keep the proposed pair");
    vi.mocked(createSession).mockResolvedValue({ ...modelDoc("new"), profile: "orchestrator", part: null, resumed: false });
    const host = mount(true, null);
    key(host.querySelector("textarea")!, "Enter"); await act(async () => {});
    expect(createSession).toHaveBeenCalledWith("orchestrator", null, expect.objectContaining({ model_id: vision.model_id }));
    expect(sendPrompt).not.toHaveBeenCalled();
    expect(conversationStore.get("new").draft.text).toBe("keep the proposed pair");
    expect(conversationStore.get("new").attempt?.reason).toBe("model_changed");
  });
  it("selects a fresh choice locally with the server default visible, without creating or sending", async () => {
    const host = mount(false, null); await act(async () => {});
    const button = host.querySelector("[data-model-button]");
    expect(button?.getAttribute("title")).toContain("Proposed default");
    expect(button?.getAttribute("title")).toContain("Text + images");
    click(host.querySelector("[data-model-button]")); await act(async () => {});
    click([...host.querySelectorAll('[role="option"]')].find(el => el.textContent?.includes("Spark"))!);
    expect(conversationStore.get(null).proposal?.model_id).toBe("spark");
    expect(createSession).not.toHaveBeenCalled(); expect(selectSessionModel).not.toHaveBeenCalled(); expect(sendPrompt).not.toHaveBeenCalled();
  });
});
