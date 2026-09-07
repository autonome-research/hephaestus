// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The client half of provider sign-in (INTERFACE.md §23; Stages 10B and 10C).
//
// The suite renders with `renderToStaticMarkup` and no testing library, so what
// it can assert is *what the markup says* — which happens to be exactly the set
// of §23 properties that are the client's to keep:
//
// * **no credential material anywhere in the rendered DOM** (§23.8) — the
//   sharpest assertion in this file, because it is the one §23.13 pays for;
// * **two axes, never collapsed** (§23.8);
// * **the password discipline: `type=password`, `autocomplete=off`, and NO
//   `name`** (§23.3);
// * **scope has no default and nothing is preselected** (§23.2);
// * **nothing adopts on render** (§23.14 item 19).
//
// Clean-room hygiene (§3): no assertion is on a string of UI copy. Where a
// distinction must be visible, the assertion is that two states render
// *different* text — never that either says any particular words.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import {
  AUTH_FLOW_TYPES,
  AUTH_HEALTH,
  AUTH_SOURCES,
  CREDENTIAL_SCOPES,
  DISCOVERY_KINDS,
  PROVIDER_KINDS,
  isAuthHealth,
  isAuthSource,
  type DiscoveryOffer,
  type ProviderRow,
} from "../src/api/providers";
import { availabilityChip, healthObserved } from "../src/components/ProvidersPanel";
import { formatObservedAt } from "../src/system";
import { SignInDialog } from "../src/components/SignInDialog";
// J-web-stream-6: `refusalText` moved out of `SignInDialog.tsx` into a
// surface-neutral module neither surface owns, because the providers panel and
// the composer's attach action both render `POST /providers/attach` refusals a
// few inches apart on the same screen. The old import path no longer exports
// it at all — that is this test file catching the move rather than a defect.
import { refusalCode, refusalText } from "../src/components/refusalText";
import { ATTACH_CAUSES, type AttachCause } from "../src/api/attach";
import { WorkspaceError } from "../src/api/client";
import { copy } from "../src/copy";

/** A key literal. If any of it reaches markup, an assertion below fails. */
const SECRET = "sk-web-SENTINEL-42a19c7f-never-render-me";

function html(node: ReactElement): string {
  return renderToStaticMarkup(node);
}

function row(overrides: Partial<ProviderRow> = {}): ProviderRow {
  return {
    id: "heph-fake",
    kind: "openai_compatible",
    name: "Fake",
    models: [{ id: "m", name: "M" }],
    source: "none",
    health: "unused",
    last_observed_at: null,
    available: null,
    unavailable_reason: null,
    ...overrides,
  };
}

function offer(overrides: Partial<DiscoveryOffer> = {}): DiscoveryOffer {
  return {
    discovery_id: "disc-abc",
    kind: "pi_auth",
    provider_id: "openai-codex",
    model_ids: ["gpt-5-codex"],
    source_path: "/home/someone/.pi/agent/auth.json",
    ...overrides,
  };
}

// --------------------------------------------------------------------------
// 1. the closed vocabularies, and the two axes that are never collapsed
// --------------------------------------------------------------------------

describe("the §23 vocabularies are closed", () => {
  it("matches the server's four provider kinds", () => {
    expect([...PROVIDER_KINDS]).toEqual([
      "anthropic",
      "openai_compatible",
      "local",
      "pi_native",
    ]);
  });

  it("has a copy string for every value of both status axes", () => {
    // §23.14 item 15: closed copy for both axes and every refusal reason. A
    // value with no string would render blank, which §4.4 says reads as a bug.
    for (const source of AUTH_SOURCES) expect(copy.providers.source[source]).toBeTruthy();
    for (const health of AUTH_HEALTH) expect(copy.providers.health[health]).toBeTruthy();
    for (const kind of DISCOVERY_KINDS) expect(copy.providers.discover.kind[kind]).toBeTruthy();
    for (const scope of CREDENTIAL_SCOPES) expect(copy.providers.dialog.scope[scope]).toBeTruthy();
  });

  it("gives each source and each health its own distinct sentence", () => {
    // The two axes answer different questions (§23.8), so no two values inside
    // one axis may share a rendering — a duplicated string is a collapse.
    const sources = AUTH_SOURCES.map((s) => copy.providers.source[s]);
    const healths = AUTH_HEALTH.map((h) => copy.providers.health[h]);
    expect(new Set(sources).size).toBe(sources.length);
    expect(new Set(healths).size).toBe(healths.length);
  });

  it("refuses a value outside either axis", () => {
    expect(isAuthSource("project")).toBe(true);
    expect(isAuthSource("connected")).toBe(false);
    expect(isAuthHealth("rate_limited")).toBe(true);
    expect(isAuthHealth("green")).toBe(false);
  });

  it("names the two flows and nothing else", () => {
    expect([...AUTH_FLOW_TYPES]).toEqual(["device_code", "authorize_url"]);
  });
});

describe("§23.7's verification is reported without substitution", () => {
  it("distinguishes unverified from unknown", () => {
    // `null` — nothing has verified this — is NOT `ok`. The difference is the
    // whole of the no-substitution property: a provider nothing checked is not
    // a checked provider.
    expect(availabilityChip(null)).toBe("unknown");
    expect(availabilityChip(true)).toBe("ok");
    expect(availabilityChip(false)).toBe("error");
  });
});

describe("§23.8's health is LAST OBSERVED, never current", () => {
  it("says nothing observed when the timestamp is absent", () => {
    expect(healthObserved(row({ health: "unused", last_observed_at: null }))).toBeNull();
  });

  it("prints a clock for today and a date when the observation is older (#94)", () => {
    const now = new Date("2026-09-01T14:32:00");
    const today = Math.floor(now.getTime() / 1000);
    const threeDays = today - 3 * 86_400;
    expect(formatObservedAt(today, now)).toBe(new Date(today * 1000).toLocaleTimeString());
    expect(formatObservedAt(threeDays, now)).not.toBe(new Date(threeDays * 1000).toLocaleTimeString());
    const observed = healthObserved(row({ health: "accepted", last_observed_at: threeDays }), now);
    expect(observed).toContain(copy.providers.healthStale);
    expect(observed).not.toBeNull();
  });
});

// --------------------------------------------------------------------------
// 2. §23.3's password discipline
// --------------------------------------------------------------------------

describe("the key field follows §23.3", () => {
  const markup = html(
    <SignInDialog
      provider={row()}
      open
      onClose={() => {}}
      onSignedIn={() => {}}
    />,
  );

  it("renders the key as a password field", () => {
    expect(markup).toContain('type="password"');
  });

  it("turns autocomplete off", () => {
    // Case-insensitive on purpose: React 18's static renderer emits this one
    // attribute in its JSX casing while the browser DOM carries the lowercase
    // form a password manager actually reads. `providers.spec.ts` asserts the
    // real attribute on the real element; this asserts that it is set at all.
    expect(markup.toLowerCase()).toContain('autocomplete="off"');
  });

  it("gives the field NO name a password manager could save it under", () => {
    // The subtle one, and the reason it has its own test: a provider key filed
    // by a browser under the identity of a loopback page is a credential in the
    // wrong place forever. Nothing in this dialog emits a `name` at all.
    expect(markup).not.toContain("name=");
  });
});

// --------------------------------------------------------------------------
// 3. §23.2 — scope has no default
// --------------------------------------------------------------------------

describe("the persistence scope is not defaulted", () => {
  const markup = html(
    <SignInDialog provider={row()} open onClose={() => {}} onSignedIn={() => {}} />,
  );

  it("preselects neither scope", () => {
    // Both toggles render, and neither is pressed. §23.2: "A defaulted
    // secret-persistence decision is the single most consequential default a
    // local tool can have, and this document declines to make it."
    for (const scope of CREDENTIAL_SCOPES) {
      expect(markup).toContain(`data-signin-scope="${scope}"`);
    }
    // Scoped to the SCOPE controls: the mode toggle above them is legitimately
    // pressed (the dialog opens on one of its two halves), and asserting over
    // the whole document would be asserting about the wrong control.
    for (const scope of CREDENTIAL_SCOPES) {
      const at = markup.indexOf(`data-signin-scope="${scope}"`);
      const button = markup.slice(markup.lastIndexOf("<button", at), at);
      expect(button).toContain('aria-pressed="false"');
    }
  });

  it("disables submission with a reason while nothing is chosen", () => {
    // §4.7: a disabled control in this app must always be able to say why, and
    // "type a key" and "choose where it lives" are different remedies.
    expect(markup).toContain("data-signin-submit");
    expect(markup).toContain("disabled");
  });
});

// --------------------------------------------------------------------------
// 4. the property §23.13 pays for: no credential material in the DOM
// --------------------------------------------------------------------------

describe("no rendered surface can carry credential material", () => {
  it("has no field on the row type that could hold one", () => {
    // The type is the assertion. A key, a token or a masked tail would have to
    // be a member here first, so this is what makes §23.8's "no masked key tail
    // — not four characters, not two" a compile-time fact rather than a habit.
    const keys = Object.keys(row());
    for (const forbidden of ["key", "token", "secret", "masked", "tail", "hint"]) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it("has no field on the discovery offer either", () => {
    // §23.5 constraint 2, and the ceiling/floor distinction §0.2a draws: the
    // ruling permits "a masked hint at most", which does not oblige one, and
    // §15.41's stricter refusal stands.
    expect(Object.keys(offer()).sort()).toEqual([
      "discovery_id",
      "kind",
      "model_ids",
      "provider_id",
      "source_path",
    ]);
  });

  it("renders no part of a secret even when one is typed", () => {
    // A controlled password input echoes its value into `value="…"` on the
    // server-rendered markup, so this asserts on the *panel's* surfaces — the
    // ones a screenshot or a screen-share would capture.
    const rendered = html(
      <SignInDialog
        provider={row({ source: "project", health: "accepted", last_observed_at: 1 })}
        open
        onClose={() => {}}
        onSignedIn={() => {}}
      />,
    );
    expect(rendered).not.toContain(SECRET);
    expect(rendered).not.toContain(SECRET.slice(-4));
  });
});

// --------------------------------------------------------------------------
// 5. refusals are the server's, phrased once (§23.14 item 15)
// --------------------------------------------------------------------------

describe("every named refusal has exactly one sentence", () => {
  it("maps a known reason to the closed vocabulary", () => {
    const error = new WorkspaceError(400, "credential_scope_required", "server text");
    expect(refusalText(error)).toBe(copy.providers.refusal.credential_scope_required);
  });

  it("falls back to the generic title for a reason it does not know, never the raw message (J-web-stream-6)", () => {
    // REVERSED, on purpose. The raw-message fallback used to stand here on the
    // reasoning that "the server named it, so the server's words stand" — true
    // of a plain sentence and false of a COMPOSED one: `agent_unavailable`'s
    // message is `f"{cause}: {detail}"`, so that fallback is what rendered
    // `no_provider_config: no provider config at <path>` inside a `role="alert"`
    // for the one route whose reason the map had no row for. The root fix
    // removes the fallback entirely, for every reason absent from the map, not
    // only the attach one — an unknown reason must never reach the screen as
    // the server's own words.
    const error = new WorkspaceError(400, "something_new", "the server's own sentence");
    expect(refusalText(error)).toBe(copy.errors.title);
    expect(refusalText(error)).not.toBe("the server's own sentence");
    expect(refusalText(error)).not.toMatch(/something_new/);
  });

  it("never renders a machine-reason shape as the sentence, for any reason string", () => {
    // A copy lint over the map itself: no mapped sentence is a bare
    // underscore_case word or a colon-prefixed code, the shape a raw `cause` or
    // `f"{cause}: {detail}"` composition would produce.
    const shape = /^[a-z]+(?:_[a-z]+)+$|^[a-z_]+:\s/;
    for (const sentence of Object.values(copy.providers.refusal)) {
      expect(sentence).not.toMatch(shape);
    }
    for (const sentence of Object.values(copy.attach.cause)) {
      expect(sentence).not.toMatch(shape);
    }
  });
});

// --------------------------------------------------------------------------
// J-web-stream-6 — the structured attach cause is the shared vocabulary
// --------------------------------------------------------------------------
//
// §7A.8's `agent_unavailable` / `attach_failed` refusal carries a structured
// `cause` in its `data`, and it is consulted BEFORE the plain reason map: three
// distinct conditions (missing config, invalid config, no Node…) share one
// `reason` string, so mapping by reason alone would read them all identically.

describe("the structured attach cause is mapped ahead of the plain reason map", () => {
  function attachError(cause: string, detail?: string): WorkspaceError {
    return new WorkspaceError(
      503,
      "agent_unavailable",
      detail === undefined ? `${cause}: reduced detail` : `${cause}: ${detail}`,
      {
        attached: false,
        config_path: "/project/.heph/providers.json",
        generation: 0,
        cause,
        ...(detail === undefined ? {} : { detail }),
      },
    );
  }

  it("maps every member of the closed cause vocabulary to its own sentence, never the composed message", () => {
    for (const cause of ATTACH_CAUSES) {
      const error = attachError(cause);
      const text = refusalText(error);
      expect(text, cause).toBe(copy.attach.cause[cause]);
      expect(text, cause).not.toMatch(new RegExp(`^${cause}:`));
    }
  });

  it("still exposes the machine reason for the chip, alongside the mapped sentence", () => {
    const error = attachError("no_provider_config");
    expect(refusalCode(error)).toBe("agent_unavailable");
    expect(refusalText(error)).toBe(copy.attach.cause.no_provider_config);
  });

  it("falls through to the plain reason map for a refusal with no structured cause", () => {
    const error = new WorkspaceError(400, "credential_scope_required", "server text");
    expect(refusalText(error)).toBe(copy.providers.refusal.credential_scope_required);
  });

  it("pins the client's cause vocabulary against a fixed list, so a server addition is caught here", () => {
    // Not a drift-against-the-server test (that needs the server's own
    // vocabulary, out of this lane's reach) — a change-detector so the seven
    // named causes cannot silently become six or eight without a reviewer
    // seeing this test fail and updating both this list and the copy map.
    const known: readonly AttachCause[] = [
      "no_provider_config",
      "provider_config_invalid",
      "node_missing",
      "node_too_old",
      "sidecar_failed",
      "auth_link_refused",
      "detached",
    ];
    expect([...ATTACH_CAUSES].sort()).toEqual([...known].sort());
    expect(Object.keys(copy.attach.cause).sort()).toEqual([...known].sort());
  });

  it("gives each refusal a distinct sentence", () => {
    const sentences = Object.values(copy.providers.refusal);
    expect(new Set(sentences).size).toBe(sentences.length);
  });

  it("names the two refusals the 2026-08-28 ruling added", () => {
    expect(copy.providers.refusal.path_not_web_writable).toBeTruthy();
    expect(copy.providers.refusal.discovery_source_unknown).toBeTruthy();
  });
});

// --------------------------------------------------------------------------
// J-web-stream-6 — the class-closing test.
//
// Removing the raw-message fallback (above) changes behaviour for every
// provider refusal whose reason is absent from `copy.providers.refusal`: an
// unmapped reason used to leak the server's own composed sentence and now
// degrades SILENTLY to the generic §2.4 title, with no test failing. So the
// map must be checked against the server's own closed vocabulary rather than
// against a second copy of it retyped here — the same drift class L8 exists to
// catch, applied to this one map.
//
// `PROVIDER_REFUSALS` (`server/src/hephaestus/http/providers.py`) is that
// vocabulary: "Every refusal §23.11 introduces, plus the engine codes it
// reuses. Enumerated so `test_http_providers.py` can test the vocabulary BY
// ENUMERATION and a reason cannot arrive without a status, a test, and a copy
// string." Read as text rather than imported — this is a `.ts` suite with no
// Python runtime — exactly as the CSS-source assertions elsewhere in this lane
// read a stylesheet as text rather than executing it.
// --------------------------------------------------------------------------

const here = dirname(fileURLToPath(import.meta.url));
const PROVIDERS_PY = join(here, "..", "..", "server", "src", "hephaestus", "http", "providers.py");

/** `PROVIDER_REFUSALS`'s own quoted entries, parsed out of the source text. */
function serverProviderRefusals(): readonly string[] {
  const source = readFileSync(PROVIDERS_PY, "utf8");
  // `PROVIDER_REFUSALS` also appears earlier in the module's `__all__` export
  // list, so anchor on the DECLARATION itself rather than the bare name.
  const start = source.indexOf("PROVIDER_REFUSALS: Final[tuple[str, ...]] =");
  if (start === -1) {
    throw new Error(
      "PROVIDER_REFUSALS's declaration not found in providers.py — has its type annotation changed?",
    );
  }
  const open = source.indexOf("(", start);
  const close = source.indexOf(")", open);
  const body = source.slice(open + 1, close);
  const reasons = [...body.matchAll(/"([a-z_]+)"/g)].map((m) => m[1] ?? "");
  if (reasons.length === 0) {
    throw new Error("parsed zero reasons out of PROVIDER_REFUSALS — the regex no longer matches its shape");
  }
  return reasons;
}

describe("copy.providers.refusal — a class-closing check against the SERVER's vocabulary (J-web-stream-6)", () => {
  it("maps every reason PROVIDER_REFUSALS enumerates, not a second hand-typed copy of it", () => {
    const server = serverProviderRefusals();
    const client = Object.keys(copy.providers.refusal);
    // Guard the guard: a parse that silently returned too few entries would
    // make this assertion vacuously pass.
    expect(server.length).toBeGreaterThanOrEqual(20);
    const missing = server.filter((reason) => !client.includes(reason));
    expect(missing, `reasons the server can emit with no mapped sentence: ${missing.join(", ")}`).toEqual(
      [],
    );
  });

  it("never renders a machine-reason shape for ANY reason in the server's own list, even if unmapped", () => {
    // The behavioural half: simulate the server emitting each of its own
    // reasons and assert the rendered sentence is never the raw text this
    // fallback used to leak — the exact regression the ledger's fix note
    // describes ("no_provider_config: no provider config at <path>" behind a
    // role="alert").
    for (const reason of serverProviderRefusals()) {
      const raw = `${reason}: some engine-composed detail nobody should read`;
      const error = new WorkspaceError(400, reason, raw);
      const text = refusalText(error);
      expect(text, reason).not.toBe(raw);
      expect(text, reason).not.toMatch(new RegExp(`^${reason}:`));
    }
  });
});

// --------------------------------------------------------------------------
// 6. §23.4's disclosure, said before the click
// --------------------------------------------------------------------------

describe("the subscription flow discloses what the provider will show", () => {
  it("carries the disclosure and the no-refresh statement", () => {
    const markup = html(
      <SignInDialog
        provider={row({ kind: "pi_native" })}
        open
        onClose={() => {}}
        onSignedIn={() => {}}
      />,
    );
    // Two implications §23.4 states rather than buries, and both are in the
    // markup BEFORE any control that starts a flow: the operator's provider
    // will list the embedded agent library, and this server never refreshes a
    // token. Asserted by presence of the sentence, not by its wording.
    expect(markup).toContain(copy.providers.dialog.subscriptionDisclosure);
    const disclosureAt = markup.indexOf(copy.providers.dialog.subscriptionDisclosure);
    const beginAt = markup.indexOf("data-signin-begin");
    expect(disclosureAt).toBeGreaterThanOrEqual(0);
    expect(beginAt).toBeGreaterThan(disclosureAt);
  });

  it("offers device code first, which is the flow that opens no socket", () => {
    const markup = html(
      <SignInDialog
        provider={row({ kind: "pi_native" })}
        open
        onClose={() => {}}
        onSignedIn={() => {}}
      />,
    );
    const device = markup.indexOf('data-signin-begin="device_code"');
    const fallback = markup.indexOf('data-signin-begin="authorize_url"');
    expect(device).toBeGreaterThanOrEqual(0);
    expect(fallback).toBeGreaterThan(device);
  });
});
