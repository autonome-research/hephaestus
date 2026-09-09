// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Give every test process an agent dir of its own, before any test imports
 * `src/main.ts`.
 *
 * `src/main.ts` reads `HEPHAESTUS_AGENT_DIR` once, at module load, and falls
 * back to `process.cwd()`. Under vitest the working directory is this package,
 * so a test that built a runtime without naming an agent dir made the CHECKOUT
 * the sidecar's credential home: Pi writes an empty `auth.json` placeholder
 * there on first run, and `agent/auth.json` (mode 0600) appeared in `git
 * status` after a plain `pnpm test`. Harmless in itself — the placeholder holds
 * `{}` — but it is a credential path pointed at a source tree, and the next
 * thing written there would not be a placeholder.
 *
 * Setting it here rather than per test is the point: the leak came from
 * omission, so the default has to be safe rather than each caller having to
 * remember. A test that wants its own directory still passes one explicitly.
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

process.env.HEPHAESTUS_AGENT_DIR ??= mkdtempSync(
  path.join(tmpdir(), "heph-agent-test-"),
);
