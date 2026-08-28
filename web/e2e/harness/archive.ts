// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// G4.12: "Screenshot artifacts archived."
//
// §16's row for that clause is one sentence long and both halves matter:
// "Playwright artifact retention; **screenshots never an assertion**". So this
// helper attaches bytes and returns nothing comparable. There is no golden, no
// baseline, no threshold and no image diff anywhere in this suite — §5.3 refuses
// to create a browser-golden family, and §14 repeats that screenshots "are
// **never** compared against a golden". They are evidence a human reads after a
// failure; the pass/fail signal is always the scripted assertion beside them.
//
// The one place this suite reads browser pixels at all is G4.5's before/after
// delta inside a decoded solid-pass mask, which compares two frames from the
// same rasterizer in the same run and stores nothing (§5.4).

import type { Page, TestInfo } from "@playwright/test";

/** Attach a named screenshot to the run's artifacts. Never asserted. */
export async function archive(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await testInfo.attach(name, {
    body: await page.screenshot({ fullPage: false }),
    contentType: "image/png",
  });
}
