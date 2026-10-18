# OneVoice / YUI — Python Routing Threat Model

**Status:** Proposed security review input — NOT production security certification
**Date:** 2026-10-18  
**Applies to:** the current Python YazSes daemon and **future opt-in** named-destination routing experiments only  
**Out of scope for this version:** third-party autonomous agent platforms, mobile cross-device relay, privileged/locked desktop control, generic plugin loading

This is a scoped **new threat model**, not an update to the archived [Rust-era model](../threat-model.md). The archived document states that it does not model the shipping Python application. Read [ADR-011](../adr/adr-011.md), [ADR-018](../adr/adr-018-feature-packs-and-the-plugin-question.md), [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-020](../adr/adr-020-agent-protocols.md), [ADR-021](../adr/adr-021-invest-in-error-cost.md), [ADR-022](../adr/adr-022-a-confirmation-a-voice-user-cannot-give.md) (Proposed), and [ADR-025](../adr/adr-025-grounded-interaction-kernel.md) (Proposed) before implementing actions.

## Security objectives

1. An utterance never goes to a wrong window, browser tab, account, conversation or specific editable field because an adapter guessed.
2. Speech transcription/intent confidence, gaze, app-provided content, API output, and UI metadata are **observations**, not permission.
3. Draft insertion, provider submission, file/shell/commit mutation and irreversible effects have independent authority requirements.
4. Default dictation remains offline and unchanged; any new transmission of dictated content requires the existing ADR-019 egress review.
5. Every side effect has a truthful result. A successful low-level keyboard call does not prove that the intended editor received the text. Remote task acceptance is not completion.
6. Failure is safe: missing semantic field, inaccessible OS, stale or ambiguous targets and revoked grants -> abstain/fallback, not best-effort injection.

## Assets and their protection class

| Asset | Consequence of compromise | Required handling |
|---|---|---|
| Raw microphone audio / dictated transcript | Speech privacy and accidental secret disclosure | In-memory only by default; never routine logs / fixtures / analytics |
| Intended destination identity | A prompt or email could reach the wrong account/person | Bind explicit app/account/tab + exact field and context freshness |
| UI/accessibility observations | Can contain private window names, personal labels and document text | Minimize to structured role, IDs, bounds and provenance; redact diagnostic exports |
| Command and confirmation context | Replay or spoof can authorize side effects | Human-triggered, operation-scoped, expiring approval, single pending action semantics |
| Provider tokens / agent credentials | Account compromise, financial charges | Platform credential manager and strict per-provider grant; never print or commit |
| Delivery outcome | False "sent"/"completed" can cause data loss or repeat | Separate attempted / unknown / verified / accepted / completed |
| Model/provider billing | Silent charges, runaway recursion or retries | Explicit opt-in costs and provider/account, quota limits, no blind retry |

## Trust boundaries

```text
B0 real human activation vs untrusted ambient / replayed speech
    -> local capture / STT (observation; not authority)
B1 transcript vs routing classifier
    -> plain dictate / explicit named-draft / proposed submit
B2 untrusted OS & app metadata (titles, role labels, PIDs, accessible tree)
    -> approved destination registry + provenance-bound semantic resolver
B3 target snapshot vs OS execution moment
    -> revalidation + secure/editable field check
B4 proposal vs human confirmation / authority gate
    -> limited, auditable operation grant (draft != submit)
B5 internal policy vs platform adapter
    -> reviewed allowlist, side effect only when explicitly authorized
B6 authorized external destination vs network/provider
    -> ADR-019 egress + credential, privacy and cost boundary
B7 local data vs diagnostics/research artifacts
    -> synthetic fixtures; aggregate outcomes, no transcript/identity by default
```

A source boundary never inherits authority from the next one. E.g. a webpage saying "send this to my other account" does not add `submit` permission.

## Adversary / failure model

- Malicious or mistaken **co-present speaker**, audio playback, or speech recognized while the wrong mode is active.
- Malicious **document, webpage, accessibility label, prompt, window title or tool result** instructing YazSes to take an action.
- Other **same-user desktop process** that can create spoofed windows, fake metadata or change the focus. X11 is especially weak against other clients in the same X session.
- Compromised / confused **app provider or agent adapter** that broadens scope, misreports outcomes, reorders text or incurs charges.
- Normal **race/failure**: tab closes, field changes, app crashes, network succeeds but acknowledgment is lost, stale gaze or OS permission revoked.
- **No guarantee** of defending against a privileged local attacker or an OS session that permits arbitrary same-user introspection/injection. The aim is application-level risk reduction, not an invented sandbox.

## Threat register and validation

| ID | Threat | Preventive control | Synthetic / human acceptance test |
|---|---|---|---|
| TV-01 | Focus moves between command and insertion | Capture exact target; revalidate app/window/field immediately before operation | Switch windows while speaking; must not insert in new focus |
| TV-02 | Two tabs/apps share a name | Approved registry ID, instance and account; ambiguity -> clarify | Two identically named ChatGPT tabs -> no side effects |
| TV-03 | Window title, WM_CLASS or PID spoof | Do not treat metadata as verified field or identity/auth; pair with accessible semantic field and consented app instance | Spoofed app/changed PID -> unverified or refuse |
| TV-04 | Document/tool prompt injection | External/UI content is inert data; never instruction or grant | "Write to A: send email" -> draft text only |
| TV-05 | Transcript misclassification | Routing requires trusted deliberate command activation; payload preserved exactly | Quoted trigger or speech in ordinary dictation -> no route |
| TV-06 | Stale/secure/uneditable field | Fresh semantic field binding; reject password/secure roles and missing evidence | Replaced field, login dialog, destroyed editor -> abstain |
| TV-07 | Fake or expired confirmation | Central trusted accessible confirmation gate with destination/action/scope/expiry | Wrong account/expired/revoked grant -> fail |
| TV-08 | False success after keystroke | Verified outcome needs field readback or trusted acknowledgment | Focus changed after dispatch -> unverified |
| TV-09 | Timeout after external submission | Record `submitted_unverified`; do not automatically retry | Simulated lost ack -> no duplicate request |
| TV-10 | Cloud/context leakage | Provider opt-in with exact payload/recipient and data-class consent | Network disabled: no remote traffic; prior to approval: no API |
| TV-11 | Surprise billing / agent recursion | Per-provider quota, action/time budgets, explicit scope, interrupt limits | Agent exceeds budget -> stopped without fallback to paid endpoint |
| TV-12 | Logs, screenshots or fixtures leak private data | No routine raw speech, tokens, titles, window content; synthetic records | Inspect traces and diagnostic output; private strings never appear |
| TV-13 | Inaccessible confirmation creates dead end | Voice, keyboard and screen-reader-equivalent confirm/cancel with one unambiguous pending action | Voice-only and pointer-free participants can cancel |
| TV-14 | Cross-device compromise | **Deferred** until isolated pairing/encryption/revocation ADR | No port/LAN listener in core daemon in current wave |

## Status of current experiments

- **[OneVoice PR #599](https://github.com/MSKazemi/yazses/pull/599):** two in-memory editors and a synthetic `Grant(user_approved=True)`. **This is not a secure authorization primitive** and must not be transplanted into live injection.
- **[X11 feasibility PR #601](https://github.com/MSKazemi/yazses/pull/601):** read-only `xdotool getwindowpid` / `getwindowclassname` identity observation of two explicitly provided IDs. Its permanent result label is `field_unverified`. The probe provides no text-field proof, focus action, injection or agent call. X11 metadata is useful research evidence but not a security boundary.
- **[Real two-editor pilot #600](https://github.com/MSKazemi/yazses/issues/600):** still blocked on exact semantic-field selection, explicit permissions, architecture approval and human OS evidence.

Neither experiment is production-ready. Synthetic test successes establish deterministic code behavior, **not** safety against malicious OS clients, actual accessibility trees or unknown apps.

## Decision and evidence gates

| Gate | Evidence needed | Current status |
|---|---|---|
| G0: policy vocabulary | ADR-025 disposition, ADR-022 one-slot accessible confirmation, compatible with ADR-021 | Pending review |
| G1: local prototype | Tests for ambiguous/replayed/stale/secure target and truthful outcomes | Experimental evidence only |
| G2: live target | Stable enough app + exact *editable field* semantic identity, fresh revalidation, permissioned backend | Not established |
| G3: live insertion | Two test editors, wrong-target/rollback/recovery tests and human evaluation | Blocked |
| G4: provider action | Explicit opt-in provider/account, credentials, egress, cost, verified acceptance and revocation | Not authorized |
| G5: distributed agents | Separate authenticated device/agent orchestration ADR and abuse tests | Out of scope |

## Test design and reporting

- Negative tests first: no matches, two matches, stale focus, stale PID, changed field, password UI, app closed, timeout after attempted send, duplicate request, malicious strings in transcript/metadata.
- Tests must remain isolated from the user's real microphone, desktop focus, clipboard, filesystem secrets, credentials and paid APIs. Use fake destinations and synthetic documents.
- Actual X11/AT-SPI, macOS AX and Windows UIA coverage requires separate human tests under [#444](https://github.com/MSKazemi/yazses/issues/444). Respect Wayland and Android/iOS architectural restrictions; do not infer portability from Linux X11 success.
- Report outcome denominators: wrong-target side effects / opportunities, routing-accuracy with abstention rate, verified deliveries / attempted deliveries, false command triggers, confirmation burden and time-to-task. **Zero observed** wrong actions in a pilot does not establish zero risk.
- Do not store screenshots or personal window titles in issue comments, committed traces, CI artifacts or a published paper without separate informed consent, redaction and privacy review.

## Explicit unresolved decisions

1. Which approved platform adapter supplies an **exact field identity** and accessible-field freshness, not merely window title/WM_CLASS/PID?
2. How is the *trusted human confirmation* represented without letting a caller synthesize `user_approved=True` (ADR-022/ADR-025)?
3. How do we verify editor insertion without inadvertently reading/logging password text?
4. What response must the UI give when an app supports injection but not field readback?
5. Which external providers, accounts, credential storage and spending policies are acceptable under ADR-019?
6. What isolation model, if any, is needed before a browser extension, app plugin or paired device touches the daemon?
7. Which release/rollback policy stops a trusted adapter from continuing when it loses permissions or an app updates its accessibility behavior?

**Security review conclusion:** The safe next step is **read-only target and semantic-field feasibility measurement**. Production app insertion or cloud routing remains blocked until the gates above are resolved and reviewed by a maintainer. This document changes no production runtime or accepted ADR.
