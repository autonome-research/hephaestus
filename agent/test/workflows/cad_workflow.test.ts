// The Stage 2 CAD workflow: decomposition -> delegation -> cross-part checks ->
// CAPPED repair -> final verification, all deterministic, all checkpointed, and
// cooperatively cancellable.

import { describe, expect, it } from "vitest";
import {
  cadWorkflowDefinition,
  cadWorkflowPhases,
  cadWorkflowResult,
  createCadWorkflowContext,
  MAX_PARTS,
  MAX_REPAIR_ROUNDS,
  PHASE_KEYS,
  parseCadWorkflowInput,
  repairTargets,
  toCheckSnapshot,
  workflowInvocation,
  type CadBridge,
  type CadWorkflowContext,
  type CadWorkflowInput,
  type CheckSnapshot,
  type DelegateOutcome,
  type DelegateRequest,
} from "../../src/workflows/cad_workflow.js";
import {
  createJobRunner,
  registerWorkflowMethods,
  startWorkflow,
  WORKFLOW_RESUME,
  WORKFLOW_RUN,
  type WorkflowPeer,
} from "../../src/workflows/runner.js";
import { BridgeJobStore } from "../../src/workflows/jobstore.js";
import type { JsonValue } from "../../src/framing.js";
import { ScriptedPyPeer } from "./py_peer.js";

const PASS: CheckSnapshot = {
  status: "ok",
  passed: true,
  failing: [],
  total: 2,
  checkSetRef: "checkset:1",
};
const failing = (names: string[]): CheckSnapshot => ({
  status: "ok",
  passed: false,
  failing: names,
  total: 2,
  checkSetRef: "checkset:1",
});

function input(overrides: Partial<CadWorkflowInput> = {}): CadWorkflowInput {
  return {
    projectRoot: "/tmp/proj",
    sessionId: "orch-1",
    parentRunId: "run-parent",
    parts: [
      { part: "bracket", prompt: "build bracket", repairPrompt: "fix bracket" },
      { part: "shelf", prompt: "build shelf", repairPrompt: "fix shelf" },
    ],
    maxParts: MAX_PARTS,
    maxRepairRounds: MAX_REPAIR_ROUNDS,
    deadlineSeconds: 600,
    ...overrides,
  };
}

interface FakeBridge extends CadBridge {
  readonly delegations: DelegateRequest[];
  checkCalls: number;
  peakConcurrency: number;
}

function fakeBridge(options: {
  checks: CheckSnapshot[];
  capacity?: number;
  delegate?: (request: DelegateRequest) => Partial<DelegateOutcome>;
  delayMs?: number;
}): FakeBridge {
  const queue = [...options.checks];
  let active = 0;
  const bridge: FakeBridge = {
    delegations: [],
    checkCalls: 0,
    peakConcurrency: 0,
    async delegate(request) {
      bridge.delegations.push(request);
      active += 1;
      bridge.peakConcurrency = Math.max(bridge.peakConcurrency, active);
      await new Promise((resolve) => setTimeout(resolve, options.delayMs ?? 2));
      active -= 1;
      return {
        part: request.part,
        status: "completed",
        childRunId: `cr-${request.part}-${request.round}`,
        delegationRef: `dg-${request.part}-${request.round}`,
        resultArtifactRef: `artifact:${request.part}`,
        error: null,
        ...(options.delegate?.(request) ?? {}),
      };
    },
    async runChecks() {
      bridge.checkCalls += 1;
      return queue.length > 1 ? (queue.shift() as CheckSnapshot) : (queue[0] as CheckSnapshot);
    },
    async admissionCapacity() {
      return options.capacity ?? 4;
    },
  };
  return bridge;
}

interface Harness {
  readonly peer: ScriptedPyPeer;
  readonly store: BridgeJobStore;
  readonly ctx: CadWorkflowContext;
  readonly jobId: string;
  run(): Promise<{ status: string; reason?: string }>;
  cancel(): void;
}

async function harness(
  bridge: CadBridge,
  workflowInput: CadWorkflowInput = input(),
): Promise<Harness> {
  const peer = new ScriptedPyPeer();
  const store = new BridgeJobStore(peer.call, { newJobId: () => "job-cad" });
  const runner = createJobRunner(store);
  const jobId = await store.createJob("cad_project", null);
  const ctx = createCadWorkflowContext(
    workflowInput,
    { store, call: peer.call },
    jobId,
    bridge,
  );
  let cancel = (): void => {};
  return {
    peer,
    store,
    ctx,
    jobId,
    cancel: () => cancel(),
    async run() {
      const handle = startWorkflow(runner, jobId, cadWorkflowPhases(), ctx, () =>
        cadWorkflowResult(ctx),
      );
      cancel = () => handle.cancel("operator");
      try {
        return await handle.result;
      } catch (err) {
        return { status: (err as Error).name === "AbortError" ? "cancelled" : "failed" };
      }
    },
  };
}

describe("cad workflow — happy path", () => {
  it("decomposes, delegates, checks, and verifies with no repair round", async () => {
    const bridge = fakeBridge({ checks: [PASS] });
    const h = await harness(bridge);
    const summary = await h.run();

    expect(summary.status).toBe("completed");
    expect(h.ctx.tasks.map((t) => t.part)).toEqual(["bracket", "shelf"]);
    expect(h.ctx.delegations.map((d) => d.status)).toEqual(["completed", "completed"]);
    expect(h.ctx.repairs).toEqual([]);
    expect(h.ctx.verification?.passed).toBe(true);
    // Initial delegation only, and the cross-check + verification runs.
    expect(bridge.delegations.map((d) => d.round)).toEqual([0, 0]);
    expect(bridge.checkCalls).toBe(2);

    // Every phase checkpointed with the workflow version + input/output hashes.
    const checkpoints = await h.store.listCheckpoints(h.jobId);
    expect([...checkpoints.keys()].sort()).toEqual(
      [
        PHASE_KEYS.decompose,
        PHASE_KEYS.delegate,
        PHASE_KEYS.crossChecks,
        PHASE_KEYS.repair,
        PHASE_KEYS.verify,
      ].sort(),
    );
    for (const record of checkpoints.values()) {
      expect(record.workflowVersion).toBe(cadWorkflowDefinition.version);
      expect(record.inputHash).toMatch(/^[0-9a-f]{64}$/);
      expect(record.outputHash).toMatch(/^[0-9a-f]{64}$/);
    }
    // …and the durable log carries a phase_complete per checkpointed phase.
    const events = await h.store.getEvents(h.jobId);
    const completed = events.filter((e) => e.eventType === "phase_complete");
    expect(completed.length).toBe(5);
    expect((await h.store.getJob(h.jobId))?.status).toBe("COMPLETED");
  });

  it("caps the decomposition at MAX_PARTS and de-duplicates parts", async () => {
    const many = Array.from({ length: 12 }, (_v, i) => ({
      part: `p${i}`,
      prompt: `build p${i}`,
    }));
    const bridge = fakeBridge({ checks: [PASS], capacity: 16 });
    const h = await harness(bridge, input({ parts: [...many, ...many], maxParts: 100 }));
    await h.run();
    expect(h.ctx.tasks.length).toBe(MAX_PARTS);
    expect(new Set(h.ctx.tasks.map((t) => t.part)).size).toBe(MAX_PARTS);
  });
});

describe("cad workflow — capped repair", () => {
  it("repairs the interfering part in one round and then verifies green", async () => {
    // Cross-part interference is reported once; the repair round clears it.
    const bridge = fakeBridge({ checks: [failing(["assembly:shelf_clearance"]), PASS] });
    const h = await harness(bridge);
    const summary = await h.run();

    expect(summary.status).toBe("completed");
    expect(h.ctx.repairs.length).toBe(1);
    expect(h.ctx.repairs[0]?.parts).toEqual(["shelf"]);
    expect(h.ctx.repairs[0]?.checks.passed).toBe(true);
    expect(h.ctx.verification?.passed).toBe(true);
    // The repair delegation used the repair prompt and round 1.
    expect(bridge.delegations.filter((d) => d.round === 1)).toEqual([
      { part: "shelf", prompt: "fix shelf", round: 1, index: 0 },
    ]);
    const result = cadWorkflowResult(h.ctx) as { verified: boolean; repair_rounds: number };
    expect(result.verified).toBe(true);
    expect(result.repair_rounds).toBe(1);
  });

  it("never exceeds MAX_REPAIR_ROUNDS per part and refuses to claim success", async () => {
    const bridge = fakeBridge({ checks: [failing(["assembly:interference"])] });
    const h = await harness(bridge);
    const summary = await h.run();

    expect(summary.status).toBe("stopped");
    expect(summary.reason).toBe("checks_failing");
    expect(h.ctx.repairs.length).toBe(MAX_REPAIR_ROUNDS);
    expect(h.ctx.repairs.map((r) => r.round)).toEqual([1, 2]);
    // Two parts x two rounds, plus the initial delegation of both.
    expect(bridge.delegations.filter((d) => d.round > 0).length).toBe(2 * MAX_REPAIR_ROUNDS);
    expect(bridge.delegations.filter((d) => d.round > MAX_REPAIR_ROUNDS).length).toBe(0);
    expect(h.ctx.verification?.passed).toBe(false);
    expect((cadWorkflowResult(h.ctx) as { verified: boolean }).verified).toBe(false);
  });

  it("honours a lower per-run repair cap", async () => {
    const bridge = fakeBridge({ checks: [failing(["assembly:interference"])] });
    const h = await harness(bridge, input({ maxRepairRounds: 1 }));
    await h.run();
    expect(h.ctx.repairs.length).toBe(1);
  });

  it("targets the part whose own delegation failed", async () => {
    const bridge = fakeBridge({
      checks: [failing(["assembly:unattributable"]), PASS],
      delegate: (request) =>
        request.part === "bracket" && request.round === 0
          ? { status: "failed", error: "build_failed" }
          : {},
    });
    const h = await harness(bridge);
    await h.run();
    expect(h.ctx.repairs[0]?.parts).toEqual(["bracket"]);
  });

  it("retries every part when a cross-part failure names none of them", () => {
    const tasks = input().parts;
    const completed: DelegateOutcome[] = tasks.map((t) => ({
      part: t.part,
      status: "completed",
      childRunId: null,
      delegationRef: null,
      resultArtifactRef: null,
      error: null,
    }));
    expect(repairTargets(tasks, completed, failing(["assembly:total_mass"])).map((t) => t.part))
      .toEqual(["bracket", "shelf"]);
  });
});

describe("cad workflow — bounds and cancellation", () => {
  it("fan-out never exceeds the live admission capacity", async () => {
    const bridge = fakeBridge({ checks: [PASS], capacity: 1, delayMs: 5 });
    const parts = ["a", "b", "c", "d"].map((p) => ({ part: p, prompt: `build ${p}` }));
    const h = await harness(bridge, input({ parts }));
    await h.run();
    expect(h.ctx.fanoutConcurrency).toEqual([1]);
    expect(bridge.peakConcurrency).toBe(1);
  });

  it("cooperative cancellation stops the workflow before verification", async () => {
    const bridge = fakeBridge({ checks: [PASS], capacity: 1, delayMs: 40 });
    const parts = ["a", "b", "c", "d"].map((p) => ({ part: p, prompt: `build ${p}` }));
    const h = await harness(bridge, input({ parts }));
    const running = h.run();
    setTimeout(() => h.cancel(), 20);
    const summary = await running;
    expect(summary.status).toBe("cancelled");
    expect(h.ctx.verification).toBeNull();
    expect((await h.store.getJob(h.jobId))?.status).toBe("CANCELLED");
    const events = await h.store.getEvents(h.jobId);
    expect(events.filter((e) => e.eventType === "cancelled").length).toBe(1);
    // Not every part was dispatched: cancellation stopped the fan-out cursor.
    expect(bridge.delegations.length).toBeLessThan(parts.length);
  });
});

describe("cad workflow — bridge mapping and parsing", () => {
  it("projects a run_checks payload onto a pass/fail snapshot, failing closed", () => {
    // The wire shape is core's CheckResult.to_json: {"pass", "measured"}.
    const ok = toCheckSnapshot({
      status: "ok",
      check_set_ref: "checkset:7",
      checks: { "a:fits": { pass: true, measured: 0 }, "a:sealed": { pass: true, measured: true } },
    });
    expect(ok).toEqual({
      status: "ok",
      passed: true,
      failing: [],
      total: 2,
      checkSetRef: "checkset:7",
    });
    const bad = toCheckSnapshot({
      status: "ok",
      checks: { "a:fits": { pass: false, measured: 12 }, "a:sealed": { pass: true } },
    });
    expect(bad.passed).toBe(false);
    expect(bad.failing).toEqual(["a:fits"]);
    // `passed` is accepted as an alias of `pass`…
    expect(toCheckSnapshot({ status: "ok", checks: { "a:fits": { passed: true } } }).passed).toBe(
      true,
    );
    // …and a check with no verdict at all is a failure, never a pass.
    expect(toCheckSnapshot({ status: "ok", checks: { "a:fits": {} } }).failing).toEqual(["a:fits"]);
    // An invalid check generation, or zero checks, is never a pass.
    expect(toCheckSnapshot({ status: "invalid_check_generation", checks: {} }).passed).toBe(false);
    expect(toCheckSnapshot({ status: "ok", checks: {} }).passed).toBe(false);
    expect(toCheckSnapshot(null).passed).toBe(false);
  });

  it("derives stable, distinct trusted invocations per (job, phase, round, part)", () => {
    const a = workflowInvocation("s", "job-1", "delegate", 0, 0, "bracket");
    const again = workflowInvocation("s", "job-1", "delegate", 0, 0, "bracket");
    const round2 = workflowInvocation("s", "job-1", "delegate", 1, 0, "bracket");
    const other = workflowInvocation("s", "job-1", "delegate", 0, 1, "shelf");
    expect(a.invocation_id).toBe(again.invocation_id);
    expect(a.invocation_id).not.toBe(round2.invocation_id);
    expect(a.invocation_id).not.toBe(other.invocation_id);
    expect(a.session_id).toBe("s");
  });

  it("stores an input digest that parses back into the same workflow input", () => {
    const parsed = parseCadWorkflowInput({
      project_root: "/p",
      session_id: "orch",
      parent_run_id: "run-1",
      parts: [{ part: "a", prompt: "build a", repair_prompt: "fix a" }],
      max_repair_rounds: 1,
      max_concurrency: 3,
    });
    const digest = cadWorkflowDefinition.inputDigest(parsed) as { [k: string]: JsonValue };
    // The digest IS the job row's stored input, so a resume can re-parse it…
    expect(digest.parent_run_id).toBeUndefined();
    const again = parseCadWorkflowInput(digest);
    // …recovering everything except the run id, which the resume supplies fresh.
    expect(again).toEqual({ ...parsed, parentRunId: "" });
  });

  it("parses (and rejects) workflow input from the bridge", () => {
    const parsed = parseCadWorkflowInput({
      project_root: "/p",
      session_id: "orch",
      parent_run_id: "run",
      parts: [
        { part: "a", prompt: "build a", repair_prompt: "fix a" },
        { part: "", prompt: "ignored" },
      ],
      max_repair_rounds: 1,
      max_concurrency: 3,
    });
    expect(parsed.parts).toEqual([{ part: "a", prompt: "build a", repairPrompt: "fix a" }]);
    expect(parsed.maxRepairRounds).toBe(1);
    expect(parsed.maxConcurrency).toBe(3);
    expect(parsed.deadlineSeconds).toBe(600);
    expect(() => parseCadWorkflowInput({ session_id: "orch", parts: [] })).toThrow(/at least one/);
    expect(() => parseCadWorkflowInput({ parts: [{ part: "a", prompt: "b" }] })).toThrow(
      /session_id/,
    );
  });
});

// ── workflow.run / workflow.resume over a scripted bridge peer ───────────────

class FakePeer implements WorkflowPeer {
  readonly handlers = new Map<
    string,
    (params: { [k: string]: JsonValue }) => Promise<JsonValue>
  >();

  on(
    method: string,
    handler: (params: { [k: string]: JsonValue }) => Promise<JsonValue>,
  ): void {
    this.handlers.set(method, handler);
  }

  request(): Promise<JsonValue> {
    throw new Error("the fake peer originates no requests");
  }

  invoke(method: string, params: { [k: string]: JsonValue }): Promise<JsonValue> {
    const handler = this.handlers.get(method);
    if (handler === undefined) throw new Error(`no handler for ${method}`);
    return handler(params);
  }
}

describe("workflow.run / workflow.resume", () => {
  function wire(peer: ScriptedPyPeer): { fake: FakePeer; store: BridgeJobStore } {
    let n = 0;
    const store = new BridgeJobStore(peer.call, { newJobId: () => `job-${++n}` });
    const runner = createJobRunner(store);
    const fake = new FakePeer();
    registerWorkflowMethods(fake, {
      store,
      runner,
      call: peer.call,
      definitions: [cadWorkflowDefinition],
    });
    return { fake, store };
  }

  const workflowParams = {
    workflow: "cad_project",
    input: {
      project_root: "/p",
      session_id: "orch-1",
      parent_run_id: "run-parent",
      parts: [
        { part: "bracket", prompt: "build bracket" },
        { part: "shelf", prompt: "build shelf" },
      ],
    },
  } as unknown as { [k: string]: JsonValue };

  it("runs end to end through the real py.* bridge calls", async () => {
    const peer = new ScriptedPyPeer();
    peer.handle("py.admission_capacity", () => ({ capacity: 2 }));
    peer.handle("py.delegate", (params) => ({
      status: "completed",
      part_session_id: `part:${String(params.part)}`,
      child_run_id: `cr-${String(params.part)}`,
      delegation_ref: `dg-${String(params.part)}`,
      result_artifact_ref: `artifact:${String(params.part)}`,
    }));
    peer.handle("py.tool_dispatch", () => ({
      status: "ok",
      check_set_ref: "checkset:1",
      checks: { "assembly:fits": { pass: true, measured: 0 } },
    }));
    const { fake, store } = wire(peer);

    const outcome = (await fake.invoke(WORKFLOW_RUN, workflowParams)) as unknown as {
      job_id: string;
      status: string;
      skipped_phases: string[];
    };
    expect(outcome.status).toBe("completed");
    expect(outcome.skipped_phases).toEqual([]);
    expect((await store.getJob(outcome.job_id))?.status).toBe("COMPLETED");
    // Delegation went out over py.delegate — never the model-visible tool.
    const delegated = peer.methodCalls("py.delegate");
    expect(delegated.length).toBe(2);
    // Each concurrent delegation carries its own branch parent run, rooted in
    // the workflow's run id (one suspension per run in the admission substrate).
    expect(delegated.map((entry) => String(entry.params.parent_run_id))).toEqual([
      "run-parent:bracket:0",
      "run-parent:shelf:0",
    ]);
    for (const entry of delegated) {
      expect(entry.params.workflow_run_id).toBe("run-parent");
      expect(entry.params.delivery).toBe("prompt");
    }
    const dispatched = peer
      .methodCalls("py.tool_dispatch")
      .map((entry) => String(entry.params.tool));
    expect(new Set(dispatched)).toEqual(new Set(["run_checks"]));
    expect(dispatched.length).toBe(2);
  });

  it("resumes from verified checkpoints without redoing delegation", async () => {
    const peer = new ScriptedPyPeer();
    peer.handle("py.admission_capacity", () => ({ capacity: 2 }));
    peer.handle("py.delegate", (params) => ({
      status: "completed",
      child_run_id: `cr-${String(params.part)}`,
      delegation_ref: `dg-${String(params.part)}`,
      result_artifact_ref: `artifact:${String(params.part)}`,
    }));
    let checkCalls = 0;
    peer.handle("py.tool_dispatch", () => {
      checkCalls += 1;
      // The first cross-part check run fails the phase outright (bridge fault).
      if (checkCalls === 1) throw new Error("state.db unavailable");
      return {
        status: "ok",
        check_set_ref: "checkset:1",
        checks: { "assembly:fits": { pass: true, measured: 0 } },
      };
    });
    const { fake, store } = wire(peer);

    const first = (await fake.invoke(WORKFLOW_RUN, workflowParams)) as unknown as {
      job_id: string;
      status: string;
    };
    expect(first.status).toBe("failed");
    expect((await store.getJob(first.job_id))?.status).toBe("FAILED");
    expect(peer.methodCalls("py.delegate").length).toBe(2);

    // The resumed run carries a NEW parent run id — orchestration identity is not
    // workflow input, so it must not invalidate the prior run's checkpoints.
    const resumed = (await fake.invoke(WORKFLOW_RESUME, {
      ...workflowParams,
      input: {
        ...(workflowParams.input as { [k: string]: JsonValue }),
        parent_run_id: "run-parent-resumed",
      },
      job_id: first.job_id,
    })) as unknown as { job_id: string; status: string; skipped_phases: string[] };
    expect(resumed.status).toBe("completed");
    expect(resumed.job_id).not.toBe(first.job_id);
    expect(resumed.skipped_phases).toEqual(["decompose", "delegate"]);
    // The verified checkpoints spared the (side-effecting) delegations.
    expect(peer.methodCalls("py.delegate").length).toBe(2);
    const record = await store.getJob(resumed.job_id);
    expect(record?.status).toBe("COMPLETED");
    expect((record?.result as { verified: boolean }).verified).toBe(true);
    expect((record?.result as { delegations: unknown[] }).delegations.length).toBe(2);
  });

  it("re-runs every phase when the input hash no longer matches the checkpoint", async () => {
    const peer = new ScriptedPyPeer();
    peer.handle("py.admission_capacity", () => ({ capacity: 2 }));
    peer.handle("py.delegate", () => ({ status: "completed", child_run_id: "cr" }));
    let calls = 0;
    peer.handle("py.tool_dispatch", () => {
      calls += 1;
      if (calls === 1) throw new Error("boom");
      return { status: "ok", checks: { "assembly:fits": { pass: true, measured: 0 } } };
    });
    const { fake } = wire(peer);
    const first = (await fake.invoke(WORKFLOW_RUN, workflowParams)) as unknown as {
      job_id: string;
    };
    const changed = {
      ...workflowParams,
      job_id: first.job_id,
      input: {
        ...(workflowParams.input as { [k: string]: JsonValue }),
        parts: [{ part: "bracket", prompt: "build a DIFFERENT bracket" }],
      },
    } as unknown as { [k: string]: JsonValue };
    const resumed = (await fake.invoke(WORKFLOW_RESUME, changed)) as unknown as {
      skipped_phases: string[];
    };
    expect(resumed.skipped_phases).toEqual([]);
  });

  it("rejects an unknown workflow name", async () => {
    const peer = new ScriptedPyPeer();
    const { fake } = wire(peer);
    await expect(fake.invoke(WORKFLOW_RUN, { workflow: "nope" })).rejects.toThrow(/unknown workflow/);
  });
});
