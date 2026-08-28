// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The entry point. Order matters and is the contract:
//
// 1. `claimToken()` takes `#t=<token>` out of the fragment into
//    `sessionStorage` and rewrites the URL (§2.2). It runs **first**, because
//    §4.5's route lives in that same fragment and `#t=…` is not a route.
// 2. `startUrlSync()` hydrates the workspace store from the (now token-free)
//    hash and keeps the two in step for the app's life.
// 3. React mounts.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { claimToken } from "./api/token";
import { copy } from "./copy";
import { startUrlSync } from "./state/react";
import "./global.css";

claimToken();
startUrlSync();

document.title = `${copy.app.name} ${copy.app.tagline}`;

const host = document.getElementById("root");
if (host === null) throw new Error("index.html is missing #root");

createRoot(host).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
