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
    expect(sessionLabel({ sessionId: UUID })).toBe(copy.composer.createOrchestrator);
    expect(sessionLabel({ sessionId: UUID })).not.toContain("dd5ec5c0");
    expect(sessionLabel({ sessionId: OTHER, firstPrompt: OTHER })).toBe(
      copy.composer.createOrchestrator,
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
    expect(holderSessionTitle(UUID, UUID)).toBe(copy.composer.createOrchestrator);
    expect(holderSessionTitle(UUID, "Ask about kerf_coupon")).toBe("Ask about kerf_coupon");
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

  it("prefers the first prompt line, then the bound part, then New session", () => {
    expect(
      sessionLabel({
        sessionId: UUID,
        firstPrompt: "Widen the kerf.\nAnd rebuild.",
        part: "kerf_card",
      }),
    ).toBe("Widen the kerf.");
    expect(sessionLabel({ sessionId: UUID, part: "kerf_card" })).toBe(
      copy.composer.createPart("kerf_card"),
    );
    expect(sessionLabel({ sessionId: UUID, origin: { part: "tread" } })).toBe(
      copy.composer.createPart("tread"),
    );
  });

  it("adds a relative time to an untitled orchestrator when the edge has one", () => {
    const now = new Date("2026-09-01T15:00:00Z");
    const created = Date.UTC(2026, 8, 1, 12, 0, 0) / 1000;
    const label = sessionLabel({ sessionId: UUID, createdAt: created, now });
    expect(label.startsWith(`${copy.composer.createOrchestrator} · `)).toBe(true);
    expect(label).not.toContain(UUID);
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
    expect(title).toBe(copy.composer.createPart("kerf_card"));
    expect(title).not.toBe(UUID);
  });
});
