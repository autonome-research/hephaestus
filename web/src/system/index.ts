// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The system layer's public surface (INTERFACE.md §3.4).
//
// §4.2: "System primitives are not panels." `Badge`, `Button`, `Chip`,
// `DataTable`, `Panel`/`PanelHeader`, `TabBar`, `TreeRow`, `Field`, `Input`,
// `Popover`, `EmptyState`, `Icon` live here and are *how* a panel is built, not
// entries in the closed panel inventory. Adding one is not §18 work; adding a
// **panel** still is.
//
// §3.4's rule, which this barrel exists to make easy to obey: a component under
// `web/src/components/` may not declare a `font-size`, `color`, `border`,
// `border-radius`, or `background` on a text-bearing element. It composes a type
// role and renders a system primitive. Panel-local CSS Modules survive only for
// *layout*.

export { Badge, SeverityBadge, StatusBadge } from "./Badge";
export {
  BADGE_STATUSES,
  BADGE_ICONS,
  SEVERITIES,
  SEVERITY_ICONS,
  CHIP_STATUSES,
  CHIP_ICONS,
} from "./Badge";
export type { BadgeStatus, Severity, ChipStatus } from "./Badge";

export { Button, BUTTON_VARIANTS } from "./Button";
export type { ButtonProps, ButtonVariant } from "./Button";

export { Chip } from "./Chip";
export type { ChipProps } from "./Chip";

export { DataTable, Field } from "./DataTable";
export type { DataRow, DataTableProps, FieldProps } from "./DataTable";

export { EmptyState } from "./EmptyState";
export type { EmptyStateProps } from "./EmptyState";

export { Icon, ICON_IDS } from "./icons";
export type { IconId, IconProps } from "./icons";

export { Select, Slider, TextInput } from "./Input";
export type { SelectProps, SliderProps, TextInputProps } from "./Input";

export { Panel, PanelBody, PanelHeader, PanelNote, PanelSection } from "./Panel";
export type { PanelBodyProps, PanelHeaderProps, PanelProps } from "./Panel";

export { Popover } from "./Popover";
export type { PopoverProps } from "./Popover";

export { TabBar } from "./TabBar";
export type { TabBarProps, TabSpec } from "./TabBar";

export { Tree, TreeGroup, TreeRow } from "./TreeRow";
export type { TreeProps, TreeRowProps } from "./TreeRow";

export { useBreakpoint, useShell } from "./useBreakpoint";
export { BREAKPOINT_RAIL, BREAKPOINT_STREAM, bandFor } from "./useBreakpoint";
export type { Band, ShellState } from "./useBreakpoint";

export {
  CHIP_REF_WIDTH,
  formatBytes,
  formatNumber,
  formatOid,
  formatRef,
  formatValue,
  metricLabel,
  metricUnit,
} from "./format";

export { cx } from "./dataAttrs";
export type { DataAttributes } from "./dataAttrs";
