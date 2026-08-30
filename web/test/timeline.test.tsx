// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Statement Timeline: marks from `GET /parts/{part}/build` only, rewind is
// `hold(error.last_good_artifact_ref)`. No invented statement events.

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
} from "../src/components/stage/timelineMarks";

const failed = failedJson as BuildDocument;
const ok = okJson as BuildDocument;
const LAST_GOOD = failed.error?.last_good_artifact_ref ?? "";

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

describe("marksFromBuild", () => {
  it("emits last-good then failed from the error projection, and nothing else", () => {
    const marks = marksFromBuild(failed);
    expect(marks.map((mark) => mark.kind)).toEqual(["last_good", "failed"]);
    expect(marks[0]?.artifact_ref).toBe(LAST_GOOD);
    // No statement index, no script-derived events, no geometry recount.
    expect(marks).toHaveLength(2);
  });

  it("emits only current on a successful build — there is no last-good to invent", () => {
    const marks = marksFromBuild(ok);
    expect(marks.map((mark) => mark.kind)).toEqual(["current"]);
    expect(marks[0]?.artifact_ref).toBe(ok.artifact_ref);
  });

  it("emits nothing for a named absence", () => {
    expect(
      marksFromBuild({
        status: "not_built",
        current: false,
        geometry_count: 0,
        geometries: [],
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
  });

  it("rewinds by holding the last-good ref and follows current otherwise", () => {
    const marks = marksFromBuild(failed);
    expect(actionForIndex(marks, 0, null)).toEqual({ action: "hold", ref: LAST_GOOD });
    expect(actionForIndex(marks, 1, null)).toEqual({ action: "follow", currentRef: null });
  });
});

describe("TimelineView", () => {
  it("renders the last-good ref as a fact and the two projected marks", () => {
    const host = render(
      <TimelineView build={failed} pin={null} onRewind={() => undefined} onFollowCurrent={() => undefined} />,
    );
    const marks = [...host.querySelectorAll("[data-timeline-mark]")].map((node) =>
      node.getAttribute("data-timeline-mark"),
    );
    expect(marks).toEqual(["last_good", "failed"]);
    const fact = host.querySelector('[data-source="build.error.last_good_artifact_ref"]');
    expect(fact?.getAttribute("data-value")).toBe(LAST_GOOD);
    const statement = host.querySelector('[data-source="build.error.built_through.statement"]');
    expect(statement?.getAttribute("data-value")).toBe(
      failed.error?.built_through?.statement ?? "",
    );
    expect(host.querySelector("[data-timeline-scrub]")).not.toBeNull();
  });

  it("does not invent a scrubber on a successful build", () => {
    const host = render(
      <TimelineView build={ok} pin={ok.artifact_ref ?? null} onRewind={() => undefined} onFollowCurrent={() => undefined} />,
    );
    expect(host.querySelector("[data-timeline-scrub]")).toBeNull();
    expect(host.querySelectorAll("[data-timeline-mark]")).toHaveLength(0);
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
