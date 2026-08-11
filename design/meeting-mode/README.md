# Meeting Mode — design & state-of-the-art

**Status:** design (2026-07-10) · private dev doc
**Decisions:** [ADR-v2-127](../adr/adr-v2-127-live-meeting-mode.md) (live meeting mode + hybrid diarization),
[ADR-v2-128](../adr/adr-v2-128-meeting-minutes-generation.md) (on-device minutes)
**Plan:** an internal planning note
**Full SoA study:** [`soa-report.html`](./soa-report.html) (57 cited primary sources; also a private
claude.ai artifact)

---

## 1. The problem

Hold-to-talk dictation cannot cover a one-hour meeting — you can't hold a key for an hour, and
one person holding a key can't capture several people talking. The ask: **press start once, let it
run, have it work out how many distinct people are speaking (without being told the count), label
each of them, and produce notes at the end.** "Online dictation, not just recording" — the user
wants to *see the transcript forming live*, not just get a recording.

This is not a greenfield feature. YazSes already ships almost every core it needs (see §5).

## 2. How do you actually tell speakers apart? (the core question)

**Neural speaker embeddings + clustering — not voice pitch/frequency.** This is settled science, and
it matters because the intuitive answer ("detect each person's voice frequency") is wrong:

- A single speaker's fundamental frequency (F0/pitch) varies enormously with intonation, emphasis and
  emotion — one documented case swings **140 Hz → 228 Hz** within one speaker — and different speakers'
  ranges overlap heavily. F0 alone is unreliable for identification.
  ([ResearchGate — the problem of F0 and real-life speaker ID](https://www.researchgate.net/publication/276914683_The_problem_of_F0_and_real-life_speaker_identification_a_case_study),
  [Oxford Wave Research x-vectors vs F0](https://oxfordwaveresearch.com/wp-content/uploads/2020/02/IAFPA19_xvectors_Kelly_et_al_presentation.pdf))
- The modern pipeline instead turns each short speech segment into a fixed-length **speaker embedding**
  (a d-vector / x-vector / ECAPA-TDNN vector) that captures voice *identity* (vocal-tract + habitual
  articulation), then **clusters** those vectors — segments in the same cluster are the same person.
  Distance is cosine similarity in embedding space, not Hz. (Foundational: d-vector
  [1710.10467](https://arxiv.org/abs/1710.10467); ECAPA-TDNN
  [speechbrain/spkrec-ecapa-voxceleb](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb), 0.8% EER.)

So "detect the number of people by voice" = **embed every segment → cluster → count the clusters.**
The number of speakers is *discovered* as the number of clusters; you do not have to know it up front.

## 3. Online vs offline diarization — and why we go hybrid

| | Offline (batch) clustering | Online (streaming) diarization |
|---|---|---|
| When | Needs the whole recording | Labels in real time |
| Accuracy | High — global view, best count estimate | Lower — irrevocable early labels, re-clustering churn |
| Unknown count | Yes (eigengap / threshold picks *k*) | Harder; most open systems cap speakers |
| On-device/CPU | Proven (sherpa-onnx, ~30 s for 45 min) | Immature or GPU-first |
| Open + ungated | **sherpa-onnx: Apache-2.0, no HF token** | diart needs gated pyannote; NeMo Sortformer GPU-first |

**Decision: hybrid.** Stream the *transcript* live (so the user watches it form — "online dictation"),
but run the accurate **diarization as a batch post-pass when the meeting stops.** Rationale:

1. **Real-time diarization is a downgrade, not an upgrade.** Live systems must commit a speaker label
   before they've heard enough to be sure, then thrash when a later utterance reveals the guess was
   wrong. A batch pass over the finished recording sees every speaker's full range at once.
2. **The only mature open streamer drags in gated models.** [diart](https://github.com/juanmc2005/diart)
   is real and good, but depends on [pyannote](https://huggingface.co/pyannote/speaker-diarization-3.1)
   segmentation/embedding weights behind a **Hugging Face token gate** — a non-starter for a
   ship-to-users offline app. [NVIDIA Streaming Sortformer](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2)
   is CC-BY-4.0 but **GPU-first and hard-capped at 4 speakers**; the non-streaming
   [Sortformer v1](https://huggingface.co/nvidia/diar_sortformer_4spk-v1) and
   [DiariZen](https://github.com/BUTSpeechFIT/DiariZen) weights are **CC-BY-NC — un-shippable.**
3. **We already ship the batch engine.** `recimport/diarizer.py::SherpaDiarizer` (ADR-v2-125) does
   exactly this on CPU with ungated ONNX models. Meeting mode reuses it verbatim.
4. **The proven local pattern is hybrid.** [OpenWhispr's local diarization](https://openwhispr.com/blog/local-speaker-diarization)
   and [ownscribe](https://github.com/paberr/ownscribe) both transcribe live/fast and diarize the whole
   file after — ~30 s to diarize 45 min on a laptop, CPU-only.

whisper.cpp's "diarization" flag is **stereo-channel splitting, not speaker diarization**
([tinydiarize](https://github.com/akashmjn/tinydiarize) is the real attempt) — not usable here.

## 4. Estimating an unknown speaker count (and living with its errors)

sherpa-onnx's clustering runs with `num_clusters = -1` (auto) governed by `cluster_threshold`; the
count falls out of the clustering. But **automatic count estimation is imperfect** — literature and
practitioner reports put roughly **1 in 4 sessions** at the wrong count, with a bias toward
*under*-counting (merging two quiet speakers) ([spectral-clustering diarization, ICASSP-2018](https://wangquan.me/files/research/diarization_ICASSP_2018.pdf);
eigengap/auto-tune discussion in the SoA report §C).

**Consequence for the design:** we must ship a **human correction step**, not pretend the count is
always right. Meeting mode provides post-hoc `relabel` (merge two speaker clusters, split is out of
scope, rename to a real name) that **re-renders the transcript and notes without re-diarizing.** This
is the honest way to handle unknown-count error, and it's cheap because rendering is pure.

**Overlapping speech** is the other known limiter: clustering + max-overlap word assignment drops the
minority speaker when two people talk at once (overlap-aware EEND models exist but are the same gated/
GPU set we rejected). Carried as a documented caveat, identical to ADR-v2-125.

## 5. What already exists (reuse, do not rebuild)

The codebase map (2026-07-10) confirms meeting mode needs **no new heavy dependency** — every core is
present with tests:

| Need | Existing component | Notes |
|---|---|---|
| Audio capture | `audio/recorder.py::AudioRecorder` (callback, `on_chunk`) | Remove the 90 s cap for continuous run |
| Live transcript | `stt/streaming.py::StreamingEngine` + `stt/faster_whisper.py::transcribe_words` | LocalAgreement partials; word timestamps |
| VAD segmentation | `audio/vad_calibrated.py` (+ Silero VAD as an option) | Chunk continuous audio into utterances |
| Diarizer (batch) | `recimport/diarizer.py::SherpaDiarizer` | Auto count, CPU ONNX, Apache-2.0, **already shipped** |
| Word↔speaker align | `recimport/align.py::assign_words_to_turns` / `merge_utterances` | Pure numpy, tested |
| Speaker naming | `recimport/naming.py` + `voiceprint/` (ECAPA, `nearest_profile`) | Enrolled → "You"; others → "Speaker N" |
| Label/render | `scribe/diarize.py`, `diarize/labels.py`, `recimport/render.py` | Pure, zero-model; md/txt/srt/vtt/json |
| Notes LLM | `postprocess/llm_cleanup.py::build_cleaner` (ADR-013) | Offline llama.cpp plumbing to extend |
| State machine / IPC / CLI | `core/daemon.py`, `ipc/`, `cli.py` | Add a `MEETING` state + `meeting` subcommand |

There is also **accepted prior design**: [ADR-v2-019 Ambient Meeting Scribe](../adr/adr-v2-019-meeting-scribe.md)
("who said what", "You" from the enrolled voiceprint, pure labelling layer, *not* a keyboard-injection
path). Meeting mode is the **implementation** of that intent, with the diarization strategy corrected
from "Streaming Sortformer online" (its original anchor, now rejected on licensing/GPU grounds) to the
hybrid batch pass we already ship.

## 6. Target architecture

```
 yazses meeting start ──IPC──► daemon: enter MEETING state
                                  │
      continuous mic  ──► AudioRecorder(on_chunk) ──┬──► temp WAV (full recording, local)
                                                    │
                                                    └──► VAD utterance chunker
                                                            │
                              live transcript view  ◄──── faster-whisper (per utterance, word ts)
                              (yazses meeting status /            │  append → rolling transcript.jsonl
                               overlay; NOT injected)             │
 yazses meeting stop  ──IPC──► finalize ──────────────────────────┘
                                  │
                                  ├─ SherpaDiarizer.diarize(full WAV)      → turns (auto speaker count)
                                  ├─ assign_words_to_turns + merge_utterances → per-speaker utterances
                                  ├─ naming.py (+ voiceprint)               → "You" / "Speaker N" / --names
                                  ├─ render.py                              → transcript.md / .json / .srt
                                  └─ [opt-in] minutes LLM (ADR-128)         → notes.md (summary/decisions/actions)
                                  │
                                  ▼
        ~/.local/share/yazses/meetings/<timestamp>/{audio.wav?, transcript.md, transcript.json, notes.md}
        yazses meeting relabel <id> --merge s2=s1 --rename s1=Alice   (re-render, no re-diarize)
```

Key properties: **no keystroke injection** (a saved artifact, per ADR-v2-019), **on-device only**
(ADR-011), audio persisted locally only for the post-pass and **deleted unless `retain_audio`**,
speaker embeddings biometric → encrypted-corpus-only, never auto-enroll third parties (ADR-011/012).

## 7. On-device meeting notes (see ADR-v2-128)

Turning the speaker-labelled transcript into minutes is realistic on CPU but is **minutes of compute,
not seconds**, and needs care:

- A one-hour transcript **exceeds a small model's context** → **turn-aware chunking + map-reduce**
  (summarise windows, then summarise the summaries).
- **Constrain the output** (GBNF / JSON schema) so you reliably get `{summary, decisions[],
  action_items[{owner, task}], per_speaker[]}` instead of free prose.
- Feasible models on CPU Q4: **Phi-4-mini**, **Qwen2.5-3B/7B**. Reuse the ADR-013 llama.cpp path.
- Opt-in, behind an extra; dormant by default. Grounding datasets for evaluation: AMI, ICSI, QMSum.
  ([transcript→notes with an LLM, Gladia](https://www.gladia.io/blog/transcript-to-actionable-notes-llm))

## 8. Competitive position

No on-device competitor offers **persistent, voiceprint-based speaker naming**. Otter/Fireflies/Granola
are cloud ([Otter speaker ID](https://help.otter.ai/hc/en-us/articles/21665587209367-Speaker-Identification-Overview),
[Granola](https://docs.granola.ai/article/transcription)); MacWhisper/[meetily](https://github.com/Zackriya-Solutions/meetily)/
[ownscribe](https://github.com/paberr/ownscribe) are local but label speakers only as "Speaker N" per
session. YazSes' encrypted-corpus voiceprint (ADR-012) + offline diarization lets a meeting say
**"Alice", "Bob", "You"** and remember them across meetings — an unoccupied niche.

## 9. Risks (carried honestly)

| Risk | Mitigation |
|---|---|
| Auto speaker-count wrong (~25%) | `relabel` merge/rename, pure re-render; expose count in `status` |
| Overlapping speech drops minority speaker | Documented caveat; overlap-aware models are gated/GPU (rejected) |
| CPU can't keep up live on a big model | Live view is best-effort; the *authoritative* transcript is the batch pass at stop; `[stt].model` tunable |
| faster-whisper word timestamps drift 100–400 ms | Turn boundaries approximate on rapid exchanges (same as ADR-125) |
| Notes LLM slow / hallucinated | Opt-in, off by default, constrained JSON, map-reduce, show "generating…" |
| Long meeting fills disk | Stream to temp WAV; cap/rotate; delete unless `retain_audio` |
| Biometric/consent (GDPR Art.9 / BIPA) | Naming opt-in + consent notice; never auto-enroll others (ADR-011/012) |

## 10. Sources

Full cited study with 57 primary sources: [`soa-report.html`](./soa-report.html). Load-bearing ones:
sherpa-onnx diarization ([docs](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html),
[example](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-speaker-diarization.py)),
OpenWhispr hybrid-local pattern, diart, pyannote 3.1 (gated), NVIDIA Sortformer (GPU/NC),
ECAPA-TDNN, F0-unreliability studies, Gladia transcript→notes.
