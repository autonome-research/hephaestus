// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ParamSliders` — INTERFACE.md §10, generated from `GET /parts/{part}/params`.
//
// Bounds, names, and the starting value come from that projection. The client
// does not invent a parameter and does not clamp: a typed out-of-bounds value
// is sent so `set_params` can reject it (`rejected[]` rendered verbatim). A
// slider commits through `set_params` + a default `build_part` with no
// transient params. Live rebuild is debounced 300 ms on release, not during
// drag.

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { postBuild, postParams } from "../../api/params";
import { keys, useParams } from "../../api/queries";
import { refreshKeys } from "../../api/refresh";
import { uuid7 } from "../../api/idempotency";
import type { ParamRejection, ParamRow, ParamsDocument } from "../../api/types";
import { copy } from "../../copy";
import { useWorkspace } from "../../state/react";
import { EmptyState, Panel, PanelBody, PanelHeader, PanelNote, Slider } from "../../system";
import { Fact } from "../Fact";
import styles from "./ParamSliders.module.css";

/** §10: rebuild is debounced 300 ms on release, not during drag. */
export const PARAM_COMMIT_MS = 300;

export interface ParamSlidersViewProps {
  readonly part: string;
  readonly document: ParamsDocument;
  readonly draft: Readonly<Record<string, number>>;
  readonly rejected: readonly ParamRejection[];
  readonly conflict: boolean;
  readonly committing: boolean;
  readonly onDraft: (name: string, value: number) => void;
  readonly onRelease: (name: string, value: number) => void;
}

function rejectionFor(
  rejected: readonly ParamRejection[],
  name: string,
): ParamRejection | undefined {
  return rejected.find((entry) => entry.name === name);
}

/**
 * Control increment for the HTML range. When the server sent `step: null`,
 * an integer declaration uses 1 (the type's own constraint). A float without
 * a step keeps the number input as the real control; the range uses 0.01 as
 * a thumb increment, never as a bound.
 */
export function controlStep(row: ParamRow): number {
  if (row.step !== null) return row.step;
  const integer =
    Number.isInteger(row.default) && Number.isInteger(row.min) && Number.isInteger(row.max);
  return integer ? 1 : 0.01;
}

export function isIntegerParam(row: ParamRow): boolean {
  return Number.isInteger(row.default);
}

/**
 * Keys to refetch after a slider write.
 *
 * A rebuild is the same mutation surface as an agent turn: Results / Checks /
 * DFM / properties go stale with the mesh. A conflict rebuilt nothing, so only
 * the params projection is reread.
 */
export function keysAfterParamCommit(
  part: string,
  rebuilt: boolean,
): readonly (readonly unknown[])[] {
  return rebuilt ? refreshKeys(part) : [keys.params(part)];
}

function rejectionText(entry: ParamRejection): string {
  const parts = [entry.reason];
  if (entry.value !== undefined) parts.push(String(entry.value));
  if (entry.min !== undefined) parts.push(String(entry.min));
  if (entry.max !== undefined) parts.push(String(entry.max));
  if (entry.detail !== undefined) parts.push(entry.detail);
  return parts.join(" ");
}

/** The panel's rendering half: a pure function of one params document. */
export function ParamSlidersView(props: ParamSlidersViewProps): React.JSX.Element {
  const { document, draft, rejected, conflict, committing, onDraft, onRelease } = props;
  return (
    <Panel label={copy.params.heading} data-panel="params">
      <PanelHeader title={copy.params.heading} level={3} />
      <PanelBody>
        {document.params.length === 0 ? (
          <EmptyState icon="file" title={copy.params.emptyTitle} body={copy.params.empty} />
        ) : (
          <ul className={styles["list"]}>
            {document.params.map((row) => {
              const value = draft[row.name] ?? row.value;
              const refusal = rejectionFor(rejected, row.name);
              return (
                <li key={row.name} className={styles["row"]} data-param={row.name}>
                  <Slider
                    label={row.name}
                    min={row.min}
                    max={row.max}
                    step={controlStep(row)}
                    precision={isIntegerParam(row) ? 0 : 2}
                    value={value}
                    clamp={false}
                    disabled={committing}
                    invalid={refusal === undefined ? undefined : rejectionText(refusal)}
                    data-param-slider={row.name}
                    onChange={(next) => {
                      onDraft(row.name, next);
                    }}
                    onRelease={(next) => {
                      onRelease(row.name, next);
                    }}
                  />
                  <Fact source="params[].value" value={row.value} className={styles["server"]} />
                  <Fact source="params[].min" value={row.min} className={styles["server"]} />
                  <Fact source="params[].max" value={row.max} className={styles["server"]} />
                  <Fact source="params[].default" value={row.default} className={styles["server"]} />
                  <Fact source="params[].step" value={row.step} className={styles["server"]} />
                </li>
              );
            })}
          </ul>
        )}
        <Fact source="params.state_hash" value={document.state_hash} className={styles["hash"]} />
        {conflict ? <PanelNote>{copy.params.conflict}</PanelNote> : null}
        {committing ? <PanelNote>{copy.params.committing}</PanelNote> : null}
      </PanelBody>
    </Panel>
  );
}

export function ParamSliders(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const query = useParams(part);
  const client = useQueryClient();
  const [local, setLocal] = useState<{
    hash: string;
    values: Record<string, number>;
    rejected: readonly ParamRejection[];
    conflict: boolean;
  }>({ hash: "", values: {}, rejected: [], conflict: false });
  const [committing, setCommitting] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<{ name: string; value: number } | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);

  const hash = query.data?.state_hash ?? "";
  const draft = local.hash === hash ? local.values : {};
  const rejected = local.hash === hash ? local.rejected : [];
  const conflict = local.hash === hash ? local.conflict : false;

  if (part === null) {
    return <EmptyState icon="file" title={copy.params.noPartTitle} body={copy.params.noPart} />;
  }
  if (query.data === undefined) {
    return <PanelNote>{copy.params.loading}</PanelNote>;
  }

  const commit = (name: string, value: number): void => {
    const document = query.data;
    if (document === undefined) return;
    setCommitting(true);
    setLocal((current) => ({
      hash: document.state_hash,
      values: current.hash === document.state_hash ? current.values : {},
      rejected: [],
      conflict: false,
    }));
    void postParams(
      part,
      { values: { [name]: value }, expected_state_hash: document.state_hash },
      uuid7(),
    )
      .then((result) => {
        if (result.conflict !== undefined) {
          setLocal((current) => ({
            hash: document.state_hash,
            values: current.hash === document.state_hash ? current.values : {},
            rejected: [],
            conflict: true,
          }));
          for (const queryKey of keysAfterParamCommit(part, false)) {
            void client.invalidateQueries({ queryKey });
          }
          return;
        }
        if (result.rejected.length > 0) {
          setLocal((current) => ({
            hash: document.state_hash,
            values: current.hash === document.state_hash ? current.values : {},
            rejected: result.rejected,
            conflict: false,
          }));
          return;
        }
        return postBuild(part, uuid7()).then(() => {
          for (const queryKey of keysAfterParamCommit(part, true)) {
            void client.invalidateQueries({ queryKey });
          }
        });
      })
      .finally(() => {
        setCommitting(false);
      });
  };

  const schedule = (name: string, value: number): void => {
    pending.current = { name, value };
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const next = pending.current;
      pending.current = null;
      if (next !== null) commit(next.name, next.value);
    }, PARAM_COMMIT_MS);
  };

  return (
    <ParamSlidersView
      part={part}
      document={query.data}
      draft={draft}
      rejected={rejected}
      conflict={conflict}
      committing={committing}
      onDraft={(name, value) => {
        setLocal((current) => ({
          hash,
          values: { ...(current.hash === hash ? current.values : {}), [name]: value },
          rejected: current.hash === hash ? current.rejected : [],
          conflict: current.hash === hash ? current.conflict : false,
        }));
      }}
      onRelease={(name, value) => {
        setLocal((current) => ({
          hash,
          values: { ...(current.hash === hash ? current.values : {}), [name]: value },
          rejected: current.hash === hash ? current.rejected : [],
          conflict: current.hash === hash ? current.conflict : false,
        }));
        schedule(name, value);
      }}
    />
  );
}
