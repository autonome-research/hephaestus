// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-stream-11: the export panel and the header chrome drive the same
// `POST /parts/{part}/export` submission with what used to be two hand-copied
// state machines. A shared `useExportSubmission` hook now lives in
// `components/export/submission.ts`; this file is the PAIRED assertion the
// ledger asks for — one behavioural table driven against BOTH surfaces —
// which is what keeps a future edit to one from drifting from the other again,
// the way the panel's own stale-result clear once did.
//
// BOTH surfaces now run that one hook: `ExportView` (the inspector tab) and
// `ExportChrome` (the header dialog) hold no export state of their own and
// differ only in the submission they build and the markup they render, which is
// the part that legitimately differs. The table below is what keeps that true —
// the divergence it guards against is the one that actually happened, where the
// chrome's `run` cleared the previous result and the panel's did not.

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { ExportView, resetSubmissionKeys, type Submission } from "../src/components/inspector/ExportPanel";
import { ExportChrome } from "../src/components/chrome/ExportChrome";
import type { ExportOutput, ExportResult, ExportsDocument } from "../src/api/exports";
import { WorkspaceError } from "../src/api/client";
import { claimToken, dropToken } from "../src/api/token";

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

const PINNED = "artifact:build:sha256:" + "a".repeat(64);

function successResult(overrides: Partial<ExportResult> = {}): ExportResult {
  return {
    paths: ["out/bracket.step"],
    source_artifact_ref: PINNED,
    source_input_hashes: {},
    export_hashes: { step: "sha256:" + "b".repeat(64) },
    kerf: { applied_mm: 0.2, source: "process_pack", process: "laser_cut" },
    ...overrides,
  };
}

/** A committed history matching `successResult()`'s STEP output, for `producedRow`. */
function historyWithProducedStep(): ExportsDocument {
  return {
    status: "ok",
    part: "bracket",
    total_bytes: 4096,
    unpin_available: false,
    max_download_bytes: 50_000_000,
    exports: [
      {
        op_id: "op-1",
        format: "step",
        layout: "as_built",
        state: "COMMITTED",
        source_artifact_ref: PINNED,
        source_input_hashes: {},
        extra: {},
        total_bytes: 4096,
        outputs: [
          {
            path: ".heph/exports/bracket.step",
            blob: "blob-1",
            bytes: 4096,
            content_type: "model/step",
            filename: "bracket.step",
          },
        ],
      },
    ],
  };
}

/** Flush the microtask queue enough times for a chained `.then().catch().finally()`. */
async function flush(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

function mount(element: React.ReactElement): { host: HTMLElement; root: Root } {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(element);
  });
  return { host, root };
}

function unmount(mounted: { host: HTMLElement; root: Root }): void {
  act(() => {
    mounted.root.unmount();
  });
  mounted.host.remove();
}

/** One surface under test, named so a failure names which one broke. */
interface Surface {
  readonly name: string;
  readonly mount: (
    onExport: (submission: Submission) => Promise<ExportResult>,
    onDownload: (output: ExportOutput) => Promise<void>,
    part?: string,
  ) => { host: HTMLElement; root: Root };
  /** Whether the surface shows a fact attributable to a produced RESULT. */
  readonly showsResult: (host: HTMLElement) => boolean;
}

const SURFACES: readonly Surface[] = [
  {
    name: "ExportView (inspector tab)",
    mount: (onExport, onDownload, part = "bracket") =>
      mount(
        <ExportView
          part={part}
          pinned={PINNED}
          pinMode="pinned"
          history={historyWithProducedStep()}
          onExport={onExport}
          onDownload={onDownload}
        />,
      ),
    // The kerf block is only ever rendered from `result.kerf` (§22.1).
    showsResult: (host) => host.querySelector("[data-export-kerf]") !== null,
  },
  {
    name: "ExportChrome (header dialog)",
    mount: (onExport, onDownload, part = "bracket") =>
      mount(
        <ExportChrome
          part={part}
          pinned={PINNED}
          pinMode="pinned"
          history={historyWithProducedStep()}
          onExport={onExport}
          onDownload={onDownload}
          onOpenInspector={() => undefined}
        />,
      ),
    // The produced-file row is only ever rendered from a matched `result`.
    showsResult: (host) => host.querySelector("[data-export-file]") !== null,
  },
];

describe("both export surfaces clear the previous result on a new refused submission (J-web-stream-11)", () => {
  afterEach(() => {
    resetSubmissionKeys();
    dropToken();
  });

  it.each(SURFACES)("$name: a refusal after a success shows the refusal and no stale result", async (surface) => {
    window.history.replaceState(null, "", "/#t=export-tok");
    claimToken();
    let call = 0;
    const onExport = async (): Promise<ExportResult> => {
      call += 1;
      if (call === 1) return successResult();
      throw new WorkspaceError(409, "kerf_unresolved", "no kerf process for this material");
    };
    const onDownload = async (): Promise<void> => undefined;

    const mounted = surface.mount(onExport, onDownload);
    try {
      // First submission: succeeds, and the result-derived fact renders.
      await act(async () => {
        mounted.host.querySelector<HTMLButtonElement>("[data-export-run]")?.click();
      });
      await flush();
      expect(surface.showsResult(mounted.host)).toBe(true);

      // Second submission on the SAME mount: refused. The previous result must
      // not survive into a submission that produced no result at all — a fact
      // surviving here is a §1/§4.6 violation, not a cosmetic one.
      await act(async () => {
        mounted.host.querySelector<HTMLButtonElement>("[data-export-run]")?.click();
      });
      await flush();
      expect(mounted.host.querySelector("[data-export-refusal]")).not.toBeNull();
      expect(surface.showsResult(mounted.host)).toBe(false);
    } finally {
      unmount(mounted);
    }
  });

  it.each(SURFACES)("$name: a failed download followed by a success clears the download refusal", async (surface) => {
    window.history.replaceState(null, "", "/#t=export-tok");
    claimToken();
    const onExport = async (): Promise<ExportResult> => successResult();
    let downloadCall = 0;
    const onDownload = async (): Promise<void> => {
      downloadCall += 1;
      if (downloadCall === 1) {
        throw new WorkspaceError(500, "download_failed", "the bytes could not be read");
      }
    };

    const mounted = surface.mount(onExport, onDownload);
    try {
      await act(async () => {
        mounted.host.querySelector<HTMLButtonElement>("[data-export-run]")?.click();
      });
      await flush();
      const downloadButton = () =>
        mounted.host.querySelector<HTMLButtonElement>("[data-export-download]");
      expect(downloadButton()).not.toBeNull();

      await act(async () => {
        downloadButton()?.click();
      });
      await flush();
      expect(mounted.host.querySelector("[data-export-download-refusal]")).not.toBeNull();

      await act(async () => {
        downloadButton()?.click();
      });
      await flush();
      expect(mounted.host.querySelector("[data-export-download-refusal]")).toBeNull();
    } finally {
      unmount(mounted);
    }
  });

  it.each(SURFACES)("$name: the refusal literal appears at most once in the rendered markup", async (surface) => {
    window.history.replaceState(null, "", "/#t=export-tok");
    claimToken();
    const onExport = async (): Promise<ExportResult> => {
      throw new WorkspaceError(409, "kerf_unresolved", "no kerf process for this material");
    };
    const onDownload = async (): Promise<void> => undefined;
    const mounted = surface.mount(onExport, onDownload);
    try {
      await act(async () => {
        mounted.host.querySelector<HTMLButtonElement>("[data-export-run]")?.click();
      });
      await flush();
      const nodes = [...mounted.host.querySelectorAll("[data-export-refusal]")];
      // Zero or one element carries the attribute with non-empty text — never
      // two independent renderings of the same refusal in one surface.
      const withText = nodes.filter((node) => (node.textContent ?? "").trim().length > 0);
      expect(withText.length).toBeLessThanOrEqual(1);
    } finally {
      unmount(mounted);
    }
  });

  it.each(SURFACES)(
    "$name: the same idempotency key survives a remount of an unchanged submission, and a changed part mints a fresh one",
    (surface) => {
      const onExport = async (): Promise<ExportResult> => successResult();
      const onDownload = async (): Promise<void> => undefined;

      const first = surface.mount(onExport, onDownload, "assembly_jig");
      const firstKey = first.host.querySelector("[data-export-run]")?.getAttribute("data-export-key");
      expect(firstKey).toBeTruthy();
      unmount(first);

      // Remounting with the IDENTICAL submission (switching Inspector tabs, or
      // reopening the chrome dialog) must reuse the key: the operator has not
      // sent a new one, only re-rendered the control for it (§22.2). The
      // `SUBMISSION_KEYS` map is module-scoped precisely so this remount does
      // not mint a new key for an already-sendable submission.
      const again = surface.mount(onExport, onDownload, "assembly_jig");
      const againKey = again.host.querySelector("[data-export-run]")?.getAttribute("data-export-key");
      expect(againKey).toBe(firstKey);
      unmount(again);

      // A held pin can outlive a rail click (#100): a DIFFERENT part is a
      // different submission and must mint a fresh key, never reuse the
      // retained one above.
      const otherPart = surface.mount(onExport, onDownload, "kerf_card");
      const otherPartKey = otherPart.host
        .querySelector("[data-export-run]")
        ?.getAttribute("data-export-key");
      expect(otherPartKey).not.toBe(firstKey);
      unmount(otherPart);
    },
  );
});
