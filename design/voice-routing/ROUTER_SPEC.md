# OneVoice Router — proposed technical contract

**Status: RFC / not yet accepted.** This defines a narrow pilot without claiming ADR-025 is accepted.

## Separations

`Capture -> STT -> Command boundary -> Route proposal -> Target grounding -> Authorization -> Adapter -> Outcome verification -> Feedback`

- Plain dictation is the default. Routing only when an explicit invocation phrase/command mode is active; embedded quotations such as "please write 'ask ChatGPT'" must not trigger routing.
- Parse the routing prefix and preserve the body exactly, including casing and punctuation, rather than using the existing normalized tool planner's lossy trailing argument. Preserve both raw transcript and parsed command separately.
- Route names must correspond to registered user-visible destinations, not substring matches on arbitrary window titles.
- Selected destination, exact window/tab/session or API account, purpose, target field, timestamp, and consent scope are bound together. If any changes, refuse or re-resolve before injection.
- A destination may be `focused_field`, `local_app`, `browser_composer`, `approved_agent_tool`, `paired_device` (deferred). Names do not imply capability.
- Separate operations: `draft_insert`, `submit_external`, `read_status`, `cancel_task`. Never infer submission from draft insertion.
- The model is not an authority source. UI text, search results, agent outputs and transcripts can never raise execution permissions.

## Reference message schema (conceptual, versioned)

```json
{
  "schema_version": 1,
  "utterance_id": "random-session-id",
  "operation": "draft_insert",
  "raw_transcript": "YazSes write to ChatGPT: explain this traceback",
  "payload": "explain this traceback",
  "target": {
    "registered_destination_id": "chatgpt-browser-primary",
    "surface": "browser_composer",
    "instance_id": "ephemeral-tab-or-window-handle",
    "field_id": "ephemeral-accessibility-identity",
    "snapshot_id": "short-lived-context-token"
  },
  "authority": {
    "user_initiated": true,
    "allowed_operations": ["draft_insert"],
    "expires_with_session": true,
    "external_egress": false
  },
  "evidence": {
    "target_source": "explicit_user_selection",
    "verified_editable": true
  }
}
```

Never serialize private transcript bodies or credentials to ordinary logs. The schema is a discussion aid, not an API promised to contributors.

## Result states

`proposed -> awaiting_confirmation | ready -> running -> inserted_unverified | inserted_verified | submitted_unverified | submitted_verified | agent_accepted | failed | cancelled | abstained`

- `inserted_verified` requires an observed matching editor value or equivalent app acknowledgment; successful OS keystroke injection alone is `inserted_unverified`.
- `submitted_verified` requires a trusted app/API confirmation, not merely an Enter keypress.
- `agent_accepted` is not `task_completed`; subsequent status is distinct.
- Timeout, modal dialog, stolen focus, closed tab, multiple identical tabs, password fields, stale snapshot, wrong app instance, and withdrawn authorization fail closed.
- Repeated requests use distinct idempotency keys where supported. On an uncertain submission result, do not automatically retry.
- Each destination in a fan-out request records a separate outcome; no claim of all-or-nothing transactions.

## Adapter protocol

```python
class DestinationAdapter(Protocol):
    def describe_capabilities(self) -> CapabilitySet: ...
    def resolve(self, snapshot: ContextSnapshot, target: DestinationRef) -> ResolvedTarget | Unresolved: ...
    def preview(self, proposal: RouteProposal) -> DeliveryPreview: ...
    def execute(self, approved: AuthorizedProposal) -> DeliveryOutcome: ...
    def verify(self, outcome: DeliveryOutcome) -> VerifiedOutcome: ...
```

All classes are conceptual. Pure core accepts fake adapters; platform dependencies are behind boundaries. Adapter capabilities specify operation support, required permissions, data-egress classification, outcome verifiability, and maximum payload limits. A local approved app adapter can focus an explicit semantic editable field; do not emulate an app's Send click without separate submission authorization. Prefer first-party native integrations or explicit, consented browser extension bridges over arbitrary visual coordinate clicking.

## Permissions and security

- Global default: **disabled**; per-destination opt-in; no auto-discovery of accounts or private tabs.
- No microphone always-on/wake word by default; activation retains the existing hold-to-talk path.
- Offline default: no network stack required. Explicit third-party submission is an egress event and must follow ADR-019 with destination, payload, permissions, secrets, costs and revocation disclosed.
- Any sending to remote AI, emailing, posting, commits, shell execution, or cross-device transfer must require confirmation unless a narrow, separately reviewed and expiring grant allows it. No silent paid API calls.
- Keep provider credentials in an OS credential store, never in config files, logs, CLI flags or test fixtures.
- Sensitive/secret/password input targets: refuse on unknown role if sensitive intent is plausible; never forward secure text.
- No screen/audio capture expansion implied. OCR, screenshots, extensions, automation APIs and LAN relay each need explicit review and separate capability grants.
- Browser pages and tool replies are untrusted. Do not treat webpage text as commands.
- Emergency stop, revoke destination, cancel queued tasks, and clear pending drafts must be user-accessible.

## Compatibility and operational constraints

- Default existing dictation and commands must remain bit-for-bit compatible with existing golden fixtures.
- No unconditional model, browser automation or cloud dependency; use existing optional feature and dependency budget.
- Do not add a general HTTP server to the dictation daemon: ADR-020 and ADR-019 prohibit this architecture without new review. Paired devices need an isolated service boundary and new ADR, not an open daemon port.
- No third-party arbitrary plugin loading under ADR-018. First-wave reviewed adapters are in-tree.
- Mobile core follows shared vectors; Android IME can insert into the *bound* editor, not arbitrary background apps; iOS main-app handoff restrictions apply.

## Edge-case contracts

1. `"YazSes write to ChatGPT: say send email to Bob"` -> **draft text only**; nested `send` remains data.
2. `"Ask ChatGPT about this"` with no selected content -> clarification; never capture arbitrary screen without consent.
3. Two Chrome tabs named ChatGPT -> clarify target, or use a previously explicitly pinned identity that is still fresh.
4. Focus changes while speaking -> use pinned snapshot and revalidate before write; never send to the new focused field by accident.
5. Submission times out -> mark `submitted_unverified`; do not silently submit twice.
6. Destination unavailable -> keep local draft and report, without disclosing text.
7. Spoken `stop/cancel` -> cancels queued work, does not claim it can reverse an external side effect already committed.

## Governance gates

This spec does not supersede ADR-020, ADR-025, ADR-018 or mobile ADRs. Maintainer approval and an ADR are required for persistent autonomous delegation, novel network paths, Android AccessibilityService, iOS background mic access claims, or generic third-party plugin loading.
