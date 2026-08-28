// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The shell (INTERFACE.md §4.1): HEADER over RAIL | STAGE | STREAM.
//
// The STREAM is "a full-height peer column, collapsible but not hidden by
// default. Giving the agent a column rather than a bottom drawer is the
// 'collaborator, not console' claim cashed out in layout." It is a peer here
// even though its contents are §7's work — collapsing it into a drawer now and
// promoting it later would be exactly the claim §4.1 says the layout makes.

import { useState } from "react";
import { useProject } from "../api/queries";
import { copy } from "../copy";
import { useWorkspace } from "../state/react";
import { Header } from "./Header";
import { RefusalBanner } from "./RefusalBanner";
import { GitDirtyPanel } from "./rail/GitDirty";
import { ProjectTree } from "./rail/ProjectTree";
import { VersionList } from "./rail/VersionList";
import { Stage } from "./stage/Stage";
import { StreamPanel } from "./stream/StreamPanel";
import styles from "./Shell.module.css";

export function Shell(): React.JSX.Element {
  const [streamOpen, setStreamOpen] = useState(true);
  // §4.1: when the pin is not the current build "the header is visibly marked
  // and every panel below inherits that marking". The attribute is the
  // inheritance: any panel can style against `[data-pin-mode="pinned"] …`.
  const pinMode = useWorkspace((s) => s.pin_mode);
  // `GET /project` is the read every other panel presupposes. When *it* is
  // refused, saying which refusal it was beats N empty panels (§2.4).
  const project = useProject();

  return (
    <div className={styles["shell"]} data-pin-mode={pinMode}>
      <Header />
      <RefusalBanner
        error={project.error}
        onRetry={() => {
          void project.refetch();
        }}
      />
      <div className={styles["body"]} data-stream={streamOpen ? "open" : "collapsed"}>
        <nav className={styles["rail"]} aria-label={copy.rail.title}>
          <ProjectTree />
          <GitDirtyPanel />
          <VersionList />
        </nav>

        <main className={styles["stage"]}>
          <Stage />
        </main>

        <aside className={styles["stream"]} aria-label={copy.stream.title}>
          {streamOpen ? (
            <>
              <div className={styles["streamHeader"]}>
                <span className={styles["streamTitle"]}>{copy.stream.title}</span>
                <button
                  type="button"
                  className={styles["streamToggle"]}
                  aria-label={copy.stream.collapse}
                  onClick={() => {
                    setStreamOpen(false);
                  }}
                >
                  ›
                </button>
              </div>
              <StreamPanel />
            </>
          ) : (
            <div className={styles["streamStrip"]}>
              <button
                type="button"
                className={styles["stripToggle"]}
                aria-label={copy.stream.expand}
                onClick={() => {
                  setStreamOpen(true);
                }}
              >
                {copy.stream.title}
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
