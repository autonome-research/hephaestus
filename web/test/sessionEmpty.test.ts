// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Empty-session copy: the blank-canvas sentence is true only when the project
// has no parts (INTERFACE.md §7A.2). A selected part with "There is no part
// yet" is a lie.

import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { copy } from "../src/copy";
import { sessionEmptyBody, sessionEmptyKind } from "../src/stream/sessionEmpty";
import { sessionCannotPrompt } from "../src/stream/sessionPromptGate";

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

// ---------------------------------------------------------------------------
// §7.1(c) — the one-character filename confusion, repaired
//
// `stream/sessionPrompt.ts` (the gate) and `stream/sessionPrompts.ts` (the
// remembered-first-line store) differed by a trailing `s` and were imported
// side by side in `StreamPanel.tsx`. The gate is now `sessionPromptGate.ts`.
// The rename is mechanical — `sessionCannotPrompt` is imported above under the
// new path, unchanged — so the test worth having is the RULE, not the pair:
// a build in which two modules under `stream/` differ only by a trailing `s`
// fails this clause, whatever they are called.

describe("§7.1(c) — no two stream modules differ only by a trailing s", () => {
  it("finds no such pair", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const names = readdirSync(join(here, "../src/stream"))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => name.slice(0, -".ts".length));
    const set = new Set(names);
    for (const name of names) {
      expect(
        name.endsWith("s") && set.has(name.slice(0, -1)),
        `stream/${name}.ts and stream/${name.slice(0, -1)}.ts differ only by a trailing s`,
      ).toBe(false);
    }
    // …and the rename itself landed.
    expect(set.has("sessionPromptGate")).toBe(true);
    expect(set.has("sessionPrompt")).toBe(false);
    expect(set.has("sessionPrompts")).toBe(true);
  });
});
