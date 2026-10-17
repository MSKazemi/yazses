# OneVoice / YUI — Comprehensive Design Considerations and Decision Gates

**Status:** Proposed; design review only, not an implementation or accepted platform guarantee.  
**Date:** 2026-10-17  
**Companion:** [OneVoice overview](README.md) · [Universal Interface](UNIVERSAL_INTERFACE.md) · [Router contract](ROUTER_SPEC.md) · [Evaluation and task plan](VALIDATION_AND_TASKS.md)

## Executive recommendation

YUI should offer **one consistent, human-controlled interaction model** across supported applications, not the impossible guarantee that every app accepts arbitrary commands. Focus investment on **right destination + limited authority + proven outcome** before broad app coverage. All new features remain optional, offline by default and backward-compatible with existing focused-field dictation.

Three distinct operations have different security properties:
- **Dictate** to the currently focused editor: existing default input behavior.
- **Draft** for a named and explicitly resolved destination: local text entry, no external send.
- **Act / submit** to a provider or tool: explicit recipient, preview, authorization and postcondition; no implicit network or paid API use.

The proposed internal adapter API must fit *inside* the Grounded Interaction Kernel if [ADR-025](../adr/adr-025-grounded-interaction-kernel.md) is accepted. It is **not** a new universal wire protocol and does not justify autonomous agent-to-agent negotiation or an HTTP service.

## 16 dimensions of the design

### A. Product & human interaction

**A1 — Scope and jobs to be done [Decision: before any implementation]**

Define supported tasks with exact verbs: dictate, draft, send, query, read status, cancel, switch target. Keep a strict distinction between interacting with the user's *existing* application session and initiating a *new* provider API request. Identify target user workflows: hands-busy desk users, people with accessibility needs, and coding-agent users. Explicitly exclude autonomous indefinite planning, unrestricted device control, and the assertion "controls every app". 
- Required evidence: at least five synthetic user journeys and negative cases with stated expected outcome.
- Open decision: which 1–2 workflows establish the initial value proposition? Recommend named-destination draft insertion and safe fallback.

**A2 — Activation, speech boundaries and multilingual routing [Decision: first pure prototype]**

Retain explicit hold-to-talk as the default, not an ambient mic or wake-word promise. Command recognition must distinguish utterance-level routing requests from content (e.g. "write to ChatGPT: send the email" is text to insert, *not* a new command). Preserve the dictated payload exactly; avoid using lowercased/punctuation-stripped classification strings for delivery. Support synonyms, disfluency, code switching, localized destination names and BCP-47 locale tags, but test those individually instead of implying language parity.
- Required evidence: false-command trigger rate on ordinary dictation and routing-intent precision/recall, broken out by language/locale.

**A3 — Inclusive user experience and confirmation [Decision: before real pilot]**

The overlay should show a destination/account, target field, proposed action, payload preview, status and recovery. It must work with a keyboard and screen reader and provide a **voice-only confirmation and voice-only cancellation path** where the mode is meant to be hands-free. No approval UI should force someone using gaze/switch input to click a pointer-only button. Limit unsolicited agent interruptions and never interrupt an ongoing hold.
- Required evidence: screen-reader and voice-only task completion, number of dead-end states, wrong approvals, confirmation fatigue and time-to-recover.
- Repository conflict to resolve: [ADR-022](../adr/adr-022-a-confirmation-a-voice-user-cannot-give.md) is still **Proposed** and addresses a real confirmation gap. Do not create competing confirmation slots in YUI.

### B. Targeting, integration and platform capability

**B4 — Grounded destination identity [Critical gate]**

Identify a concrete target, not an app-name string: machine/user session, OS process/window, browser profile/tab, app account or conversation, exact editor/field, snapshot age and permission context. Never infer which of two similarly named tabs is intended. Revalidate identity before delivering; focus changing between speech and injection must not retarget silently. Sensitive/password field detection may require abstention when certainty is unavailable.
- Required evidence: zero wrong-target actions in the controlled safety pilot; ambiguity, stale-window, changed-focus, duplicate-tab and multi-monitor fixture tests.
- Dependency: [ADR-v2-151](../adr/adr-v2-151-grounded-target-resolution.md) remains proposed and should not be overridden by a parallel target resolver.

**B5 — OS and mobile differences [Critical feasibility gate]**

Audit actual current support separately for Linux X11, GNOME/KDE Wayland, macOS, Windows, Android IME, and iOS/iPadOS. An API for inserting into the **active field** is not an API to focus or write into any background app. Desktop security controls, permission prompts, elevated windows, remote sessions, secure fields, accessibility-tree gaps, compositor restrictions and application-specific overrides must be explicit in the support matrix.
- Linux X11: existing focused-field injection, window manipulation and optional AT-SPI; test exact target carefully.
- Linux Wayland: current YazSes capability matrix reports no general voice focus / Glance-Type routing; RemoteDesktop portal grants keyboard/pointer sessions, not universal other-window semantic focus.
- Windows: UI Automation coverage is good for many apps, but UIPI/integrity and locked/elevated sessions can prevent automation.
- macOS: Accessibility and Microphone grants; secure-input and application-specific restrictions.
- Android: InputMethodService uses current InputConnection; not an offscreen universal app-control channel.
- iOS/iPadOS: custom keyboard extensions have no microphone access, and apps can reject third-party keyboards; design main-app capture and handoff.
- Required evidence: per-platform *tested* capability matrix with reproducible app/OS/version/method/provenance.

**B6 — Adapter architecture and interoperability [Before connecting third parties]**

Use a reviewed internal DestinationAdapter with **capabilities → resolve → preview → execute → verify → cancel**. Adapter manifests declare supported operations, target granularity, assurance levels, required grants, data destination, network/price behavior and version. Prefer an app-owned API when it satisfies user intent; an API call to an LLM is **not** equivalent to inserting into that app's current conversation. Use OS accessibility and selected editor bridges where permission allows; avoid blind coordinate clicking. Use local stdio MCP *client* where approved; do not silently expand the existing two-tool MCP server to general remote control, add HTTP to the daemon, or ship arbitrary Python plugins under [ADR-018](../adr/adr-018-feature-packs-and-the-plugin-question.md) and [ADR-020](../adr/adr-020-agent-protocols.md).
- Required evidence: fake adapters, contract tests, capability mismatch refusal and provider version/permission failure behavior.

### C. Authority, privacy and security

**C7 — Per-action authority and consequence [Critical gate]**

Separate observation from authorization. Classify read-only, reversible draft/edit, externally visible submission, destructive action and physical-device action. Keep physical effects out of the initial scope. Grants must name destination/account, exact operation, payload scope, expiration and revocation. Higher-confidence model output never elevates permission. Require an accessible, deliberate confirmation for consequential and external actions; separate approval to draft from approval to send.
- Required evidence: denied/expired/revoked-scope tests; no externally visible side effect without a current valid grant.
- Dependency: accepted [ADR-021](../adr/adr-021-invest-in-error-cost.md) says error *consequence*, not only recognition confidence, drives guards.

**C8 — Privacy, egress and data minimization [Critical gate]**

Trace microphone audio, transcript, user selection, app labels, contextual document snippets, prompts, outbound request, provider response, diagnostic records and optional research data. Default to local ephemeral processing; do not store raw text or screenshots in diagnostics or send them to coding agents. Any external AI submission is a **new, explicitly disclosed egress event**, even when the user spoke locally. Show what content and which endpoint/account would receive it; permit refusal and redaction. Define retention, deletion, jurisdiction and participant consent for studies.
- Required evidence: per-operation data-flow diagram and negative egress tests with network disabled; separate review for every new network path under accepted [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md).

**C9 — Live threat model, injection and spoofing [Critical gate]**

Treat app window titles, accessibility labels, web pages, selected text, model output and MCP/tool replies as **untrusted data**. Attackers could impersonate "ChatGPT" in a window title; change focus mid-speech; insert "ignore your rules" into content; replay an old authorization; or spoof a voice command from a speaker. Protect boundaries with allowlisted identity, fresh snapshot binding, explicit user activation, isolation and independent permission checks. Review microphone/clipboard leakage, local-process tampering, adapter supply chain and browser-extension privileges. Never treat speaker biometrics alone as sufficient authorization for a risky action.
- Important finding: [design/threat-model.md](../threat-model.md) is **archived and describes the unshipped Rust architecture**. A shipping Python/YUI threat-model update is a prerequisite, not an optional polish step.
- Required evidence: adversarial prompt-injection, replay, focus-hijack, impersonation and malicious-adapter test scenarios.

**C10 — Identity, credentials, account mixing and usage costs [Critical gate for agents]**

Distinguish two Google/ChatGPT/browser profiles, two coding projects, local vs remote agent instances and a shared workstation user. Use provider-supported authorization and platform credential stores; never expose credentials to model prompts or issue fixtures. External AI endpoints may consume paid tokens; a "connected" state is not a cost authorization. Disclose provider, data class, possible charge, and if known estimate or configured budget; support per-provider enable/disable and revocation. Do not purchase credits, upgrade, auto-reload or turn on paid overages without separate user authorization.
- Required evidence: mixed-account test; no accidental cross-profile submissions; revoked-token behavior; budget and billing disclosures.

### D. Execution and coordination

**D11 — Lifecycle, verification, recovery and idempotency [Critical gate]**

State is not a Boolean success flag. Distinguish **transcribed / targeted / authorized / attempted / inserted-unverified / inserted-verified / submitted-unverified / submitted-verified / agent-accepted / task-completed / failed / cancelled**. Confirm via editor readback or trusted application/API acknowledgement where possible. A keyboard event returning success does not prove correct content arrived. On a timeout after a send, status is **unknown**; never automatically retry unless endpoint idempotency and target identity make it safe. Cancellation is best effort and cannot undo an already sent request or external charge.
- Required evidence: kill/freeze app, altered field, timeout-after-submit, duplicate-request and crashed-agent scenarios; truthful user feedback.

**D12 — Multiple agents, cross-device control and interrupts [Separate later decision]**

A request addressed to two agents must have two explicit destinations, two authorizations when appropriate, separate error states and independent completion tracking. Cap total chain depth, actions, token spending and interruptions. Have a predictable stop mechanism. Phone-to-desktop handoff requires authentic pairing, device selection, encryption, replay protection, lost-device revocation, and a **new network/egress security review**. The existing local daemon must not become an unauthenticated LAN control endpoint.
- Required evidence: partial fan-out failure, one device offline, same command heard on two devices, revoked pairing and safe task cancellation.
- Architectural gate: persistent autonomous agent negotiation would change accepted ADR-020 and requires a new superseding decision; **not** a side effect of introducing an adapter API.

### E. Performance, testing and evidence

**E13 — Latency, resources and offline-first operation [Before pilot rollout]**

Budget capture-to-transcript, intent parse, target grounding, permission UX, delivery and verification separately. Measure p50/p95 on warm and cold starts, low-power machines, CPU-only setups and mobile battery. Keep default dictation fast even when no adapter is enabled; make SLM/agent models optional and dependency isolated under the project's dependency budget. Never silently substitute a cloud model when the local decoder fails.
- Required evidence: CPU/RAM/model download costs, startup delta, latency by stage, energy where measurable, offline negative tests.

**E14 — Reproducible evaluation, observability and human studies [Before claims/publication]**

Use deterministic synthetic fixtures and app simulators first, platform-specific UI integration tests second, independent human participants on diverse machines third. Evaluate destination precision, false activation, abstention, wrong-target side effects, privacy leaks, verified delivery, task completion, editing effort, accessibility dead ends, and cost-weighted mistakes. Collect minimal operational counters with no raw transcripts, app titles or credentials by default. Distinguish repeated runs from independent people and publish denominators, limitations and negative results.
- Required evidence: fixed test matrix, preregistered protocols if publication is intended, consent/retention review, repeated OS tests, and a comparison against normal application switching.

### F. Maintainability and governance

**F15 — Schema stability and contributor architecture [Before broad integrations]**

Version internal value schemas and capability declarations; keep the core pure/testable while OS APIs remain in adapters. Share behavioral vectors between desktop/Android/iOS, not necessarily executable code. Reject unknown required capabilities rather than guessing. Require semantic versioning rules, compatibility tests and an adapter lifecycle (proposed, experimental, tested, disabled, deprecated). Respect accepted [ADR-018](../adr/adr-018-feature-packs-and-the-plugin-question.md): **do not load arbitrary third-party code inside the voice daemon**. A reviewed in-tree adapter is not the same as a marketplace plugin.
- Required evidence: fake adapter conformance suite, API-compatibility fixtures, dependency and packaging budget tests, contributor templates.

**F16 — Product/research governance, distribution and law [Before release]**

Define maintainers for core policy and each trusted adapter; ADR approvals precede runtime wiring. Document store policies and privacy labels for Android/iOS, accessibility permission explanations, provider branding/terms, software licenses, data rights and applicable privacy law obligations. Avoid untested "universal" marketing claims. Supply separate rollback/kill switch and clear user documentation for configuration, billing, revocation and unsupported capabilities. Keep community tasks narrow and traceable to ADRs; do not label them agent-ready before prerequisite decisions and tests.
- Required evidence: approved ADR/dependency map, release checklist, audit of permissions and third-party terms, reproducible build, disabled-by-default rollback.

## Cross-cutting risk register

| Risk | Why it matters | First mitigation | Evidence required |
|---|---|---|---|
| Wrong destination/field | Confidential or destructive text reaches the wrong place | Exact target binding + freshness gate + abstain | Focus-switch and duplicate-tab tests |
| Unintended send | Draft becomes published prompt/message | Distinct draft versus submit intent + confirmation | Nested-command and submit tests |
| False success | User assumes action happened | Separate unverified/verified outcomes | Crash, lost acknowledgment and readback |
| Prompt injection | Tool or webpage content grants itself authority | Untrusted-content boundary + allowlist | Adversarial fixtures |
| Cloud transcript leakage | Private data transferred without understanding | Explicit egress preview, no implicit API use | Network-blocked and opt-in tests |
| Token charges | AI tasks create paid usage or runaway loops | Opt-in provider budgets/limits and no silent retries | Quota and duplicate scenarios |
| Unavailable OS capability | User promise fails silently | Per-OS capability registry with honest fallbacks | Real OS/app test matrix |
| Voice-only confirmation trap | Accessibility feature impossible to use safely | Accessible readback, confirm/cancel/escape | Voice-only task study |
| Arbitrary plugin code | Access to live mic/typing granted to a malicious plugin | No untrusted dynamic plugins in daemon | Dependency boundary tests |
| Unsafe cross-device bridge | Another machine gains control of mic/keyboard | Defer until separate authenticated/isolated relay ADR | Pairing and revocation tests |

## Metrics — define before publishing results

- **Wrong-target action rate** = wrong-target side effects / attempted target actions, with explicit test coverage and 95% confidence interval where appropriate.
- **Command false-positive rate** = ordinary dictation utterances wrongly interpreted as route commands / ordinary dictation utterances tested.
- **Selective routing accuracy** = correct destinations / all evaluated intended routes, reported together with the abstention rate; never report only success cases that were executed.
- **Verified delivery rate** = deliveries with trusted matching readback or application acknowledgments / delivery attempts; unverified stays separate.
- **External duplicate action rate** = unintended duplicate external side effects / external action opportunities.
- **Voice-only completion** = participants completing a scenario without inaccessible pointer-only confirmation / attempts, broken out by participant and task type.
- **Interaction gain** = change in median app-switches, touches/keystrokes and end-to-end task time versus the baseline.
- **Privacy/egress violations** = any request that transfers content without the intended recipient/payload being authorized; use negative tests.

A goal of **zero observed wrong consequential actions in a controlled pilot** is a safety gate, not proof of zero risk. Do not claim field reliability from synthetic fixture passes alone. Set numerical thresholds and sample sizes after baseline measurement and before a human trial.

## Decision queue (explicit maintainer approvals)

| Decision ID | Question | Recommended starting answer | Blocking |
|---|---|---|---|
| YUI-D01 | What does "universal" mean? | Universal *interaction semantics* for **supported and permitted** destinations | Product messaging / implementation |
| YUI-D02 | Do we reuse ADR-025's Grounded Interaction Kernel? | Yes after acceptance/reconciliation; otherwise only a disposable narrow experiment | Core wiring |
| YUI-D03 | Where does accessible confirmation live? | One shared held state, resolving ADR-022; don't invent a second confirmation path | Hands-free actions |
| YUI-D04 | Which first OS and apps? | Linux X11 + one simple editor first; browser composer research second; require maintainer/participant evidence | Real pilot |
| YUI-D05 | Are remote AI APIs part of MVP? | No; start offline with a fake tool and permitted desktop text insertion | Egress, credentials, cost |
| YUI-D06 | Can an app/API adapter submit automatically? | No; external submission requires explicit confirmation for first release | Provider adapters |
| YUI-D07 | Should external plugin discovery be allowed? | No, only reviewed in-tree adapters per ADR-018 | Extension implementation |
| YUI-D08 | Should YUI coordinate persistent autonomous agents? | Not under ADR-020; separate new ADR and safety evaluation if later justified | Long-running tasks |
| YUI-D09 | Do mobile and remote-control integrations launch with MVP? | No, capability contract design only; native IME and Apple handoff under their own ADRs | Cross-device / mobile |
| YUI-D10 | Do we need a current security assessment? | Yes; archived Rust threat model is not evidence of Python safety | Any live universal routing |

## Stage gates and recommended sequence

| Gate | Minimum deliverable | What is explicitly **not** authorized |
|---|---|---|
| G0 — governance | Scope D01–D10 reviewed; ADR-025 and ADR-022 dependencies resolved or limited to experiments; live Python threat-model delta | No code wired into daemon |
| G1 — pure contract | Deterministic command parser, destination registry, fake adapter, policy, status machine; synthetic tests; no network | No cloud/API calls, no app injection |
| G2 — local desktop pilot | One OS/editor, visible draft-only routing, stale-target guards and verification | No uncontrolled app focus or Send |
| G3 — browser/app integration | Explicitly selected browser tab or trusted native API, account-specific capability and consent | No scraping private tabs, no silent external send |
| G4 — approved agent tools | Local stdio MCP client, scoped actions, status and interruption/cost controls | No unrestricted autonomy, no generic HTTP daemon |
| G5 — mobile & paired devices | Shared behavior vectors, Android IME-aware contract, iOS handoff study, separate pairing ADR | No fictitious iOS keyboard mic or arbitrary background mobile control |

Research and review work can proceed before ADR acceptance. Implementation-ready contributor issues must identify allowed paths, dependencies, tests, platform/permission constraints and honest failure behavior. Do not apply auto-execution labels or enable paid services while preparing the plan.

## Documents / current as-built references

- [Project capability matrix](../../docs/capability-matrix.md) — what currently works on each desktop system.
- [Android text delivery ADR-MOB-003](../../docs/mobile/adr/adr-mob-003-text-delivery-surfaces.md) and [Apple ADR-MOB-010](../../docs/mobile/adr/adr-mob-010-apple-second-wave.md).
- [Agent protocol ADR-020](../adr/adr-020-agent-protocols.md): local stdio boundary and prohibition on arbitrary HTTP/A2A.
- [Egress ADR-019](../adr/adr-019-egress-inventory-and-escalation.md): enumerate and authorize all outbound paths.
- [Error-cost ADR-021](../adr/adr-021-invest-in-error-cost.md): downstream consequence matters, not only intent confidence.
- [Confirmation ADR-022](../adr/adr-022-a-confirmation-a-voice-user-cannot-give.md): still Proposed.
- [Kernel ADR-025](../adr/adr-025-grounded-interaction-kernel.md): still Proposed.
- [Existing threat model](../threat-model.md): archived Rust design, **not** a live Python security assurance.
- [Android InputConnection](https://developer.android.com/reference/android/view/inputmethod/InputConnection), [Apple custom keyboard restrictions](https://developer.apple.com/library/archive/documentation/General/Conceptual/ExtensibilityPG/CustomKeyboard.html), [XDG RemoteDesktop portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html), [Microsoft UI Automation security limitations](https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-automate/desktop-flows/ui-automation/uipi-issues).
- [Current MCP specification update](https://blog.modelcontextprotocol.io/posts/2026-07-28/) is an interoperability reference, **not** an authorization to widen the current YazSes server.

## What this document changes

It records a **review checklist, risks, evidence and decisions** in the draft PR. It does **not** modify source code, release claims, current ADR statuses, default configuration, permissions, connector credentials, CI, milestones or external APIs.
