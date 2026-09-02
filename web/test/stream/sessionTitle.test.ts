// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Session tabs are conversations, not keys (#51, #62, #66).

import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../../src/copy";
import type { SessionRow } from "../../src/api/sessions";
import type { ThreadTab } from "../../src/stream/thread";
import { sessionPromptStore } from "../../src/stream/sessionPrompts";
import {
  SESSION_LABEL_MAX,
  applySessionDocumentTitle,
  defaultDocumentTitle,
  holderSessionTitle,
  isSessionRoot,
  sessionDocumentTitle,
  sessionLabel,
  sessionTabMeta,
  sessionTitleAttr,
  titleForSession,
} from "../../src/stream/sessionTitle";

const UUID = "dd5ec5c0-1111-4111-8111-000000000001";
const OTHER = "1cb16a1c-2222-4222-8222-000000000002";

function tab(over: Partial<ThreadTab> = {}): ThreadTab {
  return {
    session_id: UUID,
    parent_session_id: null,
    kind: null,
    depth: 0,
    thread_state: "unlinked",
    origin: {},
    created_at: null,
    ...over,
  };
}

function row(over: Partial<SessionRow> = {}): SessionRow {
  return {
    session_id: UUID,
    profile: "orchestrator",
    part: null,
    parent_session_id: null,
    thread_state: "unlinked",
    ...over,
  };
}

afterEach(() => {
  sessionPromptStore.reset();
  applySessionDocumentTitle(null);
});

describe("session tab labels are human (#51)", () => {
  it("never uses the UUID as the visible label", () => {
    // §7.1 C6: with no server fact at all, the fallback is still a noun
    // phrase, never the create affordance's wording.
    expect(sessionLabel({ sessionId: UUID })).toBe(copy.stream.projectSession);
    expect(sessionLabel({ sessionId: UUID })).not.toContain("dd5ec5c0");
    expect(sessionLabel({ sessionId: OTHER, firstPrompt: OTHER })).toBe(
      copy.stream.projectSession,
    );
  });

  it("clips a long first prompt instead of falling back to the id", () => {
    const prompt =
      "Create a new laser-cut part named kerf_coupon with slots to measure kerf compensation across the sheet.";
    const label = sessionLabel({ sessionId: UUID, firstPrompt: prompt });
    expect(label.length).toBeLessThanOrEqual(SESSION_LABEL_MAX);
    expect(label.endsWith("…")).toBe(true);
    expect(label).toContain("kerf_coupon");
    expect(label).not.toContain(UUID);
    expect(label).not.toBe(UUID.slice(0, 8));
  });

  it("wires a remembered prompt into titleForSession for the in-flight holder", () => {
    const title = titleForSession(
      UUID,
      [row()],
      [tab()],
      undefined,
      "Create a new laser-cut part named kerf_coupon…",
    );
    expect(title).toContain("kerf_coupon");
    expect(title).not.toBe(UUID);
  });

  it("rejects a holder title that is still the session id (#66)", () => {
    // §7.1 C6: the holder fallback is a noun phrase, not a create-control label.
    expect(holderSessionTitle(UUID, UUID)).toBe(copy.stream.projectSession);
    expect(holderSessionTitle(UUID, "tread · quick edit")).toBe("tread · quick edit");
  });

  it("keeps the browser tab title off the raw id", () => {
    expect(sessionDocumentTitle("Create a new laser-cut part named kerf_coupon")).not.toContain(
      UUID,
    );
    applySessionDocumentTitle("Create a new laser-cut part named kerf_coupon");
    expect(document.title).not.toBe(UUID);
    expect(document.title).toContain("kerf_coupon");
    applySessionDocumentTitle(null);
    expect(document.title).toBe(defaultDocumentTitle());
  });

  it("prefers the first prompt line, then a server-fact noun phrase (§7.1 C6)", () => {
    expect(
      sessionLabel({
        sessionId: UUID,
        firstPrompt: "Widen the kerf.\nAnd rebuild.",
        part: "kerf_card",
      }),
    ).toBe("Widen the kerf.");
    // Part form: the part's name with the session kind — never `Ask about …`.
    expect(sessionLabel({ sessionId: UUID, part: "kerf_card", profile: "part" })).toBe(
      `kerf_card · ${copy.stream.profile.part}`,
    );
    expect(sessionLabel({ sessionId: UUID, origin: { part: "tread" }, kind: "quick_edit" })).toBe(
      `tread · ${copy.stream.tabKind.quick_edit}`,
    );
    // With neither kind nor profile served, the part name stands alone rather
    // than borrowing a word the server never said.
    expect(sessionLabel({ sessionId: UUID, part: "kerf_card" })).toBe("kerf_card");
  });

  it("titles an untitled session by profile word plus created hh:mm (§7.1 C6)", () => {
    const created = Date.UTC(2026, 8, 1, 12, 0, 0) / 1000;
    const label = sessionLabel({
      sessionId: UUID,
      profile: "orchestrator",
      createdAt: created,
    });
    expect(label.startsWith(`${copy.stream.profile.orchestrator} · `)).toBe(true);
    expect(label).toMatch(/ · \d{2}:\d{2}$/);
    expect(label).not.toContain(UUID);
    // Without a created time the profile word stands alone.
    expect(sessionLabel({ sessionId: UUID, profile: "orchestrator" })).toBe(
      copy.stream.profile.orchestrator,
    );
  });

  it("never titles any tab with a create-control label (§7.1 C6, both sides)", () => {
    // The testable, run over every fixture shape the label function can see:
    // no fallback title is string-equal to any create affordance's wording.
    const createLabels = [
      copy.composer.createOrchestrator,
      copy.composer.createPart("kerf_card"),
      copy.composer.createPart("tread"),
      copy.stream.createMenu,
    ];
    const fixtures = [
      sessionLabel({ sessionId: UUID }),
      sessionLabel({ sessionId: UUID, profile: "orchestrator" }),
      sessionLabel({ sessionId: UUID, profile: "orchestrator", createdAt: 1_756_728_000 }),
      sessionLabel({ sessionId: UUID, part: "kerf_card" }),
      sessionLabel({ sessionId: UUID, part: "kerf_card", profile: "part" }),
      sessionLabel({ sessionId: UUID, part: "tread", kind: "quick_edit" }),
      sessionLabel({ sessionId: UUID, part: "tread", kind: "delegation" }),
      sessionLabel({ sessionId: UUID, profile: "quick_edit", part: "tread" }),
      holderSessionTitle(UUID, UUID),
      holderSessionTitle(UUID, null),
    ];
    for (const label of fixtures) {
      for (const forbidden of createLabels) {
        expect(label).not.toBe(forbidden);
      }
      // And the positive half: it is a non-empty noun phrase, not a UUID.
      expect(label).not.toBe("");
      expect(label).not.toContain(UUID);
    }
    // The quick-edit child's fallback follows the part form — a distinct
    // string from the `+` menu entry that spawns one (rule 3).
    expect(sessionLabel({ sessionId: UUID, part: "tread", kind: "quick_edit" })).not.toBe(
      copy.composer.createPart("tread"),
    );
  });

  it("remembers only the first prompt this page sent", () => {
    sessionPromptStore.remember(UUID, "Create a new laser-cut part named kerf_coupon…");
    sessionPromptStore.remember(UUID, "Now add mounting holes.");
    expect(sessionPromptStore.getSnapshot()[UUID]).toContain("kerf_coupon");
    expect(sessionPromptStore.getSnapshot()[UUID] ?? "").not.toContain("mounting");
  });

  it("keeps the UUID on title / tooltip", () => {
    expect(sessionTitleAttr(UUID, "linked")).toBe(UUID);
    expect(sessionTitleAttr(UUID, "unlinked")).toContain(UUID);
    expect(sessionTitleAttr(UUID, "unlinked")).toContain("cannot be recovered");
  });
});

describe("a root tab does not say no parent (#62, #66)", () => {
  it("treats depth-0 with no parent as a root", () => {
    expect(isSessionRoot(tab())).toBe(true);
    expect(isSessionRoot(tab({ parent_session_id: UUID, depth: 1 }))).toBe(false);
  });

  it("subtitles an orchestrator root as a project session", () => {
    const meta = sessionTabMeta(tab(), row());
    expect(meta).toBe(copy.stream.projectSession);
    expect(meta).not.toMatch(/no parent/i);
  });

  it("looks up a human title for the in-flight holder, not the raw id", () => {
    const title = titleForSession(UUID, [row({ part: "kerf_card", profile: "part" })], [tab()]);
    expect(title).toBe(`kerf_card · ${copy.stream.profile.part}`);
    expect(title).not.toBe(UUID);
  });
});
