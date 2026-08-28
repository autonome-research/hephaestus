// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * `heph/no-derived-fact` — INTERFACE.md §1's boundary, made mechanical.
 *
 * §1: "Every number the UI presents as fact renders through the `<Fact>`
 * primitive (§4.6) and carries a `data-source` attribute naming the HTTP
 * response field it was read from. A displayed fact with no such attribution is
 * a lint failure — `web/` eslint rule `heph/no-derived-fact`."
 *
 * WHAT THIS RULE ACTUALLY DECIDES, stated honestly rather than implied:
 *
 * 1. **`<Fact source>` must be a static, dotted response path.** A computed
 *    `source` would let a component mint an attribution at runtime, which is
 *    attribution theatre: the point of `data-source` is that a reviewer and the
 *    e2e can both read it out of the source tree.
 * 2. **`<Fact value>` may not be a derived expression.** Arithmetic, `.length`,
 *    `Math.*`, `Number(…)`, `parseInt/parseFloat`, and the reducing array
 *    methods are rejected outright: those are exactly §1's closed list of things
 *    the client must not compute ("any re-count of anything a build result
 *    already counts" is `.length` on a server array, spelled out).
 * 3. **Only `<Fact>` may carry a literal `data-source`.** Otherwise any element
 *    could forge the attribution the lint exists to check.
 *
 * What it deliberately does NOT decide: whether an arbitrary rendered number is
 * a *fact*. "Is this number presented as fact" is a judgement about meaning, and
 * a lint that guessed at it would either be trivially evadable or would flag the
 * grid readout, which §1 exempts by name ("Screen-space quantities are exempt
 * *and are never rendered as facts*"). The mechanical half is the three checks
 * above; the completeness half is the e2e's DOM-vs-JSON comparison (§6.1, §6.2).
 */

/**
 * A dotted path into an HTTP response document: `build.geometry_count`.
 *
 * `[]` marks a repeated element whose index is carried by a `data-*` attribute
 * beside the fact (`build.geometries[].label`, `git.commits[].short`): the path
 * has to be a *static* string for this rule to check it, so the index cannot be
 * in the path. At least one dot is required — a bare word names a concept, not a
 * response field, and the whole point of `data-source` is that an assertion can
 * index the JSON with it.
 */
const SOURCE_PATH = /^[A-Za-z_][\w\-[\]]*(\.[\w\-[\]]+)+$/;

/** Array methods that fold many server values into one client value. */
const FOLDING_METHODS = new Set([
  "reduce",
  "reduceRight",
  "filter",
  "map",
  "flatMap",
  "concat",
  "sort",
]);

/** Free functions that turn a string or a shape into a number. */
const COERCIONS = new Set(["Number", "parseInt", "parseFloat", "BigInt"]);

const ARITHMETIC = new Set(["+", "-", "*", "/", "%", "**"]);

function elementName(node) {
  const name = node.name;
  if (!name) return null;
  if (name.type === "JSXIdentifier") return name.name;
  if (name.type === "JSXMemberExpression" && name.property) return name.property.name;
  return null;
}

/** The static string an attribute holds, or `null` if it is not static. */
function staticString(attribute) {
  const value = attribute.value;
  if (!value) return null;
  if (value.type === "Literal" && typeof value.value === "string") return value.value;
  if (value.type === "JSXExpressionContainer") {
    const expression = value.expression;
    if (expression.type === "Literal" && typeof expression.value === "string") {
      return expression.value;
    }
    if (expression.type === "TemplateLiteral" && expression.expressions.length === 0) {
      return expression.quasis.map((q) => q.value.cooked).join("");
    }
  }
  return null;
}

/** The first derivation inside `node`, or `null`. Returns a short reason. */
function derivation(node) {
  if (node === null || typeof node !== "object") return null;
  switch (node.type) {
    case "BinaryExpression":
      if (ARITHMETIC.has(node.operator)) return `arithmetic (\`${node.operator}\`)`;
      break;
    case "UnaryExpression":
      if (node.operator === "-" || node.operator === "+") {
        if (node.argument.type !== "Literal") return `unary \`${node.operator}\``;
      }
      break;
    case "MemberExpression":
      if (!node.computed && node.property.type === "Identifier") {
        if (node.property.name === "length") return "`.length` (a client re-count)";
        if (node.object.type === "Identifier" && node.object.name === "Math") {
          return "`Math.*`";
        }
      }
      break;
    case "CallExpression": {
      const callee = node.callee;
      if (callee.type === "Identifier" && COERCIONS.has(callee.name)) {
        return `\`${callee.name}(…)\``;
      }
      if (
        callee.type === "MemberExpression" &&
        !callee.computed &&
        callee.property.type === "Identifier" &&
        FOLDING_METHODS.has(callee.property.name)
      ) {
        return `\`.${callee.property.name}(…)\``;
      }
      break;
    }
    default:
      break;
  }
  for (const key of Object.keys(node)) {
    if (key === "parent" || key === "loc" || key === "range") continue;
    const child = node[key];
    if (Array.isArray(child)) {
      for (const item of child) {
        const found = derivation(item);
        if (found !== null) return found;
      }
    } else if (child && typeof child === "object" && typeof child.type === "string") {
      const found = derivation(child);
      if (found !== null) return found;
    }
  }
  return null;
}

/** @type {import("eslint").Rule.RuleModule} */
export const noDerivedFact = {
  meta: {
    type: "problem",
    docs: {
      description:
        "A displayed fact renders through <Fact> and names the response field it was read from (INTERFACE.md §1, §4.6).",
    },
    schema: [],
    messages: {
      missingSource: "<Fact> requires a `source` naming the HTTP response field (INTERFACE.md §4.6).",
      dynamicSource:
        "<Fact source> must be a static string literal: a computed attribution cannot be reviewed or asserted on.",
      malformedSource:
        "<Fact source=\"{{source}}\"> is not a dotted response path (e.g. `build.geometry_count`).",
      missingValue: "<Fact> requires a `value` read from a server response.",
      derivedValue:
        "<Fact value> may not be derived client-side: found {{reason}}. INTERFACE.md §1 closes the list of what the client must not compute; ask the server for this number.",
      forgedSource:
        "`data-source` may only be minted by <Fact> (INTERFACE.md §4.6). Render this through <Fact> instead.",
    },
  },
  create(context) {
    return {
      JSXOpeningElement(node) {
        const name = elementName(node);
        const attributes = node.attributes.filter((a) => a.type === "JSXAttribute");

        if (name !== "Fact") {
          for (const attribute of attributes) {
            if (attribute.name.type === "JSXIdentifier" && attribute.name.name === "data-source") {
              context.report({ node: attribute, messageId: "forgedSource" });
            }
          }
          return;
        }

        const byName = new Map(
          attributes
            .filter((a) => a.name.type === "JSXIdentifier")
            .map((a) => [a.name.name, a]),
        );

        const source = byName.get("source");
        if (source === undefined) {
          context.report({ node, messageId: "missingSource" });
        } else {
          const literal = staticString(source);
          if (literal === null) {
            context.report({ node: source, messageId: "dynamicSource" });
          } else if (!SOURCE_PATH.test(literal)) {
            context.report({
              node: source,
              messageId: "malformedSource",
              data: { source: literal },
            });
          }
        }

        const value = byName.get("value");
        if (value === undefined) {
          context.report({ node, messageId: "missingValue" });
          return;
        }
        if (value.value && value.value.type === "JSXExpressionContainer") {
          const reason = derivation(value.value.expression);
          if (reason !== null) {
            context.report({ node: value, messageId: "derivedValue", data: { reason } });
          }
        }
      },
    };
  },
};

export default { rules: { "no-derived-fact": noDerivedFact } };
