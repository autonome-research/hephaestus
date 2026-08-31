// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Pin-bound Export / BOM chrome (issue #12). Assertions are on `data-*` and
// field sets, never on UI copy.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import { EXPORT_FORMATS } from "../src/api/exports";
import { SOURCING_FIELDS } from "../src/api/types";
import { ExportChrome } from "../src/components/chrome/ExportChrome";
import { exportBlocker } from "../src/components/inspector/ExportPanel";
import { INSPECTOR_TABS } from "../src/state/workspace";

function render(element: ReactElement): Document {
  return new DOMParser().parseFromString(
    `<!doctype html><body>${renderToStaticMarkup(element)}</body>`,
    "text/html",
  );
}

function chrome(
  overrides: Partial<Parameters<typeof ExportChrome>[0]> = {},
): Document {
  return render(
    <ExportChrome
      part="tread"
      pinned="artifact:build:sha256:aaaa"
      pinMode="pinned"
      onExport={() => Promise.reject(new Error("not called"))}
      onOpenInspector={() => undefined}
      {...overrides}
    />,
  );
}

describe("Export chrome — bound to the pin", () => {
  it("lives in a panel that is not the inspector export tab", () => {
    const dom = chrome();
    expect(dom.querySelector("[data-panel='export-chrome']")).not.toBeNull();
    expect(dom.querySelector("[data-panel='export']")).toBeNull();
  });

  it("renders its subject before any format button", () => {
    const dom = chrome();
    const subject = dom.querySelector("[data-source='workspace.artifact_ref']");
    const firstFormat = dom.querySelector("[data-export-format]");
    expect(subject).not.toBeNull();
    expect(firstFormat).not.toBeNull();
    expect(
      (subject?.compareDocumentPosition(firstFormat as Node) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("carries the pin and its mode as server values", () => {
    const dom = chrome();
    expect(dom.querySelector("[data-source='workspace.artifact_ref']")?.getAttribute("data-value")).toBe(
      "artifact:build:sha256:aaaa",
    );
    expect(dom.querySelector("[data-export-pin-mode]")?.getAttribute("data-export-pin-mode")).toBe(
      "pinned",
    );
  });

  it("offers exactly the six formats export_part declares", () => {
    const buttons = [...chrome().querySelectorAll("button[data-export-format]")].map((node) =>
      node.getAttribute("data-export-format"),
    );
    expect(buttons).toEqual([...EXPORT_FORMATS]);
  });

  it("disables the run control when there is no pin", () => {
    const dom = chrome({ pinned: null });
    expect(dom.querySelector("[data-export-run]")?.hasAttribute("disabled")).toBe(true);
    expect(dom.querySelector("[data-export-blocked]")?.getAttribute("data-export-blocked")).toBe(
      "no_pin",
    );
  });

  it("uses the same blocker the inspector tab uses", () => {
    expect(exportBlocker("tread", "artifact:build:sha256:a")).toBeNull();
    expect(exportBlocker("tread", null)).toBe("no_pin");
    expect(exportBlocker("tread", "artifact:export:sha256:a")).toBe("invalid_source");
  });

  it("offers a door to the inspector tab without replacing it", () => {
    expect(chrome().querySelector("[data-chrome-open-inspector='export']")).not.toBeNull();
    expect([...INSPECTOR_TABS]).toContain("export");
  });
});

describe("sourcing field set — declared manufacturing identity only", () => {
  it("is a closed subset of part.* and does not invent conform_to", () => {
    expect([...SOURCING_FIELDS]).toEqual(["process", "stock_form", "blank_size", "material_spec"]);
    expect(SOURCING_FIELDS.includes("process")).toBe(true);
    const source = readFileSync(resolve(process.cwd(), "src/api/types.ts"), "utf-8");
    const block = source.slice(
      source.indexOf("export const SOURCING_FIELDS"),
      source.indexOf("export type SourcingField"),
    );
    expect(block).not.toContain("conform_to");
    expect(block).not.toContain("description");
  });

  it("names no vendor catalog in the sourcing or chrome modules", () => {
    const files = [
      "src/components/inspector/SourcingPanel.tsx",
      "src/components/chrome/PartChrome.tsx",
      "src/components/chrome/ExportChrome.tsx",
      "src/copy.ts",
    ];
    for (const file of files) {
      const text = readFileSync(resolve(process.cwd(), file), "utf-8").toLowerCase();
      expect(text, file).not.toContain("sendcutsend");
      expect(text, file).not.toContain("mcmaster");
    }
  });
});
