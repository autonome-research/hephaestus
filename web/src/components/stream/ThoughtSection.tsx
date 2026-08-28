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
      <div className={styles["thoughtBody"]}>
        {single
          ? text(first)
          : items.map((item) => (
              <span key={item.eventId} data-event-id={item.eventId}>
                {text(item)}
              </span>
            ))}
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
  const single = items.length === 1;

  return (
    <p
      className={styles["text"]}
      data-surface={first.surface}
      {...(single ? { "data-event-id": first.eventId } : {})}
    >
      {single
        ? text(first)
        : items.map((item) => (
            <span key={item.eventId} data-event-id={item.eventId}>
              {text(item)}
            </span>
          ))}
    </p>
  );
}
