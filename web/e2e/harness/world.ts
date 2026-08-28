// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The world the Gate G4 suite runs in: one real `heph serve --web`, one real
// project, one bearer token (INTERFACE.md §14).
//
// `global-setup.ts` starts `harness/serve_fixture.py` and it writes the
// handshake this module reads. Nothing here starts, stubs or wraps a server —
// the point of the gate is that the browser talks to the shipped one.
//
// TWO RULES THIS MODULE ENFORCES FOR EVERY SPEC:
//
// 1. **The server is the source of every expected number.** `api()` reads the
//    same routes the app reads, so a DOM assertion is always DOM-versus-server
//    and never DOM-versus-a-number-typed-in-a-test. §1's whole discipline is
//    that facts come from the server; a suite that hard-coded `3` would be
//    asserting the fixture's shape twice and the client's fidelity never.
// 2. **The token enters through the fragment, once.** §2.2 mints
//    `http://HOST:PORT/#t=<token>`; `open()` loads exactly that and then
//    navigates to the §4.5 route, which is how a real operator arrives.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";

/** Written by `global-setup.ts`; read by every spec. */
export const HANDSHAKE_PATH = join(process.cwd(), "test-results", "g4-handshake.json");

export interface World {
  readonly base_url: string;
  readonly token: string;
  readonly project_root: string;
  /** The committed transcript's sessions, reopened before the browser starts. */
  readonly sessions: readonly string[];
  readonly model_base_url: string;
  readonly pid: number;
  /** The interpreter that runs `heph` verbs against the fixture. */
  readonly python: string;
}

let cached: World | null = null;

export function world(): World {
  if (cached === null) {
    cached = JSON.parse(readFileSync(HANDSHAKE_PATH, "utf8")) as World;
  }
  return cached;
}

/**
 * One request, with connection reuse refused.
 *
 * `Connection: close` is not a courtesy: Node pools keep-alive sockets, and a
 * server that closes an idle one between our pooling it and our reusing it
 * surfaces as `TypeError: fetch failed / SocketError: other side closed` in
 * whichever test happens to reuse next. It cost G4.4 a run (33194568507) —
 * the test that also spawns a subprocess, so it idles longest. A fresh socket
 * per request removes the race rather than retrying through it, which would
 * have hidden a real dropped connection just as effectively.
 */
async function request(path: string, init?: RequestInit): Promise<Response> {
  const { base_url, token } = world();
  return await fetch(`${base_url}/api/v1${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
      Connection: "close",
    },
  });
}

/** One authorized read of the workspace API — the same route the app reads. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init);
  if (!response.ok) {
    throw new Error(`GET ${path} -> ${String(response.status)} ${await response.text()}`);
  }
  return (await response.json()) as T;
}

/** The exact stored bytes of an artifact (§2.6) — no transformation anywhere. */
export async function apiBytes(path: string): Promise<Buffer> {
  const response = await request(path);
  if (!response.ok) {
    throw new Error(`GET ${path} -> ${String(response.status)} ${await response.text()}`);
  }
  return Buffer.from(await response.arrayBuffer());
}

export function refSegment(ref: string): string {
  return encodeURIComponent(ref);
}

/**
 * A UUIDv7 for `Idempotency-Key`.
 *
 * §2.5's ladder refuses anything else by name (`idempotency_key_malformed`), and
 * `crypto.randomUUID()` mints a v4 — so a suite that used it would be testing
 * the refusal rather than the mutation. The timestamp prefix is what makes a key
 * sortable and retention-prunable, which is why the server insists on it.
 */
export function uuid7(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const millis = BigInt(Date.now());
  for (let i = 0; i < 6; i += 1) {
    bytes[i] = Number((millis >> BigInt(8 * (5 - i))) & 0xffn);
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x70;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * A §4.5 workspace route, spelled the way the app spells it.
 *
 * Deliberately assembled here rather than imported from `web/src`: a spec that
 * built its URLs with the app's own encoder would agree with the app by
 * construction, including when both are wrong.
 */
export function route(part: string, query: Record<string, string> = {}): string {
  const search = new URLSearchParams(query).toString();
  return `#/p/${encodeURIComponent(part)}${search === "" ? "" : `?${search}`}`;
}

/**
 * Arrive as an operator does: the `#t=` entry URL, then the route.
 *
 * The token is claimed on the first load and moved to `sessionStorage`, so the
 * second navigation carries no credential in its URL — which is the property
 * §2.2 exists to buy, and it is asserted in `dom.spec.ts`.
 */
export async function open(page: Page, hash: string): Promise<void> {
  const { base_url, token } = world();
  await page.goto(`${base_url}/#t=${token}`);
  await page.waitForFunction(() => document.querySelector("[data-pin-mode]") !== null, null, {
    timeout: 60_000,
  });
  await page.evaluate((next: string) => {
    window.location.hash = next;
  }, hash);
  const prefix = hash.split("?")[0] ?? hash;
  await page.waitForFunction(
    (expected: string) => window.location.hash.startsWith(expected),
    prefix,
    { timeout: 30_000 },
  );
}
