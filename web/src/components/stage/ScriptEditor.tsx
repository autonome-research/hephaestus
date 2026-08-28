// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ScriptEditor` — the Stage's Script tab (mission_plan.md Stage 4: "script
// viewer (Monaco, read-only)").
//
// Read-only is a *deliverable*, not a limitation to apologise for: Stage 4 is
// the read-only workspace, and editing is Stage 5's `PUT /parts/{part}/script`,
// which §9.1 makes "a store mutation, never a file write". The editor is
// therefore constructed with `readOnly: true` and the panel says so in words
// (§4.4's discipline generalised: a limited surface states its limit).
//
// Paging follows `useScriptPages`, which follows `tool_schema.md`'s continuation
// rule — never a second read of the mutable source. The panel shows the byte
// counter and the "load next page" control because §8's rule that "multi-page is
// a user-visible fact, not only a test fact" is the same rule here.
//
// The dirty dot on this tab is §13.1's, driven by `GET /git/status` alone.

import { useEffect, useRef } from "react";
import { useScript } from "../../api/queries";
import { copy } from "../../copy";
import { useWorkspace } from "../../state/react";
import { Fact } from "../Fact";
import { installMonaco } from "./monaco";
import { useScriptPages } from "./useScriptPages";
import styles from "./ScriptEditor.module.css";

export function ScriptEditor(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const script = useScript(part);
  const pages = useScriptPages(part, script.data);
  const host = useRef<HTMLDivElement | null>(null);
  const editor = useRef<ReturnType<
    ReturnType<typeof installMonaco>["editor"]["create"]
  > | null>(null);

  useEffect(() => {
    const element = host.current;
    if (element === null) return;
    const monaco = installMonaco();
    const instance = monaco.editor.create(element, {
      value: "",
      language: "python",
      theme: "hephaestus",
      readOnly: true,
      // A read-only viewer that still shows the caret invites a keystroke that
      // does nothing. The cursor is hidden and the affordance is honest.
      domReadOnly: true,
      renderLineHighlight: "none",
      automaticLayout: true,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      fontFamily: getComputedStyle(document.documentElement).getPropertyValue("--font-mono"),
      fontSize: 12,
      lineNumbers: "on",
      wordWrap: "off",
    });
    editor.current = instance;
    return () => {
      instance.getModel()?.dispose();
      instance.dispose();
      editor.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = editor.current;
    if (instance === null) return;
    const model = instance.getModel();
    if (model !== null && model.getValue() !== pages.text) model.setValue(pages.text);
  }, [pages.text]);

  if (part === null) {
    return <p className={styles["absent"]}>{copy.stage.selectPart}</p>;
  }

  return (
    <div className={styles["panel"]} data-panel="script">
      <div className={styles["bar"]}>
        <span className={styles["readOnly"]} title={copy.script.readOnlyWhy}>
          {copy.script.readOnly}
        </span>
        {pages.lineCount === null ? null : (
          <span className={styles["meta"]}>
            <Fact source="script.line_count" value={pages.lineCount} /> {copy.script.lines}
          </span>
        )}
        {pages.contentHash === null ? null : (
          <span className={styles["meta"]} title={copy.script.contentHash}>
            <Fact source="script.content_hash" value={pages.contentHash} mono>
              {pages.contentHash.slice(-10)}
            </Fact>
          </span>
        )}
        {pages.snapshotRef === null ? null : (
          <span className={styles["meta"]} title={copy.script.snapshot}>
            <Fact source="script.snapshot_ref" value={pages.snapshotRef} mono>
              {pages.snapshotRef.slice(-10)}
            </Fact>
          </span>
        )}
      </div>

      <div className={styles["editor"]} ref={host} data-testid="script-editor" />

      {/* §8: multi-page is a user-visible fact, not only a test fact. */}
      <div className={styles["pager"]} aria-live="polite">
        {script.data === undefined ? (
          <span className={styles["absent"]}>{copy.script.loading}</span>
        ) : pages.more ? (
          <>
            <span className={styles["meta"]}>
              {copy.script.paged(pages.loadedBytes, pages.totalBytes ?? pages.loadedBytes)}
            </span>
            <button
              type="button"
              className={styles["more"]}
              onClick={pages.loadMore}
              disabled={pages.loading}
            >
              {copy.script.more}
            </button>
          </>
        ) : (
          <span className={styles["meta"]}>{copy.script.complete}</span>
        )}
        {pages.oversizedLine ? (
          <span className={styles["warn"]}>{copy.script.oversizedLine}</span>
        ) : null}
        {pages.error === null ? null : (
          <span className={styles["error"]}>{pages.error.message}</span>
        )}
      </div>
    </div>
  );
}
