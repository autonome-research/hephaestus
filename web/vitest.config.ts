// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Unit tests for the parts of the client that are not pixels: the workspace
// state module and its URL serialization (INTERFACE.md §4.5), and the inspector
// panels asserted field-for-field against **recorded** response documents
// (§6, `test/fixtures/`). Everything the gate asserts about a *live* DOM is
// Playwright's job (`pnpm test:e2e`, §14); these run without a browser.
//
// `.tsx` is included because a panel is a function from one response document to
// a DOM fragment, and the cheapest honest way to assert that function is to call
// it — `renderToStaticMarkup` over a fixture, then query the markup. No testing
// library is added for it: the assertions are on `data-*` attributes and
// `data-value`s, which is what the e2e reads too, so a query helper that hid the
// attributes behind role lookups would be testing something else.

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.{ts,tsx}"],
    environment: "jsdom",
  },
});
