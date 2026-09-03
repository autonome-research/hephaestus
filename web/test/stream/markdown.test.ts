// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Transcript markdown (INTERFACE.md §7.3): assistant and operator prose
// render headings, lists, fences, bold, and http(s) links. Tool-chip JSON
// is never passed through this renderer.

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown, renderMarkdown } from "../../src/stream/markdown";

function parse(markup: string): Document {
  return new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
}

describe("the sanitizing markdown renderer", () => {
  it("renders headings, lists, fences, bold, and http(s) links", () => {
    const document_ = parse(
      renderToStaticMarkup(
        <Markdown
          text={[
            "## Plate",
            "",
            "A **2 mm** chamfer on the `[edge](https://example.test/edge)`.",
            "",
            "- front",
            "- back",
            "",
            "```ts",
            "const x = 1;",
            "```",
            "",
            "1. first",
            "2. second",
          ].join("\n")}
        />,
      ),
    );
    expect(document_.querySelector("h4")?.textContent).toBe("Plate");
    expect(document_.querySelector("strong")?.textContent).toBe("2 mm");
    expect(document_.querySelector("a")?.getAttribute("href")).toBe("https://example.test/edge");
    expect(document_.querySelector("ul")?.textContent).toContain("front");
    expect(document_.querySelector("pre code")?.textContent).toBe("const x = 1;");
    expect(document_.querySelector("ol")?.textContent).toContain("first");
  });

  it("drops javascript: and other non-http(s) hrefs", () => {
    const nodes = renderMarkdown("[x](javascript:alert(1)) [y](https://ok.test)");
    const markup = renderToStaticMarkup(<>{nodes}</>);
    expect(markup).not.toContain("javascript:");
    expect(markup).toContain("https://ok.test/");
  });
});
