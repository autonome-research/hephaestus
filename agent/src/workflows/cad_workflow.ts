// The Stage 2 deterministic CAD workflow (arch §4.5, digest §5):
//
//   bounded project decomposition
//     -> part delegation            (py.delegate — NEVER the model-visible tool)
//     -> cross-part run_checks      (py.tool_dispatch, project scope)
//     -> capped repair              (max 2 repair rounds PER PART)
//     -> final verification
//
// Properties this file is responsible for:
//
// * **Deterministic.** No model is consulted at this layer. The decomposition is
//   the caller's bounded part list, capped at `MAX_PARTS`; every phase's control
//   flow is a function of durable bridge results only.
// * **Delegation, not recursion.** Part work is dispatched through the Python
//   delegation service (`py.delegate`). The workflow never calls
//   `delegate_part_agent`, so it cannot recurse through the model's tool surface
//   (digest §3 "thread-phase calls the session service directly").
// * **Admission-bounded fan-out.** Concurrency comes from live
//   `py.admission_capacity()` at fan-out time (see `runner.ts`), never a
//   constant, so children can always be admitted into the 16 global slots.
// * **Checkpointed.** Every phase writes a checkpoint carrying the workflow
//   version and its input/output hashes before it completes, so a resumed run
//   skips only phases whose checkpoint verifies.
// * **Cooperatively cancellable.** Each phase, and each repair round, observes
//   `ctx.signal` and unwinds with an `AbortError` that `JobRunner` persists as
//   the single `CANCELLED` terminal.
//
// Geometry truth stays where it belongs: the build artifact. This workflow's
// records are orchestration history only (mission rule 6).

import type { JsonValue } from "../framing.js";
import { makeInvocation, type TrustedInvocation } from "../tools/invocation.js";
import type { BridgeCall, WorkflowEvent } from "./jobstore.js";
import {
  admissionBoundedFanout,
  hashJson,
  WorkflowCache,
  type WorkflowContext,
  type WorkflowDefinition,
  type WorkflowDeps,
  type WorkflowPhase,
} from "./runner.js";

/** Workflow identity: the name jobs are created under. */
export const CAD_WORKFLOW_NAME = "cad_project";
/** Workflow version; participates in every checkpoint hash. */
export const CAD_WORKFLOW_VERSION = "cad_project@1";
/** Hard cap on the bounded project decomposition. */
export const MAX_PARTS = 8;
/** Hard cap on repair rounds PER PART (digest §5 "capped repair"). */
export const MAX_REPAIR_ROUNDS = 2;
/** Default synchronous delegation deadline (seconds). */
export const DEFAULT_DEADLINE_SECONDS = 600;

export const PHASE_KEYS = {
  decompose: "cad:decompose@1",
  delegate: "cad:delegate@1",
  crossChecks: "cad:cross_checks@1",
  repair: "cad:repair@1",
  verify: "cad:verify@1",
} as const;

// ── input ────────────────────────────────────────────────────────────────────

export interface CadPartTask {
  /** Normalized part id the child agent is scoped to. */
  readonly part: string;
  /** Initial instruction for the part agent (bounded by the bridge's limits). */
  readonly prompt: string;
  /** Instruction used for repair rounds; falls back to `prompt`. */
  readonly repairPrompt?: string;
}

export interface CadWorkflowInput {
  readonly projectRoot: string;
  /** Orchestrator session id: the principal cross-part checks run as. */
  readonly sessionId: string;
  /** Parent run id delegations are charged to. */
  readonly parentRunId: string;
  readonly parts: ReadonlyArray<CadPartTask>;
  readonly maxParts: number;
  readonly maxRepairRounds: number;
  readonly deadlineSeconds: number;
  /** Caller ceiling on fan-out width (still clamped by admission capacity). */
  readonly maxConcurrency?: number;
}

// ── bridge surface ───────────────────────────────────────────────────────────

export interface DelegateRequest {
  readonly part: string;
  readonly prompt: string;
  /** Repair round (0 = initial delegation) — part of the idempotency key. */
  readonly round: number;
  readonly index: number;
}

export interface DelegateOutcome {
  readonly part: string;
  readonly status: string;
  readonly childRunId: string | null;
  readonly delegationRef: string | null;
  readonly resultArtifactRef: string | null;
  readonly error: string | null;
}

export interface CheckSnapshot {
  readonly status: string;
  readonly passed: boolean;
  readonly failing: ReadonlyArray<string>;
  readonly total: number;
  readonly checkSetRef: string | null;
}

/** Everything the workflow needs from Python, injectable for tests. */
export interface CadBridge {
  delegate(request: DelegateRequest): Promise<DelegateOutcome>;
  runChecks(): Promise<CheckSnapshot>;
  admissionCapacity(): Promise<number>;
}

function asRecord(value: JsonValue | null | undefined): { [k: string]: JsonValue } {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as { [k: string]: JsonValue })
    : {};
}

function optString(value: JsonValue | undefined): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function errorText(value: JsonValue | undefined): string | null {
  if (typeof value === "string") return value;
  const record = asRecord(value);
  const message = record.message;
  return typeof message === "string" ? message : null;
}

/**
 * Trusted invocation for one workflow-originated bridge operation.
 *
 * The workflow has no persisted assistant entry, so the *job + phase + round*
 * plays that role: `(sessionId, "<jobId>#<phase>:<round>", index, "wf:<part>")`
 * is stable across retries of the same logical step and distinct for every other
 * step, which is exactly what the delegation WAL keys on.
 */
export function workflowInvocation(
  sessionId: string,
  jobId: string,
  phase: string,
  round: number,
  index: number,
  part: string,
): TrustedInvocation {
  return makeInvocation({
    sessionId,
    entryId: `${jobId}#${phase}:${round}`,
    ordinal: index,
    providerCallId: `wf:${part}`,
  });
}

/** The real bridge: `py.delegate` / `py.tool_dispatch` / `py.admission_capacity`. */
export function createCadBridge(
  call: BridgeCall,
  input: CadWorkflowInput,
  jobId: string,
): CadBridge {
  let checkOrdinal = 0;
  return {
    async delegate(request: DelegateRequest): Promise<DelegateOutcome> {
      const invocation = workflowInvocation(
        input.sessionId,
        jobId,
        "delegate",
        request.round,
        request.index,
        request.part,
      );
      const raw = await call("py.delegate", {
        // A per-branch parent run id: synchronous `delivery="prompt"` suspends
        // its parent in exchange for the child's admission, and one run can hold
        // only one suspension — so a fan-out of N parts needs N branch runs, all
        // rooted in (and reported against) the workflow's own run id. Python
        // admits the branch, then settles it when the child terminates.
        parent_run_id: `${input.parentRunId}:${request.part}:${request.round}`,
        workflow_run_id: input.parentRunId,
        part: request.part,
        prompt: request.prompt,
        delivery: "prompt",
        deadline_seconds: input.deadlineSeconds,
        invocation: invocation as unknown as JsonValue,
      });
      const record = asRecord(raw);
      return {
        part: request.part,
        status: typeof record.status === "string" ? record.status : "failed",
        childRunId: optString(record.child_run_id),
        delegationRef: optString(record.delegation_ref),
        resultArtifactRef: optString(record.result_artifact_ref),
        error: errorText(record.error) ?? optString(record.reason),
      };
    },

    async runChecks(): Promise<CheckSnapshot> {
      const invocation = workflowInvocation(
        input.sessionId,
        jobId,
        "run_checks",
        checkOrdinal,
        checkOrdinal,
        "project",
      );
      checkOrdinal += 1;
      const raw = await call("py.tool_dispatch", {
        session_id: input.sessionId,
        run_id: input.parentRunId,
        tool: "run_checks",
        arguments: { scope: "project" },
        invocation: invocation as unknown as JsonValue,
      });
      return toCheckSnapshot(raw);
    },

    async admissionCapacity(): Promise<number> {
      const raw = await call("py.admission_capacity", {});
      const record = asRecord(raw);
      return typeof record.capacity === "number" ? record.capacity : 0;
    },
  };
}

/** Project a `run_checks` result onto the workflow's pass/fail snapshot. */
export function toCheckSnapshot(raw: JsonValue | null): CheckSnapshot {
  const record = asRecord(raw);
  const status = typeof record.status === "string" ? record.status : "unknown";
  const checks = asRecord(record.checks);
  const failing: string[] = [];
  let total = 0;
  for (const [name, value] of Object.entries(checks)) {
    total += 1;
    // The canonical `run_checks` payload reports one `{"pass", "measured"}` record
    // per check (core `CheckResult.to_json`); `passed` is accepted as an alias so
    // a hand-written or re-projected payload reads the same. Anything else — a
    // missing verdict included — fails closed.
    const entry = asRecord(value);
    const verdict = entry.pass ?? entry.passed;
    if (verdict !== true) failing.push(name);
  }
  failing.sort();
  // A non-`ok` status (e.g. invalid_check_generation) fails closed, and a run
  // with zero checks is not evidence of correctness.
  const passed = status === "ok" && total > 0 && failing.length === 0;
  return {
    status,
    passed,
    failing,
    total,
    checkSetRef: optString(record.check_set_ref),
  };
}

// ── context ──────────────────────────────────────────────────────────────────

export interface RepairRound {
  readonly round: number;
  readonly parts: ReadonlyArray<string>;
  readonly outcomes: ReadonlyArray<DelegateOutcome>;
  readonly checks: CheckSnapshot;
}

export interface CadWorkflowContext extends WorkflowContext {
  readonly cache: WorkflowCache;
  readonly input: CadWorkflowInput;
  readonly bridge: CadBridge;
  readonly deps: WorkflowDeps;
  readonly jobId: string;
  stop?: { reason: string };
  signal?: AbortSignal;
  heartbeat?: () => Promise<void>;
  tasks: ReadonlyArray<CadPartTask>;
  delegations: ReadonlyArray<DelegateOutcome>;
  checks: CheckSnapshot | null;
  repairs: RepairRound[];
  verification: CheckSnapshot | null;
  /** Fan-out bound actually used, per fan-out (asserted by the G2 test). */
  fanoutConcurrency: number[];
}

function abortError(): Error {
  const err = new Error("workflow cancelled");
  err.name = "AbortError";
  return err;
}

function ensureLive(ctx: CadWorkflowContext): void {
  if (ctx.signal?.aborted === true) throw abortError();
}

// ── checkpointing ────────────────────────────────────────────────────────────

/**
 * The JSON projection of the input that participates in every checkpoint hash —
 * and, because it is stored as the job row's `input`, the payload a resume can
 * be re-parsed from. Its keys are therefore exactly `parseCadWorkflowInput`'s.
 *
 * `parentRunId` is deliberately ABSENT: the run id is orchestration identity,
 * not workflow input. A resumed run necessarily carries a new one, and it must
 * still be able to verify its predecessor's checkpoints.
 */
function inputDigest(input: CadWorkflowInput): JsonValue {
  return {
    project_root: input.projectRoot,
    session_id: input.sessionId,
    max_parts: input.maxParts,
    max_repair_rounds: input.maxRepairRounds,
    deadline_seconds: input.deadlineSeconds,
    ...(input.maxConcurrency !== undefined ? { max_concurrency: input.maxConcurrency } : {}),
    parts: input.parts.map((task) => ({
      part: task.part,
      prompt: task.prompt,
      ...(task.repairPrompt !== undefined ? { repair_prompt: task.repairPrompt } : {}),
    })),
  };
}

/** Write one phase checkpoint (workflow version + input/output hashes). */
async function checkpoint(
  ctx: CadWorkflowContext,
  checkpointKey: string,
  output: JsonValue,
): Promise<void> {
  await ctx.deps.store.checkpoint({
    jobId: ctx.jobId,
    checkpointKey,
    workflowVersion: CAD_WORKFLOW_VERSION,
    inputHash: hashJson(inputDigest(ctx.input)),
    outputHash: hashJson(output),
    value: output,
  });
}

function snapshotJson(snapshot: CheckSnapshot | null): JsonValue {
  if (snapshot === null) return null;
  return {
    status: snapshot.status,
    passed: snapshot.passed,
    failing: [...snapshot.failing],
    total: snapshot.total,
    checkSetRef: snapshot.checkSetRef,
  };
}

function outcomesJson(outcomes: ReadonlyArray<DelegateOutcome>): JsonValue {
  return outcomes.map((outcome) => ({
    part: outcome.part,
    status: outcome.status,
    childRunId: outcome.childRunId,
    delegationRef: outcome.delegationRef,
    resultArtifactRef: outcome.resultArtifactRef,
    error: outcome.error,
  }));
}

// ── fan-out over parts ───────────────────────────────────────────────────────

async function delegateAll(
  ctx: CadWorkflowContext,
  tasks: ReadonlyArray<CadPartTask>,
  round: number,
  repair: boolean,
): Promise<DelegateOutcome[]> {
  const outcome = await admissionBoundedFanout<CadPartTask, DelegateOutcome>({
    items: tasks,
    capacity: () => ctx.bridge.admissionCapacity(),
    ...(ctx.input.maxConcurrency !== undefined
      ? { maxConcurrency: ctx.input.maxConcurrency }
      : {}),
    ...(ctx.signal !== undefined ? { signal: ctx.signal } : {}),
    runner: async (task, index) =>
      ctx.bridge.delegate({
        part: task.part,
        prompt: repair ? (task.repairPrompt ?? task.prompt) : task.prompt,
        round,
        index,
      }),
  });
  ctx.fanoutConcurrency.push(outcome.concurrency);
  const results: DelegateOutcome[] = [];
  for (const [index, slot] of outcome.results.entries()) {
    const task = tasks[index];
    if (task === undefined) continue;
    results.push(
      slot.ok
        ? slot.value
        : {
            part: task.part,
            status: "failed",
            childRunId: null,
            delegationRef: null,
            resultArtifactRef: null,
            error: slot.error.message,
          },
    );
  }
  return results;
}

/**
 * Which parts a failing cross-part check implicates.
 *
 * Cross-part check names are `"<file stem>:<check name>"` and carry no part
 * attribution, so the policy is deterministic and explicit: a part is targeted
 * when its id appears in a failing check's name, when its own delegation did not
 * complete, or — when nothing matched at all — every part is retried (an
 * unattributable cross-part failure is a whole-assembly failure).
 */
export function repairTargets(
  tasks: ReadonlyArray<CadPartTask>,
  delegations: ReadonlyArray<DelegateOutcome>,
  checks: CheckSnapshot,
): CadPartTask[] {
  const failedParts = new Set(
    delegations.filter((d) => d.status !== "completed").map((d) => d.part),
  );
  const named = new Set<string>();
  for (const name of checks.failing) {
    const lowered = name.toLowerCase();
    for (const task of tasks) {
      if (lowered.includes(task.part.toLowerCase())) named.add(task.part);
    }
  }
  const targeted = tasks.filter((task) => failedParts.has(task.part) || named.has(task.part));
  return targeted.length > 0 ? targeted : [...tasks];
}

// ── phases ───────────────────────────────────────────────────────────────────

function decomposePhase(): WorkflowPhase<CadWorkflowContext> {
  return {
    name: "decompose",
    checkpointKey: PHASE_KEYS.decompose,
    async *run(ctx): AsyncGenerator<WorkflowEvent, void> {
      ensureLive(ctx);
      const cap = Math.max(1, Math.min(ctx.input.maxParts, MAX_PARTS));
      const seen = new Set<string>();
      const tasks: CadPartTask[] = [];
      for (const task of ctx.input.parts) {
        if (seen.has(task.part) || tasks.length >= cap) continue;
        seen.add(task.part);
        tasks.push(task);
      }
      ctx.tasks = tasks;
      yield {
        type: "phase",
        phase: "decompose",
        detail: `${tasks.length} part(s) within cap ${cap}`,
        counts: { parts: tasks.length, requested: ctx.input.parts.length },
      };
      const output: JsonValue = { parts: tasks.map((task) => task.part) };
      yield { type: "data", key: "tasks", value: output };
      await checkpoint(ctx, PHASE_KEYS.decompose, output);
    },
  };
}

function delegatePhase(): WorkflowPhase<CadWorkflowContext> {
  return {
    name: "delegate",
    checkpointKey: PHASE_KEYS.delegate,
    async *run(ctx): AsyncGenerator<WorkflowEvent, void> {
      ensureLive(ctx);
      yield { type: "phase", phase: "delegate", detail: `${ctx.tasks.length} part agent(s)` };
      const outcomes = await delegateAll(ctx, ctx.tasks, 0, false);
      ctx.delegations = outcomes;
      for (const outcome of outcomes) {
        yield {
          type: "agent_activity",
          agent: `part:${outcome.part}`,
          action: "delegated",
          detail: outcome.status,
        };
      }
      const output = outcomesJson(outcomes);
      yield { type: "data", key: "delegations", value: output };
      await checkpoint(ctx, PHASE_KEYS.delegate, output);
    },
  };
}

function crossChecksPhase(): WorkflowPhase<CadWorkflowContext> {
  return {
    name: "cross_checks",
    checkpointKey: PHASE_KEYS.crossChecks,
    async *run(ctx): AsyncGenerator<WorkflowEvent, void> {
      ensureLive(ctx);
      const snapshot = await ctx.bridge.runChecks();
      ctx.checks = snapshot;
      yield {
        type: "phase",
        phase: "cross_checks",
        detail: snapshot.passed ? "all cross-part checks pass" : `${snapshot.failing.length} failing`,
        counts: { total: snapshot.total, failing: snapshot.failing.length },
      };
      const output = snapshotJson(snapshot);
      yield { type: "data", key: "cross_checks", value: output };
      await checkpoint(ctx, PHASE_KEYS.crossChecks, output);
    },
  };
}

function repairPhase(): WorkflowPhase<CadWorkflowContext> {
  return {
    name: "repair",
    checkpointKey: PHASE_KEYS.repair,
    async *run(ctx): AsyncGenerator<WorkflowEvent, void> {
      const cap = Math.max(0, Math.min(ctx.input.maxRepairRounds, MAX_REPAIR_ROUNDS));
      const roundsByPart = new Map<string, number>();
      for (let round = 1; round <= cap; round += 1) {
        ensureLive(ctx);
        const current = ctx.checks;
        if (current === null || current.passed) break;
        const eligible = repairTargets(ctx.tasks, ctx.delegations, current).filter(
          (task) => (roundsByPart.get(task.part) ?? 0) < cap,
        );
        if (eligible.length === 0) break;
        yield {
          type: "phase",
          phase: "repair",
          detail: `round ${round}/${cap} over ${eligible.map((t) => t.part).join(", ")}`,
          counts: { round, parts: eligible.length, failing: current.failing.length },
        };
        for (const task of eligible) {
          roundsByPart.set(task.part, (roundsByPart.get(task.part) ?? 0) + 1);
        }
        const outcomes = await delegateAll(ctx, eligible, round, true);
        ensureLive(ctx);
        const snapshot = await ctx.bridge.runChecks();
        ctx.checks = snapshot;
        ctx.repairs.push({
          round,
          parts: eligible.map((task) => task.part),
          outcomes,
          checks: snapshot,
        });
        yield {
          type: "data",
          key: `repair_round_${round}`,
          value: { outcomes: outcomesJson(outcomes), checks: snapshotJson(snapshot) },
        };
        if (snapshot.passed) break;
      }
      const output: JsonValue = {
        rounds: ctx.repairs.map((entry) => ({
          round: entry.round,
          parts: [...entry.parts],
          checks: snapshotJson(entry.checks),
        })),
        cap,
      };
      await checkpoint(ctx, PHASE_KEYS.repair, output);
    },
  };
}

function verifyPhase(): WorkflowPhase<CadWorkflowContext> {
  return {
    name: "verify",
    checkpointKey: PHASE_KEYS.verify,
    async *run(ctx): AsyncGenerator<WorkflowEvent, void> {
      ensureLive(ctx);
      const snapshot = await ctx.bridge.runChecks();
      ctx.verification = snapshot;
      yield {
        type: "phase",
        phase: "verify",
        detail: snapshot.passed ? "verified" : `unresolved: ${snapshot.failing.join(", ")}`,
        counts: { total: snapshot.total, failing: snapshot.failing.length },
      };
      const output = snapshotJson(snapshot);
      yield { type: "data", key: "verification", value: output };
      await checkpoint(ctx, PHASE_KEYS.verify, output);
      if (!snapshot.passed) {
        // A stopped pipeline is an honest terminal: never report success from a
        // partially-repaired assembly.
        ctx.stop = { reason: "checks_failing" };
      }
    },
  };
}

/** The ordered phase list (exported for direct-invocation tests). */
export function cadWorkflowPhases(): ReadonlyArray<WorkflowPhase<CadWorkflowContext>> {
  return [decomposePhase(), delegatePhase(), crossChecksPhase(), repairPhase(), verifyPhase()];
}

// ── input parsing ────────────────────────────────────────────────────────────

export function parseCadWorkflowInput(raw: JsonValue): CadWorkflowInput {
  const record = asRecord(raw);
  const partsRaw = Array.isArray(record.parts) ? record.parts : [];
  const parts: CadPartTask[] = [];
  for (const entry of partsRaw) {
    const item = asRecord(entry);
    const part = typeof item.part === "string" ? item.part : "";
    const prompt = typeof item.prompt === "string" ? item.prompt : "";
    if (part === "" || prompt === "") continue;
    const repairPrompt = typeof item.repair_prompt === "string" ? item.repair_prompt : undefined;
    parts.push({ part, prompt, ...(repairPrompt !== undefined ? { repairPrompt } : {}) });
  }
  if (parts.length === 0) throw new Error("cad workflow input requires at least one part task");
  const sessionId = typeof record.session_id === "string" ? record.session_id : "";
  if (sessionId === "") throw new Error("cad workflow input requires session_id");
  const maxConcurrency =
    typeof record.max_concurrency === "number" && record.max_concurrency > 0
      ? Math.floor(record.max_concurrency)
      : undefined;
  return {
    projectRoot: typeof record.project_root === "string" ? record.project_root : "",
    sessionId,
    parentRunId: typeof record.parent_run_id === "string" ? record.parent_run_id : "",
    parts,
    maxParts:
      typeof record.max_parts === "number" ? Math.floor(record.max_parts) : MAX_PARTS,
    maxRepairRounds:
      typeof record.max_repair_rounds === "number"
        ? Math.floor(record.max_repair_rounds)
        : MAX_REPAIR_ROUNDS,
    deadlineSeconds:
      typeof record.deadline_seconds === "number"
        ? Math.floor(record.deadline_seconds)
        : DEFAULT_DEADLINE_SECONDS,
    ...(maxConcurrency !== undefined ? { maxConcurrency } : {}),
  };
}

/** Fresh workflow context (optionally with an injected bridge, for tests). */
export function createCadWorkflowContext(
  input: CadWorkflowInput,
  deps: WorkflowDeps,
  jobId: string,
  bridge?: CadBridge,
): CadWorkflowContext {
  return {
    cache: new WorkflowCache(),
    input,
    bridge: bridge ?? createCadBridge(deps.call, input, jobId),
    deps,
    jobId,
    tasks: [],
    delegations: [],
    checks: null,
    repairs: [],
    verification: null,
    fanoutConcurrency: [],
  };
}

/** The final result recorded on the job row. */
export function cadWorkflowResult(ctx: CadWorkflowContext): JsonValue {
  return {
    workflow: CAD_WORKFLOW_NAME,
    version: CAD_WORKFLOW_VERSION,
    parts: ctx.tasks.map((task) => task.part),
    delegations: outcomesJson(ctx.delegations),
    repair_rounds: ctx.repairs.length,
    checks: snapshotJson(ctx.checks),
    verification: snapshotJson(ctx.verification),
    verified: ctx.verification?.passed === true,
    fanout_concurrency: [...ctx.fanoutConcurrency],
  };
}

/** The registered definition the workflow-runner process serves. */
export const cadWorkflowDefinition: WorkflowDefinition<CadWorkflowInput, CadWorkflowContext> = {
  name: CAD_WORKFLOW_NAME,
  version: CAD_WORKFLOW_VERSION,
  parseInput: parseCadWorkflowInput,
  inputDigest,
  createContext: (input, deps, jobId) => createCadWorkflowContext(input, deps, jobId),
  phases: () => cadWorkflowPhases(),
  finalResult: cadWorkflowResult,
  rehydrate(ctx, checkpoints) {
    // Resume restores orchestrator position only; the caller rebuilds ctx. These
    // are the exact outputs the skipped phases would have produced.
    const tasks = asRecord(checkpoints.get(PHASE_KEYS.decompose) ?? null);
    if (Array.isArray(tasks.parts)) {
      const names = new Set(tasks.parts.filter((p): p is string => typeof p === "string"));
      ctx.tasks = ctx.input.parts.filter((task) => names.has(task.part));
    }
    const delegations = checkpoints.get(PHASE_KEYS.delegate);
    if (Array.isArray(delegations)) {
      ctx.delegations = delegations.map((entry) => {
        const item = asRecord(entry);
        return {
          part: typeof item.part === "string" ? item.part : "",
          status: typeof item.status === "string" ? item.status : "failed",
          childRunId: optString(item.childRunId),
          delegationRef: optString(item.delegationRef),
          resultArtifactRef: optString(item.resultArtifactRef),
          error: errorText(item.error),
        };
      });
    }
    const checks = checkpoints.get(PHASE_KEYS.crossChecks);
    if (checks !== undefined && checks !== null) ctx.checks = toStoredSnapshot(checks);
    const verification = checkpoints.get(PHASE_KEYS.verify);
    if (verification !== undefined && verification !== null) {
      ctx.verification = toStoredSnapshot(verification);
    }
  },
};

function toStoredSnapshot(raw: JsonValue): CheckSnapshot {
  const record = asRecord(raw);
  const failing = Array.isArray(record.failing)
    ? record.failing.filter((entry): entry is string => typeof entry === "string")
    : [];
  return {
    status: typeof record.status === "string" ? record.status : "unknown",
    passed: record.passed === true,
    failing,
    total: typeof record.total === "number" ? record.total : 0,
    checkSetRef: optString(record.checkSetRef),
  };
}
