// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { loadModels, type ModelOption } from "../../api/providers";
import type { ThinkingLevel } from "../../api/sessions";
import { copy } from "../../copy";
import { ProvidersPanel } from "../ProvidersPanel";
import { Button, Popover } from "../../system";
import { filterModels, modelCapability, modelIdentity, modelUnavailableReason, sameModel } from "../../stream/composerChrome";
import { canSelectModel, changeSessionModel, conversationStore, readSessionModel, useConversation } from "../../stream/conversation";
import styles from "./ModelPicker.module.css";

export interface CreationModelChoice {
  readonly choice: ModelOption | null;
  readonly isDefault: boolean;
  readonly busy: boolean;
  readonly onChoose: (option: ModelOption) => void;
}

const EFFORTS: readonly ThinkingLevel[] = ["low", "medium", "high"];
const effortLabel = (effort: ThinkingLevel): string => effort === "low" ? copy.composer.effortLow
  : effort === "high" ? copy.composer.effortHigh : copy.composer.effortMedium;

export function ModelPicker({ sessionId, creation, effort = "medium", onEffort }: {
  readonly sessionId: string | null;
  readonly creation?: CreationModelChoice;
  /** Accepted for source compatibility; metadata now lives in the picker. */
  readonly detailsContainer?: HTMLElement | null;
  readonly effort?: ThinkingLevel;
  readonly onEffort?: ((effort: ThinkingLevel) => void) | undefined;
}): React.JSX.Element {
  const c = useConversation(sessionId);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const list = useRef<HTMLDivElement>(null);
  const catalog = useQuery({
    queryKey: ["provider-models"], retry: false, staleTime: 5_000,
    queryFn: async () => {
      const doc = await loadModels();
      if (creation === undefined) conversationStore.catalog(doc);
      return doc;
    },
  });
  const model = creation ? creation.choice : sessionId === null ? c.proposal : c.model?.current ?? c.model?.selected ?? null;
  const input = creation ? creation.choice?.input : sessionId === null ? c.proposal?.input : c.model?.current?.input;
  const capability = modelCapability(input);
  const prefix = sessionId === null ? (creation?.isDefault ?? c.proposalIsDefault) ? copy.models.proposed : copy.models.choice
    : c.model?.current ? copy.models.current : copy.models.saved;
  const label = sessionId === null ? copy.models.newLabel : copy.models.currentLabel;
  const busy = creation ? creation.busy : sessionId === null ? c.modelPending || c.attempt?.phase === "sending" : !canSelectModel(c);
  const reason = creation?.busy ? copy.models.creating : c.modelPending || c.model?.state === "changing" ? copy.models.changing
    : c.checking || c.modelChecking ? copy.models.checking : copy.models.busy;
  const groups = filterModels(catalog.data ?? null, search);
  const options = groups.flatMap(provider => provider.models);
  const activeIndex = Math.min(active, Math.max(0, options.length - 1));
  const identity = model === null ? copy.models.none : "name" in model && typeof model.name === "string" ? model.name : model.model_id;

  const choose = (option: ModelOption) => {
    if (!option.available || busy) return;
    if (creation) creation.onChoose(option);
    else if (sessionId === null) conversationStore.propose(option);
    else void changeSessionModel(sessionId, option);
    setOpen(false);
  };
  const show = () => {
    setSearch(""); setActive(0); setOpen(true);
    void catalog.refetch();
    if (sessionId !== null) void readSessionModel(sessionId, true);
  };

  /*
   * §7A: "keyboard option navigation remain required". The handler hangs on the
   * LISTBOX, where the option buttons bubble to it, AND on the search field,
   * which is a sibling of the listbox and therefore bubbles nowhere near it.
   * Attaching it only to the listbox left a filter box you could type into and
   * not act on — Enter and the arrows were dead in the one control whose whole
   * purpose is to narrow the list before you pick from it.
   */
  const navigate = (event: React.KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const option = options[activeIndex];
      if (option) choose(option);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = options.length === 0 ? 0 : (activeIndex + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length;
      setActive(next);
      list.current?.querySelector<HTMLElement>(`[id="${listId}-${next}"]`)?.focus();
    }
  };

  return <div className={styles["control"]} data-model-control="">
    {creation ? <p className={styles["note"]}>{label}</p> : null}
    <Button
      variant="secondary"
      icon="levels"
      iconLabel={creation ? undefined : `${label}. ${prefix}: ${model === null ? copy.models.none : modelIdentity(model)} · ${capability}. ${copy.composer.effort}: ${effortLabel(effort)}`}
      onClick={show}
      className={styles["button"]}
      expanded={open}
      data-model-button=""
      title={`${label}. ${prefix}: ${model === null ? copy.models.none : modelIdentity(model)}. ${copy.composer.effort}: ${effortLabel(effort)}.`}
      {...(busy ? { disabled: true as const, reason } : {})}
    >
      {creation ? <>
        <span className={styles["srOnly"]}>{label}. {prefix}: {model === null ? copy.models.none : modelIdentity(model)} · {capability}. {copy.composer.effort}: {effortLabel(effort)}.</span>
        <span aria-hidden="true" className={styles["identity"]}>{identity}</span>
        <span className={styles["badge"]}>{capability}</span>
      </> : undefined}
    </Button>
    <Popover open={open} onClose={() => setOpen(false)} label={copy.models.choose}
      className={creation ? `${styles["picker"]} ${styles["pickerBelow"]}` : styles["picker"]}>
      <div className={styles["pickerGrid"]}>
        <section className={styles["modelColumn"]}>
          <h3 className={styles["heading"]}>{copy.models.label}</h3>
          {options.length > 8 ? <input id={`${listId}-search`} className={styles["search"]} role="combobox"
            aria-label={copy.models.search} aria-autocomplete="list" aria-expanded="true" aria-controls={listId}
            aria-activedescendant={options.length > 0 ? `${listId}-${activeIndex}` : undefined}
            value={search} onChange={event => { setSearch(event.target.value); setActive(0); }}
            onKeyDown={navigate} /> : null}
          {catalog.isError ? <p role="status">{copy.models.catalogFailed}</p> : null}
          {catalog.isPending ? <p role="status">{copy.models.catalogLoading}</p> : null}
          <div id={listId} ref={list} role="listbox" aria-label={copy.models.choose} className={styles["options"]}
            onKeyDown={navigate}>
            {groups.map(provider => <div key={provider.provider_id} role="group" aria-label={`${provider.name} (${provider.provider_id})`}>
              {groups.length > 1 ? <h4 className={styles["provider"]}>{provider.name}</h4> : null}
              {provider.models.map(option => {
                const index = options.indexOf(option);
                return <button key={option.model_id} id={`${listId}-${index}`} type="button" role="option"
                  aria-selected={sameModel(model, option)} aria-disabled={!option.available || busy}
                  className={styles["option"]} data-highlighted={index === activeIndex}
                  onClick={() => choose(option)}>
                  <span aria-hidden="true">{sameModel(model, option) ? "✓" : ""}</span>
                  <span>{option.name}</span>
                  {!option.available ? <small>{modelUnavailableReason(option.unavailable_reason)}</small> : null}
                </button>;
              })}
            </div>)}
          </div>
          {options.length === 0 && !catalog.isPending && !catalog.isError ? <p>{copy.models.noMatches}</p> : null}
        </section>
        {!creation && onEffort ? <section className={styles["effortColumn"]} aria-label={copy.composer.effort}>
          <h3 className={styles["heading"]}>{copy.composer.effort}</h3>
          {EFFORTS.map(level => <Button key={level} variant="toggle" pressed={level === effort}
            onClick={() => onEffort(level)} data-effort-option={level}>{effortLabel(level)}</Button>)}
        </section> : null}
      </div>
      {/* §23, amended 2026-09-20: the providers surface moved here from the
          rail. It is the only place that signs in, adopts a discovered
          credential and lists egress hosts — the list above only CHOOSES among
          models a credential already makes available, so the two belong behind
          one control rather than 600px apart. Closing the popover on attach
          puts the composer back in front of the operator, which is §23.0's
          success condition. */}
      <div className={styles["providers"]} data-model-providers="">
        <ProvidersPanel onAttached={() => { setOpen(false); }} />
      </div>
    </Popover>
    {sessionId !== null && c.model?.state === "uncertain" ? <p className={styles["note"]} role="status">{copy.models.uncertain}</p> : null}
    {/* WHY A CHOICE IS REFUSED, ON BOTH SIDES (restored 2026-09-20). The
        session arm survived the picker rework and the CREATION arm did not, so
        a proposed-but-ineligible default left Create disabled with nothing
        saying why — the exact shape §7A.8 forbids for the send path, on the
        one dialog where the operator cannot simply pick something else and
        move on. `creation.choice` is the dialog's own selection;
        `c.proposal` is the server's default when nothing has been chosen. */}
    {(sessionId === null && model !== null && "available" in model && !model.available)
      || (sessionId !== null && c.model?.reason) ? (
      <p className={styles["note"]} role="status">
        {modelUnavailableReason((sessionId === null
          ? creation ? creation.choice?.unavailable_reason : c.proposal?.unavailable_reason
          : c.model?.reason) ?? null)}
      </p>
    ) : null}
    {sessionId !== null && c.modelError ? <p className={styles["note"]} role="status">{c.modelError}</p> : null}
    {/* The read can be retried by hand (restored 2026-09-20). A model state
        stuck on "checking" is the one state polling cannot end on its own, and
        without this the operator's only move is a page reload. */}
    {sessionId !== null && c.modelChecking ? (
      <Button variant="quiet" onClick={() => { void readSessionModel(sessionId, true); }}>{copy.models.retry}</Button>
    ) : null}
  </div>;
}
