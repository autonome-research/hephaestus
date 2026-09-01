// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Keyboard / a11y leftovers on the operator chrome (INTERFACE.md §3.13, §4.7).
//
// Assertions are on attributes, tab stops, and focus — never on wording (§3).
// `renderToStaticMarkup` cannot run `useLayoutEffect`, so every tree / popover
// claim that depends on a live holder or trap uses a jsdom root.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { keys } from "../src/api/queries";
import type { BuildDocument, GitStatusDocument, PartsDocument } from "../src/api/types";
import { AppearanceControls } from "../src/components/stage/viewport/AppearanceControls";
import { Inspector } from "../src/components/stage/Inspector";
import { Viewport } from "../src/components/stage/viewport/Viewport";
import { Composer } from "../src/components/stream/Composer";
import { SessionTabs } from "../src/components/stream/SessionTabs";
import {
  PROJECT_TREE_SECTIONS,
  ProjectSectionList,
  ProjectTree,
} from "../src/components/rail/ProjectTree";
import { copy } from "../src/copy";
import { DEFAULT_STATE } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";
import { Popover, TabBar, Tree, TreeRow, tabControlId } from "../src/system";

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = join(here, "../src");

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

function source(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8");
}

let mounted: { host: HTMLElement; root: Root } | null = null;

function live(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(element);
  });
  mounted = { host, root };
  return host;
}

afterEach(() => {
  if (mounted !== null) {
    const current = mounted;
    act(() => {
      current.root.unmount();
    });
    current.host.remove();
    mounted = null;
  }
  workspaceStore.reset(DEFAULT_STATE);
});

function tabStops(host: HTMLElement): HTMLElement[] {
  return [...host.querySelectorAll<HTMLElement>('[role="treeitem"]')].filter(
    (row) => row.tabIndex === 0,
  );
}

function partsDocument(names: readonly string[]): PartsDocument {
  return {
    status: "ok",
    parts: names.map((name) => ({
      name,
      path: `parts/${name}.py`,
      content_hash: "sha256:x",
      snapshot_ref: `artifact:part-snapshot:sha256:${name}`,
    })),
  };
}

const GIT: GitStatusDocument = {
  status: "ok",
  dirty: [],
  clean: true,
  head: "abc",
  branch: "main",
};

function treeClient(names: readonly string[], selected: string | null, build?: BuildDocument): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(keys.parts(), partsDocument(names));
  client.setQueryData(keys.gitStatus(), GIT);
  if (selected !== null && build !== undefined) {
    client.setQueryData(keys.build(selected), build);
  }
  workspaceStore.reset({ ...DEFAULT_STATE, part: selected });
  return (
    <QueryClientProvider client={client}>
      <ProjectTree />
    </QueryClientProvider>
  );
}

const BUILT: BuildDocument = {
  status: "ok",
  current: true,
  geometry_count: 2,
  geometries: [
    { label: "face", solids: 1 },
    { label: "hole", solids: 1 },
  ],
};

describe("Tree — focus-holder is not selection (issue 102)", () => {
  it("gives a tree with no selected row exactly one tabindex=0 holder", () => {
    const host = live(
      <Tree label="sections">
        <ProjectSectionList open={new Set()} onToggle={() => undefined} />
      </Tree>,
    );
    const items = [...host.querySelectorAll<HTMLElement>('[role="treeitem"]')];
    expect(items).toHaveLength(PROJECT_TREE_SECTIONS.length);
    expect(items.every((row) => row.getAttribute("aria-selected") === "false")).toBe(true);
    expect(tabStops(host)).toHaveLength(1);
    expect(tabStops(host)[0]?.getAttribute("data-tree-section")).toBe("analyses");
  });

  it("hands the tab stop to the selected row when one exists", () => {
    const host = live(
      <Tree label="parts">
        <TreeRow depth={0} selected={false} label="riser" data-part="riser" />
        <TreeRow depth={0} selected={true} label="tread" data-part="tread" />
      </Tree>,
    );
    expect(tabStops(host)).toHaveLength(1);
    expect(tabStops(host)[0]?.getAttribute("data-part")).toBe("tread");
    expect(host.querySelector<HTMLElement>('[data-part="riser"]')?.tabIndex).toBe(-1);
  });

  it("does not fake selection on Analyses to mint a tab stop", () => {
    const host = live(
      <Tree label="project">
        <ProjectSectionList open={new Set()} onToggle={() => undefined} />
      </Tree>,
    );
    expect(host.querySelector('[data-tree-section="analyses"]')?.getAttribute("aria-selected")).toBe(
      "false",
    );
    expect(tabStops(host)).toHaveLength(1);
  });
});

describe("ProjectTree — one tree; expand is not select (issues 65, 91)", () => {
  it("is a single tree and ArrowDown from the last part reaches Analyses", () => {
    const host = live(treeClient(["gusset", "shelf", "tread"], "gusset"));
    expect(host.querySelectorAll('[role="tree"]')).toHaveLength(1);
    const last = host.querySelector<HTMLElement>('[data-tree-row="part"][data-part="tread"]');
    const tree = host.querySelector<HTMLElement>('[role="tree"]');
    expect(last).not.toBeNull();
    act(() => {
      last?.focus();
    });
    act(() => {
      tree?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    expect(document.activeElement?.getAttribute("data-tree-section")).toBe("analyses");
  });

  it("does not put aria-expanded on a part that has no children", () => {
    const host = live(treeClient(["gusset", "tread"], "gusset"));
    expect(host.querySelector('[data-part="tread"]')?.hasAttribute("aria-expanded")).toBe(false);
    expect(host.querySelector('[data-part="gusset"]')?.hasAttribute("aria-expanded")).toBe(false);
  });

  it("keeps ArrowRight from selecting another part", () => {
    const host = live(treeClient(["gusset", "tread"], "gusset"));
    const tread = host.querySelector<HTMLElement>('[data-tree-row="part"][data-part="tread"]');
    const tree = host.querySelector<HTMLElement>('[role="tree"]');
    act(() => {
      tread?.focus();
    });
    act(() => {
      tree?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(workspaceStore.getSnapshot().part).toBe("gusset");
    expect(document.activeElement?.getAttribute("data-tree-section")).toBe("analyses");
  });

  it("expands a selected part with children without navigating", () => {
    const host = live(treeClient(["gusset", "tread"], "gusset", BUILT));
    const part = host.querySelector<HTMLElement>('[data-tree-row="part"][data-part="gusset"]');
    expect(part?.getAttribute("aria-expanded")).toBe("true");
    expect(host.querySelectorAll('[data-tree-row="geometry"]')).toHaveLength(2);
    const twisty = part?.querySelector<HTMLElement>("[data-tree-toggle]");
    act(() => {
      twisty?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(part?.getAttribute("aria-expanded")).toBe("false");
    expect(workspaceStore.getSnapshot().part).toBe("gusset");
    expect(host.querySelector('[data-tree-row="geometry"]')).toBeNull();
    const tree = host.querySelector<HTMLElement>('[role="tree"]');
    act(() => {
      part?.focus();
    });
    act(() => {
      tree?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(workspaceStore.getSnapshot().part).toBe("gusset");
    expect(part?.getAttribute("aria-expanded")).toBe("true");
  });

  it("keeps empty sections collapsed by default", () => {
    const host = live(treeClient(["gusset"], "gusset"));
    for (const id of PROJECT_TREE_SECTIONS) {
      expect(host.querySelector(`[data-tree-section="${id}"]`)?.getAttribute("aria-expanded")).toBe(
        "false",
      );
    }
    expect(host.querySelector("[data-tree-section-empty]")).toBeNull();
  });
});

describe("canvas, skip links, composer name (issues 64, 68)", () => {
  it("puts the canvas in the tab order and names it, not the wrapper", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const host = live(
      <QueryClientProvider client={client}>
        <Viewport />
      </QueryClientProvider>,
    );
    const canvas = host.querySelector<HTMLCanvasElement>("[data-viewport-canvas]");
    const well = host.querySelector("[data-testid=\"viewport\"]");
    expect(canvas?.tabIndex).toBe(0);
    expect(canvas?.id).toBe("stage");
    expect(canvas?.getAttribute("aria-label")).toBe(copy.viewport.label);
    expect(well?.hasAttribute("aria-label")).toBe(false);
    expect(well?.hasAttribute("role")).toBe(false);
  });

  it("names the composer from copy.ts and lands a skip target on it", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const host = live(
      <QueryClientProvider client={client}>
        <Composer
          sessionId="sess-1"
          profile="orchestrator"
          attach={null}
          agentUnavailable={false}
          liveRunId={null}
          streamLive
        />
      </QueryClientProvider>,
    );
    const form = host.querySelector<HTMLElement>("[data-composer]");
    expect(form?.id).toBe("composer");
    expect(form?.getAttribute("aria-label")).toBe(copy.composer.label);
    expect(form?.tabIndex).toBe(-1);
  });

  it("wires skip links past the rail to those two ids", () => {
    const shell = source("components/Shell.tsx");
    expect(shell).toContain('data-skip="stage"');
    expect(shell).toContain('href="#stage"');
    expect(shell).toContain('data-skip="composer"');
    expect(shell).toContain('href="#composer"');
    expect(source("components/stage/viewport/Viewport.tsx")).toContain('id="stage"');
    expect(source("components/stream/Composer.tsx")).toContain('id="composer"');
  });
});

describe("tablists wire aria-controls / aria-labelledby (issues 82, 68)", () => {
  it("points inspector tabs at the drawer panel", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const host = live(
      <QueryClientProvider client={client}>
        <Inspector />
      </QueryClientProvider>,
    );
    const selected = host.querySelector<HTMLElement>('[data-inspector-tab][aria-selected="true"]');
    const panel = host.querySelector<HTMLElement>("[data-inspector-panel]");
    expect(selected?.getAttribute("aria-controls")).toBe("inspector-panel");
    expect(panel?.id).toBe("inspector-panel");
    expect(panel?.getAttribute("role")).toBe("tabpanel");
    expect(panel?.getAttribute("aria-labelledby")).toBe(selected?.id);
    expect(selected?.id).toBe(tabControlId("data-inspector-tab", "results"));
  });

  it("points a session tab at the transcript panel id", () => {
    const html = renderToStaticMarkup(
      <SessionTabs
        tabs={[
          {
            session_id: "sess-kerf",
            parent_session_id: null,
            kind: null,
            depth: 0,
            thread_state: "linked",
            origin: {},
          },
        ]}
        sessions={[
          {
            session_id: "sess-kerf",
            profile: "part",
            part: "kerf_card",
            parent_session_id: null,
            thread_state: "linked",
          },
        ]}
        selected="sess-kerf"
        onSelect={() => undefined}
        bounded={false}
        panelId="transcript-panel"
      />,
    );
    const host = document.createElement("div");
    host.innerHTML = html;
    const tab = host.querySelector("[data-session-tab]");
    expect(tab?.getAttribute("aria-controls")).toBe("transcript-panel");
    expect(tab?.id).toBe(tabControlId("data-session-tab", "sess-kerf"));
    expect(source("components/stream/StreamPanel.tsx")).toContain('id="transcript-panel"');
    expect(source("components/stream/StreamPanel.tsx")).toContain('role="tabpanel"');
  });

  it("emits aria-controls from the TabBar primitive", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <TabBar
        attr="data-inspector-tab"
        panelId="inspector-panel"
        label="Inspector"
        selected="results"
        onSelect={() => undefined}
        tabs={[
          { id: "results", label: "Results" },
          { id: "checks", label: "Checks" },
        ]}
      />,
    );
    expect(host.querySelector('[data-inspector-tab="results"]')?.getAttribute("aria-controls")).toBe(
      "inspector-panel",
    );
    expect(host.querySelector('[data-inspector-tab="checks"]')?.getAttribute("aria-controls")).toBe(
      "inspector-panel",
    );
  });
});

describe("Popover trap stays closed after a panel click (issue 84)", () => {
  it("cycles Tab back to the first control when the panel itself is focused", () => {
    const host = live(
      <Popover open onClose={() => undefined} label="export" variant="dialog">
        <button type="button" data-first="">
          first
        </button>
        <button type="button" data-last="">
          last
        </button>
      </Popover>,
    );
    const panel = host.querySelector<HTMLElement>('[role="dialog"]');
    const first = host.querySelector<HTMLElement>("[data-first]");
    const last = host.querySelector<HTMLElement>("[data-last]");
    expect(panel).not.toBeNull();
    act(() => {
      panel?.focus();
    });
    expect(document.activeElement).toBe(panel);
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
    });
    expect(document.activeElement).toBe(first);
    act(() => {
      last?.focus();
    });
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
    });
    expect(document.activeElement).toBe(first);
    act(() => {
      panel?.focus();
    });
    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true, shiftKey: true }),
      );
    });
    expect(document.activeElement).toBe(last);
  });
});

describe("Fit / Cancel / disclose resting chrome and Button min-width (issues 67, 87)", () => {
  it("gives Fit the same resting variant as a control, not quiet", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <AppearanceControls canFit onFit={() => undefined} />,
    );
    const fit = host.querySelector('[data-appearance-control="fit"]');
    const grid = host.querySelector('[data-appearance-control="grid"]');
    expect(fit?.getAttribute("data-variant")).toBe("secondary");
    expect(fit?.getAttribute("data-variant")).not.toBe("quiet");
    expect(grid?.getAttribute("data-variant")).toBe("toggle");
  });

  it("gives composer Cancel and disclose a resting control surface", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <Composer
          sessionId="sess-1"
          profile="orchestrator"
          attach={null}
          agentUnavailable={false}
          liveRunId={null}
          streamLive
        />
      </QueryClientProvider>,
    );
    const host = document.createElement("div");
    host.innerHTML = html;
    expect(host.querySelector("[data-composer-cancel]")?.getAttribute("data-variant")).toBe(
      "secondary",
    );
    expect(host.querySelector("[data-context-disclose]")?.getAttribute("data-variant")).toBe(
      "secondary",
    );
    expect(host.querySelector("[data-composer-cancel]")?.getAttribute("data-variant")).not.toBe(
      "quiet",
    );
  });

  it("sets min-width on the Button primitive next to min-height", () => {
    const rules = css("system/Button.module.css");
    expect(rules).toMatch(/\.button\s*\{[^}]*min-height:\s*var\(--target-min\)/);
    expect(rules).toMatch(/\.button\s*\{[^}]*min-width:\s*var\(--target-min\)/);
  });
});
