// Spike D+G: thread-phase free-runner proof through the openai-free
// `/session` subpath ONLY (mission forbids the AgentAdapter surface).
//  - injects a CUSTOM async in-memory JobStore (not SqliteJobStore, no native)
//  - runs a two-phase pipeline through JobRunner, streams live events
//  - proves durable event persistence, terminal COMPLETED transition,
//    and cooperative cancellation on a second job
//  - asserts that neither `openai` nor any `.node` addon was loaded.
import { registerHooks } from "node:module";
const loadedUrls = [];
registerHooks({ resolve(s, c, next) { const r = next(s, c); loadedUrls.push(r.url ?? s); return r; } });

const { JobRunner } = await import("@autonome-research/thread-phase/session");

const assert = (cond, msg) => { if (!cond) throw new Error(`ASSERT FAILED: ${msg}`); console.log(`ok: ${msg}`); };

// --- custom async in-memory JobStore (stands in for the Python-SQLite bridge) ---
class MemoryJobStore {
  jobs = new Map(); events = []; nextEvent = 1; seq = 0;
  async createJob(name, input) { const id = `job-${++this.seq}`; this.jobs.set(id, { id, name, input, status: "PENDING", result: null, error: null, eventCount: 0, createdAt: new Date(), startedAt: null, completedAt: null }); return id; }
  async acquireExclusive(name, input) { for (const j of this.jobs.values()) if (j.name === name && j.status === "RUNNING") return null; const id = await this.createJob(name, input); this.jobs.get(id).status = "RUNNING"; this.jobs.get(id).startedAt = new Date(); return id; }
  async setRunning(id, ownership = {}) { const j = this.jobs.get(id); if (!j || (j.status !== "PENDING" && j.status !== "RUNNING")) return false; if (j.ownerId && ownership.ownerId && j.ownerId !== ownership.ownerId) return false; Object.assign(j, ownership); j.status = "RUNNING"; j.startedAt ??= new Date(); return true; }
  #terminal(id, status, patch, ownerId) { const j = this.jobs.get(id); if (!j || !["PENDING", "RUNNING"].includes(j.status)) return false; if (ownerId && j.ownerId && ownerId !== j.ownerId) return false; Object.assign(j, patch, { status, completedAt: new Date() }); return true; }
  async setCompleted(id, result, ownerId) { return this.#terminal(id, "COMPLETED", { result }, ownerId); }
  async setFailed(id, error, ownerId) { return this.#terminal(id, "FAILED", { error }, ownerId); }
  async setCancelled(id, reason, ownerId) { return this.#terminal(id, "CANCELLED", { error: reason }, ownerId); }
  async setAbandoned(id, reason) { return this.#terminal(id, "ABANDONED", { error: reason }); }
  async setAbandonedIfStale(id, staleBefore, reason, owner) { const j = this.jobs.get(id); if (!j || j.status !== "RUNNING") return false; if (j.heartbeatAt && j.heartbeatAt >= staleBefore) return false; return this.#terminal(id, "ABANDONED", { error: reason }, owner); }
  async finalizeJob(id, fin) { const ok = await ({ COMPLETED: () => this.setCompleted(id, fin.result, fin.ownerId), FAILED: () => this.setFailed(id, fin.error ?? "", fin.ownerId), CANCELLED: () => this.setCancelled(id, fin.error ?? "", fin.ownerId), ABANDONED: () => this.setAbandoned(id, fin.error ?? "") })[fin.status](); if (!ok) return null; const eid = await this.appendEvent(id, fin.event); return this.events.find((e) => e.id === eid) ?? null; }
  async finalizeAbandonedIfStale(id, staleBefore, reason, owner) { const ok = await this.setAbandonedIfStale(id, staleBefore, reason, owner); if (!ok) return null; const eid = await this.appendEvent(id, { type: "error", message: reason }); return this.events.find((e) => e.id === eid) ?? null; }
  async heartbeat(id) { const j = this.jobs.get(id); if (j?.status === "RUNNING") j.heartbeatAt = new Date(); }
  async enableHeartbeat(id, ownerId) { const j = this.jobs.get(id); if (!j || j.status !== "RUNNING") return false; j.heartbeatEnabled = true; j.heartbeatAt = new Date(); return true; }
  async getJob(id) { return this.jobs.get(id) ?? null; }
  async listJobs(opts = {}) { return [...this.jobs.values()].filter((j) => !opts.name || j.name === opts.name).slice(0, opts.limit ?? 50); }
  async appendEvent(jobId, event) { const id = this.nextEvent++; this.events.push({ id, jobId, eventType: event.type, data: event, createdAt: new Date() }); const j = this.jobs.get(jobId); if (j) j.eventCount++; return id; }
  async getEvents(jobId, afterId = 0) { return this.events.filter((e) => e.jobId === jobId && e.id > afterId); }
  close() {}
}

// --- free-runner phases: plain objects, no adapters, no agents ---
const phaseA = {
  name: "produce",
  checkpointKey: "produce-v1",
  async *run(ctx) {
    yield { type: "phase", phase: "produce", detail: "starting" };
    ctx.produced = 42;
    yield { type: "data", key: "produced", value: 42 };
  },
};
const phaseB = {
  name: "consume",
  async *run(ctx) {
    yield { type: "phase", phase: "consume", detail: `saw ${ctx.produced}` };
  },
};

const store = new MemoryJobStore();
const runner = new JobRunner(store, { heartbeatMs: 50 });
// happy path — live events are emitted per-job on channel `job:<id>`
const live = [];
const jobId = await runner.create("heph-pipeline", { seed: 1 });
runner.on(`job:${jobId}`, (e) => live.push(e));
const handle = runner.start(jobId, [phaseA, phaseB], { cache: new Map(), produced: 0 }, () => ({ answer: 42 }), { sessionId: "spike-session", launchSource: "spike" });
const summary = await handle.result;
const rec = await store.getJob(jobId);
const persisted = await store.getEvents(jobId, 0);
assert(rec.status === "COMPLETED", `job terminal status COMPLETED (got ${rec.status})`);
assert(rec.result?.answer === 42, "finalResult persisted on the job record");
assert(persisted.length >= 3 && live.length >= persisted.length - 1, `events durable (${persisted.length}) and streamed live (${live.length})`);
assert(persisted.some((e) => e.data.type === "data" && e.data.key === "produced"), "phase data event persisted with payload");
console.log(`summary keys: ${Object.keys(summary)}; persisted event types: [${persisted.map((e) => e.eventType)}]`);

// cancellation path
const slowPhase = { name: "slow", async *run(ctx) { yield { type: "phase", phase: "slow" }; await new Promise((r) => setTimeout(r, 5_000)); } };
const jobId2 = await runner.create("heph-slow", {});
const h2 = runner.start(jobId2, [slowPhase], { cache: new Map() });
setTimeout(() => h2.cancel("spike-cancel"), 150);
await h2.result.catch(() => {});
const rec2 = await store.getJob(jobId2);
assert(rec2.status === "CANCELLED", `cancelled job terminal status CANCELLED (got ${rec2.status})`);
assert(h2.signal.aborted, "JobRunHandle.signal aborted");

// import hygiene
const openaiLoaded = loadedUrls.filter((u) => /\/openai\//.test(u));
const nativeLoaded = loadedUrls.filter((u) => u.endsWith(".node"));
assert(openaiLoaded.length === 0, "no `openai` module loaded via /session free-runner path");
assert(nativeLoaded.length === 0, "no native .node addon loaded");
console.log(`total modules loaded: ${loadedUrls.length}`);
console.log("THREAD-PHASE JOBRUNNER PROOF COMPLETE");
