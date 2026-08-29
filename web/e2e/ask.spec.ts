// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Answering `ask_user` from the browser (INTERFACE.md §7A.7; plan item 1).
//
// G4's deliverable text says `ask_user widgets`, and §7A.7 rules that "a widget
// that cannot be answered is a rendering of a question". This file is the
// acceptance evidence the plan names for that item:
//
//   * `data-answered-by="self"` on the widget that answered;
//   * `data-answered-by="other"` on a second attached client;
//   * a question that is no longer open renders `data-ask-state="abandoned"`
//     **in place** — §7A.7's first-class rendering of `404 unknown_question`.
//
// THE VALUE THAT REACHES THE RUN IS THE SERVER'S LABEL. The scripted question
// offers `{label, consequence}` options, and the harness publishes the labels in
// the handshake, so this spec asserts the *server's* string round-tripping
// through a click — which is the §7A.7 tightening (§19.29) seen from the browser
// end: before it, `agent_bridge/cli.py` answered the same question with a Python
// dict repr.
//
// TWO ATTACHED CLIENTS, NO LOCK. §2.7: "Both the CLI's numbered prompt and the
// web widget may answer; neither is privileged." Two browser tabs are two
// clients; the losing one learns the outcome from the run's own `answer` event,
// not from a web-side lock over the suspended question, because inventing one
// would be a second session-ownership mechanism.
//
// ON `accepted:false`. The plan lists it with the two `data-answered-by` values.
// It is asserted where it is deterministic — `web/test/stream/ask.test.tsx`
// renders the loser's document — because the server pops a question the instant
// the winner's answer releases the suspended run, so a second client that posts
// after that (which is what a real second client does) receives
// `404 unknown_question` rather than `accepted:false`. That refusal is asserted
// below, on the route and in the DOM; the two-microsecond window in which the
// route answers `accepted:false` instead is not something a browser can be
// aimed at, and a test that tried would be a coin toss.

import { expect, test, type Page } from "@playwright/test";
import { archive } from "./harness/archive";
import { api, open, route, world } from "./harness/world";

const PART = "tread";

interface SessionDocument {
  readonly session_id: string;
}

interface PromptDocument {
  readonly run_id: string;
  readonly run_status: string;
}

interface AnswerDocument {
  readonly accepted: boolean;
  readonly answered_by: string;
  readonly answer: unknown;
}

/** A fresh orchestrator session, created the way §7A.2 has the browser create one. */
async function createSession(): Promise<string> {
  const created = await api<SessionDocument>("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: "orchestrator" }),
  });
  return created.session_id;
}

/**
 * Start a turn and **do not wait for it**: the whole point is that it suspends.
 *
 * `POST /sessions/{id}/prompt` blocks for the length of the run, and this run
 * cannot finish until somebody answers the question it raises. The promise is
 * returned so the test can settle it at the end rather than leave it dangling.
 */
function startTurn(sessionId: string): Promise<PromptDocument> {
  return api<PromptDocument>(`/sessions/${encodeURIComponent(sessionId)}/prompt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: `${world().ask.sentinel}: which wall thickness?` }),
  });
}

async function openSession(page: Page, sessionId: string): Promise<void> {
  await open(page, route(PART, { s: sessionId }));
  await expect(page.locator('[data-testid="stream-panel"]')).toBeVisible();
}

/** The widget for the suspended question, once the socket has carried it. */
function widget(page: Page) {
  return page.locator('[data-testid="transcript"] [data-ask-state]').last();
}

// --------------------------------------------------------------------------
// §7A.7 — self, other, and the label the server sent

test("a browser answers a suspended ask_user; a second client sees who won (§7A.7)", async ({
  context,
}, testInfo) => {
  test.setTimeout(300_000);
  const labels = world().ask.options.map((option) => option.label);
  const session = await createSession();

  const answering = await context.newPage();
  const observing = await context.newPage();
  await openSession(answering, session);
  await openSession(observing, session);

  const turn = startTurn(session);
  try {
    // The question reaches BOTH attached clients: §2.7 broadcasts it, and
    // neither tab is privileged.
    for (const page of [answering, observing]) {
      await expect(widget(page)).toHaveAttribute("data-ask-state", "answerable", {
        timeout: 180_000,
      });
    }
    // §7A.7's affordance, derived from the question's OWN params and asserted
    // against the harness's answer for the question it scripted. The scripted
    // question declares `allow_free_text: false`, so there is no text field —
    // §15.35 refuses "a free-text answer to a question that declared
    // `allow_free_text: false`", and the schema's default for the field is
    // `true`, so this assertion also proves the `question` event carried the
    // param at all (`agent/src/main.ts`).
    await expect(widget(answering)).toHaveAttribute(
      "data-ask-affordance",
      world().ask.affordance,
    );
    const options = answering.locator('[data-testid="transcript"] [data-ask-option]');
    const rendered = await options.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-ask-option")),
    );
    expect(rendered).toEqual(labels);
    await expect(answering.locator("[data-ask-text]")).toHaveCount(0);

    // One click, and the value that leaves is the label the server sent.
    await options.nth(1).click();

    await expect(widget(answering)).toHaveAttribute("data-answered-by", "self", {
      timeout: 60_000,
    });
    await expect(widget(answering)).toHaveAttribute("data-ask-state", "answered");
    // The second client learns it from the run's `answer` event, and reports the
    // only thing it can honestly report about who acted.
    await expect(widget(observing)).toHaveAttribute("data-answered-by", "other", {
      timeout: 60_000,
    });

    // Both render the SAME recorded selection, and it is the option's `label` —
    // not a rendered string, not a serialized option object.
    for (const page of [answering, observing]) {
      const answer = page.locator('[data-testid="transcript"] [data-ask-answer]').last();
      await expect(answer).toContainText(labels[1] ?? "");
      expect(await answer.textContent()).not.toContain("consequence");
    }

    // The run resumes with that selection and reaches its own terminal state.
    const result = await turn;
    expect(result.run_status).toBe("completed");

    // A client that answers now is not a loser, it is late: the winning answer
    // released the suspended run, and the run took its question with it. §7A.7
    // makes that one rendered state — "answered, abandoned, or never asked".
    const questionId = questionIdOf(await widget(observing).getAttribute("data-question-id"));
    const late = await answerLate(session, questionId);
    expect(late.status).toBe(404);
    expect(late.reason).toBe("unknown_question");

    await archive(answering, testInfo, "ask-answered-self");
    await archive(observing, testInfo, "ask-answered-other");
  } finally {
    await turn.catch(() => undefined);
  }
});

// --------------------------------------------------------------------------
// §7A.7 — the abandoned state, rendered in place

test("a question whose run was cancelled renders as abandoned, in place (§7A.7)", async ({
  page,
}, testInfo) => {
  test.setTimeout(300_000);
  const session = await createSession();
  await openSession(page, session);

  const turn = startTurn(session);
  try {
    const ask = widget(page);
    await expect(ask).toHaveAttribute("data-ask-state", "answerable", { timeout: 180_000 });

    // The run id is the server's own, read back out of the identity it rendered
    // (`<run_id>#<seq>`, §2.8) rather than minted here — §15.29 gives the client
    // no run ids of its own.
    const eventId = (await ask.getAttribute("data-event-id")) ?? "";
    const runId = eventId.split("#")[0] ?? "";
    expect(runId).not.toBe("");
    const cancelled = await api<{ abandoned_questions: number }>(
      `/runs/${encodeURIComponent(runId)}/cancel`,
      { method: "POST" },
    );
    // The suspended tool call fails honestly instead of being handed a
    // fabricated selection; that is the question this widget is still showing.
    expect(cancelled.abandoned_questions).toBe(1);

    // The controls are still live — nothing told this tab the question had gone,
    // and §15.33 mints no event to tell it. The answer attempt is what learns it,
    // and the widget renders the refusal where the question is.
    await page.locator('[data-testid="transcript"] [data-ask-option]').first().click();
    await expect(ask).toHaveAttribute("data-ask-state", "abandoned", { timeout: 60_000 });
    await expect(ask).toHaveAttribute("data-refusal-reason", "unknown_question");
    await expect(ask.locator("[data-ask-abandoned]")).toHaveCount(1);
    await expect(ask).not.toHaveAttribute("data-answered-by", /self|other/);

    await archive(page, testInfo, "ask-abandoned");
  } finally {
    await turn.catch(() => undefined);
  }
});

function questionIdOf(attribute: string | null): string {
  expect(attribute, "the widget rendered no question id to answer with").toBeTruthy();
  return attribute ?? "";
}

/** One late answer, kept raw: the refusal *is* the assertion, so `api` cannot throw it away. */
async function answerLate(
  sessionId: string,
  questionId: string,
): Promise<{ status: number; reason: string; document: AnswerDocument | null }> {
  const { base_url, token } = world();
  const response = await fetch(
    `${base_url}/api/v1/sessions/${encodeURIComponent(sessionId)}/answer`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Connection: "close",
      },
      body: JSON.stringify({ question_id: questionId, answer: "Keep 2 mm walls" }),
    },
  );
  const body = (await response.json()) as { reason?: string } & AnswerDocument;
  return {
    status: response.status,
    reason: body.reason ?? "",
    document: response.ok ? body : null,
  };
}
