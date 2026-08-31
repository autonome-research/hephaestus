// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §4.1's HEADER: `identity → pin → Export/BOM chrome → build state → token`.
//
// The two axes §13.1 insists must never blur are split across the shell on
// purpose: **the header shows the artifact axis** (pin, build state) and **the
// rail shows the git axis** (dirty markers, versions). `branch` and `HEAD` sit
// here as identity, not as state — they say *which repository this is*, and
// nothing in the header reports whether the tree is dirty.
//
// §4.1's 2026-08-28 AMENDMENT, header half. The shipped grid was a symmetric
// three-up centring the pin, so with a short project name roughly 450px of the
// left cell and 350px of the right were dead in a 44px bar. It becomes
// `auto 1fr auto`, LEFT-ALIGNED ON ONE BASELINE, with one dominant element — the
// pin chip, carrying the ref in `.code` — and `ARTIFACT PIN` demoted from a
// printed label to a `title`.
//
// COPY DEFECT FIXED AT THE SAME TIME. `copy.ts`'s `pin.current` and
// `buildState.current` were two different closed vocabularies that both spelled
// "current", rendered in two chip styles ~600px apart on two different axes —
// pin freshness versus build state. The build-state vocabulary now says
// **"up to date"**; the pin vocabulary keeps "current". Two axes, two words.

import type { ReactNode } from "react";
import { useBuild, useGitStatus, useProject } from "../api/queries";
import { copy } from "../copy";
import { useWorkspace } from "../state/react";
import { Chip, formatRef } from "../system";
import { ArtifactPin } from "./ArtifactPin";
import { BuildStateChip } from "./BuildStateChip";
import { PartChrome } from "./chrome/PartChrome";
import { Fact } from "./Fact";
import styles from "./Header.module.css";

export interface HeaderProps {
  /** §4.1(b): the rail toggle, present only while the rail is an overlay. */
  readonly railToggle?: ReactNode | undefined;
}

export function Header({ railToggle }: HeaderProps): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const project = useProject();
  const git = useGitStatus();
  const build = useBuild(part);

  const head = git.data?.head ?? null;
  const branch = git.data?.branch ?? null;

  return (
    <header className={styles["header"]}>
      <div className={styles["identity"]}>
        {railToggle ?? null}
        <span className={styles["mark"]} aria-hidden="true" />
        {project.data === undefined ? (
          <span className={styles["absent"]}>{copy.absent.loading}</span>
        ) : (
          <>
            <Fact source="project.name" value={project.data.name} className={styles["project"]} />
            <span className={styles["dot"]} aria-hidden="true">
              ·
            </span>
            <Fact source="project.units" value={project.data.units} className={styles["meta"]} />
          </>
        )}
        {branch === null ? null : (
          <>
            <span className={styles["dot"]} aria-hidden="true">
              ·
            </span>
            <Fact source="git.branch" value={branch} className={styles["meta"]} />
          </>
        )}
        {head === null ? null : (
          <Fact source="git.head" value={head} className={styles["head"]}>
            {formatRef(head, 8)}
          </Fact>
        )}
      </div>

      <div className={styles["subject"]}>
        <ArtifactPin currentRef={build.data?.artifact_ref ?? null} />
        <PartChrome />
      </div>

      <div className={styles["right"]}>
        <BuildStateChip build={build.data} />
        <Chip title={copy.header.token} data-token-state="present">
          {copy.header.token}
        </Chip>
      </div>
    </header>
  );
}
