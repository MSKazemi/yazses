# YUI — YazSes Universal Interaction Interface

**Status:** Proposal / internal design contract only, not implemented or accepted  
**Date:** 2026-10-17  
**Parent RFC:** [OneVoice](README.md), [Router Spec](ROUTER_SPEC.md), [Evaluation and Tasks](VALIDATION_AND_TASKS.md)  
**Scope:** One shared human-facing interaction surface and one **internal** destination-adapter vocabulary.

> Universal **interaction semantics**, not universal authority over every app. A destination works only when a permitted, verified adapter can act on it.

## Why this is useful

Today a user separately selects an app, focuses a prompt, presses that app's microphone button, dictates and presses Send. A YazSes user should instead be able to hold the **existing** activation key and say:
- "Write to ChatGPT: explain this traceback." -> insert a draft into a previously approved, resolvable ChatGPT composer; do not submit.
- "Ask ChatGPT: explain this traceback." -> prepare a send proposal; obtain approval for the exact destination and payload before external submission.
- "Put this in my VS Code editor." -> insert a draft into an explicitly selected editable editor; never automatically execute terminal input.
- "Tell my local coding tool to summarize the project." -> use an authorized local tool capability, if configured; read-only task only.
- "Send to ChatGPT and Claude." -> phase-later two independent, explicitly reviewed submissions with separate outcomes; never assume one provider is another.

This is also a common accessibility surface: voice, keyboard, switch, gaze and pointer can propose the *same* action but do not implicitly authorize it.

## Two distinct interfaces

### 1. Human interface (unified overlay / command palette)

The user sees one consistent interaction contract across supported platforms:

1. **Activation:** existing hold-to-talk (not an always-open mic).
2. **Destination:** explicit user-approved app or pinned window/tab; visible name and instance label.
3. **Mode:** *Dictate*, *Draft*, *Ask/Send*, or *Read Status*; mode is never inferred only from a model's confidence.
4. **Payload:** editable transcript preview where feasible, without hidden prompt augmentation.
5. **Permission preview:** operation, recipient/account, local vs cloud, possibly paid API use, risk.
6. **Execution:** keyboard-accessible, screen-reader-readable Confirm / Cancel.
7. **Outcome:** *draft inserted*, *insertion unverified*, *request accepted*, *response available*, *failed*, or *unknown*. No false success badges.

The overlay must not block ordinary focused-field dictation, and no proprietary assistant is privileged. A destination picker should show **capabilities**, not a misleading always-green "connected" state: "Draft only", "Can submit with confirmation", "Read-only", "Not available", "Needs permission".

### 2. Developer-facing internal adapter interface

YUI is **not** a new internet-wide protocol and **not** a replacement for MCP. It is a small interface between the proposed grounded-interaction/policy layer and trusted, reviewed destination implementations.

Conceptual component layout:

~~~text
Input: voice, keyboard, gaze, switch (existing sources)
   |
Speech/command classification (existing YazSes pipeline)
   |
Grounded Interaction Kernel (ADR-025, currently Proposed)
   |  Observation / GroundedTarget / IntentHypothesis
   |  AuthorityContext / ActionProposal / ActionOutcome
   |
YUI Destination Registry + Routing Policy (pure)
   |  discover -> resolve -> preview -> authorize
   |
YUI reviewed adapter boundary
   +-- local focused-field delivery (existing inject/)
   +-- OS accessibility and editor-native bridges (platform gated)
   +-- explicitly selected browser composer (future, app scoped)
   +-- local MCP tool client / existing agent planner (opt-in)
   +-- remote app/provider API (future, separate egress approval)
   +-- mobile IME / Shortcuts / approved device relay (later)
   |
execute -> verify -> outcome -> local user feedback
~~~

**Compatibility decision:** ADR-025 says not to publish a universal external "intent protocol" before the grounding semantics have been validated. This document proposes **only an internal adapter API**. If ADR-025 is accepted, YUI is a thin adapter boundary *inside* its kernel, not a second kernel. If ADR-025 is declined, a scoped experimental route-to-adapter pilot must not silently establish a general public protocol.

## Capability discovery

Every in-tree adapter declares what it **actually** supports. Capability catalogs are plain, reviewed data, not executable third-party plugins.

| Field | Meaning |
|---|---|
| destination_id | User-approved, stable registry identifier |
| display_name | Human-visible app, account or target name |
| surface | focused_field / named_app_editor / browser_composer / local_tool / remote_provider |
| operations | Set from insert_draft / submit / read_status / cancel |
| target_granularity | Focused field, exact semantic field, tab, app instance or tool endpoint |
| assurance | Can verify target? Can verify insertion? Can verify remote acceptance? |
| required_grants | OS accessibility, selected tab, credential or tool permission |
| egress | local_only / external_with_review |
| charges_possible | Explicit per-adapter unknown/yes/no disclosure; no assumed free provider |
| limitations | Secure fields, OS restrictions, no submit capability, etc. |

Reject requests for operations not in the catalog, even when an LLM or app-provided text proposes them. Cache capability data only within a validity interval appropriate to the adapter; re-check it before changing anything.

## Minimal internal contract (illustrative Python Protocol)

The implementation will choose concrete value types after the ADR review. All methods other than execute/cancel are side-effect free by contract:

~~~python
from typing import Protocol

class DestinationAdapter(Protocol):
    def capabilities(self) -> CapabilitySet: ...
    def resolve(self, target: DestinationRequest, context: ContextSnapshot) -> Resolution: ...
    def preview(self, proposal: ActionProposal, target: ResolvedTarget) -> ActionPreview: ...
    def execute(self, approved: AuthorizedAction) -> ActionOutcome: ...
    def verify(self, outcome: ActionOutcome) -> Verification: ...
    def cancel(self, execution_id: str) -> CancellationOutcome: ...
~~~

- **resolve:** may return exactly one grounded target, ambiguous targets, or unresolved. Never silently pick one of multiple similarly titled browser tabs.
- **preview:** cannot transfer data to a provider, type keys, open tabs, or change focus.
- **execute:** accepts an unforgeable permission-checked action produced by the central policy layer; adapters never receive a raw instruction to "do anything".
- **verify:** observes trustworthy postconditions when possible; lack of readback is **unverified**, not success.
- **cancel:** best effort on queued/running work. Does not imply that a sent message, committed code or provider charge can be undone.
- No adapter may grant permissions to itself or broaden the scope by following instructions in a document, webpage, prompt, transcript or tool response.

Use the existing ADR-025 type names, once accepted, rather than parallel event, permission, action or result hierarchies. Do not put OS-native accessibility objects or secrets in the pure contract.

## Versioned message example (NOT a promised public wire protocol)

~~~json
{
  "schema_version": 0,
  "request_id": "synthetic-001",
  "intent": "insert_draft",
  "destination_id": "approved-chatgpt-browser-tab",
  "payload": "Explain the exception in this traceback.",
  "target_binding": {
    "session": "synthetic-session",
    "instance": "synthetic-tab-handle",
    "field": "composer",
    "snapshot": "synthetic-ephemeral-snapshot"
  },
  "authority": {
    "origin": "explicit-user-command",
    "allowed_operation": "insert_draft",
    "external_send_approved": false
  }
}
~~~

This is a readable fixture, not persisted conversation data. Production code must not log plaintext user utterances as routine diagnostics. Identifiers must be short-lived for transient windows and fields.

## Router invariants

1. **Default behavior preserved:** no explicit routing activation -> current ordinary YazSes dictation.
2. **No nested instruction execution:** "write to ChatGPT: send an email" inserts the words as a draft, not an email.
3. **Payload fidelity:** route commands are parsed from the original text; never let normalization lower-case or strip punctuation from the content to deliver.
4. **Destination is grounded:** explicit app/window/tab/field identity plus context freshness; a matching name alone is not proof.
5. **No time-of-check/time-of-use gap:** revalidate target identity immediately before execution. A changed focus or tab -> clarify/abstain.
6. **Authority is separate from confidence:** a certain interpretation does not permit a remote send, shell command or purchase.
7. **Network stays opt-in:** local dictation must work with network disabled, existing AF_UNIX daemon IPC stays unchanged. Browser extensions, remote APIs and cross-device bridges need independent security/egress ADR review.
8. **Uncertain submission is not retried automatically:** prevent double posts, duplicate agent jobs, repeated purchases and extra token charges.
9. **No broad third-party plugin loading:** only reviewed in-tree adapters until ADR-018 is revisited explicitly.
10. **Unsupported apps fail honestly:** local draft, clipboard with visible explanation, user-selectable alternatives, never silently pretend that injection succeeded.

## Relationship to existing protocols

- **MCP:** use the existing YazSes Voice-to-Tool *client direction* as an adapter to approved **local stdio** tools, subject to ADR-v2-006 and ADR-020. Do not add new outbound/network MCP paths implicitly. The current repo's stdio server exposing two tools does **not** become a general universal agent server.
- **2026-07-28 MCP spec:** current upstream added new protocol capabilities, including a revised stateless core and task extension; that is **not authorization to retrofit YazSes's stdio MCP server**, which currently advertises an earlier version. Capture interoperability/version-negotiation tests as separate scoped work, preserving the current trusted boundary. [Official MCP release](https://blog.modelcontextprotocol.io/posts/2026-07-28/).
- **OS accessibility:** platform-specific APIs provide *capabilities* rather than unlimited app control. OS security policy, consent and secure-field restrictions win.
- **Android:** the native IME can write to its currently bound editor via InputConnection. It cannot generally target arbitrary other apps' hidden fields. [Android official guidance](https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method).
- **iOS/iPadOS:** keyboard extensions cannot directly use the mic; main-app recording and approved handoff/Shortcuts are the route. The platform may reject custom keyboards. [Apple custom keyboard rules](https://developer.apple.com/library/archive/documentation/General/Conceptual/ExtensibilityPG/CustomKeyboard.html).
- **Application APIs:** only when the app offers an authorized integration. Using an LLM provider API is a *new conversation/operation*, not magically entering the user's existing app conversation.

## Example operations and results

| User command | Supported operation | Confirmation default | Verified outcome |
|---|---|---|---|
| "Write to ChatGPT: ..." | insert_draft to selected composer | no extra remote-send permission; binding must remain fresh | composer text observed or unverified |
| "Ask ChatGPT: ..." | submit to explicitly selected provider/app | explicit approval; possible cloud data transfer | provider/app ack, not mere keystroke |
| "Insert this in VS Code" | insert_draft to selected editor | route choice must be explicit and target checked | editor text observed |
| "Tell Codex to review issue 413" | submit authorized task | explicit workspace, scope, provider and possible costs | accepted task ID, **not** completed |
| "What happened to that task?" | read_status | within existing approved task scope | fresh provider state or unknown |
| "Stop that task" | cancel | when supported | cancellation requested / confirmed / unsupported; cannot reverse completed actions |

## Human-interface accessibility and discoverability

- Minimal overlay with current destination, mode, transcript preview, permission + cost indicator, and high-contrast action controls.
- Keyboard and screen-reader parity; announcements are concise and never overlap active hold-to-talk recording.
- Color is never the only signal. Failure and **unverified** outcomes have readable labels.
- Clear way to switch back to normal dictation, unpin a target and revoke a grant.
- Optional quick destination aliases may be user-created, scoped to known registry IDs, and visible in the interface.

## Delivery design / no false promises

| Stage | What can be claimed |
|---|---|
| Recognized | text transcribed (not necessarily accurately) |
| Planned | operation and candidate destination identified |
| Authorized | a current human-approved scoped grant exists |
| Dispatched | adapter tried an operation |
| Inserted, unverified | keystrokes or OS action returned, no trustworthy text readback |
| Inserted, verified | editable target confirmed the expected content |
| Submitted, unverified | submit attempted, provider ack unavailable |
| Submitted, verified | provider/target acknowledged receipt |
| Task accepted / completed | distinct agent states with actual provider evidence |

A display label such as "Done" must never hide which state was proven.

## Pilot and acceptance gates

**P0 — design:** maintainer reviews this narrow interface, ADR-025 integration, ADR-020 compatibility, privacy, UI/UX. No new runtime imports or permissions.

**P1 — pure prototype:** small data-only registry + fake adapters, no network or microphone. Use synthetic fixtures for:
- normal dictation including quoted trigger commands;
- explicit destination matching and ambiguous instances;
- changed focus between plan and execute;
- unavailable/secure editor;
- write-only vs submit-capable destination;
- double-submission prevention after unknown timeout;
- provider task accepted vs completed;
- independent outcomes for two destinations.

**P2 — desktop single-app pilot:** one desktop OS and one accessible editor chosen by maintainers. Compare named-route vs focused dictation with real permission checks, target verification and undo where possible.

**P3 — integration pilots:** a second native editor, selected browser composer, and an approved local MCP tool separately. Only add external cloud/provider integration after a specific ADR-019 egress review and explicit costs/credential UX.

**P4 — cross-platform shared behavior vectors:** run pure-contract vectors on Linux, macOS, Windows, Android. Treat iOS as handoff design until that programme is scheduled under MOB-010. Publish tested support matrix, not aspirational universal coverage.

Metrics: destination correctness, wrong-target side effects, abstention, duplicate external actions, false confirmations, verified delivery rate, time-to-draft, task completion and interaction effort. Separate simulated success from field-study claims.

## Decisions required before shipping

1. Narrow pilot standalone for experimentation, or accept ADR-025 first? **Recommend acceptance/reconciliation of ADR-025 before any production wiring.**
2. What may a browser integration read/control, and how does the user select one exact tab?
3. Should any external submission have an approval-free mode? **Recommend no in the first release.**
4. Which OS/editor pairing gives repeatable evidence for the first pilot?
5. Must user-facing "universal" branding explicitly say "supported applications only"? **Yes.**

**Nothing in this document implements or authorizes new code, network communication, app credentials, screen scraping, autonomous goal pursuit, or changing accepted ADRs.**
