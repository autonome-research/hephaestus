// Image identity lives in supported text descriptors, not extra Pi ImageContent
// fields (pinned 0.80.10 supports only type/data/mimeType on image blocks).
import { createHash } from "node:crypto";
import type { JsonValue } from "./framing.js";

export const IMAGE_IDENTITY_FIELDS = ["part", "view", "channel", "source_artifact_ref", "render_artifact_ref"] as const;
// `part` names the requested inspection context; an explicit immutable source
// ref can be non-current, so this is not an artifact ownership assertion.
export type ImageIdentity = { readonly [K in typeof IMAGE_IDENTITY_FIELDS[number]]: string };
export const RENDER_REF = /^artifact:render:sha256:[a-f0-9]{64}$/;
const PREVIEW_REF = /^artifact:selection-preview:sha256:[a-f0-9]{64}$/;
const PASS_REF = /^artifact:selection-pass:sha256:[a-f0-9]{64}$/;
const BUNDLE_REF = /^artifact:selection-bundle:sha256:[a-f0-9]{64}$/;
const SOURCE_REF = /^artifact:[a-z][a-z0-9-]*:sha256:[a-f0-9]{64}$/;
export function renderRef(bytes: Buffer, kind: "render" | "selection-preview" = "render"): string {
  return `artifact:${kind}:sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
export function readImageIdentity(value: unknown): ImageIdentity | undefined {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return undefined;
  const obj = value as Record<string, unknown>;
  for (const key of IMAGE_IDENTITY_FIELDS) {
    const field = obj[key];
    if (typeof field !== "string" || field.length === 0 || field.length > 256 || [...field].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) return undefined;
  }
  const ref = obj.render_artifact_ref as string;
  if (!(RENDER_REF.test(ref) || (obj.channel === "mask" && PREVIEW_REF.test(ref))) || !SOURCE_REF.test(obj.source_artifact_ref as string)) return undefined;
  if (!["rgb", "mask", "section"].includes(obj.channel as string)) return undefined;
  return Object.fromEntries(IMAGE_IDENTITY_FIELDS.map(key => [key, obj[key]])) as ImageIdentity;
}

/** Selection masks retain preview + three artifact-only ID passes per view.
 * Their flat retention list is not a one-ref-per-inline-image list. */
export function inlineRenderRefs(result: Record<string, JsonValue>, count: number): JsonValue[] | undefined {
  const refs = result.render_artifact_refs;
  if (!Array.isArray(refs)) return undefined;
  const bundles = result.selection_bundles;
  if (bundles === undefined) return refs.length === count && refs.every(ref => typeof ref === "string" && RENDER_REF.test(ref)) ? refs : undefined;
  if (!Array.isArray(bundles) || bundles.length !== count || refs.length !== count * 4) return undefined;
  for (const [index, bundle] of bundles.entries()) {
    if (!bundle || typeof bundle !== "object" || Array.isArray(bundle)) return undefined;
    const preview = refs[index * 4];
    if (typeof preview !== "string" || !PREVIEW_REF.test(preview) || typeof bundle.bundle_ref !== "string" || !BUNDLE_REF.test(bundle.bundle_ref)) return undefined;
    const image = Array.isArray(result.images) ? result.images[index] : undefined;
    if (!image || typeof image !== "object" || Array.isArray(image) || image.view !== bundle.view || image.channel !== "mask") return undefined;
    const passes = bundle.pass_refs;
    if (!passes || typeof passes !== "object" || Array.isArray(passes)) return undefined;
    if (["solid", "face", "edge"].some((key, offset) => typeof passes[key] !== "string" || !PASS_REF.test(passes[key] as string) || passes[key] !== refs[index * 4 + offset + 1])) return undefined;
  }
  return bundles.map((_, index) => refs[index * 4]!);
}

/** Read only complete recorded identities. No association guessed from nearby
 * calls, top-level refs or a different result. History never loads image bytes.
 * Live additionally verifies descriptor-to-content byte and MIME correlation.
 */
export function imageIdentities(text: string, images: readonly { mimeType?: string; data?: string }[], live: boolean): (ImageIdentity | undefined)[] {
  try {
    const result = JSON.parse(text) as Record<string, JsonValue>;
    const descriptors = result.images;
    const refs = inlineRenderRefs(result, images.length);
    if (!Array.isArray(descriptors) || descriptors.length !== images.length || refs === undefined) return [];
    return descriptors.map((descriptor, index) => {
      const identity = readImageIdentity(descriptor);
      if (!identity || identity.source_artifact_ref !== result.source_artifact_ref || identity.render_artifact_ref !== refs[index]) return undefined;
      const image = images[index];
      if (live && (typeof image?.data !== "string" || renderRef(Buffer.from(image.data, "base64"), result.selection_bundles === undefined ? "render" : "selection-preview") !== identity.render_artifact_ref || (descriptor as Record<string, JsonValue>).mime_type !== image.mimeType)) return undefined;
      return identity;
    });
  } catch { return []; }
}
