# ADR-v2-133 — The diarization clustering default, measured on real meeting audio

**Status:** **proposed — evidence complete for the problem, decision open.** Written
2026-08-23 during the Azure measurement window, the first time Meeting Mode's speaker
attribution had ever been scored against annotated human audio.
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-v2-125]] (diarized recording import — the cores this reuses),
[[adr-v2-127]] (meeting mode), [[adr-v2-128]] (on-device minutes, which consume the
speaker labels), [[adr-011]] (nothing leaves the machine — constrains which models may
be fetched and from where)

---

## Context

`[recimport] cluster_threshold` and `[meeting] cluster_threshold` both default to `0.5`,
and `recimport/download.py` fetches
`3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx` as the speaker embedder.
Both values were adopted together from sherpa-onnx's
`python-api-examples/offline-speaker-diarization.py`, which demonstrates the pipeline on
`0-four-speakers-zh.wav` — Mandarin audio, with a Mandarin-trained embedder and the
threshold that suits it. YazSes is English-first: `[meeting] language` defaults to `"en"`.

Until this week the only evidence for either value was a synthetic corpus of eight
TTS-rendered meetings, swept over `0.4–0.9`. That sweep found `0.5` dominated with an
interior minimum near `0.8`, and `docs/benchmarks.md` correctly declined to move the
default on TTS evidence alone.

### What real audio says

Four AMI sessions (`EN2002a`, `ES2004a`, `IS1009a`, `TS3003a`), Mix-Headset, four
speakers each, scored against the standard `pyannote/AMI-diarization-setup` `only_words`
reference RTTMs with no forgiveness collar:

| | DER (collar 0) | missed | false alarm | confusion | speakers found / true |
|---|---|---|---|---|---|
| shipped defaults | **84.1%** | 10.9% | 4.7% | **68.5%** | mean count error **+126.5** |

The result is not a scoring artefact. The `IS1009a` hypothesis was dumped to RTTM and
re-scored by two tools sharing no code with the harness: `pyannote.metrics` 4.1
reproduces every term exactly (90.20 / 7.72 / 6.58 / 75.90), and NIST `md-eval-22.pl`
agrees to 0.86 pp, the difference falling entirely in the false-alarm term where the two
are known to treat overlapped speech differently.

Missed speech and false alarm are both small, so segmentation is close to correct: the
speech is found, and then attributed to 86 speakers instead of 4.

### Which of the two copied values is responsible

Two one-variable sweeps separate them.

*Threshold moved, shipped Mandarin embedder held (IS1009a):*

| threshold | 0.5 | 0.7 | 0.9 | 1.0 | 1.1 | **1.2** | 1.3 | 1.5 | 1.7 | 2.0 |
|---|---|---|---|---|---|---|---|---|---|---|
| DER | 90.20 | 76.49 | 51.68 | 31.89 | 28.14 | **21.89** | 45.45 | 45.45 | 45.45 | 45.45 |
| speakers | 86 | 56 | 28 | 21 | 10 | **4** | 1 | 1 | 1 | 1 |

*Embedder changed, shipped threshold `0.5` held (IS1009a):* the English sibling of the
same architecture takes DER from 90.20% to 52.89% and still finds **62** speakers.

So the threshold is the dominant defect and the embedder is a second, smaller one. Both
came from the same upstream example, which is why they were easy to conflate.

Two properties of that curve matter more than the optimum itself:

1. **The window is narrow.** 1.2 works, 1.3 collapses the whole meeting into a single
   cluster. A shipped default has to sit inside a band roughly 0.1 wide on this meeting,
   and nothing yet says the band sits in the same place on other audio.
2. **A threshold is a distance in one embedding space.** It does not transfer between
   embedders, so "change the model" and "change the threshold" cannot be decided
   independently — whichever model ships needs its own sweep.

### Why the synthetic corpus did not catch this

Its sweep range stopped at `0.9`. A sweep whose optimum lies outside its range does not
report "range too narrow"; it reports a metric improving monotonically toward the edge,
which reads exactly like "no threshold helps". The corpus may or may not have been an
adequate proxy — that is being measured separately by re-sweeping it over the wider
range — but the range was capped below the answer either way.

**Re-swept to `1.6`, the synthetic corpus keeps its optimum at `0.8`–`0.9`** (15.79% at
`0.9`, 7 of 8 counts right) and collapses to a flat 63.61% from `1.2` upward. That was
recorded as a falsifiable prediction before the run: *if the optimum stays put, the
complete-linkage mechanism explains both corpora; if it drifts toward AMI's `1.2`, they
disagree about something else.* It stayed. So the corpus was not simply mis-swept — it
genuinely has a lower optimum, because complete linkage cuts at a fixed height and the
cut must clear the worst-case *same-speaker* pair in the recording. Three minutes of one
synthetic voice barely varies; forty minutes of a person in a real room varies a lot.

**That is the finding with the most weight for this decision, and it argues against
option 1.** The useful cut height is a property of the recording — its length, its room,
its speakers — not of the dataset or of the language. A single shipped constant is being
asked to be right across all of them.

### The four-meeting sweep

| threshold | 0.9 | 1.0 | 1.1 | **1.2** |
|---|---|---|---|---|
| DER (4 AMI meetings) | 46.28% | 33.58% | 30.11% | **27.07%** |
| mean speaker-count error | +35.00 | +22.00 | +7.75 | **+0.75** |
| meetings with the right count | 0/4 | 0/4 | 0/4 | 1/4 |

`1.2` reaches **27.07%**, which is *better* than the 28.55% that forcing
`max_speakers = 4` achieves on the same four meetings — and it gets there without asking
the user anything.

### At `1.2` the clustering recovers the right partition, it does not merely improve

Per-speaker total speech on `IS1009a` (14 minutes, four people), same audio:

| setting | speakers | turns | per-speaker seconds |
|---|---|---|---|
| shipped `0.5` | 86 | 190 | largest five 60.1, 47.6, 46.9, 38.4, 37.9; **smallest 0.32** |
| `cluster_threshold = 1.2` | 4 | 148 | 412.7, 165.3, 73.8, 35.6 |
| `max_speakers = 4` | 4 | 148 | 412.7, 165.3, 73.8, 35.6 |

The last two rows are identical to the decimal. On this recording the threshold does not
approximate the forced-count answer, it arrives at the same partition — so options 1 and
3 are not a trade-off here, and the remaining question is only whether `1.2` holds
elsewhere.

### The failure was visible in the output and nothing looked

That table is also a signal. A label holding 0.32 s of speech across a 14-minute meeting
is not a participant, and at `0.5` most of the 86 labels are of that kind, while the
smallest genuine speaker at `1.2` holds 35.6 s. Nothing in the pipeline asked, so Meeting
Mode wrote the transcript and [[adr-v2-128]]'s minutes consumed the labels as if they
named people.

**Shipped independently of this decision** as `recimport/plausibility.py`: it fires on
the *shape* of the distribution — most labels too small to be a participant, and only
once there are enough labels for "most" to mean something — never on the count, which
cannot tell a large meeting from a broken small one. It is advisory and one-directional:
it can say a result looks wrong, never that one looks right, and it never edits or
suppresses a transcript. Whatever this ADR decides, a future regression of the same kind
now announces itself.

## Decision

**Open.** The evidence above establishes the problem and rules out two explanations
(scoring, segmentation). It does not yet establish a replacement default: that needs the
four-meeting sweep over `0.9–1.6` and the per-model threshold sweep, both in flight.

## Options under consideration

1. **Raise `cluster_threshold` only.** Cheapest; no new download, no ADR-011 surface.
   Risk: one number tuned on four AMI meetings, in a window ~0.1 wide, shipped to
   arbitrary rooms and microphones.
2. **Switch the embedder to an English or bilingual sibling and re-tune the threshold
   for it.** Changes what a user's machine downloads, which is why this needs an ADR at
   all. All candidates come from the same sherpa-onnx release already trusted by
   `download.py`, so no new host is contacted.
3. **Stop shipping a bare threshold.** `max_speakers` is an *exact* cluster count on this
   backend, so a user who knows how many people were in the room bypasses clustering's
   count estimate entirely. Being measured as `ami_maxspk4.json`. This is the only option
   that does not ask a single constant to generalise across rooms.
4. **Do nothing and document it.** Rejected as a standalone option: 84% DER with 86
   labels for 4 speakers is not a degraded transcript, it is an unusable one, and Meeting
   Mode's minutes (ADR-v2-128) consume those labels.

Whatever is chosen, the honest number goes in `docs/benchmarks.md` first — the AMI result
is published whether or not the fix lands in the same release.

## Consequences

To be written with the decision.
