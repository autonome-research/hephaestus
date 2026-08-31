// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * §3.14's four checks, on the `no-derived-fact` precedent.
 *
 * "§1 made the client boundary a lint rule rather than a promise. The same move
 * applies here; without it this section is a mood board with hex codes."
 *
 *   no-palette-token    hue spent ad hoc — the reason `.chip` and `.state`
 *                       diverged into five bordered pills with five borders
 *   no-raw-type         the 65-of-91 collapse to 11px
 *   system-owns-status  `ChecksPanel.tsx`:59 — an attribute one element away
 *                       from its selector, silently
 *   token-contrast      §3.13.1 being prose. This is the check that catches a
 *                       `--border-control` at 1.85:1, which is how that defect
 *                       reached a spec draft in the first place.
 *
 * The rules run on `.css` files through `css-parser.js` (an empty `Program`, so
 * the four read `sourceCode.text` directly) and on `.tsx` files through ordinary
 * AST visitors. No dependency is added — §3.2's rejections all survive, and a
 * lint dependency is a dependency.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, sep } from "node:path";

// ---------------------------------------------------------------------------
// shared helpers
// ---------------------------------------------------------------------------

/** Blank out `/* … *\/` comments, preserving offsets so `loc`s stay exact. */
function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, " "));
}

/** A `{line, column}` for a character offset, 1-based line / 0-based column. */
function locAt(text, offset) {
  let line = 1;
  let lineStart = 0;
  for (let i = 0; i < offset; i += 1) {
    if (text[i] === "\n") {
      line += 1;
      lineStart = i + 1;
    }
  }
  return { line, column: offset - lineStart };
}

/** Report at a text offset, with a one-character span. */
function reportAt(context, text, offset, messageId, data) {
  const start = locAt(text, offset);
  context.report({ loc: { start, end: { line: start.line, column: start.column + 1 } }, messageId, data });
}

/** Normalised, `/`-separated path so the exemptions read the same on any OS. */
function posix(filename) {
  return filename.split(sep).join("/");
}

function isCss(filename) {
  return filename.endsWith(".css");
}

// ---------------------------------------------------------------------------
// 1. no-palette-token
// ---------------------------------------------------------------------------

/** `#abc`, `#abcd`, `#aabbcc`, `#aabbccdd` — and nothing else that starts `#`. */
const HEX = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;
const PALETTE_VAR = /--p-[a-zA-Z0-9-]+/g;

const TOKENS_FILE = "src/system/tokens.css";

export const noPaletteToken = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Raw hue lives in the private palette layer of system/tokens.css and nowhere else (INTERFACE.md §3.6, §3.14).",
    },
    schema: [],
    messages: {
      paletteVar:
        "`{{name}}` is a LAYER 1 palette token and is private to system/tokens.css (§3.6). Reference a semantic token — a component that spends hue directly is how `.chip` and `.state` diverged.",
      literalHex:
        "`{{hex}}` is a literal colour. Every colour in this workspace is a semantic token (§3.6, §3.9); a hex here is a decision nobody can find again.",
    },
  },
  create(context) {
    const filename = posix(context.filename);
    // The palette's own home, and the only file permitted to hold raw hue.
    if (filename.endsWith(TOKENS_FILE)) return {};
    // `type.module.css` is the type layer's owner (§3.8) and the declared
    // consumer of the five private `--p-size-*` steps. Hue stays forbidden
    // here like everywhere else; only the size steps are its to spend.
    const typeOwner = filename.endsWith(TYPE_FILE);

    if (isCss(filename)) {
      return {
        Program() {
          const raw = context.sourceCode.text;
          const text = stripComments(raw);
          for (const match of text.matchAll(PALETTE_VAR)) {
            if (typeOwner && match[0].startsWith("--p-size-")) continue;
            reportAt(context, raw, match.index, "paletteVar", { name: match[0] });
          }
          for (const match of text.matchAll(HEX)) {
            reportAt(context, raw, match.index, "literalHex", { hex: match[0] });
          }
        },
      };
    }

    // In TS/TSX only *string literals* are inspected. Scanning the raw text
    // would flag the hex values quoted in this file's own documentation, and a
    // check that cannot survive being written about is not a check.
    const check = (node, value) => {
      if (typeof value !== "string") return;
      const hex = value.match(HEX);
      if (hex !== null && hex[0] !== undefined) {
        context.report({ node, messageId: "literalHex", data: { hex: hex[0] } });
        return;
      }
      const palette = value.match(PALETTE_VAR);
      if (palette !== null && palette[0] !== undefined) {
        context.report({ node, messageId: "paletteVar", data: { name: palette[0] } });
      }
    };
    return {
      Literal(node) {
        check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.cooked);
      },
    };
  },
};

// ---------------------------------------------------------------------------
// 2. no-raw-type
// ---------------------------------------------------------------------------

const TYPE_PROPERTIES = ["font-size", "font-weight", "letter-spacing", "text-transform", "font-family"];
/** The shorthand sets `font-size` and `font-family` at once, so it is included. */
const TYPE_DECLARATION = new RegExp(
  `(^|[;{\\s])(${[...TYPE_PROPERTIES, "font"].join("|")})\\s*:`,
  "g",
);
const TYPE_STYLE_PROPS = new Set([
  "fontSize",
  "fontWeight",
  "letterSpacing",
  "textTransform",
  "fontFamily",
  "font",
]);

const TYPE_FILE = "src/system/type.module.css";

export const noRawType = {
  meta: {
    type: "problem",
    docs: {
      description:
        "The seven type roles of system/type.module.css are the only type declarations in web/ (INTERFACE.md §3.8, §3.14).",
    },
    schema: [],
    messages: {
      rawType:
        "`{{property}}` may be declared only in system/type.module.css (§3.8). Compose a type role instead — `.display .title .body .label .data .code .eyebrow` — which is what turns 91 declarations at five sizes into a ramp with a shape.",
      elevenPx:
        "11px may appear only inside `.eyebrow` (§3.8's TIGHTENING). This is the one rule that keeps the shipped 65-of-91-at-11px collapse from coming back.",
      inlineType:
        "`style={{ {{property}} }}` is a type declaration outside system/type.module.css (§3.8). Compose a type role.",
    },
  },
  create(context) {
    const filename = posix(context.filename);

    if (isCss(filename)) {
      if (filename.endsWith(TYPE_FILE)) {
        // The owner still answers to the 11px tightening: exactly one `11px`,
        // and it must be inside `.eyebrow`.
        return {
          Program() {
            const raw = context.sourceCode.text;
            const text = stripComments(raw);
            const eyebrow = text.indexOf(".eyebrow");
            for (const match of text.matchAll(/\b11px\b/g)) {
              const inEyebrow =
                eyebrow !== -1 &&
                match.index > eyebrow &&
                match.index < (text.indexOf("}", eyebrow) === -1 ? text.length : text.indexOf("}", eyebrow));
              if (!inEyebrow) reportAt(context, raw, match.index, "elevenPx");
            }
          },
        };
      }
      return {
        Program() {
          const raw = context.sourceCode.text;
          const text = stripComments(raw);
          for (const match of text.matchAll(TYPE_DECLARATION)) {
            reportAt(context, raw, match.index, "rawType", { property: match[2] });
          }
          // `tokens.css` DECLARES the private `--p-size-xs: 11px` step; it does
          // not spend it. Scanning the declaration would make the palette layer
          // fail the rule whose whole subject is what the other layers do.
          if (filename.endsWith(TOKENS_FILE)) return;
          for (const match of text.matchAll(/\b11px\b/g)) {
            reportAt(context, raw, match.index, "elevenPx");
          }
        },
      };
    }

    return {
      JSXAttribute(node) {
        if (node.name.type !== "JSXIdentifier" || node.name.name !== "style") return;
        const value = node.value;
        if (!value || value.type !== "JSXExpressionContainer") return;
        const expression = value.expression;
        if (expression.type !== "ObjectExpression") return;
        for (const property of expression.properties) {
          if (property.type !== "Property") continue;
          const key = property.key;
          const name = key.type === "Identifier" ? key.name : key.type === "Literal" ? key.value : null;
          if (typeof name === "string" && TYPE_STYLE_PROPS.has(name)) {
            context.report({ node: property, messageId: "inlineType", data: { property: name } });
          }
        }
      },
    };
  },
};

// ---------------------------------------------------------------------------
// 3. system-owns-status
// ---------------------------------------------------------------------------

const STATUS_ATTRIBUTES = ["data-badge", "data-severity", "data-chip-status"];

/** Does any `.css` beside this file select `[<attribute>`? */
function declaredInDirectory(filename, attribute) {
  const directory = dirname(filename);
  let entries;
  try {
    entries = readdirSync(directory);
  } catch {
    return false;
  }
  for (const entry of entries) {
    if (!entry.endsWith(".css")) continue;
    try {
      if (readFileSync(join(directory, entry), "utf8").includes(`[${attribute}`)) return true;
    } catch {
      // A file that cannot be read is not a declaration.
    }
  }
  return false;
}

export const systemOwnsStatus = {
  meta: {
    type: "problem",
    docs: {
      description:
        "A status attribute and the CSS that styles it live in the same directory (INTERFACE.md §3.4, §3.14).",
    },
    schema: [],
    messages: {
      orphaned:
        "`{{attribute}}` is written here but no stylesheet in this directory selects it. This is the shipped P0 exactly: `ChecksPanel.tsx`:59 put `data-badge` on the `<li>` while the CSS selected it one element down, so `pass`, `fail` and `error` computed identically. Render a `<Badge>` from `src/system/` — the primitive owns both halves (§3.4).",
    },
  },
  create(context) {
    const filename = posix(context.filename);
    if (isCss(filename)) return {};
    return {
      JSXAttribute(node) {
        if (node.name.type !== "JSXIdentifier") return;
        const attribute = node.name.name;
        if (!STATUS_ATTRIBUTES.includes(attribute)) return;
        if (declaredInDirectory(context.filename, attribute)) return;
        context.report({ node, messageId: "orphaned", data: { attribute } });
      },
    };
  },
};

// ---------------------------------------------------------------------------
// 4. token-contrast
// ---------------------------------------------------------------------------

/** WCAG relative luminance of an `#rrggbb`. */
function luminance(hex) {
  const value = hex.slice(1);
  const channel = (i) => {
    const c = parseInt(value.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * §3.14's floors. `seam` is measured and reported; see tokens.css for why.
 *
 * `part` is a NAMED EXTENSION added 2026-08-28 with plan item 6 (viewport
 * display authorship). §3.11.2 writes a floor out in full — "≥ 4.5:1 part vs
 * ground, exporter-independent" — for a thing that carries no words, and none
 * of the four original classes states that: `ui` is 3.0 and would under-state
 * a number the spec sets, `text` is the right number under the wrong name.
 * Adding a key weakens nothing; the four existing classes and their floors are
 * untouched, and `test/system/checks.test.ts` covers the new one on both sides.
 */
const FLOORS = { text: 4.5, part: 4.5, ui: 3.0, mark: 3.0, seam: 0 };

/** Every `--name: value;` in the file, with `var(--x)` chased to a hex. */
function readDeclarations(text) {
  const declarations = new Map();
  for (const match of text.matchAll(/(--[a-zA-Z0-9-]+)\s*:\s*([^;]+);/g)) {
    const name = match[1];
    const value = match[2];
    if (name !== undefined && value !== undefined) declarations.set(name, value.trim());
  }
  return declarations;
}

/** Resolve a token to `#rrggbb`, following one chain of `var()` indirections. */
function resolve(declarations, name, depth = 0) {
  if (depth > 8) return null;
  const value = declarations.get(name);
  if (value === undefined) return null;
  const direct = /^#([0-9a-fA-F]{6})$/.exec(value);
  if (direct !== null) return value.toLowerCase();
  const indirect = /^var\((--[a-zA-Z0-9-]+)\)$/.exec(value);
  if (indirect !== null && indirect[1] !== undefined) {
    return resolve(declarations, indirect[1], depth + 1);
  }
  return null;
}

/** A surface word from an `@permit` line → the token it names. */
function backdropToken(word) {
  if (word.startsWith("status-")) return `--${word}`;
  if (word === "accent" || word === "accent-quiet") return `--${word}`;
  // The modeling well is not `--surface-canvas` (that rung stays the dark
  // chrome-adjacent fill). Part/edge/grid contrast is against the well.
  if (word === "viewport-ground") return "--viewport-ground";
  return `--surface-${word}`;
}

export const tokenContrast = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Every declared role × permitted-surface pairing meets its §3.9 floor (INTERFACE.md §3.13.1, §3.14).",
    },
    schema: [],
    messages: {
      unresolved: "`{{token}}` does not resolve to a hex value, so its contrast cannot be measured.",
      belowFloor:
        "{{token}} on {{surface}} measures {{ratio}}:1, below the {{klass}} floor of {{floor}}:1 (§3.13.1). This is the check that catches a --border-control at 1.85:1.",
      refusedPairing:
        "{{token}} is permitted on {{surface}} by an @permit line, but an @refuse line forbids that pairing (§3.9).",
      refusedText:
        "{{token}} is declared not-a-text-token by @refuse-text, but an @permit text line assigns it as text (§3.9). --ink-faint is for a separator glyph and a decorative rule: no prose, no unit column, no disabled-control label.",
      noTable: "system/tokens.css declares no @permit lines: §3.9's permission table is the normative artefact and this check has nothing to read.",
    },
  },
  create(context) {
    const filename = posix(context.filename);
    if (!filename.endsWith(TOKENS_FILE)) return {};
    return {
      Program() {
        const raw = context.sourceCode.text;
        const declarations = readDeclarations(stripComments(raw));

        const permits = [];
        for (const match of raw.matchAll(/@permit\s+(\w+)\s+(--[\w-]+)\s*:\s*([^\n*]+)/g)) {
          const [, klass, token, surfaces] = match;
          if (klass === undefined || token === undefined || surfaces === undefined) continue;
          permits.push({
            klass,
            token,
            surfaces: surfaces.trim().split(/\s+/).filter(Boolean),
            offset: match.index,
          });
        }
        const refusals = [];
        for (const match of raw.matchAll(/@refuse\s+(--[\w-]+)\s*:\s*([^\n*]+)/g)) {
          const [, token, surfaces] = match;
          if (token === undefined || surfaces === undefined) continue;
          for (const surface of surfaces.trim().split(/\s+/).filter(Boolean)) {
            refusals.push({ token, surface, offset: match.index });
          }
        }
        const textRefusals = new Set();
        for (const match of raw.matchAll(/@refuse-text\s+(--[\w-]+)/g)) {
          if (match[1] !== undefined) textRefusals.add(match[1]);
        }

        if (permits.length === 0) {
          reportAt(context, raw, 0, "noTable");
          return;
        }

        for (const permit of permits) {
          if (permit.klass === "text" && textRefusals.has(permit.token)) {
            reportAt(context, raw, permit.offset, "refusedText", { token: permit.token });
            continue;
          }
          const ink = resolve(declarations, permit.token);
          if (ink === null) {
            reportAt(context, raw, permit.offset, "unresolved", { token: permit.token });
            continue;
          }
          for (const surface of permit.surfaces) {
            if (refusals.some((r) => r.token === permit.token && r.surface === surface)) {
              reportAt(context, raw, permit.offset, "refusedPairing", {
                token: permit.token,
                surface,
              });
              continue;
            }
            const backdrop = resolve(declarations, backdropToken(surface));
            if (backdrop === null) {
              reportAt(context, raw, permit.offset, "unresolved", {
                token: backdropToken(surface),
              });
              continue;
            }
            const floor = FLOORS[permit.klass] ?? FLOORS.text;
            const ratio = contrast(ink, backdrop);
            if (ratio + 1e-9 < floor) {
              reportAt(context, raw, permit.offset, "belowFloor", {
                token: permit.token,
                surface,
                ratio: ratio.toFixed(2),
                klass: permit.klass,
                floor: floor.toFixed(1),
              });
            }
          }
        }
      },
    };
  },
};

export default {
  rules: {
    "no-palette-token": noPaletteToken,
    "no-raw-type": noRawType,
    "system-owns-status": systemOwnsStatus,
    "token-contrast": tokenContrast,
  },
};
