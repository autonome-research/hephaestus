// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A small sanitizing markdown renderer for transcript prose (INTERFACE.md §7.3).
//
// Assistant and operator turns carry headings, lists, code fences, bold, and
// links. Tool-chip JSON is not passed through here. The renderer never emits
// raw HTML: every node is a React element, and link hrefs are restricted to
// http(s). House copy stays in `copy.ts`; this module only shapes the model's
// (and the operator's) own words.

import type { ReactNode, JSX } from "react";

const SAFE_HREF = /^(https?:)\/\//i;

function safeHref(raw: string): string | null {
  const href = raw.trim();
  if (!SAFE_HREF.test(href)) return null;
  try {
    const url = new URL(href);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.href;
  } catch {
    return null;
  }
}

function inline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+?\*\*|`[^`]+?`|\[[^\]]+?\]\([^)]+?\))/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={`b${key}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      nodes.push(<code key={`c${key}`}>{token.slice(1, -1)}</code>);
    } else {
      const link = /^\[([^\]]+?)\]\(([^)]+?)\)$/.exec(token);
      const href = link === null ? null : safeHref(link[2] ?? "");
      if (link !== null && href !== null) {
        nodes.push(
          <a key={`a${key}`} href={href} target="_blank" rel="noopener noreferrer">
            {link[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }
    key += 1;
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

interface Block {
  readonly type: "heading" | "p" | "ul" | "ol" | "pre";
  readonly level?: number;
  readonly lang?: string;
  readonly lines: string[];
}

function blocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !(lines[i] ?? "").startsWith("```")) {
        body.push(lines[i] ?? "");
        i += 1;
      }
      if (i < lines.length) i += 1;
      out.push({ type: "pre", lang, lines: body });
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading !== null) {
      out.push({ type: "heading", level: heading[1]?.length ?? 1, lines: [heading[2] ?? ""] });
      i += 1;
      continue;
    }
    const unordered = /^[-*]\s+(.+)$/.exec(line);
    if (unordered !== null) {
      const items: string[] = [unordered[1] ?? ""];
      i += 1;
      while (i < lines.length) {
        const next = /^[-*]\s+(.+)$/.exec(lines[i] ?? "");
        if (next === null) break;
        items.push(next[1] ?? "");
        i += 1;
      }
      out.push({ type: "ul", lines: items });
      continue;
    }
    const ordered = /^\d+\.\s+(.+)$/.exec(line);
    if (ordered !== null) {
      const items: string[] = [ordered[1] ?? ""];
      i += 1;
      while (i < lines.length) {
        const next = /^\d+\.\s+(.+)$/.exec(lines[i] ?? "");
        if (next === null) break;
        items.push(next[1] ?? "");
        i += 1;
      }
      out.push({ type: "ol", lines: items });
      continue;
    }
    if (line.trim() === "") {
      i += 1;
      continue;
    }
    const para: string[] = [line];
    i += 1;
    while (i < lines.length) {
      const next = lines[i] ?? "";
      if (
        next.trim() === "" ||
        next.startsWith("```") ||
        /^#{1,3}\s+/.test(next) ||
        /^[-*]\s+/.test(next) ||
        /^\d+\.\s+/.test(next)
      ) {
        break;
      }
      para.push(next);
      i += 1;
    }
    out.push({ type: "p", lines: para });
  }
  return out;
}

/** Render markdown source as sanitised React nodes. */
export function renderMarkdown(source: string): ReactNode {
  if (source === "") return null;
  const parsed = blocks(source);
  if (parsed.length === 0) return null;
  return parsed.map((block, index) => {
    if (block.type === "heading") {
      const Tag = block.level === 1 ? "h3" : block.level === 2 ? "h4" : "h5";
      return <Tag key={index}>{inline(block.lines[0] ?? "")}</Tag>;
    }
    if (block.type === "pre") {
      return (
        <pre key={index}>
          <code>{block.lines.join("\n")}</code>
        </pre>
      );
    }
    if (block.type === "ul") {
      return (
        <ul key={index}>
          {block.lines.map((item, itemIndex) => (
            <li key={itemIndex}>{inline(item)}</li>
          ))}
        </ul>
      );
    }
    if (block.type === "ol") {
      return (
        <ol key={index}>
          {block.lines.map((item, itemIndex) => (
            <li key={itemIndex}>{inline(item)}</li>
          ))}
        </ol>
      );
    }
    return <p key={index}>{inline(block.lines.join("\n"))}</p>;
  });
}

export function Markdown({ text }: { readonly text: string }): JSX.Element {
  return <>{renderMarkdown(text)}</>;
}
