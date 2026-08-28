// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §4.1's HEADER: `project · branch · HEAD | ARTIFACT PIN | build state | token`.
//
// The two axes §13.1 insists must never blur are split across the shell on
// purpose: **the header shows the artifact axis** (pin, build state) and **the
// rail shows the git axis** (dirty markers, versions). `branch` and `HEAD` sit
// here as identity, not as state — they say *which repository this is*, and
// nothing in the header reports whether the tree is dirty.

import { useBuild, useGitStatus, useProject } from "../api/queries";
import { copy } from "../copy";
import { useWorkspace } from "../state/react";
import { ArtifactPin } from "./ArtifactPin";
import { BuildStateChip } from "./BuildStateChip";
import { Fact } from "./Fact";
import styles from "./Header.module.css";

export function Header(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const project = useProject();
  const git = useGitStatus();
  const build = useBuild(part);

  const head = git.data?.head ?? null;
  const branch = git.data?.branch ?? null;

  return (
    <header className={styles["header"]}>
      <div className={styles["identity"]}>
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
          <Fact source="git.head" value={head} mono className={styles["head"]}>
            {head.slice(0, 8)}
          </Fact>
        )}
      </div>

      <ArtifactPin currentRef={build.data?.artifact_ref ?? null} />

      <div className={styles["right"]}>
        <BuildStateChip build={build.data} />
        <span className={styles["token"]} title={copy.header.token}>
          <span aria-hidden="true">●</span> {copy.header.token}
        </span>
      </div>
    </header>
  );
}
