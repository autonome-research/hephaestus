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
//
// AND THE DEFECT THE ONE-LINE FIX LEFT STANDING (operator review, 2026-09-01).
// One line each is still 37 lines: on the live fixture the whole section was
// `.heph/blobs/sha256/…`, `.heph/state.db`, `.heph/serve.token`, `.heph/agent/…`
// — the workspace's own store, reported as untracked, pushing the part tree and
// the providers sign-in below the fold of a 280px rail. §13.1 says report, not
// enumerate-at-equal-weight: the `.heph/` rows are now ONE row carrying their
// count, expandable to exactly the same table with exactly the same `<Fact>`
// attribution. Nothing is dropped, and no path is shortened.
//
// GIT IDENTITY LIVES HERE NOW, for the same §13.1 reason the dirty rows do:
// "the header shows the artifact axis; the rail shows the git axis; the UI never
// blurs them." `branch` and `HEAD` were in the 44px header bar, where the head
// was also being printed at full 40-glyph length by a `formatRef` width bug.
// They are identity — *which repository this is* — so they sit above the working
// tree, and this panel still reports nothing about whether a build is current.

import { useState } from "react";
import { useGitStatus } from "../../api/queries";
import { WorkspaceError } from "../../api/client";
import { copy } from "../../copy";
import type { GitDirtyEntry } from "../../api/types";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  formatOid,
} from "../../system";
import { Fact } from "../Fact";
import styles from "./GitDirty.module.css";

/** git porcelain v2 `# branch.head (detached)` — not a branch Fact. */
export const DETACHED_BRANCH = "(detached)";

/** A real git object id. The word `HEAD` is a ref name, not an oid. */
const GIT_OID = /^[0-9a-f]{7,64}$/i;

/**
 * The branch Fact the rail may print. `(detached)` is porcelain, not a
 * name — omit it rather than rendering it as `git.branch`.
 */
export function railBranch(branch: string | null | undefined): string | null {
  if (branch === null || branch === undefined || branch === "" || branch === DETACHED_BRANCH) {
    return null;
  }
  return branch;
}

/**
 * The head Fact the rail may print. Only a real oid is abbreviated
 * (`formatOid`). The label `HEAD` without a sha is not a fact.
 */
export function railHead(head: string | null | undefined): string | null {
  if (head === null || head === undefined || head === "" || head === "HEAD") return null;
  return GIT_OID.test(head) ? head : null;
}

/** The prefix under which the workspace writes its own store (§2.1, §13.1). */
const GENERATED_PREFIX = ".heph/";

/** True for a path the workspace itself produced, not part source. */
export function isGeneratedPath(path: string): boolean {
  return path.startsWith(GENERATED_PREFIX);
}

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
  /** §13.1's git identity, on the git axis: which repository this is. */
  readonly branch: string | null;
  readonly head: string | null;
}

const EMPTY_INDEX: DirtyIndex = {
  byPart: new Map(),
  others: [],
  entries: [],
  clean: null,
  absence: null,
  branch: null,
  head: null,
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
  return {
    byPart,
    others,
    entries: data.dirty,
    clean: data.clean,
    absence: null,
    branch: railBranch(data.branch),
    head: railHead(data.head),
  };
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
  const [generatedOpen, setGeneratedOpen] = useState(false);
  const generated = index.others.filter((entry) => isGeneratedPath(entry.path));
  const authored = index.others.filter((entry) => !isGeneratedPath(entry.path));

  return (
    <Panel className={styles["panel"]} label={copy.rail.gitHeading}>
      <PanelHeader
        title={copy.rail.gitHeading}
        level={2}
        actions={
          index.branch === null && index.head === null ? undefined : (
            <span className={styles["identity"]}>
              {index.branch === null ? null : (
                <span title={copy.rail.branch} className={styles["branchWrap"]}>
                  <Fact source="git.branch" value={index.branch} className={styles["branch"]} />
                </span>
              )}
              {index.head === null ? null : (
                // The full oid stays on `data-value`; the prefix is what a git
                // reader recognises and what fits beside a heading.
                <span title={`${copy.rail.head} ${index.head}`}>
                  <Fact source="git.head" value={index.head} className={styles["head"]}>
                    {formatOid(index.head)}
                  </Fact>
                </span>
              )}
            </span>
          )
        }
      />
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
            {authored.length === 0 ? null : (
              <>
                <p className={styles["subheading"]}>{copy.rail.dirtyOutsideParts}</p>
                <DirtyRows entries={authored} />
              </>
            )}
            {generated.length === 0 ? null : (
              // ONE row for the workspace's own store, with its count and one
              // click to the same table. §13.1 reports the dirty tree; it does
              // not owe every `.heph/blobs/sha256/…` object equal weight with
              // `parts/gusset.py` in a 280px rail.
              <>
                <Button
                  variant="quiet"
                  icon={generatedOpen ? "chevron-down" : "chevron-right"}
                  title={copy.rail.generatedWhy}
                  expanded={generatedOpen}
                  className={styles["group"]}
                  onClick={() => {
                    setGeneratedOpen(!generatedOpen);
                  }}
                  data-dirty-group="generated"
                  data-dirty-group-count={generated.length}
                >
                  {copy.rail.generated(generated.length)}
                </Button>
                {generatedOpen ? <DirtyRows entries={generated} /> : null}
              </>
            )}
          </>
        )}
      </PanelBody>
    </Panel>
  );
}

/**
 * The dirty rows, as §4.7's three-track table.
 *
 * The full path stays on `<Fact>` (`data-value`); the wrapper is presentation —
 * one line, ellipsis, the complete path on hover. Shortening the *text* through
 * `formatRef` would hide bytes the server sent.
 */
function DirtyRows({ entries }: { readonly entries: readonly GitDirtyEntry[] }): React.JSX.Element {
  return (
    <DataTable
      as="div"
      rows={entries.map((entry) => ({
        key: entry.path,
        label: <DirtyMarker entry={entry} />,
        value: (
          <span className={styles["path"]} title={entry.path}>
            <Fact source="git.dirty[].path" value={entry.path} />
          </span>
        ),
        attrs: { "data-dirty": dirtySide(entry) },
      }))}
    />
  );
}

export function GitDirtyPanel(): React.JSX.Element {
  return <GitDirtyView index={useDirtyIndex()} />;
}
