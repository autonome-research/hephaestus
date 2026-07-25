import { describe, it, expect } from "vitest";
import {
  buildInvocationId,
  makeInvocation,
  InvocationTracker,
} from "../src/tools/invocation.js";

describe("trusted invocation ids", () => {
  const base = { sessionId: "sess-uuid-1", entryId: "entry-A", ordinal: 0, providerCallId: "call_0" };

  it("is stable for the same tuple (lost-response retry reconciles)", () => {
    expect(buildInvocationId(base)).toBe(buildInvocationId({ ...base }));
  });

  it("stays unique when the provider repeats call_0 across distinct entries (G2 fixture)", () => {
    const a = buildInvocationId({ ...base, entryId: "entry-A", ordinal: 0, providerCallId: "call_0" });
    const b = buildInvocationId({ ...base, entryId: "entry-B", ordinal: 0, providerCallId: "call_0" });
    expect(a).not.toBe(b);
  });

  it("distinguishes ordinals within the same entry even if the provider id repeats", () => {
    const a = buildInvocationId({ ...base, ordinal: 0, providerCallId: "call_0" });
    const b = buildInvocationId({ ...base, ordinal: 1, providerCallId: "call_0" });
    expect(a).not.toBe(b);
  });

  it("is injective across separator-bearing components (length-prefixed encoding)", () => {
    // Values that could collide under a naive join, disambiguated by lengths.
    const a = buildInvocationId({ sessionId: "a:1", entryId: "b", ordinal: 0, providerCallId: "c" });
    const b = buildInvocationId({ sessionId: "a", entryId: "1:b", ordinal: 0, providerCallId: "c" });
    expect(a).not.toBe(b);
  });

  it("carries the four components in wire-facing snake_case", () => {
    const inv = makeInvocation(base);
    expect(inv).toMatchObject({
      session_id: "sess-uuid-1",
      entry_id: "entry-A",
      ordinal: 0,
      provider_call_id: "call_0",
    });
    expect(inv.invocation_id).toBe(buildInvocationId(base));
  });
});

describe("InvocationTracker", () => {
  it("is idempotent on the same tuple and unique across repeated provider ids", () => {
    const t = new InvocationTracker();
    const a1 = t.register({ sessionId: "s", entryId: "e1", ordinal: 0, providerCallId: "call_0" });
    const a2 = t.register({ sessionId: "s", entryId: "e1", ordinal: 0, providerCallId: "call_0" });
    const b = t.register({ sessionId: "s", entryId: "e2", ordinal: 0, providerCallId: "call_0" });
    expect(a1.invocation_id).toBe(a2.invocation_id);
    expect(a1.invocation_id).not.toBe(b.invocation_id);
    expect(t.size).toBe(2);
    expect(t.has(a1.invocation_id)).toBe(true);
  });
});
