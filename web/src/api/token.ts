// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The bearer token, and the one place it is taken out of the URL.
//
// INTERFACE.md §2.2: `heph serve --web` prints `http://127.0.0.1:PORT/#t=<token>`
// and "the token rides in the **fragment**, never a query string, so it never
// enters an access log or a `Referer`. The app moves it to `sessionStorage`,
// rewrites the URL, and sends `Authorization: Bearer …` on every request
// including the WS upgrade. Without a token the app renders one non-interactive
// panel explaining how to obtain one; it never prompts for credentials, because
// there are none to prompt for."
//
// The rewrite happens **once, before anything else reads the hash**, because
// §4.5's route lives in that same fragment and `#t=…` is not a route. `main.tsx`
// calls `claimToken()` first for exactly that reason.

const STORAGE_KEY = "hephaestus.workspace.token";

/**
 * The `#t=` parameter, if this load carries one.
 *
 * **`t` COLLIDES, and the discriminator is the leading slash.** §2.2 mints
 * `#t=<token>`; §4.5 serializes `explode_t` as `…&t=0.0` inside a route
 * fragment. Both are the letter `t` in the same fragment, so parsing a
 * *route* fragment for a `t` key reads the explode value as a token — which
 * silently replaces a good token with `"0.0"`, 401s every request, and (because
 * this function's caller rewrites the URL afterwards) throws the whole route
 * away on every reload. It is a real defect and it was caught live.
 *
 * A token fragment is exactly `t=<token>`; a §4.5 route fragment always begins
 * with `/` (`/` or `/p/{part}`). So a fragment that starts with `/` carries no
 * token, full stop, and the two shapes can never be confused again.
 */
function tokenFromHash(hash: string): string | null {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (raw === "" || raw.startsWith("/")) return null;
  const token = new URLSearchParams(raw).get("t");
  return token !== null && token !== "" ? token : null;
}

function session(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    // A browser with storage denied still works for one page load; the token
    // simply does not survive a reload. Refusing to run would be worse.
    return null;
  }
}

let held: string | null = null;

/**
 * Take the token out of the URL fragment into `sessionStorage`, once.
 *
 * Returns the token this tab holds, or `null` when there is none — the state
 * §2.2 renders as one non-interactive panel rather than a credential prompt.
 */
export function claimToken(): string | null {
  const store = session();
  const fromHash = tokenFromHash(window.location.hash);
  if (fromHash !== null) {
    held = fromHash;
    store?.setItem(STORAGE_KEY, fromHash);
    // Rewrite before the router reads the hash. `replaceState` and not
    // `pushState`: the token-bearing URL must not remain reachable by Back.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return held;
  }
  held = store?.getItem(STORAGE_KEY) ?? null;
  return held;
}

/** The token this tab holds. `claimToken()` must have run first. */
export function workspaceToken(): string | null {
  return held;
}

/** Forget the token — used when the server rejects it (§2.4 `unauthorized`). */
export function dropToken(): void {
  held = null;
  session()?.removeItem(STORAGE_KEY);
}
