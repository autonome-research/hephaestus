// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The system layer's contracts, where they are testable without a browser
// (INTERFACE.md §3.4, §4.1, §4.7).
//
// Three things are asserted here that §3.14's e2e cannot reach:
//
// * `format.ts` is the numeric RENDER boundary and nothing more — §1 is
//   untouched because formatting is presentation, not derivation, and the proof
//   is that `data-value` still carries the server's bytes while the glyphs
//   change. `74289.99999999999` is the case §4.7 names.
// * `useBreakpoint`'s store is the SOLE breakpoint authority, and the band
//   arithmetic is pure — so the 1024–1279px band where the shipped CSS and the
//   shipped `useState` disagreed can be asserted at every boundary without a
//   viewport.
// * `Button` cannot be disabled without a reason. That is a type-level rule; what
//   is asserted here is that the reason actually REACHES the DOM in both
//   carriers, because a `title` alone is not reachable from the keyboard and a
//   disabled control is exactly where a keyboard user is stuck.

import { describe, expect, it, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import {
  BREAKPOINT_RAIL,
  BREAKPOINT_STREAM,
  Button,
  Chip,
  DataTable,
  EmptyState,
  Field,
  Panel,
  PanelBody,
  PanelHeader,
  bandFor,
  formatBytes,
  formatNumber,
  formatRef,
  formatValue,
  metricLabel,
  metricUnit,
} from "../../src/system";
import { DRAWER_MAX, DRAWER_MIN, shellStore } from "../../src/state/shell";
import { Fact } from "../../src/components/Fact";
import { copy } from "../../src/copy";

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

// ---------------------------------------------------------------------------
// format.ts — §4.7's render boundary
// ---------------------------------------------------------------------------

describe("§4.7 — format.ts renders numbers without deriving them", () => {
  it("retires `74289.99999999999` shipped to an engineer as a measurement", () => {
    // A float artefact of an exact computation. Printing it whole tells the
    // reader the engine measured to fourteen digits, which it did not.
    expect(formatNumber(74289.99999999999)).toBe("74290");
    expect(formatNumber(0.1 + 0.2)).toBe("0.3");
  });

  it("leaves an integer and a genuinely fractional value alone", () => {
    expect(formatNumber(12)).toBe("12");
    expect(formatNumber(5.5)).toBe("5.5");
    expect(formatNumber(-3.25)).toBe("-3.25");
  });

  it("renders a bbox triple as a dimension, not as JSON punctuation", () => {
    expect(formatValue([250, 156, 5.5])).toBe("250 × 156 × 5.5");
  });

  it("splits a SCREAMING_SNAKE key into a label and a unit column", () => {
    // "units welded into SCREAMING_SNAKE API keys (`AREA_MM2`, `BBOX_MM`) and
    // shown raw" is one of the four defects §4.7's DataTable retires.
    expect(metricLabel("AREA_MM2")).toBe("area");
    expect(metricUnit("AREA_MM2")).toBe("mm²");
    expect(metricLabel("BBOX_MM")).toBe("bbox");
    expect(metricUnit("BBOX_MM")).toBe("mm");
    expect(metricLabel("volume_mm3")).toBe("volume");
    expect(metricUnit("volume_mm3")).toBe("mm³");
  });

  it("NEVER invents a unit for a key that does not declare one", () => {
    // §1's boundary is about numbers, but a fabricated unit is the same failure
    // in a different column: it would be the client asserting a dimension the
    // server never sent.
    expect(metricUnit("solid_count")).toBeNull();
    expect(metricUnit("watertight")).toBeNull();
    expect(metricLabel("solid_count")).toBe("solid count");
  });

  it("keeps head AND tail of a ref, so two refs cannot collide into one string", () => {
    // `ScriptEditor`'s status bar shipped two DIFFERENT refs both rendered
    // `.slice(-10)`, which collided on the fixture and printed the same hash
    // twice with no labels (§4.7).
    const a = "artifact:build:sha256:aaaaaaaaaaaaaaaaaaaaaaaacbe552b4cf";
    const b = "artifact:render:sha256:bbbbbbbbbbbbbbbbbbbbbbbcbe552b4cf";
    expect(a.slice(-10)).toBe(b.slice(-10));
    expect(formatRef(a)).not.toBe(formatRef(b));
    expect(formatRef("short")).toBe("short");
  });

  it("counts bytes in decimal, because the server counts bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.048 kB");
  });
});

// ---------------------------------------------------------------------------
// useBreakpoint — §4.1(a)'s single authority
// ---------------------------------------------------------------------------

describe("§4.1(a) — one breakpoint authority, and the band it got wrong", () => {
  beforeEach(() => {
    shellStore.reset();
  });

  it("puts each of §4.1's measured widths in the band the table names", () => {
    expect(bandFor(1440)).toBe("wide");
    expect(bandFor(BREAKPOINT_STREAM)).toBe("wide");
    // The band where `Shell.module.css` and `Shell.tsx` disagreed: the column
    // was 44px, the panel's scrollWidth was 81px, and the body overflowed.
    expect(bandFor(BREAKPOINT_STREAM - 1)).toBe("medium");
    expect(bandFor(BREAKPOINT_RAIL)).toBe("medium");
    expect(bandFor(BREAKPOINT_RAIL - 1)).toBe("narrow");
  });

  it("closes the stream and opens the rail as a column in the middle band", () => {
    shellStore.applyWidth(1279);
    const state = shellStore.getSnapshot();
    expect(state.band).toBe("medium");
    // The two facts that used to have two owners now have one, and they agree.
    expect(state.streamOpen).toBe(false);
    expect(state.railOverlay).toBe(false);
  });

  it("overlays the rail below 1024 and opens it CLOSED, with a way back", () => {
    shellStore.applyWidth(900);
    expect(shellStore.getSnapshot().railOverlay).toBe(true);
    expect(shellStore.getSnapshot().railOpen).toBe(false);
    shellStore.setRailOpen(true);
    expect(shellStore.getSnapshot().railOpen).toBe(true);
    shellStore.setRailOpen(false);
    expect(shellStore.getSnapshot().railOpen).toBe(false);
  });

  it("keeps an explicit collapse across a resize INSIDE a band", () => {
    // §4.1(a): "A user's explicit collapse survives a resize inside a band and
    // is re-evaluated on a band crossing."
    shellStore.applyWidth(1440);
    expect(shellStore.getSnapshot().streamOpen).toBe(true);
    shellStore.setStreamOpen(false);
    shellStore.applyWidth(1600);
    expect(shellStore.getSnapshot().streamOpen).toBe(false);
    expect(shellStore.streamHeld()).toBe(true);
  });

  it("re-evaluates on a band CROSSING, and forgets the hold", () => {
    shellStore.applyWidth(1440);
    shellStore.setStreamOpen(false);
    shellStore.applyWidth(1000);
    expect(shellStore.streamHeld()).toBe(false);
    shellStore.applyWidth(1440);
    expect(shellStore.getSnapshot().streamOpen).toBe(true);
  });

  it("clamps the drawer to the band its token default clamps to (§4.1(c))", () => {
    shellStore.setDrawerHeight(10_000);
    expect(shellStore.getSnapshot().drawerHeight).toBe(DRAWER_MAX);
    shellStore.setDrawerHeight(1);
    expect(shellStore.getSnapshot().drawerHeight).toBe(DRAWER_MIN);
    shellStore.setDrawerHeight(null);
    expect(shellStore.getSnapshot().drawerHeight).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// the primitives' markup contracts
// ---------------------------------------------------------------------------

describe("§4.7 — a disabled control always says why", () => {
  it("renders the reason as a title AND as an aria-describedby target", () => {
    const host = render(
      <Button disabled reason={copy.header.holdUnavailable} data-pin-action="hold">
        {copy.pinMode.pinned}
      </Button>,
    );
    const button = host.querySelector("button");
    expect(button?.hasAttribute("disabled")).toBe(false);
    expect(button?.getAttribute("aria-disabled")).toBe("true");
    expect(button?.getAttribute("title")).toBe(copy.header.holdUnavailable);
    const describedBy = button?.getAttribute("aria-describedby") ?? "";
    expect(describedBy).not.toBe("");
    // A `title` is not reachable from the keyboard, and a disabled control is
    // exactly where a keyboard user is stuck. The second carrier is the one that
    // makes the rule mean something.
    const target = host.querySelector(`#${CSS.escape(describedBy)}`);
    expect(target?.textContent).toBe(copy.header.holdUnavailable);
  });

  it("forwards the addressing attributes the gate suite reads", () => {
    const host = render(
      <Button data-visibility-toggle="tread" data-testid="x">
        hide
      </Button>,
    );
    const button = host.querySelector("button");
    expect(button?.getAttribute("data-visibility-toggle")).toBe("tread");
    expect(button?.getAttribute("data-testid")).toBe("x");
  });

  it("marks a toggle pressed, and never marks a plain button", () => {
    expect(
      render(
        <Button variant="toggle" pressed>
          on
        </Button>,
      )
        .querySelector("button")
        ?.getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      render(<Button>go</Button>).querySelector("button")?.getAttribute("aria-pressed"),
    ).toBeNull();
  });

  it("emits aria-expanded on a disclosure, and never aria-pressed", () => {
    const open = render(
      <Button variant="quiet" expanded>
        show
      </Button>,
    ).querySelector("button");
    expect(open?.getAttribute("aria-expanded")).toBe("true");
    expect(open?.getAttribute("aria-pressed")).toBeNull();
    const shut = render(
      <Button variant="quiet" expanded={false}>
        show
      </Button>,
    ).querySelector("button");
    expect(shut?.getAttribute("aria-expanded")).toBe("false");
  });
});

describe("§4.7 — Chip is inert by contract", () => {
  it("renders a span, so it cannot be mistaken for a control", () => {
    // The shipped `DfmPanel.tsx`:225 rendered a read-only project setting as a
    // chip in the panel's ACTION CORNER, looking exactly like a settings toggle,
    // and the prose underneath had to apologise for it. A `<span>` with no
    // `onClick` in its props type makes that arrangement unspellable.
    const host = render(<Chip data-x="1">off</Chip>);
    expect(host.querySelector("span")).not.toBeNull();
    expect(host.querySelector("button")).toBeNull();
  });
});

describe("§4.7 — DataTable carries a ReactNode, never a source string", () => {
  it("renders three columns and forwards the row's addressing attributes", () => {
    const host = render(
      <Panel>
        <PanelHeader title="Metrics" />
        <PanelBody>
          <DataTable
            rows={[
              {
                key: "area",
                label: "area",
                // The real primitive, not a stand-in: `data-source` may only be
                // minted by `<Fact>` (§4.6, and `heph/no-derived-fact` enforces
                // it), so a test that forged one would be asserting against
                // markup the app cannot produce.
                value: (
                  <Fact source="build.metrics[]" value={74289.99999999999}>
                    {formatNumber(74289.99999999999)}
                  </Fact>
                ),
                unit: "mm²",
                attrs: { "data-metric": "AREA_MM2" },
              },
            ]}
          />
        </PanelBody>
      </Panel>,
    );
    const row = host.querySelector('[data-metric="AREA_MM2"]');
    expect(row).not.toBeNull();
    // §1 is untouched: the FORMATTED text is what a reader sees, and the
    // server's own bytes are still what an assertion reads.
    const fact = row?.querySelector("[data-source]");
    expect(fact?.getAttribute("data-value")).toBe("74289.99999999999");
    expect(fact?.textContent).toBe("74290");
    expect(row?.textContent).toContain("mm²");
  });

  it("gives Field the same three-column geometry as a one-row table", () => {
    const host = render(<Field label="process" value={<span>milled</span>} />);
    expect(host.querySelectorAll("dt")).toHaveLength(1);
    expect(host.querySelectorAll("dd")).toHaveLength(1);
  });
});

describe("§4.7 — EmptyState is a composed state, not a grey sentence", () => {
  it("renders an icon, a heading and prose, and an action only when one exists", () => {
    const withAction = render(
      <EmptyState
        icon="cube"
        title={copy.results.notBuiltTitle}
        body={copy.results.notBuilt}
        action={<Button>build</Button>}
      />,
    );
    expect(withAction.querySelector("svg[data-icon]")).not.toBeNull();
    expect(withAction.querySelector("p")?.textContent).toBe(copy.results.notBuiltTitle);
    expect(withAction.querySelector("button")).not.toBeNull();

    const withoutAction = render(
      <EmptyState icon="cube" title={copy.results.notBuiltTitle} body={copy.results.notBuilt} />,
    );
    // "optional `Button`" means optional: an empty state with nothing to do
    // renders no control rather than a decorative one.
    expect(withoutAction.querySelector("button")).toBeNull();
  });
});
