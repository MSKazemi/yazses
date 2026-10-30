# YazSes XR — proposed architecture and trust boundaries

**Status: design only.** There is no operational XR endpoint in this specification. The prior [XR API research card](../research/studies/yazses-innovation/output/capability_cards/cap-006.md) is a candidate, not proof of a shipped server. [ADR-025](../adr/adr-025-grounded-interaction-kernel.md) is still proposed; this document aligns conceptual interfaces without treating them as implemented.

## Principles

- Preserve existing dictation as the default. XR is a separate, explicit opt-in adapter.
- Local speech decoding does **not** mean social-world output stays private; the boundary is at the host application.
- Source observations (transcript/gaze/head ray/face switch) cannot by themselves authorize actions.
- Structured commands are proposals, not arbitrary keyboard injection, URLs, shell execution or calls to third-party tools.
- The **application owns** scene object IDs, raycast semantics, allowed actions, avatar permissions and verification.
- Keep perception and safety independent of OpenXR/Unity/Unreal/WebXR. Each engine is merely an adapter.
- No headset LAN listener by default. PC loopback is not headset loopback.

## Data flow

~~~text
[User consent / microphone / optional headset sensors]
             |
             v
[Existing local YazSes STT, hotkeys and state]
             |
             v
[Opt-in application session: scope, allowlist, expiry]
             |
             v
[Transcript or observation -> candidate intent / target]
             |
             v
[Policy: execute local reversible / confirm / clarify / abstain]
             |
             v
[Application adapter: mock / VRChat / Unity / Unreal / WebXR]
             |
             v
[App-reported observable result -> user feedback]
~~~

## Minimum interface before any server

P0 should be an **in-process/local mock** accepting a final transcript and returning a compose draft. The human must separately press the mock's send control. A general event server is not required to prove this.

If P1 evidence justifies the WebSocket approach from the earlier research card, keep the transport optional, loopback-only, disabled by default, with authenticated per-application sessions, explicit client scopes, token rotation/revocation, allowed Origin checks for browsers, strict payload-size and rate limits, bounded queues and no raw-audio events. Loopback does not protect against malicious local processes; origin checks are not a substitute for authentication. The event stream must not be treated as a command execution API.

### Proposed event contract v0 (illustrative, unimplemented)

Every event carries a protocol version, event identifier and session ID. Fields containing speech can be sensitive; redact them from default logs.

~~~json
{
  "version": 0,
  "event_id": "evt-local-example",
  "session_id": "authorized-session",
  "kind": "final_transcript",
  "payload": {"text": "hello everyone", "language": "en"}
}
~~~

A **command proposal**, not an authorized action:

~~~json
{
  "version": 0,
  "event_id": "evt-local-example-2",
  "session_id": "authorized-session",
  "kind": "action_proposal",
  "payload": {
    "verb": "set_color",
    "target": {"app_owned_id": "scene/cube-1", "age_ms": 40},
    "args": {"color": "blue"},
    "risk": "reversible",
    "needs_confirmation": false
  }
}
~~~

Never infer intent solely from the raw transcript text. A target reference must be app-issued, session-scoped, fresh, resolvable, and have the required permission. Intent and target confidence are separate; an execution result must have a verifiable app postcondition when possible. On timeout, invalid target, stale session, denied permission or ambiguous referent: **abstain**.

Proposed states: DISABLED -> IDLE -> CAPTURING -> TRANSCRIBING -> DRAFT_READY -> [REVIEWED] -> USER_COMMIT / CANCELLED. The bridge must **not** traverse DRAFT_READY -> external message automatically. User input in the host application is the only send authorization for the initial social-chat experiment.

## Adapter boundaries

| Adapter | Candidate input | Candidate output | Special rule |
|---|---|---|---|
| Mock chatbox | Authorized local transcript | Editable draft | No external transport, ever |
| VRChat OSC | User-confirmed text/allowlisted parameter | Official OSC messages | Chat **prefill only** in first live pilot; native user send |
| Unity test scene | Transcript + app-provided ray/object | Undoable scene edit | Stable object ID and outcome check |
| Unreal/WebXR | Same semantic contract | Host-defined adapter | No cross-platform support claim until tested |
| Remote headset | Device audio/sensors (future) | Secured session events | Requires separate ADR, pairing, encryption, threat model |

Do not hardcode XR vendor names into core classes or requirements. Hosted application APIs and platform policies may change; reverify before implementation.

## Security, privacy and failure handling

| Risk | Required control / test |
|---|---|
| Accidental external chat publication | Separate review and user-native send; mock test proving no auto-send |
| Unauthorized local application reads speech | Explicit enable/session grant; authentication, scopes, expiry, revocation |
| Browser-to-loopback abuse | Origin allowlist **and** authentication; reject unauthorized connections |
| Remote device confusion | No remote bind; design pairing and encrypted transport separately |
| Wrong 3D object | App-owned target IDs, freshness, confidence, ambiguity => abstain |
| Bad or replayed action event | IDs, session checks, replay bounds, strict schema and per-action permission |
| Persistent gesture movement | Deadman/release, stop and reset on tracking loss |
| Unauthorized audio capture | Only user-permitted sources, recording indicator, no ambient default |
| Overflow / malicious text | Length limits, bounded queues, validation and graceful error |
| Misleading success | Verify host postcondition; present “unverified” if the adapter cannot confirm |

No transcript, gaze trace, contact, location or speaker audio is to be published with a bug report by default. Use synthetic fixtures and opt-in, de-identified evaluations.

## Compatibility and dependency review

Reusing the core STT, command parsing, hands-free safety and existing IPC is preferred to parallel copies. Avoid importing Unity SDKs, OpenXR runtimes or heavy graphics dependencies into the desktop daemon. A transport-extra must be loaded only when enabled, and must not increase the baseline install or start any listener unexpectedly.

See [FEATURES.md](FEATURES.md) for feature contracts and [EVALUATION.md](EVALUATION.md) for the evidence expected before any public compatibility claim.