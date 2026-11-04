# Specification — ThinkGear first-device qualification, transport health and evaluation parity

| Field | Value |
|---|---|
| ID | `spec-thinkgear-first-device-qualification` |
| Status | **Proposed; implementation not authorized until maintainer reviews ADR-v2-155** |
| Date | 2026-11-03 |
| Scope | Narrow hardening of an existing opt-in ThinkGear source, then physical Linux feasibility |
| Companion decision | [ADR-v2-155](../adr/adr-v2-155-thinkgear-transport-safety.md) |
| Research baseline | [Evidence inventory](../research/2026-11-03-thinkgear-first-device-evidence.md) |
| Higher-priority constraints | [AGENTS.md](../../AGENTS.md); [ADR-030](../adr/adr-030-agent-era-direction.md); [ADR-v2-152](../adr/adr-v2-152-biosignal-artifact-switches.md); [current field protocol](biosignal-validation-protocol.md) |
| Hardware | **Not yet available or measured** for this work; no product-specific compatibility claim |

## 0. What coding agents must do first

1. Read `AGENTS.md`, `design/architecture.md`, ADR-030, ADR-v2-152/153/155, this spec, the existing validation protocol, then **re-inspect latest main** before editing. This audit is tied to the 2026-11-03 tree; a later PR may already solve part of it.
2. Do not build a parallel biosignal pipeline, replace `BlockSource`, introduce EEG/attention/brain-intent decoding, add a network dependency, alter default-on behavior, or change the public command contract without a reviewed ADR.
3. Work in **small separate PRs**: PR A pure health-state unit tests / source behavior; PR B safe guard composition + shared CLI wiring; PR C diagnostics/docs; PR D real hardware results only after there is hardware and explicit human control. The human author reviews every PR before opening it.
4. All automated fixtures are **synthetic bytes and fake clocks**. Do not upload actual raw signals, files of a person's calibration, device identifiers, video or audio to any cloud coding service.
5. Run `uv sync`, targeted pytest, whole `uv run python -m pytest tests/ -v`, `uv run ruff check src tests scripts`, `uv run mypy src` and documentation-generation commands when corresponding interfaces change. Never report passing without logs.

## 1. Existing code and extension points (do not duplicate)

| Function/contract | Existing path | Requested addition |
|---|---|---|
| Binary parser, fake serial | `src/yazses/biosignal/thinkgear.py`, `tests/test_biosignal_thinkgear.py` | Per-read fault/contact provenance and strict recovery state |
| Data contract | `biosignal/types.py:SampleBlock, BlockSource` | **No public dataclass/protocol change**; optional read-only internal provenance adapter |
| Sample-integrity guard | `biosignal/integrity.py:IntegrityGuard, IntegrityGate` | Preserve shape/timing guard; let guard carry source-health provenance through sanitized copies |
| Quality and detector | `biosignal/quality.py:SignalQualityMonitor`, `biosignal/artifacts.py:BlinkDetector` | Preserve waveform gate; additive veto; **do not retune detector** on guesswork |
| Runtime | `biosignal/runner.py:build_runner_from_config` and `BiosignalRunner` | Reuse watchdog, event mapping, global pause, ledger, backlog cancellation |
| Monitor | `biosignal/cli_impl.py:run_monitor` | Call shared guard builder instead of duplicating conditional guard logic |
| Field test | `biosignal/cli_impl.py:run_field_test`, `biosignal/fieldtest.py:FieldTestSession` | **Currently missing parity:** wrap source and install same integrity/health quality gate |
| Conformance | `biosignal/conformance.py:check_source`, `cli_impl.py:run_check_source` | Add optional scoped ThinkGear health summary; don't redefine conformance for every source |
| Safety tests | `tests/test_biosignal_runner.py`, `tests/test_biosignal_cli_devices.py`, `tests/test_biosignal_integrity.py` (verify actual files) | Guard parity, invalid episodes, shutdown/release |
| User docs | `docs/how-to/biosignal-hardware.md` and `docs/how-to/biosignal-switch.md` | Minimal hardware-specific Linux setup and known limits after tests |

## 2. Wire processing and the contamination problem

Existing parser emits a list of valid `ThinkGearPacket(raw: tuple[int,...], poor_signal: int|None)`; rejected packets are counted in `stats`. The source currently collapses all accepted raw rows from **one serial read** into one `SampleBlock`. It stores only the **last** poor-signal value in the source; that is insufficient for a batch `poor=0 -> poor=200 -> poor=0`, because a final zero would conceal a no-contact transition. Similarly, a valid raw-looking blink adjacent to a corrupted frame cannot be reliably timed against the missing frame.

**Required deterministic order for one source.read():**

1. Read no more than a bounded amount of serial bytes per iteration; honor any internal parser-buffer bounds. Do not block the runner indefinitely.
2. Snapshot parser counters **before** feeding; parse bytes; compute *deltas* after feeding. Inspect every **accepted** packet's `poor_signal` in wire order; count all nonzero values even if later packets report zero.
3. If any parser reject/dropped framing segment occurred during the batch, or **any** nonzero quality value occurred, mark the *whole emitted batch* `UNTRUSTED` and start/continue a fault epoch. **Do not count zero reports in a tainted batch as rearm evidence.**
4. If there is no fault, process separate explicit-zero quality reports as clean reports. Accumulate contiguous valid raw samples only while the latest known quality is zero and fresh (no gap/stall/contact issue).
5. The batch that brings an unhealthy state back to the ready threshold remains **untrusted**. No event is admitted until the **next separate, clean** batch. This avoids applying the end-of-batch metadata to earlier bytes.
6. Return a `SampleBlock` only if actual decoded raw samples exist, preserving their order and nominal scaling; otherwise return `None` while maintaining the updated health state. A rejected packet does **not** cause guessed timestamps, synthesized samples or stream padding.
7. Attach an immutable read-level health snapshot to the returned block, using an internal provenance helper (not a public dataclass change). At most a small fixed number of recently emitted blocks may be retained, e.g. the existing `IntegrityGuard` provenance depth. If the block is not recognized, veto it.
8. On `stop()`, disconnect, restart or unavailable transport, clear readiness, pending rearm and provenance. Counters may persist in-session for diagnostics, but must not carry trusted state across new source instances.

**Correction to a tempting shortcut:** never derive quality from just `source.poor_signal` at evaluation time, because that is the current, possibly later, state rather than the state of the block being evaluated.

## 3. Internal health state contract (pure, stdlib only)

Suggested file `src/yazses/biosignal/thinkgear_health.py` or a clearly separated pure section in `thinkgear.py`, with deterministic fake monotonic clock injection.

Suggested immutable types (illustrative names; maintainers may choose alternatives if semantics and tests match):

~~~python
from dataclasses import dataclass
from enum import Enum

class HealthReason(str, Enum):
    UNKNOWN_CONTACT = "unknown_contact"
    CONTACT_CONTAMINATED = "contact_contaminated"
    CONTACT_STALE = "contact_stale"
    CORRUPT_PACKET = "corrupt_packet"
    TRANSPORT_STALLED = "transport_stalled"
    REARMING = "rearming"
    TRUSTED = "trusted"

@dataclass(frozen=True)
class BatchHealth:
    epoch: int
    trusted: bool
    reason: HealthReason
    nonzero_quality_reports: int
    rejected_packet_delta: int
    last_poor_signal: int | None
    consecutive_good_reports: int
    continuous_good_samples: int
    # No raw samples, per-event timestamps, device address or file path
~~~

The pure state machine accepts parser-derived *counts/quality updates* and monotonic arrival time. It must not import `serial`, `brainflow`, `pylsl`, `Qt` or OS modules. Its input includes the number of **distinct** explicit-zero reports, whether any nonzero report was present, parser reject deltas and valid raw sample count; unknown/missing metadata is not treated as healthy.

**Initial engineering constants, pending real evidence:** `CONTACT_TTL_S=3.0`, `REARM_GOOD_REPORTS=2`, `REARM_CLEAN_SAMPLE_S=1.0`, nominal `THINKGEAR_FS=512.0`. Use an injected monotonic clock for TTL, not `SampleBlock.t0`. A `POOR_SIGNAL=200` is no-contact, but **all nonzero** values veto. Avoid adding new user-configurable thresholds in this narrow phase. Check float finiteness and negative time/clock discontinuities; a reversed clock is not proof of freshness. For protocol stats, `bad_checksum`, `bad_length`, `malformed` and significant stream skips trigger conservative invalidation; a lone extraneous framing byte need not equal a dropped sample but may conservatively veto that batch.

### State table

| Existing state | Input during a read | Result for **this** batch | Next state |
|---|---|---|---|
| UNKNOWN (initial) | Valid raw; no `0x02` report | Suppress | UNKNOWN |
| UNKNOWN | First `poor=0` and valid raw | Suppress | REARMING |
| UNKNOWN / READY | Any `poor != 0` (incl. 200), even if later `0` | Suppress | UNTRUSTED; clear clean counters |
| UNKNOWN / READY / REARMING | Any bad checksum, bad length, malformed row or significant resync | Suppress; do not infer sample count | UNTRUSTED; clear counters |
| READY | Fresh `poor=0`, no fault, clean valid raw | Admit, subject also to waveform+integrity gates | READY |
| READY | No contact update for >3s of live monotonic time | Suppress | UNTRUSTED/STALE |
| UNTRUSTED | One good report; clean valid raw | Suppress | REARMING |
| REARMING | Second distinct good report and ≥512 consecutive valid raw samples since fault | Suppress **this** batch | READY for next clean batch |
| REARMING | Explicit quality becomes nonzero, stale, parser invalid or stream stalls | Suppress | UNTRUSTED; clear counters |
| Any | Stop, serial disconnect, runtime restart | Suppress; invalidate source | UNKNOWN until fresh start |

The device may provide two good reports in one large serial batch; **a batch is still suppressed** until the next clean batch even if the state reaches READY. An absent `0x02` stream never becomes qualified by waveform cleanliness alone. Watchdog and generic integrity guard remain independently active.

### Temporal limitations

- The source's `t0` is based on **delivered samples**, not sensor wall time. After loss, report **unknown sample gap** instead of fabricating `t0` increments.
- A corrupted/uncertain epoch must reset blink pairing history, filters and gate-span history as required, without resetting a false-positive governor's evidence of earlier problems.
- A clock TTL can only say a report was received recently; it does not prove that the headset sampled recently (Bluetooth buffering). Use the already-existing arrival-rate, stall and backlog checks, and call this limitation out in results.
- A block spanning a transition is wholly suppressed even though some samples may have been healthy. This errs toward false negatives during reconnect, which must be reported.

## 4. Guard composition and shared factory

**Reference flow:**

~~~text
Serial bytes (local only)
   -> ThinkGearParser (raw 0x80; 0x02 contact as metadata)
   -> ThinkGearSource (SampleBlock + immutable BatchHealth)
   -> IntegrityGuard (existing typed stream/t0/arrival validation)
   -> BiosignalPipeline:
        existing SignalQualityMonitor
        + existing IntegrityGate
        + ThinkGearHealthGate (additional per-block veto)
   -> existing BlinkDetector -> gated BioEvent
   -> existing runner/activation policy (no driver-owned OS action)
~~~

Do not copy/move detectors or create a second runner. Add a **small shared constructor** in a neutral helper (e.g. `biosignal/source_gates.py`) that:
- wraps all live sources in `IntegrityGuard`; chooses `check_arrival_rate=True` only for live sources;
- for a ThinkGear source, preserves block-specific `BatchHealth` through the integrity guard, including cases where it sanitizes non-finite data by producing a new block instance;
- composes `IntegrityGate` with a ThinkGear-specific quality veto that provides the existing fields `overall`, `suppress_events`, `bad_during_update` and an explicit reason; the outer gate must respect inner BAD, never bypass it;
- on missing provenance or health-gate error returns BAD (no activation), and resets any pending detector state; the global quality gate must **not** be silently disabled because of an exception;
- leaves all other source schemes behavior-identical (synthetic, file, BrainFlow, LSL, BITalino, Myo).

**Provenance implementation guidance:** `IntegrityGuard.read` knows the inner source's exact just-returned block, and when it produces a sanitized copy knows the corresponding outer emitted block. Capture the optional health snapshot at that boundary and record it beside its existing bounded identity map. Expose a read-only `health_for(block)` method returning the snapshot **only** for a recognized emitted block. If none exists, a ThinkGear gate vetoes; non-ThinkGear sources simply never install that gate. Do not rely on a single mutable `source.poor_signal` at pipeline evaluation time or on new attributes in `SampleBlock`.

**Failure-without-block caveat:** a bad health packet with zero raw rows can arrive while a blink candidate is pending. The next block must still be suppressed and reset the candidate. If the source then goes silent, the current watchdog/stop path releases a held input. Avoid synthetic empty blocks (the existing `SampleBlock` invariants may not support them). The worst-case release bound must be validated with a fake stalled source.

**Three callers:**
- `build_runner_from_config`: use the shared constructor after lazy `open_source`; no new eager dependency.
- `run_monitor`: same constructor, no second handwritten gate path; its `status` prints contact/transport reasons without values from raw signal.
- `run_field_test`: same constructor for the source and pipeline; the session must exclude unhealthy blocks from **usable exposure** and void overlapping cues through its existing `_trust(status)` path; its result must match admitted/refused events from the same packet sequence. Do not change aggregate report schema unless required and reviewed.
- `run_check_source`: keep generic conformance unchanged for other sources; optionally append read-only ThinkGear source-health summary (contact report seen, parser errors, untrusted reason) and label as **protocol qualification** not proof of usable gestures.

## 5. Fake-transport tests (mandatory before live hardware)

Make independent synthetic bytes using the existing `packet()` and `raw_row()` fixture helpers; no proprietary recordings. Use injectable serial factory, fake monotonic clock, fake event callbacks and deterministic block boundaries. Suggested tests:

| ID | Case | Expected invariant |
|---|---|---|
| TG-01 | Valid NeuroSky packet, `poor=0`, raw i16 | Scaling and parser payload unchanged; no vendor scores exposed |
| TG-02 | Raw values before first quality report | ZERO accepted blink events |
| TG-03 | `poor=0,200,0` inside one serial `read()` | Whole batch veto; no final-good rescue |
| TG-04 | `poor=1` low contamination, `poor=200` loss contact | Both suppress; status distinguishes quality from validity |
| TG-05 | Checksum bad + valid raw packet in one read | Whole batch veto; no synthetic sample or invented gap |
| TG-06 | Malformed row and invalid PLENGTH | Parser counters rise; health epoch invalid; bounded resync |
| TG-07 | Quality report stops for >3s; raw samples continue | Events cease, later recovery requires fresh reports |
| TG-08 | Two explicit good updates + ≥512 clean samples | Candidate batch still vetoed; only next clean batch eligible |
| TG-09 | Blink pair begins before contact loss and ends afterward | No double blink; detector reset prevents delayed event |
| TG-10 | Serial unreadable, partial packets, huge garbage | Bounded memory; optional source fails as no-op; daemon lives |
| TG-11 | Source stop/start/reconnect | Old contact trust cannot survive new session |
| TG-12 | Non-finite array sanitized by `IntegrityGuard` | Provenance preserved across copied block; no exception-driven permit |
| TG-13 | A source without health metadata | Existing generic sources unchanged and still pass known tests |
| TG-14 | Same fake packet trace through monitor, runner and field test | Same accepted/drop behavior; same closed cause while untrusted |
| TG-15 | Held action + fault + pause / watchdog + recovery | Exactly one release, zero new activation until rearmed |
| TG-16 | Source-health veto during field-test rest and gesture cues | Untrusted seconds excluded; invalid cue windows voided; all reports aggregate-only |
| TG-17 | Exact privacy report schema and permissions | No waveform, raw byte stream, calibration, serial port path, MAC, timestamps or personally identifying content |
| TG-18 | No transport attempt with `[biosignal] enabled=false` | Base install and default command path unchanged |

For TG-14 create a **shared trace fixture** with ordered `bytes`, `arrival_clock_s`, `expected_health`, `accepted_event_kinds`, `dropped_reason`; keep this trace independent of production detector implementation so regression tests can falsify code. Include both 50 Hz/60 Hz mains mocks where applicable; do not alter blink amplitude until hardware evidence exists.

## 6. Linux first-device qualification — human-operated only

No remote coding agent can pair or wear the device for the owner. Physical steps must remain an explicit human handoff. The following is an **investigation protocol**, not a demonstrated working guide for a particular headset.

1. Record product model/revision, firmware if accessible, Linux distribution/kernel, BlueZ version, adapter, connection method, power/battery state, electrode setup and YazSes revision locally. Do not publish device address or OS username.
2. On Linux, use regular OS Bluetooth discovery to check whether the device exposes a local serial/RFCOMM profile or another documented raw-data interface. Do **not** assume every BrainLink-class device exposes SPP. If unavailable, classify as `raw transport unavailable` pending documented vendor instructions, no speculative cloud workaround.
3. Only if an RFCOMM TTY is actually available and linked, and pyserial installed from the YazSes optional `emg` extra, attempt `thinkgear:/dev/rfcomm0` (the actual port may differ; never hard-code a Bluetooth address into a public artifact).
4. Run (from the official CLI help if flags have since changed):

~~~sh
yazses biosignal doctor --source 'thinkgear:/dev/rfcomm0'
yazses biosignal check-source 'thinkgear:/dev/rfcomm0' --seconds 30
yazses biosignal monitor --source 'thinkgear:/dev/rfcomm0' --blink --seconds 60
~~~

5. Observe raw packet count, observed sampling cadence, contact and integrity reasons, not just nominal 512 Hz. Demonstrate `poor=0`, real blink signal, lift-off veto, reconnection, and quality rearm. Record failures if the device never shows usable contact metadata.
6. Calibrate in a separate, voluntary single-person session; keep the default action disabled for initial observation. Start `yazses biosignal field-test` only after source preflight, as prescribed in [existing protocol](biosignal-validation-protocol.md). Keep this as observation (no app input) before any live activation.
7. If proceeding to live activation after safety checks, retain an ordinary physical key/stop alternative and execute the existing stress matrix (pause, device loss, stuck input recovery). Do not assume `SIGKILL` automatically releases an OS-level key: verify end-to-end manually and report the result.
8. Repeat after electrode reseat or on another day, **freezing thresholds** for each scored evaluation round. A different montage/firmware is a new configuration. No claims of generalization.
9. Export only reviewed aggregate result JSON with explicit permission; erase/redact any identifying metadata and never upload raw signals or personal recordings.

**Interpretation:** One participant's first-device pilot can establish *feasibility or failure modes*, not clinical safety or ADR-v2-152 acceptance. In one usable hour with zero observed false activations, the one-sided 95% Poisson upper bound is approximately 3/h; a short per-phase session gives a weaker bound. Report counts, exposure, lower/upper intervals, missing/voided trials and firmware/OS separately.

## 7. Deployment and reporting gates

| Gate | Requirement | Evidence artifact | Cannot claim |
|---|---|---|---|
| G0 — Architecture review | Maintainer reviews proposed ADR-v2-155 against ADR-030/152 and accepts or revises its conservative thresholds | Dated ADR decision; implementation issues refined | Feature ready |
| G1 — Source health | TG-01..11 deterministic fake-serial tests pass | Green targeted/whole pytest, ruff and typed check output | Any real hardware supported |
| G2 — Parity and privacy | TG-12..18 pass; field-test and runtime use same admission path | Trace comparison, redacted report schema test, generated-doc check | Statistical real-world performance |
| G3 — Hardware feasibility | Human records local raw link, contact, sample coverage, quality, safe failure handling | Dated engineering report with negative results included | ADR Accepted, clinical/accessibility efficacy |
| G4 — Experimental release decision | Compare results to ADR-v2-152 thresholds and gate consequences; maintainer decides whether to document a narrow **tested-on** note | Release-note evidence with code revision + OS + model + config | General platform support; safe default-on |
| G5 — Wider validation (later) | ADR-v2-152 sample/phase/uncertainty criteria and research-governance checks | Multi-person evidence with consent where required | Automatically accepted ADR or medical claim |

Do **not** block the pure-code G1/G2 on a physical device. Do **not** claim G3/G4 complete from synthetic CI. A failure at any gate is useful outcome data. New hardware claims stay absent until G3.

## 8. Required changes by PR / owner

### PR A — pure device health and fake-wire tests (automatable, after G0)
- Files: `src/yazses/biosignal/thinkgear.py`, optional `thinkgear_health.py`, `tests/test_biosignal_thinkgear.py` and a dedicated health test.
- Unit-test health states and byte ordering. No CLI, config, action or OS changes.
- Add a short correctness note to `design/architecture.md`; no hand edit to generated ADR/docs index.
- **Done:** TG-01..11 and unchanged parser tests; all base imports work without pyserial.

### PR B — shared safety gate + field-test parity (automatable, after PR A)
- Files: `src/yazses/biosignal/integrity.py` (minimal provenance seam), optional `source_gates.py`, `runner.py`, `cli_impl.py`, `tests/test_biosignal_integrity.py`, `tests/test_biosignal_runner.py` and field-test tests.
- Collapse duplicate guard assembly. No new user-visible command or eager imports.
- **Done:** TG-12..16, same decisions on same synthetic trace, no unintended change to other source kinds, no stuck hold.

### PR C — local diagnostics, evidence rules and user guide (automatable, after PR B)
- Files: `docs/how-to/biosignal-hardware.md`, `docs/how-to/biosignal-switch.md`, `docs/contribute/biosignal-device-driver.md`, tests of JSON privacy/schema and CLI if modified; `CHANGELOG.md` if user-visible.
- Maintain distinction `parser valid` / `serial reachable` / `stream healthy` / `gesture usable` / `supported configuration`. If adding CLI/config, regenerate `scripts/gen-docs.py` outputs and add maintainer review.
- **Done:** TG-17..18; documentation says physical validation pending.

### Physical validation — explicit human dependency (not cloud-executable)
- The owner pairs/wears the hardware and runs preflight/field-test, with costs/safety/consent handled outside the public technical work.
- A contributor may review **aggregate** results only after human decides they are suitable to share.
- **Done:** G3 evidence logged truthfully, model and firmware characterized; otherwise record BLOCKED.

### Review/honest release note (after hardware)
- Document observed success **and** failure, retain experimental off-by-default status; only maintainer can approve any support claim or ADR status change.
- ADR-v2-152 multi-person gate remains an independent task.

## 9. Commands and generated files

~~~sh
uv sync
uv run python -m pytest tests/test_biosignal_thinkgear.py -v
uv run python -m pytest tests/ -v
uv run ruff check src tests scripts
uv run mypy src
# Only if public config/CLI/registry changes were reviewed:
uv run python scripts/gen-docs.py
# When adding/promoting an ADR file into the main ADR index:
uv run python scripts/gen-adr-index.py
~~~

Do not manually modify generated `docs/configuration.md`, `docs/features.md` or `design/adr/README.md`. Do not rerun broken CI repeatedly; follow `.github/CI_POLICY.md`. Add concise negative test summaries to PR rather than claiming code is tested in this research branch.

## 10. Open questions that require observation or explicit decision

- Does the actual hardware expose ThinkGear data through local Linux RFCOMM/TTY, and how does its firmware identify the connection?
- Are `0x02` reports present and fresh during normal use? Does the selected **zero-only** policy make real use possible or suppress all input?
- Can prolonged Bluetooth buffering make apparently healthy samples stale despite host-side arrival checks? What maximum lag is observed?
- How much clean time is needed after re-seat so recovery suppresses artifacts without unbearable friction? Decide only using **separate training runs**, never on scored evaluation data.
- Do contact faults arrive in messages with no raw rows, and does the runner's watchdog cover the resulting no-block interval?
- Is the sensor's ADC scale accurate enough for fixed μV bounds, or is per-device calibration required? Keep nominal scale caveat, do not silently auto-tune.
- Are alternative local transports required for a specific model? Add **separate** reviewed source work rather than violating this adapter's scope.

**Verification note:** This is an implementation contract written from repository inspection and published protocol information. No implementation, tests, hardware run or human study was performed to create this spec.
