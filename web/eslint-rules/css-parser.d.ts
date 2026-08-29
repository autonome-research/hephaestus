// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `css-parser.js`, typed for the one consumer that imports it from TypeScript.
// It yields an EMPTY `Program` spanning the stylesheet, so the four design
// checks read `sourceCode.text` and every inherited JS rule finds nothing to
// say — see the module's own header for why that is the honest shape.

export declare function parseForESLint(text: string): {
  ast: unknown;
  visitorKeys: Record<string, string[]>;
};

declare const parser: { parseForESLint: typeof parseForESLint };
export default parser;
