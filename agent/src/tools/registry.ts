// Per-profile Pi custom-tool registry (architecture §4.1/§4.2, digest §1/§2).
//
// Builds the Pi custom-tool set for a session profile from the generated tool
// surface. Only tools whose generated `meta.profiles` include the profile are
// exposed (part / orchestrator / quick_edit object scoping); the strict
// allowlist form is used elsewhere so no built-in coding tool leaks in.
// Sequential-execution declarations come straight from `meta.sequential`
// (ask_user, the part/globals/check editors, set_params, build_part,
// export_part, and the delegation tools). Every tool's `execute` delegates to
// the ToolProxy, resolving trusted per-call invocation context by tool-call ID.

import { defineTool, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { TOOLS, TOOL_NAMES, type ToolProfile } from "./schema.gen.js";
import type { ProxyContext, ToolProxy } from "./proxy.js";

export interface RegistryDeps {
  readonly proxy: ToolProxy;
  /** Resolve the trusted invocation context for a provider tool-call ID. */
  readonly resolveContext: (toolCallId: string) => ProxyContext;
}

/** Tool names available to a profile, in the generated (stable) order. */
export function toolNamesForProfile(profile: ToolProfile): string[] {
  return TOOL_NAMES.filter((name) => TOOLS[name]!.meta.profiles.includes(profile));
}

/**
 * Build the Pi custom-tool definitions for a profile. Pass the returned array as
 * `customTools`, and the same names (from `toolNamesForProfile`) as the strict
 * `tools` allowlist, when creating the Pi session.
 */
export function buildToolSet(profile: ToolProfile, deps: RegistryDeps): ToolDefinition[] {
  return buildToolsForNames(toolNamesForProfile(profile), deps);
}

/**
 * Build custom-tool definitions for EVERY generated tool (the union across all
 * profiles). The session's per-profile `tools` allowlist still selects which of
 * these are actually exposed to the model, so one shared `customTools` array can
 * back sessions of any profile (the sidecar builds a single SessionService).
 */
export function buildAllTools(deps: RegistryDeps): ToolDefinition[] {
  return buildToolsForNames([...TOOL_NAMES], deps);
}

function buildToolsForNames(names: readonly string[], deps: RegistryDeps): ToolDefinition[] {
  const tools: ToolDefinition[] = [];
  for (const name of names) {
    const entry = TOOLS[name];
    if (entry === undefined) continue;
    const { meta, params } = entry;
    tools.push(
      defineTool({
        name,
        label: name,
        description: meta.summary,
        parameters: params,
        executionMode: meta.sequential ? "sequential" : "parallel",
        execute(toolCallId, args) {
          const ctx = deps.resolveContext(toolCallId);
          return deps.proxy.execute(name, args, ctx);
        },
      }),
    );
  }
  return tools;
}
