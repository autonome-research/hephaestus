// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as providers from "../src/api/providers";
import type { ProviderRow, ProvidersDocument } from "../src/api/providers";
import { keys } from "../src/api/queries";
import { ProvidersPanel } from "../src/components/ProvidersPanel";
import { copy } from "../src/copy";

vi.mock("../src/api/providers", async (original) => ({
  ...await original<typeof providers>(),
  loadProviders: vi.fn(),
  discover: vi.fn(),
  adopt: vi.fn(),
  unlinkAuthSource: vi.fn(),
  signOut: vi.fn(),
}));

function provider(overrides: Partial<ProviderRow> = {}): ProviderRow {
  return {
    id: "openai-codex", name: "openai-codex", kind: "pi_native",
    models: [{ id: "catalog-model", name: "Catalog model" }],
    source: "linked", health: "unused", last_observed_at: null,
    available: false, unavailable_reason: "model_unknown", ...overrides,
  };
}

function documentFor(rows = [provider()], linked = true): ProvidersDocument {
  return {
    status: "ok", config_path: "/project/.heph/providers.json",
    config_exists: true, config_malformed: false,
    file_mode: "0600", file_mode_private: true, credential_allowlist: [],
    auth_source: linked ? "/home/operator/.pi/agent/auth.json" : null,
    auth_source_linked: linked, egress_acknowledged: [], adopted_sources: [],
    credential_sources: [],
    attach: { attached: true, config_path: "/project/.heph/providers.json", generation: 1 },
    providers: rows,
  };
}

let root: Root | undefined;
let host: HTMLDivElement;
let client: QueryClient;

async function mount(doc: ProvidersDocument, onAttached = vi.fn()): Promise<void> {
  vi.mocked(providers.loadProviders).mockResolvedValue(doc);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(keys.providers(), doc);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(<QueryClientProvider client={client}><ProvidersPanel onAttached={onAttached} /></QueryClientProvider>);
  });
}

async function click(selector: string): Promise<void> {
  const button = host.querySelector<HTMLButtonElement>(selector);
  expect(button, selector).not.toBeNull();
  await act(async () => { button?.click(); });
}

afterEach(() => {
  act(() => root?.unmount());
  root = undefined;
  host?.remove();
  client?.clear();
  vi.resetAllMocks();
});

describe("existing subscriptions have honest status and usable recovery controls", () => {
  it("shows the named catalog failure and discovery without opening configuration", async () => {
    await mount(documentFor());
    expect(host.querySelector('[data-provider-unavailable-reason="model_unknown"]')).not.toBeNull();
    expect(host.textContent).toContain(copy.providers.modelUnavailableNote);
    expect(host.querySelector("[data-discovery-run]")).not.toBeNull();
    expect(providers.discover).not.toHaveBeenCalled();
    expect(providers.adopt).not.toHaveBeenCalled();
  });

  it("does not hide a failed subscription's recovery when another provider works", async () => {
    await mount(documentFor([provider(), provider({ id: "other", available: true, unavailable_reason: null })]));
    expect(host.querySelector("[data-discovery-run]")).not.toBeNull();
  });

  it("explains sharing, omits irrelevant API-key variables, and never offers forbidden writes", async () => {
    await mount(documentFor());
    await click("[data-providers-details]");
    expect(host.querySelector('[data-source="providers.source"]')?.getAttribute("data-value")).toBe(copy.providers.source.linked);
    expect(host.textContent).toContain(copy.providers.authSourceLinked);
    expect(host.textContent).not.toContain(copy.providers.allowlist);
    expect(host.querySelector("[data-auth-unlink]")).not.toBeNull();
    expect(host.querySelector("[data-provider-signin]")).toBeNull();
    expect(host.querySelector("[data-provider-signout]")).toBeNull();
    expect(host.querySelector("[data-provider-write-blocked]")).not.toBeNull();
    expect(providers.unlinkAuthSource).not.toHaveBeenCalled();
    expect(providers.signOut).not.toHaveBeenCalled();
  });

  it("blocks all credential writes while linked, including non-native providers", async () => {
    await mount(documentFor([provider({ kind: "openai_compatible", source: "none" })]));
    expect(host.querySelector("[data-provider-signin]")).toBeNull();
    await click("[data-providers-details]");
    expect(host.querySelector("[data-provider-signin]")).toBeNull();
    expect(host.textContent).toContain(copy.providers.allowlist);
  });

  it("distinguishes an unchecked provider from a ready one without claiming credential health", async () => {
    await mount(documentFor([provider({ available: null, unavailable_reason: null })]));
    expect(host.querySelector('[data-provider-readiness="unknown"]')?.textContent).toContain(copy.providers.availabilityUnknown);
    expect(host.textContent).not.toContain(copy.providers.available);
    await click("[data-providers-details]");
    expect(host.querySelector('[data-source="providers.health"]')?.getAttribute("data-value")).toBe("unused");
  });

  it("names subscription reauthentication rather than API-key replacement", async () => {
    await mount(documentFor([provider({ source: "project" })], false));
    await click("[data-providers-details]");
    const signIn = host.querySelector("[data-provider-signin]");
    expect(signIn?.textContent).toBe(copy.providers.subscriptionSignIn);
    expect(signIn?.textContent).not.toBe(copy.providers.rotate);
  });

  it("shows partial readiness and names unsupported models without deleting declarations", async () => {
    await mount(documentFor([provider({
      available: true, unavailable_reason: null,
      models: [{ id: "known", name: "Known" }, { id: "newer", name: "Newer" }],
      unavailable_models: [{ id: "newer", unavailable_reason: "model_unknown" }],
    })]));
    expect(host.querySelector('[data-provider-readiness="partial"]')?.textContent).toContain(copy.providers.partialAvailability);
    await click("[data-providers-details]");
    expect(host.querySelector('[data-provider-model-unavailable="newer"]')).not.toBeNull();
    expect(host.querySelector('[data-provider-model-unavailable="known"]')).toBeNull();
    expect(host.querySelectorAll('[data-source="providers.models.id"]')).toHaveLength(2);
  });

  it("retains key replacement for an app-owned API credential", async () => {
    await mount(documentFor([provider({ kind: "openai_compatible", source: "project" })], false));
    await click("[data-providers-details]");
    expect(host.querySelector("[data-provider-signin]")?.textContent).toBe(copy.providers.rotate);
    expect(host.querySelector("[data-provider-signout]")).not.toBeNull();
  });

  it.each([false, true])("only opens the agent after the adopted provider is usable (%s)", async (available) => {
    const onAttached = vi.fn();
    const doc = documentFor();
    await mount(doc, onAttached);
    const offer = {
      discovery_id: "opaque-handle", provider_id: "openai-codex", kind: "pi_auth" as const,
      model_ids: ["catalog-model"], source_path: "/home/operator/.pi/agent/auth.json",
    };
    vi.mocked(providers.discover).mockResolvedValue({ status: "ok", sources: [offer] });
    await click("[data-discovery-run]");
    expect(host.textContent).toContain(copy.providers.discover.subscriptionNote);
    expect(providers.adopt).not.toHaveBeenCalled();
    vi.mocked(providers.adopt).mockResolvedValue({
      status: "ok", adopted: offer, config_path: doc.config_path, file_mode: "0600", adopted_sources: [],
    });
    vi.mocked(providers.loadProviders).mockResolvedValue(documentFor([provider({ available, unavailable_reason: available ? null : "model_unknown" })]));
    await click("[data-discovery-adopt]");
    // Adoption sends only the server-issued handle, never a path or credential.
    expect(providers.adopt).toHaveBeenCalledExactlyOnceWith("opaque-handle");
    expect(onAttached).toHaveBeenCalledTimes(available ? 1 : 0);
    if (!available) expect(host.querySelector("[data-providers-expanded]")).not.toBeNull();
  });
});
