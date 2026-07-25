// Thread-phase `JobStore` implemented entirely over the private Python bridge.
//
// The packaged sidecar ships NO native SQLite addon and never opens a database
// (repo_conventions Stage S disposition 4; DESIGN.md `workflows/jobstore.ts`):
// every read and write here becomes one `py.jobstore_*` request answered by
// `hephaestus.agent_bridge.jobstore.JobStore` over the opstore `state.db`
// (`tp_`-prefixed tables). Thread-phase's `SqliteJobStore` is never constructed.
//
// Types come from the `@autonome-research/thread-phase/session` subpath only —
// the root barrel eagerly loads the transitive `openai` SDK (Stage S) and is
// eslint-forbidden inside agent/. Every import here is `import type`, so this
// module contributes zero thread-phase runtime code.
//
// ## Durable layout (CROSS-LANGUAGE CONTRACT with agent_bridge/workflows.py)
//
//   namespace `tp:jobs`    key `<jobId>`                     -> StoredJob (JSON)
//   namespace `tp:events`  key `<jobId>#<eventId, 12 digits>`-> StoredEvent (JSON)
//   namespace `tp:meta`    key `event_seq`                    -> last event id
//   namespace `tp:checkpoints` key `<jobId>#<checkpointKey>`  -> WorkflowCheckpoint
//
// The `tp:checkpoints` rows MIRROR the normative `tp_jobstore_checkpoints` table
// written by `py.jobstore_checkpoint`; the bridge has no checkpoint *read*
// method, and resume must verify a checkpoint's workflow version and input hash
// before skipping a phase.
//
// Field names in the stored records are the camelCase names of thread-phase's
// `JobRecord`/`EventRecord`, with `Date` fields as ISO-8601 strings. Python reads
// the same rows to replay durable events and to project orphaned `RUNNING` jobs
// as `interrupted`; changing a namespace, key format, or field name is a wire
// break on both sides.
//
// ## Atomicity
//
// The five bridge primitives are get/put/list/delete/checkpoint — there is no
// conditional write. First-writer-wins terminal transitions and
// `acquireExclusive` are therefore implemented as read-modify-write sequences
// serialized through an in-process mutex (`#serialize`). That is sufficient
// because exactly one workflow-runner process owns a job at a time: the Python
// `WorkflowService` supervises a single runner and owns cross-process
// exclusivity (leases + admission). Two concurrent runner processes writing the
// same job id would race — a documented limitation, not a supported mode.

import { randomUUID } from "node:crypto";
import type { JsonValue } from "../framing.js";
import type {
  EventRecord,
  GetJobOptions,
  JobFinalization,
  JobOwnership,
  JobRecord,
  JobStatus,
  JobStore,
  ListJobsOptions,
} from "@autonome-research/thread-phase/session";

/** One durable pipeline event (thread-phase's `PipelineEvent`, structurally). */
export type WorkflowEvent = Parameters<JobStore["appendEvent"]>[1];

/** Statuses that are actually persisted (`STALE` is computed at read time). */
export type PersistedJobStatus = Exclude<JobStatus, "STALE">;

/** Minimal bridge request surface (`RpcPeer.request`). */
export type BridgeCall = (
  method: string,
  params: { [k: string]: JsonValue },
) => Promise<JsonValue>;

/** Durable job row as stored by the bridge (ISO dates, JSON-safe values). */
export interface StoredJob {
  id: string;
  name: string;
  input: JsonValue;
  status: PersistedJobStatus;
  result: JsonValue;
  error: string | null;
  eventCount: number;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  sessionId?: string;
  pid?: number;
  ppid?: number;
  cwd?: string;
  hostname?: string;
  ownerId?: string;
  launchSource?: string;
  heartbeatEnabled?: boolean;
  heartbeatAt?: string;
  /** Set by Python when a terminal is synthesized (e.g. `"interrupted"`). */
  failureClass?: string;
}

/** Durable event row as stored by the bridge. */
export interface StoredEvent {
  id: number;
  jobId: string;
  eventType: string;
  data: JsonValue;
  createdAt: string;
}

/** Resumable phase checkpoint (workflow version + input/output hashes). */
export interface WorkflowCheckpoint {
  readonly jobId: string;
  readonly checkpointKey: string;
  readonly workflowVersion: string;
  readonly inputHash: string;
  readonly outputHash: string;
  readonly value: JsonValue;
}

export interface BridgeJobStoreOptions {
  /** Namespace prefix; defaults to `tp` (the cross-language contract). */
  readonly namespacePrefix?: string;
  /** Job-id factory (injected in tests for deterministic ids). */
  readonly newJobId?: () => string;
  /** Clock (injected in tests). */
  readonly now?: () => Date;
}

const DEFAULT_LIST_LIMIT = 50;
const EVENT_KEY_DIGITS = 12;
const TERMINAL_STATUSES: ReadonlySet<PersistedJobStatus> = new Set<PersistedJobStatus>([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "ABANDONED",
]);

/** `tp:events` key for one event id — zero-padded so prefix listing sorts. */
export function eventKey(jobId: string, eventId: number): string {
  return `${jobId}#${String(eventId).padStart(EVENT_KEY_DIGITS, "0")}`;
}

/** `tp:checkpoints` key for one phase checkpoint. */
export function checkpointKey(jobId: string, key: string): string {
  return `${jobId}#${key}`;
}

function toJson(value: unknown): JsonValue {
  if (value === undefined) return null;
  return JSON.parse(JSON.stringify(value)) as JsonValue;
}

function isRecord(value: JsonValue | null): value is { [k: string]: JsonValue } {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isLive(status: PersistedJobStatus): boolean {
  return !TERMINAL_STATUSES.has(status);
}

/** Rehydrate the public `JobRecord` (Date fields) from its stored form. */
export function toJobRecord(stored: StoredJob, status: JobStatus = stored.status): JobRecord {
  const record: JobRecord = {
    id: stored.id,
    name: stored.name,
    input: stored.input,
    status,
    result: stored.result,
    error: stored.error,
    eventCount: stored.eventCount,
    createdAt: new Date(stored.createdAt),
    startedAt: stored.startedAt === null ? null : new Date(stored.startedAt),
    completedAt: stored.completedAt === null ? null : new Date(stored.completedAt),
    ...(stored.sessionId !== undefined ? { sessionId: stored.sessionId } : {}),
    ...(stored.pid !== undefined ? { pid: stored.pid } : {}),
    ...(stored.ppid !== undefined ? { ppid: stored.ppid } : {}),
    ...(stored.cwd !== undefined ? { cwd: stored.cwd } : {}),
    ...(stored.hostname !== undefined ? { hostname: stored.hostname } : {}),
    ...(stored.ownerId !== undefined ? { ownerId: stored.ownerId } : {}),
    ...(stored.launchSource !== undefined ? { launchSource: stored.launchSource } : {}),
    ...(stored.heartbeatEnabled !== undefined
      ? { heartbeatEnabled: stored.heartbeatEnabled }
      : {}),
    ...(stored.heartbeatAt !== undefined ? { heartbeatAt: new Date(stored.heartbeatAt) } : {}),
  };
  return record;
}

function toEventRecord(stored: StoredEvent): EventRecord {
  return {
    id: stored.id,
    jobId: stored.jobId,
    eventType: stored.eventType,
    data: stored.data as unknown as WorkflowEvent,
    createdAt: new Date(stored.createdAt),
  };
}

/**
 * Thread-phase `JobStore` whose every operation is a `py.jobstore_*` bridge
 * call. Construct with the sidecar's `RpcPeer.request`.
 */
export class BridgeJobStore implements JobStore {
  readonly #call: BridgeCall;
  readonly #jobsNs: string;
  readonly #eventsNs: string;
  readonly #metaNs: string;
  readonly #checkpointsNs: string;
  readonly #newJobId: () => string;
  readonly #now: () => Date;
  #tail: Promise<unknown> = Promise.resolve();
  #nextEventId: number | undefined;

  constructor(call: BridgeCall, options: BridgeJobStoreOptions = {}) {
    const prefix = options.namespacePrefix ?? "tp";
    this.#call = call;
    this.#jobsNs = `${prefix}:jobs`;
    this.#eventsNs = `${prefix}:events`;
    this.#metaNs = `${prefix}:meta`;
    this.#checkpointsNs = `${prefix}:checkpoints`;
    this.#newJobId = options.newJobId ?? (() => `job-${randomUUID()}`);
    this.#now = options.now ?? (() => new Date());
  }

  // -- bridge primitives ----------------------------------------------------

  async #get(namespace: string, key: string): Promise<JsonValue | null> {
    const raw = await this.#call("py.jobstore_get", { namespace, key });
    if (!isRecord(raw)) return null;
    const value = raw.value;
    return value === undefined ? null : value;
  }

  async #put(namespace: string, key: string, value: JsonValue): Promise<void> {
    await this.#call("py.jobstore_put", { namespace, key, value });
  }

  async #delete(namespace: string, key: string): Promise<boolean> {
    const raw = await this.#call("py.jobstore_delete", { namespace, key });
    return isRecord(raw) && raw.deleted === true;
  }

  async #list(
    namespace: string,
    prefix?: string,
    limit?: number,
  ): Promise<Array<{ key: string; value: JsonValue }>> {
    const params: { [k: string]: JsonValue } = { namespace };
    if (prefix !== undefined) params.prefix = prefix;
    if (limit !== undefined) params.limit = limit;
    const raw = await this.#call("py.jobstore_list", params);
    if (!isRecord(raw) || !Array.isArray(raw.items)) return [];
    const items: Array<{ key: string; value: JsonValue }> = [];
    for (const entry of raw.items) {
      if (!isRecord(entry) || typeof entry.key !== "string") continue;
      items.push({ key: entry.key, value: entry.value ?? null });
    }
    return items;
  }

  /** Serialize read-modify-write sequences so they are atomic in this process. */
  #serialize<T>(body: () => Promise<T>): Promise<T> {
    const run = this.#tail.then(body, body);
    this.#tail = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }

  // -- job records ----------------------------------------------------------

  async #readJob(jobId: string): Promise<StoredJob | null> {
    const raw = await this.#get(this.#jobsNs, jobId);
    return isRecord(raw) ? (raw as unknown as StoredJob) : null;
  }

  async #writeJob(job: StoredJob): Promise<void> {
    await this.#put(this.#jobsNs, job.id, job as unknown as JsonValue);
  }

  /** The stored (pre-rehydration) row — used by workflow resume and tests. */
  storedJob(jobId: string): Promise<StoredJob | null> {
    return this.#readJob(jobId);
  }

  async createJob(name: string, input: unknown): Promise<string> {
    return this.createJobWithId(this.#newJobId(), name, input);
  }

  /**
   * `createJob` with a caller-supplied id.
   *
   * The Python `WorkflowService` mints the id before launching so it can cancel
   * or inspect the run while `workflow.run` is still in flight. Re-creating an
   * existing id is refused — a job row is never silently reset.
   */
  async createJobWithId(id: string, name: string, input: unknown): Promise<string> {
    return this.#serialize(async () => {
      if ((await this.#readJob(id)) !== null) throw new Error(`job ${id} already exists`);
      const job: StoredJob = {
        id,
        name,
        input: toJson(input),
        status: "PENDING",
        result: null,
        error: null,
        eventCount: 0,
        createdAt: this.#now().toISOString(),
        startedAt: null,
        completedAt: null,
      };
      await this.#writeJob(job);
      return id;
    });
  }

  async acquireExclusive(name: string, input: unknown): Promise<string | null> {
    return this.#serialize(async () => {
      for (const entry of await this.#list(this.#jobsNs)) {
        if (!isRecord(entry.value)) continue;
        const job = entry.value as unknown as StoredJob;
        if (job.name === name && job.status === "RUNNING") return null;
      }
      const id = this.#newJobId();
      const startedAt = this.#now().toISOString();
      const job: StoredJob = {
        id,
        name,
        input: toJson(input),
        status: "RUNNING",
        result: null,
        error: null,
        eventCount: 0,
        createdAt: startedAt,
        startedAt,
        completedAt: null,
      };
      await this.#writeJob(job);
      return id;
    });
  }

  async setRunning(jobId: string, ownership?: JobOwnership): Promise<boolean> {
    return this.#serialize(async () => {
      const job = await this.#readJob(jobId);
      if (job === null) return false;
      if (job.status !== "PENDING" && job.status !== "RUNNING") return false;
      const claimedOwner = ownership?.ownerId;
      if (job.ownerId !== undefined && claimedOwner !== undefined && job.ownerId !== claimedOwner) {
        return false;
      }
      const next: StoredJob = { ...job, status: "RUNNING" };
      if (ownership !== undefined) applyOwnership(next, ownership);
      next.startedAt = job.startedAt ?? this.#now().toISOString();
      await this.#writeJob(next);
      return true;
    });
  }

  /** Shared terminal CAS: only a live row owned by `ownerId` may transition. */
  async #finalize(
    jobId: string,
    status: PersistedJobStatus,
    patch: { result?: JsonValue; error?: string | null },
    ownerId?: string,
  ): Promise<StoredJob | null> {
    const job = await this.#readJob(jobId);
    if (job === null || !isLive(job.status)) return null;
    if (ownerId !== undefined && job.ownerId !== undefined && job.ownerId !== ownerId) return null;
    const next: StoredJob = {
      ...job,
      status,
      completedAt: this.#now().toISOString(),
      ...(patch.result !== undefined ? { result: patch.result } : {}),
      ...(patch.error !== undefined ? { error: patch.error } : {}),
    };
    await this.#writeJob(next);
    return next;
  }

  setCompleted(jobId: string, result: unknown, ownerId?: string): Promise<boolean> {
    return this.#serialize(async () =>
      (await this.#finalize(jobId, "COMPLETED", { result: toJson(result) }, ownerId)) !== null,
    );
  }

  setFailed(jobId: string, error: string, ownerId?: string): Promise<boolean> {
    return this.#serialize(async () =>
      (await this.#finalize(jobId, "FAILED", { error }, ownerId)) !== null,
    );
  }

  setCancelled(jobId: string, reason: string, ownerId?: string): Promise<boolean> {
    return this.#serialize(async () =>
      (await this.#finalize(jobId, "CANCELLED", { error: reason }, ownerId)) !== null,
    );
  }

  setAbandoned(jobId: string, reason: string): Promise<boolean> {
    return this.#serialize(async () =>
      (await this.#finalize(jobId, "ABANDONED", { error: reason })) !== null,
    );
  }

  setAbandonedIfStale(
    jobId: string,
    staleBefore: Date,
    reason: string,
    expectedOwnerId?: string,
  ): Promise<boolean> {
    return this.#serialize(
      async () => (await this.#abandonIfStale(jobId, staleBefore, reason, expectedOwnerId)) !== null,
    );
  }

  async #abandonIfStale(
    jobId: string,
    staleBefore: Date,
    reason: string,
    expectedOwnerId?: string,
  ): Promise<StoredJob | null> {
    const job = await this.#readJob(jobId);
    if (job === null || job.status !== "RUNNING") return null;
    if (job.heartbeatAt !== undefined && new Date(job.heartbeatAt) >= staleBefore) return null;
    return this.#finalize(jobId, "ABANDONED", { error: reason }, expectedOwnerId);
  }

  finalizeJob(jobId: string, finalization: JobFinalization): Promise<EventRecord | null> {
    return this.#serialize(async () => {
      const patch: { result?: JsonValue; error?: string | null } =
        finalization.status === "COMPLETED"
          ? { result: toJson(finalization.result) }
          : { error: finalization.error ?? "" };
      const job = await this.#finalize(jobId, finalization.status, patch, finalization.ownerId);
      if (job === null) return null;
      return this.#appendEvent(job, finalization.event);
    });
  }

  finalizeAbandonedIfStale(
    jobId: string,
    staleBefore: Date,
    reason: string,
    expectedOwnerId?: string,
  ): Promise<EventRecord | null> {
    return this.#serialize(async () => {
      const job = await this.#abandonIfStale(jobId, staleBefore, reason, expectedOwnerId);
      if (job === null) return null;
      return this.#appendEvent(job, { type: "error", message: reason } as WorkflowEvent);
    });
  }

  async heartbeat(jobId: string, ownerId?: string): Promise<void> {
    await this.#serialize(async () => {
      const job = await this.#readJob(jobId);
      if (job === null || job.status !== "RUNNING") return;
      if (ownerId !== undefined && job.ownerId !== undefined && job.ownerId !== ownerId) return;
      await this.#writeJob({ ...job, heartbeatAt: this.#now().toISOString() });
    });
  }

  enableHeartbeat(jobId: string, ownerId: string): Promise<boolean> {
    return this.#serialize(async () => {
      const job = await this.#readJob(jobId);
      if (job === null || job.status !== "RUNNING") return false;
      if (job.ownerId !== undefined && job.ownerId !== ownerId) return false;
      await this.#writeJob({
        ...job,
        ownerId,
        heartbeatEnabled: true,
        heartbeatAt: this.#now().toISOString(),
      });
      return true;
    });
  }

  async getJob(jobId: string, options?: GetJobOptions): Promise<JobRecord | null> {
    const job = await this.#readJob(jobId);
    if (job === null) return null;
    return toJobRecord(job, this.#readStatus(job, options?.staleAfterMs));
  }

  /** `STALE` is never persisted: it is computed from `heartbeatAt` on read. */
  #readStatus(job: StoredJob, staleAfterMs?: number): JobStatus {
    if (staleAfterMs === undefined || job.status !== "RUNNING") return job.status;
    if (job.heartbeatAt === undefined) return job.status;
    const cutoff = this.#now().getTime() - staleAfterMs;
    return new Date(job.heartbeatAt).getTime() < cutoff ? "STALE" : job.status;
  }

  async listJobs(options: ListJobsOptions = {}): Promise<JobRecord[]> {
    const entries = await this.#list(this.#jobsNs);
    const records: JobRecord[] = [];
    for (const entry of entries) {
      if (!isRecord(entry.value)) continue;
      const job = entry.value as unknown as StoredJob;
      if (options.name !== undefined && job.name !== options.name) continue;
      const status = this.#readStatus(job, options.staleAfterMs);
      if (options.status !== undefined && status !== options.status) continue;
      records.push(toJobRecord(job, status));
    }
    // Newest first, matching the bundled SqliteJobStore's `created_at DESC`.
    records.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
    return records.slice(0, options.limit ?? DEFAULT_LIST_LIMIT);
  }

  // -- durable event log ----------------------------------------------------

  async #reserveEventId(): Promise<number> {
    if (this.#nextEventId === undefined) {
      const raw = await this.#get(this.#metaNs, "event_seq");
      this.#nextEventId = typeof raw === "number" ? raw + 1 : 1;
    }
    const id = this.#nextEventId;
    this.#nextEventId = id + 1;
    await this.#put(this.#metaNs, "event_seq", id);
    return id;
  }

  /** Append + bump the job's `eventCount` (caller already holds the mutex). */
  async #appendEvent(job: StoredJob, event: WorkflowEvent): Promise<EventRecord> {
    const id = await this.#reserveEventId();
    const stored: StoredEvent = {
      id,
      jobId: job.id,
      eventType: String((event as { type?: unknown }).type ?? "unknown"),
      data: toJson(event),
      createdAt: this.#now().toISOString(),
    };
    await this.#put(this.#eventsNs, eventKey(job.id, id), stored as unknown as JsonValue);
    await this.#writeJob({ ...job, eventCount: job.eventCount + 1 });
    return toEventRecord(stored);
  }

  appendEvent(jobId: string, event: WorkflowEvent): Promise<number> {
    return this.#serialize(async () => {
      const job = await this.#readJob(jobId);
      if (job === null) throw new Error(`unknown job ${jobId}`);
      const record = await this.#appendEvent(job, event);
      return record.id;
    });
  }

  async getEvents(jobId: string, afterId = 0): Promise<EventRecord[]> {
    const entries = await this.#list(this.#eventsNs, `${jobId}#`);
    const records: EventRecord[] = [];
    for (const entry of entries) {
      if (!isRecord(entry.value)) continue;
      const stored = entry.value as unknown as StoredEvent;
      if (stored.id <= afterId) continue;
      records.push(toEventRecord(stored));
    }
    records.sort((a, b) => a.id - b.id);
    return records;
  }

  // -- resumable checkpoints (beyond the JobStore interface) ---------------

  /**
   * Persist one resumable phase checkpoint with its workflow version and
   * input/output hashes (`py.jobstore_checkpoint`; digest §5).
   *
   * Two writes, deliberately: `py.jobstore_checkpoint` fills the normative
   * `tp_jobstore_checkpoints` table (what Python verifies and what survives as
   * the durable record), and a `tp:checkpoints` key/value mirror gives the
   * sidecar a read path — the bridge exposes no checkpoint *read* method, and
   * resume must verify version/input hashes before skipping a phase.
   */
  async checkpoint(record: WorkflowCheckpoint): Promise<void> {
    await this.#call("py.jobstore_checkpoint", {
      job_id: record.jobId,
      checkpoint_key: record.checkpointKey,
      workflow_version: record.workflowVersion,
      input_hash: record.inputHash,
      output_hash: record.outputHash,
      value: record.value,
    });
    await this.#put(
      this.#checkpointsNs,
      checkpointKey(record.jobId, record.checkpointKey),
      record as unknown as JsonValue,
    );
  }

  /** The mirrored checkpoint for `(jobId, checkpointKey)`, if one was written. */
  async readCheckpoint(jobId: string, key: string): Promise<WorkflowCheckpoint | null> {
    const raw = await this.#get(this.#checkpointsNs, checkpointKey(jobId, key));
    return isRecord(raw) ? (raw as unknown as WorkflowCheckpoint) : null;
  }

  /** Every mirrored checkpoint for a job, keyed by `checkpointKey`. */
  async listCheckpoints(jobId: string): Promise<Map<string, WorkflowCheckpoint>> {
    const entries = await this.#list(this.#checkpointsNs, `${jobId}#`);
    const found = new Map<string, WorkflowCheckpoint>();
    for (const entry of entries) {
      if (!isRecord(entry.value)) continue;
      const record = entry.value as unknown as WorkflowCheckpoint;
      found.set(record.checkpointKey, record);
    }
    return found;
  }

  /** Drop a job row (its events stay unless removed explicitly). */
  deleteJob(jobId: string): Promise<boolean> {
    return this.#serialize(() => this.#delete(this.#jobsNs, jobId));
  }

  /** No-op: the durable connection lives in Python, not in the sidecar. */
  close(): void {}
}

function applyOwnership(job: StoredJob, ownership: JobOwnership): void {
  if (ownership.sessionId !== undefined) job.sessionId = ownership.sessionId;
  if (ownership.pid !== undefined) job.pid = ownership.pid;
  if (ownership.ppid !== undefined) job.ppid = ownership.ppid;
  if (ownership.cwd !== undefined) job.cwd = ownership.cwd;
  if (ownership.hostname !== undefined) job.hostname = ownership.hostname;
  if (ownership.ownerId !== undefined) job.ownerId = ownership.ownerId;
  if (ownership.launchSource !== undefined) job.launchSource = ownership.launchSource;
  if (ownership.heartbeatEnabled !== undefined) job.heartbeatEnabled = ownership.heartbeatEnabled;
}
