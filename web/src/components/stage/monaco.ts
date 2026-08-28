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
// Only Python is registered, and only the base editor worker is provided —
// the CSS/JSON/HTML/TypeScript language workers serve languages that never
// appear here and would be weight in the wheel §3 ships.

import * as monaco from "monaco-editor/editor";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

import "monaco-editor/languages/definitions/python/register";

declare global {
  interface Window {
    MonacoEnvironment?: { getWorker: (workerId: string, label: string) => Worker };
  }
}

let installed = false;

/** Register the worker factory and the workspace theme. Idempotent. */
export function installMonaco(): typeof monaco {
  if (installed) return monaco;
  installed = true;

  window.MonacoEnvironment = {
    getWorker: () => new EditorWorker(),
  };

  // The theme takes literal colours, so it is derived from the design tokens by
  // hand rather than read out of CSS at runtime: reading a custom property here
  // would make the editor's palette depend on stylesheet load order.
  monaco.editor.defineTheme("hephaestus", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "5d6675", fontStyle: "italic" },
      { token: "string", foreground: "9ad1a8" },
      { token: "number", foreground: "e2b23c" },
      { token: "keyword", foreground: "4ea3f0" },
    ],
    colors: {
      "editor.background": "#0d0f12",
      "editor.foreground": "#eef1f6",
      "editorLineNumber.foreground": "#3b4350",
      "editorLineNumber.activeForeground": "#868f9f",
      "editor.lineHighlightBackground": "#14171c",
      "editorGutter.background": "#0d0f12",
    },
  });

  return monaco;
}
