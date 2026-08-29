// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The section plate (INTERFACE.md §5.3) — "a fitted image layer in the Stage —
// with the plate's `source_artifact_ref` shown in the header".
//
// This is the **evidentiary** half of §5.3. The pixels are the server's, fetched
// as the exact stored bytes of a `render`-kind artifact (§2.6), so what a reader
// sees is byte-identical to what G4.7's golden comparison reads. The browser's
// clipping preview underneath is the working surface and says so.
//
// §5.3's consequence, stated so it is not discovered later: "for gated views,
// `web/` is a viewer of server pixels." This component is that sentence.
//
// The `source_artifact_ref` shown is the **plate's own** — the ref the server
// resolved the render against, which §12.1 and §4.4 make the answer, not the pin
// the request happened to carry. Those are the same value in the ordinary case
// and differ in exactly the cases that matter.

import { useEffect, useMemo } from "react";
import { WorkspaceError } from "../../../api/client";
import { copy } from "../../../copy";
import { useWorkspace } from "../../../state/react";
import { CapabilityRefusal, useSectionPlate } from "../../../viewport/useSectionPlate";
import { Badge, Chip, EmptyState } from "../../../system";
import { Fact } from "../../Fact";
import styles from "./SectionPlate.module.css";

export interface SectionPlateProps {
  /** The canonical `[+-]AXIS@OFFSET` the plate was asked for. */
  readonly plane: string;
}

export function SectionPlate({ plane }: SectionPlateProps): React.JSX.Element | null {
  const part = useWorkspace((s) => s.part);
  const artifactRef = useWorkspace((s) => s.artifact_ref);
  const view = useWorkspace((s) => s.view);

  const request =
    part === null || artifactRef === null
      ? null
      : { part, artifact_ref: artifactRef, view, section_plane: plane };
  const plate = useSectionPlate(request, true);

  const bytes = plate.data?.bytes;
  const mime = plate.data?.mime_type;
  // The object URL is minted here and revoked here: it is a browser resource
  // with this component's lifetime, and the query cache outlives it.
  const url = useMemo(
    () =>
      bytes === undefined
        ? null
        : URL.createObjectURL(new Blob([bytes], { type: mime ?? "image/png" })),
    [bytes, mime],
  );
  useEffect(() => {
    if (url === null) return;
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [url]);

  if (request === null) return null;

  if (plate.isPending) {
    return (
      <div className={styles["plate"]} data-section-plate="pending">
        <div className={styles["centre"]}>
          <EmptyState
            icon="plane"
            title={copy.viewport.section.renderingTitle}
            body={copy.viewport.section.rendering}
          />
        </div>
      </div>
    );
  }

  if (plate.isError || url === null || plate.data === undefined) {
    const reason =
      plate.error instanceof WorkspaceError
        ? plate.error.reason
        : plate.error instanceof CapabilityRefusal
          ? plate.error.code
          : "section_render_absent";
    return (
      <div className={styles["plate"]} data-section-plate="refused">
        <div className={styles["centre"]}>
          <EmptyState
            icon="alert"
            title={copy.viewport.section.plateRefusedTitle}
            body={
              <>
                <p>{copy.viewport.section.plateRefused}</p>
                <p>
                  <Chip tone="code" data-refusal-reason={reason}>
                    {reason}
                  </Chip>
                </p>
              </>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div
      className={styles["plate"]}
      data-section-plate="rendered"
      data-plate-ref={plate.data.render_artifact_ref}
    >
      <header className={styles["header"]}>
        <Badge status="info">{copy.viewport.section.plateLabel}</Badge>
        <span className={styles["from"]}>
          {copy.viewport.section.plateFrom}{" "}
          <Fact
            source="inspect.source_artifact_ref"
            value={plate.data.source_artifact_ref}
            mono
            className={styles["ref"]}
          />
        </span>
      </header>
      <img className={styles["image"]} src={url} alt={copy.viewport.section.plateLabel} />
    </div>
  );
}
