// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Build the *bounded sidecar artifact* the Python wheel ships
// (`repo_conventions.md` §Naming and packaging).
//
// `pnpm build` (plain `tsc`) emits `dist/`, which is NOT self-contained: Node
// resolves four bare specifiers by walking up to `agent/node_modules`. A
// production-only closure of that tree measures 202 MB / 24,480 files and drags
// in three Linux `.node` addons that the sidecar never loads — an unacceptable
// wheel payload and an audit surface we would have to defend per platform.
//
// This bundler collapses both entry points into a self-contained ESM tree with
// shared chunks: ~14 MB, ~44 files, zero `.node` files. The only unresolved
// bare specifiers are `bufferutil` and `utf-8-validate`, ws's optional native
// accelerators, both loaded inside try/catch and absent by design.
//
// The output is deliberately NOT minified: stack traces from the sidecar are
// operator-facing, and the wheel compresses the bytes anyway.

import { rm, mkdir, writeFile, copyFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";
import { build } from "esbuild";

const agentDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(agentDir, "build", "sidecar");

/** Entry points the Python supervisor spawns, keyed by the name it asks for. */
export const ENTRYPOINTS = {
  main: "main.js",
  runner: "workflows/runner.js",
};

/**
 * Bare specifiers the bundle is permitted to leave unresolved.
 *
 * Both are ws's optional native accelerators, required inside a try/catch and
 * intentionally absent: leaving them external is what keeps the sidecar free of
 * a *required* native addon. Anything else escaping the bundle is a defect —
 * `verify_bundle.mjs` fails the build on it.
 */
export const ALLOWED_EXTERNALS = ["bufferutil", "utf-8-validate"];

async function main() {
  await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });

  const result = await build({
    absWorkingDir: agentDir,
    entryPoints: [join(agentDir, "src", "main.ts"), join(agentDir, "src", "workflows", "runner.ts")],
    outbase: join(agentDir, "src"),
    outdir: outDir,
    bundle: true,
    splitting: true,
    format: "esm",
    platform: "node",
    target: "node22",
    // Optional ws accelerators; see ALLOWED_EXTERNALS.
    external: ALLOWED_EXTERNALS,
    metafile: true,
    logLevel: "warning",
    sourcemap: false,
    minify: false,
    // ESM output has no `require`, but several transitive CJS dependencies
    // (cross-spawn, graceful-fs, ws's optional accelerators) call it — esbuild
    // emits a shim that throws "Dynamic require of X is not supported" unless a
    // real `require` is in scope. Re-create one per output file from
    // `import.meta.url`; esbuild's shim prefers it over throwing. The alias is
    // deliberately obscure: the banner is raw text, so a plain `createRequire`
    // import could collide with esbuild's own renamed imports in a chunk.
    banner: {
      js: [
        'import { createRequire as __hephCreateRequire } from "node:module";',
        "const require = __hephCreateRequire(import.meta.url);",
      ].join("\n"),
    },
  });

  // `schemas/bridge_limits.json` is data the sidecar reads at startup, not a
  // module it imports, so the bundler cannot inline it. Copy it beside the entry
  // point where `limits.ts`'s second candidate finds it. It lands inside the
  // staged tree, so the integrity manifest covers it — the bridge's bounds
  // cannot be widened by editing a file in site-packages.
  await mkdir(join(outDir, "schemas"), { recursive: true });
  await copyFile(
    join(agentDir, "..", "schemas", "bridge_limits.json"),
    join(outDir, "schemas", "bridge_limits.json"),
  );

  await writeFile(join(outDir, "meta.json"), JSON.stringify(result.metafile, null, 2));
  process.stdout.write(`sidecar bundled -> ${outDir}\n`);
}

await main();
