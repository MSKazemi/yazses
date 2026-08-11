---
id: "eval-yazses-v030"
title: "YazSes v0.3.0 — Evaluation Plan"
type: eval_plan
scenario: yazses-innovation
created_at: 2026-05-14
updated_at: 2026-05-14
confidence: high
---

# YazSes v0.3.0 — Evaluation Plan

## 1. Primary Metrics

One primary metric is defined per capability cluster (cap-001 through cap-005). Each metric has a formal definition, a measurement method, and a pass/fail threshold derived from the PRD NFRs.

### cap-001 — SSH/Remote Voice Forwarding

**Metric:** End-to-end text injection latency over SSH tunnel.

**Formal definition:** `T_inject = t_char_appears_remote − t_hotkey_release`, measured in milliseconds. `t_hotkey_release` is the UNIX timestamp at which the hold-to-talk hotkey `on_hold_end` event fires on the local machine. `t_char_appears_remote` is the timestamp logged by the remote agent immediately after `InjectorBackend.inject(text)` returns on the remote machine.

**Measurement method:** Integration test. Local machine sends a known 10-character string through a containerised SSH tunnel to a remote agent mock. The mock logs timestamps. Median and 99th-percentile latencies are computed over 50 injections. Two network conditions are simulated: LAN (netem 1 ms RTT) and WAN-equivalent (netem 100 ms RTT).

**Pass threshold:**
- Median latency ≤ 500 ms on LAN (NFR-001.1).
- Median latency ≤ 800 ms on WAN (NFR-001.1).
- 99th-percentile ≤ 1000 ms on WAN (graceful bound; no NFR defined).

---

### cap-002 — Streaming Transcription with Real-Time Display and Correction

**Metric A:** Time-to-first-partial (TTFP) — the delay between speech onset and the first stable partial hypothesis appearing in the active window.

**Formal definition:** `TTFP = t_first_inject − t_speech_onset`, where `t_speech_onset` is the sample index at which RMS exceeds `vad_threshold`, converted to wall-clock time, and `t_first_inject` is the timestamp at which `StreamingInjector.inject_partial()` is first called with a non-empty string.

**Measurement method:** Unit test using pre-recorded audio fixtures (3 s clean speech, 16 kHz, float32). The `StreamingEngine` is run with a mock injector that records call timestamps. TTFP is computed across 20 fixture utterances.

**Pass threshold:** Median TTFP ≤ 600 ms (NFR-002.1). [EVIDENCE src-002, src-003]

**Metric B:** Correction operation latency — the time from `commit(final_text)` call to the last keypress event completing in the mock injector.

**Formal definition:** `T_correction = t_last_keypress − t_commit_call`, measured in milliseconds.

**Measurement method:** Unit test. `StreamingInjector.commit()` is called with `_chars_injected = 50` (representative median). Mock injector records event timestamps. Test is run 100 times.

**Pass threshold:** Median T_correction ≤ 200 ms (NFR-002.2). [EVIDENCE src-004]

---

### cap-003 — Code Command Grammar

**Metric:** Command recognition precision and false-positive rate on a labelled phrase set.

**Formal definition (precision):** `P = TP / (TP + FP)`, where TP is the count of command phrases correctly classified to their intended intent, and FP is the count of dictation-only phrases incorrectly classified as a command intent.

**Formal definition (false-positive rate):** `FPR = FP_dictation / N_dictation`, where `N_dictation` = 500 words in dictation corpus segmented into utterance-length phrases.

**Measurement method:** Parametrised pytest fixture. Two test sets (see §3). `grammar.classify()` is called with each phrase. Results compared against ground-truth labels.

**Pass threshold:**
- Precision ≥ 90% on the 50-command phrase set (NFR-003.1).
- Zero false-positive commands on the 500-word dictation corpus (NFR-003.2).

---

### cap-004 — Offline Disfluency Filter

**Metric:** Rule-path runtime per transcript and filter correctness.

**Formal definition (runtime):** Median wall-clock execution time of `DisfluencyFilter.filter_transcript(text, config)` across a 100-transcript corpus.

**Formal definition (correctness):** `F_correct = (transcripts where output matches expected_clean) / 100`. Expected clean output is determined by a human-authored reference for each transcript.

**Measurement method:** Pytest benchmark. Each of the 100 synthetic transcripts is passed through `filter_transcript()`. `time.perf_counter()` wraps each call. Correctness is checked against stored expected outputs.

**Pass threshold:**
- Median runtime ≤ 10 ms per transcript (NFR-004.1). [EVIDENCE src-012]
- Correctness ≥ 95 / 100 on the synthetic corpus (authorial threshold; NFR for correctness is implicit in the PRD's "must not alter proper nouns or code identifiers" constraint).

---

### cap-005 — Accessibility Profile

**Metric:** Enrollment wizard completion time and VAD parameter accuracy.

**Formal definition (wizard time):** `T_enroll = t_wizard_complete − t_wizard_start`, in minutes of user-interactive time (excluding audio recording processing time).

**Formal definition (VAD accuracy):** After enrollment, the derived `vad_threshold` must correctly classify ≥ 95% of voiced frames as speech and ≥ 95% of silent frames as silence on the calibration utterances.

**Measurement method:** End-to-end test using synthetic audio fixtures for 20 calibration utterances. Enrollment wizard is run non-interactively using a fixture driver. `T_enroll` is measured excluding I/O prompts (interactive time proxy). VAD accuracy is computed on a held-out 30-utterance fixture set.

**Pass threshold:**
- `T_enroll` ≤ 10 minutes of user time (NFR-005.1).
- VAD frame classification accuracy ≥ 95% on held-out fixtures.
- All accessibility settings accessible via CLI without GUI (NFR-005.2). [EVIDENCE src-008]

---

## 2. Baseline System

All v0.3.0 metrics are compared against **YazSes v0.2.4** — the current production release.

| Baseline property | Value |
|---|---|
| Version | v0.2.4 |
| ASR backend | faster-whisper 1.2.1, CPU int8, tiny.en |
| Streaming | Disabled (not implemented) |
| SSH remote | Not supported |
| Command grammar | Not implemented |
| Disfluency filter | Not implemented |
| Accessibility options | Model selection only (no enrollment, no evdev_device, no silence/padding config) |
| Hotkey latency | Measured as `t_inject − t_hotkey_release` on local machine |
| WER on clean speech | Measured on LibriSpeech test-clean subset (50 utterances, `tiny.en`) |

The baseline WER and hotkey latency measurements are collected fresh from v0.2.4 before the v0.3.0 implementation begins, and stored in `tests/fixtures/baseline_metrics.json`. These values are used in §5 (Regression Tests).

---

## 3. Test Dataset Construction

### cap-001: SSH Integration Test Corpus

**Construction method:** A Docker Compose environment (`tests/integration/docker/ssh/`) runs a minimal OpenSSH server (Alpine Linux image) in a container. The local test harness:

1. Starts the container with `AllowTcpForwarding yes` in `sshd_config`.
2. Generates a throwaway RSA keypair for the test session.
3. Invokes `yazses remote --host test@localhost --port 2222` via the test harness.
4. Injects 50 text strings of varying length (5, 10, 20, 50, 100 characters) into the tunnel.
5. The remote agent mock inside the container logs receipt timestamps.

**Network simulation:** `tc netem` is used to apply controlled delay: LAN = 1 ms RTT, WAN = 100 ms RTT.

**Dataset size:** 50 injections × 2 network conditions = 100 latency data points.

**Ground truth:** Exact text received by remote agent mock must match text sent by local daemon. Any mismatch is a data-integrity failure (separate from latency).

---

### cap-002: Streaming Latency Test Corpus

**Construction method:** 20 audio fixture files (WAV, 16 kHz, float32, 3–8 s duration) are selected from LibriSpeech `test-clean` (first 20 utterances of speaker 1089). These fixtures are committed to `tests/fixtures/streaming/`.

- `t_speech_onset` for each fixture is annotated by a one-time script that applies the default RMS VAD to identify the first voiced frame. Annotations are stored in `tests/fixtures/streaming/onsets.json`.
- The `StreamingEngine` runs against each fixture with a mock injector. Partial hypothesis timestamps and character counts are recorded.
- `TTFP` and `T_correction` are computed from logged timestamps.

**Coverage:** Fixtures include fast speech (6+ words/s), slow speech (2 words/s), and utterances with initial pause (simulating delayed phonation onset). [EVIDENCE src-002]

---

### cap-003: Command Recognition Test Corpus

**Construction method:** Two independent phrase sets, authored manually and stored in `tests/fixtures/commands/`:

**Set A — command phrases (50 items):** One phrase per unique action in FR-003.3's command table, plus variants covering ordinal words ("one"/"1", "two"/"2", "three"/"3") and optional tokens ("undo" / "undo that" / "undo 3 times"). Each phrase is labelled with its expected `IntentType` and `action`.

**Set B — dictation corpus (500 words):** A 500-word passage of natural English prose (first 500 words of a public-domain text), segmented into 25 utterance-length phrases of ~20 words each. No intentional command phrases. Expected classification for every phrase: `IntentType.DICTATE`.

**Ground truth:** Authored labels are considered ground truth. No ASR inference is involved; `grammar.classify()` receives text strings directly.

---

### cap-004: Disfluency Filter Corpus

**Construction method:** 100 synthetic transcripts authored in `tests/fixtures/disfluency/corpus.json`. Each entry has three fields: `input` (raw transcript with known fillers/repetitions/triggers), `expected` (human-authored clean output), and `rule_path` (which of the three filter rules — filler removal, repetition dedup, self-correction — should fire).

Distribution across rule paths:
- 40 transcripts: filler-word removal only (rules A).
- 30 transcripts: repetition deduplication (rule B).
- 20 transcripts: self-correction trigger (rule C).
- 10 transcripts: combined (rules A+B or A+C).

Each transcript also includes a "no-change" control section: a proper noun, a code identifier (e.g., `FasterWhisperEngine`), and a quoted string. These must be preserved verbatim to validate NFR-004.2. [EVIDENCE src-012]

---

### cap-005: Accommodation Setting Test Corpus

**Construction method:** Five test scenarios in `tests/fixtures/accessibility/`:

1. **Footpedal evdev simulation:** A mock evdev device node is injected into the Linux hotkey backend via dependency injection (replacing the real `evdev.InputDevice` constructor with a mock that replays a hold-press event sequence). The test confirms the daemon enters `RECORDING` state on the mock hold event.

2. **Silence threshold test:** Audio fixture with 600 ms of trailing silence. The default `min_silence_ms = 500` must stop recording within 600±50 ms of the silence onset. An extended `min_silence_ms = 1500` must continue recording through the 600 ms silence.

3. **Pre-speech padding test:** Audio fixture with 300 ms of silence followed by 2 s of speech. With `pre_speech_padding_ms = 400`, the audio array passed to the STT engine must begin 400 ms before the VAD-detected speech onset.

4. **Model selection test:** ASR engine initialisation is mocked. The test confirms that setting `stt.model = "base.en"` in config causes `WhisperModel("base.en", ...)` to be called with the correct model identifier.

5. **Enrollment wizard fixture test:** 20 synthetic calibration utterances (WAV files) with known RMS statistics. The enrollment wizard must produce a `vad_threshold` within ±15% of the analytically computed optimal threshold. [EVIDENCE src-008]

---

## 4. Pass/Fail Thresholds

| Metric ID | Capability | Metric | Threshold | NFR Source |
|---|---|---|---|---|
| M-001-LAN | cap-001 | SSH injection latency, LAN | ≤ 500 ms median | NFR-001.1 |
| M-001-WAN | cap-001 | SSH injection latency, WAN | ≤ 800 ms median | NFR-001.1 |
| M-001-INT | cap-001 | Data integrity through tunnel | 100% exact match | FR-001.3 |
| M-002-TTFP | cap-002 | Time-to-first-partial | ≤ 600 ms median | NFR-002.1 |
| M-002-COR | cap-002 | Correction operation latency | ≤ 200 ms median | NFR-002.2 |
| M-002-CANCEL | cap-002 | No partial text after cancel | 0 chars remaining | NFR-002.3 |
| M-003-PREC | cap-003 | Command recognition precision | ≥ 90% on 50-item set | NFR-003.1 |
| M-003-FPR | cap-003 | False-positive command rate | 0 on 500-word corpus | NFR-003.2 |
| M-003-RT | cap-003 | Grammar classifier runtime | ≤ 5 ms per classify() call | FR-003.2 |
| M-004-RT | cap-004 | Disfluency filter runtime | ≤ 10 ms per transcript | NFR-004.1 |
| M-004-CORR | cap-004 | Filter correctness | ≥ 95 / 100 transcripts | NFR-004.2 |
| M-004-PNID | cap-004 | Proper noun / identifier preservation | 100% unmodified | NFR-004.2 |
| M-005-ENR | cap-005 | Enrollment wizard time | ≤ 10 minutes user time | NFR-005.1 |
| M-005-VAD | cap-005 | VAD accuracy post-enrollment | ≥ 95% frame classification | derived from cap-005 |
| M-005-CLI | cap-005 | Accessibility settings via CLI | All settings reachable | NFR-005.2 |

---

## 5. Regression Tests

The following baseline measurements from v0.2.4 must not degrade in v0.3.0.

### R-001: WER on Clean Speech

**Measurement:** Word Error Rate of `FasterWhisperEngine` on the first 50 utterances of LibriSpeech `test-clean` with `tiny.en` model, CPU int8.

**Baseline value:** Stored in `tests/fixtures/baseline_metrics.json` as `wer_librispeech_test_clean_tiny_en`.

**Pass threshold:** v0.3.0 WER ≤ baseline WER + 0.5 percentage points. A tolerance of 0.5 pp accounts for minor environment differences across test runs. [EVIDENCE src-001, src-009]

**Rationale:** cap-002 (streaming), cap-004 (disfluency filter), and cap-005 (VAD changes) all touch the audio-to-text pipeline. None should alter the core Whisper model output. If WER increases, it indicates an unintended modification to the STT path.

### R-002: Hotkey Detection Latency

**Measurement:** Time from hardware key event to `daemon._on_hold_start()` being called, measured in the Linux evdev path using a synthetic evdev input fixture.

**Baseline value:** Stored in `tests/fixtures/baseline_metrics.json` as `hotkey_latency_ms_p99`.

**Pass threshold:** v0.3.0 99th-percentile hotkey latency ≤ baseline + 10 ms. The 10 ms allowance accounts for timer jitter in CI.

**Rationale:** cap-005 adds the `evdev_device` config path to the Linux hotkey backend. The default path must not be slower.

### R-003: Config Load and Schema Validation

**Measurement:** `Config.load()` must succeed on a minimal v0.2.4-era `config.toml` (without any v0.3.0 keys) without raising an exception, and must produce safe defaults for all new v0.3.0 config fields.

**Pass threshold:** Zero exceptions; all new fields have expected default values.

**Rationale:** The v0.3.0 config schema adds 5 new dataclasses with default values. Existing user configs must remain valid (no breaking schema changes).

### R-004: IPC Protocol Backward Compatibility

**Measurement:** The existing `test_ipc_protocol.py` suite (covering JSON-RPC 2.0 framing, `status`, `shutdown`, and `inject` methods) must pass without modification.

**Pass threshold:** All existing IPC tests pass. No new required fields in existing RPC method schemas.

---

## 6. Test Tooling

### pytest Structure

```
tests/
  __init__.py
  # Existing tests (must continue passing — R-003, R-004)
  test_auto_inject.py
  test_cleaner.py
  test_config.py
  test_hold_detector.py
  test_ipc_protocol.py
  test_platform_factory.py
  # New v0.3.0 unit tests
  test_disfluency_filter.py       # cap-004: 100-corpus parametrised test
  test_grammar_classifier.py      # cap-003: 50+500-phrase parametrised test
  test_streaming_engine.py        # cap-002: TTFP and correction latency
  test_streaming_injector.py      # cap-002: _chars_injected state machine
  test_accessibility_enroll.py    # cap-005: enrollment wizard with fixtures
  test_vad_calibrated.py          # cap-005: threshold derivation
  test_audio_padding.py           # cap-005: pre-speech ring buffer
  test_remote_agent.py            # cap-001: agent JSON-RPC mock
  # Integration tests
  integration/
    test_ssh_tunnel.py            # cap-001: Docker Compose SSH tunnel
```

### Key Test Fixtures

```
tests/fixtures/
  streaming/
    *.wav                         # 20 LibriSpeech utterances
    onsets.json                   # speech onset annotations
  commands/
    command_phrases.json          # 50 labelled command phrases
    dictation_corpus.txt          # 500-word prose passage
  disfluency/
    corpus.json                   # 100 synthetic transcripts with expected output
  accessibility/
    calibration_utterances/       # 20 synthetic calibration WAV files
    rms_stats.json                # expected RMS statistics for fixture utterances
  baseline_metrics.json           # v0.2.4 baseline WER and latency values
```

### Fixture Design Principles

- All audio fixtures are committed as WAV files (16 kHz, 16-bit, mono) to keep the test suite self-contained.
- No real microphone, no `sounddevice` calls in unit tests. The `AudioRecorder` is replaced by a fixture-reading mock via `pytest-mock`.
- No real SSH server in unit tests. The `RemoteForwarder` and `remote/agent.py` are tested with mock socket connections.
- Integration tests (Docker SSH) are gated behind the `--integration` pytest marker and skipped in standard CI runs to avoid Docker-in-Docker complexity on Windows and macOS CI runners.

### CI Configuration

The existing `.github/workflows/test.yml` runs `uv run pytest tests/ -v` on Python 3.11 and 3.12 across Linux, macOS, and Windows. For v0.3.0, the following changes are made:

1. A `pytest.ini_options.markers` entry is added for `integration` to suppress the SSH Docker test on non-Linux CI runners.
2. The Linux CI job gains a step to build the Docker SSH container before running integration tests: `docker compose -f tests/integration/docker/docker-compose.yml up -d`.
3. `pytest-benchmark` is added to the dev dependency group for the runtime measurements in M-003-RT and M-004-RT.

```toml
# pyproject.toml additions
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-mock>=3.14",
    "pytest-benchmark>=5.1",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: requires Docker and external services",
]
```
