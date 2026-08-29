// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `VersionList` (INTERFACE.md §13, §2.9) — the selected part's history.
//
// `GET /git/log?part=` is `log --follow -- parts/<part>.py` (§2.9), so a rename
// does not truncate a part's history. Rows are `{sha, short, subject,
// author_date, tags[]}` verbatim; the tag names on a commit come from the same
// projection and are not joined here against `GET /git/tags`.
//
// §13.2's naming discipline, which this panel is the main site of: **the bare
// word "publish" never appears.** A build becoming `current` and a git tag are
// two different operations that G5 calls by the same word, so the workspace
// calls them "current build" and "tag release" and never lets them read as one.
// Creating a tag is a §2.3 keyed mutation (`POST /git/tag`) and is not part of
// this read-only half; the panel shows the tags that exist and offers no action.
//
// §4.7's EmptyState rule 2, the other half: when git itself is the cause, this
// panel renders NOTHING and `GitDirtyPanel` prints the sentence once for both
// sections. The shipped pair printed the identical sentence twice, in adjacent
// rail sections, above ~1000px of void.

import { useGitLog, useGitTags } from "../../api/queries";
import { copy } from "../../copy";
import { useWorkspace } from "../../state/react";
import { Chip, EmptyState, Panel, PanelBody, PanelHeader } from "../../system";
import { Fact } from "../Fact";
import { railGitAbsence, useDirtyIndex } from "./GitDirty";
import styles from "./VersionList.module.css";

/** `%aI`-shaped ISO date → the date alone. A time nobody reads is noise. */
function day(authorDate: string): string {
  const cut = authorDate.indexOf("T");
  return cut === -1 ? authorDate : authorDate.slice(0, cut);
}

export function VersionList(): React.JSX.Element | null {
  const part = useWorkspace((s) => s.part);
  const log = useGitLog(part);
  const tags = useGitTags();
  const shared = railGitAbsence(useDirtyIndex());

  // The shared cause is printed once, by the panel above. Rendering a second
  // copy of the same sentence is the defect §4.7 names, not a courtesy.
  if (shared !== null) return null;

  return (
    <Panel className={styles["panel"]} label={copy.rail.versionsHeading}>
      <PanelHeader title={copy.rail.versionsHeading} level={2} />
      <PanelBody className={styles["body"]}>
        {part === null ? (
          <EmptyState
            icon="tag"
            density="inline"
            title={copy.rail.versionsNoPartTitle}
            body={copy.rail.versionsNoPart}
          />
        ) : log.data === undefined ? (
          <p className={styles["absent"]}>{copy.absent.loading}</p>
        ) : log.data.commits.length === 0 ? (
          <EmptyState
            icon="tag"
            density="inline"
            title={copy.rail.versionsEmptyTitle}
            body={copy.rail.versionsEmpty}
          />
        ) : (
          <ol className={styles["list"]}>
            {log.data.commits.map((commit) => (
              <li key={commit.sha} className={styles["commit"]} data-commit={commit.sha}>
                <div className={styles["line"]}>
                  <Fact source="git.commits[].short" value={commit.short} mono />
                  <Fact
                    source="git.commits[].author_date"
                    value={commit.author_date}
                    className={styles["date"]}
                  >
                    {day(commit.author_date)}
                  </Fact>
                </div>
                <Fact
                  source="git.commits[].subject"
                  value={commit.subject}
                  className={styles["subject"]}
                />
                {commit.tags.length === 0 ? null : (
                  <div className={styles["tags"]}>
                    {commit.tags.map((tag) => (
                      <Chip key={tag} tone="code" data-git-tag={tag}>
                        <Fact source="git.commits[].tags[]" value={tag} />
                      </Chip>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}

        {tags.data === undefined || tags.data.tags.length === 0 ? null : (
          <details className={styles["allTags"]}>
            <summary className={styles["summary"]}>{copy.rail.tagsHeading}</summary>
            <ul className={styles["list"]}>
              {tags.data.tags.map((tag) => (
                <li key={tag.name} className={styles["tagRow"]} data-tag={tag.name}>
                  <Fact source="git.tags[].name" value={tag.name} mono />
                  <Fact source="git.tags[].object" value={tag.object} className={styles["date"]} />
                </li>
              ))}
            </ul>
          </details>
        )}
      </PanelBody>
    </Panel>
  );
}
