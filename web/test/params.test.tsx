// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// PARAMS sliders (INTERFACE.md §10): one control per `GET /parts/{part}/params`
// row, bounds from that projection, no client clamp, rejected[] verbatim.

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import paramsJson from "./fixtures/params.json";
import type { ParamRejection, ParamsDocument } from "../src/api/types";
import {
  controlStep,
  isIntegerParam,
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
