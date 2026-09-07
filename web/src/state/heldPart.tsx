// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Which part a held artifact came from (INTERFACE.md §4.1, §4.5).
//
// **Read, not remembered** (J-web-viewport-5). `WorkspaceStore.heldFrom` is a
// private field explicitly outside §4.5's closed record — "not URL state: the
// closed record does not grow a field for a sentence" — written on hold and
// cleared on follow-current and on adopting a state that is not pinned or
// carries a different reference. That decision is right about the record and
// wrong about the fact: a reload or a pasted URL arrives with the pin held and
// nothing to say which part minted it, so the workspace stopped being able to
// answer a question §4.1 says the operator must never have to ask.
//
// The pinned reference IS an artifact reference and `GET /artifacts/{ref}/meta`
// is already served and keyless, so the fact is a server value — attributable,
// surviving a reload, and the closed record does not grow.
//
// **The projection does not name the part yet**, and that is the one server
// change this needs: a `part` field on `http/artifacts.py::artifact_meta`, not a
// route. Until it lands the value falls back to the remembered one, which is
// correct within a session and `null` after a reload — today's behaviour
// exactly, so nothing regresses while the client half waits.
//
// A CONTEXT rather than a hook that queries, because four components need the
// answer and only one of them can own the request: `ArtifactPin`, the stage
// marker, the inspector marker and (through the pin) the export subject would
// otherwise each mount their own. It also keeps the answer reachable from a
// component rendered WITHOUT a query client — every panel unit test renders its
// component bare — where the hook falls back to the store rather than throwing.

import { createContext, useContext, type ReactNode } from "react";
import { useArtifactMeta } from "../api/queries";
import { useWorkspace, workspaceStore } from "./react";

/** `null` means "no provider above me", which is a different state from "unknown". */
const HeldPartContext = createContext<{ readonly part: string | null } | null>(null);

export function HeldPartProvider({ children }: { readonly children: ReactNode }): React.JSX.Element {
  const pinMode = useWorkspace((s) => s.pin_mode);
  const artifactRef = useWorkspace((s) => s.artifact_ref);
  const meta = useArtifactMeta(pinMode === "pinned" ? artifactRef : null);
  const part =
    pinMode === "pinned" ? (meta.data?.part ?? workspaceStore.heldFromPart()) : null;
  return <HeldPartContext.Provider value={{ part }}>{children}</HeldPartContext.Provider>;
}

/**
 * The part the held artifact was minted for, or `null`.
 *
 * `null` while nothing is held, and `null` where neither the server nor this
 * session can say — a marker that guessed which part a pasted reference came
 * from would be exactly the fabricated content §4.4 forbids.
 */
export function useHeldPart(): string | null {
  const provided = useContext(HeldPartContext);
  return provided === null ? workspaceStore.heldFromPart() : provided.part;
}
