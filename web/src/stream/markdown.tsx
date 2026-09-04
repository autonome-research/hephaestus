// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The sanitizing markdown renderer for transcript prose (INTERFACE.md §7.3).
//
// §7.3: `text_delta` is "markdown-rendered in the transcript", and "the same
// sanitizing renderer shapes operator prompt echoes and restored `user-prompt`
// rows". Tool-chip JSON is never passed through here. House copy stays in
// `copy.ts`; this module only shapes the model's (and the operator's) own words.
//
// WHY IT IS STILL HAND-ROLLED. A markdown library is also an HTML pipeline:
// every one of them can emit raw HTML, and the ones that will not still ship a
// sanitizer whose *configuration* is the actual boundary. Here the boundary is
// structural rather than configured — every node this file returns is a React
// element it constructed, `dangerouslySetInnerHTML` appears nowhere, and a link
// is a link only when its href survives `safeHref`. Raw HTML in the source is
// never stripped, because it is never parsed: `<script>` is four punctuation
// marks and a word, and it renders as those characters.
//
// WHAT IT UNDERSTANDS (widened 2026-09-03 so ordinary model output survives the
// trip): ATX headings `#`..`######`, paragraphs, fenced and indented code,
// bullet and ordered lists nested by indentation, blockquotes, GFM pipe tables,
// thematic breaks, hard breaks (two trailing spaces, or a trailing backslash),
// `**strong**`, `*emphasis*`, `~~strike~~`, code spans (including inside bold),
// backslash escapes, and http(s) links. What it deliberately does NOT
// understand: raw HTML (above), images (`![alt](src)` renders as its own
// characters rather than fetching a remote byte from a transcript), reference
// links, and setext headings — a model writes `##`, and a renderer that guesses
// at `---` under a line would eat the thematic break that line actually is.
//
// WHITE SPACE, AND THE ONE OPTION. Agent prose follows markdown's rule: a soft
// line break is a space, because a model hard-wraps its own paragraphs and
// honouring those wraps would re-ragged every reply at whatever column the
// model happened to choose. The operator's rows pass `preserveLineBreaks`,
// because a person who pressed Return meant it — their line breaks are content.
// That is the whole difference between the two callers, and it is one flag
// rather than two renderers so the sanitizing half cannot diverge between them.

import { Fragment } from "react";
import type { JSX, ReactNode } from "react";
import roles from "../system/type.module.css";

/** How deep a quote/list nest or an emphasis nest is followed before it is
 *  treated as prose. Model output does not nest eight deep; adversarial input
 *  might, and a recursive descent parser with no floor is a stack overflow
 *  waiting for one pathological reply. */
const MAX_DEPTH = 8;

// ---------------------------------------------------------------------------
// hrefs — the one place a string from the model becomes a navigable thing
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// type roles for prose headings (§3.8)
// ---------------------------------------------------------------------------

/**
 * The three prose-heading roles, keyed by the level this renderer maps to.
 *
 * Exported so the presentation layer can name the same roles a stylesheet
 * composes (`composes: proseH1 from ".../system/type.module.css"`) without
 * re-deriving the mapping. `type.module.css` remains the only file in `web/`
 * that may declare a font-size (§3.8, §3.14); this record only *references*
 * what it declared.
 */
export const MARKDOWN_HEADING_ROLES: {
  readonly 1: string | undefined;
  readonly 2: string | undefined;
  readonly 3: string | undefined;
} = { 1: roles["proseH1"], 2: roles["proseH2"], 3: roles["proseH3"] };

/**
 * Markdown levels 4-6 collapse onto the third role rather than being dropped or
 * shrunk: a `####` is still a heading, and §3.8's ramp has no step below body
 * size to give it (11px belongs to `.eyebrow` and nothing else).
 */
function headingRole(level: 1 | 2 | 3): string | undefined {
  return MARKDOWN_HEADING_ROLES[level];
}

// ---------------------------------------------------------------------------
// inline scanning
// ---------------------------------------------------------------------------

const ASCII_PUNCTUATION = /[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]/;
const ALPHANUMERIC = /[\p{L}\p{N}]/u;

/** The length of the run of `ch` starting at `at`. */
function runLength(text: string, at: number, ch: string): number {
  let n = 0;
  while (text[at + n] === ch) n += 1;
  return n;
}

/** Start of the backtick run of exactly `width` that closes a code span, or -1. */
function findCodeClose(text: string, from: number, width: number): number {
  let i = from;
  while (i < text.length) {
    if (text[i] === "`") {
      const len = runLength(text, i, "`");
      if (len === width) return i;
      i += len;
      continue;
    }
    i += 1;
  }
  return -1;
}

interface DelimiterRun {
  readonly start: number;
  readonly length: number;
}

/**
 * The run that closes an emphasis opened with `need` copies of `ch`.
 *
 * Two rules do the work of CommonMark's delimiter stack without the stack, and
 * between them they get the cases a model actually writes right:
 *
 *  - a run preceded by white space cannot close, so the `**` in `*a **b** c*`
 *    is not mistaken for the `*` that closes the outer emphasis;
 *  - a run of exactly `need` wins over a longer one, so `*a **b** c*` closes on
 *    the final single `*` rather than the first `**` it meets.
 *
 * When only a longer run is available it is consumed from its RIGHT end, which
 * is what makes `***both***` and `**a *b***` nest correctly: the delimiters left
 * over stay inside the content and are parsed as the inner emphasis they are.
 */
function findCloser(
  text: string,
  from: number,
  ch: string,
  need: number,
  intraword: boolean,
): DelimiterRun | null {
  let fallback: DelimiterRun | null = null;
  let i = from;
  while (i < text.length) {
    const c = text[i];
    if (c === "\\") {
      i += 2;
      continue;
    }
    if (c === "`") {
      const len = runLength(text, i, "`");
      const close = findCodeClose(text, i + len, len);
      i = close === -1 ? i + len : close + len;
      continue;
    }
    if (c === ch) {
      const len = runLength(text, i, ch);
      const before = text[i - 1];
      const after = text[i + len];
      const closes =
        before !== undefined &&
        !/\s/.test(before) &&
        (intraword || after === undefined || !ALPHANUMERIC.test(after));
      if (closes && len >= need) {
        if (len === need) return { start: i, length: len };
        fallback ??= { start: i, length: len };
      }
      i += len;
      continue;
    }
    i += 1;
  }
  return fallback;
}

interface Link {
  readonly label: string;
  readonly href: string | null;
  readonly end: number;
}

/** `[label](destination "title")` starting at `[`, or null when it is just a bracket. */
function parseLink(text: string, at: number): Link | null {
  let i = at + 1;
  let depth = 1;
  while (i < text.length && depth > 0) {
    const ch = text[i];
    if (ch === "\\") {
      i += 2;
      continue;
    }
    if (ch === "`") {
      const len = runLength(text, i, "`");
      const close = findCodeClose(text, i + len, len);
      i = close === -1 ? i + len : close + len;
      continue;
    }
    if (ch === "[") depth += 1;
    if (ch === "]") depth -= 1;
    i += 1;
  }
  if (depth !== 0 || text[i] !== "(") return null;
  const label = text.slice(at + 1, i - 1);
  i += 1;
  let destination = "";
  let parens = 1;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "\\") {
      destination += text[i + 1] ?? "";
      i += 2;
      continue;
    }
    if (ch === "(") parens += 1;
    if (ch === ")") {
      parens -= 1;
      if (parens === 0) break;
    }
    destination += ch;
    i += 1;
  }
  if (parens !== 0) return null;
  // A title (`"…"` or `'…'`) is not rendered, but it must not end up in the
  // href — the destination is everything before the first unquoted space.
  const bare = destination.trim().replace(/^<(.*)>$/, "$1");
  const space = bare.search(/\s/);
  const target = space === -1 ? bare : bare.slice(0, space);
  return { label, href: safeHref(target), end: i + 1 };
}

/**
 * Source text to React nodes.
 *
 * `hardWrap` is `preserveLineBreaks`: with it a soft line break renders as a
 * `<br>` rather than the space markdown says it is. A break the author marked
 * explicitly — two trailing spaces, or a trailing backslash — is a `<br>` under
 * both settings, because that is what the marks mean.
 */
function inlineNodes(source: string, hardWrap: boolean, depth: number): ReactNode[] {
  const out: ReactNode[] = [];
  let buffer = "";
  let serial = 0;
  const key = (): string => `i${(serial += 1)}`;
  const flush = (): void => {
    if (buffer !== "") {
      out.push(buffer);
      buffer = "";
    }
  };
  const emit = (node: ReactNode): void => {
    flush();
    out.push(node);
  };

  let i = 0;
  while (i < source.length) {
    const ch = source[i] ?? "";

    if (ch === "\\") {
      const next = source[i + 1];
      if (next === "\n") {
        // A trailing backslash is a hard break under both white-space policies.
        emit(<br key={key()} />);
        i += 2;
        while (source[i] === " ") i += 1;
        continue;
      }
      if (next !== undefined && ASCII_PUNCTUATION.test(next)) {
        buffer += next;
        i += 2;
        continue;
      }
      buffer += ch;
      i += 1;
      continue;
    }

    if (ch === "\n") {
      const trimmed = buffer.replace(/ +$/, "");
      const marked = buffer.length - trimmed.length >= 2;
      buffer = trimmed;
      if (marked || hardWrap) emit(<br key={key()} />);
      else buffer += " ";
      i += 1;
      while (source[i] === " ") i += 1;
      continue;
    }

    if (ch === "`") {
      const width = runLength(source, i, "`");
      const close = findCodeClose(source, i + width, width);
      if (close !== -1) {
        // A code span is a single line of code: its own newlines are spaces,
        // and one padding space on each side is the fence, not content.
        let content = source.slice(i + width, close).replace(/\n/g, " ");
        if (content.length > 1 && content.startsWith(" ") && content.endsWith(" ")) {
          content = content.slice(1, -1);
        }
        emit(<code key={key()}>{content}</code>);
        i = close + width;
        continue;
      }
      buffer += "`".repeat(width);
      i += width;
      continue;
    }

    // `![alt](src)` is left as its own characters: a transcript that fetched a
    // remote byte because a model wrote a URL would be a different privacy
    // claim than the one §7.3 makes for `image` events.
    if (ch === "[" && !buffer.endsWith("!")) {
      const link = parseLink(source, i);
      if (link !== null && link.href !== null) {
        emit(
          <a key={key()} href={link.href} target="_blank" rel="noopener noreferrer">
            {inlineNodes(link.label, hardWrap, depth + 1)}
          </a>,
        );
        i = link.end;
        continue;
      }
      buffer += ch;
      i += 1;
      continue;
    }

    if ((ch === "*" || ch === "_" || ch === "~") && depth < MAX_DEPTH) {
      const run = runLength(source, i, ch);
      const need = ch === "~" ? 2 : Math.min(run, 3);
      const after = source[i + run];
      const before = source[i - 1];
      const opens =
        run >= need &&
        after !== undefined &&
        !/\s/.test(after) &&
        // `snake_case_name` is one word, not three emphasised fragments. The
        // asymmetry is markdown's own: `_` is intraword-inert, `*` is not.
        (ch !== "_" || before === undefined || !ALPHANUMERIC.test(before));
      if (opens) {
        const closer = findCloser(source, i + run, ch, need, ch !== "_");
        if (closer !== null) {
          const content = source.slice(i + run, closer.start + closer.length - need);
          const inner = inlineNodes(content, hardWrap, depth + 1);
          if (ch === "~") emit(<del key={key()}>{inner}</del>);
          else if (need === 3)
            emit(
              <em key={key()}>
                <strong>{inner}</strong>
              </em>,
            );
          else if (need === 2) emit(<strong key={key()}>{inner}</strong>);
          else emit(<em key={key()}>{inner}</em>);
          i = closer.start + closer.length;
          continue;
        }
      }
      buffer += ch.repeat(run);
      i += run;
      continue;
    }

    buffer += ch;
    i += 1;
  }
  flush();
  return out;
}

// ---------------------------------------------------------------------------
// block parsing
// ---------------------------------------------------------------------------

type Align = "left" | "center" | "right";

type Block =
  | { readonly kind: "heading"; readonly level: number; readonly text: string }
  | { readonly kind: "paragraph"; readonly text: string }
  | { readonly kind: "code"; readonly lang: string; readonly text: string }
  | {
      readonly kind: "list";
      readonly ordered: boolean;
      readonly start: number;
      readonly items: readonly (readonly Block[])[];
    }
  | { readonly kind: "quote"; readonly blocks: readonly Block[] }
  | {
      readonly kind: "table";
      readonly head: readonly string[];
      readonly align: readonly (Align | null)[];
      readonly rows: readonly (readonly string[])[];
    }
  | { readonly kind: "rule" };

const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^`]*)$/;
const ATX = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$/;
const THEMATIC = /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/;
const QUOTE = /^ {0,3}>[ \t]?(.*)$/;
const BULLET = /^( {0,3})([-*+])(?:( +)(.*)| *$)/;
const ORDERED = /^( {0,3})(\d{1,9})[.)](?:( +)(.*)| *$)/;
const INDENTED = /^ {4}/;
const TABLE_DELIMITER = /^ *\|? *:?-+:? *(?:\| *:?-+:? *)*\|? *$/;
const RULER = /^:?-+:?$/;

function leadingWidth(line: string): number {
  return (/^ */.exec(line)?.[0] ?? "").length;
}

function isBlockStart(line: string): boolean {
  return (
    FENCE.test(line) || ATX.test(line) || THEMATIC.test(line) || QUOTE.test(line)
  );
}

interface ItemStart {
  readonly contentIndent: number;
  readonly rest: string;
  readonly ordered: boolean;
  readonly number: number;
}

/** A list-item marker at the head of `line`, with the column its content starts in. */
function matchItem(line: string): ItemStart | null {
  if (THEMATIC.test(line)) return null;
  const bullet = BULLET.exec(line);
  if (bullet !== null) {
    const indent = (bullet[1] ?? "").length;
    const spaces = bullet[3] === undefined ? 1 : Math.min(bullet[3].length, 4);
    return { contentIndent: indent + 1 + spaces, rest: bullet[4] ?? "", ordered: false, number: 1 };
  }
  const ordered = ORDERED.exec(line);
  if (ordered !== null) {
    const indent = (ordered[1] ?? "").length;
    const digits = (ordered[2] ?? "1").length;
    const spaces = ordered[3] === undefined ? 1 : Math.min(ordered[3].length, 4);
    return {
      contentIndent: indent + digits + 1 + spaces,
      rest: ordered[4] ?? "",
      ordered: true,
      number: Number.parseInt(ordered[2] ?? "1", 10),
    };
  }
  return null;
}

/** The cells of one pipe-table row, with `\|` kept out of the split. */
function splitRow(line: string): string[] {
  let inner = line.trim();
  if (inner.startsWith("|")) inner = inner.slice(1);
  if (inner.endsWith("|") && !inner.endsWith("\\|")) inner = inner.slice(0, -1);
  const cells: string[] = [];
  let cell = "";
  for (let i = 0; i < inner.length; i += 1) {
    const ch = inner[i];
    if (ch === "\\" && inner[i + 1] === "|") {
      cell += "|";
      i += 1;
      continue;
    }
    if (ch === "|") {
      cells.push(cell.trim());
      cell = "";
      continue;
    }
    cell += ch ?? "";
  }
  cells.push(cell.trim());
  return cells;
}

function cellAlign(spec: string): Align | null {
  const left = spec.startsWith(":");
  const right = spec.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  if (left) return "left";
  return null;
}

interface Scan {
  readonly block: Block;
  readonly next: number;
}

/** A GFM pipe table headed at `from`, or null. */
function tableAt(lines: readonly string[], from: number): Scan | null {
  const header = lines[from] ?? "";
  const delimiter = lines[from + 1];
  if (delimiter === undefined || !header.includes("|")) return null;
  if (!TABLE_DELIMITER.test(delimiter) || !delimiter.includes("-")) return null;
  const head = splitRow(header);
  const spec = splitRow(delimiter);
  if (spec.length !== head.length || head.length === 0) return null;
  if (!spec.every((cell) => RULER.test(cell))) return null;
  const rows: string[][] = [];
  let i = from + 2;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (line.trim() === "" || !line.includes("|") || isBlockStart(line)) break;
    const cells = splitRow(line);
    while (cells.length < head.length) cells.push("");
    rows.push(cells.slice(0, head.length));
    i += 1;
  }
  return {
    block: { kind: "table", head, align: spec.map(cellAlign), rows },
    next: i,
  };
}

/** A blockquote starting at `from`; its body is parsed as blocks in its own right. */
function quoteAt(lines: readonly string[], from: number, depth: number): Scan {
  const body: string[] = [];
  let i = from;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    const marked = QUOTE.exec(line);
    if (marked !== null) {
      body.push(marked[1] ?? "");
      i += 1;
      continue;
    }
    // Lazy continuation: an unmarked line still belongs to the quote's
    // paragraph, which is how a model's wrapped quote survives.
    if (line.trim() === "" || isBlockStart(line) || matchItem(line) !== null) break;
    body.push(line.trim());
    i += 1;
  }
  return { block: { kind: "quote", blocks: parseBlocks(body, depth + 1) }, next: i };
}

/**
 * A list starting at `from`.
 *
 * Nesting is by indentation and nothing else: an item's continuation lines are
 * the ones indented to its content column, they are dedented by exactly that
 * column, and the result is parsed as blocks again. A nested list, a fenced
 * block inside an item and a paragraph under a bullet all fall out of that one
 * rule rather than each needing a case.
 */
function listAt(lines: readonly string[], from: number, depth: number): Scan | null {
  const first = matchItem(lines[from] ?? "");
  if (first === null) return null;
  const ordered = first.ordered;
  const items: Block[][] = [];
  let i = from;
  while (i < lines.length) {
    const start = matchItem(lines[i] ?? "");
    if (start === null || start.ordered !== ordered) break;
    const body: string[] = [start.rest];
    i += 1;
    let blanks = 0;
    while (i < lines.length) {
      const line = lines[i] ?? "";
      if (line.trim() === "") {
        blanks += 1;
        i += 1;
        continue;
      }
      if (leadingWidth(line) >= start.contentIndent) {
        for (let b = 0; b < blanks; b += 1) body.push("");
        blanks = 0;
        body.push(line.slice(start.contentIndent));
        i += 1;
        continue;
      }
      if (blanks > 0 || isBlockStart(line) || matchItem(line) !== null) break;
      body.push(line.trim());
      i += 1;
    }
    items.push(parseBlocks(body, depth + 1));
    if (blanks > 0) {
      const next = i < lines.length ? matchItem(lines[i] ?? "") : null;
      if (next === null || next.ordered !== ordered) break;
    }
  }
  if (items.length === 0) return null;
  return { block: { kind: "list", ordered, start: first.number, items }, next: i };
}

function parseBlocks(lines: readonly string[], depth: number): Block[] {
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (line.trim() === "") {
      i += 1;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence !== null) {
      const opener = fence[1] ?? "```";
      const closer = new RegExp(`^ {0,3}[${opener[0] ?? "`"}]{${opener.length},} *$`);
      const body: string[] = [];
      i += 1;
      while (i < lines.length) {
        const candidate = lines[i] ?? "";
        i += 1;
        if (closer.test(candidate)) break;
        body.push(candidate);
      }
      out.push({ kind: "code", lang: (fence[2] ?? "").trim(), text: body.join("\n") });
      continue;
    }

    const heading = ATX.exec(line);
    if (heading !== null) {
      out.push({
        kind: "heading",
        level: (heading[1] ?? "#").length,
        // A closing run of hashes is decoration, not content.
        text: (heading[2] ?? "").replace(/[ \t]+#+$/, ""),
      });
      i += 1;
      continue;
    }

    if (THEMATIC.test(line)) {
      out.push({ kind: "rule" });
      i += 1;
      continue;
    }

    if (QUOTE.test(line) && depth < MAX_DEPTH) {
      const quote = quoteAt(lines, i, depth);
      out.push(quote.block);
      i = quote.next;
      continue;
    }

    const table = tableAt(lines, i);
    if (table !== null) {
      out.push(table.block);
      i = table.next;
      continue;
    }

    if (matchItem(line) !== null && depth < MAX_DEPTH) {
      const list = listAt(lines, i, depth);
      if (list !== null) {
        out.push(list.block);
        i = list.next;
        continue;
      }
    }

    // An indented chunk is code only at the head of a block — it may not
    // interrupt a paragraph, which is why this test lives here and not in the
    // continuation loop below.
    if (INDENTED.test(line)) {
      const body: string[] = [];
      while (i < lines.length) {
        const candidate = lines[i] ?? "";
        if (candidate.trim() === "") {
          let j = i + 1;
          while (j < lines.length && (lines[j] ?? "").trim() === "") j += 1;
          if (j >= lines.length || !INDENTED.test(lines[j] ?? "")) break;
          for (let b = i; b < j; b += 1) body.push("");
          i = j;
          continue;
        }
        if (!INDENTED.test(candidate)) break;
        body.push(candidate.slice(4));
        i += 1;
      }
      out.push({ kind: "code", lang: "", text: body.join("\n") });
      continue;
    }

    const paragraph: string[] = [line.replace(/^ +/, "")];
    i += 1;
    while (i < lines.length) {
      const next = lines[i] ?? "";
      if (
        next.trim() === "" ||
        isBlockStart(next) ||
        matchItem(next) !== null ||
        tableAt(lines, i) !== null
      ) {
        break;
      }
      paragraph.push(next.replace(/^ +/, ""));
      i += 1;
    }
    out.push({ kind: "paragraph", text: paragraph.join("\n") });
  }
  return out;
}

// ---------------------------------------------------------------------------
// rendering
// ---------------------------------------------------------------------------

function alignAttribute(align: Align | null | undefined): { readonly "data-align"?: Align } {
  return align === null || align === undefined ? {} : { "data-align": align };
}

/**
 * One list item's blocks.
 *
 * A leading paragraph renders as bare inline content rather than a `<p>`: a
 * tight list is the common case, and wrapping every bullet in a paragraph is
 * how a four-item list acquires four paragraph gaps. Anything after it — a
 * nested list, a fenced block, a second paragraph — renders as the block it is.
 */
function renderItem(blocks: readonly Block[], hardWrap: boolean, prefix: string): ReactNode[] {
  const [head, ...rest] = blocks;
  if (head === undefined) return [];
  if (head.kind === "paragraph") {
    return [
      <Fragment key={`${prefix}t`}>{inlineNodes(head.text, hardWrap, 0)}</Fragment>,
      ...renderBlocks(rest, hardWrap, `${prefix}r`),
    ];
  }
  return renderBlocks(blocks, hardWrap, `${prefix}b`);
}

function renderBlock(block: Block, hardWrap: boolean, key: string): ReactNode {
  switch (block.kind) {
    case "heading": {
      // Levels beyond three are never dropped; they map onto the smallest
      // prose-heading role. The source level rides along on `data-md-level` so
      // the collapse is visible to a test rather than inferred from a tag name.
      const level = (block.level > 3 ? 3 : block.level) as 1 | 2 | 3;
      const Tag = level === 1 ? "h3" : level === 2 ? "h4" : "h5";
      return (
        <Tag key={key} className={headingRole(level)} data-md-level={String(block.level)}>
          {inlineNodes(block.text, hardWrap, 0)}
        </Tag>
      );
    }
    case "paragraph":
      return <p key={key}>{inlineNodes(block.text, hardWrap, 0)}</p>;
    case "code":
      return (
        <pre key={key}>
          <code {...(block.lang === "" ? {} : { "data-lang": block.lang })}>{block.text}</code>
        </pre>
      );
    case "rule":
      return <hr key={key} />;
    case "quote":
      return (
        <blockquote key={key}>{renderBlocks(block.blocks, hardWrap, `${key}q`)}</blockquote>
      );
    case "list": {
      const children = block.items.map((item, index) => (
        <li key={index}>{renderItem(item, hardWrap, `${key}i${index}`)}</li>
      ));
      return block.ordered ? (
        <ol key={key} {...(block.start === 1 ? {} : { start: block.start })}>
          {children}
        </ol>
      ) : (
        <ul key={key}>{children}</ul>
      );
    }
    case "table":
      return (
        <table key={key}>
          <thead>
            <tr>
              {block.head.map((cell, column) => (
                <th key={column} scope="col" {...alignAttribute(block.align[column])}>
                  {inlineNodes(cell, hardWrap, 0)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, index) => (
              <tr key={index}>
                {row.map((cell, column) => (
                  <td key={column} {...alignAttribute(block.align[column])}>
                    {inlineNodes(cell, hardWrap, 0)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
  }
}

function renderBlocks(blocks: readonly Block[], hardWrap: boolean, prefix: string): ReactNode[] {
  return blocks.map((block, index) => renderBlock(block, hardWrap, `${prefix}${index}`));
}

/** How a caller asks for the operator's white-space policy instead of the model's. */
export interface MarkdownOptions {
  /**
   * Keep a typed line break as a line break (§7.3's operator rows). Off by
   * default, which is markdown's own rule and the right one for model prose.
   */
  readonly preserveLineBreaks?: boolean;
}

/** Render markdown source as sanitised React nodes. */
export function renderMarkdown(source: string, options: MarkdownOptions = {}): ReactNode {
  if (source === "") return null;
  // Tabs become four columns before anything measures an indent, so "nested by
  // indentation" means one thing rather than two.
  const lines = source.replace(/\r\n?/g, "\n").replace(/\t/g, "    ").split("\n");
  const parsed = parseBlocks(lines, 0);
  if (parsed.length === 0) return null;
  return renderBlocks(parsed, options.preserveLineBreaks === true, "m");
}

export function Markdown({
  text,
  preserveLineBreaks = false,
}: {
  readonly text: string;
  readonly preserveLineBreaks?: boolean;
}): JSX.Element {
  return <>{renderMarkdown(text, { preserveLineBreaks })}</>;
}
