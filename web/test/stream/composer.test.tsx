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

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Composer, COMPOSER_STATES, DISABLED_REASONS } from "../../src/components/stream/Composer";
import { CONTEXT_MEMBERS, type ContextMember } from "../../src/api/sessions";
import type { ProvidersDocument } from "../../src/api/providers";
import type { DfmDocument } from "../../src/api/types";
import { refreshKeys } from "../../src/api/refresh";
import { keys } from "../../src/api/queries";
import {
  EFFORT_LEVELS,
  defaultModel,
  effortOptionsFor,
  modelKey,
  modelsFrom,
  showDfmChrome,
  showModelChrome,
} from "../../src/stream/composerChrome";
import { CHIP_ORDER, chipsFor, envelopeFor } from "../../src/stream/composerContext";
import { DEFAULT_STATE, type WorkspaceState } from "../../src/state/workspace";

const NOTHING: ReadonlySet<ContextMember> = new Set();

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
    expect(attribute(html, "data-composer-state")).toBe("disabled");
    expect(attribute(html, "data-disabled-reason")).toBe("no_session");
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

  it("renders cancel as unavailable-with-a-reason, never as a dead button", () => {
    // §7A.5's named limit. Between submit and the first event carrying the run
    // id, cancel is unavailable — the window is one model round-trip, and the
    // composer says so rather than offering a control that does nothing.
    const html = markup({ liveRunId: null });
    expect(attribute(html, "data-cancel-state")).toBe("unavailable");
    expect(html).toContain("data-composer-cancel");
  });

  it("puts no data-source on any context chip", () => {
    // §7A.10: "no chip carries a `data-source`, because no chip is a fact
    // (§4.6)". The chips render §4.5 navigation state, which is the same
    // exemption §1 grants the grid readout.
    const html = markup();
    const chipRow = /<ul[^>]*data-context-chips[^>]*>([\s\S]*?)<\/ul>/.exec(html);
    expect(chipRow).not.toBeNull();
    expect(chipRow?.[1] ?? "").not.toContain("data-source");
  });

  it("keeps the existing composer selectors when chrome is present", () => {
    const html = markup({}, { providers: providersDocument() });
    expect(html).toContain("data-composer=\"\"");
    expect(html).toContain("data-composer-input");
    expect(html).toContain("data-context-chips");
    expect(html).toContain("data-composer-send");
    expect(html).toContain("data-context-add-view");
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
    expect(modelKey(models[0]!)).toBe("heph-fake/heph-fake-model");
    expect(modelKey(models[0]!)).not.toMatch(/smith|arche|composer-1/i);
  });

  it("names no models when the configuration file does not exist", () => {
    expect(modelsFrom(providersDocument({ config_exists: false, providers: [] }))).toEqual([]);
    expect(showModelChrome(false, [])).toBe(false);
  });

  it("hides the model picker when the runtime is missing", () => {
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
    expect(html).toContain("data-context-add-view");
  });

  it("renders the declared model id on the picker when a runtime is attached", () => {
    const html = markup({}, { providers: providersDocument() });
    expect(attribute(html, "data-composer-model")).toBe("heph-fake-model");
    expect(attribute(html, "data-composer-provider")).toBe("heph-fake");
  });

  it("offers effort levels only when the selected model declared reasoning", () => {
    const plain = defaultModel(modelsFrom(providersDocument()));
    expect(effortOptionsFor(plain)).toEqual(["off"]);
    const reasoning = defaultModel(
      modelsFrom(
        providersDocument({
          providers: [
            {
              id: "heph-fake",
              kind: "openai_compatible",
              name: "Fake",
              models: [{ id: "reasoner", name: "reasoner", reasoning: true }],
              source: "project",
              health: "accepted",
              last_observed_at: null,
              available: true,
              unavailable_reason: null,
            },
          ],
        }),
      ),
    );
    expect(effortOptionsFor(reasoning)).toEqual(EFFORT_LEVELS);
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
    expect(html).toContain("data-composer-effort-absent");
    expect(attribute(html, "data-composer-effort")).toBe("off");
  });
});

describe("the DFM chip is the engine equivalent, not a per-message flag", () => {
  it("shows the two §6.4 controls only when a part's DFM document is in hand", () => {
    expect(showDfmChrome(false, "tread", true)).toBe("chip");
    expect(showDfmChrome(false, "tread", false)).toBe("hidden");
    expect(showDfmChrome(false, null, false)).toBe("absent");
    expect(showDfmChrome(true, "tread", true)).toBe("hidden");
  });

  it("names the absence when no part is selected and does not fake DFM chrome", () => {
    const html = markup();
    expect(html).toContain("data-composer-dfm-absent");
    expect(html).not.toContain("data-dfm-auto-run-toggle");
    expect(html).not.toContain("data-dfm-run");
  });

  it("hides DFM chrome on the agent_unavailable refusal", () => {
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
    expect(html).toContain("data-context-add-view");
  });
});
