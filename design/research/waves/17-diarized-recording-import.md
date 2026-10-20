# Wave O — diarized recording import (offline file transcription + speaker attribution) — SoA research

**Date:** 2026-07-04 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-125](../../adr/adr-v2-125-diarized-recording-import.md) (Diarized
Recording Import, shipped as `yazses transcribe`) and
[adr-v2-126](../../adr/adr-v2-126-cloud-escalation.md) (Cloud Escalation, design-only, deferred).
Builds on [adr-v2-083](../../adr/adr-v2-083-recording-import.md),
[adr-v2-074](../../adr/adr-v2-074-diarized-conversation-capture.md), and
[adr-v2-019](../../adr/adr-v2-019-meeting-scribe.md). See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Feature status should be checked against `yazses features` and the linked ADRs, not this note.

**Method:** five parallel SoA scout passes (2025-2026 model cards, arXiv eess.AS/cs.CL, library
docs/PyPI, provider pricing pages, general market survey) plus direct source-file verification,
run against the existing codebase (faster-whisper int8, the `voiceprint/` ECAPA infra, the pure
cores of ADR-v2-019/074/083). ~70 primary-source lookups. Every load-bearing claim is cited with
a URL and a confidence mark: **[H]** primary-source verified · **[M]** multi-secondary consistent
· **[L]** single source / estimate.

**Feature in one line:** `yazses transcribe <audio-file>` — decode any common audio format offline,
transcribe on CPU, diarize into speaker turns, tag each utterance (`Speaker 1:` / names), and write a
sidecar text file next to the input. Off by default, on-device, no cloud.

---

## 0. Reconciliation with existing ADRs (this is not greenfield)

Three accepted-but-partially-built ADRs already touch this space; the pure cores exist and are reused:

| ADR | Section | What was built | What this feature adds |
|---|---|---|---|
| **[adr-v2-083](../../adr/adr-v2-083-recording-import.md) Recording Import** | `[recimport]` | `recimport/subtitles.py` (`merge_word_timestamps`, `write_srt/vtt`, `format_timestamp`) | the **CLI command**, **file audio decode**, and **diarization** (083 was plain transcription only) |
| **[adr-v2-074](../../adr/adr-v2-074-diarized-conversation-capture.md) Diarized Conversation Capture** | `[diarize]` | `diarize/labels.py` (`SpeakerLabelMap`, `parse_rename`, `render_attributed_markdown`) | uses these pure labellers on the **pre-recorded file** path (074 is live) |
| **[adr-v2-019](../../adr/adr-v2-019-meeting-scribe.md) Meeting Scribe** | `[scribe]` | `scribe/diarize.py` (`label_speakers`, `merge_turns`, `format_transcript`) | reuses `format_transcript`/`merge_turns` for plain-text rendering (019 is live) |

**So the genuinely new engineering = a diarizer backend + file decode + word↔turn alignment + the CLI,
wiring three existing pure cores together.** ADR-083 anchored on NVIDIA Parakeet-TDT-0.6B-v2; §2 below
re-evaluates that against the incumbent faster-whisper.

---

## 1. Diarization engine — the central decision

**Constraint set (from the project's own invariants):** no PyTorch, no GPU, no Hugging-Face token
gating, small download, `pip`-installable, offline. Ranked against those bars:

| Rank | Engine | torch-free | GPU-free | token-free | size | pip | streaming | best DER (dataset) | license | verdict |
|---|---|:--:|:--:|:--:|---|:--:|:--:|---|---|---|
| **1** | **sherpa-onnx** | ✅ | ✅ | ✅ | ~15–32 MB | ✅ | ❌ whole-file | ~3.1-tier, **unpublished** | Apache-2.0 | **only engine meeting all bars — ship it** |
| 2 | pyannote community-1 | ❌ | ⚠️ slow | ❌ gated | 100s MB | ✅ | ❌ | **11.2** VoxConverse / 17.0 AMI | CC-BY-4.0 | top open accuracy; token+torch block it |
| 3 | DiariZen (WavLM+Conformer) | ❌ | ⚠️ GPU-rec | ⚠️ | large | ⚠️ | ❌ | **13.9** AMI-SDM | open | best open accuracy, worst footprint |
| 4 | diart | ❌ | ✅ | ❌ gated | large | ✅ | ✅ | pyannote-tier | MIT | only if streaming were needed |
| 5 | NeMo (Streaming) Sortformer | ❌ | ❌ GPU-bound | ⚠️ | large | ❌ git | ✅ | 6.57 CALLHOME-2spk | CC-BY-4.0 | GPU tool; reject for CPU |

**Decision: sherpa-onnx is the default (and only shipped) diarizer.** [H]

- Pipeline: **pyannote segmentation-3.0 (ONNX)** → **speaker-embedding extractor (3D-Speaker ERes2Net /
  NeMo TitaNet / wespeaker, ONNX)** → **fast agglomerative clustering**. `pip install sherpa-onnx`,
  prebuilt wheels (Linux x86-64 wheel ≈4.4 MB), **ONNX Runtime bundled — no `onnxruntime`, no `torch`**.
  Models come from **GitHub Releases as tarballs (no HF gate)**. Engine Apache-2.0; seg-3.0 model MIT;
  3D-Speaker embedders Apache-2.0. [H]
  Sources: [PyPI](https://pypi.org/project/sherpa-onnx/) ·
  [Python example](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-speaker-diarization.py) ·
  [docs](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html) ·
  [seg-3.0 ONNX size](https://huggingface.co/onnx-community/pyannote-segmentation-3.0)
- **API shape:** `OfflineSpeakerDiarizationConfig(segmentation=…pyannote(model=…), embedding=…(model=…),
  clustering=FastClusteringConfig(num_clusters=-1, threshold=0.5))` → `.process(samples16k).sort_by_start_time()`
  → segments `(start, end, speaker)`. `num_clusters=-1` ⇒ **auto speaker count** (via `threshold`);
  positive `num_speakers=N` ⇒ **fixed**. Input must be 16 kHz mono. [H]
- **Recommended small model combo:** seg-3.0 (~6 MB) + ERes2Net-base int8 (~8 MB) ≈ **~15 MB**. [H seg / M embedder]
- **Honest gaps to design around** [M/L]: sherpa publishes **no DER and no CPU real-time factor**; it
  reuses seg-3.0 but is **not bit-identical** to pyannote's own pipeline (documented result drift,
  [issue #1708](https://github.com/k2-fsa/sherpa-onnx/issues/1708)). ⇒ **measure accuracy and speed on
  real clips before quoting numbers.** It is whole-file (offline) only — fine for a batch file command.

**pyannote / NeMo remain pluggable-but-dormant backend *names*** (a factory returns `None` unless the
extra is present), mirroring `voiceprint/factory.py`. pyannote is the documented "max-accuracy, accepts
the torch+token cost" opt-in; NeMo/Sortformer is GPU-only and stays a name only.

---

## 2. STT backend for the batch path — reuse faster-whisper, don't chase Parakeet

ADR-083's anchor, **Parakeet-TDT-0.6B-v2**, advertises **RTFx≈3386 — but that is a GPU batch-128
number**; the model card targets "NVIDIA GPU-accelerated systems" and documents no CPU path. [H]
([model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2)) A **community ONNX int8 export**
(`onnx-asr`, no NeMo/torch) does run CPU-only at **~18–30× real-time**, CC-BY-4.0 — genuinely strong,
but the numbers come from single community repos, not audited benchmarks. [L/M]
([istupakov ONNX](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx))

**Decision: default = reuse the existing faster-whisper (CTranslate2 int8) engine** — same weights and
accuracy profile as live dictation, one model to manage, fastest mainstream CPU stack. [H] Enhancements:

- **Turn on `BatchedInferencePipeline` for the batch path** — VAD-chunks voiced regions into ~30 s
  windows and batches them; **~2.6× CPU speedup on long files** (14.6× vs 5.6× RT, 16-thread). [H GPU / M CPU]
  ([MobiusML batched blog](https://mobiusml.github.io/batched_whisper_blog/))
- **Offer `large-v3-turbo` as the accuracy option** — ~8× faster decode than large-v3 at ~same English
  WER; best quality-per-CPU-second in the Whisper family. [H]
- **Parakeet = optional extra, later**, via the ONNX/`onnx-asr` path only (never `nemo_toolkit`),
  dependency-isolated like the v2 cognitive layer. Not this wave.

**Realistic CPU throughput (int8, single-file; 4-core is the weak spot)** [L/M]:

| Model | CPU RTF | 1 h audio → time |
|---|---|---|
| base.en (int8) | ~10–20× | ~3–6 min |
| **small.en (int8)** — current default | ~6–10× | **~6–10 min** |
| large-v3-turbo (int8) | ~8–15× | ~4–8 min |
| large-v3 (int8) | ~2–4× | ~15–30 min |
| small.en + batched | ×~1.5–2.6 faster | ~4–7 min |

Memory stays **flat regardless of file length** if chunks are streamed (only ~30 s in the decoder
window; a 1 h 16 kHz mono file is ~115 MB raw). [M]

---

## 3. Audio decoding — zero new dependency (the big simplifier)

**`faster_whisper.decode_audio(path_or_fileobj, sampling_rate=16000)` already does everything.** [H]
It uses **PyAV (`av`)**, which bundles the FFmpeg libraries in its own wheel (no system ffmpeg, no
subprocess), decodes essentially every FFmpeg format, downmixes to mono, resamples to 16 kHz via
`av.audio.resampler.AudioResampler`, and returns float32. PyAV is already a transitive dependency of
faster-whisper, which the project already ships ⇒ **marginal cost of full-format coverage = zero new
deps.** ([faster_whisper/audio.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/audio.py))

Format coverage (primary path = PyAV/`decode_audio`):

| Format | PyAV / `decode_audio` | ffmpeg-CLI fallback | soundfile 0.14 |
|---|:--:|:--:|:--:|
| wav / flac / ogg | ✅ | ✅ | ✅ |
| mp3 | ✅ | ✅ | ✅ (0.11+) |
| **m4a / aac / mp4-audio** | ✅ | ✅ | ❌ |
| opus | ✅ | ✅ | ⚠️ fragile |

**Decode strategy:** (1) primary `faster_whisper.decode_audio` (PyAV, all formats); (2) optional
`ffmpeg`-CLI subprocess fallback (`ffmpeg -i in -f f32le -ac 1 -ar 16000 -`) **only if `shutil.which
("ffmpeg")`** — rescues the rare files where PyAV's decode loop stalls
([#988](https://github.com/SYSTRAN/faster-whisper/issues/988)). No torchaudio/librosa dependency added.
If a future minimal path decodes WAV via soundfile, pair it with **`soxr`** for resampling (bundles
libsoxr, numpy-native, the same SRC librosa uses under the hood —
[python-soxr](https://github.com/dofuuz/python-soxr)). Not needed for the PyAV path (it resamples itself).

---

## 4. Word-timestamp ↔ speaker-turn alignment — pure numpy, mirrors WhisperX

WhisperX's `assign_word_speakers` is a **max-overlap interval assignment**, reproducible in pure numpy
with no torch: [H] ([whisperX/diarize.py](https://github.com/m-bain/whisperX))

1. **Assign each word to the max-overlap turn.** For word `w` and each turn `t`, overlap
   `= max(0, min(w.end,t.end) − max(w.start,t.start))`; **sum overlap per speaker** (a word can straddle
   two same-speaker turns), pick the argmax speaker. If a word overlaps no turn → `fill_nearest`:
   nearest turn by midpoint (cap the distance, else leave `None`).
2. **Merge consecutive same-speaker words into utterances**, breaking on speaker change or a silence gap
   `> MAX_GAP` (~1.0 s). Utterance `start/end` = first/last word times; `text = " ".join(words)`.

Vectorize overlap with numpy broadcasting; use `searchsorted` on sorted turn-starts to get WhisperX's
interval-tree speedup ([#1335, 228×](https://github.com/m-bain/whisperX/issues/1335)) without a tree lib.

**Edge cases to bake in** [M]: *backchannel guard* (a <0.3 s word fully inside one turn shouldn't be
stolen by `fill_nearest` — only nearest-fill on true zero overlap); *straddling* (sum-per-speaker before
argmax); *overlapped speech* (minority speaker is dropped — document it; optionally flag `overlap=True`);
*deterministic tie-break* (earliest-start speaker) for stable output; *timestamp-less punctuation words*
inherit the previous word's speaker.

**Word-timestamp quality caveat** [H]: faster-whisper word timestamps come from DTW over cross-attention
and **drift ~100–400 ms** (first word after long silence can be seconds off;
[#125](https://github.com/guillaumekln/faster-whisper/issues/125),
[#294](https://github.com/guillaumekln/faster-whisper/issues/294)). That drift is on the order of turn
boundaries, so assignment degrades on rapid turn-taking. Good enough for turns ≥1–2 s with the edge-case
rules; **forced alignment** (wav2vec2 / ctc-forced-aligner → <100 ms) is the fix but needs torch ⇒ ship
it later as an **opt-in heavy extra**, not the default.

---

## 5. Speaker naming from enrolled voiceprints — reuse `voiceprint/`, gate hard

Method (standard): per cluster, **mean-centroid ECAPA embedding** over all its segments → cosine-match
against enrolled references → assign a name only if it clears an open-set threshold, else keep the
anonymous label. [H] ([arXiv 2406.17124](https://arxiv.org/pdf/2406.17124))

**Recommended defaults, with evidence:**

| Parameter | Default | Basis |
|---|---|---|
| cluster representation | mean centroid over all cluster segments | standard [H] |
| **naming cosine-similarity threshold** | **0.50** (reject-biased, open-set) | above ECAPA's EER point (~0.25–0.35; [SpeechBrain ships 0.25](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)) because a wrong name costs more than "unknown"; matches the project's existing Cocktail-Filter `target_threshold=0.5` [M] |
| **min aggregated speech to name a cluster** | **≥ 3 s** of that cluster's total speech | ERes2NetV2 EER 0.61%→0.98%→1.48% at full→3 s→2 s; sharp degradation below 3 s ([arXiv 2406.02167](https://arxiv.org/html/2406.02167v1)) — directly addresses the known sub-second ECAPA failure the project had already documented [H] |
| enrollment reference length | ≥ 20 s/person (the project already uses `enroll_seconds=25.0`) | robust single-enrollment embedding from ~20 s [H] |
| open-set rule | accept name iff `rank==1` AND `sim ≥ θ`, else "Speaker N" | canonical open-set decision ([arXiv 2407.11510](https://arxiv.org/html/2407.11510v1)) [H] |
| unknown handling | always anonymous fallback; **never auto-enroll** | biometric-consent best practice [H] |

Keep the **cosine-similarity** sign convention consistent (SpeechBrain uses similarity; pyannote's 0.715
is *distance* = 1−sim). Reuses `voiceprint/embedding.py::cosine_similarity`, `voiceprint/factory.py`,
`voiceprint/profiles.py`, and the encrypted `voiceprint/store.py`.

---

## 6. Privacy / consent — the honest boundary (ties to ADR-011 / ADR-012)

**Speaker embeddings are biometric data** (GDPR Art. 9 special category; Illinois BIPA names
"voiceprint" explicitly, with a private right of action; there have been 2026 class actions against
cloud transcription vendors over exactly this). [H] Zero-telemetry ([adr-011](../../adr/adr-011.md))
kills the *transmission* risk but **not the *possession* risk** — the gap to close is local
persistence + auto-enrollment.
([reference survey of the legal landscape](https://basilai.app/articles/2026-03-15-speaker-diarization-privacy-risks-who-gets-identified-in-cloud-transcription.html))

**Policy the feature adopts:**
1. **Diarization is transient by default** — a file yields "Speaker A/B/C" labels for that transcript
   only; **no embedding is persisted** unless the user has explicitly enrolled someone.
2. **Naming is opt-in and consent-gated** — auto-naming matches ONLY against voiceprints the user
   deliberately enrolled; it never creates a profile from a recording.
3. **Unknown → anonymous, always** (no enrolled match ≥ θ, or cluster < 3 s) → "Speaker N"; never guessed.
4. **Everything on-device**, embeddings in the existing encrypted corpus; never transmitted.
5. **Ship a consent notice** (first-run / enable-time / docs), stating voiceprints are biometric data,
   that the user is responsible for recording-consent law (all-party-consent US states; EU/GDPR
   informed consent + purpose limitation), and to only enroll a voice with that person's consent.
   Surface the existing corpus `forget`/`destroy` retention controls. *(Reasoned guidance, not legal
   advice — wording should get a legal review before release.)*

**Responsibility split:** the **user is the data controller** (they chose to record/provide the file —
the app is a local instrument, like a tape recorder); the **app's duty** is to not make it worse than a
tape recorder (no silent third-party biometric profiles), to inform, to stay on-device, and to give easy
delete controls. [H legal landscape / M the split]

---

## 7. Cloud escalation (design-only, deferred — see adr-v2-126)

Optional future path: a user pastes an API key to boost quality; audio would leave the machine, so it
would be **off by default, opt-in per invocation, with a one-time consent prompt naming the destination
host**, never touching the encrypted corpus. Provider-pluggable adapter interface (`diarize`,
`word_timestamps`, `languages`, `upload`). A neutral market survey of what existed at the time, for
scoping purposes only — none of this is used by the project, which remains offline by default:

| Provider | Diarize | Word ts | ~$/audio-hr | On-prem | Note |
|---|:--:|:--:|---|:--:|---|
| Deepgram Nova-3 | ✅ | ✅ | ~0.26 (+0.12 diar) | ✅ self-host | cheap, native, has an on-prem option |
| AssemblyAI | ✅ | ✅ | ~0.15 (+0.02 diar) | ❌ | cheapest base, 99 langs, simple async API |
| OpenAI gpt-4o-transcribe-diarize | ✅ | ❌ segment-only | ~token-billed | ❌ | convenience for an existing API key; no word ts |
| A disconnected-container offering (e.g. Azure Speech) | ✅ | ✅ | ~0.62-eq | ✅ air-gapped | the only genuinely offline/air-gapped licensed option surveyed; not used by this project |
| ElevenLabs Scribe / Google Chirp | ✅ | ✅ | ~0.22 / ~0.24 | ❌ | deferred at the time (realtime Scribe drops diarization; Chirp diarization pricing undocumented) |

This section is a market survey for a deferred, design-only ADR — see
[adr-v2-126](../../adr/adr-v2-126-cloud-escalation.md) for the actual (unimplemented) scope decision.

---

## 8. Competitive UX — conventions worth adopting

Drawn from a survey of comparable local/offline transcription tools at the time (WhisperX, MacWhisper,
noScribe, Vibe, Reverb, whisper.cpp, and others): [M]

- **Sidecar naming:** `<input-stem>.<ext>` written next to the source; `--output-dir` to redirect. Default `txt`.
- **Speaker tags:** human-friendly **`Speaker 1:`** in txt/md; raw **`SPEAKER_00`** in json for tooling.
  **Never ship a txt path that silently drops speaker labels** — a documented bug in at least one
  comparable tool ([WhisperX #801](https://github.com/m-bain/whisperX/issues/801)).
- **JSON is the lossless canonical** (word-level timestamps + per-word speaker); srt/vtt are derivations.
- **CLI flags worth copying:** `--diarize` (off by default), `--speakers N` / `--min-speakers` /
  `--max-speakers`, `--rename SPEAKER_00=Alice`, `--model`, `--format txt,srt,vtt,json,md`, progress bar
  over audio duration. Voiceprint auto-naming (§5) was identified as a real differentiator versus tools
  surveyed at the time.

---

## 9. Open items the design had to carry honestly

- **Unmeasured:** sherpa-onnx DER + CPU RTF; Parakeet CPU throughput (single-repo numbers). Benchmark
  before quoting; feature ships off by default so this was safe to defer.
- **Word-timestamp drift** (100–400 ms) limits turn-boundary precision on rapid exchanges → forced
  alignment is a deferred opt-in extra.
- **Overlapped speech:** minority speaker dropped by max-overlap assignment → documented limitation.
- **First-run model fetch:** sherpa seg + embedder tarballs (~15 MB) must download once → mirror the STT
  model-download UX; provide a `--download-models` affordance and a clear offline error.
- **Consent notice wording** needed legal review before release.

---

### Confidence summary
sherpa-onnx as the only-fit CPU diarizer, PyAV/`decode_audio` zero-dep decoding, the pure max-overlap
alignment, the ≥3 s / 0.50 naming gates, and the biometric-consent legal landscape were all **High**
confidence (primary sources) at the time. CPU throughput tables, the batched-pipeline CPU multiplier,
Parakeet CPU numbers, and the specific 0.50 naming threshold were **Medium/Low** — flagged for
on-hardware measurement, which the shipped feature ([adr-v2-125](../../adr/adr-v2-125-diarized-recording-import.md))
carried out.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
