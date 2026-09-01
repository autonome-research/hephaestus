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
//
// Persistence is `sessionStorage` keyed to this origin — not a query string
// (§2.2 forbids that) and not a fragment the workspace route then overwrites.
// A 401 forgets the token and tells the App gate, so this tab remounts the
// §2.2 panel instead of leaving a shell that 401s every subsequent request.

export const TOKEN_STORAGE_KEY = "hephaestus.workspace.token";

/** Why this tab has no token. `unauthorized` is a live §2.4 401, not absence at open. */
export type TokenAbsence = "none" | "unauthorized";

type TokenListener = () => void;

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
let absence: TokenAbsence = "none";
const listeners = new Set<TokenListener>();

function remember(token: string): void {
  held = token;
  absence = "none";
  session()?.setItem(TOKEN_STORAGE_KEY, token);
}

function notify(): void {
  for (const listener of listeners) listener();
}

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
    remember(fromHash);
    // Rewrite before the router reads the hash. `replaceState` and not
    // `pushState`: the token-bearing URL must not remain reachable by Back.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return held;
  }
  held = store?.getItem(TOKEN_STORAGE_KEY) ?? null;
  // A page load has no live 401. Absence-at-open is `none` whether storage
  // still holds a token or not; `unauthorized` is only set by `dropToken`.
  absence = "none";
  return held;
}

/**
 * The token this tab holds.
 *
 * Falls back to `sessionStorage` when the in-memory hold is empty so a reload
 * (new JS context, same origin, same tab) still has the token the page was
 * given, even if `claimToken()` has not run again yet.
 */
export function workspaceToken(): string | null {
  if (held !== null) return held;
  held = session()?.getItem(TOKEN_STORAGE_KEY) ?? null;
  return held;
}

/** Why the gate is showing the no-token panel. */
export function tokenAbsence(): TokenAbsence {
  return absence;
}

/**
 * Subscribe to hold / drop. The App gate remounts when the token this tab
 * holds changes — a live 401 must not leave a zombie Shell (#80).
 */
export function subscribeToken(listener: TokenListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * A `#t=` value pasted into the no-token panel (#47).
 *
 * Accepts the printed address, a `#t=…` fragment, a `t=…` pair, or the bare
 * token. A §4.5 route fragment is never a token — that is the explode collision.
 */
export function parsePastedToken(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  try {
    const fromUrl = tokenFromHash(new URL(trimmed).hash);
    if (fromUrl !== null) return fromUrl;
  } catch {
    // Not an absolute URL; try the other shapes.
  }
  const hashAt = trimmed.indexOf("#");
  if (hashAt >= 0) return tokenFromHash(trimmed.slice(hashAt));
  const fromPair = tokenFromHash(trimmed);
  if (fromPair !== null) return fromPair;
  if (trimmed.startsWith("/") || trimmed.includes("?") || /\s/.test(trimmed)) return null;
  return trimmed;
}

/** Hold a pasted `#t=` (or the token itself) and tell the gate. */
export function holdPastedToken(raw: string): string | null {
  const token = parsePastedToken(raw);
  if (token === null) return null;
  remember(token);
  notify();
  return token;
}

/** Forget the token — used when the server rejects it (§2.4 `unauthorized`). */
export function dropToken(): void {
  held = null;
  absence = "unauthorized";
  session()?.removeItem(TOKEN_STORAGE_KEY);
  notify();
}
