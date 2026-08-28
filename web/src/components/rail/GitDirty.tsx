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

import { useGitStatus } from "../../api/queries";
import { WorkspaceError } from "../../api/client";
import { copy } from "../../copy";
import type { GitDirtyEntry } from "../../api/types";
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

/** The inline marker §13.1 puts on a part tree row and on the Script tab. */
export function DirtyMarker({ entry }: { readonly entry: GitDirtyEntry }): React.JSX.Element {
  const side = dirtySide(entry);
  return (
    <span
      className={styles["marker"]}
      data-dirty={side}
      title={`${copy.rail.dirtyMarkerLabel} (${copy.gitStatus[side]})`}
      aria-label={`${copy.rail.dirtyMarkerLabel} (${copy.gitStatus[side]})`}
    >
      ●
    </span>
  );
}

export function GitDirtyPanel(): React.JSX.Element {
  const index = useDirtyIndex();

  if (index.absence !== null) {
    return (
      <section className={styles["panel"]} aria-label={copy.rail.gitHeading}>
        <h2 className={styles["heading"]}>{copy.rail.gitHeading}</h2>
        <p className={styles["absent"]}>{index.absence}</p>
      </section>
    );
  }

  return (
    <section className={styles["panel"]} aria-label={copy.rail.gitHeading}>
      <h2 className={styles["heading"]}>{copy.rail.gitHeading}</h2>
      {index.clean === null ? (
        <p className={styles["absent"]}>{copy.absent.loading}</p>
      ) : index.clean ? (
        <p className={styles["clean"]}>
          <span aria-hidden="true">✓</span> {copy.rail.cleanTree}
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
              <ul className={styles["list"]}>
                {index.others.map((entry) => (
                  <li key={entry.path} className={styles["row"]} data-dirty={dirtySide(entry)}>
                    <DirtyMarker entry={entry} />
                    <Fact source="git.dirty[].path" value={entry.path} mono />
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
