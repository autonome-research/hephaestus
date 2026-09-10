// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { loadModels, type ModelOption } from "../../api/providers";
import { copy } from "../../copy";
import { Button, Popover } from "../../system";
import { filterModels, modelCapability, modelIdentity, modelUnavailableReason, sameModel } from "../../stream/composerChrome";
import { canSelectModel, changeSessionModel, conversationStore, readSessionModel, useConversation } from "../../stream/conversation";
import styles from "./ModelPicker.module.css";

export function ModelPicker({ sessionId }: { readonly sessionId: string | null }): React.JSX.Element {
  const c = useConversation(sessionId);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const list = useRef<HTMLDivElement>(null);
  const catalog = useQuery({ queryKey: ["provider-models"], retry: false, staleTime: 5_000,
    queryFn: async () => {
      const doc = await loadModels();
      conversationStore.catalog(doc);
      return doc;
    },
  });
  const model = sessionId === null ? c.proposal : c.model?.current ?? c.model?.selected ?? null;
  const input = sessionId === null ? c.proposal?.input : c.model?.current?.input;
  const capability = modelCapability(input);
  const prefix = sessionId === null ? c.proposalIsDefault ? copy.models.proposed : copy.models.choice
    : c.model?.current ? copy.models.current : copy.models.saved;
  const busy = sessionId === null ? c.modelPending || c.attempt?.phase === "sending" : !canSelectModel(c);
  const reason = c.modelPending || c.model?.state === "changing" ? copy.models.changing
    : c.checking || c.modelChecking ? copy.models.checking : copy.models.busy;
  const groups = filterModels(catalog.data ?? null, search);
  const options = groups.flatMap(p => p.models);
  const activeIndex = Math.min(active, Math.max(0, options.length - 1));
  const choose = (option: ModelOption) => {
    if (!option.available || busy) return;
    if (sessionId === null) conversationStore.propose(option);
    else void changeSessionModel(sessionId, option);
    setOpen(false);
  };
  const show = () => {
    setSearch(""); setActive(0); setOpen(true);
    void catalog.refetch();
    if (sessionId !== null) void readSessionModel(sessionId, true);
  };
  return <div className={styles["control"]} data-model-control="">
    <Button variant="secondary" onClick={show} className={styles["button"]}
      expanded={open} data-model-button="" {...(busy ? { disabled: true as const, reason } : {})}>
      <span className={styles["srOnly"]}>{prefix}: {model === null ? copy.models.none : modelIdentity(model)} · {capability}. {copy.models.choose}</span>
      <span aria-hidden="true" className={styles["identity"]}>{sessionId === null ? `${prefix}: ` : ""}{model === null ? copy.models.none : sessionId === null ? modelIdentity(model) : model.model_id}</span>
      <span aria-hidden="true" className={styles["badge"]}>{capability}</span>
    </Button>
    <details className={styles["details"]}>
      <summary>{copy.models.details}</summary>
      <p>{prefix}: {model === null ? copy.models.none : modelIdentity(model)} · {capability}</p>
      {c.model?.pending_selection ? <p>{copy.models.changing} {modelIdentity(c.model.pending_selection)}</p> : null}
    </details>
    {sessionId !== null && busy ? <p className={styles["note"]}>{reason}</p> : null}
    {sessionId !== null && c.model?.state === "uncertain" ? <p role="status">{copy.models.uncertain}</p> : null}
    {(sessionId === null && c.proposal?.available === false) || (sessionId !== null && c.model?.reason) ?
      <p role="status">{modelUnavailableReason((sessionId === null ? c.proposal?.unavailable_reason : c.model?.reason) ?? null)}</p> : null}
    {sessionId !== null && c.modelError ? <p role="status">{c.modelError}</p> : null}
    {sessionId !== null && c.modelChecking ? <Button variant="quiet" onClick={() => { void readSessionModel(sessionId, true); }}>{copy.models.retry}</Button> : null}
    <Popover open={open} onClose={() => setOpen(false)} label={copy.models.choose} variant="dialog" className={styles["picker"]}>
      <label htmlFor={`${listId}-search`}>{copy.models.search}</label>
      <input id={`${listId}-search`} className={styles["search"]} role="combobox"
        aria-autocomplete="list" aria-expanded="true" aria-controls={listId}
        aria-activedescendant={options.length > 0 ? `${listId}-${activeIndex}` : undefined}
        value={search} onChange={e => { setSearch(e.target.value); setActive(0); }}
        onKeyDown={e => {
          if (e.key === "Enter") {
            e.preventDefault(); e.stopPropagation();
            const option = options[activeIndex]; if (option) choose(option);
          } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            const next = options.length === 0 ? 0 : (activeIndex + (e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length;
            setActive(next);
            list.current?.querySelector(`[id="${listId}-${next}"]`)?.scrollIntoView?.({ block: "nearest" });
          }
        }} />
      <p className={styles["note"]}>{prefix}: {model === null ? copy.models.none : modelIdentity(model)} · {capability}</p>
      {busy ? <p role="status">{reason}</p> : null}
      {catalog.isError ? <p role="status">{copy.models.catalogFailed}</p> : null}
      {catalog.isPending ? <p role="status">{copy.models.catalogLoading}</p> : null}
      <div id={listId} ref={list} role="listbox" aria-label={copy.models.choose} className={styles["options"]}>
        {groups.map(p => <div key={p.provider_id} role="group" aria-label={`${p.name} (${p.provider_id})`}>
          <h3 className={styles["provider"]}>{p.name} · {p.provider_id}</h3>
          {p.models.map(option => {
            const index = options.indexOf(option);
            return <div key={option.model_id} id={`${listId}-${index}`} role="option"
              aria-selected={sameModel(model, option)} aria-disabled={!option.available || busy}
              className={styles["option"]} data-highlighted={index === activeIndex}
              onClick={() => choose(option)}>
              <span>{modelIdentity(option)}</span>
              <span>{option.name} · {modelCapability(option.input)}</span>
              {!option.available ? <span>{modelUnavailableReason(option.unavailable_reason)}</span> : null}
            </div>;
          })}
        </div>)}
      </div>
      {options.length === 0 && !catalog.isPending && !catalog.isError ? <p>{copy.models.noMatches}</p> : null}
      <p className={styles["note"]}>{copy.models.local}</p>
      <Button variant="quiet" onClick={() => setOpen(false)}>{copy.models.done}</Button>
    </Popover>
  </div>;
}
