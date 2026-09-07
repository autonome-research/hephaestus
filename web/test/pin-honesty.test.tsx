// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Chrome polish PR 3 — pin / header / export axis honesty.
//
// Assertions are on fields, keys, and information content (§3), not wording.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import type { ReactElement } from "react";

import { CHIP_REF_WIDTH, formatRef } from "../src/system";
import { copy } from "../src/copy";
import { ArtifactPin } from "../src/components/ArtifactPin";
import { Header } from "../src/components/Header";
import { PinSplitMarker } from "../src/components/PinSplitMarker";
import { pinSplit } from "../src/state/pinSplit";
import { ExportChrome, producedRow } from "../src/components/chrome/ExportChrome";
import {
  resetSubmissionKeys,
  signature,
  submissionKeyFor,
  type Submission,
} from "../src/components/inspector/ExportPanel";
import type { BuildDocument, ProjectDocument } from "../src/api/types";
import type { ExportResult, ExportsDocument } from "../src/api/exports";
import { keys } from "../src/api/queries";
import { adoptCreatedPart, createdPartNames } from "../src/api/refresh";
import { DEFAULT_STATE, WorkspaceStore, type WorkspaceState } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = join(here, "..", "src");

const JIG =
  "artifact:build:sha256:1c657297d5dc41cf5f454f12095d63b01b29665e6ae6a7c6aaaaaaaaaaaaaaaa";

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

function build(over: Partial<BuildDocument> = {}): BuildDocument {
  return {
    status: "ok",
    current: true,
    geometry_count: 1,
    geometries: [],
    artifact_ref: JIG,
    ...over,
  };
}

let mounted: { host: HTMLElement; root: Root } | null = null;

function mount(element: ReactElement): HTMLElement {
  const host = window.document.createElement("div");
  window.document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(element);
  });
  mounted = { host, root };
  return host;
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
  resetSubmissionKeys();
});

function pin(state: Partial<WorkspaceState>, document: BuildDocument | undefined): Element {
  workspaceStore.reset({ ...DEFAULT_STATE, ...state });
  const host = mount(<ArtifactPin build={document} />);
  const node = host.querySelector('[data-testid="artifact-pin"]');
  if (node === null) throw new Error("no pin");
  return node;
}

describe("formatRef — hash prefix, not the scheme (#57)", () => {
  it("does not spend its width on artifact:build:", () => {
    const shown = formatRef(JIG, CHIP_REF_WIDTH);
    expect(shown).toBe("build · 1c657297");
    expect(shown).not.toContain("artifact:");
    expect(shown).not.toMatch(/buil…/);
    expect(shown.length).toBeLessThanOrEqual(CHIP_REF_WIDTH);
  });

  it("still distinguishes two refs that share a tail", () => {
    const tail = "cbe552b4cf";
    const a = "artifact:build:sha256:" + "a".repeat(54) + tail;
    const b = "artifact:render:sha256:" + "b".repeat(54) + tail;
    expect(a.slice(-10)).toBe(b.slice(-10));
    expect(formatRef(a)).toBe("build · aaaaaaaa");
    expect(formatRef(b)).toBe("render · bbbbbbbb");
  });
});

describe("pinnedBanner — names the split, not every panel (#78)", () => {
  it("does not claim every panel reports against the held artifact", () => {
    const same = copy.header.pinnedBanner("assembly_jig", "assembly_jig");
    const split = copy.header.pinnedBanner("assembly_jig", "kerf_card");
    expect(same).not.toMatch(/every panel below/i);
    expect(split).not.toMatch(/every panel below/i);
    expect(split).toContain("assembly_jig");
    expect(split).toContain("kerf_card");
    expect(split).toContain("canvas");
    expect(split).toContain("inspector");
  });

  it("names the source part on the chip when the rail has moved on", () => {
    workspaceStore.reset({ ...DEFAULT_STATE, part: "assembly_jig", artifact_ref: JIG });
    workspaceStore.hold(JIG);
    workspaceStore.update({ part: "kerf_card" });
    const node = pin(
      workspaceStore.getSnapshot(),
      build({ status: "not_built", current: false, artifact_ref: null, geometry_count: 0 }),
    );
    expect(node.getAttribute("data-pin-from")).toBe("assembly_jig");
    expect(node.getAttribute("title") ?? "").toContain("assembly_jig");
    expect(node.getAttribute("title") ?? "").not.toMatch(/every panel below/i);
  });
});

describe("build.current — no bare true/false (#96)", () => {
  it("keeps the attribution and hides the boolean from the accessibility tree", () => {
    const node = pin({ artifact_ref: JIG, pin_mode: "current" }, build());
    const current = node.querySelector('[data-source="build.current"]');
    expect(current?.getAttribute("data-value")).toBe("true");
    expect(current?.getAttribute("aria-hidden")).toBe("true");
  });

  it("stays silent on the held path, where both fields are clipped", () => {
    const node = pin({ artifact_ref: JIG, pin_mode: "pinned" }, build({ current: false }));
    expect(node.querySelector('[data-source="build.current"]')?.getAttribute("aria-hidden")).toBe(
      "true",
    );
    expect(node.querySelector('[data-source="build.status"]')?.getAttribute("aria-hidden")).toBe(
      "true",
    );
  });
});

describe("header chips — labelled group (#83)", () => {
  it("puts role=group and an aria-label on the pin/export/BOM cluster", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.project(), {
      status: "ok",
      root: "/tmp/p",
      name: "fixture",
      units: "mm",
      parts: [],
      serve_mode: true,
    } satisfies ProjectDocument);
    const host = mount(
      <QueryClientProvider client={client}>
        <Header />
      </QueryClientProvider>,
    );
    const group = host.querySelector('[role="group"][aria-label]');
    expect(group).not.toBeNull();
    expect(group?.querySelector('[data-testid="artifact-pin"]')).not.toBeNull();
    expect(group?.querySelector("[data-chrome-export]")).not.toBeNull();
    expect(group?.querySelector("[data-chrome-bom]")).not.toBeNull();
    expect(group?.getAttribute("aria-label")).toBe(copy.header.chromeGroup);
  });
});

/*
 * §4.1(d), amended 2026-09-01 — repair (a).
 *
 * The section carried two readings of what the header draws: an opening bullet
 * naming "the artifact pin **and** the build-state chip", and the 2026-09-01
 * one-chip collapse. Both are struck but the collapse, and the collapse is now
 * the sole normative statement — so the thing worth asserting is the SINGULAR:
 * one element mints `data-build-state`, it is the pin, and no second element in
 * the bar draws a build-state or pin-freshness word.
 *
 * The negative half is the half that catches a regression here. A second badge
 * added beside the pin would satisfy every existing assertion in this file: the
 * pin still has its attribute, both `<Fact>`s are still attributed, the group
 * still has its label. Only a count notices.
 */
describe("§4.1(d) — one chip, one build-state word", () => {
  function header(state: Partial<WorkspaceState>, document: BuildDocument | undefined): HTMLElement {
    workspaceStore.reset({ ...DEFAULT_STATE, ...state });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.project(), {
      status: "ok",
      root: "/tmp/p",
      name: "fixture",
      units: "mm",
      parts: state.part === undefined || state.part === null ? [] : [state.part],
      serve_mode: true,
    } satisfies ProjectDocument);
    if (document !== undefined && typeof state.part === "string") {
      client.setQueryData(keys.build(state.part), document);
    }
    return mount(
      <QueryClientProvider client={client}>
        <Header />
      </QueryClientProvider>,
    );
  }

  /** Every pin/build state the bar can be in, which is where "in any state" bites. */
  const STATES: readonly (readonly [string, Partial<WorkspaceState>, BuildDocument | undefined])[] =
    [
      ["following, up to date", { part: "tread", artifact_ref: JIG, pin_mode: "current" }, build()],
      [
        "following, preview",
        { part: "tread", artifact_ref: JIG, pin_mode: "current" },
        build({ current: false }),
      ],
      [
        "following, failed",
        { part: "tread", artifact_ref: JIG, pin_mode: "current" },
        build({ status: "error", current: false }),
      ],
      [
        "following, not built",
        { part: "tread", artifact_ref: null, pin_mode: "current" },
        build({ status: "not_built", current: false, artifact_ref: null }),
      ],
      ["held", { part: "tread", artifact_ref: JIG, pin_mode: "pinned" }, build({ current: false })],
      ["no build document", { part: "tread", artifact_ref: null, pin_mode: "current" }, undefined],
    ];

  it.each(STATES)("mints data-build-state once, on the pin — %s", (_label, state, document) => {
    const host = header(state, document);
    const minted = host.querySelectorAll("[data-build-state]");
    expect(minted.length).toBeLessThanOrEqual(1);
    for (const node of minted) {
      expect(node.getAttribute("data-testid")).toBe("artifact-pin");
    }
  });

  it.each(STATES)("draws no second build-state word — %s", (_label, state, document) => {
    const host = header(state, document);
    const text = host.textContent ?? "";
    for (const word of Object.values(copy.buildState)) {
      const drawn = text.split(word).length - 1;
      expect(drawn, word).toBeLessThanOrEqual(1);
    }
  });

  it.each(STATES)("never draws the pin-freshness word in the bar — %s", (_label, state, document) => {
    // §4.1(d): "`pinMode.current`/`pin.current` is **not drawn as a word in the
    // header in any state** and survives only as title-attribute and
    // `data-pin-mode` text." The pin axis is still readable — `data-pin-mode`
    // is on the chip and the title says which artifact is showing — and the
    // key is not deleted, because §12.1's own copy still uses the vocabulary.
    //
    // `Follow current` is exempt and is the reason this reads the bar with the
    // controls removed: it is a VERB on a button — the action §4.5 requires the
    // header to offer — not a state word reporting pin freshness. The defect
    // the clause names is a *label* printing the state, which is what the
    // shipped bar's disabled `held` button was.
    const host = header(state, document);
    const bar = host.querySelector("header");
    for (const control of bar?.querySelectorAll("button") ?? []) control.remove();
    expect(bar?.textContent ?? "").not.toContain(copy.pinMode.current);
    expect(host.querySelector("[data-pin-mode]")).not.toBeNull();
  });

  it("keeps the two vocabularies apart, and keeps both keys", () => {
    // The copy half of the ruling: `buildState.current` is the drawn word while
    // following current; `pinMode.current` stays for §12.1's pin copy. Neither
    // key is deleted — a build that draws BOTH words in the bar is what fails.
    expect(copy.buildState.current).toBe("up to date");
    expect(copy.pinMode.current).toBe("current");
    expect(copy.buildState.current).not.toBe(copy.pinMode.current);
  });
});

describe("Follow current — disabled when the selected part has no build (#90)", () => {
  it("does not discard a held artifact when the selected part is unbuilt", () => {
    workspaceStore.reset({
      ...DEFAULT_STATE,
      part: "assembly_jig",
      artifact_ref: JIG,
      pin_mode: "pinned",
      selection: { selection_id: "s", kind: "face", bundle_ref: "artifact:selection-bundle:sha256:x" },
      measure: { a: "s" },
    });
    workspaceStore.update({ part: "kerf_card" });
    const node = pin(
      workspaceStore.getSnapshot(),
      build({ status: "not_built", current: false, artifact_ref: null, geometry_count: 0 }),
    );
    const follow = node.querySelector('[data-pin-action="follow"]');
    expect(follow?.getAttribute("aria-disabled")).toBe("true");
    expect(follow?.getAttribute("title") ?? "").toContain("kerf_card");
    expect(workspaceStore.getSnapshot().artifact_ref).toBe(JIG);
    expect(workspaceStore.getSnapshot().pin_mode).toBe("pinned");
    expect(workspaceStore.getSnapshot().selection).not.toBeNull();
    act(() => {
      follow?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    });
    expect(workspaceStore.getSnapshot().artifact_ref).toBe(JIG);
    expect(workspaceStore.getSnapshot().selection).not.toBeNull();
  });
});

describe("create_part — follow the new part unless held (#58/#54/#49)", () => {
  it("selects a name the tree did not have while following current", () => {
    const store = new WorkspaceStore({ ...DEFAULT_STATE, part: "kerf_card", pin_mode: "current" });
    const created = createdPartNames(["kerf_card", "riser"], ["kerf_card", "riser", "assembly_jig"]);
    expect(created).toEqual(["assembly_jig"]);
    adoptCreatedPart(store, created);
    expect(store.getSnapshot().part).toBe("assembly_jig");
    expect(store.getSnapshot().pin_mode).toBe("current");
  });

  it("does not auto-advance a pin whose mode is pinned", () => {
    const store = new WorkspaceStore({
      ...DEFAULT_STATE,
      part: "kerf_card",
      artifact_ref: JIG,
      pin_mode: "pinned",
    });
    adoptCreatedPart(store, ["assembly_jig"]);
    expect(store.getSnapshot().part).toBe("kerf_card");
    expect(store.getSnapshot().artifact_ref).toBe(JIG);
    expect(store.getSnapshot().pin_mode).toBe("pinned");
  });
});

const BASE_SUBMISSION: Submission = {
  subject: "export",
  format: "step",
  layout: "as_built",
  blankWidth: "",
  blankHeight: "",
  drawingKind: "dimensioned",
  sheet: "A4",
  docKind: "bom",
  artifactRef: JIG,
  part: "assembly_jig",
};

// ---------------------------------------------------------------------------
// J-web-viewport-5 — the held-artifact source part is READ, not remembered.
//
// `heldFrom` is a private instance field on `WorkspaceStore`, explicitly kept
// out of the serialised record ("§4.5's closed record does not grow a field
// for a sentence"). Its own `reset()` comment already names the reload case:
// "A pasted URL can hold a ref without saying which part minted it." A real
// reload constructs a FRESH `WorkspaceStore` (its `heldFrom` starts `null` by
// the class field initializer) and then `reset()`s it from the decoded URL —
// so nothing the STORE can do recovers the fact.
//
// The fix is therefore not in the store: `state/heldPart.tsx` reads the part off
// the artifact itself (`GET /artifacts/{ref}/meta`), which makes it a server
// value that survives a reload and a pasted URL, and keeps §4.5's record closed.
// These cases pin the store's half of that split — the within-session fallback,
// and the honest `null` that makes the read necessary.
// ---------------------------------------------------------------------------

describe("the held artifact's source part (J-web-viewport-5)", () => {
  const HELD_REF = "artifact:build:sha256:" + "c".repeat(64);

  it("survives switching the selected part WITHIN one session", () => {
    const store = new WorkspaceStore();
    store.update({ part: "bracket" });
    store.hold(HELD_REF);
    store.update({ part: "kerf_card" });
    expect(store.heldFromPart()).toBe("bracket");
  });

  it("is not remembered across a reload — which is why the fact is READ, not remembered", () => {
    // Simulate a reload: the live store's snapshot is exactly what a reload's
    // decoded URL would carry (same `pin_mode`, same `artifact_ref`), handed
    // to a BRAND NEW store instance — the shape a fresh page load actually
    // takes (`decodeWorkspaceUrl` → `reset()` on a store that just booted).
    const live = new WorkspaceStore();
    live.update({ part: "bracket" });
    live.hold(HELD_REF);
    const reloaded = new WorkspaceStore();
    reloaded.reset({ ...live.getSnapshot() });

    // The pin round-trips (`pin_mode`, `artifact_ref`) and the source part does
    // not, and **no store-level fix can change that**: a fresh instance has no
    // memory of a hold that happened in a previous document, and §4.5's record
    // is closed, so the fact cannot ride in the URL either. Inferring it from
    // `state.part` would be worse than nothing — in the split state the URL's
    // part is the SELECTED one, so the inference would name the wrong part on
    // exactly the screen §4.1 exists for.
    //
    // So this is the ledger's assertion "the workspace object no longer carries
    // a derived fact", stated positively: the store answers `null` rather than
    // guessing, and `state/heldPart.tsx` reads the answer off
    // `GET /artifacts/{ref}/meta` instead — attributable, reload-surviving, and
    // no wider record. Its `part` projection is the one server change still
    // outstanding (see the handoff notes); until it lands, `useHeldPart` falls
    // back to exactly this value, so the fallback is what this pins.
    expect(reloaded.getSnapshot().pin_mode).toBe("pinned");
    expect(reloaded.getSnapshot().artifact_ref).toBe(HELD_REF);
    expect(reloaded.heldFromPart()).toBeNull();
  });

  it("names the source part as VISIBLE text when held from another part, not only on the title attribute", () => {
    // §4.1's visible, inherited marking (J-web-viewport-9's clause) must be
    // satisfiable by something other than a tooltip. The banner sentence
    // itself already carries the words when `heldFrom` is known; the
    // reproduction above is what makes it unknown after a reload.
    const store = new WorkspaceStore();
    store.update({ part: "bracket" });
    store.hold(HELD_REF);
    store.update({ part: "kerf_card" });
    const banner = copy.header.pinnedBanner(store.heldFromPart(), "kerf_card");
    expect(banner).toContain("bracket");
  });
});

// ---------------------------------------------------------------------------
// J-web-viewport-9 — the marking is words, mounted per-region, only while the
// two axes disagree. `<PinSplitMarker>` is what discharges §4.1's "every panel
// below inherits that marking"; these pin its render contract directly rather
// than through a whole `Stage`/`Inspector` mount, since the predicate itself
// is already pinned in `test/pinSplit.test.ts`.
// ---------------------------------------------------------------------------

describe("PinSplitMarker — the marking is words, per region (J-web-viewport-9)", () => {
  const split = pinSplit("pinned", "bracket", "kerf_card");
  if (split === null) throw new Error("fixture split must not be null");

  it("mounts nothing for either region when the two axes agree", () => {
    const agreeing = pinSplit("pinned", "bracket", "bracket");
    const stage = mount(<PinSplitMarker split={agreeing} region="stage" />);
    expect(stage.querySelector("[data-pin-split]")).toBeNull();
    act(() => {
      mounted?.root.unmount();
    });
    mounted?.host.remove();
    mounted = null;
    const inspector = mount(<PinSplitMarker split={agreeing} region="inspector" />);
    expect(inspector.querySelector("[data-pin-split]")).toBeNull();
  });

  it("names the held part as VISIBLE text on the stage region, attributed with the ref", () => {
    const host = mount(
      <PinSplitMarker split={split} region="stage" artifactRef={JIG} />,
    );
    const node = host.querySelector('[data-pin-split="stage"]');
    expect(node).not.toBeNull();
    expect(node?.getAttribute("data-pin-split-part")).toBe("bracket");
    // Visible text, not only the attribute — a screen reader with CSS off and
    // a sighted reader both need to meet the fact.
    expect(node?.textContent ?? "").toContain("bracket");
    expect(node?.textContent ?? "").toContain(formatRef(JIG, CHIP_REF_WIDTH).split(" · ")[1] ?? "nomatch");
  });

  it("names the selected part as visible text on the inspector region, with no ref attribution", () => {
    const host = mount(<PinSplitMarker split={split} region="inspector" />);
    const node = host.querySelector('[data-pin-split="inspector"]');
    expect(node).not.toBeNull();
    expect(node?.getAttribute("data-pin-split-part")).toBe("kerf_card");
    expect(node?.textContent ?? "").toContain("kerf_card");
    // The inspector shows the SELECTED part's own panels — attributing a ref
    // there would misname whose artifact the reference belongs to.
    expect(node?.querySelector("[data-source='workspace.artifact_ref']")).toBeNull();
  });

  it("carries BOTH part names in its accessible text, on either region", () => {
    // A screen-reader user meets one region at a time; "showing bracket" alone
    // does not say that the other region is showing something else.
    const stage = mount(<PinSplitMarker split={split} region="stage" />);
    const stageNode = stage.querySelector('[data-pin-split="stage"]');
    expect(stageNode?.getAttribute("aria-label") ?? "").toContain("bracket");
    expect(stageNode?.getAttribute("aria-label") ?? "").toContain("kerf_card");
    act(() => {
      mounted?.root.unmount();
    });
    mounted?.host.remove();
    mounted = null;
    const inspector = mount(<PinSplitMarker split={split} region="inspector" />);
    const inspectorNode = inspector.querySelector('[data-pin-split="inspector"]');
    expect(inspectorNode?.getAttribute("aria-label") ?? "").toContain("bracket");
    expect(inspectorNode?.getAttribute("aria-label") ?? "").toContain("kerf_card");
  });

  it("renders null (no wrapper element at all) when split is null", () => {
    const host = mount(<PinSplitMarker split={null} region="stage" />);
    expect(host.childElementCount).toBe(0);
  });
});

describe("export idempotency key is per part (issue 100)", () => {
  beforeEach(() => {
    resetSubmissionKeys();
  });

  it("mints a distinct key when only the part changes", () => {
    const jig = submissionKeyFor({ ...BASE_SUBMISSION, part: "assembly_jig" });
    const kerf = submissionKeyFor({ ...BASE_SUBMISSION, part: "kerf_card" });
    expect(signature({ ...BASE_SUBMISSION, part: "assembly_jig" })).not.toBe(
      signature({ ...BASE_SUBMISSION, part: "kerf_card" }),
    );
    expect(jig).not.toBe(kerf);
    expect(submissionKeyFor({ ...BASE_SUBMISSION, part: "assembly_jig" })).toBe(jig);
  });

  it("still reuses the key across retries of one unchanged submission", () => {
    const first = submissionKeyFor(BASE_SUBMISSION);
    const again = submissionKeyFor({ ...BASE_SUBMISSION });
    expect(again).toBe(first);
  });
});

const OUTPUT = {
  path: "exports/jig.step",
  blob: "sha256:1122334455667788990011223344556677889900112233445566778899001122",
  bytes: 145426,
  content_type: "model/step",
  filename: "assembly_jig-112233445566.step",
};

const RESULT: ExportResult = {
  paths: [OUTPUT.path],
  source_artifact_ref: JIG,
  source_input_hashes: {},
  export_hashes: { [OUTPUT.path]: OUTPUT.blob },
};

const HISTORY: ExportsDocument = {
  status: "ok",
  part: "assembly_jig",
  exports: [
    {
      op_id: "op-1",
      format: "step",
      layout: "as_built",
      state: "COMMITTED",
      source_artifact_ref: JIG,
      source_input_hashes: {},
      extra: {},
      outputs: [OUTPUT],
      total_bytes: OUTPUT.bytes,
    },
  ],
  total_bytes: OUTPUT.bytes,
  unpin_available: false,
  max_download_bytes: 64 * 1024 * 1024,
};

describe("header Export — produce then give (issue 77, after 100)", () => {
  it("matches the committed row this dialog produced", () => {
    const row = producedRow(HISTORY, RESULT, "step");
    expect(row?.outputs[0]?.blob).toBe(OUTPUT.blob);
    expect(row?.outputs[0]?.bytes).toBe(OUTPUT.bytes);
    expect(producedRow(HISTORY, RESULT, "stl")).toBeNull();
  });

  it("shows Download with the byte count after Export, and does not put download on Export", async () => {
    let downloaded: string | null = null;
    const host = mount(
      <ExportChrome
        part="assembly_jig"
        pinned={JIG}
        pinMode="pinned"
        history={HISTORY}
        onExport={() => Promise.resolve(RESULT)}
        onDownload={async (output) => {
          downloaded = output.blob;
        }}
        onOpenInspector={() => undefined}
      />,
    );
    const run = host.querySelector("[data-export-run]");
    expect(run?.querySelector("svg[data-icon='download']")).toBeNull();
    expect(host.querySelector("[data-export-download]")).toBeNull();
    await act(async () => {
      run?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    });
    const bytes = host.querySelector("[data-source='exports[].outputs[].bytes']");
    const download = host.querySelector("[data-export-download]");
    expect(bytes?.getAttribute("data-value")).toBe(String(OUTPUT.bytes));
    expect(download?.getAttribute("data-export-download")).toBe(OUTPUT.blob);
    expect(download?.querySelector("svg[data-icon='download']")).not.toBeNull();
    expect(
      (bytes?.compareDocumentPosition(download as Node) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await act(async () => {
      download?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    });
    expect(downloaded).toBe(OUTPUT.blob);
  });

  it("announces a refusal in a live region (#85)", () => {
    const host = mount(
      <ExportChrome
        part="assembly_jig"
        pinned={null}
        pinMode="current"
        onExport={() => Promise.reject(new Error("not called"))}
        onDownload={() => Promise.reject(new Error("not called"))}
        onOpenInspector={() => undefined}
      />,
    );
    const note = host.querySelector("[data-export-refusal]");
    expect(note?.getAttribute("role")).toBe("alert");
    expect(note?.getAttribute("aria-live")).toBe("assertive");
  });
});

describe("selected part row — name keeps pixels (#88)", () => {
  it("gives the label an ellipsis-wide floor and lets trailing shrink", () => {
    const rules = css("system/TreeRow.module.css");
    expect(rules).toMatch(/\.label\s*\{[^}]*min-width:\s*8ch/);
    expect(rules).toMatch(/\.trailing\s*\{[^}]*flex:\s*0 1 auto/);
    expect(rules).toMatch(/\.trailing\s*\{[^}]*min-width:\s*0/);
    expect(rules).not.toMatch(/\.trailing\s*\{[^}]*flex:\s*none/);
  });

  it("does not reopen the rail overflow contract (#32)", () => {
    const shell = css("components/Shell.module.css");
    expect(shell).toMatch(/\.rail\s*\{[^}]*overflow-x:\s*hidden/);
    expect(shell).toMatch(/\.rail\s*>\s*\*\s*\{[^}]*min-width:\s*0/);
  });
});
