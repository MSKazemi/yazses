# Multilingual, accent and code-switch evaluation design for offline ASR

**Date:** 2026-11-05
**Status:** Research note (not a decision). ADR-030 freeze unchanged.
**Tracking:** [#797](https://github.com/MSKazemi/yazses/issues/797) under [#787](https://github.com/MSKazemi/yazses/issues/787); reuses [#793](https://github.com/MSKazemi/yazses/issues/793) rules; coordinates [#503](https://github.com/MSKazemi/yazses/issues/503), [#505](https://github.com/MSKazemi/yazses/issues/505), [#258](https://github.com/MSKazemi/yazses/issues/258).
**Builds on:** [pinned offline ASR protocol](2026-11-03-pinned-offline-asr-evaluation-protocol.md) (normaliser, failure accounting, pinning, v1 row schema), [proposed ADR-033](../adr/adr-033-reproducible-asr-evaluation-gate.md) (Proposed, not Accepted), [fa-en code-switch protocol `fa-en-cs-v1`](../specs/persian-code-switch-evaluation.md), [Persian benchmark spec](../specs/persian-benchmark-and-validation.md), [dysfluency protocol](2026-11-03-dysfluency-fidelity-evaluation-protocol.md) (rights-ledger pattern).
**Base:** main at a241a77b. **Scope:** documentation only. No dataset or model was downloaded, no audio was processed, no score was computed. All web pages were read on **2026-11-05** through a text-summarising fetcher, so each is **"not read in full"** unless noted; treat every [Verified-primary-source] below as "the summary of that landing page said so", and re-read the page before relying on a number.

> Labels: **[Verified-primary-source]** stated on the landing page/abstract/model card/source file read on 2026-11-05; **[Upstream-claim]** the upstream authors' own claim, not re-measured; **[Verified-in-code]** read in this repository at the base SHA; **[Assumption]** a design choice or inference needing review; **[Unknown]** not established by anything read.

## 1. Answer to #797 and recommendation

**Adopt** this note as the multilingual layer on top of the #793 protocol; **defer** any "supported language" claim, default change or new engine; **reject** (a) pooling languages into one WER, (b) scoring a refused or unsupported language as 0 or 100 % WER, (c) using a corpus's marketing "zero-shot" status as proof the engine never saw it. [Assumption: recommendation]

The user-visible failures the issue asks about are mostly not recognizer errors. They are (i) output in the wrong script or language that no WER hides, (ii) orthography damage after correct recognition (Han script, ZWNJ, Yeh/Kaf), (iii) a normaliser that silently rewrites words, and (iv) an engine that never refuses. This note makes each of them a separately reported number. [Assumption]

## 2. Current YazSes state (audit, [Verified-in-code] unless marked)

| Language / target | What the repo claims or contains | Gap for a new public claim |
| --- | --- | --- |
| English | Default `base.en`; historical LibriSpeech tables in [benchmarks.md](../../docs/benchmarks.md); [docs/models.md](../../docs/models.md) says the numbers are "not a claim about your accent" | No accent slice at all |
| English accents | No accent claim anywhere; no accent corpus in the tree | Whole design below is new |
| Mandarin | Profiles `zh-CN`/`zh-TW`, speech `zh`, recommended `faster-whisper` `small` ([profiles.py](../../src/yazses/language/profiles.py)); `zh-HK`/Cantonese refused there; #505 release boundary excludes Cantonese and "arbitrary Mandarin-English code-switching" | CER evidence is #503 MODEL-0x (open); harness `benchmark/bench_mandarin.py` is cited by the [spec](../specs/chinese-language-support.md) but **not tracked in this checkout** (`git ls-files` finds none) |
| Persian | No profile. Opt-in `[stt] persian_normalisation` ([persian_text.py](../../src/yazses/postprocess/persian_text.py)). Measured on FLEURS `fa_ir` (871 test utterances) and Common Voice `fa` (10,559) in [benchmarks.md](../../docs/benchmarks.md); [multilingual-dictation.md](../../docs/use-cases/multilingual-dictation.md) still says "we do not claim support" | Harness, `persian_metrics.py` and `codeswitch_metrics.py` are cited by the specs but **not tracked here**; ADR-033 says a private archive cannot back a new public claim |
| Hindi, Tamil, Russian | Whisper capability table lists `hi`, `ta`, `ru`; Parakeet v3 lists `ru` only ([capability.py](../../src/yazses/language/capability.py)). `docs/benchmarks.md` has no number for any of the three (grep). `docs/hi` and `docs/ta` are page translations, not speech claims | No evidence of any kind |
| Code-switching | `[polyglot]` is "planned, not wired" ([multilingual-dictation.md](../../docs/use-cases/multilingual-dictation.md), [features.md](../../docs/features.md)); `fa-en-cs-v1` is a protocol with a 12-sentence fixture and no collected prompts | Only stock-decoder behaviour can be measured |

Engine fact that drives failure accounting: with a non-English `[stt] language`, an English-only checkpoint "does not fail"; faster-whisper replaces the language by `en` for a non-multilingual tokenizer, and the Distil-Whisper `large` checkpoints keep a multilingual tokenizer so nothing warns ([capability.py](../../src/yazses/language/capability.py) docstring and rows). Parakeet v2 and Moonshine take no language. `check()` returns `supported`/`unsupported`/`unknown` and callers refuse only on `unsupported`. [Verified-in-code]

## 3. Candidate public evaluation sets (read 2026-11-05)

Licences are what the landing page printed. "Split" and "overlap" columns say what was stated, not what is true. Nothing here is approved for use; each needs the rights ledger of the [dysfluency protocol §2](2026-11-03-dysfluency-fidelity-evaluation-protocol.md) before any download.

| Set (landing page) | Languages of interest | Licence | Split policy as stated | Speaker / text overlap risk |
| --- | --- | --- | --- | --- |
| [FLEURS card](https://huggingface.co/datasets/google/fleurs); [paper abstract](https://arxiv.org/abs/2205.12446) | `fa_ir`, `cmn_hans_cn`, `en_us` confirmed; `hi_in`, `ta_in`, `ru_ru` seen only as class labels | CC BY 4.0 (card YAML) | `train`/`validation`/`test`; test sizes seen: en_us 647, fa_ir 871, cmn_hans_cn 945; others not read [Verified-primary-source] | Speaker overlap **not stated** [Unknown]; whether speaker IDs are exposed is not established, which decides whether block bootstrap is possible. Built on FLoRes-101 and n-way parallel, so one sentence recurs across languages [Verified-primary-source] |
| Common Voice Scripted Speech via [Mozilla Data Collective](https://datacollective.mozillafoundation.org/datasets/cmj8u3phw00i1nxxbobq9c583) (search-result summary), [terms](https://commonvoice.mozilla.org/terms/en.html), [cv-dataset repo](https://github.com/common-voice/cv-dataset) | All five plus English are plausible; per-language presence **not individually verified** | CC0 by terms; users asked not to re-host or mirror; dataset pages reportedly bar attempts to identify speakers [Verified-primary-source, second hand] | Official per-language train/dev/test; 295 languages, latest v27.0 (repo page). Since Oct 2025 distribution is through MDC only (HF card notice) | Speaker-disjointness **not confirmed** by anything read [Unknown]; sentence reuse across splits [Unknown]. `accents` metadata column [Assumption from prior knowledge, verify per release] |
| Common Voice Spontaneous Speech v5.0, Code Switching (cv-dataset repo) | SPS: 80 languages, list not read; CS: "Alpha", **no releases** | as above | Unread | Verify per language before any use [Unknown] |
| [MLS (OpenSLR 94)](https://www.openslr.org/94/) | None of the five (en, de, nl, es, fr, it, pt, pl) | CC BY 4.0 | train/dev/test, limited-supervision subsets | Not usable for this note; relevant only as leakage evidence (§5) |
| [AISHELL-1 (OpenSLR 33)](https://www.openslr.org/33/) | Mandarin | Page prints "Apache License v.2.0" **and** "free for academic use": ambiguous, needs maintainer reading | 400 speakers "from different accent areas"; split sizes, hours and script **not stated** on the page | Speaker-disjointness not stated [Unknown]; regional-accent subset needs a metadata field the page does not describe |
| [ASCEND](https://huggingface.co/datasets/CAiRE/ASCEND); [abstract](https://arxiv.org/abs/2112.06223) | Mandarin-English code-switch | CC BY-SA 4.0 (ShareAlike reaches derived manifests) | 8:1:1 train/validation/test (9,869/1,130/1,315 utterances), gender-balanced; 10.62 h | Speaker disjointness not found. Abstract says 23 speakers, card field `original_speaker_id` spans 1-26: unresolved. 23-26 speakers is far under the §7 floor. Repo already used its test split in [han_script.py](../../src/yazses/postprocess/han_script.py) |
| [MUCS 2021 sub-task 2 (OpenSLR 104)](https://www.openslr.org/104/) | Hindi-English (and Bengali-English) | CC BY-SA 4.0 | Train 89.86 h, test 5.18 h, plus a blind test | Transcript script **not stated**; no citation on page; speakers not read [Unknown] |
| [IndicVoices](https://huggingface.co/datasets/ai4bharat/IndicVoices) | Hindi, Tamil only implied (22-language claim) | CC BY 4.0, **gated** (must share HF info) | Splits not described; 11.2K h transcribed; 51K speakers; 76 % extempore | Gating is a maintainer decision (egress/identity); no test-set description |
| [Neyshekar](https://arxiv.org/abs/2609.14542) (submitted 2026-09-13) | Persian read speech | CC0 per abstract | 99.02 h, 190 contributors; text-disjoint test subset; speaker-disjoint partition claimed and "auditable" [Upstream-claim] | Per-split counts and audio hosting not read. Very new, so a model released before it is less likely to contain it, but earlier versions are [Unknown] |
| [Golos](https://github.com/salute-developers/golos) | Russian | **Not readable**: page links licence PDFs only | not stated | Excluded until the licence is read |
| [L2-ARCTIC](https://psi.engr.tamu.edu/l2-arctic-corpus/) | English accents: Hindi, Korean, Mandarin, Spanish, Arabic, Vietnamese L1 | CC BY-NC 4.0 | 24 speakers, 4 per L1, about 1 h each | **4 speakers per L1**: accent contrasts can only be descriptive. Non-commercial: local use only, never committed. [Assumption] on whether that is compatible with an Apache-2.0 project's evaluation |

Excluded after a search summary only (not read): single-speaker or non-commercial Persian sets (a CC BY-NC Bible set and a one-speaker CC BY set) fail the speaker-block and licence rules. There is **no public Tamil code-switch or Persian-English speech set** in what was read [Unknown beyond this search]. Search recall is not a survey.

## 4. Training-data leakage by engine family

A corpus licence says nothing about whether a pretrained model saw it. Rule from #793 §3 stands: a model scored on a corpus from its training family is labelled **possibly in-domain**, never "zero-shot".

| Family | What upstream says | What is unknown |
| --- | --- | --- |
| Whisper (`small`, `large-v3`, `large-v3-turbo`) | Paper ([abstract](https://arxiv.org/abs/2212.04356)) 680,000 h; the HTML text reads "zero-shot ... without using any of the training data for each of these datasets" for its evaluation sets, with Common Voice 9 and FLEURS among them, and de-duplicates "at a transcript level" against evaluation sets, naming TED-LIUM 3 only (§2.1). `large-v3` card: 1M h weakly labelled plus 4M h pseudo-labelled by `large-v2` [Verified-primary-source, paper read as HTML summary, not in full] | The sentence means the benchmark's own training split was not used for fine-tuning. It is **not** a statement that the pretraining pool excludes CV/FLEURS test audio or text, and no overlap analysis for them was found. Hours per language for fa/zh/hi/ta/ru were not found. The `large-v3` card names no source corpora [Unknown] |
| Parakeet TDT 0.6B v3 | Card: 25 languages incl. Russian, none of fa/zh/hi/ta; trained on NeMo ASR Set 3.0 (incl. Multilingual LibriSpeech, Common Voice v7.0) plus 660,000 h Granary pseudo-labels; evaluated on FLEURS, MLS, CoVoST; "automatically detects the language"; CC-BY-4.0 [Verified-primary-source] | Card states no decontamination. MLS and Common Voice are in training **and** MLS is an evaluation set: those cells are in-domain. Which Common Voice clips overlap later releases is [Unknown] |
| Moonshine, Parakeet v2, `.en`/Distil checkpoints | English-only per model cards cited in [capability.py](../../src/yazses/language/capability.py) | Multilingual cells are `unsupported` by construction (§8) |
| Community fine-tunes | `steja/whisper-small-persian` was trained on Common Voice 11 `fa` ([benchmarks.md](../../docs/benchmarks.md), [Verified-in-repo]); the same page says overlap with the CV17 test split "has not been checked" | Any CV `fa` test number for it is in-domain |

Controls (all [Assumption]): keep a leakage register row per (engine, corpus); prefer corpora released after the model's training cut-off (Neyshekar-type sets) as the leakage-resistant slice; add a **private-free fresh slice** (§9) written for this study; report in-domain-possible and fresh slices side by side, never pooled. A large gap between them is evidence of exposure, not proof.

## 5. Per-language normalisation traps

The rule from #793 stands: score twice, **raw** and **evaluation-normalised**, pin the normaliser name and version per cell, and never apply a production cleaner to a reference. A lowercasing fallback is forbidden.

**Whisper `BasicTextNormalizer`** (source read on 2026-11-05 as a summary; verify by running it): NFKC, deletes bracketed text, and replaces every character whose Unicode category starts with M, S or P by a space. With `remove_diacritics=True` it deletes Mn and spaces Mc/Me. ZWNJ (category Cf) passes through. [Verified-primary-source] Consequences: Devanagari and Tamil vowel signs are Mc/Mn marks, so the normaliser can **split an Indic word at its vowel sign**, which changes both WER tokens and reference length for Hindi and Tamil. [Assumption: implied by the category rule; test with a Hindi and a Tamil sentence before use] Do not use it for hi/ta unless a test shows otherwise; pin NFC plus whitespace only and report CER over extended grapheme clusters beside WER.

| Language | Trap | Rule |
| --- | --- | --- |
| Persian | Arabic Yeh U+064A / Alef Maksura U+0649 vs Farsi Yeh U+06CC; Arabic Kaf U+0643 vs Keheh U+06A9; ZWNJ U+200C meaningful; digits in three forms; bidi controls | Use `fa-eval-v1` (NFC, Yeh/Kaf mapping, whitespace; ZWNJ and digits kept; no tashkeel/tatweel stripping) [Verified-in-repo, spec §6]. Keep it separate from the production [persian_text.py](../../src/yazses/postprocess/persian_text.py), which does NFC, boundary-ZWNJ strip, ZWNJ-run collapse, Yeh/Kaf mapping, bidi strip and protected URL/path spans, and deliberately no digit conversion or half-space insertion [Verified-in-code]. Report ZWNJ preservation on its own: repo data show 0 of 1,435 FLEURS reference half-spaces emitted by any measured model, while the CV `fa` references contain none, so the two corpora disagree on convention and cannot be pooled [Verified-in-repo] |
| Mandarin | Simplified vs Traditional output; full-width punctuation; Arabic vs Han numerals; no word spaces; Latin words inside Han text | Score **CER over code points** (the Whisper paper also uses CER for Chinese, Japanese, Thai, Lao, Burmese [Verified-primary-source]). Pin the reference script (FLEURS `cmn_hans_cn` is Simplified by config name; AISHELL-1 page does not say). Report both as-typed CER and script-normalised CER: [han_script.py](../../src/yazses/postprocess/han_script.py) records 35.9 % vs 16.9 % on 20 ASCEND utterances, so over half of that error was wrong-script rendering [Verified-in-code docstring; a docstring figure, not a re-run]. [cjk.py](../../src/yazses/postprocess/cjk.py) does not segment words; do not score Mandarin WER. Cantonese is out of scope (refused by `profiles.py`) |
| Hindi | Devanagari vs romanised ("Hinglish") spelling of the same word; Devanagari vs Latin digits; nukta and chandrabindu variants | Pin one reference script policy per corpus; MUCS script is unstated, so read the files first. Transliteration-tolerant scoring is a secondary, labelled number only [Assumption] |
| Tamil | Agglutinative long tokens (WER inflates, CER does not); Tamil numerals; vowel signs as above | Primary CER over grapheme clusters, WER secondary [Assumption] |
| Russian | `ё`/`е`; case; numerals | Pin whether `ё` is folded; keep Latin-in-Cyrillic as a separate preservation count [Assumption] |
| All | FLEURS has `transcription` and `raw_transcription` and the card does not say how they differ | Pin which field is the reference, record its SHA-256, and score a sample under both before choosing [Verified-primary-source for the fields; Unknown for the difference] |

## 6. Code-switch measurement

Reuse `fa-en-cs-v1` unchanged for Persian-English and extend by version, not by edit: the 6 categories, script-based token tags (`fa`/`en`/`mixed`/`neutral`), zero-denominator = `null` not 0, pooled counts, seeded prompt-id split, and aggregate-only submission [Verified-in-repo]. A change is a new protocol id.

- **MER** for zh-en: tokens are Han characters and whitespace-delimited Latin words; ASCEND's abstract reports both CER (22.69 %) and "mixed error rate" (27.05 %) for its wav2vec 2.0 baselines [Upstream-claim; the page gives no definition, so this note defines it]. Persian-English MER stays whitespace-token (spec §8). Never compare MER across pairs. [Assumption]
- **Per-language WER/CER:** attribute each aligned reference token to its script tag and report the Han/Devanagari/Perso-Arabic part and the English part separately, plus overall MER. Script tag is a proxy, not language ID: English written in the native script counts as an error and is also counted as `transliteration_rate`. Romanised Hindi is tagged English by script, so Hindi-English needs a human-checked reference policy first. [Assumption]
- **Boundaries:** boundary error rate, recall and precision as in the spec; a hypothesis with no switch where the reference has several is a high-recall-of-nothing case, so always show precision on switch-free control prompts.
- **Decoder setting is part of the arm:** a fixed `[stt] language`, or auto-detect, is a different arm. Whisper takes one language per call, so a fixed `zh` arm can transliterate English and an auto arm can pick the wrong language; report both. [Assumption]
- **What can be measured today:** only the stock decoder, since `[polyglot]` is not wired. Any adapter result is a later protocol version. [Verified-in-code]
- **#258 (code-switching vs accent as the dominant failure) is a hypothesis this note does not test.** Testing it needs a within-speaker paired design: the same speakers read matched monolingual and mixed prompts, so accent and switching effects are separable. Public sets here cannot do that (ASCEND and MUCS have no monolingual twin per speaker). [Assumption]
- **Sets:** ASCEND (zh-en, CC BY-SA, ~23-26 speakers), MUCS sub-task 2 (hi-en), and fresh prompts (§9). No public ta-en or fa-en speech set was found. Common Voice Code Switching has no release.

## 7. Statistics: intervals and minimum sizes

1. **Unit is the speaker block.** Pooled edit counts; paired speaker-block bootstrap, 10,000 replicates, recorded seed, percentile 95 % (#793 §6; [Liu & Peng, INTERSPEECH 2020](https://ai.meta.com/research/publications/statistical-testing-on-asr-performance-via-blockwise-bootstrap/) [Upstream-claim]). [Bisani & Ney, ICASSP 2004](https://doi.org/10.1109/ICASSP.2004.1326009) introduced bootstrap CIs for WER; a search summary (abstract not opened) says sentence-level resampling gave narrower intervals than speaker-level, which is the anti-conservative direction to avoid [Upstream-claim, second hand].
2. **Proportions** (exact match, ZWNJ preservation, script-collapse, refusal and coverage rates, boundary matches): Wilson or Jeffreys interval, not Wald; [Brown, Cai & DasGupta, Statistical Science 16(2), 2001](https://doi.org/10.1214/ss/1009213286) recommend them for n up to 40 and report erratic Wald coverage [Upstream-claim, via search summary; landing page did not load].
3. **Sample-size arithmetic** (normal approximation, illustration only, no data behind it): a proportion near 0.5 needs about 385 items for +/-5 points (1.96^2 x 0.25 / 0.05^2); one near 0.1 needs about 138 for +/-5 points. Speakers needed for a WER difference scale as (1.96 x SD_speaker / half-width)^2: if the between-speaker SD of per-speaker WER were 15 points and the target half-width 3 points, that is about 96 speakers. The SD must come from a dev-half pilot; the 15 is a placeholder. [Assumption]
4. **Floors proposed here** (engineering, not from a source): at least 30 speakers and 2,000 reference tokens per reported cell for an inferential claim; below that, print the point value labelled "indicative" with n. At least 20 prompts per code-switch category, inherited from `fa-en-cs-v1` §3. ASCEND (~23-26 speakers) and L2-ARCTIC (4 speakers per L1) are below the floor for accent or language contrasts. [Assumption]
5. If a corpus exposes no speaker ID (FLEURS: unknown), CIs are labelled **utterance-level, anti-conservative**, and no engine ranking is drawn from overlapping or near intervals.
6. **Multiplicity:** primary comparison = one baseline vs one candidate per language, declared before scoring; language x engine x slice grids are exploratory. Compare engines within a language only. Cross-language comparison of WER or CER is descriptive and never ranks languages. [Assumption]
7. Dev/test halves by seeded prompt-id hash as in `fa-en-cs-v1` §6; speaker-level split wherever speakers are known.

## 8. Failure accounting for engines that refuse or mishandle a language

Extends #793 §5/§8 and the v1 row `status` field. A cell is first classified by the **capability table verdict**, not by what the engine printed.

| Case | Row status | Scored? | Reported as |
| --- | --- | --- | --- |
| `check()` = `unsupported` (e.g. Parakeet v3 on `fa`; any `.en`/Distil checkpoint on a non-English language) | `unsupported` | **No.** Not 0 %, not 100 % | Coverage cell "N/A: unsupported", with the cited source URL |
| Engine does not refuse and silently decodes another language (Parakeet v3 auto language detection; faster-whisper forcing `en`; Distil-`large` multilingual tokenizer) | `unsupported` by verdict | No | Separate **silent mis-transcription rate** = share of utterances whose output script does not match the reference script, as an exposure diagnostic only |
| `check()` = `unknown` (custom hub id or local path) | `unknown` | Only as a labelled exploratory arm | Excluded from any ranking or support statement |
| Verdict `supported`, engine ran, output in the wrong script/language | `ok` + `language_collapse` flag | **Yes**, as ordinary S/D/I | WER/CER plus collapse rate with Wilson interval; never trimmed |
| Fallback to another engine, load failure, timeout, crash, missing file | `fallback`/`load_failure`/`timeout`/`crash`/`missing` | No silent skip | Failure rate beside accuracy; matched-subset sensitivity run |
| Memory gate (a fit/convert limit, as in the `large-v3` 5.2 GB < 6.0 GB skip in [benchmarks.md](../../docs/benchmarks.md)) | `skipped` with reason | No | "Not measured on this host", never a score |

Accuracy is compared only on the pre-registered completed set; coverage is a separate column. A language with no scored engine appears as an empty row with reasons, not as a missing row.

## 9. Private-free synthetic and consented evaluation (no real user audio)

AGENTS.md forbids sending real audio, transcripts, voiceprints or participant data to a third-party coding tool; this procedure keeps the coding agent on text, code and aggregates. [Verified-in-code, AGENTS.md]

1. **Text-first fixtures (agent may work on these).** Invented sentences dedicated CC0, per language and per code-switch category, as in `fa-en-cs-v1` §4: no names, accounts or private messages. Scorer unit tests run on text pairs only (the ZWNJ, Han-script, mark-splitting, empty-output, unsupported-cell vectors of §5/§8). Counts in the fixture are test vectors, never results.
2. **Synthetic audio.** Optional: render the fixtures with a locally run text-to-speech model whose licence and training-data provenance were read first. No TTS model was evaluated in this note [Unknown]. Synthetic speech measures the pipeline, normaliser and failure accounting, not human accent or spontaneous behaviour, and must be labelled `synthetic` in `study_mode`.
3. **Public audio** only after the rights ledger (§3 caveats), downloaded by the human operator in a separate preparation step, then run offline per #793 §4.
4. **Consented read prompts (human-run, local).** Adult volunteers read the CC0 prompts; written consent first, using the `fa-en-cs-v1` §5 template, which is still marked **DRAFT, owner review required**. Pseudonymous codes, option A (aggregate only) as default, audio kept on the collector's machine, deleted on a stated date. Only error counts per category leave the machine; the agent sees the aggregate JSON. Product QA consent is not research consent (ADR-v2-150 as cited in #793).
5. **Accent slices without labelling people.** Prefer public accent-labelled corpora (L2-ARCTIC locally only). For consented speakers, record self-declared first language as an optional field, never inferred, and never report a group with fewer than the §7 floor as a finding. One person recording alone is one speaker: no inferential claim.
6. **Fresh slice.** Prompts and recordings made for this study after the model snapshot are the leakage-resistant slice for §4.

## 10. Protocol checklist

- [ ] Pre-register languages, engines, corpora, slices, normaliser ids, bootstrap unit/seed, failure policy before scoring.
- [ ] Rights ledger per corpus (licence, owner, redistribution, speaker-identification limits); stop on any uncertainty.
- [ ] Capability verdict recorded per (engine, model, language) from `check()`, with source URL and date.
- [ ] Resolved engine/model and weight SHA-256 asserted; fallback invalidates the cell.
- [ ] Reference field and script pinned per corpus; sample scored under both FLEURS fields.
- [ ] Normaliser tested on a Hindi, a Tamil, a Persian-ZWNJ and a Han-script vector before use; Whisper `BasicTextNormalizer` not used for hi/ta without that test.
- [ ] Raw and normalised scores both reported; script-collapse and ZWNJ/Han-script preservation reported separately.
- [ ] Leakage register filled; possibly-in-domain cells labelled; fresh slice reported alongside.
- [ ] Speaker IDs present, else CIs labelled utterance-level; floors of §7 applied.
- [ ] Code-switch: MER, per-language error, boundary metrics, transliteration rate, fixed-language and auto-detect arms.
- [ ] Unsupported/unknown/refused cells shown as N/A with reasons; coverage column present.
- [ ] Public scorer and row-level counts for licensed-public or synthetic data; no private archive as sole source (ADR-033).
- [ ] No audio, transcript or participant data in any commit, issue or agent prompt.

## 11. What this protocol cannot show

- Whether any engine "supports" a language for real dictation: read or prompted speech is not spontaneous, noisy, microphone-varied use.
- Whether a model was or was not trained on a test item. Controls reduce and expose the risk; they cannot remove it.
- Per-accent or per-dialect performance from corpora with a handful of speakers per group, or from self-declared labels.
- Real user error cost: a lower CER does not mean fewer corrections, and typing into applications (Wayland, Windows Unicode injection) is a separate measurement.
- Cantonese, dialects, or any language whose corpus licence or script policy was not read here.
- Latency or memory: this note adds no timing method beyond #793.
- Anything about `[polyglot]` adapters, which do not exist yet.
- Cross-language ranking: different corpora, scripts and metrics make a WER of one language non-comparable with another.

## 12. Open questions for the maintainer

1. Is a CC BY-SA corpus (ASCEND, MUCS) acceptable as a local evaluation input given that ShareAlike reaches published manifests derived from it?
2. Is AISHELL-1's "Apache-2.0" or "academic use" reading controlling?
3. Does the maintainer accept IndicVoices' gating, and L2-ARCTIC's non-commercial licence, for local-only runs?
4. Should the private `benchmark/` scorers be re-implemented publicly before any #797 number is quoted (ADR-033 point 2)?
5. Review and release of the DRAFT consent template before any recording.

## Sources (read 2026-11-05, not read in full unless stated)

FLEURS [card](https://huggingface.co/datasets/google/fleurs) (first 100,000 characters of the raw README only) and [abstract](https://arxiv.org/abs/2205.12446); [Whisper abstract](https://arxiv.org/abs/2212.04356) and HTML text; [whisper-large-v3](https://huggingface.co/openai/whisper-large-v3); [parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3); [Whisper normalizer source](https://github.com/openai/whisper/blob/main/whisper/normalizers/basic.py); [Common Voice terms](https://commonvoice.mozilla.org/terms/en.html) and [cv-dataset](https://github.com/common-voice/cv-dataset); [OpenSLR 94](https://www.openslr.org/94/), [33](https://www.openslr.org/33/), [104](https://www.openslr.org/104/); [ASCEND](https://huggingface.co/datasets/CAiRE/ASCEND); [IndicVoices](https://huggingface.co/datasets/ai4bharat/IndicVoices); [Neyshekar](https://arxiv.org/abs/2609.14542); [L2-ARCTIC](https://psi.engr.tamu.edu/l2-arctic-corpus/); [Golos](https://github.com/salute-developers/golos). Statistics: Liu & Peng, Bisani & Ney, Brown et al. as linked in §7. Repository files cited by relative link. Not fetched successfully: Common Voice main dataset page, the HF Common Voice 17 card (empty, moved to MDC), the Brown et al. landing page.
