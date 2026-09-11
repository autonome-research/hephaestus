import type { AgentSessionEvent, SessionEntry } from "@earendil-works/pi-coding-agent";
import { normalizeLiveEvent } from "../src/session/live.js";
import { normalizeEntries } from "../src/session/history.js";
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { ToolProxy, type ProxyContext } from "../src/tools/proxy.js";
import { makeInvocation } from "../src/tools/invocation.js";
import type { JsonValue } from "../src/framing.js";

const ctx: ProxyContext = {
  sessionId: "image-session", runId: "image-run", imagesSupported: true,
  invocation: makeInvocation({ sessionId: "image-session", entryId: "e", ordinal: 0, providerCallId: "c" }),
};
const source = `artifact:build:sha256:${"a".repeat(64)}`;
function fixture() {
  const images = ["iso", "+X"].map((view, index) => {
    // Header-only fixture: tests validation/identity, not raster decoding.
    const bytes = Buffer.alloc(24);
    Buffer.from("89504e470d0a1a0a", "hex").copy(bytes);
    bytes.write("IHDR", 12); bytes.writeUInt32BE(2 + index, 16); bytes.writeUInt32BE(2, 20);
    return { part: "p", view, channel: "rgb", source_artifact_ref: source,
      render_artifact_ref: `artifact:render:sha256:${createHash("sha256").update(bytes).digest("hex")}`,
      data: bytes.toString("base64"), mime_type: "image/png" };
  });
  return { status: "ok", source_artifact_ref: source, render_artifact_refs: images.map(i => i.render_artifact_ref), images };
}
function selectionFixture() {
  const raw = fixture();
  const images = raw.images.map(image => ({ ...image, channel: "mask",
    render_artifact_ref: image.render_artifact_ref.replace(":render:", ":selection-preview:") }));
  const bundles = images.map((image, index) => ({ view: image.view,
    bundle_ref: `artifact:selection-bundle:sha256:${String(index).repeat(64)}`,
    pass_refs: Object.fromEntries(["solid", "face", "edge"].map((kind, offset) =>
      [kind, `artifact:selection-pass:sha256:${String(index * 3 + offset).repeat(64)}`])) }));
  return { ...raw, images, selection_bundles: bundles,
    render_artifact_refs: images.flatMap((image, index) => [image.render_artifact_ref,
      ...["solid", "face", "edge"].map(kind => bundles[index]!.pass_refs[kind]!)]) };
}
const selectionArgs = { name: "p", views: ["iso", "+X"], channel: "mask", mask_mode: "selection" };
function execute(result: JsonValue, context = ctx) {
  return new ToolProxy(async () => result).execute("inspect_part", { name: "p", views: ["iso", "+X"] }, context);
}

describe("render identity contract", () => {
  it("retains the distinct ordered identity tuples in model descriptors", async () => {
    const raw = fixture();
    const result = await execute(raw);
    const block = result.content[0];
    expect(block?.type).toBe("text");
    if (block?.type !== "text") throw new Error("missing descriptor");
    const descriptors = JSON.parse(block.text).images;
    expect(descriptors).toHaveLength(2);
    for (const [index, image] of raw.images.entries()) {
      const { data, ...identity } = image;
      expect(descriptors[index]).toMatchObject(identity);
      expect(block.text).not.toContain(data);
      expect(result.content[index + 1]).toEqual({ type: "image", data, mimeType: "image/png" });
    }
  });
  it.each(["hash", "order", "count", "part", "source", "mime", "base64", "partial"])("fails closed on %s mismatch", async fault => {
    const raw = fixture();
    const first = raw.images[0]!;
    if (fault === "hash") first.render_artifact_ref = `artifact:render:sha256:${"b".repeat(64)}`;
    if (fault === "order") raw.render_artifact_refs.reverse();
    if (fault === "count") raw.render_artifact_refs.pop();
    if (fault === "part") first.part = "other";
    if (fault === "source") first.source_artifact_ref = `artifact:build:sha256:${"b".repeat(64)}`;
    if (fault === "mime") first.mime_type = "image/jpeg";
    if (fault === "base64") first.data += "!";
    if (fault === "partial") first.view = "";
    await expect(execute(raw)).rejects.toMatchObject({ name: "ProxyResultError" });
  });
  it.each(["modern", "legacy", "absent"])("rejects a self-consistent wrong explicit source (%s metadata)", async metadata => {
    const raw = fixture();
    const images = metadata === "modern" ? raw.images : raw.images.map(image => {
      const { data, mime_type, view, channel, render_artifact_ref } = image;
      return metadata === "legacy" ? { data, mime_type, view, channel, render_artifact_ref } : { data, mime_type };
    });
    const proxy = new ToolProxy(async () => ({ ...raw, images }));
    await expect(proxy.execute("inspect_part", { name: "p", views: ["iso", "+X"], artifact_ref: `artifact:build:sha256:${"b".repeat(64)}` }, ctx)).rejects.toMatchObject({ code: "image_identity_mismatch" });
  });
  it.each([source, null, undefined])("preserves matching by-ref and implicit source inspection (%s)", async artifact_ref => {
    const result = await new ToolProxy(async () => fixture()).execute("inspect_part", {
      name: "p", views: ["iso", "+X"], ...(artifact_ref === undefined ? {} : { artifact_ref }),
    }, ctx);
    expect(result.details.images).toBe(2);
  });
  it("normalizes the same tuple live and in metadata-only history without extra Pi fields", async () => {
    const result = await execute(fixture());
    const live = normalizeLiveEvent({ type: "tool_execution_end", toolName: "inspect_part", toolCallId: "c", result, isError: false } as AgentSessionEvent, "r", () => 0).filter(e => e.kind === "image");
    const history = normalizeEntries([{ type: "message", id: "e", parentId: null, timestamp: "now", message: { role: "toolResult", toolName: "inspect_part", toolCallId: "c", content: result.content, isError: false, timestamp: 0 } } as SessionEntry], "s").filter(e => e.kind === "image");
    expect(live).toHaveLength(2); expect(history).toHaveLength(2);
    for (let index = 0; index < 2; index++) {
      const { data: _data, mime_type: _mime, ...identity } = fixture().images[index]!;
      expect(live[index]?.payload).toMatchObject({ identity });
      expect(history[index]?.payload).toEqual({ mimeType: "image/png", identity });
    }
  });
  it("preserves selection-mask preview/pass retention boundaries", async () => {
    // The publisher mints previews and artifact-only ID passes with distinct kinds.
    const raw = selectionFixture();
    const result = await new ToolProxy(async () => raw).execute("inspect_part", selectionArgs, ctx);
    expect(result.content.filter(c => c.type === "image")).toHaveLength(2);
    expect(JSON.stringify(result.content[0])).toContain("selection_bundles");
  });
  it("refuses a selection bundle whose view disagrees with its preview", async () => {
    const raw = selectionFixture();
    raw.selection_bundles[0]!.view = "-Z";
    await expect(new ToolProxy(async () => raw).execute("inspect_part", selectionArgs, ctx)).rejects.toMatchObject({ code: "image_identity_mismatch" });
  });
  it.each(["render", "selection-pass", "posed-render", "unknown", "hash", "pass-kind", "bundle-kind", "order", "source", "mode", "missing-bundles"])("rejects selection %s mismatch", async fault => {
    const raw = selectionFixture();
    if (["render", "selection-pass", "posed-render", "unknown"].includes(fault)) {
      raw.images[0]!.render_artifact_ref = raw.images[0]!.render_artifact_ref.replace(":selection-preview:", `:${fault}:`);
      raw.render_artifact_refs[0] = raw.images[0]!.render_artifact_ref;
    }
    if (fault === "hash") raw.images[0]!.data = raw.images[1]!.data;
    if (fault === "pass-kind") {
      raw.selection_bundles[0]!.pass_refs.solid = raw.selection_bundles[0]!.pass_refs.solid!.replace(":selection-pass:", ":render:");
      raw.render_artifact_refs[1] = raw.selection_bundles[0]!.pass_refs.solid!;
    }
    if (fault === "bundle-kind") raw.selection_bundles[0]!.bundle_ref = raw.selection_bundles[0]!.bundle_ref.replace(":selection-bundle:", ":render:");
    if (fault === "order") raw.render_artifact_refs.reverse();
    if (fault === "source") raw.images[0]!.source_artifact_ref = `artifact:build:sha256:${"b".repeat(64)}`;
    const result = fault === "missing-bundles" ? { ...raw, selection_bundles: undefined, render_artifact_refs: raw.images.map(i => i.render_artifact_ref) } : raw;
    await expect(new ToolProxy(async () => result as JsonValue).execute("inspect_part", { ...selectionArgs, mask_mode: fault === "mode" ? "solid" : "selection" }, ctx)).rejects.toMatchObject({ code: "image_identity_mismatch" });
  });
  it("keeps selection identities in live events and byte-free history", async () => {
    const raw = selectionFixture();
    const result = await new ToolProxy(async () => raw).execute("inspect_part", selectionArgs, ctx);
    const live = normalizeLiveEvent({ type: "tool_execution_end", toolName: "inspect_part", toolCallId: "c", result, isError: false } as AgentSessionEvent, "r", () => 0).filter(e => e.kind === "image");
    const history = normalizeEntries([{ type: "message", id: "e", parentId: null, timestamp: "now", message: { role: "toolResult", toolName: "inspect_part", toolCallId: "c", content: result.content, isError: false, timestamp: 0 } } as SessionEntry], "s").filter(e => e.kind === "image");
    expect(live).toHaveLength(2); expect(history).toHaveLength(2);
    for (const [index, image] of raw.images.entries()) {
      const { data, mime_type: _mime, ...identity } = image;
      expect(live[index]?.payload).toMatchObject({ identity, data });
      expect(history[index]?.payload).toEqual({ mimeType: "image/png", identity });
    }
  });
  it("enforces the unchanged aggregate pixel budget", async () => {
    const raw = fixture();
    const bytes = Buffer.from(raw.images[0]!.data, "base64");
    bytes.writeUInt32BE(4096, 16); bytes.writeUInt32BE(4096, 20);
    await expect(execute({ ...raw, images: Array.from({ length: 3 }, () => ({ data: bytes.toString("base64"), mime_type: "image/png" })) })).rejects.toMatchObject({ name: "ProxyResultError" });
  });
  it("legacy absent metadata never fabricates identity", async () => {
    const raw = fixture();
    const result = await execute({ ...raw, images: raw.images.map(({ data, mime_type }) => ({ data, mime_type })) });
    const live = normalizeLiveEvent({ type: "tool_execution_end", toolName: "inspect_part", toolCallId: "c", result, isError: false } as AgentSessionEvent, "r", () => 0).filter(e => e.kind === "image");
    expect(live).toHaveLength(2);
    for (const event of live) expect(event.payload).not.toHaveProperty("identity");
  });
  it("text-only refusal says only what admitted capability establishes", async () => {
    const result = await execute(fixture(), { ...ctx, imagesSupported: false });
    expect(result.content.filter(c => c.type === "image")).toHaveLength(0);
    expect(result.details.capability).toBe("image_model_required");
    expect(JSON.stringify(result.content)).not.toContain("no vision model is configured");
    expect(JSON.stringify(result.content)).toContain("automatic routing");
    expect(JSON.stringify(result.content)).toContain("not visually reviewed");
  });
});
