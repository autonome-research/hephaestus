// VALIDATION.md §3 question shaping, agent side: a clarification is refused
// before it reaches the bridge unless it offers 2-4 options that each state a
// geometric consequence. The Python side asserts the same rules over the same
// cases (server/tests/test_clarification_gate.py); these two must not drift.

import { describe, it, expect } from "vitest";
import {
  clarificationRefusal,
  invalidQuestionResult,
  optionConsequence,
  optionLabel,
  questionProblems,
  requirementIds,
  INVALID_QUESTION_CODE,
} from "../src/tools/clarify.js";
import { ToolProxy, type RpcRequest, type ProxyContext } from "../src/tools/proxy.js";
import { makeInvocation } from "../src/tools/invocation.js";
import type { JsonValue } from "../src/framing.js";

const WALL_OPTIONS: JsonValue = [
  { label: "inside the stated footprint", consequence: "40 mm overall, 34 mm internal" },
  { label: "outside the stated footprint", consequence: "46 mm overall, 40 mm internal" },
];

const CTX: ProxyContext = {
  sessionId: "sess-1",
  runId: "run-1",
  invocation: makeInvocation({
    sessionId: "sess-1",
    entryId: "entry-A",
    ordinal: 0,
    providerCallId: "call_0",
  }),
};

describe("clarification question shape", () => {
  it("treats a question with no requirement ids as an ordinary question", () => {
    expect(clarificationRefusal({ question: "proceed?", options: ["yes", "no"] })).toBeUndefined();
    expect(requirementIds(undefined)).toEqual([]);
    expect(requirementIds(["R9", "", 3 as unknown as JsonValue])).toEqual(["R9"]);
  });

  it("refuses a clarification whose options state no consequence", () => {
    const refusal = clarificationRefusal({
      requirement_ids: ["R9"],
      question: "which side does the wall stand on?",
      options: ["inside", "outside"],
    });
    expect(refusal).toMatchObject({
      status: "invalid_question",
      code: INVALID_QUESTION_CODE,
    });
    const problems = (refusal as { problems: string[] }).problems;
    expect(problems).toHaveLength(2);
    expect(problems.every((p) => p.includes("geometric consequence"))).toBe(true);
  });

  it.each([
    ["too few options", [WALL_OPTIONS[0]]],
    [
      "too many options",
      [0, 1, 2, 3, 4].map((i) => ({ label: `option ${i}`, consequence: "moves 1 mm" })),
    ],
    ["an empty consequence", [{ label: "inside", consequence: "" }, WALL_OPTIONS[1]]],
    ["an empty label", [{ label: "", consequence: "40 mm overall" }, WALL_OPTIONS[1]]],
    ["a non-array options value", "inside or outside"],
  ])("refuses a clarification with %s", (_name, options) => {
    const refusal = clarificationRefusal({
      requirement_ids: ["R9"],
      question: "which side?",
      options: options as JsonValue,
    });
    expect(refusal).toBeDefined();
  });

  it("asks a well-shaped clarification", () => {
    expect(
      clarificationRefusal({
        requirement_ids: ["R9"],
        question: "which side does the wall stand on?",
        options: WALL_OPTIONS,
      }),
    ).toBeUndefined();
  });

  it("requires a non-empty question", () => {
    expect(questionProblems("", WALL_OPTIONS)).toContain("question must be a non-empty string");
  });

  it("reads either option form", () => {
    expect(optionLabel(WALL_OPTIONS[1])).toBe("outside the stated footprint");
    expect(optionLabel("plain")).toBe("plain");
    expect(optionConsequence("plain")).toBeUndefined();
    expect(optionConsequence(WALL_OPTIONS[0])).toBe("40 mm overall, 34 mm internal");
  });

  it("names every problem at once", () => {
    const result = invalidQuestionResult(["a", "b"]) as { problems: string[]; message: string };
    expect(result.problems).toEqual(["a", "b"]);
    expect(result.message).toContain("was not asked");
  });
});

describe("the proxy enforces the shape before the bridge is called", () => {
  function fakeBridge() {
    const calls: string[] = [];
    const request: RpcRequest = async (method) => {
      calls.push(method);
      return { selection: "outside" };
    };
    return { calls, request };
  }

  it("never asks a badly-shaped clarification", async () => {
    const bridge = fakeBridge();
    const result = await new ToolProxy(bridge.request).execute(
      "ask_user",
      { question: "what did you mean?", options: ["a", "b"], requirement_ids: ["R9"] },
      CTX,
    );
    expect(bridge.calls).toEqual([]);
    expect(result.details.result).toMatchObject({ status: "invalid_question" });
  });

  it("passes the bridge's own refusal through result validation", async () => {
    // The Python side is authoritative and refuses too (it also covers MCP);
    // its payload must satisfy the declared ask_user result union.
    const request: RpcRequest = async () => ({
      status: "invalid_question",
      code: "clarification_question_shape",
      message: "the question was not asked",
      problems: ["option 0: must state its geometric consequence"],
    });
    const result = await new ToolProxy(request).execute(
      "ask_user",
      { question: "which side?", options: WALL_OPTIONS, requirement_ids: ["R9"] },
      CTX,
    );
    expect(result.details.result).toMatchObject({ status: "invalid_question" });
  });

  it("forwards a well-shaped clarification with its requirement ids", async () => {
    const calls: { method: string; params: { [k: string]: JsonValue } }[] = [];
    const request: RpcRequest = async (method, params) => {
      calls.push({ method, params });
      return { selection: "outside the stated footprint" };
    };
    await new ToolProxy(request).execute(
      "ask_user",
      {
        question: "which side does the wall stand on?",
        options: WALL_OPTIONS,
        requirement_ids: ["R9"],
      },
      CTX,
    );
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("py.ask_user");
    expect(calls[0].params.requirement_ids).toEqual(["R9"]);
  });
});
