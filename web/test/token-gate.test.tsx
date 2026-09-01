// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The App token gate (#47, #80, #73): the hold survives reload, a live 401
// remounts the no-token panel in this tab, and that panel does not blame the
// operator for opening the page wrong.

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "../src/App";
import { apiFetch } from "../src/api/client";
import { claimToken, dropToken, holdPastedToken, tokenAbsence, workspaceToken } from "../src/api/token";
import { NoToken } from "../src/components/NoToken";
import { copy } from "../src/copy";

vi.mock("../src/components/Shell", () => ({
  Shell: () => <div data-shell="" />,
}));

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

function resetHold(): void {
  window.sessionStorage.clear();
  dropToken();
  window.history.replaceState(null, "", "/");
}

function live(element: React.ReactElement): { host: HTMLElement; root: Root } {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(element);
  });
  return { host, root };
}

function drop(mounted: { host: HTMLElement; root: Root }): void {
  act(() => {
    mounted.root.unmount();
  });
  mounted.host.remove();
}

async function flush(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  });
}

describe("NoToken copy (#73)", () => {
  beforeEach(resetHold);

  it("states the page has no token held, not that it was opened without one", () => {
    expect(copy.noToken.body.toLowerCase()).not.toMatch(/opened without/);
    expect(copy.noToken.body.toLowerCase()).toMatch(/held/);
  });

  it("marks absence-at-open as none and a live 401 as unauthorized", () => {
    window.history.replaceState(null, "", "/");
    claimToken();
    expect(tokenAbsence()).toBe("none");
    const none = renderToStaticMarkup(<NoToken />);
    expect(none).toContain('data-token-absence="none"');
    expect(none).toContain('data-testid="no-token"');
    expect(none).toContain("data-token-paste");

    window.history.replaceState(null, "", "/#t=was-held");
    claimToken();
    dropToken();
    expect(tokenAbsence()).toBe("unauthorized");
    const refused = renderToStaticMarkup(<NoToken />);
    expect(refused).toContain('data-token-absence="unauthorized"');
    expect(refused).not.toBe(none);
  });
});

describe("NoToken paste recovery (#47)", () => {
  beforeEach(resetHold);
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("holds a pasted #t= value from the field", () => {
    const mounted = live(<NoToken />);
    try {
      const field = mounted.host.querySelector<HTMLInputElement>("[data-token-paste]");
      expect(field).not.toBeNull();
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      act(() => {
        setter?.call(field, "http://127.0.0.1:8761/#t=PASTED-TOKEN");
        field!.dispatchEvent(new Event("input", { bubbles: true }));
      });
      act(() => {
        mounted.host.querySelector<HTMLButtonElement>("[data-token-apply]")?.click();
      });
      expect(workspaceToken()).toBe("PASTED-TOKEN");
    } finally {
      drop(mounted);
    }
  });
});

describe("App gate (#80)", () => {
  beforeEach(resetHold);
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the no-token panel when nothing is held", () => {
    claimToken();
    const mounted = live(<App />);
    try {
      expect(mounted.host.querySelector('[data-testid="no-token"]')).not.toBeNull();
      expect(mounted.host.querySelector("[data-shell]")).toBeNull();
      expect(mounted.host.querySelector("[data-token-absence]")?.getAttribute("data-token-absence")).toBe(
        "none",
      );
    } finally {
      drop(mounted);
    }
  });

  it("remounts NoToken in this tab when a 401 drops the token", async () => {
    window.history.replaceState(null, "", "/#t=LIVE-TOKEN");
    claimToken();
    expect(workspaceToken()).toBe("LIVE-TOKEN");
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(JSON.stringify({ status: "error", reason: "unauthorized", message: "rejected" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const mounted = live(<App />);
    try {
      expect(mounted.host.querySelector("[data-shell]")).not.toBeNull();
      await flush();
      expect(workspaceToken()).toBeNull();
      expect(tokenAbsence()).toBe("unauthorized");
      expect(mounted.host.querySelector("[data-shell]")).toBeNull();
      const panel = mounted.host.querySelector('[data-testid="no-token"]');
      expect(panel).not.toBeNull();
      expect(panel?.getAttribute("data-token-absence")).toBe("unauthorized");
      expect(panel?.querySelector("[data-token-paste]")).not.toBeNull();
    } finally {
      drop(mounted);
    }
  });

  it("apiFetch 401 drops the token before the next caller runs", async () => {
    window.history.replaceState(null, "", "/#t=LIVE-TOKEN");
    claimToken();
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(JSON.stringify({ status: "error", reason: "unauthorized", message: "rejected" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const response = await apiFetch("/parts");
    expect(response.status).toBe(401);
    expect(workspaceToken()).toBeNull();
    expect(tokenAbsence()).toBe("unauthorized");
  });

  it("a paste after a 401 remounts the signed-in tree", async () => {
    window.history.replaceState(null, "", "/#t=OLD");
    claimToken();
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(JSON.stringify({ status: "error", reason: "unauthorized", message: "rejected" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const mounted = live(<App />);
    try {
      await flush();
      expect(mounted.host.querySelector('[data-testid="no-token"]')).not.toBeNull();
      vi.stubGlobal(
        "fetch",
        async () =>
          new Response(JSON.stringify({ status: "ok", parts: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      );
      act(() => {
        holdPastedToken("#t=NEW-TOKEN");
      });
      expect(workspaceToken()).toBe("NEW-TOKEN");
      expect(mounted.host.querySelector("[data-shell]")).not.toBeNull();
      expect(mounted.host.querySelector('[data-testid="no-token"]')).toBeNull();
    } finally {
      drop(mounted);
    }
  });
});
