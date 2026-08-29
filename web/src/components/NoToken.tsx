// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// INTERFACE.md §2.2, the last two sentences, are the whole specification of this
// component:
//
//   "Without a token the app renders one non-interactive panel explaining how to
//   obtain one; **it never prompts for credentials, because there are none to
//   prompt for.** No login, no cookie, no refresh, no user model."
//
// So: no form, no input, no button that retries. The panel names the command
// that mints a token and stops. A "sign in" affordance here would be a lie about
// a system that has no accounts, and a retry button would be a control whose
// only outcome is the same panel.
//
// This and the fatal screen are the ONLY two surfaces permitted `.display`
// (§3.8) — 18px exists for the two screens that are the entire viewport.

import { copy } from "../copy";
import { Icon } from "../system";
import styles from "./NoToken.module.css";

export function NoToken(): React.JSX.Element {
  return (
    <div className={styles["screen"]} data-testid="no-token">
      <div className={styles["card"]}>
        <Icon id="alert" size={22} className={styles["icon"]} />
        <h1 className={styles["title"]}>{copy.noToken.title}</h1>
        <p className={styles["body"]}>{copy.noToken.body}</p>
        <pre className={styles["command"]}>{copy.noToken.command}</pre>
        <p className={styles["hint"]}>{copy.noToken.hint}</p>
      </div>
    </div>
  );
}
