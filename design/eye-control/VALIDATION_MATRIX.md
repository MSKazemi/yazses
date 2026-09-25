# Eye / camera validation matrix

**Purpose:** one place to answer **what test runs where, how many independent replications are
needed, and what counts as evidence**.

This matrix complements:
- [EVALUATION.md](EVALUATION.md) — evidence levels E0–E7;
- [METRICS.md](METRICS.md) — exact field meanings;
- [DATA_SHARING.md](DATA_SHARING.md) — what may be shared;
- [PAPER_EVIDENCE.md](PAPER_EVIDENCE.md) — research/paper path.

## Evidence units

Keep these separate:

- **trial** — one target/activation/action;
- **session** — one continuous test run;
- **person** — independent tester/participant;
- **computer** — independent physical host;
- **OS/session** — Windows, macOS, GNOME Wayland, KDE Wayland, X11;
- **camera** — integrated/USB model/category.

Ten sessions by one person on one laptop are **not** ten independent people or ten independent
computers.

## Engineering support matrix

For **recommended engineering support**, not paper claims, target at least:

- two independent physical computers for each claimed major OS/session bucket;
- preferably two different people for the two machines;
- at least one integrated camera and one different camera/device class across the programme where
  practical;
- at least one non-100% scale or multi-monitor setup;
- one repeated-session result for calibration/drift-sensitive features.

A/B issues exist so contributors do not need to coordinate a large matrix themselves.

| Environment | A | B | Requirement |
|---|---:|---:|---|
| Windows 11 | #428 | #429 | different computer; preferably different person |
| macOS Apple Silicon | #430 | #431 | different computer; preferably different person |
| GNOME Wayland | #432 | #433 | different computer; preferably different person |
| KDE Wayland | #434 | #438 | different computer; preferably different person |
| Linux X11 | #435 | #439 | different computer; preferably different person |
| HiDPI / multi-monitor | #436 | #440 | different topology/computer |
| same person / same machine | #437 | — | three separated sessions |

These public reports are `community_qa`, not automatic research participants.

## Machine-readable form

[`validation-slots.json`](validation-slots.json) carries this matrix as one versioned entry per
cell — pack, environment/session, A/B/repeat, PLANNED/READY, prerequisite issues, target issue
where one exists, time estimate, hardware requirement, beginner-safety and evidence class. It
holds no participant identity, contact detail or raw result.

This prose file stays authoritative for *why* a cell exists; the JSON exists so tooling does not
have to parse the tables above.

```sh
uv run python scripts/check_eye_validation_slots.py
```

The validator is offline, deterministic and stdlib-only. It exits `0` when valid, `1` on a rule
violation, and `2` when the registry cannot be read or parsed at all — a registry it could not
read is never reported as compliant. An empty registry fails for the same reason.

## Test packs

Each test pack is intentionally small. A contributor should run **one pack** unless an issue says
otherwise.

### T0 — install / camera lifecycle / privacy

**Question:** can the feature start and stop safely on this platform?

Steps:
1. camera feature disabled -> camera is not opened;
2. enable -> permission/setup succeeds or produces a clear BLOCKED reason;
3. source becomes healthy;
4. cover/lose camera;
5. no stale action repeats;
6. disable;
7. camera is released.

Collect:
- PASS/PARTIAL/FAIL/BLOCKED;
- start/stop result;
- permission result;
- camera-open count where instrumented;
- failure reason;
- OS/computer/camera/display provenance.

Required for every claimed camera platform.

### T1 — coarse gaze 4-target

**Question:** does webcam gaze choose the intended coarse target?

Standard block:
- four large generated targets;
- 40 trials total, balanced 10 per target after practice.

Collect:
- trials;
- correct target;
- wrong target;
- fallback/no-route;
- invalid tracking;
- calibration validation error;
- calibration age;
- result by time block for drift.

Important:
- **wrong target** and **fallback** remain separate;
- fallback is safer and must not be hidden inside one generic "error rate".

### T2 — Head-Pointer large target

**Question:** can the pointer reach and commit on large targets without phantom actions?

Collect:
- target success;
- movement time;
- misses/overshoots;
- accidental clicks;
- tracking losses;
- pauses;
- recenters;
- test exposure time.

Aggregate:
- completion rate;
- median/P95 movement time;
- miss rate;
- accidental clicks/hour.

### T3 — face-switch activation

Three short blocks:
1. deliberate requested activations;
2. neutral/no-action exposure;
3. ordinary speaking exposure when mouth gestures are tested.

Collect:
- intended activations;
- detections;
- misses;
- false activations;
- exposure seconds/minutes;
- activation latency;
- gesture + threshold/hold/refractory configuration.

Primary safety metric:
**false activations/hour**.

### T4 — safety / pause / recovery

Deliberately:
- pause;
- lose tracking/camera;
- recover;
- resume/re-arm;
- shut down.

PASS requires:
- no stale pointer movement;
- no repeated switch event;
- no immediate dwell click on recovery;
- an independent stop path works.

### T5 — display topology

Run with:
- non-100% scaling and/or multiple monitors;
- topology change where safe.

Collect:
- topology fingerprint;
- calibration valid/stale transition;
- wrong-display result;
- whether routing suspends when topology becomes incompatible.

### T6 — semantic grounding

Related to #441–#445.

Collect on controlled non-sensitive UI:
- candidates in coarse region;
- candidates with usable bounds;
- actionable candidates;
- grounded-correct;
- grounded-wrong;
- ambiguous;
- unresolved/abstained;
- candidate count before/after optional intent hint.

Primary safety outcomes:
- wrong-target rate;
- ambiguity rate;
- abstention rate.

### T7 — hands-free workflow

One synthetic/demo workflow:
1. target text area;
2. dictate provided phrase;
3. move pointer;
4. commit;
5. simulate camera loss;
6. recover;
7. pause;
8. resume;
9. finish.

Collect:
- task completed;
- total time;
- unintended actions;
- recoveries;
- fallbacks;
- keyboard/mouse intervention;
- stop/pause success.

## Which test must run where?

| Test | CI | Windows | macOS | GNOME WL | KDE WL | X11 | multi-monitor |
|---|---:|---:|---:|---:|---:|---:|---:|
| T0 lifecycle/privacy | fake/static | A+B | A+B | A+B | A+B | A+B | useful |
| T1 coarse gaze | synthetic | when runtime supported | when supported | when supported | when supported | **A+B first** | required |
| T2 Head-Pointer | synthetic | A+B | A+B | A+B | A+B | A+B | useful |
| T3 face switch | synthetic | A+B | A+B | A+B | A+B | A+B | not primary |
| T4 safety/recovery | synthetic | A+B | A+B | A+B | A+B | A+B | useful |
| T5 topology | synthetic | at least one | at least one | at least one | at least one | at least one | **A+B** |
| T6 grounding | synthetic | UIA | AX | AT-SPI | AT-SPI | AT-SPI | useful |
| T7 bundle workflow | fake E2E | A+B | A+B | A+B | A+B | A+B | useful |

Do not ask contributors to run a row before that capability is actually reachable on their platform.

## Automatic evaluation gates

Every relevant PR should run, as applicable:

- pure state-machine tests;
- property/boundary tests for confidence/time/coordinate values;
- deterministic synthetic traces;
- privacy/schema validator;
- lazy-import/no-camera-open tests;
- platform import tests;
- fake pointer/portal/native-API tests;
- stale signal/recovery tests;
- output determinism.

#424 owns the cross-OS CI matrix.

## Paper-quality replication is different

The A/B engineering matrix is **not a scientific sample-size rule**.

For a paper:
- freeze research question and analysis first (#425);
- determine ethics/review requirements before recruitment;
- justify participant sample size based on the analysis/precision/effect of interest;
- use multiple trials per participant but analyze the correct independent unit;
- preserve failures and exclusions;
- record repeated sessions separately;
- do not mix `community_qa` into `research` rows by default.

## Stop conditions

A validation should stop rather than force completion when:
- pointer behavior feels unsafe;
- participant/tester is uncomfortable or fatigued;
- camera permission cannot be granted;
- feature is not actually implemented on that OS;
- result schema/version mismatch occurs;
- the test would require sharing private desktop content.

A BLOCKED result is useful evidence and may close a no-code QA task.
