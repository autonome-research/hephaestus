// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { currentTurn, readExecutionSessions, useConversation, type CurrentTurn } from "../../stream/conversation";
import { sessionPromptStore } from "../../stream/sessionPrompts";
import { titleForSession } from "../../stream/sessionTitle";
import { useWorkspace } from "../../state/react";
import { copy } from "../../copy";
import styles from "../Shell.module.css";

/** A compact rendering of S2's projection, never a second execution authority. */
export function returnTaskLabel(turn: CurrentTurn): string | null {
  return turn.status === "Waiting for your answer" ? copy.stream.answerNeeded : turn.status;
}

export function ConversationReturn({ onOpen }: { readonly onOpen: (questionId: string | null) => void }): React.JSX.Element {
  const selected = useWorkspace(s => s.session);
  const conversation = useConversation(selected);
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: readExecutionSessions, staleTime: 5_000, retry: false });
  const prompts = useSyncExternalStore(sessionPromptStore.subscribe, sessionPromptStore.getSnapshot, sessionPromptStore.getServerSnapshot);
  const title = selected === null ? copy.stream.noSessionsTitle
    : titleForSession(selected, sessions.data?.sessions ?? [], [], undefined, prompts[selected]);
  const turn = currentTurn(conversation, selected !== null);
  const state = returnTaskLabel(turn);
  return (
    <button type="button" className={styles["strip"]} aria-expanded={false}
      aria-controls="chat-column" data-stream-strip="" data-return-session={selected ?? ""}
      onClick={() => onOpen(turn.questionId ?? null)}>
      <span>{copy.stream.conversation}</span>
      <span className={styles["stripLabel"]} title={title}>{title}</span>
      <strong data-return-state="">{state}</strong>
      <span>{copy.stream.open}</span>
    </button>
  );
}
