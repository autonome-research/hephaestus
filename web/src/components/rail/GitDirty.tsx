// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `GitDirty` (INTERFACE.md §13.1) — the git axis of the rail.
//
// §13.1, quoted because every line of it is a constraint on this file:
//
//   "`GET /git/status` drives inline markers on the part tree and a dot on the
//   Script tab. Dirtiness is a `git status` fact about `parts/*.py` in the
//   working tree. `.heph/journal/` is gitignored and contributes nothing, so
//   **dirtiness is entirely disjoint from artifact and publication state** — a
//   part can be clean and unbuilt, or dirty and current. The header shows the
//   artifact axis; the rail shows the git axis; the UI never blurs them."
//
// So: this module knows nothing about builds, refs, or `current`, and the part
// tree's dirty marker is fed from here rather than from anything the build
// projection says. The `part` field is the server's — `git_projection.py` fills
// it only for a path under `parts/` ending in `.py`, and a changed
// `globals.py` is dirty with no part, which the panel shows as its own group
// rather than silently dropping.
//
// §4.7's TreeRow clause: "The §13.1 dirty marker is a `Badge` variant carrying
// an `aria-label`, **never a bare coloured dot**." The shipped marker was a `●`
// whose only differentiator between staged, unstaged and untracked was its hue.
// It is now a `Badge status="dirty"` with the side of the index in words.
//
// §4.7's SECOND EmptyState rule lives here too: "a shared cause is detected
// once". `WORKING TREE` and `VERSIONS` shipped the *identical* sentence in
// adjacent rail sections above ~1000px of void. `railGitAbsence` is that shared
// cause, this panel prints it once for both sections, and `VersionList` renders
// nothing while it holds.
//
// THE WRAPPING DEFECT THE G4 SCREENSHOTS STILL SHOW. Untracked rows under
// `CHANGED PATHS OUTSIDE PARTS/` are often `.heph/blobs/sha256/<dir>/<64 hex>`.
// Those are real git facts — §13.1 reports a dirty tree, never hides it — but
// `.code { word-break: break-all }` plus a two-column body grid (the empty unit
// cell wrapping onto the next row) turned each path into a multi-line ribbon
// that ate the rail. The path stays on one line; `data-value` still carries
// every byte the server sent.

import { useGitStatus } from "../../api/queries";
import { WorkspaceError } from "../../api/client";
import { copy } from "../../copy";
import type { GitDirtyEntry } from "../../api/types";
import { Badge, DataTable, EmptyState, Panel, PanelBody, PanelHeader } from "../../system";
import { Fact } from "../Fact";
import styles from "./GitDirty.module.css";

/** Which side of the index a change sits on — the server's two porcelain codes. */
export function dirtySide(entry: GitDirtyEntry): keyof typeof copy.gitStatus {
  if (entry.index === "?" || entry.worktree === "?") return "untracked";
  const staged = entry.index !== "." && entry.index !== "";
  const unstaged = entry.worktree !== "." && entry.worktree !== "";
  if (staged && unstaged) return "both";
  return staged ? "index" : "worktree";
}

export interface DirtyIndex {
  /** part name → its dirty row, for the tree's inline markers. */
  readonly byPart: ReadonlyMap<string, GitDirtyEntry>;
  /** Changed paths the server did not attribute to a part. */
  readonly others: readonly GitDirtyEntry[];
  readonly entries: readonly GitDirtyEntry[];
  readonly clean: boolean | null;
  /** A named absence: not a git work tree, or git is not available. */
  readonly absence: string | null;
}

const EMPTY_INDEX: DirtyIndex = {
  byPart: new Map(),
  others: [],
  entries: [],
  clean: null,
  absence: null,
};

/** The one read of `GET /git/status`, shared by the tree and this panel. */
export function useDirtyIndex(): DirtyIndex {
  const status = useGitStatus();
  if (status.error instanceof WorkspaceError) {
    return {
      ...EMPTY_INDEX,
      absence:
        status.error.reason === "git_unavailable" ? copy.absent.gitUnavailable : copy.absent.noGit,
    };
  }
  const data = status.data;
  if (data === undefined) return EMPTY_INDEX;
  const byPart = new Map<string, GitDirtyEntry>();
  const others: GitDirtyEntry[] = [];
  for (const entry of data.dirty) {
    const part = entry.part ?? null;
    if (part === null) others.push(entry);
    else byPart.set(part, entry);
  }
  return { byPart, others, entries: data.dirty, clean: data.clean, absence: null };
}

/**
 * The cause `WORKING TREE` and `VERSIONS` share (§4.7's EmptyState rule 2).
 *
 * Non-null means both rail sections are empty **for the same reason**, so the
 * sentence is printed once, by this panel, and `VersionList` stands down.
 */
export function railGitAbsence(index: DirtyIndex): string | null {
  return index.absence;
}

/** The inline marker §13.1 puts on a part tree row and on the Script tab. */
export function DirtyMarker({ entry }: { readonly entry: GitDirtyEntry }): React.JSX.Element {
  const side = dirtySide(entry);
  const label = `${copy.rail.dirtyMarkerLabel} (${copy.gitStatus[side]})`;
  return (
    <Badge status="dirty" title={label} className={styles["marker"]}>
      <span data-dirty={side}>{copy.gitStatus[side]}</span>
    </Badge>
  );
}

/**
 * The panel body, given an already-read index.
 *
 * Split out so a long untracked path can be asserted as a DOM fragment without
 * standing up `GET /git/status`. The fixture that produced the wrapping
 * screenshot had four `.heph/blobs/sha256/…` rows; those paths are real git
 * facts (§13.1 reports, never hides) and the job here is to keep them on one
 * line rather than eating the rail.
 */
export function GitDirtyView({ index }: { readonly index: DirtyIndex }): React.JSX.Element {
  const absence = railGitAbsence(index);

  return (
    <Panel className={styles["panel"]} label={copy.rail.gitHeading}>
      <PanelHeader title={copy.rail.gitHeading} level={2} />
      <PanelBody className={styles["body"]}>
        {absence !== null ? (
          // One EmptyState for BOTH rail sections. §4.7: "a shared cause is
          // detected once", and the heading names both so the reader is not
          // left wondering why the panel below is silent.
          <EmptyState
            icon="tag"
            density="inline"
            title={copy.rail.gitAbsentTitle}
            body={absence}
            data-rail-shared-absence=""
          />
        ) : index.clean === null ? (
          <p className={styles["absent"]}>{copy.absent.loading}</p>
        ) : index.clean ? (
          <p className={styles["clean"]}>
            <Badge status="pass">{copy.rail.cleanTree}</Badge>
          </p>
        ) : (
          <>
            {/* Deliberately NOT a `<Fact>`. `git status` serves no count field,
                and a count this component derived from the array it is about to
                render would be exactly the client-side re-count §1 forbids. It is
                a caption over the list; the rows below carry the attribution. */}
            <p className={styles["count"]}>{copy.rail.dirtyCount(index.entries.length)}</p>
            {index.others.length === 0 ? null : (
              <>
                <p className={styles["subheading"]}>{copy.rail.dirtyOutsideParts}</p>
                <DataTable
                  as="div"
                  rows={index.others.map((entry) => ({
                    key: entry.path,
                    label: <DirtyMarker entry={entry} />,
                    value: (
                      // The full path stays on `<Fact>` (`data-value`). The
                      // wrapper is presentation: one line, ellipsis, the
                      // complete path on hover. Shortening the *text* through
                      // `formatRef` would hide bytes the server sent.
                      <span className={styles["path"]} title={entry.path}>
                        <Fact source="git.dirty[].path" value={entry.path} />
                      </span>
                    ),
                    attrs: { "data-dirty": dirtySide(entry) },
                  }))}
                />
              </>
            )}
          </>
        )}
      </PanelBody>
    </Panel>
  );
}

export function GitDirtyPanel(): React.JSX.Element {
  return <GitDirtyView index={useDirtyIndex()} />;
}
