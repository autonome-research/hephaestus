// The shipped, trusted Hephaestus Pi extension (architecture §4.1, §7.2;
// STAGE2_DIGEST §1).
//
// Everything Hephaestus needs Pi to enforce *inside* the agent loop lives here,
// so `defaultSessionFactory` can install one inline extension instead of
// scattering hooks across the session layer. Ambient/global Pi extensions stay
// disabled (`noExtensions: true`); the DefaultResourceLoader still loads
// `extensionFactories`, which is how a trusted extension is shipped without
// re-opening the ambient-extension door.
//
// Two policies:
//
//  1. **Tool-call preflight** (`ask_user` isolation). Pi runs a batch of tool
//     calls in parallel by default. `message_end` hands us the COMPLETE
//     assistant tool-call message, which is exactly the granularity
//     `tools/preflight.ts` needs; the resulting plan is applied by the
//     `tool_call` hook, which blocks each non-`ask_user` sibling with
//     `ask_user_must_be_alone` while the question proceeds. Blocking happens
//     before `execute` runs, so no mutation reaches the Python core in the
//     question's turn, in EITHER source order.
//
//  2. **Image eviction K=3**. `context` fires before every provider request
//     with the full message list (a structured clone), so evicting image blocks
//     here changes only what the MODEL sees — the Pi JSONL keeps its history and
//     the immutable render artifacts stay on disk. Only the most recent K
//     `inspect_part` results keep their image blocks; older ones are replaced by
//     the normative `[render: … superseded — re-run inspect_part to view]` stub.

import type {
  ExtensionAPI,
  ExtensionFactory,
  InlineExtension,
} from "@earendil-works/pi-coding-agent";
import { ASK_USER_MUST_BE_ALONE, preflight, type ToolCall } from "../tools/preflight.js";
import { IMAGE_EVICTION_K, renderStub, type RenderRef } from "./context.js";

/** Extension name shown by Pi as `<inline:hephaestus>`. */
export const HEPHAESTUS_EXTENSION_NAME = "hephaestus";

export interface HephaestusExtensionOptions {
  /** Image-eviction window; defaults to the normative K=3. */
  readonly imageEvictionK?: number;
}

// ── minimal structural views of the Pi message shapes we touch ───────────────
// `AgentMessage` is a wide union (provider messages + custom entries); we only
// need the two arms below, and only their toolCall/image fields.

interface ToolCallContent {
  readonly type: "toolCall";
  readonly id: string;
  readonly name: string;
  readonly arguments?: Record<string, unknown>;
}

interface ContentBlock {
  readonly type: string;
  readonly [k: string]: unknown;
}

interface AssistantLike {
  readonly role: "assistant";
  readonly content: ContentBlock[];
}

interface ToolResultLike {
  role: "toolResult";
  toolCallId: string;
  toolName: string;
  content: ContentBlock[];
  details?: unknown;
}

function isAssistant(message: unknown): message is AssistantLike {
  return (
    typeof message === "object" &&
    message !== null &&
    (message as { role?: unknown }).role === "assistant" &&
    Array.isArray((message as { content?: unknown }).content)
  );
}

function isToolResult(message: unknown): message is ToolResultLike {
  return (
    typeof message === "object" &&
    message !== null &&
    (message as { role?: unknown }).role === "toolResult" &&
    Array.isArray((message as { content?: unknown }).content)
  );
}

function toolCallsOf(message: AssistantLike): ToolCallContent[] {
  const calls: ToolCallContent[] = [];
  for (const block of message.content) {
    if (block.type !== "toolCall") continue;
    const id = block.id;
    const name = block.name;
    if (typeof id !== "string" || typeof name !== "string") continue;
    const args = block.arguments;
    calls.push({
      type: "toolCall",
      id,
      name,
      ...(typeof args === "object" && args !== null
        ? { arguments: args as Record<string, unknown> }
        : {}),
    });
  }
  return calls;
}

// ── image eviction ───────────────────────────────────────────────────────────

/** The render descriptors a proxied `inspect_part` result carries, in image order. */
function renderRefsOf(message: ToolResultLike, partName: string): RenderRef[] {
  const details = message.details;
  const result =
    typeof details === "object" && details !== null
      ? (details as { result?: unknown }).result
      : undefined;
  const images =
    typeof result === "object" && result !== null
      ? (result as { images?: unknown }).images
      : undefined;
  if (!Array.isArray(images)) return [];
  return images.map((entry) => {
    const img = (typeof entry === "object" && entry !== null ? entry : {}) as {
      view?: unknown;
      channel?: unknown;
    };
    return {
      name: partName,
      view: typeof img.view === "string" ? img.view : "unknown",
      channel: typeof img.channel === "string" ? img.channel : "unknown",
    };
  });
}

/**
 * Replace the image blocks of every `inspect_part` result older than the K most
 * recent with their text stubs. Returns the rewritten message list (the input
 * is Pi's own clone, so in-place content replacement is safe).
 */
export function evictImages(messages: readonly unknown[], k: number = IMAGE_EVICTION_K): unknown[] {
  // toolCallId -> the `name` argument of its inspect_part call.
  const inspectNames = new Map<string, string>();
  for (const message of messages) {
    if (!isAssistant(message)) continue;
    for (const call of toolCallsOf(message)) {
      if (call.name !== "inspect_part") continue;
      const name = call.arguments?.name;
      inspectNames.set(call.id, typeof name === "string" ? name : "unknown");
    }
  }

  // The inspect_part results that actually carry image blocks, in transcript order.
  const withImages: ToolResultLike[] = [];
  for (const message of messages) {
    if (!isToolResult(message)) continue;
    if (message.toolName !== "inspect_part") continue;
    if (!message.content.some((block) => block.type === "image")) continue;
    withImages.push(message);
  }

  for (const message of withImages.slice(0, Math.max(0, withImages.length - k))) {
    const refs = renderRefsOf(message, inspectNames.get(message.toolCallId) ?? "unknown");
    let imageIndex = 0;
    message.content = message.content.map((block) => {
      if (block.type !== "image") return block;
      const ref = refs[imageIndex] ?? {
        name: inspectNames.get(message.toolCallId) ?? "unknown",
        view: "unknown",
        channel: "unknown",
      };
      imageIndex += 1;
      return { type: "text", text: renderStub(ref) };
    });
  }
  return [...messages];
}

// ── the extension ────────────────────────────────────────────────────────────

/**
 * Build the trusted Hephaestus extension factory. One instance per session: the
 * blocked-call set is per-session state keyed by provider tool-call ID.
 */
export function hephaestusExtensionFactory(
  options: HephaestusExtensionOptions = {},
): ExtensionFactory {
  const k = options.imageEvictionK ?? IMAGE_EVICTION_K;
  return (pi: ExtensionAPI): void => {
    // Provider tool-call IDs the preflight plan blocked for the current batch.
    const blocked = new Map<string, string>();

    pi.on("message_end", (event) => {
      const message = event.message as unknown;
      if (!isAssistant(message)) return;
      // Each assistant message is a fresh batch: any residue from the previous
      // one (a blocked call the loop never dispatched) is stale by definition.
      blocked.clear();
      const calls = toolCallsOf(message);
      if (calls.length === 0) return;
      const batch: ToolCall[] = calls.map((call) => ({
        toolCallId: call.id,
        toolName: call.name,
      }));
      for (const decision of preflight(batch).decisions) {
        if (decision.action === "block") blocked.set(decision.toolCallId, decision.reason);
      }
    });

    pi.on("tool_call", (event) => {
      const reason = blocked.get(event.toolCallId);
      if (reason === undefined) return undefined;
      blocked.delete(event.toolCallId);
      return { block: true, reason };
    });

    pi.on("context", (event) => ({
      messages: evictImages(event.messages, k) as typeof event.messages,
    }));
  };
}

/** The inline extension entry handed to the app-owned ResourceLoader. */
export function hephaestusInlineExtension(
  options: HephaestusExtensionOptions = {},
): InlineExtension {
  return { name: HEPHAESTUS_EXTENSION_NAME, factory: hephaestusExtensionFactory(options) };
}

export { ASK_USER_MUST_BE_ALONE };
