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
import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { keys } from "../src/api/queries";
import type { ProvidersDocument } from "../src/api/providers";
import type { BuildDocument, GitStatusDocument, ProjectDocument } from "../src/api/types";
import { ArtifactPin } from "../src/components/ArtifactPin";
import { BUILD_STATE_BADGE } from "../src/components/BuildStateChip";
import { Header } from "../src/components/Header";
import { DEFAULT_STATE, type WorkspaceState } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";
import { NewSessionAction } from "../src/components/stream/Composer";
import { PROJECT_TREE_SECTIONS, ProjectSectionList } from "../src/components/rail/ProjectTree";
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

  // RETARGETED, and the claim is unweakened. This used to assert the panel's
  // `grid-template-rows: auto minmax(0, 1fr) auto`, which pinned the composer by
  // its child INDEX — so the panel with no session, whose header carries no fact
  // and is not rendered, put `main` on the `auto` row and the composer on the
  // `1fr` one: the composer floated in the middle of an empty column. The
  // property the assertion was always for is "the composer is the last child and
  // main is the one that shrinks", and a flex column states that per child
  // rather than per position.
  it("pins the composer as the last child under a shrinking main", () => {
    expect(stream).toMatch(/\.panel\s*\{[^}]*flex-direction:\s*column/);
    expect(stream).toMatch(/\.header\s*\{[^}]*flex:\s*none/);
    expect(stream).toMatch(/\.main\s*\{[^}]*flex:\s*1 1 auto/);
    expect(stream).toMatch(/\.main\s*\{[^}]*min-height:\s*0/);
    expect(stream).toMatch(/\.main\s*\{[^}]*overflow:\s*hidden/);
    expect(stream).toMatch(/\.scroll\s*\{[^}]*overflow:\s*auto/);
    expect(stream).toMatch(/\.panel\s*\{[^}]*overflow:\s*hidden/);
    const composer = css("components/stream/Composer.module.css");
    expect(composer).toMatch(/\.composer\s*\{[^}]*flex:\s*0 0 auto/);
    // #56: the empty column's leftover height sits *above* the invitation,
    // not between the plate and the composer. Alignment, not re-order.
    expect(stream).toMatch(/\[data-stream-empty\]\s*\.main\s*\{[^}]*justify-content:\s*flex-end/);
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
  it("still paints New session when GET /sessions left profiles empty (#43)", () => {
    const markup = html(
      <NewSessionAction profiles={[]} part="kerf_card" pending={false} onCreate={() => undefined} />,
    );
    expect(markup).toContain('data-create-profile="orchestrator"');
    expect(markup).toContain('data-create-profile="part"');
    expect(markup).toContain(copy.composer.createOrchestrator);
    expect(markup).toContain(copy.composer.createPart("kerf_card"));
  });

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
  const panel = css("system/Panel.module.css");
  const tokens = css("system/tokens.css");

  it("keeps the rail a height-bounded scroll host", () => {
    expect(shell).toMatch(/\.rail\s*\{[^}]*min-height:\s*0/);
    expect(shell).toMatch(/\.rail\s*\{[^}]*overflow-y:\s*auto/);
    expect(shell).toMatch(/\.body\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/);
    expect(providersCss).toMatch(/\.panel\s*\{[^}]*grid-template-rows:\s*auto auto/);
    expect(providersCss).toMatch(/\.panel\s*\{[^}]*flex:\s*none/);
  });

  it("fails if a rail descendant can force wider than --rail-width", () => {
    // Measured on the live operator at 1280×800: nav._rail clientWidth 279
    // vs scrollWidth 319. Sign-in sat at x 244–311, 31px past the 280px box,
    // reachable only by a horizontal bar at the rail floor. The leak is the
    // same class as the stream chip: a nowrap header pair (title + "Show
    // configuration") or an egress host/timestamp on `max-content` tracks
    // sets a flex child's min-content above `--rail-width`.
    expect(tokens).toMatch(/--rail-width:\s*280px/);
    expect(shell).toMatch(/\.rail\s*\{[^}]*overflow-x:\s*hidden/);
    expect(shell).toMatch(/\.rail\s*>\s*\*\s*\{[^}]*min-width:\s*0/);
    expect(panel).toMatch(/\.header\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(panel).toMatch(/\.header\s*\{[^}]*min-width:\s*0/);
    expect(panel).toMatch(/\.actions\s*\{[^}]*min-width:\s*0/);
    expect(panel).not.toMatch(/\.actions\s*\{[^}]*flex:\s*none/);
    expect(providersCss).toMatch(/\.compactRow\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(providersCss).toMatch(/\.compactRow\s*\{[^}]*min-width:\s*0/);
    expect(providersCss).toMatch(/\.body\s*\{[^}]*minmax\(0,\s*1fr\)/);
    expect(providersCss).toMatch(/\.body\s*\{[^}]*overflow-x:\s*hidden/);
    expect(providersCss).not.toMatch(/max-content/);
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

  it("collapses a signed-in provider to one chip, not the configuration essay (#55)", () => {
    const markup = providersMarkup(
      providersDocument({
        providers: [
          {
            id: "heph-fake",
            kind: "openai_compatible",
            name: "Fake",
            models: [{ id: "glm-5.3-flash", name: "glm-5.3-flash" }],
            source: "project",
            health: "accepted",
            last_observed_at: 1_700_000_000,
            available: true,
            unavailable_reason: null,
          },
        ],
      }),
    );
    expect(markup).toContain("data-providers-collapsed");
    expect(markup).toContain('data-provider-chip="heph-fake"');
    expect(markup).toContain('data-provider-source="project"');
    expect(markup).not.toContain("data-provider-signin");
    expect(markup).not.toContain("data-provider-signout");
    expect(markup).not.toContain("data-discovery-run");
    expect(markup).toContain("data-providers-details");
  });

  it("keeps acknowledged egress hosts in the compact DOM (G10C)", () => {
    const markup = providersMarkup(
      providersDocument({
        egress_acknowledged: [{ host: "models.example", at: "1700000000" }],
      }),
    );
    expect(markup).toContain("data-providers-collapsed");
    expect(markup).toContain('data-egress-host="models.example"');
    expect(markup).not.toContain(copy.providers.egressNote);
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

  it("splits health into two Facts with unformatted wire values (#94)", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(
      keys.providers(),
      providersDocument({
        providers: [
          {
            id: "heph-fake",
            kind: "openai_compatible",
            name: "Fake",
            models: [{ id: "glm-5.3-flash", name: "glm-5.3-flash" }],
            source: "project",
            health: "accepted",
            last_observed_at: 1_700_000_000,
            available: true,
            unavailable_reason: null,
          },
        ],
      }),
    );
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
      await act(async () => {
        root.render(
          <QueryClientProvider client={client}>
            <ProvidersPanel />
          </QueryClientProvider>,
        );
      });
      await act(async () => {
        host.querySelector("[data-providers-details]")?.dispatchEvent(
          new MouseEvent("click", { bubbles: true }),
        );
      });
      const health = host.querySelector('[data-source="providers.health"]');
      expect(health?.getAttribute("data-value")).toBe("accepted");
      const observed = host.querySelector('[data-source="providers.last_observed_at"]');
      expect(observed?.getAttribute("data-value")).toBe("1700000000");
      expect(health?.textContent).not.toContain("1700000000");
    } finally {
      act(() => {
        root.unmount();
      });
      host.remove();
    }
  });
});

describe("build-state badge mapping", () => {
  it("maps stale to an absence, not an error (#97)", () => {
    expect(BUILD_STATE_BADGE.stale).toBe("not_run");
    expect(BUILD_STATE_BADGE.not_built).toBe("not_run");
    expect(BUILD_STATE_BADGE.failed).toBe("fail");
    expect(BUILD_STATE_BADGE.stale).not.toBe("error");
  });
});

describe("artifact pin — one chip, one state word", () => {
  const REF_A = "artifact:build:sha256:" + "a".repeat(64);

  function build(over: Partial<BuildDocument> = {}): BuildDocument {
    return {
      status: "ok",
      current: true,
      geometry_count: 2,
      geometries: [],
      artifact_ref: REF_A,
      ...over,
    };
  }

  let mounted: { host: HTMLElement; root: Root } | null = null;

  /**
   * A LIVE root, not `renderToStaticMarkup`. `useWorkspace`'s server snapshot is
   * `DEFAULT_STATE` by design (§4.5), so static markup cannot see a held pin.
   */
  function pin(state: Partial<WorkspaceState>, document: BuildDocument | undefined): Element {
    workspaceStore.reset({ ...DEFAULT_STATE, ...state });
    const host = window.document.createElement("div");
    window.document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(<ArtifactPin build={document} />);
    });
    mounted = { host, root };
    const node = host.querySelector('[data-testid="artifact-pin"]');
    if (node === null) throw new Error("no pin");
    return node;
  }

  afterEach(() => {
    if (mounted !== null) {
      const live = mounted;
      act(() => {
        live.root.unmount();
      });
      live.host.remove();
      mounted = null;
    }
    workspaceStore.reset(DEFAULT_STATE);
  });

  it("prints the build state and a hold VERB while following current", () => {
    const node = pin({ artifact_ref: REF_A, pin_mode: "current" }, build());
    expect(node.getAttribute("data-build-state")).toBe("current");
    expect(node.querySelector('[data-pin-action="hold"]')?.textContent).toBe(copy.header.hold);
    // The pin vocabulary's own word is not also printed: one axis at a time.
    expect(node.textContent).not.toContain(copy.pinMode.current);
    expect(node.textContent).toContain(copy.buildState.current);
  });

  it("prints `held` and the discard action while held, and no second state word", () => {
    const node = pin({ artifact_ref: REF_A, pin_mode: "pinned" }, build({ current: false }));
    expect(node.querySelector("[data-pin-state]")?.textContent).toBe(copy.pinMode.pinned);
    expect(node.querySelector('[data-pin-action="follow"]')).not.toBeNull();
    expect(node.textContent).not.toContain(copy.buildState.preview);
  });

  it("keeps both build fields attributed WHILE HELD, which is the G5.5/G5.6 path", () => {
    // The first cut of this chip chose between the `held` word and the badge
    // with a ternary, so while held the badge never mounted and both build
    // fields went with it — on the one path §4.1 says the operator must not be
    // able to forget which build they are looking at. Same strength as the
    // following-current case below; only the drawn badge differs.
    const node = pin({ artifact_ref: REF_A, pin_mode: "pinned" }, build({ current: false }));
    expect(node.getAttribute("data-build-state")).toBe("preview");
    expect(node.querySelector('[data-source="build.status"]')?.getAttribute("data-value")).toBe("ok");
    expect(node.querySelector('[data-source="build.current"]')?.getAttribute("data-value")).toBe(
      "false",
    );
    expect(node.querySelector('[data-source="build.artifact_ref"]')?.getAttribute("data-value")).toBe(
      REF_A,
    );
    // §3.4: `data-build-state` is the pin chip's own, minted once. `node` IS the
    // chip, so a second copy would show up as a DESCENDANT carrying it.
    expect(node.querySelectorAll("[data-build-state]")).toHaveLength(0);
  });

  it("mounts the build fields on every state the server answered for", () => {
    // Enumerated rather than sampled: the defect was one branch of a ternary,
    // and a per-state assertion is what makes another one impossible to add
    // without a failure.
    const states = [
      { over: {}, expected: "current" },
      { over: { current: false }, expected: "preview" },
      { over: { status: "error" as const, current: false }, expected: "failed" },
      { over: { status: "not_built" as const, current: false }, expected: "not_built" },
    ];
    for (const mode of ["current", "pinned"] as const) {
      for (const { over, expected } of states) {
        const node = pin({ artifact_ref: REF_A, pin_mode: mode }, build(over));
        expect(node.getAttribute("data-build-state"), `${mode}/${expected}`).toBe(expected);
        expect(
          node.querySelector('[data-source="build.status"]'),
          `${mode}/${expected} status`,
        ).not.toBeNull();
        expect(
          node.querySelector('[data-source="build.current"]'),
          `${mode}/${expected} current`,
        ).not.toBeNull();
        act(() => {
          mounted?.root.unmount();
        });
        mounted?.host.remove();
        mounted = null;
      }
    }
  });

  it("says `not built` once, with no ref, no hold, and no fourth label", () => {
    const node = pin(
      { artifact_ref: null, pin_mode: "current" },
      build({ status: "not_built", current: false, artifact_ref: null, geometry_count: 0 }),
    );
    expect(node.getAttribute("data-build-state")).toBe("not_built");
    // One visible word. `build.current`'s clipped 1px mirror stays attributed
    // and is silent in the accessibility tree (#96).
    expect(node.querySelector('[data-source="build.status"]')?.textContent).toBe(
      copy.buildState.not_built,
    );
    expect(node.querySelector('[data-source="build.current"]')?.getAttribute("aria-hidden")).toBe(
      "true",
    );
    expect(node.querySelector("[data-pin-action]")).toBeNull();
    expect(node.querySelector("[data-pin-state]")).toBeNull();
    expect(node.querySelector('[data-source="build.artifact_ref"]')).toBeNull();
  });

  it("keeps both build fields attributed inside the chip", () => {
    const node = pin({ artifact_ref: REF_A, pin_mode: "current" }, build());
    expect(node.querySelector('[data-source="build.status"]')?.getAttribute("data-value")).toBe("ok");
    expect(node.querySelector('[data-source="build.current"]')?.getAttribute("data-value")).toBe(
      "true",
    );
  });
});

describe("artifact pin — chip width that fits the 1280 header", () => {
  it("shortens the visible pin below the width that ate Token", () => {
    expect(CHIP_REF_WIDTH).toBeLessThanOrEqual(22);
    expect(formatRef(REF, CHIP_REF_WIDTH).length).toBeLessThanOrEqual(CHIP_REF_WIDTH);
    expect(formatRef(REF, CHIP_REF_WIDTH)).not.toBe(REF);
    expect(formatRef(REF, CHIP_REF_WIDTH)).toMatch(/^build · [0-9a-f]{8}$/);
    expect(formatRef(REF, CHIP_REF_WIDTH)).not.toContain("artifact:");
    const pin = readFileSync(join(webSrc, "components/ArtifactPin.tsx"), "utf8");
    expect(pin).toMatch(/formatRef\(ref,\s*CHIP_REF_WIDTH\)/);
    const composer = readFileSync(join(webSrc, "components/stream/Composer.tsx"), "utf8");
    expect(composer).toMatch(/formatRef\(chip\.value[^)]*CHIP_REF_WIDTH/);
  });
});

describe("composer chrome — talking surface, not a Plan/DFM toolbar", () => {
  it("does not render a bare effort off in the strip", () => {
    const composer = readFileSync(join(webSrc, "components/stream/Composer.tsx"), "utf8");
    expect(composer).not.toContain("data-composer-effort");
    expect(composer).not.toContain("data-dfm-auto-run-toggle");
    expect(composer).not.toContain("data-dfm-run");
    expect(composer).not.toContain("data-composer-dfm");
    expect(composer).not.toMatch(/rows=\{3\}/);
    expect(composer).toContain("promptRows");
  });

  it("defaults the idle prompt to one row so Send stays on-screen", () => {
    const composer = readFileSync(join(webSrc, "components/stream/Composer.tsx"), "utf8");
    expect(composer).toMatch(/promptFocused \|\| text\.trim\(\) !== "" \? 3 : 1/);
    expect(composer).toContain("data-composer-send");
    expect(composer).toContain("data-composer-cancel");
    expect(composer).toContain("data-context-disclose");
    expect(composer).toContain("data-context-add-view");
    expect(composer.indexOf("data-context-add-view")).toBeGreaterThan(
      composer.indexOf("data-context-disclose"),
    );
    // AMENDED 2026-09-01 (§7A.10(a)): and the row Send sits in holds nothing
    // else at rest. The model moved to the meta line, the disclosure to the
    // summary line, and Cancel mounts only while a run is cancellable.
    expect(composer).toContain("data-context-summary");
    expect(composer).not.toMatch(/<Chip[\s\S]{0,80}data-composer-model/);
  });
});

describe("rail project sections — listed, empty-honest, collapsed", () => {
  it("keeps the closed inventory and does not expand empty bodies by default", () => {
    const markup = html(<ProjectSectionList open={new Set()} onToggle={() => undefined} />);
    for (const id of PROJECT_TREE_SECTIONS) {
      expect(markup).toContain(`data-tree-section="${id}"`);
    }
    expect(markup).not.toContain("data-tree-section-empty");
    expect(PROJECT_TREE_SECTIONS).toEqual(["analyses", "docs", "globals", "imports", "materials"]);
  });
});

describe("header — one row of facts on the artifact axis", () => {
  const OID = "aabbccddeeff0011223344556677889900112233";

  function projectDocument(): ProjectDocument {
    return {
      status: "ok",
      root: "/tmp/p",
      name: "fixture",
      units: "mm",
      parts: [],
      serve_mode: true,
    };
  }

  function gitDocument(over: Partial<GitStatusDocument> = {}): GitStatusDocument {
    return {
      status: "ok",
      dirty: [],
      clean: true,
      head: OID,
      branch: "main",
      ...over,
    };
  }

  function headerMarkup(git: GitStatusDocument | null): string {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.project(), projectDocument());
    if (git !== null) client.setQueryData(keys.gitStatus(), git);
    return html(
      <QueryClientProvider client={client}>
        <Header />
      </QueryClientProvider>,
    );
  }

  it("keeps the git axis out of the 44px bar entirely (§13.1)", () => {
    // The header used to print `project · units · branch · HEAD`, and the HEAD
    // it printed was the WHOLE 40-glyph oid plus an ellipsis plus its own last
    // eight bytes, because `formatRef(ref, 8)` sliced `(0, -1)`. Both halves are
    // closed here: `format.ts` refuses that width, and branch/HEAD are the git
    // axis, so they live in the rail's Working tree panel (`rail.test.tsx`).
    const markup = headerMarkup(gitDocument({ branch: "main", head: OID }));
    expect(markup).not.toContain('data-source="git.branch"');
    expect(markup).not.toContain('data-source="git.head"');
    expect(markup).not.toContain(OID);
    expect(formatRef(OID, 8)).toBe(OID.slice(0, 8));
    expect(formatRef(OID, 8).length).toBe(8);
  });

  it("still names the project and its units, and nothing else, as identity", () => {
    const markup = headerMarkup(gitDocument());
    expect(markup).toContain('data-source="project.name"');
    expect(markup).toContain('data-source="project.units"');
  });

  it("offers no hold control while there is no artifact to hold", () => {
    // The shipped bar carried a DISABLED button labelled `held` — a state word
    // on a control — beside `unavailable`, `CURRENT` and `not built`. Four
    // labels, one fact. The control is gone on this path; the chip keeps one word.
    const markup = headerMarkup(gitDocument());
    expect(markup).toContain('data-testid="artifact-pin"');
    expect(markup).not.toContain('data-pin-action="hold"');
    expect(markup).not.toContain('data-pin-action="follow"');
  });

  it("does not paint a decorative Token chip in the signed-in header", () => {
    const markup = headerMarkup(gitDocument());
    expect(markup).not.toContain("data-token-state");
    const header = readFileSync(join(webSrc, "components/Header.tsx"), "utf8");
    expect(header).not.toContain("data-token-state");
    expect(header).not.toContain("copy.header.token");
  });

  it("keeps Export and BOM as two addressable header controls next to the pin", () => {
    const markup = headerMarkup(gitDocument());
    expect(markup).toContain("data-chrome-export");
    expect(markup).toContain("data-chrome-bom");
    expect(markup).toContain("data-part-chrome");
    expect(markup).toContain("data-testid=\"artifact-pin\"");
  });
});
