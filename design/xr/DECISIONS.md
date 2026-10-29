# YazSes XR — open decisions and risk register

**Status: proposed, not accepted.** [ADR-030](../adr/adr-030-agent-era-direction.md) is the controlling decision on new capabilities. [ADR-025](../adr/adr-025-grounded-interaction-kernel.md) is an unaccepted architecture proposal, not a reason to expand scope without review.

## Questions that need explicit decisions

| ID | Question | Recommended starting position | What a different answer changes |
|---|---|---|---|
| D1 | Is user demand sufficient to revisit ADR-030? | No assumption; collect non-contributor evidence | Whether implementation can start |
| D2 | What is the first demonstrator? | Local chatbox draft + native user send | Complexity, dependency and privacy |
| D3 | Which transport? | In-process first, opt-in loopback only if needed | Auth, dependency and lifecycle cost |
| D4 | What counts as authorization? | Per-app consent + separate confirmation for external actions | Allowed actions and threat model |
| D5 | Is VRChat prefill safe on a real version? | Verify actual client behaviour; no auto-send | Whether a live VRChat pilot can happen |
| D6 | How should actions be grounded? | App-provided stable object IDs, not pixel guesswork | Kernel adoption, data contract |
| D7 | What headset scope is defensible? | PC-first only; remote headset is separate ADR | Pairing, transport, encryption and support |
| D8 | When may hands-free controls act? | Explicit armed switch + pause/recovery; gaze never commits alone | False-action and accessibility risk |
| D9 | Which code belongs in core? | None of OpenXR/Unity/Unreal in default daemon | Packaging, tests, support |
| D10 | How do we know the experiment helped? | Predeclared task and safety metrics | Go/no-go, whether to expand |

## Risk register

| Risk | Severity if ignored | Mitigation / stop criterion |
|---|---|---|
| A misheard transcript publishes social chat | High | Draft-before-send; separate native user action; block experiment if any silent send occurs |
| Loopback client exfiltrates transcript | High | Auth, explicit scoped enable, browser Origin checks, revocation; block if unauthorized client succeeds |
| Wrong gaze target changes shared object | High | Scene-owned IDs, freshness, clarify/abstain, undo and verified outcome |
| Standalone headset cannot reach PC service | Medium | No false “localhost works everywhere” claim; separate secure device transport |
| Feature breadth undermines current reliability focus | High | Honor ADR-030 freeze; no implementation issue or release promise before approval |
| API/platform changes or policies prohibit integration | Medium | Recheck official docs and verify current real client; use only supported interfaces |
| Always-on or other participants' recordings violate privacy | High | No ambient capture default; consent and explicit audio routing |
| Repeated gesture triggers, fatigue, accidental locomotion | High | Calibrated intentional control, multiple stop paths, measured false-activation |
| Local inference too slow for use | Medium | Measure actual p50/p95, hardware and trade-offs; no unsupported latency threshold claims |
| Maintenance and dependency burden | Medium | Minimal optional adapters, no change to core dependencies by default |
| False claim of platform support | Medium | Explicit simulated vs hardware-verified matrix; release blocker for unsupported copy |
| Inaccessible confirmation leaves user trapped | High | Alternative switch/voice/manual control, pause/reset, accessible fallback |

## Research hypotheses, not facts

- A local voice-to-chat draft may be more usable than headset keyboard entry for some tasks.
- An application-provided head ray or headset gaze + voice may help select coarse objects.
- A small, local event contract may reduce XR developer integration effort without duplicating a speech engine.
- Voice for text plus a distinct discrete confirmation input may be more comfortable than saying a command for every selection.

Each requires actual measurement and a stated population/task before becoming a claim.

## Decision process

Record the evidence and decision in the existing ADR process. Do not mutate historical accepted ADRs silently: propose an explicit amendment/superseding decision with the reason, scope, risk, and what remains frozen. A docs-only research initiative is allowed now. New code and feature-registry changes require explicit maintainer acceptance.

See [EVALUATION.md](EVALUATION.md) for measures and [TASKS.md](TASKS.md) for conditional work packages.