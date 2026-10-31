# Persian–English Code-Switch Evaluation Protocol (`fa-en-cs-v1`)

**Status:** Proposed — protocol only. No prompt has been collected, no recording made, and
no model output scored under it.
**Work package:** FA-09 ([#518](https://github.com/MSKazemi/yazses/issues/518)), part of
the Persian programme ([#483](https://github.com/MSKazemi/yazses/issues/483)).
**Companions:** [persian-benchmark-and-validation.md](persian-benchmark-and-validation.md)
§5 "Code-switch" (the metric list this makes precise) and §8 (sampling);
[polyglot-switch.md](polyglot-switch.md) (the feature being measured).
**Scorer:** `benchmark/codeswitch_metrics.py`, tested by
`tests/test_codeswitch_metrics.py` on synthetic text.

---

## 1. Why the protocol comes first

`[polyglot] pair = "fa-en"` is accepted by the config today, but the router stays dormant
until a user supplies `[polyglot] adapter_path` (`src/yazses/polyglot/router.py`,
`PolyglotRouter.active`). FA-10 is meant to measure a baseline before any adapter is
trained. That measurement only means something if the questions, the categories, the
split and the metric definitions are fixed **before** anyone looks at a model's output.
Otherwise the set gets tuned to the model, and the number describes the tuning.

So this document freezes all of them as protocol version **`fa-en-cs-v1`**. The rules:

1. Nothing in §3–§8 changes after a result has been inspected. A change, however small,
   is a new protocol version (`fa-en-cs-v2`), recorded in §11 with the reason, and the
   scorer's `PROTOCOL_VERSION` changes with it. A `v1` number and a `v2` number are not
   compared.
2. The held-out half (§6) is not used to choose prompts, thresholds (`[polyglot]
   mer_gate`), decoder settings or adapters. Use the dev half for those.
3. A prompt found to be wrong *after* scoring (a typo in the reference, say) is fixed in
   a new version of the prompt file, and both scores are reported. It is never edited
   out silently.

When this file landed, `results/` held no fa-en code-switch result.

## 2. Scope

**Measured:** how well a transcript keeps Persian and English apart and intact when one
utterance uses both, scored from text: a reference transcript and a hypothesis per prompt.

**Not measured here:** acoustic robustness, latency or RTF (bench_persian.py covers those
for monolingual Persian), injection or bidi display (persian-text-and-rtl.md), and a
decoder's own span labels. The scorer reads script, not a decoder's language tags (§7).

**Not claimed:** that YazSes handles fa-en code-switching today. Without an adapter the
router is inactive, and the `[polyglot]` config itself records that stock Whisper
cannot code-switch (`PolyglotConfig` docstring in `src/yazses/config.py`).

## 3. Content categories

Every prompt belongs to exactly one category. These are the six from #518, and the scorer
rejects any other value (`CATEGORIES` in the scorer).

| Category id | What a prompt contains | Synthetic example (from the test fixture) |
|---|---|---|
| `fa_with_en_term` | A Persian sentence carrying one English technical noun | `این فایل را در GitHub گذاشتم` |
| `product_names` | Product, package or service names, with their casing | `برای نصب از pip و uv استفاده کن` |
| `numbers_versions` | Numbers, versions or units next to either script | `می‌خواهم Python 3.12 را نصب کنم` |
| `en_clause_in_fa` | An English clause inside a Persian sentence | `گفت that's not a bug و رفت` |
| `fa_clause_in_en` | A Persian clause inside an English sentence | `I told him خیلی ممنون and left` |
| `rapid_switch` | Two or more switches within a few words | `این PR را merge کن` |

Authoring rules:

- Each reference is written the way a careful bilingual writer would type it: English
  terms in Latin script with their usual casing, Persian in Persian script with ZWNJ
  where the word takes one (`می‌خواهم`). Persian (Yeh U+06CC, Keheh U+06A9) letters,
  not Arabic ones. Digits in the script the prompt uses. A prompt whose correct written
  form is disputed (Latin or Persian spelling of a loanword, say) is dropped, because
  the protocol would score a matter of taste as an error.
- Before any held-out result is quoted per category, each category has at least
  **20 held-out prompts**. This is a protocol rule, not a power calculation; below it a
  per-category rate is reported with its `n` and marked indicative. The overall rate
  carries the per-category `n` beside it.
- A prompt holds no personal data: no real person's name except public product or
  organisation names, no address, no account identifier, nothing from a private message.

## 4. Sourcing

In order of preference:

1. **Prompts written for this set** by a contributor who dedicates them to the public
   domain (CC0 1.0, <https://creativecommons.org/publicdomain/zero/1.0/>). This is the
   default. The prompts are invented sentences of the kinds in §3, so no third party's
   text is involved and the prompt file can be committed.
2. **Openly licensed public text** (CC0, CC BY 4.0, CC BY-SA 4.0), adapted into prompts.
   Each prompt records its source URL, the revision or access date, and the licence.
   ShareAlike carries over to the prompt file, so CC BY-SA material makes that file
   CC BY-SA. It goes in a separate file, not mixed into a CC0 one.
3. **A public code-switch speech corpus**, if one exists with a clear licence. The
   protocol does not assume one does. If one is adopted, it is pinned (version, split,
   sample ids, as in persian-benchmark-and-validation.md §2) and reported **as its own
   corpus**, never pooled with read-prompt results.

Never used: private chats, emails, work documents, dictation logs, the learning corpus,
voiceprints, or any text or audio a person produced without knowing it would be
evaluated. AGENTS.md also forbids uploading real user audio or transcripts to a
third-party coding agent. That covers any recording made under §5.

The **prompt text** may be committed when it meets source 1 or 2. **Audio is never
committed by default**, and neither is a hypothesis transcript of a recorded speaker.
Both stay on the collector's machine, under the manifest rules `bench_persian.py`
already enforces (licence and consent values required, speaker and session only as
opaque pseudonyms, audio read only from the manifest directory or `--audio-root`;
persian-benchmark-and-validation.md §6.1).

## 5. Recordings, consent and data sharing

Recordings are **read prompts**: an adult volunteer reads prompts from §3 aloud. Nobody
records spontaneous speech about their own life for this set.

Every recording session needs written informed consent obtained **before** recording,
using the template below. The participant's sharing choice (A, B or C) is recorded in
the manifest's `consent` field as `aggregate-only`, `share-with-maintainer` or
`publish-cc-by-4.0`. The default, when nothing else is chosen, is **A**.

> ### DRAFT — owner review required
>
> **This template is a draft. It has not been reviewed by the project owner or by anyone
> qualified in data-protection law, and it must not be used to collect a recording until
> that review is done and this banner is removed.** Voice recordings are personal data.
> The collector is responsible for checking this text against the law that applies to
> them and to the participant (for example the GDPR where either is in the EU) and for
> adapting it. This draft is not legal advice.
>
> ---
>
> **YazSes Persian–English code-switch evaluation — participant information and consent**
>
> *What this is.* YazSes is an open-source, offline voice-typing program. We are
> measuring how accurately it writes sentences that mix Persian and English. You will
> read **[N]** short prepared sentences aloud. The sentences are written by the project
> and contain nothing about you.
>
> *Who is collecting.* **[collector name and contact]**, a volunteer contributor to
> YazSes. This collection is **[not] / [is]** carried out on behalf of an organisation:
> **[name, if any]**.
>
> *What is recorded.* Audio of you reading the sentences, plus your choice below. We do
> not record your name with the audio. Recordings are labelled with a random code.
> We ask for: **[none / age range / device and microphone type]**.
>
> *Where it is kept.* On the collector's own computer, **[encrypted disk / location]**.
> It is not uploaded to any online service, including AI tools.
>
> *How it is used.* Speech-recognition software runs over the audio on that computer, and
> the output is compared with the sentences you read. Only **numbers** leave the
> computer: error counts and rates per sentence category, with no audio, no text and no
> sentence identifiers.
>
> *Your sharing choice.* Choose **one**:
>
> - [ ] **A — Aggregate only (default).** My audio stays on the collector's computer
>   and is deleted by **[date]**. Only aggregate numbers are shared or published.
> - [ ] **B — Share with the maintainer for evaluation only.** In addition to A, the
>   audio may be passed privately to the YazSes maintainer, only to re-run this
>   evaluation, and deleted by **[date]**. It is never published.
> - [ ] **C — Publish under CC BY 4.0.** My recordings may be published under the
>   Creative Commons Attribution 4.0 licence
>   (<https://creativecommons.org/licenses/by/4.0/>), credited as
>   **[pseudonym / "anonymous contributor"]**. I understand that published audio cannot
>   be fully withdrawn once others have copied it, and that a voice can identify me.
>
> *Voluntary and withdrawable.* Taking part is voluntary. You can stop at any time
> during recording. You can withdraw later by contacting **[contact]** with your
> recording code: we will delete audio we still hold and leave you out of any result not
> yet published. Numbers already published as aggregates cannot be recalculated without
> you, and for option C, copies already made by others cannot be recalled.
>
> *Eligibility.* I am 18 or older, and I am reading only the provided sentences.
>
> Recording code: ______ Date: ______ Signature or recorded verbal consent: ______

## 6. Held-out split

The split is decided by the prompt id alone:

```
point = int.from_bytes(sha256(SEED + "\x00" + prompt_id)[:8], "big") / 2**64
split = "heldout" if point < HELDOUT_FRACTION else "dev"
```

with **`SEED = "yazses-fa-en-cs-v1"`** and **`HELDOUT_FRACTION = 0.5`**, frozen with the
protocol (`split_of` in the scorer; a known-answer test pins the assignment of the
fixture ids).

- **Reproducible without coordination.** Anyone with the prompt ids gets the same split.
  Adding, removing or reordering prompts never moves an existing prompt.
- **Split by prompt, not by recording.** Every recording of a prompt lands on the same
  side, so a prompt seen during tuning is never scored as held-out.
- **Speakers are not split.** The same speaker can appear on both sides. A held-out
  result measures generalisation to unseen *prompts*, not to unseen *speakers*, and is
  reported as such.
- **Equal halves.** The dev half is for tuning (§1 rule 2) and the held-out half for
  reporting. Both need enough prompts per category for §3's minimum. With only one
  collection effort to spend, halves are the simplest choice that serves both.
- **Prompt ids are opaque**: `^[a-z0-9][a-z0-9-]{0,63}$`, naming a prompt and never a
  speaker, session or person. The scorer refuses any other id.
- **Published with every result:** the split name, seed, fraction, prompt count and
  `prompt_digest`, a SHA-256 over the sorted held-out ids. A reader with the prompt file
  can confirm the same prompts were scored without anyone sharing a transcript.

## 7. Normalisation, tokens and script tags

1. Normalise reference and hypothesis with **`fa-eval-v1`** (persian-benchmark-and-
   validation.md §6, `persian_metrics.normalize_fa_eval_v1`): NFC, Arabic Yeh/Kaf to
   Persian, whitespace collapsed. ZWNJ, digits and punctuation are kept. Matching is
   case-sensitive.
2. Split on whitespace. ZWNJ stays inside a word.
3. Tag each token from its **letters** (Unicode category `L*`, script from the
   character name):
   - `fa`: an ARABIC-script letter and no LATIN letter;
   - `en`: a LATIN letter and no ARABIC-script letter;
   - `mixed`: letters from both scripts (`PRها`);
   - `neutral`: no letter at all (`3.12`, `۱۴۰۳`, `،`).

The tag is a **script** tag, not language identification. English written in Persian
script (`گیت‌هاب`) is tagged `fa`, and Persian written in Latin script (Finglish,
`kheili`) is tagged `en`. That is on purpose: both are what a code-switch decoder gets
wrong, and both have to show up as errors. `mixed` tokens count toward MER and are
reported as `mixed_ref_tokens`, but they make no boundary and take no part in
English-preservation or Persian CER. Their count shows how much of a set falls outside
those two metrics.

## 8. Metrics

Each metric is a sum of counts over utterances divided by a sum of denominators. They
are never averaged per utterance. A metric with a zero denominator is **`null`, never
`0`**. Alignment is minimum-edit over tokens. When two alignments cost the same, the
diagonal (match or substitution) wins, then deletion.

| Metric | Definition |
|---|---|
| `mer` | Token edit distance / reference tokens, over the whole mixed stream after `fa-eval-v1`. Both languages are whitespace-delimited, so the mixed unit is the word for both, unlike Mandarin–English MER, which counts Mandarin characters. |
| `mer_raw` | The same on raw text (whitespace split only). Reported beside `mer`, never instead of it (persian-benchmark-and-validation.md §5: normalisation can hide errors). |
| `boundary_error_rate` | (missed + spurious boundaries) / reference boundaries. A boundary is a script change between consecutive `fa`/`en` tokens. A hypothesis boundary *matches* an unclaimed reference boundary in the same direction (`fa→en` or `en→fa`) when its two flanking tokens are aligned to reference tokens that bracket it. Each reference boundary is claimed at most once. Can exceed 1. |
| `boundary_recall`, `boundary_precision` | matched / reference boundaries, matched / hypothesis boundaries. Precision is the only one defined when the reference has no switch, so it is where spurious switches show up. |
| `en_preservation` | Reference `en` tokens whose aligned hypothesis token is identical after stripping leading and trailing punctuation (`GitHub،` = `GitHub`). |
| `en_preservation_casefold` | The same, case-folded (`Pip` = `pip`). The gap between the two is the casing error. |
| `en_transliteration_rate` | Reference `en` tokens aligned to a hypothesis token tagged `fa`, i.e. written in Persian script. |
| `fa_cer` | Character edit distance between the reference's `fa` tokens and the hypothesis's `fa` tokens (each side joined by single spaces) / reference characters. English rendered in Persian script costs Persian characters here. |
| `token_language_accuracy` | Of the reference `fa`/`en` tokens aligned to a hypothesis token, the share whose script tag agrees. This is the part of the spec's "span-language accuracy where observable" that text alone can observe. |

Every metric is reported **overall and per category**, with `n` and the raw counts, so a
reader can recompute any rate and judge its size.

## 9. Submitting results: aggregate only

A contributor scores locally and shares only the aggregate block:

```sh
uv run python benchmark/codeswitch_metrics.py rows.jsonl --split heldout --out agg.json
```

`rows.jsonl` holds `{id, category, reference, hypothesis}` per prompt. It stays on the
contributor's machine. The output (`schema: yazses.bench.codeswitch/1`) is the only thing
submitted. It contains the protocol and normaliser versions, the split block from §6,
and counts and rates overall and per category. It contains **no** text, prompt ids,
audio paths, speaker codes or per-utterance rows, and a test asserts that for the
synthetic fixture. Aggregate-only is the CLI's only output mode. Anyone who needs
per-utterance scores for their own debugging calls `score_utterance` locally.

A submission also states, in prose, the model, decoder settings, YazSes commit and
machine, as persian-benchmark-and-validation.md §7 asks of every Persian result, plus the
corpus source from §4 and how many speakers there were. Results from different sources
or protocol versions are reported separately and never pooled.

## 10. What this commit does not do

- It collects no prompts and makes no recordings. The fixture is twelve invented
  sentences, enough to test the scorer and far short of §3's minimum.
- The consent template is a **draft** awaiting owner review (§5).
- It runs no model. Decoding a manifest and handing the hypotheses to this scorer is
  FA-10's measurement, not FA-09's.
- It does not score a decoder's own `LangSpan` labels (polyglot-switch.md). If the
  decoder ever exposes them, scoring them is a protocol addition (`v2`).

## 11. Version history

| Version | Change | Reason |
|---|---|---|
| `fa-en-cs-v1` | Initial protocol: six categories, sourcing order, draft consent, seeded split (`yazses-fa-en-cs-v1`, 0.5), metric definitions §7–§8. | FA-09, written before any result was inspected. |
