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
  it("restores operator prompts in the historical prefix and mints no hedge", () => {
    const rows = historicalRows(historyItems(), [{ seq: 0, text: "Add a 2 mm chamfer." }]);
    expect(rows.filter((row) => row.row === "absence")).toEqual([]);
    expect(rows[0]).toEqual({
      row: "user-prompt",
      key: "user-prompt:0",
      text: "Add a 2 mm chamfer.",
      eventId: `${historyItems()[0]?.sessionId ?? ""}@prompt:0`,
    });
    expect(rows.some((row) => row.row === "user-prompt")).toBe(true);
  });

  it("names no absences on a reopened transcript", () => {
    const rows = historicalRows(historyItems());
    expect(rows.filter((row) => row.row === "absence")).toEqual([]);
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

// ---------------------------------------------------------------------------
// §7.2 (a) — repeat groups, both halves
// ---------------------------------------------------------------------------

describe("consecutive identical successful calls coalesce (§7.2 (a))", () => {
  const RUN = "run-repeat000000";
  const DOC = { status: "ok", total: 1, items: [{ name: "tread_checks" }] };

  /** One `tool_call` + `tool_result` pair, in the live namespace. */
  function pair(
    index: number,
    patch: {
      readonly tool?: string;
      readonly doc?: unknown;
      readonly text?: string;
      readonly isError?: boolean | null;
      readonly args?: unknown;
    } = {},
  ): TranscriptItem[] {
    const tool = patch.tool ?? "list_project_checks";
    const callId = `c-${String(index)}`;
    const payload =
      patch.text === undefined ? JSON.stringify(patch.doc ?? DOC) : patch.text;
    return [
      liveItem({
        run_id: RUN,
        seq: index * 2,
        kind: "tool_call",
        session_id: "sess-repeat",
        tool_call_id: callId,
        payload: { name: tool, arguments: patch.args ?? {} },
      }),
      liveItem({
        run_id: RUN,
        seq: index * 2 + 1,
        kind: "tool_result",
        session_id: "sess-repeat",
        tool_call_id: callId,
        // `?? false` would turn the deliberate `null` — §7.2's `unknown`
        // fallback — into `ok`, which is the very defect the fallback exists to
        // stop, so the absent case is tested rather than the falsy one.
        payload: {
          toolName: tool,
          isError: patch.isError === undefined ? false : patch.isError,
          text: payload,
        },
      }),
    ];
  }

  function chips(items: readonly TranscriptItem[]): readonly PanelRow[] {
    return groupRows(items).filter((row) => row.row === "chip");
  }

  it("folds a run of three into one row carrying the count", () => {
    const rows = chips([...pair(0), ...pair(1), ...pair(2)]);
    expect(rows).toHaveLength(1);
    const row = rows[0];
    expect(row?.row === "chip" ? row.repeat?.length : null).toBe(3);
  });

  it("loses no id: the members' ids are the calls' ids, in render order", () => {
    const items = [...pair(0), ...pair(1), ...pair(2)];
    const row = chips(items)[0];
    const members = row?.row === "chip" ? (row.repeat ?? []) : [];
    expect(members.map((member) => member.call.eventId)).toEqual([
      `${RUN}#0`,
      `${RUN}#2`,
      `${RUN}#4`,
    ]);
    expect(members.map((member) => member.result?.eventId)).toEqual([
      `${RUN}#1`,
      `${RUN}#3`,
      `${RUN}#5`,
    ]);
    // The row still anchors on the FIRST member, so every address that resolved
    // before the amendment still resolves.
    expect(row?.row === "chip" ? row.call.eventId : null).toBe(`${RUN}#0`);
  });

  it("draws no count for a run of one", () => {
    const rows = chips(pair(0));
    expect(rows).toHaveLength(1);
    expect(rows[0]?.row === "chip" ? rows[0].repeat : "missing").toBeUndefined();
  });

  it("coalesces across key order, because the test is on the canonical document", () => {
    const rows = chips([
      ...pair(0, { doc: { a: 1, b: 2 } }),
      ...pair(1, { doc: { b: 2, a: 1 } }),
    ]);
    expect(rows).toHaveLength(1);
  });

  describe("the negative half — a group does NOT form when", () => {
    it("the documents differ by any byte", () => {
      expect(chips([...pair(0), ...pair(1, { doc: { ...DOC, total: 2 } })])).toHaveLength(2);
    });

    it("the tool names differ", () => {
      expect(chips([...pair(0), ...pair(1, { tool: "read_part" })])).toHaveLength(2);
    });

    it("any member failed — two identical failures never coalesce", () => {
      const rows = chips([...pair(0, { isError: true }), ...pair(1, { isError: true })]);
      expect(rows).toHaveLength(2);
      expect(rows.every((row) => row.row === "chip" && row.status === "error")).toBe(true);
    });

    it("a member is still running", () => {
      const [call] = pair(9);
      expect(call).toBeDefined();
      const rows = chips([...pair(0), ...(call === undefined ? [] : [call])]);
      expect(rows).toHaveLength(2);
    });

    it("a member's outcome is unknown", () => {
      const rows = chips([
        ...pair(0, { isError: null }),
        ...pair(1, { isError: null }),
      ]);
      expect(rows).toHaveLength(2);
      expect(rows.every((row) => row.row === "chip" && row.status === "unknown")).toBe(true);
    });

    it("an item of another kind falls between them", () => {
      const between = liveItem({
        run_id: RUN,
        seq: 500,
        kind: "text_delta",
        session_id: "sess-repeat",
        payload: { text: "Scanning." },
      });
      expect(chips([...pair(0), between, ...pair(1)])).toHaveLength(2);
    });

    it("a member carries an inline image, whose own identity a shared row cannot hold", () => {
      const image = liveItem({
        run_id: RUN,
        seq: 501,
        kind: "image",
        session_id: "sess-repeat",
        tool_call_id: "c-0",
        payload: { mimeType: "image/png", bytes: 5, data: "aGVsbG8=" },
      });
      const [call, result] = pair(0);
      expect(call).toBeDefined();
      expect(result).toBeDefined();
      if (call === undefined || result === undefined) return;
      expect(chips([call, result, image, ...pair(1)])).toHaveLength(2);
    });

    it("the members lie on opposite sides of the §8 seam", () => {
      const history = [...pair(0)].map((item) =>
        historicalItem(
          { run_id: "sess-repeat", seq: item.seq, kind: item.rawKind, tool_call_id: "c-0", payload: item.payload },
          "sess-repeat",
        ),
      );
      const rows = panelRows(
        history,
        pair(1).map((item) => ({ entry: "event", item }) as const),
      );
      expect(rows.filter((row) => row.row === "chip")).toHaveLength(2);
    });

    it("a labelled resync break falls between them", () => {
      const rows = liveRows([
        ...pair(0).map((item) => ({ entry: "event", item }) as const),
        { entry: "break", resync: { key: "r1", outcome: "gap", after: null } },
        ...pair(1).map((item) => ({ entry: "event", item }) as const),
      ]);
      expect(rows.filter((row) => row.row === "chip")).toHaveLength(2);
    });
  });
});

describe("cycle groups: (chip, text) pairs coalesce from the third pair (§7.2 C4/C5)", () => {
  const RUN = "run-cycle0000000";
  const DOC = { status: "ok", total: 1 };

  /** One `tool_call` + `tool_result` + narration `text_delta` triple. */
  function cyclePair(
    index: number,
    patch: {
      readonly tool?: string;
      readonly doc?: unknown;
      readonly isError?: boolean | null;
      readonly narration?: string;
    } = {},
  ): TranscriptItem[] {
    const tool = patch.tool ?? "list_project_checks";
    const callId = `cy-${String(index)}`;
    return [
      liveItem({
        run_id: RUN,
        seq: index * 3,
        kind: "tool_call",
        session_id: "sess-cycle",
        tool_call_id: callId,
        payload: { name: tool, arguments: {} },
      }),
      liveItem({
        run_id: RUN,
        seq: index * 3 + 1,
        kind: "tool_result",
        session_id: "sess-cycle",
        tool_call_id: callId,
        payload: {
          toolName: tool,
          isError: patch.isError === undefined ? false : patch.isError,
          text: JSON.stringify(patch.doc ?? DOC),
        },
      }),
      liveItem({
        run_id: RUN,
        seq: index * 3 + 2,
        kind: "text_delta",
        session_id: "sess-cycle",
        payload: { text: patch.narration ?? `Still scanning (${String(index)}).` },
      }),
    ];
  }

  function triples(n: number): TranscriptItem[] {
    return Array.from({ length: n }, (_, index) => cyclePair(index)).flat();
  }

  it("folds three (chip, text) pairs into ONE cycle row, first pair intact", () => {
    const rows = groupRows(triples(3));
    expect(rows).toHaveLength(1);
    const row = rows[0];
    if (row?.row !== "cycle") throw new Error("expected a cycle row");
    expect(row.pairs).toHaveLength(3);
    expect(row.toolName).toBe("list_project_checks");
    // The first pair is the full pair, exactly as ungrouped.
    expect(row.pairs[0]?.chip.call.eventId).toBe(`${RUN}#0`);
    expect(row.pairs[0]?.text.items[0]?.eventId).toBe(`${RUN}#2`);
    // The row anchors on the first pair's chip, so addressing still resolves.
    expect(row.key).toBe(`${RUN}#0`);
  });

  it("two pairs are two pairs — the threshold is three (the negative half, count)", () => {
    const rows = groupRows(triples(2));
    expect(rows.some((row) => row.row === "cycle")).toBe(false);
    expect(rows.filter((row) => row.row === "chip")).toHaveLength(2);
    expect(rows.filter((row) => row.row === "text")).toHaveLength(2);
  });

  it("loses NOTHING the DOM discipline tracks: every event of every pair is in the row (C5)", () => {
    const items = triples(3);
    const row = groupRows(items)[0];
    if (row?.row !== "cycle") throw new Error("expected a cycle row");
    const held = new Set<string>();
    for (const pair of row.pairs) {
      const members = pair.chip.repeat ?? [{ call: pair.chip.call, result: pair.chip.result }];
      for (const member of members) {
        held.add(member.call.eventId);
        if (member.result !== null) held.add(member.result.eventId);
      }
      for (const item of pair.text.items) held.add(item.eventId);
    }
    expect([...held].sort()).toEqual(items.map((item) => item.eventId).sort());
  });

  it("accepts a ×N repeat group as a pair's chip member (chip-or-repeat-group)", () => {
    // Two back-to-back identical calls coalesce into one ×2 row (§7.2 (a));
    // that ROW, plus its narration, is one pair of the cycle.
    const [callA, resultA] = cyclePair(0);
    const doubled = [
      ...(callA === undefined || resultA === undefined ? [] : [callA, resultA]),
      ...cyclePair(1),
      ...cyclePair(2),
      ...cyclePair(3),
    ];
    const rows = groupRows(doubled);
    expect(rows).toHaveLength(1);
    const row = rows[0];
    if (row?.row !== "cycle") throw new Error("expected a cycle row");
    expect(row.pairs).toHaveLength(3);
    expect(row.pairs[0]?.chip.repeat?.length).toBe(2);
  });

  it("does not require the narration to repeat byte-identically", () => {
    const rows = groupRows([
      ...cyclePair(0, { narration: "Scanning." }),
      ...cyclePair(1, { narration: "Scanning again." }),
      ...cyclePair(2, { narration: "And once more." }),
    ]);
    expect(rows[0]?.row).toBe("cycle");
  });

  describe("the negative half, the same four ways as (a) — a cycle does NOT form when", () => {
    it("any chip member's status is not ok — repeated failures never fold", () => {
      const rows = groupRows([
        ...cyclePair(0),
        ...cyclePair(1),
        ...cyclePair(2, { isError: true }),
      ]);
      expect(rows.some((row) => row.row === "cycle")).toBe(false);
      expect(rows.filter((row) => row.row === "chip")).toHaveLength(3);
    });

    it("any result document differs in a byte", () => {
      const rows = groupRows([
        ...cyclePair(0),
        ...cyclePair(1, { doc: { ...DOC, total: 2 } }),
        ...cyclePair(2),
      ]);
      expect(rows.some((row) => row.row === "cycle")).toBe(false);
    });

    it("the tool names differ", () => {
      const rows = groupRows([
        ...cyclePair(0),
        ...cyclePair(1, { tool: "read_part" }),
        ...cyclePair(2),
      ]);
      expect(rows.some((row) => row.row === "cycle")).toBe(false);
    });

    it("an item of a third kind falls between the pairs", () => {
      const thought = liveItem({
        run_id: RUN,
        seq: 900,
        kind: "thought",
        session_id: "sess-cycle",
        payload: { text: "Considering." },
      });
      const rows = groupRows([
        ...cyclePair(0),
        thought,
        ...cyclePair(1),
        ...cyclePair(2),
      ]);
      expect(rows.some((row) => row.row === "cycle")).toBe(false);
    });

    it("a labelled resync break falls between the pairs", () => {
      const rows = liveRows([
        ...cyclePair(0).map((item) => ({ entry: "event", item }) as const),
        { entry: "break", resync: { key: "r1", outcome: "gap", after: null } },
        ...cyclePair(1).map((item) => ({ entry: "event", item }) as const),
        ...cyclePair(2).map((item) => ({ entry: "event", item }) as const),
      ]);
      expect(rows.some((row) => row.row === "cycle")).toBe(false);
    });

    it("a §7.3 presentation row falls between the pairs", () => {
      const rows = liveRows([
        ...cyclePair(0).map((item) => ({ entry: "event", item }) as const),
        { entry: "echo", key: "echo-1", text: "again please" },
        ...cyclePair(1).map((item) => ({ entry: "event", item }) as const),
        ...cyclePair(2).map((item) => ({ entry: "event", item }) as const),
      ]);
      expect(rows.some((row) => row.row === "cycle")).toBe(false);
      expect(rows.some((row) => row.row === "local-prompt")).toBe(true);
    });

    it("the pairs lie on opposite sides of the §8 seam", () => {
      const history = cyclePair(0).map((item) =>
        historicalItem(
          {
            run_id: "sess-cycle",
            seq: item.seq,
            kind: item.rawKind,
            ...(item.toolCallId === null ? {} : { tool_call_id: item.toolCallId }),
            payload: item.payload,
          },
          "sess-cycle",
        ),
      );
      const rows = panelRows(history, [
        ...cyclePair(1).map((item) => ({ entry: "event", item }) as const),
        ...cyclePair(2).map((item) => ({ entry: "event", item }) as const),
      ]);
      expect(rows.some((row) => row.row === "cycle")).toBe(false);
      expect(rows.some((row) => row.row === "seam")).toBe(true);
    });
  });

  it("a cycle whose fourth chip lacks its narration stays maximal at the pairs it has", () => {
    const [call, result] = cyclePair(3);
    const rows = groupRows([
      ...triples(3),
      ...(call === undefined || result === undefined ? [] : [call, result]),
    ]);
    const cycle = rows.find((row) => row.row === "cycle");
    if (cycle?.row !== "cycle") throw new Error("expected a cycle row");
    expect(cycle.pairs).toHaveLength(3);
    // The unpaired chip renders as its own row — outside the group, not lost.
    expect(rows.filter((row) => row.row === "chip")).toHaveLength(1);
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

// ---------------------------------------------------------------------------
// §7.3 C1/C2/C21 and §8 C3 — the presentation rows, both halves of every rule
// ---------------------------------------------------------------------------

describe("the local prompt echo and the run-start boundary (amended 2026-09-02)", () => {
  const delta = (runId: string, seq: number): TranscriptItem =>
    liveItem({
      run_id: runId,
      seq,
      kind: "text_delta",
      session_id: fixture.session_id,
      payload: { text: `t${String(seq)}` },
    });
  const event = (runId: string, seq: number): { entry: "event"; item: TranscriptItem } => ({
    entry: "event",
    item: delta(runId, seq),
  });
  const echo = (key: string, text: string): { entry: "echo"; key: string; text: string } => ({
    entry: "echo",
    key,
    text,
  });
  const gap = (key: string): { entry: "break"; resync: { key: string; outcome: "gap"; after: null } } => ({
    entry: "break",
    resync: { key, outcome: "gap", after: null },
  });
  const names = (rows: readonly PanelRow[]): string[] => rows.map((row) => row.row);
  const starts = (rows: readonly PanelRow[]) =>
    rows.filter((row) => row.row === "run-start");

  it("renders the echo verbatim at the tail, before any frame (C1)", () => {
    const rows = liveRows([echo("echo:0", "add a 3mm fillet")]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({ row: "local-prompt", key: "echo:0", text: "add a 3mm fillet" });
  });

  it("licenses exactly one run-start from the echo — C21's base case", () => {
    const rows = liveRows([echo("echo:0", "p"), event("run-a", 0), event("run-a", 1)]);
    expect(names(rows)).toEqual(["local-prompt", "run-start", "text"]);
    expect(starts(rows)[0]?.runId).toBe("run-a");
  });

  it("mints no boundary with no previous rendered live row and no echo (mid-run attach)", () => {
    // An observer attaching mid-run honestly renders the run in progress with
    // no top boundary — the frames it never held cannot license a row.
    const rows = liveRows([event("run-a", 5), event("run-a", 6)]);
    expect(starts(rows)).toHaveLength(0);
  });

  it("mints by comparison on a run change, and never within a run", () => {
    // Observer: no echo, two runs → exactly one boundary, at the change.
    const rows = liveRows([event("run-a", 5), event("run-b", 0), event("run-b", 1)]);
    expect(starts(rows)).toHaveLength(1);
    expect(starts(rows)[0]?.runId).toBe("run-b");
    expect(names(rows)).toEqual(["text", "run-start", "text"]);
  });

  it("renders, in the originating tab, two runs as exactly two boundaries with distinct ids", () => {
    // The amendment's own testable: the first echo-licensed, the second by
    // comparison.
    const rows = liveRows([
      echo("echo:0", "p"),
      event("run-a", 0),
      event("run-a", 1),
      event("run-b", 0),
    ]);
    expect(starts(rows).map((row) => row.runId)).toEqual(["run-a", "run-b"]);
  });

  it("consumes the license on the first frame: a same-run frame after a mid-live echo mints nothing new", () => {
    // Second Send while the previous run's frames are still arriving: the echo
    // stands, but no boundary is minted within a run, and the next run change
    // still mints exactly one (by comparison).
    const rows = liveRows([
      event("run-a", 0),
      echo("echo:0", "p2"),
      event("run-a", 1),
      event("run-b", 0),
    ]);
    expect(starts(rows).map((row) => row.runId)).toEqual(["run-b"]);
  });

  it("terminates derivation at a resync seam exactly as at the §8 seam (C21)", () => {
    // Same run resumes after the break → no boundary; a DIFFERENT run's first
    // frame after the break mints none either, because run ids are never
    // compared across a gap in which boundary events may have been lost.
    const sameRun = liveRows([event("run-a", 0), gap("r1"), event("run-a", 1)]);
    expect(starts(sameRun)).toHaveLength(0);
    const newRun = liveRows([event("run-a", 0), gap("r1"), event("run-b", 0)]);
    expect(starts(newRun)).toHaveLength(0);
    // Derivation restarts from the frames after the refill.
    const later = liveRows([event("run-a", 0), gap("r1"), event("run-b", 0), event("run-c", 0)]);
    expect(starts(later).map((row) => row.runId)).toEqual(["run-c"]);
  });

  it("keeps the echo's license across a break — the Send is a held fact, not a comparison", () => {
    const rows = liveRows([echo("echo:0", "p"), gap("r1"), event("run-a", 0)]);
    expect(names(rows)).toEqual(["local-prompt", "resync", "run-start", "text"]);
  });

  it("mints no presentation row from history — reopen restores recorded prompts (C3)", () => {
    const rows = historicalRows(historyItems(), [{ seq: 0, text: "Add a 2 mm chamfer." }]);
    expect(rows.some((row) => row.row === "local-prompt" || row.row === "run-start")).toBe(false);
    expect(rows[0]?.row).toBe("user-prompt");
  });

  it("keeps every presentation row out of the history prefix and off the seam (C3)", () => {
    const rows = panelRows(historyItems(), [echo("echo:0", "p"), event("run-a", 0)]);
    const seamAt = rows.findIndex((row) => row.row === "seam");
    expect(seamAt).toBeGreaterThan(-1);
    const prefix = rows.slice(0, seamAt);
    expect(prefix.some((row) => row.row === "local-prompt" || row.row === "run-start")).toBe(false);
    // The first live row after the seam is the echo, then its licensed boundary.
    expect(names(rows.slice(seamAt + 1, seamAt + 3))).toEqual(["local-prompt", "run-start"]);
  });

  it("carries no event id on either presentation row, and loses none to them", () => {
    const entries = [echo("echo:0", "p"), event("run-a", 0), event("run-b", 0)];
    const rows = liveRows(entries);
    for (const row of rows) {
      if (row.row === "local-prompt" || row.row === "run-start") {
        expect("items" in row || "item" in row || "call" in row).toBe(false);
      }
    }
    // The §7.2 id-set discipline: every event's id survives into some row.
    const ids = new Set<string>();
    for (const row of rows) {
      if (row.row === "text") for (const item of row.items) ids.add(item.eventId);
    }
    expect(ids).toEqual(new Set(["run-a#0", "run-b#0"]));
  });
});
