// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The Stream column's EXCEPTION ROW (INTERFACE.md §7.4, §8, both amended
// 2026-09-01 under §0.2b — the badge and the page counter are exception-only;
// §4.1(h) C25, amended 2026-09-02, gives the row its named home: directly
// below the session tab strip and above the transcript scroll region, one
// shared row when both mount, badge leading).
//
// A SEPARATE COMPONENT, and the reason is testability rather than taste.
// `StreamPanel` mounts a query client, a socket and the workspace store, so the
// only assertions its own tests can make are over its source text. Both clauses
// this row implements have an explicit negative half — the badge "does not
// mount… no element, not a muted one, not a dot", the counter "no `historyBar`
// element mounts" — and a negative half is an assertion about the DOM. This
// component is a pure function of its props, so both halves are read from the
// rendered document, which is what the e2e reads too.
//
// WHAT IS **NOT** HERE. `data-stream`, `data-history-state` and
// `data-history-pages` are on the panel root, unconditionally, because §7.4(b)
// and §8(c) make them the durable hooks the gates read in *every* state — the
// badge is the drawn exception, not the record. Putting them here would make
// the record disappear with the row, which is the failure both clauses name.
//
// The row itself does not mount when it would be empty: §7.4(a)'s steady live
// state has no badge, §8(b)'s one-page history has no counter, and a bordered
// 32px strip with nothing in it is the furniture §0.2b measured.

import { copy } from "../../copy";
import { Badge, type BadgeStatus } from "../../system";
import type { HistoryProgress } from "../../stream/history";
import type { RuntimeFault } from "../../stream/runtimeFault";
import type { StreamState } from "../../stream/transcript";
import { showsHistoryBar, showsStreamBadge } from "../../stream/streamChrome";
import styles from "./Stream.module.css";

/**
 * §7.4's five stream states onto §4.7's six-value badge vocabulary.
 *
 * `live` keeps its entry although §7.4(a) never draws it: the map stays total
 * over the closed vocabulary for the same reason `copy.stream.stateWhy` does —
 * so a future state cannot land without a tone.
 */
const STREAM_STATUS: Readonly<Record<StreamState, BadgeStatus>> = {
  live: "pass",
  reconnecting: "error",
  resyncing: "error",
  historical: "info",
  detached: "not_run",
};

export interface StreamHeaderProps {
  readonly status: StreamState;
  readonly fault: RuntimeFault | null;
  /** `null` when there is no history to report — an `agent_unavailable` panel. */
  readonly history: HistoryProgress | null;
  readonly resyncs: number;
}

export function StreamHeader({
  status,
  fault,
  history,
  resyncs,
}: StreamHeaderProps): React.JSX.Element | null {
  const bar = history !== null && showsHistoryBar(history);
  const badge = showsStreamBadge(status, fault);
  // §7.4(c): the resync readout is an exception by construction and keeps
  // rendering exactly as specified. It is the third thing that can hold the row
  // open, and the only one of the three that survives a `live` socket.
  const count = resyncs > 0;
  if (!bar && !badge && !count) return null;

  return (
    <div className={styles["header"]}>
      {/* §4.1(h) C25: one shared exception row directly below the tab strip,
          BADGE LEADING — §7.4(a): four states and a runtime fault. When a
          fault is known the badge shows THAT, because it is the fact that
          changes what the operator does next; the socket's own answer stays on
          the panel root's `data-stream`, so a reader inspecting the DOM can
          tell them apart. */}
      {badge ? (
        <Badge
          status={fault !== null ? "error" : STREAM_STATUS[status]}
          title={fault !== null ? copy.stream.runtimeFaultWhy[fault] : copy.stream.stateWhy[status]}
          data-stream-state={status}
        >
          {fault !== null ? copy.stream.runtimeFault[fault] : copy.stream.state[status]}
        </Badge>
      ) : null}

      {count ? (
        <span className={styles["resyncCount"]} data-resync-count={resyncs}>
          {resyncs}
        </span>
      ) : null}

      {/* §8(a): a read that did not complete stays loud, and a bounded walk says
          how many pages of recorded transcript sit above what is drawn. The
          count that used to render for every session — "1 page of recorded
          transcript" — is a row spent saying there is nothing to say. */}
      {bar && history !== null ? (
        <span className={styles["historyBar"]} data-history-bar={history.state}>
          {/* A failed read has no count to report, and "0 pages" beside a
              stated failure claims a number the load never reached. The
              panel root's `data-history-pages` still carries the count. */}
          {history.state === "failed"
            ? copy.stream.historyFailed
            : copy.stream.historyPages(history.pages)}
        </span>
      ) : null}
    </div>
  );
}
