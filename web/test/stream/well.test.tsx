// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The agent well is a conversation, not a status board (INTERFACE.md §7, §7A).
//
// Three complaints from a 1280×800 operator session, each with an assertion:
//
// 1. **The header lied.** A sidecar restart killed the run and the badge went on
//    reading `✓ live`. §7.4's vocabulary is closed and its five values are all
//    claims about the socket, so the fault is a separate addressable fact — and
//    the badge shows it, because it is the one that changes what to do next.
// 2. **The well was a wall of rows.** At ~420px the column spent a bordered
//    full-width row on "1 page of recorded transcript", an eyebrow on a session
//    list of one, and a third metadata word on that one tab. Height a
//    transcript did not get.
// 3. **An empty well read as an error.** With no session selected the header
//    still rendered an `historical` pill, which is a state the operator has to
//    resolve rather than an invitation to start.
//
// `StreamPanel` mounts a query client, a socket and the workspace store, so the
// panel-level assertions here are on its source and its stylesheet in
// `operator-chrome.test.tsx`'s idiom; `SessionTabs` is a pure component and is
// rendered.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { SessionCreateAction, SessionTabs } from "../../src/components/stream/SessionTabs";
import { StreamHeader } from "../../src/components/stream/StreamHeader";
import { copy } from "../../src/copy";
import { sessionPromptStore } from "../../src/stream/sessionPrompts";
import { applySessionDocumentTitle } from "../../src/stream/sessionTitle";
import { RUNTIME_FAULTS, type RuntimeFault } from "../../src/stream/runtimeFault";
import {
  EXCEPTIONAL_STREAM_STATES,
  showsHistoryBar,
  showsStreamBadge,
} from "../../src/stream/streamChrome";
import type { HistoryProgress } from "../../src/stream/history";
import type { StreamState } from "../../src/stream/transcript";
import type { ProfileCapability, SessionRow } from "../../src/api/sessions";
import type { ThreadTab } from "../../src/stream/thread";

const webSrc = join(dirname(fileURLToPath(import.meta.url)), "../../src");

function source(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8");
}

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

function parse(markup: string): Document {
  return new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
}

function tab(patch: Partial<ThreadTab> = {}): ThreadTab {
  return {
    session_id: "sess-kerf",
    parent_session_id: null,
    kind: null,
    depth: 0,
    thread_state: "linked",
    origin: {},
    ...patch,
  };
}

function row(patch: Partial<SessionRow> = {}): SessionRow {
  return {
    session_id: "sess-kerf",
    profile: "part",
    part: "kerf_card",
    parent_session_id: null,
    thread_state: "linked",
    ...patch,
  };
}

function tabsMarkup(tabs: readonly ThreadTab[], sessions: readonly SessionRow[]): Document {
  return parse(
    renderToStaticMarkup(
      <SessionTabs
        tabs={tabs}
        sessions={sessions}
        selected={tabs[0]?.session_id ?? null}
        onSelect={() => undefined}
        bounded={false}
      />,
    ),
  );
}

describe("a runtime fault is named, and does not masquerade as a stream state", () => {
  const panel = source("components/stream/StreamPanel.tsx");

  it("keeps §7.4's closed vocabulary out of the fault's way", () => {
    // No sixth stream state. `data-stream-state` still carries the socket's own
    // answer wherever the badge is drawn (§7.4(b)) — and since the badge is now
    // exception-only, the panel root carries the same answer in EVERY state,
    // which is what the e2e reads by name (`stream.spec.ts` G4.8).
    const states = source("stream/transcript.ts");
    expect(states).toMatch(
      /STREAM_STATES = \[\s*"live",\s*"reconnecting",\s*"resyncing",\s*"historical",\s*"detached",\s*\]/,
    );
    expect(source("components/stream/StreamHeader.tsx")).toContain("data-stream-state={status}");
    expect(panel).toContain("data-stream={stream.status}");
    expect(panel).not.toContain('data-stream-state="runtime');
  });

  it("gives the fault its own attribute, on exactly one node", () => {
    const occurrences = panel.match(/data-runtime-fault=/g) ?? [];
    expect(occurrences).toHaveLength(1);
  });

  it("shows the fault on the badge instead of the socket state", () => {
    // The badge is what the operator reads; `live` beside a dead run is the
    // one true thing that does not matter. The row moved to `StreamHeader`
    // (§7.4(a)), and the fault is still what it draws.
    const header = source("components/stream/StreamHeader.tsx");
    expect(header).toMatch(/status=\{fault !== null \? "error"/);
    expect(header).toMatch(/fault !== null \? copy\.stream\.runtimeFault\[fault\]/);
  });

  it("has one sentence per fault grade, and no grade without one", () => {
    for (const grade of RUNTIME_FAULTS) {
      expect(copy.stream.runtimeFault[grade], grade).toBeTruthy();
      expect(copy.stream.runtimeFaultWhy[grade], grade).toBeTruthy();
    }
    expect(Object.keys(copy.stream.runtimeFaultWhy).sort()).toEqual([...RUNTIME_FAULTS].sort());
  });

  it("offers New session on the fault band, never Send again (#43)", () => {
    // Recovery is POST /sessions `{profile: "orchestrator"}`. No reconnect
    // wizard — no route backs one. The band is the only place a runtime fault
    // is stated; the next-step sentence must not point at Send.
    const band = panel.slice(
      panel.indexOf("data-runtime-fault={fault}"),
      panel.indexOf("sessions.error !== null && sessionsFault === null"),
    );
    expect(band).toContain("{createAction}");
    expect(band).not.toMatch(/<Button[^>]*>[\s\S]*[Rr]econnect/);
    expect(copy.stream.runtimeFaultNext).toMatch(/[Nn]ew session/);
    expect(copy.stream.runtimeFaultNext).not.toMatch(/Send again/);
    expect(copy.stream.runtimeFaultNext).not.toMatch(/composer below/);
    expect(copy.composer.retry).toBe("Send again");
  });

  it("renders the create pair when the current tab cannot prompt (#43)", () => {
    // §7A.2's pair is not only the empty-list invitation. A selected dead
    // session keeps the tabs; the pair must still be reachable.
    expect(panel).toContain("sessionCannotPrompt");
    expect(panel).toContain("cannotPrompt");
    expect(panel).toContain("data-session-cannot-prompt");
  });

  it("refreshes workspace reads when the process is gone, without touching the pin (#59)", () => {
    const refresh = panel.slice(
      panel.indexOf("Sidecar death produces neither"),
      panel.indexOf("§7A.2: `POST /sessions`"),
    );
    expect(refresh).toContain("processGone(fault)");
    expect(refresh).toContain("refreshAfterTurn(client, part)");
    expect(refresh).not.toContain("workspaceStore");
    expect(refresh).not.toMatch(/observeCurrent\(/);
    expect(refresh).not.toMatch(/followCurrent\(/);
    expect(refresh).not.toMatch(/hold\(/);
  });

  it("states a shared cause once", () => {
    // §4.7's second EmptyState rule: the generic refusal is suppressed when the
    // band is already showing the same failure.
    expect(panel).toContain("sessionsFault === null");
  });
});

describe("the well spends its height on the transcript", () => {
  const panel = source("components/stream/StreamPanel.tsx");
  const stream = css("components/stream/Stream.module.css");

  it("keeps §8's page count on the panel root, where the gates read it", () => {
    // §8(c): `data-history-state` and `data-history-pages` are unconditionally
    // mounted on the panel root, so dropping the drawn row drops no fact. They
    // are minted once each — a second copy on the row would give a gate two
    // answers, and the row is now the half that can be absent.
    expect(panel).toContain("data-history-state={stream.history.state}");
    expect(panel).toContain("data-history-pages={stream.history.pages}");
    expect(panel.match(/data-history-state=/g) ?? []).toHaveLength(1);
    expect(panel.match(/data-history-pages=/g) ?? []).toHaveLength(1);
    expect(source("components/stream/StreamHeader.tsx")).not.toContain("data-history-state=");
    expect(stream).not.toMatch(/\.historyBar\s*\{[^}]*border-bottom/);
    expect(stream).toMatch(/\.historyBar\s*\{[^}]*flex:\s*1 1 auto/);
  });

  it("renders no header row at all with no session selected", () => {
    // An `historical` pill over an empty well is a state to resolve, and an
    // empty bordered strip is furniture; the empty well's content is an action.
    expect(panel).toMatch(/\{selected === null \? null : \(\s*<StreamHeader/);
  });

  it("still keeps the composer as the panel's last child", () => {
    expect(panel.lastIndexOf("<Composer")).toBeGreaterThan(panel.lastIndexOf("data-stream-main"));
  });

  it("bottom-anchors the empty invitation so the void sits above it (#56)", () => {
    expect(stream).toMatch(/\[data-stream-empty\]\s*\.main\s*\{[^}]*justify-content:\s*flex-end/);
    expect(panel).toContain('data-stream-empty');
  });

  it("keeps a create reachable after the first session exists (#70, §7.1(b))", () => {
    // §7A.2's create stays reachable after the first session — but beside a
    // drawn tab strip it is the strip's `+`, not a second worded band. The
    // worded pair survives on the two surfaces §7.1(b)(1) leaves it on: the
    // empty-list invitation and the runtime-fault band.
    expect(panel).toContain("const createAction");
    expect(panel).toContain("action={createAction}");
    expect(panel).toContain("const stripCreate");
    expect(panel).toMatch(/fault === null && \(cannotPrompt \|\| rows\.length > 0\)/);
    expect(panel).toContain("create={stripCreate}");
    const tabsRegion = panel.slice(panel.indexOf("<SessionTabs"), panel.indexOf("<StreamHeader"));
    expect(tabsRegion).not.toContain("{createAction}");
  });

  it("focuses the composer after New session (#61)", () => {
    expect(panel).toContain("setFocusNonce");
    expect(panel).toContain("focusNonce={focusNonce}");
  });

  it("scrolls only the transcript, and follows newest until the operator leaves (#98)", () => {
    expect(stream).toMatch(/\.main\s*\{[^}]*overflow:\s*hidden/);
    expect(stream).toMatch(/\.scroll\s*\{[^}]*overflow:\s*auto/);
    expect(panel).toContain("useFollowScroll");
    expect(panel).toContain("data-transcript-scroll");
    expect(panel).toContain("data-jump-latest");
    expect(source("components/stream/StreamHeader.tsx")).toContain("copy.stream.historyFailed");
  });

  it("anchors the Latest pill in the scroll gutter, off the cards (§7.4 C20)", () => {
    // The scroller reserves a trailing strip by padding, and the pill anchors
    // inside it, written vertically so a word fits a gutter. The pairwise
    // non-intersection half is the e2e (`stream.spec.ts`); this is the
    // mechanism that makes it hold at every scroll position.
    expect(stream).toMatch(/\.scroll\s*\{[^}]*padding-right:\s*var\(--space-5\)/);
    const pill = stream.slice(stream.indexOf(".scrollHost .jumpLatest"));
    expect(pill).toMatch(/position:\s*absolute/);
    expect(pill).toMatch(/writing-mode:\s*vertical-rl/);
    expect(pill).toMatch(/right:\s*var\(--space-0\)/);
    // Mount condition unchanged: only while the view is not following.
    expect(panel).toMatch(/\{following \? null : \(/);
  });

  it("states a failed read in one string, and keeps no second spelling of it", () => {
    // §7A.10(e)(2), amended 2026-09-01: `historyFailedShort` was `historyFailed`
    // byte for byte and its only reader was the assertion that the panel did
    // not render it. "A copy key that only a test reads is a string the product
    // does not have", so the key is gone and the assertion is on the string the
    // product does draw.
    expect(Object.keys(copy.stream)).not.toContain("historyFailedShort");
    expect(copy.stream.historyFailed).toBe("The recorded transcript could not be read.");
    const header = source("components/stream/StreamHeader.tsx");
    expect(header).not.toContain("historyFailedShort");
    expect(panel).not.toContain("historyFailedShort");
  });
});

describe("§7A.10(e)(2) — copy keys with no importer are gone", () => {
  it("removes the select-a-session pair, which nothing drew", () => {
    // The panel with no session selected renders §7A.2's create invitation —
    // "There is no session yet" and the two actions — not an instruction to
    // pick one from a strip that may be empty. Neither key had an importer.
    expect(Object.keys(copy.stream)).not.toContain("selectSessionTitle");
    expect(Object.keys(copy.stream)).not.toContain("selectSession");
    expect(source("components/stream/StreamPanel.tsx")).not.toMatch(/selectSession/);
  });

  it("keeps `sessionsHeading`, which §7.1(a) still needs as an accessible name", () => {
    // The removal rule is "no importer", not "not drawn". This one is drawn
    // nowhere and imported by the tab list's `aria-label`, and deleting it
    // would take §3.13's accessible name with it.
    expect(copy.stream.sessionsHeading).toBe("Sessions");
    expect(source("components/stream/SessionTabs.tsx")).toContain("sessionsHeading");
  });
});

describe("well leftover copy (#66, #74, #75)", () => {
  it("uses human words for explode, roots, disclose, and a failed history read", () => {
    expect(copy.composer.contextKey.explode_t).toBe("explode");
    expect(copy.composer.contextKey.explode_t).not.toMatch(/explode t/i);
    expect(copy.stream.projectSession).toBe("project session");
    // AMENDED 2026-09-01 (§7A.10(c)): one word each. The control is a compact
    // quiet toggle attached to a line that already starts `Context:`, so
    // "Composer preview" spent three words saying where it was. It is still a
    // human word, which is what this test is about, and it is still not
    // "What will the agent be told?".
    expect(copy.composer.disclose).toBe("Preview");
    expect(copy.composer.discloseHide).toBe("Hide");
    expect(copy.stream.historyFailed).toMatch(/could not be read/);
    expect(copy.composer.runInFlightHolder("Ask about kerf_card")).toContain("Ask about kerf_card");
    expect(copy.composer.runInFlightHolder("Ask about kerf_card")).not.toMatch(/session sess-/);
  });
});

describe("the session tab row is a name, not three metadata strings", () => {
  it("reuses TabBar for the session tablist", () => {
    expect(source("components/stream/SessionTabs.tsx")).toContain("<TabBar");
    expect(source("components/stream/SessionTabs.tsx")).toContain('attr="data-session-tab"');
    expect(source("components/stream/SessionTabs.tsx")).toContain('layout="stack"');
  });

  it("draws no heading in any state, and keeps it as the list's name (§7.1(a))", () => {
    // Both halves of the clause. The heading used to appear once there was a
    // choice to make; the amendment strikes it outright, because the list's
    // `aria-label` is the same string and a visible copy of an accessible name
    // is the duplicate §0.2b measured — not the name itself.
    const one = tabsMarkup([tab()], [row()]);
    const many = tabsMarkup(
      [tab(), tab({ session_id: "sess-child", parent_session_id: "sess-kerf", depth: 1 })],
      [row(), row({ session_id: "sess-child", part: "riser" })],
    );
    for (const document_ of [one, many]) {
      expect(document_.querySelector("h1,h2,h3,h4,h5,h6")).toBeNull();
      expect(document_.body.textContent ?? "").not.toContain(copy.stream.sessionsHeading);
      // §3.13's floor is unchanged: the name is still on the list.
      const list = document_.querySelector("[role='tablist']");
      expect(list?.getAttribute("aria-label")).toBe(copy.stream.sessionsHeading);
    }
  });

  it("does not restate the indent as a word", () => {
    const linked = tabsMarkup([tab()], [row()]);
    const button = linked.querySelector("[data-session-tab]");
    expect(button?.getAttribute("data-thread-state")).toBe("linked");
    expect(button?.textContent ?? "").not.toContain(copy.stream.threadState.linked);
    expect(button?.textContent ?? "").toContain("kerf_card");
    // Issue 112: one kind word. Label carries `kerf_card · part`; meta is empty.
    expect(button?.textContent ?? "").toBe(`kerf_card · ${copy.stream.profile.part}`);
    expect(button?.textContent ?? "").not.toMatch(/part part/);
  });

  it("does not call a root 'no parent' — a root is not a missing parent", () => {
    const root = tabsMarkup(
      [tab({ thread_state: "unlinked", parent_session_id: null, depth: 0 })],
      [row({ thread_state: "unlinked", profile: "orchestrator", part: null })],
    );
    const button = root.querySelector("[data-session-tab]");
    expect(button?.getAttribute("data-thread-state")).toBe("unlinked");
    expect(button?.textContent ?? "").not.toMatch(/no parent/i);
    expect(button?.textContent ?? "").toContain(copy.stream.projectSession);
    // §7.1 C6: the fallback title is the profile word, never the create
    // affordance's wording.
    expect(button?.textContent ?? "").toContain(copy.stream.profile.orchestrator);
    expect(button?.textContent ?? "").not.toContain(copy.composer.createOrchestrator);
    expect(button?.getAttribute("title") ?? "").toContain("cannot be recovered");
    expect(button?.getAttribute("data-session-id")).toBe("sess-kerf");
  });
});

describe("the composer is usable, and says how it is used", () => {
  const composer = source("components/stream/Composer.tsx");

  it("binds the keyboard to Send through the pure decision", () => {
    expect(composer).toContain("isSendKey");
    expect(composer).toContain("onKeyDown={onPromptKey}");
  });

  it("keeps Send a first-class control and not an overflow item", () => {
    expect(composer).toContain('data-composer-send=""');
    expect(composer).toContain("onClick={submit}");
    expect(composer).toContain("canSendTurn");
    expect(composer).not.toMatch(/overflow|Popover/);
  });

  // AMENDED 2026-09-01 (§7A.6, §7A.10(b)): Cancel MOUNTS rather than dims. The
  // old reading — "rendered whether or not it is available" — was the shipped
  // behaviour the amendment names as the defect: a disabled button standing in
  // the action row for nearly all of the time. The fact stays: the state
  // attribute is unconditional and its reason moved to the form's `title`.
  it("mounts Cancel iff the state is available, and keeps the attribute (§7A.6)", () => {
    expect(composer).toContain('data-composer-cancel=""');
    expect(composer).toMatch(/\{cancellable \? \(/);
    expect(composer).toContain('data-cancel-state={cancellable ? "available" : "unavailable"}');
    expect(composer).toMatch(/cancelWhy !== null \? \{ title: cancelWhy \}/);
    expect(composer).not.toMatch(/data-composer-cancel[\s\S]{0,120}disabled: true as const/);
  });

  it("makes a run_in_flight refusal cancellable and typable, so it has an exit", () => {
    expect(composer).toContain("cancelAvailability");
    expect(composer).toContain("isComposable(disabledReason)");
    // And it expires on the frame that says the run ended.
    expect(composer).toMatch(/seenTerminals\.current = count/);
  });

  it("keeps the idle composer one row, and the hint out of it", () => {
    expect(composer).toMatch(/promptRows = promptFocused \|\| text\.trim\(\) !== "" \? 3 : 1/);
    // AMENDED 2026-09-02 (§0.2c, C15): the meta line that used to carry the
    // hint is struck outright — the keyboard binding lives on Send's `title`
    // and no `data-composer-hint` row mounts in any state.
    expect(composer).not.toContain("data-composer-hint");
    expect(composer).toMatch(/title=\{sendHint\}/);
  });
});

describe("a first prompt is the visible session name, not the UUID (#51)", () => {
  let host: HTMLDivElement | null = null;
  let unmount: (() => void) | null = null;

  afterEach(() => {
    if (unmount !== null) act(unmount);
    host?.remove();
    host = null;
    unmount = null;
    sessionPromptStore.reset();
    applySessionDocumentTitle(null);
  });

  it("does not render the UUID as the accessible or visible name, nor as document.title", () => {
    const sessionId = "ecec51cc-c398-4811-b0d9-35ad6d77bf18";
    const prompt = "Create a new laser-cut part named kerf_coupon with slots for kerf.";
    sessionPromptStore.remember(sessionId, `${prompt}\nAnd rebuild.`);
    host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(
        <SessionTabs
          tabs={[tab({ session_id: sessionId, thread_state: "unlinked" })]}
          sessions={[row({ session_id: sessionId, profile: "orchestrator", part: null })]}
          selected={sessionId}
          onSelect={() => undefined}
          bounded={false}
        />,
      );
    });
    unmount = () => {
      root.unmount();
    };
    const button = host.querySelector<HTMLButtonElement>("[data-session-tab]");
    expect(button).not.toBeNull();
    expect(button?.textContent ?? "").toContain("kerf_coupon");
    expect(button?.textContent ?? "").not.toContain(sessionId);
    expect(button?.getAttribute("aria-label") ?? "").toContain("kerf_coupon");
    expect(button?.getAttribute("aria-label") ?? "").not.toContain(sessionId);
    expect(button?.getAttribute("title") ?? "").toContain(sessionId);
    expect(button?.getAttribute("data-session-id")).toBe(sessionId);
    expect(document.title).not.toBe(sessionId);
    expect(document.title).not.toContain(sessionId);
    expect(document.title).toContain("kerf_coupon");
  });
});

describe("session tabs reuse TabBar keyboard (#62)", () => {
  let host: HTMLDivElement | null = null;
  let unmount: (() => void) | null = null;

  afterEach(() => {
    if (unmount !== null) act(unmount);
    host?.remove();
    host = null;
    unmount = null;
  });

  it("moves with arrows and Home/End; Tab leaves the list", () => {
    const tabs = [
      tab(),
      tab({ session_id: "sess-child", parent_session_id: "sess-kerf", depth: 1, thread_state: "linked" }),
      tab({ session_id: "sess-other", parent_session_id: null, depth: 0, thread_state: "unlinked" }),
    ];
    const sessions = [
      row(),
      row({ session_id: "sess-child", part: "riser" }),
      row({ session_id: "sess-other", profile: "orchestrator", part: null }),
    ];
    const seen: string[] = [];
    host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(
        <SessionTabs
          tabs={tabs}
          sessions={sessions}
          selected="sess-kerf"
          onSelect={(id) => {
            seen.push(id);
          }}
          bounded={false}
        />,
      );
    });
    unmount = () => {
      root.unmount();
    };
    const list = host.querySelector("[role='tablist']");
    expect(list).not.toBeNull();
    const buttons = [...host.querySelectorAll<HTMLButtonElement>("[data-session-tab]")];
    expect(buttons.map((node) => node.tabIndex)).toEqual([0, -1, -1]);
    act(() => {
      list?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    act(() => {
      list?.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
    });
    act(() => {
      list?.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    });
    expect(seen).toEqual(["sess-child", "sess-other", "sess-kerf"]);
    expect(host.querySelector("ul[role='tablist']")).toBeNull();
  });
});

// --------------------------------------------------------------------------
// §7.4(a) and §8(a), amended 2026-09-01 — the header row is an exception
//
// Both clauses have an explicit negative half, so every assertion below comes
// in a pair: the state that must draw the element, and the state that must not
// mount it at all. `StreamHeader` is a pure function of its props, so the pair
// is read from the DOM rather than from the panel's source text.

function header(props: {
  status?: StreamState;
  fault?: RuntimeFault | null;
  history?: HistoryProgress | null;
  resyncs?: number;
}): Document {
  return parse(
    renderToStaticMarkup(
      <StreamHeader
        status={props.status ?? "live"}
        fault={props.fault ?? null}
        history={props.history === undefined ? history({}) : props.history}
        resyncs={props.resyncs ?? 0}
      />,
    ),
  );
}

function history(patch: Partial<HistoryProgress>): HistoryProgress {
  return { items: [], userPrompts: [], pages: 1, state: "complete", error: null, ...patch };
}

describe("the stream-state badge mounts only for an exceptional state (§7.4(a))", () => {
  it("mounts nothing in the steady live state", () => {
    const steady = header({ status: "live" });
    expect(steady.querySelector("[data-stream-state]")).toBeNull();
    // Not a muted one, not a dot: the row itself is gone when it holds nothing.
    expect(steady.body.textContent).toBe("");
    expect(steady.body.firstElementChild).toBeNull();
  });

  it("mounts exactly one badge for each of the four exceptional states", () => {
    for (const status of EXCEPTIONAL_STREAM_STATES) {
      const drawn = header({ status });
      const badges = drawn.querySelectorAll("[data-stream-state]");
      expect(badges, status).toHaveLength(1);
      expect(badges[0]?.getAttribute("data-stream-state"), status).toBe(status);
      expect(drawn.body.textContent ?? "", status).toContain(copy.stream.state[status]);
    }
  });

  it("mounts one badge for a runtime fault under a live socket, and draws the fault", () => {
    // The socket says `live` and is telling the truth; the sidecar is gone. The
    // fault outranks the word, and the socket's own answer stays on the panel
    // root's `data-stream` (asserted on the panel above).
    for (const grade of RUNTIME_FAULTS) {
      const drawn = header({ status: "live", fault: grade });
      const badge = drawn.querySelector("[data-stream-state]");
      expect(badge?.getAttribute("data-stream-state"), grade).toBe("live");
      expect(badge?.textContent ?? "", grade).toBe(copy.stream.runtimeFault[grade]);
      expect(badge?.getAttribute("title") ?? "", grade).toBe(copy.stream.runtimeFaultWhy[grade]);
    }
  });

  it("decides the same thing in the predicate the row is drawn from", () => {
    expect(showsStreamBadge("live", null)).toBe(false);
    expect(showsStreamBadge("live", "unreachable")).toBe(true);
    for (const status of EXCEPTIONAL_STREAM_STATES) {
      expect(showsStreamBadge(status, null), status).toBe(true);
    }
  });
});

describe("the page counter mounts only when it is an exception (§8(a))", () => {
  it("mounts nothing for a one-page, a no-page, or a loading history", () => {
    for (const progress of [
      history({ pages: 1, state: "complete" }),
      history({ pages: 0, state: "complete" }),
      history({ pages: 0, state: "loading" }),
      history({ pages: 3, state: "loading" }),
      // A multi-page history whose latest page is the one on screen: this
      // client walks the cursor to `done` and renders every page it fetched.
      history({ pages: 4, state: "complete" }),
    ]) {
      const drawn = header({ history: progress, status: "live" });
      expect(drawn.querySelector("[data-history-bar]"), progress.state).toBeNull();
      expect(drawn.body.textContent ?? "", progress.state).not.toContain(
        copy.stream.historyPages(progress.pages),
      );
    }
  });

  it("mounts and stays loud when the read failed", () => {
    const failed = header({ history: history({ pages: 0, state: "failed" }), status: "live" });
    expect(failed.querySelector("[data-history-bar]")).not.toBeNull();
    expect(failed.body.textContent ?? "").toContain(copy.stream.historyFailed);
    // No count beside a stated failure: "0 pages" claims a number the load
    // never reached. The panel root's attribute still carries what it has.
    expect(failed.body.textContent ?? "").not.toContain(copy.stream.historyPages(0));
  });

  it("mounts when a bounded walk left recorded transcript above the prefix", () => {
    const bounded = header({ history: history({ pages: 7, state: "truncated" }), status: "live" });
    expect(bounded.querySelector("[data-history-bar]")).not.toBeNull();
    expect(bounded.body.textContent ?? "").toContain(copy.stream.historyPages(7));
  });

  it("decides the same thing in the predicate the row is drawn from", () => {
    expect(showsHistoryBar(history({ pages: 1, state: "complete" }))).toBe(false);
    expect(showsHistoryBar(history({ pages: 9, state: "complete" }))).toBe(false);
    expect(showsHistoryBar(history({ pages: 0, state: "loading" }))).toBe(false);
    expect(showsHistoryBar(history({ pages: 9, state: "loading" }))).toBe(false);
    expect(showsHistoryBar(history({ pages: 1, state: "truncated" }))).toBe(false);
    expect(showsHistoryBar(history({ pages: 2, state: "truncated" }))).toBe(true);
    expect(showsHistoryBar(history({ pages: 0, state: "failed" }))).toBe(true);
  });

  it("keeps §7.4(c)'s resync readout, which is an exception by construction", () => {
    const resynced = header({ status: "live", resyncs: 2 });
    expect(resynced.querySelector("[data-resync-count]")?.getAttribute("data-resync-count")).toBe(
      "2",
    );
    expect(header({ status: "live", resyncs: 0 }).querySelector("[data-resync-count]")).toBeNull();
  });

  it("draws no counter at all when there is no history to count", () => {
    // `agent_unavailable`: the panel has no session read to report on, and a
    // count of a load that never started would be a fact the panel does not have.
    expect(header({ history: null, status: "live" }).body.firstElementChild).toBeNull();
  });
});

describe("the create affordance is one `+` in the strip (§7.1(b))", () => {
  const profiles: readonly ProfileCapability[] = [
    { profile: "orchestrator", can_delegate: true, part_scoped: false, requires_part: false },
    { profile: "part", can_delegate: false, part_scoped: true, requires_part: true },
  ];

  function strip(part: string | null): Document {
    return parse(
      renderToStaticMarkup(
        <SessionCreateAction
          profiles={profiles}
          part={part}
          pending={false}
          onCreate={() => undefined}
        />,
      ),
    );
  }

  it("prints neither wording as a visible label while the strip is drawn", () => {
    for (const part of [null, "kerf_card"]) {
      const drawn = strip(part);
      const text = drawn.body.textContent ?? "";
      expect(text, String(part)).not.toContain(copy.composer.createOrchestrator);
      expect(text, String(part)).not.toContain(copy.composer.createPart("kerf_card"));
      // Icon-only: the label is the accessible name, not a word in the strip.
      const button = drawn.querySelector("button");
      expect(button?.getAttribute("aria-label") ?? "", String(part)).not.toBe("");
    }
  });

  it("is a quiet button with a worded accessible name, never a bare `+` (§3.9 C29)", () => {
    // Both halves: the control matches the quiet-button recipe (control
    // surface, `--border-control`, focus ring come with `data-variant`), and
    // its accessible name is a non-empty phrase that is not the literal glyph.
    for (const part of [null, "kerf_card"]) {
      const drawn = strip(part);
      const button = drawn.querySelector("button");
      expect(button?.getAttribute("data-variant"), String(part)).toBe("quiet");
      const name = button?.getAttribute("aria-label") ?? "";
      expect(name, String(part)).not.toBe("");
      expect(name, String(part)).not.toBe("+");
      // No unbordered accent glyph: the `+` is an Icon inside a Button, not a
      // text node.
      expect(button?.textContent ?? "", String(part)).not.toContain("+");
    }
  });

  it("activates the one create directly when no part is selected", () => {
    // A menu with one entry is a click that reports nothing. The `+` IS the
    // action, and it keeps the hook that addresses it.
    const drawn = strip(null);
    expect(drawn.querySelectorAll("button")).toHaveLength(1);
    const button = drawn.querySelector("[data-session-create]");
    expect(button?.getAttribute("data-create-profile")).toBe("orchestrator");
    expect(drawn.querySelector("[data-session-ask]")).toBeNull();
    expect(drawn.querySelector("[data-session-create-open]")).toBeNull();
  });

  it("draws the menu only while open, with both hooks inside it", () => {
    const closed = strip("kerf_card");
    expect(closed.querySelectorAll("button")).toHaveLength(1);
    expect(closed.querySelector("[data-session-create-menu]")?.getAttribute("aria-expanded")).toBe(
      "false",
    );
    expect(closed.querySelector("[data-session-create-open]")).toBeNull();
    expect(closed.querySelector("[data-session-create]")).toBeNull();
    expect(closed.querySelector("[data-session-ask]")).toBeNull();

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(
        <SessionCreateAction
          profiles={profiles}
          part="kerf_card"
          pending={false}
          onCreate={() => undefined}
        />,
      );
    });
    act(() => {
      host.querySelector<HTMLButtonElement>("[data-session-create-menu]")?.click();
    });
    const menu = host.querySelector("[data-session-create-open]");
    expect(menu).not.toBeNull();
    expect(menu?.querySelector("[data-session-create]")?.getAttribute("data-create-profile")).toBe(
      "orchestrator",
    );
    expect(menu?.querySelector("[data-session-ask]")?.getAttribute("data-create-profile")).toBe(
      "part",
    );
    expect(menu?.textContent ?? "").toContain(copy.composer.createOrchestrator);
    expect(menu?.textContent ?? "").toContain(copy.composer.createPart("kerf_card"));
    act(() => {
      root.unmount();
    });
    host.remove();
  });

  it("sits inside the tab strip, and only when the panel passes one", () => {
    const without = tabsMarkup([tab()], [row()]);
    expect(without.querySelector("[data-session-create], [data-session-create-menu]")).toBeNull();
    const withCreate = parse(
      renderToStaticMarkup(
        <SessionTabs
          tabs={[tab()]}
          sessions={[row()]}
          selected="sess-kerf"
          onSelect={() => undefined}
          bounded={false}
          create={
            <SessionCreateAction
              profiles={profiles}
              part={null}
              pending={false}
              onCreate={() => undefined}
            />
          }
        />,
      ),
    );
    const create = withCreate.querySelector("[data-session-create]");
    expect(create).not.toBeNull();
    // Outside the tablist: a create is not a session, and the roving tabindex
    // must not walk onto it.
    expect(create?.closest("[role='tablist']")).toBeNull();
    const tabsBand = withCreate.body.firstElementChild;
    expect(create?.closest("div")?.parentElement).toBe(tabsBand);
  });
});

describe("§4.1(h) C25 — the eyebrow band is struck; the chevron joins the strip", () => {
  const shell = source("components/Shell.tsx");
  const panel = source("components/stream/StreamPanel.tsx");

  it("renders no streamHeader band and no collapse control in the shell", () => {
    // The negative half: no element above the transcript matches the former
    // `streamHeader`, in source or stylesheet, and the shell no longer mounts
    // the chevron — the strip does.
    expect(shell).not.toContain("streamHeader");
    expect(shell).not.toContain("data-stream-collapse");
    expect(shell).not.toContain("streamTitle");
    expect(shell).toContain('aria-label={copy.stream.title}');
    expect(css("components/Shell.module.css")).not.toContain(".streamHeader");
    expect(css("components/Shell.module.css")).not.toContain(".streamTitle");
  });

  it("mounts the chevron from the panel, as the strip's trailing item", () => {
    // The hook, the recipe and the accessible name survive the move verbatim.
    expect(panel).toContain('data-stream-collapse=""');
    expect(panel).toContain("iconLabel={copy.stream.collapse}");
    expect(panel).toContain('icon="chevron-right"');
    expect(panel).toContain("collapse={collapseControl}");
    expect(panel.match(/data-stream-collapse/g) ?? []).toHaveLength(1);
  });

  it("mounts the strip first and the exception row directly below it", () => {
    // C25's named home: SessionTabs, then StreamHeader (§7.4 badge +
    // `[data-resync-count]` + §8 historyBar), then the transcript region.
    const stripAt = panel.indexOf("<SessionTabs");
    const exceptionAt = panel.indexOf("<StreamHeader");
    const mainAt = panel.indexOf("data-stream-main");
    expect(stripAt).toBeGreaterThan(-1);
    expect(exceptionAt).toBeGreaterThan(stripAt);
    expect(mainAt).toBeGreaterThan(exceptionAt);
  });

  it("places the chevron inside the strip, as its last interactive element", () => {
    const collapseNode = (
      <button type="button" data-stream-collapse="" aria-label={copy.stream.collapse} />
    );
    // Both sides: with and without the `+`, the chevron is a descendant of the
    // strip and the last interactive element in it.
    for (const create of [
      undefined,
      <SessionCreateAction
        key="create"
        profiles={[]}
        part={null}
        pending={false}
        onCreate={() => undefined}
      />,
    ]) {
      const drawn = parse(
        renderToStaticMarkup(
          <SessionTabs
            tabs={[tab()]}
            sessions={[row()]}
            selected="sess-kerf"
            onSelect={() => undefined}
            bounded={false}
            create={create}
            collapse={collapseNode}
          />,
        ),
      );
      const strip = drawn.querySelector("[data-session-strip]");
      const chevron = drawn.querySelector("[data-stream-collapse]");
      expect(chevron).not.toBeNull();
      expect(chevron?.closest("[data-session-strip]")).toBe(strip);
      const interactive = [...(strip?.querySelectorAll("button") ?? [])];
      expect(interactive[interactive.length - 1]).toBe(chevron);
      if (create !== undefined) {
        // After the `+` (§7.1(b)): the create precedes the chevron.
        const plus = drawn.querySelector("[data-session-create]");
        expect(plus).not.toBeNull();
        expect(interactive.indexOf(plus as HTMLButtonElement)).toBeLessThan(
          interactive.indexOf(chevron as HTMLButtonElement),
        );
      }
    }
  });

  it("leads the shared exception row with the badge (C25)", () => {
    const both = header({
      status: "resyncing",
      history: history({ pages: 3, state: "truncated" }),
      resyncs: 1,
    });
    const rowEl = both.body.firstElementChild;
    const children = [...(rowEl?.children ?? [])];
    expect(children[0]?.hasAttribute("data-stream-state")).toBe(true);
    const badgeAt = children.findIndex((node) => node.hasAttribute("data-stream-state"));
    const barAt = children.findIndex((node) => node.hasAttribute("data-history-bar"));
    expect(badgeAt).toBeGreaterThan(-1);
    expect(barAt).toBeGreaterThan(badgeAt);
  });

  it("renders the panel only while the column is expanded", () => {
    expect(shell).toMatch(/\{shell\.streamOpen \? \(/);
  });

  it("renders no unread count, dot or badge on the collapsed strip (§4.1(f))", () => {
    // The clause is WITHDRAWN, not merely unbuilt (§19.42): the strip is a
    // control that expands on focus, and "unread" is a fact this product does
    // not have. The strip is an icon and the column's name, and nothing else.
    const strip = shell.slice(shell.indexOf("data-stream-strip"));
    expect(strip).not.toMatch(/unread|Badge|data-unread|count/i);
    // And no copy exists for one, so a lane cannot draw it by accident.
    expect(Object.keys(copy.stream).filter((key) => /unread/i.test(key))).toEqual([]);
  });
});
