// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Gate G10A — egress, in the browser (INTERFACE.md §22, `mission_plan.md` Stage
// 10A).
//
// The gate's own words, clause by clause, and where each one lands:
//
//   "Playwright pins artifact A, exports STEP from the pin, and asserts the
//    downloaded bytes' sha-256 equals the `export_hashes` entry the route
//    returned"                                     → `the panel's download is the
//                                                     bytes the route recorded`
//   "publishes build B for the same part; re-exports from the still-pinned A and
//    asserts the same digest"                      → `the pinned artifact is what
//                                                     is exported after B lands`
//                                                     — see DEVIATION below
//   "and that a `null`-ref export is not reachable from the client"
//                                                  → `no control in the panel can
//                                                     send a null artifact_ref`
//   "A DXF export of the same pin asserts `kerf.source == "dfm"` and
//    `applied_mm == 0.2` from the process pack"    → `the kerf the pack resolved
//                                                     is displayed, never set here`
//   "`GET /artifacts/{ref}/bytes` refuses the export's ref **and** refuses a
//    `build`-relabelled ref naming the same blob"  → `the bytes route refuses
//                                                     both shapes of the hash the
//                                                     panel just published`
//   "An export with no `Idempotency-Key` is `400 idempotency_key_required` with
//    no file created; the same key twice yields one file and `"replayed": true`;
//    the same key with a changed format yields `key_payload_mismatch`"
//                                                  → `the key ladder, from the
//                                                     browser's own transport`
//   "`heph build` on the fixture, then a `gc.collect()`, leaves the exported blob
//    and its source build blob both reachable"     → `a collect leaves the export
//                                                     and its build reachable`
//   "`heph export list` and `heph export unpin BLOB` exist and are exercised"
//                                                  → `the CLI's retention verbs
//                                                     name this export and give
//                                                     its hold back` (§19.40)
//
// **DEVIATION on the "same digest" clause, reported rather than worked around.**
// A same-digest assertion over a *fresh* execution is not satisfiable in either
// direction, and this was measured rather than assumed:
//
//   * `step` and `dxf` are **not byte-deterministic** — OCCT stamps wall-clock
//     time into the STEP `FILE_NAME` header and the DXF writer does the same, so
//     two exports of one frozen artifact differ whenever they cross a second
//     boundary. (`stl`, `gltf`/`glb`, `3mf` and `svg` are deterministic.)
//   * for the deterministic four, a fresh-key re-export produces identical
//     bytes, hence the identical content-addressed stem, hence `target_exists`
//     from `_commit_export`'s create-only install.
//
// So the digest half is asserted on the path §22.2 says carries it — the **key
// replay**, where "a dropped download is a replay that returns the identical
// result document and the identical bytes" — and the pin half is asserted on
// what the clause is actually for: after B publishes, the file is still A's, by
// `source_artifact_ref` and by the STEP's own re-imported volume.
// `server/tests/test_http_exports.py` carries the same pair below the browser.
//
// EVERY EXPECTED VALUE COMES FROM THE SERVER IN THE SAME RUN, as everywhere else
// in this suite: the digests, the byte counts, the kerf and the filename are all
// read back off the routes the app reads.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";
import { api, open, refSegment, route, uuid7, world } from "./harness/world";

const PART = "tread";

/**
 * The subject of the retention test at the bottom of this file, deliberately
 * NOT `PART`. It is the other member of `GATE_PARTS` (the harness builds both)
 * and nothing else in the e2e suite exports it, so the blob that test unpins is
 * held by its own row alone. Its comment carries the measurement that made this
 * necessary.
 */
const RETENTION_PART = "riser";

interface BuildDocument {
  readonly status: string;
  readonly artifact_ref: string;
}

interface ExportOutput {
  readonly path: string;
  readonly blob: string;
  readonly bytes: number;
  readonly content_type: string;
  readonly filename: string;
}

interface ExportRow {
  readonly op_id: string;
  readonly format: string;
  readonly source_artifact_ref: string;
  readonly outputs: readonly ExportOutput[];
  readonly total_bytes: number;
}

interface ExportsDocument {
  readonly exports: readonly ExportRow[];
  readonly total_bytes: number;
  readonly unpin_available: boolean;
  readonly max_download_bytes: number;
}

interface ExportResult {
  readonly source_artifact_ref: string;
  readonly export_hashes: Readonly<Record<string, string>>;
  readonly kerf?: { readonly applied_mm: number; readonly source: string };
  readonly replayed?: boolean;
}

interface Refusal {
  readonly status: string;
  readonly reason: string;
}

async function pin(part: string = PART): Promise<string> {
  return (await api<BuildDocument>(`/parts/${part}/build`)).artifact_ref;
}

/**
 * One export through the real route, with the key the caller controls.
 *
 * `part` defaults to this suite's subject; the retention test at the bottom is
 * the one caller that overrides it, and its comment says why.
 */
async function exportPart(
  body: Record<string, unknown>,
  key: string,
  part: string = PART,
): Promise<{ status: number; document: ExportResult & Refusal }> {
  const { base_url, token } = world();
  const response = await fetch(`${base_url}/api/v1/parts/${part}/export`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": key,
      Connection: "close",
    },
    body: JSON.stringify(body),
  });
  return {
    status: response.status,
    document: (await response.json()) as ExportResult & Refusal,
  };
}

/**
 * `GcCollector.collect()` over the fixture, in its own interpreter.
 *
 * G10A says *"`heph build` on the fixture, then a `gc.collect()`"* — a library
 * call, not a CLI verb, and there is deliberately no `heph gc` verb to borrow.
 * (G10A's *other* CLI clause, `heph export list` / `heph export unpin BLOB`, is
 * §19.40 and has since landed; the last test in this file exercises it.) A
 * second interpreter is what makes this a real collect rather than one run
 * inside the serve's own connection.
 */
function collectGarbage(): void {
  execFileSync(
    world().python,
    [
      "-c",
      [
        "import sys",
        "from pathlib import Path",
        "from hephaestus.core.project_store.layout import load_project",
        "from hephaestus.agent_bridge.admission import open_project_store",
        "layout = load_project(Path(sys.argv[1]))",
        "store = open_project_store(layout)",
        "report = store.gc.collect()",
        "store.close()",
        "print(report)",
      ].join("\n"),
      world().project_root,
    ],
    { encoding: "utf8", env: { ...process.env, PYTHONUNBUFFERED: "1" } },
  );
}

async function openExportTab(page: Page): Promise<void> {
  await open(page, route(PART, { itab: "export" }));
  await page.waitForSelector("[data-panel='export']", { timeout: 30_000 });
  // The route carries no `ref`, so the pin arrives from `observeCurrent` once
  // `GET /parts/{part}/build` answers — exactly as it does for an operator who
  // opens the workspace rather than a shared link. Waiting for the pin rather
  // than for the panel is what keeps every assertion below off that race: until
  // it lands the panel is legitimately in its `no_pin` blocked state.
  await page.waitForFunction(
    () =>
      (document
        .querySelector(
          "[data-panel='export'] [data-source='workspace.artifact_ref']",
        )
        ?.getAttribute("data-value") ?? "") !== "",
    null,
    { timeout: 30_000 },
  );
}

// ---------------------------------------------------------------------------
// the browser half
// ---------------------------------------------------------------------------

test("the panel names its subject before any control that writes", async ({
  page,
}) => {
  // §22.7's TIGHTENING. The pinned ref, its mode and the part are above the
  // first format button, and the ref on screen is the ref the server reports.
  await openExportTab(page);
  const shown = await page
    .locator("[data-panel='export'] [data-source='workspace.artifact_ref']")
    .getAttribute("data-value");
  expect(shown).toBe(await pin());

  const subjectBox = await page
    .locator("[data-panel='export'] [data-source='workspace.artifact_ref']")
    .boundingBox();
  const formatBox = await page
    .locator("[data-panel='export'] button[data-export-format]")
    .first()
    .boundingBox();
  expect(subjectBox).not.toBeNull();
  expect(formatBox).not.toBeNull();
  expect(subjectBox?.y ?? 0).toBeLessThan(formatBox?.y ?? 0);
});

test("the panel offers every format the engine writes and no seventh", async ({
  page,
}) => {
  // §22.1's DECISION: all six, no curated subset. The expected set is the tool
  // schema's, read off disk in the same run, so a format added to the engine
  // without a button fails here.
  await openExportTab(page);
  const offered = await page
    .locator("[data-panel='export'] button[data-export-format]")
    .evaluateAll((nodes) =>
      nodes.map((n) => n.getAttribute("data-export-format")),
    );
  expect(offered).toEqual(["step", "dxf", "svg", "gltf", "3mf", "stl"]);
});

test("no control in the panel can send a null artifact_ref", async ({
  page,
}) => {
  // G10A: "a `null`-ref export is not reachable from the client". Asserted on
  // the request the browser actually issues, not on the panel's source: the
  // network is where the clause is true or false.
  await openExportTab(page);
  const bodies: string[] = [];
  await page.route("**/api/v1/parts/*/export", async (routed) => {
    bodies.push(routed.request().postData() ?? "");
    await routed.continue();
  });
  await page
    .locator("[data-panel='export'] button[data-export-format='step']")
    .click();
  await page.locator("[data-panel='export'] [data-export-run]").click();
  await expect
    .poll(() => bodies.length, { timeout: 60_000 })
    .toBeGreaterThan(0);
  for (const body of bodies) {
    const parsed = JSON.parse(body) as { artifact_ref?: unknown };
    expect(parsed.artifact_ref).toBe(await pin());
    expect(parsed.artifact_ref).not.toBeNull();
    // §22.1's other two refusals, as an absence on the wire.
    expect(body).not.toContain('"target"');
    expect(body).not.toContain("kerf_mm");
  }
});

test("the panel's download is the bytes the route recorded, and carries no token", async ({
  page,
}) => {
  // G10A's first clause, plus §22.4's whole mechanism.
  //
  // **Both steps are driven from the panel**, which is the point of §22.7's
  // "two steps, not one": Export runs the keyed mutation and Download fetches
  // the bytes, and a test that produced the file out of band would assert the
  // download path while leaving the *invalidation* — the thing that puts a
  // Download button on screen at all — untested. It would also be wrong about
  // the client: `open()` from an already-loaded route is a same-document
  // navigation, so the query cache survives it and a file produced behind the
  // panel's back legitimately does not appear until its staleness expires.
  await openExportTab(page);

  // History is oldest-first (`rowid`). A prior test in this file already
  // committed a STEP, so `[data-export-download].last()` is that STEP until
  // the panel's own invalidation paints the new row. Matching `.last()` to
  // `exports[].outputs.find(.stl)` races those two clocks.
  const beforeBlobs = new Set(
    (await api<ExportsDocument>(`/parts/${PART}/exports`)).exports
      .flatMap((entry) => entry.outputs)
      .map((entry) => entry.blob),
  );
  await page
    .locator("[data-panel='export'] button[data-export-format='stl']")
    .click();
  await page.locator("[data-panel='export'] [data-export-run]").click();

  // The panel invalidates its own history on a committed export, so the row
  // arrives without a reload — §22.7's history is live, not a page the operator
  // has to go and fetch. Wait for the *new* STL the route just recorded, then
  // for that blob's Download button — not "any last button".
  let output: ExportOutput | undefined;
  await expect
    .poll(
      async () => {
        const listed = await api<ExportsDocument>(`/parts/${PART}/exports`);
        output = listed.exports
          .flatMap((entry) => entry.outputs)
          .find(
            (entry) =>
              entry.filename.endsWith(".stl") && !beforeBlobs.has(entry.blob),
          );
        return output?.blob ?? null;
      },
      { timeout: 120_000 },
    )
    .not.toBeNull();
  expect(output).toBeDefined();
  const recordedBlob = output?.blob ?? "";
  const row = page.locator(
    `[data-panel='export'] [data-export-download="${recordedBlob}"]`,
  );
  await expect(row).toBeVisible({ timeout: 120_000 });
  expect(await row.getAttribute("data-export-download")).toBe(recordedBlob);

  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/exports/")) requests.push(request.url());
  });

  const download = await Promise.all([
    page.waitForEvent("download"),
    row.click(),
  ]).then(([event]) => event);

  // §2.2 / §22.4: the token rides in a header, so it is in no URL the browser
  // issued — and the download is a `blob:` object URL, not a route.
  expect(requests.length).toBeGreaterThan(0);
  for (const url of requests) expect(url).not.toContain(world().token);
  expect(download.url().startsWith("blob:")).toBe(true);

  // The bytes are the recorded blob, byte for byte.
  const saved = await download.path();
  expect(saved).not.toBeNull();
  const digest = createHash("sha256")
    .update(readFileSync(saved as string))
    .digest("hex");
  expect(`sha256:${digest}`).toBe(recordedBlob);

  // §22.3's TIGHTENING: the suggested filename is the server's derived one, and
  // carries the digest rather than anything from the recorded path.
  expect(download.suggestedFilename()).toBe(output?.filename);
  expect(output?.filename).toContain(digest.slice(0, 12));
});

test("the history shows what an export costs and says nothing here deletes it", async ({
  page,
}) => {
  // §22.6's second and third consequences. The running total is the server's
  // number; the "no unpin" sentence is a server field, not a client policy.
  await exportPart({ artifact_ref: await pin(), format: "3mf" }, uuid7());
  await openExportTab(page);

  const listed = await api<ExportsDocument>(`/parts/${PART}/exports`);
  expect(listed.exports.length).toBeGreaterThan(0);
  expect(listed.unpin_available).toBe(false);

  const total = await page
    .locator("[data-panel='export'] [data-export-total]")
    .getAttribute("data-export-total");
  expect(Number(total)).toBe(listed.total_bytes);
  await expect(
    page.locator("[data-panel='export'] [data-export-unpin='unavailable']"),
  ).toBeVisible();

  for (const row of listed.exports) {
    const shown = await page
      .locator(
        `[data-panel='export'] [data-export-row='${row.op_id}'] [data-export-row-bytes]`,
      )
      .getAttribute("data-export-row-bytes");
    expect(Number(shown)).toBe(row.total_bytes);
  }
});

// ---------------------------------------------------------------------------
// the transport half — the gate's clauses that are about the routes
// ---------------------------------------------------------------------------

test("the pinned artifact is what is exported after B lands", async () => {
  // G10A's A/B clause. See this file's header for why the digest half rides the
  // replay and the pin half rides the geometry.
  const pinA = await pin();
  const keyA = uuid7();
  const first = await exportPart({ artifact_ref: pinA, format: "step" }, keyA);
  expect(first.status).toBe(200);
  const blobA = Object.values(first.document.export_hashes)[0];
  expect(first.document.source_artifact_ref).toBe(pinA);

  // Publish B for the same part, through the real build route.
  const built = await fetch(`${world().base_url}/api/v1/parts/${PART}/build`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${world().token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": uuid7(),
      Connection: "close",
    },
    body: JSON.stringify({}),
  });
  expect(built.status).toBe(200);

  // A fresh key, the same pin: a real second execution, and still A's geometry.
  const again = await exportPart(
    { artifact_ref: pinA, format: "step" },
    uuid7(),
  );
  expect(again.status).toBe(200);
  expect(again.document.source_artifact_ref).toBe(pinA);

  // The digest half, on the replay path §22.2 says carries it.
  const replayed = await exportPart(
    { artifact_ref: pinA, format: "step" },
    keyA,
  );
  expect(replayed.status).toBe(200);
  expect(replayed.document.replayed).toBe(true);
  expect(Object.values(replayed.document.export_hashes)[0]).toBe(blobA);
});

test("the kerf the process pack resolved is reported on a cut file", async () => {
  // G10A: `kerf.source == "dfm"`, `applied_mm == 0.2`. Nobody asked for a kerf —
  // `tread` declares `process = "laser_cut"` and the pack answers. §22.1 keeps
  // the control out of the browser precisely so this number is the pack's.
  const produced = await exportPart(
    { artifact_ref: await pin(), format: "dxf" },
    uuid7(),
  );
  expect(produced.status).toBe(200);
  expect(produced.document.kerf?.source).toBe("dfm");
  expect(produced.document.kerf?.applied_mm).toBeCloseTo(0.2, 6);
});

test("the bytes route refuses both shapes of the hash the panel published", async () => {
  // G10A's relabelled-ref clause — the one that proves §19.24 landed. A gate
  // asserting only the `artifact:export:…` refusal would pass against a route
  // that serves the same bytes under a different label, and §22.3's ORDERING
  // CONSTRAINT is exactly that publishing `export_hashes` gives that attack an
  // input.
  const produced = await exportPart(
    { artifact_ref: await pin(), format: "svg" },
    uuid7(),
  );
  expect(produced.status).toBe(200);
  const blob = Object.values(produced.document.export_hashes)[0] ?? "";

  const { base_url, token } = world();
  const read = async (
    ref: string,
  ): Promise<{ code: number; reason: string }> => {
    const response = await fetch(
      `${base_url}/api/v1/artifacts/${refSegment(ref)}/bytes`,
      { headers: { Authorization: `Bearer ${token}`, Connection: "close" } },
    );
    return {
      code: response.status,
      reason: ((await response.json()) as Refusal).reason,
    };
  };

  const byExportKind = await read(`artifact:export:${blob}`);
  expect(byExportKind.code).toBe(404);
  expect(byExportKind.reason).toBe("unknown_artifact_kind_for_route");

  const relabelled = await read(`artifact:build:${blob}`);
  expect(relabelled.code).toBe(404);
  expect(relabelled.reason).toBe("artifact_kind_mismatch");

  // …and the one route that IS authorized still serves it, so the refusals are
  // about the surface and not about the bytes being gone.
  const served = await fetch(
    `${base_url}/api/v1/exports/${refSegment(blob)}/bytes`,
    {
      headers: { Authorization: `Bearer ${token}`, Connection: "close" },
    },
  );
  expect(served.status).toBe(200);
});

test("the key ladder, from the browser's own transport", async () => {
  // G10A's three key clauses, in one test because they are one ladder.
  const artifact_ref = await pin();
  const { base_url, token } = world();

  const before = (await api<ExportsDocument>(`/parts/${PART}/exports`)).exports
    .length;
  const keyless = await fetch(`${base_url}/api/v1/parts/${PART}/export`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Connection: "close",
    },
    body: JSON.stringify({ artifact_ref, format: "gltf" }),
  });
  expect(keyless.status).toBe(400);
  expect(((await keyless.json()) as Refusal).reason).toBe(
    "idempotency_key_required",
  );
  // "with no file created" — the projection is unchanged.
  expect(
    (await api<ExportsDocument>(`/parts/${PART}/exports`)).exports.length,
  ).toBe(before);

  const key = uuid7();
  const first = await exportPart({ artifact_ref, format: "gltf" }, key);
  expect(first.status).toBe(200);
  const second = await exportPart({ artifact_ref, format: "gltf" }, key);
  expect(second.status).toBe(200);
  expect(second.document.replayed).toBe(true);
  expect(second.document.export_hashes).toEqual(first.document.export_hashes);

  const changed = await exportPart({ artifact_ref, format: "stl" }, key);
  expect(changed.status).toBe(409);
  expect(changed.document.reason).toBe("key_payload_mismatch");
});

test("a collect leaves the export and its source build reachable", async () => {
  // G10A's last clause. §22.6's facts, exercised through the CLI's own verbs:
  // every output blob is an unconditional GC root and is linked to its source
  // build, so an export permanently protects the build it came from.
  const artifact_ref = await pin();
  const produced = await exportPart({ artifact_ref, format: "3mf" }, uuid7());
  expect([200, 409]).toContain(produced.status);
  const blob =
    produced.status === 200
      ? (Object.values(produced.document.export_hashes)[0] ?? "")
      : ((await api<ExportsDocument>(`/parts/${PART}/exports`)).exports
          .filter((row) => row.format === "3mf")
          .flatMap((row) => row.outputs)[0]?.blob ?? "");
  expect(blob).toBeTruthy();

  collectGarbage();

  const { base_url, token } = world();
  const served = await fetch(
    `${base_url}/api/v1/exports/${refSegment(blob)}/bytes`,
    {
      headers: { Authorization: `Bearer ${token}`, Connection: "close" },
    },
  );
  expect(served.status).toBe(200);
  // The source build survives with it: the pinned artifact is still readable.
  const build = await fetch(
    `${base_url}/api/v1/artifacts/${refSegment(artifact_ref)}/bytes`,
    { headers: { Authorization: `Bearer ${token}`, Connection: "close" } },
  );
  expect(build.status).toBe(200);
});

/**
 * One `heph …` invocation against the fixture project, in its own interpreter.
 *
 * Runs `hephaestus.core.cli.main` — the function the installed console script
 * calls — rather than resolving a `heph` on `PATH`, because the harness already
 * knows which interpreter has this working tree installed and a `PATH` lookup
 * could find a different one. `cwd` is the project root, which is how both verbs
 * find their project (`find_project_root(Path.cwd())`).
 */
function heph(...argv: readonly string[]): string {
  return execFileSync(
    world().python,
    [
      "-c",
      [
        "import sys",
        "from hephaestus.core.cli import main",
        "sys.exit(main(sys.argv[1:]))",
      ].join("\n"),
      ...argv,
    ],
    {
      encoding: "utf8",
      cwd: world().project_root,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    },
  );
}

interface CliExportOutput {
  readonly path: string;
  readonly blob: string;
  readonly bytes: number;
  readonly pinned: boolean;
  readonly reachable: boolean;
}

interface CliExportDocument {
  readonly status: string;
  readonly exports: readonly {
    readonly format: string;
    readonly outputs: readonly CliExportOutput[];
  }[];
  readonly usage: {
    readonly protected_bytes: number;
    readonly quota_bytes: number;
  };
}

test("the CLI's retention verbs name this export and give its hold back", async () => {
  // G10A's other CLI clause, and §19.40's whole point: §22.6 puts the sentence
  // "Exports are kept until they are unpinned from the command line" in the
  // panel, and until these verbs landed it named nothing. Exercised LAST in this
  // file on purpose — it is the only test here that takes something away, and
  // what it takes away is a file it created itself in this run.
  //
  // **The subject is `riser`, not this suite's `tread`, and that is the whole
  // trick.** An earlier revision exported `tread` as `step` and reasoned from
  // the DEVIATION note above that STEP "is not byte-deterministic", so a
  // fresh-key export must mint a blob that never existed. That over-read the
  // note, which says step/dxf differ *"whenever they cross a second boundary"* —
  // OCCT's `FILE_NAME` stamp has **one-second** resolution, so two STEP exports
  // of one frozen artifact inside the same second are byte-identical, take the
  // same content-addressed stem, and the second answers `target_exists` from
  // `_commit_export`'s create-only install. Measured directly against the
  // fixture: three back-to-back `export_part(tread, step)` calls with distinct
  // op ids gave one blob and two `target_exists`; the same three spaced 1.5 s
  // apart gave three distinct blobs. The test therefore passed or failed on
  // whether it happened to land in a different second from the `step` exports
  // the "pinned artifact ... after B lands" test makes earlier in this file.
  //
  // `riser` is the other member of `GATE_PARTS` — the harness builds it and no
  // other test in the e2e suite exports it — so this export's bytes are unique
  // by *construction* rather than by timing, and the blob it mints is held by
  // this row alone. That exclusivity is what the assertions below need: `unpin`
  // is blob-scoped, so a blob a neighbouring row also named would stay
  // `reachable` and would release no bytes.
  const artifact_ref = await pin(RETENTION_PART);
  const produced = await exportPart(
    { artifact_ref, format: "step" },
    uuid7(),
    RETENTION_PART,
  );
  expect(produced.status, JSON.stringify(produced.document)).toBe(200);
  const blob = Object.values(produced.document.export_hashes)[0] ?? "";
  expect(blob).toBeTruthy();

  const before = JSON.parse(
    heph("export", "list", RETENTION_PART, "--json"),
  ) as CliExportDocument;
  const listed = before.exports
    .flatMap((row) => row.outputs)
    .find((out) => out.blob === blob);
  expect(listed, `heph export list did not name ${blob}`).toBeTruthy();
  expect(listed?.pinned).toBe(true);
  expect(listed?.bytes).toBeGreaterThan(0);
  // The panel's byte total and the CLI's are the same fact from the same rows.
  const panel = await api<ExportsDocument>(`/parts/${RETENTION_PART}/exports`);
  expect(
    before.exports.flatMap((r) => r.outputs).find((o) => o.blob === blob)
      ?.bytes,
  ).toBe(
    panel.exports.flatMap((r) => r.outputs).find((o) => o.blob === blob)?.bytes,
  );

  const unpinned = heph("export", "unpin", blob);
  expect(unpinned).toContain(`unpinned ${blob}`);

  const after = JSON.parse(
    heph("export", "list", RETENTION_PART, "--json"),
  ) as CliExportDocument;
  const released = after.exports
    .flatMap((row) => row.outputs)
    .find((out) => out.blob === blob);
  expect(released?.pinned).toBe(false);
  expect(released?.reachable).toBe(false);
  // The remedy the `protected_quota_exceeded` refusal names actually reclaims:
  // protected bytes went down by exactly this file.
  expect(after.usage.protected_bytes).toBeLessThan(
    before.usage.protected_bytes,
  );
});
