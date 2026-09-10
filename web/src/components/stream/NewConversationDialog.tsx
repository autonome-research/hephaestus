// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { useId, useLayoutEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { loadModels, type ModelOption, type ModelsDocument } from "../../api/providers";
import { createSession, type ProfileCapability } from "../../api/sessions";
import { conversationStore } from "../../stream/conversation";
import { sameModel } from "../../stream/composerChrome";
import { workspaceStore } from "../../state/react";
import { Button } from "../../system";
import { copy } from "../../copy";
import { ModelPicker } from "./ModelPicker";
import styles from "./NewConversationDialog.module.css";

export function NewConversationDialog({ profile: initialProfile, part, profiles, opener, onCancel, onCreated }: {
  readonly profile: "orchestrator" | "part";
  readonly part: string | null;
  readonly profiles: readonly ProfileCapability[];
  readonly opener: HTMLElement | null;
  readonly onCancel: () => void;
  readonly onCreated: () => void;
}): React.JSX.Element {
  const client = useQueryClient();
  const scopeId = useId();
  // A proposal is dialog-owned, never the live session model or no-session draft.
  // Freeze the opening default; absent/unknown defaults require deliberate choice.
  const [choice, setChoice] = useState<ModelOption | null>(() => {
    const doc = client.getQueryData<ModelsDocument>(["provider-models"]);
    const proposed = doc?.proposed_default;
    return proposed == null ? null : doc?.providers.flatMap(p => p.models).find(m => sameModel(m, proposed))
      ?? { ...proposed, available: false, unavailable_reason: "model_not_configured" };
  });
  const [isDefault, setIsDefault] = useState(true);
  const [profile, setProfile] = useState(initialProfile);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const catalog = useQuery({ queryKey: ["provider-models"], queryFn: loadModels, retry: false, staleTime: 5_000 });
  const option = catalog.data?.providers.flatMap(p => p.models).find(m => sameModel(m, choice));
  const reviewed = choice === null ? null : option ?? { ...choice, available: false, input: null, unavailable_reason: "model_not_configured" };
  const capability = profiles.find(p => p.profile === profile);
  const title = `${copy.models.createTitle} · ${profile === "part" ? part : "Project"}`;

  useLayoutEffect(() => {
    const node = dialog.current;
    node?.showModal(); // Native top layer: all old controls are inert, not just dimmed.
    return () => {
      node?.close();
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [opener]);

  const create = () => {
    if (pending.current || reviewed?.available !== true || (profile === "part" && part === null)) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    void createSession(profile, profile === "part" ? part : null, reviewed).then(document => {
      conversationStore.modelSnapshot(document.session_id, document.model_state, document.execution, conversationStore.ticket());
      workspaceStore.update({ session: document.session_id });
      void client.invalidateQueries({ queryKey: ["sessions"] });
      onCreated(); // Idle session only. There is no prompt/draft-copy path here.
    }).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : copy.errors.title);
    }).finally(() => { pending.current = false; setBusy(false); });
  };

  return <dialog ref={dialog} className={styles["dialog"]} aria-label={title} data-new-conversation=""
    onCancel={event => { event.preventDefault(); if (!pending.current) onCancel(); }}
    onKeyDown={event => {
      if (event.key !== "Tab" || event.defaultPrevented || dialog.current?.querySelector('[role="dialog"]')) return;
      const items = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), input:not(:disabled), summary, [tabindex="0"]')]
        .filter(el => el.getClientRects().length > 0);
      const first = items[0]; const last = items.at(-1);
      if (event.shiftKey && (document.activeElement === first || !items.includes(document.activeElement as HTMLElement))) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}>
    <h2 className={styles["title"]}>{title}</h2>
    <div className={styles["scope"]}><label htmlFor={scopeId}>Scope</label>
      <select id={scopeId} className={styles["select"]} value={profile} disabled={busy} onChange={event => setProfile(event.target.value as "orchestrator" | "part")}>
        <option value="orchestrator">Project</option>
        {part === null ? null : <option value="part">Part — {part}</option>}
      </select>
    </div>
    {capability ? <p className={styles["note"]}>{copy.composer.profileWhat(capability.profile, capability.can_delegate, capability.part_scoped)}</p> : null}
    <ModelPicker sessionId={null} creation={{ choice: reviewed, isDefault, busy,
      onChoose: model => { setChoice(model); setIsDefault(false); } }} />
    {reviewed === null ? <p role="status">{copy.models.none}</p> : null}
    <p className={styles["note"]}>{copy.models.local}</p>
    {error === null ? null : <p role="alert" data-create-error="">{error}</p>}
    <div className={styles["actions"]}>
      <Button variant="quiet" onClick={onCancel} {...(busy ? { disabled: true as const, reason: copy.models.creating } : {})}>{copy.models.cancel}</Button>
      <Button variant="primary" onClick={create} data-create-confirm=""
        {...(busy || reviewed?.available !== true ? { disabled: true as const, reason: busy ? copy.models.creating : copy.models.none } : {})}>{copy.models.create}</Button>
    </div>
  </dialog>;
}
