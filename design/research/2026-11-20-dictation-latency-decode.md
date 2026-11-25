# Dictation latency, key release → transcript: where the time goes on the decode side

**Date:** 2026-11-20 · **Status:** research note, recommendations for the owner · **Scope:**
the stretch between `recorder.stop()` and the decoder returning text (post-processing and
injection are measured separately). **No default is changed by this note.**

## Question

What does a default install (`faster-whisper`, `base.en`, int8, CPU, `beam_size = 0`,
300 ms lead-in, built-in prompt, speech-presence check on) spend between key release and
transcript, and which of it can be removed without changing a single transcript?

## Method and provenance (ADR-033 fields)

| Field | Value |
|---|---|
| YazSes commit | `8ecfd4aeadcdeea8590754445653854ddc2ae82a` (+ this branch's harness) |
| Harness | `scripts/bench-decode-latency.py` (`cold`, `warm`, `idle`, `predecode`) |
| Engine / model | faster-whisper 1.2.1, ctranslate2 4.8.1, `Systran/faster-whisper-base.en` rev `3d3d5dee26484f91867d81cb899cfcf72b96be6c`, `model.bin` sha256 `2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef` |
| Runtime | Python 3.12.3, numpy 2.4.6, onnxruntime 1.28.0, Linux 7.0.0-43 |
| CPU | Intel Core i7-6500U, 2 cores / 4 threads |
| Corpus | `data/librispeech-sample/jfk.wav` (public domain, 11 s), cut at silences into 2.5 s, 5.0 s and the full 11 s — dictation-length bursts |
| Decoder | `language="en"`, `initial_prompt="The app is called YazSes."`, 300 ms of zeros prepended, faster-whisper defaults otherwise |
| Offline | `local_files_only=True`, `HF_HUB_OFFLINE=1`; nothing fetched |
| Repeats | 15 per cell; warm variants interleaved round-robin; cold arms alternated process by process |
| Load | `os.getloadavg()` recorded per measurement. The machine was shared with other jobs: load 4.6–7.5 during the cold run, 2.7–4.3 during the warm grid, 1.4–1.7 during the idle run |

One fixture, one speaker, read speech. Timing conclusions here are about *where* the time
goes, which is a property of the architecture; they are not a WER result. Where a setting
changed the text, that is reported, and no WER claim is made from one sentence.

A first harness version cut the 5 s clip at 5.5 s, mid-word. `base.en` answered that clip
with a repetition loop ("…ask not what the f***ing f***ing …"), which turned one cell into
a hallucination benchmark. Cutting at silences fixed it; the loop is noted because a
hold released mid-word produces the same input.

## Results

### 1. The encoder is the latency, and it does not scale with the burst

Warm decode, median of 15, interleaved (load median ≈ 3.5):

| Burst | Total | Features | Encoder | Decoder (beam 5) |
|---|---|---|---|---|
| 2.5 s | 1 645 ms (p95 1 912) | 9 ms | 1 279 ms | 322 ms |
| 5.0 s | 1 418 ms (p95 2 171) | 6 ms | 1 118 ms | 325 ms |
| 11 s | 1 678 ms (p95 2 191) | 7 ms | 1 060 ms | 623 ms |

Whisper's encoder always runs on a 30-second window, so a 2.5 s "yes, send it" costs the
same ~1.1 s of encoder as an 11 s sentence. The decoder is the only part that grows with
what was said. Feature extraction (log-mel) is under 10 ms.

### 2. Everything before the decode call is ~12 ms, and it is all Silero

`predecode` mode, 300 interleaved repetitions on a 5 s burst (load 0.7):

| Stage | p50 | p95 |
|---|---|---|
| concatenate PortAudio blocks | 0.09 ms | 0.14 ms |
| three level reads (`np.abs().mean()`) | 0.20 ms | 0.32 ms |
| calibrated energy gate | 0.05 ms | 0.09 ms |
| speech-presence check (Silero, warm) | **11.1 ms** | 13.8 ms |
| 300 ms lead-in concat | 0.04 ms | 0.06 ms |
| prompt merge | 0.01 ms | 0.02 ms |

There is no redundant copy or resample worth removing: the recorder opens the stream at
16 kHz mono float32, so the audio reaches the decoder without resampling, and the copies
are tens of microseconds.

### 3. Cold start: no first-decode penalty worth a warm-up; Silero's first call has one

`cold` mode, 15 fresh processes per arm, alternating (load median 5.6):

| | no warm-up | with warm-up |
|---|---|---|
| model load (local cache) | 1 542 ms (p95 2 600) | 1 548 ms (p95 3 698) |
| warm-up cost | — | **1 856 ms** (p95 4 254) |
| first speech-presence check | **48 ms** (p95 101) | 13 ms (p95 34) |
| later speech-presence check | 13 ms | 13 ms |
| first decode (5 s burst) | 2 207 ms (p95 7 155) | 2 041 ms (p95 7 742) |
| first − mean(2nd, 3rd), paired | +74 ms (IQR −63…+283) | +135 ms (IQR −76…+524) |

The decode warm-up (one bounded decode of 1 s of silence: greedy, temperature 0, ≤ 4
tokens) costs a full encoder pass, because the encoder window is fixed. It did **not**
remove the small first-decode excess: the excess is the same size with or without it, and
both are inside the noise. A warm-up would add ~1.9 s to every start-up, and ~1.1 s to
every idle-unload reload, for no measured benefit. **Not shipped.**

Silero is different: its first call builds the ONNX session (≈ 36 ms paired), and priming
it on silence removes that entirely. **Shipped** as
`audio.speech_presence.prime_detector`, called from `Daemon._build_pipeline` only when the
check will run.

### 4. A resident model does not get slower when idle

`idle` mode, 15 repetitions, a decode after 0 / 10 / 30 s of rest (load median 1.4–1.7):
1 310 / 1 367 / 1 298 ms median. No keep-warm or periodic decode is justified.

### 5. Decoder settings: what is faster, and what it does to the text

Same warm grid as §1 (load median ≈ 3.5); change of median against the baseline, and
whether the text was byte-identical to the baseline on that clip:

| Setting | 2.5 s | 5.0 s | 11 s | Text identical? |
|---|---|---|---|---|
| `beam_size=1` | −26.6 % | −12.5 % | −21.6 % | 2 of 3 (11 s: comma) |
| `beam_size=2` | −20.5 % | −7.0 % | −6.0 % | 2 of 3 (2.5 s: comma) |
| `without_timestamps=True` | −8.1 % | −5.2 % | −4.1 % | 2 of 3 (11 s: "asked"→"ask", which matches the reference) |
| `vad_filter=True` | −13.7 % | +9.0 % | +2.6 % | 0 of 3 |
| no prompt | −7.1 % | −7.0 % | −2.4 % | 0 of 3 |
| long prompt (32 terms) | −2.9 % | +8.3 % | +8.5 % | 0 of 3 |
| no 300 ms lead-in | +0.4 % | −0.4 % | −0.9 % | 0 of 3 (punctuation) |
| `cpu_threads=1` | +17.3 % | +37.0 % | +31.4 % | 3 of 3 |
| `cpu_threads=2` | +2.8 % | +1.0 % | −11.0 % | 3 of 3 |
| `cpu_threads=4` | −12.6 % | +7.4 % | +6.3 % | 3 of 3 |

A second, narrower run (`--only threads2,threads4,beam2,without_timestamps`, 15
repetitions, load median 3.5–3.8) repeated the cells whose sign was unclear:

| Setting | 2.5 s | 5.0 s | 11 s | p95, baseline → setting (2.5 / 5 / 11 s) | Text identical? |
|---|---|---|---|---|---|
| `beam_size=2` | +3.2 % | −6.8 % | −7.0 % | 1 446→1 642 / 1 539→1 416 / 2 068→2 167 | 2 of 3 |
| `without_timestamps=True` | −0.1 % | −5.3 % | −2.2 % | 1 446→1 690 / 1 539→1 769 / 2 068→1 719 | 2 of 3 |
| `cpu_threads=2` | −5.2 % | −11.0 % | −13.2 % | 1 446→1 276 / 1 539→1 458 / 2 068→1 557 | 3 of 3 |
| `cpu_threads=4` | +2.9 % | +0.9 % | +0.4 % | 1 446→1 852 / 1 539→1 668 / 2 068→1 880 | 3 of 3 |

`condition_on_previous_text` was not measured: a burst under 30 s is one window, so there
is no previous text to condition on and the setting cannot act.

Reading it:

* **The beam is the one decode knob with a real saving** (decoder time ≈ halves at beam 1),
  and it changes text. `docs/benchmarks.md` ("The one decode knob that is not the
  model") already settled on 200 + 200 LibriSpeech utterances, paired,
  that `base.en` at **beam 2 is indistinguishable from beam 5** (0.000 points clean,
  0.03 hard) while beam 1 costs 0.38 / 1.10 points.
* **The lead-in costs nothing in time** — the encoder pads to 30 s anyway — but it does
  change punctuation, so removing it is a transcript change, not a free win.
* **Threads: the only transcript-preserving lever, and not settled.** `cpu_threads=0`
  (ctranslate2's default) behaved like 4 in both runs. On this 2-core / 4-thread CPU,
  2 threads — one per physical core — was 5–13 % faster with a lower p95 in all three
  cells of the second run, but +3 / +1 / −11 % in the first. Text was identical at every
  count; 1 thread was 17–37 % slower. One machine, a shared one, and a split result is not
  enough to change what `0` means for every CPU, so it is not changed here.

## Recommendations for the owner (L3: defaults or output change)

1. **Consider `[stt] beam_size` → 2 as the shipped default for `base.en` dictation.**
   Measured here: −6 to −20 % in the first run, +3 to −7 % in the second — a saving of
   roughly 70–160 ms of decoder time per burst, which is small against the fixed encoder.
   Accuracy evidence already in the repository: paired 400-utterance bootstrap, beam 2 =
   beam 5 within ±0.4 points. The text does change on some utterances (one comma in
   three here). Needs an ADR-033-style paired rerun on the pinned corpus before
   adoption; the governor's normal-load beam already follows `[stt] beam_size`.
2. **Consider `without_timestamps=True` for the plain dictation decode** (not
   `transcribe_words`, which needs timestamps). 0 to −8 % across the two runs. It changes segmenting
   and, on 1 of 3 clips, a word (towards the reference). Needs a paired WER run first;
   not recommended on this evidence alone.
3. **The real lever is the fixed 30 s encoder.** ~1.1 s of every burst on this CPU is
   encoder time that does not depend on how long the user spoke. Only an engine whose
   encoder scales with input length (Moonshine is one; the engine decision is #645)
   removes it. Any default-engine decision should weigh release-to-text p95 on *short*
   bursts, which this note shows is dominated by that constant.
4. **Measure `cpu_threads = physical cores` on SMT machines.** If a second and third CPU
   (one with ≥ 4 physical cores) reproduce the 2-thread result here, the candidate rule
   for `cpu_threads = 0` is "physical cores, capped at ctranslate2's 4" — transcript
   identical, so it needs evidence of speed, not of accuracy. Until then a user on a
   2-core laptop can set `[stt] cpu_threads = 2` themselves.
5. **Do not add a decode warm-up** (start-up or idle reload): measured cost ~1.9 s,
   measured benefit indistinguishable from zero.
6. **Leave `pre_speech_padding_ms` alone for latency purposes**: it costs no time; its
   accuracy trade-off is the existing onset study's question, not this one.

## What changed in the code

* `audio/speech_presence.py::prime_detector` and `Daemon._prime_speech_detector`:
  the first dictation after a start no longer pays Silero's ~36 ms session build.
* `scripts/bench-decode-latency.py`: the harness, with tests of its pure parts.

## Not measured

Real microphones and real hold-releases; a second machine; other models (`tiny.en`,
`small.en`) and other engines; memory effect of loading onnxruntime at start (it was
loaded on the first burst anyway); WER of any setting above.
