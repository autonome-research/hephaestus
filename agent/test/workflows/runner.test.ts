// Runner-level guarantees: the fan-out bound is derived from LIVE admission
// capacity (never a constant), zero capacity waits instead of deadlocking,
// cancellation propagates, and the checkpoint hashing/replay helpers are stable.

import { describe, expect, it, vi } from "vitest";
import {
  AdmissionCapacityError,
  admissionBoundedFanout,
  canonicalJson,
  completedCheckpointKeys,
  createJobRunner,
  hashJson,
  resolveFanoutConcurrency,
  startWorkflow,
  WorkflowCache,
  type WorkflowContext,
  type WorkflowPhase,
} from "../../src/workflows/runner.js";
import { BridgeJobStore, type WorkflowEvent } from "../../src/workflows/jobstore.js";
import { ScriptedPyPeer } from "./py_peer.js";

/** A runner that records the maximum number of simultaneously active items. */
function concurrencyTracker(delayMs = 5): {
  runner: (item: number) => Promise<number>;
  peak: () => number;
} {
  let active = 0;
  let peak = 0;
  return {
    peak: () => peak,
    runner: async (item: number) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      active -= 1;
      return item * 2;
    },
  };
}

describe("admission-clamped fan-out", () => {
  it("clamps the bound to the mocked live capacity", async () => {
    const capacity = vi.fn(async () => 2);
    const { runner, peak } = concurrencyTracker();
    const outcome = await admissionBoundedFanout<number, number>({
      items: [1, 2, 3, 4, 5, 6],
      capacity,
      runner,
    });
    expect(outcome.concurrency).toBe(2);
    expect(peak()).toBeLessThanOrEqual(2);
    expect(outcome.results.map((slot) => (slot.ok ? slot.value : null))).toEqual([
      2, 4, 6, 8, 10, 12,
    ]);
    expect(capacity).toHaveBeenCalled();
  });

  it("never exceeds capacity even when the caller asks for more", async () => {
    const { runner, peak } = concurrencyTracker();
    const outcome = await admissionBoundedFanout<number, number>({
      items: [1, 2, 3, 4, 5, 6, 7, 8],
      capacity: async () => 3,
      maxConcurrency: 8,
      runner,
    });
    expect(outcome.concurrency).toBe(3);
    expect(peak()).toBeLessThanOrEqual(3);
  });

  it("honours the caller ceiling when capacity is larger", async () => {
    const outcome = await admissionBoundedFanout<number, number>({
      items: [1, 2, 3, 4],
      capacity: async () => 16,
      maxConcurrency: 2,
      runner: async (item) => item,
    });
    expect(outcome.concurrency).toBe(2);
  });

  it("collects per-item failures instead of discarding siblings", async () => {
    const outcome = await admissionBoundedFanout<number, number>({
      items: [1, 2, 3],
      capacity: async () => 2,
      runner: async (item) => {
        if (item === 2) throw new Error("part 2 exploded");
        return item;
      },
    });
    expect(outcome.results.map((slot) => slot.ok)).toEqual([true, false, true]);
    const failed = outcome.results[1];
    expect(failed?.ok === false && failed.error.message).toBe("part 2 exploded");
  });

  it("waits for capacity rather than running with a bound of zero", async () => {
    let calls = 0;
    const capacity = async (): Promise<number> => {
      calls += 1;
      return calls < 3 ? 0 : 1;
    };
    const concurrency = await resolveFanoutConcurrency(capacity, 4, { pollMs: 1 });
    expect(concurrency).toBe(1);
    expect(calls).toBeGreaterThanOrEqual(3);
  });

  it("gives up (structurally) if capacity never frees", async () => {
    await expect(
      resolveFanoutConcurrency(async () => 0, 2, { pollMs: 1, timeoutMs: 10 }),
    ).rejects.toBeInstanceOf(AdmissionCapacityError);
  });

  it("cancellation while awaiting capacity unwinds as an AbortError", async () => {
    const controller = new AbortController();
    setTimeout(() => controller.abort("stop"), 5);
    await expect(
      resolveFanoutConcurrency(async () => 0, 2, {
        pollMs: 1,
        timeoutMs: 5_000,
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("an empty item list needs no capacity at all", async () => {
    const capacity = vi.fn(async () => 0);
    const outcome = await admissionBoundedFanout<number, number>({
      items: [],
      capacity,
      runner: async (item) => item,
    });
    expect(outcome).toEqual({ concurrency: 0, results: [] });
    expect(capacity).not.toHaveBeenCalled();
  });
});

describe("checkpoint helpers", () => {
  it("hashes canonically (key order independent, value sensitive)", () => {
    expect(canonicalJson({ b: 1, a: [1, { d: 2, c: 3 }] })).toBe('{"a":[1,{"c":3,"d":2}],"b":1}');
    expect(hashJson({ a: 1, b: 2 })).toBe(hashJson({ b: 2, a: 1 }));
    expect(hashJson({ a: 1 })).not.toBe(hashJson({ a: 2 }));
    expect(hashJson(null)).toMatch(/^[0-9a-f]{64}$/);
  });

  it("derives completed checkpoint keys from a durable event log", () => {
    const keys = completedCheckpointKeys([
      { data: { type: "phase", phase: "a" } },
      { data: { type: "phase_complete", phase: "a", checkpointKey: "k1" } },
      { data: { type: "phase_complete", phase: "b", checkpointKey: "k2" } },
      { data: null },
      { data: { type: "phase_complete", phase: "c" } },
    ]);
    expect([...keys].sort()).toEqual(["k1", "k2"]);
  });
});

describe("JobRunner over the bridge store", () => {
  it("runs phases, persists events durably, and completes the job", async () => {
    const peer = new ScriptedPyPeer();
    const store = new BridgeJobStore(peer.call, { newJobId: () => "job-run" });
    const runner = createJobRunner(store);
    interface Ctx extends WorkflowContext {
      produced: number;
    }
    const phase: WorkflowPhase<Ctx> = {
      name: "produce",
      checkpointKey: "produce@1",
      async *run(ctx) {
        ctx.produced = 42;
        yield { type: "data", key: "produced", value: 42 } as unknown as WorkflowEvent;
      },
    };
    const ctx: Ctx = { cache: new WorkflowCache(), produced: 0 };
    const handle = startWorkflow(runner, await runner.create("wf", null), [phase], ctx, () => ({
      answer: ctx.produced,
    }));
    const summary = await handle.result;
    expect(summary.status).toBe("completed");
    const record = await store.getJob("job-run");
    expect(record?.status).toBe("COMPLETED");
    expect(record?.result).toEqual({ answer: 42 });
    const events = await store.getEvents("job-run");
    expect(events.map((e) => e.eventType)).toEqual(["data", "phase_complete", "done"]);
  });

  it("cooperative cancellation persists exactly one CANCELLED terminal", async () => {
    const peer = new ScriptedPyPeer();
    const store = new BridgeJobStore(peer.call, { newJobId: () => "job-cancel" });
    const runner = createJobRunner(store);
    let observedAbort = false;
    const slow: WorkflowPhase<WorkflowContext> = {
      name: "slow",
      async *run(ctx) {
        yield { type: "phase", phase: "slow" } as unknown as WorkflowEvent;
        for (let i = 0; i < 200; i += 1) {
          if (ctx.signal?.aborted === true) {
            observedAbort = true;
            const err = new Error("cancelled");
            err.name = "AbortError";
            throw err;
          }
          await new Promise((resolve) => setTimeout(resolve, 2));
        }
      },
    };
    const jobId = await runner.create("wf", null);
    const handle = startWorkflow(runner, jobId, [slow], { cache: new WorkflowCache() });
    setTimeout(() => handle.cancel("operator"), 15);
    await expect(handle.result).rejects.toMatchObject({ name: "AbortError" });
    expect(observedAbort).toBe(true);
    const record = await store.getJob(jobId);
    expect(record?.status).toBe("CANCELLED");
    const cancelled = (await store.getEvents(jobId)).filter((e) => e.eventType === "cancelled");
    expect(cancelled.length).toBe(1);
  });
});
