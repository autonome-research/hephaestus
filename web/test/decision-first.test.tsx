// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DfmView } from "../src/components/inspector/DfmPanel";
import { ChecksView } from "../src/components/inspector/ChecksPanel";
import type { DfmDocument, ChecksDocument } from "../src/api/types";
import dfmJson from "./fixtures/dfm.json";
import checksJson from "./fixtures/checks.json";
const dfm = dfmJson as DfmDocument;
function render(doc = dfm, ref: string | null | undefined = dfm.last!.source_artifact_ref) {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<DfmView dfm={doc} currentArtifactRef={ref} />);
  return host;
}
describe("decision-first inspection without invented verdicts", () => {
  it("orders known outcome/count and first finding ahead of closed provenance, retaining every bound/topology", () => {
    const host = render();
    const decision = host.querySelector("[data-dfm-decision]")!;
    const first = host.querySelector("[data-dfm-finding]")!;
    const provenance = host.querySelector("[data-dfm-provenance]")!;
    expect(decision.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(first.compareDocumentPosition(provenance) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(provenance.hasAttribute("open")).toBe(false);
    expect(host.querySelectorAll("[data-dfm-finding]")).toHaveLength(dfm.last!.findings.length);
    expect(host.querySelectorAll("[data-finding-bound]")).toHaveLength(dfm.last!.findings.filter(f => f.suggested_bound !== null).length);
    expect(host.querySelectorAll("[data-dfm-descriptor]")).toHaveLength(dfm.last!.findings.flatMap(f => f.topology).length);
    expect(provenance.textContent).toContain(dfm.last!.source_artifact_ref);
    expect(host.querySelector("h3")?.textContent).toContain("current artifact");
    expect(render(dfm, "different-build").querySelector("h3")?.textContent).toContain("stale result");
    expect(render(dfm, null).querySelector("h3")?.textContent).toContain("stale result");
  });
  it("keeps unknown, unevaluated, incomplete, rule error and clean evidence distinct", () => {
    const empty = { ...dfm, last: { ...dfm.last!, findings: [], severity_counts: {}, rules: [], errored_rules: [], truncated: false } };
    expect(render(empty).querySelector("[data-dfm-decision]")?.textContent).toBe("Evaluation summary unavailable");
    expect(render(empty).textContent).not.toContain("reported no findings");
    const missingDetails = render({ ...empty, last: { ...empty.last, severity_counts: { error: 4 } } });
    expect(missingDetails.querySelector("[data-dfm-decision]")?.textContent).toBe("Findings reported");
    expect(missingDetails.textContent).toContain("details are unavailable");
    expect(missingDetails.textContent).not.toContain("reported no findings");
    expect(render({ ...dfm, last: null }).textContent).toContain("Not evaluated");
    for (const last of [{ ...empty.last, errored_rules: ["broken-rule"] }, { ...empty.last, truncated: true }]) {
      const host = render({ ...empty, last });
      expect(host.querySelector("[data-dfm-decision]")?.textContent).toBe("Evaluation incomplete");
      expect(host.textContent).not.toContain("reported no findings");
    }
    const clean = { ...empty, last: { ...empty.last, rules: [{ rule_id: "known", title: "Known", severity: "error", status: "ok" as const, findings: [], params: {}, error: null }] } };
    expect(render(clean).querySelector("[data-dfm-decision]")?.textContent).toBe("No findings");
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<DfmView dfm={dfm} />);
    expect(host.querySelector("h3")?.textContent).toContain("artifact relation unknown");
  });
  it("orders supplied check errors before passes, not measured-value-derived verdicts", () => {
    const host = document.createElement("div");
    const checks = { ...checksJson, badges: { a_pass: "pass", z_error: "error", b_fail: "fail", c_unknown: "not_run" } } as ChecksDocument;
    host.innerHTML = renderToStaticMarkup(<ChecksView checks={checks} />);
    expect([...host.querySelectorAll("[data-check]")].map(el => el.getAttribute("data-check"))).toEqual(["z_error", "b_fail", "c_unknown", "a_pass"]);
    expect(host.querySelector("[data-checks-summary]")?.textContent).toBe("1 error · 1 fail · 1 not run · 1 pass");
    expect(host.querySelector("[data-checks-provenance]")?.hasAttribute("open")).toBe(false);
  });
});
