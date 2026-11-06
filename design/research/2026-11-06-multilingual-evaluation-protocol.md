# Multilingual evaluation protocol: addendum (metric choice, test vectors, attribution, native review)

**Date:** 2026-11-06
**Status:** Research draft (not a decision). Review pending. ADR-030 freeze unchanged. Makes **no
language-support claim** of any kind.
**Tracking:** [#797](https://github.com/MSKazemi/yazses/issues/797); coordinates
[#503](https://github.com/MSKazemi/yazses/issues/503) and [#505](https://github.com/MSKazemi/yazses/issues/505).
**Base:** main at `8a72bbc6`. Documentation only: no dataset, model or audio was touched and no
score was computed.

## 0. Why this is an addendum and not a new protocol

The #797 protocol already exists:
[2026-11-05 multilingual, accent and code-switch evaluation design](2026-11-05-multilingual-accent-and-code-switch-evaluation-design.md)
(below: **the base note**). It covers the corpus licence audit (§3), leakage (§4), per-language
normalisation traps (§5), code-switch measurement (§6), statistics (§7), failure accounting (§8)
and consent (§9). This file does **not** repeat any of that. It adds the five pieces the base note
leaves open, each found by reading it at `8a72bbc6`:

| Gap in the base note | Where it is left open | Filled here |
| --- | --- | --- |
| No single per-language view of which corpora are licence-read and usable | §3 is organised by corpus | §1 |
| CER vs WER vs MER rules are spread across §5 and §6, and "grapheme cluster" is undefined | §5 rows, §6 bullets | §2 |
| The checklist demands "a Hindi, a Tamil, a Persian-ZWNJ and a Han-script vector" but defines none | §10, line 133 | §3 |
| Per-language attribution of code-switch errors does not say how insertions are attributed or how alignment ties are broken | §6, line 83 | §4 |
| No native-review gate for **evaluation artefacts** (prompts, references, normaliser rules, adjudication) | not present; the only native-review gates in the tree are product-facing | §5 |

Labels follow the base note: **[Verified-in-repo]** read in this repository at `8a72bbc6`;
**[Verified-primary-source]** read on the cited page on the stated date; **[Upstream-claim]**;
**[Assumption]** a design choice needing review; **[Unknown]**.

## 1. Corpus licensing, per language (index into base note §3)

Read across, not down: "usable for an inferential public number" requires a read licence, a
stated speaker-disjoint test split with speaker IDs, and the §7 floors of the base note (30
speakers, 2,000 reference tokens per cell). Every licence below is what the base note recorded on
2026-11-05; nothing was re-read today.

| Language | Licence-read candidates (licence) | Blocking issue | Usable for an inferential public number today? |
| --- | --- | --- | --- |
| Persian `fa` | FLEURS `fa_ir` (CC BY 4.0); Common Voice `fa` (CC0, no re-hosting); Neyshekar (CC0 per abstract, [Upstream-claim]) | FLEURS speaker overlap/IDs [Unknown]; CV speaker-disjointness [Unknown]; FLEURS and CV disagree on ZWNJ convention and cannot be pooled (base note §5) | **No.** Neyshekar is the most promising (speaker-disjoint claimed) but its splits were not read |
| Mandarin `zh` | FLEURS `cmn_hans_cn` (CC BY 4.0); AISHELL-1 (page says both Apache-2.0 and "free for academic use") | AISHELL-1 licence ambiguous (owner question 2 in base note §12); FLEURS speakers [Unknown] | **No** |
| Mandarin-English | ASCEND (CC BY-SA 4.0) | 23-26 speakers, under the floor; ShareAlike reaches derived manifests | **No** (indicative only) |
| Hindi `hi` | FLEURS `hi_in` (class label only); IndicVoices (CC BY 4.0, **gated**) | IndicVoices gating = sharing account data with a host, a maintainer decision; no test split described | **No** |
| Hindi-English | MUCS 2021 sub-task 2 (CC BY-SA 4.0) | Transcript script unstated (Devanagari vs romanised decides the metric, §2) | **No** |
| Tamil `ta` | FLEURS `ta_in` (class label only); IndicVoices (gated) | as Hindi | **No** |
| Russian `ru` | FLEURS `ru_ru` (class label only); Common Voice `ru` (presence not individually verified) | Golos licence unreadable (excluded) | **No** |
| English accents | L2-ARCTIC (CC BY-NC 4.0) | 4 speakers per L1; non-commercial, local only | **No** (descriptive only) |
| Persian-English, Tamil-English | none found | no public speech set | Fresh consented slice only (base note §9) |

Consequence [Assumption]: under this protocol **no language currently has a public evaluation set
that can back an inferential claim**. The cheapest unblock per language is a maintainer licence
reading (AISHELL-1, IndicVoices gating), not more search.

## 2. Primary metric per script

One metric is **primary** per (language, corpus) cell and is pre-registered; the others are
reported beside it and never substituted after scoring. [Assumption: all rows are design choices
except where marked]

| Script / pair | Primary | Secondary | Never | Unit definition |
| --- | --- | --- | --- | --- |
| Latin (`en`), Cyrillic (`ru`) | WER | CER (code points) | — | whitespace tokens after the pinned normaliser |
| Perso-Arabic (`fa`) | WER over whitespace tokens, ZWNJ **inside** a token (as `fa-eval-v1`, [Verified-in-repo, `design/specs/persian-benchmark-and-validation.md` §6]) | CER (code points); ZWNJ preservation as a proportion | a WER that splits on ZWNJ | `می‌خواهم` is **one** token; `می خواهم` is two |
| Han (`zh`) | CER over code points, whitespace deleted from both sides | script-normalised CER (base note §5) | WER (`cjk.py` does not segment) | one Han character = one unit; Latin letters in Han text count one unit each |
| Devanagari (`hi`) | WER | CER over **extended grapheme clusters** | CER over code points as the only CER | see grapheme note below |
| Tamil (`ta`) | CER over extended grapheme clusters | WER | — | agglutination inflates WER (base note §5) |
| `zh`-`en` mixed | MER | per-language CER (Han part) and WER (Latin part), §4 | pooled CER that splits English words into letters as the headline | token = one Han character **or** one whitespace-delimited Latin word |
| `fa`-`en` mixed | MER over whitespace tokens (`fa-en-cs-v1` §8) | per-language WER, §4 | — | as `fa-en-cs-v1`, unchanged |
| `hi`-`en` mixed | MER over whitespace tokens, **only after** a native-reviewed reference script policy (§5) | per-language WER | any score while the reference script is unknown | — |

**Grapheme clusters are version-dependent.** The extended-grapheme-cluster rule GB9c
(`\p{InCB=Linker} \p{InCB=Extend}* × \p{InCB=Consonant}`, "do not break within certain
combinations with Indic_Conjunct_Break=Linker") keeps virama conjuncts such as क्ष together, and
UAX #29 revision 49 (Unicode 18.0.0, dated 2026-09-01) *changed* GB9c again
[Verified-primary-source, <https://www.unicode.org/reports/tr29/>, read 2026-11-06]. The property
was introduced in Unicode 15.1 [prior knowledge, not re-read today]. So the same Hindi string has a
different cluster count under different Unicode data, and a grapheme CER is reproducible only if
the segmenter **and its Unicode version** are pinned in the result row (e.g. the segmenting
library's version plus the Unicode version it reports). Which scripts carry InCB=Linker is in the
Unicode Character Database, not in UAX #29; whether Tamil is covered was not read [Unknown], so the
Tamil vectors in §3 must be checked against the pinned segmenter, not against this note.

**Han CER whitespace rule.** Han references carry no word spaces, while hypotheses with embedded
English do. Deleting all whitespace (Unicode `White_Space`) on both sides before CER makes the
metric insensitive to spacing around Latin words; spacing is then measured only by MER. This is
a pinned choice, not a standard; ASCEND's own CER/MER definitions were not stated on the page the
base note read [Unknown].

## 3. Normaliser and scorer test vectors

The base note's checklist (§10) requires a normaliser to pass a Hindi, Tamil, Persian-ZWNJ and
Han-script vector before use. These are those vectors. They are **text-only, invented, CC0**, so
they may be committed and run by a coding agent (AGENTS.md: no real audio or transcripts). Each
expected value is what the protocol **requires**, not what any current code does; a scorer that
disagrees fails the pre-flight. Code points are given so the vectors survive editors that
normalise silently.

| # | Language | Reference | Hypothesis | Required result |
| --- | --- | --- | --- | --- |
| P1 | fa | `می‌خواهم` (U+0645 U+06CC U+200C U+062E U+0648 U+0627 U+0647 U+0645) | identical | WER 0, CER 0, ZWNJ preserved 1/1 |
| P2 | fa | as P1 | `می خواهم` (ZWNJ → U+0020) | `fa-eval-v1` WER = 1 S + 1 I over 1 ref token (= 2.0); CER = 1 S over 8 code points; ZWNJ preserved 0/1 |
| P3 | fa | as P1 | `میخواهم` (ZWNJ deleted) | WER 1 S; CER 1 D; ZWNJ preserved 0/1 |
| P4 | fa | `کتاب` (U+06A9 …) | `كتاب` (Arabic Kaf U+0643) | raw CER 1 S; `fa-eval-v1` CER 0 (Kaf mapped) |
| P5 | fa | `یک` with Farsi Yeh U+06CC | same word with Arabic Yeh U+064A | raw CER 1 S; `fa-eval-v1` CER 0 |
| P6 | fa | `۱۲` (U+06F1 U+06F2) | `12` (Latin) | `fa-eval-v1` does **not** fold digits [Verified-in-repo, spec §6]: CER 2 S; reported also as digit-form mismatch |
| P7 | fa | `سلام` | `سلام` preceded by U+200F (RLM) | raw CER 1 I; `fa-eval-v1` CER also 1 I, because it does **not** strip bidi marks [Verified-in-repo, `design/specs/persian-benchmark-and-validation.md` §6]. Production `persian_text.py` would not remove this mark either: its strip covers only embeddings/overrides U+202A-U+202E and isolates U+2066-U+2069, not RLM/LRM [Verified-in-repo, `src/yazses/postprocess/persian_text.py:58`]. Any change is a new normaliser id |
| H1 | zh | `我们` (U+6211 U+4EEC, Simplified) | `我們` (U+6211 U+5011, Traditional) | as-typed CER 1/2; script-normalised CER 0 |
| H2 | zh | `你好。` (U+3002) | `你好.` (U+002E) | punctuation-removed CER 0; raw CER 1 S. NFKC does **not** fold U+3002 to U+002E, but does fold full-width U+FF0C to U+002C [Verified locally 2026-11-06: CPython `unicodedata` (Unicode 15.0.0) maps `"。，"` to `"。,"` under NFKC] — so punctuation must be removed by an explicit rule, never by relying on NFKC |
| H3 | zh | `二十` | `20` | CER 2 S; counted also as numeral-form mismatch; no numeral folding in the primary metric |
| H4 | zh-en | `我用 Python 写` | `我用Python写` | CER 0 (whitespace deleted); MER 0 (tokens: 我/用/Python/写 on both sides) |
| H5 | zh-en | as H4 | `我用 派森 写` | MER 1 S + 1 I over 4 tokens; `transliteration_rate` 1/1 English tokens (base note §6) |
| D1 | hi | `कि` (U+0915 U+093F) | `क` | code-point CER 1 D over 2; grapheme CER 1 S over 1 cluster |
| D2 | hi | `क्ष` (U+0915 U+094D U+0937) | `क` | grapheme count of the reference is 1 under GB9c-aware data, 2 otherwise: the row must record which (§2) |
| D3 | hi | Whisper `BasicTextNormalizer` on `किताब` | — | must not split the word at U+093F; if it does, the normaliser is rejected for `hi` (base note §5 [Assumption] made testable) |
| T1 | ta | `கா` (U+0B95 U+0BBE) | `க` | grapheme CER 1 S over 1 cluster |
| T2 | ta | Whisper `BasicTextNormalizer` on `தமிழ்` | — | as D3 for Tamil |
| E1 | any | non-empty | empty string | CER/WER = 1.0 (all deletions); row `status` = `ok`, never dropped |
| E2 | any | empty reference | non-empty | per-cell rate is `null` (zero denominator, as `fa-en-cs-v1`), insertions counted in the pooled numerator |

Expected numbers for P2/P3 assume Levenshtein with unit costs and the tie-break in §4.

## 4. Code-switch error attribution (closes base note §6, line 83)

Per-language rates depend on the alignment, and unit-cost Levenshtein often has several optimal
alignments. To make per-language numbers reproducible [Assumption]:

1. **Tokenise** per §2, then tag each token by script (`fa-en-cs-v1` tags: `fa`/`en`/`mixed`/
   `neutral`, extended with `zh` and `hi` by the same rule). The tag is a script proxy, not
   language identification.
2. **Align** with unit costs and a fixed tie-break: prefer match, then substitution, then
   deletion, then insertion, scanning from the end of both sequences. Pin the library and version
   that produce the alignment; if it cannot honour the tie-break, record its own and do not
   compare across libraries.
3. **Attribute:** a match, substitution or deletion belongs to the **reference** token's tag; an
   insertion belongs to the **hypothesis** token's tag; a `neutral` insertion (digits,
   punctuation that survived) goes to an `unattributed` bucket that is reported, never dropped.
4. **Denominator:** reference tokens of that tag. Per-language rates therefore do not sum to MER
   (insertions and `unattributed`), and the report says so.
5. **Script mismatch:** a substitution whose reference tag differs from the hypothesis tag is
   counted once in the reference language's errors and once in `transliteration_rate` (base note
   §6); it is not double-counted in MER.

## 5. Native-review gate for evaluation artefacts

**What exists:** product-facing native review only. Chinese phrase/usability review needs an
independent native reviewer for Simplified and for Traditional
(`design/chinese/2026-10-29-validation-and-release-gates.md:85-93`); Persian usability testing asks
for at least three native speakers (`design/specs/persian-benchmark-and-validation.md:271-287`);
localisation pages have a reviewer column (`docs/localization/STATUS.md`). None of these covers the
artefacts an accuracy number is computed **from**. Because a reference with a wrong orthographic
choice turns a correct hypothesis into an error, those artefacts need their own gate. [Verified-in-repo for what exists; Assumption for the gate]

### 5.1 Artefacts that need native review before a number is quoted

| Artefact | Why a non-native check is not enough | Minimum review [Assumption] |
| --- | --- | --- |
| Prompt sets / fresh-slice prompts (base note §9) | naturalness, register, unintended offensive or identifying content | 1 reviewer; 2 for a set backing a public number |
| Reference transcripts of consented recordings | spelling convention (ZWNJ, Yeh/Kaf, Simplified/Traditional, Devanagari vs romanised) decides the score | 2 independent reviewers; disagreements adjudicated and logged |
| Reference script/convention policy per corpus (FLEURS `transcription` vs `raw_transcription`, MUCS script, CV `fa` ZWNJ absence) | a policy choice, not a fact in the data | 1 reviewer signs the written policy before scoring |
| Evaluation normaliser rules (`fa-eval-v1` mappings, Han script mapping, digit policy, `ё` folding) | a rule can silently erase a meaningful distinction | 1 reviewer per language signs the rule list and the §3 vectors |
| Code-switch category and script-tag adjudication (loanwords, brand names, transliterations) | the tag decides which language an error is charged to | 1 reviewer; a disputed token goes to `mixed`, not to a guess |
| Error-category adjudication on a sample of hypotheses ("acceptable variant" vs error) | only a fluent reader knows whether two spellings are both standard | 2 reviewers, blind to engine identity; report agreement (Cohen's kappa) with n |

### 5.2 Rules

1. **Who counts.** A reviewer self-describes competence; it is never inferred from name, location,
   handle or history (rule already in `design/chinese/human-validation-data-protocol.md:74`).
   Machine translation, an LLM, synthetic text or an English maintainer's intuition never counts as
   a reviewer (`design/chinese/2026-10-29-validation-and-release-gates.md:10`). The contributor who
   wrote a prompt set may not be its only reviewer.
2. **What reviewers see.** Text only by default: invented prompts, public-corpus references, and
   hypotheses produced on public or synthetic audio. A hypothesis of a consented speaker is shown
   only if that speaker's consent covers it (the `fa-en-cs-v1` §5 template is still DRAFT, so today
   it covers nothing). No audio is sent to a reviewer by the project.
3. **Blinding.** Adjudication sheets carry an opaque system id; the engine-to-id map is revealed
   after adjudication is frozen.
4. **Before scoring, not after.** References, normaliser rules and script policy are frozen and
   hashed (SHA-256) before the first hypothesis is scored. A later fix is a new artefact version
   and every affected number is re-scored and re-labelled, never patched.
5. **Record.** Each review leaves a row: artefact path, SHA-256, language/locale, reviewer
   pseudonym, self-stated competence, date, decision (`approved`/`changed`/`rejected`), count of
   changes, disagreement count. Pseudonyms only; legal names and emails are never required (as the
   Chinese release gates already say, `design/chinese/2026-10-29-validation-and-release-gates.md:93`).
6. **Effect of a missing review.** A cell whose artefacts lack a review row is labelled
   `exploratory` and cannot appear in `docs/`, a release note, a README or any support statement.
   This is the evaluation-side twin of the localisation rule that a `draft` page carries a visible
   banner.

### 5.3 Current status

No evaluation-artefact review record exists in the tree at `8a72bbc6` (grep for reviewer records
under `design/` finds only the product-facing gates above). Localisation reviewers listed in
`docs/localization/STATUS.md` reviewed translated pages, not evaluation references, and are not
evidence for this gate. Persian, Hindi and Simplified Chinese doc pages are themselves still
looking for reviewers there.

## 6. Recommendation

**Adopt** §2-§5 as an addendum to the base note (or fold them into it in a follow-up owned by its
author); **defer** every multilingual accuracy number until (a) one corpus per language clears
§1, (b) the §3 vectors pass on a public scorer, (c) §5 review rows exist. **Reject** quoting any
per-language rate from an unreviewed reference or an unpinned grapheme segmenter. [Assumption]

## 7. Open questions for the maintainer

1. Accept two-reviewer references (§5.1) as the bar for a public number, or one reviewer plus
   agreement on a double-reviewed sample?
2. `fa-eval-v1` keeps every bidi mark and production strips only U+202A-U+202E and U+2066-U+2069 (vector P7). Should a later evaluation normaliser version strip bidi controls, and if so which set (does it include RLM/LRM/ALM)?
3. Who owns folding this addendum into the base note?
4. The base note's §12 questions (AISHELL-1 licence, IndicVoices gating, CC BY-SA manifests,
   public scorer, consent template) still gate §1.

## Sources

- Base note and repository files as linked, read at `8a72bbc6` on 2026-11-06.
- Unicode Standard Annex #29, *Unicode Text Segmentation*, Unicode 18.0.0, revision 49,
  2026-09-01: <https://www.unicode.org/reports/tr29/> (read 2026-11-06 through a summarising
  fetcher; GB9c text and the revision note only).
- Corpus licences: as recorded in the base note §3 (read 2026-11-05); not re-read here.
