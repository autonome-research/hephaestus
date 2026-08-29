// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Answering `ask_user` from the browser (INTERFACE.md §7A.7, §7.3; plan item 1).
//
// Three claims, and each is tested where it is decided rather than where it is
// rendered — `ask.ts` decides, the JSX only spells the decision into attributes.
//
// 1. **The affordance is the question's.** `askAffordance` is §7A.7's mapping
//    from `options` / `allow_free_text` / `multi` onto what may be offered, and
//    the table below is that paragraph transcribed.
// 2. **The submitted value is the server's `label`.** The cases come from
//    `tests/stage4/goldens/ask/answer_namespace.json`, which
//    `server/tests/test_cli_agent.py` reads too and answers with `heph agent`'s
//    numbered prompt: one file, two surfaces, one value. That is the §7A.7
//    tightening — before §19.29 the CLI answered an object option with a Python
//    dict repr and this surface answered with the label.
// 3. **Every state is a rendered state.** `first answer wins` gives a loser
//    `accepted:false`, a question that has gone gives `404 unknown_question`,
//    and both are widget states with copy, not dead controls.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AskUserWidget } from "../../src/components/stream/AskUserWidget";
import type { EventFrame } from "../../src/api/events";
import type { AnswerDocument } from "../../src/api/sessions";
import {
  answerValue,
  askAffordance,
  askContent,
  ASK_AFFORDANCES,
  type AskAffordance,
  type AskChoice,
  type AskRowLike,
} from "../../src/stream/ask";
import { liveItem } from "../../src/stream/transcript";
import { repoRoot } from "./fixture";

interface NamespaceCase {
  readonly name: string;
  readonly params: Readonly<Record<string, unknown>>;
  readonly affordance: AskAffordance;
  readonly choice: AskChoice;
  readonly cli_input: string;
  readonly cli_display: readonly string[];
  readonly selection: string | readonly string[];
}

/** The file `server/tests/test_cli_agent.py` pins the other surface against. */
const namespace = JSON.parse(
  readFileSync(
    join(repoRoot, "tests", "stage4", "goldens", "ask", "answer_namespace.json"),
    "utf8",
  ),
) as { readonly cases: readonly NamespaceCase[] };

const SESSION = "sess-ask";
const RUN = "run-ask";

/** One live `question` event, exactly as `main.ts` mints it around the suspension. */
function questionRow(
  payload: Readonly<Record<string, unknown>>,
  overrides: Partial<EventFrame> = {},
): AskRowLike {
  const frame: EventFrame = {
    run_id: RUN,
    seq: 1,
    kind: "question",
    session_id: SESSION,
    payload: { question_id: "q-ask-0", ...payload },
    ...overrides,
  };
  return {
    source: "question",
    question: liveItem(frame),
    call: null,
    result: null,
    answer: null,
    status: "running",
  };
}

function answerDocument(over: Partial<AnswerDocument> = {}): AnswerDocument {
  return {
    status: "ok",
    question_id: "q-ask-0",
    session_id: SESSION,
    run_id: RUN,
    answer: "Go to 3 mm walls",
    accepted: true,
    answered_by: "self",
    requested_session_id: SESSION,
    ...over,
  };
}

describe("§7A.7 — the affordance is derived from the question, never chosen", () => {
  it("maps the three params onto the closed affordance set", () => {
    expect(askAffordance(2, true, false)).toBe("options_text");
    expect(askAffordance(2, false, false)).toBe("options");
    expect(askAffordance(2, true, true)).toBe("multi_text");
    expect(askAffordance(2, false, true)).toBe("multi");
    expect(askAffordance(0, true, false)).toBe("text");
    // No options and no free text: nothing any client could answer with. §4.4's
    // discipline says name it rather than render an inert control.
    expect(askAffordance(0, false, false)).toBe("none");
    expect(new Set(ASK_AFFORDANCES).size).toBe(6);
  });

  it("reads the schema's defaults for a payload that omits the two flags", () => {
    // An older sidecar minted `{question_id, question, options}` only. The
    // schema's defaults are `allow_free_text: true` / `multi: false`, so an
    // omitted field means what the schema says it means — never `false` and
    // never a guess.
    const content = askContent(questionRow({ question: "Which?", options: ["a", "b"] }));
    expect(content.allowFreeText).toBe(true);
    expect(content.multi).toBe(false);
    expect(content.affordance).toBe("options_text");
  });

  it("never offers free text to a question that declared allow_free_text false", () => {
    const content = askContent(
      questionRow({ question: "Which?", options: ["a"], allow_free_text: false }),
    );
    expect(content.affordance).toBe("options");
    // §15.35 forbids the answer, not only the field: even handed the text, this
    // surface refuses to turn it into a value.
    expect(answerValue(content, { kind: "text", text: "something else" })).toBeNull();
  });
});

describe("§7A.7 — one question, one answer value, two surfaces", () => {
  for (const testCase of namespace.cases) {
    it(`submits the server-sent label: ${testCase.name}`, () => {
      const content = askContent(questionRow(testCase.params));
      expect(content.affordance).toBe(testCase.affordance);
      expect(answerValue(content, testCase.choice)).toEqual(testCase.selection);
    });
  }

  it("emits a multi answer in the question's order, not in click order", () => {
    const content = askContent(
      questionRow({
        question: "Which?",
        options: ["a", "b", "c"],
        multi: true,
        allow_free_text: false,
      }),
    );
    expect(answerValue(content, { kind: "options", indices: [2, 0] })).toEqual(["a", "c"]);
  });

  it("refuses a choice the question does not admit rather than posting one", () => {
    const single = askContent(
      questionRow({ question: "Which?", options: ["a"], allow_free_text: false }),
    );
    expect(answerValue(single, { kind: "option", index: 7 })).toBeNull();
    expect(answerValue(single, { kind: "options", indices: [0] })).toBeNull();

    const multi = askContent(
      questionRow({ question: "Which?", options: ["a"], multi: true, allow_free_text: false }),
    );
    expect(answerValue(multi, { kind: "option", index: 0 })).toBeNull();
    expect(answerValue(multi, { kind: "options", indices: [] })).toBeNull();

    const free = askContent(questionRow({ question: "How thick?", options: [] }));
    expect(answerValue(free, { kind: "text", text: "   " })).toBeNull();
  });
});

describe("§7A.7 — first answer wins, and every outcome is a rendered state", () => {
  const row = questionRow({
    question: "Which wall?",
    options: [{ label: "Keep 2 mm walls", consequence: "under one nozzle width" }],
    allow_free_text: false,
  });

  it("is answerable while the question is open", () => {
    const content = askContent(row);
    expect(content.state).toBe("answerable");
    expect(content.unavailable).toBeNull();
    expect(content.answeredBy).toBeNull();
    expect(content.sessionId).toBe(SESSION);
  });

  it("says self for the winner and other for the loser, on the route's own flag", () => {
    const won = askContent(row, { phase: "settled", document: answerDocument() });
    expect(won.state).toBe("answered");
    expect(won.answeredBy).toBe("self");

    // The loser is told, in its own response, that someone answered first — and
    // the recorded selection it renders is the **winner's**, returned unchanged,
    // so both clients agree on what the run was told.
    const lost = askContent(row, {
      phase: "settled",
      document: answerDocument({
        accepted: false,
        answered_by: "other",
        answer: "Keep 2 mm walls",
      }),
    });
    expect(lost.state).toBe("answered");
    expect(lost.answeredBy).toBe("other");
    expect(lost.answer).toBe("Keep 2 mm walls");
  });

  it("renders a 404 unknown_question as the abandoned state, in place", () => {
    const gone = askContent(row, {
      phase: "refused",
      reason: "unknown_question",
      message: "no question 'q-ask-0' is pending; it was answered, abandoned, or never asked",
    });
    expect(gone.state).toBe("abandoned");
    expect(gone.answered).toBe(false);
    expect(gone.refusal?.reason).toBe("unknown_question");
  });

  it("keeps any other refusal named rather than flattening it into failure", () => {
    const refused = askContent(row, {
      phase: "refused",
      reason: "agent_unavailable",
      message: "no agent runtime is attached",
    });
    expect(refused.state).toBe("failed");
    expect(refused.refusal).toEqual({
      reason: "agent_unavailable",
      message: "no agent runtime is attached",
    });
  });

  it("marks the post in flight, and lets another client's answer overtake it", () => {
    expect(askContent(row, { phase: "sending" }).state).toBe("submitting");

    const answered: AskRowLike = {
      ...row,
      answer: liveItem({
        run_id: RUN,
        seq: 2,
        kind: "answer",
        session_id: SESSION,
        payload: { question_id: "q-ask-0", answer: "Keep 2 mm walls" },
      }),
    };
    const overtaken = askContent(answered, { phase: "sending" });
    expect(overtaken.state).toBe("answered");
    expect(overtaken.answeredBy).toBe("other");
  });
});

describe("§7A.7 — a widget that cannot be answered says which kind of cannot", () => {
  it("names a live question with no question id", () => {
    const content = askContent(questionRow({ question: "Which?", options: ["a"] }, {}));
    expect(content.state).toBe("answerable");

    const idless: AskRowLike = questionRow({ question: "Which?", options: ["a"] });
    const stripped: AskRowLike = {
      ...idless,
      question:
        idless.question === null
          ? null
          : { ...idless.question, payload: { question: "Which?", options: ["a"] } },
    };
    const out = askContent(stripped);
    expect(out.state).toBe("unavailable");
    expect(out.unavailable).toBe("no_question_id");
  });

  it("names an event whose session binding has been evicted", () => {
    const content = askContent(
      questionRow({ question: "Which?", options: ["a"] }, { session_id: null }),
    );
    expect(content.state).toBe("unavailable");
    expect(content.unavailable).toBe("no_session");
  });

  it("names a question that admits no answer at all", () => {
    const content = askContent(
      questionRow({ question: "Which?", options: [], allow_free_text: false }),
    );
    expect(content.affordance).toBe("none");
    expect(content.state).toBe("unavailable");
    expect(content.unavailable).toBe("no_answer_shape");
  });
});

// --------------------------------------------------------------------------
// The DOM half: the affordance a live question actually renders.
//
// `renderToStaticMarkup` plus the environment's parser, as in
// `components.test.tsx` — the assertions are the `data-*` attributes a
// Playwright assertion reads, so no component harness is added for them. What a
// static render cannot reach is the post's own outcome (`self`, `abandoned`),
// because that state is owned by the widget and arrives from the route; §7A.12
// case 5 asserts those in the browser, against a real answer.

function render(row: AskRowLike): Document {
  const markup = renderToStaticMarkup(<AskUserWidget row={row} />);
  return new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
}

describe("§7A.7 — the widget's controls, and the `disabled` that closed", () => {
  it("offers one enabled button per option, and a text field when free text is allowed", () => {
    const document_ = render(
      questionRow({
        question: "Which bore fit?",
        options: [
          { label: "H7 clearance", consequence: "the shaft slides by hand" },
          { label: "H7/p6 press", consequence: "the shaft needs an arbor press" },
        ],
        allow_free_text: true,
      }),
    );
    const ask = document_.querySelector("[data-ask-state]");
    expect(ask?.getAttribute("data-ask-state")).toBe("answerable");
    expect(ask?.getAttribute("data-ask-affordance")).toBe("options_text");
    expect(ask?.getAttribute("data-question-id")).toBe("q-ask-0");

    const options = [...document_.querySelectorAll("[data-ask-option]")];
    expect(options.map((node) => node.getAttribute("data-ask-option"))).toEqual([
      "H7 clearance",
      "H7/p6 press",
    ]);
    // The hardcoded `disabled` at `AskUserWidget.tsx`:101 is what §7A.7 calls a
    // deviation and closes. A live, unanswered question is answerable.
    expect(options.some((node) => node.hasAttribute("disabled"))).toBe(false);
    expect(document_.querySelector("[data-ask-text]")).not.toBeNull();
    expect(document_.querySelector('[data-ask-submit="text"]')).not.toBeNull();
  });

  it("renders no text field at all when the question forbade free text", () => {
    const document_ = render(
      questionRow({ question: "Which?", options: ["a", "b"], allow_free_text: false }),
    );
    expect(document_.querySelector("[data-ask-affordance]")?.getAttribute("data-ask-affordance"))
      .toBe("options");
    expect(document_.querySelector("[data-ask-text]")).toBeNull();
    expect(document_.querySelector('[data-ask-submit="text"]')).toBeNull();
  });

  it("renders a multi-select and one submit for a multi question", () => {
    const document_ = render(
      questionRow({
        question: "Which features may be dropped?",
        options: ["The rim fillet", "The drain slot"],
        multi: true,
        allow_free_text: false,
      }),
    );
    const options = [...document_.querySelectorAll("[data-ask-option]")];
    expect(options.every((node) => node.getAttribute("type") === "checkbox")).toBe(true);
    // Nothing is selected yet, so the one submit is inert — and inert because
    // there is no answer to send, which is a different thing from unanswerable.
    const submit = document_.querySelector('[data-ask-submit="options"]');
    expect(submit?.hasAttribute("disabled")).toBe(true);
    expect(document_.querySelector('[data-ask-submit="text"]')).toBeNull();
  });

  it("states the reason when a live question admits no answer this page can give", () => {
    const document_ = render(
      questionRow({ question: "Which?", options: [], allow_free_text: false }),
    );
    const ask = document_.querySelector("[data-ask-state]");
    expect(ask?.getAttribute("data-ask-state")).toBe("unavailable");
    expect(ask?.getAttribute("data-ask-unavailable")).toBe("no_answer_shape");
    expect(document_.querySelector("[data-ask-disabled]")?.textContent ?? "").toContain(
      "admits no answer",
    );
  });
});
