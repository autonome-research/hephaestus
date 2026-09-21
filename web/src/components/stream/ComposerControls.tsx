// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import type { DfmMode, InteractionMode } from "../../api/sessions";
import { copy } from "../../copy";
import { Button, Popover } from "../../system";
import styles from "./Composer.module.css";

const DFM_OPTIONS: readonly { readonly id: DfmMode; readonly label: string }[] = [
  { id: "off", label: copy.composer.modeling },
  { id: "general", label: copy.composer.dfmGeneral },
  { id: "additive", label: copy.composer.dfmAdditive },
  { id: "sheet_metal", label: copy.composer.dfmSheetMetal },
  { id: "machining", label: copy.composer.dfmMachining },
  { id: "casting", label: copy.composer.dfmCasting },
];

/**
 * The chat's two modes, on one control (2026-09-20).
 *
 * This was a `Plan` TOGGLE — pressed meant plan, unpressed meant the other
 * thing, and the other thing had no name on screen. A pressed-state toggle is
 * the right shape for a flag (grid on, wireframe on); it is the wrong shape
 * for a CHOICE between two named modes, because half the choice is invisible
 * and the operator has to infer that "not Plan" is a mode at all.
 *
 * So the button prints the mode it is IN and switches to the other. `Build` is
 * the word for the server's `modeling`: the chat vocabulary is the operator's,
 * and "modeling" is what the API calls it, not what the person is doing.
 *
 * `data-composer-plan` and `aria-pressed` are unchanged, so every gate that
 * reads plan state by name or by pressed-ness still reads it.
 */
export function PlanControl({
  interactionMode,
  disabled,
  disabledReason,
  onInteractionMode,
}: {
  readonly interactionMode: InteractionMode;
  readonly disabled: boolean;
  readonly disabledReason: string;
  readonly onInteractionMode: (mode: InteractionMode) => void;
}): React.JSX.Element {
  const disablement = disabled ? { disabled: true as const, reason: disabledReason } : {};
  const planning = interactionMode === "plan";
  return (
    <Button
      variant="toggle"
      pressed={planning}
      title={planning ? copy.composer.modeSwitchToBuild : copy.composer.modeSwitchToPlan}
      onClick={() => onInteractionMode(planning ? "modeling" : "plan")}
      data-composer-plan=""
      data-chat-mode={planning ? "plan" : "build"}
      {...disablement}
    >
      {planning ? copy.composer.plan : copy.composer.modeBuild}
    </Button>
  );
}

/** The manufacturing-context menu, on the outer toolbar. */
export function ComposerControls({
  dfmMode,
  disabled,
  disabledReason,
  onDfmMode,
}: {
  readonly dfmMode: DfmMode;
  readonly disabled: boolean;
  readonly disabledReason: string;
  readonly onDfmMode: (mode: DfmMode) => void;
}): React.JSX.Element {
  const [dfmOpen, setDfmOpen] = useState(false);
  const selected = DFM_OPTIONS.find(option => option.id === dfmMode) ?? DFM_OPTIONS[0]!;
  const disablement = disabled ? { disabled: true as const, reason: disabledReason } : {};

  return <>
    <div className={styles["toolbarAnchor"]}>
      <Button
        variant="toggle"
        icon="geometry-network"
        iconLabel={`${copy.composer.manufacturing}: ${selected.label}`}
        pressed={dfmMode !== "off"}
        expanded={dfmOpen}
        title={`${copy.composer.manufacturing}: ${selected.label}`}
        onClick={() => setDfmOpen(open => !open)}
        data-composer-dfm={dfmMode}
        {...disablement}
      />
      <Popover
        open={dfmOpen}
        onClose={() => setDfmOpen(false)}
        label={copy.composer.manufacturing}
        className={styles["toolbarMenu"]}
        data-composer-dfm-menu=""
      >
        {DFM_OPTIONS.map(option => <Button
          key={option.id}
          variant="toggle"
          pressed={option.id === dfmMode}
          onClick={() => { onDfmMode(option.id); setDfmOpen(false); }}
          data-dfm-option={option.id}
        >
          {option.label}
        </Button>)}
      </Popover>
    </div>
  </>;
}
