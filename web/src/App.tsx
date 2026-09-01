// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The app root: the query client, the token gate, and the one server→pin edge.

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MissingTokenError, WorkspaceError } from "./api/client";
import { useBuild, useParts } from "./api/queries";
import { subscribeToken, workspaceToken } from "./api/token";
import { NoToken } from "./components/NoToken";
import { Shell } from "./components/Shell";
import { useWorkspace, workspaceStore } from "./state/react";

const QUERY_DEFAULTS: ConstructorParameters<typeof QueryClient>[0] = {
  defaultOptions: {
    queries: {
      // A refusal is the server's considered answer, not a transient failure.
      // §2.4's taxonomy is closed, and retrying a `stale_selection` or an
      // `unknown_artifact` produces the same refusal at the cost of load.
      retry: (failureCount, error) => {
        if (error instanceof MissingTokenError) return false;
        if (error instanceof WorkspaceError) return false;
        return failureCount < 2;
      },
      refetchOnWindowFocus: true,
    },
  },
};

/**
 * The token this tab holds, subscribed so a live 401 remounts the gate (#80).
 *
 * `workspaceToken()` is not reactive on its own. `dropToken()` (and a paste
 * recovery) notify; this hook is the one place the gate re-reads.
 */
function useHeldToken(): string | null {
  const [token, setToken] = useState(workspaceToken);
  useEffect(() => subscribeToken(() => setToken(workspaceToken())), []);
  return token;
}

/**
 * The **only** path from a server response to the pin.
 *
 * §4.5's TIGHTENING (binds G5.6): "Publishing a new build **never** advances a
 * pin whose `pin_mode` is `"pinned"`." `observeCurrent` enforces that itself, so
 * this effect can fire on every build response without ever moving a held pin.
 */
function CurrentBuildObserver(): null {
  const part = useWorkspace((s) => s.part);
  const build = useBuild(part);
  const ref = build.data?.artifact_ref ?? null;
  useEffect(() => {
    workspaceStore.observeCurrent(ref);
  }, [ref]);
  return null;
}

/**
 * With no part in the URL, open the project's first part.
 *
 * A navigation default, not a fact: it decides what the workspace *shows*, and
 * nothing it decides is ever rendered as a number.
 */
function DefaultPart(): null {
  const part = useWorkspace((s) => s.part);
  const parts = useParts();
  const first = parts.data?.parts[0]?.name ?? null;
  useEffect(() => {
    if (part === null && first !== null) workspaceStore.update({ part: first });
  }, [part, first]);
  return null;
}

function SignedInApp(): React.JSX.Element {
  // A fresh client per hold: a 401 that remounts this tree must not keep the
  // refusals of the token that was just forgotten.
  const [client] = useState(() => new QueryClient(QUERY_DEFAULTS));
  return (
    <QueryClientProvider client={client}>
      <DefaultPart />
      <CurrentBuildObserver />
      <Shell />
    </QueryClientProvider>
  );
}

export function App(): React.JSX.Element {
  // §2.2: with no token, one panel — and no query is issued, because every
  // request would 401 and the panel is the answer either way. The gate
  // re-renders when the hold changes, so a live 401 cannot leave a zombie Shell.
  const token = useHeldToken();
  if (token === null) return <NoToken />;
  return <SignedInApp />;
}
