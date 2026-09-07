// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-stream-12's mechanical check, scoped to this lane's files.
//
// The ledger's fix asks for a REPOSITORY-level scanner wired into CI beside the
// linters (`repo_conventions.md`, `CONTRIBUTING.md`) — that scanner is not this
// lane's file to write (it lives under `scripts/` and CI config, owned by other
// lanes of this ledger). What belongs here is the guard for `web/`'s own
// tracked sources, so this lane's tree cannot regress the exact class this item
// names while the repo-wide check is landed elsewhere: a raw NUL byte (or any
// other control character besides tab and newline) in a tracked `.ts`/`.tsx`
// file is invisible in every editor and diff and makes the file binary to
// `grep`, which is precisely what made J-web-stream-12 possible in the first
// place — undetectable by reading, by review, and by the tool one would use to
// look for it.

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "..");

/** Every `.ts`/`.tsx` file `git` tracks under `web/src` and `web/test`. */
function trackedSources(): string[] {
  const out = execFileSync(
    "git",
    ["ls-files", "--", "src/**/*.ts", "src/**/*.tsx", "test/**/*.ts", "test/**/*.tsx"],
    { cwd: webRoot, encoding: "utf8" },
  );
  return out
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** A control character other than tab (0x09) and newline (0x0A). CR is flagged too. */
// eslint-disable-next-line no-control-regex -- the whole point is to find one.
const STRAY_CONTROL = /[\x00-\x08\x0b\x0c\x0e-\x1f]/u;

describe("no stray control character in a tracked web source (J-web-stream-12)", () => {
  const files = trackedSources();

  it("finds at least one tracked file, so the guard is not silently vacuous", () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it.each(files)("%s carries no control byte other than tab/newline", (relative) => {
    const bytes = readFileSync(join(webRoot, relative));
    const text = bytes.toString("utf8");
    const match = STRAY_CONTROL.exec(text);
    if (match !== null) {
      const before = text.slice(0, match.index);
      const line = before.split("\n").length;
      expect.fail(
        `${relative}:${String(line)} contains control byte 0x${match[0]
          .charCodeAt(0)
          .toString(16)
          .padStart(2, "0")} — invisible in an editor/diff and binary to grep`,
      );
    }
  });
});
