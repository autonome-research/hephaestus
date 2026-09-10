// Session registry, creation/resume, and per-run cancellation.
//
// STAGE2_DIGEST §2: one persistent Pi session per part, a separate orchestrator
// session, scoped quick-edit children, and ephemeral query_snapshot children.
// Each session persists under .heph/sessions/<id> (query_snapshot is in-memory).
// STAGE2_DIGEST §6 (cancellation): each run owns its own AbortController so
// cancelling one run terminates only that run's tool child processes — other
// multiplexed sessions stay healthy.
//
// The Pi wiring lives in `defaultSessionFactory`; it installs a CAD system prompt
// and an isolation-locked ResourceLoader (no ambient extensions/skills/context
// files) so global Pi state can never leak into a run. Tests drive real sessions
// through a FakeModel-backed ModelRuntime — the same code path as production.

import {
  createAgentSession,
  SessionManager as PiSessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import type {
  AgentSession,
  ModelRuntime,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { DefaultResourceLoader } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { profileDefinition, sessionDirFor, type SessionProfile } from "./profiles.js";
import { hephaestusInlineExtension } from "./extension.js";
import type { PiModel } from "./runtime.js";
import { RpcError } from "../rpc.js";
import { loadSelection, saveSelection, modelError, modelRef, resolvedModel, sameModel, type ModelRef, type ModelRevision, type ModelResolver, type SessionModelState } from "./model-selection.js";

/**
 * A resume naming a session this project holds no persisted transcript for.
 *
 * INTERFACE.md §2.3/§2.4 (amended 2026-09-04). `resume` used to be a request
 * the manager could not fail: `resume()` delegated straight to `create()`, and
 * `PiSessionManager.continueRecent` over an absent directory has nothing to
 * continue, so it minted a **fresh session under the old name** and every layer
 * above reported `resumed: true`. The operator was told they had reopened a
 * transcript they had not, and §2.8's re-adoption path — which is this same
 * call — would silently replace a session it failed to recover with an empty
 * one bearing its id.
 *
 * The message is the exact shape the Python side already parses
 * (`server/src/hephaestus/http/errors.py`'s `_UNKNOWN_SESSION_RE`, and
 * `agent_bridge/app.py`'s `_names_unknown_session`), so no new reason and no new
 * mapping code is needed on either side of the bridge; `main.ts` also puts
 * `reason: "unknown_session"` in the frame's `data` so the classification does
 * not depend on the sentence at all.
 */
export class UnknownSessionError extends Error {
  constructor(readonly sessionId: string) {
    super(`unknown session '${sessionId}'`);
    this.name = "UnknownSessionError";
  }
}

export interface SessionCreateRequest {
  readonly profile: SessionProfile;
  readonly projectRoot: string;
  readonly sessionId?: string;
  readonly part?: string;
  readonly resume?: boolean;
  readonly model?: ModelRef;
}

export interface ManagedSession {
  readonly id: string;
  readonly profile: SessionProfile;
  readonly part: string | undefined;
  readonly session: AgentSession;
  /** Persistence dir, or undefined for in-memory (query_snapshot). */
  readonly sessionDir: string | undefined;
  liveSession: AgentSession | undefined;
  readonly piSessionManager: PiSessionManager;
  readonly build: Omit<SessionBuildSpec, "model">;
  modelState: SessionModelState;
}

/** Everything the Pi wiring needs to build one AgentSession. */
export interface SessionBuildSpec {
  readonly profile: SessionProfile;
  readonly sessionId: string;
  readonly part: string | undefined;
  readonly projectRoot: string;
  readonly tools: string[];
  readonly systemPrompt: string;
  readonly persist: boolean;
  readonly extensions: boolean;
  readonly resume: boolean;
  readonly piSessionManager: PiSessionManager;
  readonly customTools: readonly ToolDefinition[];
  readonly settings: SettingsManager | undefined;
  readonly model: PiModel;
  readonly agentDir: string;
  readonly runtime: ModelRuntime;
}

export type SessionFactory = (spec: SessionBuildSpec) => Promise<AgentSession>;

export interface SessionServiceDeps {
  readonly runtime: ModelRuntime;
  readonly agentDir: string;
  /** Compatibility default only for internal, non-HTTP creation. */
  readonly model: PiModel | ((profile: SessionProfile) => PiModel);
  readonly resolver?: ModelResolver;
  readonly customTools?: readonly ToolDefinition[];
  readonly settings?: (profile: SessionProfile) => SettingsManager | undefined;
  /** Override the Pi wiring (defaults to `defaultSessionFactory`). */
  readonly factory?: SessionFactory;
}

interface RunEntry {
  readonly sessionId: string;
  readonly controller: AbortController;
}

/**
 * Default Pi wiring: an isolation-locked DefaultResourceLoader carrying the CAD
 * system prompt, the profile tool allowlist, and no ambient extensions. An empty
 * allowlist (query_snapshot) yields a toolless session — NOT noTools:"all", which
 * would also strip custom tools (Stage S finding).
 *
 * The one extension that DOES load is the shipped, trusted Hephaestus extension
 * (`extensionFactories` survives `noExtensions`, which suppresses only ambient
 * global/project extensions). It carries the in-loop policies Pi must enforce:
 * `ask_user` tool-call preflight and K=3 image eviction. The ephemeral
 * `query_snapshot` child is explicitly excluded — arch §4.4 requires it to run
 * with no extensions at all.
 */
export async function defaultSessionFactory(spec: SessionBuildSpec): Promise<AgentSession> {
  const trusted = spec.profile === "query_snapshot" ? [] : [hephaestusInlineExtension()];
  const loader = new DefaultResourceLoader({
    cwd: spec.projectRoot,
    agentDir: spec.agentDir,
    systemPrompt: spec.systemPrompt,
    noExtensions: !spec.extensions,
    extensionFactories: trusted,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  await loader.reload();
  const base = {
    cwd: spec.projectRoot,
    agentDir: spec.agentDir,
    modelRuntime: spec.runtime,
    model: spec.model,
    thinkingLevel: "off" as const,
    tools: spec.tools,
    customTools: [...spec.customTools],
    resourceLoader: loader,
    sessionManager: spec.piSessionManager,
  };
  // Pi's OWN provider auto-retry (settings.retry, default enabled x3 with
  // backoff) is disabled: the single audited transient-fault retry in
  // main.ts/session/retry.ts is the only retry authority, so the archive shows
  // every fault and a second one fails the run loudly. A test that passes its
  // own SettingsManager owns the whole settings surface, this knob included.
  const options = {
    ...base,
    settingsManager: spec.settings ?? SettingsManager.inMemory({ retry: { enabled: false } }),
  };
  const { session } = await createAgentSession(options);
  return session;
}

/** In-process registry of live sessions plus per-run cancellation. */
export class SessionService {
  private readonly sessions = new Map<string, ManagedSession>();
  private readonly runs = new Map<string, RunEntry>();
  private readonly operations = new Set<string>();
  private readonly factory: SessionFactory;

  constructor(private readonly deps: SessionServiceDeps) {
    this.factory = deps.factory ?? defaultSessionFactory;
  }

  /** Create (or resume, when request.resume) a managed session. */
  async create(request: SessionCreateRequest): Promise<ManagedSession> {
    const id = request.sessionId ?? randomUUID();
    if (!id || id === "." || id === ".." || /[/\\\\\0]/u.test(id)) throw modelError("invalid_params");
    if (this.operations.has(id)) throw modelError("model_change_in_progress");
    if (this.sessions.has(id)) {
      throw new Error(`session '${id}' already exists`);
    }
    if (request.resume && request.model !== undefined) throw modelError("invalid_params");
    this.operations.add(id);
    try {
      return await this.createReserved(request, id);
    } finally {
      this.operations.delete(id);
    }
  }

  private async createReserved(request: SessionCreateRequest, id: string): Promise<ManagedSession> {
    const definition = profileDefinition(request.profile, request.part !== undefined ? { part: request.part } : {});
    const persist = definition.persist;
    const sessionDir = persist ? sessionDirFor(request.projectRoot, id) : undefined;
    const resume = request.resume ?? false;
    const piSessionManager = this.buildPiSessionManager(request.projectRoot, sessionDir, persist, resume);
    let selected: ModelRef | null = request.model ?? null;
    let pending: ModelRef | null = null;
    let reason: string | null = null;
    if (resume) {
      try {
        const record = loadSelection(sessionDir);
        const legacy = piSessionManager.buildSessionContext().model;
        selected = record ? record.selected : legacy ? { provider_id: legacy.provider, model_id: legacy.modelId } : null;
        pending = record?.pending_selection ?? null;
        if (pending) reason = "model_selection_uncertain";
      } catch { reason = "model_selection_uncertain"; }
    }
    let model: PiModel | undefined;
    if (!reason) {
      if (resume && !selected) reason = "selection_required";
      else {
        try {
          model = selected ? this.resolve(selected) : typeof this.deps.model === "function" ? this.deps.model(request.profile) : this.deps.model;
          selected ??= modelRef(model);
        } catch (err) {
          if (!resume) throw err;
          reason = err instanceof Error ? err.message.replaceAll(" ", "_") : "model_unavailable";
        }
      }
    }
    const spec: Omit<SessionBuildSpec, "model"> = {
      profile: request.profile,
      sessionId: id,
      part: request.part,
      projectRoot: request.projectRoot,
      tools: definition.tools,
      systemPrompt: definition.systemPrompt,
      persist,
      extensions: definition.extensions,
      resume,
      piSessionManager,
      customTools: this.deps.customTools ?? [],
      settings: this.deps.settings?.(request.profile),
      agentDir: this.deps.agentDir,
      runtime: this.deps.runtime,
    };
    const session = model ? await this.factory({ ...spec, model }) : undefined;
    if (session && (!session.model || !sameModel(modelRef(session.model), selected))) {
      session.dispose();
      throw modelError("model_selection_failed");
    }
    if (session) {
      try { saveSelection(sessionDir, { schema_version: 1, selected, pending_selection: null }); }
      catch { session.dispose(); throw modelError("model_selection_failed"); }
    }
    const managed: ManagedSession = {
      id,
      profile: request.profile,
      part: request.part,
      get session() {
        if (!this.liveSession) throw modelError(this.modelState.reason ?? "selection_required");
        return this.liveSession;
      },
      liveSession: session,
      sessionDir,
      piSessionManager,
      build: spec,
      modelState: { revision: { epoch: randomUUID(), version: 0 }, current: session?.model ? resolvedModel(session.model) : null, selected, pending_selection: pending, state: reason === "model_selection_uncertain" ? "uncertain" : reason ? "unavailable" : "ready", reason },
    };
    this.sessions.set(id, managed);
    return managed;
  }

  /**
   * Resume a persisted session by ID (continue its most recent JSONL).
   *
   * **Refuses rather than minting** (INTERFACE.md §2.3/§2.4, amended
   * 2026-09-04): a resume for an id with no persisted session directory is
   * `unknown session '<id>'`, which the bridge maps to §2.4's existing
   * `unknown_session` at 404. See {@link UnknownSessionError} for what the
   * silent-create did instead.
   *
   * The check is on the **directory**, not on a transcript file inside it.
   * `PiSessionManager.create` makes the directory when the session is opened,
   * before any entry is written, so a session that was created and then died
   * mid-turn still has one — and §2.8(6)'s re-adoption must be able to recover
   * exactly that session. A file-level check would turn the crash this clause
   * exists to heal into a permanent refusal.
   */
  async resume(request: SessionCreateRequest): Promise<ManagedSession> {
    const id = request.sessionId;
    if (id === undefined) {
      throw new Error("resume requires a session id: there is nothing to resume without a name");
    }
    if (!this.hasPersistedSession(request, id)) {
      throw new UnknownSessionError(id);
    }
    return this.create({ ...request, resume: true });
  }

  /** Is there something on disk for this id that `resume` could continue? */
  private hasPersistedSession(request: SessionCreateRequest, id: string): boolean {
    const definition = profileDefinition(
      request.profile,
      request.part !== undefined ? { part: request.part } : {},
    );
    // A non-persisting profile (query_snapshot, reviewer) writes no JSONL at
    // all, so there is never anything to resume under one — the request is an
    // addressing miss whatever is on disk.
    if (!definition.persist) return false;
    return existsSync(sessionDirFor(request.projectRoot, id));
  }

  private buildPiSessionManager(
    projectRoot: string,
    sessionDir: string | undefined,
    persist: boolean,
    resume: boolean,
  ): PiSessionManager {
    if (!persist || sessionDir === undefined) {
      return PiSessionManager.inMemory(projectRoot);
    }
    return resume
      ? PiSessionManager.continueRecent(projectRoot, sessionDir)
      : PiSessionManager.create(projectRoot, sessionDir);
  }

  private resolve(ref: ModelRef): PiModel {
    if (this.deps.resolver) return this.deps.resolver.resolve(ref);
    const model = this.deps.runtime.getModel(ref.provider_id, ref.model_id);
    if (!model) throw modelError("model_unknown");
    if (!this.deps.runtime.hasConfiguredAuth(ref.provider_id)) throw modelError("model_unavailable", { unavailable_reason: "provider_not_authenticated" });
    return model;
  }

  /** Called after locally settled credential changes, never by a GET. */
  refreshEligibility(): void {
    for (const managed of this.sessions.values()) {
      if (this.operations.has(managed.id) || !managed.liveSession?.model || managed.modelState.state === "uncertain") continue;
      let reason: string | null = null;
      try { this.resolve(modelRef(managed.liveSession.model)); }
      catch { reason = "model_unavailable"; }
      const state = reason ? "unavailable" : "ready";
      if (managed.modelState.state !== state || managed.modelState.reason !== reason) managed.modelState = { ...managed.modelState, state, reason, revision: { ...managed.modelState.revision, version: managed.modelState.revision.version + 1 } };
    }
  }

  modelState(id: string): SessionModelState {
    const managed = this.sessions.get(id);
    if (!managed) throw modelError("unknown_session", { session_id: id });
    const current = managed.liveSession?.model;
    return { ...managed.modelState, revision: { ...managed.modelState.revision }, current: current ? resolvedModel(current) : null };
  }

  private checkIdle(id: string): ManagedSession {
    const managed = this.sessions.get(id);
    if (!managed) throw modelError("unknown_session", { session_id: id });
    if (this.operations.has(id)) throw modelError("model_change_in_progress", { session_id: id, model_state: this.modelState(id) });
    const run = [...this.runs.entries()].find(([, r]) => r.sessionId === id);
    const session = managed.liveSession;
    if (run || (session && (!session.isIdle || session.isCompacting || session.isRetrying || session.pendingMessageCount > 0))) throw modelError("run_in_flight", { session_id: id, run_id: run?.[0] ?? null, scope: "session" });
    return managed;
  }

  private checkRevision(id: string, expected: ModelRevision): void {
    const revision = this.modelState(id).revision;
    if (expected.epoch !== revision.epoch || expected.version !== revision.version) throw modelError("model_changed", { session_id: id, model_state: this.modelState(id) });
  }

  async selectModel(id: string, ref: ModelRef, expected: ModelRevision): Promise<SessionModelState> {
    const managed = this.checkIdle(id);
    this.checkRevision(id, expected);
    const model = this.resolve(ref);
    this.operations.add(id); // Synchronous: before any SDK await, never timeout-raced.
    const previous = managed.modelState;
    let intentAttempted = false;
    try {
      intentAttempted = true;
      saveSelection(managed.sessionDir, { schema_version: 1, selected: previous.selected, pending_selection: ref });
      managed.modelState = { ...previous, revision: { ...previous.revision, version: previous.revision.version + 1 }, state: "changing", reason: null, pending_selection: ref };
      if (managed.liveSession) await managed.liveSession.setModel(model);
      else managed.liveSession = await this.factory({ ...managed.build, model });
      if (!managed.liveSession.model || !sameModel(modelRef(managed.liveSession.model), ref)) throw modelError("model_selection_failed");
      // Auth/catalog could have changed during Pi's uncancellable await.
      this.resolve(ref);
      saveSelection(managed.sessionDir, { schema_version: 1, selected: ref, pending_selection: null });
      managed.modelState = { ...managed.modelState, revision: { ...previous.revision, version: previous.revision.version + 2 }, selected: ref, pending_selection: null, state: "ready", reason: null };
      return this.modelState(id);
    } catch {
      if (intentAttempted) managed.modelState = { ...managed.modelState, revision: { ...previous.revision, version: previous.revision.version + 2 }, pending_selection: ref, state: "uncertain", reason: "model_selection_uncertain" };
      throw modelError("model_selection_failed", { session_id: id, model_state: this.modelState(id) });
    } finally { this.operations.delete(id); }
  }

  async compact(id: string, instructions: string): Promise<{ summary: string }> {
    const managed = this.checkIdle(id);
    this.operations.add(id);
    try { return await managed.session.compact(instructions); }
    finally { this.operations.delete(id); }
  }

  get(id: string): ManagedSession | undefined {
    return this.sessions.get(id);
  }

  list(): ManagedSession[] {
    return [...this.sessions.values()];
  }

  /**
   * Register a run against a session and return its dedicated AbortController.
   * The controller's signal is the one a tool proxy forwards to Python so that
   * cancelling this run kills only this run's tool children.
   */
  beginRun(sessionId: string, runId: string, expected?: ModelRevision): AbortController {
    const managed = this.checkIdle(sessionId);
    if (expected) this.checkRevision(sessionId, expected);
    if (managed.modelState.state !== "ready") throw modelError(managed.modelState.reason ?? "selection_required", { session_id: sessionId, model_state: this.modelState(sessionId) });
    const live = managed.liveSession?.model;
    if (!live) throw modelError("selection_required");
    try { this.resolve(modelRef(live)); }
    catch (err) {
      this.refreshEligibility();
      const extra = err instanceof RpcError ? err.data as Record<string, import("../framing.js").JsonValue> : {};
      throw modelError("model_unavailable", { ...extra, session_id: sessionId, model_state: this.modelState(sessionId), reason: "model_unavailable" });
    }
    if (this.runs.has(runId)) {
      throw new Error(`run '${runId}' already active`);
    }
    const controller = new AbortController();
    this.runs.set(runId, { sessionId, controller });
    return controller;
  }

  runController(runId: string): AbortController | undefined {
    return this.runs.get(runId)?.controller;
  }

  /** Cancel one run: abort its session's current stream and its tool children. */
  async cancel(runId: string): Promise<void> {
    const run = this.runs.get(runId);
    if (run === undefined) return;
    run.controller.abort();
    const managed = this.sessions.get(run.sessionId);
    if (managed !== undefined) {
      await managed.liveSession?.abort();
    }
  }

  endRun(runId: string): void {
    this.runs.delete(runId);
  }

  /** Dispose a session, aborting and dropping any of its live runs. */
  async dispose(id: string): Promise<void> {
    const managed = this.sessions.get(id);
    if (managed === undefined) return;
    for (const [runId, run] of this.runs) {
      if (run.sessionId === id) {
        run.controller.abort();
        this.runs.delete(runId);
      }
    }
    if (this.operations.has(id)) throw modelError("model_change_in_progress");
    await managed.liveSession?.abort();
    managed.liveSession?.dispose();
    this.sessions.delete(id);
  }

  async disposeAll(): Promise<void> {
    for (const id of [...this.sessions.keys()]) {
      await this.dispose(id);
    }
  }
}
