// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The rule plugin is plain JS tooling (§3.14: "grep-shaped `node` scripts…
// adding no dependency"), and `test/system/checks.test.ts` imports it to assert
// that each check actually fires. This is the minimum shape that import needs;
// it is deliberately not a full `eslint` rule type, because the test treats the
// plugin as an opaque object it hands to `ESLint`.

import type { ESLint } from "eslint";

declare const plugin: ESLint.Plugin;
export default plugin;
