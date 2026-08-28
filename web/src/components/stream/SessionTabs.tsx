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
// `data-thread-state="unlinked"` is §2.8's honesty state and it is *stated*, not
// implied by an absent indent: an unindented tab and a session whose parent
// cannot be recovered look identical, and only one of them is a fact about the
// project. A pre-existing transcript reopens flat and says why.
//
// A browser tab is a client, never a lease holder (§7.1). Selecting a tab
// changes `?s=` in the §4.5 route and nothing else — no lease is taken, no
// session is created, and the CLI's hold on a session is untouched.

import { copy } from "../../copy";
import type { SessionRow } from "../../api/sessions";
import type { ThreadTab } from "../../stream/thread";
import { originPart } from "../../stream/thread";
import styles from "./Stream.module.css";

export interface SessionTabsProps {
  readonly tabs: readonly ThreadTab[];
  readonly sessions: readonly SessionRow[];
  readonly selected: string | null;
  readonly onSelect: (sessionId: string) => void;
  readonly bounded: boolean;
}

const PROFILE_LABELS = copy.stream.profile;
const EDGE_LABELS = copy.stream.edgeKind;

function profileLabel(profile: string | undefined): string | null {
  if (profile === undefined) return null;
  if (profile === "orchestrator" || profile === "part" || profile === "quick_edit") {
    return PROFILE_LABELS[profile];
  }
  // A profile outside `SESSION_PROFILES` is shown as the server spelled it
  // rather than mapped onto a neighbour.
  return profile;
}

function edgeLabel(kind: string | null): string | null {
  if (kind === "quick_edit" || kind === "delegation") return EDGE_LABELS[kind];
  return kind;
}

export function SessionTabs({
  tabs,
  sessions,
  selected,
  onSelect,
  bounded,
}: SessionTabsProps): React.JSX.Element {
  const byId = new Map(sessions.map((row) => [row.session_id, row]));

  return (
    <div className={styles["tabs"]}>
      <h2 className={styles["tabsHeading"]}>{copy.stream.sessionsHeading}</h2>
      {bounded ? <p className={styles["note"]}>{copy.stream.threadBounded}</p> : null}
      <ul className={styles["tabList"]} role="tablist" aria-label={copy.stream.sessionsHeading}>
        {tabs.map((tab) => {
          const row = byId.get(tab.session_id);
          const part = row?.part ?? originPart(tab.origin);
          const kind = edgeLabel(tab.kind);
          return (
            <li key={tab.session_id} className={styles["tabItem"]}>
              <button
                type="button"
                role="tab"
                aria-selected={selected === tab.session_id}
                className={styles["tab"]}
                data-session-tab={tab.session_id}
                data-thread-depth={tab.depth}
                data-thread-state={tab.thread_state}
                {...(tab.kind === null ? {} : { "data-thread-kind": tab.kind })}
                {...(part === null || part === undefined ? {} : { "data-part": part })}
                style={{ paddingLeft: `calc(var(--space-2) + ${String(tab.depth)} * var(--space-4))` }}
                onClick={() => {
                  onSelect(tab.session_id);
                }}
                title={tab.thread_state === "unlinked" ? copy.stream.unlinkedWhy : undefined}
              >
                <span className={styles["tabLabel"]}>{part ?? tab.session_id}</span>
                <span className={styles["tabMeta"]}>
                  {profileLabel(row?.profile) ?? (kind ?? copy.absent.unavailable)}
                </span>
                {/* The state lives on the button alone: two elements carrying
                    `data-thread-state` would double every selector that reads
                    it, and the tab IS the thing that is linked or not. */}
                <span className={styles["tabThread"]}>
                  {copy.stream.threadState[tab.thread_state]}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
