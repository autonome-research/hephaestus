// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Loading the recorded normalized-event fixture (see
// `web/test/fixtures/record-normalized-events.mjs` for how it is produced and
// why it is recorded rather than written).

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { EventFrame } from "../../src/api/events";
import type { HistoryPageDocument } from "../../src/api/sessions";

const here = dirname(fileURLToPath(import.meta.url));

export interface RecordedFixture {
  readonly provenance: Readonly<Record<string, unknown>>;
  readonly session_id: string;
  readonly child_session_id: string;
  readonly run_id: string;
  readonly pages: readonly HistoryPageDocument[];
  readonly child_page: HistoryPageDocument;
  readonly live_frames: readonly EventFrame[];
}

export const fixture: RecordedFixture = JSON.parse(
  readFileSync(join(here, "..", "fixtures", "normalized-events.json"), "utf8"),
) as RecordedFixture;

/** The repository root, for reading the generated tool schemas. */
export const repoRoot = join(here, "..", "..", "..");

/** Every historical event of the recorded session, in page order. */
export function allHistoryFrames(): readonly HistoryPageDocument["events"][number][] {
  return fixture.pages.flatMap((page) => [...page.events]);
}
