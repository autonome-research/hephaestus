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
            "A **2 mm** chamfer on the [edge](https://example.test/edge).",
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
    expect(markup).not.toContain('href="javascript:');
    expect(markup).not.toMatch(/<a[^>]+javascript:/);
    expect(markup).toContain("https://ok.test/");
  });
});

// ---------------------------------------------------------------------------
// W4 GOAL: "markdown that holds up to ordinary model output". These fixtures
// are red against the renderer as it stands (`web/src/stream/markdown.tsx`):
// its `blocks()` walk has no nesting, no table, no blockquote, and its
// `inline()` scanner only matches a flat `**bold**|`code`|[link](href)`
// alternation — a nested span, a hard break, or an unmatched `*` all fall
// straight through as literal text. Each case below names the exact defect.
// ---------------------------------------------------------------------------

describe("markdown that holds up to ordinary model output", () => {
  it("keeps nested bullets as one nested list, not a flattened run of paragraphs", () => {
    const document_ = parse(
      renderToStaticMarkup(
        <Markdown text={["- Top A", "  - Nested A1", "  - Nested A2", "- Top B"].join("\n")} />,
      ),
    );
    const topLists = [...document_.body.children].filter((node) => node.tagName === "UL");
    expect(topLists).toHaveLength(1);
    const outer = topLists[0];
    const topItems = outer === undefined ? [] : [...outer.children].filter((node) => node.tagName === "LI");
    expect(topItems).toHaveLength(2);
    expect(topItems.map((li) => li.textContent ?? "")).toEqual(
      expect.arrayContaining([expect.stringContaining("Top A"), expect.stringContaining("Top B")]),
    );
    const nested = outer?.querySelector("ul") ?? null;
    expect(nested).not.toBeNull();
    expect(nested?.textContent ?? "").toContain("Nested A1");
    expect(nested?.textContent ?? "").toContain("Nested A2");
    // The nested items are NOT also top-level <li>s of the outer list.
    expect(topItems.some((li) => (li.textContent ?? "").trim() === "Nested A1")).toBe(false);
  });

  it("renders a level-4 heading (####) as a heading, not a literal paragraph", () => {
    const document_ = parse(renderToStaticMarkup(<Markdown text="#### Detail" />));
    const heading = document_.querySelector("h1, h2, h3, h4, h5, h6");
    expect(heading).not.toBeNull();
    expect(heading?.textContent).toBe("Detail");
    expect(document_.querySelector("p")?.textContent ?? "").not.toContain("####");
  });

  it("renders a pipe table as a <table>", () => {
    const document_ = parse(
      renderToStaticMarkup(
        <Markdown text={["| Part | Qty |", "| --- | --- |", "| bracket | 2 |"].join("\n")} />,
      ),
    );
    const table = document_.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.querySelectorAll("tr").length ?? 0).toBeGreaterThanOrEqual(2);
    expect(table?.textContent ?? "").toContain("Part");
    expect(table?.textContent ?? "").toContain("bracket");
    // The separator row's dashes are structure, not visible text.
    expect(table?.textContent ?? "").not.toContain("---");
  });

  it("renders a blockquote line as <blockquote>", () => {
    const document_ = parse(renderToStaticMarkup(<Markdown text="> Measured twice, cut once." />));
    const quote = document_.querySelector("blockquote");
    expect(quote).not.toBeNull();
    expect(quote?.textContent ?? "").toContain("Measured twice, cut once.");
    expect(document_.querySelector("p")?.textContent ?? "").not.toContain(">");
  });

  it("renders a two-trailing-space hard break as <br>, not a swallowed newline", () => {
    const document_ = parse(renderToStaticMarkup(<Markdown text={"line one  \nline two"} />));
    expect(document_.querySelector("br")).not.toBeNull();
    const p = document_.querySelector("p");
    expect(p?.textContent ?? "").toContain("line one");
    expect(p?.textContent ?? "").toContain("line two");
  });

  it("renders the code span inside bold text, rather than leaving raw backticks", () => {
    const document_ = parse(renderToStaticMarkup(<Markdown text="**bold with `code`**" />));
    const strong = document_.querySelector("strong");
    expect(strong).not.toBeNull();
    const code = strong?.querySelector("code") ?? null;
    expect(code).not.toBeNull();
    expect(code?.textContent).toBe("code");
    expect(document_.body.textContent ?? "").not.toContain("`");
  });

  it("renders ***both*** as bold-and-italic with no stray asterisks left over", () => {
    const document_ = parse(renderToStaticMarkup(<Markdown text="***both***" />));
    expect(document_.body.textContent ?? "").not.toContain("*");
    const emphasized = document_.querySelector("strong, em");
    expect(emphasized).not.toBeNull();
    expect((document_.body.textContent ?? "")).toContain("both");
  });

  it("renders an escaped asterisk literally, without the backslash", () => {
    const document_ = parse(renderToStaticMarkup(<Markdown text={"\\*not bold\\*"} />));
    expect(document_.body.textContent ?? "").toBe("*not bold*");
    expect(document_.body.textContent ?? "").not.toContain("\\");
    expect(document_.querySelector("strong")).toBeNull();
  });

  it("preserves a typed newline as a <br> on an operator row via preserveLineBreaks", () => {
    // §7.3(b)/W4: the operator's own prose keeps a typed line break even
    // though a bare Enter in a textarea carries none of GFM's two-trailing-
    // space hard-break marking. The transcript passes this only on a
    // `user-prompt` row, never on assistant text, so it is an explicit opt in
    // rather than the renderer's default behaviour.
    const document_ = parse(
      renderToStaticMarkup(<Markdown text={"First line\nSecond line"} preserveLineBreaks />),
    );
    expect(document_.querySelectorAll("br").length).toBeGreaterThanOrEqual(1);
    const text = document_.body.textContent ?? "";
    expect(text).toContain("First line");
    expect(text).toContain("Second line");
  });
});
