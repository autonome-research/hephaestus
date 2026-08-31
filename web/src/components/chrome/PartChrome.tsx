// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Part chrome — Export and BOM next to the on-screen pin (issue #12).
//
// §22.7 put export in an inspector tab and said the header gains nothing.
// Issue #12 amended that: two simple controls sit in chrome, bound to the
// thing on screen, not only a buried tab. They stay two distinct, visible,
// clickable buttons — icon-only so the pin dominates the 44px bar. There is
// no overflow, menu, or extra click in front of them.
//
// Both buttons still send the workspace pin; they do not resolve "current"
// at click time. Export opens a compact format+run dialog. BOM opens the
// sourcing inspector (declared `process` / stock / material spec only — no
// vendor catalog). The inspector Export tab stays for history, drawings, and
// documents. There is no third egress surface.

import { useState } from "react";
import { copy } from "../../copy";
import { workspaceStore } from "../../state/react";
import { Button, Popover } from "../../system";
import { ExportChrome } from "./ExportChrome";
import { useExportActions } from "../inspector/ExportPanel";
import { SourcingPanel } from "../inspector/SourcingPanel";
import styles from "./PartChrome.module.css";

type ChromeDialog = "export" | "sourcing" | null;

export function PartChrome(): React.JSX.Element {
  const [open, setOpen] = useState<ChromeDialog>(null);
  const { part, pinned, pinMode, onExport } = useExportActions();

  const close = (): void => {
    setOpen(null);
  };
  const openInspectorExport = (): void => {
    workspaceStore.update({ inspector_tab: "export" });
    close();
  };

  return (
    <div className={styles["chrome"]} data-part-chrome="">
      <Button
        variant="quiet"
        icon="download"
        iconLabel={copy.chrome.exportTitle}
        data-chrome-export=""
        title={copy.chrome.exportTitle}
        onClick={() => {
          setOpen("export");
        }}
      />
      <Button
        variant="quiet"
        icon="file"
        iconLabel={copy.chrome.bomTitle}
        data-chrome-bom=""
        title={copy.chrome.bomTitle}
        onClick={() => {
          setOpen("sourcing");
        }}
      />

      <Popover
        open={open === "export"}
        onClose={close}
        label={copy.chrome.export}
        variant="dialog"
        data-chrome-dialog="export"
      >
        <ExportChrome
          part={part}
          pinned={pinned}
          pinMode={pinMode}
          onExport={onExport}
          onOpenInspector={openInspectorExport}
        />
      </Popover>

      <Popover
        open={open === "sourcing"}
        onClose={close}
        label={copy.sourcing.heading}
        variant="dialog"
        data-chrome-dialog="sourcing"
      >
        <SourcingPanel />
      </Popover>
    </div>
  );
}
