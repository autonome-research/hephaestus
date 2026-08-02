// Thread-phase `JobRunner` construction, admission-clamped fan-out, and the
// workflow-runner stdio entry (DESIGN.md `workflows/runner.ts`, digest §5).
//
// ## Import discipline (Stage S disposition 4 — binding)
//
// thread-phase is imported ONLY through its `/session` and `/patterns` subpaths;
// the root barrel eagerly loads the transitive `openai` SDK. An eslint
// `no-restricted-imports` rule forbids the bare specifier inside agent/, and
// `test/workflows/imports.test.ts` re-proves it with a live resolution trace.
//
// A consequence worth knowing: `Phase`, `BasePipelineContext` and `PipelineCache`
// are exported from the root barrel only, so this module declares its own
// structurally-identical `WorkflowPhase` / `WorkflowContext` / `WorkflowCache`
// and performs ONE isolated cast at the `JobRunner.start` boundary
// (`startWorkflow`). `PipelineCache` carries private fields, so a duck-typed
// cache cannot be assigned nominally — the runtime contract (`ctx.cache.clear()`
// between runs) is what actually matters and is honoured.
//
// ## Fan-out bound
//
// The fan-out bound is NOT a constant: it is `py.admission_capacity()` sampled
// at fan-out time and clamped against the caller's ceiling, so a workflow never
// dispatches more concurrent children than the 16-slot admission substrate can
// admit. Zero capacity waits (cancellably, bounded) rather than deadlocking on a
// concurrency of 0.

import { createHash } from "node:crypto";
import process from "node:process";
import { JobRunner } from "@autonome-research/thread-phase/session";
import type { JobRunHandle, JobRunOptions } from "@autonome-research/thread-phase/session";
import { boundedFanout } from "@autonome-research/thread-phase/patterns";
import type { FanOutResult } from "@autonome-research/thread-phase/patterns";
import type { JsonValue } from "../framing.js";
import { FrameDecoder, FrameTooLargeError, encodeFrame } from "../framing.js";
import { RpcPeer, RpcError, ErrorCode, FRAME_VERSION } from "../rpc.js";
import { BridgeJobStore, type BridgeCall, type WorkflowEvent } from "./jobstore.js";

// ── context / phase shapes (structural mirrors of the root-barrel types) ─────

/**
 * Pipeline-scoped cache. Faithful stand-in for thread-phase's `PipelineCache`
 * (only the root barrel exports the class); the orchestrator uses `clear()`.
 */
export class WorkflowCache {
  readonly #store: Map<string, unknown>;
  readonly #pending: Map<string, Promise<unknown>>;
  readonly #prefix: string;

  constructor(
    store: Map<string, unknown> = new Map<string, unknown>(),
    prefix = "",
    pending: Map<string, Promise<unknown>> = new Map<string, Promise<unknown>>(),
  ) {
    this.#store = store;
    this.#pending = pending;
    this.#prefix = prefix;
  }

  #k(key: string): string {
    return this.#prefix + key;
  }

  get<T>(key: string): T | undefined {
    return this.#store.get(this.#k(key)) as T | undefined;
  }

  set(key: string, value: unknown): void {
    this.#store.set(this.#k(key), value);
  }

  has(key: string): boolean {
    return this.#store.has(this.#k(key));
  }

  async getOrFetch<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
    const full = this.#k(key);
    if (this.#store.has(full)) return this.#store.get(full) as T;
    const inflight = this.#pending.get(full);
    if (inflight !== undefined) return inflight as Promise<T>;
    const run = fetcher()
      .then((value) => {
        this.#store.set(full, value);
        return value;
      })
      .finally(() => {
        this.#pending.delete(full);
      });
    this.#pending.set(full, run);
    return run;
  }

  clear(): void {
    if (this.#prefix === "") {
      this.#store.clear();
      return;
    }
    for (const key of [...this.#store.keys()]) {
      if (key.startsWith(this.#prefix)) this.#store.delete(key);
    }
  }

  get size(): number {
    return this.#store.size;
  }

  namespace(name: string): WorkflowCache {
    if (name === "") throw new Error("cache namespace must be non-empty");
    return new WorkflowCache(this.#store, `${this.#prefix}${name}:`, this.#pending);
  }
}

/** Structural mirror of thread-phase's `BasePipelineContext`. */
export interface WorkflowContext {
  readonly cache: WorkflowCache;
  stop?: { reason: string };
  signal?: AbortSignal;
  heartbeat?: () => Promise<void>;
}

/** Structural mirror of thread-phase's `Phase<TCtx>`. */
export interface WorkflowPhase<TCtx extends WorkflowContext> {
  readonly name: string;
  readonly checkpointKey?: string;
  run(ctx: TCtx): AsyncGenerator<WorkflowEvent, void>;
}

/** Terminal summary of a job run (thread-phase's `PipelineSummary`). */
export type WorkflowSummary = Awaited<JobRunHandle["result"]>;

// ── construction ─────────────────────────────────────────────────────────────

export interface JobRunnerOptions {
  /** Automatic heartbeat interval for active runs (ms). */
  readonly heartbeatMs?: number;
}

/** Build a `JobRunner` over the bridge-backed job store. */
export function createJobRunner(store: BridgeJobStore, options: JobRunnerOptions = {}): JobRunner {
  return new JobRunner(store, options.heartbeatMs !== undefined ? { heartbeatMs: options.heartbeatMs } : {});
}

type StartFn<TCtx extends WorkflowContext> = (
  jobId: string,
  phases: ReadonlyArray<WorkflowPhase<TCtx>>,
  ctx: TCtx,
  finalResult?: () => unknown,
  options?: JobRunOptions,
) => JobRunHandle;

/**
 * Start a job run with locally-declared phase/context types.
 *
 * The single cast in this function is the whole reason the root barrel is not
 * needed: `JobRunner.start` is generic over thread-phase's own `Phase` /
 * `BasePipelineContext`, which are structurally identical to the mirrors above.
 */
export function startWorkflow<TCtx extends WorkflowContext>(
  runner: JobRunner,
  jobId: string,
  phases: ReadonlyArray<WorkflowPhase<TCtx>>,
  ctx: TCtx,
  finalResult?: () => unknown,
  options?: JobRunOptions,
): JobRunHandle {
  const start = runner.start.bind(runner) as unknown as StartFn<TCtx>;
  return start(jobId, phases, ctx, finalResult, options);
}

// ── admission-clamped fan-out ────────────────────────────────────────────────

/** `() => available child-admission slots` (live `py.admission_capacity`). */
export type AdmissionCapacityProbe = () => Promise<number>;

export class AdmissionCapacityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AdmissionCapacityError";
  }
}

export interface CapacityWaitOptions {
  /** Poll interval while capacity is zero (ms). Default 25. */
  readonly pollMs?: number;
  /** Give up after this long with zero capacity (ms). Default 60_000. */
  readonly timeoutMs?: number;
  readonly signal?: AbortSignal;
}

function abortError(reason: string): Error {
  const err = new Error(reason);
  err.name = "AbortError";
  return err;
}

async function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted === true) throw abortError("cancelled while awaiting admission capacity");
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(abortError("cancelled while awaiting admission capacity"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * The concurrency a fan-out may use right now: `min(requested, capacity)`,
 * never above the live admission capacity and never below 1.
 *
 * With zero capacity the call waits (cancellably, bounded by `timeoutMs`)
 * instead of returning 0 — a bound of 0 would stall the workflow forever.
 */
export async function resolveFanoutConcurrency(
  capacity: AdmissionCapacityProbe,
  requested: number,
  options: CapacityWaitOptions = {},
): Promise<number> {
  const ceiling = Math.max(1, Math.floor(requested));
  const pollMs = options.pollMs ?? 25;
  const deadline = Date.now() + (options.timeoutMs ?? 60_000);
  for (;;) {
    if (options.signal?.aborted === true) {
      throw abortError("cancelled while awaiting admission capacity");
    }
    const available = Math.floor(await capacity());
    if (available >= 1) return Math.min(ceiling, available);
    if (Date.now() >= deadline) {
      throw new AdmissionCapacityError(
        `no child admission capacity available within ${options.timeoutMs ?? 60_000}ms`,
      );
    }
    await sleep(pollMs, options.signal);
  }
}

export interface AdmissionFanoutOptions<TItem, TResult> {
  readonly items: ReadonlyArray<TItem>;
  /** Live admission capacity; sampled once, at fan-out time. */
  readonly capacity: AdmissionCapacityProbe;
  readonly runner: (item: TItem, index: number, signal?: AbortSignal) => Promise<TResult>;
  /** Caller ceiling on concurrency (default: one per item). */
  readonly maxConcurrency?: number;
  readonly signal?: AbortSignal;
  readonly onItemError?: (event: { item: TItem; index: number; error: Error }) => void;
  readonly capacityWait?: CapacityWaitOptions;
}

export interface AdmissionFanoutOutcome<TResult> {
  /** The bound actually used — `min(ceiling, live capacity)`. */
  readonly concurrency: number;
  /** Position-stable per-item outcomes (`collect` mode: failures are values). */
  readonly results: ReadonlyArray<FanOutResult<TResult>>;
}

/**
 * `boundedFanout` whose concurrency is derived from live admission capacity.
 *
 * `collect` mode: one failing item never discards its siblings' work — the CAD
 * workflow's repair rounds need the per-part outcome of every part.
 */
export async function admissionBoundedFanout<TItem, TResult>(
  options: AdmissionFanoutOptions<TItem, TResult>,
): Promise<AdmissionFanoutOutcome<TResult>> {
  if (options.items.length === 0) return { concurrency: 0, results: [] };
  const ceiling = Math.min(options.maxConcurrency ?? options.items.length, options.items.length);
  const concurrency = await resolveFanoutConcurrency(options.capacity, ceiling, {
    ...(options.capacityWait ?? {}),
    ...(options.signal !== undefined ? { signal: options.signal } : {}),
  });
  const results = await boundedFanout<TItem, TResult>({
    items: options.items,
    concurrency,
    mode: "collect",
    runner: options.runner,
    ...(options.signal !== undefined ? { signal: options.signal } : {}),
    ...(options.onItemError !== undefined ? { onItemError: options.onItemError } : {}),
  });
  return { concurrency, results };
}

// ── hashing / checkpoint helpers ─────────────────────────────────────────────

/** Canonical JSON (recursively key-sorted) — the hashing pre-image. */
export function canonicalJson(value: JsonValue): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const keys = Object.keys(value).sort();
  const parts = keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k] ?? null)}`);
  return `{${parts.join(",")}}`;
}

/** SHA-256 over canonical JSON: the workflow's input/output hash. */
export function hashJson(value: JsonValue): string {
  return createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

/** Checkpoint keys a prior run completed, read from its durable event log. */
export function completedCheckpointKeys(events: Iterable<{ data: unknown }>): Set<string> {
  const keys = new Set<string>();
  for (const event of events) {
    const data = event.data;
    if (data === null || typeof data !== "object") continue;
    const record = data as { type?: unknown; checkpointKey?: unknown };
    if (record.type === "phase_complete" && typeof record.checkpointKey === "string") {
      keys.add(record.checkpointKey);
    }
  }
  return keys;
}

// ── workflow definitions + the runner process's method surface ───────────────

/** What a workflow definition needs from the bridge. */
export interface WorkflowDeps {
  readonly store: BridgeJobStore;
  readonly call: BridgeCall;
}

/**
 * A named, versioned deterministic workflow.
 *
 * `version` participates in every checkpoint: a resumed run may only skip a
 * phase whose checkpoint was written by the same workflow version and the same
 * input hash (digest §5 — "resume continues from a verified checkpoint").
 */
export interface WorkflowDefinition<TInput, TCtx extends WorkflowContext> {
  readonly name: string;
  readonly version: string;
  parseInput(raw: JsonValue): TInput;
  /** JSON projection of the input that participates in checkpoint hashes. */
  inputDigest(input: TInput): JsonValue;
  createContext(input: TInput, deps: WorkflowDeps, jobId: string): TCtx;
  phases(input: TInput, deps: WorkflowDeps, jobId: string): ReadonlyArray<WorkflowPhase<TCtx>>;
  finalResult(ctx: TCtx): JsonValue;
  /** Rebuild the state a skipped phase would have produced, from checkpoints. */
  rehydrate?(ctx: TCtx, checkpoints: ReadonlyMap<string, JsonValue>): void;
}

/** The private request methods the workflow-runner process serves. */
export const WORKFLOW_RUN = "workflow.run";
export const WORKFLOW_RESUME = "workflow.resume";
export const WORKFLOW_CANCEL = "workflow.cancel";
export const WORKFLOW_STATUS = "workflow.status";

/** Minimal peer surface (`RpcPeer`) the registration needs. */
export interface WorkflowPeer {
  on(method: string, handler: (params: { [k: string]: JsonValue }) => Promise<JsonValue>): void;
  request(
    method: string,
    params?: { [k: string]: JsonValue },
    timeoutMs?: number,
  ): Promise<JsonValue>;
}

export interface WorkflowServiceDeps<TInput, TCtx extends WorkflowContext> {
  readonly store: BridgeJobStore;
  readonly runner: JobRunner;
  readonly call: BridgeCall;
  readonly definitions: ReadonlyArray<WorkflowDefinition<TInput, TCtx>>;
}

interface RunOutcome {
  readonly job_id: string;
  readonly status: string;
  readonly summary: JsonValue;
  readonly resumed_from: string | null;
  readonly skipped_phases: string[];
}

/**
 * Register `workflow.{run,resume,cancel,status}` on a peer.
 *
 * `workflow.run` blocks until the job reaches a terminal state (so the Python
 * caller gets the outcome in the response) while `workflow.cancel` is answered
 * concurrently — that is what makes cooperative cancellation observable.
 */
export function registerWorkflowMethods<TInput, TCtx extends WorkflowContext>(
  peer: WorkflowPeer,
  deps: WorkflowServiceDeps<TInput, TCtx>,
): void {
  const byName = new Map(deps.definitions.map((d) => [d.name, d] as const));
  const resolve = (raw: JsonValue | undefined): WorkflowDefinition<TInput, TCtx> => {
    const name = typeof raw === "string" ? raw : "";
    const definition = byName.get(name);
    if (definition === undefined) {
      throw new RpcError(ErrorCode.INVALID_PARAMS, `unknown workflow '${name}'`);
    }
    return definition;
  };

  const createJob = async (
    definition: WorkflowDefinition<TInput, TCtx>,
    input: TInput,
    requested: JsonValue | undefined,
  ): Promise<string> => {
    const digest = definition.inputDigest(input);
    // Python may mint the job id so it can cancel/inspect a run in flight.
    return typeof requested === "string" && requested !== ""
      ? deps.store.createJobWithId(requested, definition.name, digest)
      : deps.store.createJob(definition.name, digest);
  };

  peer.on(WORKFLOW_RUN, async (params) => {
    const definition = resolve(params.workflow);
    const input = definition.parseInput(params.input ?? null);
    const jobId = await createJob(definition, input, params.job_id);
    const outcome = await execute(deps, definition, input, jobId, null);
    return outcome as unknown as JsonValue;
  });

  peer.on(WORKFLOW_RESUME, async (params) => {
    const definition = resolve(params.workflow);
    const priorJobId = String(params.job_id ?? "");
    const prior = await deps.store.storedJob(priorJobId);
    if (prior === null) {
      throw new RpcError(ErrorCode.INVALID_PARAMS, `unknown job '${priorJobId}'`);
    }
    const input = definition.parseInput(
      params.input !== undefined && params.input !== null ? params.input : prior.input,
    );
    const jobId = await createJob(definition, input, params.resume_job_id);
    const outcome = await execute(deps, definition, input, jobId, priorJobId);
    return outcome as unknown as JsonValue;
  });

  peer.on(WORKFLOW_CANCEL, async (params) => {
    const jobId = String(params.job_id ?? "");
    const reason = typeof params.reason === "string" ? params.reason : "cancelled";
    const cancelled = deps.runner.cancel(jobId, reason);
    return { job_id: jobId, cancelled };
  });

  peer.on(WORKFLOW_STATUS, async (params) => {
    const jobId = String(params.job_id ?? "");
    const stored = await deps.store.storedJob(jobId);
    if (stored === null) return { job_id: jobId, status: null };
    return { job_id: jobId, status: stored.status, event_count: stored.eventCount };
  });
}

async function execute<TInput, TCtx extends WorkflowContext>(
  deps: WorkflowServiceDeps<TInput, TCtx>,
  definition: WorkflowDefinition<TInput, TCtx>,
  input: TInput,
  jobId: string,
  resumeOf: string | null,
): Promise<RunOutcome> {
  const ctx = definition.createContext(input, { store: deps.store, call: deps.call }, jobId);
  let phases = definition.phases(input, { store: deps.store, call: deps.call }, jobId);
  const skipped: string[] = [];

  if (resumeOf !== null) {
    // Resume: skip only phases whose prior checkpoint VERIFIES against this
    // workflow version + input hash, and rehydrate their outputs into ctx.
    const completed = completedCheckpointKeys(await deps.store.getEvents(resumeOf, 0));
    const mirrors = await deps.store.listCheckpoints(resumeOf);
    const inputHash = hashJson(definition.inputDigest(input));
    const verified = new Map<string, JsonValue>();
    for (const key of completed) {
      const record = mirrors.get(key);
      if (record === undefined) continue;
      if (record.workflowVersion !== definition.version) continue;
      if (record.inputHash !== inputHash) continue;
      verified.set(key, record.value);
    }
    if (verified.size > 0) {
      definition.rehydrate?.(ctx, verified);
      phases = phases.filter((phase) => {
        const key = phase.checkpointKey;
        if (key !== undefined && verified.has(key)) {
          skipped.push(phase.name);
          return false;
        }
        return true;
      });
    }
  }

  const handle = startWorkflow(deps.runner, jobId, phases, ctx, () => definition.finalResult(ctx), {
    launchSource: "hephaestus-workflow",
    sessionId: jobId,
  });
  let status = "completed";
  let summary: JsonValue = null;
  try {
    const result = await handle.result;
    status = result.status;
    summary = {
      status: result.status,
      eventCount: result.eventCount,
      ...(result.reason !== undefined ? { reason: result.reason } : {}),
    };
  } catch (err) {
    const error = err as Error;
    status = error.name === "AbortError" ? "cancelled" : "failed";
    summary = { status, error: error.message };
  }
  return {
    job_id: jobId,
    status,
    summary,
    resumed_from: resumeOf,
    skipped_phases: skipped,
  };
}

// ── stdio entry: the supervised workflow-runner process ─────────────────────

export interface WorkflowSidecarOptions {
  readonly stdin?: NodeJS.ReadableStream;
  readonly stdout?: NodeJS.WritableStream;
  readonly stderr?: NodeJS.WritableStream;
  /** Injected in tests; defaults to the CAD workflow definition. */
  readonly definitions?: ReadonlyArray<WorkflowDefinition<never, never>>;
}

/**
 * Run the workflow-runner process: a *second* supervised Node entry whose only
 * outbound traffic is `py.*` (jobstore / admission capacity / delegate / tool
 * dispatch). It never owns a Pi session — part agents live in the main sidecar
 * and are reached through the Python delegation service, exactly as digest §3
 * requires ("thread-phase calls the session service directly — never
 * recursively invokes the tool").
 */
export async function runWorkflowSidecar(options: WorkflowSidecarOptions = {}): Promise<void> {
  const stdout = options.stdout ?? process.stdout;
  const stderr = options.stderr ?? process.stderr;
  const stdin = options.stdin ?? process.stdin;
  const log = (message: string): void => {
    stderr.write(`[heph-workflow] ${message}\n`);
  };
  const peer = new RpcPeer((frame) => {
    stdout.write(encodeFrame(frame));
  });
  const call: BridgeCall = (method, params) => peer.request(method, params);
  const store = new BridgeJobStore(call);
  const runner = createJobRunner(store, { heartbeatMs: 1_000 });
  // Deferred import: the CAD workflow imports this module's fan-out helper, and
  // a dynamic import keeps that dependency one-directional.
  const { cadWorkflowDefinition } = await import("./cad_workflow.js");
  const definitions =
    options.definitions ??
    ([cadWorkflowDefinition] as unknown as ReadonlyArray<WorkflowDefinition<never, never>>);
  registerWorkflowMethods(
    peer,
    // One cast: the peer registration is generic per definition, the process
    // hosts a heterogeneous list.
    {
      store,
      runner,
      call,
      definitions,
    } as unknown as WorkflowServiceDeps<never, never>,
  );
  peer.on("shutdown", async () => {
    log("shutdown requested");
    queueMicrotask(() => process.exit(0));
    return { ok: true };
  });

  const decoder = new FrameDecoder();
  stdin.on("data", (chunk: Buffer) => {
    let frames: Buffer[];
    try {
      frames = decoder.push(chunk);
    } catch (err) {
      log(
        err instanceof FrameTooLargeError
          ? `fatal framing error: ${err.message}`
          : `fatal framing error: ${String(err)}`,
      );
      process.exit(1);
      return;
    }
    for (const frame of frames) void peer.handleFrame(frame);
  });
  stdin.on("end", () => process.exit(0));
  log(`started pid=${process.pid} hv=${FRAME_VERSION}`);
}

/**
 * True when this process was started as the workflow runner
 * (`node .../workflows/runner.js`).
 *
 * Deliberately asks only about `process.argv[1]` — what the supervisor spawned.
 * An earlier version also required `import.meta.url` to end in
 * `/workflows/runner.js`, which held for `tsc` output (one module per file) but
 * is false for the bundled sidecar the wheel ships: code splitting hoists this
 * module's body into a shared chunk, so `import.meta.url` names the chunk and
 * the runner silently exited 0 at every spawn. `argv[1]` states the intent
 * directly and is independent of how the code was packaged.
 *
 * The dropped half guarded against this module being *imported* by a different
 * entry that happened to be invoked as `runner.js` — which cannot occur: the
 * session sidecar is spawned as `main.js`, so the check is false there.
 */
function isProcessEntry(): boolean {
  const entry = process.argv[1];
  if (entry === undefined) return false;
  return entry.endsWith("workflows/runner.js");
}

if (isProcessEntry()) {
  void runWorkflowSidecar();
}
