// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import { SessionTabs } from "../src/components/stream/SessionTabs";
import { sessionPromptStore } from "../src/stream/sessionPrompts";
import type { SessionRow } from "../src/api/sessions";
import type { ThreadTab } from "../src/stream/thread";

const sessions: SessionRow[] = Array.from({ length: 30 }, (_, i) => ({
  session_id: `session-${String(i)}`,
  profile: i === 0 ? "orchestrator" : "part",
  part: i === 0 ? null : `part-${String(i)}`,
  parent_session_id: null,
  thread_state: "linked",
}));
const tabs: ThreadTab[] = sessions.map((row) => ({
  session_id: row.session_id, parent_session_id: null,
  kind: null, depth: 0, thread_state: "linked", origin: {},
}));

afterEach(() => sessionPromptStore.reset());

it("shows one selected human title and scope, with the whole session forest only in the switcher", () => {
  sessionPromptStore.remember("session-0", "Make a cabinet");
  sessionPromptStore.remember("session-1", "Make a cabinet");
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  function Harness(): React.JSX.Element {
    const [selected, select] = useState("session-0");
    return <SessionTabs tabs={tabs} sessions={sessions} selected={selected} onSelect={select}
      bounded={true} panelId="transcript-panel"
      create={<button data-new="">New</button>} collapse={<button data-collapse="">Collapse</button>} />;
  }
  try {
    act(() => root.render(<Harness />));
    expect(host.querySelectorAll("[data-session-tab]")).toHaveLength(1);
    expect(host.querySelector("[data-session-option]")).toBeNull();
    expect(host.querySelector("[data-session-tab]")?.textContent).toContain("Make a cabinet");
    expect(host.querySelector("[data-session-tab]")?.textContent).toContain("project session");
    const controls = [...host.querySelectorAll("button")];
    expect(controls.map((button) => button.hasAttribute("data-collapse"))).toEqual([false, false, false, true]);
    const switcher = host.querySelector<HTMLButtonElement>("[data-session-switch]")!;
    act(() => { switcher.focus(); switcher.click(); });
    expect(switcher.getAttribute("aria-expanded")).toBe("true");
    expect(host.querySelectorAll("[data-session-option]")).toHaveLength(30);
    act(() => host.querySelector<HTMLButtonElement>('[data-session-option="session-1"]')?.click());
    expect(host.querySelector("[data-session-switch-open]")).toBeNull();
    expect(document.activeElement).toBe(switcher);
    const selected = host.querySelector("[data-session-tab]");
    expect(selected?.textContent).toContain("Make a cabinet");
    expect(selected?.textContent).toContain("part-1");
    expect(selected?.getAttribute("aria-label")).toContain("part-1");
    expect(selected?.getAttribute("aria-controls")).toBe("transcript-panel");
    expect(selected?.id).toBe("session-tab-session-1");
    const ids = [...host.querySelectorAll("[id]")].map((el) => el.id);
    expect(new Set(ids).size).toBe(ids.length);
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(host.querySelector("[data-session-switch-open]")).toBeNull();
    expect(document.activeElement).toBe(switcher);
    expect(document.title).toContain("Make a cabinet");
    // Reopening from the title starts at the selected choice and still restores
    // focus to the stable switch control after that title changes.
    act(() => host.querySelector<HTMLButtonElement>("[data-session-tab]")?.click());
    expect(document.activeElement).toBe(host.querySelector('[data-session-option="session-1"]'));
    act(() => host.querySelector<HTMLButtonElement>('[data-session-option="session-2"]')?.click());
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(document.activeElement).toBe(switcher);
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});
