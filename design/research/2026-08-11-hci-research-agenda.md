# The YazSes HCI research agenda — ten directions

> **Written:** 2026-08-11 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Companion:** [the 105-reference corpus](2026-08-11-hci-reference-corpus.md) ·
> [`hci-corpus.bib`](hci-corpus.bib)
> **Tier:** `design/` — **public**. **No GitHub issues have been filed for these** — the
> reserved `good first issue` / `help wanted` queue stays untouched by design.

## How to read this

Each direction is stated as a **measurable claim**, not a feature. That is deliberate:
YazSes already has more features than evidence, and the corpus made clear that the
project's scarce resource is *measurement*, not ideas. Every entry names the code seam
it touches, the literature that defines the method, and what a result would actually
say.

They are ordered by **evidence produced per unit of effort**, not by ambition.
Directions 1, 2 and 9 need no new code at all.

A note on scale: YazSes has roughly four addressable contributors today. This agenda is
therefore written for one person with a laptop, not for a lab. Where a direction needs
recruitment, that is called out as the binding constraint.

---

## 1. The first user study — throughput *and* correction cost

**Claim to test:** for composed prose on a desktop, hold-to-talk dictation delivers
higher net words-per-minute than typing *after correction cost is subtracted* — and the
margin is smaller than the 3× that gets quoted.

**Why it is first.** In `wobbrock2016researchcontributions` terms YazSes is today an
*artifact* contribution awaiting its *empirical* counterpart: the performance claims
characterise the recogniser rather than the person using it. The often-quoted 3× speech
advantage (`ruan2016speech`) was measured on **short messages on touchscreen phones** —
a different task, a different device, and a baseline (phone typing) that is far weaker
than a desktop keyboard. Nobody has published the desktop-daemon equivalent.

**Method is settled, not open.** `mackenzie2002textentry` gives the protocol,
`soukoreff2003metrics` the unified error metric, `vertanen2011enron` a realistic phrase
set drawn from genuine email, and `kristensson2012phrasesets` the warning that phrase
set and presentation style *change the measured result* — so the comparison must be
pre-specified. `karat1999patterns` is the prior dictation measurement a YazSes result
would sit beside.

**Seam:** none. The learning corpus (`learning/store.py`) already records one event per
hold-release including discards; a study instrument is a scripted task plus consented
logging.

**Binding constraint:** participants. Even n=8 within-subjects would be the first such
number for an offline dictation daemon.

**Preregister it** (`cockburn2018hark`). This is a single-shot claim about our own
software — precisely the case where analysis flexibility silently becomes a result.

---

## 2. False-activation rate per working day

**Claim to test:** a hold-to-talk trigger produces under *N* unintended activations per
eight-hour day, where every competing modality (wake word, EMG squeeze, gaze dwell)
produces measurably more.

**Why it matters more than accuracy.** Benchmarks report accuracy on curated sets. The
number that decides whether you can leave a thing switched on is how often it fires
when you did not mean it. **No paper in the silent-input literature reports it** —
`kaifosh2025neuromotor` omits both latency and false-activation rate despite being the
landmark result. This is a genuine, publishable gap that YazSes is unusually well
placed to fill, because it is already deployed on a real machine doing real work.

**Seam:** already instrumented. `audio/device_monitor.py::SilentStreakTracker` counts
consecutive silent discards, and the learning corpus records discards as events. What is
missing is a *definition* (what counts as unintended) and a reporting convention.

**Status:** already recognised as `measurement-wanted` in issue #140. Keep it there;
do not convert it into a code task.

---

## 3. Widen the activation seam to carry intent, not just onset

**Claim to test:** a single `ActivationSource` protocol that emits an *intent* (a word,
a gesture class, a confidence) rather than "started"/"stopped" makes every published
silent-speech and neuromotor decoder pluggable into YazSes without a bespoke adapter.

**The argument that makes it undeniable** is a table: five systems in the corpus
(`jou2006emg`, `kapur2018alterego`, `su2023liplearner`, `willett2023speech`,
`card2024nejm`) each produce a *word*, against a seam (`HotkeyBackend`) that accepts
only two edge events. The mismatch is architectural, not incidental.

**Seam:** `platform/base.py::HotkeyBackend`, `platform/emg/backend.py`,
`core/daemon.py::_build_activation_sources`, and `modality/router.py` — which is pure,
tested, and still in `_UNWIRED`. **ADR-v2-011 was accepted in July 2026 and never
wired**, so the "EMG owns commands" decision is already made; this is wiring, not
design.

**Vocabulary:** `buxton1983lexical` (lexical vs pragmatic structure of input) is the
right frame for describing what a source may say.

**Status:** issue #137.

---

## 4. A confirmation model proportional to the error rate

**Claim to test:** a confirmation gate that triggers on *low decoder confidence only*
costs less total time than either always-confirming or never-confirming, at the 3–4%
error rate real command channels exhibit.

**Why.** Closed-vocabulary silent input runs at 96–97% — about one command in thirty is
wrong. For a destructive action that is unacceptable; for dictation it is noise. The
design literature says the interface should *absorb* recognition error rather than
pretend to eliminate it (`oviatt2000taming`), and that **setting expectations changes
acceptance of an imperfect system more than accuracy does**
(`kocielnik2019imperfect`). `horvitz1999mixed` gives the principles for when to act
versus when to ask.

**Seam:** ADR-v2-010's `needs_confirm` already exists: the policy is decided in
`gaze/deixis.py` and the actionable-toast confirmation is `core/daemon.py::_confirm_deixis`,
used for destructive actions on a gaze-routed target. Generalise that path, do not invent
a second mechanism.

**Status:** issue #138.

---

## 5. Make uncertainty visible

**Claim to test:** rendering per-word ASR confidence at injection time reduces
correction time versus uniform text, without increasing perceived effort.

**Why.** This is the intelligibility result applied to dictation: why/why-not
explanations measurably improve users' understanding of an intelligent system
(`lim2009why`), and accountability requires the system to expose what it is unsure of
(`bellotti2001intelligibility`). It also directly serves direction #1 — if you can see
which word is doubtful, correction becomes targeted rather than a re-read.

**Seam:** ADR-v2-001 "confidence ink". `stt/base.py` would need to surface per-word
confidence through `transcribe_words()` (it already exists for the diarization path),
then `inject/streaming.py` applies the treatment.

**Risk to state honestly:** confidence from a Whisper-family decoder is poorly
calibrated. The study may find the signal is not good enough to be worth showing —
which is itself a publishable negative result.

---

## 6. Evaluate with dysfluent and dysarthric speakers

**Claim to test:** the shipped dysfluency-friendly mode measurably improves usable
transcription for people who stutter — or it does not, and we say so.

**Why this is the highest-value direction that is not first.** ADR-015 ships a mode
named for a population it has never been tested with; the paper's own evaluation used
*hand-authored text, not affected-speaker audio*. `lea2023stutter` provides the method
end to end (user perceptions → technical improvement), `lea2021sep28k` is a **public
dataset that exists today**, so the work can start without recruitment, and
`green2021euphonia` establishes that personalized models can beat human listeners on
short phrases — which is exactly what YazSes's on-device learning loop is for.

**Non-negotiable:** `mankoff2010disability` is why this must be done *with* rather than
*for*. A benchmark result on SEP-28k is a start, not the finish.

**Seam:** `stt/filters/disfluency.py`, `postprocess/cleaner.py`, and the
`learning/analysis.py` retranscription path.

---

## 7. Put-That-There on a $0 sensor

**Claim to test:** at webcam-grade accuracy (2–4°), demonstrative commands
("close this", "focus that window") succeed on a real multi-window desktop at a rate
high enough to be worth the confirmation gate they require.

**Why it is a genuine contribution.** `bolt1980` is 45 years old and was demonstrated on
custom hardware. The gaze constraints are known — `jacob1990midas` (gaze alone cannot
express intent, hence a manual commit), `zhai1999magic` (gaze selects coarsely, hand
confirms), `sugano2015online` (2.9° via implicit calibration from mouse clicks).
`kaur2003whereislinda` measured **event synchronisation** in gaze-speech systems, which
is precisely the open parameter in our implementation: *when* to snapshot gaze relative
to speech onset.

**Seam:** wired and working on X11 today — `gaze/targeter.py`, `gaze/deixis.py`,
`gaze/zones.py`, `core/daemon.py::_on_hold_start`. The cheapest upgrade in the whole
agenda is implicit calibration from mouse clicks (`sugano2015online`), which removes the
explicit 9-point step entirely.

**Scope limit:** Wayland cannot focus other windows, so this is an X11 result and must
be reported as one.

---

## 8. Adaptation the user can see and steer

**Claim to test:** propose-and-approve tuning produces higher user trust than silent
adaptation **at equal or slightly worse WER** — i.e. the two outcomes disagree, and
predictability wins.

**Why.** `gajos2008predictability` found users of adaptive interfaces value
predictability alongside accuracy, so an unannounced improvement can still degrade the
interaction. `hook2000steps` is a checklist to audit an intelligent UI against before
claiming it works, and `amershi2014power` frames the corpus as *interaction* rather than
data collection. YazSes already implements the arm the literature predicts wins
(`yazses tune` proposes, the user approves) — so this is a comparison we are set up to
run and have not.

**Seam:** `learning/tuner.py`, `learning/analysis.py`. The silent arm would need a flag;
do not ship it as a default.

---

## 9. The no-text-target guard as an error-prevention study

**Claim to test:** the wrong-target slip occurs at a measurable rate in ordinary desktop
use, and the `clipboard` policy recovers it at lower cost than `warn`.

**Why it is nearly free.** This is `norman1981slips` with a shipped intervention and
**three policies already in config** (`[injection] target_guard` = `clipboard` | `warn` |
`off`). The comparison arms exist; nothing needs building. `hutchins1985dm` supplies the
framing (gulf of evaluation), and `sellen1992mode` explains why the *tray colour* is a
weaker signal than the held key — visual feedback for a state the user is not touching.

**Seam:** `inject/target.py::TargetDetector`, `core/daemon.py::_handle_no_target`,
`tray/menu.py` for the yellow state.

**Caveat:** `TargetDetector` is tri-state (True/False/**None**) — AT-SPI is precise but
optional, and the xdotool fallback is best-effort. The study must report the unknown
rate, not fold it into one of the other two.

---

## 10. Code-switching as an equity question

**Claim to test:** for bilingual users, within-utterance code-switching — not accent —
is the dominant source of dictation failure, and which language *pairs* matter is an
empirical question nobody has asked dictation users.

**Why it is an HCI question and not only an ML one.** Whisper decodes one language per
30-second window, so a code-switched sentence is structurally mis-served; adapters reach
roughly 14% mixed error rate but need per-pair training, which means somebody chooses
which pairs get built. That choice decides who the tool serves. The corpus's
accessibility section (`wobbrock2011ability`) supplies the principle: adapt to the
abilities and practices people actually have, and bilingual speakers code-switch as a
matter of course.

**Seam:** `polyglot/lid.py` is pure and tested; `[polyglot] adapter_path` is dormant
until a trained adapter exists. ADR-v2-008 covers the design.

**Cheapest first step:** ask. A Discussion asking bilingual users which pair they need
costs nothing and produces the prioritisation that the training work would otherwise
guess.

---

## Held in reserve

- **Privacy-by-construction versus consent as an interaction study.**
  `nissenbaum2010context` argues privacy is appropriate *flow*; `lau2018alexa` shows
  concern drives non-adoption. The testable version: does "it never leaves your machine"
  change willingness to dictate sensitive text more than a permissions dialog?
- **Consent and diarization in Meeting Mode.** `porcheron2018voice` and `abdi2021norms`
  are about people who never agreed to be in the room with a recorder. This is a design
  obligation before it is a research direction.

## What this agenda deliberately does not do

- **It files no issues.** Directions 2, 3 and 4 already have issues (#140, #137, #138).
  The rest stay here until Mohsen decides otherwise — the contributor queue is
  traffic-bound, not idea-bound, and adding more open issues makes the queue look
  staler, not healthier.
- **It proposes no new features.** Every direction either measures something already
  shipped or wires something already designed and accepted. The one exception is #5,
  which has an accepted ADR.
