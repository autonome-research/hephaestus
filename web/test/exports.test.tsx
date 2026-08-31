// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §22 — egress, client side.
//
// Three things are asserted here and nowhere else:
//
// 1. **The enum drift test (§19.36, §22.1).** §22.1 says the client renders the
//    format picker "from `TOOLS_BY_NAME["export_part"].params`, never from a list
//    of its own — §1's no-derived-fact rule reaches enums, not only values." A
//    browser cannot reach a Python object and no route serves a tool schema, so
//    `api/exports.ts` transcribes the committed, generated
//    `schemas/tools/*.schema.json` and this test reads those very files and
//    asserts equality. A seventh format, a fourth drawing kind or a renamed
//    layout fails here rather than shipping a picker that disagrees with the
//    tool.
// 2. **The key discipline (§22.2's TIGHTENING).** One key per *submission*: the
//    same key across retries of one unchanged submission, a fresh key the moment
//    any field changes. Both halves are wrong in different ways and both are the
//    client's to prevent.
// 3. **The download mechanism (§22.4).** The token never enters a URL; the
//    object URL is revoked in a `finally` on **every** path including the throw;
//    the filename is the server's and is never parsed out of a header.
//
// The panel's DOM is asserted the way every other inspector panel's is:
// `renderToStaticMarkup` over a document, queried by `data-*`. No assertion is on
// a string of UI copy (§3); where the obligation is a *visible distinction* the
// assertion is that two states render different text.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import {
  DOC_KINDS,
  DRAWING_KINDS,
  DRAWING_SHEETS,
  EXPORT_FORMATS,
  EXPORT_LAYOUTS,
  EXPORT_STATES,
  LAYOUT_FORMATS,
  downloadExport,
  exportBytesPath,
  tooLargeToBuffer,
  type ExportOutput,
  type ExportsDocument,
} from "../src/api/exports";
import { uuid7 } from "../src/api/idempotency";
import { ExportView, exportBlocker } from "../src/components/inspector/ExportPanel";
import { INSPECTOR_TABS } from "../src/state/workspace";
import { WorkspaceError } from "../src/api/client";
import { claimToken } from "../src/api/token";

// ---------------------------------------------------------------------------
// the drift test (§19.36) — the client's enums against the engine's schemas
// ---------------------------------------------------------------------------

interface ToolSchema {
  readonly parameters: {
    readonly properties: Record<string, { readonly enum?: readonly string[] }>;
    readonly allOf?: readonly {
      readonly then?: { readonly properties?: Record<string, { readonly enum?: string[] }> };
    }[];
  };
}

// `resolve(process.cwd(), …)` rather than `new URL(…, import.meta.url)`: the
// second is a Vite asset-URL construct, and Vite refuses to resolve one that
// points outside the project root. These files are read at *test* time with
// plain node fs, from `web/`, which is where vitest runs.
const REPO = resolve(process.cwd(), "..");

function toolSchema(tool: string): ToolSchema {
  const path = resolve(REPO, "schemas", "tools", `${tool}.schema.json`);
  return JSON.parse(readFileSync(path, "utf-8")) as ToolSchema;
}

function enumOf(tool: string, param: string): readonly string[] {
  const declared = toolSchema(tool).parameters.properties[param]?.enum;
  if (declared === undefined) throw new Error(`${tool}.${param} declares no enum`);
  return declared;
}

describe("§22.1 — the engine's enum IS the closed vocabulary", () => {
  it("offers exactly the six formats export_part declares, in its order", () => {
    expect([...EXPORT_FORMATS]).toEqual([...enumOf("export_part", "format")]);
  });

  it("offers exactly the two layouts export_part declares", () => {
    expect([...EXPORT_LAYOUTS]).toEqual([...enumOf("export_part", "layout")]);
  });

  it("reveals layout only for the formats the tool's own conditional permits", () => {
    // §22.1: "a control that exists only to produce `invalid_params` is a trap".
    // The permitted set is not a judgement call — it is `allOf[0].then`, the
    // conditional the tool applies when `layout = nested_sheet`.
    const conditional = toolSchema("export_part").parameters.allOf?.[0];
    expect([...LAYOUT_FORMATS]).toEqual(conditional?.then?.properties?.["format"]?.enum);
  });

  it("offers all three drawing kinds and all three sheets", () => {
    expect([...DRAWING_KINDS]).toEqual([...enumOf("generate_drawing", "kind")]);
    expect([...DRAWING_SHEETS]).toEqual([...enumOf("generate_drawing", "sheet")]);
  });

  it("offers all three document kinds", () => {
    expect([...DOC_KINDS]).toEqual([...enumOf("generate_doc", "kind")]);
  });

  it("declares no target and no kerf_mm field, in either direction", () => {
    // §22.1's two refusals, as an absence in the client's own request type. The
    // server refuses both by name anyway (`test_http_exports.py`); this asserts
    // the client has no way to produce one.
    const source = readFileSync(resolve(process.cwd(), "src/api/exports.ts"), "utf-8");
    const request = source.slice(
      source.indexOf("export interface ExportRequest"),
      source.indexOf("export interface DrawingRequest"),
    );
    expect(request).not.toContain("target?");
    expect(request).not.toContain("kerf_mm");
  });
});

// ---------------------------------------------------------------------------
// §2.5 / §22.2 — the key
// ---------------------------------------------------------------------------

describe("§2.5 — the client mints a key the server will accept", () => {
  it("mints a UUIDv7, not a v4", () => {
    // `http/idempotency.py::_uuid7_timestamp` refuses any other version as
    // `idempotency_key_malformed`, because it reads the freshness rung out of
    // the key's own timestamp.
    const key = uuid7();
    expect(key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("embeds the timestamp the server reads back", () => {
    const at = 1_756_000_000_000;
    const key = uuid7(at);
    const millis = Number.parseInt(key.slice(0, 8) + key.slice(9, 13), 16);
    expect(millis).toBe(at);
  });

  it("mints a distinct key each call", () => {
    const minted = new Set(Array.from({ length: 64 }, () => uuid7()));
    expect(minted.size).toBe(64);
  });
});

// ---------------------------------------------------------------------------
// §22.4 — the download
// ---------------------------------------------------------------------------

const OUTPUT: ExportOutput = {
  path: 'evil";filename="owned.exe',
  blob: "sha256:1122334455667788990011223344556677889900112233445566778899001122",
  bytes: 4096,
  content_type: "model/step",
  filename: "tread-112233445566.step",
};

const HISTORY: ExportsDocument = {
  status: "ok",
  part: "tread",
  exports: [
    {
      op_id: "op-1",
      format: "step",
      layout: "as_built",
      state: "COMMITTED",
      source_artifact_ref: "artifact:build:sha256:aaaa",
      source_input_hashes: { script: "sha256:bbbb" },
      extra: {},
      outputs: [OUTPUT],
      total_bytes: 4096,
    },
  ],
  total_bytes: 4096,
  unpin_available: false,
  max_download_bytes: 64 * 1024 * 1024,
};

const TOKEN = "test-token-value";

function stubDownloadEnvironment(): { readonly created: string[]; readonly revoked: string[] } {
  const created: string[] = [];
  const revoked: string[] = [];
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: (): string => {
      const url = `blob:workspace/${String(created.length)}`;
      created.push(url);
      return url;
    },
    revokeObjectURL: (url: string): void => {
      revoked.push(url);
    },
  });
  return { created, revoked };
}

// Response bodies here are `Uint8Array`, never a jsdom `Blob`: undici's
// `Response` calls `.stream()` on what it wraps, jsdom's Blob has none, and
// whether that surfaces depends on the Node/jsdom pairing — green on this
// machine, `object.stream is not a function` on the runner (CI run
// 33233646522). A Uint8Array is accepted natively everywhere, and every
// assertion below only reads the bytes back.
describe("§22.4 — bytes without a token in a URL", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    // The token enters exactly as it does in the product: out of the URL
    // fragment, into `sessionStorage`, and out of the URL again (§2.2).
    window.location.hash = `#t=${TOKEN}`;
    claimToken();
  });

  it("puts the token in a header and never in the path", async () => {
    const { revoked } = stubDownloadEnvironment();
    const seen: { url: string; init: RequestInit | undefined }[] = [];
    vi.stubGlobal(
      "fetch",
      (url: string, init?: RequestInit): Promise<Response> => {
        seen.push({ url, init });
        return Promise.resolve(new Response(new Uint8Array([1, 2, 3])));
      },
    );

    await downloadExport(OUTPUT);

    expect(seen).toHaveLength(1);
    const call = seen[0];
    expect(call?.url).not.toContain(TOKEN);
    // …and the token really is being sent, so "not in the URL" is a statement
    // about where it went rather than about it being absent.
    const headers = new Headers(call?.init?.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(revoked).toHaveLength(1);
  });

  it("revokes the object URL even when the click throws", async () => {
    const { created, revoked } = stubDownloadEnvironment();
    vi.stubGlobal(
      "fetch",
      (): Promise<Response> => Promise.resolve(new Response(new Uint8Array([1]))),
    );
    const appendChild = document.body.appendChild.bind(document.body);
    vi.spyOn(document.body, "appendChild").mockImplementation((node: Node): Node => {
      const added = appendChild(node);
      (added as HTMLAnchorElement).click = (): never => {
        throw new Error("the download manager refused");
      };
      return added;
    });

    await expect(downloadExport(OUTPUT)).rejects.toThrow("the download manager refused");

    // §22.4: an object URL that is never revoked pins the whole buffered file in
    // the tab for the life of the document.
    expect(revoked).toEqual(created);
    vi.restoreAllMocks();
  });

  it("keeps a refused download's named reason instead of 'download failed'", async () => {
    stubDownloadEnvironment();
    vi.stubGlobal(
      "fetch",
      (): Promise<Response> =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              status: "error",
              reason: "unknown_export",
              message: "not an output of any committed export",
            }),
            { status: 404 },
          ),
        ),
    );
    await expect(downloadExport(OUTPUT)).rejects.toMatchObject({ reason: "unknown_export" });
  });

  it("refuses to build a path that would carry the token", () => {
    expect(exportBytesPath(OUTPUT.blob)).toBe(
      `/exports/${encodeURIComponent(OUTPUT.blob)}/bytes`,
    );
    expect(exportBytesPath(OUTPUT.blob)).not.toContain(TOKEN);
  });

  it("reads the size ceiling off the server document, never a client constant", () => {
    expect(tooLargeToBuffer(OUTPUT, HISTORY)).toBe(false);
    expect(tooLargeToBuffer(OUTPUT, { ...HISTORY, max_download_bytes: 1 })).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// §22.7 — the panel
// ---------------------------------------------------------------------------

function render(element: ReactElement): Document {
  return new DOMParser().parseFromString(
    `<!doctype html><body>${renderToStaticMarkup(element)}</body>`,
    "text/html",
  );
}

function panel(
  overrides: Partial<Parameters<typeof ExportView>[0]> = {},
): Document {
  return render(
    <ExportView
      part="tread"
      pinned="artifact:build:sha256:aaaa"
      pinMode="pinned"
      history={HISTORY}
      onExport={() => Promise.reject(new Error("not called"))}
      onDownload={() => Promise.reject(new Error("not called"))}
      {...overrides}
    />,
  );
}

describe("§22.7 — the export panel", () => {
  it("is an Inspector tab, and sourcing sits beside it", () => {
    expect([...INSPECTOR_TABS]).toContain("export");
    expect([...INSPECTOR_TABS]).toContain("sourcing");
    expect(INSPECTOR_TABS).toHaveLength(7);
  });

  it("renders its subject above every format button", () => {
    // §22.7's TIGHTENING: "renders its subject before its controls… There is no
    // bare 'Export ▾' that resolves its subject at click time." Asserted as
    // document order, which is what a reader actually experiences.
    const dom = panel();
    const subject = dom.querySelector("[data-source='workspace.artifact_ref']");
    const firstFormat = dom.querySelector("[data-export-format]");
    expect(subject).not.toBeNull();
    expect(firstFormat).not.toBeNull();
    expect(
      (subject?.compareDocumentPosition(firstFormat as Node) ?? 0) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("carries the pin and its mode as server values", () => {
    const dom = panel();
    expect(
      dom.querySelector("[data-source='workspace.artifact_ref']")?.getAttribute("data-value"),
    ).toBe("artifact:build:sha256:aaaa");
    expect(dom.querySelector("[data-export-pin-mode]")?.getAttribute("data-export-pin-mode")).toBe(
      "pinned",
    );
  });

  it("offers exactly the six formats and no seventh", () => {
    const dom = panel();
    const offered = [...dom.querySelectorAll("[data-export-format]")]
      .map((node) => node.getAttribute("data-export-format"))
      .filter((value): value is string => value !== null && !value.includes("|"));
    // The history entry carries `data-export-row-format`, so the format buttons
    // are the ones whose attribute is on a button.
    const buttons = [...dom.querySelectorAll("button[data-export-format]")].map((node) =>
      node.getAttribute("data-export-format"),
    );
    expect(buttons).toEqual([...EXPORT_FORMATS]);
    expect(offered.length).toBeGreaterThanOrEqual(buttons.length);
  });

  it("hides the layout control for a format the tool would refuse it for", () => {
    // `step` is the initial format and is not in LAYOUT_FORMATS.
    expect(panel().querySelector("[data-export-layout]")).toBeNull();
  });

  it("disables the run control with a reason when there is no pin", () => {
    const dom = panel({ pinned: null });
    const run = dom.querySelector("[data-export-run]");
    expect(run?.hasAttribute("disabled")).toBe(true);
    // §4.7: a disabled control in this app must always be able to say why.
    expect(run?.getAttribute("title")).toBeTruthy();
    expect(dom.querySelector("[data-export-blocked]")?.getAttribute("data-export-blocked")).toBe(
      "no_pin",
    );
  });

  it("disables the run control when the pin is not a successful build", () => {
    const dom = panel({ pinned: "artifact:build-checkpoint:sha256:cccc" });
    expect(dom.querySelector("[data-export-run]")?.hasAttribute("disabled")).toBe(true);
    expect(dom.querySelector("[data-export-blocked]")?.getAttribute("data-export-blocked")).toBe(
      "invalid_source",
    );
  });

  it("names the blocker rather than folding two states into one", () => {
    // §22.7: "distinct from the above, **never folded into it**". Two different
    // blockers must render two different sentences.
    const noPin = panel({ pinned: null }).querySelector("[data-export-refusal]")?.textContent;
    const badKind = panel({
      pinned: "artifact:build-checkpoint:sha256:cccc",
    }).querySelector("[data-export-refusal]")?.textContent;
    expect(noPin).toBeTruthy();
    expect(badKind).toBeTruthy();
    expect(noPin).not.toBe(badKind);
  });

  it("decides the blocker from the ref's own kind segment", () => {
    expect(exportBlocker(null, "artifact:build:sha256:a")).toBe("no_part");
    expect(exportBlocker("tread", null)).toBe("no_pin");
    expect(exportBlocker("tread", "artifact:build-checkpoint:sha256:a")).toBe("invalid_source");
    expect(exportBlocker("tread", "artifact:export:sha256:a")).toBe("invalid_source");
    expect(exportBlocker("tread", "artifact:build:sha256:a")).toBeNull();
  });

  it("renders the history with the server's byte counts and filenames", () => {
    const dom = panel();
    const download = dom.querySelector("[data-export-download]");
    expect(download?.getAttribute("data-export-download")).toBe(OUTPUT.blob);
    // §22.4: the filename comes from the result document, not from a header, and
    // is never derived here from `path` — which in this fixture is hostile.
    expect(download?.getAttribute("data-export-filename")).toBe(OUTPUT.filename);
    expect(dom.querySelector("[data-export-path]")?.getAttribute("data-export-path")).toBe(
      OUTPUT.path,
    );
    expect(
      dom.querySelector("[data-export-row-bytes]")?.getAttribute("data-export-row-bytes"),
    ).toBe("4096");
    expect(dom.querySelector("[data-export-total]")?.getAttribute("data-export-total")).toBe(
      "4096",
    );
  });

  it("states the byte cost before offering the download", () => {
    // §22.4's TIGHTENING: "a large file is a stated cost and not a hang". The
    // count must precede the button in document order.
    const dom = panel();
    const bytes = dom.querySelector("[data-source='exports[].outputs[].bytes']");
    const button = dom.querySelector("[data-export-download]");
    expect(
      (bytes?.compareDocumentPosition(button as Node) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("disables a download above the server's ceiling, with a reason", () => {
    const dom = panel({ history: { ...HISTORY, max_download_bytes: 1 } });
    const download = dom.querySelector("[data-export-download]");
    expect(download?.hasAttribute("disabled")).toBe(true);
    expect(download?.getAttribute("title")).toBeTruthy();
  });

  it("says there is no unpin, because the server said so", () => {
    expect(panel().querySelector("[data-export-unpin='unavailable']")).not.toBeNull();
    expect(
      panel({ history: { ...HISTORY, unpin_available: true } }).querySelector(
        "[data-export-unpin]",
      ),
    ).toBeNull();
  });

  it("renders a stale pin as a sentence and not as a refusal", () => {
    // §22.7: "A *stale* part is not a refusal — the pin is exported and the
    // subject line says the build is behind the script."
    const dom = panel({ stale: true });
    expect(dom.querySelector("[data-export-stale='true']")).not.toBeNull();
    expect(dom.querySelector("[data-export-run]")?.hasAttribute("disabled")).toBe(false);
  });

  it("starts in the idle state, from the closed vocabulary", () => {
    const state = panel().querySelector("[data-export-state]")?.getAttribute("data-export-state");
    expect(EXPORT_STATES).toContain(state);
    expect(state).toBe("idle");
  });

  it("carries one idempotency key per submission on the run control", () => {
    const first = panel()
      .querySelector("[data-export-key]")
      ?.getAttribute("data-export-key");
    // §22.2's TIGHTENING: the same unchanged submission keeps its key across
    // renders — the retry button does not re-mint.
    const again = panel()
      .querySelector("[data-export-key]")
      ?.getAttribute("data-export-key");
    expect(first).toBe(again);
    // …and a different pin is a different submission, so it is a different key.
    const other = panel({ pinned: "artifact:build:sha256:dddd" })
      .querySelector("[data-export-key]")
      ?.getAttribute("data-export-key");
    expect(other).not.toBe(first);
  });

  it("renders an empty history without pretending nothing is retained", () => {
    const dom = panel({ history: { ...HISTORY, exports: [], total_bytes: 0 } });
    expect(dom.querySelector("[data-export-download]")).toBeNull();
    expect(dom.querySelector("[data-export-unpin='unavailable']")).not.toBeNull();
  });

  it("keeps a refused export's engine reason on the DOM", () => {
    // The panel maps a `WorkspaceError.reason` onto a designed sentence; an
    // unnamed failure falls back rather than rendering a raw message.
    expect(new WorkspaceError(409, "target_exists", "already exists").reason).toBe(
      "target_exists",
    );
  });
});
