# Idea mining: silent speech & neural interfaces (2026-08-08)

Private (`design/` is gitignored). The public output of this work is the new
**"Silent speech: when the muscle does carry the words"** section in
`docs/research/muscle-brain-control.md`, refs 13–28.

**PDFs of cited papers are kept in a local, gitignored cache and are never published.**
Only citations and our own summaries go public; no paper text is redistributed.

## Corpus — 20 sources, every one verified before use

Verified via **Crossref** (journal DOIs) and **DataCite** (`10.48550/arXiv.<id>`).
`export.arxiv.org` hangs from this sandbox — Crossref and DataCite both work, so
**use DataCite for arXiv, not the arXiv API**. The machine-readable dump of the verified
metadata is kept in the same local, gitignored cache.

Verification caught two errors before they reached the site:

- **LipLearner's first author is Zixiong Su, not Naoki Kimura.** A search-results
  grouping implied Kimura; the record says otherwise.
- **Chenyu Tang is first author of the Nature Sensors 2026 SSI review** — he is a
  principal in this field, not a junior co-author as the earlier reading suggested.

## The ideas, ranked by how soon they could matter

### 1. Widen the activation seam from *onset* to *intent* ⭐ highest leverage

`EMGBackend` implements `HotkeyBackend` — it can say **start** and **stop**, and
nothing else. Every system in the corpus produces a *word* or an *intent*, and
none of them can express it through our seam. A protocol that admits an
intent-carrying source is the smallest change that makes SilentWear, the Cambridge
headphones, emg2speech and any BCI decoder pluggable.

Blocking design question, now public as open question 6: a source with a ~3% error
rate can inject text the user never reviewed. **What is the confirmation model?**
ADR-v2-010's `needs_confirm` (already used for gaze deixis) is the precedent.

### 2. Silent commands + voice dictation — the hybrid nobody ships

The corpus is unanimous: **96–97% on 10–30 words** (Tang 2025, Kurotaki 2026),
**~68% WER open-vocabulary** (Gaddy & Klein 2020). So closed vocabularies are
solved and dictation is not.

That maps onto our **command grammar**, not the dictation path. Silently mouthing
*undo* / *new line* / *send* while the voice carries prose is buildable today and
is a genuine product position. It also inverts the usual pitch — we are not
claiming EMG will replace typing, we are claiming it should replace the *modifier
key*.

### 3. The shared latent space is the cheap integration point

emg2speech: S3 (self-supervised speech) representations linearly predict EMG power
at **r = 0.85**, and EMG mapped into S3 space synthesises audio with no vocoder
training. Consequence: an EMG decoder targeting the representation a speech encoder
already computes can reuse our whole downstream stack — LM, vocabulary priming,
disfluency filter — rather than rebuilding it. Integration at the representation
layer, not the text layer.

### 4. Cross-user domain shift is a problem we already own

emg2qwerty (108 users, 346 h) names **domain shift across users and sessions** as
the central obstacle. We already carry per-user calibration and an encrypted
on-device learning corpus for exactly that failure in the voice path. Same
machinery, different signal — worth saying out loud to any collaborator.

### 5. A degradation ladder across activation sources

Cross-modal masking (del Blanco 2026) fuses sEMG + lipreading so the system
survives losing one modality. We have several activation sources (key, EMG, gaze)
treated as alternatives. Treating them as a **ladder that degrades gracefully** is
the same idea and costs no new dependency.

### 6. A device-neutral activation contract

Inoue 2025 trains one model across **heterogeneous electrode configurations**. That
is the sensor-side analogue of the `contract/` vectors built for the Android port.
An activation contract — "these are the events a source may emit, here are the
cases it must pass" — would let a lab prove its adapter works without owning our
pipeline. Reuses a pattern already proven here.

### 7. Evidence for the accessibility case (no code, immediate use)

- **emg2speech demonstrated with an ALS participant** silently articulating.
- **Card et al. 2026 (Nature Medicine)**: long-term *independent* home use of an
  intracortical BCI for speech and cursor control.
- Willett 2023: **62 WPM**, 23.8% WER at 125k vocabulary; Card 2024: **2.5% WER**.

The honest framing this supports, now on the public page: *the fast, accurate,
open-vocabulary paths still require surgery; every non-invasive path buys
reliability by shrinking the vocabulary.* That sentence is defensible and nobody
else assembles the table behind it.

### 8. Power budget: an always-on wearable trigger is proven feasible

SilentWear: 14 channels, **20.5 mW, >27 h on 150 mAh**, 15k-parameter CNN
on-device. This retires "would a wearable trigger even last a day" as an objection.

## Two publishable gaps we are positioned to fill

1. **Nobody publishes false-activation rates over a real workday.** Every paper
   reports session accuracy on 3–4 subjects. FP/hour across a working day, with
   electrodes re-seated between sessions, is the number that decides whether a
   trigger is livable — and we have the daemon, the logging and the users to
   measure it. Already open question 1 on the public page.
2. **There is no open closed-loop testbed for non-keyboard text input.** Every
   group rebuilds a demo harness. An Apache-2.0, cross-platform pipeline with a
   documented activation seam *is* that testbed. This is both the collaboration
   pitch (see an internal planning note) and a plausible systems
   paper.

## Next

- Ideas 1 and 2 are roadmap candidates; neither is filed as an issue yet.
- Ideas 7 and 8 are pure citation work — the accessibility use-case page could
  reuse them today.
- Same treatment could be applied to `docs/research/eye-control.md` and
  `voice-control.md`; only `muscle-brain-control.md` was swept in this pass.
