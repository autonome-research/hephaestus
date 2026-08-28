// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The script viewer's cursor discipline (tool_schema.md §read_part, INTERFACE.md
// §2.6), kept out of the component so it can be read as one rule.
//
// `tool_schema.md`, §read_part, verbatim on the point that matters:
//
//   "Any truncated response returns snapshot-bound absolute
//   `next_offset_bytes`; **all continuation uses `read_artifact(snapshot_ref,
//   offset_bytes=…)`, never another mutable source read.**"
//
// The web spelling of `read_artifact(snapshot_ref, offset_bytes)` is
// `GET /artifacts/{snapshot_ref}/text?offset_bytes=` — §2.6's shared UTF-8
// pager, the *same* `core.artifacts.page_text` behind a different principal
// check. So:
//
// * page 0 is `GET /parts/{part}/script`, which registers the snapshot and
//   hands back `snapshot_ref`;
// * every later page is the artifact pager against **that snapshot ref**, never
//   `/parts/{part}/script` again. Re-reading the mutable source mid-page would
//   splice two different files together and call the result one script.
// * `offset_bytes` is always a value the server gave us. §2.6: "an offset that
//   is neither `0`, nor `total_bytes`, nor an exact code-point boundary returns
//   `invalid_utf8_offset` **without normalizing it**" — so a cursor this client
//   invented would be refused, correctly, and there is no reason to invent one.
// * a single oversized line is supported by the pager and surfaced as a
//   user-visible fact rather than a silent cut.
//
// REALITY NOTE (recorded rather than assumed): the shipped `_read_part`
// (`agent_bridge/dispatch.py`) returns the whole script with `truncated: false`
// and no `next_offset_bytes` — it does not implement `offset_line`/`limit_lines`
// paging today. The continuation path below is therefore dormant against the
// current engine and correct the day it is not. It is written from the contract,
// not from the current implementation, because the contract is what the route
// promises to serve verbatim.

import { useCallback, useEffect, useState } from "react";
import { apiJson, refSegment } from "../../api/client";
import type { ArtifactTextPage, ScriptDocument } from "../../api/types";

export interface ScriptPages {
  /** Everything paged in so far, concatenated in cursor order. */
  readonly text: string;
  /** The snapshot these bytes came from — one snapshot, never a mix. */
  readonly snapshotRef: string | null;
  readonly contentHash: string | null;
  readonly lineCount: number | null;
  /** Bytes loaded and, once known, the snapshot's total. */
  readonly loadedBytes: number;
  readonly totalBytes: number | null;
  /** `true` while a `next_offset_bytes` is outstanding. */
  readonly more: boolean;
  readonly loading: boolean;
  readonly oversizedLine: boolean;
  readonly error: Error | null;
  /** Fetch the next page from the server-supplied cursor. */
  readonly loadMore: () => void;
}

const NOTHING: Omit<ScriptPages, "loadMore"> = {
  text: "",
  snapshotRef: null,
  contentHash: null,
  lineCount: null,
  loadedBytes: 0,
  totalBytes: null,
  more: false,
  loading: false,
  oversizedLine: false,
  error: null,
};

interface State extends Omit<ScriptPages, "loadMore"> {
  readonly cursor: number | null;
}

const INITIAL: State = { ...NOTHING, cursor: null };

export function useScriptPages(
  part: string | null,
  script: ScriptDocument | undefined,
): ScriptPages {
  const [state, setState] = useState<State>(INITIAL);

  useEffect(() => {
    if (part === null || script === undefined) {
      setState(INITIAL);
      return;
    }
    // A new snapshot resets the accumulator outright. Appending a page of the
    // new snapshot onto bytes of the old one is the exact splice the
    // "never another mutable source read" rule exists to prevent.
    setState({
      ...NOTHING,
      text: script.script,
      snapshotRef: script.snapshot_ref,
      contentHash: script.content_hash,
      lineCount: script.line_count,
      loadedBytes: new TextEncoder().encode(script.script).length,
      totalBytes: script.truncated ? null : new TextEncoder().encode(script.script).length,
      more: script.truncated,
      oversizedLine: script.oversized_line === true,
      cursor: script.next_offset_bytes ?? null,
    });
  }, [part, script]);

  const { snapshotRef, cursor, loading } = state;

  const loadMore = useCallback(() => {
    if (loading || cursor === null || snapshotRef === null) return;
    const ref = snapshotRef;
    setState((prev) => (prev.snapshotRef === ref ? { ...prev, loading: true } : prev));
    void (async () => {
      try {
        const page = await apiJson<ArtifactTextPage>(
          `/artifacts/${refSegment(ref)}/text?offset_bytes=${cursor}`,
        );
        setState((prev) =>
          // Guard against a snapshot swap that landed while this was in flight:
          // the page belongs to `ref`, not to whatever is current now.
          prev.snapshotRef !== ref
            ? prev
            : {
                ...prev,
                text: prev.text + page.content,
                loadedBytes: page.next_offset_bytes ?? page.total_bytes,
                totalBytes: page.total_bytes,
                more: page.truncated,
                cursor: page.next_offset_bytes ?? null,
                loading: false,
                error: null,
              },
        );
      } catch (error) {
        setState((prev) =>
          prev.snapshotRef !== ref
            ? prev
            : { ...prev, loading: false, error: error as Error, more: false },
        );
      }
    })();
  }, [snapshotRef, cursor, loading]);

  return { ...state, loadMore };
}
