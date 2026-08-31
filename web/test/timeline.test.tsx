// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Statement Timeline: marks from `GET /parts/{part}/build` only, rewind is
// `hold` of a projected checkpoint ref. No invented statement events.

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import failedJson from "./fixtures/build_failed.json";
import okJson from "./fixtures/build.json";
import type { BuildDocument } from "../src/api/types";
import { TimelineView } from "../src/components/stage/Timeline";
import {
  actionForIndex,
  indexForPin,
  kindForPin,
  marksFromBuild,
  rewindMarks,
} from "../src/components/stage/timelineMarks";

const failed = failedJson as BuildDocument;
const okRecorded = okJson as BuildDocument;
/** Recorded `build.json` predates `checkpoints[]`; compose the projection here. */
const ok: BuildDocument = {
  ...okRecorded,
  checkpoints: [
    {
      index: 0,
      line: 1,
      statement: 'PARAMS = {\n    "thickness": Param(5.5, min=3.0, max=12.0),\n}',
      span: [1, 0, 4, 1],
      bound: ["PARAMS"],
      shapes: [],
      artifact_ref: null,
    },
    {
      index: 1,
      line: 7,
      statement: "panel = Box(p.width, 40.0, p.thickness)",
      span: [7, 0, 7, 39],
      bound: ["panel"],
      shapes: ["panel"],
      artifact_ref: null,
    },
  ],
};
const LAST_GOOD = failed.error?.last_good_artifact_ref ?? "";

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

describe("marksFromBuild", () => {
  it("projects executor checkpoints and names last-good from the minted ref", () => {
    const marks = marksFromBuild(failed);
    expect(marks.map((mark) => mark.kind)).toEqual(["statement", "last_good", "failed"]);
    expect(marks[0]?.statement).toBe(failed.checkpoints?.[0]?.statement);
    expect(marks[1]?.artifact_ref).toBe(LAST_GOOD);
    expect(marks[1]?.statement).toBe(failed.checkpoints?.[1]?.statement);
    // No script-derived extra events, no geometry recount.
    expect(marks).toHaveLength(3);
  });

  it("projects successful-build checkpoints then the current artifact", () => {
    const marks = marksFromBuild(ok);
    expect(marks.map((mark) => mark.kind)).toEqual(["statement", "statement", "current"]);
    expect(marks[0]?.statement).toBe(ok.checkpoints?.[0]?.statement);
    expect(marks[2]?.artifact_ref).toBe(ok.artifact_ref);
  });

  it("falls back to last-good vs failed when the record named no checkpoints", () => {
    const marks = marksFromBuild({
      ...failed,
      checkpoints: [],
    });
    expect(marks.map((mark) => mark.kind)).toEqual(["last_good", "failed"]);
    expect(marks[0]?.artifact_ref).toBe(LAST_GOOD);
  });

  it("emits nothing for a named absence", () => {
    expect(
      marksFromBuild({
        status: "not_built",
        current: false,
        geometry_count: 0,
        geometries: [],
        checkpoints: [],
      }),
    ).toEqual([]);
  });
});

describe("the pin match", () => {
  it("selects last-good only when the pin is that checkpoint ref", () => {
    const marks = marksFromBuild(failed);
    expect(kindForPin(marks, LAST_GOOD)).toBe("last_good");
    expect(kindForPin(marks, null)).toBe("failed");
    expect(indexForPin(marks, LAST_GOOD)).toBe(0);
    expect(indexForPin(marks, null)).toBe(1);
    expect(rewindMarks(marks).map((mark) => mark.kind)).toEqual(["last_good", "failed"]);
  });

  it("rewinds by holding the last-good ref and follows current otherwise", () => {
    const marks = marksFromBuild(failed);
    expect(actionForIndex(marks, 0, null)).toEqual({ action: "hold", ref: LAST_GOOD });
    expect(actionForIndex(marks, 1, null)).toEqual({ action: "follow", currentRef: null });
  });
});

describe("TimelineView", () => {
  it("renders projected statement stops as facts and the rewindable marks", () => {
    const host = render(
      <TimelineView build={failed} pin={null} onRewind={() => undefined} onFollowCurrent={() => undefined} />,
    );
    const marks = [...host.querySelectorAll("[data-timeline-mark]")].map((node) =>
      node.getAttribute("data-timeline-mark"),
    );
    expect(marks).toEqual(["statement", "last_good", "failed"]);
    const statement = host.querySelector('[data-source="build.checkpoints[].statement"]');
    expect(statement?.getAttribute("data-value")).toBe(failed.checkpoints?.[0]?.statement ?? "");
    const fact = host.querySelector('[data-source="build.error.last_good_artifact_ref"]');
    expect(fact?.getAttribute("data-value")).toBe(LAST_GOOD);
    const builtThrough = host.querySelector('[data-source="build.error.built_through.statement"]');
    expect(builtThrough?.getAttribute("data-value")).toBe(
      failed.error?.built_through?.statement ?? "",
    );
    expect(host.querySelector("[data-timeline-scrub]")).not.toBeNull();
  });

  it("does not invent a rewind scrubber on a successful build", () => {
    const host = render(
      <TimelineView build={ok} pin={ok.artifact_ref ?? null} onRewind={() => undefined} onFollowCurrent={() => undefined} />,
    );
    expect(host.querySelector("[data-timeline-scrub]")).toBeNull();
    const marks = [...host.querySelectorAll("[data-timeline-mark]")].map((node) =>
      node.getAttribute("data-timeline-mark"),
    );
    expect(marks).toEqual(["statement", "statement", "current"]);
  });

  it("marks the last-good stop selected when that ref is pinned", () => {
    const host = render(
      <TimelineView
        build={failed}
        pin={LAST_GOOD}
        onRewind={() => undefined}
        onFollowCurrent={() => undefined}
      />,
    );
    expect(host.querySelector('[data-timeline-position="last_good"]')).not.toBeNull();
    expect(
      host.querySelector('[data-timeline-mark="last_good"]')?.getAttribute("data-selected"),
    ).toBe("true");
  });
});
