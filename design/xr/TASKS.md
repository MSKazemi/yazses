# YazSes XR — issue-sized research and future implementation tasks

**Read first:** [README.md](README.md), [ROADMAP.md](ROADMAP.md), [DECISIONS.md](DECISIONS.md). This file is a proposed dependency map, **not** a list of READY issues or permission to implement. Any implementation task requires the ADR-030 entry gate and the repository's [milestone policy](../milestone-policy.md). No task should be assigned, marked help-wanted, or promised until actually ready.

| ID | Phase | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|---|
| XR-R01 | R0 | Demand summary with explicit problem statements | None | Non-contributor evidence, anonymized, no invented demand |
| XR-R02 | R0 | Current official VRChat OSC prefill/avatar API audit | None | Versioned doc links and real-client unknowns recorded |
| XR-R03 | R0 | Compare in-process callbacks vs OSC vs WebSocket | XR-R02 | Dependency, privacy and lifecycle comparison |
| XR-R04 | R0 | Privacy/egress and permissions threat review | XR-R03 | Revocation, trust boundary and external-action policy |
| XR-R05 | R0 | ADR-030 decision memo | XR-R01–R04 | Approved decision or documented deferral |
| XR-P001 | P0 | Pure compose/review/cancel state machine | XR-R05 approved | Unit tests including “never auto-send” |
| XR-P002 | P0 | Mock chatbox showcase | XR-P001 | Offline demo and failure matrix |
| XR-P003 | P0 | Measured report | XR-P002 | Timing/error/negative-case denominators |
| XR-P101 | P1 | Minimal versioned event contract | P0 gate | Schema/compatibility and redaction tests |
| XR-P102 | P1 | Optional local transport + authorization | XR-P101 | Off-by-default, origin/auth/revoke/replay tests |
| XR-P103 | P1 | One sample adapter/SDK | XR-P102 | Consumer integration tests and documentation |
| XR-P201 | P2 | VRChat OSC mock and prefill validation | XR-P101 | No auto-send, real host version verified |
| XR-P202 | P2 | Allowlisted avatar action study | XR-P201 | Parameter and failure-mode evidence |
| XR-P301 | P3 | Unity/other instrumented scene target snapshot | XR-P101 | Fresh/stale/ambiguous object-id tests |
| XR-P302 | P3 | Reversible “color this object” proposal | XR-P301 | Explicit authority, undo and verified outcome |
| XR-P401 | P4 | Head/gaze/switch confirmation + pause | XR-P302 | Tracking-loss, stop/recovery tests |
| XR-P402 | P4 | Consented accessibility evaluation | XR-P401 | Task/fatigue/false-action report |
| XR-P501 | P5 | Bounded navigation evaluation | P3 | Host waypoints, comfort/cancel data |
| XR-P502 | P5 | Scene editing research | P3 | Sandbox undo and ownership checks |
| XR-P503 | P5 | Translation/subtitle feasibility | P1 | Local model and consent benchmark |
| XR-P504 | P5 | Meeting notes feasibility | P1 | Authorized audio path and transcription evidence |
| XR-P505 | P5 | Spatial guide feasibility | P3 | Metadata-grounding and storage policy |

## Suggested PR boundaries (after approval)

1. **R0 research PR:** official platform behaviour, demand, updated decisions only—no runtime.
2. **P0 core PR:** pure state machine, synthetic fixtures and the mock demonstration—no network.
3. **P1 transport PR:** optional package extra, security controls, schema and negative tests.
4. **P2 app PRs:** VRChat adapter and Unity demonstration separately.
5. **P3/P4 research PRs:** separate targeting and accessibility evaluations.

Every PR should state “proposed / simulated / hardware-verified,” the affected trust boundaries, how to disable it, tests, and any actual egress.

## First useful contribution today

An independent user can file a **non-sensitive research question or demand report**, e.g. “I use [platform/device] and cannot enter text in [task]; I would test a voice-to-prefill solution,” without posting recordings or private conversations. An XR developer can independently check host API constraints and contribute documentation. Under ADR-030 neither action automatically authorizes a new capability wave.

No synthetic benchmark, supported-platform badge, user-study conclusion or feature-registry toggle should be created as a substitute for observed evidence.