# YazSes XR — voice-first interaction for virtual worlds

**Status: PROPOSED FUTURE RESEARCH — not approved for implementation or shipping.**  
**Initiated:** 2026-10-29  
**Scope:** An optional, local-first integration layer for social VR, Unity/Unreal, WebXR, and, eventually, headset-based multimodal input.

> This is a public design record, not a feature announcement. No YazSes XR bridge, VRChat adapter, Unity package, headset client, or XR command is claimed to ship today.

## The proposition

Make YazSes useful *inside applications that already provide a virtual world*, rather than building a new metaverse product: speech generates text or explicit intent; an application supplies its own known targets and controls; a guarded, user-authorized adapter presents or performs permitted actions. Speech recognition remains on the user's own computer unless a separately approved design changes that boundary.

A compelling future demo is: dictate a message in a local VR scene, review it, and explicitly send using the host application's own control. The research stretch goal is: look at a known 3D object, say “make this blue,” and have the application resolve, confirm when necessary, execute, and verify the change.

## Start here

| Question | Document |
|---|---|
| What are all ten ideas and their acceptance criteria? | [FEATURES.md](FEATURES.md) |
| In which order could we explore them, and when is work allowed? | [ROADMAP.md](ROADMAP.md) |
| How should the protocol, integrations and privacy boundary work? | [ARCHITECTURE.md](ARCHITECTURE.md) |
| How do we decide whether a prototype works? | [EVALUATION.md](EVALUATION.md) |
| What are the issue-sized work packages? | [TASKS.md](TASKS.md) |
| Which decisions are still open? | [DECISIONS.md](DECISIONS.md) |

## Fit with the current project

1. **ADR-030 is binding.** [The accepted agent-era direction](../adr/adr-030-agent-era-direction.md) freezes new capability waves until demand evidence and an explicit change to that decision. Research and design documentation are allowed; the work below is **not** a currently scheduled delivery milestone.
2. **ADR-025 is not implemented by assumption.** [The proposed Grounded Interaction Kernel](../adr/adr-025-grounded-interaction-kernel.md) is the preferred vocabulary for observation, target, intent, authority, proposal and verified outcome. Do not silently bypass that proposal or present it as shipped.
3. **Reuse the existing research.** The [May 2026 XR Voice API card](../research/studies/yazses-innovation/output/capability_cards/cap-006.md), [AR/wearables review](../research/waves/03-ar-wearables.md), [eye-control programme](../eye-control/README.md) and [interaction-kernel synthesis](../../docs/research/interaction-kernel.md) are starting points, not implementation evidence.
4. **Preserve the product's differentiator.** No cloud STT, always-on microphone, autonomous assistant, silent message sending, or new default network listener.

## Proposed first vertical slice

**PC-first, no headset required for automated testing.** Use the existing local YazSes STT path to prepare text for a mock chatbox in a small local test application. Require an explicit user action before the mock's “send” operation. Then, *only after approval and verification*, consider a VRChat OSC chatbox integration that prefills rather than sends and a separate, allowlisted avatar-parameter experiment. Any eventual external message remains under user control.

A VRChat-compatible headset, a Unity scene, or a cross-device LAN bridge is **not** a prerequisite for the initial research. Standalone headsets are separate security, audio-routing and connectivity projects; a loopback server on the PC is not reachable as “localhost” on a different device.

## Design invariants

- **Default OFF.** The current dictation, command grammar, hotkeys, IPC and platform compatibility must work unchanged.
- **Human agency.** Only explicit per-application authorization may surface transcripts. Sending external chat, publishing creations, deleting objects, purchases and similarly consequential actions are never implicit side effects of dictation.
- **Separate perception and execution.** Eye/head pose proposes a target, not an action. An intentional speech or switch event plus an authority check commits; ambiguous or stale targets must abstain.
- **App-native capabilities only.** Adapters map to documented host APIs. Never guess at another user's objects, permissions, scene state or social identity.
- **Local processing first.** A permitted output to VRChat or any shared world *is still egress*. Explain it accurately; offline recognition does not make publishing a message private.
- **Accessibility without dangerous assumptions.** Offer alternative confirmation and immediate stop/recovery paths. Do not make blink-to-click, continuous movement or persistent mic capture the default.
- **Evidence over claims.** Proposed targets, measured results and hardware validation are distinct; a docs-only PR cannot claim runtime support.

## Scope and non-goals

**In scope (future, conditional):** transcript event API; local text prefill; declared avatar controls; 3D object targeting in an instrumented scene; multimodal hands-free control; bounded voice navigation; optional translation, meeting notes, scene authoring and spatial guide.

**Out of scope:** a new virtual world or VR operating system; unattended automation in social platforms; game modifications that bypass platform permissions; robot/physical actuation; scraping other participants' speech; silently streaming raw microphone audio; generalized world modification in applications that provide no supported API.

## Governance

This directory is a design proposal. It does **not** override the roadmap's existing priorities or establish a release date. Per [milestone policy](../milestone-policy.md), exploratory research may be tracked as an evergreen research question without a delivery milestone; implementation tasks and milestones are created only after the accepted direction permits them. Any new dependency, network boundary, feature-registry entry or external side effect needs an explicit architecture/security review.

**Next decision:** gather evidence that real users/developers need the XR interface and decide, through an amendment to ADR-030, whether a small experiment may start. See [DECISIONS.md](DECISIONS.md).