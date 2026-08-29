// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The `data-*` passthrough type every primitive accepts.
//
// §3.4's ownership rule says a primitive owns the `data-*` contract that
// *describes the primitive* — `data-badge` belongs to `Badge` and no call site
// may write it. It does not say a primitive may refuse the attributes that
// **address** it: `data-testid`, `data-visibility-toggle`, `data-view`,
// `data-ask-submit`, `data-inspector-tab` and the other 20-odd selectors the
// gate suite reads are the call site's namespace, not the primitive's, and
// §3.14's migration criterion is that every one of them survives verbatim.
//
// So the split is: a primitive MINTS its status/state attributes and FORWARDS
// the addressing ones. This type is the forwarding half, and it is a template
// literal key so a typo like `date-testid` is a compile error rather than a
// silently dropped selector.

export type DataAttributes = {
  readonly [key: `data-${string}`]: string | number | boolean | undefined;
};

/** Keep only the `data-*` keys of a props object, for spreading onto an element. */
export function dataProps(props: object): DataAttributes {
  const out: Record<string, string | number | boolean | undefined> = {};
  for (const [key, value] of Object.entries(props as Record<string, unknown>)) {
    if (!key.startsWith("data-")) continue;
    if (value === undefined) continue;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      out[key] = value;
    }
  }
  return out as DataAttributes;
}

/** Join class names, dropping the `string | undefined` a CSS-module index gives. */
export function cx(...parts: readonly (string | false | null | undefined)[]): string {
  return parts.filter((p): p is string => typeof p === "string" && p !== "").join(" ");
}
