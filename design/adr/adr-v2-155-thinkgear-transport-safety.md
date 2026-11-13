# ADR-v2-155 — Fail-closed ThinkGear stream health before first physical-device qualification

**Status:** Accepted (2026-11-13, maintainer; G0 #827)  
**Scope:** Device-specific correctness hardening of the already-shipped, opt-in biosignal source; **not** a new capability or a claim of hardware support  
**Related:** [ADR-v2-152](adr-v2-152-biosignal-artifact-switches.md), [ADR-v2-153](adr-v2-153-biosignal-false-positive-governor.md), [ADR-030](adr-030-agent-era-direction.md), [research](../research/2026-11-03-thinkgear-first-device-evidence.md), [implementation spec](../specs/thinkgear-hardware-qualification.md), [flowcharts: as built vs proposed](../biosignal/thinkgear-flowcharts.md).

## Context and problem

The existing `ThinkGearSource` reads raw TGAM/ThinkGear packets into `SampleBlock` and exposes `poor_signal` as metadata. The same source can report rejected checksums, malformed payloads and discarded framing bytes. The live daemon and `biosignal monitor` use `IntegrityGuard` and `IntegrityGate`; `biosignal field-test` currently does not use their same composition. All parser/gesture verification is synthetic or fake-transport; real-device interoperability and accuracy are unverified.

A ThinkGear packet has no sample sequence or true sensor timestamp. `t0 = accepted_raw_samples / 512` is an **index in emitted data**, not proof that no sample was lost. An ordinary timestamp-continuity guard cannot infer whether a rejected packet concealed raw data. A `POOR_SIGNAL` value is reported periodically, not per sample, so a later good value must never retroactively clear a bad or unknown interval.

The existing [ThinkGear protocol](https://developer.neurosky.com/docs/doku.php?id=thinkgear_communications_protocol) defines `0x02` as a contamination/contact signal: **zero** denotes no detected contamination; **any nonzero** value denotes contamination, with 200 a documented no-contact case. The signal is an additional veto, **not** evidence by itself that the waveform is suitable.

## Decision (proposed)

1. **Retain existing raw-only artifact semantics.** Keep `0x80` raw i16 as the only input to blink/jaw detectors. Never turn vendor eSense, attention, meditation or vendor blink-strength values into activation intents. Never infer neural intent, health or emotion.
2. **Attach a typed, bounded, per-read health verdict to the source's accepted blocks.** Read and validate all packet health changes **in wire order**. Any checksum/length/malformed frame, nonzero contact value, unknown contact state, stale contact report or device disconnect marks that entire affected read/batch untrusted; an end-of-batch good value cannot rescue the batch. Keep health facts separate from waveform samples and never persist raw signals to reporting artifacts. A batch without raw data may update health but may not generate an event.
3. **Compose a source-specific health veto with existing guards**, not an alternative signal detector. The event gate is open only when source-health, stream integrity and waveform quality all permit it, and only after a clean rearm period. A source-health veto must close/release an already-held activation (where one exists), suppress pending double-blink state and prevent a stale event from appearing on recovery. Preserve the runner watchdog and existing global pause/activation safety. Missing or unrecognized provenance is treated as untrusted.
4. **First-device policy is intentionally conservative and initially fixed in code:** receive at least one explicit `POOR_SIGNAL=0` before admitting events; consider `POOR_SIGNAL != 0` unhealthy; close if the most recent report is older than **3.0 seconds** of an injected monotonic live clock; following any unhealthy/unknown state, require **two fresh, separate zero-valued health reports** and **at least 1.0 second of contiguous valid raw samples** before admitting. The current read/batch that completes this requirement remains vetoed; admit no earlier than the following clean batch. These are **untested engineering thresholds**, not product-validated defaults; they may be changed only in a reviewed follow-up with measured evidence, never tuned on evaluation samples.
5. **Malformed/rejected data creates an uncertainty epoch, not a guessed time interval.** Count discarded packets and discarded bytes, but **never assume each bad packet represents one raw sample** and never insert zero/repeated/interpolated samples to conceal transport damage. Invalidate a gesture that spans an uncertainty boundary, reset detector/filter state on gate transitions, and exclude untrusted exposure from the field-test denominator. Where a true lost-sample count is unknowable, label it `unknown`.
6. **Single shared live-policy composition.** Make the daemon runner, `monitor`, and `field-test` construct the same source-health/integrity/quality stack. `check-source` still performs its generic conformance checks but should add a ThinkGear-specific protocol-health qualification line, without claiming device support. Preserve `BlockSource` as-is, avoiding public config, CLI or IPC changes unless a separate maintainer-reviewed interface change is needed.
7. **Failure isolation.** A missing `pyserial`, no RFCOMM serial port, unexpected firmware payloads, stale quality, device disappearance, invalid block or health-gate error cannot crash normal dictation and cannot cause a new activation. A generic quality-gate exception must not silently disable the remaining source-health veto; fail closed for this path.
8. **Privacy and evidence.** Preserve off-by-default behavior and no network calls, telemetry, cloud dependency or automatic vendor SDK. Only local human-selected hardware can be opened. Shareable reports contain aggregate counts/exposure and non-identifying hardware metadata only; raw EEG/EOG and personalized calibration files remain local. For the first test, use a single volunteer as an **engineering feasibility** result, not a clinical trial or ADR acceptance evidence.

## Important implementation boundary

Do **not** change the `SampleBlock` dataclass, its `t0` contract, the generic event vocabulary, action mapping or core blink thresholds as a shortcut. An internal optional source-provenance interface on `IntegrityGuard` is acceptable only if it is backward-compatible and tested with every existing source type. No action or key injection is added to the driver itself.

All packet-level transitions occurring inside a single serial `read()` must affect that read's gate verdict. Conservative whole-batch veto is preferable to pretending that the final `poor_signal` applies to earlier samples; splitting batches is optional only if strictly proven necessary and bounded. If an invalid frame arrives without any raw block, it still invalidates pending detector state and cannot leave a held action indefinitely: coordinate the fail-closed transition with the runner watchdog/release path.

## Alternatives

| Alternative | Upside | Failure | Decision |
|---|---|---|---|
| No change; trust generic signal-quality heuristics | Smallest patch | Ignores explicit contact-loss signal; nominal sample-index clock masks possible loss | Reject |
| Use vendor's built-in blink-strength / attention values | Easy demo | Opaque algorithm, proprietary heuristics, poor reproducibility | Reject |
| Assume one missing raw sample per rejected packet and synthesize a timestamp | Simple clock bookkeeping | Incorrect for metadata packets, multirow raw packets and lost chunks; false precision | Reject |
| New proprietary EEG SDK or remote service | May improve device interoperability | Duplicates validated source shape, might depend on account/network | Defer unless a documented offline incompatibility |
| **Source-specific typed health veto + reuse existing gates** | Conservative, testable with fake serial, works offline | Needs provenance and shared construction; may be overly strict | **Selected** |

## Consequences and explicit trade-offs

- A headset that never emits `POOR_SIGNAL` or reports low nonzero values continuously will be *ineligible for qualified activation* under this initial policy. Report `unqualified/needs investigation` instead of silently bypassing the gate. This may reduce availability; that is the safety choice until evidence exists.
- A valid packet stream may still have real-world dropouts. A passed conformance run demonstrates the limited interval measured, never universal reliability.
- One usability pilot cannot upgrade [ADR-v2-152](adr-v2-152-biosignal-artifact-switches.md) from Proposed: its five-participant, multi-configuration, per-phase statistical and safety gates remain intact.
- A future alternate sensor with a different metadata contract must declare an explicit adapter and independent tests; this ADR is **not** a generic EEG driver mandate.

## Acceptance tests before a reviewable runtime PR

- Fake-serial streams: contact unknown, fresh zero, nonzero after good, 200 no-contact, 0/200/0 interleaving in one batch, corrupt checksum before a valid blink, malformed length/payload, missing reports >3s, serial unplug/replug, idle/stall, multiple starts/stops, and oversized garbage; all events suppressed when health is untrusted.
- A double blink straddling a health transition is not accepted; no event leaks on rearm; a held activation releases exactly once even across errors, pause and watchdog.
- `field-test`, `monitor`, and daemon apply the **same** health gate and report comparable reasons for the same packet sequence. Their normal synthetic/file/LSL/BrainFlow behavior remains unchanged.
- Shareable field-test output has only counts/durations and no raw waveform, source path, per-event time, address or identifying data; critical errors remain in local diagnostics.
- `uv run python -m pytest tests/ -v`, `uv run ruff check src tests scripts` and `uv run mypy src` (advisory) verified; generated documentation and the ADR index updated via their **generators**, not manually.
- A human hardware pilot and the larger acceptance study are **separate** future evidence stages, not prerequisites to reviewing a pure fake-transport patch.

## Revisit / kill

Stop this device path (no launch/support claim) if the local host cannot access raw values without cloud/account, if contact health cannot be observed with sufficient freshness, if the supported firmware supplies no dependable raw stream, or if any recurrent stuck-action scenario remains after a fix. Log a reproducible limitation rather than bypassing the safety gate. Any change to these rules needs a dated amendment and maintainers' review.

**Verification status:** Design and code review only. No code patch, tests, physical board, human participant or device measurement was run for this ADR.
