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
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SessionTabs } from "../../src/components/stream/SessionTabs";
import { copy } from "../../src/copy";
import { RUNTIME_FAULTS } from "../../src/stream/runtimeFault";
import type { SessionRow } from "../../src/api/sessions";
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
    // No sixth stream state, and `data-stream-state` still carries the socket's
    // own answer — which the e2e reads by name (`stream.spec.ts` G4.8).
    const states = source("stream/transcript.ts");
    expect(states).toMatch(
      /STREAM_STATES = \[\s*"live",\s*"reconnecting",\s*"resyncing",\s*"historical",\s*"detached",\s*\]/,
    );
    expect(panel).toContain("data-stream-state={stream.status}");
    expect(panel).not.toContain('data-stream-state="runtime');
  });

  it("gives the fault its own attribute, on exactly one node", () => {
    const occurrences = panel.match(/data-runtime-fault=/g) ?? [];
    expect(occurrences).toHaveLength(1);
  });

  it("shows the fault on the badge instead of the socket state", () => {
    // The badge is what the operator reads; `live` beside a dead run is the
    // one true thing that does not matter.
    expect(panel).toMatch(/status=\{fault !== null \? "error"/);
    expect(panel).toMatch(/fault !== null \? copy\.stream\.runtimeFault\[fault\]/);
  });

  it("has one sentence per fault grade, and no grade without one", () => {
    for (const grade of RUNTIME_FAULTS) {
      expect(copy.stream.runtimeFault[grade], grade).toBeTruthy();
      expect(copy.stream.runtimeFaultWhy[grade], grade).toBeTruthy();
    }
    expect(Object.keys(copy.stream.runtimeFaultWhy).sort()).toEqual([...RUNTIME_FAULTS].sort());
  });

  it("offers no recovery control, and points at the composer instead", () => {
    // §7A.5: a turn that may have started is never resent automatically, so the
    // recovery on offer is the operator's own next message and nothing else —
    // no button in the band, no wizard behind one.
    const band = panel.slice(
      panel.indexOf("data-runtime-fault={fault}"),
      panel.indexOf("sessionsFault === null"),
    );
    expect(band).not.toContain("<Button");
    expect(band).not.toContain("onClick");
    expect(copy.stream.runtimeFaultNext).toContain("composer");
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

  it("folds §8's page counter onto the header row it shares with the state", () => {
    // The attributes both gates read are unmoved; only the row is.
    expect(panel).toContain("data-history-state={stream.history.state}");
    expect(panel).toContain("data-history-pages={stream.history.pages}");
    expect(stream).not.toMatch(/\.historyBar\s*\{[^}]*border-bottom/);
    expect(stream).toMatch(/\.historyBar\s*\{[^}]*flex:\s*1 1 auto/);
  });

  it("renders no header row at all with no session selected", () => {
    // An `historical` pill over an empty well is a state to resolve, and an
    // empty bordered strip is furniture; the empty well's content is an action.
    expect(panel).toMatch(/\{selected === null \? null : \(\s*<div className=\{styles\["header"\]\}/);
  });

  it("still keeps the composer as the panel's last child", () => {
    expect(panel.lastIndexOf("<Composer")).toBeGreaterThan(panel.lastIndexOf("data-stream-main"));
  });

  it("bottom-anchors the empty invitation so the void sits above it (#56)", () => {
    expect(stream).toMatch(/\[data-stream-empty\]\s*\.main\s*\{[^}]*justify-content:\s*flex-end/);
    expect(panel).toContain('data-stream-empty');
  });

  it("does not mount NewSessionAction only when the session list is empty (#70)", () => {
    // §7A.2's two create affordances stay reachable after the first session.
    // One element, two call sites: the empty invitation *and* the tab stack.
    expect(panel).toContain("const createAction");
    expect(panel).toContain("action={createAction}");
    const afterTabs = panel.slice(panel.indexOf("<SessionTabs"));
    expect(afterTabs).toContain("{createAction}");
    expect(afterTabs).toContain("Send does not create a session");
  });

  it("focuses the composer after New session (#61)", () => {
    expect(panel).toContain("setFocusNonce");
    expect(panel).toContain("focusNonce={focusNonce}");
  });
});

describe("the session tab row is a name, not three metadata strings", () => {
  it("drops the heading over a list of one", () => {
    const one = tabsMarkup([tab()], [row()]);
    expect(one.querySelector("h2")).toBeNull();
    const many = tabsMarkup(
      [tab(), tab({ session_id: "sess-child", parent_session_id: "sess-kerf", depth: 1 })],
      [row(), row({ session_id: "sess-child", part: "riser" })],
    );
    expect(many.querySelector("h2")?.textContent).toBe(copy.stream.sessionsHeading);
  });

  it("does not restate the indent as a word", () => {
    const linked = tabsMarkup([tab()], [row()]);
    const button = linked.querySelector("[data-session-tab]");
    expect(button?.getAttribute("data-thread-state")).toBe("linked");
    expect(button?.textContent ?? "").not.toContain(copy.stream.threadState.linked);
    expect(button?.textContent ?? "").toContain("kerf_card");
  });

  it("keeps §2.8's unlinked state stated, short, with the whole reason on title", () => {
    const unlinked = tabsMarkup(
      [tab({ thread_state: "unlinked" })],
      [row({ thread_state: "unlinked" })],
    );
    const button = unlinked.querySelector("[data-session-tab]");
    expect(button?.getAttribute("data-thread-state")).toBe("unlinked");
    expect(button?.textContent ?? "").toContain(copy.stream.threadState.unlinked);
    expect(button?.getAttribute("title") ?? "").toContain("cannot be recovered");
    // Short enough to sit beside a part name in a 420px column.
    expect(copy.stream.threadState.unlinked.length).toBeLessThanOrEqual(12);
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

  it("keeps Cancel rendered whether or not it is available (§7A.6)", () => {
    expect(composer).toContain('data-composer-cancel=""');
    expect(composer).toMatch(/cancellable \? \{\} : \{ disabled: true as const, reason: cancelWhy \}/);
  });

  it("makes a run_in_flight refusal cancellable and typable, so it has an exit", () => {
    expect(composer).toContain("cancelAvailability");
    expect(composer).toContain("isComposable(disabledReason)");
    // And it expires on the frame that says the run ended.
    expect(composer).toMatch(/seenTerminals\.current = count/);
  });

  it("keeps the idle composer one row, and the hint out of it", () => {
    expect(composer).toMatch(/promptRows = promptFocused \|\| text\.trim\(\) !== "" \? 3 : 1/);
    expect(composer).toMatch(/\{promptFocused \|\| text !== "" \? \(/);
  });
});
