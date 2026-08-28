// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Gate G4's DOM clauses: tree rows against the build-result geometry count
// (G4.2), the properties panel against the projection (G4.3), the check badges
// against `heph check --json` (G4.4), and the DFM panel (G4.X, deferred from
// G6).
//
// EVERY EXPECTED VALUE COMES FROM THE SERVER IN THE SAME RUN. Not one number in
// this file is typed by hand. That is not tidiness: §1's whole discipline is
// that a displayed fact is a server value, and a test that compared the DOM to a
// literal would be checking the fixture twice and the client's fidelity never.

import { execFileSync } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";
import { archive } from "./harness/archive";
import { api, open, route, uuid7, world } from "./harness/world";

const PART = "tread";

interface BuildDocument {
  readonly status: string;
  readonly geometry_count: number;
  readonly geometries: readonly { readonly label: string; readonly solids: number }[];
  readonly artifact_ref: string;
}

interface PropertiesDocument {
  readonly properties: Readonly<Record<string, string>>;
  readonly fields: readonly string[];
  readonly source: string;
}

interface ChecksDocument {
  readonly badges: Readonly<Record<string, string>>;
  readonly report: unknown;
}

interface DfmDocument {
  readonly status: string;
  readonly last: {
    readonly findings: readonly { readonly rule_id: string }[];
    readonly rules: readonly { readonly rule_id: string }[];
  } | null;
}

/**
 * Open one Inspector tab and wait for its panel.
 *
 * The panel selector is scoped **inside** the tabpanel: `[data-panel]` and
 * `[data-inspector-panel]` both name the tab, one on the drawer's tabpanel and
 * one on the panel it contains, and a union selector matches both.
 */
/** `heph check --json`'s document, whatever the verdict's exit status. */
function checkJson(): string {
  const options = {
    cwd: world().project_root,
    encoding: "utf8" as const,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    maxBuffer: 32 * 1024 * 1024,
  };
  try {
    return execFileSync(world().python, ["-m", "hephaestus.core.cli", "check", "--json"], options);
  } catch (failure) {
    const stdout = (failure as { stdout?: string }).stdout ?? "";
    if (stdout.trim() === "") throw failure;
    return stdout;
  }
}

async function openInspector(page: Page, tab: string): Promise<void> {
  await open(page, route(PART, { itab: tab }));
  await expect(page.locator(`[data-inspector-panel="${tab}"] [data-panel="${tab}"]`)).toBeVisible();
}

// --------------------------------------------------------------------------
// G4.2 — tree row count equals the build-result geometry count

test("the tree renders one geometry row per build-result geometry (G4.2)", async ({
  page,
}, testInfo) => {
  const build = await api<BuildDocument>(`/parts/${PART}/build`);
  await open(page, route(PART));

  const rows = page.locator('[data-tree-row="geometry"][data-part="tread"]');
  await expect(rows).toHaveCount(build.geometry_count);

  // The count the rail *states* is the server's field, attributed to it. §1:
  // "every number the UI presents as fact renders through `<Fact>` and carries a
  // `data-source` attribute naming the HTTP response field it was read from."
  // Scoped to the rail's own row: the Results panel attributes the same field,
  // which is correct — two surfaces reading one server value — and would make an
  // unscoped selector ambiguous.
  const chip = page.locator(
    '[data-tree-row="part"][data-part="tread"] [data-source="build.geometry_count"]',
  );
  await expect(chip).toHaveAttribute("data-value", String(build.geometry_count));

  // Row identity, not just arity: a panel that rendered N copies of one row
  // would satisfy a count and nothing else.
  const labels = await rows.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-geometry-label")),
  );
  expect(labels).toEqual(build.geometries.map((geometry) => geometry.label));

  await archive(page, testInfo, "g4.2-project-tree");
});

test("the Results panel renders the same geometries the tree does (G4.2)", async ({ page }) => {
  const build = await api<BuildDocument>(`/parts/${PART}/build`);
  await openInspector(page, "results");
  const rows = page.locator("[data-inspector-panel='results'] [data-geometry-row]");
  await expect(rows).toHaveCount(build.geometry_count);
  const labels = await rows.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-geometry-label")),
  );
  expect(labels).toEqual(build.geometries.map((geometry) => geometry.label));
});

// --------------------------------------------------------------------------
// G4.3 — the properties panel shows all metadata fields

test("the properties panel's fields are exactly the projection's keys (G4.3)", async ({
  page,
}, testInfo) => {
  const document = await api<PropertiesDocument>(`/parts/${PART}/properties`);
  await openInspector(page, "properties");

  // §6.2 assertion (1): SET EQUALITY, both directions. Containment alone is
  // satisfied by rendering one field, which is the degenerate pass mission
  // rule 1 requires be closed. The other direction — that the projection is the
  // enumerated `part.*` contract and not a thin subset — is
  // `tests/stage4/test_g4_fixture.py`, because a browser cannot see it.
  const fields = await page
    .locator("[data-inspector-panel='properties'] [data-field]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-field")));
  expect([...fields].sort()).toEqual([...Object.keys(document.properties)].sort());
  expect(fields.length).toBe(document.fields.length);

  // And each row carries the value the server sent, attributed to it.
  for (const [key, value] of Object.entries(document.properties)) {
    const fact = page.locator(
      `[data-inspector-panel='properties'] [data-source="properties.${key}"]`,
    );
    await expect(fact).toHaveAttribute("data-value", value);
  }

  await archive(page, testInfo, "g4.3-properties");
});

// --------------------------------------------------------------------------
// G4.4 — check badges match `heph check --json`

test("the check badges match a subprocess `heph check --json` (G4.4)", async ({
  page,
}, testInfo) => {
  // §6.3: "the e2e compares browser DOM badges against a subprocess
  // `heph check --json` — one serializer, two callers". The subprocess is run
  // here, in this test, against the same project the browser is looking at.
  // `heph check` exits NON-ZERO when a check fails, and this fixture has a
  // failing check on purpose — so a bare `execFileSync` would throw on exactly
  // the fixture G4.4 needs. The document is on stdout either way.
  // `CheckResult.to_json` spells the verdict `pass`, not `passed` — the record's
  // own wire name (`core/types.py`). Reading the wrong key would have made every
  // expectation `fail` and the test would have "caught" a bug that was its own.
  const printed = JSON.parse(checkJson()) as {
    readonly checks: Record<string, { readonly pass: boolean; readonly measured: unknown }>;
  };

  const served = await api<ChecksDocument>(`/parts/${PART}/checks`);
  expect(Object.keys(served.badges).sort()).toEqual(Object.keys(printed.checks).sort());

  await openInspector(page, "checks");
  const rendered = await page
    .locator("[data-inspector-panel='checks'] [data-check]")
    .evaluateAll((nodes) =>
      nodes.map((node) => [node.getAttribute("data-check"), node.getAttribute("data-badge")]),
    );
  const shown = new Map(rendered as [string, string][]);

  // The badge each check must show, derived from the SUBPROCESS's own document
  // (`core/checks/report.py::badge`), not from the route's `badges` map — so the
  // chain asserted is: subprocess JSON -> expected badge -> what the browser
  // drew. Reading the expectation off the route would have compared the route
  // with itself.
  expect(shown.size).toBe(Object.keys(printed.checks).length);
  for (const [name, result] of Object.entries(printed.checks)) {
    const measured = result.measured as Record<string, unknown> | null;
    const errored =
      measured !== null &&
      typeof measured === "object" &&
      ("error" in measured || "unverifiable" in measured);
    const expected = errored ? "error" : result.pass ? "pass" : "fail";
    expect(shown.get(name), `badge for ${name}`).toBe(expected);
  }

  // §6.3's closed vocabulary, and the rule that silence never reads as a pass:
  // every rendered badge is one of the four, and the fixture reaches three of
  // them (`not_run` has no engine producer — see the fixture README).
  const badges = new Set(shown.values());
  for (const badge of badges) expect(["pass", "fail", "error", "not_run"]).toContain(badge);
  expect([...badges].sort()).toEqual(["error", "fail", "pass"]);

  await archive(page, testInfo, "g4.4-checks");
});

// --------------------------------------------------------------------------
// G4.X — the DFM toggle surfacing findings (deferred from G6 to G4/G5)

test("running DFM surfaces the pack's findings as topology descriptors (G4.X)", async ({
  page,
}, testInfo) => {
  // §6.4 splits the "DFM toggle" into an action and a project-config write. This
  // is the action's result surfacing in the panel; the fixture violates all
  // three rules the shipped `laser_cut` pack carries, so an empty list cannot
  // pass for a clean part.
  await api(`/parts/${PART}/dfm`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": uuid7() },
    body: "{}",
  });
  const document = await api<DfmDocument>(`/parts/${PART}/dfm`);
  expect(document.last).not.toBeNull();
  const findings = document.last?.findings ?? [];
  expect(findings.length).toBeGreaterThan(0);

  await openInspector(page, "dfm");
  const rows = page.locator("[data-inspector-panel='dfm'] [data-dfm-finding]");
  await expect(rows).toHaveCount(findings.length);
  const rules = await rows.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-dfm-rule")),
  );
  expect(rules).toEqual(findings.map((finding) => finding.rule_id));

  // "findings report descriptors rather than bare mask IDs" (§6.4): every
  // finding that names topology renders a descriptor carrying its kind.
  const descriptors = page.locator("[data-inspector-panel='dfm'] [data-dfm-descriptor]");
  expect(await descriptors.count()).toBeGreaterThan(0);
  await expect(descriptors.first()).toHaveAttribute("data-descriptor-kind", /face|edge|solid/);

  // Which artifact the findings are about is visible, not inferred (§6.4's
  // preview-versus-current requirement).
  await expect(
    page.locator("[data-inspector-panel='dfm'] [data-dfm-source]").first(),
  ).toHaveAttribute(
    "data-dfm-source",
    /current|preview/,
  );

  await archive(page, testInfo, "g4.x-dfm");
});

// --------------------------------------------------------------------------
// §2.2 — the token never survives in the URL, and its absence is a named state

test("the bearer leaves the URL and a missing one renders one named panel", async ({ page }) => {
  const { base_url, token } = world();
  await page.goto(`${base_url}/#t=${token}`);
  await expect(page.locator("[data-pin-mode]").first()).toBeVisible();
  expect(page.url()).not.toContain(token);

  const context = await page.context().browser()?.newContext();
  if (context === undefined) throw new Error("no browser context");
  const fresh = await context.newPage();
  try {
    await fresh.goto(`${base_url}/`);
    await expect(fresh.locator('[data-testid="no-token"]')).toBeVisible();
  } finally {
    await context.close();
  }
});
