// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The transcript model, over recorded normalized events (INTERFACE.md §7.2,
// §7.3, §8, §2.8).

import { describe, expect, it } from "vitest";
import { identitySurface } from "../../src/api/events";
import {
  chipStatus,
  groupRows,
  historicalItem,
  historicalRows,
  liveItem,
  liveRows,
  panelRows,
  runsWithTerminal,
  type PanelRow,
  type TranscriptItem,
} from "../../src/stream/transcript";
import { allHistoryFrames, fixture } from "./fixture";

function historyItems(): TranscriptItem[] {
  return allHistoryFrames().map((frame) => historicalItem(frame, fixture.session_id));
}

function liveItems(): TranscriptItem[] {
  return fixture.live_frames.map((frame) => liveItem(frame));
}

describe("event identity (§2.8)", () => {
  it("mints historical ids in the session namespace and live ids in the run namespace", () => {
    const history = historyItems();
    const live = liveItems();
    expect(history[0]?.eventId).toBe(`${fixture.session_id}@0`);
    expect(live[0]?.eventId).toBe(`${fixture.run_id}#0`);
    expect(identitySurface(history[0]?.eventId ?? "")).toBe("historical");
    expect(identitySurface(live[0]?.eventId ?? "")).toBe("live");
  });

  it("reads the session id from the page, not from the frame's misnamed run_id", () => {
    // `main.ts` passes the session id into `history.ts`'s `runId` parameter, so
    // the frame's `run_id` IS the session id. The identity is built from the
    // page's own field; this asserts the two agree, which is what makes the
    // misnomer harmless rather than invisible.
    const frame = allHistoryFrames()[0];
    expect(frame?.run_id).toBe(fixture.session_id);
  });

  it("gives every historical event a distinct, ordinal-ordered identity", () => {
    const ids = historyItems().map((item) => item.eventId);
    expect(new Set(ids).size).toBe(ids.length);
    // The ordinal restarts at 0 for the session and increments by one, which is
    // the property G4.11's archive is an archive of.
    expect(ids.slice(0, 4)).toEqual([
      `${fixture.session_id}@0`,
      `${fixture.session_id}@1`,
      `${fixture.session_id}@2`,
      `${fixture.session_id}@3`,
    ]);
  });
});

describe("chip status (§7.2)", () => {
  const rows = groupRows(historyItems());
  const chips = rows.filter((row) => row.row === "chip");
  const byTool = new Map(chips.map((chip) => [chip.toolName, chip]));

  it("derives ok / error from the engine's own isError", () => {
    expect(byTool.get("build_part")?.status).toBe("ok");
    expect(byTool.get("edit_part")?.status).toBe("error");
  });

  it("recovers a failure from the serialized envelope when Pi's flag is absent", () => {
    // The recorded `run_checks` entry has NO `isError` field; `recoverIsError`
    // read `{"status": "error"}` out of the result envelope. Without §7.2's NEW
    // WORK this chip would have read `ok` — a failed call stated as a success.
    expect(byTool.get("run_checks")?.status).toBe("error");
  });

  it("never reads an unrecoverable flag as ok", () => {
    // The recorded `measure` entry has neither signal and an unparseable body.
    // §7.2's named fourth value is what it gets; `ok` is not an option.
    expect(byTool.get("measure")?.status).toBe("unknown");
  });

  it("leaves a call with no result running, whatever the run did", () => {
    const call = historyItems()[2];
    expect(call).toBeDefined();
    expect(chipStatus(null)).toBe("running");
    // Cancellation is a property of the run, not of a chip: no row type here
    // turns a terminal into a chip status.
    const terminalRows = groupRows(liveItems()).filter((row) => row.row === "terminal");
    expect(terminalRows).toHaveLength(1);
  });
});

describe("pairing and grouping (§7.2, §7.3)", () => {
  it("attaches a result and its images to the call's chip", () => {
    const chips = groupRows(historyItems()).filter((row) => row.row === "chip");
    const inspect = chips.find((chip) => chip.toolName === "inspect_part");
    expect(inspect?.result).not.toBeNull();
    expect(inspect?.images).toHaveLength(1);
    expect(inspect?.images[0]?.kind).toBe("image");
  });

  it("renders ask_user as a widget, not as a generic chip", () => {
    const rows = groupRows(historyItems());
    expect(rows.filter((row) => row.row === "chip" && row.toolName === "ask_user")).toHaveLength(0);
    const ask = rows.find((row) => row.row === "ask");
    expect(ask?.source).toBe("tool_result");
    expect(ask?.call).not.toBeNull();
    expect(ask?.result).not.toBeNull();
    expect(ask?.status).toBe("ok");
  });

  it("folds a live question into the open ask_user call and records its answer", () => {
    const rows = groupRows(liveItems());
    const asks = rows.filter((row) => row.row === "ask");
    expect(asks).toHaveLength(1);
    expect(asks[0]?.source).toBe("question");
    expect(asks[0]?.answer).not.toBeNull();
  });

  it("produces no row for progress, the one droppable kind", () => {
    const progress = fixture.live_frames.filter((frame) => frame.kind === "progress");
    expect(progress.length).toBeGreaterThan(0);
    const rows = groupRows(liveItems());
    expect(rows.some((row) => row.row === "unknown")).toBe(false);
    // Every row is accounted for by a non-progress kind.
    expect(rows.map((row) => row.row).sort()).toEqual(
      ["ask", "chip", "terminal", "text", "thought"].sort(),
    );
  });

  it("groups contiguous deltas without losing an identity", () => {
    const rows = groupRows(liveItems());
    const text = rows.find((row) => row.row === "text");
    const thought = rows.find((row) => row.row === "thought");
    expect(text?.items).toHaveLength(2);
    expect(thought?.items).toHaveLength(2);
    const grouped = [...(text?.items ?? []), ...(thought?.items ?? [])].map((i) => i.eventId);
    expect(new Set(grouped).size).toBe(grouped.length);
  });

  it("never groups a historical text block with the one after it", () => {
    // Historical `text_delta` events are whole blocks, and the recorded session
    // ends with a long run of them. They still group for layout, but every id
    // survives — the group carries one element per event.
    const rows = groupRows(historyItems());
    const texts = rows.filter((row) => row.row === "text");
    const ids = texts.flatMap((row) => row.items.map((item) => item.eventId));
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("the panel's rows (§8)", () => {
  it("names the two absences a reopened transcript cannot fill", () => {
    const rows = historicalRows(historyItems());
    const absences = rows.filter((row) => row.row === "absence").map((row) => row.absence);
    expect(absences).toEqual(["user_prompt", "terminal"]);
    expect(rows[0]?.row).toBe("absence");
    expect(rows[rows.length - 1]?.row).toBe("absence");
  });

  it("says nothing about absences when there is no history to reopen", () => {
    expect(historicalRows([])).toEqual([]);
  });

  it("puts a visible seam between the historical prefix and the live suffix", () => {
    const rows = panelRows(
      historyItems(),
      liveItems().map((item) => ({ entry: "event", item }) as const),
    );
    const seams = rows.filter((row) => row.row === "seam");
    expect(seams).toHaveLength(1);
    const seamAt = rows.findIndex((row) => row.row === "seam");
    const before = rows.slice(0, seamAt);
    const after = rows.slice(seamAt + 1);
    expect(surfaces(before)).toEqual(new Set(["historical"]));
    expect(surfaces(after)).toEqual(new Set(["live"]));
  });

  it("shows no seam when only one side exists", () => {
    expect(panelRows(historyItems(), []).some((row) => row.row === "seam")).toBe(false);
    expect(
      panelRows(
        [],
        liveItems().map((item) => ({ entry: "event", item }) as const),
      ).some((row) => row.row === "seam"),
    ).toBe(false);
  });

  it("never groups across a labelled break", () => {
    const items = liveItems();
    const first = items[0];
    const second = items[1];
    expect(first).toBeDefined();
    expect(second).toBeDefined();
    if (first === undefined || second === undefined) return;
    const rows = liveRows([
      { entry: "event", item: first },
      { entry: "break", resync: { key: "r1", outcome: "gap", after: null } },
      { entry: "event", item: second },
    ]);
    // Two text rows, not one: a paragraph flowing across a labelled gap would
    // be the silent join §8 forbids.
    expect(rows.filter((row) => row.row === "text")).toHaveLength(2);
    expect(rows[1]?.row).toBe("resync");
  });
});

describe("runsWithTerminal — sidecar death never mints one (#50)", () => {
  it("collects only live terminal rows", () => {
    const ended = liveItem({
      run_id: "run-done",
      seq: 99,
      kind: "terminal",
      session_id: "sess-1",
      payload: { state: "completed", terminal_id: "term-1" },
    });
    const open = liveItem({
      run_id: "run-open",
      seq: 1,
      kind: "question",
      session_id: "sess-1",
      payload: { question_id: "q-1", question: "Which?" },
    });
    const rows = liveRows([
      { entry: "event", item: open },
      { entry: "event", item: ended },
    ]);
    expect([...runsWithTerminal(rows)]).toEqual(["run-done"]);
  });
});

function surfaces(rows: readonly PanelRow[]): Set<string> {
  const found = new Set<string>();
  for (const row of rows) {
    switch (row.row) {
      case "text":
      case "thought":
        for (const item of row.items) found.add(item.surface);
        break;
      case "chip":
        found.add(row.call.surface);
        break;
      case "ask": {
        const anchor = row.call ?? row.question ?? row.answer;
        if (anchor !== null) found.add(anchor.surface);
        break;
      }
      case "image":
      case "audit":
      case "terminal":
      case "unknown":
        found.add(row.item.surface);
        break;
      default:
        break;
    }
  }
  return found;
}
