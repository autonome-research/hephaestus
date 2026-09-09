// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { act, useSyncExternalStore } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StreamResize } from "../src/components/Shell";
import { ShellStore, shellStore, streamSizing, STAGE_MIN, RAIL_WIDTH } from "../src/state/shell";

vi.mock("../src/components/stage/Stage", () => ({ Stage: () => null }));

const WIDTHS = [843, 1000, 1024, 1279, 1440];

describe("chat width is local shell preference, bounded by current rail and viewport", () => {
  it.each(WIDTHS)("keeps useful chat and stage at %ipx; collapse/reopen retains width", (width) => {
    const store = new ShellStore();
    store.applyWidth(width);
    store.setStreamOpen(true);
    for (const request of [0, 400, 10000]) {
      store.setStreamWidth(request);
      const state = store.getSnapshot();
      const sizing = streamSizing(state);
      expect(sizing.width).toBeGreaterThanOrEqual(360);
      expect(sizing.width).toBeLessThanOrEqual(640);
      const rail = state.railOverlay ? 0 : RAIL_WIDTH;
      expect(width - rail - sizing.width).toBeGreaterThanOrEqual(STAGE_MIN);
      store.setStreamOpen(false);
      expect(store.getSnapshot().streamOpen).toBe(false);
      store.setStreamOpen(true);
      expect(streamSizing(store.getSnapshot())).toEqual(sizing);
      store.setRailOpen(true);
      expect(streamSizing(store.getSnapshot())).toEqual(sizing);
    }
  });

  it("temporarily clamps a preferred width across every viewport, then restores it", () => {
    const store = new ShellStore();
    store.setStreamWidth(600);
    for (const width of WIDTHS) {
      store.applyWidth(width);
      expect(store.getSnapshot().streamWidth).toBe(600);
      const { min, max, width: actual } = streamSizing(store.getSnapshot());
      expect(actual).toBe(Math.min(600, max));
      expect(actual).toBeGreaterThanOrEqual(min);
    }
    expect(streamSizing(store.getSnapshot()).width).toBe(600);
  });

  it("reclamps inside a band without resetting explicit expansion", () => {
    const store = new ShellStore();
    store.applyWidth(1279);
    store.setStreamOpen(true);
    store.setStreamWidth(600);
    store.applyWidth(1024);
    expect(store.getSnapshot().streamOpen).toBe(true);
    expect(streamSizing(store.getSnapshot()).width).toBe(384);
    store.applyWidth(1279);
    expect(streamSizing(store.getSnapshot()).width).toBe(600);
    store.setStreamWidth(null);
    expect(streamSizing(store.getSnapshot()).width).toBe(384);
  });

  it("never overflows even below the supported useful two-column budget; ignores invalid inputs", () => {
    const store = new ShellStore();
    for (const width of [0, 200, 359, 500, 719]) {
      store.applyWidth(width);
      const { min, max, width: actual } = streamSizing(store.getSnapshot());
      expect(min).toBeLessThanOrEqual(max);
      expect(actual).toBeLessThanOrEqual(width);
    }
    const before = store.getSnapshot();
    store.applyWidth(NaN);
    store.setStreamWidth(Infinity);
    expect(store.getSnapshot()).toBe(before);
  });
});

let root: Root | null = null;
let host: HTMLDivElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  host?.remove();
  host = null;
  shellStore.reset();
});

function Harness(): React.JSX.Element {
  const shell = useSyncExternalStore(shellStore.subscribe, shellStore.getSnapshot);
  return shell.streamOpen ? <StreamResize sizing={streamSizing(shell)} viewportWidth={shell.viewportWidth} /> : <button onClick={() => shellStore.setStreamOpen(true)}>Reopen</button>;
}

function mount(width: number): HTMLDivElement {
  shellStore.applyWidth(width);
  shellStore.setStreamOpen(true);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root?.render(<Harness />));
  return host.querySelector<HTMLDivElement>("[role=separator]")!;
}

function pointer(el: HTMLElement, type: string, x: number, id = 1, extra = {}): void {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, button: 0 });
  Object.defineProperties(event, {
    pointerId: { value: id }, isPrimary: { value: true },
    ...Object.fromEntries(Object.entries(extra).map(([key, value]) => [key, { value }])),
  });
  act(() => { el.dispatchEvent(event); });
}

function capture(el: HTMLElement): Set<number> {
  const captured = new Set<number>();
  el.setPointerCapture = vi.fn((id: number) => { captured.add(id); });
  el.hasPointerCapture = (id) => captured.has(id);
  el.releasePointerCapture = vi.fn((id: number) => { captured.delete(id); });
  return captured;
}

function key(el: HTMLElement, name: string): void {
  act(() => { el.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true })); });
}

describe("captured pointer and accessible keyboard separator", () => {
  it.each(WIDTHS)("resizes with pointer and keyboard at %ipx, then survives collapse/reopen", (width) => {
    const el = mount(width);
    const captured = capture(el);
    expect(el.getAttribute("aria-orientation")).toBe("vertical");
    expect(el.getAttribute("aria-label")).toBeTruthy();
    expect(el.tabIndex).toBe(0);
    const initial = streamSizing(shellStore.getSnapshot()).width;
    pointer(el, "pointerdown", 500);
    expect(document.activeElement).toBe(el);
    expect(captured.has(1)).toBe(true);
    pointer(el, "pointermove", 490, 2); // unrelated pointer cannot resize
    expect(streamSizing(shellStore.getSnapshot()).width).toBe(initial);
    pointer(el, "pointermove", 490);
    expect(Number(el.getAttribute("aria-valuenow"))).toBe(initial + 10);
    pointer(el, "pointerup", 490);
    expect(captured.size).toBe(0);
    pointer(el, "pointermove", 0);
    expect(Number(el.getAttribute("aria-valuenow"))).toBe(initial + 10);
    key(el, "End");
    expect(el.getAttribute("aria-valuenow")).toBe(el.getAttribute("aria-valuemax"));
    key(el, "Home");
    expect(el.getAttribute("aria-valuenow")).toBe(el.getAttribute("aria-valuemin"));
    key(el, "ArrowLeft");
    expect(Number(el.getAttribute("aria-valuenow"))).toBe(370);
    key(el, "ArrowRight");
    expect(Number(el.getAttribute("aria-valuenow"))).toBe(360);
    const preferred = shellStore.getSnapshot().streamWidth;
    act(() => shellStore.setStreamOpen(false));
    expect(host?.querySelector("[role=separator]")).toBeNull();
    act(() => host?.querySelector("button")?.click());
    expect(shellStore.getSnapshot().streamWidth).toBe(preferred);
    expect(host?.querySelector("[role=separator]")?.getAttribute("aria-valuenow")).toBe("360");
  });

  it.each(["pointercancel", "lostpointercapture", "blur", "viewport", "collapse", "unmount"])("cleans capture on %s and ignores later moves", (reason) => {
    const el = mount(1440);
    const captured = capture(el);
    pointer(el, "pointerdown", 500);
    pointer(el, "pointermove", 470);
    const preferred = shellStore.getSnapshot().streamWidth;
    if (reason === "viewport") act(() => shellStore.applyWidth(1400));
    else if (reason === "collapse") act(() => shellStore.setStreamOpen(false));
    else if (reason === "unmount") { act(() => root?.unmount()); root = null; }
    else if (reason === "blur") act(() => window.dispatchEvent(new Event("blur")));
    else pointer(el, reason, 470);
    expect(captured.size).toBe(0);
    pointer(el, "pointermove", 0);
    expect(shellStore.getSnapshot().streamWidth).toBe(preferred);
  });

  it("ignores non-primary pointers and non-left buttons", () => {
    const el = mount(1440);
    const captured = capture(el);
    pointer(el, "pointerdown", 500, 1, { isPrimary: false });
    pointer(el, "pointerdown", 500, 2, { button: 2 });
    expect(captured.size).toBe(0);
  });
});
