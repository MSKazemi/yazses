# YazSes OneVoice — universal voice destination routing (RFC)

**Status:** Proposed research/design programme; not implemented, not a product promise  
**Date:** 2026-10-17  
**Owner:** YazSes community / maintainer review  
**Scope:** desktop-first, offline-default, human-directed routing to explicitly authorized apps and AI tools  
**Name:** "OneVoice" is a working name, not a trademark or release commitment.

## Product problem

Many applications expose an individual microphone, prompt box, or voice agent. A user must repeatedly select the app, click into its editor, activate voice capture, and submit. Existing YazSes dictation already reaches a focused text field, but cannot reliably answer a more precise question: **which application, session, field, or approved tool did this utterance mean to reach?**

The proposed feature is a *voice control plane*: one YazSes capture surface with an explicit destination router, a permission check, a delivery adapter and independently verified outcomes. It is **not** a new general-purpose autonomous agent and **not** permission to control all applications indiscriminately.

## User-facing promise, with honest boundaries

> Speak through YazSes; name a destination when needed. YazSes drafts or delivers the utterance to a supported application or authorized agent, shows what happened, and refuses to guess when the destination is uncertain.

A supported app means one of:
1. An editable field YazSes can identify and address using permitted operating-system APIs.
2. An app-specific integration with an explicit capability contract.
3. A connected tool/agent endpoint for which the user has approved credentials, scope and data egress.

An unsupported, inaccessible or ambiguous destination **must not receive text by guess**. The fallback is a local draft, copy-to-clipboard with an explanation, or clarification.

## Three distinct product modes

| Mode | Example spoken command after deliberate activation | Outcome |
|---|---|---|
| Focused dictation (existing default) | "The bug happens after login" | Insert into the current editable text field; no agent routing |
| Named destination / compose-only | "Write to ChatGPT: explain this traceback" | Find a user-approved ChatGPT input target and insert text as a **draft**, without pressing Send |
| Explicit action / approved agent | "Ask ChatGPT: explain this traceback" | Preview destination and exact payload; request affirmative approval for outbound submission; dispatch via an approved adapter and report verified/unknown outcome |

Further modes are proposed only after evidence:
- pinned target ("dictate to the ChatGPT tab until I say stop"), clearly visible and expiring on a timer;
- one utterance to more than one destination, with per-destination consent, previews and independent outcomes;
- scoped multi-agent task tracking ("ask coding agent to work on issue X; show me status"), **not** delegation of unrestricted autonomy;
- phone-to-desktop routing with device pairing and explicit network/egress design.

**Important:** "Write to" and "ask/send to" are different intentions. Inserting text is not sending it. API execution is not the same as typing into a particular ChatGPT web conversation. No adapter may silently pretend those are interchangeable.

## Experience example

User presses the existing YazSes hold-to-talk hotkey and says:

> "YazSes, write to ChatGPT: how can I debug this Python traceback?"

YazSes:
1. transcribes offline;
2. recognizes a *routing command* rather than ordinary dictation;
3. resolves an allowlisted ChatGPT tab and its editable composer, or abstains;
4. presents "ChatGPT (browser tab) · Draft only" and the exact text;
5. inserts only after verifying that target is still current;
6. reports "Draft inserted" **only when insertion is observed**, otherwise "Insertion unverified; kept local copy".

A later separate "Send this to ChatGPT" action is an external side effect: confirm exact recipient and payload and obtain a distinct success/unknown outcome. Nothing goes to ChatGPT's API unless an API adapter was separately configured; an API request would create its own service interaction, not modify a ChatGPT app chat.

## Architecture alignment — read before implementing

The repo already has the building blocks:
- [text target detection](../../src/yazses/inject/target.py) and [app profiles](../../docs/how-to/app-profiles.md);
- [Voice-to-Tool planner](../../src/yazses/agent/plan.py) and [Spoken MCP ADR](../adr/adr-v2-006-spoken-mcp.md);
- [semantic grounding proposal ADR-v2-151](../adr/adr-v2-151-grounded-target-resolution.md);
- [Grounded Interaction Kernel proposal ADR-025](../adr/adr-025-grounded-interaction-kernel.md);
- [agent-protocols ADR-020](../adr/adr-020-agent-protocols.md);
- [egress inventory ADR-019](../adr/adr-019-egress-inventory-and-escalation.md);
- [offline-by-default ADR-011](../adr/adr-011.md);
- [mobile architecture](../../docs/mobile/architecture.md) and [Android delivery ADR-MOB-003](../../docs/mobile/adr/adr-mob-003-text-delivery-surfaces.md);
- [iOS deferred second-wave ADR-MOB-010](../../docs/mobile/adr/adr-mob-010-apple-second-wave.md).

**Do not invent a parallel general-purpose interaction kernel.** This RFC treats the proposed ADR-025 types as the preferred vocabulary if adopted. Until ADR-025 is accepted, use a narrow, pure `RouteProposal` experiment rather than making unreviewed changes to existing routing/daemon APIs.

**Do not install arbitrary third-party Python plugins.** ADR-018 defers untrusted plugins. Adapters in the first wave are built-in, explicitly reviewed, allowlisted and dependency-isolated.

**Do not silently supersede ADR-020.** It rejects A2A and autonomous goals. Dispatching one human-authorized request to a supported agent is compatible; persistent task orchestration or agent-to-agent delegation requires a new architecture decision explicitly superseding the applicable parts of ADR-020.

## Platform reality

| Platform | Feasible first route | Main limitation |
|---|---|---|
| Linux X11 | Current focused field, native app focus, AT-SPI where available | App UI metadata varies; exact field identity not universal |
| Linux Wayland | Existing consented input backend/portal plus app-supported semantics | Compositor security forbids unconsented global focus/control |
| Windows | Focused field, UI Automation and app-specific bridge | TextPattern is read-oriented; injection may need ValuePattern/keyboard, subject to UIPI |
| macOS | Focused field and permissioned Accessibility APIs | OS/app permission and secure inputs; not a universal direct app API |
| Android | Already planned `InputMethodService` / `InputConnection.commitText()` | The IME writes to its bound editor; targeting an arbitrary offscreen app needs a separately reviewed architecture |
| iOS/iPadOS | Main-app capture + keyboard handoff, Share/Shortcuts/App Intents | Custom keyboard extensions cannot directly use the microphone; apps/secure fields can reject custom keyboards |

User-visible copy must state "supported apps and destinations", not "all apps".

## Release positioning

1. **Phase A:** Reliable desktop routing and compose-only text delivery to known fields, without new network access.
2. **Phase B:** Explicitly consented, opt-in agent/tool adapters; separate compose, send and verify outcomes.
3. **Phase C:** Existing Android IME semantics, more OS/app coverage, and opt-in device-to-device handoff after security review.
4. **Phase D (separate ADR):** User-controlled multi-agent workspaces and multi-agent task tracking, if evidence warrants the complexity.

This order prioritizes **wrong-target prevention** and system compatibility over demonstrations of seemingly magical autonomy.

## Review decisions before a shipping issue

- Is the product goal *destination routing* (compatible with ADR-020) or autonomous multi-agent delegation (requires superseding ADR-020)?
- Will ADR-025 be accepted first, or is this constrained to a single narrow router pilot?
- Which desktop OS and app pair has repeatable human test capacity for the first pilot? Suggested low-dependency pilot: Linux X11 + AT-SPI + ordinary editor; platform choice needs maintainer approval.
- What source of app identity is acceptable for a browser tab (user-selected tab/browser extension vs speculative accessibility title matching)?
- Should named-destination commands default to compose-only? **Recommended: yes.**
- What optional cloud/API service and billing/disclosure policy can pass the existing ADR-019 egress review?

No production implementation, public release claim, or `agent-ready` implementation task follows merely from this RFC.

## Documents

- [Router contract and safety specification](ROUTER_SPEC.md)
- [Evaluation protocol and contributor-sized work packages](VALIDATION_AND_TASKS.md)

## Primary external capability references

- Android: [InputConnection API](https://developer.android.com/reference/android/view/inputmethod/InputConnection).
- Apple: [Custom keyboard boundaries](https://developer.apple.com/documentation/UIKit/configuring-a-custom-keyboard-interface), [open-access privacy](https://developer.apple.com/documentation/uikit/configuring-open-access-for-a-custom-keyboard), [App Intents](https://developer.apple.com/documentation/AppIntents).
- Windows: [UI Automation Text Object Model](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-understandingtheuiautomationtextobjectmodel).
- macOS: [AXUIElement](https://developer.apple.com/documentation/applicationservices/axuielement_h).
- Wayland: [XDG RemoteDesktop portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html).
