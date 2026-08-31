// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Leftover operator chrome at 1280×800. jsdom cannot measure pixels, so the
// assertions are on the CSS and DOM that make the measured defects impossible:
// a pinned composer last row, one-sentence empty-session create, a collapsed
// rail providers block, and a chip-width pin.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { keys } from "../src/api/queries";
import type { ProvidersDocument } from "../src/api/providers";
import { NewSessionAction } from "../src/components/stream/Composer";
import { ProvidersPanel } from "../src/components/ProvidersPanel";
import { CHIP_REF_WIDTH, formatRef } from "../src/system";
import { copy } from "../src/copy";

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = join(here, "..", "src");

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

function html(element: ReactElement): string {
  return renderToStaticMarkup(element);
}

const REF =
  "artifact:build:sha256:488c0e1a9f2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5";

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
    providers: [
      {
        id: "heph-fake",
        kind: "openai_compatible",
        name: "Fake",
        models: [{ id: "glm-5.3-flash", name: "glm-5.3-flash" }],
        source: "none",
        health: "unused",
        last_observed_at: null,
        available: null,
        unavailable_reason: null,
      },
    ],
    ...overrides,
  };
}

function providersMarkup(document: ProvidersDocument): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(keys.providers(), document);
  return html(
    <QueryClientProvider client={client}>
      <ProvidersPanel />
    </QueryClientProvider>,
  );
}

describe("stream column — composer is a pinned footer, not overflow", () => {
  const stream = css("components/stream/Stream.module.css");
  const shell = css("components/Shell.module.css");

  it("pins the composer as the last auto row under a shrinking main", () => {
    expect(stream).toMatch(
      /\.panel\s*\{[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto/,
    );
    expect(stream).toMatch(/\.main\s*\{[^}]*min-height:\s*0/);
    expect(stream).toMatch(/\.main\s*\{[^}]*overflow:\s*auto/);
    expect(stream).toMatch(/\.panel\s*\{[^}]*overflow:\s*hidden/);
  });

  it("keeps the stream column from growing the 800px shell", () => {
    expect(shell).toMatch(/\.body\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/);
    expect(shell).toMatch(/\.stream\s*\{[^}]*overflow:\s*hidden/);
    expect(shell).toMatch(/\.stream\s*\{[^}]*min-height:\s*0/);
  });

  it("keeps Send inside the composer, which is the panel's last child in source", () => {
    const panel = readFileSync(join(webSrc, "components/stream/StreamPanel.tsx"), "utf8");
    const composerIdx = panel.lastIndexOf("<Composer");
    const mainIdx = panel.lastIndexOf("data-stream-main");
    const sendSource = readFileSync(join(webSrc, "components/stream/Composer.tsx"), "utf8");
    expect(composerIdx).toBeGreaterThan(mainIdx);
    expect(sendSource).toContain("data-composer-send");
    expect(sendSource.indexOf("data-composer-send")).toBeGreaterThan(
      sendSource.indexOf("data-composer-input"),
    );
  });
});

describe("empty-session create — one sentence, two actions, no tutorial", () => {
  it("renders the two create buttons and no explainer paragraphs", () => {
    const markup = html(
      <NewSessionAction
        profiles={[
          { profile: "orchestrator", can_delegate: true, part_scoped: false, requires_part: false },
          { profile: "part", can_delegate: false, part_scoped: true, requires_part: true },
        ]}
        part="gusset"
        pending={false}
        onCreate={() => undefined}
      />,
    );
    expect(markup).toContain('data-create-profile="orchestrator"');
    expect(markup).toContain('data-create-profile="part"');
    expect(markup).not.toContain("data-profile-what");
    expect(markup).not.toContain("data-orphan-note");
    expect(markup).not.toContain(copy.composer.orphanNote);
  });

  it("keeps the honest selected-part sentence and does not grow a tutorial", () => {
    const body = copy.composer.noSessionSelectedPart("gusset");
    expect(body).toContain("gusset");
    expect(body).not.toContain("There is no part yet");
    expect(body.split(".").filter((part) => part.trim() !== "").length).toBeLessThanOrEqual(2);
  });
});

describe("rail providers — collapsed by default so Sign-in stays in the box", () => {
  const shell = css("components/Shell.module.css");
  const providersCss = css("components/ProvidersPanel.module.css");

  it("keeps the rail a height-bounded scroll host", () => {
    expect(shell).toMatch(/\.rail\s*\{[^}]*min-height:\s*0/);
    expect(shell).toMatch(/\.rail\s*\{[^}]*overflow:\s*auto/);
    expect(shell).toMatch(/\.body\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/);
    expect(providersCss).toMatch(/\.panel\s*\{[^}]*grid-template-rows:\s*auto auto/);
    expect(providersCss).toMatch(/\.panel\s*\{[^}]*flex:\s*none/);
  });

  it("does not mount the configuration table or allowlist until expanded", () => {
    const markup = providersMarkup(providersDocument());
    expect(markup).toContain("data-providers-collapsed");
    expect(markup).not.toContain("data-providers-expanded");
    expect(markup).toContain("data-provider-signin");
    expect(markup).toContain("data-discovery-run");
    expect(markup).not.toContain("data-source=\"providers.config_path\"");
    expect(markup).not.toContain("data-source=\"providers.file_mode\"");
    expect(markup).not.toContain(copy.providers.allowlistNote);
    expect(markup).not.toContain(copy.providers.discover.note);
  });

  it("still offers Sign-in and discovery in the compact row", () => {
    const markup = providersMarkup(providersDocument());
    expect(markup).toContain('data-provider-signin="heph-fake"');
    expect(markup).toContain("data-discovery-run");
    expect(markup).toContain("data-providers-details");
  });

  it("keeps the zero-config empty action when there is no provider row", () => {
    const markup = providersMarkup(providersDocument({ providers: [], attach: {
      attached: false,
      config_path: "/tmp/p/.heph/providers.json",
      generation: 0,
    } }));
    expect(markup).toContain("data-providers-empty");
    expect(markup).toContain("data-providers-attach");
    expect(markup).toContain("data-discovery-run");
    expect(markup).not.toContain(copy.providers.allowlistNote);
  });
});

describe("artifact pin — chip width that fits the 1280 header", () => {
  it("shortens the visible pin below the width that ate Token", () => {
    expect(CHIP_REF_WIDTH).toBeLessThanOrEqual(22);
    expect(formatRef(REF, CHIP_REF_WIDTH).length).toBeLessThanOrEqual(CHIP_REF_WIDTH);
    expect(formatRef(REF, CHIP_REF_WIDTH)).not.toBe(REF);
    const pin = readFileSync(join(webSrc, "components/ArtifactPin.tsx"), "utf8");
    expect(pin).toMatch(/formatRef\(ref,\s*CHIP_REF_WIDTH\)/);
    const composer = readFileSync(join(webSrc, "components/stream/Composer.tsx"), "utf8");
    expect(composer).toMatch(/formatRef\(chip\.value[^)]*CHIP_REF_WIDTH/);
  });
});

describe("composer chrome — no unlabelled off toggles", () => {
  it("does not render a bare effort off in the strip", () => {
    const composer = readFileSync(join(webSrc, "components/stream/Composer.tsx"), "utf8");
    expect(composer).not.toContain("data-composer-effort");
    expect(composer).toContain("data-dfm-auto-run-toggle");
    expect(composer).toContain("data-dfm-run");
  });
});
