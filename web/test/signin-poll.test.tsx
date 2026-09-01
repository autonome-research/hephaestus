// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Device-code / authorize-url completion (#76). The API (`loginStatus`,
// `cancelLogin`) already existed; the dialog never called either.

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { FlowDocument, ProviderRow } from "../src/api/providers";
import * as providers from "../src/api/providers";
import { loginPollOutcome, SignInDialog } from "../src/components/SignInDialog";

vi.mock("../src/api/providers", async (importOriginal) => {
  const actual = await importOriginal<typeof providers>();
  return {
    ...actual,
    beginLogin: vi.fn(),
    loginStatus: vi.fn(),
    cancelLogin: vi.fn(),
    completeLogin: vi.fn(),
  };
});

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

function row(): ProviderRow {
  return {
    id: "heph-fake",
    kind: "pi_native",
    name: "Fake",
    models: [{ id: "m", name: "M" }],
    source: "none",
    health: "unused",
    last_observed_at: null,
    available: null,
    unavailable_reason: null,
  };
}

function deviceFlow(over: Partial<FlowDocument> = {}): FlowDocument {
  return {
    status: "ok",
    provider_id: "heph-fake",
    type: "device_code",
    state: "authorization_pending",
    user_code: "HEPH-TEST",
    verification_uri: "https://provider.example/device",
    interval_seconds: 1,
    expires_at: 2_000_000_000,
    ...over,
  };
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

describe("loginPollOutcome", () => {
  it("stays pending while the sidecar reports authorization_pending", () => {
    expect(
      loginPollOutcome({
        status: "ok",
        state: "none",
        flow: { state: "authorization_pending" },
      }),
    ).toBe("pending");
    expect(loginPollOutcome({ status: "error", reason: "authorization_pending" })).toBe("pending");
    expect(loginPollOutcome({ status: "error", reason: "slow_down" })).toBe("pending");
  });

  it("completes on flow.state or type=oauth", () => {
    expect(loginPollOutcome({ status: "ok", flow: { state: "complete" } })).toBe("complete");
    expect(loginPollOutcome({ status: "ok", state: "project", type: "oauth" })).toBe("complete");
  });

  it("fails on a named flow failure", () => {
    expect(loginPollOutcome({ status: "ok", flow: { state: "failed" } })).toBe("failed");
    expect(loginPollOutcome({ status: "error", reason: "authorization_expired" })).toBe("failed");
  });
});

describe("SignInDialog polls and cancels (#76)", () => {
  beforeEach(() => {
    vi.mocked(providers.beginLogin).mockReset();
    vi.mocked(providers.loginStatus).mockReset();
    vi.mocked(providers.cancelLogin).mockReset();
    vi.mocked(providers.completeLogin).mockReset();
    vi.mocked(providers.cancelLogin).mockResolvedValue({ status: "ok" });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls loginStatus until complete, then onSignedIn / onClose", async () => {
    vi.mocked(providers.beginLogin).mockResolvedValue(deviceFlow());
    vi.mocked(providers.loginStatus)
      .mockResolvedValueOnce({ status: "ok", state: "none", flow: { state: "authorization_pending" } })
      .mockResolvedValueOnce({ status: "ok", state: "project", type: "oauth" });
    const onClose = vi.fn();
    const onSignedIn = vi.fn();
    const mounted = live(<SignInDialog provider={row()} open onClose={onClose} onSignedIn={onSignedIn} />);
    try {
      act(() => {
        mounted.host.querySelector<HTMLButtonElement>('[data-signin-begin="device_code"]')?.click();
      });
      await act(async () => {
        await Promise.resolve();
      });
      expect(mounted.host.querySelector('[data-signin-device-code="HEPH-TEST"]')).not.toBeNull();
      expect(providers.loginStatus).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(providers.loginStatus).toHaveBeenCalledTimes(1);
      expect(onSignedIn).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(providers.loginStatus).toHaveBeenCalledTimes(2);
      expect(onSignedIn).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(providers.cancelLogin).not.toHaveBeenCalled();
    } finally {
      drop(mounted);
    }
  });

  it("calls cancelLogin when the dialog is dismissed", async () => {
    vi.mocked(providers.beginLogin).mockResolvedValue(deviceFlow());
    vi.mocked(providers.loginStatus).mockResolvedValue({
      status: "ok",
      state: "none",
      flow: { state: "authorization_pending" },
    });
    const onClose = vi.fn();
    const mounted = live(
      <SignInDialog provider={row()} open onClose={onClose} onSignedIn={() => undefined} />,
    );
    try {
      act(() => {
        mounted.host.querySelector<HTMLButtonElement>('[data-signin-begin="device_code"]')?.click();
      });
      await act(async () => {
        await Promise.resolve();
      });
      act(() => {
        mounted.host.querySelector<HTMLElement>("[data-popover-scrim]")?.click();
      });
      expect(providers.cancelLogin).toHaveBeenCalledWith("heph-fake");
      expect(onClose).toHaveBeenCalledTimes(1);
    } finally {
      drop(mounted);
    }
  });
});
