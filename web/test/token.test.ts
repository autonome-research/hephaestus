// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The `#t=` handshake (INTERFACE.md §2.2) and the collision it hides.
//
// §2.2 mints `http://127.0.0.1:PORT/#t=<token>`; §4.5 serializes `explode_t`
// into the *same fragment* as `t=0.0`. Reading a route fragment for a `t` key
// therefore adopts the explode value as the bearer token — every request 401s,
// and because claiming rewrites the URL afterwards, the whole workspace route is
// discarded on each reload. This was found by driving the built app against a
// live `heph serve --web`, and these tests are what keep it found.

import { beforeEach, describe, expect, it } from "vitest";
import { claimToken, dropToken, workspaceToken } from "../src/api/token";
import { DEFAULT_STATE, encodeWorkspaceUrl } from "../src/state/workspace";

function open(hash: string): void {
  window.sessionStorage.clear();
  dropToken();
  window.history.replaceState(null, "", `/${hash}`);
}

describe("claimToken", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    dropToken();
  });

  it("takes the token out of the fragment and rewrites the URL", () => {
    open("#t=SECRET-abc123");
    expect(claimToken()).toBe("SECRET-abc123");
    expect(workspaceToken()).toBe("SECRET-abc123");
    // §2.2: the token must not remain in an address that can be copied, logged,
    // or reached with Back.
    expect(window.location.hash).toBe("");
    expect(window.sessionStorage.getItem("hephaestus.workspace.token")).toBe("SECRET-abc123");
  });

  it("never reads explode_t as a token, and leaves a route fragment alone", () => {
    open("#t=SECRET-abc123");
    claimToken();
    const route = encodeWorkspaceUrl({ ...DEFAULT_STATE, part: "stair", explode_t: 0 });
    expect(route).toContain("t=0.0"); // the collision is real, not hypothetical
    window.history.replaceState(null, "", `/${route}`);
    expect(claimToken()).toBe("SECRET-abc123"); // from storage, not from `t=0.0`
    expect(window.location.hash).toBe(route); // the route survives the reload
  });

  it("reports no token rather than inventing one", () => {
    open("");
    expect(claimToken()).toBeNull();
    open("#/p/stair?view=iso&t=0.5");
    expect(claimToken()).toBeNull();
  });
});
