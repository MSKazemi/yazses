# OneVoice — universal destination routing (proposal)

**Status:** RFC, experimental design — **not shipped**. The architecture and integration decisions are open for maintainer and community review.

OneVoice proposes a single **human-directed voice interface** that can prepare drafts for *supported and explicitly authorized* application fields, eventually call approved local agent tools, and report what happened without guessing a target or silently submitting external requests.

This is **not** a promise of universal control over all desktop/mobile apps. No release claim or blanket app/agent access is authorized by these design notes.

## Read in this order

1. [Product vision, use cases and platform limits](README.md)
2. [Universal Interaction Interface / adapter contract](UNIVERSAL_INTERFACE.md)
3. [Router proposal, permission and outcome requirements](ROUTER_SPEC.md)
4. [Sixteen design dimensions and decision gates](CONSIDERATIONS_AND_DECISIONS.md)
5. [Evaluation protocol and proposed contributor-sized tasks](VALIDATION_AND_TASKS.md)

## Related work

- [Draft RFC #596](https://github.com/MSKazemi/yazses/pull/596): architecture review; no new runtime capability.
- [Separate offline prototype PR #599](https://github.com/MSKazemi/yazses/pull/599): two in-memory app editors, guarded local drafts, synthetic tests; **not real window control**.
- [Real two-editor pilot issue #600](https://github.com/MSKazemi/yazses/issues/600): blocked by targeting, permission and architecture review.
- [ADR-025 Grounded Interaction Kernel](../adr/adr-025-grounded-interaction-kernel.md) is still Proposed and must not be bypassed with a parallel permanent kernel.
- [ADR-020 Agent Protocols](../adr/adr-020-agent-protocols.md) is Accepted and restricts agent/transport capabilities.

**Non-negotiable:** preserve ordinary offline dictation; do not add always-on recording, external providers, new network listeners or untrusted plugins by virtue of this RFC.
