// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The composer's decisions, tested where they are decided (INTERFACE.md §7A).
//
// The pure half of §7A lives in `stream/composerContext.ts` and `api/refresh.ts`;
// the JSX only spells those decisions into the §7A.10 attributes. So the
// assertions below are on the two pure modules plus a DOM pass over the rendered
// form, which is what the e2e addresses.
//
// THE CLAIM THAT MATTERS MOST is the one §7A.3 calls the sharpest constraint in
// the section: **the client sends references and never facts.** A test that only
// checked "the envelope has a `part` field" would pass on an implementation that
// also sent a bounding box, so the assertions here are on the closed member set
// and on the two members where a fact would most plausibly be smuggled in —
// `explode_t` (a parameter, never a displacement) and `hidden_labels` (the
// toggles, never what is visible).

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Composer, COMPOSER_STATES, DISABLED_REASONS } from "../../src/components/stream/Composer";
import { WorkspaceError } from "../../src/api/client";
import {
  CONTEXT_MEMBERS,
  cancelRun,
  createSession,
  sendPrompt,
  type ContextMember,
  type PromptDocument,
} from "../../src/api/sessions";
import type * as SessionsModule from "../../src/api/sessions";
import type { ProvidersDocument } from "../../src/api/providers";
import type { DfmDocument } from "../../src/api/types";
import { collectSessionIds } from "../../src/api/projectRefresh";
import { refreshAfterTurn, refreshKeys } from "../../src/api/refresh";
import { keys } from "../../src/api/queries";
import { defaultModel, modelsFrom, showModelChrome } from "../../src/stream/composerChrome";
import {
  CHIP_ORDER,
  SUMMARY_ORDER,
  addViewOnLine,
  chipsFor,
  envelopeFor,
  summaryFor,
} from "../../src/stream/composerContext";
import { DEFAULT_STATE, type WorkspaceState } from "../../src/state/workspace";
import { workspaceStore } from "../../src/state/react";
import { formatRef } from "../../src/system";
import { sessionPromptStore } from "../../src/stream/sessionPrompts";
import { copy } from "../../src/copy";

// The one route the last block counts calls on. Everything else in the module is
// the real thing — `CONTEXT_MEMBERS` is asserted against directly, and a
// wholesale stub would make that assertion about the stub.
vi.mock("../../src/api/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof SessionsModule>();
  return { ...actual, sendPrompt: vi.fn(), cancelRun: vi.fn(), createSession: vi.fn() };
});

const NOTHING: ReadonlySet<ContextMember> = new Set();

/** Every `.ts`/`.tsx` under a directory, for the dead-surface gate below. */
function sourceFiles(root: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(path));
    else if (path.endsWith(".ts") || path.endsWith(".tsx")) out.push(path);
  }
  return out;
}

function stateWith(patch: Partial<WorkspaceState>): WorkspaceState {
  return { ...DEFAULT_STATE, ...patch };
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
    providers: [
      {
        id: "heph-fake",
        kind: "openai_compatible",
        name: "Fake",
        models: [{ id: "heph-fake-model", name: "Heph Fake Model" }],
        source: "project",
        health: "accepted",
        last_observed_at: null,
        available: true,
        unavailable_reason: null,
      },
    ],
    ...overrides,
  };
}

/** The composer inside a query client, as `StreamPanel` mounts it. */
function markup(
  props: Partial<React.ComponentProps<typeof Composer>> = {},
  seeded: { providers?: ProvidersDocument; dfm?: DfmDocument } = {},
): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (seeded.providers !== undefined) {
    client.setQueryData(keys.providers(), seeded.providers);
  }
  if (seeded.dfm !== undefined) {
    client.setQueryData(keys.dfm(seeded.dfm.part), seeded.dfm);
  }
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <Composer
        sessionId="sess-1"
        profile="orchestrator"
        attach={null}
        agentUnavailable={false}
        liveRunId={null}
        streamLive={true}
        {...props}
      />
    </QueryClientProvider>,
  );
}

function attribute(html: string, name: string): string | null {
  const match = new RegExp(`${name}="([^"]*)"`).exec(html);
  return match === null ? null : (match[1] ?? null);
}

// ---------------------------------------------------------------------------
// §7A.3 — the envelope carries references, never facts

describe("the context envelope", () => {
  it("draws every member from the closed set and invents none", () => {
    const envelope = envelopeFor(
      stateWith({
        part: "tread",
        view: "+X",
        explode_t: 0.5,
        section_plane: "+Z@10",
        focus: "geometry:cleat_left",
      }),
      ["cleat_left"],
      NOTHING,
    );
    expect(envelope).not.toBeNull();
    // The set equality is the assertion: containment would pass on an
    // implementation that also sent a number it computed.
    for (const key of Object.keys(envelope ?? {})) {
      expect(CONTEXT_MEMBERS as readonly string[]).toContain(key);
    }
  });

  it("carries the explode PARAMETER and has nowhere to put a displacement", () => {
    // §7A.3: "`explode_t` is a parameter, not a displacement… The envelope
    // carries `t`. It never carries a distance."
    const envelope = envelopeFor(stateWith({ part: "tread", explode_t: 0.25 }), [], NOTHING);
    expect(envelope?.explode_t).toBe(0.25);
    expect(JSON.stringify(envelope)).not.toMatch(/mm/);
  });

  it("reports the hidden toggles, sorted, and never a visible count", () => {
    // Sorted so the envelope is a function of the SET rather than of toggle
    // order — which is what keeps the server's composed block deterministic.
    const envelope = envelopeFor(
      stateWith({ part: "tread" }),
      ["cleat_right", "cleat_left"],
      NOTHING,
    );
    expect(envelope?.hidden_labels).toEqual(["cleat_left", "cleat_right"]);
  });

  it("submits the selection ids and never describes the selection", () => {
    const envelope = envelopeFor(
      stateWith({
        part: "tread",
        selection: { selection_id: "12", kind: "face", bundle_ref: "artifact:selection-bundle:x" },
      }),
      [],
      NOTHING,
    );
    // `kind` is the server's answer about the selection and stays out: the
    // server resolves the ids through §12.3 and says what they are.
    expect(envelope?.selection).toEqual({
      selection_id: "12",
      bundle_ref: "artifact:selection-bundle:x",
    });
  });

  it("sends the pin mode only with the ref it qualifies", () => {
    const withRef = envelopeFor(
      stateWith({ part: "tread", artifact_ref: "artifact:build:sha256:a", pin_mode: "pinned" }),
      [],
      NOTHING,
    );
    expect(withRef?.pin_mode).toBe("pinned");
    const withoutRef = envelopeFor(stateWith({ part: "tread" }), [], NOTHING);
    expect(withoutRef?.pin_mode).toBeUndefined();
  });

  it("is null for the blank canvas, whatever the tabs say", () => {
    // §7A.3: "`context: null` is the blank canvas and the server composes
    // nothing." A workspace with a tab selected and no part, no pin and no
    // selection is a blank canvas however many navigation tokens it holds.
    expect(envelopeFor(DEFAULT_STATE, [], NOTHING)).toBeNull();
    expect(
      envelopeFor(stateWith({ stage_tab: "script", inspector_tab: "checks" }), [], NOTHING),
    ).toBeNull();
  });

  it("honours a dropped member — every member is opt-out", () => {
    const dropped: ReadonlySet<ContextMember> = new Set(["part"]);
    const envelope = envelopeFor(
      stateWith({ part: "tread", section_plane: "+Z@10" }),
      [],
      dropped,
    );
    expect(envelope?.part).toBeUndefined();
    expect(envelope?.section_plane).toBe("+Z@10");
  });

  it("drops the whole envelope when every reference is dropped", () => {
    const dropped: ReadonlySet<ContextMember> = new Set(["part"]);
    expect(envelopeFor(stateWith({ part: "tread" }), [], dropped)).toBeNull();
  });

  it("lets an explicit Add current view make the view a reference", () => {
    // Navigation tokens alone are still the blank canvas. Adding the view
    // is the operator saying the camera token *is* the reference.
    const added: ReadonlySet<ContextMember> = new Set(["view"]);
    const envelope = envelopeFor(DEFAULT_STATE, [], NOTHING, added);
    expect(envelope).not.toBeNull();
    expect(envelope?.view).toBe(DEFAULT_STATE.view);
    for (const key of Object.keys(envelope ?? {})) {
      expect(CONTEXT_MEMBERS as readonly string[]).toContain(key);
    }
  });
});

describe("the chip row", () => {
  it("offers a chip for every reference the state names, in a fixed order", () => {
    const chips = chipsFor(
      stateWith({
        part: "tread",
        artifact_ref: "artifact:build:sha256:a",
        explode_t: 0.5,
        focus: "geometry:tread",
      }),
      ["cleat_left"],
    );
    const order = chips.map((chip) => chip.key);
    // A stable order rather than a set: a row that reshuffled as state changed
    // would move the drop control out from under the pointer.
    expect(order).toEqual([...order].sort((a, b) => CHIP_ORDER.indexOf(a) - CHIP_ORDER.indexOf(b)));
    expect(order).toContain("part");
    expect(order).toContain("hidden_labels");
  });

  it("renders the hidden set as a COUNT of toggles, not a value", () => {
    const chips = chipsFor(stateWith({ part: "tread" }), ["a", "b"]);
    const hidden = chips.find((chip) => chip.key === "hidden_labels");
    expect(hidden?.count).toBe(2);
    expect(hidden?.value).toBeNull();
  });

  it("offers no chip for pin_mode, which is not independently droppable", () => {
    const chips = chipsFor(stateWith({ artifact_ref: "artifact:build:sha256:a" }), []);
    expect(chips.map((chip) => chip.key)).not.toContain("pin_mode");
  });
});

// ---------------------------------------------------------------------------
// §7A.11 — the read-refresh boundary

describe("the read-refresh boundary", () => {
    it("names exactly the keys §7A.11 enumerates for a selected part", () => {
    expect(refreshKeys("tread")).toEqual([
      keys.project(),
      keys.parts(),
      keys.gitStatus(),
      keys.build("tread"),
      keys.script("tread"),
      keys.params("tread"),
      keys.properties("tread"),
      keys.checks("tread"),
      keys.dfm("tread"),
    ]);
  });

  it("still refreshes the project keys on the blank canvas", () => {
    // The case that matters: no part is selected, and `keys.parts()` is how the
    // part the agent just created appears in the tree without a manual reload.
    expect(refreshKeys(null)).toEqual([keys.project(), keys.parts(), keys.gitStatus()]);
  });

  it("collects listed sessions and thread children so a delegated turn refreshes (#92)", () => {
    expect(collectSessionIds(["orch"], ["orch", "child"])).toEqual(["child", "orch"]);
    expect(collectSessionIds([], ["child"])).toEqual(["child"]);
    expect(collectSessionIds(["a", "b"], ["b"])).toEqual(["a", "b"]);
  });

  it("hangs the §7A.11 terminal observer at project lifetime, not Stream mount (#92)", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const observer = readFileSync(join(here, "../../src/api/projectRefresh.ts"), "utf8");
    const shell = readFileSync(join(here, "../../src/components/Shell.tsx"), "utf8");
    const panel = readFileSync(join(here, "../../src/components/stream/StreamPanel.tsx"), "utf8");
    expect(observer).toContain("frame.kind !== \"terminal\"");
    expect(observer).toContain("refreshAfterTurn(client, partRef.current)");
    expect(observer).toContain("collectSessionIds");
    expect(observer).toContain('invalidateQueries({ queryKey: ["sessions"] })');
    expect(observer).not.toContain("setQueryData");
    expect(shell).toContain("useProjectRefresh()");
    expect(panel).not.toContain("stream.terminals === seenTerminals.current");
  });

  it("does not move a held pin when those keys are invalidated (#59)", () => {
    const A = "artifact:build:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    workspaceStore.reset({ ...DEFAULT_STATE, artifact_ref: A, pin_mode: "pinned" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    refreshAfterTurn(client, "kerf_card");
    expect(invalidate).toHaveBeenCalled();
    expect(workspaceStore.getSnapshot().artifact_ref).toBe(A);
    expect(workspaceStore.getSnapshot().pin_mode).toBe("pinned");
    workspaceStore.reset(DEFAULT_STATE);
  });
});

// ---------------------------------------------------------------------------
// §7A.10 — the DOM contract, which the e2e addresses

describe("the DOM contract", () => {
  it("carries the closed state vocabulary and the session it is bound to", () => {
    const html = markup();
    expect(attribute(html, "data-composer-state")).toBe("idle");
    expect(COMPOSER_STATES as readonly string[]).toContain(
      attribute(html, "data-composer-state") ?? "",
    );
    expect(attribute(html, "data-session-id")).toBe("sess-1");
    expect(attribute(html, "data-profile")).toBe("orchestrator");
    expect(attribute(html, "data-send-state")).toBe("ok");
    expect(html).toContain("data-composer-input");
  });

  it("says no_session rather than rendering nothing", () => {
    // §7A.8's argument generalised: a state that exists for a reason reads as
    // designed; the same state with its content missing reads as a bug.
    const html = markup({ sessionId: null });
    expect(attribute(html, "data-disabled-reason")).toBe("no_session");
    expect(html).not.toMatch(/<textarea[^>]*disabled/);
  });

  it("names agent_unavailable, its cause, and the path the server checked", () => {
    const html = markup({
      agentUnavailable: true,
      attach: {
        attached: false,
        config_path: "/tmp/p/.heph/providers.json",
        generation: 1,
        cause: "no_provider_config",
      },
    });
    expect(attribute(html, "data-disabled-reason")).toBe("agent_unavailable");
    expect(attribute(html, "data-attach-cause")).toBe("no_provider_config");
    expect(attribute(html, "data-attach-path")).toBe("/tmp/p/.heph/providers.json");
    // §7A.8: it names the file and does NOT offer to write it. The one action
    // it offers re-reads a configuration the operator fixed themselves.
    expect(html).toContain("data-attach-retry");
  });

  it("keeps every disabled reason inside the closed vocabulary", () => {
    for (const reason of DISABLED_REASONS) {
      expect(["agent_unavailable", "run_in_flight", "no_session"]).toContain(reason);
    }
  });

  it("mounts NO cancel while the run is not cancellable, and keeps the attribute", () => {
    // §7A.6 / §7A.10(b), amended 2026-09-01. Between submit and the first event
    // carrying the run id, cancel is unavailable — and a permanently-mounted
    // disabled button for nearly all of the time is the chrome the amendment
    // removes. The FACT does not leave the DOM: `data-cancel-state` is still on
    // the form, and its reason is on the form's `title`.
    const html = markup({ liveRunId: null });
    expect(attribute(html, "data-cancel-state")).toBe("unavailable");
    expect(html).not.toContain("data-composer-cancel");
    const host = document.createElement("div");
    host.innerHTML = html;
    expect(host.querySelector("[data-composer]")?.getAttribute("title")).toBe(
      copy.composer.cancelIdle,
    );
  });

  it("mounts cancel the instant the state says available (the other half)", () => {
    const html = markup({ liveRunId: "run-live", streamLive: true });
    expect(attribute(html, "data-cancel-state")).toBe("available");
    expect(html).toContain("data-composer-cancel");
  });

  it("has exactly one button-role element in the resting input row (§7A.10(a))", () => {
    // The clause's own test, restated 2026-09-02 (§0.2c, C15) to the INPUT
    // ROW — the action row it used to query no longer mounts at rest, and a
    // query against a row that does not mount returns zero, not one. (c)
    // still puts `[data-context-disclose]` inside the same <form>, attached
    // to the summary line, so a form-scoped count is two at rest by design;
    // the rule is that the row holding the send target holds exactly one.
    const html = markup();
    const host = document.createElement("div");
    host.innerHTML = html;
    const row = host.querySelector("[data-composer-input-row]");
    expect(row).not.toBeNull();
    expect(row?.contains(host.querySelector("[data-composer-input]"))).toBe(true);
    const buttons = row?.querySelectorAll("button, [role='button']");
    expect(buttons?.length).toBe(1);
    expect(buttons?.[0]?.hasAttribute("data-composer-send")).toBe(true);
    // Send keeps disabled-with-reason: a PRIMARY action that vanished would
    // leave no target for "why can't I send?", which is the opposite case
    // from Cancel.
    expect(host.querySelector("[data-composer-send]")?.getAttribute("aria-disabled")).toBe("true");
  });

  it("is exactly two rows at rest, and mounts no model chip (C15, #114)", () => {
    // §7A.10's 2026-09-02 amendment, plus #114. POSITIVE: the form's
    // directly rendered rows number two — the context row (§7A.3(a)'s summary
    // line) and the input row (the textarea with Send on the same row).
    // NEGATIVE: no meta line, no action row, no model/effort vocabulary.
    const html = markup({}, { providers: providersDocument() });
    const host = document.createElement("div");
    host.innerHTML = html;
    const form = host.querySelector("[data-composer]");
    expect(form).not.toBeNull();
    const rows = [...(form?.children ?? [])];
    expect(rows).toHaveLength(2);
    expect(rows[0]?.hasAttribute("data-context-summary")).toBe(true);
    expect(form?.querySelector("[data-composer-model]")).toBeNull();
    expect(html).not.toContain("gpt-5.5");
    expect(html).not.toContain("data-composer-provider");
    expect(rows[1]?.hasAttribute("data-composer-input-row")).toBe(true);
    expect(rows[1]?.contains(form?.querySelector("[data-composer-send]") ?? null)).toBe(true);
    expect(html).not.toContain("data-composer-hint");
    expect(html).not.toContain("data-composer-cancel");
  });

  it("adds the Cancel row only as the running exception (C15's loud path)", () => {
    // The exception half of the two-row rule: exceptional states add their
    // rows AS SPECIFIED and stay loud. Cancel's row mounts while a run is
    // cancellable (§7A.10(b)) — and it is a third row then, outside the input
    // row, so the restated (a) count still holds during the exception.
    const html = markup({ liveRunId: "run-live", streamLive: true }, { providers: providersDocument() });
    const host = document.createElement("div");
    host.innerHTML = html;
    const form = host.querySelector("[data-composer]");
    expect([...(form?.children ?? [])].length).toBe(3);
    const cancel = form?.querySelector("[data-composer-cancel]");
    expect(cancel).not.toBeNull();
    expect(host.querySelector("[data-composer-input-row]")?.contains(cancel ?? null)).toBe(false);
    const row = host.querySelector("[data-composer-input-row]");
    expect(row?.querySelectorAll("button, [role='button']").length).toBe(1);
  });

  it("puts no data-source on any context chip", () => {
    // §7A.10: "no chip carries a `data-source`, because no chip is a fact
    // (§4.6)". An empty envelope mounts no row; the row template itself
    // must still not mint a `data-source`.
    const html = markup();
    expect(html).not.toContain("data-context-chips");
    const source = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../../src/components/stream/Composer.tsx"),
      "utf8",
    );
    const row = source.slice(
      source.indexOf("function ContextChipRow"),
      source.indexOf("export function NewSessionAction"),
    );
    expect(row).toContain("data-context-key");
    expect(row).not.toContain("data-source");
    expect(row).toContain('variant="toggle"');
    expect(row).toContain("pressed={dropped}");
  });

  it("uses expanded on disclosures and toggle on context-drop (pressed discriminant)", () => {
    const source = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../../src/components/stream/Composer.tsx"),
      "utf8",
    );
    // The JSX occurrence, not the header comment's mention of the hook.
    const hook = source.indexOf('data-context-disclose=""');
    const discloseBtn = source.slice(source.lastIndexOf("<Button", hook), hook + 40);
    expect(discloseBtn).toContain("expanded={disclosed}");
    expect(discloseBtn).not.toContain("pressed={disclosed}");
    const providers = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../../src/components/ProvidersPanel.tsx"),
      "utf8",
    );
    const details = providers.slice(
      providers.lastIndexOf("<Button", providers.indexOf("data-providers-details")),
      providers.indexOf("data-providers-details") + 40,
    );
    expect(details).toContain("expanded={detailsOpen}");
    expect(details).not.toContain("pressed={detailsOpen}");
  });

  it("keeps the existing composer selectors when chrome is present", () => {
    const html = markup({}, { providers: providersDocument() });
    expect(html).toContain("data-composer=\"\"");
    expect(html).toContain("data-composer-input");
    expect(html).toContain("data-composer-send");
    expect(html).toContain("data-context-disclose");
    expect(html).toContain("data-context-summary");
    expect(html).toMatch(/<textarea[^>]*rows="1"/);
    expect(html).not.toMatch(/<textarea[^>]*rows="3"/);
    expect(html).not.toContain("data-context-chips");
    expect(html).not.toContain("data-context-add-view");
  });

  it("labels disclose in one word, attached to the summary line (§7A.10(c))", () => {
    const html = markup();
    expect(html).toContain(copy.composer.disclose);
    expect(html).not.toContain("What will the agent be told?");
    // One word each, and the hook and both strings survive the shortening.
    expect(copy.composer.disclose.split(" ")).toHaveLength(1);
    expect(copy.composer.discloseHide.split(" ")).toHaveLength(1);
    expect(copy.composer.discloseAdvisory.length).toBeGreaterThan(20);
    const host = document.createElement("div");
    host.innerHTML = html;
    const toggle = host.querySelector("[data-context-disclose]");
    // The line and the toggle are ONE affordance: the toggle is a child of the
    // summary line, quiet rather than a full `secondary` button in the actions.
    expect(toggle?.getAttribute("data-variant")).toBe("quiet");
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(toggle?.closest("[data-context-summary]")).not.toBeNull();
  });

  it("mounts no model chip at rest, even when a runtime is attached (#114)", () => {
    const html = markup({}, { providers: providersDocument() });
    const host = document.createElement("div");
    host.innerHTML = html;
    expect(host.querySelector("[data-composer-model]")).toBeNull();
    expect(host.querySelector("[data-composer-provider]")).toBeNull();
    expect(html).not.toContain("gpt-5.5");
    expect(html).not.toMatch(/<select\b/i);
    expect(host.querySelector("[data-composer-input]")).not.toBeNull();
    expect(host.querySelector("[data-composer-send]")).not.toBeNull();
    expect(host.querySelector("[data-context-summary]")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// §7A.3(a)-(e) — the resting summary line

describe("the resting context summary", () => {
  it("names the envelope's members in the fixed order, and counts the rest", () => {
    const state = stateWith({
      part: "tread",
      artifact_ref: "artifact:build:sha256:f908224c00000000000000000000000000000000000000000000000000000000",
      stage_tab: "viewport",
      inspector_tab: "results",
      view: "iso",
      focus: "geometry:tread",
    });
    const envelope = envelopeFor(state, ["cleat_left"], NOTHING);
    const summary = summaryFor(envelope, chipsFor(state, ["cleat_left"]), NOTHING);
    expect(summary.tokens.map((token) => token.key)).toEqual([
      "part",
      "artifact_ref",
      "stage_tab",
      "view",
    ]);
    // §7A.3(a)'s worked example: `Context: tread · build f908224c · viewport/results · iso`.
    expect(summary.tokens[0]?.text).toBe("tread");
    expect(summary.tokens[2]?.text).toBe("viewport/results");
    expect(summary.tokens[3]?.text).toBe("iso");
    // The ref is abbreviated where it is drawn, never re-worded here.
    expect(summary.tokens[1]?.abbreviate).toBe(true);
    expect(summary.tokens[1]?.text).toBe(state.artifact_ref);
    // `hidden_labels` and `focus` are past `view` in the drawn order, so they
    // are counted rather than drawn.
    expect(summary.remaining).toBe(2);
  });

  it("publishes exactly the envelope's own member keys (§7A.3(d))", () => {
    const state = stateWith({
      part: "tread",
      artifact_ref: "artifact:build:sha256:aa",
      focus: "geometry:tread",
    });
    const chips = chipsFor(state, []);
    const envelope = envelopeFor(state, [], NOTHING);
    const summary = summaryFor(envelope, chips, NOTHING);
    // The one member `keys` folds away, said out loud: `pin_mode` is not
    // independently addressable — it qualifies `artifact_ref` and travels with
    // it — so it has no chip and no summary token either. Everything else is
    // key-for-key the envelope this form would POST.
    const published = new Set<string>(summary.keys);
    if (envelope?.artifact_ref !== undefined) published.add("pin_mode");
    expect([...published].sort()).toEqual(Object.keys(envelope ?? {}).sort());
    // …and the same set the chips carry once the disclosure is open. Nothing
    // is dropped here, so the two must agree member for member.
    expect([...summary.keys].sort()).toEqual([...chips.map((chip) => chip.key)].sort());
    expect(SUMMARY_ORDER).not.toContain("pin_mode");
  });

  it("says an excluded member out loud, and keeps saying it when nothing is left", () => {
    // §7A.3(e). Dropping the only reference collapses the envelope to the blank
    // canvas — and the line must still report the exclusion, because "the agent
    // will not be told about the part" is a fact about what is being sent.
    const state = stateWith({ part: "tread" });
    const dropped: ReadonlySet<ContextMember> = new Set(["part"]);
    const chips = chipsFor(state, []);
    const envelope = envelopeFor(state, [], dropped);
    expect(envelope).toBeNull();
    const summary = summaryFor(envelope, chips, dropped);
    expect(summary.removed).toEqual(["part"]);
    expect(summary.keys).toEqual([]);
  });

  it("reports nothing removed on the envelope the workspace state implies", () => {
    const state = stateWith({ part: "tread" });
    const summary = summaryFor(envelopeFor(state, [], NOTHING), chipsFor(state, []), NOTHING);
    expect(summary.removed).toEqual([]);
    expect(summary.keys).toContain("part");
  });
});

// ---------------------------------------------------------------------------
// §7A.3 (C22) — "Add current view" surfaces where the gap is visible

describe("the resting line's Add current view predicate", () => {
  const SELECTION = {
    selection_id: "12",
    kind: "face",
    bundle_ref: "artifact:selection-bundle:x",
  } as const;

  it("renders exactly when view and selection are absent and a selection exists", () => {
    // The one moment the affordance matters: the operator excluded both
    // members, so the envelope carries neither, and the resting line shows
    // the gap without the disclosure open.
    const state = stateWith({ part: "tread", selection: SELECTION });
    const dropped: ReadonlySet<ContextMember> = new Set(["view", "selection"]);
    const envelope = envelopeFor(state, [], dropped);
    expect(envelope?.view).toBeUndefined();
    expect(envelope?.selection).toBeUndefined();
    expect(addViewOnLine(envelope, true, false)).toBe(true);
    // The null-envelope shape of the same gap: everything dropped.
    expect(addViewOnLine(null, true, false)).toBe(true);
  });

  it("does not render when the members are already in the envelope", () => {
    // Negative half 1. A selection that exists and was not dropped puts both
    // members in the envelope, and there is no gap to close.
    const state = stateWith({ part: "tread", selection: SELECTION });
    const envelope = envelopeFor(state, [], NOTHING);
    expect(envelope?.view).toBeDefined();
    expect(envelope?.selection).toBeDefined();
    expect(addViewOnLine(envelope, true, false)).toBe(false);
    // …and one member alone is not the gap: `view` present, selection dropped.
    const halfDropped = envelopeFor(state, [], new Set<ContextMember>(["selection"]));
    expect(halfDropped?.view).toBeDefined();
    expect(addViewOnLine(halfDropped, true, false)).toBe(false);
  });

  it("does not render when no selection exists", () => {
    // Negative half 2 — the blank canvas included: `envelope === null` with no
    // selection is not the C22 gap, it is §7A.3's blank canvas, and the
    // disclosure's own copy is the route to Add current view there.
    expect(addViewOnLine(null, false, false)).toBe(false);
    const state = stateWith({ part: "tread" });
    expect(addViewOnLine(envelopeFor(state, [], NOTHING), false, false)).toBe(false);
  });

  it("does not render while the disclosure is open", () => {
    // Negative half 3: the form's copy of the control is showing, and two
    // live copies of one affordance is the same control twice.
    const state = stateWith({ part: "tread", selection: SELECTION });
    const dropped: ReadonlySet<ContextMember> = new Set(["view", "selection"]);
    expect(addViewOnLine(envelopeFor(state, [], dropped), true, true)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// issue #13 — session chrome, still a thin client
// ---------------------------------------------------------------------------

describe("session chrome from GET /providers", () => {
  it("uses the provider's own model id as the identifier, never a house name", () => {
    const document = providersDocument();
    const models = modelsFrom(document);
    expect(models).toHaveLength(1);
    expect(models[0]?.id).toBe("heph-fake-model");
    expect(models[0]?.providerId).toBe("heph-fake");
    expect(models[0]?.id).not.toMatch(/smith|arche|composer-1/i);
    expect(models[0]?.providerId).not.toMatch(/smith|arche|composer-1/i);
  });

  it("projects the FIRST declared model, and nothing when there is none", () => {
    expect(defaultModel(modelsFrom(providersDocument()))?.id).toBe("heph-fake-model");
    expect(defaultModel([])).toBeNull();
  });

  it("names no models when the configuration file does not exist", () => {
    expect(modelsFrom(providersDocument({ config_exists: false, providers: [] }))).toEqual([]);
    expect(showModelChrome(false, [])).toBe(false);
  });

  it("hides the model projection when the runtime is missing", () => {
    const models = modelsFrom(providersDocument());
    expect(showModelChrome(true, models)).toBe(false);
    const html = markup(
      {
        agentUnavailable: true,
        attach: {
          attached: false,
          config_path: "/tmp/p/.heph/providers.json",
          generation: 1,
          cause: "no_provider_config",
        },
      },
      { providers: providersDocument() },
    );
    expect(attribute(html, "data-disabled-reason")).toBe("agent_unavailable");
    expect(html).not.toContain("data-composer-model");
    expect(html).toContain("data-context-disclose");
    expect(html).not.toContain("data-context-add-view");
  });

  it("does not rest a model chip or picker when a runtime is attached (#114)", () => {
    const html = markup({}, { providers: providersDocument() });
    expect(html).not.toContain("data-composer-model");
    expect(html).not.toContain("data-composer-provider");
    expect(html).not.toContain("gpt-5.5");
    // §7A.3's prompt body is `{text, context?}`. A Select here would write
    // nothing and read as hosted-chat chrome.
    expect(html).not.toMatch(/<select\b/i);
  });

  it("mints no effort control and no effort vocabulary (§7A.10(e)(1))", () => {
    const html = markup(
      {},
      {
        providers: providersDocument({
          providers: [
            {
              id: "heph-fake",
              kind: "openai_compatible",
              name: "Fake",
              models: [{ id: "heph-fake-model", name: "Heph Fake Model" }],
              source: "project",
              health: "accepted",
              last_observed_at: null,
              available: true,
              unavailable_reason: null,
            },
          ],
        }),
      },
    );
    // Effort is not a prompt field. The strip used to project a bare "off"
    // with no accessible name; that control is gone — and so, now, is the
    // vocabulary behind it: §7A.10(e)(1) removed `EFFORT_LEVELS` /
    // `isEffortLevel` outright, because "a closed vocabulary with no surface is
    // a spec claim by implication".
    expect(html).not.toContain("data-composer-effort");
    expect(html).not.toContain("data-composer-effort-absent");
    const chrome = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../../src/stream/composerChrome.ts"),
      "utf8",
    );
    expect(chrome).not.toContain("EFFORT_LEVELS");
    expect(chrome).not.toContain("isEffortLevel");
    expect(chrome).not.toContain("parseModelKey");
    expect(copy.composer).not.toHaveProperty("effort");
    expect(copy.composer).not.toHaveProperty("effortOff");
    expect(copy.composer).not.toHaveProperty("model");
    expect(copy.composer).not.toHaveProperty("noModels");
  });

  // §7A.10(e)(1), amended 2026-09-03 (#114): the idle composer no longer
  // imports this module. Remaining helpers stay as the GET /providers
  // projection and must be imported from src or test.
  it("exports nothing from composerChrome.ts that no src or test module imports", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const src = join(here, "../../src");
    const testRoot = join(here, "..");
    const chrome = readFileSync(join(src, "stream/composerChrome.ts"), "utf8");
    const values = [...chrome.matchAll(/^export (?:const|function|class) (\w+)/gm)].map(
      (match) => match[1] ?? "",
    );
    expect(values.length).toBeGreaterThan(0);
    const sources = [
      ...sourceFiles(src).filter((file) => !file.endsWith("composerChrome.ts")),
      ...sourceFiles(testRoot),
    ];
    const corpus = sources.map((file) => readFileSync(file, "utf8")).join("\n");
    for (const symbol of values) {
      expect(
        new RegExp(`\\b${symbol}\\b`).test(corpus),
        `${symbol} is exported from composerChrome.ts and imported by nothing under src/ or test/`,
      ).toBe(true);
    }
    const composer = readFileSync(join(src, "components/stream/Composer.tsx"), "utf8");
    expect(composer).not.toContain("data-composer-model");
    // A TYPE export is held to the neighbouring rule rather than to this one,
    // and §7A.10(e)(1)'s testable now splits the two kinds itself rather than
    // leaving the split to this comment (amended 2026-09-01):
    // it earns its keep by being NAMEABLE, so a caller can declare a variable
    // of the type an exported function returns. The test is that it appears in
    // one of this module's own exported signatures — an exported type nothing
    // in the module's surface mentions is the same dead claim as a dead value.
    const types = [...chrome.matchAll(/^export (?:interface|type) (\w+)/gm)].map(
      (match) => match[1] ?? "",
    );
    const signatures = [...chrome.matchAll(/^export (?:const|function) [\s\S]*?\{$/gm)]
      .map((match) => match[0])
      .join("\n");
    for (const symbol of types) {
      expect(
        new RegExp(`\\b${symbol}\\b`).test(signatures) || new RegExp(`\\b${symbol}\\b`).test(corpus),
        `${symbol} is exported from composerChrome.ts and named by nothing`,
      ).toBe(true);
    }
  });
});

describe("the idle composer does not host DFM chrome", () => {

  it("does not put auto_run or Run DFM on the idle composer", () => {
    const html = markup();
    expect(html).not.toContain("data-composer-dfm");
    expect(html).not.toContain("data-composer-dfm-absent");
    expect(html).not.toContain("data-dfm-auto-run-toggle");
    expect(html).not.toContain("data-dfm-run");
    expect(html).toMatch(/<textarea[^>]*rows="1"/);
  });

  it("does not grow DFM chrome on the agent_unavailable refusal", () => {
    const html = markup({
      agentUnavailable: true,
      attach: {
        attached: false,
        config_path: "/tmp/p/.heph/providers.json",
        generation: 1,
        cause: "no_provider_config",
      },
    });
    expect(html).not.toContain("data-composer-dfm-absent");
    expect(html).not.toContain("data-dfm-auto-run-toggle");
    expect(html).not.toContain("data-dfm-run");
    expect(html).toContain("data-context-disclose");
  });
});

describe("context chips do not force a 2400px stream", () => {
  it("keeps the full artifact ref on the chip and shortens only the glyphs", () => {
    const ref =
      "artifact:build:sha256:83f4822a7943a7baf11b29d15c8af23c341fb4c0bfff352ac44a3f67d4bac82b";
    const chips = chipsFor(stateWith({ part: "shelf", artifact_ref: ref }), []);
    const artifact = chips.find((chip) => chip.key === "artifact_ref");
    expect(artifact?.value).toBe(ref);
    expect(formatRef(ref)).not.toBe(ref);
    expect(formatRef(ref, 22).length).toBeLessThanOrEqual(22);
  });
});

// ---------------------------------------------------------------------------
// A LIVE DOM, for the one claim static markup cannot make.
//
// Every other assertion in this file is over `renderToStaticMarkup`, which is
// the right apparatus for a component that is a function of its props. The guard
// inside `submit` is not: it is about a state the parent cannot pass in
// (`post.phase === "refused"`, reached only by a POST that came back refused)
// being reached through an event the button does not own. So this block mounts
// the component, types into it, and dispatches the two events that bypass Send.
//
// It also carries the OTHER half of that state, which is the half a guard is
// most likely to break by accident: while a run is in flight, only **send** is
// blocked. The box stays typable and Cancel stays reachable, and both are
// asserted against the live DOM rather than by grepping the source, because
// "the guard turned Cancel off too" is exactly the regression a source grep
// cannot see.

let host: HTMLDivElement | null = null;
let unmount: (() => void) | null = null;

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterEach(() => {
  const teardown = unmount;
  if (teardown !== null) act(teardown);
  host?.remove();
  host = null;
  unmount = null;
  vi.mocked(sendPrompt).mockReset();
  vi.mocked(cancelRun).mockReset();
  vi.mocked(createSession).mockReset();
  workspaceStore.reset(DEFAULT_STATE);
  sessionPromptStore.reset();
});

function mount(props: Partial<React.ComponentProps<typeof Composer>> = {}): HTMLDivElement {
  const element = document.createElement("div");
  document.body.appendChild(element);
  const root = createRoot(element);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => {
    root.render(
      <QueryClientProvider client={client}>
        <Composer
          sessionId="sess-1"
          profile="orchestrator"
          attach={null}
          agentUnavailable={false}
          liveRunId={null}
          streamLive={true}
          {...props}
        />
      </QueryClientProvider>,
    );
  });
  host = element;
  unmount = () => {
    root.unmount();
  };
  return element;
}

function input(root: HTMLElement): HTMLTextAreaElement {
  const box = root.querySelector<HTMLTextAreaElement>("[data-composer-input]");
  if (box === null) throw new Error("the composer rendered no input");
  return box;
}

/** Type, the way a browser does: the native setter, then an `input` event. */
function type(root: HTMLElement, value: string): void {
  const setValue = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  if (setValue === undefined) throw new Error("no textarea value setter");
  const box = input(root);
  act(() => {
    setValue.call(box, value);
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function pressEnter(root: HTMLElement): void {
  const box = input(root);
  act(() => {
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  });
}

/** The form's own submit, which is the other path that never touches Send. */
function submitForm(root: HTMLElement): void {
  const form = root.querySelector("form");
  if (form === null) throw new Error("the composer rendered no form");
  act(() => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

function composer(root: HTMLElement): HTMLElement {
  const form = root.querySelector<HTMLElement>("[data-composer]");
  if (form === null) throw new Error("the composer rendered no form");
  return form;
}

/** Drive the composer into §7A.5's `run_in_flight` refusal, the only way in. */
async function refuseRunInFlight(
  props: Partial<React.ComponentProps<typeof Composer>> = {},
): Promise<HTMLDivElement> {
  vi.mocked(sendPrompt).mockRejectedValue(
    new WorkspaceError(409, "run_in_flight", "a run is already live", {
      session_id: "sess-other",
      run_id: "run-live",
    }),
  );
  const root = mount(props);
  type(root, "Bump the kerf to 0.25 mm.");
  pressEnter(root);
  expect(vi.mocked(sendPrompt)).toHaveBeenCalledTimes(1);
  await act(async () => undefined);
  expect(composer(root).getAttribute("data-disabled-reason")).toBe("run_in_flight");
  return root;
}

describe("the paths that bypass Send are gated where Send's gate is decided", () => {
  it("sends on Enter when nothing refuses it", async () => {
    const settled: PromptDocument = {
      status: "ok",
      session_id: "sess-1",
      run_id: "run-1",
      run_status: "completed",
      terminal: null,
      events: [],
      context: null,
    };
    vi.mocked(sendPrompt).mockResolvedValue(settled);
    const root = mount();
    type(root, "Bump the kerf to 0.25 mm.");
    pressEnter(root);
    expect(vi.mocked(sendPrompt)).toHaveBeenCalledTimes(1);
    expect(sessionPromptStore.getSnapshot()["sess-1"]).toBe("Bump the kerf to 0.25 mm.");
    await act(async () => undefined);
  });

  it("does NOT post a second prompt on Enter while a run is in flight", async () => {
    // §7A.5: `POST /sessions/{id}/prompt` "refuses while any run is live under
    // the runtime", and the composer disables on that refusal. `disabled` is
    // about SENDING — this component keeps the textarea typable while the turn
    // finishes, on purpose — so Enter reaches `submit` with a live text box and
    // a correctly-disabled Send. Without the guard inside `submit`, that is a
    // second POST against a run the server has already named.
    const root = await refuseRunInFlight();

    // The refusal landed, and it is the state §7A.10 names.
    expect(composer(root).getAttribute("data-composer-state")).toBe("disabled");
    // Send stays off. The point of the fix is that the keyboard agrees with it,
    // not that the button starts agreeing with the keyboard.
    expect(root.querySelector("[data-composer-send]")?.getAttribute("aria-disabled")).toBe("true");
    expect(root.querySelector("[data-composer-send]")?.hasAttribute("disabled")).toBe(false);

    pressEnter(root);
    submitForm(root);
    await act(async () => undefined);
    expect(vi.mocked(sendPrompt)).toHaveBeenCalledTimes(1);
  });

  it("blocks only SEND while a run is in flight: the box types and Cancel works", async () => {
    // The guard's blast radius, pinned. `run_in_flight` must leave the operator
    // able to write the next message and able to end the run that is in the way
    // — that pairing is the whole reason the refusal is not a dead end, and a
    // guard placed one line too broadly (say, on `composerState !== "idle"`)
    // would silently take both with it while every source grep still passed.
    vi.mocked(cancelRun).mockResolvedValue({
      status: "ok",
      run_id: "run-live",
      session_id: "sess-other",
      abandoned_questions: 0,
    });
    const root = await refuseRunInFlight({ liveRunId: "run-live", streamLive: true });

    // The box is live, and it accepts more text than the refused turn's.
    expect(input(root).disabled).toBe(false);
    type(root, "Bump the kerf to 0.25 mm and rebuild.");
    expect(input(root).value).toBe("Bump the kerf to 0.25 mm and rebuild.");

    // Cancel is reachable — §7A.10's own attribute says so, the control is not
    // disabled, and pressing it reaches the route.
    expect(composer(root).getAttribute("data-cancel-state")).toBe("available");
    const cancelButton = root.querySelector<HTMLButtonElement>("[data-composer-cancel]");
    expect(cancelButton?.getAttribute("aria-disabled")).not.toBe("true");
    expect(cancelButton?.hasAttribute("disabled")).toBe(false);
    act(() => {
      cancelButton?.click();
    });
    await act(async () => undefined);
    expect(vi.mocked(cancelRun)).toHaveBeenCalledWith("run-live");

    // And none of that posted a prompt.
    expect(vi.mocked(sendPrompt)).toHaveBeenCalledTimes(1);
  });

  it("names the holding session with the human tab title, not the UUID (#66)", async () => {
    const root = await refuseRunInFlight({
      sessionTitle: (id) => (id === "sess-other" ? "Ask about kerf_card" : id),
    });
    const holder = root.querySelector("[data-run-in-flight-session]");
    expect(holder?.getAttribute("data-run-in-flight-session")).toBe("sess-other");
    expect(holder?.textContent ?? "").toContain("Ask about kerf_card");
    expect(holder?.textContent ?? "").not.toContain("sess-other");
  });

  it("does not paint HTTP 500 under the composer when the runtime is gone (#52)", async () => {
    const report = vi.fn();
    vi.mocked(sendPrompt).mockRejectedValue(
      new WorkspaceError(500, "transport_error", "HTTP 500"),
    );
    const root = mount({ onRuntimeFault: report });
    type(root, "Bump the kerf to 0.25 mm.");
    pressEnter(root);
    await act(async () => undefined);

    expect(report).toHaveBeenCalledWith("unreachable");
    expect(composer(root).getAttribute("data-send-state")).toBe("unknown");
    expect(root.querySelector("[data-composer-refused]")).toBeNull();
    expect(root.querySelector("[data-send-unknown]")).toBeNull();
    expect(root.querySelector("[data-composer-retry]")).toBeNull();
    expect(root.textContent ?? "").not.toContain("HTTP 500");
    expect(root.textContent ?? "").not.toContain(copy.errors.title);
  });

  it("grades a named process_down as idle so the band is the only statement (#52)", async () => {
    const report = vi.fn();
    vi.mocked(sendPrompt).mockRejectedValue(
      new WorkspaceError(503, "process_down", "sidecar restarted"),
    );
    const root = mount({ onRuntimeFault: report });
    type(root, "Bump the kerf to 0.25 mm.");
    pressEnter(root);
    await act(async () => undefined);

    expect(report).toHaveBeenCalledWith("process_down");
    expect(composer(root).getAttribute("data-send-state")).toBe("ok");
    expect(root.querySelector("[data-composer-refused]")).toBeNull();
    expect(root.textContent ?? "").not.toContain("sidecar restarted");
  });

  it("keeps §7A.5's manual retry working after a lost POST", async () => {
    // The other side of the guard: `data-send-state="unknown"` is not a
    // `disabledReason`, so the operator's own Send-again must still post. A
    // guard that refused every non-idle state would have taken this with it.
    vi.mocked(sendPrompt).mockRejectedValue(new Error("the POST did not come back"));
    const root = mount();
    type(root, "Bump the kerf to 0.25 mm.");
    pressEnter(root);
    await act(async () => undefined);

    expect(composer(root).getAttribute("data-send-state")).toBe("unknown");
    expect(composer(root).getAttribute("data-disabled-reason")).toBe("null");
    const retry = root.querySelector<HTMLButtonElement>("[data-composer-retry]");
    expect(retry).not.toBeNull();
    act(() => {
      retry?.click();
    });
    await act(async () => undefined);
    expect(vi.mocked(sendPrompt)).toHaveBeenCalledTimes(2);
  });

  it("creates a part session on first send when none is selected", async () => {
    vi.mocked(createSession).mockResolvedValue({
      status: "ok",
      session_id: "sess-new",
      profile: "part",
      part: "tread",
      resumed: false,
    });
    vi.mocked(sendPrompt).mockResolvedValue({
      status: "ok",
      session_id: "sess-new",
      run_id: "run-1",
      run_status: "completed",
      terminal: null,
      events: [],
      context: null,
    });
    workspaceStore.reset({ ...DEFAULT_STATE, part: "tread" });
    const root = mount({ sessionId: null });
    expect(input(root).disabled).toBe(false);
    type(root, "Ask about this plate.");
    pressEnter(root);
    await act(async () => undefined);
    expect(vi.mocked(createSession)).toHaveBeenCalledWith("part", "tread");
    expect(vi.mocked(sendPrompt)).toHaveBeenCalledWith(
      "sess-new",
      "Ask about this plate.",
      expect.anything(),
    );
    expect(workspaceStore.getSnapshot().session).toBe("sess-new");
    workspaceStore.reset(DEFAULT_STATE);
  });

  it("starts a turn from Send click, not only Enter (#44)", async () => {
    const settled: PromptDocument = {
      status: "ok",
      session_id: "sess-1",
      run_id: "run-1",
      run_status: "completed",
      terminal: null,
      events: [],
      context: null,
    };
    vi.mocked(sendPrompt).mockResolvedValue(settled);
    const forget = vi.fn();
    const root = mount({ onForgetLiveRun: forget });
    type(root, "Bump the kerf to 0.25 mm.");
    const send = root.querySelector<HTMLButtonElement>("[data-composer-send]");
    expect(send?.getAttribute("aria-disabled")).not.toBe("true");
    act(() => {
      send?.click();
    });
    expect(vi.mocked(sendPrompt)).toHaveBeenCalledTimes(1);
    expect(forget).toHaveBeenCalledTimes(1);
    await act(async () => undefined);
  });

  it("appends the local-prompt echo on Send, verbatim, before the POST settles (§7A.5 C1)", async () => {
    // The echo is minted from the textarea's own value on the same submit that
    // calls `sessionPromptStore.remember` — not from the response.
    let resolveTurn: (value: PromptDocument) => void = () => undefined;
    vi.mocked(sendPrompt).mockImplementation(
      () => new Promise<PromptDocument>((resolve) => (resolveTurn = resolve)),
    );
    const onEcho = vi.fn();
    const root = mount({ onEcho });
    type(root, "Chamfer the lid, 0.5 mm.");
    pressEnter(root);
    expect(onEcho).toHaveBeenCalledExactlyOnceWith("Chamfer the lid, 0.5 mm.");
    resolveTurn({
      status: "ok",
      session_id: "sess-1",
      run_id: "run-1",
      run_status: "completed",
      terminal: null,
      events: [],
      context: null,
    });
    await act(async () => undefined);
    // The response settles the turn; it does not mint a second echo.
    expect(onEcho).toHaveBeenCalledTimes(1);
  });

  it("leaves the echo standing beside data-send-state=unknown on a lost POST (C1/C2)", async () => {
    // The negative half: nothing retracts the echo — the words were sent into
    // uncertainty, and hiding them would un-say something the operator said.
    vi.mocked(sendPrompt).mockRejectedValue(new Error("the POST did not come back"));
    const onEcho = vi.fn();
    const root = mount({ onEcho });
    type(root, "Bump the kerf to 0.25 mm.");
    pressEnter(root);
    await act(async () => undefined);
    expect(composer(root).getAttribute("data-send-state")).toBe("unknown");
    expect(onEcho).toHaveBeenCalledTimes(1);
    // A second, deliberate Send appends a second echo.
    const retry = root.querySelector<HTMLButtonElement>("[data-composer-retry]");
    act(() => {
      retry?.click();
    });
    await act(async () => undefined);
    expect(onEcho).toHaveBeenCalledTimes(2);
  });

  it("summarises the envelope at rest and mounts NO chip row (§7A.3(a)(c))", () => {
    workspaceStore.reset({ ...DEFAULT_STATE, part: "kerf_card" });
    const root = mount();
    // The resting height is one line of context, whatever the envelope carries.
    expect(root.querySelector("[data-context-chips]")).toBeNull();
    const line = root.querySelector("[data-context-summary]");
    expect(line).not.toBeNull();
    expect(line?.textContent ?? "").toContain(copy.composer.contextSummary);
    expect(line?.textContent ?? "").toContain("kerf_card");
    expect((line?.getAttribute("data-context-keys") ?? "").split(" ")).toContain("part");
    // Disclose still hides the composed preview; nothing about the route moved.
    expect(root.querySelector("[data-context-preview]")).toBeNull();
    expect(root.querySelector("[data-context-block]")).toBeNull();
  });

  it("expands the editable chip form on the summary toggle, and collapses again", () => {
    workspaceStore.reset({ ...DEFAULT_STATE, part: "kerf_card" });
    const root = mount();
    const toggle = root.querySelector<HTMLButtonElement>("[data-context-disclose]");
    expect(toggle).not.toBeNull();
    act(() => {
      toggle?.click();
    });
    // The chips are COMPLETE when shown — `chipsFor` still enumerates every
    // member; what changed is when the list mounts.
    expect(root.querySelector("[data-context-chips]")).not.toBeNull();
    expect(
      root.querySelector('[data-context-key="part"]')?.getAttribute("data-context-value"),
    ).toBe("kerf_card");
    // §7A.3(d)'s testable, against the live DOM: the published key set is the
    // chips' key set.
    const published = (
      root.querySelector("[data-context-summary]")?.getAttribute("data-context-keys") ?? ""
    ).split(" ");
    const chipKeys = [...root.querySelectorAll("[data-context-chips] [data-context-key]")].map(
      (node) => node.getAttribute("data-context-key") ?? "",
    );
    expect([...published].sort()).toEqual([...chipKeys].sort());
    act(() => {
      root.querySelector<HTMLButtonElement>("[data-context-disclose]")?.click();
    });
    expect(root.querySelector("[data-context-chips]")).toBeNull();
  });

  it("draws an excluded member on the resting line (§7A.3(e))", () => {
    workspaceStore.reset({ ...DEFAULT_STATE, part: "kerf_card" });
    const root = mount();
    act(() => {
      root.querySelector<HTMLButtonElement>("[data-context-disclose]")?.click();
    });
    act(() => {
      root.querySelector<HTMLButtonElement>('[data-context-drop="part"]')?.click();
    });
    act(() => {
      root.querySelector<HTMLButtonElement>("[data-context-disclose]")?.click();
    });
    const line = root.querySelector("[data-context-summary]");
    expect(line?.querySelector('[data-context-removed="part"]')).not.toBeNull();
    expect(line?.textContent ?? "").toContain(copy.composer.contextKey.part);
    expect(line?.getAttribute("data-context-keys")).toBe("");
  });

  it("holds §7A.3(d)'s halves with a member dropped, superset and all", () => {
    // The amended (d). `data-context-keys` names exactly what the POST would
    // send; the chips are a SUPERSET by construction, because a chip is the
    // control a member is un-excluded from and one that vanished with its
    // member would take that control away. Halves (2), (3) and (4) here; half
    // (1) — published == envelope — is `summaryFor`'s own unit above.
    workspaceStore.reset({ ...DEFAULT_STATE, part: "kerf_card" });
    const root = mount();
    act(() => {
      root.querySelector<HTMLButtonElement>("[data-context-disclose]")?.click();
    });
    const keysNow = (): string[] =>
      (root.querySelector("[data-context-summary]")?.getAttribute("data-context-keys") ?? "")
        .split(" ")
        .filter((key) => key !== "");
    const chipKeys = (selector: string): string[] =>
      [...root.querySelectorAll(`[data-context-chips] ${selector}`)].map(
        (node) => node.getAttribute("data-context-key") ?? "",
      );

    // (4), nothing dropped and the envelope non-null: published == chips.
    expect(keysNow().sort()).toEqual(chipKeys("[data-context-key]").sort());
    expect(chipKeys("[data-context-key][data-context-dropped]")).toEqual([]);

    act(() => {
      root.querySelector<HTMLButtonElement>('[data-context-drop="view"]')?.click();
    });

    // (3): `view` leaves the published set and the envelope, and its chip stays
    // in the row wearing `data-context-dropped` — no fact left the DOM (§0.2b).
    expect(keysNow()).not.toContain("view");
    expect(chipKeys("[data-context-key][data-context-dropped]")).toEqual(["view"]);
    // (4) again, with the exclusion: published == chips minus the dropped ones.
    expect(keysNow().sort()).toEqual(
      chipKeys("[data-context-key]:not([data-context-dropped])").sort(),
    );
    // (2): the line never names a member the form does not offer, even now.
    for (const key of keysNow()) expect(chipKeys("[data-context-key]")).toContain(key);

    // Drop the only member that names a reference: the envelope goes away
    // entirely, so the published set is empty while the chips still OFFER the
    // three navigation members. Superset, not equality — this is the case the
    // struck three-way equality got wrong.
    act(() => {
      root.querySelector<HTMLButtonElement>('[data-context-drop="part"]')?.click();
    });
    expect(keysNow()).toEqual([]);
    expect(chipKeys("[data-context-key]")).toContain("stage_tab");
    // And both exclusions are visible on the resting line, not quiet (§7A.3(e)).
    act(() => {
      root.querySelector<HTMLButtonElement>("[data-context-disclose]")?.click();
    });
    const line = root.querySelector("[data-context-summary]");
    expect(line?.querySelector('[data-context-removed="part"]')).not.toBeNull();
    expect(line?.querySelector('[data-context-removed="view"]')).not.toBeNull();
  });

  it("surfaces Add current view on the resting line exactly while the gap is visible (C22)", () => {
    // §7A.3, amended 2026-09-02 (§0.2c, C22), against the live DOM: all three
    // negative halves and the positive, in the order an operator reaches them.
    workspaceStore.reset({
      ...DEFAULT_STATE,
      part: "kerf_card",
      selection: { selection_id: "12", kind: "face", bundle_ref: "artifact:selection-bundle:x" },
    });
    const root = mount();
    const lineAdd = (): HTMLButtonElement | null =>
      root.querySelector<HTMLButtonElement>("[data-context-summary] [data-context-add-view]");
    const keysNow = (): string[] =>
      (root.querySelector("[data-context-summary]")?.getAttribute("data-context-keys") ?? "")
        .split(" ")
        .filter((key) => key !== "");

    // SATISFIED: a live selection rides in the envelope with `view`, so there
    // is no gap and the line mounts no control.
    expect(keysNow()).toContain("selection");
    expect(lineAdd()).toBeNull();

    // Exclude both members through the form. While the disclosure is OPEN the
    // line still mounts nothing — the form's copy of the control is showing,
    // and two live copies of one affordance is the same control twice.
    act(() => {
      root.querySelector<HTMLButtonElement>("[data-context-disclose]")?.click();
    });
    act(() => {
      root.querySelector<HTMLButtonElement>('[data-context-drop="view"]')?.click();
    });
    act(() => {
      root.querySelector<HTMLButtonElement>('[data-context-drop="selection"]')?.click();
    });
    expect(lineAdd()).toBeNull();
    expect(root.querySelector("[data-context-preview] [data-context-add-view]")).not.toBeNull();

    // Close the disclosure: the gap is visible at rest and the affordance
    // surfaces on the resting line, quiet, at the line's end.
    act(() => {
      root.querySelector<HTMLButtonElement>("[data-context-disclose]")?.click();
    });
    const control = lineAdd();
    expect(control).not.toBeNull();
    expect(control?.getAttribute("data-variant")).toBe("quiet");
    expect(keysNow()).not.toContain("view");
    expect(keysNow()).not.toContain("selection");

    // ACTIVATE: exactly what the form's copy does — the members join the
    // `added` set and hence `data-context-keys` — and the affordance unmounts
    // from the line because the gap it closed is gone. The (d) equality is
    // untouched: the keys name exactly what would be sent, before and after.
    act(() => {
      control?.click();
    });
    expect(lineAdd()).toBeNull();
    expect(keysNow()).toContain("view");
    expect(keysNow()).toContain("selection");
  });

  it("says the blank canvas in one word, and mounts no chip row (#79)", () => {
    workspaceStore.reset(DEFAULT_STATE);
    const root = mount();
    expect(root.querySelector("[data-context-chips]")).toBeNull();
    // The long paragraph is not the resting rendering; one word is.
    expect(root.textContent ?? "").not.toContain(copy.composer.contextNone);
    const line = root.querySelector("[data-context-summary]");
    expect(line?.getAttribute("data-context-keys")).toBe("");
    expect(line?.textContent ?? "").toContain(copy.composer.contextEmpty);
    // The long form is not gone, it is on `title` (§7.4(d)'s rule).
    expect(line?.getAttribute("title")).toBe(copy.composer.contextNone);
  });

  it("focuses the composer input when the create nonce ticks (#61)", () => {
    const root = mount({ focusNonce: 1 });
    expect(document.activeElement).toBe(input(root));
  });

  it("does not offer Cancel against a finished run, and a no-op does not print Cancelled (#99)", async () => {
    vi.mocked(cancelRun).mockResolvedValue({
      status: "ok",
      run_id: "run-old",
      session_id: "sess-1",
      abandoned_questions: 0,
    });
    const root = mount({ liveRunId: null, streamLive: true });
    expect(composer(root).getAttribute("data-cancel-state")).toBe("unavailable");
    // §7A.10(b): the control is not there to click. The fact is still readable.
    expect(root.querySelector("[data-composer-cancel]")).toBeNull();
    expect(composer(root).getAttribute("title")).toBe(copy.composer.cancelIdle);
    await act(async () => undefined);
    expect(vi.mocked(cancelRun)).not.toHaveBeenCalled();
    expect(root.querySelector("[data-cancel-note]")).toBeNull();
  });

  it("keeps Cancel available through a live turn (#45)", () => {
    const root = mount({ liveRunId: "run-live", streamLive: true });
    expect(composer(root).getAttribute("data-cancel-state")).toBe("available");
    const cancelButton = root.querySelector<HTMLButtonElement>("[data-composer-cancel]");
    expect(cancelButton).not.toBeNull();
    expect(cancelButton?.getAttribute("aria-disabled")).not.toBe("true");
    // A cancellable run gets an ENABLED control, never a disabled one — the
    // amendment's whole point is that there is no third state to draw.
    expect(cancelButton?.hasAttribute("disabled")).toBe(false);
    // And the form no longer carries a reason it has no control for.
    expect(composer(root).hasAttribute("title")).toBe(false);
  });
});
