// `BridgeJobStore` — every JobStore operation must round-trip through the five
// `py.jobstore_*` bridge methods and NOTHING else (no native sqlite, no local
// state that would not survive a restart).

import { describe, expect, it } from "vitest";
import { BridgeJobStore, eventKey, toJobRecord } from "../../src/workflows/jobstore.js";
import type { StoredJob, WorkflowEvent } from "../../src/workflows/jobstore.js";
import { ScriptedPyPeer } from "./py_peer.js";

function newStore(peer: ScriptedPyPeer, prefix = "tp"): BridgeJobStore {
  let n = 0;
  return new BridgeJobStore(peer.call, {
    namespacePrefix: prefix,
    newJobId: () => `job-${++n}`,
    now: () => new Date(1_700_000_000_000 + n * 1000),
  });
}

const dataEvent = (key: string): WorkflowEvent =>
  ({ type: "data", key, value: 1 }) as unknown as WorkflowEvent;

describe("BridgeJobStore over the py.jobstore_* bridge", () => {
  it("persists a job and its events only through bridge calls", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);

    const jobId = await store.createJob("cad_project", { seed: 1 });
    expect(jobId).toBe("job-1");
    await store.setRunning(jobId, { ownerId: "owner-a", sessionId: "sess" });
    const first = await store.appendEvent(jobId, dataEvent("a"));
    const second = await store.appendEvent(jobId, dataEvent("b"));
    expect([first, second]).toEqual([1, 2]);

    const record = await store.getJob(jobId);
    expect(record?.status).toBe("RUNNING");
    expect(record?.ownerId).toBe("owner-a");
    expect(record?.eventCount).toBe(2);
    expect(record?.createdAt).toBeInstanceOf(Date);

    // Every method that touched durable state used a frozen bridge method.
    const used = new Set(peer.calls.map((entry) => entry.method));
    expect([...used].sort()).toEqual(["py.jobstore_get", "py.jobstore_put"]);
    // The durable rows live under the contract namespaces/keys Python reads.
    expect([...(peer.rows.get("tp:jobs")?.keys() ?? [])]).toEqual(["job-1"]);
    expect([...(peer.rows.get("tp:events")?.keys() ?? [])]).toEqual([
      eventKey("job-1", 1),
      eventKey("job-1", 2),
    ]);
  });

  it("replays the durable event log in id order, honouring the resume cursor", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const jobId = await store.createJob("cad_project", null);
    await store.appendEvent(jobId, dataEvent("a"));
    await store.appendEvent(jobId, dataEvent("b"));
    await store.appendEvent(jobId, dataEvent("c"));

    const all = await store.getEvents(jobId, 0);
    expect(all.map((e) => e.id)).toEqual([1, 2, 3]);
    expect(all.map((e) => e.eventType)).toEqual(["data", "data", "data"]);
    const tail = await store.getEvents(jobId, 2);
    expect(tail.map((e) => e.id)).toEqual([3]);

    // A brand-new store instance over the same rows replays identically: no
    // event id or job state lives in sidecar memory.
    const reopened = newStore(peer);
    const replayed = await reopened.getEvents(jobId, 0);
    expect(replayed.map((e) => e.id)).toEqual([1, 2, 3]);
    const next = await reopened.appendEvent(jobId, dataEvent("d"));
    expect(next).toBe(4);
  });

  it("keeps event ids per-job separated but globally monotonic", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const a = await store.createJob("wf", null);
    const b = await store.createJob("wf", null);
    await store.appendEvent(a, dataEvent("a1"));
    await store.appendEvent(b, dataEvent("b1"));
    await store.appendEvent(a, dataEvent("a2"));
    expect((await store.getEvents(a)).map((e) => e.id)).toEqual([1, 3]);
    expect((await store.getEvents(b)).map((e) => e.id)).toEqual([2]);
  });

  it("makes terminal transitions first-writer-wins", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const jobId = await store.createJob("wf", null);
    await store.setRunning(jobId, { ownerId: "owner-a" });

    expect(await store.setCompleted(jobId, { answer: 42 }, "owner-a")).toBe(true);
    expect(await store.setFailed(jobId, "too late", "owner-a")).toBe(false);
    expect(await store.setCancelled(jobId, "too late", "owner-a")).toBe(false);
    const record = await store.getJob(jobId);
    expect(record?.status).toBe("COMPLETED");
    expect(record?.result).toEqual({ answer: 42 });
  });

  it("refuses transitions from a foreign owner", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const jobId = await store.createJob("wf", null);
    await store.setRunning(jobId, { ownerId: "owner-a" });
    expect(await store.setRunning(jobId, { ownerId: "owner-b" })).toBe(false);
    expect(await store.setCompleted(jobId, null, "owner-b")).toBe(false);
    expect(await store.finalizeJob(jobId, {
      status: "COMPLETED",
      result: null,
      event: { type: "done" } as unknown as WorkflowEvent,
      ownerId: "owner-b",
    })).toBeNull();
    expect((await store.getJob(jobId))?.status).toBe("RUNNING");
  });

  it("finalizeJob writes the terminal row and its terminal event atomically", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const jobId = await store.createJob("wf", null);
    await store.setRunning(jobId, { ownerId: "o" });
    const terminal = await store.finalizeJob(jobId, {
      status: "CANCELLED",
      error: "operator",
      event: { type: "cancelled", reason: "operator" } as unknown as WorkflowEvent,
      ownerId: "o",
    });
    expect(terminal?.eventType).toBe("cancelled");
    const record = await store.getJob(jobId);
    expect(record?.status).toBe("CANCELLED");
    expect(record?.error).toBe("operator");
    expect(record?.eventCount).toBe(1);
    // A second finalization is refused and appends no event.
    expect(
      await store.finalizeJob(jobId, {
        status: "COMPLETED",
        result: 1,
        event: { type: "done" } as unknown as WorkflowEvent,
        ownerId: "o",
      }),
    ).toBeNull();
    expect((await store.getJob(jobId))?.eventCount).toBe(1);
  });

  it("acquireExclusive admits one RUNNING job per name", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const first = await store.acquireExclusive("cad_project", null);
    expect(first).not.toBeNull();
    expect(await store.acquireExclusive("cad_project", null)).toBeNull();
    expect(await store.acquireExclusive("other", null)).not.toBeNull();
    await store.setCompleted(first as string, null);
    expect(await store.acquireExclusive("cad_project", null)).not.toBeNull();
  });

  it("accepts a caller-minted job id but never resets an existing row", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    expect(await store.createJobWithId("wf-job-7", "cad_project", { a: 1 })).toBe("wf-job-7");
    await store.setRunning("wf-job-7", { ownerId: "o" });
    await expect(store.createJobWithId("wf-job-7", "cad_project", null)).rejects.toThrow(
      /already exists/,
    );
    expect((await store.getJob("wf-job-7"))?.status).toBe("RUNNING");
  });

  it("computes STALE at read time without ever persisting it", async () => {
    const peer = new ScriptedPyPeer();
    let clock = 1_000_000;
    const store = new BridgeJobStore(peer.call, {
      newJobId: () => "job-stale",
      now: () => new Date(clock),
    });
    const jobId = await store.createJob("wf", null);
    await store.setRunning(jobId, { ownerId: "o" });
    await store.heartbeat(jobId, "o");
    clock += 10_000;
    expect((await store.getJob(jobId))?.status).toBe("RUNNING");
    expect((await store.getJob(jobId, { staleAfterMs: 5_000 }))?.status).toBe("STALE");
    const stored = peer.rows.get("tp:jobs")?.get(jobId) as unknown as StoredJob;
    expect(stored.status).toBe("RUNNING");
    const listed = await store.listJobs({ status: "STALE", staleAfterMs: 5_000 });
    expect(listed.map((j) => j.id)).toEqual([jobId]);
    // …and the conditional abandon transition only fires while it IS stale.
    expect(
      await store.setAbandonedIfStale(jobId, new Date(clock - 5_000), "owner lost", "o"),
    ).toBe(true);
    expect((await store.getJob(jobId))?.status).toBe("ABANDONED");
  });

  it("lists jobs newest-first with name/limit filters", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const a = await store.createJob("cad_project", null);
    const b = await store.createJob("cad_project", null);
    await store.createJob("other", null);
    const listed = await store.listJobs({ name: "cad_project" });
    expect(listed.map((j) => j.id)).toEqual([b, a]);
    expect((await store.listJobs({ limit: 1 })).length).toBe(1);
  });

  it("checkpoints through py.jobstore_checkpoint and mirrors them for resume", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const jobId = await store.createJob("cad_project", null);
    await store.checkpoint({
      jobId,
      checkpointKey: "cad:decompose@1",
      workflowVersion: "cad_project@1",
      inputHash: "in",
      outputHash: "out",
      value: { parts: ["a"] },
    });
    expect(peer.checkpoints.get(`${jobId}#cad:decompose@1`)).toEqual({
      workflowVersion: "cad_project@1",
      inputHash: "in",
      outputHash: "out",
      value: { parts: ["a"] },
    });
    const mirrored = await store.readCheckpoint(jobId, "cad:decompose@1");
    expect(mirrored?.inputHash).toBe("in");
    expect((await store.listCheckpoints(jobId)).get("cad:decompose@1")?.outputHash).toBe("out");
  });

  it("serializes concurrent read-modify-write sequences", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const jobId = await store.createJob("wf", null);
    await store.setRunning(jobId, { ownerId: "o" });
    const ids = await Promise.all(
      Array.from({ length: 8 }, (_v, i) => store.appendEvent(jobId, dataEvent(`e${i}`))),
    );
    expect([...ids].sort((x, y) => x - y)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect((await store.getJob(jobId))?.eventCount).toBe(8);
  });

  it("surfaces bridge failures instead of silently forgetting a write", async () => {
    const peer = new ScriptedPyPeer();
    const store = newStore(peer);
    const jobId = await store.createJob("wf", null);
    peer.down = true;
    await expect(store.appendEvent(jobId, dataEvent("x"))).rejects.toThrow(/bridge down/);
    peer.down = false;
    // The mutex is not wedged by the rejection.
    expect(await store.appendEvent(jobId, dataEvent("y"))).toBe(1);
  });

  it("rehydrates ISO dates into a JobRecord", () => {
    const stored: StoredJob = {
      id: "j",
      name: "wf",
      input: null,
      status: "COMPLETED",
      result: null,
      error: null,
      eventCount: 0,
      createdAt: "2026-07-24T00:00:00.000Z",
      startedAt: "2026-07-24T00:00:01.000Z",
      completedAt: "2026-07-24T00:00:02.000Z",
      failureClass: "interrupted",
    };
    const record = toJobRecord(stored);
    expect(record.createdAt.toISOString()).toBe("2026-07-24T00:00:00.000Z");
    expect(record.startedAt?.toISOString()).toBe("2026-07-24T00:00:01.000Z");
    expect(record.completedAt?.toISOString()).toBe("2026-07-24T00:00:02.000Z");
    expect(record.heartbeatAt).toBeUndefined();
  });
});
