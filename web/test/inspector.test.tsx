// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The inspector's five panels, asserted **field for field against recorded
// response documents** (INTERFACE.md §6).
//
// Every fixture in `test/fixtures/` came out of a real `server/http` app
// (`scripts/record_web_fixtures.py`; see that directory's README for the three
// that are not pure route output and why). That is the whole point: §1 makes
// each displayed fact carry the response field it was read from, and a test
// written against a hand-authored idea of the wire would assert only that the
// client agrees with itself.
//
// What is asserted here, and what is deliberately left to `pnpm test:e2e`:
//
// * HERE — the mapping from one document to one DOM fragment: set equality of
//   `data-field` against the projection's keys, one row per `geometries` entry,
//   a `data-value` equal to the JSON value it names, the four badge states, the
//   descriptor rendered instead of a bare index, §4.4's three provenance shapes.
// * THERE — anything requiring a live server, a browser, or pixels: the DOM
//   against a *fetched* document, `heph check --json` byte-parity, the
//   visibility toggle's effect on the viewport.
//
// No assertion is on a string of UI copy (§3 forbids tests on wording). Where a
// *visible distinction* is the obligation — "`not_run` renders as its own
// visible state", "a weak provenance answer says why it is weak" — the assertion
// is that two states render **different** text, never that either says any
// particular words.

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import buildJson from "./fixtures/build.json";
import checksJson from "./fixtures/checks.json";
import checksNotRunJson from "./fixtures/checks_not_run.json";
import dfmJson from "./fixtures/dfm.json";
import dfmAbsentJson from "./fixtures/dfm_absent.json";
import dfmPreviewJson from "./fixtures/dfm_preview.json";
import propertiesJson from "./fixtures/properties.json";
import provenanceOwnedJson from "./fixtures/provenance_owned.json";
import provenanceTaggedJson from "./fixtures/provenance_tagged.json";
import provenanceUnattributedJson from "./fixtures/provenance_unattributed.json";

import { visibilityKey } from "../src/state/visibility";
import { ResultsView } from "../src/components/inspector/ResultsPanel";
import { PropertiesView } from "../src/components/inspector/PropertiesPanel";
import { SourcingView } from "../src/components/inspector/SourcingPanel";
import { ChecksView } from "../src/components/inspector/ChecksPanel";
import { DfmView } from "../src/components/inspector/DfmPanel";
import { ProvenanceView } from "../src/components/inspector/ProvenancePanel";
import {
  SOURCING_FIELDS,
  type BuildDocument,
  type ChecksDocument,
  type DfmDocument,
  type PropertiesDocument,
  type ResolvedSelection,
} from "../src/api/types";

// The fixtures are JSON, so they arrive structurally typed. Each is asserted
// against the interface the client reads it through — a fixture that stopped
// matching its wire type would fail to compile, which is the earliest place the
// drift could possibly be caught.
const build = buildJson as BuildDocument;
const properties = propertiesJson as PropertiesDocument;
const checks = checksJson as ChecksDocument;
const checksNotRun = checksNotRunJson as ChecksDocument;
const dfm = dfmJson as DfmDocument;
const dfmPreview = dfmPreviewJson as DfmDocument;
const dfmAbsent = dfmAbsentJson as DfmDocument;
const tagged = provenanceTaggedJson as ResolvedSelection;
const owned = provenanceOwnedJson as ResolvedSelection;
const unattributed = provenanceUnattributedJson as ResolvedSelection;

/** Render one panel to a detached document fragment and query it. */
function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

/** Every `data-value` under one `data-source` path, in document order. */
function values(host: HTMLElement, source: string): string[] {
  return [...host.querySelectorAll(`[data-source="${source}"]`)].map(
    (node) => node.getAttribute("data-value") ?? "",
  );
}

/** The single `data-value` at one path. Fails loudly if there is not exactly one. */
function value(host: HTMLElement, source: string): string {
  const found = values(host, source);
  expect(found, `expected exactly one ${source}`).toHaveLength(1);
  return found[0] ?? "";
}

function attributes(host: HTMLElement, selector: string, name: string): string[] {
  return [...host.querySelectorAll(selector)].map((node) => node.getAttribute(name) ?? "");
}

// ---------------------------------------------------------------------------
// §1 — the boundary, asserted over every panel at once
// ---------------------------------------------------------------------------

describe("the §1 attribution discipline holds in every panel", () => {
  const panels: Record<string, ReactElement> = {
    results: <ResultsView part="panel" build={build} hidden={new Set()} />,
    properties: <PropertiesView properties={properties} />,
    sourcing: <SourcingView properties={properties} pinned={build.artifact_ref ?? null} />,
    checks: <ChecksView checks={checks} />,
    dfm: <DfmView dfm={dfm} secureExecutor />,
    provenance: <ProvenanceView pinned={build.artifact_ref ?? null} resolved={tagged} />,
  };

  it("gives every displayed fact a data-value beside its data-source", () => {
    for (const [name, element] of Object.entries(panels)) {
      const host = render(element);
      const attributed = [...host.querySelectorAll("[data-source]")];
      expect(attributed.length, `${name} displays no attributed fact at all`).toBeGreaterThan(0);
      for (const node of attributed) {
        expect(node.hasAttribute("data-value"), `${name}: ${node.outerHTML}`).toBe(true);
      }
    }
  });

  it("names a dotted response path in every attribution", () => {
    // §4.6: `data-source` names the HTTP response *field*, so an assertion can
    // index the JSON with it. A bare word would name a concept instead.
    const path = /^[A-Za-z_][\w[\]]*(\.[\w[\]]+)+$/;
    for (const [name, element] of Object.entries(panels)) {
      for (const source of attributes(render(element), "[data-source]", "data-source")) {
        expect(path.test(source), `${name}: ${source}`).toBe(true);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// §6.1 / §5.4 — Results
// ---------------------------------------------------------------------------

describe("ResultsView renders the build result (§6.1)", () => {
  it("renders exactly one row per geometries entry, in server order", () => {
    const host = render(<ResultsView part="panel" build={build} hidden={new Set()} />);
    const rows = [...host.querySelectorAll("[data-geometry-row]")];
    // §6.1's TIGHTENING: the count is the SERVER's explicit field, and the row
    // count is compared to it — never to `geometries.length` computed here.
    expect(rows).toHaveLength(build.geometry_count);
    expect(rows.map((r) => r.getAttribute("data-geometry-index"))).toEqual(
      build.geometries.map((_, index) => String(index)),
    );
    expect(rows.map((r) => r.getAttribute("data-geometry-label"))).toEqual(
      build.geometries.map((entry) => entry.label),
    );
  });

  it("reads the count off the response field rather than recounting rows", () => {
    const host = render(<ResultsView part="panel" build={build} hidden={new Set()} />);
    expect(value(host, "build.geometry_count")).toBe(String(build.geometry_count));
  });

  it("attributes every geometry label and solid count to its own field", () => {
    const host = render(<ResultsView part="panel" build={build} hidden={new Set()} />);
    expect(values(host, "build.geometries[].label")).toEqual(
      build.geometries.map((entry) => entry.label),
    );
    expect(values(host, "build.geometries[].solids")).toEqual(
      build.geometries.map((entry) => String(entry.solids)),
    );
  });

  it("renders every metric the result carries, and no metric it does not", () => {
    const host = render(<ResultsView part="panel" build={build} hidden={new Set()} />);
    const metrics = build.metrics ?? {};
    expect(new Set(attributes(host, "[data-metric]", "data-metric"))).toEqual(
      new Set(Object.keys(metrics)),
    );
    const rendered = values(host, "build.metrics[]");
    const expected = Object.keys(metrics)
      .sort()
      .map((name) => {
        const raw: unknown = metrics[name];
        return typeof raw === "number" || typeof raw === "boolean" || typeof raw === "string"
          ? String(raw)
          : JSON.stringify(raw);
      });
    expect(rendered).toEqual(expected);
  });

  it("marks a hidden entry without changing any number it reports (§5.4)", () => {
    const first = build.geometries[0];
    expect(first).toBeDefined();
    const label = first?.label ?? "";
    const shown = render(<ResultsView part="panel" build={build} hidden={new Set()} />);
    // Amendment (§5.4, viewport task): the key was spelled `` `panel ${label}` ``
    // here — a *space* where `state/visibility.ts::key` uses U+0000. The panel
    // read the same wrong key, so the two agreed and this assertion passed while
    // a real click hid nothing (the toggle wrote a NUL key the reader never
    // looked for). Both now call `visibilityKey`, which is the only place the
    // separator is spelled. The assertion is unchanged in strength; only the key
    // it builds is now the one the store actually uses.
    const hidden = render(
      <ResultsView part="panel" build={build} hidden={new Set([visibilityKey("panel", label)])} />,
    );
    expect(attributes(shown, "[data-geometry-row]", "data-visible")).toEqual(
      build.geometries.map(() => "true"),
    );
    expect(attributes(hidden, "[data-geometry-row]", "data-visible")).toEqual(
      build.geometries.map((entry) => (entry.label === label ? "false" : "true")),
    );
    // Hiding is a scene-graph property: every fact the panel reports is the same
    // before and after, which is the claim the note in the panel makes.
    expect(values(hidden, "build.geometry_count")).toEqual(values(shown, "build.geometry_count"));
    expect(values(hidden, "build.metrics[]")).toEqual(values(shown, "build.metrics[]"));
  });

  it("names the absence when a part has no current build", () => {
    const notBuilt: BuildDocument = {
      status: "not_built",
      current: false,
      geometry_count: 0,
      geometries: [],
    };
    const host = render(<ResultsView part="panel" build={notBuilt} hidden={new Set()} />);
    expect(host.querySelectorAll("[data-geometry-row]")).toHaveLength(0);
    expect(host.textContent?.trim()).not.toBe("");
  });
});

// ---------------------------------------------------------------------------
// §6.2 — Properties
// ---------------------------------------------------------------------------

describe("PropertiesView renders the part.* metadata (§6.2)", () => {
  const host = render(<PropertiesView properties={properties} />);

  it("marks exactly the projection's keys with data-field", () => {
    // §6.2 assertion (1), the half that lives in the DOM: SET EQUALITY, because
    // containment would be satisfied by rendering one field.
    expect(new Set(attributes(host, "[data-field]", "data-field"))).toEqual(
      new Set(Object.keys(properties.properties)),
    );
  });

  it("renders each declared field's value under its own dotted path", () => {
    for (const [field, expected] of Object.entries(properties.properties)) {
      expect(value(host, `properties.${field}`)).toBe(expected);
    }
  });

  it("never falls back to the indexed path for a declared vocabulary name", () => {
    // The nine `<Fact source="properties.<key>">` literals are written out
    // because §1's lint requires a static attribution and §6.2 requires a
    // per-key one. This asserts the enumeration is complete against the
    // SERVER's vocabulary rather than against the client's copy of it.
    const each = render(
      <PropertiesView
        properties={{
          ...properties,
          properties: Object.fromEntries(properties.fields.map((field) => [field, "x"])),
        }}
      />,
    );
    expect(values(each, "properties[].value")).toEqual([]);
    for (const field of properties.fields) {
      expect(value(each, `properties.${field}`)).toBe("x");
    }
  });

  it("shows an undeclared field as a visible absence, outside the data-field set", () => {
    const undeclared = properties.fields.filter((field) => !(field in properties.properties));
    expect(undeclared.length, "the fixture declares every field; the absence path is untested").
      toBeGreaterThan(0);
    expect(new Set(attributes(host, "[data-undeclared-field]", "data-undeclared-field"))).toEqual(
      new Set(undeclared),
    );
  });

  it("reports which read answered, and the artifact it was evaluated with", () => {
    expect(host.querySelector("[data-properties-source]")?.getAttribute("data-properties-source"))
      .toBe(properties.source);
    expect(value(host, "properties.source")).toBe(properties.source);
    expect(value(host, "properties.build_artifact_ref")).toBe(properties.build_artifact_ref ?? "");
  });

  it("carries a value the static script parse could not have produced", () => {
    // The recorded fixture's `blank_size` is an f-string in the script, so its
    // presence here is the whole of G4.3's "from the script": a literal-only
    // read reports the field as missing.
    expect(properties.source).toBe("build_record");
    expect(properties.properties.blank_size).toBeDefined();
    expect(value(host, "properties.blank_size")).toBe(properties.properties.blank_size);
  });

  it("names the weaker read when there is no build record behind it", () => {
    const weak = render(
      <PropertiesView
        properties={{ ...properties, source: "script_literals", build_artifact_ref: null }}
      />,
    );
    expect(values(weak, "properties.build_artifact_ref")).toEqual([]);
    expect(weak.querySelector("[data-properties-source]")?.getAttribute("data-properties-source"))
      .toBe("script_literals");
    // The two reads mean different things, so they must not read identically.
    expect(weak.textContent).not.toBe(host.textContent);
  });
});

// ---------------------------------------------------------------------------
// Sourcing — declared manufacturing identity only (issue #12)
// ---------------------------------------------------------------------------

describe("SourcingView reads only declared process / stock / material spec", () => {
  const pin = properties.build_artifact_ref;
  const host = render(<SourcingView properties={properties} pinned={pin} />);
  const declaredSourcing = SOURCING_FIELDS.filter((field) => field in properties.properties);

  it("marks exactly the declared sourcing fields with data-field", () => {
    expect(new Set(attributes(host, "[data-field]", "data-field"))).toEqual(new Set(declaredSourcing));
  });

  it("does not render description, finish, or other non-sourcing part.* names as fields", () => {
    const fields = new Set(attributes(host, "[data-field]", "data-field"));
    expect(fields.has("description")).toBe(false);
    expect(fields.has("finish")).toBe(false);
    expect(fields.has("joint")).toBe(false);
    expect(fields.has("assembly_method")).toBe(false);
    expect(fields.has("general_tolerance")).toBe(false);
  });

  it("renders each declared sourcing value under its own dotted path", () => {
    for (const field of declaredSourcing) {
      expect(value(host, `properties.${field}`)).toBe(properties.properties[field]);
    }
  });

  it("binds the readout to the workspace pin and the properties artifact", () => {
    expect(value(host, "workspace.artifact_ref")).toBe(pin ?? "");
    expect(value(host, "properties.build_artifact_ref")).toBe(properties.build_artifact_ref ?? "");
  });

  it("says there is no catalog, as an attribute rather than as wording", () => {
    expect(host.querySelector("[data-sourcing-catalog='none']")).not.toBeNull();
  });

  it("shows undeclared sourcing fields as a visible absence, outside data-field", () => {
    const thin: PropertiesDocument = {
      ...properties,
      properties: { process: "laser_cut" },
    };
    const sparse = render(<SourcingView properties={thin} pinned={pin} />);
    expect(attributes(sparse, "[data-field]", "data-field")).toEqual(["process"]);
    expect(new Set(attributes(sparse, "[data-undeclared-field]", "data-undeclared-field"))).toEqual(
      new Set(SOURCING_FIELDS.filter((field) => field !== "process")),
    );
  });

  it("is empty-honest when none of the sourcing fields are declared", () => {
    const none: PropertiesDocument = { ...properties, properties: { description: "a vent" } };
    const empty = render(<SourcingView properties={none} pinned={null} />);
    expect(empty.querySelector("[data-field]")).toBeNull();
    expect(empty.querySelector("[data-source='workspace.artifact_ref']")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// §6.3 — Checks
// ---------------------------------------------------------------------------

describe("ChecksView renders the report's own badges (§6.3)", () => {
  const host = render(<ChecksView checks={checks} />);

  it("renders one row per badge, badged with the server's word", () => {
    const rows = [...host.querySelectorAll("[data-check]")];
    expect(rows.map((row) => row.getAttribute("data-check")).sort()).toEqual(
      Object.keys(checks.badges).sort(),
    );
    for (const row of rows) {
      const name = row.getAttribute("data-check") ?? "";
      expect(row.getAttribute("data-badge")).toBe(checks.badges[name]);
    }
    expect(values(host, "checks.badges[]").sort()).toEqual(
      Object.keys(checks.badges)
        .sort()
        .map((name) => checks.badges[name] ?? ""),
    );
  });

  it("covers the three badge states a run can reach, from one recorded run", () => {
    const reached = new Set(Object.values(checks.badges));
    expect(reached).toEqual(new Set(["pass", "fail", "error"]));
  });

  it("never turns an unevaluable check into a failure", () => {
    // `measured.error` is a predicate that RAISED. §6.3 closes the vocabulary at
    // four and `error` outranks `fail`, because a check with no verdict must not
    // be reported as having reached one.
    for (const [name, result] of Object.entries(checks.report.checks)) {
      const measured = result.measured;
      const unevaluable =
        typeof measured === "object" &&
        measured !== null &&
        ("error" in measured || "unverifiable" in measured);
      if (unevaluable) expect(checks.badges[name]).toBe("error");
    }
  });

  it("renders each check's measured value as the report carries it", () => {
    for (const name of Object.keys(checks.badges).sort()) {
      const result = checks.report.checks[name];
      if (result === undefined) continue;
      // REPOINTED, and the amendment is §4.7's `Badge` clause: `data-badge` is
      // emitted "on the element it styles", and G4.4's e2e reads `data-check`
      // and `data-badge` **off the same node** — so `data-check` now sits on the
      // badge rather than on the `<li>` around it. The assertion itself is
      // unchanged; only the walk from the check's name to its row is, and the
      // row is still the element the measured value lives in.
      const badge = host.querySelector(`[data-check="${name}"]`);
      const row = badge?.closest("li") ?? null;
      expect(row?.querySelector('[data-source="checks.report.checks[].measured"]')
        ?.getAttribute("data-value")).toBe(JSON.stringify(result.measured));
    }
  });

  it("renders not_run as its own visible state, with no measurement", () => {
    const notRun = render(<ChecksView checks={checksNotRun} />);
    const names = Object.entries(checksNotRun.badges)
      .filter(([, badge]) => badge === "not_run")
      .map(([name]) => name);
    expect(names.length, "the fixture reaches no not_run badge").toBeGreaterThan(0);
    for (const name of names) {
      const row = notRun.querySelector(`[data-check="${name}"]`);
      expect(row?.getAttribute("data-badge")).toBe("not_run");
      // A check the run did not reach has nothing measured, and the panel shows
      // no measurement rather than an empty one.
      expect(row?.querySelector('[data-source="checks.report.checks[].measured"]')).toBeNull();
      // §6.3's obligation is that silence never reads as a pass: the state is
      // visible and it does not read like the passing row. The assertion is on
      // the distinction, never on the words.
      const passing = notRun.querySelector('[data-badge="pass"]');
      expect(row?.textContent?.trim()).not.toBe("");
      expect(row?.textContent).not.toBe(passing?.textContent);
    }
  });

  it("attributes the bundle ref and generation the report was produced under", () => {
    expect(value(host, "checks.report.check_bundle_ref")).toBe(checks.report.check_bundle_ref);
    expect(value(host, "checks.report.check_set_generation")).toBe(
      String(checks.report.check_set_generation),
    );
  });
});

// ---------------------------------------------------------------------------
// §6.4 — DFM
// ---------------------------------------------------------------------------

describe("DfmView renders a run_dfm result (§6.4)", () => {
  const host = render(<DfmView dfm={dfm} secureExecutor />);
  const run = dfm.last;

  it("has a recorded run to assert against", () => {
    expect(run).not.toBeNull();
  });

  it("renders the run's header facts: process, pack, registry, material", () => {
    if (run === null) return;
    expect(value(host, "dfm.last.process")).toBe(run.process);
    expect(value(host, "dfm.last.pack.name")).toBe(run.pack.name);
    expect(value(host, "dfm.last.pack.version")).toBe(run.pack.version);
    expect(value(host, "dfm.last.pack.registry")).toBe(run.pack.registry);
    expect(value(host, "dfm.last.pack.registry_digest")).toBe(run.pack.registry_digest);
    expect(value(host, "dfm.last.source_artifact_ref")).toBe(run.source_artifact_ref);
    expect(value(host, "dfm.auto_run")).toBe(String(dfm.auto_run));
    if (run.material !== null) {
      expect(value(host, "dfm.last.material.name")).toBe(String(run.material["name"]));
    }
  });

  it("renders the severity counts the run reported", () => {
    if (run === null) return;
    const names = Object.keys(run.severity_counts).sort();
    expect(values(host, "dfm.last.severity_counts[]")).toEqual(
      names.map((severity) => String(run.severity_counts[severity])),
    );
    expect(attributes(host, "[data-severity]", "data-severity")).toContain(names[0]);
  });

  it("renders one finding per finding, with every field §6.4 enumerates", () => {
    if (run === null) return;
    const findings = [...host.querySelectorAll("[data-dfm-finding]")];
    expect(findings).toHaveLength(run.findings.length);
    expect(values(host, "dfm.last.findings[].rule_id")).toEqual(
      run.findings.map((finding) => finding.rule_id),
    );
    expect(values(host, "dfm.last.findings[].severity")).toEqual(
      run.findings.map((finding) => finding.severity),
    );
    expect(values(host, "dfm.last.findings[].title")).toEqual(
      run.findings.map((finding) => finding.title),
    );
    expect(values(host, "dfm.last.findings[].message")).toEqual(
      run.findings.map((finding) => finding.message),
    );
    expect(values(host, "dfm.last.findings[].measured")).toEqual(
      run.findings.map((finding) => JSON.stringify(finding.measured)),
    );
    expect(values(host, "dfm.last.findings[].bound_unit")).toEqual(
      run.findings.filter((f) => f.suggested_bound !== null).map((f) => f.bound_unit),
    );
    expect(values(host, "dfm.last.findings[].suggested_bound")).toEqual(
      run.findings
        .filter((f) => f.suggested_bound !== null)
        .map((f) => String(f.suggested_bound)),
    );
    expect(values(host, "dfm.last.findings[].tags[]")).toEqual(
      run.findings.flatMap((finding) => [...finding.tags]),
    );
  });

  it("renders a topology descriptor, never a bare index (§6.4, G6)", () => {
    if (run === null) return;
    const expected = run.findings.flatMap((finding) => finding.topology);
    expect(expected.length, "no finding in the fixture carries topology").toBeGreaterThan(0);
    const descriptors = [...host.querySelectorAll("[data-dfm-descriptor]")];
    expect(descriptors).toHaveLength(expected.length);
    descriptors.forEach((node, index) => {
      const descriptor = expected[index];
      expect(node.getAttribute("data-descriptor-kind")).toBe(descriptor?.kind);
      expect(node.getAttribute("data-descriptor-solid")).toBe(String(descriptor?.solid_id));
      expect(node.getAttribute("data-descriptor-index")).toBe(String(descriptor?.topology_index));
      expect(node.getAttribute("data-descriptor-tag")).toBe(descriptor?.tag ?? "");
      // The descriptor is a control, not a label: it is what §6.4 makes
      // clickable, and a span could not be clicked.
      expect(node.tagName).toBe("BUTTON");
    });
    expect(values(host, "dfm.last.findings[].topology[].kind")).toEqual(
      expected.map((descriptor) => descriptor.kind),
    );
    expect(values(host, "dfm.last.findings[].topology[].solid_id")).toEqual(
      expected.map((descriptor) => String(descriptor.solid_id)),
    );
    expect(values(host, "dfm.last.findings[].topology[].topology_index")).toEqual(
      expected.map((descriptor) => String(descriptor.topology_index)),
    );
  });

  it("distinguishes a current-artifact run from a preview run", () => {
    // §6.4: transient-preview and current-artifact resolution must be
    // distinguishable in the panel. The engine's three-valued `resolved_from`
    // rides through unrewritten beside §6.4's two-valued attribute.
    const panel = host.querySelector('[data-panel="dfm"]');
    expect(panel?.getAttribute("data-dfm-source")).toBe("current");
    expect(panel?.getAttribute("data-dfm-resolved-from")).toBe("current");
    expect(attributes(host, "[data-dfm-finding]", "data-dfm-source")).toEqual(
      (run?.findings ?? []).map(() => "current"),
    );

    const preview = render(<DfmView dfm={dfmPreview} secureExecutor />);
    const previewPanel = preview.querySelector('[data-panel="dfm"]');
    expect(dfmPreview.resolved_from).toBe("artifact_ref");
    expect(previewPanel?.getAttribute("data-dfm-source")).toBe("preview");
    expect(previewPanel?.getAttribute("data-dfm-resolved-from")).toBe("artifact_ref");
    expect(new Set(attributes(preview, "[data-dfm-finding]", "data-dfm-source"))).toEqual(
      new Set(["preview"]),
    );
  });

  it("hands a clicked descriptor to its caller with the finding's own artifact", () => {
    if (run === null) return;
    const seen: string[] = [];
    // `renderToStaticMarkup` never dispatches events, so the handler is asserted
    // through the props the panel builds rather than through a click: what is
    // under test is that the intent carries the FINDING's `source_artifact_ref`
    // and the descriptor verbatim (§6.4), not that a browser fires onClick.
    render(
      <DfmView
        dfm={dfm}
        secureExecutor
        onResolveDescriptor={(intent) => {
          seen.push(intent.rule_id);
        }}
      />,
    );
    const first = run.findings[0];
    expect(first?.source_artifact_ref).toBe(run.source_artifact_ref);
  });

  it("names the absence of a run rather than showing an empty finding list", () => {
    const absent = render(<DfmView dfm={dfmAbsent} secureExecutor />);
    expect(dfmAbsent.last).toBeNull();
    expect(absent.querySelectorAll("[data-dfm-finding]")).toHaveLength(0);
    expect(absent.querySelector("[data-dfm-absence]")?.getAttribute("data-dfm-absence")).toBe(
      "no_run",
    );
  });

  it("exposes auto_run and Run DFM as two separate actions, including with no run", () => {
    const toggle = host.querySelector("[data-dfm-auto-run-toggle]");
    const runControl = host.querySelector("[data-dfm-run]");
    expect(host.querySelector("[data-composer-dfm]")).not.toBeNull();
    expect(toggle).not.toBeNull();
    expect(runControl).not.toBeNull();
    expect(toggle).not.toBe(runControl);
    expect(toggle?.getAttribute("data-dfm-auto-run")).toBe(String(dfm.auto_run));
    expect(host.querySelector("[data-source='dfm.auto_run']")).not.toBeNull();

    const absent = render(<DfmView dfm={dfmAbsent} secureExecutor />);
    expect(absent.querySelector("[data-dfm-auto-run-toggle]")).not.toBeNull();
    expect(absent.querySelector("[data-dfm-run]")).not.toBeNull();
    expect(absent.querySelector("[data-dfm-auto-run-toggle]")).not.toBe(
      absent.querySelector("[data-dfm-run]"),
    );
    expect(absent.querySelector("[data-dfm-auto-run-toggle]")?.getAttribute("data-dfm-auto-run")).toBe(
      String(dfmAbsent.auto_run),
    );
  });

  it("renders a missing sandbox as an explanatory refusal, not as an empty list", () => {
    // §6.4: "`capability_not_available` (no sandbox) renders as an explicit
    // explanatory refusal card, never an empty list. Silence never reads as a
    // pass." The two absences are different facts and must read differently.
    const refused = render(<DfmView dfm={dfmAbsent} secureExecutor={false} />);
    const noRun = render(<DfmView dfm={dfmAbsent} secureExecutor />);
    expect(refused.querySelector("[data-dfm-absence]")?.getAttribute("data-dfm-absence")).toBe(
      "capability",
    );
    expect(refused.querySelector("[data-dfm-absence]")?.textContent).not.toBe(
      noRun.querySelector("[data-dfm-absence]")?.textContent,
    );
  });
});

// ---------------------------------------------------------------------------
// §4.3 / §4.4 — Provenance
// ---------------------------------------------------------------------------

describe("ProvenanceView renders §4.4's three shapes", () => {
  const cases: readonly (readonly [string, ResolvedSelection])[] = [
    ["tagged", tagged],
    ["owned", owned],
    ["unattributed", unattributed],
  ];

  it("renders the state the server resolved, never one it inferred", () => {
    for (const [state, resolution] of cases) {
      const host = render(<ProvenanceView pinned={null} resolved={resolution} />);
      expect(resolution.provenance.state).toBe(state);
      expect(
        host.querySelector("[data-provenance-state]")?.getAttribute("data-provenance-state"),
      ).toBe(state);
    }
  });

  it("renders every field of the resolution, field for field", () => {
    for (const [, resolution] of cases) {
      const host = render(<ProvenanceView pinned={null} resolved={resolution} />);
      expect(value(host, "selection.selection_id")).toBe(String(resolution.selection_id));
      expect(value(host, "selection.kind")).toBe(resolution.kind);
      expect(value(host, "selection.solid_index")).toBe(String(resolution.solid_index));
      expect(value(host, "selection.topology_index")).toBe(String(resolution.topology_index));
      expect(value(host, "selection.source_artifact_ref")).toBe(resolution.source_artifact_ref);
      expect(value(host, "selection.bundle_ref")).toBe(resolution.bundle_ref);
      expect(value(host, "selection.selection_table_ref")).toBe(resolution.selection_table_ref);
      expect(values(host, "selection.tag")).toEqual(
        resolution.tag === null ? [] : [resolution.tag],
      );
      expect(values(host, "selection.label")).toEqual(
        resolution.label === null ? [] : [resolution.label],
      );
      expect(values(host, "selection.line")).toEqual(
        resolution.line === null ? [] : [String(resolution.line)],
      );
      // §12.5's `selection-crop` kind is named new work; an absent crop is a
      // named absence, never a fabricated ref.
      expect(values(host, "selection.crop_artifact_ref")).toEqual(
        resolution.crop_artifact_ref === null ? [] : [resolution.crop_artifact_ref],
      );
    }
  });

  it("carries the creating line only where the server resolved one (§12.4)", () => {
    expect(tagged.tag).not.toBeNull();
    expect(tagged.line).not.toBeNull();
    expect(owned.line).toBeNull();
    const strong = render(<ProvenanceView pinned={null} resolved={tagged} />);
    const weak = render(<ProvenanceView pinned={null} resolved={owned} />);
    expect(value(strong, "selection.line")).toBe(String(tagged.line));
    expect(values(weak, "selection.line")).toEqual([]);
  });

  it("says why a weak answer is weak, and says it differently per reason", () => {
    // §4.4: "A weak answer that *says why it is weak* reads as instrument
    // honesty; the same answer with a blank field reads as a bug." And the one
    // case §4.4 singles out — a tagged face whose source map is no longer stored
    // — must NOT render the generic copy.
    const genericOwned = render(
      <ProvenanceView
        pinned={null}
        resolved={{ ...owned, provenance: { state: "owned", reason: "boolean_result_face" } }}
      />,
    );
    const retention = render(
      <ProvenanceView
        pinned={null}
        resolved={{
          ...owned,
          tag: "vent_bore",
          provenance: { state: "owned", reason: "source_map_not_stored" },
        }}
      />,
    );
    const unattributedHost = render(<ProvenanceView pinned={null} resolved={unattributed} />);

    const why = (host: HTMLElement): string =>
      host.querySelector("[data-provenance-why]")?.textContent?.trim() ?? "";
    expect(why(genericOwned)).not.toBe("");
    expect(why(retention)).not.toBe("");
    expect(why(retention)).not.toBe(why(genericOwned));
    expect(why(unattributedHost)).not.toBe(why(genericOwned));
    expect(
      retention.querySelector("[data-provenance-reason]")?.getAttribute("data-provenance-reason"),
    ).toBe("source_map_not_stored");
  });

  it("drops an unrecognized reason back to the state's own sentence", () => {
    // The reason vocabulary is closed; echoing whatever arrived would widen it.
    const unknown = render(
      <ProvenanceView
        pinned={null}
        resolved={{ ...owned, provenance: { state: "owned", reason: "something_new" } }}
      />,
    );
    expect(
      unknown.querySelector("[data-provenance-reason]")?.getAttribute("data-provenance-reason"),
    ).toBe("");
  });

  it("names the missing station rather than dressing an address as a resolution", () => {
    const first = dfm.last?.findings[0];
    const descriptor = first?.topology[0];
    expect(descriptor).toBeDefined();
    if (first === undefined || descriptor === undefined) return;
    const host = render(
      <ProvenanceView
        pinned={build.artifact_ref ?? null}
        origin="dfm_finding"
        intent={{
          part: dfm.part,
          source_artifact_ref: first.source_artifact_ref,
          rule_id: first.rule_id,
          descriptor,
        }}
      />,
    );
    // An address is not a resolution: no state is claimed…
    expect(host.querySelector("[data-provenance-state]")).toBeNull();
    // …but the artifact-bound address the finding carries is shown, and where
    // the reader arrived from is named.
    expect(host.querySelector("[data-provenance-origin]")?.getAttribute("data-provenance-origin"))
      .toBe("dfm_finding");
    expect(value(host, "dfm.last.findings[].source_artifact_ref")).toBe(first.source_artifact_ref);
    expect(value(host, "dfm.last.findings[].topology[].solid_id")).toBe(
      String(descriptor.solid_id),
    );
  });

  it("renders the pinned artifact as the head of §4.3's spine", () => {
    const host = render(<ProvenanceView pinned={build.artifact_ref ?? null} resolved={tagged} />);
    expect(value(host, "workspace.artifact_ref")).toBe(build.artifact_ref);
  });
});
