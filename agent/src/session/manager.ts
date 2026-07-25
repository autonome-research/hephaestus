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
} from "@earendil-works/pi-coding-agent";
import type {
  AgentSession,
  ModelRuntime,
  SettingsManager,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { DefaultResourceLoader } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { profileDefinition, sessionDirFor, type SessionProfile } from "./profiles.js";
import type { PiModel } from "./runtime.js";

export interface SessionCreateRequest {
  readonly profile: SessionProfile;
  readonly projectRoot: string;
  readonly sessionId?: string;
  readonly part?: string;
  readonly resume?: boolean;
}

export interface ManagedSession {
  readonly id: string;
  readonly profile: SessionProfile;
  readonly part: string | undefined;
  readonly session: AgentSession;
  /** Persistence dir, or undefined for in-memory (query_snapshot). */
  readonly sessionDir: string | undefined;
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
  readonly model: PiModel | ((profile: SessionProfile) => PiModel);
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
 */
export async function defaultSessionFactory(spec: SessionBuildSpec): Promise<AgentSession> {
  const loader = new DefaultResourceLoader({
    cwd: spec.projectRoot,
    agentDir: spec.agentDir,
    systemPrompt: spec.systemPrompt,
    noExtensions: !spec.extensions,
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
  const options = spec.settings !== undefined ? { ...base, settingsManager: spec.settings } : base;
  const { session } = await createAgentSession(options);
  return session;
}

/** In-process registry of live sessions plus per-run cancellation. */
export class SessionService {
  private readonly sessions = new Map<string, ManagedSession>();
  private readonly runs = new Map<string, RunEntry>();
  private readonly factory: SessionFactory;

  constructor(private readonly deps: SessionServiceDeps) {
    this.factory = deps.factory ?? defaultSessionFactory;
  }

  /** Create (or resume, when request.resume) a managed session. */
  async create(request: SessionCreateRequest): Promise<ManagedSession> {
    const id = request.sessionId ?? randomUUID();
    if (this.sessions.has(id)) {
      throw new Error(`session '${id}' already exists`);
    }
    const definition = profileDefinition(request.profile, request.part !== undefined ? { part: request.part } : {});
    const persist = definition.persist;
    const sessionDir = persist ? sessionDirFor(request.projectRoot, id) : undefined;
    const resume = request.resume ?? false;
    const piSessionManager = this.buildPiSessionManager(request.projectRoot, sessionDir, persist, resume);
    const model = typeof this.deps.model === "function" ? this.deps.model(request.profile) : this.deps.model;

    const spec: SessionBuildSpec = {
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
      model,
      agentDir: this.deps.agentDir,
      runtime: this.deps.runtime,
    };
    const session = await this.factory(spec);
    const managed: ManagedSession = { id, profile: request.profile, part: request.part, session, sessionDir };
    this.sessions.set(id, managed);
    return managed;
  }

  /** Resume a persisted session by ID (continue its most recent JSONL). */
  async resume(request: SessionCreateRequest): Promise<ManagedSession> {
    return this.create({ ...request, resume: true });
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
  beginRun(sessionId: string, runId: string): AbortController {
    if (!this.sessions.has(sessionId)) {
      throw new Error(`cannot begin run for unknown session '${sessionId}'`);
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
      await managed.session.abort();
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
    await managed.session.abort();
    managed.session.dispose();
    this.sessions.delete(id);
  }

  async disposeAll(): Promise<void> {
    for (const id of [...this.sessions.keys()]) {
      await this.dispose(id);
    }
  }
}
