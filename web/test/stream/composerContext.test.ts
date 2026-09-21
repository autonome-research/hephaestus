// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §7A.3's context envelope, tested AT THE MODULE (2026-09-20).
//
// WHY THIS FILE EXISTS. The envelope's semantics — which members are offered,
// which survive a drop, what the summary publishes — had no direct coverage.
// Every one of them was asserted through the composer's DOM: mount the form,
// click the disclosure, read the chips. That worked while the disclosure was
// on screen.
//
// The context READOUT was struck from the composer on request; the envelope it
// described is unchanged and still sent with every turn. Deleting the DOM
// tests would therefore have dropped the coverage of the half that survived,
// which is the wrong half to lose. The assertions moved here instead, to the
// functions the composer calls, where they do not depend on a control being
// drawn.
//
// What is NOT here, because it went with the UI: the chips' markup, the
// disclosure's expanded state, and `[data-context-summary]`'s attributes.

import { describe, expect, it } from "vitest";
import {
  CHIP_ORDER,
  SUMMARY_ORDER,
  chipsFor,
  envelopeFor,
  summaryFor,
} from "../../src/stream/composerContext";
import type { ContextMember } from "../../src/api/sessions";
import { DEFAULT_STATE, type WorkspaceState } from "../../src/state/workspace";

const REF = "artifact:build:sha256:d266f257c390143eca85ca60eae63829a02cc0d3a3360daa3668e118132b69a5";

function state(over: Partial<WorkspaceState> = {}): WorkspaceState {
  return { ...DEFAULT_STATE, ...over };
}

function envelope(over: Partial<WorkspaceState> = {}, dropped: ContextMember[] = []) {
  return envelopeFor(state(over), [], new Set(dropped));
}

describe("chipsFor — what the workspace OFFERS the turn (§7A.3(c))", () => {
  it("always offers where the operator IS, even with nothing selected", () => {
    // The navigation members are unconditional: a turn sent from an empty
    // workspace still happened somewhere, and "which view was open" is a fact
    // about the question being asked. Only the SELECTION-shaped members
    // (part, artifact, selection) depend on there being something selected.
    const keys = chipsFor(state(), []).map((chip) => chip.key);
    expect(keys).toContain("stage_tab");
    expect(keys).not.toContain("part");
    expect(keys).not.toContain("artifact_ref");
    expect(keys).not.toContain("selection");
  });

  it("offers the open part, and carries its value", () => {
    const chips = chipsFor(state({ part: "kerf_card" }), []);
    expect(chips.map((chip) => chip.key)).toContain("part");
    expect(chips.find((chip) => chip.key === "part")?.value).toBe("kerf_card");
  });

  it("offers the pinned artifact with its ref verbatim, never abbreviated here", () => {
    // Abbreviation is a rendering; this module is the decision. A chip that
    // carried `build: d266f257` would make the envelope lossy.
    const chips = chipsFor(state({ artifact_ref: REF }), []);
    expect(chips.find((chip) => chip.key === "artifact_ref")?.value).toBe(REF);
  });

  it("keeps CHIP_ORDER's order, so the offer does not reshuffle between reads", () => {
    const chips = chipsFor(state({ part: "kerf_card", artifact_ref: REF }), []);
    const order = chips.map((chip) => chip.key);
    const expected = CHIP_ORDER.filter((key) => order.includes(key));
    expect(order).toEqual([...expected]);
  });
});

describe("envelopeFor — what the turn actually CARRIES", () => {
  it("is null on a blank canvas, though navigation members were offered", () => {
    // The asymmetry is deliberate and worth pinning: `chipsFor` OFFERS the
    // navigation members unconditionally, but the envelope is withheld unless
    // it NAMES A REFERENCE — a part, an artifact, a selection, or a view the
    // operator explicitly added. "Which tab was open" is not a reference, so
    // a turn from an empty workspace carries no context at all rather than
    // context that points at nothing.
    expect(chipsFor(state(), []).map((chip) => chip.key)).toContain("stage_tab");
    expect(envelope()).toBeNull();
  });

  it("carries the navigation members once something else names a reference", () => {
    const built = envelope({ part: "kerf_card" });
    expect(built?.part).toBe("kerf_card");
    expect(built?.stage_tab).toBe(DEFAULT_STATE.stage_tab);
  });

  it("carries the open part", () => {
    expect(envelope({ part: "kerf_card" })?.part).toBe("kerf_card");
  });

  it("sends pin_mode WITH the ref it qualifies, never alone", () => {
    const withRef = envelope({ artifact_ref: REF, pin_mode: "pinned" });
    expect(withRef?.artifact_ref).toBe(REF);
    expect(withRef?.pin_mode).toBe("pinned");
    // Drop the ref and the qualifier goes with it — a pin mode describing no
    // ref is a fact about nothing.
    const dropped = envelope({ artifact_ref: REF, pin_mode: "pinned" }, ["artifact_ref"]);
    expect(dropped?.artifact_ref).toBeUndefined();
    expect(dropped?.pin_mode).toBeUndefined();
  });

  it("omits a dropped member and keeps the rest", () => {
    const kept = envelope({ part: "kerf_card", artifact_ref: REF }, ["part"]);
    expect(kept?.part).toBeUndefined();
    expect(kept?.artifact_ref).toBe(REF);
  });

  it("is null only once EVERY offered member is dropped", () => {
    const all = chipsFor(state({ part: "kerf_card" }), []).map((chip) => chip.key);
    expect(envelopeFor(state({ part: "kerf_card" }), [], new Set(all))).toBeNull();
  });
});

describe("summaryFor — §7A.3(d): the published keys ARE the envelope's keys", () => {
  it("publishes exactly the members the envelope carries, in SUMMARY_ORDER", () => {
    const state_ = state({ part: "kerf_card", artifact_ref: REF });
    const built = envelopeFor(state_, [], new Set());
    const summary = summaryFor(built, chipsFor(state_, []), new Set());
    // The testable §7A.3(d) states: nothing is published that is not carried.
    for (const key of summary.keys) expect(built?.[key]).not.toBeUndefined();
    const expected = SUMMARY_ORDER.filter((key) => built?.[key] !== undefined);
    expect([...summary.keys]).toEqual([...expected]);
  });

  it("publishes no keys for an empty envelope", () => {
    expect(summaryFor(null, [], new Set()).keys).toEqual([]);
  });

  it("drops a member from the published keys when it is dropped from the envelope", () => {
    const state_ = state({ part: "kerf_card" });
    const dropped = new Set<ContextMember>(["part"]);
    const built = envelopeFor(state_, [], dropped);
    const summary = summaryFor(built, chipsFor(state_, []), dropped);
    expect(summary.keys).not.toContain("part");
  });
});
