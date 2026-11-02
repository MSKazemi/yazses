# Meeting Mode — design & state-of-the-art

**Status:** design written 2026-07-10; the architecture in §6 has since shipped (first in
v2.12.0) — see **Delivery status** below for what is built, what is partial, and what is
still being measured · public design document, published on the docs site
**Decisions:** [ADR-v2-127](../adr/adr-v2-127-live-meeting-mode.md) (live meeting mode + hybrid diarization),
[ADR-v2-128](../adr/adr-v2-128-meeting-minutes-generation.md) (on-device minutes)
**Plan:** an internal planning note
**Full SoA study:** [`soa-report.html`](./soa-report.html) (57 cited primary sources; also a private
claude.ai artifact)

---

## Delivery status (current, 2026-10-21)

This block is the only part of the page that tracks the code. Everything from §1 on is the
original 2026-07-10 design, kept as written — read it as the reasoning behind what was
built, not as a list of open work. Each row below was checked against `src/yazses/meeting/`,
`docs/features.md`, `docs/command-index.md`, `CHANGELOG.md` and the git tags on
2026-10-21; release numbers are the first tag containing the change. Tracking: parent
[#481](https://github.com/MSKazemi/yazses/issues/481), this reconciliation
[#489](https://github.com/MSKazemi/yazses/issues/489).

Meeting Mode is an **optional, off-by-default** feature (`[meeting] enabled = false`;
`yazses features enable meeting`). Speaker labels need the diarization extra; minutes need
the `notes` extra plus a GGUF model you supply.

### As-built / shipped

| Design element (§) | Shipped as | First release |
|---|---|---|
| Hands-free capture, no key held (§1, §6) | `yazses meeting start` / `stop` / `status` / `list`; `meeting/controller.py`, `session.py` (audio streamed to a WAV on disk) | v2.12.0 |
| Live transcript, not injected (§6) | VAD utterance segmenter (`meeting/segmenter.py`, `vad.py`) → rolling `live.jsonl`; `live-transcript.md` you can `tail -f` (`[meeting] live_markdown`, default on) | v2.12.0; `live-transcript.md` v2.32.0 |
| Hybrid diarization: batch post-pass at stop (§3) | `meeting/finalize.py` delegates to `recimport.pipeline.transcribe_file` — the same cores as `yazses transcribe` (ADR-v2-125) | v2.12.0 |
| Unknown speaker count (§4) | sherpa-onnx auto-clustering; default `[meeting] cluster_threshold = 1.2`, chosen by measurement in [ADR-v2-133](../adr/adr-v2-133-diarization-clustering-default.md) | v2.12.0; `1.2` default v2.30.0 |
| Human correction step (§4) | `yazses meeting relabel` — merge and rename clusters, re-rendered from `transcript.json` without re-diarizing (`meeting/store.py::relabel`) | v2.12.0 |
| Speaker naming (§5, §8) | "You" from the enrolled voiceprint; `yazses meeting enroll` turns a cluster from a stored meeting into an encrypted, on-device voiceprint (`meeting/participants.py`) | `enroll` in v2.12.0 |
| Minutes pipeline (§7, ADR-v2-128) | `meeting/notes.py` — turn-aware map-reduce, optional GBNF grammar (`[meeting] notes_grammar`), `yazses meeting notes` | v2.12.0 |
| Selectable VAD (§5) | `[meeting] vad_backend = calibrated` (default) or `silero` (optional `silero` extra, falls back to calibrated) | v2.12.0 |
| Accuracy backend option | `[meeting] backend = "pyannote"` behind the opt-in `diarization-pyannote` extra (a one-time gated model download; sherpa stays the default) | v2.19.0 |
| Audio deleted unless `retain_audio`; auto-stop at `max_minutes` (§6, §9) | `[meeting] retain_audio = false`, `max_minutes = 180` (finalizes rather than dropping audio) | v2.12.0 |
| Tray entry points | **Start meeting** / **Stop meeting** in the tray menu on Linux, macOS and Windows (`tray/meeting.py`) | v2.28.0 |
| Retry a failed post-pass | `yazses meeting recover` (`meeting/recover.py`) — never truncates or deletes the recording | v2.30.0 |
| Transcript quality gate (not in the original design) | `meeting/quality.py`, [ADR-v2-134](../adr/adr-v2-134-meeting-transcript-quality-gate.md): live vs batch decode compared, `quality.json` written, recording kept on a bad verdict; `yazses meeting summary` | v2.32.0 |

Tests: `tests/test_meeting_*.py`. Both decision records,
[ADR-v2-127](../adr/adr-v2-127-live-meeting-mode.md) and ADR-v2-128, are still marked
*Proposed* although their code ships; changing an ADR's status is the owner's decision.

### Partially shipped

- **`[meeting] model` / `language` on a live meeting.** The live post-pass still decodes with
  the daemon's dictation engine (`core/daemon.py` passes `engine=self._engine`), so those two
  keys are not applied there yet. The `[Unreleased]` section of `CHANGELOG.md` records the
  file-transcription path, including `meeting recover`, now honouring them; that fix is not
  yet released.
- **Minutes (ADR-v2-128, status still *Proposed*).** The pipeline ships, but there is no
  bundled model and no default: notes stay dormant until you set `[meeting] notes_model` to a
  local GGUF and install the `notes` extra.
- **Cross-meeting naming.** `meeting enroll` reads the stored recording, so it works only for
  meetings captured with `[meeting] retain_audio = true`; with the default, the audio is gone.
- **Live view.** §6 names "status / overlay"; what shipped is `meeting status`,
  `live-transcript.md` and the tray. The overlay does not show the meeting transcript.
- **Snap.** The snap bundles `sherpa-onnx` for Meeting Mode; verification on real machines,
  especially arm64, is open in [#142](https://github.com/MSKazemi/yazses/issues/142).

### Research / quality validation

These are measurement questions, not missing features. No result is claimed here beyond what
the linked record states.

- **Diarization accuracy, headset condition — measured.** ADR-v2-133 scores the shipped
  clustering against the AMI test split (16 recordings, 543.7 min; the headset mix, per
  #502) with a VoxConverse cross-domain check; the figures stand as recorded in the ADR
  (the harness is no longer part of this repository).
- **Diarization accuracy, far-field condition — open.** A laptop/table microphone is closer to
  real Meeting Mode use than a headset mix:
  [#502](https://github.com/MSKazemi/yazses/issues/502), under the paper-v2 programme
  [#510](https://github.com/MSKazemi/yazses/issues/510).
- **Speaker-count error and overlap (§4, §9).** Speaker-count error is part of #502's required
  reporting. Overlapping speech stays a documented caveat; no measurement of it is tracked.
- **Minutes quality (ADR-v2-128).** ADR-v2-128 names AMI, ICSI and QMSum as evaluation
  grounding. No minutes evaluation has been run and no issue tracks one as of 2026-10-21;
  until one exists, treat minutes quality as unmeasured.
- **Non-English meetings.** Mandarin file/meeting transcription:
  [#501](https://github.com/MSKazemi/yazses/issues/501).

### Deferred (not scheduled; none is a commitment)

- **Online/streaming diarization** — rejected in §3 on licensing and GPU grounds; the hybrid
  batch pass is the design.
- **Overlap-aware diarization** — the candidate models are the gated/GPU set §3 rejects.
- **`relabel` split** of one cluster into two — out of scope in §4; merge and rename only.
- **System-audio / call capture** — Meeting Mode records the room microphone, not a
  Zoom/Teams call's audio (stated in `docs/meeting-notes-offline.md`).
- **Meeting transcript in the overlay** — see *Partially shipped*.

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
*under*-counting (merging two quiet speakers) ([spectral-clustering diarization, ICASSP-2018](https://arxiv.org/abs/1710.10468);
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
