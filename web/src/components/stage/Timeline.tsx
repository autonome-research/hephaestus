// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Statement Timeline — a scrubber over the positions `GET /parts/{part}/build`
// actually names (INTERFACE.md §0.1, architecture.md §3.1).
//
// "Drag to rewind" is `hold(error.last_good_artifact_ref)`. The viewport is
// bound to the pin, so holding the last-good checkpoint is last-good inspect
// (`artifact_ref` and `last_good` are mutually exclusive; the pin path sends
// the ref). Dragging back follows current. Nothing here invents a per-statement
// event list: the worker's `checkpoints` array is not on the HTTP projection.

import { copy } from "../../copy";
import { useBuild } from "../../api/queries";
import type { BuildDocument } from "../../api/types";
import { workspaceStore, useWorkspace } from "../../state/react";
import { Chip, EmptyState, formatRef, Panel, PanelBody, PanelHeader, Slider } from "../../system";
import roles from "../../system/type.module.css";
import { Fact } from "../Fact";
import { actionForIndex, indexForPin, marksFromBuild, type TimelineKind } from "./timelineMarks";
import styles from "./Timeline.module.css";

export interface TimelineViewProps {
  readonly build: BuildDocument;
  readonly pin: string | null;
  readonly onRewind: (ref: string) => void;
  readonly onFollowCurrent: (currentRef: string | null) => void;
}

const KIND_COPY: Readonly<Record<TimelineKind, string>> = {
  last_good: copy.timeline.lastGood,
  failed: copy.timeline.failed,
  current: copy.timeline.current,
};

/** The panel's rendering half: a pure function of one build document and the pin. */
export function TimelineView(props: TimelineViewProps): React.JSX.Element {
  const { build, pin, onRewind, onFollowCurrent } = props;
  const marks = marksFromBuild(build);
  const index = indexForPin(marks, pin);
  const selected = marks[index] ?? null;
  const error = build.error;
  const lastGoodRef = error?.last_good_artifact_ref ?? null;
  const canScrub = marks.length > 1 && lastGoodRef !== null;

  return (
    <Panel label={copy.timeline.heading} data-panel="timeline">
      <PanelHeader
        title={copy.timeline.heading}
        level={3}
        actions={
          selected === null ? undefined : (
            <Chip data-timeline-position={selected.kind}>{KIND_COPY[selected.kind]}</Chip>
          )
        }
      />
      <PanelBody>
        {build.status === "not_built" ? (
          <EmptyState icon="file" title={copy.timeline.notBuiltTitle} body={copy.timeline.notBuilt} />
        ) : build.status === "ok" ? (
          <EmptyState icon="cube" title={copy.timeline.okTitle} body={copy.timeline.ok} />
        ) : lastGoodRef === null ? (
          <EmptyState
            icon="alert"
            title={copy.timeline.noCheckpointTitle}
            body={copy.timeline.noCheckpoint}
          />
        ) : (
          <div className={styles["scrub"]}>
            <Slider
              label={copy.timeline.scrub}
              min={0}
              max={marks.length - 1}
              step={1}
              precision={0}
              value={index}
              disabled={!canScrub}
              data-timeline-scrub=""
              onChange={(next) => {
                const nextAction = actionForIndex(marks, next, build.artifact_ref ?? null);
                if (nextAction === null) return;
                if (nextAction.action === "hold") onRewind(nextAction.ref);
                else onFollowCurrent(nextAction.currentRef);
              }}
            />
            <ol className={styles["marks"]}>
              {marks.map((mark) => (
                <li
                  key={mark.kind}
                  className={styles["mark"]}
                  data-timeline-mark={mark.kind}
                  data-selected={mark.kind === selected?.kind ? "true" : "false"}
                >
                  <span className={styles["markLabel"]}>{KIND_COPY[mark.kind]}</span>
                  {mark.kind === "last_good" && mark.artifact_ref !== null ? (
                    <Fact source="build.error.last_good_artifact_ref" value={mark.artifact_ref} mono>
                      {formatRef(mark.artifact_ref)}
                    </Fact>
                  ) : mark.artifact_ref !== null ? (
                    <Fact source="build.artifact_ref" value={mark.artifact_ref} mono>
                      {formatRef(mark.artifact_ref)}
                    </Fact>
                  ) : null}
                </li>
              ))}
            </ol>
          </div>
        )}

        {error === undefined ? null : (
          <dl className={styles["facts"]}>
            {error.built_through === null ? null : (
              <>
                <div className={styles["fact"]}>
                  <dt className={roles["label"]}>{copy.timeline.lastGood}</dt>
                  <dd className={roles["data"]}>
                    <Fact source="build.error.built_through.line" value={error.built_through.line} />
                  </dd>
                </div>
                <div className={styles["fact"]} data-timeline-statement="">
                  <dt className={roles["label"]} />
                  <dd className={roles["data"]}>
                    <Fact
                      source="build.error.built_through.statement"
                      value={error.built_through.statement}
                      mono
                    />
                  </dd>
                </div>
              </>
            )}
            <div className={styles["fact"]}>
              <dt className={roles["label"]}>{copy.timeline.failed}</dt>
              <dd className={roles["data"]}>
                <Fact source="build.error.line" value={error.line} />
              </dd>
            </div>
            {error.last_good === null ? null : (
              <div className={styles["fact"]}>
                <dt className={roles["label"]}>{copy.timeline.lastGood}</dt>
                <dd className={roles["data"]}>
                  <Fact source="build.error.last_good.solids" value={error.last_good.solids} />
                </dd>
              </div>
            )}
            {lastGoodRef === null ? null : (
              <div className={styles["fact"]}>
                <dt className={roles["label"]}>{copy.timeline.rewind}</dt>
                <dd className={roles["data"]}>
                  <Fact source="build.error.last_good_artifact_ref" value={lastGoodRef} mono>
                    {formatRef(lastGoodRef)}
                  </Fact>
                </dd>
              </div>
            )}
          </dl>
        )}
      </PanelBody>
    </Panel>
  );
}

export function Timeline(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const pin = useWorkspace((s) => s.artifact_ref);
  const build = useBuild(part);

  if (part === null) {
    return <EmptyState icon="file" title={copy.timeline.noPartTitle} body={copy.timeline.noPart} />;
  }
  if (build.data === undefined) {
    return <EmptyState icon="cube" title={copy.timeline.heading} body={copy.script.loading} />;
  }
  return (
    <TimelineView
      build={build.data}
      pin={pin}
      onRewind={(ref) => {
        workspaceStore.hold(ref);
      }}
      onFollowCurrent={(currentRef) => {
        workspaceStore.followCurrent(currentRef);
      }}
    />
  );
}
