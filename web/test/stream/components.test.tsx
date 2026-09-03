// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The DOM contract, over recorded normalized events (INTERFACE.md §7.2, §7.3,
// §8; mission_plan.md G4.D).
//
// The gate reads the DOM, so these tests read the DOM. `renderToStaticMarkup`
// plus the environment's own parser is the whole apparatus: no testing library,
// no component harness, no new dependency — the components under test are pure
// functions of their props by construction, and the one piece of state in them
// (an image that failed to decode) has a rendered initial value.
//
// What is asserted here is exactly what a Playwright assertion would read:
// `data-tool-name`, `data-status`, the `data-field` set, `data-event-id` in the
// right namespace, `data-widget-source`, `data-thread-depth`,
// `data-thread-state`, the seam, the absences and the labelled break.

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { readToolResult } from "../../src/api/events";
import { SessionTabs } from "../../src/components/stream/SessionTabs";
import { Transcript } from "../../src/components/stream/Transcript";
import { copy } from "../../src/copy";
import { parseToolResult } from "../../src/stream/toolResult";
import {
  groupRows,
  historicalItem,
  liveItem,
  panelRows,
  type LiveEntry,
  type PanelRow,
} from "../../src/stream/transcript";
import type { ThreadTab } from "../../src/stream/thread";
import { allHistoryFrames, fixture } from "./fixture";

function parse(markup: string): Document {
  return new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
}

function renderRows(rows: readonly PanelRow[]): Document {
  return parse(renderToStaticMarkup(<Transcript rows={rows} />));
}

const historyItems = allHistoryFrames().map((frame) => historicalItem(frame, fixture.session_id));
const liveItems = fixture.live_frames.map((frame) => liveItem(frame));
const liveEntries: LiveEntry[] = liveItems.map((item) => ({ entry: "event", item }));

describe("the tool chip's attribute contract (G4.D, §7.2)", () => {
  const document_ = renderRows(groupRows(historyItems));
  const chips = [...document_.querySelectorAll("[data-tool-name]")];

  it("gives every chip a stable tool name and a status from the closed set", () => {
    expect(chips.length).toBeGreaterThan(3);
    for (const chip of chips) {
      expect(chip.getAttribute("data-tool-name")).toBeTruthy();
      expect(["running", "ok", "error", "unknown"]).toContain(chip.getAttribute("data-status"));
    }
  });

  it("names the tools it rendered", () => {
    const names = chips.map((chip) => chip.getAttribute("data-tool-name"));
    expect(names).toContain("build_part");
    expect(names).toContain("edit_part");
    expect(names).toContain("run_checks");
    expect(names).toContain("ask_user");
  });

  it("renders a failed call as error and never as ok", () => {
    const edit = chips.find((chip) => chip.getAttribute("data-tool-name") === "edit_part");
    expect(edit?.getAttribute("data-status")).toBe("error");
    const checks = chips.find((chip) => chip.getAttribute("data-tool-name") === "run_checks");
    expect(checks?.getAttribute("data-status")).toBe("error");
  });

  it("renders an unrecoverable outcome as unknown, with its reason in the chip", () => {
    const measure = chips.find((chip) => chip.getAttribute("data-tool-name") === "measure");
    expect(measure?.getAttribute("data-status")).toBe("unknown");
    expect(measure?.textContent ?? "").toContain("does not record whether the call failed");
  });

  it("carries a historical identity in the historical namespace", () => {
    for (const chip of chips) {
      expect(chip.getAttribute("data-event-id")).toContain("@");
      expect(chip.getAttribute("data-event-id")).not.toContain("#");
    }
  });

  it("carries the tool call id", () => {
    const build = chips.find((chip) => chip.getAttribute("data-tool-name") === "build_part");
    expect(build?.getAttribute("data-tool-call-id")).toBe("call-build-1");
  });
});

describe("the data-field predicate on the rendered DOM (G4.D)", () => {
  const document_ = renderRows(groupRows(historyItems));

  function fieldsOf(toolName: string): string[] {
    const chip = [...document_.querySelectorAll("[data-tool-name]")].find(
      (node) => node.getAttribute("data-tool-name") === toolName,
    );
    return [...(chip?.querySelectorAll("[data-field]") ?? [])].map(
      (node) => node.getAttribute("data-field") ?? "",
    );
  }

  function documentKeys(toolName: string): string[] {
    const row = groupRows(historyItems).find(
      (candidate) =>
        (candidate.row === "chip" && candidate.toolName === toolName) ||
        (candidate.row === "ask" && toolName === "ask_user"),
    );
    const result = row?.row === "chip" || row?.row === "ask" ? row.result : null;
    if (result === null || result === undefined) return [];
    const payload = readToolResult(result.payload);
    if (payload === null) return [];
    const parsed = parseToolResult(payload.text);
    return parsed.state === "parsed" ? [...parsed.fields] : [];
  }

  it("renders one node per key of the parsed result document", () => {
    for (const tool of ["build_part", "inspect_part", "edit_part", "run_checks", "ask_user"]) {
      expect(fieldsOf(tool), tool).toEqual(documentKeys(tool));
    }
  });

  it("renders §7.2's own example fields for build_part", () => {
    expect(fieldsOf("build_part")).toEqual(
      expect.arrayContaining(["status", "artifact_ref", "project_snapshot_ref"]),
    );
  });

  it("degrades visibly, with zero fields and a stated reason", () => {
    const chip = [...document_.querySelectorAll("[data-tool-name]")].find(
      (node) => node.getAttribute("data-tool-name") === "measure",
    );
    expect(chip?.getAttribute("data-field-state")).toBe("unparsed");
    expect(chip?.querySelectorAll("[data-field]")).toHaveLength(0);
    expect(chip?.textContent ?? "").toContain("not a JSON document");
    // The empty field set is a visible refusal carrying its cause, not a pass:
    // the recorded text is still shown, unread rather than discarded.
    expect(chip?.textContent ?? "").toContain("distance: 12.5 mm");
  });

  it("never mints a data-field on a node that is not inside a chip", () => {
    const fields = [...document_.querySelectorAll("[data-field]")];
    for (const field of fields) {
      expect(field.closest("[data-tool-name]")).not.toBeNull();
    }
  });
});

describe("thought sections and images (§7.3)", () => {
  it("renders a thought as an expandable section carrying its event id", () => {
    const document_ = renderRows(groupRows(historyItems));
    const thought = document_.querySelector("[data-thought]");
    expect(thought?.tagName.toLowerCase()).toBe("details");
    expect(thought?.getAttribute("data-event-id")).toBe(`${fixture.session_id}@1`);
  });

  it("keeps every event id when live deltas group into one section", () => {
    const document_ = renderRows(liveRowsOf(liveEntries));
    const thought = document_.querySelector("[data-thought]");
    const inner = [...(thought?.querySelectorAll("[data-event-id]") ?? [])];
    expect(inner).toHaveLength(2);
    expect(thought?.hasAttribute("data-event-id")).toBe(false);
  });

  it("renders a reopened image as a labelled metadata placeholder, not as nothing", () => {
    const document_ = renderRows(groupRows(historyItems));
    const image = document_.querySelector("[data-image-state]");
    expect(image?.getAttribute("data-image-state")).toBe("metadata_only");
    expect(image?.getAttribute("data-mime-type")).toBe("image/png");
    expect(image?.querySelector("img")).toBeNull();
    expect(image?.textContent ?? "").toContain("bytes are not retained");
  });

  it("renders a live image inline from its own bytes", () => {
    const document_ = renderRows(liveRowsOf(liveEntries));
    const image = document_.querySelector("[data-image-state]");
    expect(image?.getAttribute("data-image-state")).toBe("shown");
    expect(image?.querySelector("img")?.getAttribute("src")).toContain("data:image/png;base64,");
  });
});

describe("the ask_user widget (§7.3)", () => {
  it("is rebuilt from the call and result in a reopened transcript", () => {
    const document_ = renderRows(groupRows(historyItems));
    const ask = document_.querySelector("[data-widget-source]");
    expect(ask?.getAttribute("data-widget-source")).toBe("tool_result");
    expect(ask?.getAttribute("data-tool-name")).toBe("ask_user");
    expect(ask?.textContent ?? "").toContain("Rebuilt from the recorded ask_user call");
  });

  it("renders label and consequence, and says when a consequence is absent", () => {
    const document_ = renderRows(groupRows(historyItems));
    const options = [...document_.querySelectorAll("[data-ask-option]")];
    expect(options.map((node) => node.getAttribute("data-ask-option"))).toEqual([
      "Top outer edge",
      "Inner bore edge",
      "Neither",
    ]);
    const consequences = [...document_.querySelectorAll("[data-ask-consequence]")];
    expect(consequences.map((node) => node.getAttribute("data-ask-consequence"))).toEqual([
      "present",
      "present",
      "absent",
    ]);
  });

  // REPOINTED, and the amendment is §7A.7. This assertion used to read "not
  // part of this build", which was true of the hardcoded `disabled` §7A.7 calls
  // a **deviation** and closes. What survives unweakened — and is what the
  // assertion was actually for — is that a disabled control still states its
  // reason: §7A.7 keeps the reopened widget non-interactive *correctly* ("there
  // is no pending question; the run is over") and requires it to keep its
  // stated reason. So the control is still disabled, and the reason is now the
  // named `reopened` one rather than a build-status apology.
  it("disables every control in a reopened transcript and says which kind of disabled it is", () => {
    const document_ = renderRows(groupRows(historyItems));
    const options = [...document_.querySelectorAll("[data-ask-option]")];
    expect(options.every((node) => node.getAttribute("aria-disabled") === "true")).toBe(true);
    expect(options.every((node) => !node.hasAttribute("disabled"))).toBe(true);
    // The archived question was answered, so the widget's *state* is `answered`
    // — but `data-ask-unavailable` is a property of answerability, not of the
    // lifecycle, so the reason the controls are dead survives the answer.
    const ask = document_.querySelector("[data-ask-state]");
    expect(ask?.getAttribute("data-ask-state")).toBe("answered");
    expect(ask?.getAttribute("data-ask-unavailable")).toBe("reopened");
    expect(ask?.textContent ?? "").toContain("Rebuilt from the recorded ask_user call");
  });

  it("is built from the live question, and marks who answered", () => {
    const document_ = renderRows(liveRowsOf(liveEntries));
    const ask = document_.querySelector("[data-widget-source]");
    expect(ask?.getAttribute("data-widget-source")).toBe("question");
    expect(ask?.getAttribute("data-question-id")).toBe(`q-${fixture.run_id}-0`);
    expect(ask?.getAttribute("data-answered-by")).toBe("other");
    expect(document_.querySelector("[data-ask-answer]")?.textContent ?? "").toContain("Keep 2 mm");
  });
});

describe("the transcript's honesty rows (§8, §7.4)", () => {
  it("puts a visible seam between the surfaces and draws no absence hedge", () => {
    const document_ = renderRows(panelRows(historyItems, liveEntries));
    expect(document_.querySelectorAll("[data-absence]")).toHaveLength(0);
    expect(document_.body.textContent ?? "").not.toContain(
      "This reopened transcript doesn't show how the run ended.",
    );
    expect(document_.querySelectorAll("[data-seam]")).toHaveLength(1);
  });

  it("renders a labelled break carrying its outcome and its cursor", () => {
    const rows = panelRows(historyItems, [
      ...liveEntries,
      {
        entry: "break",
        resync: { key: "resync:1", outcome: "gap", after: { run_id: fixture.run_id, seq: 6 } },
      },
    ]);
    const document_ = renderRows(rows);
    const marker = document_.querySelector("[data-resync]");
    expect(marker?.getAttribute("data-resync")).toBe("gap");
    expect(marker?.textContent ?? "").toContain("are not recovered from the recorded transcript");
    expect(marker?.textContent ?? "").toContain(`${fixture.run_id}#6`);
  });

  it("renders no terminal band and no reopen hedge in the historical prefix", () => {
    const document_ = renderRows(panelRows(historyItems, []));
    expect(document_.querySelectorAll("[data-terminal-state]")).toHaveLength(0);
    expect(document_.querySelector("[data-absence]")).toBeNull();
    expect(document_.body.textContent ?? "").not.toContain(
      "This reopened transcript doesn't show how the run ended.",
    );
  });

  it("keeps the run-ended hedge out of the document (§8 C24)", () => {
    const document_ = renderRows(panelRows(historyItems, []));
    expect(document_.querySelectorAll("[data-absence]")).toHaveLength(0);
    expect(document_.body.textContent ?? "").not.toContain("event vocabulary");
    expect(document_.body.textContent ?? "").not.toContain("run-end band");
    expect(document_.body.textContent ?? "").not.toContain(copy.stream.absence.terminal);
  });

  it("does not draw the user-prompt absence sentence", () => {
    const document_ = renderRows(panelRows(historyItems, []));
    expect(document_.querySelector("[data-absence]")).toBeNull();
    expect(document_.body.textContent ?? "").not.toContain(copy.stream.absence.user_prompt);
  });

  it("keeps the break's verdict drawn and its mechanism on title", () => {
    const rows = panelRows(historyItems, [
      ...liveEntries,
      { entry: "break", resync: { key: "resync:2", outcome: "gap", after: null } },
    ]);
    const marker = renderRows(rows).querySelector("[data-resync]");
    // §7.4(c): nothing here permits a silent gap. The drawn line still says
    // the events are not recovered; the two-namespace reason is the title.
    expect(marker?.textContent ?? "").toContain("are not recovered");
    expect(marker?.getAttribute("title")).toBe(copy.stream.resyncDetail.gap);
  });

  it("renders the live terminal band with its outcome", () => {
    const document_ = renderRows(liveRowsOf(liveEntries));
    const band = document_.querySelector("[data-terminal-state]");
    expect(band?.getAttribute("data-terminal-state")).toBe("completed");
    expect(band?.hasAttribute("data-terminal-backpressure")).toBe(false);
  });

  it("distinguishes a backpressure cancellation from a model stopping", () => {
    const backpressure = liveItem({
      run_id: fixture.run_id,
      seq: 2 ** 62,
      kind: "terminal",
      session_id: fixture.session_id,
      payload: { state: "failed", terminal_id: `backpressure:${fixture.run_id}` },
    });
    const document_ = renderRows(groupRows([backpressure]));
    const band = document_.querySelector("[data-terminal-state]");
    expect(band?.getAttribute("data-terminal-backpressure")).toBe("1");
    expect(band?.textContent ?? "").toContain("could not keep up with its events");
  });

  it("gives every rendered event id exactly one element", () => {
    const document_ = renderRows(panelRows(historyItems, liveEntries));
    const ids = [...document_.querySelectorAll("[data-event-id]")].map((node) =>
      node.getAttribute("data-event-id"),
    );
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("puts every archived event id in the reopened DOM, exactly once", () => {
    // G4.11's assertion in miniature: the ids a reopened transcript emits are
    // the `(session_id, ordinal)` pairs, every one of them reaches the DOM, and
    // none reaches it twice. An id that grouping or pairing swallowed would be
    // an id the gate cannot find.
    const document_ = renderRows(panelRows(historyItems, []));
    const rendered = [...document_.querySelectorAll("[data-event-id]")].map(
      (node) => node.getAttribute("data-event-id") ?? "",
    );
    const expected = historyItems.map((item) => item.eventId);
    expect(expected.length).toBeGreaterThan(250);
    expect(new Set(rendered)).toEqual(new Set(expected));
    expect(rendered.length).toBe(expected.length);
    // Every one of them is in the historical namespace, and none is live.
    expect(rendered.every((id) => id.includes("@") && !id.includes("#"))).toBe(true);
  });
});

describe("the session tabs (§7.1, G4.10)", () => {
  const tabs: ThreadTab[] = [
    { session_id: "a", parent_session_id: null, kind: null, depth: 0, thread_state: "linked", origin: {} },
    { session_id: "b", parent_session_id: "a", kind: "delegation", depth: 1, thread_state: "linked", origin: {} },
    {
      session_id: "c",
      parent_session_id: "b",
      kind: "quick_edit",
      depth: 2,
      thread_state: "linked",
      origin: { part: "bracket" },
    },
    { session_id: "d", parent_session_id: null, kind: null, depth: 0, thread_state: "unlinked", origin: {} },
  ];

  const document_ = parse(
    renderToStaticMarkup(
      <SessionTabs
        tabs={tabs}
        sessions={[
          { session_id: "a", profile: "orchestrator", part: null, parent_session_id: null, thread_state: "linked" },
        ]}
        selected="a"
        onSelect={() => undefined}
        bounded={false}
      />,
    ),
  );

  it("renders the three levels with the server's depths", () => {
    const rendered = [...document_.querySelectorAll("[data-session-tab]")];
    expect(rendered.map((node) => node.getAttribute("data-thread-depth"))).toEqual([
      "0",
      "1",
      "2",
      "0",
    ]);
  });

  it("marks the quick-edit and delegation edges by kind", () => {
    const kinds = [...document_.querySelectorAll("[data-session-tab]")].map((node) =>
      node.getAttribute("data-thread-kind"),
    );
    expect(kinds).toEqual([null, "delegation", "quick_edit", null]);
  });

  it("states an unrecoverable parent rather than implying a root", () => {
    const unlinked = [...document_.querySelectorAll('[data-thread-state="unlinked"]')];
    expect(unlinked).toHaveLength(1);
    expect(unlinked[0]?.getAttribute("data-session-tab")).toBe("d");
    expect(unlinked[0]?.getAttribute("title") ?? "").toContain("cannot be recovered");
  });

  it("labels a quick-edit tab from its edge origin", () => {
    const quick = document_.querySelector('[data-session-tab="c"]');
    expect(quick?.getAttribute("data-part")).toBe("bracket");
  });
});

function liveRowsOf(entries: readonly LiveEntry[]): readonly PanelRow[] {
  return panelRows([], entries);
}

describe("the presentation rows' DOM contract (§7.3 C2/C21, amended 2026-09-02)", () => {
  const withEcho: LiveEntry[] = [
    { entry: "echo", key: "echo:0", text: "chamfer the lid, 0.5 mm" },
    ...liveEntries,
  ];

  it("renders the echo with its contract: data-row, data-local-echo, verbatim text", () => {
    const document_ = renderRows(liveRowsOf(withEcho));
    const echo = document_.querySelector('[data-row="local-prompt"]');
    expect(echo).not.toBeNull();
    expect(echo?.getAttribute("data-local-echo")).toBe("1");
    expect(echo?.textContent ?? "").toContain("chamfer the lid, 0.5 mm");
  });

  it("marks the echo unrecorded on its visible face, not on title alone", () => {
    const document_ = renderRows(liveRowsOf(withEcho));
    const echo = document_.querySelector('[data-row="local-prompt"]');
    // The visible-at-rest marker word, C2 verbatim.
    expect(echo?.textContent ?? "").toContain(copy.stream.localEcho.marker);
    // The accessible not-a-recorded-event equivalent, in the DOM as text.
    expect(echo?.textContent ?? "").toContain(copy.stream.localEcho.accessible);
    // `title` carries only the long form — and it is non-empty.
    expect(echo?.querySelector("[title]")?.getAttribute("title")).toBe(copy.stream.localEcho.title);
  });

  it("renders the run-start boundary as a rule line carrying only the run id", () => {
    const document_ = renderRows(liveRowsOf(withEcho));
    const boundary = document_.querySelector('[data-row="run-start"]');
    expect(boundary).not.toBeNull();
    expect(boundary?.getAttribute("data-run-id")).toBe(fixture.run_id);
    expect(boundary?.textContent ?? "").toContain(fixture.run_id);
    expect(boundary?.textContent ?? "").toContain(copy.stream.runStart.accessible);
  });

  it("gives neither presentation row an event id, and loses no real id to them", () => {
    // C2/C21's shared testable: across any transcript, every local-prompt and
    // run-start element carries no data-event-id, and the §7.2 id-set equality
    // still holds on a transcript containing both.
    const document_ = renderRows(liveRowsOf(withEcho));
    for (const row of document_.querySelectorAll(
      '[data-row="local-prompt"], [data-row="run-start"]',
    )) {
      expect(row.hasAttribute("data-event-id")).toBe(false);
      expect(row.querySelector("[data-event-id]")).toBeNull();
    }
    const domIds = new Set<string>();
    for (const node of document_.querySelectorAll("[data-event-id], [data-event-ids]")) {
      const single = node.getAttribute("data-event-id");
      if (single !== null) domIds.add(single);
      for (const id of (node.getAttribute("data-event-ids") ?? "").split(" ")) {
        if (id !== "") domIds.add(id);
      }
    }
    for (const item of liveItems) {
      if (item.kind === "progress") continue; // droppable by §7.3, no row
      expect(domIds.has(item.eventId), item.eventId).toBe(true);
    }
  });

  it("names every id-less data-row: the matcher's by-name skip covers the DOM (G4.11)", () => {
    // The amendment's guard cuts both ways: any data-row other than the two
    // named presentation rows either carries an id itself or is pure layout
    // over id-carrying children. This walks the rendered transcript and
    // asserts the by-name skip list is exhaustive.
    const document_ = renderRows(panelRows(historyItems, withEcho));
    const skip = new Set(["local-prompt", "run-start", "absence", "seam", "resync"]);
    for (const row of document_.querySelectorAll("[data-row]")) {
      const name = row.getAttribute("data-row") ?? "";
      if (skip.has(name)) continue;
      const carries =
        row.querySelector("[data-event-id], [data-event-ids]") !== null ||
        row.hasAttribute("data-event-id");
      expect(carries, `id-less event row: ${name}`).toBe(true);
    }
  });

  it("renders no presentation row in the history prefix; the echo stays live-only (§8 C3)", () => {
    const rows = panelRows(historyItems, withEcho);
    const seamAt = rows.findIndex((row) => row.row === "seam");
    expect(seamAt).toBeGreaterThan(-1);
    const prefix = rows.slice(0, seamAt);
    expect(prefix.some((row) => row.row === "local-prompt" || row.row === "run-start")).toBe(false);
    const document_ = renderRows(rows);
    expect(document_.querySelector("[data-absence]")).toBeNull();
    expect(document_.querySelector('[data-row="local-prompt"]')).not.toBeNull();
  });

  it("renders the observer tab's reopen with no echo and no absence hedge (§8 C3)", () => {
    // Two-tab testable: the second tab has history only (no echo entry — the
    // echo is never minted by history, resync, or observer tabs).
    const observer = renderRows(panelRows(historyItems, []));
    expect(observer.querySelector('[data-row="local-prompt"]')).toBeNull();
    expect(observer.querySelector('[data-row="run-start"]')).toBeNull();
    expect(observer.querySelector("[data-absence]")).toBeNull();
    const originating = renderRows(panelRows(historyItems, withEcho));
    expect(originating.querySelector("[data-absence]")).toBeNull();
    expect(observer.body.textContent ?? "").not.toContain(copy.stream.absence.user_prompt);
    expect(originating.body.textContent ?? "").not.toContain(copy.stream.absence.user_prompt);
  });
});
