# ThinkGear/BrainLink-class first-device qualification — evidence review

**Date:** 2026-11-03  
**Status:** Research/design proposal; code and hardware changes NOT performed  
**Scope:** public engineering only, independent of any particular supplier relationship  
**Baseline:** `main` as inspected on 2026-11-03; existing implementation in `src/yazses/biosignal/`  
**Decision companion:** [ADR-v2-155](../adr/adr-v2-155-thinkgear-transport-safety.md)  
**Implementation contract:** [ThinkGear qualification spec](../specs/thinkgear-hardware-qualification.md)  
**Existing governing work:** [ADR-v2-152](../adr/adr-v2-152-biosignal-artifact-switches.md), [ADR-v2-153](../adr/adr-v2-153-biosignal-false-positive-governor.md), [biosignal validation protocol](../specs/biosignal-validation-protocol.md), [ADR-030](../adr/adr-030-agent-era-direction.md).

## Executive finding

YazSes has an opt-in, off-by-default ThinkGear `BlockSource`, a verified-by-fixtures parser, a raw-waveform double-blink detector, stream-integrity protection in the daemon and monitor, calibration, a guided field test, and a conservative false-activation policy. **There is not yet evidence that a specific TGAM headset works in YazSes on physical Linux hardware.** This study does not build a second EEG stack or create a new device driver.

Three concrete correctness gaps merit an engineering pass before a first-device evaluation:

1. `ThinkGearSource.poor_signal` records packet code `0x02` but the live detector decision does not explicitly veto on the source's hardware-reported **no-contact** state.
2. Corrupted packets are counted and discarded, but the source's `t0 = delivered_samples / 512` necessarily **compresses unobserved time**. Ordinary `IntegrityGuard` continuity checks cannot identify an isolated rejected packet from `t0` alone. A rejected packet is **not** proof exactly one raw sample was lost: packet boundaries may contain metadata or multiple values.
3. `run_field_test` in `cli_impl.py` opens and feeds an unguarded source, whereas `run_monitor` and `build_runner_from_config` wrap their source with `IntegrityGuard` and combine `IntegrityGate` with the signal monitor. The evidence-gathering path must use equivalent safety policies to the runtime.

These are observations from code inspection, **not** observed defects on a real headset. Keep the existing generic guards and their tests: the proposal is a narrow adapter-level extension and parity fix.

## Authoritative protocol evidence

| Evidence | What it establishes | What it does NOT establish |
|---|---|---|
| [NeuroSky ThinkGear Communications Protocol](https://developer.neurosky.com/docs/doku.php?id=thinkgear_communications_protocol) | Binary `AA AA length payload checksum` framing; maximum payload 169; `0x02` poor-signal metadata (200 explicitly means no electrode contact); raw `0x80` signed big-endian i16; TGAM ASIC nominal 512 raw samples/s; 57,600 baud required for 16-bit raw | Whether a particular end product exposes its serial byte stream over Linux Bluetooth; independent sequence numbers or true sensor timestamps (none specified) |
| [NeuroSky support: raw-count voltage conversion](https://support.neurosky.com/kb/science/how-to-convert-raw-values-to-voltage) | Nominal TGAM voltage conversion `V = raw * (1.8/4096) / 2000`; actual gains can differ by hardware | Calibrated absolute microvolt accuracy for the candidate unit |
| [Macrotellect public BrainLink Lite specifications](https://o.macrotellect.com/2020/BrainLink_Lite.html) | Product page advertises TGAM, RAW+eSense, 57,600 baud, Bluetooth, and model BL002 V2.0 | Linux host support, RFCOMM/SPP channel availability, physical firmware revision, or compatibility with YazSes |
| [Linux kernel Bluetooth RFCOMM TTY list](https://docs.kernel.org/6.16/admin-guide/devices.html) and [Debian BlueZ rfcomm manual](https://manpages.debian.org/experimental/bluez/rfcomm.1.en.html) | Linux can expose a Bluetooth RFCOMM serial TTY such as `/dev/rfcomm0`; `rfcomm bind` creates a binding, the connection opens on use | That **this headset** advertises RFCOMM, or that BlueZ's rfcomm utility is installed on a user's distro |
| [YazSes ThinkGear source](../../src/yazses/biosignal/thinkgear.py) + [parser tests](../../tests/test_biosignal_thinkgear.py) | Parser rejects malformed/checksum-invalid packets, ignores attention/meditation/blink-strength vendor scores, exposes raw i16 waveform as nominal µV, records quality metadata | Real headset quality, pairing, timing, false-activation rate |
| [YazSes monitor](../../src/yazses/biosignal/cli_impl.py) and [runner](../../src/yazses/biosignal/runner.py) | Existing live stream integrity guard + watchdog; monitor has `IntegrityGate` | Field-test runtime parity today |

### Data model / limitations

- ThinkGear reports an **EEG electrode channel** at the forehead; blinks are **ocular artifacts** visible in that channel, not a thought or motor-imagery decoder.
- `POOR_SIGNAL` is a coarse manufacturer contact/noise indicator, normally about once per second. It is **neither** a blink detector nor a universal certificate of good signal. The waveform quality monitor must remain active after `POOR_SIGNAL=0`.
- A model's raw output rate is typically **512 Hz**, but this is not an observed sample-rate guarantee for the particular product, firmware or Bluetooth link. The physical pilot must measure arrival rates and long-run coverage.
- The stream format has **no sample sequence number or sensor timestamp**. Do not invent either, reconstruct lost raw samples, or claim millisecond-accurate time when packets are dropped.
- The product's advertised Bluetooth and UART capabilities do **not** prove an RFCOMM serial endpoint on Linux; qualification must inspect the actual unit and record a refusal/inconclusive result if SPP is unavailable.

## Current architecture and non-duplication map

| Existing | File / behavior | Proposed treatment |
|---|---|---|
| Parser | `thinkgear.py:ThinkGearParser` | Reuse. Add *targeted* tests for interleaved health and corrupted packets. No new parser. |
| Source | `thinkgear.py:ThinkGearSource` | Add a bounded, typed protocol-health snapshot and block-level provenance without changing the `BlockSource` protocol. |
| Transport integrity | `integrity.py:IntegrityGuard/IntegrityGate` | Reuse composition; add an adapter-specific **source-health veto** rather than treating nominal `t0` as evidence of no loss. |
| Waveform quality | `quality.py:SignalQualityMonitor` | Reuse and keep mandatory for admission; hardware quality veto is additive. |
| Detection | `artifacts.py:BlinkDetector` | Keep detector algorithm unchanged until hardware evidence requires a separate, frozen-configuration tuning round. |
| Runner | `runner.py` | Preserve watchdog, global pause, stale queue handling and action mapping. No direct OS key actions in the new source. |
| CLI evidence | `cli_impl.py` | Make `monitor`, `field-test`, `check-source` and daemon agree on the source-health gate and reason vocabulary. |
| Metrics | `fieldtest.py`, `evaluate.py`, `fprate.py` | Reuse Wilson/Poisson and privacy-safe aggregate schema. Never equate a ten-minute test with robust false-positive evidence. |

## Alternatives evaluated

| Option | Privacy/offline | Complexity | Detects contact loss | Detects corrupted frames | Main limitation | Decision |
|---|---|---|---|---|---|---|
| A. Keep current waveform + integrity only | Yes | None | Indirectly | Parser counts, not a hard veto | Short bursts can be joined across corruption; hardware's explicit no-contact is ignored | **Reject** for qualified live operation |
| B. Device-specific typed health veto composed with existing quality & integrity | Yes | Low–moderate | Explicit 200+ and unknown/stale | Explicit checksum/malformed counters | Status frequency, thresholds and latency must be evaluated; no exact sample-loss timing | **Recommend**, proposed ADR |
| C. Derive blinks from vendor attention/strength scores | Device SDK-dependent | Low coding, weak evidence | No | No | Proprietary event heuristics; vendor-defined behavior; defeats raw-signal, reproducible switch contract | **Reject** |
| D. Add a second proprietary SDK/EEG service | Unknown | High | Maybe | Maybe | Cloud/account/closed driver risk; duplicates the source | **Reject pending an offline gap demonstration** |
| E. Fake precise timestamps or insert synthetic samples for rejected packets | Yes | Medium | No | Masks loss | Gives detectors a false continuity claim and could create gestures across gaps | **Reject** |

## Hypotheses, evidence and falsifiers

**H1 — physical transport:** Linux can read raw `0x80` values without cloud service or vendor account. *Test:* paired device advertises an accessible local serial channel, `check-source` sees nonzero raw samples at a sustained plausible rate. *Falsifier:* only mobile SDK/BLE encrypted app access or no host-visible serial. No bypass by decompiling protocols or switching to cloud.

**H2 — protocol safety:** A disconnected electrode or corrupted packet cannot lead to an accepted double blink, even if a valid-looking waveform continues. *Test:* fake-serial interleavings, hardware contact-lift and deliberate transport corruption; event gate closes, release occurs once, rearm occurs only on fresh clean evidence. *Falsifier:* any accepted event during a tainted block.

**H3 — reproducible live evidence:** The same source-health policy drives the CLI monitor, field test and daemon; repeatable sessions produce truthful aggregate rates. *Test:* equivalent fake-block trace through all three entry points, compare admitted/refused event reasons. *Falsifier:* a trace yields an admitted event in field-test but not daemon.

**H4 — usability:** One operator can set up, calibrate and deliberately trigger blinks across repeated sessions with reasonable burden and without dangerous stuck microphone behavior. *Test:* existing guided protocol and separate hardware safety exercises; report hits, misses, confidence bounds, false activations, reset/reseat burden. *Falsifier:* runaway actions, unacceptable spurious events or unreliable pairing. This is a **feasibility study** only.

## Safety, validity and ethics boundary

- Keep `[biosignal] enabled=false` as the default; it keeps the whole stack inert. `double_blink` currently defaults to true (`src/yazses/config.py`) but has no effect while `enabled` is false.
- No EEG-to-text, attention/emotion/health classification, continuous listening or medical claims.
- Do not grant the source any action capability; existing runner translates bounded events under existing activation policy.
- The first-device test is a single-person **engineering feasibility pilot**, not an effectiveness study and **not** satisfaction of ADR-v2-152's acceptance gate (at least five participants and two configurations). No external participant recruitment or publication of personal biosignals without separate review under ADR-v2-150.
- Do not upload personal raw recordings, voice, calibration profile or per-event timestamps to a hosted coding agent; synthetic bytes only. The shareable field-test report remains aggregate counts/durations without private identifiers.
- If a feature stays experimental or a board fails, report that explicitly. Zero false events in one usable hour yields a one-sided Poisson 95% upper rate of roughly **3 events/hour**, not proof of zero risk; phase-specific upper bounds are often much worse due to shorter exposure.
- A local device connection is not network telemetry. Still require local-only operation and no automatic vendor app activation, data upload or background scan in the code.

## Prioritized research conclusions

1. Solve **test-path parity** and **explicit health gate** before hardware: high-value, reproducible, no participant data.
2. Do not modify the blink detector's numeric defaults based on conjecture; capture baseline from hardware first and predeclare any later retuning round.
3. Treat Linux RFCOMM availability and stream cadence as separate **device qualification results** rather than assumed properties.
4. Keep existing ADR-v2-152 and validation protocol authoritative; this device-specific project must never loosen their evidence gates.

## Source reproducibility

Code locations inspected: `src/yazses/biosignal/{thinkgear,runner,integrity,pipeline,cli_impl,fieldtest,quality}.py`, `tests/test_biosignal_thinkgear.py`, `design/specs/biosignal-validation-protocol.md`; all on public `main` 2026-11-03. Vendor/OS primary landing pages linked above; product pages can change. **No tests or physical experiments were performed in producing this review.**
