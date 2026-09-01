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

import { readFileSync } from "node:fs";
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
  sendPrompt,
  type ContextMember,
  type PromptDocument,
} from "../../src/api/sessions";
import type * as SessionsModule from "../../src/api/sessions";
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
import { formatRef } from "../../src/system";

// The one route the last block counts calls on. Everything else in the module is
// the real thing — `CONTEXT_MEMBERS` is asserted against directly, and a
// wholesale stub would make that assertion about the stub.
vi.mock("../../src/api/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof SessionsModule>();
  return { ...actual, sendPrompt: vi.fn(), cancelRun: vi.fn() };
});

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
    // (§4.6)". Chips fold into disclose, so idle markup has no chip row;
    // the row template itself must still not mint a `data-source`.
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
  });

  it("keeps the existing composer selectors when chrome is present", () => {
    const html = markup({}, { providers: providersDocument() });
    expect(html).toContain("data-composer=\"\"");
    expect(html).toContain("data-composer-input");
    expect(html).toContain("data-composer-send");
    expect(html).toContain("data-context-disclose");
    expect(html).toMatch(/<textarea[^>]*rows="1"/);
    expect(html).not.toMatch(/<textarea[^>]*rows="3"/);
    expect(html).not.toContain("data-context-chips");
    expect(html).not.toContain("data-context-add-view");
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

  it("renders the declared model id as a projection, not a picker, when a runtime is attached", () => {
    const html = markup({}, { providers: providersDocument() });
    expect(attribute(html, "data-composer-model")).toBe("heph-fake-model");
    expect(attribute(html, "data-composer-provider")).toBe("heph-fake");
    // §7A.3's prompt body is `{text, context?}`. A Select here would write
    // nothing and read as hosted-chat chrome.
    expect(html).not.toMatch(/<select\b/i);
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
    // Effort is not a prompt field. The strip used to project a bare "off"
    // with no accessible name; that control is gone. The decision module
    // still records the closed vocabulary for a later route.
    expect(html).not.toContain("data-composer-effort");
    expect(html).not.toContain("data-composer-effort-absent");
  });
});

describe("the idle composer does not host DFM chrome", () => {
  it("still knows when the inspector may show the two §6.4 controls", () => {
    expect(showDfmChrome(false, "tread", true)).toBe("chip");
    expect(showDfmChrome(false, "tread", false)).toBe("hidden");
    expect(showDfmChrome(false, null, false)).toBe("absent");
    expect(showDfmChrome(true, "tread", true)).toBe("hidden");
  });

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
    expect(root.querySelector("[data-composer-send]")?.hasAttribute("disabled")).toBe(true);

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
    expect(cancelButton?.hasAttribute("disabled")).toBe(false);
    act(() => {
      cancelButton?.click();
    });
    await act(async () => undefined);
    expect(vi.mocked(cancelRun)).toHaveBeenCalledWith("run-live");

    // And none of that posted a prompt.
    expect(vi.mocked(sendPrompt)).toHaveBeenCalledTimes(1);
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
});
