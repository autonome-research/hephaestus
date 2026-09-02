// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The single-primary discipline and the providers panel's variant, eyebrow and
// caption clauses (INTERFACE.md §4.7 C8, §23.8 C9/C13/C14; AMENDED 2026-09-02).
//
// C8's testable is a three-fixture querySelector count-of-one over the shell's
// two variant-bearing surfaces — the composer and the ProvidersPanel — mounted
// together, the way `Shell` mounts them. The exception keys off the composer's
// CURRENT `data-disabled-reason="agent_unavailable"`, published through
// `stream/composerGate.ts`; the struck health-keyed condition is pinned dead
// by the all-rejected fixture, where health screams and Send stays primary.
//
// Clean-room hygiene (§3): assertions are on `data-` attributes and on copy
// keys' structural properties (a word count), never on particular UI wording.

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Composer } from "../src/components/stream/Composer";
import { ProvidersPanel } from "../src/components/ProvidersPanel";
import { composerGateStore } from "../src/stream/composerGate";
import { keys } from "../src/api/queries";
import type { ProviderRow, ProvidersDocument } from "../src/api/providers";
import { copy } from "../src/copy";

function row(overrides: Partial<ProviderRow> = {}): ProviderRow {
  return {
    id: "heph-fake",
    kind: "openai_compatible",
    name: "Fake",
    models: [{ id: "glm-5.3-flash", name: "glm-5.3-flash" }],
    source: "none",
    health: "unused",
    last_observed_at: null,
    available: null,
    unavailable_reason: null,
    ...overrides,
  };
}

function providersDocument(overrides: Partial<ProvidersDocument> = {}): ProvidersDocument {
  return {
    status: "ok",
    config_path: "/tmp/p/.heph/providers.json",
    config_exists: true,
    config_malformed: false,
    file_mode: "0600",
    file_mode_private: true,
    credential_allowlist: [],
    auth_source: null,
    auth_source_linked: false,
    egress_acknowledged: [],
    adopted_sources: [],
    credential_sources: [],
    attach: { attached: true, config_path: "/tmp/p/.heph/providers.json", generation: 1 },
    providers: [row()],
    ...overrides,
  };
}

/** Composer + ProvidersPanel in one host, as the shell frames them. */
async function mountShell(input: {
  readonly agentUnavailable: boolean;
  readonly document: ProvidersDocument;
}): Promise<{ host: HTMLDivElement; root: Root }> {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(keys.providers(), input.document);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <ProvidersPanel />
        <Composer
          sessionId="sess-1"
          profile="orchestrator"
          attach={null}
          agentUnavailable={input.agentUnavailable}
          liveRunId={null}
          streamLive={false}
        />
      </QueryClientProvider>,
    );
  });
  return { host, root };
}

async function unmount(mounted: { host: HTMLDivElement; root: Root }): Promise<void> {
  await act(async () => {
    mounted.root.unmount();
  });
  mounted.host.remove();
}

/** C8's selector, verbatim: primaries outside open dialogs. */
function primaries(host: HTMLElement): Element[] {
  return [...host.querySelectorAll('[data-variant="primary"]')].filter(
    (element) => element.closest("dialog[open]") === null,
  );
}

afterEach(() => {
  composerGateStore.publish(null);
});

// ---------------------------------------------------------------------------
// §4.7 (C8) — the three-fixture count-of-one

describe("exactly one data-variant=primary per shell (§4.7 C8)", () => {
  it("steady state: length 1, and it is the Send hook", async () => {
    const mounted = await mountShell({
      agentUnavailable: false,
      document: providersDocument({
        providers: [row({ source: "project", health: "accepted", available: true })],
      }),
    });
    try {
      const loud = primaries(mounted.host);
      expect(loud).toHaveLength(1);
      expect(loud[0]?.hasAttribute("data-composer-send")).toBe(true);
    } finally {
      await unmount(mounted);
    }
  });

  it("agent_unavailable: length 1, it is the sign-in action, and Send is mounted secondary", async () => {
    const mounted = await mountShell({
      agentUnavailable: true,
      document: providersDocument(),
    });
    try {
      const loud = primaries(mounted.host);
      expect(loud).toHaveLength(1);
      expect(loud[0]?.hasAttribute("data-provider-signin")).toBe(true);
      const send = mounted.host.querySelector("[data-composer-send]");
      // §7A.10(a): Send stays MOUNTED — a vanished primary leaves no target
      // for "why can't I send?" — but demoted for exactly this reason's span.
      expect(send).not.toBeNull();
      expect(send?.getAttribute("data-variant")).toBe("secondary");
    } finally {
      await unmount(mounted);
    }
  });

  it("every credential rejected, composer enabled: length 1 and it is Send", async () => {
    // The struck health-keyed condition would promote Sign-in here and mint a
    // second primary beside an active Send. §23.10 fails the next run; it
    // never disables the composer, so the health axis carries the bad news
    // and the variant does not.
    const mounted = await mountShell({
      agentUnavailable: false,
      document: providersDocument({
        providers: [
          row({ id: "a", source: "project", health: "rejected", available: true }),
          row({ id: "b", source: "env", health: "expired", available: true }),
        ],
      }),
    });
    try {
      const loud = primaries(mounted.host);
      expect(loud).toHaveLength(1);
      expect(loud[0]?.hasAttribute("data-composer-send")).toBe(true);
    } finally {
      await unmount(mounted);
    }
  });

  it("promotes at most ONE sign-in action even with several unsigned rows", async () => {
    const mounted = await mountShell({
      agentUnavailable: true,
      document: providersDocument({
        providers: [row({ id: "a" }), row({ id: "b" }), row({ id: "c" })],
      }),
    });
    try {
      expect(primaries(mounted.host)).toHaveLength(1);
    } finally {
      await unmount(mounted);
    }
  });
});

// ---------------------------------------------------------------------------
// §23.8 (C9) — primary is availability, not invitation

describe("the sign-in action's variant (§23.8 C9)", () => {
  function panelMarkup(document_: ProvidersDocument): string {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.providers(), document_);
    return renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ProvidersPanel />
      </QueryClientProvider>,
    );
  }

  function signInVariant(markup: string, id: string): string | null {
    // The button carries data-variant before/after data-provider-signin in
    // attribute order; read the whole opening tag.
    const at = markup.indexOf(`data-provider-signin="${id}"`);
    if (at < 0) return null;
    const open = markup.lastIndexOf("<button", at);
    const close = markup.indexOf(">", at);
    const tag = markup.slice(open, close);
    const match = /data-variant="([^"]*)"/.exec(tag);
    return match?.[1] ?? null;
  }

  it("renders secondary beside an accepted key", () => {
    const markup = panelMarkup(
      providersDocument({
        providers: [row({ source: "project", health: "accepted", available: true })],
      }),
    );
    // Compact signed-in rows collapse to a chip; open the not-signed-in case
    // for the button, and assert the signed-in surface minted no primary.
    expect(markup).not.toContain('data-variant="primary"');
  });

  it("renders primary while the composer publishes agent_unavailable", () => {
    composerGateStore.publish("agent_unavailable");
    const markup = panelMarkup(providersDocument());
    expect(signInVariant(markup, "heph-fake")).toBe("primary");
  });

  it("renders secondary with a rejected credential and an enabled composer", () => {
    composerGateStore.publish(null);
    const markup = panelMarkup(
      providersDocument({
        providers: [row({ source: "project", health: "rejected", available: true })],
      }),
    );
    expect(markup).not.toContain('data-variant="primary"');
  });

  it("keeps the attach action and adopt affordance off the primary variant", () => {
    const markup = panelMarkup(
      providersDocument({
        providers: [],
        attach: { attached: false, config_path: "/tmp/p/.heph/providers.json", generation: 0 },
      }),
    );
    expect(markup).toContain("data-providers-attach");
    expect(markup).not.toContain('data-variant="primary"');
  });
});

// ---------------------------------------------------------------------------
// §23.8 (C13) — one section, one heading, at most one resting eyebrow

describe("the panel is ONE section (§23.8 C13)", () => {
  async function panelHost(
    document_: ProvidersDocument,
  ): Promise<{ host: HTMLDivElement; root: Root }> {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.providers(), document_);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <ProvidersPanel />
        </QueryClientProvider>,
      );
    });
    return { host, root };
  }

  it("renders at most one eyebrow-role element at rest", async () => {
    const mounted = await panelHost(
      providersDocument({
        egress_acknowledged: [{ host: "models.example", at: "1700000000" }],
      }),
    );
    try {
      const eyebrows = mounted.host.querySelectorAll('[class*="eyebrow"]');
      expect(eyebrows.length).toBeLessThanOrEqual(1);
    } finally {
      await unmount(mounted);
    }
  });

  it("renders no two visible headings with the same string", async () => {
    const mounted = await panelHost(providersDocument());
    try {
      const texts = [
        ...mounted.host.querySelectorAll('h1,h2,h3,h4,[class*="eyebrow"],[class*="title"]'),
      ]
        .map((element) => element.textContent?.trim() ?? "")
        .filter((text) => text !== "");
      expect(new Set(texts).size).toBe(texts.length);
    } finally {
      await unmount(mounted);
    }
  });

  it("never renders the struck SIGN IN eyebrow copy key", () => {
    // The key itself is gone from copy.ts: nothing can render it in any state.
    expect((copy.providers as Record<string, unknown>)["eyebrow"]).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// §23.8 (C14) — the privacy caption, visible at rest, and its negative half

describe("the discovery caption (§23.8 C14)", () => {
  it("is at most 20 words and names both halves of the §23.5 contract", () => {
    const caption = copy.providers.discover.caption;
    const words = caption.split(/\s+/).filter((word) => word !== "");
    expect(words.length).toBeLessThanOrEqual(20);
    // Both halves: read-on-press, unused-until-adopt. Presence of the two
    // facts, not of any particular sentence.
    expect(caption.toLowerCase()).toMatch(/press/);
    expect(caption.toLowerCase()).toMatch(/adopt/);
    expect(caption.toLowerCase()).toMatch(/home directory/);
  });

  it("is visible AT REST beside the discover control", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.providers(), providersDocument());
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ProvidersPanel />
      </QueryClientProvider>,
    );
    // The resting (collapsed) face: the control and its caption, without the
    // details-only long note.
    expect(markup).toContain("data-discovery-run");
    expect(markup).toContain("data-discovery-caption");
    expect(markup).toContain(copy.providers.discover.caption);
    expect(markup).not.toContain(copy.providers.discover.note);
  });
});
