// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A named refusal, rendered by name (INTERFACE.md §2.4).
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

import { WorkspaceError } from "../api/client";
import { copy } from "../copy";
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
    <div className={styles["banner"]} role="alert" data-refusal-reason={error.reason}>
      <span className={styles["title"]}>{copy.errors.title}</span>
      <span className={styles["reason"]}>
        {copy.errors.reason}: <code>{error.reason}</code>
      </span>
      <span className={styles["message"]}>
        {unauthorized ? copy.errors.unauthorized : error.message}
      </span>
      {onRetry === undefined || unauthorized ? null : (
        <button type="button" className={styles["retry"]} onClick={onRetry}>
          {copy.errors.retry}
        </button>
      )}
    </div>
  );
}
