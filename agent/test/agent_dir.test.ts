// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The suite may not use the checkout as the sidecar's credential home.
 *
 * Regression pin for the leak `test/setup.ts` closes: a plain `pnpm test` left
 * an `auth.json` (mode 0600) in this package, because `src/main.ts`'s agent dir
 * falls back to `process.cwd()` and Pi writes its placeholder there on first
 * run. Asserting the ENV rather than the absence of the file is what makes this
 * hold for a test nobody has written yet.
 */

import path from "node:path";
import { describe, expect, it } from "vitest";

describe("the sidecar's agent dir under test", () => {
  it("is set, and is not inside this package", () => {
    const agentDir = process.env.HEPHAESTUS_AGENT_DIR;
    expect(agentDir, "test/setup.ts must set HEPHAESTUS_AGENT_DIR").toBeTruthy();
    const resolved = path.resolve(agentDir!);
    const pkg = path.resolve(process.cwd());
    expect(resolved).not.toBe(pkg);
    expect(resolved.startsWith(pkg + path.sep)).toBe(false);
  });
});
