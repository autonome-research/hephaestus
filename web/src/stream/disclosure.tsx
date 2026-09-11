// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { createContext, useContext, useId, useSyncExternalStore, type ComponentProps } from "react";

/** Session + stable presentation-row identity, never a component lifetime. */
export const DisclosureOwner = createContext<string | null>(null);
const expanded = new Map<string, boolean>();
const listeners = new Set<() => void>();
const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
export function useDisclosure(name: string): readonly [boolean, (open: boolean) => void] {
  const owner = useContext(DisclosureOwner);
  const local = useId();
  const key = JSON.stringify([owner ?? local, name]);
  const open = useSyncExternalStore(subscribe, () => expanded.get(key) ?? false, () => false);
  return [open, (value) => {
    if (expanded.get(key) === value) return;
    expanded.set(key, value);
    for (const listener of listeners) listener();
  }];
}
export function PersistentDetails({ name = "details", ...props }: ComponentProps<"details"> & {
  readonly name?: string;
}): React.JSX.Element {
  const [open, setOpen] = useDisclosure(name);
  return <details {...props} open={open} onToggle={event => {
    setOpen(event.currentTarget.open);
    props.onToggle?.(event);
  }} />;
}
