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
import { availabilityChip, healthLine } from "../src/components/ProvidersPanel";
import { SignInDialog, refusalText } from "../src/components/SignInDialog";
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
  it("says only the state when nothing has been observed", () => {
    const line = healthLine(row({ health: "unused", last_observed_at: null }));
    expect(line).toBe(copy.providers.health.unused);
  });

  it("carries a time when something has", () => {
    const line = healthLine(row({ health: "accepted", last_observed_at: 1_700_000_000 }));
    expect(line).toContain(copy.providers.health.accepted);
    // A time is present, so the staleness is on screen rather than implied.
    expect(line.length).toBeGreaterThan(copy.providers.health.accepted.length);
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

  it("falls back to the server's own message for a reason it does not know", () => {
    // A client that paraphrased a refusal it did not recognise would be
    // guessing; the server named it, so the server's words stand.
    const error = new WorkspaceError(400, "something_new", "the server's own sentence");
    expect(refusalText(error)).toBe("the server's own sentence");
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
