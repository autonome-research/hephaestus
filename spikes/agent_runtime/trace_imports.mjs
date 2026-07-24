// Spike D+G audit 2a/2b: does importing thread-phase's public surfaces load
// the transitive `openai` SDK or any native addon (.node)?
// Usage: node trace_imports.mjs <specifier>
// Reports every loaded module path matching openai / .node / node:sqlite,
// via a require/import hook (module.registerHooks, Node >=22.15).

import { registerHooks } from "node:module";

const spec = process.argv[2];
if (!spec) {
  console.error("usage: node trace_imports.mjs <import-specifier>");
  process.exit(2);
}

const loaded = [];
registerHooks({
  resolve(specifier, context, nextResolve) {
    const r = nextResolve(specifier, context);
    loaded.push(r.url ?? specifier);
    return r;
  },
});

const before = process.moduleLoadList ? [...process.moduleLoadList] : [];
const mod = await import(spec);

const hits = {
  openai: loaded.filter((u) => /[/\\]openai[@/\\]|^openai$|\/openai\//.test(u)),
  native: loaded.filter((u) => u.endsWith(".node")),
  nodeSqlite: loaded.filter((u) => u.includes("node:sqlite")),
};

console.log(JSON.stringify({
  specifier: spec,
  totalModulesLoaded: loaded.length,
  exportedNames: Object.keys(mod).sort(),
  openaiModulesLoaded: hits.openai.length,
  openaiSample: hits.openai.slice(0, 5),
  nativeAddonsLoaded: hits.native,
  nodeSqliteLoaded: hits.nodeSqlite.length > 0,
}, null, 2));
