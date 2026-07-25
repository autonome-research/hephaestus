// Unit coverage for the shipped trusted Hephaestus extension: the tool-call
// preflight it applies via Pi's hooks, and the K=3 image eviction it applies to
// the model-visible context. The end-to-end proof (through the real bridge and
// a real Pi session) lives in tests/stage2; these tests pin the pure edges.

import { describe, it, expect } from "vitest";
import {
  evictImages,
  hephaestusExtensionFactory,
  HEPHAESTUS_EXTENSION_NAME,
  hephaestusInlineExtension,
} from "../../src/session/extension.js";
import { ASK_USER_MUST_BE_ALONE } from "../../src/tools/preflight.js";

// ── a minimal ExtensionAPI stand-in ─────────────────────────────────────────

type Handler = (event: unknown) => unknown;

class FakePi {
  readonly handlers = new Map<string, Handler[]>();
  on(event: string, handler: Handler): void {
    const list = this.handlers.get(event) ?? [];
    list.push(handler);
    this.handlers.set(event, list);
  }
  emit(event: string, payload: unknown): unknown {
    const list = this.handlers.get(event) ?? [];
    let last: unknown;
    for (const handler of list) last = handler(payload);
    return last;
  }
}

function install(): FakePi {
  const pi = new FakePi();
  // The factory only needs `on`; the cast keeps the test free of the full API.
  hephaestusExtensionFactory()(pi as unknown as Parameters<
    ReturnType<typeof hephaestusExtensionFactory>
  >[0]);
  return pi;
}

function assistant(...calls: { id: string; name: string; args?: Record<string, unknown> }[]) {
  return {
    role: "assistant" as const,
    content: calls.map((c) => ({
      type: "toolCall",
      id: c.id,
      name: c.name,
      arguments: c.args ?? {},
    })),
  };
}

function inspectResult(toolCallId: string, views: string[], channel = "rgb") {
  return {
    role: "toolResult" as const,
    toolCallId,
    toolName: "inspect_part",
    content: [
      { type: "text", text: "{}" },
      ...views.map(() => ({ type: "image", data: "AAAA", mimeType: "image/png" })),
    ],
    details: {
      tool: "inspect_part",
      result: { images: views.map((view) => ({ view, channel })) },
    },
  };
}

// ── preflight application ───────────────────────────────────────────────────

describe("tool-call preflight hook", () => {
  it("blocks a mutating sibling of ask_user in both source orders", () => {
    for (const order of [
      [
        { id: "q", name: "ask_user" },
        { id: "m", name: "edit_part" },
      ],
      [
        { id: "m", name: "edit_part" },
        { id: "q", name: "ask_user" },
      ],
    ]) {
      const pi = install();
      pi.emit("message_end", { type: "message_end", message: assistant(...order) });
      expect(pi.emit("tool_call", { toolCallId: "m", toolName: "edit_part" })).toEqual({
        block: true,
        reason: ASK_USER_MUST_BE_ALONE,
      });
      expect(pi.emit("tool_call", { toolCallId: "q", toolName: "ask_user" })).toBeUndefined();
    }
  });

  it("leaves an ordinary mutating batch (no question) unblocked", () => {
    const pi = install();
    pi.emit("message_end", {
      type: "message_end",
      message: assistant({ id: "a", name: "build_part" }, { id: "b", name: "build_part" }),
    });
    expect(pi.emit("tool_call", { toolCallId: "a", toolName: "build_part" })).toBeUndefined();
    expect(pi.emit("tool_call", { toolCallId: "b", toolName: "build_part" })).toBeUndefined();
  });

  it("clears a block after it fires so a later turn's re-issue proceeds", () => {
    const pi = install();
    pi.emit("message_end", {
      type: "message_end",
      message: assistant({ id: "q", name: "ask_user" }, { id: "m", name: "edit_part" }),
    });
    expect(pi.emit("tool_call", { toolCallId: "m", toolName: "edit_part" })).toMatchObject({
      block: true,
    });
    // Re-issued alone in the next turn: no plan blocks it.
    pi.emit("message_end", {
      type: "message_end",
      message: assistant({ id: "m", name: "edit_part" }),
    });
    expect(pi.emit("tool_call", { toolCallId: "m", toolName: "edit_part" })).toBeUndefined();
  });

  it("ignores non-assistant messages and assistant messages with no tool calls", () => {
    const pi = install();
    pi.emit("message_end", { type: "message_end", message: { role: "user", content: [] } });
    pi.emit("message_end", {
      type: "message_end",
      message: { role: "assistant", content: [{ type: "text", text: "hi" }] },
    });
    expect(pi.emit("tool_call", { toolCallId: "x", toolName: "edit_part" })).toBeUndefined();
  });
});

// ── image eviction ──────────────────────────────────────────────────────────

function imageCount(messages: readonly unknown[]): number {
  let n = 0;
  for (const m of messages) {
    const content = (m as { content?: { type: string }[] }).content ?? [];
    n += content.filter((b) => b.type === "image").length;
  }
  return n;
}

function stubs(messages: readonly unknown[]): string[] {
  const found: string[] = [];
  for (const m of messages) {
    const content = (m as { content?: { type: string; text?: string }[] }).content ?? [];
    for (const block of content) {
      if (block.type === "text" && block.text?.startsWith("[render:")) found.push(block.text);
    }
  }
  return found;
}

describe("image eviction (K=3)", () => {
  it("keeps the three most recent inspect results and stubs the rest", () => {
    const messages: unknown[] = [];
    for (let i = 1; i <= 4; i++) {
      messages.push(assistant({ id: `c${i}`, name: "inspect_part", args: { name: "widget" } }));
      messages.push(inspectResult(`c${i}`, ["iso"]));
    }
    const out = evictImages(messages);
    expect(imageCount(out)).toBe(3);
    expect(stubs(out)).toEqual([
      "[render: widget iso/rgb, superseded — re-run inspect_part to view]",
    ]);
  });

  it("is a no-op at or below the window", () => {
    const messages: unknown[] = [];
    for (let i = 1; i <= 3; i++) {
      messages.push(assistant({ id: `c${i}`, name: "inspect_part", args: { name: "widget" } }));
      messages.push(inspectResult(`c${i}`, ["iso"]));
    }
    const out = evictImages(messages);
    expect(imageCount(out)).toBe(3);
    expect(stubs(out)).toEqual([]);
  });

  it("stubs every image of an evicted multi-view result, naming each view", () => {
    const messages: unknown[] = [];
    messages.push(assistant({ id: "c0", name: "inspect_part", args: { name: "shelf" } }));
    messages.push(inspectResult("c0", ["iso", "+X"], "mask"));
    for (let i = 1; i <= 3; i++) {
      messages.push(assistant({ id: `c${i}`, name: "inspect_part", args: { name: "shelf" } }));
      messages.push(inspectResult(`c${i}`, ["iso"]));
    }
    const out = evictImages(messages);
    expect(imageCount(out)).toBe(3);
    expect(stubs(out)).toEqual([
      "[render: shelf iso/mask, superseded — re-run inspect_part to view]",
      "[render: shelf +X/mask, superseded — re-run inspect_part to view]",
    ]);
  });

  it("ignores non-inspect tool results and results without images", () => {
    const messages: unknown[] = [
      assistant({ id: "b", name: "build_part", args: { name: "widget" } }),
      {
        role: "toolResult",
        toolCallId: "b",
        toolName: "build_part",
        content: [{ type: "text", text: "{}" }],
      },
    ];
    for (let i = 1; i <= 4; i++) {
      messages.push(assistant({ id: `c${i}`, name: "inspect_part", args: { name: "widget" } }));
      messages.push(inspectResult(`c${i}`, ["iso"]));
    }
    const out = evictImages(messages);
    expect(out).toHaveLength(messages.length);
    expect(imageCount(out)).toBe(3);
  });

  it("honours a custom window", () => {
    const messages: unknown[] = [];
    for (let i = 1; i <= 3; i++) {
      messages.push(assistant({ id: `c${i}`, name: "inspect_part", args: { name: "widget" } }));
      messages.push(inspectResult(`c${i}`, ["iso"]));
    }
    expect(imageCount(evictImages(messages, 1))).toBe(1);
  });
});

describe("inline extension entry", () => {
  it("is named so Pi lists it as <inline:hephaestus>", () => {
    const inline = hephaestusInlineExtension();
    expect(inline).toMatchObject({ name: HEPHAESTUS_EXTENSION_NAME });
    expect(HEPHAESTUS_EXTENSION_NAME).toBe("hephaestus");
  });
});
