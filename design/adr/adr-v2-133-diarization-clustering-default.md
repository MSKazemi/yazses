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
