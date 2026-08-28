// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `image` events (INTERFACE.md §7.3). Three renderings, three different facts.
//
// * **Live, decodable.** The event carries base64 `data` and a `mimeType`
//   (`live.ts`), so the image is shown inline. §0's deficit closed: "the images
//   live in the transcript, not only in `.heph/agent_images/`".
// * **Live, oversized or undecodable.** A labelled placeholder, and it never
//   throws — the CLI's precedent. A browser that fails to decode a data URI
//   fires `onerror`; that is the one signal available and it is used.
// * **Historical.** `normalizeEntries` emits `{mimeType}` alone; the base64
//   `data` that the live path carries is **not retained** in the archived
//   payload. So a reopened transcript renders a labelled metadata placeholder
//   stating the mime type and that the bytes are not kept. Rendering nothing
//   would read as "the agent produced no image", which is false; carrying the
//   bytes into Pi entries would be engine new work no G4/G5 clause asks for.
//
// Every branch carries `data-image-state` so a test can tell which of the three
// it got, and `data-event-id` so the archive can find it.

import { useState } from "react";
import { readImage } from "../../api/events";
import { copy } from "../../copy";
import type { TranscriptItem } from "../../stream/transcript";
import styles from "./Transcript.module.css";

/** Closed: what this component decided to show, and why. */
export const IMAGE_STATES = ["shown", "metadata_only", "undecodable"] as const;
export type ImageState = (typeof IMAGE_STATES)[number];

export function EventImageInline({
  item,
}: {
  readonly item: TranscriptItem;
}): React.JSX.Element {
  const [failed, setFailed] = useState(false);
  const payload = readImage(item.payload);
  const mimeType = payload?.mimeType ?? null;
  const data = payload?.data ?? null;
  const state: ImageState = data === null ? "metadata_only" : failed ? "undecodable" : "shown";

  return (
    <figure
      className={styles["image"]}
      data-event-id={item.eventId}
      data-surface={item.surface}
      data-image-state={state}
      {...(mimeType === null ? {} : { "data-mime-type": mimeType })}
    >
      {state === "shown" && data !== null ? (
        <img
          className={styles["imageBody"]}
          alt={copy.stream.image.alt}
          src={`data:${mimeType ?? "image/png"};base64,${data}`}
          onError={() => {
            setFailed(true);
          }}
        />
      ) : (
        <div className={styles["imagePlaceholder"]}>
          {state === "metadata_only"
            ? copy.stream.image.historicalPlaceholder
            : copy.stream.image.undecodable}
        </div>
      )}
      <figcaption className={styles["imageCaption"]}>
        <span>
          {copy.stream.image.mimeType}: {mimeType ?? copy.absent.unavailable}
        </span>
        {payload?.bytes === null || payload === null ? null : (
          <span>
            {copy.stream.image.bytes}: {payload.bytes}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
