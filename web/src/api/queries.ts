// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// TanStack Query wiring for the §2.3 read routes.
//
// INTERFACE.md §3 chose TanStack Query because "server state is almost entirely
// content-addressed and cacheable **by ref** (§2.6); refetch/invalidate is the
// whole problem". Staleness here is a property of the *route*, not a tuning
// knob. Every route in this module is **project state** — `/project`, `/parts`,
// `/parts/{part}/{build,script}`, `/git/*` — which changes when the human or the
// agent changes it, so each carries a short staleness and refetches on focus.
//
// The **by-ref** tier has no hook here on purpose. Its one consumer today is the
// script pager, which must *accumulate* pages of one snapshot in cursor order;
// a per-page query cache holds each page but not the sequence, so
// `components/stage/useScriptPages.ts` owns that accumulation and calls
// `apiJson` directly. A hook that fetched a page and threw away the sequence
// would be a cache with nothing to cache for.
//
// Nothing here transforms a response. A `select` that reshaped a document would
// be the client deriving a fact one layer below the panel that renders it (§1),
// and it would put the `<Fact source="…">` paths out of step with the wire.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiJson } from "./client";
import { fetchExports, type ExportsDocument } from "./exports";
import { loadProviders, type ProvidersDocument } from "./providers";
import type {
  BuildDocument,
  ChecksDocument,
  DfmDocument,
  PropertiesDocument,
  GitLogDocument,
  GitStatusDocument,
  GitTagsDocument,
  PartsDocument,
  ProjectDocument,
  ScriptDocument,
} from "./types";

/** Project-state reads: cheap, and wrong only briefly. */
const PROJECT_STALE_MS = 5_000;

/** Query keys, in one place so an invalidation names the same tuple a read does. */
export const keys = {
  project: () => ["project"] as const,
  parts: () => ["parts"] as const,
  build: (part: string) => ["parts", part, "build"] as const,
  script: (part: string) => ["parts", part, "script"] as const,
  properties: (part: string) => ["parts", part, "properties"] as const,
  checks: (part: string) => ["parts", part, "checks"] as const,
  dfm: (part: string) => ["parts", part, "dfm"] as const,
  exports: (part: string) => ["parts", part, "exports"] as const,
  gitStatus: () => ["git", "status"] as const,
  gitLog: (part: string | null) => ["git", "log", part] as const,
  gitTags: () => ["git", "tags"] as const,
  /**
   * §23.8's read. Project state like every other key here, and **not** a probe:
   * it reads a file the serve already owns and, when a sidecar is attached, the
   * auth state that sidecar already holds. Nothing on this path asks a provider
   * anything, which is §15.41's "no background credential probe" — the refusal
   * is about *outbound* traffic, and a cached local read makes none.
   */
  providers: () => ["providers"] as const,
};

/**
 * `GET /providers` — the panel's whole read (§23.8).
 *
 * On the query layer rather than in a `useEffect` so the panel has one source of
 * truth and a credential change invalidates rather than re-fetching by hand.
 * **`POST /providers/discover` is deliberately NOT here**: a query hook runs on
 * mount and refetches on focus, and §15.41 forbids exactly that for discovery.
 * The offer is a click, and it lives in the panel's own state.
 */
export function useProviders(): UseQueryResult<ProvidersDocument, Error> {
  return useQuery({
    queryKey: keys.providers(),
    queryFn: loadProviders,
    staleTime: PROJECT_STALE_MS,
  });
}

export function useProject(): UseQueryResult<ProjectDocument, Error> {
  return useQuery({
    queryKey: keys.project(),
    queryFn: () => apiJson<ProjectDocument>("/project"),
    staleTime: PROJECT_STALE_MS,
  });
}

export function useParts(): UseQueryResult<PartsDocument, Error> {
  return useQuery({
    queryKey: keys.parts(),
    queryFn: () => apiJson<PartsDocument>("/parts"),
    staleTime: PROJECT_STALE_MS,
  });
}

/**
 * `GET /parts/{part}/build` — the projection G4.2's row count is read from.
 *
 * A part with no current build answers `status: "not_built"` with
 * `geometry_count: 0`: a **named absence**, not a 404 and not an empty success
 * (`http/projections.py`). The tree renders that state as words, because §6.3's
 * rule — silence never reads as a pass — is a UI obligation on every axis.
 */
export function useBuild(
  part: string | null,
  enabled = true,
): UseQueryResult<BuildDocument, Error> {
  return useQuery({
    queryKey: keys.build(part ?? ""),
    queryFn: () => apiJson<BuildDocument>(`/parts/${encodeURIComponent(part ?? "")}/build`),
    enabled: enabled && part !== null,
    staleTime: PROJECT_STALE_MS,
  });
}

export function useScript(part: string | null): UseQueryResult<ScriptDocument, Error> {
  return useQuery({
    queryKey: keys.script(part ?? ""),
    queryFn: () => apiJson<ScriptDocument>(`/parts/${encodeURIComponent(part ?? "")}/script`),
    enabled: part !== null,
    staleTime: PROJECT_STALE_MS,
  });
}

/**
 * `GET /parts/{part}/properties` — the §6.2 `part.*` projection.
 *
 * The panel renders one `data-field` node per key of `properties` and nothing
 * else, so the e2e's set equality against this document is an assertion about
 * the panel rather than about a filter the panel applied.
 */
export function useProperties(part: string | null): UseQueryResult<PropertiesDocument, Error> {
  return useQuery({
    queryKey: keys.properties(part ?? ""),
    queryFn: () =>
      apiJson<PropertiesDocument>(`/parts/${encodeURIComponent(part ?? "")}/properties`),
    enabled: part !== null,
    staleTime: PROJECT_STALE_MS,
  });
}

/**
 * `GET /parts/{part}/checks` — the shared `heph check --json` serializer (§6.3).
 *
 * **A check run is a real run**, not a cached read: the route executes the
 * project's check set against every part's current artifact. So this query does
 * not refetch on focus and carries a longer staleness than the project reads —
 * a window regaining focus is not a reason to re-run the checks — and it never
 * retries, because a refused run is an answer the panel must show by name.
 */
export function useChecks(part: string | null): UseQueryResult<ChecksDocument, Error> {
  return useQuery({
    queryKey: keys.checks(part ?? ""),
    queryFn: () => apiJson<ChecksDocument>(`/parts/${encodeURIComponent(part ?? "")}/checks`),
    enabled: part !== null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

/** `GET /parts/{part}/dfm` — the last recorded evaluation plus `auto_run` (§6.4). */
export function useDfm(part: string | null): UseQueryResult<DfmDocument, Error> {
  return useQuery({
    queryKey: keys.dfm(part ?? ""),
    queryFn: () => apiJson<DfmDocument>(`/parts/${encodeURIComponent(part ?? "")}/dfm`),
    enabled: part !== null,
    staleTime: PROJECT_STALE_MS,
    retry: false,
  });
}

/**
 * `GET /parts/{part}/exports` — §22.6's export history with its byte total.
 *
 * Never retried and never refetched on focus, for the same reason `useChecks`
 * is not: this is the record of a *retention obligation*, and a window regaining
 * focus is not a reason to re-read it. It is invalidated explicitly when an
 * export commits, which is the only moment it can change from this client.
 */
export function useExports(part: string | null): UseQueryResult<ExportsDocument, Error> {
  return useQuery({
    queryKey: keys.exports(part ?? ""),
    queryFn: () => fetchExports(part ?? ""),
    enabled: part !== null,
    staleTime: PROJECT_STALE_MS,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function useGitStatus(): UseQueryResult<GitStatusDocument, Error> {
  return useQuery({
    queryKey: keys.gitStatus(),
    queryFn: () => apiJson<GitStatusDocument>("/git/status"),
    staleTime: PROJECT_STALE_MS,
    // §13.1: a dirty tree is reported, never cleaned — and never guessed at
    // either. A failed git read stays a named absence rather than retrying into
    // a spinner that reads as "clean".
    retry: false,
  });
}

export function useGitLog(part: string | null): UseQueryResult<GitLogDocument, Error> {
  return useQuery({
    queryKey: keys.gitLog(part),
    queryFn: () =>
      apiJson<GitLogDocument>(
        part === null ? "/git/log" : `/git/log?part=${encodeURIComponent(part)}`,
      ),
    staleTime: PROJECT_STALE_MS,
    retry: false,
  });
}

export function useGitTags(): UseQueryResult<GitTagsDocument, Error> {
  return useQuery({
    queryKey: keys.gitTags(),
    queryFn: () => apiJson<GitTagsDocument>("/git/tags"),
    staleTime: PROJECT_STALE_MS,
    retry: false,
  });
}
