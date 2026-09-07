// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// PARAMS sliders (INTERFACE.md §10): one control per `GET /parts/{part}/params`
// row, bounds from that projection, no client clamp, rejected[] verbatim.

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import paramsJson from "./fixtures/params.json";
import { keys } from "../src/api/queries";
import { refreshKeys } from "../src/api/refresh";
import type { ParamRejection, ParamsDocument } from "../src/api/types";
import {
  controlStep,
  isIntegerParam,
  keysAfterParamCommit,
  ParamSlidersView,
} from "../src/components/stage/ParamSliders";
import { Slider } from "../src/system";

const paramsDoc = paramsJson as ParamsDocument;

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

describe("the projection is the inventory", () => {
  it("renders one slider per params row and no invented name", () => {
    const host = render(
      <ParamSlidersView
        part="tread"
        document={paramsDoc}
        draft={{}}
        rejected={[]}
        conflict={false}
        committing={false}
        placeholder={false}
        onDraft={() => undefined}
        onRelease={() => undefined}
      />,
    );
    const sliders = [...host.querySelectorAll("[data-param-slider]")];
    expect(sliders.map((node) => node.getAttribute("data-param-slider"))).toEqual(
      paramsDoc.params.map((row) => row.name),
    );
    expect(host.querySelector("[data-param='width']")).toBeNull();
    const row = paramsDoc.params[0];
    expect(row).toBeDefined();
    if (row === undefined) return;
    expect(host.querySelector('[data-source="params[].value"]')?.getAttribute("data-value")).toBe(
      String(row.value),
    );
    expect(host.querySelector('[data-source="params[].min"]')?.getAttribute("data-value")).toBe(
      String(row.min),
    );
    expect(host.querySelector('[data-source="params[].max"]')?.getAttribute("data-value")).toBe(
      String(row.max),
    );
    expect(host.querySelector('[data-source="params.state_hash"]')?.getAttribute("data-value")).toBe(
      paramsDoc.state_hash,
    );
  });

  it("uses the integer type as the control step when the server sent null", () => {
    const row = paramsDoc.params[0];
    expect(row).toBeDefined();
    if (row === undefined) return;
    expect(row.step).toBeNull();
    expect(isIntegerParam(row)).toBe(true);
    expect(controlStep(row)).toBe(1);
  });
});

describe("G5.3 — rejected[] is verbatim, and the primitive does not clamp", () => {
  it("renders each rejected entry beside its control", () => {
    const rejected: readonly ParamRejection[] = [
      { name: "groove_count", reason: "out_of_bounds", value: 11, min: 2, max: 10 },
    ];
    const host = render(
      <ParamSlidersView
        part="tread"
        document={paramsDoc}
        draft={{ groove_count: 11 }}
        rejected={rejected}
        conflict={false}
        committing={false}
        placeholder={false}
        onDraft={() => undefined}
        onRelease={() => undefined}
      />,
    );
    const message = host.querySelector("[data-param='groove_count'] p");
    expect(message?.textContent).toContain("out_of_bounds");
    expect(message?.textContent).toContain("11");
    expect(message?.textContent).toContain("2");
    expect(message?.textContent).toContain("10");
  });

  it("the number input has no min/max when clamp is off, so a typed 11 can leave", () => {
    const host = render(
      <Slider label="groove_count" min={2} max={10} step={1} value={11} clamp={false} onChange={() => undefined} />,
    );
    const number = host.querySelector('input[type="number"]');
    expect(number?.getAttribute("min")).toBeNull();
    expect(number?.getAttribute("max")).toBeNull();
    expect((number as HTMLInputElement | null)?.value).toBe("11.00");
  });
});

describe("a slider write refreshes the inspector, not just params and build", () => {
  it("a successful rebuild invalidates the refreshKeys set", () => {
    // The two ad-hoc keys (params + build) would leave Results / Checks / DFM
    // / properties showing the pre-rebuild projection.
    expect(keysAfterParamCommit("tread", true)).toEqual(refreshKeys("tread"));
    expect(keysAfterParamCommit("tread", true)).toEqual(
      expect.arrayContaining([
        keys.properties("tread"),
        keys.checks("tread"),
        keys.dfm("tread"),
      ]),
    );
  });

  it("a conflict invalidates only the params projection", () => {
    expect(keysAfterParamCommit("tread", false)).toEqual([keys.params("tread")]);
  });
});

// ---------------------------------------------------------------------------
// J-cli-startup-8 — the Script tab's "Loading parameters…" full-panel
// replacement, on a part switch that hits a slow (server-side) params read.
// ---------------------------------------------------------------------------

describe("placeholder rendering keeps the panel's layout instead of a blocking note (J-cli-startup-8)", () => {
  function placeholderView(overrides: Partial<Parameters<typeof ParamSlidersView>[0]> = {}) {
    return (
      <ParamSlidersView
        part="tread"
        document={paramsDoc}
        draft={{}}
        rejected={[]}
        conflict={false}
        committing={false}
        placeholder
        onDraft={() => undefined}
        onRelease={() => undefined}
        {...overrides}
      />
    );
  }

  it("mounts the panel and its header, not a bare loading string, while placeholder data is showing", () => {
    const host = render(placeholderView());
    expect(host.querySelector('[data-panel="params"]')).not.toBeNull();
    expect(host.querySelector('[data-params-placeholder]')).not.toBeNull();
    // The panel keeps its shape: a row per the RETAINED (previous part's) row
    // count, not a full-panel replacement note.
    expect(host.querySelectorAll("li").length).toBe(paramsDoc.params.length);
  });

  it("mounts no interactive Slider while placeholder data is showing — nothing here is commit-eligible", () => {
    const host = render(placeholderView());
    // A placeholder row set carries the PREVIOUS part's `state_hash`; a control
    // that could commit against it would send a write under an expectation
    // that belongs to a different part, or matches nothing at all.
    expect(host.querySelectorAll("[data-param-slider]")).toHaveLength(0);
    expect(host.querySelectorAll('input[type="range"]')).toHaveLength(0);
  });

  it("marks the list busy for assistive tech rather than swapping in a blocking note", () => {
    const host = render(placeholderView());
    const list = host.querySelector("ul");
    expect(list?.getAttribute("aria-busy")).toBe("true");
  });

  it("renders the normal interactive list once placeholder clears, with the same document", () => {
    const host = render(placeholderView({ placeholder: false }));
    expect(host.querySelector('[data-params-placeholder]')).toBeNull();
    expect(host.querySelectorAll("[data-param-slider]").length).toBe(paramsDoc.params.length);
  });
});
