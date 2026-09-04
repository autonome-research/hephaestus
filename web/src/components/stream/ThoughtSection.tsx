// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `thought` and `text_delta` (INTERFACE.md §7.3).
//
// §7.3: "`text_delta` → streamed assistant text"; "`thought` → collapsed
// `ThoughtSection`, expandable, `data-event-id` present."
//
// EXPANDABILITY IS `<details>`, not state. A native disclosure is keyboard
// reachable, works with no JavaScript, and is testable from static markup — the
// accessibility floor §3 states as a floor rather than a gap. Collapsed by
// default, because reasoning is context for the transcript and not the
// transcript.
//
// GROUPING NEVER EATS AN IDENTITY. A live stream emits one `thought` per
// thinking delta, so contiguous deltas group into one section; a reopened
// transcript emits one per whole thinking block, so a group is usually one
// event. Either way every event's id reaches the DOM exactly once: a group of
// one puts its id on the section, a group of many puts one span per event
// inside. G4.11 matches archived ids against the reopened DOM, and an id lost to
// grouping would be an id the gate cannot find.

import { readText } from "../../api/events";
import { copy } from "../../copy";
import { Markdown } from "../../stream/markdown";
import type { TranscriptItem } from "../../stream/transcript";
import styles from "./Transcript.module.css";

function text(item: TranscriptItem): string {
  return readText(item.payload) ?? "";
}

export function ThoughtSection({
  items,
}: {
  readonly items: readonly TranscriptItem[];
}): React.JSX.Element | null {
  const first = items[0];
  if (first === undefined) return null;
  const single = items.length === 1;
  const joined = items.map(text).join("");
  // §7.3, W4: an EMPTY run is a named absence, not an empty body. `Markdown`
  // renders `""` as `null`, so the disclosure used to open on nothing at all —
  // a control that appears broken rather than a state that reads as designed
  // (§4.4). The row still renders: the events happened and their ids must stay
  // in the DOM (G4.11 matches archived ids against the reopened transcript), so
  // the honest move is to say what is missing, not to drop the row.
  //
  // The sidecar guards this at the source — an empty `thinking` item emits no
  // `thought` event at all (`agent/src/session/history.ts`, W1) — so this is
  // the client's own floor for a legacy record or an older bundle, not a
  // duplicate of that fix. It says nothing about WHY the text is empty, because
  // the client does not know.
  const empty = joined.trim() === "";

  return (
    <details
      className={styles["thought"]}
      data-thought="1"
      data-surface={first.surface}
      {...(single ? { "data-event-id": first.eventId } : {})}
    >
      <summary className={styles["thoughtSummary"]}>
        <span>{copy.stream.thought}</span>
        {single ? null : (
          <span className={styles["thoughtCount"]}>{copy.stream.thoughtParts(items.length)}</span>
        )}
      </summary>
      <div className={styles["thoughtBody"]} {...(empty ? {} : { "data-markdown": "" })}>
        {single ? null : (
          <>
            {items.map((item) => (
              <span key={item.eventId} data-event-id={item.eventId} className={styles["eventAnchor"]} />
            ))}
          </>
        )}
        {empty ? (
          <p className={styles["thoughtAbsence"]} data-thought-empty="1">
            {copy.stream.thoughtEmpty}
          </p>
        ) : (
          <Markdown text={joined} />
        )}
      </div>
    </details>
  );
}

export function TextBlock({
  items,
}: {
  readonly items: readonly TranscriptItem[];
}): React.JSX.Element | null {
  const first = items[0];
  if (first === undefined) return null;
  const joined = items.map(text).join("");

  return (
    <div
      className={styles["text"]}
      data-surface={first.surface}
      data-markdown=""
      {...(items.length === 1 ? { "data-event-id": first.eventId } : {})}
    >
      {items.length > 1
        ? items.map((item) => (
            <span key={item.eventId} data-event-id={item.eventId} className={styles["eventAnchor"]} />
          ))
        : null}
      <Markdown text={joined} />
    </div>
  );
}
