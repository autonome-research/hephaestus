// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { attachAgent } from "../api/attach";
import {
  loadCatalog,
  loadProviders,
  registerProvider,
  type CatalogAuthMethod,
  type CatalogProvider,
  type ProviderRow,
  type ProvidersDocument,
} from "../api/providers";
import { copy } from "../copy";
import { Button, Panel, PanelBody, PanelHeader, PanelNote, Popover } from "../system";
import { refusalText } from "./refusalText";
import styles from "./AddProviderDialog.module.css";

export function AddProviderDialog({ open, providers, onClose, onRegistered, onManage }: {
  readonly open: boolean;
  readonly providers: ProvidersDocument | null;
  readonly onClose: () => void;
  readonly onRegistered: (provider: ProviderRow, method: CatalogAuthMethod) => void;
  readonly onManage: () => void;
}): React.JSX.Element {
  const [method, setMethod] = useState<CatalogAuthMethod | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const stage = useRef<HTMLDivElement>(null);
  const catalog = useQuery({
    queryKey: ["provider-catalog"],
    queryFn: loadCatalog,
    enabled: open,
    retry: false,
    staleTime: 5_000,
  });


  const declared = useMemo(
    () => new Set((providers?.providers ?? []).map((provider) => provider.id)),
    [providers],
  );
  const choices = (catalog.data?.catalog ?? []).filter((provider) =>
    method !== null
    && !declared.has(provider.id)
    && provider.models.length > 0
    && provider.auth_methods.some((auth) => auth.type === method));

  useEffect(() => {
    if (!open) return;
    const target = method === null
      ? stage.current?.querySelector<HTMLElement>('[data-add-provider-method="subscription"]')
      : stage.current?.querySelector<HTMLElement>("[data-add-provider-option]")
        ?? stage.current?.querySelector<HTMLElement>("[data-add-provider-back]");
    target?.focus();
  }, [open, method]);

  const choose = (provider: CatalogProvider): void => {
    if (method === null || busy) return;
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        const current = providers ?? await loadProviders();
        if (current.providers.some((candidate) => candidate.id === provider.id)) {
          throw new Error(copy.providers.add.alreadyRegistered);
        }
        await registerProvider(provider.id, method);
        if (!current.attach.attached) await attachAgent();
        const updated = await loadProviders();
        const row = updated.providers.find((candidate) => candidate.id === provider.id);
        if (row === undefined) throw new Error("Registered provider was not projected");
        onRegistered(row, method);
      } catch (reason) {
        // Registration is intentionally not rolled back: it is a durable,
        // additive write. The provider panel will show what landed and the
        // operator can retry attach/auth without losing unrelated declarations.
        setError(reason);
      } finally {
        setBusy(false);
      }
    })();
  };

  return <Popover open={open} onClose={onClose} label={copy.providers.add.title}
    variant="dialog" data-add-provider-dialog="">
    <Panel label={copy.providers.add.title}>
      <PanelHeader title={copy.providers.add.title} />
      <PanelBody className={styles["body"]}>
        <div ref={stage}>
        {method === null ? <>
          <PanelNote>{copy.providers.add.methodFirst}</PanelNote>
          <div className={styles["methods"]} data-add-provider-methods="">
            <Button variant="secondary" onClick={() => setMethod("subscription")}
              data-add-provider-method="subscription">{copy.providers.add.subscription}</Button>
            <Button variant="secondary" onClick={() => setMethod("api_key")}
              data-add-provider-method="api_key">{copy.providers.add.apiKey}</Button>
          </div>
        </> : <>
          <div className={styles["back"]}>
            <Button variant="quiet" onClick={() => { setMethod(null); setError(null); }}
              data-add-provider-back="">{copy.providers.add.back}</Button>
          </div>
          <PanelNote>{method === "subscription" ? copy.providers.add.chooseSubscription : copy.providers.add.chooseApiKey}</PanelNote>
          {catalog.isPending ? <PanelNote>{copy.providers.add.loading}</PanelNote> : null}
          {catalog.isError ? <PanelNote>{refusalText(catalog.error)}</PanelNote> : null}
          <div className={styles["providers"]} role="listbox" aria-label={copy.providers.add.chooseProvider}>
            {choices.map((provider) => <button key={provider.id} type="button" role="option"
              aria-selected="false" disabled={busy} className={styles["provider"]}
              onClick={() => choose(provider)} data-add-provider-option={provider.id}>
              <span>{provider.name}</span>
              <small>{provider.auth_methods.find((auth) => auth.type === method)?.label}</small>
            </button>)}
          </div>
          {!catalog.isPending && !catalog.isError && choices.length === 0
            ? <PanelNote>{copy.providers.add.none}</PanelNote> : null}
        </>}
        </div>
        {providers?.auth_source_linked ? <div data-add-provider-linked="">
          <PanelNote>{copy.providers.linkedWriteNote}</PanelNote>
          <Button variant="secondary" onClick={onManage}>{copy.providers.detailsShow}</Button>
        </div> : null}
        {error === null ? null : <p role="alert" className={styles["error"]}
          data-add-provider-error="">{refusalText(error)}</p>}
      </PanelBody>
    </Panel>
  </Popover>;
}
