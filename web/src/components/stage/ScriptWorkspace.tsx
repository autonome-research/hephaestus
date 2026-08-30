// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Script tab contents: Monaco plus PARAMS sliders beside it (INTERFACE.md §10,
// architecture.md §8). The editor is unchanged; this file is the split.

import { useWorkspace } from "../../state/react";
import { ParamSliders } from "./ParamSliders";
import { ScriptEditor } from "./ScriptEditor";
import styles from "./ScriptWorkspace.module.css";

export function ScriptWorkspace(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  if (part === null) return <ScriptEditor />;
  return (
    <div className={styles["split"]} data-stage-panel="script">
      <ScriptEditor />
      <aside className={styles["params"]} aria-label="PARAMS">
        <ParamSliders />
      </aside>
    </div>
  );
}
