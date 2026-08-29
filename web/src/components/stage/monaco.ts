// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Monaco, set up once for the whole app.
//
// INTERFACE.md §3 pins **Monaco** for script and diff and rejects any component
// or icon library, so Monaco is imported directly rather than through a React
// wrapper package: a wrapper's only output here would be the `useEffect` in
// `ScriptEditor`.
//
// Monaco is bundled, never loaded from a CDN. `architecture.md` §7 is a loopback
// posture with no network story, §3 ships the built assets inside the wheel, and
// an editor that silently needed the internet would fail at the moment a human
// opens a script on a disconnected machine.
//
// IMPORT SPELLING, because it is version-specific and easy to get wrong.
// `monaco-editor@0.56`'s `exports` map is `"./*": "./esm/vs/*.js"`, so a subpath
// is written *without* the `esm/vs` prefix:
//
//   monaco-editor/editor                              → esm/vs/editor.js
//   monaco-editor/editor/editor.worker                → esm/vs/editor/editor.worker.js
//   monaco-editor/languages/definitions/python/register
//
// The bare `monaco-editor` entry point is deliberately NOT used: its index
// registers **every** bundled language, and this workspace opens exactly one.
//
// THE THEME NOW READS THE TOKENS (§3.6, §3.14's `no-palette-token`). It used to
// carry ten literal hex values with a comment explaining that reading custom
// properties "would make the editor's palette depend on stylesheet load order".
// That trade is no longer available — a literal hex outside `system/tokens.css`
// is a lint failure, and the ten literals had in fact already drifted: the
// comment colour was `#5d6675`, the 3.10:1 ink §3.9 retires by name.
//
// The load-order worry is answered rather than ignored: `installMonaco` runs
// from a `useEffect`, after the stylesheet is applied, and if a token still
// resolves EMPTY the theme simply omits that colour and inherits `vs-dark`.
// Inheriting a base theme is honest; a hard-coded copy of the tokens that
// silently disagrees with them is what this replaces.

import * as monaco from "monaco-editor/editor";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

import "monaco-editor/languages/definitions/python/register";

declare global {
  interface Window {
    MonacoEnvironment?: { getWorker: (workerId: string, label: string) => Worker };
  }
}

let installed = false;

/** A design token's computed value, or `null` when the sheet has not applied. */
function token(name: string): string | null {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value === "" ? null : value;
}

/** Monaco's `rules` want a bare `rrggbb`; the tokens carry a leading `#`. */
function bare(value: string | null): string | null {
  return value === null ? null : value.replace("#", "");
}

/** Drop the entries whose token did not resolve, so `vs-dark` fills the gap. */
function defined<T extends string>(
  entries: readonly (readonly [T, string | null])[],
): Record<T, string> {
  const out: Partial<Record<T, string>> = {};
  for (const [key, value] of entries) if (value !== null) out[key] = value;
  return out as Record<T, string>;
}

/** Register the worker factory and the workspace theme. Idempotent. */
export function installMonaco(): typeof monaco {
  if (installed) return monaco;
  installed = true;

  window.MonacoEnvironment = {
    getWorker: () => new EditorWorker(),
  };

  const rules: monaco.editor.ITokenThemeRule[] = [];
  const rule = (name: string, property: string, italic = false): void => {
    const foreground = bare(token(property));
    if (foreground === null) return;
    rules.push(italic ? { token: name, foreground, fontStyle: "italic" } : { token: name, foreground });
  };
  rule("comment", "--code-comment", true);
  rule("string", "--code-string");
  rule("number", "--code-number");
  rule("keyword", "--code-keyword");

  // §3.10's surface assignment: the Script tab lives on the STAGE, so its ground
  // is `app` — `canvas` is the viewport's and nothing else's.
  monaco.editor.defineTheme("hephaestus", {
    base: "vs-dark",
    inherit: true,
    rules,
    colors: defined([
      ["editor.background", token("--surface-app")],
      ["editor.foreground", token("--ink-strong")],
      ["editorLineNumber.foreground", token("--ink-faint")],
      ["editorLineNumber.activeForeground", token("--ink-muted")],
      ["editor.lineHighlightBackground", token("--surface-panel")],
      ["editorGutter.background", token("--surface-app")],
    ]),
  });

  return monaco;
}
