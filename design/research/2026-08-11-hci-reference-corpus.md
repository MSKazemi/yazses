# The YazSes HCI reference corpus — 105 verified references

> **Status:** verified 2026-08-11 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Machine-readable master:** [`hci-corpus.bib`](hci-corpus.bib) (105 entries)
> **Verifier:** [`verify_refs.py`](verify_refs.py) — re-run it after any edit.
> **Tier:** `design/` — **public**. The curated reader-facing subset is
> [`docs/research/hci-canon.md`](../../docs/research/hci-canon.md).

## Why this exists

YazSes competes on being an *interaction design*, not a model wrapper. That is a claim
about a research literature, so it needs one: a single, verified corpus that says what
each result establishes and which design decision it actually drives.

The corpus serves three surfaces at once:

1. **The manuscript.** It supplies the HCI grounding for the Related Work of the YazSes
   paper — the text-entry, mode-error, multimodal and accessibility literature that a
   dictation system should be argued against.
2. **The public research notebook.** `docs/research/` is organised by *modality* (eye /
   voice / muscle-brain) and answers "what can this sensor do". This corpus is organised
   by *argument* and answers "why should the software behave this way".
3. **The agenda.** Knowing what has been measured is what makes it possible to say
   precisely what has not — see [the research agenda](2026-08-11-hci-research-agenda.md).

The organising rule: **every reference carries the claim it supports and the YazSes
surface it lands on**. A reference with neither is not in the corpus.

## The finding this exercise produced

Assembling the corpus made one gap impossible to miss and it is worth stating at the top:

> **YazSes has not yet been evaluated with human participants.**

The project states this openly in the manuscript's Limitations. What the corpus adds is
that the gap is now **costed and methodologically solved** rather than merely
acknowledged: section 10 supplies the protocol, section 3 supplies the prior measurements
a YazSes result would sit beside, and `wobbrock2016researchcontributions` supplies the
vocabulary for what is outstanding (an *artifact* contribution awaiting its *empirical*
counterpart). It moves from "known weakness" to "specified, runnable next study".

Recognition and latency are measured today. Every section below that is about *people* —
sections 2, 3, 7, 8, 10 especially — describes a method YazSes has the instrumentation
for and has never applied. Sections 3 and 10 in particular hand over a ready-made
protocol: `mackenzie2002textentry` + `soukoreff2003metrics` + `wobbrock2006inputstream`
define how input studies report throughput and error, and `karat1999patterns` +
`sears2003handsfree` + `suhm2001multimodal` define what has already been measured for
dictation specifically, so a YazSes study would be directly comparable rather than
free-standing. This is the cheapest publishable contribution available to the project,
and it is direction #1 in
[the research agenda](2026-08-11-hci-research-agenda.md).

## Verification protocol — and what it caught

Every entry was resolved against a live API before it was written down. Nothing here
rests on recall.

- **DOIs → Crossref** (`api.crossref.org/works/<doi>`), sub-second from this sandbox.
- **arXiv → DataCite** (`api.datacite.org/dois/10.48550/arXiv.<id>`) — `export.arxiv.org`
  hangs here and WebFetch on arXiv rate-limits, per the silent-speech sweep.
- Title+author search when a DOI is unknown, scored by normalised similarity against the
  intended title; anything below 0.85 was resolved by hand, not accepted.
- ACM DL stores subtitles separately (`title` = "Put-that-there", `subtitle` = "Voice and
  gesture at the graphics interface"), so the verifier concatenates both — otherwise a
  correct record scores 0.35 and looks like a miss.

### What has and has not been verified — read this before citing

**Done — identity, for all 105.** Title, full author list, year and venue each came back
from Crossref or DataCite. No entry rests on recall.

**Not done — claim-checking against the PDFs.** The "What it establishes" column below is
grounded in the paper *titles*, in the abstract-level content those titles assert, and —
for the ~20 entries shared with `docs/research/` — in the 2026-08-08 sweep that verified
them. It is **not** the page-and-table-level check that the 2026-07-30 audit applied to
the paper's own references (where Whisper's "≈3%" became "2.7%, Table 2").

Consequence: **before any of these numbers or findings enters the manuscript or a public
page, the specific entry must be read at source.** The load-bearing claims are the ones
set in **bold** in the tables below — 33 of the 121 rows. Until an entry has been read,
treat its annotation as a routing label, not as a citable claim.

What already cleared that bar and is safe to quote: the entries carried over from
`docs/research/`, which the 2026-08-08 sweep verified (Ruan's 153/52 WPM, Majaranta's
6.9 → 19.9 WPM, Sugano's 2.9°, Kaifosh's 20.9 WPM, Gaddy & Klein's ≈68% WER, Willett's
62 WPM / 23.8%, Card's 2.5%). The claims used in the manuscript were deliberately kept
to title- and abstract-level statements for the same reason — no unread number was
promoted into the manuscript.

**Result: 104 of 105 confirmed by API.** The exception is `raskin2000humane` (the book is
not in Crossref; recorded at metadata level with the verified ACM *Ubiquity* excerpt
DOI alongside — the same convention the 2026-07-30 audit used for `shostack2014threat`).

**Fifteen entries would have been wrong if written from memory.** This is the case for
never skipping verification:

| Entry | What memory said | What the API says |
|---|---|---|
| `jacob1990midas` | `10.1145/97243.97274` | `10.1145/97243.97246` — the guessed DOI is a *different CHI '90 paper* ("IShell") |
| `schultz2017biosignal` | `10.1109/TASLP.2017.2680867` | `10.1109/taslp.2017.2752365` |
| `monk1986mode` | `…80009-9` | `10.1016/s0020-7373(86)80049-9` |
| `lim2009why` | `10.1145/1518701.1518815` | `10.1145/1518701.1519023` |
| `vertanen2009parakeet` | `10.1145/1502650.1502692` | `10.1145/1502650.1502685` |
| `mackenzie1999softkeyboard` | `10.1145/302979.303005` | `10.1145/302979.302983` (the guess resolves to "Nomadic radio") |
| `poller1984modes` | `…2600406` | `10.1177/001872088402600408` |
| `norman1983designrules` | `10.1145/358584.358598` | `10.1145/2163.358092` |
| `hook2000steps` | `…(99)00021-8` | `10.1016/s0953-5438(99)00006-5` |
| `kristensson2009challenges` | Kristensson, sole author | **Kristensson & Jameson** |
| `trnka2009prediction` | "…on user performance" | "**User Interaction with Word Prediction: The Effects of Prediction Quality**" |
| `koester2006speech` | "Factors that influence… experienced *assistive technology* users" | "…experienced **speech recognition** users" |
| `kaifosh2025neuromotor` | — | title-search returns only the **2024 bioRxiv preprint**; the Nature 2025 version must be fetched by DOI |
| `mackenzie2002textentry` | `10.1207/S15327051HCI172&3_1` | `…172&3_2` — `_1` is the special-issue *introduction*, not the article |
| `nissenbaum2004contextual` | Wash. Law Review article | not in Crossref; replaced with the verifiable 2010 book `10.1515/9780804772891` |

**Edition caveats** (the DOI resolves to a reprint, so cite the original year and say so):
`bush1945` → ACM *interactions* 1996 reprint; `buxton1986chunking` → *Readings in HCI*
1995 reprint; `cardmorannewell1983` → Routledge 2018 reissue; `suchman2007` → Cambridge
online 2006; `nissenbaum2010context` → De Gruyter e-edition dated 2009 (the Stanford
University Press print edition is 2010, which is how it is cited).
`oviatt1997maps` carries a typo in the published record itself
("Mulitmodal") — quote it corrected, and do not "fix" the `.bib`, which mirrors Crossref.

---

## 1. Foundations and theory (13)

Why an input system is judged on time-and-error, not on features.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `fitts1954` | The speed/accuracy law that makes input channels comparable at all | The reason WPM-and-error is the right axis, not "features" |
| `card1978mouse` | The first head-to-head input-device evaluation; the method every later one copies | The template for direction #1's dictation-vs-typing study |
| `card1980klm` | KLM — predicting task time from elementary operators | Lets a hold-to-talk burst be costed against a keystroke sequence *before* a study |
| `cardmorannewell1983` | The founding text: humans as information processors with measurable limits | The frame for the whole corpus (cite 1983; DOI is the 2018 reissue) |
| `fitts1954` / `mackenzie1992fitts` | Fitts' law as a *design* tool, not just a model | How to argue a modality is throughput-limited rather than badly designed |
| `shneiderman1983dm` | Direct manipulation: continuous representation, rapid reversible action, visible effect | Why "scratch that" and undo matter more than command coverage |
| `hutchins1985dm` | Gulf of execution / gulf of evaluation | The theory behind the tray colours: the user must *see* which mode they are in |
| `norman1981slips` | Slips are the errors of skilled users; they follow structure | Directly names the failure the no-text-target guard prevents (direction #9) |
| `buxton1986chunking` | Input as phrases, not atoms; tension delimits a chunk | The strongest theoretical argument for hold-to-talk (cite 1986) |
| `weiser1991` | Computing that recedes into the background | The ambient/meeting-mode framing, and its privacy obligation |
| `suchman2007` | Plans are resources for action, not scripts that determine it | Why a fixed command grammar will always be partial; why dictation is the default path |
| `nielsen1994heuristic` | Heuristic evaluation with explanatory power | Cheap pre-study evaluation before recruiting anyone |
| `bush1945` | The augmentation premise the whole field descends from | Positioning only (cite 1945; DOI is the 1996 reprint) |

## 2. Modes, quasimodes, and activation (7)

**The most under-cited section relative to how load-bearing it is.** Hold-to-talk is a
mode decision, and there is fifty years of literature saying which mode designs fail.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `sellen1992mode` | **Kinaesthetic feedback prevents mode errors where visual feedback does not** | The single best citation for hold-to-talk over toggle-to-talk: the held key *is* the feedback |
| `norman1983designrules` | Design rules derived from human-error analysis | Why the target guard defaults to `clipboard` (recoverable) rather than `off` |
| `monk1986mode` | Mode errors reduced by keying-contingent sound | Precedent for an audible/visible burst cue; ties to the tray's purple command-mode state |
| `poller1984modes` | Measured cost of modes for experienced editor users | Evidence that experts are not immune — relevant to the dedicated `command_key` |
| `buxton1983lexical` | Input structures have lexical and pragmatic structure | The vocabulary for describing the activation seam (direction #3) |
| `kurtenbach1993marking` | Novice/expert continuity in one gesture vocabulary | Model for a command grammar that does not punish the beginner |
| `raskin2000humane` | **Quasimode**: a mode held in place by sustained user action cannot be forgotten | The name for what YazSes does. Book, metadata-level; excerpt DOI `10.1145/341836.342022` |

## 3. Speech as an input channel (14)

What is already measured about dictation — throughput, and the correction cost that eats it.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `ruan2016speech` | **153 WPM spoken vs 52 WPM typed**, same lab, same task | The headline claim; already cited in `docs/research/index.md`. Note: *short messages on phones* — the desktop equivalent is unmeasured |
| `karat1999patterns` | Entry *and correction* patterns in large-vocabulary dictation; correction dominates | The reason raw WPM overstates dictation. The baseline direction #1 must beat |
| `sears2003handsfree` | Hands-free navigation during dictation: difficulties, consequences, solutions | Directly about the navigate-while-dictating problem the command grammar addresses |
| `suhm2001multimodal` | **Multimodal correction beats respeaking** for repairing recognition errors | Evidence for correction-by-another-channel; supports directions #4 and #7 |
| `shneiderman2000limits` | Speech competes with working memory in a way typing does not | The honest limit to put in Limitations — and why dictation ≠ universal replacement |
| `oviatt2000taming` | An interface can absorb recognition error instead of eliminating it | The design stance behind the confirmation model (direction #4) |
| `koester2006speech` | Performance factors for *experienced* speech-recognition users | Longitudinal framing: novice numbers mislead |
| `vertanen2009parakeet` | A deployed continuous-speech system with a correction UI | Closest prior art to YazSes as an interactive system |
| `kristensson2009challenges` | Five open challenges for intelligent text entry (Kristensson **& Jameson**) | A ready-made gap list to position against |
| `radford2023whisper` | Whisper; weak supervision, robust transfer | The engine; already cited by the manuscript |
| `baevski2020wav2vec2` | Self-supervised speech representations | Background for the pluggable engine seam |
| `gulati2020conformer` | Conformer — the architecture behind current CPU-viable transducers | Why Parakeet-class models are fast enough to matter |
| `graves2012transducer` | RNN-T: streaming-capable transduction | The theory under the streaming path |
| `panayotov2015librispeech` | LibriSpeech | The paper's WER benchmark; already cited |
| `gaddy2020voicing` | **Open-vocabulary silent speech ≈68% WER** | The number that forces silent *commands* + spoken prose |

## 4. Multimodal fusion and deixis (11)

The lineage `gaze/deixis.py` belongs to — and the evidence for what fusion buys.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `bolt1980` | **Put-That-There**: speech carries the verb, pointing carries the referent | The direct ancestor of "close this"/"focus that window". Direction #7 is its replication on a webcam |
| `oviatt1999myths` | Ten myths — notably that multimodal input is *not* usually simultaneous | Sets the timing tolerance the deixis snapshot needs |
| `oviatt2004when` | Users go multimodal **under cognitive load**, not uniformly | Predicts when gaze routing helps and when it is overhead |
| `oviatt1997maps` | Multimodal maps designed for human performance | Method for evaluating fusion (published title carries a typo) |
| `oviatt2000perceptual` | Perceptual UIs: interfaces that process what comes naturally | The framing for the whole v2 cognitive layer |
| `cohen1997quickset` | QuickSet: a working distributed multimodal architecture | Architectural precedent for the modality router (ADR-v2-011) |
| `nigay1993designspace` | A design space for multimodal systems; fusion levels | Vocabulary for early vs late fusion in `modality/router.py` |
| `sharma1998toward` | Survey of multimodal HCI | Positioning breadth |
| `turk2014review` | Modern review of multimodal interaction | The 30-year update, for Related Work |
| `zhai1999magic` | **MAGIC pointing**: gaze coarsely warps, hand commits | Exactly YazSes's split — gaze routes, the key commits |
| `pfeuffer2014gazetouch` | Gaze selects, touch manipulates, on one surface | Second precedent for gaze-as-selector, not gaze-as-clicker |
| `kaur2003whereislinda` | **Event synchronisation in gaze-speech systems** | The empirical answer to *when* to snapshot gaze relative to speech onset |

## 5. Gaze interaction (8)

Why webcam gaze can pick a window and never a character.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `jacob1990midas` | **The Midas touch problem**: gaze without a commit action selects everything | Why `route_dictation` requires the hotkey and never dwell |
| `sibert2000evaluation` | Gaze selection can beat the mouse for coarse targets | The upper bound the zone grid is sized to |
| `majaranta2002twenty` | Twenty years of eye typing: systems and design issues | Survey anchor; already cited publicly |
| `majaranta2009dwell` | Adjustable dwell: 6.9 → 19.9 WPM over ten sessions | The measured ceiling of gaze *as text entry* — i.e. why gaze routes and speech types |
| `sugano2015online` | **Implicit calibration from mouse clicks → 2.9°** with no explicit calibration | The single highest-value unimplemented gaze upgrade |
| `zhang2015mpiigaze` | Appearance-based gaze in the wild; the accuracy regime | Why 2–4° is the honest number |
| `krafka2016everyone` | Commodity-camera gaze at scale | Evidence a webcam suffices for zone targeting |
| `kyto2018pinpointing` | Coarse gaze + refinement beats either alone | The pattern for gaze → zone → confirm |

## 6. EMG, silent speech, and BCI as input (10)

Mostly already swept on 2026-08-08; carried here so the corpus is complete.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `kaifosh2025neuromotor` | Generic cross-user sEMG neuromotor interface; **20.9 WPM handwriting** | Muscle is a trigger, not a typewriter. Nature 2025 — fetch by DOI, title search finds only the preprint |
| `saponas2009always` | Always-available muscle input | The HCI precedent for `EMGBackend` |
| `denby2010silent` | The founding silent-speech-interface survey | Defines the modality |
| `schultz2017biosignal` | Biosignal-based spoken communication survey | The state of the field before the 2023 jump |
| `jou2006emg` | Continuous speech recognition from surface EMG | Shows decoders emit *words* — the argument for widening the seam (direction #3) |
| `kapur2018alterego` | AlterEgo: wearable silent speech, closed vocabulary | Same argument, wearable form factor |
| `su2023liplearner` | Few-shot customisable silent commands (**Su** first author, not Kimura) | Closed-vocabulary commands are the viable path |
| `willett2023speech` | 62 WPM, 23.8% WER at 125k words — **invasive** | The accuracy/invasiveness frontier |
| `metzger2023avatar` | High-performance decoding + avatar control | Same frontier, parallel result |
| `card2024nejm` | **2.5% WER** speech neuroprosthesis, rapid calibration | The ceiling; also the reason a confirmation model is needed at *any* error rate |

## 7. Accessibility and ability-based design (13)

The section with the largest gap between what YazSes ships and what it has evidenced.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `wobbrock2011ability` | **Ability-based design**: adapt the system to the person, not the person to the system | The design philosophy `enroll`, `mic-level` and dysfluency mode already follow implicitly |
| `wobbrock2018ability` | The CACM restatement, with the seven principles | The citable short form for the paper |
| `koester2006speech` | Experienced-user performance factors in speech recognition | Bridges sections 3 and 7 |
| `green2021euphonia` | **Personalised models beat human listeners** on short disordered-speech phrases | The evidence that per-user adaptation is the accessibility lever — and YazSes already has the corpus to do it |
| `macdonald2021euphonia` | Lessons from 1M disordered-speech utterances | What a real disordered-speech evaluation costs |
| `lea2021sep28k` | SEP-28k: stuttering event detection dataset | An *existing public dataset* — direction #6 does not need new recruitment to start |
| `lea2023stutter` | **From user perceptions to technical improvement** for people who stutter | The method for direction #6, end to end |
| `trnka2009prediction` | Prediction *quality* changes interaction, not just speed | Warns that better models can worsen the interaction |
| `mankoff2010disability` | Disability studies as critical inquiry for assistive technology | Guards against building *for* rather than *with* |
| `hurst2011diy` | DIY assistive technology and user agency | Why local, hackable, offline matters to this audience specifically |
| `kane2008sliderule` | Slide Rule: touch made accessible by redesigning the interaction | Precedent that the fix is interaction design, not more model |
| `bigham2010vizwiz` | Near-real-time human-in-the-loop assistance | Latency expectations in assistive contexts |
| `bragg2019sign` | Interdisciplinary perspective on sign language technology | The cautionary model for any "we solved modality X" claim |

## 8. Adaptive and mixed-initiative systems (9)

`yazses tune` is an adaptive system. This is what is known about how those fail.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `horvitz1999mixed` | **Principles of mixed-initiative UIs** — when to act vs when to ask | The direct justification for propose-and-approve in `tune` |
| `gajos2008predictability` | **Predictability and accuracy trade off** in adaptive UIs; users prefer predictable | Predicts that silent adaptation loses even when it improves WER (direction #8) |
| `gajos2004supple` | Automatic UI generation from an ability/device model | The far end of adaptation, for contrast |
| `hook2000steps` | Steps to take *before* intelligent UIs become real (**Höök**) | A checklist YazSes can be audited against |
| `bellotti2001intelligibility` | Intelligibility and accountability in context-aware systems | Why the tray must explain itself; why `logs` is metadata-only but present |
| `lim2009why` | **Why / why-not explanations measurably improve intelligibility** | Concrete design for explaining a `tune` proposal |
| `amershi2014power` | The human's role in interactive machine learning | Frames the learning corpus as interaction, not data collection |
| `amershi2019guidelines` | 18 validated human-AI interaction guidelines | A ready audit instrument for the whole v2 layer |
| `kocielnik2019imperfect` | **Expectation-setting changes acceptance of an imperfect AI** more than accuracy does | The cheapest lever for the ~1-in-30 wrong command (direction #4) |

## 9. Privacy as an interaction property (9)

YazSes's central product claim, stated in the literature's own terms.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `nissenbaum2010context` | **Contextual integrity**: privacy is appropriate *flow*, not secrecy | The precise frame for "offline by construction" beating a consent dialog |
| `langheinrich2001privacybydesign` | Privacy-aware ubiquitous systems: notice, choice, proximity, locality | Design principles ADR-011 already satisfies — now citable |
| `hong2004architecture` | An architecture for privacy-sensitive ubicomp | Architectural precedent for keeping capture local |
| `dourish2006collective` | Privacy and security as social/cultural practice, not a setting | Why "no telemetry" is a *relationship*, not a config key |
| `lau2018alexa` | Non-users cite privacy as the reason; users under-use privacy controls | Evidence the offline stance addresses a real adoption barrier |
| `malkin2019attitudes` | Most smart-speaker users do not know recordings are kept | Why YazSes's default (retain nothing) is the honest one |
| `abdi2021norms` | Privacy *norms* for smart home assistants | Norms for Meeting Mode's third parties, who never consented |
| `porcheron2018voice` | Voice interfaces in everyday life — as a social, situated activity | Meeting Mode's real setting; guards against a single-user model |
| `ackerman1999ecommerce` | Users' stated privacy preferences vs behaviour | The privacy-paradox caveat for any user-study claim |

## 10. Text entry and evaluation method (10)

How to run and report direction #1 so it is comparable to prior work.

| Reference | What it establishes | Where it lands in YazSes |
|---|---|---|
| `mackenzie2002textentry` | The canonical models-and-methods reference for text entry (article `…172&3_2`, **not** `_1`) | The protocol skeleton for direction #1 |
| `soukoreff2003metrics` | MSD, KSPC, and a **unified error metric** | The error numbers to report, so they compare to prior work |
| `wobbrock2006inputstream` | Character-level error analysis for *unconstrained* entry | The right analysis for free dictation, which has no reference string |
| `arif2009metrics` | Comparative analysis of text-entry metrics | How to choose among them and justify it |
| `mackenzie1999softkeyboard` | Design-and-evaluate exemplar, end to end | Worked example of the whole study shape |
| `kristensson2012phrasesets` | **Phrase set and presentation style change the measured result** | Prevents an unfair YazSes-vs-typing comparison |
| `vertanen2011enron` | A realistic phrase set from genuine mobile email | The stimulus set for direction #1 — real prose, not read speech |
| `hornbaek2006usability` | Current practice in measuring usability, and its failure modes | What reviewers will check |
| `cockburn2018hark` | **Preregistration for CHI experiments** | Preregister direction #1 before collecting; it is a single-shot claim |
| `wobbrock2016researchcontributions` | The taxonomy of HCI contribution types | Tells us honestly that YazSes today is an *artifact* contribution, and what would make it an *empirical* one |

---

## How to use this corpus

- **For the manuscript:** `hci-corpus.bib` is the superset the paper's own bibliography
  draws from. Copy the entries a section cites; do not fork the file.
- **For the public page:** `docs/research/hci-canon.md` carries a curated subset in the
  existing ref-anchor + evidence-grade format, so `hooks/research_schema.py` emits
  schema.org `citation` entries for it like the other research pages.
- **Adding a reference:** add it to `candidates`, re-run `verify_refs.py`, and only then
  write the row. An entry without an API response does not go in.
- **Not in scope:** PDFs of cited papers live in a local, gitignored research cache and are
  gitignored. Only citations and our own summaries are ever published.
