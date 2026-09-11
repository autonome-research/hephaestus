// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { Transcript } from "../../src/components/stream/Transcript";
import { groupRows, historicalItem } from "../../src/stream/transcript";

it("keeps individual disclosure ownership through result growth, session return and remount", () => {
  const host = document.createElement("div"); document.body.append(host);
  let root = createRoot(host);
  const call = historicalItem({ run_id: "s", seq: 0, kind: "tool_call", tool_call_id: "call", payload: { name: "inspect", arguments: {} } }, "s");
  const result = historicalItem({ run_id: "s", seq: 1, kind: "tool_result", tool_call_id: "call", payload: { toolName: "inspect", text: "Result grows" } }, "s");
  const render = (session: string, complete = false) => act(() => {
    root.render(<Transcript sessionId={session} rows={groupRows(complete ? [call, result] : [call])} />);
  });
  const detail = () => host.querySelector<HTMLDetailsElement>("[data-chip-detail]")!;
  render("disclosure-first"); expect(detail().open).toBe(false);
  act(() => { detail().open = true; detail().dispatchEvent(new Event("toggle")); });
  render("disclosure-first", true); expect(detail().open).toBe(true);
  expect(host.querySelectorAll("[data-tool-call-id]")).toHaveLength(1);
  render("disclosure-other", true); expect(detail().open).toBe(false);
  render("disclosure-first", true); expect(detail().open).toBe(true);
  act(() => root.unmount()); root = createRoot(host);
  render("disclosure-first", true); expect(detail().open).toBe(true);
  act(() => root.unmount()); host.remove();
});
