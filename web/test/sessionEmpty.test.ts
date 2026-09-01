// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Empty-session copy: the blank-canvas sentence is true only when the project
// has no parts (INTERFACE.md §7A.2). A selected part with "There is no part
// yet" is a lie.

import { describe, expect, it } from "vitest";
import { copy } from "../src/copy";
import { sessionEmptyBody, sessionEmptyKind } from "../src/stream/sessionEmpty";
import { sessionCannotPrompt } from "../src/stream/sessionPrompt";

describe("session empty-state copy — honest about parts", () => {
  it("claims there is no part only when the project has none", () => {
    expect(sessionEmptyKind(0)).toBe("no_part");
    expect(sessionEmptyBody(0, null)).toBe(copy.composer.blankCanvas);
    expect(sessionEmptyBody(0, "shelf")).toBe(copy.composer.blankCanvas);
  });

  it("does not say there is no part when a part is selected", () => {
    expect(sessionEmptyKind(3)).toBe("no_session");
    const body = sessionEmptyBody(3, "shelf");
    expect(body).toBe(copy.composer.noSessionSelectedPart("shelf"));
    expect(body).not.toContain("There is no part yet");
    expect(body).toContain("shelf");
  });

  it("does not say there is no part while parts exist but none is selected", () => {
    expect(sessionEmptyKind(2)).toBe("no_session");
    const body = sessionEmptyBody(2, null);
    expect(body).toBe(copy.composer.noSessionHasParts);
    expect(body).not.toContain("There is no part yet");
  });

  it("does not guess a blank canvas while GET /parts is in flight", () => {
    expect(sessionEmptyKind(undefined)).toBe("no_session");
    expect(sessionEmptyBody(undefined, null)).toBe(copy.stream.noSessions);
    expect(sessionEmptyBody(undefined, "shelf")).toBe(copy.composer.noSessionSelectedPart("shelf"));
    expect(sessionEmptyBody(undefined, "shelf")).not.toContain("There is no part yet");
  });
});

describe("the current tab cannot take a prompt (#43)", () => {
  it("is true for a runtime fault, unknown_session, or unread history", () => {
    expect(
      sessionCannotPrompt({ runtimeFault: "unreachable", historyFailed: false, streamReason: null }),
    ).toBe(true);
    expect(
      sessionCannotPrompt({
        runtimeFault: null,
        historyFailed: false,
        streamReason: "unknown_session",
      }),
    ).toBe(true);
    expect(
      sessionCannotPrompt({ runtimeFault: null, historyFailed: true, streamReason: null }),
    ).toBe(true);
  });

  it("is false for a healthy tab, and does not steal §7A.8's refusal", () => {
    expect(
      sessionCannotPrompt({ runtimeFault: null, historyFailed: false, streamReason: null }),
    ).toBe(false);
    expect(
      sessionCannotPrompt({
        runtimeFault: null,
        historyFailed: false,
        streamReason: "agent_unavailable",
      }),
    ).toBe(false);
  });
});
