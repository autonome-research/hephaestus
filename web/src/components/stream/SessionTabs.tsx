// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §7.1's session tabs: "an orchestrator, its delegated part sessions, and a part
// session's quick-edit children form a three-level tree rendered as an indented
// tab list with `data-thread-depth`. **The edge source is
// `GET /sessions/{id}/thread` — never inference.**"
//
// So the tree here is exactly the server's `nodes`, in the server's
// breadth-first order, at the server's `depth`. Nothing is sorted, nested, or
// inferred from a session's profile or its part name.
//
// `data-thread-state="unlinked"` is §2.8's honesty state. A root is not a
// missing parent — the unlinked word is not printed there. The attribute
// stays, and the UUID stays on `title` / `data-session-id`.
//
// A browser tab is a client, never a lease holder (§7.1). Selecting a tab
// changes `?s=` in the §4.5 route and nothing else — no lease is taken, no
// session is created, and the CLI's hold on a session is untouched.
//
// The widget is `TabBar`: roving tabindex, arrows, Home/End, Tab leaves the
// list. #68's tabpanel / well-role work is a later a11y PR.

import { copy } from "../../copy";
import type { SessionRow } from "../../api/sessions";
import type { ThreadTab } from "../../stream/thread";
import { originPart } from "../../stream/thread";
import {
  sessionLabel,
  sessionTabMeta,
  sessionTitleAttr,
} from "../../stream/sessionTitle";
import { TabBar } from "../../system";
import styles from "./Stream.module.css";

export interface SessionTabsProps {
  readonly tabs: readonly ThreadTab[];
  readonly sessions: readonly SessionRow[];
  readonly selected: string | null;
  readonly onSelect: (sessionId: string) => void;
  readonly bounded: boolean;
}

export function SessionTabs({
  tabs,
  sessions,
  selected,
  onSelect,
  bounded,
}: SessionTabsProps): React.JSX.Element {
  const byId = new Map(sessions.map((row) => [row.session_id, row]));
  const selectedId = selected ?? tabs[0]?.session_id ?? "";

  return (
    <div className={styles["tabs"]}>
      {/* A heading over a list of one is a label for something the reader can
          already see. It appears once there is a choice to make. */}
      {tabs.length > 1 ? (
        <h2 className={styles["tabsHeading"]}>{copy.stream.sessionsHeading}</h2>
      ) : null}
      {bounded ? <p className={styles["note"]}>{copy.stream.threadBounded}</p> : null}
      <TabBar
        attr="data-session-tab"
        layout="stack"
        className={styles["sessionTabs"]}
        label={copy.stream.sessionsHeading}
        selected={selectedId}
        onSelect={onSelect}
        tabs={tabs.map((tab) => {
          const row = byId.get(tab.session_id);
          const part = row?.part ?? originPart(tab.origin);
          const label = sessionLabel({
            sessionId: tab.session_id,
            profile: row?.profile ?? null,
            part: row?.part ?? null,
            kind: tab.kind,
            origin: tab.origin,
            createdAt: tab.created_at ?? null,
          });
          const meta = sessionTabMeta(tab, row);
          return {
            id: tab.session_id,
            label,
            title: sessionTitleAttr(tab.session_id, tab.thread_state),
            trailing:
              meta === null ? undefined : <span className={styles["tabMeta"]}>{meta}</span>,
            style: {
              paddingLeft: `calc(var(--space-2) + ${String(tab.depth)} * var(--space-4))`,
            },
            attrs: {
              "data-session-id": tab.session_id,
              "data-thread-depth": tab.depth,
              "data-thread-state": tab.thread_state,
              ...(tab.kind === null ? {} : { "data-thread-kind": tab.kind }),
              ...(part === null || part === undefined ? {} : { "data-part": part }),
            },
          };
        })}
      />
    </div>
  );
}
