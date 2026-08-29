// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A named refusal, rendered by name (INTERFACE.md §2.4, §4.7).
//
// §2.4's envelope is `{status, reason, message, …data}` and the reason is the
// *machine* word — `unauthorized`, `unknown_artifact`, `stale_selection`,
// `git_unavailable`. Collapsing that to "something went wrong" is the same
// defect §4.4 names for provenance: an answer that does not say why it is weak
// reads as a bug rather than as an instrument being honest. So the banner shows
// the reason verbatim beside the human message, and `unauthorized` — the one
// reason a human can act on without reading the engine — gets its own sentence.
//
// No retry button for `unauthorized`: §2.2 has no credential to re-present, and
// a control whose only outcome is the same refusal is not a control.
//
// §4.7 — "**kept, promoted.** The closest-to-right component already shipped."
// It gains `role="alert"` + `aria-live="assertive"` (§3.13.5), a `.title`
// heading, **the reason code as a `Chip` in `.code`**, a `secondary` retry
// `Button`, and the shared danger fill so it is the same recipe as every other
// danger surface in the system rather than a fifth hand-mixed one.

import { WorkspaceError } from "../api/client";
import { copy } from "../copy";
import { Button, Chip, Icon } from "../system";
import styles from "./RefusalBanner.module.css";

export function RefusalBanner({
  error,
  onRetry,
}: {
  readonly error: unknown;
  readonly onRetry?: (() => void) | undefined;
}): React.JSX.Element | null {
  if (!(error instanceof WorkspaceError)) return null;
  const unauthorized = error.reason === "unauthorized";
  return (
    <div
      className={styles["banner"]}
      role="alert"
      aria-live="assertive"
      data-refusal-reason={error.reason}
    >
      <Icon id="alert" size={15} className={styles["icon"]} />
      <p className={styles["title"]}>{copy.errors.title}</p>
      <Chip tone="code" title={copy.errors.reason} data-refusal-code={error.reason}>
        {error.reason}
      </Chip>
      <p className={styles["message"]}>
        {unauthorized ? copy.errors.unauthorized : error.message}
      </p>
      {onRetry === undefined || unauthorized ? null : (
        <Button variant="secondary" icon="refresh" onClick={onRetry} data-refusal-retry="">
          {copy.errors.retry}
        </Button>
      )}
    </div>
  );
}
