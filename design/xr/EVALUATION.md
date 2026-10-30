# YazSes XR — evaluation and validation protocol (proposed)

**No XR benchmark numbers or hardware-verified compatibility results are asserted here.** This is a prospective test plan. Offline unit/contract tests and real device observations are different evidence classes.

## Evidence ladder

| Tier | Meaning | May claim |
|---|---|---|
| E0 | Static architecture/security review | Proposed design only |
| E1 | Deterministic offline state-machine/contract tests | Core logic tested in simulation |
| E2 | Local mock client with synthetic audio/transcripts | Local integration demonstrated |
| E3 | Real PC application and versioned hardware report | Verified on that specific host/OS/device |
| E4 | Consented end-user study across varied devices/users | Measured user benefit within sample |

A simulator result never becomes a Quest, Vision Pro, VRChat or Unity compatibility claim.

## Metrics and denominators

- Final transcript word error rate (WER): measured on a held-out, consented corpus, partitioned by language and model; no invented baselines.
- Time from **speech end** to final transcript, and from user confirmation to observable app outcome (median/p90/p95, device and sample count). Report actual distributions; the earlier research card's sub-second targets are targets only.
- Intent resolution: correct structured proposals / unambiguous eligible requests.
- Target resolution: correct app-owned object IDs / eligible target references.
- Wrong-action rate: incorrect actions actually executed / eligible action opportunities; break down reversible, external and destructive classes.
- Unsafe-external-action rate: unintended published messages or disallowed side effects / external-action opportunities. A zero result is only meaningful with an explicit denominator and scenarios.
- Clarification burden: clarification requests / eligible tasks, plus unnecessary-clarification rate.
- Task completion: independently verified successful outcomes / attempted tasks, with participant dropouts stated.
- Time to stop/recover, unintended gesture activations, and subjective fatigue for hands-free testing.
- Adapter reliability: invalid message rejection, dropped events, reconnection behaviour and memory/queue bounds.
- Privacy: unauthorized-client access successes, off-by-default listener scans, and unintended raw-audio egress.

## Minimum test matrix

| Test | Expected |
|---|---|
| Feature disabled on a fresh install | Existing dictation unchanged; no XR port/listener |
| Final transcript, mock client | Editable draft; no send |
| Transcript containing command-like text | Treated as content absent explicit command mode/authorization |
| Malformed/oversized input | Rejected without crash or unexpected action |
| Duplicate/replayed event | No duplicate external action |
| Missing focus/permission/session expiry | Safe refusal; transcript remains local or discarded per user choice |
| Wrong object/stale ray/multiple candidates | Clarification/abstain, no unverified mutation |
| Client disconnect during capture or commit | Bounded cleanup, no silent retries that publish |
| Tracking loss during gesture | Stop/release, no persistent action |
| Voice “pause” vs spoken content | Only deliberate activation changes mode; no dangerous auto-resume |
| Auth, origin and revocation | Unapproved client cannot receive private transcripts |
| Local processing with network disconnected | Core test path works offline |

## Hardware reporting template

~~~text
Feature / phase:
Test date (UTC):
Test method: E1 / E2 / E3 / E4
Git commit and exact YazSes version:
Operating system and display/session type:
VR application, exact version and its supported API:
Headset/controller/eye-tracker model (if used):
Audio input and routing:
Consent/permission state:
Expected user action and observable result:
Observed PASS / PARTIAL / FAIL / BLOCKED:
Median and p95 latencies, repetitions, measurement method:
Failures, false triggers, unintended sends, workarounds:
Whether the run is reproducible without hardware:
Anonymized evidence location (no raw speech by default):
~~~

## Human study precautions

Invite people voluntarily and obtain explicit informed consent for any recording, headset data, transcripts or publication. Do not assume other VR participants consented to be recorded. Document sampling and accessibility accommodations, allow participants to withdraw, minimize retained identifiers, and keep any personal recordings out of the public repository.

## Release decision

A proof of concept may remain internal if unauthorized delivery, tracking loss, unsafe defaults or false “success” signals persist. Publish only the functionality validated on explicitly named versions/devices; do not promote a new feature toggle based on mocked tests alone. A maintainer-approved security/privacy review and ADR-030 scope decision are necessary before deployment.