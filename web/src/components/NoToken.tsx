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
// The panel is still that absence screen, not a settings app and not a sign-in.
// The one extra control is #47's recovery: a single field that holds a `#t=`
// the page was given (or a new one after a 401), because rewriting the fragment
// is how you get a pretty route and losing it is how you get a brick. That is
// restoring a bearer, not prompting for an account.
//
// Copy states that this page has no token *held* (#73). A live 401 remounts
// here with §2.4 `unauthorized` (#80) — not "opened without a token."
//
// This and the fatal screen are the ONLY two surfaces permitted `.display`
// (§3.8) — 18px exists for the two screens that are the entire viewport.

import { useState, type FormEvent } from "react";
import { holdPastedToken, tokenAbsence } from "../api/token";
import { copy } from "../copy";
import { Button, Icon, TextInput } from "../system";
import styles from "./NoToken.module.css";

export function NoToken(): React.JSX.Element {
  const absence = tokenAbsence();
  // §2.2 (amended 2026-09-05): ONE branch produces BOTH strings. Branching the
  // body and leaving the heading unconditional is what shipped, and it put "No
  // workspace token" over "the token this page holds was not accepted" — the
  // heading and the body asserting opposite things about one state, with the
  // heading the one an operator reads first (J-web-stream-10).
  const rejected = absence === "unauthorized";
  const title = rejected ? copy.noToken.rejectedTitle : copy.noToken.title;
  const body = rejected ? copy.errors.unauthorized : copy.noToken.body;
  const [paste, setPaste] = useState("");
  const [invalid, setInvalid] = useState<string | undefined>(undefined);
  const empty = paste.trim() === "";

  const apply = (event: FormEvent): void => {
    event.preventDefault();
    if (empty) return;
    const held = holdPastedToken(paste);
    if (held === null) {
      setInvalid(copy.noToken.pasteInvalid);
      return;
    }
    setInvalid(undefined);
  };

  return (
    <div
      className={styles["screen"]}
      data-testid="no-token"
      data-token-absence={absence}
    >
      <div className={styles["card"]}>
        <Icon id="alert" size={22} className={styles["icon"]} />
        <h1 className={styles["title"]}>{title}</h1>
        <p className={styles["body"]}>{body}</p>
        <pre className={styles["command"]}>{copy.noToken.command}</pre>
        <p className={styles["hint"]}>{copy.noToken.hint}</p>
        <form className={styles["recover"]} onSubmit={apply}>
          <TextInput
            label={copy.noToken.paste}
            value={paste}
            onChange={(value) => {
              setPaste(value);
              setInvalid(undefined);
            }}
            invalid={invalid}
            data-token-paste=""
          />
          {empty ? (
            <Button
              variant="primary"
              type="submit"
              disabled
              reason={copy.noToken.paste}
              data-token-apply=""
            >
              {copy.noToken.apply}
            </Button>
          ) : (
            <Button variant="primary" type="submit" data-token-apply="">
              {copy.noToken.apply}
            </Button>
          )}
        </form>
      </div>
    </div>
  );
}
