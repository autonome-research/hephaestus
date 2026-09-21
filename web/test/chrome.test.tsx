// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Pin-bound Export / BOM (issue #12). Assertions are on `data-*` and field
// sets, never on UI copy.
//
// REWRITTEN 2026-09-20. This file covered `PartChrome`/`ExportChrome`, the
// header's two pin-bound buttons and the dialog behind them. Both are struck
// (§4.1(i)): the dialog ran the same submission hook as the Export tab over a
// strict subset of its surface, and BOM mounted the very component the Sourcing
// tab mounts. The clauses below are the ones with a subject left, pointed at
// the surface that kept the capability — and the last describe is the strike
// itself, so a header that grows a second egress surface fails here.

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import { EXPORT_FORMATS } from "../src/api/exports";
import { SOURCING_FIELDS } from "../src/api/types";
import { exportBlocker, ExportView } from "../src/components/inspector/ExportPanel";
import { INSPECTOR_TABS } from "../src/state/workspace";

function render(element: ReactElement): Document {
  return new DOMParser().parseFromString(
    `<!doctype html><body>${renderToStaticMarkup(element)}</body>`,
    "text/html",
  );
}

function chrome(
  overrides: Partial<Parameters<typeof ExportView>[0]> = {},
): Document {
  return render(
    <ExportView
      part="tread"
      pinned="artifact:build:sha256:aaaa"
      pinMode="pinned"
      onExport={() => Promise.reject(new Error("not called"))}
      onDownload={() => Promise.reject(new Error("not called"))}
      {...overrides}
    />,
  );
}

describe("Export — bound to the pin", () => {
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
    expect(dom.querySelector("[data-export-run]")?.getAttribute("aria-disabled")).toBe("true");
    expect(dom.querySelector("[data-export-blocked]")?.getAttribute("data-export-blocked")).toBe(
      "no_pin",
    );
  });

  it("uses the same blocker the inspector tab uses", () => {
    expect(exportBlocker("tread", "artifact:build:sha256:a")).toBeNull();
    expect(exportBlocker("tread", null)).toBe("no_pin");
    expect(exportBlocker("tread", "artifact:export:sha256:a")).toBe("invalid_source");
  });

  it("is the inspector tab, which is where the capability now lives", () => {
    expect([...INSPECTOR_TABS]).toEqual(expect.arrayContaining(["export", "sourcing"]));
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
      "src/components/inspector/ExportPanel.tsx",
      "src/copy.ts",
    ];
    for (const file of files) {
      const text = readFileSync(resolve(process.cwd(), file), "utf-8").toLowerCase();
      expect(text, file).not.toContain("sendcutsend");
      expect(text, file).not.toContain("mcmaster");
    }
  });
});

describe("the header grows no second egress surface (§4.1(i), struck 2026-09-20)", () => {
  it("mounts no Export/BOM chrome and keeps no module for one", () => {
    const header = readFileSync(resolve(process.cwd(), "src/components/Header.tsx"), "utf-8");
    // The strike is the assertion: the header renders neither control, and the
    // modules that drew them are gone rather than left orphaned in the tree.
    for (const hook of ["data-part-chrome", "data-chrome-export", "data-chrome-bom"]) {
      expect(header, hook).not.toContain(hook);
    }
    for (const gone of [
      "src/components/chrome/PartChrome.tsx",
      "src/components/chrome/ExportChrome.tsx",
      "src/components/chrome/PartChrome.module.css",
    ]) {
      expect(existsSync(resolve(process.cwd(), gone)), gone).toBe(false);
    }
  });

  it("leaves the capability reachable, on one surface each", () => {
    expect([...INSPECTOR_TABS]).toEqual(expect.arrayContaining(["export", "sourcing"]));
    const panel = readFileSync(resolve(process.cwd(), "src/components/inspector/ExportPanel.tsx"), "utf-8");
    expect(panel).toContain("useExportActions");
    expect(panel).not.toMatch(/data-chrome-overflow|data-chrome-more/);
  });
});
