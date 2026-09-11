import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EventImageInline } from "../../src/components/stream/EventImage";
import { liveItem } from "../../src/stream/transcript";
import { readImage } from "../../src/api/events";

const identity = { part: "p", view: "+X", channel: "rgb", source_artifact_ref: `artifact:build:sha256:${"a".repeat(64)}`, render_artifact_ref: `artifact:render:sha256:${"b".repeat(64)}` };
function render(payload: Record<string, unknown>) {
  const item = liveItem({ session_id: "s", run_id: "r", seq: 1, kind: "image", payload });
  return new DOMParser().parseFromString(renderToStaticMarkup(<EventImageInline item={item} />), "text/html");
}
describe("image identity captions", () => {
  it.each([true, false])("shows only recorded identity (live=%s), retaining exact refs without fetching", live => {
    const dom = render({ mimeType: "image/png", identity, ...(live ? { data: "AAAA", bytes: 3 } : {}) });
    const figure = dom.querySelector("figure")!;
    expect(figure.dataset["imageState"]).toBe(live ? "shown" : "metadata_only");
    expect(figure.dataset["renderRef"]).toBe(identity.render_artifact_ref);
    expect(figure.textContent).toContain("p · +X / rgb");
    expect(figure.textContent).toContain("artifact:render:sha256:bbbbbbbbbbbb…");
    expect(dom.querySelector(`[title="${identity.source_artifact_ref}"]`)).not.toBeNull();
    expect(dom.querySelectorAll("a")).toHaveLength(0);
    expect(dom.querySelectorAll("img")).toHaveLength(live ? 1 : 0);
  });
  it("legacy and incomplete tuples are explicitly unavailable", () => {
    for (const value of [undefined, { view: "iso" }, { ...identity, render_artifact_ref: "https://outside.invalid/image" }]) {
      expect(readImage({ identity: value })?.identity).toBeNull();
      const dom = render({ mimeType: "image/png", identity: value });
      expect(dom.body.textContent).toContain("Image identity unavailable");
      expect(dom.querySelector("[data-render-ref]")).toBeNull();
      expect(dom.querySelector("img")).toBeNull();
    }
  });
  it("identity strings are inert text rather than HTML or navigation", () => {
    const dom = render({ mimeType: "image/png", identity: { ...identity, part: '<img src="https://outside.invalid">' } });
    expect(dom.querySelector("img")).toBeNull();
    expect(dom.body.textContent).toContain('<img src="https://outside.invalid">');
  });
});
