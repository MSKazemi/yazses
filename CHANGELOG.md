# Changelog

All notable changes to YazSes are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — the Android privacy gates, as build failures

[ADR-MOB-007](https://mskazemi.com/yazses/mobile/adr/adr-mob-007-privacy-permissions-lifecycle.html)
was a policy document. `./gradlew checkPrivacy` now makes it a build failure, because
on Android the privacy posture is decided by the **merged manifest** and by
**transitive dependencies** — an SDK three levels down can add `INTERNET` and
phone-home behaviour no reviewer spots in a diff, and a keyboard is the most
sensitive app class the platform has.

- **Manifest golden diff** — every permission and exported component in one
  reviewable file. Verified: adding `CAMERA` to `:feature:ime` fails, names the
  permission and the module, and tells you to update both the golden file and the
  ADR's permission table in the same PR.
- **Dependency allow-list and network containment** — no analytics or crash SDK
  anywhere, and network code only in `:model`. Verified: OkHttp in `:feature:ime`
  fails with *"only :model may reach the network"*.
- **No content in logs** — verified: `println("delivered: $transcript")` in
  `:core:session` fails, because logcat is readable by the user, by any bug report,
  and by anything holding `READ_LOGS`.

Each gate prints the fix rather than the fact. A new permission is not
automatically wrong — it is something a human has to agree to, and the gate exists
to make sure one does. (#85)

### Added — `:core:postprocess` ported to Kotlin, verified against the shipping vectors

The four units that turn recognised words into the text actually typed —
`cleanText`, the three-pass disfluency filter, continuation spacing and voice
punctuation — now exist in Kotlin, and `:core:contract-test` runs **180 cases from
`contract/vectors`** against them. The same JSON the Python suite asserts on.

That is the whole definition of done: a contributor never has to guess what the
desktop does, and a reviewer never has to remember. The harness was checked
red-green — breaking `cleanText` on purpose failed 7 vectors.

**The vectors caught a real disagreement.** The Kotlin initially chained
self-correction triggers (a trigger that became utterance-initial because an
earlier one was consumed could still fire). The desktop does not do that, the
vector said so, and the Kotlin was changed to match. That is the harness doing
exactly the job it exists for — the contract is the Python, not the porter's
preference.

Idiomatic Kotlin rather than a transliteration, as ADR-MOB-008 §4 requires: the
contract constrains behaviour, never structure. (#86)

### Added — the Android Gradle skeleton, with the architecture rules enforced by the build

`android/` had one README. It now has every module from
[architecture.md §3](https://mskazemi.com/yazses/mobile/architecture.html) — 21 of them —
each compiling with a placeholder test, so several people can start in parallel
without colliding or re-deciding the same questions in review.

**Two rules the build enforces, verified by making them fail:**

- **`:core:*` cannot see Android.** They are `kotlin("jvm")`, so the SDK is not on
  the classpath: adding `import android.content.Context` to `:core:vad` fails with
  *"Unresolved reference 'android'"*. Not a lint rule — there is nothing to import.
- **Dependencies point one way.** `checkLayering` fails a `:core:* → :feature:*` or
  `:platform:* → :feature:*` edge and prints the reason and the fix. Worth having
  even where Gradle would fail anyway: for a core→feature edge it fails on *variant
  resolution*, which is a wall of attribute-matching text that never mentions the
  architecture.

`:core:contract-test` runs `contract/vectors/*.json` — the same files the Python
suite asserts against — so a port is reviewable against the JSON rather than
against someone's memory of what the desktop does.

CI is **path-filtered** to `android/**` and `contract/**`, so a Python contributor
never watches a Gradle job run on a docs typo. `contract/**` is in there because
changing a vector can break the Kotlin port without touching a Kotlin file.

`./gradlew test` is green from a clean clone with no phone attached, and Gradle
downloads the JDK 17 toolchain itself rather than requiring it to be installed.

One finding worth recording: the Gradle paths `:native:whispercpp` and
`:native:sherpaonnx` match the architecture doc, but their namespaces are
`com.yazses.jni.*` — **`native` is a Java keyword** and cannot be a package
segment. (#84)

### Fixed — the mid-sentence half of the correction-trigger bug
### Added — 25 README translations, shipped as reviewable drafts

The README existed in three languages and 26 issues asked for more. It is now in
**28**, generated from a string table by
`scripts/gen-readme-translation.py`, with the localisation tooling extended so a
new language cannot break the existing ones.

**Every new file is `status=draft`, and says so in the reader's own language at the
top**, next to an English sentence stating that it is machine-assisted and not yet
reviewed. That is the project's own mechanism —
`scripts/check-translations.py` already required a visible banner for
`status=draft` — and it changes the ask rather than removing it: **reviewing a
draft is a much smaller job than translating a README from scratch**, which is
what the linked issue now asks for.

What the generator guarantees, because these are the things that break by hand:

- **Commands are copied verbatim** from the English README. A translated
  `yazses quickstart` is a command that does not exist, and the checker fails the
  build if one appears.
- **The badge block and the all-contributors wall are copied from the English
  README at generation time**, so the contributor count and the DOI cannot drift
  across 28 files — two existing tests enforce exactly that.
- **The language switcher lists every locale.** Adding twelve languages initially
  dropped Hindi, Russian and Chinese from every switcher: each file was
  individually valid and the *set* was broken. `check-translations.py` now fails
  when a locale is unreachable from another, and that guard was verified by
  reproducing the regression.
- **`docs/localization/STATUS.md` is kept in sync**, so no language is missing from
  the page a would-be translator reads first.
- Right-to-left locales (Arabic, Persian, Hebrew, Urdu) wrap the body in
  `dir="rtl"` with the switcher left on line 1, where the checker requires it.

New: Arabic, Bengali, Czech, Dutch, French, German, Greek, Hebrew, Indonesian,
Italian, Japanese, Korean, Persian, Polish, Portuguese (Brazil), Spanish, Swedish,
Tamil, Telugu, Thai, Traditional Chinese, Turkish, Ukrainian, Urdu, Vietnamese.

### Fixed — `yazses setup` sent snap users round a loop that can never close

The utterance-initial guard fixed sentences that *open* with a trigger. It cannot
reach one with text in front of it, and those were still being destroyed:

```
you should never mind the warning   ->  the warning
we can forget that idea             ->  idea
remember to delete that file        ->  file
```

A second signal closes it: a **modal or auxiliary immediately before the trigger**
makes it part of the verb phrase — "should never mind", "can forget that",
"to delete that". A self-correction is an interjection; it interrupts a clause and
never continues one, so a governing verb is decisive evidence against it. Only the
adjacent word is consulted, because a wider window would suppress genuine
corrections in any long sentence containing a "should".

The `known-gap` invariant recorded for this is **promoted to `holds`** — the
transition the harness exists to force. Contract 6.4.0 → 6.5.0.
([#302](https://github.com/MSKazemi/yazses/issues/302))

### Fixed — a sentence that *began* with a correction phrase lost its first half

Every phrase in the default self-correction list is ordinary English in some
sentence, and each of them silently deleted everything before it:

```
"delete that file when you are done"     ->  "file when you are done"
"strike that clause from the contract"   ->  "clause from the contract"
"scratch that itch on the backlog"       ->  "itch on the backlog"
"never mind the warning"                 ->  "the warning"
"forget that idea for now"               ->  "idea for now"
"no wait for the build to finish"        ->  "for the build to finish"
```

All six on default settings. This is the worst output the filter can produce,
because what survives reads as fluent text the user never said.

**A trigger that opens the utterance now needs the pause.** There is nothing in
front of it to roll back, so those words are either a correction marker or the
start of a sentence — and the two are not distinguishable by what follows:
*"no wait I should reconsider"* and *"no wait for the build to finish"* differ only
in meaning. The punctuation Whisper writes for a spoken pause is the only signal,
so it is required in that position; `"scratch that. meet at four"` still rolls back.

**Mid-utterance corrections are untouched**, punctuated or not — Whisper does not
reliably render a pause, and that path is a supported case.

The cost is asymmetric and that is the whole argument: a correction marker left in
place is two visible words to delete, while the old behaviour cost a sentence its
first half without any sign that it happened. One case changed as a result —
`"no wait I should reconsider"` now types as spoken — and the fixture says why.

[#302](https://github.com/MSKazemi/yazses/issues/302) stays open for the residual
case (`"you should never mind the warning"`, mid-sentence prose), which is still
recorded as a `known-gap` invariant that goes red the moment it is fixed.

### Added — a guide for SSH and Remote-SSH editors

**[Over SSH, and in Remote-SSH editors](https://mskazemi.com/yazses/how-to/ssh-and-remote.html)**
— the case people expect to be hard and is not: text is injected at the OS level
into the focused *local* window, so dictating into `ssh`, `tmux`, or VS Code
Remote-SSH needs nothing installed on the remote host, which cannot tell the
difference from typing.

Also covers the case that genuinely does not work (a remote *graphical* window,
which is what `yazses remote` and `yazses-agent` are for), and one fact worth
knowing: **the agent binds `127.0.0.1`, never `0.0.0.0`** — verified by connecting
to it — so it is reachable through the SSH tunnel and nothing else. Transcription
always happens where the microphone is, so the remote host receives finished text
and never audio. (#245)

### Added — an app-grid launcher, and a page for the Settings window

- **`yazses settings --install-launcher`** puts *YazSes Settings* in your
  application menu, with an icon at 48/64/128/256 px plus a scalable SVG, all
  rendered from the same "Y over a sound-wave" mark the docs header and the CLI
  banner use. A `.deb` now installs the same files system-wide;
  `--uninstall-launcher` removes them. A `pipx` or `uv tool` install owns nothing
  outside its own virtualenv, which left those users with a settings window
  reachable only by typing a command. `Exec=` is the bare `yazses settings`, not an
  absolute path, because hard-coding today's interpreter is how a launcher breaks
  at the next upgrade. Validated with `desktop-file-validate`, and a test asserts
  each PNG really is the size its filename claims. (#59)
- **[The Settings window](https://mskazemi.com/yazses/settings-gui.html)** — how to
  open it three ways, what the recommendation tiers mean, how a capability that
  needs extra packages installs them (and why a failed install leaves the switch
  **on** rather than silently discarding your intent), and why Apply offers a
  restart and then waits for the daemon to answer over IPC rather than trusting an
  exit code. The screenshot is the real window, rendered offscreen from the
  shipping code. (#64)

### Added — two more troubleshooting guides

- **[Dictation types into the wrong window](https://mskazemi.com/yazses/how-to/wrong-window.html)**
  — separates the three causes that share one symptom, and names the trap behind
  most of them: precise "is this a text field" detection needs the **system**
  `python3-pyatspi` package, which a `pipx` or `uv tool` environment cannot see, so
  `apt install` alone changes nothing. `yazses doctor` reports which mode you are
  in. (#244)
- **[After a distro upgrade](https://mskazemi.com/yazses/how-to/after-a-distro-upgrade.html)**
  — the four things a release upgrade breaks: a virtualenv pointing at a Python
  that moved, a session silently switched to Wayland (where dictation *appears* to
  work and the text goes nowhere), lost `input` group membership, and a stopped
  `ydotoold`. Each with the command that tells them apart. (#242)

Both say plainly what was not done: no system package was installed and no
distribution was upgraded to write them.

### Added — three troubleshooting guides, each written from commands actually run

The issues asked for pages built from real output rather than guesswork, so these
carry the machine they were verified on and mark the parts that were not tested.

- **["Silent audio -- discarding"](https://mskazemi.com/yazses/how-to/silent-audio-discarding.html)**
  — the most common report, end to end. Splits the two causes that share one
  symptom (the gate is above your voice vs nothing is being recorded), with real
  `yazses mic-level` output. Includes the trap that the recommendation is computed
  from whatever it heard: if you do not speak during the four seconds it measures
  your *room* and suggests a threshold below it. (#243)
- **[The tray icon does not appear](https://mskazemi.com/yazses/how-to/tray-icon-missing.html)**
  — GNOME has had no built-in tray since 3.26 and needs an AppIndicator extension;
  Ubuntu ships one enabled, which is why it "just works" there and not elsewhere.
  Starts by telling apart "the tray is not running" from "the desktop is not showing
  it", because those look identical. (#249)
- **[Running fully air-gapped](https://mskazemi.com/yazses/how-to/air-gapped.html)**
  — which two directories to carry across, and **how to prove the claim** rather
  than trust it: `HF_HUB_OFFLINE=1` is a real test here because the loader asks for
  a cached snapshot first, plus an `strace` recipe and taking the interface down.
  (#246)

### Added — `[stt] cpu_threads`, and two guides written from measurements

A decode that takes **one second of your time spends about five seconds of CPU**,
because the work is spread across cores. Nothing capped that, so a laptop on battery
had no lever at all beyond changing model.

`[stt] cpu_threads` caps it; `0` (the default) leaves the library alone, so nobody's
behaviour changed. Measured on `base.en`, three runs per setting, 11-second clip,
20-core laptop:

| `cpu_threads` | Mean wall | Mean CPU |
|---|---|---|
| `0` (default) | 0.98 s | 5.49 s |
| `4` | 0.98 s | 5.45 s |
| `2` | 1.32 s | 4.55 s |
| `1` | 2.05 s | 4.08 s |

**Capping at 4 changed nothing measurable** — the decoder was not using 20 cores'
worth to begin with, so the "limit the threads" advice written for other Whisper
tools does not transfer. The trade only starts below that. Both new pages say so
rather than selling the setting.

Two guides, from numbers measured on the machine rather than assembled from
guesswork:

- **[Reducing CPU use and battery drain](https://mskazemi.com/yazses/how-to/cpu-and-battery.html)**
  — the CPU cost per model, what actually reduces it, what polls while idle, and
  which optional features do extra work per utterance. (#248)
- **[Choosing a model on a low-RAM machine](https://mskazemi.com/yazses/how-to/low-ram-models.html)**
  — measured **peak resident memory**, which is roughly *twice* the download size
  (`base.en`: 148 MB on disk, 370 MB resident) and is the number that decides
  whether a small machine swaps. Includes how to tell whether it is swapping, and
  what does *not* reduce memory. (#247)

Both pages end with what was **not** measured — no battery was measured in
watt-hours, and no machine that actually has 2 GB was tested.

### Fixed — dictating a sentence that began "run" executed it

`run CMD` types the command **and presses Return**. Its grammar is `^run (.+)$`,
which every ordinary sentence starting with "run" satisfies — the sentence *is* the
argument — and `[commands] enabled` is true by default, so every dictated utterance
was classified. "Run the numbers again before Friday" was executed in whatever
window had focus.

The open-ended form now requires the **command key**; without it the words are
typed like any other dictation. The closed-vocabulary forms — "run the tests",
"run the build", "run that" — are unambiguous whole utterances and are untouched.
Narrowing the regex cannot fix this: a shell command and an English clause are not
distinguishable by shape, so the decision belongs to the caller that knows whether
the user meant a command. Every other command is recoverable by retyping; this one
is not, which is why it is the only one gated.

Found while writing the semantic vector for #235.

### Fixed — removing a filler left the punctuation around it stranded

- `"this is probably fine, you know"` → `"this is probably fine,"` — a dangling
  comma typed into the document.
- `"the tests, you know, are slow"` → `"the tests, are slow"` — a comma between
  subject and verb, because only the closing comma of the parenthetical was
  consumed.

The filler pattern now takes the opening comma with the closing one, and leaves a
separator behind so the neighbours do not glue together. (#236)

### Changed — `basically` and `literally` are no longer stripped by default

Issue #146 removed `like`, `right`, `sort of`, `kind of` and `actually` from the
default filler list because each is a genuine filler in some positions and
load-bearing content in others, and stripping them turns hedges into facts.
`basically` and `literally` are the same class and were simply missed:

- "it seems **basically** correct" is a hedge; "it seems correct" is a claim.
- "the value is **literally** zero" asserts a precision that "the value is zero"
  does not.

Both stay in the recognised vocabulary — add them back under
`[filters.disfluency] filler_words` if you want aggressive removal. (#236)

### Added — six semantic and parity vectors, contract 6.3.0 → 6.4.0

Negation under a rollback trigger and the stutter pair landed earlier; this closes
the rest of the set. Two of them are the reason the two fixes above exist.

- **`undo` inside a sentence is dictation**, and the bare word is still a command
  — with the count preserved, because "undo the last three commits" loses its
  instruction if the number goes. (#235)
- **Hedging survives**, both the word itself and the punctuation around a filler
  next to it. (#236)
- **Unicode identifiers survive byte for byte** — `naïve_bayes`, `Ωmega`. Any
  accent-stripping produces a name that does not exist, and it fails at import
  time, far from dictation. (#237)
- **Numbers, units and times stay as spoken** — losing "milligrams" leaves a bare
  number; losing "pm" moves an appointment twelve hours. (#238)
- **Code identifiers keep their exact shape** — `get_user_by_id`, `main.py`,
  `kubectl`. (#240)
- **A self-correction rolls back the right span**, with the affirmative partner so
  the fix could not be "stop rolling back". (#239)

Three of these turned out to be *parity* guarantees rather than semantic ones —
they assert text, not meaning — and the invariants harness said so, so they live in
`contract/vectors/` where a text guarantee belongs. The quantity lexicon grew by one
entry to support a case, which is the documented way it grows.

### Fixed — a `.venv` symlink reached `main`, and nothing was looking for it

A merge landed `.venv` in git as a symlink to an absolute path on the machine that
created it. It looks harmless there, because the target exists; every other clone
gets a **dangling link that points outside the working tree**, so a `uv sync` or
`python -m venv .venv` in a fresh clone follows it and writes somewhere the user
never chose.

`.gitignore` listed `.venv/` — with the trailing slash, which matches a *directory*.
The thing that slipped through was a file. Both forms are now ignored, and a test
reads the git index and refuses any tracked symlink that escapes the repository,
so the next one fails before it is pushed rather than after.

### Changed — the comparison table named the paid tools and omitted the free ones

The **Comparison & alternatives** table listed Dragon, Talon, Windows Voice Access
and Wispr Flow — the landscape when it was written. It did not mention the active
wave of open-source, local, free dictation tools, which made the project's most-read
honesty surface read as evasive to the readers most likely to know about them.

- **Handy, OpenWhispr and FluidVoice are now in the tables**, in the README and on
  the comparison page, each with a section saying where it is the better pick —
  Handy promoted out of a footnote, since it is the closest comparison there is.
- **The differentiator claim has been narrowed to what is still true.** "Open
  source, local, cross-platform, free" no longer separates YazSes from the field:
  Handy and OpenWhispr share all four. What remains is voice *commands* as well as
  dictation, Linux as a first-class target rather than a port, speaker-labelled
  meeting capture, published benchmarks with a stated method, and accessibility as
  a design constraint.
- Compiled from each project's own documentation in August 2026 and **not** from
  testing each tool — the pages say so, and ask to be corrected. (#304)

### Fixed — a self-correction trigger could delete the sentence that said not to

```
please do not delete that branch   ->   branch
```

`delete that` is a self-correction phrase, and the filter matched it anywhere in
the text, so an instruction whose entire point was the negation had everything
before the phrase discarded. This is the worst output the pipeline can produce:
it does not garble the sentence, it **inverts** it, and what survives reads as
fluent. The same shape hit `scratch that`, `forget that` and `never mind`.

Triggers now match on word boundaries and do not fire when a negation governs
them — the same lesson `commands/revise.py` already encodes by anchoring its
grammar. Real corrections are untouched: `send it to the archive scratch that
send it to the inbox` still rolls back.

The guard deliberately reads only the word immediately before the trigger. A
wider window would suppress genuine corrections in any long sentence containing
a "not", and a correction that silently does not happen is worse than an extra
sentence the user can see.

### Added — semantic vectors for negation and for stutters (#233, #234)

Five cases in `contract/semantic/invariants.json`, contract 6.2.0 → 6.3.0. The
negation ones are what found the bug above.

- **Negation must survive filler removal and self-correction rollback** — with
  the affirmative partner, so the fix could not be "stop rolling back".
- **A stutter is not a repeated word** — `b-b-because` collapses under
  Dysfluency-Friendly Mode, while `he said that that dose had had no effect` must
  not. A collapse rule that cannot tell them apart rewrites the tense and clause
  structure of a correct sentence, and the speaker who needs that mode is the
  least able to catch it.
- **One recorded `known-gap`**: `never mind` is both a correction marker and
  ordinary English, and the negation guard cannot see a negation that is inside
  the trigger. Documented with its cause and a tracked issue
  ([#302](https://github.com/MSKazemi/yazses/issues/302)) rather than papered over
  — the suite stays green while the gap is recorded and goes red if it is fixed.

### Added — `yazses vocab export` / `import`: the dictionary can move between machines

The personal dictionary is the main lever anyone has over recognition of *their
own* proper nouns, package names, flags and acronyms — the words a general model
gets wrong and that matter most in technical dictation. Until now it was a file
you were expected to know the path of, so every new machine started that work from
zero and a team with shared jargon could not share the fix at all.

```bash
yazses vocab export | ssh workstation 'yazses vocab import -'
yazses vocab import team-jargon.txt
```

- **Export goes to stdout** by default, so it pipes and redirects; `-o` writes a
  file. **Import reads a file or `-` for stdin.**
- **Merging is the default and de-duplicates case-insensitively.** Repeated
  imports would otherwise grow the file and dilute the STT prompt — every entry is
  primed into the decoder and prompt length is not free.
- **`--replace` asks before discarding your dictionary** (`--yes` skips it). It is
  one keystroke from `--merge` and throws away work nobody can recover.
- The format is one entry per line with `#` comments, so a shared vocabulary can
  explain itself and lives happily in a dotfiles repo. Export → import → export is
  byte-identical, which is the first test in the file. (#295)

### Fixed — packaging metadata that was wrong or could not work

- **The Scoop manifest could not update itself.** `autoupdate` rewrote the
  installer URL for a new release but carried no way to obtain the new hash, so
  `scoop update` would fail on every release after the pinned one — a manifest
  that looks self-updating and silently is not. It now reads the `SHA256SUMS.txt`
  each release already publishes, so the version and its checksum move together.
  The extraction is tested against a real published checksum file rather than
  assumed to match. (#79)
- **The Windows install page pointed at a bucket that does not exist.** The Scoop
  bucket is served from this repo, not from a separate `scoop-yazses`. The page
  now documents the Scoop path, and says plainly that neither Scoop nor winget has
  been installed end-to-end on a clean Windows machine yet — with a link to the
  issues where a report would change that. (#78, #79)
- **Drift guards for packaging metadata.** The licence, the repo namespace and the
  autoupdate URL are now compared against `pyproject.toml` by a test. Each channel
  restates them by hand in a file nobody opens between releases; the container
  image added this week was written with the wrong licence, and nothing would have
  caught it.

### Added — an official container image: offline transcription and diarization in a box

```bash
docker run --rm -v "$PWD:/data" ghcr.io/mskazemi/yazses \
    transcribe /data/meeting.m4a --diarize -f md
```

Multi-stage `python:3.12-slim`, non-root, `linux/amd64` + `linux/arm64`, published
to GHCR on tags with the built-in `GITHUB_TOKEN` (no new secrets) and build
provenance attested. Verified against the native CLI on the same clip — the
transcripts are byte-identical — and `--diarize` produces speaker-labelled output
in the container. Final image ~1.5 GB, which the docs state rather than let people
discover.

**The docs lead with what it cannot do.** Hold-to-talk dictation needs a
microphone, `/dev/input` and keystroke injection into a desktop session; a
container is the wrong shape for all three, and an image that implied otherwise
would waste someone's evening. (#76)

### Fixed — three things building that image exposed

- **`yazses transcribe --download-models` could not be run.** It exits before
  transcribing and its help says so, but `audio_file` was a *required* argument —
  so the command the tool tells you to run when diarization is unavailable failed
  with "Missing argument 'audio_file'". The argument is now optional, with a clear
  message when neither a file nor the flag is given.
- **The diarization failure message contradicted itself.** With the extra
  installed, the probe reported "backend 'sherpa' is available", the factory
  appended its download hint and the caller prefixed "unavailable:", producing
  `unavailable: backend 'sherpa' is available and run …`. When the import
  succeeds, the cause is downstream of it — for sherpa, almost always the models
  not being on disk — and the message now says that, with the real error kept.
- **The models are ~45 MB, not ~15 MB.** Measured: 39 MB embedding + 6 MB
  segmentation. The old figure appeared in nine places, including the install-cost
  table people use to decide whether to bother.

### Added — staged dictation: speak, review, then commit

Reported by a reader of the r/speechtech thread and conceded there as a real gap.
Every transcript types straight into the focused app, which is right for prose and
wrong for code and terminals: a mis-transcribed token is not a typo you skim past,
it is a command you did not mean to run. `scratch that` is already too late.

`yazses features enable staged` (**off by default**) makes each burst land in a
review buffer; `yazses staged commit` is the thing that types.

The issue left two questions open. Both are decided the same way — **the review
step must not be defeatable by the mis-transcription it exists to catch**:

- **Commit is a deliberate action by default**, spoken only if you ask for it
  (`[staged] spoken_commit`). Prose misheard as "commit" would type the buffer
  early, which is the exact accident staged mode prevents. A missed commit is
  visible and costs one more action; a premature one has already run. When the
  spoken phrases are on they are anchored at both ends, so "git commit -m fix" is
  staged rather than obeyed.
- **While something is pending, "scratch that" edits the buffer**, not the
  committed text. The buffer is what the user is looking at.

A commit hands the buffer back to the ordinary injection path rather than typing it
itself, so the no-text-target guard still applies to it — staged mode has no
business bypassing that. If the injector fails, the text goes **back** in the
buffer rather than being lost; dictation the user has already reviewed is the worst
thing to drop. `yazses status` and the IPC payload carry what is pending. (#294)

### Added — `yazses status` reports decode latency on your machine

The number was always measured and logged (`Transcribed 3.2s audio in 740 ms`) and
never summarised, so the one figure that predicts whether dictation *feels* usable
was only available by reading a log by eye.

```
  latency:  small.en p50 740 ms / p95 1210 ms (n=143)
```

- **p50 and p95, not a mean.** Decode time is right-skewed: most utterances are
  fast and the slow minority is the whole experience, because that is the moment
  you are waiting with the key already released. A mean averages the tail away and
  looks healthy the entire time.
- **Per model**, which is what makes it actionable — it turns "`tiny.en` or
  `base.en` on this machine?" into a measurement rather than a guess.
- **The count is always printed, and the p95 is withheld below 20 samples.** A p95
  over six utterances is not a p95, and printing one invites reading it as one.
- **The window is bounded** (last 200 per model) so the numbers still move after a
  model change, which is exactly when someone looks at them.
- **Nothing has to be turned on.** The samples live in memory in the running
  daemon, are never written to disk, and involve no audio or transcript text — a
  diagnostic that needed the opt-in learning corpus would not be available when it
  is wanted. Also in `--json` for status bars. (#296)

### Added — the tray menu means the same thing on every OS

"Settings…" existed only in the Linux tray, so the same menu offered a different
product depending on where you ran it — and on Windows and macOS the settings
window was reachable only by knowing to type `yazses settings`.

- **macOS (rumps) and Windows (pystray) trays** now carry the same **Settings…**
  entry, from the same shared `SETTINGS_LABEL` constant, so the three menus
  cannot drift into saying three different things.
- A **Start-menu shortcut** on Windows, for people who have not found the tray
  icon yet. It launches the bundle with `--settings`, which the single-binary
  entry point now dispatches — without that branch the windowed `.exe` would have
  fallen through to the CLI, exited 2 on an unknown argument, and (having no
  console to print to) looked like a shortcut that does nothing.
- A failed launch **says so** rather than being swallowed: a menu click with no
  visible effect is indistinguishable from a frozen tray.

Verified by driving the real dispatch and by asserting the installer's flag
against what the bundle accepts — the two are written in different files and had
no reason to stay in step. Clicking it on a Mac or a Windows box still needs
someone on that OS. (#63)
### Fixed — the Hindi and Russian READMEs told Intel Mac users to download the `.dmg`

`README.md` was corrected when the `.dmg` turned out to be Apple-silicon-only, but its
translations were not. `README.hi.md` and `README.ru.md` kept offering the `.dmg` with no
architecture caveat and no mention of the Homebrew tap — so a Hindi or Russian reader was
sent to download a bundle that cannot launch on their machine, while the English reader was
warned.

Both files now name the architecture and point at `docs/macos-install.md`. The macOS blocks
in those files are English inside the code fences, so the correction did not require
inventing Hindi or Russian technical prose that could not be checked; a native speaker
should still translate the note. `README.zh-CN.md` is a partial translation with no per-OS
install blocks and carried no claim to correct.

This is the failure mode #166 (a translation drift checker) exists to catch: a correction
applied to one README and not its copies is invisible until someone reads the other one.

### Fixed — the published SBOM did not list `noisereduce`

The spectral-denoise work added `noisereduce` to `pyproject.toml` without regenerating
`uv.lock`, so `sbom.cdx.json` — which is generated from the lock — described a dependency
set the project no longer had. Anyone consuming the SBOM for supply-chain review was reading
a component list one package short.

It also turned `main` red in a way that does not reproduce locally: `gen-sbom.py` reads the
lock and nothing else, so against the *committed* lock the SBOM is self-consistent and the
test passes on a developer machine. CI runs `uv sync` first, which updates the lock in the
runner, and the mismatch only appears there.

### Added — `scripts/inspect-dmg.py`, so the macOS artefact can be checked without a Mac

The `.dmg` is the one artefact that cannot be opened on the machine this project is
developed on, and two defects lived in exactly that gap — an `.app` reporting version
`0.1.2` for every release from v0.1.3 to v2.18.0, and a bundle with no `x86_64` slice while
the install guide promised Intel support. Neither is visible from a build log: the build
succeeds and the wrong value sits inside the artefact.

```sh
uv run python scripts/inspect-dmg.py YazSes-<version>.dmg \
    --expect-version <version> --expect-arch arm64
```

It decodes the UDIF container `create-dmg` produces and reads the bundle's `Info.plist` and
every Mach-O header out of the raw image, in stdlib-only Python. Both flags exit non-zero on
a mismatch, so a release job can gate on them; `--json` emits the findings for a job to
record or diff. Either flag would have caught its defect years earlier.

It answers *"is the right thing inside the artefact"*, never *"does it launch"* — that still
needs a Mac.

### Added — the three settings people actually tweak get real controls

Feature toggles are booleans; the hotkey, the microphone and the VAD threshold
are not, and each has a way of being wrong a checkbox cannot be.

- **Hotkey picker** validates against the platform's own key map *before*
  writing. An unbindable key would otherwise leave someone unable to dictate with
  no message explaining why, and the refusal names the keys that do work.
- **Microphone dropdown** mirrors `yazses audio devices` exactly — ● default,
  ★ pinned — including that a pinned value is matched as a *substring*, because
  that is what the recorder does. "Follow the system default" is the first row
  and writes `""`, which is the state most people should be in.
- **VAD slider** is **logarithmic**: the useful range spans three orders of
  magnitude (0.0005 for a quiet voice, 0.05 for a noisy room) and a linear slider
  puts every usable value in the leftmost pixel. It writes a real number, rounded
  to four significant figures so nobody finds `0.004000000000000001` in their
  config, and the meter answers the question behind every "Silent audio --
  discarding" report: is my voice above the line?

Qt-free models in `settingsui/controls.py` with hardware injected — 21 tests, no
keyboard, no microphone, no Qt. (#62)

### Added — the settings window can restart the daemon and prove it came back

Changing a feature writes config, and the daemon reads config at startup — so
until it restarts, the window is showing settings that are not in effect. The CLI
answered that by printing "run `yazses restart`", which is exactly the terminal
round-trip a settings app exists to remove.

Apply now offers a restart, runs the same path as `yazses restart`, and then
**polls `status` over IPC until the daemon answers** before claiming success. A
zero exit code is not a running daemon: it still has to load a model, and a
daemon that dies on startup would otherwise be reported as "Restarted!". Declining
is a first-class outcome — the window keeps a persistent "takes effect when you
restart" hint rather than going quiet and letting you believe a setting is live.

All of the decisions are Qt-free in `settingsui/restart.py` with the IPC client
injected, so the honest-state rules are tested with fakes. (#61)

### Added — Offline Command Mode: rewrite the selection by voice, locally

Select text anywhere, hold the command key, and say **"make this shorter"**, **"fix
the grammar"**, **"turn this into bullet points"**. The selection is rewritten in
place by the local model you already configure for cleanup. Voice-editing of
selected text is the most-praised capability in the paid dictation tools and it is
cloud-only in every product that has it — including the ones whose privacy
failures were around this exact feature. Nothing here leaves your machine.

**A failed or unsafe rewrite never destroys your text.** Each instruction carries
its own plausibility band, so "shorter" that came back longer, or "fix the
grammar" that halved the text, is refused; so is a model that replies "Sure, here
is a shorter version:" instead of doing the work. Every refusal leaves the
selection exactly as you wrote it, and your original is placed on the clipboard
*before* the model is called — the undo path exists before the risky step, not
after it. With nothing selected it falls back to your last dictated burst.

The clipboard gained a read path to make this possible (PRIMARY first, because
highlighting is the gesture people actually make, then CLIPBOARD). Off by default:
`yazses features enable rewrite`, plus a local GGUF under
`[filters.disfluency]`. (#99)

### Fixed — `[stt] vocab_correction` was declared on the wrong dataclass

It landed on `TtsConfig` instead of `SttConfig`, so `[stt] vocab_correction = true`
was dropped by the config loader and the feature could never turn on — silently,
because the daemon reads the flag with a defaulted `getattr`. Found by the new
example-config generator, which reads the real dataclasses; a test now asserts
every documented key exists on the class it is documented under.

### Added — four documentation gaps closed

- **`examples/config.toml`** is annotated and **generated from the dataclass
  defaults**, with a test that fails when it drifts. The previous hand-written
  example said `key = "space"` and `model = "tiny.en"` long after the defaults had
  moved — the file newcomers were told to copy taught them settings the program no
  longer used. (#20)
- **[Choosing a model](models.md)** — measured word-error rate, latency and memory
  for `tiny.en`/`base.en`/`small.en`, from this project's own benchmark harness
  rather than model cards, plus when Parakeet or Moonshine is the better answer.
  Its headline: `small.en` cuts errors by a third and costs 3× the wait, which is
  why the default sits where it does. (#16)
- **[Platform support](platform-support.md)** — one matrix of OS × capability,
  derived from the backends that actually ship, with the reason behind the two
  ❌ rows (Wayland forbids one client focusing or reading another's window, so
  voice window control and gaze routing are X11-only by design, not by omission).
  (#19)
- **[Dictating code and technical vocabulary](use-cases/dictating-code.md)** — the
  top use case had no page. Exact commands for `yazses vocab`, the new
  `vocab_correction`, spoken punctuation and `initial_prompt`, and why a bigger
  model is usually the wrong fix for a word it has never heard. (#250)
### Added — a native Windows arm64 installer, and translated READMEs that lead with installation

Windows on ARM is a real desktop target and the only `.exe` was x64, so an ARM user could
run it under emulation but never got a native build. This was left alone while the Windows
port itself was broken end to end; now that it is fixed, the architecture gap is worth
closing.

The target architecture was hardcoded in three places that had to agree and were never
checked together — Inno Setup's `OutputBaseFilename`, the `$Out` path the build script
verifies, and the workflow globs that locate, upload and attach the result. All three now
derive from one value, taken from the build host (PyInstaller does not cross-compile, so
the runner label *is* the target). The arm64 installer refuses to install on x64, while the
x64 one keeps `x64compatible` so it still runs on ARM under emulation as the fallback.

The arm64 job is advisory: neither `windows-11-arm` nor PyInstaller-on-ARM has run in this
repository, and a new cross-architecture build must not be able to fail a release the x64
build completed fine. `docs/platform-support.md` marks it built-but-unproven rather than
supported.

The Hindi, Chinese and Russian READMEs still had installation at lines 58, 48 and 61, behind
the badges and the feature table — a reader who picked their language got the old
experience. Each now carries an install block under the title, using that file's **own**
existing table lifted verbatim, with a heading reusing a word already present in the
translation. The new English framing lines are deliberately **not** carried over:
machine-translating a project's positioning statement is exactly what reads wrong to a
native speaker, so those are left for a follow-up from someone who speaks each language.

### Fixed — the arm64 artifacts we advertise are now actually built

The arm64 gap was documented but nothing built the artifacts, so the docs described a hole
that stayed open every release. `snap.yml` — the only publisher to `stable` — ran one amd64
job, so `snap install yazses` could not resolve a revision at all on a Raspberry Pi.
`release.yml` built a single amd64 `.deb`, while `update-apt-repo.sh` had always written
`Architectures "amd64 arm64 all"` into the APT `Release` file — so an arm64 machine added
the repo and found no package.

Both are now a matrix with a native job per architecture (`ubuntu-latest` and
`ubuntu-24.04-arm`; arm64 runners are free for public repos). Release creation moved into
its own job — two matrix jobs both calling `action-gh-release` would race on one tag.
Artifacts are architecture-qualified, `fail-fast` is off so one arch cannot cancel the
other and leave a release half-updated, and each build asserts the produced filename really
carries the expected architecture: a wrong runner label would otherwise ship a second amd64
artifact behind a green tick. `apt-repo.yml` ingests every `deb-package-*` artifact instead
of one fixed name. `build-deb.sh` needed no change — it already reads
`dpkg --print-architecture`. **The store does not change until the next tag is pushed.**

### Added — BSD backends, and an unsupported OS that degrades instead of crashing

FreeBSD, OpenBSD, NetBSD and DragonFly now get a real backend, composed from the Linux one
rather than reimplemented: `linux/paths.py` is `platformdirs` and already returns the XDG
locations BSDs use, IPC is a Unix socket, the injection tools are all in ports, and FreeBSD
exposes `/dev/input/event*` with `EVDEV_SUPPORT`. Detection is a **prefix** match —
`sys.platform` is `freebsd14`, never `freebsd`. Only autostart differs (no per-user
systemd), so `BsdLifecycle` refuses with rc.d instructions instead of writing a `.service`
file nothing on the system reads.

`python-xlib` was gated `sys_platform == "linux"`. It is pure Python and the only hotkey
backend a BSD can get, so `pip install` on FreeBSD would have produced an install with no
way to read the key at all. Now matched on `platform_system` — deliberately not
`sys_platform`, which carries the major version, and PEP 508 has no prefix operator.
`evdev` stays Linux-only, so BSD tries the X11 grab path first and hold-to-talk there needs
an X11 session.

It is marked experimental **at runtime**, not only in docs: `doctor` prints `[WARN]`, not a
reassuring `[OK]`, and a CI job now runs the suite in a real FreeBSD VM (advisory until it
has been green a few times).

And a system with no backend is no longer one where nothing works. `doctor`, `status`,
`features` and `quickstart` used to die with an unhandled traceback — the worst answer from
the command you run to find out whether it works. The error now names the supported set and
what still runs, via a `cli:main` wrapper (Click's standalone mode only converts its own
exception types). `transcribe` needed the platform only for two paths, so a new
`platform.get_paths()` resolves the layout on any OS — otherwise the error would have
claimed `transcribe` worked while being raised by `transcribe`.

### Added — the terminal draws the real logo, and the README leads with installation

The docs site, favicon, Snap listing and tray badge are one mark: a "Y" over a listening
sound-wave. The terminal drew an unrelated figlet wordmark, only in `yazses about`. It now
draws that mark with the brand gradient swept diagonally per character, and `quickstart`
ripples the wave once before it settles. Everything degrades — truecolor → 256 → none, and
Unicode blocks → ASCII, covering the text too, since our own tagline carries an em dash.

The README opened with a language switcher, thirteen badges, a competitor paragraph, a GIF,
two asks and a feature table before, around line 75, saying how to install it. Installation
is now the first thing on the page, with a per-OS table; everything else still exists,
below it. `docs/platform-support.md` is new and answers what nothing did: this OS and this
CPU — does it run, and how do I install it.

### Added — the personal dictionary now reaches every engine

`initial_prompt` is a Whisper concept, so with `[stt] engine = "parakeet"` the
personal dictionary, the built-in name and `[stt] initial_prompt` were all
silently dropped — switching engines for the speed cost you your only fix for
names, jargon and code identifiers. `postprocess/vocab_correct.py` recovers
mis-heard vocabulary **after** decoding, which is engine-agnostic and helps
Whisper too. Matching is a phonetic key plus an edit-distance guard, with the
budget scaled by how discriminative the key is.

Most of the work is refusing to fire. Running the corrector over this project's
own documentation with a control vocabulary that does not occur in it — so any
change is definitionally a false positive — found three defects before release:
891 hits rewriting the lowercase command name (a case difference is not a
mis-hearing, and "run yazses doctor" must not become "run YazSes doctor"); `yazses
say` read as a mangled "YazSes", deleting the subcommand; and `from this` →
`Prometheus`, because f and p share a phonetic class. Stopwords may no longer take
part in a multi-word match, and possessives keep their suffix. OFF by default
(`[stt] vocab_correction`); every substitution is logged. (#73)

### Added — a third STT engine, and a denoiser that can actually be installed

**Moonshine** (`[stt] engine = "moonshine"`) is built for short segments on CPU,
which is the shape of hold-to-talk, and needs only `onnxruntime` + `tokenizers` —
no torch. The adapter absorbs two upstream facts read out of the published wheel:
`transcribe()` returns a *list* (using it as a string would type `['hello']` into
your document), and audio must be 2-D and between 0.1 s and 64 s, enforced with
bare `assert`s. Both bounds are reachable — a key tap is under 0.1 s, a paragraph
is over 64 s — so short buffers return empty and long ones split on the silence
gate. (#74)

**Noise suppression** finally has a backend. The seam shipped with only a
DeepFilterNet adapter, which no environment can satisfy: its latest release
(2023-08-31) pins `numpy<2.0` against this project's `numpy>=2.4.6`.
`denoise/spectral.py` (`noisereduce`) has no numpy ceiling and no torch, and is
now the default. It is weaker than DeepFilterNet and the docs say so — it removes
steady broadband noise, not a second speaker. (#69)

### Added — graded squeeze, and EMG hardware you can buy

The EMG backend answered one question: is the muscle tense? Grip force regresses
at r≈0.97 in the literature, so a squeeze can carry *which mode* too — **light
squeezes to dictate, hard squeezes for command mode**, mirroring the command key
so all three mode switches behave the same way. Onset uses the Teager–Kaiser
energy operator rather than a bare threshold, because TKEO weighs frequency as
well as amplitude and so ignores the baseline wander a rectified threshold reads
as a contraction. Thresholds come from the user's own relaxed baseline and
maximum contraction — muscle amplitude varies by an order of magnitude between
people, so fixed microvolt numbers are meaningless, and an indistinguishable
baseline is refused rather than guessed at.

A BrainFlow source (`emg-band` extra) adds OpenBCI, Muse and friends alongside the
DIY serial path. A missing device or dependency is a logged no-op, and the session
is released even after an error — an un-released board keeps the device locked for
every later run. (#103)

### Added — gaze calibration that refines itself from ordinary clicks

A click is ground truth for where you were looking. Explicit calibration drifts
within a session, and every desktop gaze tool answers that with another wizard.
`gaze/implicit.py` is recursive least squares over the existing affine map —
the same estimator, updated one sample at a time, so cost per click is constant
and no history is retained. Guarded on eye-agreement confidence and a residual
gate, with a forgetting factor so it follows a moved laptop lid; and
`refined_if_better` only replaces the wizard's map when the candidate wins on
**held-out** samples, per ADR-014. (#101)

### Fixed — the semantic contract could not tell a dose correction from its inverse

`contract/semantic/invariants.json` promised its flagship case preserved "the
marker that says which value supersedes the other". It could not: `quantity` is a
set dimension and `must_preserve` is a subset assertion, so "give him fifty,
sorry, fifteen milligrams" and its inversion both extract {15, 50} with a
correction marker and satisfied the invariant identically — while meaning the
opposite. `must_preserve_relation` pins which value wins, positionally, and the
inverted sentence is now a case in its own right so the assertion is proven to
have teeth. Contract 6.1.0 → 6.2.0. Raised by @YossiMH in the #98 review. (#163)


### Added — an activation source can say *what* it meant, not just *when*

`HotkeyBackend` could express two things: a hold started, a hold ended. That is the
whole vocabulary of a key, and it is enough for a key. Every silent-speech and BCI
system in the literature produces something richer — a command label with a confidence —
and none of it fitted through an onset/offset seam, so a decoder that recognised "undo"
at 96% had to discard the label, emit a bare onset, and wait for the user to say the
word out loud. That is the opposite of what a silent interface is for.

A source may now declare a **vocabulary** and emit an **intent** (label + confidence).
Labels are validated against that declaration before anything else runs, so a source
cannot ask for something it never advertised, and the label then goes through the
**existing** command grammar and dispatcher — a silent "undo" and a spoken "undo" cannot
drift apart, because there is one implementation of what "undo" means. Injecting decoded
free text is deliberately out of scope: non-invasive decoding sits around 68% WER, so it
would be typing noise. `EMGBackend` is untouched — it declares no vocabulary. Off by
default under `[activation]`; nothing changes without an intent-carrying source. (#137)

**A decoded intent is gated on confidence × consequence, and an irreversible action
always confirms** — at any confidence. Best reported silent-command accuracy is 96–97%
over 10–30 words, in-session, on 3–4 subjects, so roughly one command in thirty is wrong
and there is no threshold that makes silently executing something unrecoverable
defensible. Reversible actions act above `confirm_threshold` (0.90, chosen just below the
reported operating point) and confirm below it; anything under `reject_floor` (0.50) is
dropped rather than prompted, because asking people to confirm coin flips teaches them to
dismiss prompts. Consequence is an **allow-list** of recoverable actions, so a command
added later confirms rather than fires, and a test walks the dispatcher and fails if any
action was never classified. (#138)

`contract/vectors/activation.json` (20 cases, contract 6.0.0 → 6.1.0) lets an external
decoder prove conformance **without reading our source**: onset/offset pairs, intents with
confidence, out-of-vocabulary and empty labels, confidence of 1.4 and -0.5, a repeated
onset, and a source that disappears mid-hold. (#139)

### Added — focus a window by name, and the modality router is finally real

"focus the browser", "switch to gedit". Matching reuses the file opener's fuzzy ranker
rather than a second implementation, so the two cannot answer differently for the same
words. **An ambiguous query focuses nothing** — two windows scoring alike would send your
next sentence into a document you were not looking at — and a command that matched nothing
is still not typed into your document. X11 only, and reported as such: Wayland forbids one
client focusing another's window and no portal exposes it, so `yazses doctor` gains a
"Voice window focus" line saying why and what still works. `windowctl` leaves the
`_UNWIRED` set because a runtime path genuinely reads it now. (#39)

The ADR-v2-011 **modality role router** had been pure policy with no caller since July, so
enabling `[modality]` wrote a key nothing read. It now resolves roles from what is actually
available — gaze counts only if the targeter really built — and decides whether EMG owns
commands. Reported in `yazses doctor` and over IPC. (#136)

### Added — the settings window installs a feature's packages

`yazses features enable <slug>` has always installed a capability's optional packages
before telling you to restart; the settings window wrote the config key and stopped. For
the 15 rows that need an extra that produced `enabled = true` and a daemon that could not
load the feature. Both front ends now make the identical `system/deps.py` call, on a
worker thread, streaming pip's real output — a mediapipe install takes minutes, and on the
Qt main thread that is indistinguishable from a hang.

**When an install fails the config key stands**, and the window says the capability is on
but dormant until its packages arrive. Rolling back would silently undo a switch you just
moved, and a transient network blip would look like a broken window; "enabled but dormant"
is a state `doctor` and `features` already model and a retry fixes. The *impossible* case
is unchanged — enabling is refused before anything is written. (#135)

### Fixed — "click bookmark" created a bookmark instead of typing it

`parse_bookmark_command` was anchored only at the end, so any sentence ending in the
ordinary English word "bookmark" was swallowed as a command. Same failure as
`commands/revise.py::_SCRATCH_RE`, fixed the same way with a both-ends anchor.

### Changed — session bookmarks resolve a real caret

The earlier approach counted characters YazSes had injected and jumped by sending that
many arrow keys. It desynchronised permanently after the first mouse click, grew into an
unbounded key injection, and bypassed the no-text-target guard. Bookmarks now store a
position the toolkit reports (AT-SPI's `Text.caretOffset`), scoped to a **document** rather
than a session, and jumping is one positioning call. Refusing is designed behaviour, not a
fallback: no backend, no caret, unknown name, or a caret now in a different document each
refuse and move nothing — a jump into the wrong file would drop your next dictation there.
`bookmarks` stays `_UNWIRED` until a daemon path calls it. (#162)

### Documentation

- **Translations get a status matrix and a read-only drift checker.** English is the source
  of truth and the translations are native human work, so nothing rewrites them — the
  checker reports and leaves the fix to someone who reads the language. It catches the
  damaging case: a *translated command*. `yazses диагностика` is not a command, and a
  reader who types it gets an error instead of a tool. Runs in CI, stdlib-only.
  `docs/localization/STATUS.md` carries the matrix and the update procedure. (#166)
- **A reproducible offline-inference challenge** (`docs/launch/offline-challenge.md`) and a
  report template, built around the distinction that decides whether a result means
  anything: installing and downloading a model needs the network, transcribing does not.
  Called a demonstration, never proof of privacy — one run on one machine cannot establish
  that. (#168)
- **Multilingual dictation gains an offline smoke test**, guidance for recording your own
  fixture (the repo ships none: a recording is personal data and corpus licensing varies
  clip by clip), and a reporting matrix. Tests pin the trap at mocked boundaries — an `.en`
  checkpoint has no language tokens, so pointing one at German transliterates into
  fluent-looking English nonsense rather than failing. (#167)

## [2.18.2] - 2026-08-13

### Fixed — cutting a release could not publish to PyPI

v2.18.1 was the first release tagged after `tests/test_platform_windows_hardening.py`
landed, and it deadlocked. `release.yml` runs the suite **at the new tag**, and
`_released_version()` returned that tag — so the manifest tests demanded that the
packaging manifests already describe a release whose assets did not exist yet. The
`.exe` and `.dmg` published from their own workflows, and PyPI never received 2.18.1
at all, because the publish job sits behind that gate.

The docstring had reasoned the gap away in one direction only: using the tag instead
of `pyproject.toml` stops `main` going red on the release *commit*, but it moves the
impossible window rather than closing it — straight onto the release itself.

`_released_version()` now ignores the tag being released, detected from
`GITHUB_REF_TYPE`/`GITHUB_REF_NAME`, so during a release it reports the previous
published version — which is what the manifests correctly describe at that moment.
**The gate is not weakened:** on `main` there is no tag ref and the behaviour is
unchanged, so `main` still goes red after a release until the manifests are
refreshed, which is the pressure that keeps them honest. Both directions are pinned
by tests.

Also carries the v2.18.1 manifest refresh: scoop, the chocolatey nuspec and its
install script, the winget manifests and the Homebrew cask now point at the v2.18.1
assets with checksums taken from the published files rather than by hand.

## [2.18.1] - 2026-08-13

### Added — two backends that config offered but no build could run (#70, #71)

`[voiceprint] backend = "resemblyzer"` and `[recimport]`/`[meeting] backend = "pyannote"`
were accepted by the config loader and then reported as *not implemented in this build*.
Both now ship an adapter, each behind its own extra — `voiceprint-resemblyzer` and
`diarization-pyannote`. Neither may advise the extra it sits beside: `voiceprint` is
speechbrain and `diarization` is sherpa-onnx, so naming those would send you after a
package that cannot supply the backend you picked. sherpa and ECAPA remain the defaults.

Resemblyzer does **not** simply call `embed_utterance`. That function slices audio into
1.6 s partials and zero-pads anything shorter, with no flag to disable it — so a 500 ms
Cocktail Filter window would be encoded as 0.5 s of speech plus 1.1 s of digital silence.
Below the partial length the adapter runs the same encoder directly on the frame instead.
Measured on the bundled sample, same-speaker similarity against a full-utterance
reference: **0.647 vs 0.509 at 500 ms** and **0.766 vs 0.605 at 1000 ms**, converging by
1500 ms. The Cocktail Filter's default `target_threshold` is `0.5`, so the padding was
dragging a speaker's *own* voice onto the rejection line.

### Fixed — enabling pyannote diarization would have sent usage data off the machine

pyannote.audio 4.x ships OpenTelemetry tracking that is **on by default**: its bundled
`telemetry/config.yaml` sets `metrics_enabled: true` with an OTLP endpoint at
`otel.pyannote.ai`, and its `track_pipeline_apply` hook reports the **duration of the audio
being diarized** along with the requested speaker counts. `telemetry_log_level` is pinned
to `CRITICAL`, so it says nothing either way. This is not an optional extra —
`opentelemetry-exporter-otlp` and `pyannoteai-sdk` are hard requirements of the package.

No audio would have been transmitted, but the length of your meetings and your usage
pattern would have been, silently, from a tool whose entire promise is that nothing leaves
the machine (ADR-011). The backend now sets `PYANNOTE_METRICS_ENABLED=false` **before**
importing pyannote — the ordering is the mechanism, because upstream defaults the variable
from its config file only when it is not already set, so disabling it afterwards would let
the import-time tracker fire first. A test pins the ordering, not just the value.

### Fixed — `missing_modules` raised instead of answering for dotted module names

`importlib.util.find_spec` returns `None` for an absent top-level module but *raises*
`ModuleNotFoundError` for a dotted name whose parent package is absent — it must import the
parent to look inside it. `pyannote.audio` is the only backend asked about by dotted name,
so the exception escaped into `recimport.factory._unavailable_detail`, whose blanket
`except` then reported an unrelated error (`No module named 'torch'`) instead of the honest
"install the `diarization-pyannote` extra". The whole point of that honesty layer was
defeated for exactly one backend, and nothing noticed because no test used a dotted name.

### Not shipped — DeepFilterNet noise suppression cannot be packaged (#69)

`[denoise] backend = "deepfilternet"` stays honestly unimplemented, and there is
deliberately **no `denoise` extra**. Every release of DeepFilterNet caps `numpy<2.0` while
this project requires `numpy>=2.4.6`; the resolver's verdict is that "all versions of
deepfilternet and all versions of yazses are incompatible", on every Python version.
Behind that sit three more problems: `deepfilterlib` publishes wheels only up to cp311
(so 3.12 would attempt a Rust build from sdist), it does not declare torch or torchaudio
despite needing both, and its last release was August 2023. An extra that can never
install is a worse lie than an honest "not implemented in this build", so the seam and its
warning are unchanged. A numpy-2-compatible backend would be a different issue.

### Fixed — dictation cleanup could POST your transcribed text to any host you typed

`[filters.disfluency] llm_endpoint` is a plain string, and when no local GGUF model was
configured, cleanup POSTed the **transcribed text** to whatever it contained. The value was
never checked for being local. The code was written for local Ollama — the default is
`http://localhost:11434` and the call site even carried a `# noqa: S310 - localhost only`
comment recording that intent — but nothing enforced it, so a typo or a copied config line
pointing at a real host turned an offline-first tool into an exfiltrating one, silently.

YazSes now checks the endpoint is loopback (`localhost`, `127.0.0.0/8`, `::1`) before any
request. A non-loopback endpoint **disables cleanup and logs why**, once, rather than per
burst. Sending dictated text off the machine now takes a second, separate, deliberate
setting — `llm_allow_remote_endpoint = true`, off by default.

A hostname that merely *resolves* to loopback is deliberately **not** trusted. DNS is
controlled by whoever owns the zone and the answer can change between the check and the
connection, so classifying by resolution would make the guard depend on the network it
exists to avoid. `localtest.me` is pinned in the tests as the case that must stay refused,
alongside `localhost.evil.com` for the suffix trick.

Nothing changes for anyone running Ollama locally, which is the documented setup and the
default. The local GGUF backend never touched this path at all.

### Fixed — the privacy statement claimed cleanup made "no HTTP API call"

It made one. `docs/privacy-statement.md` grouped dictation cleanup with the SLM intent
router as in-process `llama-cpp-python` and stated there was "no cloud LLM, no OpenAI/Azure
backend, and **no HTTP API call**". The router is genuinely in-process, but cleanup's
fallback backend is an HTTP POST to Ollama — local by default, but a socket nonetheless.
The section now says which backend does what, names the one call that carries text, and
documents the loopback guard and its opt-out. "What leaves your device" now names both
paths that can, rather than only `yazses remote`.
### Fixed — Windows: hold-to-talk, command keys, and the liveness probe that killed the daemon

Eleven defects in `platform/windows/`, found by audit and each pinned by a regression test.
Three of them meant core features could never have worked on Windows:

- **`yazses status` terminated the daemon.** `is_running()` used `os.kill(pid, 0)` as a
  liveness probe. That is the POSIX idiom; on Windows CPython's `os.kill` has no signal
  semantics and falls through to `TerminateProcess(handle, sig)`, so signal 0 *kills the
  process* with exit code 0 ([bpo-14480](https://bugs.python.org/issue14480)). `status`,
  `doctor` and the tray's poll loop all reach it. Replaced with `OpenProcess` +
  `GetExitCodeProcess`.
- **Hold-to-talk never started.** The hold threshold was only re-checked when another key
  event arrived, which assumes typematic auto-repeat. Modifier keys — every supported hotkey
  except `space` — do not repeat, so with the default `right_ctrl` the single keydown landed
  at t=0 and the next event was the keyup. A character key (`space`) now waits out the
  threshold on a timer, as in the X11 backend, so it is no longer silently replaced by the
  user's repeat-delay setting. A **modifier starts the instant it goes down** — it types
  nothing, so there is no tap to tell from a hold and nothing to wait for, and waiting would
  discard the opening words of every dictation (the pre-speech padding is a silence lead-in,
  not buffered audio). That matches `evdev_hold.py`, so Linux and Windows feel the same.
- **Every named command key was a no-op.** The VK table was keyed capitalised
  (`"Return"`) but looked up lower-cased, so `Return`, `Tab`, `Escape`, `BackSpace` and the
  arrows all resolved to `vk=0` — a keystroke Windows accepts and discards. `Home`, `End`,
  `Page_Up` and `Page_Down` were missing from the table entirely. Unknown keys now log and
  skip instead of injecting `vk=0`, and a contract test walks the dispatcher's real key
  tables so a future binding Windows cannot express fails in CI.

Also fixed: 64-bit handle truncation (`SetWindowsHookExW`/`GetModuleHandleW` had no
`restype`, so ctypes truncated their pointers to `int`); `ctypes.get_last_error()` read off a
library opened without `use_last_error`, so every "lastError=…" reported 0; a named-pipe
handle leak that permanently consumed one of eight instances per failed accept and left IPC
dead after eight; the IPC client storing `timeout_s` and never applying it, so the CLI hung
forever on a wedged daemon where the Unix client times out; an autostart value written
unquoted and without `--tray`, which broke on any username containing a space and overwrote
the installer's correct value; and a recycled-PID guard that matched `"python"` anywhere in
the `tasklist` row, including window titles.

### Fixed — Windows packaging manifests no longer ship a release behind

`scoop`, `chocolatey` and `winget` pin a version and a SHA256 by hand and nothing in the
release pipeline touches them, so they sat at 2.17.0 — carrying the *previous* release's
checksum — after 2.18.0 shipped. Bumped to 2.18.0 against the real published asset
(`YazSes-2.18.0-windows-x64.exe`, sha256 `d5d78e9d…646a`, verified by download), and guarded
by tests that check every manifest against `pyproject.toml` and cross-check the two channels'
checksums against each other. `installer.iss` was already correct — it reads
`YAZSES_VERSION` from the build script.

### Fixed — the Windows installer build could never have run

Three more defects in the bundle itself, all invisible because the binary is windowed and
nothing in CI ever installed the artefact it built:

- **The daemon could not start at all.** The tray spawned it as
  `YazSes.exe -m yazses.main`, but the bundle dispatches on argv and knows only
  `--daemon`/`--tray`/`--cli`. `-m` matched nothing, fell through to the Typer CLI and
  exited 2 while parsing it. With no console attached that error went nowhere, so the tray
  reported "not running" for ever with no diagnostic. Resolution now goes through a pure
  `resolve_daemon_command()`, tested for the frozen and pip-installed cases.
- **The entire CLI was unreachable.** `doctor`, `verify`, `status`, `logs` and `report`
  existed only inside a GUI-subsystem binary, which has no stdout, and the installer put
  nothing on PATH — so no user could run a diagnostic and no maintainer could ask for one.
  The bundle now also builds `yazses-cli.exe` (console) from the same PyInstaller Analysis,
  shipped behind a `yazses` shim and added to the per-user PATH. Uninstall removes that one
  entry surgically; `uninsdeletevalue` on `Path` would have deleted the user's whole PATH.
- **Injected keystrokes were untagged.** Synthetic events carried no `dwExtraInfo`, so the
  hook saw the app's own Ctrl presses and could trigger itself — the self-capture the Linux
  backend avoids by refusing to listen on ydotool/uinput devices.

- **`yazses --version` crashed in the bundle.** PyInstaller ships no `.dist-info`
  unless asked, so `importlib.metadata.version("yazses")` raised
  `PackageNotFoundError` — and `--version`, `about`, `doctor`, `update` and the
  diagnostic report all read it. The CLI was the one call site missing the guard
  that `__init__`, `branding` and `doctor` already had. The spec now bundles the
  metadata and the lookup degrades instead of raising. **Found by the new smoke
  test on its first run**, which is the whole argument for having it.

### Added — the gate whose absence let all of this ship

`build-windows.yml` now installs the built artefact silently, asserts the payload, requires
the CLI to actually print, exercises the shim and the PATH entry, then uninstalls and checks
PATH survived. `tests/test_packaging_windows.py` binds the spec, the shim, the installer
script and the Python entry point together on Linux CI, where the suite actually runs.

### Documentation

`docs/windows-install.md` gave the install location as `%USERPROFILE%\YazSes` in every
release so far. It is `%LOCALAPPDATA%\Programs\YazSes` — the documented path never existed,
so the uninstaller and CLI instructions pointed nowhere.

### Added — `brew install --cask yazses` works, via a real tap

The cask has existed in `packaging/homebrew/` since v1, and `brew install yazses` has
404'd that entire time, because a manifest that never reaches a registry installs nobody.
The tap is now published at
**[MSKazemi/homebrew-yazses](https://github.com/MSKazemi/homebrew-yazses)**:

```sh
brew tap MSKazemi/yazses
brew install --cask yazses
```

`Casks/yazses.rb` there is byte-identical to `packaging/homebrew/yazses.rb`, which stays
the source of truth; copying it across is a step in the post-release checklist in
`packaging/README.md`. Closes [#6](https://github.com/MSKazemi/yazses/issues/6).

Apple Silicon only — see the architecture note below. The install itself has **not** been
run end to end, because casks only install on macOS; what is verified is that the tap is
public, the cask is served intact, and the `.dmg` URL and checksum match the released
asset.

### Fixed — every macOS `.app` since v0.1.3 told the OS it was version 0.1.2

`packaging/macos/yazses.spec` set `CFBundleVersion` and `CFBundleShortVersionString` as
string literals, and they were last touched at v0.1.2. Every `.dmg` from v0.1.3 through
v2.18.0 therefore shipped a bundle that reported **0.1.2** to macOS. Finder's *Get Info*,
`mdls`, and anything comparing `CFBundleShortVersionString` all read that number, so a
genuine upgrade looked like a downgrade.

Nothing surfaced it because the value is only observable on a built `.app`, which requires
a Mac. The spec now reads the version from `pyproject.toml`, so the two cannot drift, and
`tests/test_packaging_macos.py` fails if the literal ever comes back.

### Fixed — the Homebrew cask was a release behind, and would have installed a broken app on Intel

Two independent problems in `packaging/homebrew/yazses.rb`:

**Stale.** It pinned `2.17.0` and that release's checksum while `2.18.0` was current.
Homebrew verifies the digest, so this is not a cosmetic lag — the download is refused and
the first thing a new user sees looks like a broken project. Refreshed from the real
attached asset via `scripts/refresh-package-manifests.py`. That step is manual and no
workflow runs it, which is how it drifted; the file now says so at the top instead of
implying it is automatic.

**Architecture.** The `.dmg` is built on `macos-latest`, which is an **arm64** image (the
v2.18.0 run resolved Python to `aarch64-apple-darwin`), and the spec passes
`target_arch=None` — host architecture, *not* `universal2`, whatever the comment there
claimed. The shipped `.dmg` has no `x86_64` slice and cannot launch on an Intel Mac, yet
the cask had no architecture constraint and `docs/macos-install.md` explicitly promised
"Apple Silicon or Intel".

The cask now declares `depends_on arch: :arm64` so Homebrew refuses cleanly instead of
installing something that silently fails to start, and both the cask caveats and the macOS
guide route Intel users to `pipx install yazses`, which is architecture independent.

`universal2` is not reachable by editing that one value: PyInstaller emits a universal
binary only when every bundled native dependency is universal, and `ctranslate2` publishes
separate arm64 and x86_64 macOS wheels. Real Intel coverage needs a second CI job on an
Intel runner, and GitHub now offers those only as `-large`/`-intel` labels, which are
billed even for public repositories. That is a spend decision, so it is written down in
`packaging/README.md` rather than quietly assumed.

## [2.18.0] - 2026-08-13

### Changed — Qt is the `desktop` extra now, and a headless install is ~650 MB lighter

A `uv tool install` was **1.1 GB**, and **648 MB of it — 59% — was PySide6**, present for
exactly two features: the voice-activity overlay and the system tray. Every install that
could never display either paid the full price — servers, containers, CI, and anyone who
only runs `yazses transcribe`, which does not import it at all.

**Nothing regresses for a desktop user.** `install.sh`, the `.deb` and the Snap all pull the
`desktop` extra, so the tray and the overlay appear exactly as before; `yazses features
enable tray|overlay` fetches Qt afterwards for anyone who changes their mind later. Base
dependencies go 17 → 16.

Two ways this could have broken people, both closed and both pinned by tests. The Snap never
staged PySide6 — it arrived as a base dependency — and a snap can **never** pip-install at
runtime (read-only squashfs plus PEP 668), so shipping this without adding it to
`python-packages` would have removed both features for the life of the revision,
unrecoverably. And `tray` was missing from `_FEATURE_DEPS`, so enabling the tray on a
headless install could not have fetched its own dependency.

The dependency-budget gate rejected the new extra for being unmapped, which was correct — an
unmapped extra is enforced by nothing. Mapping it exposed that the `overlay` and `parakeet`
exemptions both still read "already ships in the base install", which is now false for both.

### Added — Russian README, and the badge guard that should already have covered it

`README.ru.md` (lede, three-things, Quick Start — modules 1–2 of
[`i18n/modules.yml`](i18n/modules.yml), which is a complete contribution), contributed by
[@4nmus](https://github.com/4nmus). Every command, config key, path and code block is
byte-identical to `README.md`, the untranslated tail below Quick Start is byte-identical to
the English original, and `Русский` now appears in the language switcher of all four
READMEs. It is the first Cyrillic-script translation the project has had.

Adding it exposed that `tests/test_citation_metadata.py` checked the Zenodo DOI badge in a
**hard-coded** `("README.md", "README.hi.md")`. Every translation carries its own copy of
that badge, so `README.zh-CN.md` had already shipped unguarded and `README.ru.md` would
have too — a copied identifier nobody re-reads is the exact thing that rots. The check now
globs `README.*.md`, which is what the contributor-wall guard beside it already did.

### Added — the project now asks, once, in the two places someone is actually looking

YazSes had ~583 PyPI downloads a week and four stars. The gap was not that people disliked
it; it was that nothing ever asked. The single existing ask sat on **line 616 of a 616-line
README** — the last line of the file — and the CLI and docs never asked at all.

`yazses quickstart` now closes with one line pointing at the repo, and the README asks
immediately after the demo, where a reader has just watched it work rather than after
scrolling past the licence. Both say the same true thing: there is no company and no ad
budget here, so word of mouth is the whole distribution strategy.

It is deliberately not a nag — `quickstart` is read-only and explicitly invoked, the line
never prompts, never blocks, and appears once per invocation. A test pins both the URL and
the no-repeat property, because an onboarding path that starts begging is worse than one
that never asks.

### Fixed — `install-apt.sh` failed on every container and fresh VM

The script runs under `set -euo pipefail` and read `$USER`. That variable is set by
login shells and by PAM, and is simply **absent** in a container, under `sh -c`, in a
cron job and in some minimal VM images — so `-u` aborted the run. It aborted *after*
apt had installed the package, which is the worst place: a half-configured machine, no
`yazses` on `PATH`, a non-zero exit, and nothing said about why. Anyone evaluating
YazSes in a container or a throwaway VM hit it every time, which is exactly what a
careful person does with an install script piped in from the internet.

The same line was also wrong under `sudo`, which sets `USER=root`: it would have added
**root** to the `input` group and left the actual human without keyboard access. The
user is now resolved as `${SUDO_USER:-${USER:-$(id -un)}}`, which is right in all three
cases.

Re-testing the fix surfaced a second abort of the same shape — `usermod` against a
system with no `input` group — so joining that group is now a warning that prints the
command to run by hand, not a fatal error. A step that is not required for the install
to be usable must not take the install down with it.

### Fixed — loading an already-downloaded model still contacted Hugging Face

`WhisperModel(name)` defaults to `local_files_only=False`, so faster-whisper asked
huggingface_hub to revalidate the snapshot **on every load, even when every file was
already cached**. That put a network round-trip on the startup path of a program whose
first line is that your voice never leaves your machine — the daemon made it on every
single start, and so did `yazses transcribe` and meeting capture.

On a good connection it is a round-trip nobody notices. The problem is that it has no
timeout, so when the call neither succeeds nor fails — a captive portal, a blackholed
firewall rule, hub rate-limiting — the process simply stops. Measured on a machine with
`base.en` fully cached: **over fifteen minutes at "Loading STT model", ~0% CPU, no
output and no error**, against **2.3 s** for the identical command with
`HF_HUB_OFFLINE=1`. A hard failure would have been kinder; an air-gapped machine gets
the hard failure and is fine, which is why this went unnoticed.

The cache is now tried first and the network used only on a miss, so a cached model
loads with no network at all (2.4 s, measured, no environment variables) and a missing
one is downloaded exactly as before. The fallback is the point — trading a hang for a
broken first run would be no improvement — and a genuine download failure still
propagates rather than leaving the engine holding no model.

### Fixed — the Codespaces welcome banner told contributors to run failing commands

`.devcontainer/setup.sh` prints what to do the moment the container finishes building.
It is the first thing anyone sees in a Codespace, and **two of the three commands it
advertised failed on a clean checkout**:

- `uv run ruff check .` exited 1. CI runs `ruff check src tests scripts`, and one
  pre-existing import-order error sat in `design/research/verify_refs.py`, outside that
  scope and therefore never caught. The import order is now fixed, so `.` is clean too,
  and the banner names the same command CI runs — a contributor's green now means CI's
  green rather than something narrower.
- `uv run mypy src` exited 1: `opencc` ships no type stubs, and it arrived with the
  unreleased `chinese_script` work. `opencc.*` joins the existing override list of
  third-party packages without stubs, restoring `mypy src` to **no issues found in 435
  source files**.

A first-time contributor followed a welcome message and got two red gates for problems
that were not theirs. The banner also repeated the sidecar-overwrite from the fix below
— a fourth copy of the same snippet, and the one an evaluator meets first — so it now
passes `-o` and explains why.

### Fixed — the "try it without installing" demo overwrote its own answer key

`docs/try-without-installing.md` mounted `data/librispeech-sample` writable and ran
`yazses jfk.wav`. YazSes writes its transcript as a sidecar beside the input, so that
produced `jfk.txt` — the name of the reference transcript the very next sentence tells
you to compare against.

So the page's instructions destroyed the thing they were about to check, and the
failure mode is the bad one: the comparison then **always** looked perfect, because you
were diffing the model's output against a copy of the model's output. A wrong
transcription would have looked exactly as convincing as a right one, on the page
written to earn a stranger's trust before they install anything. It also silently
dirtied a fresh clone, and `scripts/bench-stt.py` scores WER against that same file.

Fixed everywhere the pattern appeared — the Docker demo, the Codespaces snippet, and
the `--network none` proof in the privacy statement — by mounting the sample read-only
and writing output elsewhere with `-o`. The page now also states that the two files
will *not* match byte for byte: the reference is the unpunctuated LibriSpeech
transcript and YazSes punctuates what it hears, so `Americans, ask not` against
`Americans ask not` is a pass. CI had the safe pattern all along and the docs did not,
which is how this survived; `docker.yml` now runs the documented command verbatim and
fails if the checkout is modified afterwards.

### Fixed — Indic heading anchors dropped every vowel

`pymdownx.slugs.slugify` keeps `[\w\- ]`, and Python's `\w` excludes Unicode combining
marks — `'ा'.isalnum()` is `False`. Devanagari, Tamil, Bengali and Telugu write most of
their vowels as exactly those marks, so the Hindi heading `ईमानदार सीमाएँ` became the
anchor `ईमनदर-समए`, and every deep link into a translated page was dead.

It hid because it was self-consistent: the heading id and its own table-of-contents
entry were mangled identically, so in-page navigation worked. `hooks/indic_slugify.py`
keeps combining marks while preserving the GitHub-compatible spacing the `toc:` config
was chosen for, and `validation.links.anchors: warn` makes a broken anchor fatal under
`--strict`, which it previously was not.

### Fixed — the docs site could be blocked from deploying by Google's CDN

The `Docs` workflow builds with `--strict`, which promotes every warning to an error —
including the five `fonts.gstatic.com` 404s hit while the privacy plugin was mirroring
webfonts on 2026-08-11. The mirror is now cached in CI, so an ordinary run does not
contact Google at all. The fonts remain genuinely self-hosted.

### Fixed — the APT repository lost its fallback URL

Moving the documentation to a workflow-built Pages deployment took the `gh-pages`
branch out of service, so `https://mskazemi.com/yazses/apt/` has been a 404 while
`apt-repo.yml` went on publishing there. No install broke — `install-apt.sh` tries the
`raw.githubusercontent.com` copy first — but of the two sources it knows, only one
worked, leaving the channel on a single point of failure. `docs.yml` now grafts the
repository into the site artifact, and `apt-repo.yml` triggers that deploy after
publishing so the two copies cannot drift (a stale apt index is worse than an absent
one: apt validates `Packages` against the hashes in `InRelease`).

### Fixed — the Debian package named the wrong maintainer

`debian/control`, `debian/copyright`, `debian/changelog`, `scripts/build-deb.sh`,
`scripts/upload-ppa.sh`, `.github/workflows/ppa.yml` and one winget manifest all
carried *Mohsen Seyedkazemi Moghadam*. The correct name is **Mohsen Seyedkazemi
Ardebili**, as used by `CITATION.cff` and `pyproject.toml` — and it is what
`apt show yazses` puts in front of a user, and what `debian/copyright` asserts as the
copyright holder. PPA signing selects the key by ID rather than by `DEBFULLNAME`, so
this does not affect uploads.

### Added — `[stt] chinese_script`, because Chinese users were being handed the wrong alphabet

Dictating 简体中文 got you 繁體字 back, and it looked like a much worse recognizer than it
was. Whisper decides **per utterance** whether to answer in Simplified or Traditional
characters and is not consistent about it; on 20 clean 16 kHz Mandarin utterances (ASCEND
test split, `small` model) **13 came back Traditional**, including ones where the
recognition was word-perfect. `[stt] chinese_script = "simplified" | "traditional"` pins it.

The cost of the inconsistency was mostly invisible, because it was scored as if the model
had misheard. Character error rate against Simplified references, same audio, same model,
one config key changed:

| Model | `chinese_script = ""` | `chinese_script = "simplified"` |
|---|---|---|
| `small` | 35.9% | **16.9%** |
| `large-v3` | 12.3% | **11.3%** |

Note which row moves. The setting is worth 19 points on `small` and one point on
`large-v3` — the big model already leans Simplified — so this rescues precisely the
small, fast models a CPU user actually runs.

Off by default, because the right answer is regional rather than universal: Taiwan and
Hong Kong users want the Traditional output this would convert away. Enable with
`yazses features enable chinese-script`, which installs the new `chinese` extra
(`opencc`, pure Python, imported lazily — the base install stays at 16 dependencies).
Wired once at the `stt/factory.py` chokepoint, so dictation, `yazses transcribe`, meeting
capture and the streaming decoder all get it; per-word output is converted too, so
subtitles and speaker labels do not disagree with the transcript.

Rejected along the way: forcing the script through `initial_prompt`. It does work
(0/12 Traditional) but degrades recognition — `base` went 43.1% → 59.0% raw CER — so
conversion happens after the decode, where it cannot disturb it. A reversible character
mapping cannot repair a mishearing, and the docs say so rather than implying it can.

Chinese dictation is documented as **usable but still rough**, with the corpus caveats
stated and a recommendation to test on your own audio first:
[中文语音输入](docs/zh/chinese-voice-typing.md) · [English](docs/use-cases/chinese-voice-typing.md).

### Added — Simplified Chinese README and documentation

`README.zh-CN.md` (lede, three-things, Quick Start, plus a Chinese-usage section the other
translations have no equivalent of) and a Chinese/English pair of use-case pages carrying
reciprocal `hreflang`. `zh` joins `hi` in the hreflang hook's language directories.

### Removed — the DCO sign-off gate, which was quietly unfixable for browser contributors

There is now **nothing to sign** to contribute to YazSes: no CLA, no DCO, no `Signed-off-by`
trailer, no check to trip over. Opening the pull request is the whole contract.

The DCO lasted seventeen hours and failed every time it ran. It went in on 2026-08-10 at
20:59 UTC; seventy-one minutes later a first-time contributor opened the Hindi README
translation (#165) and the check went red, twice. Their commits carried `committer: GitHub`
— they had worked in the web editor and never had a clone — while the failure message told
them to run `git commit --amend --signoff`, `git push --force-with-lease`, and
`git rebase --signoff origin/main`. None of those exist without a clone, and the workflow
offered no browser path at all. The same issue bodies said, eight lines apart, *"`git commit
-s` — the sign-off is required"* and *"You need nothing installed. This is doable entirely in
the GitHub web editor."* Both sentences were shipped in eighty-one open tasks, forty-six of
them translations and test reports that are meant to be done in a browser.

Nothing legal is lost. Apache-2.0 section 5 already grants the inbound licence — *"any
Contribution intentionally submitted for inclusion in the Work by You to the Licensor shall
be under the terms and conditions of this License"* — which is why most Apache-2.0 projects
run without a CLA or a DCO. The sign-off was re-certifying a grant the licence already made,
at the cost of a red check on a newcomer's first pull request.

Removed `DCO.md` and `.github/workflows/dco.yml`, and the sign-off step from `CONTRIBUTING.md`,
`REVIEWING.md`, `docs/contribute/start.md`, the pull-request template, and the sprint kit.
"There is nothing to sign" now also leads the README's Contributing section and the
first-time-contributor greeting, because the moment a newcomer worries about paperwork is
before they open the PR, not after.

The greeting itself was a near-miss worth recording: it was added on 2026-08-10 with the
action's **v2 hyphenated** input names, crashed on `Input required and not supplied:
issue_message`, and was repaired **24 minutes after** the first real first-timer's PR had
already gone ungreeted. It is correct now — the action validates `issue_message` even on a
pull-request event, which is exactly how it failed, so the 93 successful issue runs since
prove both input names resolve for both paths.

### Changed — the contributor taxonomy is now actually applied

`browser-only`, `hardware-required` and `cloud-agent-ready` were defined with good
descriptions and applied to **zero** of the 162 open issues, so `good first issue` sat on 98
of them and told a newcomer nothing. The labels are now set from evidence in each issue body
rather than a guess: 27 `browser-only`, 43 `hardware-required`, and a new `under 1 hour` on
the 54 tasks that state their own estimate. Umbrella issues are skipped — they quote the
evidence of the tasks they list, which is how #22 nearly acquired `hardware-required` for
mentioning other people's webcams.

`good first issue` is deliberately left in place on all 98. It is a discovery surface, not
just a hint: goodfirstissues.com is a confirmed referrer and GitHub's own `/contribute` page
reads that label. Narrowing it would have removed the project from both.

### Added — a filterable task finder

`docs/contribute/find.md` lets someone narrow 130 open tasks by what they physically have,
how much time they have, and whether they want to write code. The static table answers "what
is open"; it does not answer "which of these 297 compatibility tasks is *mine*", which is the
only question a newcomer on Fedora with KDE actually has, and scanning for it is the friction
that loses people between arriving and starting.

Every row is rendered into the HTML and the script only hides and shows. A finder that builds
its list in JavaScript is an empty box to anyone with JS off, to a text browser, and to every
crawler — including the answer engines this project wants citing it. It makes no third-party
request either, which is the only acceptable behaviour on the documentation site of a tool
whose whole claim is that nothing leaves your machine. Tests enforce all three properties,
plus HTML-escaping of task text, since titles become attribute values.

Generated by `scripts/campaign.py` from the same inventory, so it cannot drift.

### Added — a self-serve first-contribution page; group sprints parked

`docs/contribute/start.md` is one page for someone arriving alone, at any hour, with nobody
to reply to them. Five rows keyed to what they physically have — a browser, any laptop, a
microphone, an editor they use daily, Python — and the instruction to take the second row if
undecided, because nobody can test YazSes on their machine but them and 297 environments sit
uncovered. Three rules, one self-check command, and what happens after they push.

It includes a **copy-paste prompt for coding agents**, because that population will arrive
whether or not the project plans for it, and routing it well beats pretending otherwise. The
prompt points the agent at `check-task.py` output as its specification, forbids the three
things this project will not bend on (network calls, telemetry, features on by default), and
requires it to stop rather than invent evidence only a human can produce — an unverified
compatibility report or translation is a fabricated contribution regardless of who wrote it.
Everything else on that list an agent does well, and the machine checks catch what a
first-timer cannot.

The top-of-README call to action — the most visible one, far above the Contributing
section — now leads with this page in both languages, as does issue #22.

`campaign/online-sprint.md` is gitignored and `sprint-kit.md` marked parked until roughly 30
contributors exist. A sprint needs a reviewer present at a fixed hour: it does not scale, and
it blocks on one person's calendar. Self-serve does neither. Their links were removed rather
than left pointing at a file git no longer ships.

### Added — an online sprint format, which suits this project better than the in-person one

`campaign/online-sprint.md` runs the same 90-minute contribution session as a video call: no
venue, no travel, no date that only suits one city.

It is not a fallback. The two largest task families need exactly what a single room cannot
supply — 297 compatibility tasks want Fedora, Arch, macOS on Apple silicon, Windows on ARM
and a Raspberry Pi; 184 localization tasks want native speakers of 23 languages. One city
gives you one distro spread and one or two languages. For a project whose missing evidence
*is* environmental diversity, remote attendance is the feature.

It recommends **Jitsi Meet** (no account, no install, open source) — asking people to create
an account in order to help you is real drop-off, and recommending a telemetry-heavy platform
for a privacy-first tool is something people notice. It covers the three failures specific to
a call: silent stalling (a frustrated face is visible in a room, a muted tile is not), the
environment step eating the session, and PRs orphaned once the call ends. It gives four
timezone slots rather than pretending one hour serves India and Brazil, and an async
"sprint week" variant when no single hour works.

Realistic expectation stated plainly: with one reviewer, 8–12 attendees and 6–9 merges —
which roughly doubles the contributor count in ninety minutes, and is a better first target
than an 80-event campaign needing reviewers that do not exist yet.

### Added — the attribution check now actually runs, with addresses masked

`scripts/check_contributor_wall.py` has been able to detect a contributor missing from the
wall for a while, and **no workflow ever ran it** — so a dropped contributor stayed dropped
until somebody happened to think of checking. `.github/workflows/attribution.yml` now runs
it weekly, after every merge to `main` that touches a credit surface, and on demand. It also
runs `campaign_stats.py --attribution-gaps`, which catches the different failure where the
person *is* on the wall but their commit email is not connected to their account, so
GitHub's contributor graph shows nothing.

**It deliberately does not auto-commit.** Automating the wall *update* means a workflow with
write access pushing to the default branch, which can loop on its own commit — a permission
surface not worth opening for a task a human finishes in thirty seconds. Detection is the
half that has to be automatic, because it is the half nobody remembers.

Automating it surfaced a privacy bug that would have been introduced by the automation
itself: the script prints the **email address** of any author it cannot map to a login, and
workflow logs on a public repository are public. Running it in CI unmasked would have
published contributors' addresses — the exact thing `campaign_stats.py` is careful never to
do. Added `--redact-emails` (`ada.lovelace@example.com` → `a…@example.com`: enough to
recognise someone and follow up privately, not enough to harvest), which the workflow passes
and a test requires.

### Added — an incident-response playbook and an honest public dashboard

`campaign/incident-response.md` covers what a contributor drive brings that ordinary
maintenance does not, and that neither `SECURITY.md` (vulnerabilities) nor
`CODE_OF_CONDUCT.md` (behaviour) addresses: fabricated evidence, plagiarised contributions,
pull-request floods, coordinated inauthentic activity, a contributor leaking their own
credentials, and harassment during a campaign.

Its governing bias is stated first, because it decides every other call: **act on the
contribution, not the person.** Almost every bad first pull request is a misunderstanding, a
language barrier, or a task we wrote badly. Using the language of bad faith on someone who
was merely confused ends their involvement in open source, not just here. So the fabricated
evidence procedure opens with one neutral question rather than an accusation, and the
credential-leak procedure starts with "tell them to revoke it" rather than with git.

`campaign/generated/dashboard.md` publishes what contributors have actually built, by
category. It currently reads **"Nothing yet"** and will until real work merges. That is
deliberate: it counts *merged* contributions, never tasks published or people reached,
because a dashboard of activity rather than output is exactly how a campaign convinces
itself it is working while producing nothing. Reviewer load and incident details are
deliberately excluded — those concern individuals, and aggregate output is what a reader
needs.

### Added — duplicate-environment detection, an agent architecture map, and CLI smoke tests

Preflight now warns when a compatibility report describes an environment `SHOWCASE.md`
already covers. Discovering that *after* spending an evening on it is the most demoralising
way to lose a first-time contributor. It is **advisory and never fails the check** — an
independent confirmation, or a contradicting result, is worth having, and a duplicate is a
scheduling mistake on the project's side, not the contributor's. The same OS on a different
session is deliberately *not* a duplicate: X11 and Wayland behave differently enough to be
separate evidence.

`AGENTS.md` gained the compact map the playbook asks for, covering the four things an agent
reliably gets wrong here: which files are **generated** and must never be hand-edited (with
the command to regenerate each), which modules are **pure** and can be tested directly,
where the **platform seams** are, and which **public interfaces** make a change L3 work.
Every path in it was checked against `git ls-files`.

**A `NameError` in `campaign_preflight.py`'s `main()` shipped and was caught by lint, not by
tests** — the suite exercised the pure functions and never invoked an entry point, so the
CLI would have crashed for the first contributor who ran it. There are now smoke tests that
run `main()` for all five scripts, verified red against the reintroduced bug. Unit tests
over pure logic do not prove a script runs; running it does.

### Added — the rest of the campaign tooling, and the inventory at full size

`campaign/tasks.json` grows from 183 to **929 tasks** (130 open, the rest held back for
review capacity). Expanded only where the cross-product is genuinely distinct work someone
would want done: 297 compatibility environments, 184 localization tasks (23 languages × the
8 real modules now defined in `i18n/modules.yml`), 154 app configs, 90 microphone
measurements. **`qa-fixture` and `security-privacy` were deliberately not padded** — their
size depends on real bugs and real privacy boundaries existing, and inventing tasks to hit a
number sends someone to solve a problem nobody has.

`scripts/check-compatibility.py` validates `SHOWCASE.md` setup reports: required fields
present, and the OS line actually says X11 or Wayland, because a report omitting the session
cannot be acted on. `scripts/check-app-profile.py` validates `examples/*.toml` against the
real dataclasses in `src/yazses/config.py` — 138 sections, derived not hand-listed. That
catches a silent failure: the config loader is deliberately total and drops unknown keys
(#52), which is right for a user's config and wrong for a shipped example, where a typo'd
key does nothing and the person who copied it concludes the feature is broken.

`scripts/campaign_queue.py` answers who is waiting on a human, ordering by how long someone
has waited and weighting a first pull request up, since that is the one most likely to be
abandoned in silence. It also reports claims that have lapsed — 48 hours for L0/L1, seven
days for L2 — so a task nobody finished returns to the pool instead of staying locked
forever. **The wording is deliberately not a reprimand**: the task is free again, thank them,
leave their branch alone, and a test asserts that phrasing.

`i18n/` splits translation into 8 modules **without copying any English prose**. A parallel
copy of `README.md` would be a second source of truth that drifts silently, which is the
exact failure this release keeps fixing elsewhere — so `i18n/modules.yml` maps modules to
`README.md` headings as data, and a test fails when a heading is renamed out from under it.
`i18n/glossary.yml` carries the terminology decisions, which are genuinely new content:
what never gets translated, and the traps (translating the DCO sign-off line changes a legal
statement; "offline" is always rendered *by default*, never as an absolute).

### Added — funnel measurement, a local task checker, and a scoped packaging brief

`scripts/campaign_stats.py` measures whether any of the contributor work is actually
working, using only the public GitHub API and local git — no pixels, no per-user analytics,
no third-party service. Its most important query is `--attribution-gaps`: GitHub attributes
a commit by author *email*, so a contributor whose email is not connected to their account
gets a grey avatar, no profile link and no entry in the contributor graph. They did the work
and the project shows nothing. That is a bug in the project, not in them, and nothing was
looking for it. No email address ever reaches the output — a test enforces that. With no
network it falls back to git history and **says so**, rather than printing numbers it cannot
stand behind.

The report also prints a `PROMOTION: OK` / `PAUSED` line with its reasons, so the decision
to stop recruiting does not depend on anyone remembering thresholds during a busy week. It
pauses when more than 25 PRs await review, or when more than two contributors have merged
work the project is not crediting — recruiting more people while existing ones go
uncredited is the wrong order.

`scripts/check-task.py TASK-ID` runs the same three checks CI will — scope, personal data,
and the task's own validation command — against the working tree, so a contributor finds
out while the work is still in front of them rather than from a red check on a first pull
request. It exits non-zero, so it works as a pre-push hook.

**`campaign/tasks.json` is now treated as a code-execution surface.** `check-task.py` runs
a task's validation commands on a contributor's own machine, so a pull request editing that
file would otherwise be a way to run arbitrary code on anyone who validated their work
before pushing. Commands must now start with an allowlisted prefix, must contain no shell
metacharacter (a prefix allowlist alone is bypassed by chaining), and are executed without
a shell. The validator rejects the rest, and the check is repeated at run time rather than
trusting that the file was validated.

`packaging/AGENTS.md` records the two rules that genuinely differ there: packaging changes
**cannot** be verified by the offline test suite, so an agent must say what it did not
verify instead of implying success; and release credentials are deliberately not in this
repository, so anything needing one stops and goes to the maintainer. The root `AGENTS.md`
now also states that it is canonical for every tool — Codex, Claude Code, Gemini CLI,
Cursor, Copilot — because there is deliberately no per-tool instruction file here.

The pull-request template can now carry a `Task ID` and an optional cohort code, which is
what lets preflight confirm a contributor's scope for them.

### Fixed — preflight findings now say which file they are in

Simulating the preflight against a real commit range showed it reporting five personal-data
hits with no indication of where any of them were — and all five were the scanner's own test
fixtures. A finding a contributor cannot locate is not actionable, and worse, an intentional
fixture becomes indistinguishable from a genuine leaked credential. The scanner now parses
the unified diff per file and reports ``path — label: snippet — hint``.

The same run caught a real slip: a test fixture used the maintainer's actual home path,
inside the very file that teaches the scanner to find home paths. Replaced with a fabricated
username.

### Added — REVIEWING.md and a sprint kit, so scaling does not require being the maintainer

`REVIEWING.md` is written to be handed to someone on their first review rather than to
describe a team that already exists: the four risk lanes and what each may approve, the
three things a machine may never decide (whether a translation reads naturally, whether
hardware behaved as claimed, whether an architectural change is right), response templates,
what not to do on a first-time contributor's PR, and a path into reviewing that starts with
drafting reviews rather than with repository permissions. It also names the conditions under
which the project should publicly stop taking contributions — an overloaded queue harms
contributors more than a quiet week does.

`campaign/sprint-kit.md` is a 90-minute session runbook for an organizer who has never
spoken to the maintainer, including the three stalls that actually happen (a missing C
compiler on Linux, because `evdev` publishes no wheels; a missing DCO sign-off; two people
claiming one task) and an explicit rule against running a session with no reviewer present.

Both are linked from `CONTRIBUTING.md` and `campaign/README.md`. An unlinked document is
the same failure as a translation nobody can reach.

### Added — a contributor task inventory with a preflight that reviews the cheap parts

`campaign/tasks.json` holds 183 bounded tasks (126 currently open) across ten families,
every one anchored to a surface that already exists — `SHOWCASE.md`, `examples/`,
`docs/known-good-microphones.md`, `contract/vectors/`, `README.<code>.md`, `src/` — and to a
validation command that already runs. The 67 feature-wiring tasks are derived from the live
`_UNWIRED` registry, and a test fails when a task exists for a capability that has since
been wired, which is the way an inventory like this normally rots.

There is deliberately **no GitHub issue per task**: a hundred bot-filed issues would bury the
human ones and read as spam. `campaign/generated/open-tasks.md` is the browsable list.

`scripts/campaign.py` is the only thing that decides whether a row is valid. It refuses a
task with no stated value, no bounded paths, no validation command, a duplicate id, or an
estimate longer than one sitting, and it refuses to mark a compatibility, measurement or
localization task `cloud_agent_ready` — a container cannot observe hardware or judge whether
a translation reads naturally. `risk: L3` may never be advertised as an open first task.

The JSON Schema is **generated** from `FIELD_SPEC` rather than written beside it. A schema
nobody validates against is the dead-registry shape this repository has been bitten by
before; a test fails if the committed copy goes stale. No new dependency was added —
validation is hand-rolled rather than pulling in `jsonschema`, because the 18-package base
budget is not something campaign tooling gets to widen.

`scripts/campaign_preflight.py` + `.github/workflows/campaign-preflight.yml` answer the
questions that do not need a human: does the PR name a task that exists, did it stay inside
that task's `allowed_paths`, and did a home path, email or token reach the diff. It emits one
actionable summary rather than raw logs, and a PR that names no task passes untouched — this
must never become a tollgate on ordinary contributions. It runs on `pull_request`, **not**
`pull_request_target`, so it holds a read-only token and never sees secrets; PR title and body
reach it through a file rather than shell interpolation, which is the injection hole that
untrusted input would otherwise open. It reports through the job summary, so it needs no write
permission at all.

Eleven labels were added — the four `risk:` lanes, `browser-only` / `cloud-agent-ready` /
`hardware-required`, and the `status:` claim lifecycle. The playbook's fuller vocabulary was
written without sight of the repository's existing 22 labels; `task:packaging`,
`task:contract` and `task:docs` would have duplicated `packaging`, `contract` and
`documentation`, and six `review:` labels are premature for one reviewer, so those were left out.

### Added — the no-setup contribution paths are now visible from the front door

The README's Contributing section listed one generic "good first issue" link. The tasks that
actually convert drive-by traffic — translate the README, add your microphone, share an app
config, add your setup — need only a text editor and hold many contributors at once, and
nothing said so where a first-time visitor would see it. Both READMEs now name them.

`CONTRIBUTING.md` gained a **Translating the README** section recording the convention the
Hindi translation established but nobody had written down: translating the lede through Quick
Start (~120 of 581 lines) is a *complete* contribution, the rest may stay English behind a
status banner, and command names, config keys, paths and the project name are never
translated. Issue #18 said "translate the prose" in step 2 and buried "a partial translation
is welcome" at line 55 of 60 — a translator read the 581-line ask and never reached the
reassurance. That guidance now leads.

### Fixed — the documented lint gate was weaker than the one CI runs

CI and the `Makefile` lint `src tests scripts`. `AGENTS.md`, `README.md` and `README.hi.md`
told contributors to run `ruff check src tests` — leaving the 12 Python files in `scripts/`
outside the command every agent was instructed to run. Following the instructions produced
a green local check and a red CI, and `AGENTS.md` says in the same breath to "run them
before claiming anything works", so the false confidence was built in. Nothing in `scripts/`
is currently failing, so this was latent rather than active.

`tests/test_agent_instructions.py` now treats `.github/workflows/test.yml` as the authority
on the gates and fails when any surface — including a translated README — quotes a lint
command narrower than the one CI runs, whatever the targets later become. Verified red
against all three pre-change files.

### Added — the PR template now asks about AI assistance

`CONTRIBUTING.md` has asked contributors to "mention in the PR body if a change was largely
AI-generated" for a while, and the pull-request template had nowhere to put it — a policy
with no field to fill in. The template gained a short **AI assistance** section (tool used,
what the author verified themselves) and an "I have read every changed line and can explain
why it is there" checkbox, matching the responsibility `AGENTS.md` already places on the
human who opens the PR. It changes how carefully a PR is read, never whether it is accepted.

`CONTRIBUTING.md` also now shows `git commit -s` in **Before opening a pull request**, with
the amend and rebase recovery commands. It was previously documented only under *License and
sign-off* near the end of the file — after the point where a contributor has already
committed, which is exactly when knowing about it stops being useful.

### Fixed — the agent instruction files told contributors the wrong gate

`AGENTS.md` told every coding agent that the codebase carried "~135 known type errors
across 50 files" and that "a clean run is not the bar". `README.md`, `README.hi.md` and
the `Makefile` said the same in shorter words. `CONTRIBUTING.md` said the opposite, and
`CONTRIBUTING.md` was right: `uv run mypy src` reports `Success: no issues found in 433
source files`. An agent reading the stale file would have shipped type errors and
reported them as pre-existing — while following the instructions it was given. All four
surfaces now state the actual bar.

`AGENTS.md` also sent contributors to a root `CLAUDE.md` for the architecture reference.
That file is gitignored on purpose — it holds local assistant configuration — so it exists
in the maintainer's checkout and in no clone anyone else has ever made. The pointer read
fine to the only person who could not observe it failing. It now points at
`docs/architecture.md`, which is tracked, and says explicitly that root-level assistant
config files are not shipped and must never be cited to a contributor.

`tests/test_agent_instructions.py` is the guard that makes this stay true. It fails when a
shipped instruction file points at a file **git does not ship** — resolving paths through
`git ls-files` rather than the filesystem, because a working-tree check would have passed
on the maintainer's machine while the link was broken for everyone else, reproducing the
bug instead of catching it. It matches both markdown links and backticked references,
since the dangling pointer was the backticked form. It also fails when any surface —
including a translated README — goes back to describing type errors as known or
pre-existing. Both guards were verified red against the pre-change text.

### Added — the Codespaces path is finally advertised

The repo has shipped a working `.devcontainer/devcontainer.json` for a while and nothing
in `README.md` or `CONTRIBUTING.md` said so. A contributor with no local Python — the
largest group any first-contribution drive reaches — had no way to know that docs, config,
test and pure-logic changes need no setup at all. Both READMEs now link the one-click
Codespaces path and state plainly what it cannot do: anything needing a real microphone,
hotkey device, or window focus still needs a local machine.

### Added — Hindi README and the language switcher (#165, part of #18)

`README.hi.md` is the project's first translation, covering the lede through Quick
Start; the remainder is the English text verbatim and the banner at the top says so.
Commands, config keys, paths, code blocks and the project name are preserved
untranslated, so a reader can follow the install steps without reading Hindi.

README.md gained the **Read this in other languages** line it never had. Without it
the translated file existed and no reader could reach it — the work was done and
delivered nothing. `tests/test_contributors_wall.py` now fails if a `README.<code>.md`
is not linked from that line.

Translated prose is allowed to lag the English (issue #18 promises contributors that
much). The contributor wall is not prose: it is generated markup, identical in every
language, and a copy of it going stale drops a real person from the surface people
look at. Two new checks hold every translation's wall and badge count identical to
README.md.

### Fixed — the first-time-contributor greeting had never posted

`actions/first-interaction` v3 renamed its inputs to snake_case; the workflow still
passed the v2 hyphenated names, so every run aborted with `Input required and not
supplied: issue_message` before posting. The greeting meant to reach someone on their
first issue or PR has never been sent, and the failure showed up as a red check on the
newcomer's own PR. The DCO sign-off is also now in the PR-template checklist, where it
was missing — it is documented in CONTRIBUTING.md and it is the one omission that
hard-fails CI.

### Added — Voice Undo/Redo Timeline is reachable (part of #41)

`InjectionTimeline` has been able to undo YazSes's own output by word, sentence or
burst since ADR-v2-089, with nothing calling it. A whole-utterance "undo the last
word" / "undo two sentences" / "redo" now replays it, in the same shape as "scratch
that": it backspaces and retypes only what this daemon put on screen, so it can never
eat the user's own typing. `timeline` leaves `features._UNWIRED`.

The grammar is anchored at both ends, exactly as `_SCRATCH_RE` is in
`commands/revise.py` and for the same reason. "undo" is an ordinary English word: a
pattern that only has to *end* the utterance swallows "click undo", "press control z
to undo" and "there is no redo" — they are never typed, and a speaker cannot tell a
swallowed sentence from a microphone that failed. Six such phrases are now test cases.
A spoken repeat count is clamped, so a misheard "undo 9999" cannot become a keystroke
flood, and the loop stops as soon as history runs out instead of pressing keys into
an empty stack.

Session bookmarks, the other half of #41, are **not** included and stay unwired. The
implementation tracked a virtual cursor offset from session start and jumped by
injecting that many arrow keys — a model that any mouse click or arrow key silently
desynchronises, and an unbounded key injection of the exact shape that caused #153.
Jumping the caret needs a real cursor position (AT-SPI or the editor bridge) rather
than a count of characters YazSes believes it typed; that is a design decision, not a
patch, and #41 stays open for it.


### Added — STT benchmark harness and a community results table (#72)

`scripts/bench-stt.py` measures WER, real-time factor and peak RSS for any engine and
model over a directory of paired `.wav`/`.txt` files, and prints the markdown row to
paste into `docs/benchmarks.md`. "Which model should I run on my machine" has been
answerable only by anecdote; this makes it answerable by measurement, on the machine
in question. `jiwer` is a dev-group dependency — the base install is untouched.

It decodes with `recimport/audio_io.load_audio` (PyAV, ffmpeg fallback) rather than
`soundfile`, so it runs on a plain `uv sync` with no extra install step, and it
*resamples* rather than skipping: reading with `soundfile` meant every dataset that
was not already 16 kHz — LibriSpeech included — was silently passed over, and a
benchmark that skips its input reports nothing rather than reporting less.

Peak RSS now divides by the right unit on macOS, where `ru_maxrss` is bytes rather
than the kilobytes Linux reports. These numbers are meant to be compared across
machines in a shared table, so a 1024x error would have read as a Mac using almost no
memory rather than as a bug.


### Added — Voice Jump-to-Symbol is reachable (#40)

`jump/target.py` has parsed "go to line 240" and "jump to function tokenize" into a
motion since v2.6, and nothing could carry the motion to an editor. `yazses jump
"<spoken target>"` closes it: `NeovimBridge` gained `get_symbols()` (an LSP
`textDocument/documentSymbol` request, flattened to name → line) and `apply_motion()`,
so a fuzzy symbol match becomes a cursor move and anything unmatched falls back to a
buffer search. `jump` leaves `features._UNWIRED`.

The search motion passes its pattern to `search()` as an RPC argument rather than
building `/\V<pattern>` for `nvim.command`. On the Ex command line a `/` in the text
is read as a search offset and a bar or newline begins another command — and this text
is transcribed speech, where "jump to and/or" is an ordinary thing to say. It also
returns the line it landed on, so a target that is not in the buffer is reported as a
failure instead of a silent no-op that claimed success.


### Added — per-app tone & formatting profiles (#100)

Dictation now takes its tone from the application you are speaking into: casual in
Slack, formal in an email client, `verbatim` in a terminal where a formatting pass is
the last thing you want. `[profiles.app]` maps a glob over the focused window to a
tone; a value that is not a house tone is used as a complete custom LLM prompt.

The focused application is resolved by the same `TargetDetector` that already answers
"is there a text target", on the same background thread at hold-start — AT-SPI first,
xdotool on X11 as a fallback, "" when neither can say. No new dependency, no new
probe, and nothing on the hot path when `[profiles.app]` is empty.

Note that the two backends report different names for the same window: AT-SPI gives
the application name (`Firefox`), X11 gives the window class (`Navigator`). Patterns
are matched case-insensitively, and a glob such as `"*fire*"` is the portable shape.

### Added — Voice Fuzzy File Open is reachable at last (#38)

`src/yazses/fileopen/match.py` has ranked filenames against a spoken query since
v2.6, and nothing could call it. The registry advertised the capability, `features
enable fileopen` refused it as designed-but-unwired, and the feature page said
"not possible yet". The ranker was the easy half; the missing half was somewhere for
its answer to go.

`yazses fileopen "<spoken query>"` closes it: rank the files in a directory, show the
best match, confirm, and hand it to the OS opener (`xdg-open` / `open` /
`os.startfile`). `--yes` skips the prompt for a hands-free flow.

The command **always names the file it opened**, `--yes` included. It chooses by
fuzzy score, so the one path where the user never sees the choice being made is
exactly the path where they most need to be told what it landed on. It also reads
`[fileopen] threshold` rather than hardcoding the default, and a miss reports the bar
it applied instead of only that it missed — a documented key that silently does
nothing is the failure this project has been bitten by before.

`fileopen` leaves `features._UNWIRED`, so the feature page now says
`yazses features enable fileopen` instead of "designed but not wired", and the
registry blurb names the command rather than describing a capability with no door.

## [2.17.0] - 2026-08-09

Follows v2.16.0 by a day, because the snap release exposed the next layer of
problems the moment people actually used it. Streaming dictation could delete text
it had never typed; a fresh snap install said nothing about the second interface it
needs; `yazses start` never survived a reboot. Plus four capabilities wired up and
five default filler words removed after they were shown to eat real meaning.

### Fixed — five default "filler" words were load-bearing content (#146, contract 6.0.0)

`like`, `right`, `sort of`, `kind of` and `actually` shipped in
`[filters.disfluency] filler_words` by default. Each is a genuine hesitation in some
positions and meaning in others, and the filter cannot tell them apart — so a hedge
became a fact (`she is sort of stable` → `she is stable`, byte-identical to the
unhedged observation), a negated assessment lost its predicate (`that dose is not
right` → `that dose is not`), and a correction marker was erased (`she said no,
actually she said yes` → a self-contradiction). Dictation is used for clinical and
legal notes; a confident falsehood is worse than a visible disfluency.

All five are removed from the defaults, following the `err` precedent from #125, and
remain available to anyone who wants aggressive filler removal by listing them under
`[filters.disfluency]`. The five semantic invariants that recorded this as a known gap
now hold.

Contract **5.1.0 → 6.0.0**: changed expectations and a known-gap promotion are both
major bumps under `contract/README.md`. Four vector cases that existed to prove a rule
using one of these five words would have become vacuous, so each keeps its input as a
record of the new behaviour and gains a sibling case proving the same rule with a word
that is still a default filler (76 → 80 disfluency cases).
### Added — CI enforces the dependency budget (#141)

"18 base dependencies against 140+ features" was true only for as long as reviewers
kept catching drift by hand, and the failure it guards against is invisible to the
test suite: a lazy `import mediapipe` moved to the top of a daemon-imported file
during an unrelated refactor breaks nothing, it just makes every base install heavier
forever. `scripts/check_dependency_budget.py` runs in the `repo-hygiene` job and adds
three checks against a base install — growth of `[project.dependencies]` (needs the
`dependency-budget-override` label), any module belonging to an extra turning up in
`sys.modules` after `import yazses.core.daemon`, and cold-start import time against a
recorded budget.

Growth is compared against the baseline **on the base branch**, so a PR cannot excuse
a new dependency by re-recording the baseline in the same commit. Adding an extra to
`[project.optional-dependencies]` without mapping it in the script fails too — an
unmapped extra is enforced by nothing, which is the way a check like this usually
dies. The import-time budget is only enforced in CI, where the recorded number and
the runner are the same kind of machine.

### Fixed — streaming dictation deleted text it had never typed (#153)

Reported from the snap: a long dictation ended in a flood of repeated characters, then the
correction pass removed text the user wanted to keep. Three defects, all on the streaming
+ X11 path, each able to cause it on its own.

`XdotoolInjector` used a **fixed** `timeout=10` on every method. At `--delay 12` that
expires around 833 characters — and it expires *after* xdotool has already typed part of
the text, so the caller sees a failure for work that partly happened, `LinuxInjector` reads
that as a broken backend and falls back to the clipboard, and the text lands **twice**.
`YdotoolInjector` has scaled its timeout since the Wayland flood fix and says why in a
comment; the X11 path simply never got it. Timeouts now scale with the keystrokes actually
requested, on `type`, `inject_backspaces` and `inject_key_sequence` alike.

The streaming commit sends one `shift+Left` per typed character, so a long burst hit that
same wall **twice** — once selecting, once retyping. A run of one repeated key now goes out
as a single `--repeat` spec, the way `inject_backspaces` always has, which also keeps a
thousand-character correction off the argv length limit.

`StreamingInjector` had no synchronisation at all. `inject_partial` runs on the daemon's
poll thread while `commit` runs on hold-release, and the daemon's `join(timeout=1.0)`
cannot outwait an injection allowed ten times that — so a partial could land *after*
`commit` had read the character count, leaving `shift+Left × N` selecting a span that no
longer matched the screen. Every mutation now happens under one lock held across the
injection itself, and a committed injector is **sealed**: a late partial is dropped rather
than typed behind the final text.

### Fixed — a fresh snap install said nothing about the two interfaces it needs (#154)

`snap install yazses` leaves both `audio-record` and `raw-input` unconnected — snapd does
not auto-connect either, and a snap cannot connect its own. The result is the two most
visible failures possible: it cannot hear you, and it cannot see the hotkey. The daemon
starts and reports healthy in both cases.

`yazses setup` / `start` already surfaced the microphone one. It now surfaces `raw-input`
too, so the tool says what is wrong instead of leaving it to documentation, and the Snap
row in the Linux install guide lists every step rather than only the first two.

### Fixed — `yazses start` now survives a reboot, which is what it always claimed

`install_autostart()` was written so that a `pipx` / `uv tool` / `pip install` gets a
login service like the packaged installs do — its own docstring says *"a daemon you must
remember to launch is not a daemon."* It had exactly one caller: `yazses autostart
enable`, a command you only find if you already know it exists. So the ordinary path was
install → `yazses start` → dictate happily → reboot → the daemon is gone, with nothing
anywhere saying why. The promise was implemented and never wired up.

`yazses start` now installs the login service once the daemon is actually up, and says so
the single time it does it. It is best-effort: a daemon that *died* during startup is
never scheduled to run at every login, a failure to install is one line of explanation
rather than a failed start, and if we cannot tell whether autostart is already configured
we change nothing. `yazses start --no-autostart` opts out; `yazses autostart disable`
undoes it.

### Added — Style-Consistency Enforcer: config-driven rules source (#36)

The pure `styleguard` core (`load_stylerules`/`apply_style`) has existed with no rules
source wired into config, so the feature could not be turned on usefully. `[styleguard]`
now points at a `style-rules.toml` (sibling of `config.toml` by default, `[[rule]]`
entries of `preferred` → `variants`), loaded once at daemon startup and applied on the
dictation path alongside the other opt-in text transforms. `styleguard` moves from
"planned" to "optional" in `yazses features` now that a real entry point reads it.

### Added — `yazses gitvoice`: the Voice Git Choreographer is wired up (#37)

The pure grammar (`build_git_argv`, `reversibility`, `undo_hint`) has existed for a
while with no way to reach it short of importing the module directly. `yazses gitvoice`
closes that gap: it parses a spoken git command, prints the resolved `git ...` argv and
its undo, and — only with `--run` — executes it. A destructive command (force-push,
`reset --hard`, `branch -D`, discarding uncommitted changes) refuses to run even under
`--run` unless you also pass `--yes`; without either flag it only ever prints.

The grammar also gained "discard changes in `<path>`" → `git checkout -- <path>`, filling
a gap from the spoken-phrase list in the issue. `gitvoice` moves from "planned" to
"optional" in `yazses features` now that a real entry point reads it.
### Added — Diagrams-as-Code by voice now parses a whole graph, not just one edge

`parse_graph_utterance` used to accept exactly one `A goes to B` per clause; dictating
anything past a single edge meant one utterance per edge, split on `;`. "And" now fans a
clause out to multiple sources and/or destinations, so `A goes to B and C, B goes to D`
comes back as three edges in one breath, and `A and B goes to C` fans in the other
direction. An `and`-separated destination that is itself a full clause (`... and C goes
to D`) is its own statement, while a lone one is a chain — `start goes to login goes to
dashboard` links through as `start→login→dashboard` instead of inventing a node called
"login goes to dashboard". A comma separates clauses only when what follows starts one,
so a label keeps its own punctuation (`... labeled sign in, please`). Nodes come back in
the order they were spoken. `diagramvox` is still `planned — designed, not yet wired`
(issue [#34](https://github.com/MSKazemi/yazses/issues/34)).

## [2.16.0] - 2026-08-09

The release that makes the **snap** a first-class channel. A snap can never
pip-install anything into itself, so every capability whose libraries were not
baked into the image was unreachable for the life of that revision — silently,
and with the config key already written. The snap now bundles what fits (Meeting
Mode, diarized import, speaker labels, Read-Back all work there for the first
time) and refuses honestly for what cannot.

### Added — the cross-platform contract now pins meaning, not only parity (contract 5.1.0)

`contract/vectors/` guarantees every YazSes implementation delivers the same string. It
could not guarantee that string still means what was said, and the reason is structural:
every expectation in it is generated by running the shipped Python. One commit can change
the implementation, the generator and the golden data together — CI green, vectors green,
and a cleanup rule that erased a real distinction is now the specification Android and iOS
are built to.

`contract/semantic/` is the independent anchor, and its expectations are **hand-authored
and never regenerated**:

> Post-processing may simplify form, but it must not silently erase or invert a
> distinction that changes what a downstream reader should understand or do.

Nineteen cases pin `polarity`, `actor`, `time`, `quantity`, `unit`, `certainty`,
`request_or_refusal`, `correction_marker` and `assessment` — plus **minimal pairs**, two
utterances differing in exactly one consequential dimension that must not collapse into
the same output. That last check is the one no per-case assertion can make, because both
outputs look perfectly plausible on their own.

It found five shipped behaviours that destroy meaning ([#146](https://github.com/MSKazemi/yazses/issues/146))
while all 191 parity vectors were green:

| Spoken | Delivered |
|---|---|
| `that dose is not right` | `that dose is not` |
| `she is sort of stable` | `she is stable` — byte-identical to `she is stable` |
| `the wound is like two centimetres across` | `the wound is two centimetres across` |
| `he took it like an hour ago` | `he took it an hour ago` |
| `she said no, actually she said yes` | `she said no, she said yes` |

All five come from one cause: `like`, `right`, `sort of`, `kind of` and `actually` are
default filler words *and* ordinary content words — the same trap `"err"` was removed from
the list for in #125. They are recorded as `known-gap` and are strict-xfail, so the suite
is green while the gap is documented and goes **red the moment the code is fixed**, asking
for the case to be promoted. A gap can be recorded here, but not forgotten.

Decision and rationale: ADR-MOB-008 §8. The flaw was found by **@YossiMH**, who read the
ten mobile ADRs before any code existed and pointed out that parity is not correctness
([#98](https://github.com/MSKazemi/yazses/issues/98)).

### Fixed — the snap could not install any optional feature library, and said so in Debian's words

A snap can never pip-install anything into itself. Its payload is a read-only squashfs,
and the Python we stage is Debian's, which ships a PEP 668 `EXTERNALLY-MANAGED` marker.
`yazses features enable <name>` did not know that: it ran pip anyway, and the user got
Debian's error verbatim —

```
error: externally-managed-environment
... try apt install python3-xyz ...
... create a virtual environment using python3 -m venv ...
```

— three suggestions, none of which a confined user can act on, and one of which (`pipx`)
is the very thing they chose not to do. Worse, the config key had **already been written**
by the time pip failed, so the capability read as enabled while nothing could ever honour
it: exactly the lie `features enable` already refuses for unwired features.

Verified against the published `yazses_25.snap`: of the 15 capabilities that carry
optional Python packages, only `overlay` (PySide6) and `stt-parakeet` (onnx-asr) had their
libraries on board. Eight wired capabilities were unreachable for the life of the
revision, including **Meeting Mode** — the headline differentiator.

Fixed on both sides.

**The snap now bundles what fits.** `sherpa-onnx` (~40 MB) turns on `meeting`, `recimport`
and `diarize`; `kokoro-onnx` + `soundfile` turn on `read-back`. Every bundled package must
publish manylinux wheels for x86_64 *and* aarch64, since `platforms:` builds both and a
one-arch dep fails the arm64 build outright — the same trap that killed the other five
architectures. Total cost ~101 MB uncompressed on a snap that was already 422 MB
compressed.

**What cannot fit is refused honestly**, before the config is written, in the spirit of
`system/snap.py`'s existing raw-input advice (issue #44) and `system/backends.py`'s rule
that an impossible instruction is worse than none. `speechbrain` (`cocktail`) pulls torch
and would dwarf the snap; `llama-cpp-python` (`llm-cleanup`) publishes no PyPI wheels;
`mediapipe` + `opencv` (`gaze`) cost 110 MB for an experimental webcam feature;
`praat-parselmouth` (`prosody`) has no aarch64 wheel. Enabling one of those inside a snap
now explains why, names the packages, and gives the one instruction that works — while
noting that config and models do not carry across to an unconfined install.

The gate is precise, not a blanket refusal: a capability whose libraries *are* bundled
still enables normally inside the snap. `system.deps.install_blocked_reason` also catches
the general case of an unwritable site directory (a root-owned install run as a normal
user), so pip is never launched into a wall.

`yazses settings` had the same defect and is fixed the same way. The window wrote the
config keys and *then* reported the missing packages, telling the user to run
`yazses features enable <slug>` — which now refuses for exactly the reason the window
had just ignored. It refuses before writing too, so a checkbox can never be left ticked
for something that cannot work. Turning a capability **off** is never blocked: that
installs nothing, and a locked environment must not trap a user with a setting they
cannot switch back.

### Added — `yazses settings`, a settings window generated from the feature registry

YazSes had no graphical way to turn a capability on. Everything went through
`yazses features enable/disable <name>`, which is fine for the terminal and a wall for
everyone else — and "edit `config.toml`" is exactly the instruction a dictation tool for
people who find typing hard should never have to give.

`yazses settings` (and the `yazses-settings` entry point) opens a PySide6 window listing
**every** capability as a checkbox, grouped by the same categories `yazses features`
prints, with each row's advice tier underneath. There is no hand-maintained UI list: the
window is built from `system/features.py`, the same registry the CLI reads, so the two
cannot drift. It honours the same honesty rules — core features and *planned — designed,
not yet wired* ones are shown but not clickable, and an experimental feature asks for
confirmation before it is even staged, mirroring the CLI's `--force` guard. Checking a
box stages the change; Apply writes it through the same comment-preserving
`configedit.set_config_key` the CLI uses.

Split like the tray: `settingsui/model.py` and `settingsui/controller.py` are pure and
unit-tested without Qt, `settingsui/app.py` is the thin shell.

Two things the window does **not** do, and says so rather than leaving you guessing:

- It does not install a feature's optional Python packages the way
  `yazses features enable` does — a pip install would freeze the UI thread for minutes.
  It names the missing packages and the command that installs them.
- It needs a graphical session. Over SSH it prints what to run instead of aborting
  inside Qt.

Thanks to [@waterlemonnn](https://github.com/waterlemonnn) for the implementation
(PR #134, issue #58).

### Fixed — `[stt] language` was documented but did not exist; non-English dictation never worked

`docs/use-cases/multilingual-dictation.md` told users to set `[stt] language = "de"` and
restart. That key was never implemented. `SttConfig` had no `language` field, so
`configcheck.py` — which drops unknown keys by design — discarded it silently, and every
faster-whisper decode path hardcoded `language="en"`: `transcribe`, `transcribe_words`,
and `decode_window`. A German user following the page got their speech forced through
English, which Whisper answers by transliterating into English-looking nonsense rather
than erroring. The generated `docs/configuration.md`, built from the dataclasses, listed
`language` only under `[recimport]` and `[meeting]` and so had been quietly contradicting
the hand-written page for as long as it existed.

`[stt] language` is now real. It defaults to `"en"` (the previous behaviour, unchanged for
everyone who set nothing), accepts any Whisper language code, and takes `""` to auto-detect
per utterance. The translate path (ADR-v2-014) still auto-detects its source by design, and
`initial_prompt` is unaffected.

Both ways of configuring something impossible now produce an honest warning instead of
quiet nonsense, per the `system/backends.py` rule:

- A non-English language on an `.en` checkpoint — which has no language tokens and
  physically cannot decode German — names both values and says to drop the `.en` suffix.
- A non-English language on the Parakeet engine, which is English-only, says so and points
  at faster-whisper.

### Added — `man yazses`, generated from the CLI so it cannot drift

YazSes shipped no man page at all: `man yazses` returned "No manual entry", the one
place a Unix user looks first. `scripts/gen-man.py` now renders `man/yazses.1` from the
live Typer/Click app — the same trick `scripts/gen-docs.py` uses for
`docs/command-index.md` — so the page is never hand-written and never lags `--help`.
`make man` regenerates it and `tests/test_gen_man.py` fails with a "run `make man`"
message if it drifts, plus asserts every top-level command is documented.

Three details make it hold up in production rather than merely exist:

- **A version bump must not redden CI.** The `.TH` header carries the version and
  release date, so byte-comparing the whole file would have turned every release into a
  failing test run until someone remembered to regenerate. The sync test compares the
  *body* (`gen-man.py::body`) — real CLI drift still fails it, the stamp does not — and
  `scripts/build-deb.sh` regenerates the page at package build time so the shipped
  version string is always correct. `release.yml` gained the `uv sync` that makes that
  regeneration possible on the release runner.
- **It actually reaches users.** `debian/yazses.manpages` only feeds the `dh`/PPA path,
  which triggers on `v0.*` tags and is dead. The `.deb` we really publish is built by
  `scripts/build-deb.sh`, which now installs `/usr/share/man/man1/yazses.1.gz`.
- **It renders on strict toolchains.** The CLI help text is full of em dashes, arrows
  and ellipses; raw UTF-8 in a man page only survives `preconv`, and `groff -mandoc`
  alone emitted an "invalid input character code" warning for all 35 of them. They are
  now mapped to groff entities (`\(em`, `\(->`, …), and a test keeps the output ASCII.

The README states honestly where `man yazses` works — after an `apt`/`.deb` install, or
`man -l man/yazses.1` from a checkout — and notes that `pipx`/`pip` and Snap do not put
man pages on the system man path.

Thanks to [@waterlemonnn](https://github.com/waterlemonnn) for the generator, the
Makefile target, the drift test and the Debian wiring (#131, closes #3).

### Fixed — the Linux install page told newcomers to install from a path only the author had

`docs/install-linux.md` was structurally unfollowable for the exact person it was written
for. Its install step read `uv tool install --force /path/to/yazses` / `pipx install
/path/to/yazses` — a local checkout path a new user does not have, and which fails outright
if pasted. Worse, that step was **§2**: §1 opened by telling the reader to run `yazses setup`
and `yazses doctor`, commands that cannot exist until §2 has run. Anyone following the page
top to bottom hit `command not found` before reaching the install instructions at all.

The page now leads with the one-line installer that actually works
(`bash <(curl -fsSL .../install.sh)`), with APT, Snap and pipx folded into a comparison table
behind a disclosure. Provisioning (`yazses setup`, the `input` group, `ydotoold`) moved to §3
as *reference* — because the scripted channels already do all of it — leaving a first-run path
of install → log out/in → `yazses mic-level --set` → `yazses start`. The Snap row now carries
the `snap connect yazses:audio-record` line, whose absence leaves the snap with no microphone.

The by-hand section also gained the step it was missing entirely — `pipx install yazses`
*before* `yazses setup`, since `setup` is a subcommand of the very program being installed.
The page now also says plainly that **cloning the repo is not required**, which the old
`/path/to/yazses` wording had implied.

### Fixed — `install.sh` had two hard prerequisites it neither checked for nor installed

Both were found by reproducing the failure, not by reading the script. `install.sh` installs
with `uv tool install --from git+…`, and uv shells out to a real `git` binary for git
sources — so on a machine without `git` it aborted with `Git executable not found`, roughly
forty lines into unrelated build output. Separately, `evdev` (which reads the hold-to-talk
key) publishes an sdist and **no wheels at all**, so it is compiled from C source on every
`uv`/`pipx` install; uv resolves to the *system* interpreter here, so the build needs a C
compiler and that interpreter's headers. Neither was mentioned anywhere, and the script
provisions everything else — so the failure read as a YazSes bug rather than a missing
package.

`install.sh` now runs a preflight before it does any work: it probes for `git`, for `cc`/`gcc`,
and for `Python.h` (probing the header rather than the package name, since `python3-dev` is
Debian-specific but a missing header breaks the build identically everywhere), then installs
whatever is missing via `apt` — or, on a distro without `apt`, stops and names the equivalents
for Fedora and Arch. `tests/test_install_preflight.py` covers both directions: that a PATH
without `git` or a compiler aborts with exit 1 naming both, *before* reaching the network or
`sudo`, and that a healthy machine is flagged for nothing.

Only the **Snap** is exempt from the toolchain, because it bundles a prebuilt `evdev`. The APT
package is not — its post-install step `pipx`-installs the Python package, so it compiles
`evdev` like every other channel. (The `.deb` does not declare a build toolchain in `Depends`,
so that post-install step can still fail on a machine without one — filed as a follow-up
rather than fixed here, since the real repair is shipping a wheel, not making every user
install a compiler.)

### Added — the demo reel is on YouTube, and the site now says so in both directions

The 40-second reel was published to YouTube (`nn8WUKsCvZ4`) with chapters and a description
that links back to the repo, docs, PyPI and the preprint — but nothing in this repository
linked *to* it, so the two halves were invisible to each other. The README and the docs
homepage now link the video, and the homepage `@graph` gained a `VideoObject` node plus a
`sameAs` entry, which is what lets a search engine or an answer engine connect the video to
the software entity rather than treating them as unrelated pages.

Deliberately a **link, not an embed**: a YouTube iframe would load third-party tracking on
the homepage of a project whose entire claim is that nothing leaves your machine. The
trade-off is honest — without an on-page player Google may decline a video rich result, and
the animated GIF above the link already carries the same reel — so the markup is here for
entity resolution, not on the promise of a SERP thumbnail.

### Fixed — the two files most likely to be quoted about this project were citing non-canonical URLs

`docs/llms.txt` exists to be ingested whole by AI answer engines, so every URL inside it is a
citation candidate — and 23 of them used the extensionless form (`…/use-cases/voice-coding`).
Those resolve with a 200, which is why nothing looked broken, but the site runs
`use_directory_urls: false`: the page's own `rel=canonical` and its `sitemap.xml` entry are
both the `.html` form. An engine quoting llms.txt was therefore being handed the duplicate
rather than the URL the site declares for itself. The README's seven use-case links had the
same defect, and matter for the same reason — it is the highest-authority link source the
project controls, and the arXiv preprint points at it four times.

Every URL in llms.txt is now verified twice: it returns 200 **and** it appears verbatim in
`sitemap.xml`. That double check earned its keep immediately — a naive rewrite appended a
second extension to paths that already ended in `.html`, producing `mobile/index.html.html`
(404), and mangled the two directory URLs. llms.txt also now mentions the 40-second demo
recording, which it did not reference at all, carrying the same re-enactment disclosure the
video and the site use.

### Fixed — the snap asked the build farm for five architectures it can never run on

`snap/snapcraft.yaml` declared no `platforms:`, and to the snapcraft.io build service an
unset architecture list does not mean "amd64" — it means *every* architecture Launchpad
offers. Connecting the repo therefore fanned each push out to seven builds, of which five
were impossible before they started: `ctranslate2` (via faster-whisper), `onnxruntime` (via
onnx-asr) and `PySide6` publish manylinux wheels for `x86_64` and `aarch64` only, **and none
of the three publishes an sdist at all**, so on armhf, i386, ppc64el, s390x and riscv64 pip
has nothing it could even attempt to install. Observed on the first fan-out: amd64 built and
released, i386/armhf/s390x/ppc64el all reported "Failed to build".

The cost was not wasted builder time so much as a permanently red build history — five
failures per push that nobody can act on, which is exactly how a real regression gets
overlooked. `platforms:` now names `amd64` and `arm64`, the two the dependency set can
actually support. The remaining runtime deps were checked against the same bar: numpy and
cryptography ship aarch64 wheels, sounddevice / faster-whisper / onnx-asr / typer are pure
Python, and evdev builds from its sdist against the already-staged `python3-dev`.

arm64 then proved itself twice over. Build #3238849 succeeded in 14m13s — the first arm64
build this project has ever completed, slower than amd64's 7m20s rather than failing fast
the way the impossible five did, which died at pip in 2–10 minutes with nothing to install.
It then **released: `arm64 rev27` is live in `latest/edge`**, the first arm64 revision YazSes
has ever published, so `snap install --edge yazses` now works on 64-bit ARM.

`stable` remains amd64-only and is unaffected: it is published solely by the tag workflow,
which builds on an amd64 runner. arm64 reaches stable when the build service's arm64 output
is promoted, which is a separate decision.

### Fixed — the snap hardcoded the x86_64 library path, so any other architecture shipped mute

`ALSA_PLUGIN_DIR` in the app definitions and `LD_LIBRARY_PATH` in all four wrappers contained
the literal string `x86_64-linux-gnu`. The ALSA pulse plugin and the PulseAudio libraries live
beneath that Debian multiarch triplet, so on any non-amd64 build both paths resolve to nothing
and microphone capture fails — silently, with no message a user could act on, which is the
worst possible failure mode for a dictation tool. It was invisible only because amd64 was the
sole architecture ever built.

The four wrappers now source a single `snap/local/snap-env.sh` that derives the triplet from
snapd's `SNAP_ARCH` at runtime, and the audio variables moved there from the `apps.*`
`environment:` blocks — that block cannot expand the triplet, which is why the constant was
there in the first place. One copy of the path logic instead of four also removes the drift
that let the daemon and the CLI disagree.

## [2.15.1] - 2026-08-07

Two fixes, both found by tightening something that had been loose. Dictation stops deleting
a real English verb, and the type gate — 73 errors deep and therefore useless — is clean and
immediately earned its keep by surfacing a latent crash.

### Changed — the type gate is real now: `mypy src` is clean, and it found a latent crash

`mypy src` had been carrying a **73-error backlog across 21 files**, which meant the gate
could not distinguish a new mistake from the pile — a red gate that is always red is not a
gate. It is now **0 errors**, and `ruff` covers `scripts/` too (it had silently drifted out
of scope, and had 2 errors nobody could see).

Almost all of it was annotation debt rather than defects — `None`-initialised attributes that
were never annotated `T | None`, two lambdas mypy could not infer, a `Match | None` rebound to
`str`, and `os.environ` typed as `dict` when it is a `Mapping`. Three Windows modules use
`ctypes.windll`/`winreg`, which typeshed declares only for `sys.platform == "win32"`; those
are scoped to an `attr-defined` override in `pyproject.toml` with the reasoning next to it,
narrow enough that real mistakes in those files still fail.

**One real defect fell out of it.** `yazses update` did `" ".join(status.command)` while
`command` is `list[str] | None` — `None` for any install method `upgrade_command()` has no
recipe for. `detect_install_method()` only ever returns snap/uv/pipx/pip today, so it was not
reachable in production, but APT is a shipped install channel and the day an `apt` branch is
added it would have been a `TypeError` instead of a helpful message. It now says which method
has no automatic upgrade and exits non-zero, with a test that fails without the guard.

Also fixed while checking: `linux/tray.py` used the unscoped Qt enum spellings
(`Qt.transparent`, `QPainter.Antialiasing`, `Qt.AlignCenter`). They work today, but the
scoped forms are what the stubs and Qt6 document; verified both resolve to the same values
before switching.

### Fixed — "To err is human" no longer becomes "To is human" (contract **4.0.0 → 5.0.0**)

`err` shipped in the default `[filters.disfluency] filler_words`, and it is also an ordinary
English verb. Disfluency filtering is on by default, so ordinary dictation lost a real word:

```
"To err is human"             ->  "To is human"
"Err on the side of caution"  ->  "on the side of caution"
```

This is **not** part of the #117 → #120 → #122 sentence-initial chain, and none of those fixes
touched it: the first case is lowercase and mid-utterance, so plain filler removal did it with
no guard involved. It had been there far longer and was invisible because `err` reads as a
hesitation spelling (#125).

`err` is now absent from the default filler list and from the hesitation particles, so a
sentence-initial `Err` is safe too. The accepted cost is the one #120 already settled in this
direction: someone who genuinely hesitates with "err" keeps it, because leaving a filler in
beats deleting a word. Adding it back is one line of config.

**`ah` was decided at the same time and deliberately kept.** The line is lexical rather than
phonetic: `ah` is an interjection in every dictionary sense, so removing it costs tone and
never meaning, while `err` has a verb sense and cannot qualify. That test is now written down
next to the particle set instead of being rediscovered a fourth time.

As with #122, the regenerated vector diff is **additions-only** — no previously pinned
expectation changed — so the major bump is by intent: the default filler list is shared
behaviour other platforms must reproduce, and it changed.

### Fixed — `snap install --edge` served a build from before v2 existed

The release workflow only ever published to `stable`, and nothing else fed `edge`. A channel
that is never written to does not stay empty, it stays **stale**: `edge` sat on 1.4.1 while
`stable` was 2.15.0, so anyone following the usual "try edge for the newest build" instinct
got a snap eleven releases old. Releases now publish to `stable,edge`; verified in production
on this tag — `edge` moved 1.4.1 → 2.15.1.

### Security — GitPython 3.1.57 → 3.1.58 (6 advisories)

All six land on GitPython, which reaches this project only through
`mkdocs-git-revision-date-localized-plugin` in the `docs` dependency group — it is **not** in
the released wheel's dependency set, so no shipped artifact was exposed to the git
option-injection or `--pathspec-from-file` arbitrary-read issues. Bumped anyway: the fix was a
lockfile line and the alerts are real.

## [2.15.0] - 2026-08-07

**The honesty release.** Every headline item here is the same shape of defect: the software
was telling somebody something that was not true. Dictation quietly deleted real words;
`doctor` handed snap users a fix that could never work; the installer trusted whatever a URL
served; and a contributor wall that promised to list everyone listed half of them. None of it
crashed, which is why none of it had been noticed.

Also the release where the contract earned its keep: shared text behaviour went **1.1.0 →
4.0.0** across three deliberate, separately-argued changes — every one of them raised, fixed
and reviewed in the open, and inherited automatically by the Android port.

### Fixed — inside a snap, `doctor` gave keyboard advice that could never work

On a strictly confined snap, `yazses doctor` reported `Keyboard capture: denied` and told
the user to run `sudo usermod -aG input $USER` and log back in. That advice is not merely
incomplete — it is impossible: snapd blocks raw reads of `/dev/input/event*` regardless of
group membership, so users followed it in circles and concluded the app was broken (#44).

`doctor` now detects that it is running inside a confined snap and names the only two things
that can actually fix it — connecting the `raw-input` interface, or installing unconfined:

```
sudo snap connect yazses:raw-input
yazses restart
```

The snap also declares `raw-input` for the first time, which is the missing precondition
(`snap/snapcraft.yaml` previously had no interface that could ever grant keyboard access).
snapd does not auto-connect it, so the manual `snap connect` above is still required, and
Wayland keystroke *injection* remains unavailable under confinement either way — the docs
continue to steer anyone who needs it to the APT or `pipx` install.

### Fixed — `"So um …"` survived, and `"Uh…"` was mistaken for a file path (contract **3.0.0 → 4.0.0**)

Two position-0 cases left over from the previous two entries, both reachable in ordinary
dictation (#122).

**`"So um the meeting is at noon"` came through untouched.** Narrowing the relaxation to
unambiguous fillers used "is it a single word?" as the test, which excluded `so um` and
`so uh` along with genuinely ambiguous phrases like `you know`. Worse, because the longer
`so um` alternative matched first and consumed the `um`, the inner `um` was never stripped
separately either, so the whole phrase survived. Nobody dictating `"So um …"` means to keep
it. The test is now whether the filler **contains a non-lexical hesitation particle**
(`um`, `uh`, `er`, `err`, `ah`, `hmm`) rather than how many words it has — which admits
`so um` and `so uh`, and still refuses `you know` and `i mean`. `okay so` is deliberately
refused too: it has no hesitation particle, and `"Okay so what do you think?"` is a
perfectly good message.

**`"Uh... so I think"` was protected as if it were code.** Whisper writes hesitations with
trailing ellipses, and the code-identifier guard treated any dot in the token as evidence of
a path — correct for `main.py`, wrong for `Uh...`. Only a dot *inside* the token counts now,
and a filler removed from position 0 takes its own trailing punctuation with it rather than
leaving `"... so I think"`. `Actually.` at the end of a sentence is unaffected: it is not a
hesitation particle, so it never reaches this path.

The bump is **major by intent, not by mechanical diff** — no previously pinned expectation
changed, but behaviour that other platforms must reproduce did, and an unpinned behaviour
change is still a behaviour change.

### Added — property-based fuzz tests for the text post-processing pipeline (#115)

`tests/test_property_pipeline.py` uses Hypothesis to throw untrusted-ish input — control
characters, mixed scripts, RTL (Persian), zero-width characters, emoji, and very long
transcripts — at `clean_text`, `filter_transcript`, `apply_voice_punctuation`,
`continuation_prefix`, and `classify`. It asserts none of them raise, `clean_text` is
idempotent, `filter_transcript` never grows the text, and `classify` never returns a
non-DICTATE intent that isn't backed by an actual Tier-1 rule match. No property
violations turned up in this pass; the tests stay as a bounded-budget regression net
(`OpenSSF Scorecard` fuzzing check).

### Changed — sentence-initial filler stripping is narrowed to unambiguous fillers (contract **2.0.0 → 3.0.0**)

The #117 relaxation allowed any capitalised filler at utterance position 0 to be removed.
That fixed `"Um the meeting is at noon"` but also ate ordinary content words: `"Right turn at
the corner"`, `"Like button is broken"`, and `"Actually is a strong word"` all lost their
first word. The relaxation now applies only to fillers that are never ordinary
sentence-initial content words (`um`, `uh`, `er`, `err`, `ah`, `hmm`).

Multi-word fillers are deliberately **not** relaxed at position 0: `"You know the meeting is
at noon"` can be a real sentence addressed to someone, so it stays protected. Lowercase
multi-word fillers mid-utterance keep their existing removal behaviour.

The contract vectors were regenerated and the version was bumped because this changes a
shared expectation (closes #120).

### Changed — a filler at the start of a sentence is finally removed (contract **1.1.0 → 2.0.0**)

Filler removal always advertised itself as case-insensitive, and the regex genuinely was.
But the guard behind it refuses to touch any token containing an uppercase letter — that is
what stops the filter eating the `Like` in "the Like button" or a proper noun in the middle
of a sentence. The side effect went unnoticed for a year: **Whisper capitalises the first
word of an utterance**, so a filler in the single most common position it occurs — leading
`"Um, I think we should…"` — was capitalised, therefore protected, therefore never removed.

The uppercase check is now relaxed for **utterance position 0 only**:

```
"Um the meeting is at noon"        →  "the meeting is at noon"     (was unchanged)
"You know the meeting is at noon"  →  "the meeting is at noon"     (was unchanged)
"the Like button is broken"        →  unchanged                    (still protected)
"open the Actually settings panel" →  unchanged                    (still protected)
"call basically_fn in um main.py"  →  "call basically_fn in main.py"  (code tokens intact)
```

**The trade-off, stated plainly:** a *sentence-initial* proper noun that collides with the
filler list is now stripped, so `"Right turn at the corner"` becomes `"turn at the corner"`.
Disfluency filtering is on by default and `right`, `like`, `actually` and `literally` are
all default fillers, so this can reach real dictation. It was chosen deliberately —
sentence-initial `"Right, so…"` as a filler is far more common than as content, and
mid-utterance text stays fully protected. To opt out of a specific word, remove it from
`[filters.disfluency] filler_words`. Narrowing the relaxation to fillers that are never
content words (`um`, `uh`, `er`, `hmm`) is tracked in #120.

Because this changes an expectation every platform shares, `contract/VERSION` goes to
**2.0.0** and the golden vectors were regenerated — the Android port inherits the new
behaviour rather than drifting from it (community contribution, #119 — thanks
@AshSgDe29071999; closes #117).

### Changed — shell completion is documented where people install, not only in the CLI reference

`yazses --install-completion` shipped some time ago but was mentioned only in
`docs/cli-reference.md`, which is not where anyone is standing when they would want it. The
README install path now points at it (community contribution, #118 — thanks
@AshSgDe29071999; closes #75).

### Fixed — the advertised APT repository was returning 404, and five surfaces still pointed at the retired host

Switching GitHub Pages to the Actions-built MkDocs site means the `gh-pages` branch is no
longer *served* — only one Pages source can be active. The branch still carries a correctly
signed apt repo (`Release`, `InRelease`, `Packages`, `KEY.gpg`, `yazses_2.14.0_amd64.deb`),
but every advertised install path resolved to nothing: `mskazemi.github.io/yazses/apt/`
301-redirects to `mskazemi.com/yazses/apt/`, which **404s**. `install-apt.sh` had already
been routed around this via `raw.githubusercontent.com/.../gh-pages/apt` (verified 200), so
the repo worked for anyone using the installer and was broken for anyone following the
documented commands. The release-notes template and the generated apt index page now use the
same raw channel the installer uses.

Separately, `mskazemi.github.io` was retired as the docs host on 2026-08-06 but five
surfaces still asserted it. `docs/_config.yml` was the worst of them: a leftover **Jekyll**
config declaring `url: https://mskazemi.github.io` and `baseurl: /yazses`, contradicting
`mkdocs.yml`'s `site_url`. Jekyll has not built this site since the move to Actions, so the
file did nothing but ship a wrong-host assertion into the published site. Removed. Also
repointed at `mskazemi.com/yazses/`: `branding.py`'s `WEBSITE` (surfaced by `yazses about`)
and `snap/snapcraft.yaml`'s `website` field, which is a live outbound link on the Snap Store
listing.

### Fixed — a 35 MB screen recording had been committed, and nothing would have caught it

An unusable full-screen capture reached the repo through a broad `git add -A docs/`:
unreferenced, 35 MB, and invisible in review. Git keeps history, so a file like that is
paid for by every future clone permanently — deleting it later does not undo the cost, and
undoing it properly needs a history rewrite and a force-push.

The file is out of the tree, and `scripts/check_repo_size.py` now fails the build on any
tracked file over 8 MB — well above a legitimate demo GIF, well below anything that makes
cloning noticeably slower. It runs in a new cheap `repo-hygiene` CI job.

That job also runs **ruff**, which CI had never enforced. Lint was a local-only gate, so
`main` was carrying two lint errors nobody was told about; both are fixed here.

### Security — `install.sh` no longer pipes an unpinned, unverified script into `sh`

The `uv` bootstrap step downloaded `astral.sh/uv/install.sh` and ran it straight off the
network. It now pins a specific `uv` release, downloads that version's installer to a temp
file, and checks its sha256 before executing — a mismatch aborts the install instead of
running whatever the URL happens to serve that day. This is the script the README tells
people to run with `curl | bash`, so it is the one place in the project where a supply-chain
substitution would matter most (part of #116).

Verification is portable: macOS has no `sha256sum`, so it falls back to `shasum -a 256`, and
if neither exists the install **aborts rather than skipping the check** — an unverifiable
download is treated as a failure, not as a pass. The unverified temp file is removed on
every exit path, including rejection.

### Added

- Research section rebuilt as a citable, audience-routed survey. Each page now
  carries a graded reference list (primary sources with DOI/arXiv, marked
  *measured* / *vendor* / *secondary*), a one-box summary, measured-value
  charts, and a per-page contribution call. New on the index: measured
  text-entry rates by modality, an audience router (researcher / student /
  builder / people who cannot use a keyboard), a glossary, and a BibTeX block.
- `hooks/research_schema.py` emits schema.org `ScholarlyArticle` JSON-LD for
  every research page, deriving the `citation` list from the page's own
  References section so the structured data cannot drift from the visible
  bibliography.
- Shell Tab completion for bash, zsh, and fish: `yazses --install-completion`,
  plus pre-generated static scripts under `contrib/completion/` (first
  community contribution, #56 — thanks @Maqbool61).
- The roadmap is now a visionary, graphical document (era timeline, product
  mindmap, horizons flow) and every open issue is filed under an outcome-named
  GitHub milestone. New docs page "Students, researchers & industry" maps
  thesis-sized projects to open issues.

### Changed

- Research pages carry per-page `title`/`description` front matter. They
  previously inherited the site-wide meta description, so all five pages
  presented search engines and answer engines with identical, unrelated snippet
  text.
- The research section is now linked from the documentation home page and the
  README; it was previously reachable only through the nav bar.

### Fixed

- The research index's `quadrantChart` failed to render at all: Mermaid's
  lexer rejects parentheses in an unquoted point label, so the whole diagram
  was replaced by "Syntax error in text". Point labels are now quoted.
- Corrected two citations that pointed at papers not reporting the cited
  result. The blink-switch figures (99.5% accuracy, 1.3 s, 0.10 false
  positives/min) are Li et al., *Neurocomputing* 2018 — previously attributed
  to a paper that cites them; the consumer-EEG SSVEP throughput is Lin et al.,
  *J. NeuroEng. Rehabil.* 2014. The Apple Vision Pro accuracy measurement is by
  Huang et al., not "Hou et al.". Unverifiable figures were replaced with
  claims their sources support.

- `set_config_key()` no longer quotes numeric or boolean values by default. The
  rendering is now inferred from the value's Python type (`bool` -> `true`/`false`,
  `int`/`float` -> bare, everything else -> quoted string with `"`/`\` escaped), and
  `quote=` remains available as an explicit override for existing callers
  (community contribution, #57 — thanks @waterlemonnn; closes #53).
- APT repository publishing works again: the workflow had failed on every run
  since 2026-07-01 because the GPG signing secrets were never migrated from the
  old repository. A fresh signing key was generated and the repo now serves the
  current release, signed. Re-running `install-apt.sh` picks up the new key.
- Windows `.exe` and macOS `.dmg` builds fire again on release tags: both
  workflows still carried the pre-v2 `v0.*` tag filter, so no desktop binaries
  had been built since v0.x. From the next tag, releases attach all three
  platform artifacts.
- The wiring-honesty test read source files without an explicit encoding,
  breaking the test suite on Windows (cp1252). CI is green on all three
  platforms again.

### Security

- `cryptography` raised to `>=50.0.0`, closing a high-severity Bleichenbacher
  timing oracle in PKCS#7 decryption. YazSes uses this library for the
  machine-bound AES-256-GCM cipher protecting the learning corpus, so it is a
  dependency of the encrypted-at-rest guarantee in ADR-012.
- **Private vulnerability reporting is now enabled.** It had been off, which
  meant the reporting channel `SECURITY.md` documented —
  `/security/advisories/new` — could not be reached by anyone outside the
  repository. The documented way to report a vulnerability privately did not
  work; it does now.
- Dependabot alerts and security updates enabled (both were off), with a
  grouped monthly schedule for `uv` and GitHub Actions.
- Supply chain: all 38 GitHub Actions references are pinned to full commit
  SHAs rather than mutable tags, every workflow now defaults to a read-only
  `GITHUB_TOKEN` with write scopes declared per job, and CodeQL (Python and
  Actions), OpenSSF Scorecard, and dependency review run in CI. Three real
  CodeQL findings were fixed, including a single-instance lock file created
  `0o644` where ADR-011 §7 requires `0o600`.
- `main` and release tags are protected by repository rulesets: neither can be
  force-pushed or deleted. Published history and the tags that release
  artifacts are built from can no longer be rewritten by accident.

### Changed

- Dependency refresh: `mediapipe` 0.10.35 → 1.0.0, `typer` 0.26.8 → 0.27.1,
  `platformdirs` 4.10 → 4.11, `onnxruntime` 1.27 → 1.28, `llama-cpp-python`
  0.3.33 → 0.3.34, `mcp` 1.28.1 → 2.0.0. The MediaPipe major keeps the
  FaceLandmarker API the gaze backend uses, and ships a `manylinux_2_28_aarch64`
  wheel — so the optional `gaze` extra becomes installable on ARM Linux for the
  first time (installable, not yet tested there). Its Linux wheel grows from
  12 MB to 36 MB; this affects only users who opt into gaze.

## [2.14.0] - 2026-08-07

The perception release. Backed by a web-refreshed state-of-the-art study
(competitors, local STT engines, gaze/EMG/BCI input — an internal research note,
ADR-v2-129): the eye, voice, and muscle input paths each got the upgrade the
research says nobody else ships, and the STT engine monopoly is broken. Every
addition is opt-in and lazy-installs its dependencies — a plain dictation
install stays exactly as small as before.

### Added — Parakeet: a second STT engine that beats whisper-large-v3 on CPU

`[stt] engine` selects between `faster-whisper` (default, unchanged) and
`parakeet` — NVIDIA Parakeet TDT 0.6B v2 via ONNX Runtime (no torch, no NeMo,
CC-BY-4.0): lower word-error rate than whisper-large-v3 at roughly 4x
whisper-small's CPU speed, and it does not hallucinate text on silence.
`yazses features enable stt-parakeet` installs the `onnx-asr` extra on demand;
a missing dependency falls back to faster-whisper with a warning that names
the fix, never a crash. Under the hood the engine is now a real seam
(`stt/base.py` Protocol + `stt/factory.py`), and the streaming decoder
consumes a public `decode_window()` instead of reaching into the engine's
private model — a second engine now costs ~200 lines, not a refactor.

### Fixed — `yazses features enable` can no longer lie

An audit found 72 registry entries whose feature packages nothing in the
daemon or CLI ever imports: enabling them wrote a config key that no code
read, reported "enabled", and changed nothing. These are now marked
`planned — designed, not yet wired`; `features enable` refuses them with an
honest explanation, `features disable` still cleans up stale keys older
versions seeded, and first-run no longer seeds dead recommended-tier keys.
A permanent test computes package reachability from every entry point and
fails if the flag set ever drifts from reality — in either direction.

### Added — gaze deixis: "close this" acts on the window you're looking at

In command mode, whole-utterance demonstrative commands — `close this`,
`focus that window`, `switch to this one`, `minimize that` — now resolve
against the gaze snapshot taken at hold-start (ADR-v2-129). Destructive
actions on a gaze-routed target ask first via an actionable toast, wiring
ADR-v2-010's until-now-dormant `needs_confirm` policy; `[gaze] deixis`
(default on, inside the opt-in gaze feature) controls it, and with
`route_dictation` off the gaze is snapshotted without stealing focus.

### Added — sotto-voce command channel: whisper a command, speak to dictate

With `[whispermode] enabled`, a *whispered* burst is parsed as a command and
never typed, while normally-voiced speech dictates (the DualVoice pattern).
Detection is pure numpy — whispered speech has no fundamental frequency — with
a median vote across the burst so one breathy word can't flip it. No new
dependencies; `[whispermode] command_channel = false` reverts to
dictation-only behaviour.

### Added — EMG squeeze-to-talk is now actually constructed

`[emg] device_port` had config, docs, and a tested YESP serial backend — and
no code path that ever built it. The daemon now has a pluggable
activation-source seam: setting the port starts the EMG listener alongside
the hotkey, with a squeeze driving command mode (`mode = "command"`, default)
or plain hold-to-talk (`full_text`). Missing pyserial degrades to a logged
no-op, never a crash.

### Fixed — the default gaze backend's confidence was hard-coded to 1.0

`[gaze] confidence_min` gated nothing for the MediaPipe backend: every sample
was reported fully confident. Confidence is now measured per frame from
left/right eye agreement (the two eyes estimate the same gaze independently,
so divergence means bad landmarks), and low-quality frames fall back to the
focused window instead of misrouting dictation.

## [2.13.0] - 2026-08-07

The reliability release. Every defect fixed here was **silent or actively misreported** —
the app kept insisting it was fine while dictation produced nothing — so the theme is not
new capability but making YazSes tell the truth about itself, and repair itself where it
honestly can.

### Added — `yazses verify`: proof the pipeline works, instead of inference

`doctor` checks prerequisites — a mic exists, xdotool is installed, the model is cached.
Every one of those can pass while dictation still produces nothing: the silence gate can sit
above your voice, the model can return empty text, the injector can be aimed at a window
that ignores synthetic keys. Prerequisites are evidence about the parts, not evidence that
the parts work together.

`yazses verify` records you, runs the real chain — capture → silence gate → transcription →
optional injection — and names the first link that breaks, with the command that fixes it.
It stops at that link rather than cascading, because a report listing four failures hides
which one to act on. `--type` also types the result into the focused window.

### Added — the tray icon is supervised for the whole session

The daemon launched the tray once at startup and never looked again, so a tray that crashed
— a Qt fault, an OOM kill, a desktop-shell restart — left dictation working with no
indicator at all. That is the insidious version: the only thing that tells you whether
YazSes is listening, in command mode, or has nowhere to type is gone, and nothing says so.

A supervisor now checks every 20 s and brings it back, reading liveness from the tray's own
single-instance lock rather than a remembered child PID — the lock is correct when the tray
was started by hand, survived a daemon restart, or was replaced, and it is the same
condition a new tray would test, so supervision cannot fight the lock and spawn a process
that instantly exits. Bounded at five relaunches, after which it says so and points at
`yazses tray` for the real error, rather than spawning a process forever.

### Added — the silence gate now retunes itself when it is swallowing your voice

`[accessibility] vad_threshold` is one float deciding whether a burst was speech, and it is
wrong by construction: the right value depends on the microphone, the room and the speaker,
so a number calibrated once stops fitting the moment any of them changes. When it drifts too
high the failure is the worst kind — you hold the key, you speak, nothing is typed, and the
only evidence is a log line you have no reason to read.

Not hypothetical: on the machine this was written on, a laptop's digital mic array produced
`mean|audio|` of 0.003–0.005 **at full gain** against a 0.0024 gate. "Turn the microphone up"
was not available — it was already at 100%.

So YazSes watches outcomes instead. A run of bursts discarded as silence, with no successful
transcription between them, is the signature of a gate set above the user's voice, and those
bursts say where it should have been. The threshold is lowered to pass them, saved to
`config.toml` so the fix survives a restart, and announced — a setting that changes itself
silently is its own kind of unreliability.

Deliberately one-directional. Lowering the gate when speech is being lost repairs a broken
setup; raising it when noise leaks through only trims transcripts the user can already see.
Only the first failure is invisible, so only the first is automated. Discards *above* the
gate produce no suggestion at all, because a muted or dead microphone makes the same symptom
and lowering the threshold would fix nothing.

### Added — `yazses report`, a diagnostic bundle that never leaves the machine

Written locally, printed as a path, and reviewable before it goes anywhere. It carries
versions, daemon state, config-with-identifiers-removed and the tail of the metadata-only
log; the learning corpus is reported by size and never opened. No upload, no telemetry — a
daemon that phones home with diagnostics would trade away the property YazSes is chosen for.

### Fixed — `yazses.__version__` had been wrong for several releases

It was a hardcoded `2.10.0.dev5` while `yazses --version`, which reads package metadata,
correctly said 2.12.1. Anything trusting the constant reported a build that no longer
existed — worse than reporting nothing when the question is what someone is running. It is
now derived from the metadata, so there is one answer.

### Added — `yazses autostart`, so a daemon behaves like a daemon

`install_autostart()` refused to do anything unless `install.sh` had already written the
systemd unit. Every ordinary Python install — `pipx`, `uv tool`, `pip --user` — therefore
had **no autostart at all**, and nothing anywhere said so: YazSes simply was not running
after a reboot until you remembered `yazses start`. A daemon you have to remember to launch
is not a daemon.

`yazses autostart enable` now writes the unit itself, pointing at the console script beside
the running interpreter, and rewrites it when an upgrade moves it. `disable` and `status`
round out the group, and `yazses doctor` gains a **Starts at login** check that answers the
question nobody asks until after a reboot. The unit text has one home in the code instead of
being retyped in each installer.

Restart behaviour is deliberate: `on-failure`, not `always`, because a clean exit is what
`yazses stop` produces and restarting then would fight the user rather than heal anything.
The StartLimit pair bounds the crash loop. Killing the daemon outright brings it back in
about five seconds.

### Fixed — `status` and `start` could give opposite answers about the same daemon

"Is a daemon running?" had two sources of truth. The PID file is removed on a clean exit but
survives a `kill -9`, and nothing recreates it if it goes missing under a live daemon — at
which point `yazses status` reported **"not running"** while starting one failed with
**"another YazSes daemon is already running"**. Two commands, opposite answers, neither
actionable, and a real state this project reached in practice.

The lock file is now the authority. It is held by the OS for the process lifetime, so it is
exact in both directions — never stale after a crash, never absent while a daemon runs — and
it already carried the holder's PID. `is_running()` and `read_pid()` consult it first and
fall back to the PID file only where no lock primitive exists. A stale PID file no longer
fakes a running daemon, and a missing one no longer hides a real one.

### Fixed — a config file can no longer stop YazSes from starting, or break it silently

Python dataclasses enforce nothing at runtime, so `load_config` accepted whatever TOML
contained and the mistake surfaced much later, somewhere unrelated. One quoted number —
`vad_threshold = "0.004"` instead of `0.004` — turned every dictation burst into `ufunc
'less' did not contain a loop ...` while the daemon reported itself healthy and typed
nothing. A mistyped *key* was worse: an unexpected keyword argument aborted the entire
load, so a single bad character meant no daemon at all.

Config loading is now total — there is no file that makes it raise. Values that can be
repaired are repaired (`"0.004"` → `0.004`, `"false"` → `false`, `7.0` → `7`), values that
cannot fall back to their documented default, unknown keys and sections are dropped, and
unparseable TOML starts on defaults rather than not starting. Every one of those decisions
is recorded and reported: the daemon lists them at startup, and `yazses doctor` gains a
**Config validity** check naming each faulty line and whether it was repaired or defaulted.

Degrading loudly beats failing silently, and both beat refusing to start — which is the
worst outcome for a tool you reach for by holding a key. The checker is generic over the
config dataclasses, so new sections are covered the day they are added. (#52)

### Added — a one-command demo recorder, so the README can finally show the product

A dictation tool is hard to describe and trivial to show, but the README's only visual is a
`yazses doctor` screenshot — a diagnostic, not the result — and recording a real clip meant
first installing a screen recorder, which nobody had.

`scripts/record-demo.py` records a region or a clicked window straight to a size-optimised
GIF: countdown, capture, resize to README width, shared-palette quantisation, identical-frame
collapsing, and a 5 MB budget with advice when it is missed. It runs via `uv run` with inline
script metadata, so its two dependencies land in uv's cache — nothing installed system-wide,
no `sudo`, and nothing added to the project's dependencies. `--shot` takes a still instead.

Motionless frames at the start and end are trimmed automatically, so you don't have to race
a countdown: start a long recording, perform when you're ready, and the clip comes out as
long as the action. A pause in the middle survives, because that one is content — it is the
wait while speech is transcribed.

`docs/demo-guide.md` is now a recipe rather than a list of tools: the exact command, a
timed shot list, what to check before recording, and which knob to turn when the file is
too big.

### Fixed — the tray icon called a working daemon faulty after one silent clip

Red is the icon's "something is wrong" colour, and `icon_spec` reached for it as soon as
`silent_streak` was non-zero — a single discarded clip, which is ordinary: the hotkey gets
brushed, or a hold is released before speaking starts. It then stayed red until the next
successful dictation.

The daemon does not agree that one clip is trouble. It has a setting for precisely this
judgement, `[audio] silent_streak_threshold` (default 3), and checks it before notifying.
The daemon now reports that threshold in its status payload and the icon colours on the
same rule, falling back to the default of 3 when an older daemon omits it. A red badge
that appears when nothing is wrong is worse than no badge, because it teaches you to
ignore the real one. (#55)

### Fixed — the tray icon could freeze on a stale colour after a restart

`yazses restart` takes the IPC socket down for a second or two. The tray's poll thread
computed its boot deadline once at start and never reset it, so that deadline — meant
only as a "did the daemon we spawned ever come up?" grace period — also governed every
later outage. Any tray running longer than 30 seconds, which is every tray in normal
use, exited its poll thread on the first blip and never repainted again.

The colour it froze on was usually red: a daemon closing the socket mid-call surfaces as
an RPC error, which paints red, and the poll that would have cleared it never happened.
Nor could a restart heal it — the frozen tray still held `tray.lock`, so each replacement
tray exited as a duplicate. A healthy daemon could sit behind a red icon indefinitely.

Giving up now applies only to a daemon that has never answered. After a successful call
the loop always survives an outage: blue while a restart is plausibly in flight, red once
past a short grace period, so a genuinely dead daemon is still reported honestly. The
decision is a pure `unreachable_decision()` with unit tests. (#54)

### Documentation — diagnosing a config mistake that produces an unrelated error

A quoted number in `config.toml` (`vad_threshold = "0.004"` instead of `0.004`) loads
without complaint and then makes every dictation burst fail with a numpy `TypeError` that
names neither the file nor the key. Troubleshooting now leads with that failure signature
and its fix, and the generated configuration reference states that only `str` values take
quotes. Also documented: reading the daemon's startup banner as the record of which
settings are actually in effect, and diffing it against the rotated log to find what
changed — plus the two settings (`[streaming] enabled`, `[accessibility] vad_threshold`)
that alter how dictation behaves without ever raising an error.

The underlying defects are tracked in #52 (the config reader never type-checks) and #53
(the config writer quotes by default, turning numbers into strings).

## [2.12.1] - 2026-08-06

A bug-fix release. Four defects in the "enabled but doing nothing" class: a leaked
transcription thread that burned CPU indefinitely, and three features that reported
themselves as working while silently doing nothing (or telling users to install something
that could not help). Also the documentation and discoverability work since 2.12.0.

### Fixed — enabling a translation that cannot run silently transcribed instead

`[translate]` only supports Whisper's X→English task. Selecting the unimplemented
`seamless` backend, or any non-English `target`, made `translation_task()` return `None` —
correct behaviour, but the user got their speech transcribed untranslated with nothing in
the log. Enabling "translate to French" and receiving untranslated French back is
indistinguishable from translation being broken.

New pure `translate.mode.inactive_reason()` names the specific reason, and the daemon logs
it **once per process** via a new `_warn_feature_inert` helper (shared, so other
enabled-but-inert features can report the same way). Behaviour is unchanged — this only
makes an existing silent degrade audible.

### Fixed — three backends you could select had never been built, and said so misleadingly

`[denoise] backend = "deepfilternet"`, `[voiceprint] backend = "resemblyzer"` and
`[recimport]/[meeting] backend = "pyannote"` are all selectable, documented options whose
adapter modules **do not exist in this build**. Each factory caught the resulting
`ImportError` and told the user to install an extra — advice that can never work: there is
no `denoise` extra at all, the `voiceprint` extra ships speechbrain only, and `diarization`
ships sherpa-onnx only.

Worst of the three, **`yazses features enable denoise` reported the feature ON while
`apply_denoise` silently returned untouched audio** — no log line, no warning, no way to
tell it apart from denoising that simply wasn't helping.

- New `system/backends.py` (`probe_backend`) separates "the optional dependency is missing"
  (installing the named extra fixes it) from "the adapter was never shipped" (nothing can),
  and produces the honest message. Wired into all three factories.
- Denoise now logs **once per backend** — not once per dictation burst — explaining that
  audio is passing through unprocessed. This follows the same "never degrade silently" rule
  as the Meeting Mode diarization-model warning.
- The `denoise` feature is re-tiered `optional` → `experimental`, so enabling a no-op needs
  `--force`, and its description says plainly that the backend isn't implemented yet.

Behaviour is otherwise unchanged: every path still degrades to a working fallback and never
raises into dictation.

### Changed — the daemon orchestrator and Meeting Mode are now type-clean

Typed the ~20 daemon attributes that were declared bare `None` and the two
`MeetingResult` fields that were declared bare `object`, so `core/daemon.py` and the whole
`meeting/` package now pass `mypy` (75 errors across 22 leaf modules remain, down from 100
across 25). These are the highest-blast-radius modules in the codebase and the worst place
to send a first-time contributor, so they are cleared ahead of the per-module cleanup in
issue #47.

Typing them surfaced two real robustness gaps, both fixed:

- `_maybe_cocktail_gate` re-read `self._embedder` inside its per-frame closure, so a
  concurrent shutdown clearing the attribute could raise mid-gate; it is now bound to a
  local before the closure is built.
- `_voiceprint` was documented as an `Embedding` but actually holds the unwrapped d-vector
  (`emb.vector`), which the type checker caught against the `gate()` signature.

Added the first direct tests for the Cocktail Filter gate wiring (dormancy conditions,
embedder-failure fallback, and the matching-frame happy path) — it sits on the dictation
hot path and previously had none.

### Fixed — the mypy quality gate had no configuration

`CLAUDE.md` names `uv run mypy src` a quality gate, but no `[tool.mypy]` section existed, so
it ran on bare defaults and buried its real findings under ~35 import errors from optional
backends that a base install *correctly* omits — errors no contributor could fix. Added a
documented `[tool.mypy]` config; the gate now reports **100 genuine errors across 25 files**
(was 135 across 50), making the module-by-module cleanup in issue #47 actually actionable.
Not yet green — the remaining errors are pre-existing and tracked.

### Fixed — a discarded dictation burst leaked a Whisper decode loop forever

With `[streaming] enabled`, every hold started `StreamingEngine`'s background decode
loop, but only `commit()` ever stopped it — and `commit()` runs solely on the successful
transcription path. Any burst that returned early instead (audio below the VAD gate, a
Cocktail Filter gate-out, or no recorder) left its loop alive, re-decoding a rolling
buffer that could never grow again: **one leaked Whisper decode per interval, per
discarded burst, compounding until the daemon exited**. A few mis-fired holds were enough
to put a steady multi-core transcription load on an otherwise idle machine.

`_on_hold_end` now ends the loop before any early return, via a new non-blocking
`StreamingEngine.request_stop()` — so hold-release never waits on an in-flight decode,
while `commit()` keeps its blocking join before the final decode. `_shutdown()` calls the
blocking `stop()` so no decode thread outlives the process.

### Fixed — the docs site was telling search engines the wrong canonical domain

`mskazemi.github.io/yazses/` now **301-redirects to `mskazemi.com/yazses/`** and serves no
content at any path, but the site was still built as if github.io were its home. Every
indexable signal therefore pointed at a URL that only redirects: all 82 `sitemap.xml`
entries, the `Sitemap:` directive in `robots.txt`, every `rel=canonical`, `og:url`, the
homepage JSON-LD `url`, and the documentation links in the README, `llms.txt`,
`pyproject.toml`, `CITATION.cff` and the issue-template config.

Repointed `site_url` and all 34 references to `https://mskazemi.com/yazses/`.

!!! note "Owner action still required"
    The Google Search Console and Bing Webmaster properties are registered against
    `https://mskazemi.github.io/yazses/`, which now returns only redirects. A property for
    `mskazemi.com` is needed for indexing coverage to be reported at all.

### Documentation — pages that answer the questions people actually search

Every page on the docs site was brand-navigational ("Features", "CLI reference",
"Install on Linux"). Nobody searches for those, so the site could not surface for any
question a person asks *before* they know YazSes exists.

- **New "Use cases" section** — six problem-framed pages, each covering a distinct
  audience end to end and honest about where YazSes is the wrong choice:
  [voice dictation on Linux](docs/use-cases/voice-dictation-linux.md) (X11 vs Wayland
  injection), [private & confidential work](docs/use-cases/private-offline-dictation.md)
  (clinical, legal, air-gapped), [coding by voice](docs/use-cases/voice-coding.md),
  [accessibility & RSI](docs/use-cases/accessibility-rsi-hands-free.md),
  [transcribing recordings](docs/use-cases/transcribe-audio-offline.md), and
  [multilingual dictation](docs/use-cases/multilingual-dictation.md).
- **The paper is now linked from the project.** `arXiv:2607.28878` describes the system
  and links out to this repo, but nothing here linked back. Added a BibTeX entry and
  citation to the README, a `preferred-citation` to `CITATION.cff`, a `ScholarlyArticle`
  node plus `citation`/`sameAs` to the homepage structured data, and a citation block to
  `llms.txt`.
- **Per-page metadata.** Nine pages shipped with no `description:` front-matter and were
  falling back to the site-wide default; each now has its own title and description.
- `CITATION.cff` no longer claims version 1.4.1 or lists Rust as a language.

### Benchmarks are now public — and the latency claim is corrected

- **New [`docs/benchmarks.md`](docs/benchmarks.md)** publishes the measurements that
  previously existed only in the paper's working directory: WER on LibriSpeech test-clean
  across `tiny.en`/`base.en`/`small.en`, decode latency and memory, the VAD gate, command
  classification, and the Dysfluency-Friendly Mode gate — with the hardware, the method,
  and the commands to reproduce every number, plus an explicit list of what is *not*
  measured.
- **Corrected the README's "within about a second" claim.** Measured median decode is
  0.89 s (`tiny.en`), 1.56 s (`base.en`, the default) and 5.05 s (`small.en`) on a 13th-gen
  Core i7. The old wording overstated the default configuration and badly overstated
  `small.en`. The README and comparison page now cite the measured figures.

### Contributor experience — the documented gate now actually runs

- **`ruff` and `mypy` are now dev dependencies.** They were documented as the contributor
  gate in the README and `CONTRIBUTING.md` but were not installed, so a newcomer's first
  command failed with `Failed to spawn: ruff`.
- **Added a `[tool.ruff]` config** with a deliberately small, high-signal ruleset (pyflakes,
  the serious pycodestyle checks, import ordering) so the lint gate is green instead of a
  wall of style noise. Widening it is tracked as a good first issue. Applied the resulting
  safe fixes across the codebase; fixed an unresolved `GazeTargeter` forward reference and
  removed three dead local assignments.
- **The `Makefile` is Python again.** Every target still drove the archived Rust build, so
  `make test` ran `cargo test` in a Python project. It now has `check`, `test`, `test-cov`,
  `lint`, `lint-fix`, `types`, `docs`, `docs-serve`, daemon lifecycle, `build`, and `clean`.
- **Regenerated `docs/features.md`**, which was stale and failing the doc-sync test on a
  clean checkout.
- `mypy` is documented as **advisory** (135 pre-existing errors) rather than hidden behind a
  lenient config, and reducing that count one module at a time is now a good first issue.

### Documentation — lead with meeting capture and file transcription

- **The README now leads with all three capabilities** — hold-to-talk dictation, offline
  file transcription, and hands-free meeting capture. Meeting Mode previously appeared
  nowhere in the README or the comparison page. The archived Rust comparison table moved
  out of the above-the-fold position into the development section.
- **New [`docs/meeting-notes-offline.md`](docs/meeting-notes-offline.md)** — an honest
  comparison against Otter.ai, Fireflies, and the local-first tools, stating plainly that
  Meeting Mode records the room microphone rather than a video call's system audio, and
  that speaker labels and minutes are opt-in extras.
- `CONTRIBUTING.md` de-Rustified, with the blocking gates separated from the advisory one.

### Documentation site — modern MkDocs + Material

- **The documentation site is now built with [MkDocs + Material](https://squidfunk.github.io/mkdocs-material/)**,
  replacing the previous Jekyll (cayman) theme. It adds instant navigation, full-text search,
  a light/dark theme toggle, code-copy buttons, Mermaid diagram rendering, tabbed content,
  grid-card layouts, per-page "last updated" dates, and auto-generated Open Graph / Twitter
  social preview cards. A redesigned landing page leads with a hero, feature grid, and tabbed
  install instructions.
- **Page URLs are unchanged** (`use_directory_urls: false` keeps the `*.html` paths), so every
  already-indexed link and the existing `robots.txt` → `sitemap.xml` SEO wiring survive the
  cutover with no redirects. MkDocs now generates the sitemap automatically.
- The how-to guides, architecture overview, architecture diagrams, roadmap, and troubleshooting
  pages — previously kept out of the published site — are now **included in the public docs**.
- Build/serve via the new `docs` dependency group (`uv sync --group docs`; `uv run mkdocs serve`).
  A `Docs` GitHub Actions workflow builds the site with `--strict` and deploys it to GitHub Pages
  (Pages source must be switched to "GitHub Actions" once, in repo settings).

### Community & contributor experience

- Added a **contributor recognition wall** to the README (all-contributors table +
  `.all-contributorsrc`), crediting the four external contributors alongside the maintainer.
- Merged the community **"record your own demo GIF" guide** (`docs/demo-guide.md`), linked from
  the README documentation index — a first contribution from a new contributor (closes #5).

## [2.12.0] - 2026-07-31

First stable **v2** release — the on-device cognitive layer (Meeting Mode, diarized
recording import, gaze routing, learning corpus, and the tray/mic/target-guard
reliability work) graduates from the `2.x` pre-release line to a supported release.
`pip install yazses` now installs v2.

### "No text target" guard — never dictate into the wrong place

- **Speaking with no text field focused no longer loses your words.** If you dictate before
  clicking into a text box, YazSes now detects there's no text target and — instead of typing
  the transcript into the wrong window (or nowhere) — **copies it to the clipboard and notifies
  you** ("paste with Ctrl+V"), and the tray icon turns **yellow** while recording so you see it
  before you release. Detection is **AT-SPI** when available (precise editable-element check;
  `apt install python3-pyatspi gir1.2-atspi-2.0`), else a **best-effort X11** focus check;
  it only acts on a *confident* no-target, so normal dictation is never affected.
- Configurable via `[injection] target_guard` (`clipboard` default | `warn` | `off`) and the
  new `target-guard` feature (on by default). Tray icon is now **5 colours**: green (dictating
  into a field), yellow (dictating, no text target), purple (command mode — holding the command
  key), blue (idle), red (problem).
- New: `src/yazses/inject/target.py`, `src/yazses/system/clipboard.py`; wired in `core/daemon.py`.
  Tests: `test_target_detection.py`, `test_clipboard.py`, `test_target_guard_daemon.py` (+19).
  Also fixed a clipboard-set hang (xclip/wl-copy inherit stdout → `subprocess.run` blocked; now DEVNULL).

### System-tray icon with a click-menu (Linux top-bar indicator)

- **A microphone icon in the top bar** (`yazses tray`, and auto-launched with the daemon
  when a desktop is present) with a click-menu to **pick/pin your input mic** from a live
  device list, **re-calibrate**, and **restart/stop** the daemon — no terminal needed. The
  icon is the YazSes mark — a rounded badge with a bold "Y" — in a three-colour scheme:
  **green while recording** your voice (holding the key and speaking, through the brief
  transcribe/inject), **blue for the normal ready/idle** state, and **red for a problem**
  (error or a live silent-streak). So a glance says recording vs ready vs needs-attention.
  Built on
  **PySide6 `QSystemTrayIcon`** (already a base dependency — zero new deps; needs an
  SNI/AppIndicator host, standard on Ubuntu GNOME). macOS/Windows keep their existing
  rumps/pystray trays.
- Mic actions apply **live over IPC** (new `pin_mic` / `recalibrate_mic` daemon methods
  reusing the mic-guard internals) — pinning takes effect immediately, no restart. "Quit
  tray" closes the icon but leaves dictation running; a single-instance lock prevents a
  duplicate tray after `yazses restart`.
- New: `src/yazses/tray/{menu,controller,launch}.py` (pure, unit-tested),
  `src/yazses/platform/linux/tray.py` (`LinuxTray`), `[tray]` config, a `tray` feature
  (on by default), and the `yazses tray` command. Tests: `test_tray_menu.py`,
  `test_tray_controller.py`, `test_tray_launch.py`, `test_daemon_audio_ipc.py` (+21).

### Microphone-change guard — auto-heal + actionable notifications

- **Dictation no longer dies in silence when your mic switches.** Capture used to follow
  the OS default input device with no way to pin it, so plugging in a USB-C monitor (or a
  headset) that steals the default input made every clip fall below the VAD gate and get
  silently discarded — no crash, no message. YazSes now detects this two ways: a run of
  consecutive silent-discards (`SilentStreakTracker`) and a background watcher of the OS
  default input device (`DeviceMonitor`, polls only while idle). On either, it **auto-heals**
  — switching capture back to the last device that produced usable audio — and pops a
  desktop notification with **[Re-calibrate] / [Pin this mic] / [Ignore]** buttons
  (`notify-send`; degrades to a plain toast, then to log-only, never crashes the daemon).
- **Pin your microphone by name.** New `[audio] device` (a case-insensitive name
  substring, resolved fresh every recording so it survives a hotplug that renumbers
  devices) threads through `AudioRecorder` and `yazses mic-level`. Set/see it with the new
  **`yazses audio devices` / `use <name>` / `status`** command group; the current mic is
  now shown in `yazses status` and `yazses doctor`.
- New `[audio]` keys (`device`, `device_change_notify`, `silent_streak_notify`,
  `silent_streak_threshold`, `auto_heal_device`, `device_poll_interval_s`), all on by
  default; toggle both notifies with `yazses features enable/disable mic-guard`.
- New: `src/yazses/audio/devices.py`, `src/yazses/audio/device_monitor.py`,
  `src/yazses/system/notify.py`; wired in `core/daemon.py`. Tests: `test_audio_devices.py`,
  `test_device_monitor.py`, `test_notify.py`, `test_recorder_device.py`,
  `test_cli_audio.py`, `test_device_heal_daemon.py` (+36).

## [2.12.0-dev.4] - 2026-07-30

### Schema slot-filling exposed as an offline CLI command

- **`yazses slotfill <text> --slot ...`** (ADR-v2-063) — extract structured fields from
  one utterance by a schema: each `--slot` is `NAME:after=kw1,kw2` (capture the token
  after a trigger keyword) or `NAME:choices=a,b,c` (pick the first enum member present).
  Prints a JSON object of matched fields. `src/yazses/cli.py`; tests
  `tests/test_cli_slotfill.py` (+4).

### Verbatim / autoformat mode wired into the dictation path

- **Verbatim mode** (ADR-v2-078, `[verbatim]`) is now live: say **"dictate verbatim"**
  (or "raw mode"/"stop formatting") to freeze all formatting — ITN, voice punctuation,
  GEC, transliteration, markup, auto-pairing, prosody, etc. — for subsequent bursts, and
  **"resume formatting"** (or "normal mode") to restore it. The mode commands type nothing;
  a persistent `VerbatimGate` holds the mode across bursts. Off by default
  (`yazses features enable verbatim`). Wired in `core/daemon.py::_on_hold_end` (bypasses
  the transform chain, injecting the cleaned literal text); tests in
  `tests/test_v2_daemon_wiring.py` (+3).

### Reverse dictionary + citation resolver exposed as offline CLI commands

- **`yazses wordfind <description>`** (ADR-v2-118) — a reverse dictionary: describe a
  word and get ranked candidates from a built-in demo lexicon (extend with `--lexicon`,
  a JSON `{word: definition}` file).
- **`yazses cite <query> --bib <file>`** (ADR-v2-071) — resolve a spoken "author year"
  reference against a local BibTeX file and format it (`--style latex|plain|apa`).

Both exit non-zero when nothing matches. `src/yazses/cli.py`; tests
`tests/test_cli_wordfind_cite.py` (+7).

### Spaced-repetition capture — fifth stateful core given a persistent store

- **`yazses srs capture/list/review`** (ADR-v2-112) — capture "remember that X is Y"
  facts as cloze flashcards persisted at `~/.config/yazses/srscap.json`, and schedule
  reviews with the SM-2 algorithm (`review <n> --grade 0-5`). Reuses the `Sm2State` /
  `sm2_schedule` cores. New `src/yazses/srscap/store.py` + `src/yazses/cli.py`; tests
  `tests/test_srscap_store.py`, `tests/test_cli_srs.py` (+9).

### Outline builder — fourth stateful core given a persistent store

- **`yazses outline add/indent/promote/render/clear`** (ADR-v2-124) — build a nested
  outline incrementally across invocations (state at `~/.config/yazses/outline.json`)
  and render it to Markdown or OPML. New `src/yazses/outline/store.py` (OutlineItem
  (de)serialisation) + `src/yazses/cli.py`; tests `tests/test_outline_store.py`,
  `tests/test_cli_outline.py` (+7).

### Clipboard history — third stateful core given a persistent store

- **`yazses cliphistory add/list/recall`** (ADR-v2-060) — a newest-first, de-duplicated,
  capped clipboard history persisted at `~/.config/yazses/cliphistory.json`. `recall`
  resolves a spoken-style reference (`the last url`, `email`, `the second one`,
  `number 3`, …) to one entry. Reuses the `ClipboardRing` core for dedup/cap semantics.
  New `src/yazses/cliphistory/store.py` + `src/yazses/cli.py`; tests
  `tests/test_cliphistory_store.py`, `tests/test_cli_cliphistory.py` (+9).

### Writing-goal tracker — second stateful core given a persistent store

- **`yazses wordgoal add/status/goal/reset`** (ADR-v2-092) — a running word count
  persisted at `~/.config/yazses/wordgoal.json` that accumulates across invocations;
  `add` counts a chunk (arg or stdin), `goal <n>` sets a target, `status` reports
  progress, `reset` zeroes the count. `WordGoalTracker.progress()` was refactored to a
  shared pure `render_progress()` reused by the CLI. New `src/yazses/wordgoal/store.py` +
  `src/yazses/cli.py`; tests `tests/test_wordgoal_store.py`, `tests/test_cli_wordgoal.py` (+8).

### Acronym glossary — first stateful dormant core given a persistent store

- **`yazses acronyms add/list/remove/expand`** (ADR-v2-114) — a persistent acronym
  glossary stored at `~/.config/yazses/acronyms.json`. `expand` rewrites text so each
  known acronym is spelled out on first use (`Full Name (ACR)`) and contracted after.
  This is the first of the "stateful" dormant cores to get a runtime path — via a small
  JSON file store (mirroring the personal-dictionary pattern) rather than a daemon session.
  New `src/yazses/acronyms/store.py` + `expand_document()` in `acronyms/glossary.py` +
  `src/yazses/cli.py`; tests `tests/test_acronyms_store.py`, `tests/test_cli_acronyms.py` (+9).

### Two more dormant cores exposed as offline CLI commands

- **`yazses findreplace <command> --in <text>`** — apply a spoken find-and-replace
  (`replace every/first X with Y`, optionally `case-sensitive`) to text (ADR-v2-068).
- **`yazses chords [text]`** — turn a spoken key chord (`press control shift P`,
  `escape twice`) into injectable `ctrl+shift+p`-style combos, one per line (ADR-v2-085).

Both read the argument or stdin and exit non-zero on an unparseable input. `src/yazses/cli.py`;
tests `tests/test_cli_findreplace_chords.py` (+7).

### Two dormant text cores exposed as offline CLI commands

Continuing the "wire dormant feature cores into a runtime path" effort, two more pure,
tested cores now have a real entry point (offline, no daemon):

- **`yazses case [text] --style <name>`** — recase text to a naming convention
  (snake/kebab/camel/pascal/title/sentence/upper/lower/constant, ADR-v2-087). With no
  `--style` it detects a spoken `make this … case:` command and recases the remainder.
- **`yazses screenplay [text]`** — format dictated lines as Fountain screenplay markup
  (ADR-v2-110): scene headings, character cues, transitions, and smart-quoted dialogue.

Both read the argument or stdin. `src/yazses/cli.py`; tests
`tests/test_cli_case_screenplay.py` (+9).

### Meeting Mode hardening (P2–P5)

Robustness and completeness pass over Meeting Mode (`yazses meeting`, ADR-v2-127/128),
all on-device and off by default:

- **Clean auto-stop at `max_minutes`.** The recorder no longer silently drops audio once
  the safety cap is reached — the controller now owns the cap and, when captured audio
  reaches it, fires a one-shot finalize (the same path as `yazses meeting stop`), so the
  meeting up to the cap is transcribed and written instead of quietly discarded.
- **Crash-resilient live transcript.** Each finalized live line is streamed to
  `<meeting>/live.jsonl` during capture, so a daemon crash mid-meeting still leaves a
  partial transcript on disk; `yazses meeting list` flags such folders as recoverable.
  This stays separate from the authoritative `transcript.json` (the batch post-pass at stop).
- **No silent diarization degrade.** `yazses meeting start` now warns when speaker labels
  are requested but the diarization extra/models are missing (the transcript would be
  un-attributed), and `yazses meeting status` reports speaker-label availability. Fetch the
  models with `yazses transcribe --download-models`.
- **Grammar-constrained minutes.** Local-LLM minutes (`[meeting] notes`) can decode against
  a GBNF grammar (`[meeting] notes_grammar`, default on) so the JSON shape is guaranteed,
  with the tolerant parser kept as a fallback. New `notes` optional extra (llama-cpp-python);
  recommended GGUF: Phi-4-mini-instruct or Qwen2.5-3B (Q4_K_M).
- **Selectable VAD backend.** `[meeting] vad_backend` is now honoured via a factory that
  builds the calibrated RMS gate by default or a Silero neural VAD (new optional `silero`
  extra) when selected, falling back to calibrated whenever Silero is unavailable.
- **Participant enrollment.** New `yazses meeting enroll <id> --speaker <cluster> --name
  <name>` embeds a speaker's audio from a retained recording and saves it as an encrypted,
  on-device voiceprint (explicit/opt-in, ADR-011/012), so that person is auto-named in
  future meetings. Requires `[meeting] retain_audio = true`.
- `yazses features enable meeting` (and `recimport`) now auto-install their diarization
  backend on demand. `src/yazses/meeting/{controller,session,store,notes,vad,silero_vad,
  participants}.py`, `src/yazses/recimport/factory.py`, `src/yazses/core/daemon.py`,
  `src/yazses/cli.py`, `src/yazses/config.py`. Tests: `tests/test_meeting_*`, +23.

### Hotkey fix: dead hold-to-talk with more than one keyboard

- **fix(hotkey): listen on every real keyboard, not just one.** On a machine
  with more than one keyboard (a laptop's built-in keyboard plus an external
  USB keyboard, which each appear as separate `/dev/input/event*` nodes), the
  daemon bound to a single device chosen by sorted path — so it could lock onto
  the keyboard you *weren't* typing on and the hold-to-talk hotkey did nothing
  (recording never even started; no text appeared). `EvdevHoldListener` now
  discovers all real full keyboards (`_find_keyboards`) and reads them together
  via `select()`, so the hotkey fires whichever keyboard you use — built-in,
  USB, or both at once. Virtual injector devices (ydotool/wtype uinput) are
  still excluded so they can't shadow a real keyboard. `yazses doctor` now lists
  every watched keyboard so a mismatch is visible at a glance.
  `src/yazses/hotkeys/evdev_hold.py`, `src/yazses/system/doctor.py`. Tests:
  `tests/test_evdev_find_keyboard.py`, `tests/test_doctor_install_diag.py`.

## [2.12.0-dev.3] - 2026-07-10

### Glance-Type routing fix, on-demand gaze deps, features-enable crash fix

- **docs(gaze): new how-to guide for Glance-Type look-to-pane.**
  `docs/how-to/gaze-look-to-pane.md` — what it is, requirements (X11 + webcam +
  xdotool), setup (enable → auto-install → calibrate → start), how to use it, a
  concrete two-window test with live-log verification, and troubleshooting
  (camera conflict, always-same-window, Wayland). Linked from the how-to index
  and a new gaze section in `troubleshooting.md`.
- **fix(gaze): look-to-pane always routed to the desktop, never the looked-at
  window.** `XdotoolDesktop.list_windows` returned the full-screen desktop/root
  window (spanning `0,0`→screen size) alongside real windows, and
  `zones.window_at_point` returned the *first* bbox match — so the desktop, which
  contains every point, shadowed every real window and gaze always resolved to it
  (focusing the desktop is a no-op, so dictation stayed on the focused window
  regardless of gaze). Fixed on two fronts: `list_windows` now drops any
  window covering ≥98% of the screen at the origin (the desktop/root — never a
  meaningful gaze target), and `window_at_point` now returns the *smallest*
  (most specific) containing window so a real pane always wins over a larger
  container behind it. Tests: `tests/test_gaze.py`, `tests/test_gaze_wiring.py`.
- **feat(gaze): `yazses gaze calibrate` now auto-installs the webcam deps.** Running
  `gaze calibrate` (or `gaze status`) with mediapipe/opencv absent used to dead-end on
  a manual `pip install l2cs mediapipe opencv-python` hint — misleading, since l2cs is
  not the default backend and a `pip install` can't reach the uv-tool venv. Calibrate
  now installs the deps into the running environment on first run (reusing the same
  `_install_feature_deps` path as `features enable gaze`; `--no-install` to skip), and
  the hints across `calibrate`/`status`/docs point at the turnkey commands. Tests:
  `tests/test_cli_gaze_autoinstall.py`.
- **fix(features): `yazses features enable <name>` crashed for any feature with
  optional deps.** The on-demand-deps fields (`pip_packages` / `check_modules`)
  lived only on the internal `_Def` and were dropped when building the public
  `Feature` the CLI consumes, so `_install_feature_deps` raised
  `AttributeError: 'Feature' object has no attribute 'pip_packages'`. They now
  survive the conversion; added a regression test for the CLI contract.

## [2.12.0-dev.2] - 2026-07-10

### Meeting Mode, Glance-Type on X11, Read-Back fix, feature-dependency doctor

- **feat(meeting): hands-free whole-meeting capture + hybrid diarization (ADR-v2-127/128).**
  New `yazses meeting` command group (`start`, `stop`, `status`, `list`, `relabel`,
  `notes`): records a full meeting without hold-to-talk, streams a rolling transcript
  for the status view, and at *stop* runs an accurate batch diarization post-pass over
  the whole recording — reusing the ADR-v2-125 `recimport` cores (no new dependency) —
  then optionally generates speaker-aware minutes with a local LLM. Speakers are
  identified by embeddings + clustering (not pitch). New `src/yazses/meeting/`
  (`store`/`segmenter`/`session`/`finalize`/`notes`/`controller`), `MeetingConfig`
  (OFF by default, RecimportConfig-compatible diarization/naming fields), and
  `design/meeting-mode/` + ADRs 127/128. Tests: `tests/test_meeting_*.py`.
- **feat(gaze): Glance-Type look-to-pane now fully wired and tested on X11.** New default
  backend is MediaPipe FaceLandmarker (iris-offset → gaze; light, no torch,
  auto-downloads the 3.7 MB model) — glance at a coarse screen zone to choose where the
  next dictation lands; `xdotool` focuses the target window. Adds
  `gaze/{desktop,store,targeter,mediapipe_backend,download}.py`, real `yazses gaze
  calibrate` / `gaze status`, daemon `_on_hold_start` routing, and a `gaze` pip extra.
  l2cs stays opt-in (heavy CUDA). Still dormant on GNOME/Wayland (no external
  window-focus). Frames are processed in-RAM only, never stored or sent (ADR-011).
  Tests: `tests/test_gaze_{mediapipe,l2cs,wiring}.py`.
- **fix(tts): Read-Back was silently a no-op.** The code called the old `Kokoro()`
  constructor, but `kokoro-onnx >= 0.4` requires `Kokoro(model, voices)`, so the backend
  resolved to `None`. New `tts/download.py` fetches the v1.0 ONNX model + voices into
  `~/.local/share/yazses/tts`; `TtsConfig.voices_path` and `kokoro.py` now auto-resolve
  and download. No `espeak-ng` needed.
- **feat(features): on-demand dependency install on `features enable`.** Enabling a
  heavy feature now installs *only that feature's* optional extras (never all of them
  up front). New `system/deps.py` (`missing_modules` + `install_packages`, preferring
  `uv pip` and falling back to `pip`, targeting the running interpreter) plus a central
  `_FEATURE_DEPS` map wire 12 heavy features (gaze, overlay, prosody, voicehealth,
  read-back, readback_clone, llm-cleanup, agent, cocktail, multiprofile, voiceguard,
  diarize) to their pip packages. `yazses features enable <name>` probes the feature's
  imports and installs what is missing (`--no-install` to skip); pure-logic features
  install nothing. Tests: `tests/test_feature_deps.py`.
- **fix(docs-gen): Typer 0.26 compatibility.** Typer now vendors its own `click` fork, so
  `scripts/gen-docs.py`'s `isinstance` checks against upstream `click` broke the
  command-index generator (and its sync test). Switched to duck-typing on the stable
  `param_type_name` / `.commands` API.
- **chore(deps): refresh every dependency to its latest compatible stable.** Audited all
  32 declared packages and ran `uv lock --upgrade`, bumping the lagging lower bounds to
  the resolved versions — notably `PySide6` 6.8→6.11.1, `opencv-python` 4.10→5.0,
  `cryptography` 48→49, `typer` 0.25→0.26.8, `mcp` 1.9→1.28.1, `onnxruntime` 1.20→1.27,
  `kokoro-onnx` 0.4.9→0.5.0, plus numpy, platformdirs, Pillow, pywin32, pyobjc, soundfile,
  sherpa-onnx, mediapipe, llama-cpp-python, praat-parselmouth and pytest. Floors track the
  resolver's latest *compatible* pick (numpy is capped at 2.4.6 by a transitive
  constraint), so resolution stays clean across platforms.

## [2.12.0-dev.1] - 2026-07-10

### CLI help + docs: grouped feature switchboard, branded banner, full reference set + master PDF

- **feat(cli): `yazses features` now clusters all 135 capabilities into functional
  groups** (Core dictation, Accuracy & correction, Formatting & structure, Editing
  & navigation, Commands & automation, Multilingual, Accessibility & input
  modalities, Learning/memory & analytics, Conversation & recording capture)
  instead of one flat 135-row table, and gains `--on`, `--tier <core|on|rec|opt|exp>`,
  and `--category <name>` filters. New `category` field on `Feature` + a slug→category
  map in `system/features.py` (single source of truth, enforced complete by tests);
  new `grouped_features()` helper. Tests: `tests/test_features_categories.py`,
  `tests/test_cli_features_grouped.py`.
- **feat(cli): `yazses about` shows a branded ASCII wordmark banner** (`branding.banner()`)
  with a plain-text fallback on non-TTY / `NO_COLOR`, and `about` gained a usage
  example. Tests: `tests/test_about_branding.py`.
- **fix(features): accuracy pass** — corrected the `rag` example (answers from local
  docs, not "recall past dictation"), moved `affect` (Tone-Aware Formatting) from the
  Learning category to Formatting, and noted the optional extra/model dependency on
  `readback_clone` and the learning-corpus dependency on `recall`.
- **docs: a complete, non-drifting reference set.** New generator
  `scripts/gen-docs.py` emits `docs/features.md` (all 135, grouped), `docs/configuration.md`
  (every `config.toml` section/key/default from `config.py`), and `docs/command-index.md`
  (every CLI command/option from the Typer app) directly from source — kept in
  lockstep by `tests/test_gen_docs.py`. New hand-written `docs/architecture.md`
  (user-facing), `docs/roadmap.md`, `docs/troubleshooting.md`, and `docs/how-to/`
  guides (vocabulary, macros/snippets, hotkey, remote, performance tuning); refreshed
  `docs/cli-reference.md` and `docs/index.md`.
- **docs: subsystem architecture diagram in three formats.** `docs/diagrams/`
  ships the same YazSes subsystem map as Mermaid (`.mmd`, renders on GitHub), ASCII
  (`.txt`, also embedded in `docs/architecture.md` and the PDF), and a self-contained
  styled `.html` page — covering the CLI/tray control plane, the daemon pipeline,
  injection/remote paths, and the cross-cutting config, registry, platform, and
  opt-in subsystems.
- **docs: one master PDF.** `scripts/build-docs-pdf.sh` assembles the whole doc set
  into `docs/yazses-complete-reference.pdf` — a ~130-page, table-of-contents
  reference — via pandoc (`pypandoc-binary`) + xelatex, all user-space (no system
  install). Gitignored; regenerate on demand.
- **fix(docs): correct the privacy statement — it described a never-shipped Rust
  build.** `docs/privacy-statement.md` claimed a "Personal Memory" SQLCipher
  `memory.db`, an OpenAI-compatible cloud LLM backend, `llama.cpp`/Ollama at
  `localhost:11434`, "Moonshine v2 / Whisper.cpp" STT, and that remote mode
  "forwards your audio" — none of which match the real Python implementation.
  Rewritten to reflect reality: faster-whisper STT, the opt-in AES-256-GCM
  `[learning]` corpus (`corpus.db`), on-device-only optional local models
  (`llama-cpp-python`, no cloud/OpenAI), and remote mode forwarding **final text
  only** (audio never leaves the machine).
- **fix(docs/pdf): the reference PDF no longer double-numbers headings, overflows
  wide tables, or leaks a literal `\newpage`.** Dropped pandoc `--number-sections`
  (source docs carry their own manual section numbers/cross-refs that collided as
  "19.14 13. …"); added `scripts/pandoc-tablewrap.lua` so wide table cells wrap
  instead of running off the page; page breaks now come from `report`-class chapter
  starts. The fictional `docs/migration-v04-to-v10.md` (Rust "v1.0") is excluded
  from the PDF.

### Docs: stop recommending the snap for dictation (confinement blocks the hotkey)

- **docs: lead Linux installs with the APT script / `pipx`, not the snap.** The
  strictly-confined snap cannot read `/dev/input`, so hold-to-talk never fires —
  only the offline `yazses transcribe <file>` path works under confinement.
  README and `docs/index.md` now install via APT/pipx, carry an explicit
  "Not the snap" note, and drop the Snap Store badge/button; the snap-specific
  `snap connect yazses:audio-record` step was removed from the `yazses setup`
  checklist copy (README, `docs/install-linux.md`, `docs/cli-reference.md`).
  The snap remains only as a clearly-labelled, not-recommended option for the
  file-transcription use case. (Snap packaging itself to be updated separately.)

### Install: `yazses setup` prompts every manual step + offers voice calibration

- **feat(setup): an ordered "finish installing" checklist.** After provisioning,
  `yazses setup` prints the numbered steps only the user can do — grant the snap
  microphone (`sudo snap connect yazses:audio-record`), join the `input` group
  (`sudo usermod -aG input $USER`), log out and back in so it takes effect,
  calibrate the mic to your voice (`yazses mic-level --set`), and start dictating
  (`yazses start`). Steps that don't apply are omitted; shown on the apply,
  `--dry-run`, and already-provisioned paths. Single source of truth: new
  `system/setup.py::next_steps()` (+ `ManualStep`). Also offers to run the mic
  calibration for you, and the APT installer now points at those next steps.
  Tests: `tests/test_setup_next_steps.py`.

### UX: friendlier, clearer, more helpful CLI

- **feat(cli): new `yazses quickstart` — a 3-step, machine-tailored getting-started
  guide.** It checks what's already set up (prerequisites, whether the daemon is
  running, your hotkey) and prints exactly what to do next (`setup` → `start` → hold
  the key), plus handy follow-ups (`test`, `mic-level`, `features`, `doctor`). Safe to
  run anytime — changes nothing. Surfaced first in the Setup panel and top-level help.
- **feat(doctor): a bottom-line verdict.** After the check list, `yazses doctor` now
  prints one summary line — ✓ all good / ▲ optional warnings only / ✗ N problems to fix
  — each ending in the concrete next command (and "hold <hotkey> to dictate" when ready).
- **fix(cli): actionable, consistent 'not running' messages.** `yazses status` and
  `yazses stop` used to dead-end at "YazSes is not running."; they now tell you the
  next command (`yazses start`, and `quickstart` for new users). The status
  IPC-not-ready line now explains the daemon is loading the speech model rather than
  looking broken.
- **fix(help): stop leaking internal jargon into user help.** Removed developer
  codenames (`ADR-v2-038/091/082/117`, `spec-punch-in`, `ADR-011`) from the `reflow`,
  `table`, `shellpipe`, `braille`, `punch-in`, and `transcribe` command descriptions,
  and rewrote the `say`, `enroll-voice`, `gaze`, and `recall` help to lead with a
  plain description instead of internal feature codenames (Read-Back Loop, Cocktail
  Filter, Voiceprint Mind, Glance-Type, Spoken Recall).
- Tests: `tests/test_cli_quickstart.py`, `tests/test_doctor_verdict.py`.

### UX: make the required setup commands unmissable (colour)

- **`yazses doctor`, `yazses start`/`restart`, and `yazses setup` now colour their
  output.** Failures render as bold white-on-red `[FAIL]` tags, and the one action a
  user must take — e.g. `sudo usermod -aG input $USER` (the hotkey won't work without
  it) or `sudo snap connect yazses:audio-record` — is highlighted in bold red so it
  can't be missed. Colour is emitted only to a real terminal (auto-disabled when
  piped/redirected, honours `NO_COLOR`). New `doctor._format_check` + `cli._echo_action_hint`.

### `start`/`restart` verify the daemon actually came up + bounded self-healing (`v2.11.0-dev.13`)

- **feat(cli): `yazses start`/`restart` no longer lie about readiness.** They used
  to print "YazSes started" the instant the process was spawned — even when the
  daemon core-dumped a moment later during model/audio init (e.g. a PortAudio/ALSA
  abort). Now they poll the daemon over IPC after spawning and report the truth:
  - **ready** → "YazSes started. Hold <key> to dictate."
  - **still loading** → an informative note that the speech model is loading
    (first run can take 10–30s) and to check `yazses status` — not treated as a
    failure.
  - **crashed on startup** → an error with the daemon's `last_error`, a pointer to
    `yazses doctor` / `yazses logs`, and a **non-zero exit code**. Detection is
    robust: the daemon writes its PID before loading the model, so a startup crash
    shows up as the PID appearing and then vanishing.
- **feat(cli): a fresh `yazses start` now routes through systemd when a user unit
  is installed**, instead of spawning an unsupervised detached process — so the
  daemon is supervised and self-heals (`Restart=on-failure`) even when started by
  hand. (The already-running case already restarted cleanly with no duplicate.)
- **fix(systemd): bound the crash-loop.** `contrib/yazses.service` and the
  `install-pipx.sh` unit gained `StartLimitIntervalSec=60` / `StartLimitBurst=5`,
  so a persistently-broken daemon (bad config, missing audio stack) stops retrying
  after 5 failures/min rather than restarting forever.
- Status IPC now also reports `ready`. Tests: `tests/test_cli_start_restart.py`.

### Installation now shows every capability

- **feat(install): the install phase prints the full capability list.** After a
  successful install, `install-local.sh`, `install-pipx.sh`, `install-apt.sh`, and
  `yazses setup` now show every YazSes capability (● on / ○ off) with its toggle
  name and advice, so a new user immediately sees what the tool can do and how to
  enable more — instead of just "installed". The `.deb` postinstall (runs as root)
  points to `yazses features` / `yazses features info`. Rendering is shared in-process
  via the new `cli._echo_capabilities()` helper (single source of truth with
  `yazses features`; needs no running daemon).

### Author & contact surfaced in the app — `yazses about` (`v2.11.0-dev.12`)

- **feat(cli): `yazses about` prints author, version, links, and where to report
  issues or request features.** The running app now names its author
  (Mohsen Seyedkazemi Ardebili <mohsen.seyedkazemi@gmail.com>) and points people
  at the project website, source, and Issues tracker. The top-level `--help`
  epilog gained a **Help & contact** section, and `yazses doctor` prints a contact
  footer so anyone who hits a problem knows exactly where to report it or ask for a
  feature. Single source of truth: new `src/yazses/branding.py`, kept in step with
  `pyproject.toml` and `snap/snapcraft.yaml`.

### Snap: fix broken keystroke injection — bundle libxdo3 + clipboard tools (`v2.11.0-dev.11`)

- **fix(snap): dictation is now actually typed.** The snap bundled the `xdotool`
  binary but not the shared library it loads (`libxdo.so.3`, from `libxdo3`), plus
  the injector's other X11 client libs (`libXinerama`, `libXtst`, `libXmu`, …). Every
  `xdotool type` therefore exited 127 ("error while loading shared libraries"), so
  transcription succeeded but nothing reached the focused window — and the failure
  cascaded into a clipboard fallback that also failed because `xclip` wasn't bundled.
  `stage-packages` now includes `libxdo3`, `xclip`, and `wl-clipboard`; a real
  snapcraft build pulls the full library closure automatically.
- **fix(doctor): the Injection check now runs xdotool, not just finds it.** `yazses
  doctor` previously printed `[OK] Injection: xdotool (X11)` whenever the binary was
  on `PATH`, hiding exactly this loader failure. It now invokes `xdotool
  getdisplaygeometry` and reports `FAIL` (with the `libxdo.so.3` hint) when the binary
  is present but can't run. New `system/doctor.py::_binary_runs`.
- **fix(snap): the voice-activity overlay (sonar) now appears.** The Qt `xcb`
  platform plugin failed to initialise ("Could not load the Qt platform plugin
  xcb") because `libxcb-xkb1` + `libxkbcommon-x11-0` (and `libxcb-cursor0`) weren't
  in the bundle, so `yazses-overlay` crashed on launch and no rings showed. Added
  them to `stage-packages`.

### Snap: prompt for the one-time microphone permission (`v2.11.0-dev.10`)

- **feat(snap): the setup/startup flow now asks you to grant the microphone.** A
  strictly-confined snap can't self-connect interfaces, and snapd does not auto-connect
  `audio-record`, so a fresh `snap install yazses` has no mic until the interface is
  connected once. Instead of dictation silently capturing nothing, `yazses setup`,
  `yazses start`/`restart` (via the preflight hints), and `yazses doctor`'s Microphone
  check now detect the un-connected interface (`snapctl is-connected audio-record`) and
  print the exact one-liner to run: `sudo snap connect yazses:audio-record`. Non-snap
  installs (apt/pipx) are unaffected — they grant mic access directly. New
  `system/setup.py::snap_mic_pending`.

### Snap: fix the audio crash + recommended features on by default (`v2.11.0-dev.9`)

- **fix(snap): the snap no longer core-dumps on start.** A strictly-confined snap can't
  see the host's `/usr/share/alsa` config tree, so libasound had no configuration and
  `PortAudio`'s `Pa_Initialize()` aborted (`BuildDeviceList: Assertion 'devIdx < numDeviceNames'
  failed`) the moment `sounddevice` was imported — taking down `yazses doctor` and the daemon
  with a silent `SIGABRT`, while `--version`/`--help` still worked. The recipe now stages
  `libasound2-data` + `libasound2-plugins` and ships `snap/local/asound.conf` (referenced by
  `ALSA_CONFIG_PATH`) that routes the default device through PulseAudio — reached via the
  existing `audio-playback`/`audio-record` interfaces. Validated against the live snap: with a
  config present `Pa_Initialize()` returns cleanly instead of aborting. The rebuild also pulls
  the pending python3.12 security update (USN-8509-1).
- **feat: recommended features are enabled on a fresh install.** New `system/firstrun.py`
  (`ensure_recommended_config`) seeds `config.toml` on first daemon start, enabling the
  DEFAULT_ON + RECOMMENDED tiers (overlay, voice commands, mid-thought undo, dysfluency-friendly,
  and the rest) — derived from the capability registry so it stays in sync. Dataclass defaults
  stay dormant (the "loads with no config = dormant" contract and library use are unchanged),
  and an existing config is never overwritten, so a user's own `yazses features disable` choices
  are always respected. The overlay was already on by default; it simply never appeared because
  the daemon crashed before it could launch.

### Install: self-provisioning installers + a startup prereq warning (`v2.11.0-dev.8`)

- **feat(setup): `yazses start`/`restart` now warn about unmet runtime prerequisites** instead of
  starting a daemon that silently can't hear the hotkey. New `system/setup.preflight_hints()` surfaces
  two cases: (a) missing packages / `input`-group membership → points to `yazses setup`; (b) the classic
  post-`usermod` trap — you *are* in the `input` group per `/etc/group` but the current login session
  predates the change, so the hotkey can't read the keyboard until you log out and back in. New
  `system/setup.input_group_pending_relogin()` detects that by comparing the `input` gid against
  `os.getgroups()`. The re-login hint also gives the one-session bridge: `sg input -c "yazses restart"`.
- **feat(install): every installer now provisions the full system stack via `yazses setup`.**
  `install-pipx.sh` and `scripts/install-local.sh` call `yazses setup` (single source of truth for
  PortAudio + injector binaries + the `input` group + ydotoold) rather than a partial hand-rolled apt
  list, and print the re-login note when a group change is pending. New `scripts/dev-install.sh` does
  the whole from-source loop in one command: editable `uv tool` install → `yazses setup` → start (via
  `sg input` when the group isn't live yet, so you can test before logging out).
- **docs(readme):** Step 2 now spells out that the log-out/in is mandatory and one-time (a new terminal
  tab is not enough) and documents the `sg input` bridge; added a from-source `bash scripts/dev-install.sh`
  line. Regression tests in `tests/test_setup.py`. **1524 tests green.**

### Fix: release the hold-to-talk key on EVERY hold-end, not just on injection (`v2.11.0-dev.7`)

- **fix(daemon): `_on_hold_end` now synth-releases the hotkey key up-front, before transcription.**
  The `dev.6` flood guard only released `right_alt` when text was *injected* — so a **silent/discarded**
  dictation (very common when the VAD threshold is set too high) left `right_alt` stuck, and the stuck
  Alt kept re-appearing as the Alt+Space window menu / screenshots. yazses reads the physical input
  device, so it reliably knows the hold ended; it now sends a synthetic key-up (via ydotool, Linux-only,
  best-effort) at the *start* of every hold-end — dictation or discard — forcing mutter's view to match.
  Also releases the dedicated command key when configured. New `Daemon._release_hotkey_modifier()` /
  `_hotkey_release_codes()`; regression tests in `tests/test_v2_daemon_wiring.py`. **1520 tests green.**

### Fix: stuck `right_alt` after dictation → Alt+Space window menu / screenshots (`v2.11.0-dev.6`)

- **fix(inject): the ydotool flood guard now also releases the right-side modifier keycodes**
  (right_ctrl=97, right_alt=100, left_meta=125, right_meta=126). Previously it released only
  keycodes 2–57, which covers left_alt/left_ctrl/both shifts but **not `right_alt`** — the default
  hold-to-talk hotkey. On GNOME Wayland, when mutter intermittently drops the hotkey's key-up, Alt
  stayed logically held: the next Space became Alt+Space (opening the window menu, whose first item
  is "Take Screenshot") and typed letters were mangled through the AltGr layer. Injection only runs
  after hold-end, so releasing these is a safe no-op when the key isn't down. Regression test in
  `tests/test_auto_inject.py`. **1517 tests green.**

### Per-feature "use case" in help (`v2.11.0-dev.5`)

- **feat(features): every capability now shows a "Use when:" line.** `yazses features info <name>`
  (and the full `yazses features info` catalog) now prints, for each of the **135** capabilities, a
  one-line scenario describing *when you'd reach for it* — distinct from the existing description
  (what it does) and example (how to trigger it). Backed by a new slug-keyed `_USE_CASES` map in
  `system/features.py`, mirroring `_EXAMPLES`, and enforced complete by `tests/test_features_examples.py`
  (a missing/thin use-case now fails CI).
- **docs(cli): "Use it when:" added to the offline text-tool commands' `-h`** — `reflow`, `table`,
  `shellpipe`, `braille` each open with a plain-language "use it when …" scenario.
- **1516 tests green** (+2 completeness guards).

### Wire dormant feature cores — batch 2: offline text-tool CLI commands (`v2.11.0-dev.4`)

Continues connecting built-but-unwired feature cores to a runtime path. This batch exposes four
pure-text cores as real, offline `yazses` subcommands (each reads an argument or stdin):

- **feat(cli): `yazses reflow`** (ADR-v2-038) — reflow a monologue into a bulleted outline; action
  phrases ("I need to", "to do") become `- [ ]` checkboxes.
- **feat(cli): `yazses table`** (ADR-v2-091) — turn spoken rows ("row: a, b next row c, d") into
  delimited CSV lines; `--sep` sets the separator.
- **feat(cli): `yazses shellpipe`** (ADR-v2-082) — render a spoken pipeline ("list files then count
  lines") into a shell command; **printed, never executed**.
- **feat(cli): `yazses braille`** (ADR-v2-117) — translate text to Unicode Braille (UEB subset);
  `--grade 1` for uncontracted.
- **test:** `tests/test_cli_reflow_table.py` (11 cases) drives each command via `CliRunner`. **1514
  tests green.** Deferred with reasons: `diagramvox` (core parses only one edge), `gitvoice` (parser
  phrasing), and the stateful cores (outline/wordgoal/cliphistory/srscap/…) that need session state.

### Wire dormant feature cores into the live pipeline — batch 1 (`v2.11.0-dev.3`)

Many v2 feature cores were built + tested + registered but **not connected to any runtime path**, so
enabling them did nothing. This begins closing that gap, one feature at a time, each with a daemon
wiring test. All remain **OFF by default** (existing behaviour unchanged; full suite still green).

- **feat(daemon): 9 DICTATE-path text transforms are now live when enabled** — wired into the
  `_on_hold_end` post-process chain following the proven guarded pattern (ITN/redaction/symbols/…):
  - **Grammar Repair** (ADR-v2-050, `[gec]`) — "a apple" → "an apple".
  - **Diacritize** (ADR-v2-122, `[diacritize]`) — "a cafe cliche" → "a café cliché".
  - **Semantic Line Breaks** (ADR-v2-111, `[sembr]`) — one clause per source line.
  - **SafeGlyph** (ADR-v2-123, `[safeglyph]`) — warns on confusable homoglyphs (non-destructive).
  - **Inline Compute** (ADR-v2-086, `[compute]`) — "what's 15% of 240" → "36" (self-gating).
  - **Auto-Pairing** (ADR-v2-088, `[autopair]`) — "(a plus b" → "(a plus b)".
  - **Phonetic Corrector** (ADR-v2-027, `[phonetic]`) — fixes mis-heard names against your personal
    dictionary ("kubernetis" → "Kubernetes").
  - **Transliteration** (ADR-v2-116, `[translit]`) — romanized → native script (e.g. finglish).
  - **Structured-Markup Dictation** (ADR-v2-067, `[markup]`) — spoken lists/tables → Markdown (self-gating).
- **test:** 14 new daemon-wiring tests in `tests/test_v2_daemon_wiring.py` drive the real `_on_hold_end`
  and assert each transform fires only when enabled. **1503 tests green.**

### CLI help & documentation polish (`v2.11.0-dev.2`)

- **docs(cli): every command now carries a worked `Examples` block.** Added `Examples`
  epilogs to the ~19 commands/subcommands that lacked them (`stop`, `overlay`, `enroll`,
  `gaze calibrate`, `model list`, and all `features` / `vocab` / `hotkey` / `corpus`
  subcommands), so `yazses <cmd> -h` shows copy-pasteable usage for the whole surface, not
  just a flag list. Verified: all 39 commands render `-h` cleanly and every one has an
  `Examples` section.
- **docs(cli): richer `yazses transcribe` help.** The docstring now states plainly that
  transcription is fully offline (local `faster-whisper`, no cloud/account), lists all input
  and output formats, and explains `--model`, `--language translate`, and diarization/speaker
  naming; each flag reads as a full sentence; added 11 worked examples. Fixed a rich-markup
  bug where `[stt]` was swallowed in help text.
- **docs(cli-reference): fill gaps** — documented the previously-undocumented `coach`,
  `recall`, and `scratch` commands; added the `transcribe --model` row; refreshed the stale
  "v0.4 line" title and the help-panel list (now includes "Updates & maintenance").

### v2.11.0 — Wave O opens: offline media ingestion & speaker attribution (developer preview, `v2.11.0-dev.1`, all OFF by default)

New SoA round (an internal research note, ~70 cited sources) opens
Wave O — offline transcription of pre-recorded audio files with speaker diarization:

- **feat(recimport): Diarized Recording Import** (ADR-v2-125) — `yazses transcribe <file>` decodes any
  common audio format (wav/mp3/m4a/ogg/flac/opus/mp4), transcribes offline on CPU, optionally tags who
  said what (`--diarize` → "Speaker 1: …"), and writes a sidecar file next to the input
  (`talk.mp3 → talk.txt`, or `--format md|srt|vtt|json`). Names come from `--names`/`--rename` or an
  enrolled voiceprint (auto-labels you as "You"); unknown speakers stay "Speaker N". Completes the
  batch-transcription ADR-v2-083 (which had only pure subtitle writers) and reuses the live-path
  diarization cores (ADR-v2-019/074) on the file path.
  - Diarizer backend = **sherpa-onnx** (int8 ONNX, no PyTorch, no GPU, no HF token; ~15 MB models,
    lazy behind the new `diarization` extra). Audio decode reuses `faster_whisper.decode_audio` (PyAV) —
    **no new dependency** for full-format coverage. Word↔turn alignment is pure-numpy max-overlap.
  - Privacy (ADR-011/012): fully offline; diarization labels are transient; voiceprint naming is
    opt-in, consent-gated, on-device, and **never auto-enrolls** third parties.
- **feat(recimport): Cloud escalation designed & deferred** (ADR-v2-126) — a future opt-in
  `--cloud <provider>` path (Deepgram/AssemblyAI/OpenAI) is designed with hard guardrails but **not
  implemented**; offline stays the only path.
- `yazses features` still lists **135** capabilities (Recording Import was already counted; it is now
  fully implemented with diarization + naming, not a stub). New pure cores 100%-covered. **1489 tests
  green.** Base install and the v1 dictation path unchanged.

### v2.10.0 — Wave N complete: structural editing, i18n & accessibility-output (developer preview, `v2.10.0-dev.5`, all OFF by default)

New SoA round (Wave N): structural code editing, internationalization,
accessibility-output correctness; **all ten features shipped** + ADRs 115-124, pure and 100%-covered.

Eyes-free & blind-output tier (`dev.5`, Wave N complete):
- **feat(echo): Echo** (ADR-v2-119) — "play that back" replays your own captured audio for a text
  span (not TTS) to catch homophone/ASR errors eyes-free.
- **feat(srpace): SRPace** (ADR-v2-120) — pace injection to a screen reader's reading rate,
  clause-chunked, so it announces coherently.
- `yazses features` now **135**. Both cores 100% covered. 1453 tests green. **Wave N complete
  (all 10, ADRs 115-124).**

Word-finding & cognitive-load tier (`dev.4`):
- **feat(wordfind): WordFind** (ADR-v2-118) — offline reverse dictionary ("the word for when water
  turns to gas" → ranked shortlist); anomia/tip-of-the-tongue.
- **feat(loadguard): LoadGuard** (ADR-v2-121) — cognitive-load-aware guardrails: widen
  confirmations and defer risky actions when speech signals rising load.
- `yazses features` now **133**. Both cores 100% covered. 1445 tests green.

i18n & glyph-integrity tier (`dev.3`):
- **feat(diacritize): Diacritize** (ADR-v2-122) — restore dropped diacritics ("cafe" → "café"),
  unambiguous lexicon, case-preserving.
- **feat(safeglyph): SafeGlyph** (ADR-v2-123) — flag Unicode confusables/invisibles/mixed-script
  words (UTS-39 subset) before injection.
- `yazses features` now **131**. Both cores 100% covered. 1437 tests green.

Accessibility-output tier (`dev.2`):
- **feat(brailleout): BrailleOut** (ADR-v2-117) — dictation as Grade-2 UEB Unicode Braille
  (table-driven, liblouis stays optional).
- **feat(outline): Spoken Outline** (ADR-v2-124) — voice-driven outline tree → Markdown/OPML.
- `yazses features` now **129**. Both cores 100% covered. 1428 tests green.

Opener (`dev.1`):
- **feat(hatselect): HatSelect** (ADR-v2-115) — spoken structural token addressing (Cursorless-style).
- **feat(translit): Transliteration** (ADR-v2-116) — romanized → native script (Finglish→Persian
  built-in).
- `yazses features` now **127**. Both cores 100% covered. 1415 tests green.

CLI:
- **feat(cli):** `yazses features info` with no name prints the whole feature catalog (every
  capability + description + example); top-level `-h` points to it.

### v2.9.0 — Wave M complete: minimal-bandwidth AAC & text-intelligence (developer preview, `v2.9.0-dev.5`, all OFF by default)

New SoA round (Wave M): lowest-bandwidth AAC input + text-intelligence
layers; **all ten features shipped** + ADRs 105-114, pure and 100%-covered.

Authoring/proofing tier (`dev.5`):
- **feat(diagramvox): Diagrams-as-Code by Voice** (ADR-v2-107) — dictate a flowchart → Mermaid/DOT.
- **feat(proofback): Interruptible Read-Back Proofreading** (ADR-v2-108) — barge-in maps to the exact
  word being read.
- `yazses features` now **125**. Both cores 100% covered. 1408 tests green.

Formatting/capture tier (`dev.4`):
- **feat(screenplay): Screenplay Auto-Format** (ADR-v2-110) — dictated dialogue → Fountain markup.
- **feat(srscap): Spoken Spaced-Repetition Capture** (ADR-v2-112) — "remember that X is Y" → an Anki
  cloze card (SM-2).
- `yazses features` now **123**. Both cores 100% covered. 1399 tests green.

Editing-workflow tier (`dev.3`):
- **feat(styleguard): Style-Consistency Enforcer** (ADR-v2-109) — a Vale-lite house-style pass.
- **feat(suggestmode): Suggestion-Mode Dictation** (ADR-v2-113) — dictated edits as CriticMarkup
  tracked changes.
- `yazses features` now **121**. Both cores 100% covered. 1392 tests green.

Text-intelligence tier (`dev.2`):
- **feat(sembr): Semantic Line Breaks** (ADR-v2-111) — one clause per source line for clean git diffs.
- **feat(acronyms): Acronym & Glossary Manager** (ADR-v2-114) — expand on first use, contract after,
  warn on undefined (Schwartz-Hearst matcher).
- `yazses features` now **119**. Both cores 100% covered. 1386 tests green.

Opener (`dev.1`):
- **feat(morsevox): Vocal Morse** (ADR-v2-105) — type by Morse using two vocal sounds; full text from
  a single vocalization, with adaptive timing.
- **feat(checkdigit): Checksum-Validated Data Entry** (ADR-v2-106) — verify dictated account/ID
  numbers (Luhn/ISBN/Verhoeff) and suggest fixes.
- `yazses features` now **117**. Both cores 100% covered. 1378 tests green.

### v2.8.0 — Wave L complete: non-speech & prosodic voice interaction (developer preview, `v2.8.0-dev.5`, all OFF by default)

New SoA round (Wave L): non-speech vocal signals + acoustic prosody
as interaction channels; **all ten features shipped** + ADRs 095-104, pure and 100%-covered.

Accessibility tier (`dev.5`):
- **feat(mouthswitch): Mouth-Sound Switch Access** (ADR-v2-097) — scan-and-select from non-verbal
  mouth sounds (AAC switch access).
- **feat(involuntary): Involuntary-Vocalization Excision** (ADR-v2-102) — drop cough/throat-clear/
  sneeze from the stream.
- `yazses features` now **115**. Both cores 100% covered. 1369 tests green.

Robustness tier (`dev.4`):
- **feat(breath): Breath-Paced Dictation** (ADR-v2-099) — segment by natural breath onsets, not
  silence.
- **feat(whispermode): Whisper-Aware Mode** (ADR-v2-100) — detect whispered phonation and adapt
  gain/VAD/prompt.
- `yazses features` now **113**. Both cores 100% covered. 1363 tests green.

Turn-taking tier (`dev.3`):
- **feat(hesitation): Hesitation-Hold Endpointing** (ADR-v2-101) — hold the turn open on filled
  pauses ("uhh…") instead of cutting off.
- **feat(contour): Pitch-Contour Vocal Gestures** (ADR-v2-103) — hum a shape (rise=confirm,
  fall=cancel) as a word-free command.
- `yazses features` now **111**. Both cores 100% covered. 1356 tests green.

Robustness/reach tier (`dev.2`):
- **feat(spatialvad): Beam-Steered Spatial VAD** (ADR-v2-098) — 2-mic direction-of-arrival gate
  (pure-numpy GCC-PHAT), enrollment-free, composes with Cocktail Filter.
- **feat(prosodypunct): Prosodic Auto-Punctuation** (ADR-v2-104) — insert `. , ?` from prosody
  alone, no spoken punctuation words.
- `yazses features` now **109**. Both cores 100% covered. 1350 tests green.

Opener (`dev.1`):
- **feat(vocaljoystick): Vocal Joystick** (ADR-v2-095) — continuous analog cursor control by
  sustaining vowels (no words); a new modality for severe motor impairment.
- **feat(earcon): Earcon Feedback Language** (ADR-v2-096) — non-speech state tones, eyes-free.
- `yazses features` now **107**. Both cores 100% covered. 1344 tests green.

### v2.7.0 — Wave K complete (developer preview, `v2.7.0-dev.5`, all OFF by default)

Fresh SoA round (Wave K) + ADRs 085-094. **All ten Wave K features
shipped**, pure and 100%-covered.

Utilities tier (`dev.5`):
- **feat(voicetimer): Local Voice Timer & Break Reminder** (ADR-v2-093) — offline voice timers,
  spoken by read-back.
- **feat(focusprofile): Focus-Class Auto-Profile** (ADR-v2-094) — auto grammar profile from the
  focused window's class.
- `yazses features` now **105**. Both cores 100% covered. 1337 tests green.

Data/tracking tier (`dev.4`):
- **feat(tablecsv): Spoken Table Entry** (ADR-v2-091) — bulk row/field data entry ("row: Ada, 1815,
  London") with a Tab/Enter cadence.
- **feat(wordgoal): Word-Count & Goal Tracker** (ADR-v2-092) — count dictated words, track a goal,
  spoken progress.
- `yazses features` now 103. Both cores 100% covered. 1331 tests green.

Session tier (`dev.3`):
- **feat(timeline): Voice Undo/Redo Timeline** (ADR-v2-089) — undo/redo YazSes output across bursts
  by voice (word/sentence/burst), even where Ctrl+Z is unreliable.
- **feat(bookmarks): Session Bookmarks & Resume** (ADR-v2-090) — named anchors + jump-back for long
  sessions.
- `yazses features` now **101** (past triple digits). Both cores 100% covered. 1322 tests green.

Ship-now cores (`dev.1`-`dev.2`), four fully-pure:

- **feat(casetransform): Voice Case & Identifier Transform** (ADR-v2-087) — recase the selection
  ("make this snake_case"), nine styles.
- **feat(autopair): Auto-Pairing & Wrap-Selection** (ADR-v2-088) — balance brackets/quotes, wrap a
  selection; fixed a real delimiter-nesting bug.
- `yazses features` now 99. Both cores 100% covered. 1314 tests green.

Opening cores (`dev.1`):

- **feat(chords): Chorded Shortcut Synthesis** (ADR-v2-085) — say any keyboard shortcut ("press
  control shift P", "escape twice", "hit F5") and it's pressed; no macro registration.
- **feat(compute): Inline Compute** (ADR-v2-086) — "what's 15% of 240" → types 36, via a safe AST
  evaluator (never eval).
- `yazses features` now 97. Both cores 100% covered. 1306 tests green.

### v2.6.0 — Wave J complete (developer preview, `v2.6.0-dev.5`, all OFF by default)

Full 10-feature SoA round (Wave J) + ADRs 075-084.

Final tier (`dev.5`), pure core + deferred backend:
- **feat(recimport): Recording Import** (ADR-v2-083) — batch-transcribe archives to .srt/.vtt with
  timestamps; STT backend deferred.
- **feat(crowdproof): Crowd-Proof Dictation** (ADR-v2-084, experimental) — numpy TSE plumbing
  (frame/mask/overlap-add); Conv-TasNet model deferred.
- `yazses features` now 95. All Wave J cores 100% covered. 1295 tests green.

Navigation/shell tier (`dev.4`), pure core + deferred backend:
- **feat(jump): Voice Jump-to-Symbol** (ADR-v2-081) — "go to line 240"/"jump to function tokenize"
  → editor motion (fuzzy symbol match, search fallback); LSP feed deferred.
- **feat(shellpipe): Spoken Shell Pipeline Builder** (ADR-v2-082) — speak stages → render a shell
  pipeline as text, preview-first (nothing runs until "run it"); NL2Bash SLM deferred.
- `yazses features` now 93. Both cores 100% covered. 1288 tests green.

Learning/navigation tier (`dev.3`), pure core + deferred backend:
- **feat(corrdict): Self-Learning Correction Dictionary** (ADR-v2-079) — auto-fix recurring ASR
  errors mined from your own edits (support-gated, high precision).
- **feat(fileopen): Voice Fuzzy File Open** (ADR-v2-080) — "open the mortgage notes" → fuzzy-match
  and open a local file; semantic tier deferred.
- `yazses features` now 91. Both cores 100% covered. 1279 tests green.

Flagship tier (`dev.2`):
- **feat(reask): Confidence-Gated Re-Ask** (ADR-v2-077, flagship) — hold a low-confidence span and
  resolve it interactively (confusable A/B pick or repeat), instead of guessing.
- **feat(verbatim): Verbatim⇄Autoformat Live Toggle** (ADR-v2-078) — reserved phrases freeze/restore
  ITN+punctuation+reflow mid-burst; the only runtime ITN switch.
- `yazses features` now 89. Both cores 100% covered. 1270 tests green.

Opening tier (`dev.1`), two fully-pure cores:

- **feat(spelling): Phonetic Spelling Mode** (ADR-v2-075) — NATO words → exact characters for
  passwords/codes/IDs ("capital alpha bravo double lima" → Abll).
- **feat(gitvoice): Voice Git Choreographer** (ADR-v2-076) — structured git-argv grammar;
  destructive ops gated behind spoken confirm, undo always spoken; no deferred backend.

### v2.5.0 — Wave I complete (developer preview, `v2.5.0-dev.5`, all OFF by default)

Full 10-feature SoA round (Wave I) + ADRs 065-074.

Final tier (`dev.5`), pure core + deferred backend:
- **feat(latency): Adaptive Latency Governor** (ADR-v2-073) — load-aware decode policy +
  speculative decoding when idle; psutil/draft/spec-decode deferred.
- **feat(diarize): Diarized Conversation Capture** (ADR-v2-074) — attributed multi-speaker Markdown
  + rename-by-voice; pyannote deferred.
- `yazses features` now 85. All Wave I cores 100% covered. 1252 tests green.

Heavier tier (`dev.3`-`dev.4`), pure core + deferred backend:
- **feat(hotwords): Hard Contextual Biasing** (ADR-v2-069) — hotword trie + N-best rescorer,
  retraining-free rare-word biasing (in-decoder hook deferred).
- **feat(windowctl): Voice Window Management** (ADR-v2-070) — spoken desktop layout (snap/maximize/
  workspace); per-compositor backends deferred.
- **feat(cite): Citation-by-Voice** (ADR-v2-071) — "cite Vaswani 2017" → a formatted citation from
  your local .bib, fully offline.
- **feat(langroute): Per-Language Auto Model Switching** (ADR-v2-072) — detect the spoken language
  and hot-swap to its model + ITN; model files deferred.
- **fix(features): resolve a real langroute/lipread variable-name collision** in the feature
  registry, caught by the write-target regression guard.
- `yazses features` now 83. All cores 100% covered. 1243 tests green.

Ship-now tier (`dev.2`), four dependency-free cores:

- **feat(cmdsafety): Terminal Command Safety Gate** (ADR-v2-065) — hold destructive shell commands
  (rm -rf, dd, mkfs, force-push, curl|sh, fork bomb) until spoken "confirm".
- **feat(spokenregex): Spoken Regex Builder** (ADR-v2-066) — dictate search patterns
  ("four digits dash two digits" → \d{4}-\d{2}).
- **feat(markup): Structured-Markup Dictation** (ADR-v2-067) — speak lists/tables → Markdown/org.
- **feat(findreplace): Document Find-and-Replace** (ADR-v2-068) — "replace every utilise with use"
  edits the whole document, not just the last utterance.
- `yazses features` now 79. All four cores 100% covered. 1223 tests green.

### v2.4.0 — Wave H complete (developer preview, `v2.4.0-dev.2`, all OFF by default)

Full 10-feature SoA round (Wave H) + ADRs 055-064.

Medium tier (`dev.2`), pure core + deferred backend:
- **feat(audioguard): Ambient Audio-Event Guard** (ADR-v2-061) — pause/alert on interrupting sounds.
- **feat(condense): On-Device Condense** (ADR-v2-062) — insert a tightened summary of your ramble.
- **feat(slotfill): Slot-Filling Dictation** (ADR-v2-063) — one utterance fills a named-field form.
- **feat(cmdspotter): Few-Shot Command Spotter** (ADR-v2-064) — enrolled low-latency micro-commands.
- `yazses features` now 75. All Wave H cores 100% covered. 1202 tests green.

Ship-now tier (`dev.1`) + ADRs 055-060, six dependency-free features:

- **feat(commands): Emoji & Symbol by Voice** (ADR-v2-055) — spoken symbols/emoji → Unicode.
- **feat(convert): Voice Unit Conversion** (ADR-v2-056) — inline offline unit/temperature conversion.
- **feat(temporal): Spoken Temporal Normalizer** (ADR-v2-057) — "next Friday" → a concrete date.
- **feat(commands): Mid-Utterance Self-Repair** (ADR-v2-058) — "no I mean X" corrections pre-injection.
- **feat(spreadsheet): Spoken Spreadsheet** (ADR-v2-059) — grid nav + cell addressing.
- **feat(cliphistory): Clipboard-History by Voice** (ADR-v2-060) — recall recent copies by voice.
- `yazses features` now 71. All Wave H cores 100% covered. 1186 tests green.

### v2.3.0 — Wave G complete (developer preview, `v2.3.0-dev.2`, all OFF by default)

Full 10-feature SoA round (Wave G) + ADRs 045-054.

Medium + hardware tier (`dev.2`), pure core + deferred backend:
- **feat(compose): Compose-in-Target-Language** (ADR-v2-049) — speak L1, type L2.
- **feat(gec): Grammar Repair** (ADR-v2-050) — minimal-edit L2 correction.
- **feat(screengrounded): Screen-Grounded Dictation** (ADR-v2-051) — bias STT from on-screen text.
- **feat(headpointer): Head-Pointer** (ADR-v2-052) — cursor + click by head pose.
- **feat(lipread): Silent Lip-Reading** (ADR-v2-053) — dictate with no voice via webcam.
- **feat(sign): Sign-Language Input** (ADR-v2-054) — sign to the webcam, ASL → text.
- `yazses features` now 65. All Wave G cores 100% covered. 1153 tests green.

Ship-now tier (`dev.1`) + ADRs 045-048, privacy-forward, dependency-light:

- **feat(itn): Entity ITN** (ADR-v2-045) — spoken emails/versions → written form, no command
  words; wired on the dictate path.
- **feat(redaction): Redaction Ink** (ADR-v2-046) — mask spoken secrets (card-Luhn/SSN/key/…)
  before injection; wired on the dictate path.
- **feat(fieldaware): Field-Aware Dictation** (ADR-v2-047) — shape output by the focused field's
  role; password fields refused.
- **feat(learning): Corpus Voiceprint Scrub** (ADR-v2-048) — speaker-anonymize stored corpus
  audio; wired in the corpus writer.
- `yazses features` now 59. All Wave G cores 100% covered. 1124 tests green.

### v2.2.0 — Wave F complete (developer preview, `v2.2.0-dev.2`, all OFF by default)

Full 10-feature SoA round (Wave F) + ADRs 035-044.

Ship-now pure tier (`dev.1`), no new dependency:
- **feat(coach): Speaking Coach** (ADR-v2-035) — private filler/WPM/vocabulary analytics.
- **feat(smartpaste): Smart-Paste** (ADR-v2-036) — adapt injected syntax to the target app.
- **feat(scrub): Audio-Anchored Scrubbing** (ADR-v2-037) — word→audio replay/pinpoint re-dictate.
- **feat(reflow): Dictation Reflow** (ADR-v2-038) — "structure this" → bulleted outline + actions.

Medium + hardware tier (`dev.2`), pure core + deferred backend:
- **feat(acoustic_profiles): Acoustic Context Profiles** (ADR-v2-039) — scene-adaptive mic tuning.
- **feat(sentiment): Mood Ledger** (ADR-v2-040) — private speech-sentiment journal.
- **feat(pronunciation): Pronunciation Feedback** (ADR-v2-041) — per-phoneme L2 practice scoring.
- **feat(tts): Personal Read-Back Voice** (ADR-v2-042) — read back in a clone of your own voice.
- **feat(gesture): Gesture Chords** (ADR-v2-043) — multi-input chords → actions.
- **feat(interpret): Two-Way Live Interpreter** (ADR-v2-044) — face-to-face alternating translate.

- **fix(features):** corrected an enable/disable config-section collision (prosody/predict/
  spoken-edit wrote to the wrong section) + write-target regression guard.
- `yazses features` now 55. All Wave F pure cores 100% covered. 1086 tests green.

### v2.1.0 — Wave E complete (developer preview, `v2.1.0-dev.5`, all OFF by default)

ADRs 029-034 complete Wave E (10/10 features). Zero-touch bundle + language modes + health:

- **feat(autostop): Hands-Free Auto-Stop** (ADR-v2-029) — tap-and-speak, silence/duration stop.
- **feat(mousegrid): Voice Mouse Grid** (ADR-v2-030) — click-by-voice grid subdivision.
- **feat(code): Spoken Code Mode** (ADR-v2-031) — symbols→punctuation + cased identifiers.
- **feat(math): Spoken Math→LaTeX** (ADR-v2-032) — spoken equations → LaTeX.
- **feat(wakeword): Wake-Word Activation** (ADR-v2-033, experimental) — hands-free keyword start.
- **feat(voicehealth): Vocal-Strain Guard** (ADR-v2-034) — session strain → break advice.
- `yazses features` now 45. All Wave E pure cores 100% covered. 1032 tests green.

### v2.1.0 — Wave E ship-now tier (developer preview, `v2.1.0-dev.4`, all OFF by default)

Fresh SoA round (Wave E) + ADRs 025-028. First four features:

- **feat(hallucination): Hallucination Guard** (ADR-v2-025) — drops Whisper's fabricated ghost
  text (silence outros, loops) before injection; pure detector, wired into the decode path.
- **feat(snippets): Voice Snippets** (ADR-v2-026) — spoken trigger → stored template.
- **feat(phonetic): Phonetic Corrector** (ADR-v2-027) — fixes mis-heard names by sound vs vocab.
- **feat(voiceprint): Multi-User Profiles** (ADR-v2-028) — per-speaker profile routing from the
  voiceprint (distinct from Voice Guard's binary gate).
- `yazses features` now 39. All new pure cores 100% covered. 994 tests green.

### v2.1.0 — Wave D hardening + seams (developer preview, `v2.1.0-dev.3`, all OFF by default)

ADRs 021-022. Pure safety/decision seams for hard-tier features (heavy engines deferred) + hardening:

- **feat(personalize): atypical-speech LoRA held-out gate** (ADR-v2-021) — pure
  `should_apply_adapter`; applies an adapter only on a held-out WER win (`lora_min_improvement`).
- **feat(codec): neural-codec streaming engine-selection seam** (ADR-v2-022) — pure
  `select_engine` (codec vs faster-whisper); `[codec]`, feature #35. Engine lazy behind the extra.
- **test(v2): all pure v2 cores → 100%** — agent/pilot/polyglot/context + adapter_gate/codec
  100% covered (+targeted edge tests; one unreachable defensive branch marked no-cover). 947 green.

### v2.1.0 — Wave D medium tier (developer preview, `v2.1.0-dev.2`, all OFF by default)

ADRs 018-020. Three more on-device features:

- **feat(voiceguard): Voice Guard** (ADR-v2-018, experimental) — biometric + anti-spoof
  injection gate; pure `admit()`, fail-open default; ECAPA/anti-spoof lazy behind the extra.
- **feat(scribe): Meeting Scribe** (ADR-v2-019) — who-said-what transcript (You/Speaker N);
  pure label/merge/format; Sortformer diarization lazy behind the extra.
- **feat(rag): Ask My Notes** (ADR-v2-020) — voice-grounded, cited RAG over local docs; pure
  cosine/rank/format-context; embeddings + sqlite-vec + LLM lazy behind the extra.
- `yazses features` now 34 (new: `voiceguard`, `scribe`, `rag`). 934 tests green.

### v2.1.0 — Wave D (developer preview, `v2.1.0-dev.1`, all OFF by default)

Fresh SoA research (11 candidates, Wave D) + ADRs 014-017.
First four features, all on-device:

- **feat(translate): Speech Translation** (ADR-v2-014) — dictate L1, type English via Whisper's
  built-in translate task (zero new downloads); `seamless` backend opt-in for other targets.
- **feat(affect): Tone-Aware Formatting** (ADR-v2-017) — vocal tone → `!`/`?`; SER model opt-in.
- **feat(predict): Predictive Completion** (ADR-v2-016) — on-device next-phrase suggestion,
  accept by voice; generator opt-in, background thread.
- **feat(denoise): Noise Suppression** (ADR-v2-015) — DeepFilterNet denoise/dereverb before STT;
  identity passthrough when off, wired into the decode path.
- New `yazses features` entries: `translate`, `affect`, `predict`, `denoise` (31 total).
- Hardening: `edit_ops.py` coverage 92%→100%. 910 tests green.

### v2.0.0 — Voice-First Interaction Layer · Wave A (developer preview, all OFF by default)

Tagged `v2.0.0-dev.1` (developer preview — **not published**; v1.4.1 remains the
stable release). Design in `design/adr/adr-v2-*` + an internal research note.

- **feat(confidence): Confidence Ink** (`[confidence]`) — flags low-confidence words
  from Whisper's per-word token probabilities and re-picks from n-best by voice;
  wired into the decode path (metadata-count only, no transcript persisted). ADR-v2-001.
- **feat(prosody): pause→sentence punctuation** (`[prosody] pause_sentence_ms`) — a
  sentence-length pause inserts a period (opt-in; default keeps prior behaviour). ADR-v2-002.
- **feat(commands): Spoken Edit Mode** (`[commands] spoken_edit`) — open-ended voice
  edits of the last dictation ("change X to Y", "delete the last sentence");
  command-key gated, destructive ops deferred to a confirm loop. ADR-v2-003.
- **feat(context): Context-Primed Dictation** (`[context]`) — folds salient terms from
  the active window title / selection / clipboard into the STT prompt; transient reads,
  never stored, fully guarded. ADR-v2-004.
- New `yazses features` entries: `confidence`, `spoken-edit`, `context` (all off by default).

Wave B (`v2.0.0-dev.2`) — new packages, all off by default:

- **feat(personalize): Personal Adapter P1** (ADR-v2-009) — corpus n-gram + unigram
  prompt-mining biases STT toward your jargon; reads the encrypted corpus once (cached).
- **feat(recall): Spoken Recall & Ambient Scratch** (ADR-v2-005) — `yazses recall <query>`
  searches past dictations; `yazses scratch` captures/lists spoken notes-to-self. Corpus-local.
- **feat(polyglot): True Code-Switch routing** (ADR-v2-008) — routing layer; dormant until a
  user supplies an out-of-band code-switch adapter.
- **feat(agent): Voice-to-Tool / Spoken MCP** (ADR-v2-006) — voice→tool planner + confirm
  guard (`all|writes|none`); SLM + MCP client behind the `agent` extra.
- **feat(pilot): AT-SPI Voice Pilot** (ADR-v2-007) — "click Save"-style desktop control via
  the accessibility tree; pyatspi backend lazy/system-package, labels only (no screenshots).
- New `yazses features` entries: `recall`, `agent`, `pilot` (24 capabilities total, v2 ones off).

Wave C (`v2.0.0-dev.3`) — experimental, all off by default (`--force` to enable):

- **feat(modality): Modality Role Router** (ADR-v2-011) — assign each input its fastest role
  (voice→dictation, EMG→command, gaze→targeting) with presets + priority arbitration.
- **feat(continuum): Accessibility Continuum** (ADR-v2-012) — Whisper/Low-Effort Mode lowers
  the VAD gate so quiet speech is captured; wired into the daemon VAD path.
- **feat(gaze): Gaze-Routed Dictation** (ADR-v2-010) — route dictation to the looked-at window
  (confidence-gated, focus fallback, destructive-confirm).
- **feat(bridge): Glasses↔Desktop Bridge** (ADR-v2-013) — pair a phone/glasses as a mic;
  desktop runs STT + injection (reuses the remote transport).
- New `yazses features` entries: `continuum`, `modality`, `bridge` (27 capabilities total).
- **All 13 v2 features implemented** across Waves A/B/C. 876 tests green.

Polish (`v2.0.0-dev.4`) — discoverability, observability, safety (no new features):

- **docs:** `docs/v2-features.md` user guide for all 13 features (toggle names verified).
- **feat(commands):** `spoken_edit_destructive` gate — destructive voice edits opt-in + undoable.
- **feat(daemon):** `yazses status` exposes `confidence_enabled` + `low_confidence_last`.
- **feat(doctor):** per-enabled-feature v2 readiness (extra/config presence) reporting.
- **docs:** `design/architecture.md` v2 layer section.

## [1.4.1] — 2026-07-01

### Fixed
- **Cross-platform imports.** `yazses.system.setup`, `inject/auto`, and
  `inject/clipboard` now import cleanly on Windows and macOS — the Unix-only
  `grp`/`pwd` modules are imported lazily and `os.getuid` is guarded with
  `hasattr`. Test collection no longer errors out on non-Linux, restoring a green
  test matrix across Linux × macOS × Windows on Python 3.11 and 3.12.

### Changed
- **Snap release reliability.** A tagged release on the canonical repository now
  fails with a clear error when the Snap Store credential is absent, instead of
  silently skipping the publish (which had left the snap channel stale while the
  workflow still reported success). The PyPI publish step gained `skip-existing`
  so manual re-publishes are idempotent.

## [1.4.0] — 2026-07-01

### Added — voice punctuation & formatting (opt-in)
- Speak punctuation to insert it: "hello comma world period" → "hello, world.".
  Supports comma, period/full stop, question mark, exclamation mark, colon,
  semicolon, and formatting: "new line", "new paragraph", "tab key". Off by
  default (these words also occur in ordinary speech); enable with
  `yazses features enable voice-punctuation` (writes `[commands]
  voice_punctuation = true`). Longest phrase wins ("new paragraph" over "new
  line") and word boundaries protect substrings ("command" is untouched).
  `postprocess/voice_punctuation.py`, applied on the dictation path only. Tested
  in `tests/test_voice_punctuation.py`.

### Added — `[injection] backend` config (choose the injector)
- The injection method is now selectable per machine:
  `[injection] backend = "auto" | "type" | "clipboard" | "wtype"` (or the
  `YAZSES_INJECTOR` env var). `auto` (default) types via ydotool on Wayland —
  works everywhere including terminals. Set `clipboard` if you prefer instant
  paste (no-op in terminals, clobbers the clipboard). Bridged through
  `core/daemon.py` → `inject.auto.get_injector`; non-Linux platforms ignore it.
  Tested in `tests/test_auto_inject.py`.

## [1.3.9] — 2026-07-01

### Fixed — long dictations were typed twice
- On a long transcript, `ydotool type` (at its slow default speed) exceeded the
  fixed 10 s subprocess timeout and was killed mid-type. `LinuxInjector` treated
  that as a failure and ran the **clipboard fallback**, which re-injected the
  whole text — so it appeared typed *and* pasted ("typed twice"). Two fixes:
  `YdotoolInjector` now types faster (`-d 6 -H 6`, ~12 ms/char vs the 40 ms/char
  default) and scales the timeout with text length (`10 s + 30 ms/char`) so it
  cannot time out on a long take. Tested in `tests/test_auto_inject.py`
  (`test_ydotool_type_timeout_scales_with_length`, `test_ydotool_type_uses_speed_flags`).

### Changed — longer maximum recording
- A single hold-to-talk recording was capped at 90 s, cutting off long dictations
  mid-sentence. Raised the `[audio] max_record_seconds` default to 300 s (5 min);
  raise it further in config for very long takes.

## [1.3.8] — 2026-07-01

### Changed — restore "type everywhere" (revert v1.3.7's clipboard default)
- v1.3.7 dodged the Ubuntu-26 `mmmm…` flood by pasting via the clipboard, but
  that broke dictation in **terminals** (where `Ctrl+V` is literal, not paste) —
  which had worked on Ubuntu 24. The default is back to **typing** the text with
  ydotool, which works in every focused app (terminals included) and never
  touches the clipboard. The flood is not ydotool dropping events (its virtual
  device emits balanced key up/down) — it's the Ubuntu-26+ compositor
  intermittently dropping the final synthetic key-up. `YdotoolInjector` now sends
  a **flood guard** after each `ydotool type`: a key-up for every keycode `type`
  can press (input codes 2–57, incl. both shifts), which releases any key the
  compositor failed to release before the ~0.5 s auto-repeat can begin. A key-up
  for a key that isn't down is a no-op, so it is safe and layout-independent.
- Clipboard-paste is still available as an override via `get_injector("clipboard")`
  or the `YAZSES_INJECTOR=clipboard` environment variable, for anyone who prefers
  it. Tested in `tests/test_auto_inject.py` (`test_gnome_wayland_types_by_default`,
  `test_prefer_clipboard_forces_clipboard`, `test_env_override_clipboard`).

### Fixed — first word of a dictation was dropped (no STT lead-in)
- faster-whisper drops or clips the opening word when a clip starts abruptly
  mid-utterance, and the pre-speech ring buffer that was meant to supply lead-in
  audio was never fed (dead code). The daemon now prepends a short silence
  lead-in (`[accessibility] pre_speech_padding_ms`, default raised 200 → 300 ms)
  to the audio just before decode — after the VAD gate, so the added zeros can't
  trigger a false "silent" discard, and only on the batch path (streaming commits
  its own buffer). Tested in `tests/test_v2_daemon_wiring.py`
  (`test_onset_lead_in_prepended_before_stt`, `test_onset_lead_in_disabled_when_zero`).

### Fixed — `ydotool key` (voice commands, backspaces, clipboard paste) sent nothing on ydotool 1.x
- v1.3.7 switched GNOME/KDE Wayland injection to clipboard-paste, but the paste
  keystroke was `ydotool key ctrl+v` — and ydotool 1.x's `key` command **silently
  ignores symbolic key names**. Verified against ydotoold's own virtual input
  device: `ctrl+v` and even `KEY_LEFTCTRL+KEY_V` emit **zero** key events; only
  numeric `29:1 47:1 47:0 29:0` works. So the transcript was copied to the
  clipboard but never pasted, and dictation appeared to do nothing. The same
  latent bug meant every `ydotool key` call in the codebase (voice commands,
  backspaces, streaming correction) had been a no-op on ydotool 1.x. Added
  `inject/ydotool.py::ydotool_key_args`, which converts any combo (`ctrl+v`,
  `shift+Left`, `KEY_BACKSPACE`) into numeric `<keycode>:<state>` tokens (press
  in order, release in reverse), and routed the clipboard paste, backspaces, and
  the Linux key-sequence path through it. Tested in
  `tests/test_grammar_punctuation_and_keys.py`
  (`test_ydotool_key_args_numeric`, `test_ydotool_ctrl_v_exact_keycodes`).

### Fixed — intermittent clipboard paste ("worked randomly")
- Even with a valid Ctrl+V, the paste landed only sometimes: `wl-copy` set the
  clipboard and the very next instruction fired Ctrl+V microseconds later, before
  the new Wayland selection had propagated to the compositor, so the app pasted
  nothing (manual Ctrl+V seconds later always worked). `ClipboardInjector` now
  waits 150 ms after `wl-copy` for the selection to settle, and sends the paste
  with `ydotool key -d 40` so the compositor reliably registers Ctrl held when V
  is pressed.

## [1.3.7] — 2026-07-01

### Fixed — repeated-character flood on GNOME/KDE Wayland (ydotool stuck key)
- On GNOME/KDE Wayland, dictation typed runs of a single repeated character
  (`mmmm…`, `eeee…`) that the user never spoke, mangled the last word, and only
  stopped when a real key was pressed. Root cause: those compositors block
  `wtype` and force `ydotool`, whose `type` command drops the final key-up event
  under Wayland — the kernel then treats the last key as held and auto-repeats
  it. `inject/auto.py::get_injector` now prefers clipboard-paste (`wl-copy` + one
  `Ctrl+V`) on GNOME/KDE when `wl-copy` and `ydotoold` are both available, so no
  content character is ever sent as a keystroke and nothing can stick. Other
  Wayland compositors and X11 are unchanged; ydotool remains the fallback when
  `wl-copy` is missing. Tested in `tests/test_auto_inject.py`
  (`test_gnome_wayland_prefers_clipboard`,
  `test_gnome_wayland_without_wlcopy_falls_back_to_ydotool`).
- Trade-off: clipboard-paste uses the system clipboard and sends `Ctrl+V`, which
  pastes literally in terminals that expect `Ctrl+Shift+V`.

## [1.3.6] — 2026-06-27

### Fixed — voice commands never matched (Whisper punctuation broke the grammar)
- The command grammar matches anchored `^…$` patterns, but Whisper transcribes
  short utterances with a leading capital and a trailing period ("Undo." / "Save
  file." / "Select all."), so almost every spoken command fell through to
  dictation and was ignored in command mode. `commands/grammar.py::classify` now
  strips outer punctuation/whitespace before matching (interior punctuation like
  "main.py" is preserved). Matching was already case-insensitive.

### Added — basic keystroke voice commands
- Command mode gained the everyday keys it was missing: "new line"/"enter",
  "tab", "escape", "press backspace", "cut", "page up"/"page down",
  "go up/down/left/right" (arrows), "beginning of line"/"end of line". Mapped to
  real keys for both X11 (xdotool) and Wayland (ydotool); the ydotool key table
  gained `Page_Up`/`Page_Down`/`Home`/`End`. Documented in
  `docs/cli-reference.md` (new "Voice command reference" table). Tested in
  `tests/test_grammar_punctuation_and_keys.py`.

## [1.3.5] — 2026-06-27

### Fixed — first words of dictation were lost (voice-onset clipping)
- With a modifier hotkey (the default `right_alt`), recording only began after
  the hold threshold — which fires on a **kernel key-repeat event ~0.5 s after
  the press** — so the first one-to-three words spoken were never captured.
  `EvdevHoldListener` now starts recording the instant a modifier key goes down
  (`produces_char=False`), independent of the threshold and key-repeat. Character
  keys (e.g. `space`) keep the threshold gate and leaked-character cleanup, since
  for them a hold can only be told from a tap after the threshold. The press/
  repeat/release state machine was extracted to `_handle_event` and unit-tested
  in `tests/test_evdev_hold_onset.py`.
- Fixed the pre-speech padding path in `core/daemon.py`, which pushed each
  finished recording into the ring buffer and then prepended that same tail to
  the **front** of the audio — corrupting the start instead of recovering onset
  (and seeding stale audio into the streaming path). The recording now carries
  its own onset directly, so no prepend is needed.

## [1.3.4] — 2026-06-27

### Changed — Linux default hold-to-talk key is now `right_alt` (was `space`)
- The Linux platform default and the built-in `[hotkey] key` default now resolve
  to **`right_alt`** instead of `space`, matching the documentation, the macOS
  (`right_option`) and Windows (`right_ctrl`) defaults, and avoiding the obvious
  collision where the space bar doubles as the push-to-talk key. `[hotkey] key`
  now defaults to `"auto"`, which resolves to each OS's modifier-key default; set
  an explicit key in `config.toml` (or `yazses hotkey set <key>`) to override.
  Only affects users who never configured a hotkey; existing configs are
  unchanged. Fixes `cli._resolved_hotkey` so status/start messages show the
  resolved key rather than the literal `auto` sentinel.

### Documentation
- `docs/cli-reference.md`: documented the new `yazses doctor` install/lifecycle
  and hotkey-device checks, and added a "Moving your dictionary to another
  device" section (copy `~/.config/yazses/vocabulary.txt` + `config.toml`).
- `docs/install-linux.md`: added a "Troubleshooting: the hotkey does nothing"
  section covering virtual-device binding, a broken systemd `ExecStart`
  (`203/EXEC`), duplicate installs, and the `input`-group requirement.

## [1.3.3] — 2026-06-27

### Fixed — hotkey never detected when `ydotoold` is running (wrong input device)
- The evdev hold-listener selected the **first** `/dev/input` device advertising
  the hotkey, which on a Wayland box with `ydotoold` set up is the *injector's own*
  "ydotoold virtual device" — a uinput device that exposes the full key range but
  only ever carries synthetic events. The daemon listened there instead of the
  real keyboard, so holding the hotkey did nothing (no recording, no mic
  activity). This surfaced once `yazses setup` (1.3.2) started provisioning
  `ydotoold`. `hotkeys/evdev_hold.py::_find_keyboard` now skips
  virtual/injection devices by name (`ydotool`/`uinput`/`virtual`/`wtype`/
  `yazses`), prefers a device that looks like a full keyboard (complete letter
  row + Enter), and only falls back to a virtual device as a last resort with a
  loud warning. Regression-tested in `tests/test_evdev_find_keyboard.py`.

### Added — `yazses doctor` install/lifecycle diagnostics
- `yazses doctor` now reports three failure modes that previously required deep
  manual probing: a **Hotkey device** line showing which `/dev/input` device the
  hotkey binds to (FAIL if it resolves to a virtual injector device); an
  **Install** warning when multiple `yazses` executables are on `PATH` (stale
  pipx/apt copies alongside the active one); and a **systemd unit** check that
  flags an `ExecStart` pointing at a missing binary (the `203/EXEC` crash-loop
  where `yazses start`/`restart` silently start nothing) or one that differs from
  the `yazses-daemon` on `PATH`. Tested in `tests/test_doctor_install_diag.py`.

## [1.3.2] — 2026-06-27

### Added — `yazses setup`: one-command turnkey Linux provisioning
- New `yazses setup` command provisions **every** runtime requirement so a
  `pipx`/`uv`/`snap` install works out of the box, eliminating the three classic
  "YazSes does nothing" failures: missing `libportaudio2` (daemon crash), not in
  the `input` group (no hotkey), and no `ydotoold` (no injection on GNOME/KDE
  Wayland). It detects the session, installs the missing apt packages, joins the
  `input` group, and sets up + enables the `ydotoold` user service on Wayland.
  Idempotent and `--dry-run`-able. Backed by the pure, unit-tested planner in
  `system/setup.py`.

### Fixed — injection on GNOME/KDE Wayland (and robust backend selection)
- Keystroke injection failed on GNOME/KDE Wayland: the auto-probe picked
  `ydotool` whenever it was *installed*, but `ydotool` is useless without a
  running `ydotoold` (`failed to connect socket … .ydotool_socket`), and `wtype`
  — the alternative — is blocked by Mutter/KWin. Injector selection now gates
  `ydotool` on its socket actually existing (`inject/auto.py`, `inject/clipboard.py`):
  it picks `ydotool` only when `ydotoold` is up (works on any compositor), else
  falls back to `wtype` (wlroots) instead of hard-failing.
- `yazses doctor` gained an **Injection** readiness check + a `ydotoold` line:
  on GNOME/KDE Wayland with no socket it reports `[FAIL] … run yazses setup`,
  giving the exact fix instead of a runtime traceback.

### Changed — every install path sets up Wayland injection
- Ship `contrib/ydotoold.service`; `install-apt.sh` and the `.deb` postinst now
  install + enable it on Wayland, and the `.deb` points users at `yazses setup`.
  Docs (README, `docs/index.md`, `docs/install-linux.md`) lead with `yazses setup`
  and document the GNOME/KDE Wayland `ydotool`+`ydotoold` requirement.

### Changed — install-apt.sh: raw-GitHub URL is now the canonical apt channel
- GitHub Pages on this repo serves the docs site from `main`, so it cannot also
  serve the apt repo from `gh-pages` — the `mskazemi.github.io/yazses/apt` URL
  permanently 404s. `install-apt.sh` now tries the working
  `raw.githubusercontent.com/.../gh-pages/apt` URL first (Pages only as a
  fallback if ever reconfigured), removing the misleading "Pages not reachable
  yet, falling back" warning that printed on every run. `YAZSES_APT_BASE_URL`
  still overrides both. Verified end-to-end: signed `InRelease` (good signature),
  `Packages` lists 1.3.1, and the `.deb` (a thin bootstrap that `pipx install`s
  yazses and pulls `libportaudio2`/injection tools as real `Depends`) downloads.

## [1.3.1] — 2026-06-27

### Fixed — APT repository now actually publishes
- The advertised APT install (`install-apt.sh` → `mskazemi.github.io/yazses/apt`)
  had **never worked** — the `apt-repo` CI job failed on every release: the GPG
  signing secrets (`APT_REPO_GPG_PRIVATE_KEY` / `APT_REPO_GPG_KEY_ID`) were never
  set, so the "Import GPG signing key" step hard-failed (v1.0.0, v1.2.0), and
  v1.3.0 never built a `.deb` at all (its tagged `test` job failed on missing
  Qt/xcb libs, skipping `release-linux`). With the signing key now configured and
  the `test` gate fixed (`a22849a`), a tagged release builds the `.deb`, the
  `apt-repo` workflow signs it and publishes the `gh-pages` apt repo, and
  `sudo apt install yazses` works for the first time.
- `apt-repo.yml`: dropped the dead `Rust Release` `workflow_run` trigger and
  changed the `workflow_dispatch` default source from the non-existent
  `rust-release` to `release`.

### Changed — install: `install-apt.sh` now installs every injection/clipboard backend explicitly
- `install-apt.sh` previously relied on the `.deb`'s `Depends` for the injection
  and clipboard tools, but those are **alternatives** (`xdotool | ydotool | wtype`,
  `xclip | wl-clipboard`), so apt installed only the first (`xdotool`, an X11 tool)
  — leaving pure-Wayland machines with no working backend. The script now installs
  the full set (`libportaudio2 xdotool ydotool wtype xclip wl-clipboard`) in a
  per-package-tolerant loop, so dictation works on **both** X11 and Wayland out of
  the box. The runtime then auto-selects the right backend (`inject/auto.py`).
- Docs (`README.md`, `docs/index.md`, `docs/install-linux.md`) now give a single
  one-line `apt install` for all runtime deps on the `pipx`/`uv tool` path, with a
  table explaining what each package is for.

### Changed — docs: surface the two Linux prerequisites for `pipx`/`uv`/`snap` installs
- Promoted **both** Linux prerequisites — `libportaudio2` (PortAudio system
  library) and `input`-group membership — from a buried footnote/single line to
  explicit, ordered steps that run **before** `yazses start` across the install
  surfaces (`README.md` Quick Start, `docs/index.md`, `docs/install-linux.md`).
  Rationale: the APT `.deb` already declares `libportaudio2` and `install-apt.sh`
  already adds the user to `input`, but the `pipx`/`uv tool`/`snap` install paths
  do neither — so a manual install crashes on start with
  `OSError: PortAudio library not found`, or (once that's fixed) silently fails to
  detect the hotkey because the user isn't in the `input` group. These are the two
  most common "YazSes does nothing / won't start" causes on Linux. Each surface
  now also shows how to verify (`yazses doctor` → `[OK] Keyboard capture`,
  `[OK] Microphone`) and reminds users to re-login for the group change to take
  effect.

## [1.3.0] — 2026-06-23

### Added — social-preview card
- **1280×640 GitHub/social-preview card** (`snap/gui/social-preview.png`, source
  `snap/gui/social-card.html`) for link unfurls on GitHub, Reddit, Hacker News and
  social posts — dark-navy brand gradient, app icon, sonar motif and an install
  line. Upload via the repo's *Settings → Social preview*.

### Changed — voice-activity overlay on by default
- **`[overlay] enabled` now defaults to `true`** (was `false`), matching the
  `features` registry which already listed the overlay as on-by-default.
- **PySide6 is now a base dependency** (was the optional `overlay` extra), so the
  overlay works out of the box on every install — `pip install yazses`, the
  global `uv tool`, and the snap (which now bundles PySide6 plus the Qt
  xcb/wayland runtime libs in `stage-packages`). `yazses overlay` no longer
  fails with a "needs PySide6" hint on a fresh install. The `overlay` extra is
  retained for backward compatibility. The PySide6 wheels still need glibc ≥ 2.28
  (Ubuntu 20.04+); on older distros the daemon logs a one-line hint and skips the
  overlay launch (`core/daemon.py`, `overlay_dependency_available()`) instead of
  dying on the import — dictation is unaffected either way. Set
  `[overlay] enabled = false` to opt out. Docs (`cli-reference`, `install-linux`,
  `examples/config.example.toml`) updated. 689 tests pass.

## [1.2.0] — 2026-06-20

**CLI usability — control YazSes without hand-editing TOML.** A friendlier command
surface: a capabilities switchboard, a personal dictionary, hotkey management
(including a dedicated command key), and duplicate-daemon-proof lifecycle commands.
All config writes preserve comments and prompt `yazses restart`. 680 tests pass.

### Added — dedicated command key (force command mode)
- **`yazses hotkey command <key>`** (+ `off`)** — bind a *second* hold key that forces
  command mode: while held, whatever you say is parsed as a command and **never typed
  as literal text** (an unrecognised phrase is ignored, not inserted). The dictation
  key keeps its current behaviour (text + command auto-detection). New `[hotkey]
  command_key` config (default `""` = single-key auto-detect); the daemon runs the
  command-key listener in a background thread and forces command interpretation in
  `core/daemon.py::_on_hold_end`. Must differ from the dictation key. `yazses hotkey
  show` now reports both keys. 8 new tests.

### Added — CLI usability
- **`yazses hotkey show/set`** — view or change the key you hold to talk
  (`right_alt`/`right_ctrl`/`space`/…) from the CLI; writes `[hotkey] key`
  preserving comments (`system/configedit.py`), then `yazses restart`.
- **`yazses features`** — a table of every capability and whether it's on/off, now with
  a **toggle name** and an **advice tier** (core / recommended / optional / experimental)
  so you can see what to turn on at a glance (`system/features.py`).
- **`yazses features enable/disable <name>`** — turn any capability on or off without
  hand-editing TOML; writes the right config key(s) preserving comments, then
  `yazses restart`. Experimental features (Cocktail Filter, Glance-Type) are refused
  unless `--force` is passed, with an explanation of why they're not advised yet.
- **`yazses vocab add/list/remove`** — manage a personal dictionary of words STT
  mis-hears (`~/.config/yazses/vocabulary.txt`); the daemon always merges these into
  Whisper's `initial_prompt` so hard names are spelled right (`system/vocabulary.py`).
- **`yazses restart`** — stop **all** daemons (including detached `yazses.main` ones
  that survive `systemctl`) and start exactly one. **`yazses start` now restarts**
  cleanly if a daemon is already running instead of spawning a duplicate — directly
  preventing the double-typing that duplicate daemons cause.

### Changed
- **Cocktail Filter (voice focus) default OFF and unenrolled-safe.** Live testing
  showed the 0.5 s-window personal-VAD gate false-rejects the user's *own* voice
  (~90% of speech dropped) — ECAPA is unreliable on sub-second windows. Documented in
  `design/v2-cognitive-layer/02-cocktail-filter.md`; revisit needs a real
  target-speaker model. `[cocktail]` stays dormant; the enrolled voiceprint is kept.
- New `[polyglot]` config section (was referenced but missing).

### Docs
- Synced documentation to the new CLI surface: `design/architecture.md` gains a
  `src/yazses/system/` section (`features.py`/`configedit.py`/`vocabulary.py`/
  `single_instance.py`/`updater.py`); `CLAUDE.md` lists the new commands + modules;
  `docs/cli-reference.md` adds the missing `yazses test`; `ROADMAP.md` records the
  CLI-usability batch.

## [1.1.0] — 2026-06-19

### Added — v2 perceptual/personalization layer (P1/P0 cores; all off by default)
First implementation increment of the four remaining v2 features (plans in
`design/v2-cognitive-layer/`). Each ships its dependency-free, fully-tested core now;
the model/sensor/training-dependent parts are behind optional extras and gated.
- **Shared `voiceprint/`** — speaker-embedding foundation (cosine similarity +
  per-frame target/non-target decision, `SpeakerEmbedder` Protocol, dormant factory).
  `[voiceprint]`, `voiceprint` extra (speechbrain).
- **Glance-Type P1** (`[gaze]`) — look-to-pane core: gaze→screen calibration
  (least-squares) + zone/window mapping. `gaze` extra (l2cs-net/mediapipe/opencv);
  webcam used in-RAM during a hold only (ADR-011).
- **Cocktail Filter P1** (`[cocktail]`) — personal-VAD gate: drops audio frames that
  aren't the enrolled target speaker before STT (reuses the voiceprint).
- **Voiceprint Mind P1** (`[personalize]`) — biasing prompt builder: composes
  `initial_prompt` from the user vocabulary + frequent personal corpus terms (no training).
- **Polyglot Switch P0** (`[polyglot]`) — LID routing scaffolding (pair parsing,
  dominant-language, code-switch detection); the CS adapter needs training and is gated.
- **Daemon wiring (now functional, off by default):** Cocktail Filter gates
  non-target frames in `_on_hold_end` before STT; Voiceprint Mind biases the STT
  `initial_prompt` from `YAZSES_VOCABULARY`. Model/sensor backends written —
  `voiceprint/ecapa.py` (speechbrain ECAPA) and `gaze/l2cs.py` (L2CS-Net) — imported
  only when their extra is installed; `doctor` reports each when enabled.
- **CLI + enrollment:** `yazses enroll-voice` records + saves your encrypted speaker
  voiceprint; `yazses gaze calibrate` checks the gaze backend. The daemon builds the
  embedder + loads the voiceprint at startup when `[voiceprint]`/`[cocktail]` enabled.
- **Docs:** the CLI reference gained a *v2 perceptual & personalization layer* section
  (commands, config, how-to per feature); `design/architecture.md` documents the new
  `voiceprint/`/`personalize/`/`gaze/`/`polyglot/` modules + `audio/personal_vad.py`.
- 47 new TDD tests (632 total). Still gated (need hardware/compute): the gaze
  hold-start window-routing, the LoRA personalization pipeline, and the code-switch
  adapter — all behind their LOFA/WER/MER gates.

### Added — recognise the spoken app name "YazSes"
- **Built-in STT vocabulary** (`stt/vocabulary.py`): the app's own coined name is
  always primed into Whisper's `initial_prompt` (via `merge_initial_prompt`), so
  dictating "YazSes" no longer mis-transcribes to "yes ses" / "yaz says". Merged
  ahead of any configured `[stt] initial_prompt` and the personalization vocab in
  `core/daemon.py::_effective_initial_prompt`.

### Improved — `yazses doctor`
- Now reports the **installed version** and **daemon status** (PID + live
  state/model over IPC), checks the **configured STT model** is downloaded
  (vs. fetched-on-first-use), and prints a **config summary** (active config file,
  resolved hotkey + hold time, STT-prompt status).
- New `--mic` flag: records a short ambient clip and warns when the resting room
  level meets/exceeds `accessibility.vad_threshold` (would pass noise as spurious
  transcripts). Points at `yazses mic-level` for speech-level calibration.
- 16 new TDD tests (648 total).

### Packaging — fixed
- `.gitignore` had an unanchored `overlay/` pattern (intended for snapcraft's
  build dir) that also matched `src/yazses/overlay/`; hatchling honours
  `.gitignore`, so the overlay package was silently dropped from the wheel and
  `yazses overlay` failed with `ModuleNotFoundError`. Anchored to `/overlay/`.

## [1.0.0] — 2026-06-19

**First stable release of the Python app — YazSes "Part 1".** Hold a key, speak,
release: fully offline voice dictation for Linux/macOS/Windows, now with eyes-free
read-back, a friendly CLI, an opt-in self-improvement loop, and a deep set of
accessibility + dictation features — all off-by-default and local-only (ADR-011).
This 1.0.0 marks the point where the Python line became the canonical YazSes; the
earlier Rust v1.0 exploration is archived on `archive/rust-hci-v1` (see the README's
*Two versions of YazSes*). The headline additions since 0.9.0:

### Added — Read-Back Loop (Python, `[tts]` + `[accessibility] read_back`)
- **Eyes-free dictation: YazSes can now speak the transcript back** through an
  offline neural TTS voice after each dictation (spec-read-back-loop, P1). Off by
  default; enable with `[tts] enabled = true` + `[accessibility] read_back =
  "final"`. New `yazses say "<text>"` command speaks arbitrary text on demand.
- New `src/yazses/tts/` module: `TtsBackend` Protocol, sentence chunking (streams
  audio sentence-by-sentence for low time-to-first-audio), `KokoroTtsBackend`
  (Apache-2.0 Kokoro-82M, default), `NullTtsBackend` + `build_tts` factory
  (dormant → None; enabled-but-unavailable → silent, never crashes).
- New optional `tts` extra (`kokoro-onnx`, `onnxruntime`, `soundfile`) — imported
  only when enabled (ADR-011). New `READBACK` daemon state; the recorder stays
  push-to-talk so TTS audio is never re-captured (echo-loop interlock), and a hold
  during playback barges in. Permissive engines only (GPL Piper fork / XTTS excluded).
- `status` now reports `read_back` and `tts_backend`; `readback_speak` IPC method.

### Fixed — reliability (Python)
- **No more double-typing from duplicate daemons.** A detached `yazses start`
  ran independently of the systemd unit, so two daemons could grab the hotkey and
  inject every dictation twice. The daemon now takes an exclusive single-instance
  `flock` (`~/.local/share/yazses/daemon.lock`) at startup and refuses to start if
  another already holds it — making the detached and systemd starts mutually
  exclusive. The kernel releases the lock on exit/crash, so it never wedges
  startup like a stale PID file could. (`system/single_instance.py`)

### Changed / Fixed — repository & release infrastructure (Python)
- **Repository: the Rust v1.0 HCI rewrite moved off `main`** to the
  `archive/rust-hci-v1` branch. `main` is now purely the Python app ("Part 1").
  The README gained a *Two versions of YazSes* section + capability table; the old
  `v1.0-dev` branch was deleted (fully contained in the archive branch).
- **CI: PyPI publishing restored.** The `publish-pypi` job's job-level
  `permissions:` block dropped `contents: read`, so `actions/checkout` couldn't
  clone the private repo ("repository not found", exit 128) — every release had
  silently failed since v0.5.1, freezing PyPI at 0.4.1. Added `contents: read` and
  a `workflow_dispatch` re-publish path. (PyPI Trusted Publisher registration is
  the remaining one-time account setup.)
- **CI: snap publish hardened.** A convenience "upload .snap artefact" step that
  fails when the Actions artifact-storage quota is full no longer sinks the job —
  the Snap Store publish now proceeds (`continue-on-error`). `snapcraft.yaml`
  version tracks the release. 0.9.0 published to the snap stable channel.

### Feature set at 1.0.0 (all off by default unless noted; fully offline)
- **Dictation core** — hold-to-talk, faster-whisper STT (`small.en` default),
  calibrated VAD, pre-speech padding, three-pass disfluency filter, continuation
  spacing; optional streaming transcription.
- **Accessibility** — enrollment wizard, mic-level calibration, **Dysfluency-Friendly
  Mode** (collapse stutters/prolongations; ADR-015), **Read-Back Loop** (eyes-free
  TTS; new this release).
- **Editing by voice** — command grammar (28+ intents) + optional SLM router,
  **Say-Macro**, **Mid-Thought Undo** ("scratch that"), **Punch-In** (re-speak to
  correct), **Prosody Ink** (pause→¶, emphasis→bold), custom vocabulary biasing.
- **Latency** — **Ghost Ahead** endpoint pre-warm.
- **Self-improvement** — opt-in encrypted learning corpus + `yazses tune` with
  held-out validation (ADR-012/014).
- **Reach** — SSH remote dictation, sonar voice-activity overlay, EMG/BLE silent-speech
  backend, optional offline LLM cleanup (ADR-013), Neovim/VS Code LSP context.
- **CLI** — friendly help (`-h` everywhere, examples, grouped panels, completion),
  `yazses update` self-update, `yazses doctor`/`logs`/`status`.

> The detailed per-feature history is in the v0.5.0–v0.9.0 sections below. Entries
> that previously sat under *Unreleased* describing the **Rust v1.0 HCI rewrite**
> (dual STT, on-device LLM agent, PersonalMemory, its pre-release docs/packaging)
> moved with that code to the `archive/rust-hci-v1` branch — see *Two versions of
> YazSes* in the README.

---

## [0.9.0] — 2026-06-19

### Added — CLI (Python)
- **`yazses update`** — check for a newer YazSes and install it. Detects how it
  was installed and checks the matching source (the tracked **snap** channel for
  snap installs, **PyPI** for pip / pipx / uv-tool), then upgrades only when the
  available version is strictly newer (never a downgrade). `--check` reports
  without installing; `--yes` skips the prompt. (`system/updater.py`)

### Improved — CLI usability (Python)
- **`-h` works everywhere** — every command and subcommand now accepts `-h` as
  well as `--help` (previously only `--help`).
- **Examples in help** — each command's `--help` ends with a copy-pasteable
  **Examples** block; `yazses --help` adds a top-level examples + completion guide.
- **Grouped help** — commands are organised into rich panels (Daemon, Setup &
  calibration, Dictation & correction, Remote, Learning & tuning) instead of one
  flat list.
- **Friendlier basics** — bare `yazses` shows help instead of an error;
  `--version` gains a `-V` short flag; `--install-completion` enables `<Tab>`
  completion for the shell.

### Fixed — install (Python)
- **`scripts/install-local.sh` now rebuilds same-version source changes** — busts
  the `uv` build cache and adds `--reinstall`, so editing source without bumping
  the version still reinstalls (previously the cached wheel was reused).

## [0.8.0] — 2026-06-19

### Added — accessibility
- **Dysfluency-Friendly Mode** (`[accessibility] dysfluency_friendly = true`, off by
  default; ADR-015). An opt-in collapse pass in the disfluency filter cleans atypical
  speech out of the final text: sub-word repetitions (`b-b-because` → `because`), short
  fragment runs (`b b because` → `because`), heavy unigram repeats (`the the the` →
  `the`), and prolongations (`sooo` → `so`) — while protecting proper nouns, code
  identifiers, URLs, intentional hyphenation (`re-read`), and emphasis (`very very`). The
  preset also widens pre-speech padding for delayed voice onset. Grounded in Lea et al.,
  CHI 2023 (endpoint + posthoc refinement, not retraining). Fully offline, no new
  dependency, no model training; default pipeline byte-identical. A pre-registered eval
  gate (`tests/test_dysfluency_eval.py`) enforces < 2% false-collapse on clean control
  and ≥ 60% recall on labelled dysfluency spans (measured: 0% / 92.9%). Fine-grained
  knobs under `[filters.disfluency]` (`collapse_repetitions`, `collapse_prolongations`,
  `prolongation_min_run`, `repetition_max_fragment_len`); `yazses doctor` reports status.
  Endpointing is intentionally out of scope (YazSes is hold-to-talk). 536 tests pass (+20).

## [0.7.0] — 2026-06-19

### Added — learning loop
- **Held-out validation for `yazses tune` proposals (ADR-014).** Each proposal is
  now corroborated against a recent, chronologically *held-out* slice of the
  corpus that it was **not** derived from, and `yazses tune` prints an explicit
  status per proposal: *validated (N/M held-out)* · *unverified — no held-out
  corroboration* · *unvalidated (corpus too small)*. Corroborated proposals sort
  first. This closes the self-evaluation gap where a proposal could look good only
  because it was fit to the same recordings it was then scored against (the
  train/test-overlap failure mode documented across the accountable-autonomy
  research corpus). New `analysis.analyze_validated()`; a leakage guard drops
  held-out events whose text duplicates a fit event; below 20 events the corpus
  is too small to split, so behaviour is unchanged except for an honest
  "unvalidated" label. Fully offline (ADR-011) — nothing new is captured or
  transmitted. 522 tests pass (+6).

## [0.6.0] — 2026-06-19

Python daemon runtime wiring for three v2 decision cores (Prosody Ink, Ghost
Ahead, Punch-In). All three are **off by default**; with the flags unset the
pipeline behaves exactly as 0.5.1. 507 tests pass (+40).

### Added — Prosody Ink Phase 1 (`[prosody] enabled`, off by default)
- Vocal prosody now shapes dictation formatting on the **batch** path (dictation
  only): a long inter-word pause becomes a **paragraph break** (Phase 1, no
  acoustic dep), and — with `format = "markdown"` and the new `prosody` extra —
  vocal emphasis becomes **bold**. `format = "none"` keeps the universal pause→¶
  whitespace and suppresses emphasis.
- New `FasterWhisperEngine.transcribe_words()` opt-in word-timestamp path (only
  used when `[prosody] enabled`, so non-prosody users never pay the
  `word_timestamps` decode cost) and `postprocess/prosody.py::annotate()` wired
  into `core/daemon.py::_on_hold_end`.
- New optional dependency group `prosody` → `praat-parselmouth` (Phase 2 emphasis
  degrades to pause-only when absent). Pitch→question stays excluded (unreliable).
- `ProsodyConfig` reconciled to the spec fields: `format`, `pause_paragraph_ms`,
  `emphasis_enabled`, `emphasis_sensitivity`, `max_latency_ms`.
- `yazses doctor` now reports whether the `prosody` extra (parselmouth) is
  importable when `[prosody] enabled` (WARN, not FAIL — pause→¶ works without it).

### Added — Ghost Ahead Phase 1 pre-warm (`[endpoint] enabled`, off by default)
- Endpoint anticipation now wired into the Python streaming poll loop: on a likely
  end-of-utterance (stable confirmed prefix + trailing silence) the daemon
  **pre-warms** the decode path. Pre-warm is harmless — it eagerly decodes the
  streaming buffer and discards the result; the **authoritative** transcript still
  happens on real hold-release, so a wrong guess can never truncate text.
- New building blocks: `StreamingEngine.prefix_stable_for_ms()` accessor,
  `audio/vad_calibrated.py::trailing_energy_falling()`, and an `EndpointAnticipator`
  debounce (anti-thrash). `EndpointConfig` gains `prewarm`, `speculative_finalize`
  (Phase 2, gated), `debounce_ms`, `prefix_stable_ms`, `falling_window_ms`.

### Added — Punch-In re-record + confirm (`[punch_in] enabled`, off by default)
- New `yazses punch-in` command (and `punch_in` IPC method): re-speak just the
  wrong phrase; the daemon records a short window, aligns it against the last burst
  it typed (`difflib`), then deletes that burst and retypes it corrected. `--dry-run`
  lists candidate spans to confirm first; `--choose N` applies a specific rank.
- `DictationLedger` now retains each burst's **text** (not just its char count) via
  `last_text()` / `replace_last()`, so Punch-In can align against — and update — the
  exact span, and a later "scratch that" still works. Buffer-ownership invariant
  preserved (only YazSes-injected text is ever tracked).
- New `PunchInConfig.record_seconds` (re-record window).

## [0.5.1] — 2026-05-31

### Fixed — systemd service no longer loses DISPLAY on reinstall
- **Root cause fixed**: the systemd user service had no mechanism to inherit
  `DISPLAY`/`XAUTHORITY` from the desktop session, so xdotool injection and the
  overlay both failed silently after every reinstall. Fixed with two artifacts
  that now ship in the deb and snap:
  - `contrib/yazses-session.desktop` — XDG autostart entry installed to
    `/etc/xdg/autostart/` (deb) that runs
    `systemctl --user import-environment DISPLAY XAUTHORITY …` at every graphical
    login, making `PassEnvironment` reliable across all desktop environments
    (GNOME, KDE, XFCE, etc.) without any manual steps.
  - `contrib/yazses.service` updated to `PassEnvironment=DISPLAY XAUTHORITY`.
- **Double overlay eliminated**: removed the superfluous `yazses-overlay.service`
  (the daemon already manages the overlay as a child process via
  `should_launch_overlay()`; a second service caused two overlay windows).
- **New `scripts/install-local.sh`**: one-command dev reinstall
  (`bash scripts/install-local.sh --with-overlay`) — stops, uninstalls, reinstalls
  via `uv tool`, installs the XDG autostart file, and starts the service.
- **snap**: bumped spec to v0.5.1; added `yazses-overlay` app entry and autostart
  file bundled into the snap.
- **`examples/config.example.toml`**: added `[overlay]` section so users discover
  the sonar-rings feature.

### Fixed — words glued together across dictation bursts
- Consecutive hold-to-talk utterances were injected back-to-back with no
  separator, so the last word of one burst fused with the first word of the next
  (`...words together` + `I mean` → `...words togetherI mean`) — worst at sentence
  ends. The daemon now prepends a separating space when a dictation continues a
  recent burst, suppressing it before closing punctuation (`, ! ? ; : )`) so you
  still get `word.` not `word .`. New `[injection] continuation_window_ms`
  (default `30000`, `0` disables). Implemented in `postprocess/spacing.py`.

### Added — offline LLM dictation cleanup (Python parity, ADR-013)
- `postprocess/llm_cleanup.py` — `LlmCleaner` / `build_cleaner()` for optional
  offline LLM reformatting of transcribed text. Opt-in via
  `[filters.disfluency] llm_enabled = true`. Length-ratio + token-preservation
  guards reject unsafe rewrites. Brings Python daemon to parity with the Rust core
  on the LLM cleanup path.

### Added — learning loop: post-dictation correction signals (ADR-012)
- **Inferred corrections from re-dictation** (no keystroke logging): `yazses tune`
  detects when a follow-up utterance opens with a self-correction trigger ("scratch
  that", "no wait", …) or closely re-dictates the previous one, and treats the
  follow-up as an implicit correction. Persisted as `edit_signal`.
- **Opt-in editor edit capture** (`[learning] capture_edits = true`): a short delay
  after dictation, YazSes reads the editor line back via an editor bridge and
  records any in-place fix you made. **No global keystroke capture** — editor
  read-back only; currently Neovim via a `--listen` socket (`[learning]
  editor_socket`). New config keys: `capture_edits`, `edit_capture_delay_s`,
  `editor_socket`.

### Added — release tooling
- `scripts/patch-release-shas.sh` — downloads CI release assets, computes SHA256s,
  and patches Homebrew formula + winget manifests in one command:
  `bash scripts/patch-release-shas.sh 1.0.0`
- `apt-repo.yml` now triggers on both "Release" (Python) and "Rust Release"
  workflows, so v1.0 `.deb` packages publish automatically on tag push.

---

## [0.5.0] — 2026-05-29

### Added — futuristic voice-activity overlay (`yazses-overlay`)
- **Sonar overlay**: a standalone process that draws neon "sonar" rings near the
  cursor that expand and pulse with your **live voice level** while you dictate —
  visible feedback that you're talking to your machine. The window is frameless,
  always-on-top, and fully click-through, so it never interrupts typing.
- **Daemon-agnostic**: it's a thin IPC client that polls the daemon's `status`
  RPC, so **either** the Python or the Rust daemon drives it. Both daemons now
  report `audio_level` (live `mean(|samples|)` while recording) and
  `vad_threshold` in their `status` response.
- **`yazses overlay`** command runs it in the foreground (preview/debug); set
  `[overlay] enabled = true` to have the daemon auto-launch it when a display is
  present (X11/Wayland; headless sessions never spawn it).
- New `[overlay]` config section: `enabled`, `style`, `position`
  (`cursor`/`bottom_center`/`top_center`/`corner`), `react_to_voice`, `accent`,
  `size_px`, `fps`, `cursor_offset_px`.
- Requires the optional `overlay` extra (PySide6): `uv sync --extra overlay` or
  `pip install 'yazses[overlay]'`. Core/headless installs are unaffected.

### Added — opt-in self-improvement loop (ADR-012)
- **Local learning corpus**: with `[learning] enabled = true`, each dictation
  event (every text stage + optional source audio) is captured to a local,
  **encrypted** store at `~/.local/share/yazses/` so YazSes can be tuned against
  your real usage. **OFF by default** (honours ADR-011): nothing is captured,
  nothing leaves the machine, and re-transcription runs locally. AES-256-GCM with
  a machine-bound key file (`corpus.key`, `0600`).
- **`yazses tune`** — analyses the corpus and proposes concrete, reviewable
  config diffs: Whisper `initial_prompt` vocabulary, `vad_threshold`, STT model,
  disfluency rules, and SLM few-shot examples. Dry-run by default; `--apply`
  writes approved changes to `config.toml` (comments preserved). `--retranscribe`
  re-runs captured audio through a larger model to find errors automatically.
- **`yazses mark-wrong [-c "what you said"]`** — flag the last dictation as a
  misrecognition (a high-signal training label).
- **`yazses corpus status | forget --minutes N | destroy --i-mean-it`** — inspect
  and manage the corpus (verbs mirror the Rust `memory_*` API).
- New `[stt] initial_prompt` config key — vocabulary primed into Whisper; now
  wired into the batch transcribe path.
- New `[learning]` config section: `enabled`, `capture_audio`, `retention_days`,
  `max_corpus_mb`, `tune_model`, `redact_patterns`.

### Added — diagnostic logging, `logs` command, install docs
- **Persistent diagnostic log**: the daemon now writes a rotating log to
  `~/.local/state/yazses/log/daemon.log` (1 MB × 3) in addition to the console,
  so `yazses start` / the systemd service leave a record. **Metadata only** at
  INFO — audio level, decode latency, model, char/word counts, and errors; the
  transcript text appears only at `log_level = "DEBUG"`.
- **`yazses logs`** command to view the diagnostic log (`-n` lines, `--path`).
- Each transcription logs `Transcribed Ns audio in M ms (model …, level …)`; the
  inject line is now `Injecting N chars, M words` (no text) at INFO.
- **`docs/install-linux.md`** — global install (`uv tool`/`pipx`) + systemd user
  service (with the `DISPLAY`/`XAUTHORITY` requirement for X11 injection).
- **`docs/cli-reference.md`** — full command reference including `mic-level` and
  `logs`.

### Fixed — microphone open resilience
- `AudioRecorder.start()` now retries opening the input stream up to 3× with a
  short backoff instead of failing on the first transient PortAudio/PipeWire
  "device busy" error — recovers automatically where previously a daemon restart
  was needed. `stop()` no longer raises if the stream is already torn down, and
  the daemon catches an unavailable mic, logs it, records `last_error`, and
  returns to `IDLE` rather than getting stuck in `RECORDING`.

### Added — VAD threshold calibration
- **`yazses mic-level`** command: records a few seconds, reports your average mic
  level against the current `accessibility.vad_threshold`, and recommends a
  threshold (half your measured speech level, floored at `0.002`). `--set` writes
  it to `config.toml` in place, preserving comments. Fixes the case where quiet
  speech is silently discarded by a too-high threshold (e.g. a noisy
  `yazses enroll` calibration, or low late-night speaking volume).
- The `Silent audio -- discarding` log now includes the measured level, the
  active `vad_threshold`, and a pointer to `yazses mic-level --set`.

### Changed — reliable defaults
- **Live streaming injection disabled by default** (`[streaming] enabled = false`).
  The correction-on-commit path selected the streamed partials with `shift+Left`
  and overtyped them on key-release; in apps where `shift+Left` is not "extend
  selection" this deleted the dictated text instead of replacing it. Batch
  transcribe-on-release is the reliable, higher-accuracy pattern used by
  nerd-dictation and faster-whisper-dictation. Re-enable with
  `[streaming] enabled = true`.
- **Default STT model changed `tiny.en` → `base.en`.** Benchmarked on an
  i7-1370P: `tiny.en` made frequent word errors ("brown"→"round", "writes"→
  "rides"), while `base.en` transcribed the sample perfectly at ~10× realtime
  (~0.8 s decode). Override via `[stt] model = "..."`.

---

## [1.0.0-dev.5] — 2026-05-18

### Changed — Feature-complete merge to main

- Merged `v1.0-dev` branch into `main`; the Rust core is now the default
  development track alongside the preserved Python v0.4.x pipeline.
- `v1.0-dev` branch remains for ongoing development work.
- 94 Rust tests pass; zero warnings; full CI green on Linux + macOS.

### Tags
- `v1.0.0-dev.5` — merge commit on `main` (9a881bc)
- `v1.0.0-dev.4` — last commit on `v1.0-dev` pre-merge (098a67f)

---

## [1.0.0-dev.4] — 2026-05-18

### Added — Agentic OS actions, protocol completeness, memory, observability

**Dispatcher OS actions** (all formerly stubs, now real implementations)
- `open_file`: `xdg-open <path>` spawned asynchronously.
- `git_commit`: `git commit -m <message>` with SHA extraction from stdout.
- `app_launch`: direct process spawn → `xdg-open` fallback.
- `window_focus`: `wmctrl -a` → `xdotool search --name windowfocus` fallback.
- `volume_set`: `wpctl set-volume @DEFAULT_AUDIO_SINK@` → `pactl` fallback (0–100%).
- `media_play_pause`: `playerctl play-pause` → `xdotool key XF86AudioPlay` fallback.
- `screenshot_named`: `grim` (Wayland) → `scrot` (X11) → `gnome-screenshot`; creates `~/Pictures/`.
- `note_quick`: async append to `~/notes.md` with ISO-8601 timestamp heading.
- `time_set_timer`: `tokio::spawn` + `tokio::time::sleep` + `notify-send` (returns immediately).
- `dismiss_notification`: `dunstctl close` → `notify-send -t 100 " "` fallback.
- `goto_symbol`: `nvim --server $NVIM --remote-send '/<symbol><CR>'` when `$NVIM` set.
- `mode_switch`: logged, daemon mode wiring reserved for next release.
- `inject_key_sequence` on Wayland now uses `wtype -k <key>` per key → `ydotool` fallback.

**LLM protocol** (FR-19, ADR north-star commitment 5)
- `Tier` enum (`Fast` | `Deep`) added to `LLMRequest`; `Tier::Fast` default.
- All backends bail on `Tier::Deep` with a clear "reserved for v2" message.
- `OpenAICompatibleBackend`: opt-in cloud backend, feature-gated `openai-compatible`;
  never active in default config (NFR-SEC03, production readiness S-06).

**Personal memory** (production readiness R-06, Op-04)
- `OnnxEmbedder` now fully implemented: `tokenizers` crate tokenization → ONNX inference
  → mean-pool over non-padding tokens → L2-normalize to 384-dim unit vector.
- Passphrase lockout: 5 wrong attempts trigger a 15-minute cooldown (`AtomicU32`
  failure counter + `Mutex<Option<Instant>>` lockout window; R-06).
- `yazses memory destroy --i-mean-it`: permanently deletes `memory.db` (Op-04).

**Observability** (NFR-O01, NFR-O02, O-03, O-04)
- `LatencyTracker`: 100-sample `VecDeque<u64>` sliding window; P50/P95 computed on demand.
- `yazses status` now reports `latency_p50_ms`, `latency_p95_ms`, and `turn_count`.
- `yazzes bugreport`: packages `daemon.log` + `~/.config/yazses/` + `version.txt`
  into `~/yazses-bugreport-<unix-ts>.tar.gz` (O-04).
- Silero VAD v4 feature gate (`--features silero`) added to `yazses-audio`: wraps
  Silero ONNX model with stateful h/c tensors; `is_speech()` per 512-sample chunk.

---

## [1.0.0-dev.3] — 2026-05-18

### Fixed — End-to-end pipeline stabilisation

- **Whisper verbose stdout** suppressed: `whisper_rs::install_logging_hooks()` +
  `tracing_backend` feature redirect all whisper.cpp/GGML C-level output through
  Rust `tracing` (silent at INFO, available at TRACE/DEBUG).
- **WhisperState reuse**: `WhisperState` is now created once in `WhisperBackend::new()`
  and held in a `tokio::sync::Mutex`, eliminating ~230 MB buffer re-allocation
  (kv-cache + encode/decode scratch) on every transcription call.
- **Word spacing**: `inject_text()` now appends a trailing space so consecutive
  dictation utterances do not concatenate in the target window.
- **xdotool character drop**: added `--delay 12` to `xdotool type` to prevent
  characters being dropped on fast typematic repeat.
- **LLM system prompt**: replaced vague prompt with explicit JSON-only instruction
  showing the model exactly what format to return for dictation vs. command intents;
  eliminates null `message.content` errors that caused fallback to raw transcript.

---

## [1.0.0-dev.2] — 2026-05-18

### Added — Distribution infrastructure (Phase 7, commit 85809fd)
- `.github/workflows/rust-ci.yml`: cargo test + clippy + fmt on every push/PR
  (Ubuntu 22.04 + macOS 14 matrix).
- `.github/workflows/rust-release.yml`: cross-platform binary releases on
  `v1.*` tags — Linux x86_64 + aarch64 (via `cross`), macOS arm64 + x86_64,
  Windows x86_64 MSVC; `.deb` (cargo-deb) and `.rpm` (cargo-generate-rpm)
  uploads to GitHub Release.
- `[workspace.metadata.dist]` cargo-dist 0.28 config for 5 targets; Homebrew
  tap `MSKazemi/homebrew-tap`.
- `packaging/homebrew/yazses-formula.rb`: Homebrew CLI formula template
  (SHA256 placeholders; patched by `brew bump-formula-pr` after CI builds).
- `packaging/winget/manifests/m/MSKazemi/YazSes/1.0.0-dev.1/`: winget
  version + locale + installer manifests (SHA256 placeholder; patched after
  CI produces the Windows zip).

### Fixed
- `.gitignore`: add `doc/` (cargo doc output) and SOTAForge research paths
  (`docs/research/`, `docs/vision/`, `docs/prd/`, ADR draft globs).

---

## [1.0.0-dev.1] — 2026-05-18

v1.0 is a full ground-up rewrite in **Rust** (Rust-core + Python-plugin
architecture, adr-001). The Python v0.4.x pipeline is preserved and continues
to operate via `uv run yazses`. The Rust core is tracked on the `v1.0-dev`
branch; Phase 7 (cargo-dist packaging) will produce the first distributable
binaries.

### Added — Rust core (`v1.0-dev` branch, Phases 0–6)

**Phase 0 — Foundations** (commit a452ad7)
- `crates/yazses-ipc`: JSON-RPC 2.0 over Unix socket / named pipe; `handler!`
  macro, `SyncIpcClient` (adr-010).
- `crates/yazses-core`: 9-state daemon state machine (`DaemonState`); full
  daemon orchestrator with tokio event loop; PID file + SIGTERM/SIGINT shutdown.
- `crates/yazses-cli`: Rust `yazses` binary preserving all v0.4 subcommands
  (`start`, `stop`, `status`, `doctor`, `inject`, `remote`, `enroll`, `model`,
  `memory`, `test`) via `clap`.

**Phase 1 — Input + Audio** (commit 3735c4d)
- `crates/yazses-inputs`: `InputBackend` Protocol (adr-005); `HoldDetector`
  state machine; `KeyboardHoldBackend` (Linux evdev 0.13, cfg-gated);
  `EmgYespBackend` (YESP serial, feature `emg`); `MockInputBackend`.
- `crates/yazses-audio`: `AudioCapture` (cpal 0.17, stereo→mono, f32/i16/u16);
  `VadGate` (RMS); `PaddingBuffer` ring buffer.

**Phase 2 — STT** (commit cac7321)
- `crates/yazses-stt`: `STTBackend` Protocol (adr-002); `STTRouter`
  (duration-based dispatch, default threshold 4 s); `MoonshineV2Backend`
  (PyO3, feature `moonshine`); `WhisperBackend` (whisper-rs, feature
  `whisper`); `MockSTTBackend`.

**Phase 3 — LLM + Constraint** (commit 1987ab2)
- `crates/yazses-llm`: `LLMBackend` Protocol (adr-003); `LlamaCppBackend`
  (llama-cpp-2, feature `llama-cpp`); `OllamaBackend` (reqwest); `MockLLMBackend`.
- Tool registry (adr-004): all 20 v1.0 tools with JSON Schema parameters.
- GBNF grammar compiler: 100% syntactic tool-call validity by construction.

**Phase 4 — Editor Bridges** (commit 4006852)
- `crates/yazses-editors`: `EditorBridge` Protocol + `EditorContext` with
  `to_initial_prompt(224)` and `to_llm_block()` (adr-006).
- Five-tier `WindowDetector`: Hyprland IPC → Sway IPC → wlr-foreign-toplevel
  → X11 EWMH → Null.
- `NeovimBridge` (nvim-rs 0.9, `neovim` feature); `VSCodeBridge` (TCP push,
  `vscode` feature).

**Phase 5 — Memory + Dispatcher + Orchestration** (commit 4d5ee68)
- `crates/yazses-memory`: SQLite BLOB-based L2 KNN (O(n)); `PersonalMemory`
  with commit / recall / forget_last / sweep_expired; PBKDF2-HMAC-SHA256 key
  derivation (256k iterations, getrandom); SQLCipher feature gate (adr-007);
  ONNX BGE-small-en stub (`onnx` feature).
- `Dispatcher`: routes all 20 LLM tool calls; memory tools fully implemented.
- `daemon.rs`: full pipeline wiring — InputEvent → HoldStart/HoldEnd →
  STTRouter → TranscriptReady → LLM → ToolCallReady/DispatchComplete → Idle;
  memory IPC handlers (`memory_commit`, `memory_recall`, `memory_forget`).

**Phase 6 — Onboarding + Doctor + Accessibility** (commit 84c6d2d)
- `yazses doctor` (Rust, FR-22): keyboard capture (evdev group), microphone
  (ALSA cards), session type, injection tools, model cache, config dir,
  screen reader check, Talon coexistence (auto-creates
  `~/.talon/user/yazses_coexist.talon`); exits 1 on failures.
- `yazses enroll` (Rust): VAD calibration wizard — 20 Harvard Sentences,
  noise floor/pause analysis, percentile derivation, TOML config write;
  injectable `AudioRecorder` trait.
- `config.rs`: `config_dir()`, `config_file()`, `data_dir()`,
  `memory_db_path()`, `salt_path()` (cross-platform).
- `crates/yazses-atspi`: Linux AT-SPI announcer (spd-say → espeak-ng →
  espeak → silent); `probe()` + `announce()`.
- `crates/yazses-nvda`: Windows NVDA controller DLL + SAPI/PowerShell
  fallback (cfg-gated `libloading`); non-Windows no-op.
- **85 Rust tests** across 9 crates; zero warnings.

---

## [0.4.2] — 2026-05-17

### Fixed

- **`yazses doctor`**: Wayland-only tools (`ydotool`, `wtype`, `wl-copy`) now
  show `[SKIP]` on X11 sessions instead of `[FAIL]`, and vice versa for X11
  tools on Wayland. Config dir is auto-created on first run.
- **CI — test job**: added explicit `python-version: "3.12"` to `setup-uv@v5`;
  missing Python version was the root cause of 16-second test job failures on
  every release tag.
- **CI — release workflow**: merged `build-deb` + `github-release` into a
  single `release-linux` job, eliminating the cross-job artifact transfer that
  caused "Artifact not found for name: deb-package" errors.
- **CI — PortAudio**: install `libportaudio2` on Linux runners; deferred the
  `AudioRecorder` import in `enroll.py` to the `recorder_factory is None`
  branch so mock-injected tests never trigger sounddevice's module-level
  PortAudio load.
- **CI**: `setup-uv@v3` → `setup-uv@v5` across all workflows.

---

## [0.4.1] — 2026-05-17

Wireless EMG, model downloads, VS Code context bridge, and dependency refresh.

### Added

- **BLE EMG backend** (`BLEEMGBackend`) — same YESP message protocol as the
  USB serial backend but over Bluetooth LE using the Nordic UART Service.
  Configure with `[emg] ble_address = "AA:BB:CC:DD:EE:FF"`. Optional dep:
  `pip install 'yazses[ble]'` (bleak 3.0.2).
- **`yazses model list`** — lists available GGUF models for Tier 2 SLM
  routing with download status and size.
- **`yazses model download <id>`** — downloads a GGUF model to
  `~/.cache/yazses/models/` with a progress bar. Supported models:
  `qwen2.5-0.5b` (397 MB, recommended) and `phi3-mini` (2.2 GB).
- **`VSCodeBridge`** in `LspContextProvider` — reads `vscode-context.json`
  written by the YazSes VS Code companion extension. Auto-detected in
  `lsp_editor = "auto"` mode alongside Neovim. Set `lsp_editor = "vscode"`
  to prefer it explicitly.
- **`EmgConfig.ble_address`** config field — new `[emg]` key for wireless
  EMG devices; set either `device_port` (USB) or `ble_address` (BLE).

### Fixed

- **snap**: added `python3-pip-whl` to `stage-packages` — fixes the
  snapcraft prime build on some core24 builder configurations where the
  Python plugin's shebang fix helper could not find pip's wheel.

### Changed

- All dependencies updated to latest stable (2026-05-17):
  `numpy 2.4.5`, `platformdirs 4.9.6`, `pyobjc-framework-* 12.1`,
  `pywin32 311`, `Pillow 12.2.0`, `llama-cpp-python 0.3.23`, `pygls 2.1.1`,
  `pynvim 0.6.0`, `bleak 3.0.2`, `pytest 9.0.3`, `pytest-mock 3.15.1`.
- Added `pytest-cov 7.1.0` to dev dependencies.

---

## [0.4.0] — 2026-05-17

Three new capabilities from the second SoA2Prod innovation pipeline
(`design/research/studies/yazses-future-voice-hci/`), plus full ADR documentation for all
v0.4.0 architectural decisions.

### Added

- **cap-001 Offline SLM intent routing** — Tier 2 grammar classifier using
  `llama-cpp-python` (optional). When the Tier 1 regex grammar returns
  DICTATE, a locally-quantised GGUF model (Phi-3-mini-Q4 or TinyLlama-Q4)
  classifies the transcript using natural phrasing — "close this tab" and
  "save file now" both resolve to the same intent. Disabled automatically when
  `[commands] slm_model_path` is unset or the GGUF file is absent. Install
  optional dep group: `pip install yazses[slm]`.
- **cap-002 LSP code context injection** — `LspContextProvider` reads the
  active editor's language, scope chain, and recent identifiers via the
  Language Server Protocol and injects the result into the faster-whisper
  `initial_prompt`, improving recognition of code-specific vocabulary. Neovim
  is supported via `pynvim`; VS Code companion extension is planned for
  v0.4.1. 50 ms hard timeout — never blocks the audio pipeline. Enable with
  `[commands] lsp_enabled = true`. Install: `pip install yazses[lsp]`.
- **cap-003 EMG silent speech backend** — `EMGBackend` implements the
  `HotkeyBackend` protocol over USB CDC serial (YESP protocol, 115200 baud).
  Open-plan office users can articulate commands silently into an EMG device
  (OpenBCI, DIY Arduino, or any YESP-compatible hardware) and have them
  dispatched through the same grammar/injection pipeline as acoustic voice.
  Configure via `[emg] device_port`. Install: `pip install yazses[emg]`.
- **YESP protocol spec** (`docs/emg-protocol.md`) — hardware-agnostic ASCII
  message protocol for EMG devices. Any firmware developer can add YazSes
  compatibility by implementing 2–5 ASCII message types.
- **ADR-v04-001** — llama-cpp-python as Tier 2 SLM inference backend
  (`docs/adr/adr-v04-001-slm-inference.md`).
- **ADR-v04-002** — pygls + pynvim for LSP context extraction
  (`docs/adr/adr-v04-002-lsp-context.md`).
- **ADR-v04-003** — USB CDC serial with YESP for EMG devices
  (`docs/adr/adr-v04-003-emg-serial.md`).
- `FasterWhisperEngine.transcribe()` now accepts an optional `initial_prompt`
  parameter passed through to the underlying faster-whisper model.
- `grammar.classify()` now accepts an optional `slm_router` parameter; when
  provided, it is called after Tier 1 regex fails before returning DICTATE.
- New config fields: `[commands] slm_model_path`, `slm_confidence_threshold`,
  `lsp_enabled`, `lsp_editor`; new `[emg]` section with `device_port`,
  `baud_rate`, `mode`, `command_map`. All fields have defaults; existing
  configs load without changes.
- `pyproject.toml` optional dep groups: `slm`, `lsp`, `emg`, `all`.

### Changed

- `grammar.classify()` signature extended with optional `slm_router` kwarg
  (backward-compatible; existing callers unaffected).

---

## [0.3.1] — 2026-05-17

### Fixed

- **Snap runtime** — launcher commands now export `PYTHONPATH` pointing to the
  bundled site-packages (`$SNAP/lib/python3.12/site-packages`) via explicit
  wrapper scripts. Previously, `yazses`, `yazses-daemon`, and `yazses-tray`
  would fail silently inside the snap because the Python plugin does not
  automatically propagate the install-time path at runtime.

### Changed

- **Project renamed** from `novavoice` / `NovaVoice` to `yazses` / `YazSes`
  across all source files, docs, and packaging manifests.
- Snap store metadata added: `title`, `contact`, `license`, `website`,
  `source-code`, `issues`.

---

## [0.3.0] — 2026-05-14

### Added

- **cap-001 SSH/Remote voice forwarding** — `yazses remote <host>` forwards
  voice typing to a remote machine over SSH reverse tunnelling. Audio is
  captured locally; only the transcript travels over the network. Introduces
  `yazses-agent` entry point (lightweight injector daemon for the remote
  side) and `RemoteForwarder` / `RemoteInjectorProxy` classes.
- **cap-002 Streaming transcription + correction** — `StreamingEngine`
  implements LocalAgreement (emit only the stable common prefix between
  consecutive decode results). `StreamingInjector` tracks how many characters
  were injected as partials and selects them back with `Shift+Left × N` on
  commit, replacing them with the final transcript.
- **cap-003 Code command grammar** — regex-based classifier recognises 28+
  voice command intents (undo, save, delete N words/lines, go to line N, go to
  function X, etc.) with precision ≥ 90% and zero false positives on a
  500-word dictation corpus. Profile system allows per-editor customisation.
- **cap-004 Offline disfluency filter** — three-pass filter: filler-word
  removal (word-boundary regex, identity-token guard), consecutive 2-gram
  deduplication, and self-correction rollback ("scratch that" removes text back
  to the last sentence boundary). Runs in < 10 ms.
- **cap-005 Accessibility profile** — `yazses enroll` wizard records 20
  utterances and derives `vad_threshold` and `min_silence_ms` tuned to your
  voice. `PreSpeechRingBuffer` prepends the last N ms of audio to each
  recording to recover voice-onset that a hard VAD gate would otherwise clip.
  Calibrated VAD uses `config.accessibility.vad_threshold` instead of the
  hardcoded 0.01.
- `inject_key_sequence(keys)` method on `InjectorBackend` protocol and all
  platform injectors (Linux: xdotool/ydotool/wtype; macOS: CGEventSetFlags;
  Windows: SendInput+VK) plus all inject/ module backends.
- New IPC methods: `remote_start`, `remote_stop`, `remote_status`,
  `enroll_start`, `streaming_enable`, `streaming_disable`.
- New `TrayState` values: `REMOTE_SETUP`, `REMOTE_ACTIVE`, `ENROLLING`.
- New config sections: `[streaming]`, `[filters.disfluency]`,
  `[accessibility]`, `[commands]`, `[remote]`. All fields have defaults;
  existing config files load without changes.

## [0.2.0] — 2026-05-08

First cross-platform release. YazSes now runs on Linux, macOS, and Windows
from a shared codebase with platform-specific backends.

### Added

- **macOS** support: `CGEventTap` for the global hotkey, `CGEvent` Unicode
  injection, `launchd` autostart plist, `rumps` menu-bar tray. Default hotkey:
  Right Option. Ships as an unsigned `.dmg` built on `macos-latest` CI.
- **Windows** support: `WH_KEYBOARD_LL` low-level keyboard hook, `SendInput`
  Unicode injection (UTF-16 with surrogate-pair handling), per-user named-pipe
  IPC, `pystray` tray, HKCU\Run autostart. Default hotkey: Right Ctrl
  (deliberately *not* Right Alt to avoid AltGr collisions on international
  layouts). Ships as an unsigned Inno Setup `.exe` installer.
- **Platform abstraction layer** (`src/yazses/platform/`) — Protocol-based
  interfaces for hotkey, injector, lifecycle, IPC, permissions, paths, and
  tray. New platforms slot in as sibling packages.
- **JSON-RPC IPC** (`src/yazses/ipc/`) over Unix socket on Linux/macOS and
  named pipe on Windows. Used for daemon ↔ CLI ↔ tray communication.
- **Cross-platform tray application** (`yazses-tray` console script /
  `--tray` mode) that polls the daemon and reflects state in the menu bar.
- **`__main__.py` mode dispatch** (`--daemon | --tray | --cli`) so a single
  PyInstaller binary can play any of the three roles inside an `.app` /
  `.exe` bundle.
- **CI matrix** extended to `[ubuntu-latest, macos-latest, windows-latest] ×
  [Python 3.11, 3.12]`.
- **Build-and-package workflows**: `build-macos.yml` and `build-windows.yml`
  produce unsigned installers on tag push, on relevant PRs, and via manual
  dispatch.
- **Install docs** for macOS (`docs/macos-install.md`) and Windows
  (`docs/windows-install.md`) covering Gatekeeper / SmartScreen bypass,
  permission grants, troubleshooting, and uninstall.

### Changed

- `yazses status` queries the daemon over IPC and reports `state`,
  `hotkey`, `model`, `injection_backend`, `uptime_s`, and `last_error`. Falls
  back to PID-file inspection if IPC isn't yet reachable (covers the few
  seconds during model load).
- `yazses doctor` now delegates platform-specific checks to
  `platform.permissions` and prints a per-OS report.
- The hotkey is configurable per platform with the new `key = "auto"` value
  resolving to the OS default.
- `pyproject.toml` runtime deps use `sys_platform` env markers so a single
  `pip install yazses` pulls only the right backend libraries.

### Backwards compatibility

- Linux v1 behavior is unchanged for end users. `yazses start`, the
  systemd unit, and the existing `.deb` / apt / snap / PPA install paths all
  continue to work.

### Notes

- macOS and Windows builds in v0.2.0 are **unsigned developer previews**.
  Users see Gatekeeper / SmartScreen warnings on first launch; the install
  docs walk through the bypass. Code signing + Apple notarization land
  before public beta.

## [0.1.2] — 2026-05-07

Linux V1 release — see git history for the V1 design and implementation
notes (`refactor: introduce platform abstraction layer` is the boundary
between V1 and V2 in the log).
