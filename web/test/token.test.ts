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
import {
  TOKEN_STORAGE_KEY,
  claimToken,
  dropToken,
  holdPastedToken,
  parsePastedToken,
  subscribeToken,
  tokenAbsence,
  workspaceToken,
} from "../src/api/token";
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
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe("SECRET-abc123");
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

  it("survives a reload from sessionStorage after the hash is rewritten", () => {
    open("#t=SECRET-abc123");
    claimToken();
    const stored = window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
    expect(stored).toBe("SECRET-abc123");
    // New JS context: in-memory hold is gone, origin storage remains. A `?r=`
    // cache-buster and a workspace route (with explode `t=`) must not eat it.
    dropToken();
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, stored ?? "");
    window.history.replaceState(null, "", "/?r=1#/p/stair?pin=current&t=0.0");
    expect(claimToken()).toBe("SECRET-abc123");
    expect(workspaceToken()).toBe("SECRET-abc123");
    expect(window.location.search).toBe("?r=1");
  });

  it("re-reads sessionStorage when the in-memory hold is empty", () => {
    open("#t=SECRET-abc123");
    claimToken();
    dropToken();
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, "SECRET-abc123");
    expect(workspaceToken()).toBe("SECRET-abc123");
  });
});

describe("parsePastedToken / holdPastedToken", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    dropToken();
  });

  it("accepts the printed address, a fragment, and the bare token", () => {
    expect(parsePastedToken("http://127.0.0.1:8761/#t=NEW-TOKEN")).toBe("NEW-TOKEN");
    expect(parsePastedToken("#t=NEW-TOKEN")).toBe("NEW-TOKEN");
    expect(parsePastedToken("t=NEW-TOKEN")).toBe("NEW-TOKEN");
    expect(parsePastedToken("NEW-TOKEN")).toBe("NEW-TOKEN");
  });

  it("never reads a workspace route's explode_t as a token", () => {
    expect(parsePastedToken("#/p/stair?view=iso&t=0.5")).toBeNull();
    expect(parsePastedToken("http://127.0.0.1:8761/#/p/stair?t=0.0")).toBeNull();
  });

  it("holds a pasted value and notifies the gate", () => {
    const seen: string[] = [];
    const stop = subscribeToken(() => {
      seen.push(workspaceToken() ?? "");
    });
    expect(holdPastedToken("http://127.0.0.1:8761/#t=PASTED")).toBe("PASTED");
    expect(workspaceToken()).toBe("PASTED");
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe("PASTED");
    expect(tokenAbsence()).toBe("none");
    expect(seen).toEqual(["PASTED"]);
    stop();
  });
});

describe("dropToken", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    dropToken();
  });

  it("forgets the hold, clears storage, and names the absence unauthorized", () => {
    open("#t=SECRET-abc123");
    claimToken();
    const seen: Array<string | null> = [];
    const stop = subscribeToken(() => {
      seen.push(workspaceToken());
    });
    dropToken();
    expect(workspaceToken()).toBeNull();
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(tokenAbsence()).toBe("unauthorized");
    expect(seen).toEqual([null]);
    stop();
  });
});
