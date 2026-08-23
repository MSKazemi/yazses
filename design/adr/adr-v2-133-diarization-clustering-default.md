# ADR-v2-133 — The diarization clustering default, measured on real meeting audio

**Status:** Accepted — 2026-08-23
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-v2-125]] (diarized recording import — the cores this reuses),
[[adr-v2-127]] (meeting mode), [[adr-v2-128]] (on-device minutes, which consume the
speaker labels), [[adr-011]] (nothing leaves the machine — constrains which models may
be fetched and from where)

Decided during the Azure measurement window, the first time Meeting Mode's speaker
attribution had ever been scored against annotated human audio. The decision below rests
on the full AMI test split (16 recordings, 543.7 min) and a cross-domain gate on
VoxConverse (15 recordings, 137.7 min); both are reproducible with
`paper/benchmark/bench_diarization.py`.

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

### The gate: `1.2` does not transfer to another domain

VoxConverse exists in this harness for exactly one purpose — *"it checks that a change does
not help one domain by hurting another"* (`paper/benchmark/README.md`). Fifteen dev
recordings, 137.7 min, broadcast and YouTube audio:

| threshold | 0.5 (shipped) | 0.7 | **1.2 (AMI optimum)** |
|---|---|---|---|
| DER | 41.72% | **24.39%** | 42.13% |
| mean speaker-count error | +31.73 | +16.20 | **−6.40** |
| exact count | 1/15 | 2/15 | 1/15 |

Two things fall out, and they point in opposite directions.

**The optimum does not transfer.** AMI's best value is VoxConverse's worst of the three, and
the count error changes *sign*: at `1.2` VoxConverse is under-counted by 6.4 speakers per
recording, where AMI at the same value is within 0.75. This is the complete-linkage mechanism
again, now measured across domains rather than inferred: a cut height that clears the
worst-case same-speaker pair in a 40-minute meeting merges distinct speakers in a
crowd-scene broadcast. **`0.5` is nevertheless not optimal anywhere measured** — synthetic
peaks near `0.9`, AMI at `1.2`, and VoxConverse is 17 pp better at `0.7` than at the shipped
value.

**But the cost of raising it is not symmetric with the gain.** Moving the default from `0.5`
to `1.2` is worth **+57 pp** on AMI (84.1% → 27.07%) and **−0.41 pp** on VoxConverse
(41.72% → 42.13%), which on fifteen files is noise. So the gate did not veto raising the
default; it vetoed the *claim* that `1.2` is the right number in general. Meeting Mode is
pointed at meetings, and on the corpus that is not meetings the change costs approximately
nothing while leaving that domain as mis-tuned as it already was.

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

### The full test split, and what it does to option 3

The four-meeting sweep was four recordings. Repeated on the **entire AMI test split** — 16
recordings, 543.7 minutes, `only_words` references, collar 0:

| | DER | mean speaker-count error | exact count |
|---|---|---|---|
| shipped (`0.5`, auto-count) | **75.21%** | **+155.19** | 0/16 |
| `cluster_threshold = 1.2` | **26.71%** | +2.06 | 2/16 |
| `max_speakers = 4` | 29.42% | +0.06 | 16/16 by construction |

Per recording the shipped default runs from 53.7% to 92.0% DER, finding between 81 and 272
speakers in rooms holding four people.

**`1.2` beats forcing the exact count on four times the audio** — 26.71% against 29.42% —
and it does so without asking the user a question. The four-meeting run said the same thing
(27.07 against 28.55) and could have been luck; it was not. That is the measurement option 3
needed to win and did not get.

Option 3 also has a defect the split exposes on its own terms: **`EN2002c` has three
speakers, not four.** `max_speakers` is an *exact* cluster count on this backend, so the arm
is guaranteed wrong there — and a four-person meeting where somebody stays silent or joins
late is ordinary. Forcing 4 still scores 18.84% on it, far better than the shipped 84.74%,
so the option is not harmful; it is just not better than a threshold, and it costs a question.

## Decision

**Raise the threshold, and stop pretending the two features see the same audio.**

* `[meeting] cluster_threshold`: `0.5` → **`1.2`**
* `[recimport] cluster_threshold`: `0.5` → **`1.0`**
* `max_speakers` stays `0` and stays documented as the escape hatch for a user who knows
  the count and wants it obeyed.
* The embedder is not changed (option 2 deferred, see below).

The two keys already existed separately and were only ever set together by inheritance from
the same upstream example. They point at different audio, and the measurements say so:

| corpus | what it stands for | optimum measured |
|---|---|---|
| AMI test split (16, 543.7 min) | Meeting Mode: one room, one microphone, long | **1.2** |
| VoxConverse dev (15, 137.7 min) | `yazses transcribe`: arbitrary files, 1–20 speakers | **0.9** |
| Synthetic TTS (8) | neither; a proxy that turned out to be a poor one | 0.8–0.9 |

**`0.5` is optimal on none of them.** That is the whole case for moving, and it does not
depend on picking the right replacement.

### Why `[recimport]` gets `1.0` and not the `0.9` that measured best

`0.9` is the point optimum on VoxConverse — 16.30% against `1.0`'s 17.34%, a 1 pp lead on
fifteen files. Two things outweigh it:

1. **Speaker count.** At `0.9` VoxConverse is over-counted by **+5.20** speakers per
   recording; at `1.0` by **+0.73**, with the count exactly right on 3 of 15. ADR-v2-125's
   naming path consumes those labels — a voiceprint match, a `min_speaker_seconds` gate, a
   "Speaker N" fallback — so a label count that is nearly right is worth more downstream than
   a DER that is 1 pp lower.
2. **`recimport` does not know what it was handed.** It is `yazses transcribe <file>`:
   podcasts, interviews, lectures, and meeting recordings. On meeting audio `0.9` scores
   46.28% and `1.0` scores 33.58%. Choosing for the tail rather than for the point estimate
   costs 1 pp on the matched corpus and saves 12.7 pp on the mismatched one.

`[meeting]` has no such ambiguity — it only ever sees audio YazSes recorded itself in a room
— so it takes its corpus's optimum outright.

### What this decision does not claim

**Not that `1.2` is a good number in general.** VoxConverse is 42.13% there, and the
speaker-count error changes *sign*: at `1.2` a broadcast recording is under-counted by 6.4
speakers where a meeting is within 0.75. The gate did its job. It vetoed the general claim,
not the change.

**Not that a constant is the right shape.** Complete-linkage cuts at a fixed height, and the
height that clears the worst-case same-speaker pair depends on the recording — three minutes
of one synthetic voice barely varies, forty minutes of a person in a real room varies a lot.
Three corpora produced three optima for exactly that reason. A per-recording estimate is the
better answer and nobody has one here; two defaults matched to two input domains is the best
a constant can do, and the plausibility guard is what covers the rest.

### The guard is what makes a split default safe

`recimport/plausibility.py` (shipped independently of this decision) was run against real
diarizer output on `IS1009a` at every threshold on the curve:

| threshold | labels | under 20 s | verdict | DER |
|---|---|---|---|---|
| 0.5 | 86 | 75 | **fires** | 90.20% |
| 0.9 | 28 | 22 | **fires** | 51.68% |
| 1.0 | 21 | 17 | **fires** | 31.89% |
| 1.1 | 10 | 4 | silent | 28.14% |
| 1.2 | 4 | 0 | silent | 21.89% |
| 1.3 | 1 | 0 | silent | 45.45% |

On the same recording's **human annotation** — four speakers holding 412, 144, 71 and 68
seconds — it is silent. So it catches the case the split default is exposed to (a meeting
imported through `transcribe`, where `1.0` over-splits) and leaves a correct answer alone.

It is honest about what it does not cover: `1.1` is still wrong (10 labels for 4 people) and
passes, and `1.3` collapses the meeting into one cluster and passes, because the guard is
one-directional and a single cluster is not "mostly fragments". It is a floor, not a check.

### Option 2 (change the embedder) — deferred, not rejected

The English sibling of the same architecture takes `IS1009a` from 90.20% to 52.89% at the
shipped threshold, so the Mandarin embedder is a real second-order defect. It is deferred
because **a threshold is a distance in one embedding space**: adopting a new embedder
invalidates every number above and requires the whole sweep again, on both corpora, before
anything could be shipped. That is a separate measurement window, and the threshold change
delivers the larger share of the win without changing what a user's machine downloads.

## Options considered

Outcomes are recorded against each; the reasoning is in the Decision above.

1. **Raise `cluster_threshold` only.** — **CHOSEN**, with one value per feature. Cheapest; no new download, no ADR-011 surface.
   Risk: one number tuned on four AMI meetings, in a window ~0.1 wide, shipped to
   arbitrary rooms and microphones.
2. **Deferred. Switch the embedder to an English or bilingual sibling and re-tune the threshold
   for it.** Changes what a user's machine downloads, which is why this needs an ADR at
   all. All candidates come from the same sherpa-onnx release already trusted by
   `download.py`, so no new host is contacted.
3. **Rejected as a default. Stop shipping a bare threshold.** `max_speakers` is an *exact* cluster count on this
   backend, so a user who knows how many people were in the room bypasses clustering's
   count estimate entirely. Measured on the full split: 29.42% against `1.2`'s 26.71%. This is the only option
   that does not ask a single constant to generalise across rooms.
4. **Rejected. Do nothing and document it.** Rejected as a standalone option: 84% DER with 86
   labels for 4 speakers is not a degraded transcript, it is an unusable one, and Meeting
   Mode's minutes (ADR-v2-128) consume those labels.

Whatever is chosen, the honest number goes in `docs/benchmarks.md` first — the AMI result
is published whether or not the fix lands in the same release.

## Consequences

* **Meeting Mode's speaker labels become usable.** 75.21% → 26.71% DER on the AMI test
  split. Not good — 26.71% is a poor diarization result by the literature's standards — but
  the difference between "which of these four people said this" and "here are 155 speakers
  who were not in the room", and ADR-v2-128's minutes consume these labels directly.
* **Two defaults now differ where one used to be copied.** `docs/configuration.md` and
  `docs/benchmarks.md` must say why, because a user comparing the two sections will otherwise
  read it as an oversight.
* **The published numbers get worse before they get better.** `docs/benchmarks.md` carries
  the shipped-default result as measured, including the 75.21%. It was true of every release
  to date and is not deleted by fixing it.
* **A user who pinned `cluster_threshold = 0.5` keeps it.** The change is to the dataclass
  default; `configcheck.py` does not rewrite an explicit value.
* **The synthetic corpus is demoted, not deleted.** Its optimum (0.8–0.9) matched neither
  shipped default, and it swept a range that could not contain AMI's answer. It stays as a
  cheap regression fixture and stops being evidence for a default.
* **Nothing is re-tuned for the embedder that is actually shipped.** If option 2 lands, all
  of this is measured again.
