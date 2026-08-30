# Changelog

All notable changes to YazSes are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed — a byte-order mark threw away every setting in `config.toml`

`tomllib` rejects a leading BOM. A TOML document parses as a whole, so the failure was
not the first line — it was the **entire file**: `load_config` fell back to defaults
for the model, the hotkey, the VAD threshold, the injector, everything, and reported

    could not be read (Invalid statement (at line 1, column 1))

about a line that looks perfectly correct on screen, because the bytes are invisible.
Dictation then behaves as though the user had never configured it.

This is an ordinary Windows file. Windows PowerShell 5.1 — the default shell there —
writes UTF-8 **with** a BOM from `Set-Content` and `Out-File`, and "UTF-8 with BOM" is
still an offered encoding in Notepad and Visual Studio.

Every hand-edited TOML the project reads was affected: `config.toml`, the macros file,
the style-rules file, and the copy `yazses report` puts in a diagnostic bundle — the
last being what someone sends when nothing works, so it would have pointed every
reader at the wrong problem. All four now go through `yazses.tomlio`, which strips a
leading BOM and changes nothing else: an invisible encoding artefact stops being a
syntax error, while a real one still is. `system/configedit.py` reads `utf-8-sig`, so
`features enable` / `hotkey set` / `audio use` repair a file that already had a BOM
instead of writing it back.

### Fixed — a byte-order mark silently disabled the first vocabulary entry

The same encoding artefact, in the other hand-edited file. `~/.config/yazses/vocabulary.txt`
is line-oriented, so a BOM costs one entry rather than the document — and it is always the
*first* one, the word the user cared enough about to add before any other.

It then fails three ways at once and looks correct in all of them. `"\ufeffKubernetes"`
renders identically to `Kubernetes` in `yazses vocab list`; `yazses vocab remove Kubernetes`
does not match it, so it cannot be taken out; and it reaches Whisper's `initial_prompt` as a
token the model has never seen, so priming that word — the entire point of the file — quietly
stops working while the entry sits there in plain sight.

`load_vocab` now decodes `utf-8-sig` on both its strict and its tolerant path, and
`parse_vocab` strips a BOM from imported text, since `yazses vocab import` reads a file
someone else exported and sent on. Invalid bytes still warn and degrade rather than raise,
which is what keeps dictation running. Adding a word rewrites the file without the BOM, so
one `vocab add` repairs it.

### Fixed — the egress inventory listed transports and no installers

ADR-019 exists because "nothing leaves this machine" is only as strong as a complete
list of the exceptions, and it is enforced rather than written down: a module that
gains an outbound primitive fails the build until it is registered and classified.

Its spawn scan looked for `ssh`, `curl`, `wget`, `git` — transports. It listed no
package manager, so the two modules that fetch code and then **run** it were invisible
to every scan in the file:

* `system/deps.py` runs `uv pip install` so `yazses features enable <name>` can fetch
  that feature's extras from PyPI;
* `system/setup.py` runs `sudo apt-get install` for ydotool and wl-clipboard;
* `system/updater.py` spawns the upgrade itself — `snap refresh`, `pip install
  --upgrade`, winget/choco/scoop. Its existing row covered reading the version
  *string*; the download that follows a yes was undeclared.

Downloading code to run is the largest thing that can cross this wire, and it was the
one class of program the list omitted. All three are now registered and in the ADR
table. The scan matches a tool name inside a **list literal** — the shape an argv has —
because matching any string constant would declare `windowctl/focus.py` a spawner of
`snap` on the strength of `("snap", "center")`, and a false row in a published table
costs more than a narrow rule. Every module the looser rule found is still found.

Four of the seven inventories — `FETCH`, `SHELL_OUT`, `LOCAL_IPC`, `LOCAL_BOUND` — had
no check that their modules appear in the ADR at all; only `SEND`, `HANDOFF` and
`DEPENDENCY_FETCH` did. The cross-check is now derived from the inventories rather than
written one per inventory, with a second test that fails if a new inventory is added
without joining it. ADR-019 already records this exact failure one level up: a
hand-written "seven" that had been five for months.

### Fixed — the analytics ban only saw dependencies a reviewer could already see

`checkDependencyPolicy` forbids analytics and crash-reporting SDKs anywhere, and
network libraries outside `:model`. Its own file opens by saying why the build has
to decide this rather than a reviewer: "an SDK three levels down can add INTERNET
and phone-home behaviour that no reviewer spots in a diff."

It read `conf.dependencies` — the artefacts each module names in its own build
file. So a banned SDK written into a build file failed the build, and the identical
SDK arriving transitively did not: exactly the case the gate was written for was
the case it could not see. Measured: `org.opentest4j` is on `:core:contract-test`'s
runtime classpath via junit-jupiter, and banning it changed nothing.

It now walks the resolved graph of every runtime classpath — those are what ships
and what can phone home — and reports the artefact against each module carrying it.
All 22 subprojects resolve. It also refuses to pass on nothing: a run that resolved
no dependencies checked nothing, and reads exactly like a clean build, so it now
fails saying so.

### Fixed — a wrapped log call carried a transcript straight past the privacy gate

`checkNoContentLogging` (ADR-MOB-007) fails the Android build when a log call
mentions a transcript or raw audio, because logcat is readable by the user, by any
bug report, and by anything holding `READ_LOGS`. It scanned one line at a time, so
it saw only the leaks that fit on one line:

    Log.d("tag", "got $transcript")          // caught
    Log.d(                                   // was not caught
        "tag",
        "got $transcript",
    )

Those are the same leak, and the second is what a log call becomes the moment it
passes a line-length rule — these sources already wrap 26 calls, so the formatting
most likely to appear was the formatting the gate could not see.

It now scans the *statement*: the argument list is taken by a balanced-paren walk
that treats string literals and raw strings as opaque, since one `)` inside a
message would otherwise end the scan early and read every later call in the file at
the wrong offset. Verified against the real task in five cases — the wrapped leak
now fails, the single-line one still fails, a `)` in the message no longer truncates,
metadata-only logging still passes, and the repository still passes.

### Fixed — "comment this line" did nothing at all on Android

`37997ae` widened the desktop's `comment` rule so the phrasing people actually use
stopped being typed into the file. That was three days after `c5bd487` ported the
narrow form to Kotlin, and nothing carried the fix across. On Android the rule only
accepted `comment`, `comment this`, `comment line`, `comment selection` and
`comment out` — so `"comment this line"` matched no rule, and an utterance that
matches no rule in command mode is **discarded**: no comment, no text, no error.

Two things let it ship. The 228-vector contract corpus — ADR-MOB-008's stated
mechanism for keeping the ports in step — did not name `comment` in either
direction. And the failure is silent by construction, so there was nothing for a
user to report but "it ignored me".

Fixed by comparing the **tables** rather than adding examples, the lesson of the
disfluency port where a corpus of examples named 1 of 33 missing words:
`tests/test_kotlin_port_shares_the_command_grammar.py` parses `Grammar.kt` and
imports `grammar.py`, and holds all 39 rules — pattern text, intent, action,
argument names, and **order**, since both classifiers take the first match and the
table deliberately puts `run tests` ahead of the catch-all `run (.+)`. Four vectors
record the three phrasings and the anchoring that keeps the widening safe
(`"comment the line about the retry budget"` is still dictation); contract
6.6.0 → 6.7.0.

### Fixed — a contract-only change reported the previous run's pass

`:core:contract-test` received the vector directory as a system property and never
declared it as a task **input**. Gradle keys up-to-date checks and the build cache on
declared inputs, so amending the contract left every input identical and the task
returned the earlier result: reproduced locally as a `FROM-CACHE` pass reporting
`tests="228"` against a 232-case corpus, with only `--rerun-tasks` running the new
cases. `gradle/actions/setup-gradle` restores that cache between CI runs.

This defeated precisely the guard it was paired with — `android-test.yml` triggers on
`contract/**` because amending the contract can break the port, and a contract-only
change is the single case where every other input is unchanged, so it was the case
guaranteed to hit the cache. The directory is now `inputs.dir(...)`.

### Fixed — "they never mind the noise" lost its first half

The self-correction guard asks whether the single word before a trigger makes that
trigger part of a phrase rather than an interjection. It knew negations and modals,
and determiners, reporting verbs and copulas. It did not know a **subject**, so an
ordinary sentence whose verb happens to be a trigger was rolled back:

    "they never mind the noise from the street"  ->  "the noise from the street"
    "we never mind waiting for the next train"   ->  "waiting for the next train"

Nominative-only pronouns (`i`, `we`, `they`, `he`, `she`) now join the guard, in both
the Python filter and the Kotlin port. The boundary is measured, not chosen: in a
genuine correction the word before the trigger is the object being replaced, and one
of those is a pronoun — "i think we should ship it never mind lets wait" turns on
`it`. So `it` and `you`, which are objects as well as subjects, are deliberately
absent, as are the indefinites ("email everyone scratch that email bob" is real).
Three contract vectors record both sides of that line, contract 6.5.0 → 6.6.0.

**What is still wrong, recorded rather than guessed at.** A plural common noun as the
subject reads exactly like the pronoun case and cannot be enumerated —
`"students forget that lesson by the summer"` still becomes `"lesson by the summer"`,
six such cases measured. A rule suppressing rollback after any noun would break real
corrections, whose triggers follow bare nouns (`bob`, `tuesday`, `file`). The module's
stated policy is that this residue is "tracked as a known gap rather than guessed at",
so `tests/test_self_correction_prose_gap.py` records the six, the six that *are*
covered, and the four real corrections that must keep rolling back — failing in both
directions, so the list cannot grow silently or outlive its own fix.

It is not in `contract/semantic/` where a `known-gap` belongs, because that layer
requires a tracked issue URL per gap and one does not exist yet.

### Fixed — the suite's result depended on the order pytest collected files in

Running the 653 test files in reverse order turned seven passing tests red. CI only
ever runs one order, so neither cause was visible; both polluting files carried a
fixture whose author believed it handled exactly this.

**`YAZSES_INJECTOR` leaked out of two files.** `apply_injection_config` writes that
variable and `YAZSES_INJECT_FALLBACK` straight into the process environment — by
design, since it is how `[injection] backend` reaches a zero-argument
`injector_factory`. Both files guarded it with
`monkeypatch.delenv(name, raising=False)`, which does not do what it looks like: when
the variable is absent — the normal case — `delitem` records nothing to undo, so the
fixture is inert and anything set during the test survives teardown. Four assertions
in `test_auto_inject.py` then asked for an xdotool injector and got a clipboard one.

**The CLI's help strings were rewritten in place.** `cli_help.apply` escapes
`[section]` on the module-level command functions, and its own docstring states the
contract that makes that safe — *"called from `cli.main()` and nowhere else"*, so the
doc and man-page generators read the strings raw. That contract holds in production,
where each invocation is a fresh process, and cannot hold in a test session where
both share one. `test_platform_bsd_and_fallback.py` calls `main()` to prove the
console script prints a sentence rather than a traceback, and every later test saw
escaped help: `test_gen_docs.py`, `test_gen_man.py` and
`test_cli_help_keeps_config_sections.py` all failed on it — the last of which already
says in its own fixture that a test which changes another test's outcome is not a
guard but a coin flip.

Both files now save and restore explicitly, and `tests/conftest.py` grew two autouse
guards so neither class can return: one restores and fails on a leaked injector
variable, the other on a rewritten help string. The second resolves its witness
command once per session and compares a single attribute per test — scanning every
command against every config-section name on each of 14 500 tests cost a third of the
suite's runtime.

Verified both ways: reverse order was 7 failed, and is now 14489 passed / 210
skipped; forward order is unchanged at 14499 passed / 209 skipped. Each guard was
re-falsified against its own polluter after being made cheap.

### Fixed — the Android port rolled back a quoted correction and inverted the sentence

Python's self-correction guard is two lists: verbs and negations that put a trigger
inside a verb phrase, and — added later — the determiners, possessives, reporting verbs
and copulas that make it part of a noun phrase or somebody else's quoted speech. Only
the first was ever ported to Kotlin, so on Android these still lost their first half and
left a fluent remainder the user never said:

    "he said never mind the cost and left"    ->  "the cost and left"
    "the no wait policy applies to walk-ins"  ->  "policy applies to walk-ins"
    "there is no wait time at this branch"    ->  "time at this branch"

That is the output the filter's own docstring names as the worst it can produce: it does
not garble the meaning, it inverts it.

The contract vectors are supposed to be what keeps the ports in step (ADR-MOB-008), and
here they caught it — once. Of the 33 words in the missing list the corpus names exactly
one, `said`, so the Android leg reported a single red for a defect with 33 instances and
the other 32 would have survived the fix that closed it. A vector proves an *example*;
only comparing the sets proves the *set*.

So alongside the port, `tests/test_kotlin_port_shares_the_disfluency_guards.py` parses
the Kotlin declarations and compares each against the Python constant it mirrors, in both
directions — a word only Python knows means Android destroys meaning, and a word only
Kotlin knows means the two platforms disagree about whether a real correction happened.
It lives in the Python suite because that runs on every platform leg, while the Kotlin
tests run only in the Android job.

Verified by reproducing CI's exact failure locally (`225 tests completed, 1 failed`, same
vector) and re-running it green on the fix.

### Fixed — the Dependabot SBOM refresh could not reach the two PRs it was written for

`dependabot-sbom.yml` regenerates the committed SBOM on a bot lockfile branch, because
`test_sbom.py` fails on a stale one and Dependabot cannot run the generator. It triggers
on `pull_request_target`, which fires on a pull-request *event* — and #320 and #321 were
already open when it was added, so no further event will ever reach them. They stayed red
on the single assertion the workflow exists to clear, with only a `@dependabot rebase`
comment or a close-and-reopen (which discards the review history) as remedies.

Added a `workflow_dispatch` entry point taking a PR number.

That moves where the author gate has to live. The job-level
`if: github.event.pull_request.user.login == 'dependabot[bot]'` is vacuous on a dispatch —
there is no pull request in the payload, only a number someone typed — so the job now
resolves the PR through the API and refuses unless it was opened by `dependabot[bot]`, has
its head in this repository, and is still open. That check runs **before** the checkout,
because the checkout keeps a push-capable token (`persist-credentials`), and the head
repository is now verified rather than assumed: checking out a fork's head with that token
would hand it to code from outside the repository.

Confirmed against the previous file: the new "there is a manual entry point" check fails
on it, and the ordering check correctly stays silent there, since without a manual path
the job-level `if` really is the gate.

### Fixed — 14 pages on the docs site shared one search snippet

`tests/test_docs_frontmatter.py` checked that a page's `description:` survives being
rendered into a meta tag — but it built its case list from the pages that *have* one. A
page declaring no description simply dropped out of the parametrization and was checked
by nothing, which is also what an unquoted colon does to a whole front-matter block.

The build cannot notice either: MkDocs falls back to `site_description`, so every such
page still renders a `<meta name=description>` tag and `mkdocs build --strict` stays
green. Measured: **14 pages reachable from the site nav** declared none, so all 14 shipped
the identical sentence the home page uses as their search snippet — indistinguishable to
a search engine and to a person scanning a results list.

All 14 now describe themselves. Two of them (`contribute/tasks.md`,
`contribute/built.md`) are generated, so the description was added to
`scripts/campaign.py` — a hand-added block there is overwritten on the next `--generate`
— and only to the `docs/` copies, since the `campaign/generated/` originals are not
published and would carry an unread YAML block.

The new check derives its scope from `mkdocs.yml`'s own `nav`, so a page added to the
site is covered the day it is added rather than when someone remembers to list it.

### Fixed — a pyannote pipeline that returns no `Annotation` failed mid-loop

`PyannoteDiarizer.diarize` called `annotation.itertracks(...)` on whatever the pipeline
returned. pyannote's `Pipeline.__call__` is typed as returning its own result **or** an
iterator, because it also accepts an iterable of files, and only the first has
`itertracks`. The other raises `AttributeError` from inside the loop — during a meeting's
post-pass, which runs after the recording has been consumed and long after the user
walked away, so the message nobody sees is also the only clue about a transcript that no
longer has audio behind it.

It now checks and raises a `RuntimeError` naming the type it actually got.

This was only visible with the `diarization-pyannote` extra installed: mypy has no types
for the pipeline without it, so `uv run mypy src` was clean in CI and reported the
`union-attr` the moment the extra was present. The same is true of the whole
`test_shipped_backends.py` file — its real-backend tests are the ones nothing routinely
runs.

### Fixed — a test gated on `find_spec` failed the moment its extra was installed

`tests/test_shipped_backends.py` skipped its real-Resemblyzer test on
`importlib.util.find_spec("resemblyzer") is None`, then imported the backend. Installing
the `voiceprint-resemblyzer` extra therefore turned the skip into a **failure**:
resemblyzer pulls in `webrtcvad`, whose first line is `import pkg_resources`, which
setuptools removed in 81.0.0. So the test passed only while the thing it tests was
absent.

That is the exact mistake the module under test documents in a comment — "the probe
answers from `importlib.util.find_spec`, which reports whether a package is on disk,
never whether it imports" — written when `voiceprint/factory.py` was given the same fix.
The test file was not.

The precondition is now a real import attempt, and it skips with a reason that names the
cause rather than claiming the extra is missing. Added
`test_a_resemblyzer_that_cannot_import_names_the_remedy_and_stays_dormant`, which runs in
precisely the state every user of this extra lands in on a current setuptools and asserts
the behaviour that protects them: `build_embedder` returns `None` — dormant optional
feature, not a crashed daemon — and the warning names `pkg_resources` and
`pip install "setuptools<81"` instead of leaving a `ModuleNotFoundError` raised three
layers down inside `webrtcvad`.

### Fixed — the "prove we're offline" container command could not run

Four pages invited the reader not to trust the offline claim but to check it, in one
command. The command was broken in two independent ways, and had been since it was
written:

```sh
docker run --rm --network none -v yazses-models:/models -v "$PWD:/data" yazses jfk.wav
```

The image's `ENTRYPOINT` is `yazses`, so this runs `yazses jfk.wav` — and `jfk.wav` is
not a command. Click exits 2 having transcribed nothing. Separately, the named volume
was mounted at `/models`, a path that appears nowhere in the image; the models cache
into `XDG_CACHE_HOME=/home/yazses/.cache`. So the volume cached nothing, every run
re-downloaded the model, and the `--network none` run — the whole point — had no way to
obtain one.

`docs/docker.md` and the README carried the correct form (`transcribe /data/talk.m4a`,
`-v yazses-models:/home/yazses/.cache`) throughout, which is why it went unnoticed: the
working version was one file away. The wrong one was on the privacy statement, the cost
page, "try without installing", and the page written for people whose recordings are
confidential — i.e. every page where a reader who tries the command and watches it fail
concludes the offline claim was the false part.

Verified by building the image and running the corrected commands: 44 s cold (the page
claims 43 s on its author's machine), then 5 s with `--network none` and no route to the
internet, transcribing the sample word for word.

`tests/test_documented_docker_commands_run.py` now parses every shell block, resolves
each container invocation against the real command tree, and checks each model-cache
mount against the path read out of the Dockerfile's own `XDG_CACHE_HOME` — derived, not
restated, so the guard cannot agree with the docs and disagree with the image. Both
checks fail against the text that shipped.

### Fixed — a misspelled `[emg] mode` switched an armband from commands to dictation

`configcheck` carried a note listing eight settings deliberately left out of its
validation table "because each one already fails safe and says so". Three of the eight
had since been added to the table and the note was never corrected. Of the five really
absent, only three had the fail-safe property asserted by any test. Reading the other
two found the claim false both times.

**`[emg] mode`.** The selection was `if mode == "command": … else: <dictation>`, so any
value that was not exactly `"command"` — a typo, a capital `C`, an empty string — did
not disable EMG and did not fall back to anything. It switched the armband to the
*other* mode, and every squeeze typed a transcript into the focused window instead of
running a command. The log line then reported `(commmand mode)`, echoing the typo back
as though it were a mode that exists. `cmdsafety` offers no protection here: it guards
the command branch, which is precisely the branch no longer being taken. This is the
`[injection] target_guard = "of"` shape — a misspelling leaving the wrong behaviour
*on* — on the input path, and it lands on an accessibility input for people who cannot
use a keyboard. `emg.mode` is now in `_ENUMS`, so a bad value is repaired to `"command"`
and reported under `yazses doctor`'s **Config validity**; the daemon additionally warns
and takes the documented default rather than the opposite one.

**`[gaze] zones` and `[polyglot] lid`** are not fail-safe either — they are **inert**.
Nothing in `src/` reads either, so there is no consumer to fail safely. `zones` names a
scheme (`grid3x3 | grid2x2 | windows`) that only `zones.grid_zone` implements, and the
daemon's gaze path calls `targeter.resolve_window`, which resolves a *window* and never
consults a grid; `lid` belongs to a router that stays dormant until `[polyglot]
adapter_path` names an adapter that is not shipped.

Both had been invisible to `scripts/config_status.py`, the detector that generates the
⚠️ inert markers in `docs/configuration.md`, since it was written. It matches
`[."']<field>` over the source, and a dotted module path is spelled exactly like an
attribute access — `from yazses.gaze.zones import resolve_window` contains `.zones`.
The collision is structural rather than unlucky: config sections are named after the
subsystems they configure, so a field sharing a name with a module of that subsystem is
the expected case. Import lines are now blanked alongside comments, which were already
blanked for the same reason. The count on the configuration reference moves from 59
inert keys to **61**, and both keys are marked. This is the second blind spot found in
this detector class this cycle — the first was a `getattr` with a string literal, which
an AST walk cannot see either.

The exclusion note has been rewritten to say which settings are excluded *today*
(`[cocktail] mode`, `[meeting] vad_backend`, both with their fail-safe behaviour
asserted), and a test now fails if the stale sentence returns.

### Fixed — `gitvoice --help` shipped a copy-pasteable force push

`yazses gitvoice --help` ended with two example lines, and the second was
`yazses gitvoice "force push" --run --yes  -> actually runs it`. Every part of that
is armed: `--run` executes the resolved git command, `--yes` is the flag that clears
the destructive-action refusal, and the aside promises it works. A `--help` example is
the one piece of documentation people paste without reading twice, and the outcome of
pasting this one is a force push against whatever repository the shell happens to be
sitting in.

The confirmation that this was known is in the project's own test suite.
`tests/test_help_examples_do_what_they_claim.py` runs every documented example and
checks it does what the text beside it says; that line sat in its `_UNRUN` exclusion
list with the reason *"the example's whole point is that it runs the git command for
real; executing it in a test would push."* CI was protected from the example while
users were handed it.

The armed line is replaced with a printed-only one
(`yazses gitvoice "push to origin main"  -> git push origin main`), which demonstrates
the same resolution without executing anything, and the refusal example above it is
kept, since showing that destructive commands are refused is the point worth making.
`_UNRUN` is now empty: every shipped example is actually run by the suite. A new
guard, `test_no_shipped_example_is_a_copy_pasteable_irreversible_command`, resolves
each example through `gitvoice.plan.build_git_argv` and fails any whose plan is
irreversible and whose invocation carries both `--run` and `--yes` — so the next
armed example cannot be added by simply extending the exclusion list.

### Security — a pin inside one opt-in extra was holding every install below a patch

`pyproject.toml`'s `voiceprint-resemblyzer` extra pinned `setuptools<81`, because
`resemblyzer` needs `webrtcvad`, whose first line is `import pkg_resources` — removed
from setuptools in 81 (verified: 80.10.2 has it, 83.0.0 and 84.0.0 do not). Three files
said in three different wordings that this was confined to that opt-in extra:
pyproject.toml ("a base install never sees the pin"), `.github/dependabot.yml` ("the
exposure is bounded to `voiceprint-resemblyzer`, which is opt-in, excluded from
`[all]`"), and `.github/SECURITY.md` ("not one YazSes creates").

It was not confined. `uv.lock` is a **universal** resolution — one version per package
for the whole workspace, with no way to hold a package back only inside an extra.
`uv export --no-dev`, asking for no extras at all, emitted `setuptools==80.10.2`,
because core `ctranslate2` requires setuptools and there was a single entry to satisfy
every consumer. `scripts/build-macos.sh` and `scripts/build-windows.ps1` build the
shipped `.dmg` and `.exe` from that lock, so it went out in release artifacts too.

The lock now resolves **84.0.0**, above the 83.0.0 that patches Dependabot alert #9.

The guard that should have caught it is the interesting part. It read
`project.dependencies` and `optional-dependencies` and asserted that only that one
extra named a setuptools pin — while its own docstring stated the real property, *"a
base install must never be held below the patched release"*. Declarations cannot
establish that; the resolution can. It now asserts the version `uv.lock` resolves, and
fails against the old lockfile.

The `ignore` rule that was suppressing the security PR is gone from
`.github/dependabot.yml` (an `ignore` silences security updates too, not just routine
bumps). The remedy for that one extra moved to where the choice is made: install it,
then `pip install "setuptools<81"` in that environment. `voiceprint/factory.py` already
told apart "installed but cannot import" from "absent"; it now also names the fix
instead of only reporting `ModuleNotFoundError`, and the weekly `heavy-extras`
workflow applies the same remedy — which is what proves the instruction works.

The other open advisory, `diskcache` ≤ 5.6.3, was re-checked and its published
assessment still holds: nothing in `src/` calls `Llama.set_cache`, constructs
`LlamaDiskCache`, or imports `diskcache`, and an AST scan in the test suite enforces
that. No upstream patch exists, so it stays open with reasoning rather than silenced.

### Added — Tier 2 intent routing is reachable, and `[emg] ble_address` connects something

Two settings that were documented, validated, defaulted, and read by nothing.

**`[commands] slm_model_path` / `slm_confidence_threshold`.** `grammar.classify()` has
accepted an `slm_router` parameter since v0.4.0 and **no caller ever passed one**, so
Tier 2 could not run however those keys were set — the architecture reference marked
both "inert", and `yazses tune` mined few-shot examples into a `few_shots.toml` that
nothing read. `core/daemon.py::_build_slm_router` now builds the router when a model
path is set, feeds it those tuned examples, and passes it to *both* `classify()` call
sites (command mode and the dictation path — wiring one and not the other is a shape
this project has shipped before). It stays completely absent for anyone who configures
no model: no GGUF is loaded and no inference runs on the dictation path.

Filling the seam exposed a defect in it. Nothing had ever failed there, so
`classify()` had no guard around the Tier 2 call — a llama-cpp crash mid-utterance
would have propagated out and lost words the user had already said. It now falls back
to typing them, which is what would have happened with no router at all.

**`[emg] ble_address`.** `_build_activation_sources` read `device_port` and stopped, so
an armband paired over Bluetooth was configured and never connected — and `yazses
doctor` printed a flat `OK` beside the address, because the address was indeed valid.
There is no symptom to notice either: a hotkey that does not fire is silent, which is
also what a hotkey you are not pressing does. Both transports now build, each in its
own try/except so a missing USB device cannot take the Bluetooth one down with it, and
the `[emg] mode` routing is decided once and shared rather than reimplemented per
transport. `doctor` reports WARN when `bleak` is not installed.

Documentation caught up in the same commit: five pages still said Tier 2 was "designed,
not wired", including the CLI reference for `yazses model` and the benchmark page that
put the claim next to a command-recognition number Tier 1 produced alone. The guard
that used to *demand* those caveats now forbids them, and separately requires every
page to say the router needs a local model — under-claiming is the cheaper error but
the more durable one, since nobody re-reads a caveat when the code catches up.

### Added — window layout by voice, the half of `windowctl` that was never connected

`windowctl/commands.py::parse_wm_command` has turned "move window left half",
"maximize" and "workspace 3" into a `WmAction` since ADR-v2-070, and **nothing in
`src/` imported it**. The `WindowBackend` protocol offered `list_windows()` and
`focus()` only, so there was not even a method that could have executed one. The
result was a feature that enabled cleanly and then did nothing — `yazses features
enable windowctl` reported success, `yazses features info windowctl` printed the three
examples, and saying them typed the words as text.

Now wired end to end: `windowctl/actions.py` plans a `WmAction` into xdotool argv,
`XdotoolWindows.perform()` runs it, and `core/daemon.py::_try_window_action` calls it
in command mode. Snap (halves and quarters), maximize, minimize, fullscreen, center,
close, and absolute or relative workspace switching. X11 only, like focus.

Three things worth knowing:

- **xdotool only, no new dependency.** `wmctrl` is the usual tool for this; everything
  needed is expressible in xdotool ≥ 3.0 (`windowstate`, `set_desktop`, `windowclose`),
  which `build_window_backend` already requires.
- **A failed action is reported as failed**, and the phrase is dictated as text
  instead. Returning success on a no-op is exactly what made the original defect
  invisible: nothing typed and nothing moved is indistinguishable from a
  misrecognition.
- **"go to workspace 3" is the one phrase both grammars claim** — the focus grammar
  accepts "go to …", so it parses as focusing a window *titled* "workspace 3". The
  layout handler therefore runs first, and a test pins that order.

Also fixed while building it: a snap now un-maximizes before it moves (a window
manager accepts `windowmove` on a maximized window and ignores it), "workspace 3"
maps to xdotool's 0-based desktop 2 rather than 3, and snap rectangles are computed
from edges so two halves tile exactly instead of leaving a one-pixel strip of desktop
showing on an odd-width screen.

### Added — `doctor` warns Intel Mac users before a Python upgrade breaks the install

macOS on Intel now has a wheel ceiling that is nobody's decision here: `onnxruntime`
published no `x86_64` macOS wheel after **1.23.2** (built for CPython 3.10–3.13), and
`faster-whisper` requires it, so the **base** install cannot resolve on Python 3.14.
`torch` published none after **2.4.1** (CPython 3.12), so `yazses[all]` already cannot
resolve on 3.13. Measured against the live index, per Python version, not assumed.

The failure mode is the problem: nothing breaks while you are running: it breaks the
*next* install, with a resolver backtrace that names `onnxruntime` and reads like a
YazSes packaging bug. `yazses doctor` now prints an **Intel macOS** row showing where
you sit against the ceiling, so it is visible while things still work. The row appears
on Intel Macs only, and never as `FAIL` — the copy printing it demonstrably resolved.

### Fixed — the docs promised Intel Mac users a fallback that no longer always works

`docs/macos-install.md` said PyPI "is architecture independent and always works", and
`packaging/README.md` said the Intel `.dmg` still needed a CI job that had not been paid
for. Both were out of date: the Intel build has existed since v2.22.0
(`macos-15-intel`), and the pipx fallback now needs **Python 3.11–3.13** on Intel, or
3.11–3.12 for `[all]`. Both pages now state the ceiling, its upstream cause, and the
`--python python3.13` workaround, and `tests/test_intel_macos_ceiling.py` ties the
numbers to the markers in `pyproject.toml` so they cannot drift apart. Context: #264.

### Fixed — every spoken command crashed on FreeBSD, and the comment said it could not

`inject/ydotool.py::ydotool_key_args` read its keycodes from `evdev.ecodes` at call
time, under a comment reading *"evdev is Linux-only, but this module is imported on
every platform via inject.auto. The function only ever runs on Linux."* The first
sentence is right and the second is not. `platform/bsd/` composes itself from
`LinuxInjector`, and `inject/auto.py` selects ydotool on **any** Wayland session where
the binary and ydotoold's socket exist — it never asks which OS it is on. FreeBSD ships
ydotool in ports and runs Wayland compositors, and it cannot have python-evdev, which
`pyproject.toml` marks `sys_platform == "linux"` because it is a C extension against
`<linux/input.h>`.

So on a FreeBSD Wayland desktop, dictation typed fine and everything else raised
`ModuleNotFoundError: evdev` from inside the injector: every spoken command (Enter, Tab,
an arrow key, any Ctrl combination), every backspace — which is correction-on-commit and
"scratch that" — and the clipboard backend's own Ctrl+V paste.

The numbers were never the Linux-only part. They are `input-event-codes.h`, a frozen
kernel ABI that FreeBSD's evdev implements identically, and this file already hardcoded a
dozen of them. They now live in `inject/keycodes.py`, generated from `evdev.ecodes` for
the whole keyboard range (1–255) and re-derived against it by
`tests/test_ydotool_keycodes.py` wherever evdev is importable, so a hand-written table
cannot drift into pressing the wrong key. Names above that range still resolve through
evdev, so nothing that worked on Linux stops working.

### Fixed — the FreeBSD job ran 48 tests out of ~13,800

The advisory `freebsd` job existed to check that a real FreeBSD selects and builds
`platform/bsd/` rather than a monkeypatched `sys.platform`. It ran exactly one test file,
on the reasoning that most of the suite imports the transcription stack — which
`ctranslate2` makes genuinely impossible there, since it publishes 35 wheels and no
source distribution at all.

Measured rather than assumed, that reasoning covers a small set of files, not the suite.
Simulating exactly this job's environment — every module FreeBSD cannot supply made
unimportable — **13,707 tests pass**. The decoder-bound files now carry
`pytest.importorskip("faster_whisper")`, so they skip where the decoder cannot exist and
run everywhere else; a new decoder test that forgets the line fails loudly on FreeBSD
rather than quietly reducing coverage. The job installs the three binary ports the rest
of the suite reaches for (`yaml`, `pillow`, `scipy`) and builds `cryptography` through
the Rust toolchain it was already installing, and then runs `pytest tests/`.

It stays `continue-on-error`: the simulation ran on a Linux host and cannot fake
`sys.platform == "freebsdN"`, so the first real run is expected to differ and is there to
be read, not muted. It has already earned its place — widening it is what surfaced the
`ydotool_key_args` defect above. (#306)

### Fixed — every Dependabot lockfile PR was red on arrival

`sbom.cdx.json` is generated from `uv.lock` and committed, because the privacy statement
and the comparison page point people at it as a file they can read.
`tests/test_sbom.py` fails when the two drift, which is right — a stale SBOM is worse
than none, because it is trusted. Nothing wired up the other half: Dependabot edits
`uv.lock` and nothing else, so every uv update PR failed that one assertion out of
13,805 the moment it opened. #320 (17 grouped updates) and #321 (evdev 2.0.0) both died
there, on a generated file the bot cannot regenerate rather than on any incompatibility.

A new `dependabot-sbom.yml` regenerates it and commits it to Dependabot's own branch. It
uses `pull_request_target` because GitHub hands a Dependabot-triggered `pull_request`
workflow a read-only token — it would compute the right file and then fail to push it —
and it is gated on the pull request's author being `dependabot[bot]`, an identity no
outside contributor can forge. `tests/test_bot_prs_can_go_green.py` holds the pairing:
as long as a bot opens lockfile PRs and a test fails on a stale SBOM, something automated
has to close the gap, with a write permission, a bot gate, and the repository's own
commit author.

### Fixed — dependabot.yml claimed an `ignore` rule was free, and it is not

The file said security updates "are enabled separately in repo settings and are NOT
limited by this file — they always open a PR." GitHub's reference says the opposite:
Dependabot can be configured to ignore dependencies "when it opens pull requests for
version updates **and** security updates". Only `update-types` is exempt; `versions:` is
not. The claim was wrong in the direction that hides a vulnerability rather than the one
that adds noise, and the `setuptools >= 81` rule was written under it — that rule stands,
because the range it would move to is the range `voiceprint-resemblyzer` cannot import,
but it now says out loud what it costs.

`tests/test_dependabot_ignores_are_honest.py` holds two properties: an ignore must name
the versions it cannot take rather than the whole package, and `onnxruntime` must not
have quietly acquired one.

### Documented — why the monthly Dependabot `uv` job is red, and why the obvious fix is wrong

Dependabot checks a bump by pinning the target version across the whole resolution
(`uv lock --upgrade-package onnxruntime==<new>`). That pin carries no environment marker,
so it lands in the Intel-macOS fork too, where the project caps onnxruntime below 1.24
because upstream published no x86_64 macOS wheel after 1.23.2. A global `==` and a
per-marker `<` are a contradiction, so the resolution is unsatisfiable by construction.

Reproduced locally against this exact lockfile and confirmed in four arrangements: the
same error appears whether the cap sits in `[project]`, in `[tool.uv]
constraint-dependencies`, or in `override-dependencies`, and it goes away only when the
cap is gone. Removing it is a support decision, not a config change — a fresh Intel
resolution of `yazses[all]` still succeeds today on Python 3.11 and 3.12 (onnxruntime
1.23.2, torch 2.2.2), and already fails on 3.13+ for an unrelated reason, since torch
ships no Intel macOS wheel either. Ignoring `onnxruntime >= 1.24` would stop the red and
also stop every onnxruntime update, security ones included, on Linux, Windows and Apple
silicon — which is where the users are. The reasoning is written beside the ignore list
so the monthly red is not mistaken for new breakage. (#322)

### Fixed — the attribution guard fired on the act of crediting someone

`scripts/campaign_stats.py::attribution_gaps` answered "is GitHub attributing this
person's work?" with a set difference against the `/contributors` API. That endpoint is a
**cached statistic**, not a live query, and it lags a merge by hours — so every author
merged that same day was reported as unattributed. The guard therefore turned CI red on
the very commit that added two contributors to the wall, and the failure text sent the
maintainer to contact them privately about a commit email that was linked all along.
Verified against the repository's own history: every author merged before that day was
present in the cached list, and the only two missing were the two merged that day, while
GitHub resolved both accounts from their commits immediately.

It now asks GitHub whether it can attribute the commits (`/commits?author=`, computed per
request rather than served from the statistics cache), and only for the candidates the
cache could not account for — so a green run costs no extra requests. With no network the
old set difference is kept, and a failed lookup reports the candidate rather than going
quiet: over-reporting shows a name a human dismisses, while under-reporting loses a
contributor in silence, which is the failure nobody ever reports.

### Fixed — a distribution channel that stayed broken became its own baseline

The daily channel-drift watch runs `check-release-channels.py --compare-with <previous
release>`, reporting only channels that went *backwards*. That was deliberate: six
channels have no credential wired up and are absent for every version, so naming them
daily teaches the reader to close the issue unread.

The blind spot is permanent. Comparing against the previous release catches a channel the
moment it breaks and never again — once it has missed two releases running it did not
carry the previous one either, so it becomes its own baseline and drops out of the
comparison for good.

The Homebrew tap fell into it. `TAP_TOKEN` is not set, so the `homebrew` job in
`publish-channels.yml` takes its skip branch and reports **success**; the tap has never
published automatically and froze at 2.18.2 on 2026-08-13. The watcher was written on
2026-08-26 — by which point the tap was already stale, therefore already baseline — so it
never once flagged it, printing "every channel that carried v2.34.0 also has v2.35.0" and
exiting 0 while `brew install --cask yazses` served a build seventeen releases old.

That was not theoretical. Both macOS fixes — `3bffc07` (the `.app` could not name its own
version) and `7b039fb` (`CGEventTap` needs Input Monitoring) — landed after 2.18.2, so
every Homebrew user was installing a build from before either existed. A contributor did
exactly that and reported those already-fixed bugs as live.

A channel is now regressed if **either** the previous release reached it and this one did
not, **or** it is serving a concrete version that is not this one. The second rule needs
no history: the channel is asked what it serves now. Absence is still not staleness — a
channel answering "HTTP 404" or "not in AUR" reports no version and stays suppressed, so
the six unwired channels are as quiet as before.

This makes the next breakage visible; it does not republish the tap. That still requires
`TAP_TOKEN`.

### Fixed — the setup-report linter demanded a Linux display server from Windows and macOS

`check-compatibility.py` requires every `SHOWCASE.md` entry to name X11 or Wayland. On
Linux that is load-bearing: the two behave differently enough that a report omitting the
session cannot be acted on. The rule was applied unconditionally — and X11 and Wayland are
Linux/BSD display servers that Windows and macOS do not have.

So the first Windows entry and the first macOS entry this project ever received were both
rejected as malformed, on a project whose scarcest evidence is Windows and macOS testing.
The linter was refusing precisely the reports it most needed, and telling the contributor
their correct report was wrong. The rule is narrowed, not removed: still required of
anything that is not Windows or macOS.

Also fixed: the assertion that hid it. `tests/test_campaign.py` checked
`assert capsys.readouterr().out or capsys.readouterr().err`, and `readouterr()` **drains**
the buffer — so the second call always returns empty and the assertion collapses to
`out or ""`. A script reporting only on stderr could never satisfy it, which is why this
surfaced as a campaign-harness failure naming no script rather than as the linter
rejecting an entry.

### Fixed — the Homebrew cask told macOS users to grant one permission of the two

A `CGEventTap` needs **Input Monitoring** as well as Accessibility, and either one being
off produces the identical symptom: the dictation key dead in every application while the
Accessibility toggle sits there enabled. `7b039fb` taught the app to request Input
Monitoring, and both `docs/macos-install.md` and `platform/macos/permissions.py` were
updated to say so.

The cask was not, and the cask's `caveats` are the *only* instructions a
`brew install --cask` user ever sees. Six version-bump refreshes touched that file
afterwards and none noticed, because a refresh rewrites `version` and `sha256` and reads
nothing else.

The caveats now walk both grants in order, explain that an app is absent from the Input
Monitoring pane until it has asked (so `+` cannot add it first), tie the microphone prompt
to the key actually working, and note that an unsigned upgrade drops **both** grants. A
test guards the content, so the next refresh cannot quietly drop it again.


### Fixed — in command mode, `run <destructive>` skipped the safety gate

The Command Safety Gate (ADR-v2-065) was wired onto the **dictation** branch of
`_on_hold_end`. A `TERMINAL` intent goes to `cmd_dispatch` on the *other* branch, so the
gate was never consulted for it — and `dispatch._run_terminal` types `run_command`'s
payload **and presses Return**. `assess_command("rm -rf build")` returns `dangerous` on
both routes; only one of them asked. The one path that *runs* a command rather than
typing one was the unguarded path.

The argument for leaving it alone was that command mode is itself the confirmation, and
that a second confirmation trains dismissal. That argument is real but insufficient:
holding the key says *"this is a command"*, not *"and I accept this particular one"*, and
the gate exists because a **misheard** command is as dangerous as an unintended one.
Holding a key does not protect against mishearing. The friction is near-zero — measured
on this project's own corpus, `assess_command` fires on 0 of 1422 real dictations.

Confirming re-dispatches the held intent **as a command**, so Return is pressed the way
running it would have. Typing the released text onto the prompt instead would be safer
and is a different feature, one a user cannot tell apart from the gate having failed.

Fixed in the same change, because the first fix would otherwise have created it: command
mode discards what it cannot classify, and "confirm" is not a command — it classifies as
dictation, falls through every handler, and was dropped as `command_unmatched`. A gate
that held the command but let command mode swallow the release word would be strictly
worse than no gate, since the command is lost *and* the user cannot tell why. The held
state is now checked before those handlers run.

`run_tests` and `run_build` are deliberately not gated: they expand to fixed strings the
project chose (`pytest`, `make build`), not to anything the user said, so gating them
would be friction protecting nobody. `run_last` presses Up+Return and re-runs whatever
the shell last had — risky, but unassessable, since the daemon cannot see the shell's
history, so it is left alone rather than guarded by a check that could only guess.

`[cmdsafety]` remains off by default; nothing changes for an install that never enables it.

### Fixed — `mic-level` calibrated to an empty room and called it a recommendation

`yazses mic-level` recorded once and assumed the clip was speech. It has no way to know
that. Recording a quiet room four times measured 0.0036–0.0050 and recommended
0.002–0.0025 — every one of them *below* the room noise that produced it. Written with
`--set`, that is the gate ambient noise clears: near-silence reaches the decoder and
comes back as a confident invented word.

It now records **twice** — stay quiet for the first, speak for the second — and places
the threshold between the two levels. The second recording is not a refinement; it
supplies the one fact a single clip cannot carry, which is which of the recordings was
the room. Classifying one clip acoustically was tried and stays disproved: on this
project's own corpus the peak-to-mean populations of speech and no-text audio overlap,
with the no-text p90 *above* the speech p90.

When the two recordings are closer than **3×** apart, it says so instead of recommending
a number. That requirement is derived, not tuned: the gate must sit at least 1.5× above
the room and at most 0.5× of the voice, and those bounds cross below 3×. So an empty room
cannot be made to calibrate by nudging a constant — there is no separate constant. At
that separation no usable gate exists at any margin: it is either at the room level,
where the room clears it, or at the voice level, where it discards the voice. The right
answer is that the microphone or the room is the problem, and the command now says that.

The 3× requirement is measured against the 1646-event learning corpus, where real speech
and real no-text audio sit 5.7× apart (medians 0.0394 vs 0.0069) — comfortably clear of
it. Two independent measurements of the same room agree: the corpus no-text p10–p25 is
0.0039–0.0054, against the four direct empty-room readings of 0.0036–0.0050.

Also fixed while here: `_calibrate_mic` never passed the pinned `[audio] device` to the
recorder, so on a machine with a pinned microphone it measured whatever the OS default
happened to be — the opposite of what `record`'s own docstring says the pinning is for.

### Added — `doctor` now says the update watcher exists

`[general] update_check` is off by default and must stay that way: it is the only
part of YazSes that opens an outbound connection, and "nothing leaves the machine"
is the product, not a setting. But off was also *invisible*. The watcher appeared in
`yazses features` among some sixty other rows and nowhere else, so someone running a
build with a since-fixed bug had no path from "this is broken" to "a newer release
exists" — the fix shipped and never reached them.

`yazses doctor` now carries one row directly under **Version**, because "what am I
running" and "is there anything newer" are one question to a user and only the first
half was answerable. When the watcher is off the row is a dim `[SKIP]` carrying the
exact command (`yazses features enable update-check`); when it is on it says so and
restates that nothing about the user is sent.

It is `SKIP`, not `WARN`, on purpose. Nothing is broken — this is the documented,
privacy-preserving default — and a report that warns about a deliberate default is
how people learn to skim past the failures that matter.

The default did not change, `firstrun` still does not seed it, and no new outbound
connection was added.


### Fixed — the Windows signing path could never have worked

The SignPath signing steps in `build-windows.yml` are gated on four `SIGNPATH_*`
secrets that have never been set, so they have never executed once. Reviewing them
before applying to the SignPath Foundation programme found that
`github-artifact-id` was passed `${{ github.run_id }}` — the id of the workflow
*run*, not of the uploaded *artifact*, which is what the action's own input
description asks for. SignPath would have looked up an artifact that does not exist,
and the first signed release would have been the release that discovered it.

The upload step now carries an `id` and the signing step reads its `artifact-id`
output. The signing wait also rises from the action's 600 s default to 1800 s,
because a Foundation signing policy may require a human to approve each request and
ten minutes is not enough to notice a mail and click approve; 30 min still fits
inside the 45-minute producer wait in `checksums.yml`, so `SHA256SUMS.txt` continues
to cover both installers.

`tests/test_signpath_signing_wiring.py` reads the workflow directly, so the wiring is
checked without the secrets — including that the signed binary replaces the unsigned
one *before* anything hashes, attests or uploads it.

## [2.35.0] - 2026-08-27

### Fixed — "Check for updates" on Windows never showed an update

Reported from a Windows desktop: the tray's **Check for updates…** never announced a
new version and never updated anything, so upgrading meant uninstalling and installing
the new build by hand.

Windows gives a balloon body a 256-wide-character buffer (`NOTIFYICONDATA.szInfo`) and
**discards an oversized balloon whole** — no truncation, no exception, nothing in a log.
Measured against the real messages:

| Case | Body |
|---|---:|
| Windows installer, update available | **512** — dropped |
| check failed / offline | **623** — dropped |
| up to date | 40 — shown |
| Scoop / Chocolatey / winget, update available | 60–79 — shown |

So the two cases that carry information were exactly the two that vanished, and the only
message able to render was *"YazSes is up to date"*. The entry looked like it could never
find anything.

This had already been found and fixed for **About**, six lines above in the same file,
and the update path was not covered. The fitting now happens inside the one function that
reaches the Windows notification API, so every balloon — including the daemon's relayed
self-healing messages, which are the longest the tray shows — inherits it, and a
structural test fails the build if any call bypasses it. A test pinning one path would
have passed on the other bug, which is how this shipped twice.

**And the click now does something.** A Windows-installer install has no upgrade command
by design — the upgrade is a downloaded `.exe` — so the tray's whole response was to
print the releases URL into a balloon, where it is text rather than a link. It now opens
the download page, and says the installer upgrades in place and keeps your settings and
models, which is what makes the uninstall-first workaround unnecessary. Downloading and
running the installer automatically is deliberately not done: that is executing a fetched
binary on the user's behalf, and it waits on code signing.

### Fixed — a macOS `.app` was told to update itself with a Windows `.exe`

Found next to the balloon bug, in the same function. `updater.detect_install_method`
classified **anything** with `sys.frozen` set as `windows-installer`, because the frozen
branch was written when Windows was the only bundled build. The `.dmg` `.app` is frozen
too, so every Mac user who opened **Check for updates…** was told, confidently and in
step-by-step detail, to download a `YazSes-<version>-windows-<arch>.exe` — a file that
cannot run on their machine, in a message with nothing to suggest the advice itself was
the problem. A wrong instruction stated with certainty is worse than a silent failure,
because the reader has no reason to doubt it.

A bundle is not a Windows bundle; it is a bundle on whichever OS is running it. There is
now a `macos-app` method with its own steps (open the current `.dmg`, drag YazSes to
Applications), its own recovery hint, and Homebrew named as the alternative — `brew
upgrade --cask yazses` — rather than guessed at, since a cask install and a direct `.dmg`
install are the same bundle and are not distinguishable from inside it.

Like the Windows installer, `macos-app` has no upgrade command on purpose: the upgrade
*is* a download. Its version therefore comes from the GitHub release rather than PyPI
(PyPI carries no `.dmg`), and the macOS tray's **Check for updates…** now opens the
download page for the same reason the Windows one does. `yazses update --check` on a
`.app` also stops exiting 1 with *"no automatic upgrade is available"* — the method is
recognised, so it prints real steps and exits 0.

The docs' [update did nothing](docs/how-to/update-did-nothing.md) page gained the macOS
tab it never had.

### Hardened — the balloon *title* is now bounded too

`NOTIFYICONDATA.szInfoTitle` is a 64-wide-character buffer, the same family of fixed
buffer as the `szInfo` body above. No title YazSes ships comes close — the longest is 47
characters — so this is the class being closed rather than a live overrun, and the same
structural test now covers both fields of every `notify()` call in the Windows tray. The
body overrun shipped twice in that one file; the title was the last unbounded field on
the same call.


## [2.34.0] - 2026-08-27

### Fixed — Settings opened nothing and dictation showed no sign of running, on Windows and macOS

Two defects reported first-hand from a Windows machine: clicking **Settings…** in the
tray did nothing at all, and holding the hotkey produced correct text with no visible
indication anything was happening — no sonar overlay, and a tray icon that stayed the
same colour.

**One cause for the first and half of the second.** Three separate gates decided "is
there a graphical session?" with the same two lines — `DISPLAY` or `WAYLAND_DISPLAY`.
Those are X11 and Wayland concepts. Windows and macOS set neither and never have, so
all three answered *headless* on every Windows and macOS install there has ever been:

- the Settings window refused to open,
- the daemon never spawned the voice-activity overlay (the sonar rings),
- the daemon never auto-spawned the tray.

Reproduced against the shipped 2.33.0 binary on a clean Windows host — `yazses-cli.exe
--settings` exits 1 with *"needs a graphical session — no DISPLAY or WAYLAND_DISPLAY is
set"*. From the windowed `YazSesApp.exe` that explanation has no console to print to,
which is why the button looked inert rather than broken. PySide6 is present in the
bundle; the gate was the only thing stopping it.

The predicate now lives in one module and takes the platform as an argument, because
the honest answer differs: on Windows and macOS an interactive process has a desktop by
construction and no variable says so, while on Linux and the BSDs those variables are
the only evidence there is. A guard fails the build if any module decides it again on
its own — matched precisely enough to still permit `inject/target.py`, which asks the
genuinely different question "is this *plain X11*?" for xdotool.

**The tray colour was a second, independent defect.** The tray polled the daemon once a
second at rest and only dropped to 0.15 s *after* it had seen a recording state — a
chicken-and-egg, since the fast rate exists to track a burst the slow rate has to catch
first. A one-to-two-second hold could begin and end between two samples and never be
observed, so the icon stayed blue through a dictation that worked. The overlay, polling
the same RPC for the same transition, already used 0.25 s and said why. The tray now
does too.


### Fixed — every Scoop install silently had no Start Menu entry

`scoop install yazses` printed

```
Creating shortcut for YazSes (yazses.exe) failed:
    Couldn't find C:\scoop\apps\yazses\current\yazses.exe
```

and then reported success. There is no `yazses.exe` in the bundle and there never
was: the Windows build produces `YazSesApp.exe` (windowed — the tray and daemon) and
`yazses-cli.exe` (console — the CLI, shimmed onto `PATH` as `yazses`). The manifest's
`bin` entry named the second one correctly, which is why the CLI always worked and
this stayed invisible; the `shortcuts` entry named a file that does not exist, so the
Start Menu entry was never created — while the manifest's own notes tell the user to
"launch the tray app from the Start Menu".

The shortcut now points at `YazSesApp.exe`. A new guard reads the executable names out
of the PyInstaller spec and fails if any `bin` or `shortcuts` target is not one the
installer actually ships, so renaming a binary breaks the test rather than the
shortcut. Found by installing the published build on a clean Windows host and reading
the installer output rather than its exit code.


### Fixed — the test suite read the developer's own config file

`load_config(None)` means *the defaults*, and several call sites say so in a comment
(`# defaults: macros.enabled is False`). It actually resolved to
`~/.config/yazses/config.toml` — the real one, on whatever machine the suite happened to
run on, written by the daemon's own first-run seeding.

It was caught by failing a release gate rather than by any review: a test asserting that
with no configuration `doctor` reports *"STT prompt: app name only"* passed for months,
then failed on an unchanged tree, because starting the daemon on that laptop between two
runs had seeded `[context] enabled = true`. The flake is the mild part. A suite whose
meaning depends on the host asserts nothing reliable about the case it names — it can
pass in CI while being vacuous, which is the failure mode that does not announce itself.

The default is now a named function, `config.default_config_path()`, and a session fixture
points it at an empty directory for the whole suite — the mirror of the existing guard
that stops a test *writing* the user's config. `system/firstrun.py` had hand-copied the
same path with a docstring claiming it "mirrors `config.load_config`'s default"; it now
delegates, and a test fails the build if either end restates it. Seeding a config the
loader does not read is a first run that appears to have done nothing.


## [2.33.0] - 2026-08-27

### Fixed — two workflow-shell test files asked the wrong question about the host

`test_checksums_workflow_waits_for_builds.py` and `test_snap_publish_matrix.py` execute a
GitHub Actions `run:` block verbatim, and guarded themselves with
`shutil.which("bash")`. Presence is not capability, in two different ways that were both
red in CI:

- On a GitHub **Windows** runner `bash` resolves to `C:\Windows\System32\bash.exe` — the
  WSL launcher. With no distribution installed it exits 1 with *"Windows Subsystem for
  Linux has no installed distributions."* in UTF-16, so the guard passed and all six
  tests failed.
- **macOS** has a real bash and still cannot run the snap step, because it calls
  `timeout 900` — GNU coreutils, absent there. That is why both macOS legs were red.

The condition is now the one the workflow itself states: these steps are Linux `run:`
blocks, so they run on Linux. A companion test asserts the job's `runs-on` really is
ubuntu, so a permanently-skipped file cannot go unnoticed if that changes.

### Fixed — CI was red on all eight legs for a hook that is entirely correct

`test_sitemap_dates_hook.py` failed on every matrix leg from the day it landed and
passed in every local checkout. `hooks/sitemap_dates.py` asks

```
git log -1 --format=%cs -- docs/index.md
```

and the test job checked out with `filter: tree:0`. A **treeless** clone cannot answer a
path-limited `git log`: deciding which commits touched a path needs the commit trees, so
git falls back to fetching them one at a time from the promisor remote, the hook's 10 s
timeout expires, and the date comes back `""`. Measured against real clones of this
repository:

```
--filter=tree:0     fatal: could not fetch <tree> from promisor remote
--filter=blob:none  2026-08-26
```

The filter is now `blob:none`, which keeps the trees and skips the file contents — where
nearly all of the size is. `fetch-depth: 0` stays: it is a separate requirement (the
packaging guards compare manifests against the latest release *tag*) and was not what
broke this.

### Fixed — the bundled `.exe` and `.app` entered a different CLI from the one shipped

`pyproject.toml` binds the `yazses` console script to `yazses.cli:main`, and `main` does
three things before handing over to Typer. `src/yazses/__main__.py` — the PyInstaller
entry point for every Windows and macOS bundle — called `cli.app()` directly, so a
bundled user got **none** of them:

- `ensure_printable_streams()`. Reproduced end to end on a real Windows host by
  installing v2.32.0 from the Scoop bucket: `yazses doctor` printed most of its report
  and then died with `UnicodeEncodeError: 'charmap' codec can't encode character '✗'`.
  Redirecting a diagnostic command is exactly what somebody does when filing an issue.
- `escape_help_sections(app)`. Rich reads `[meeting]` in a help string as a style tag
  and drops it, so twelve commands named a config key without naming its section.
- The `UnsupportedPlatformError` handler, which turns "no backend for this OS" into a
  sentence instead of a traceback.

The bundle now enters through `cli.main` like everything else. `wincon.ensure_streams()`
still runs first and separately: it answers "is there a stream at all", which the
windowed binary can fail before anything is printable.

The shape is what made it survive — two entry points into one CLI, one of them reachable
only from a build artifact no test suite imports. `tests/test_bundled_cli_is_the_same_cli.py`
now pins them together in both directions.

### Fixed — the last twelve Windows test failures were the test host, not the product

With collection repaired the Windows suite ran end to end for the first time: **13445
passed, 12 failed**. None of the twelve was a product defect, and all twelve failed for
a reason that says something about the tests themselves:

- Six earcon tests and one PortAudio test reached `mocker.patch("sounddevice.play")`,
  which has to import the module to find the attribute. They now go through
  `sounddevice_or_skip()`; `earcon/play.py` itself imports it inside the function it
  plays from, so the product was never exposed.
- `test_a_working_import_is_ok` asserted `portaudio_state() == "ok"` flatly. On a host
  with no audio device the honest answer is `"uninitialised"` — PortAudio loaded and
  `Pa_Initialize()` failed — so the test reported a broken product where the product was
  right. It now asserts that the state and the two predicates derived from it agree, and
  that an importable sounddevice means `"ok"`.
- Two snap tests execute the publish workflow's own POSIX shell, which needs a real
  bash. That step runs on `ubuntu-latest`; they skip where there is none.
- `test_a_microphone_named_after_its_owner_is_redacted` read `getpass.getuser()`, so it
  meant something different on every machine — and nothing at all on CI, where the
  account is the deliberately-exempt `runner`. It patches the name now.

### Fixed — `yazses report` left a Windows account name in clear

The diagnostic bundle redacts the account name because it identifies the machine's
owner, and a Bluetooth microphone carries it (`Ada's AirPods Pro`). The matcher was
`re.compile(rf"\b{re.escape(name)}\b")`, and `\b` asserts a *transition*: placed next
to a non-word character it demands a word character on the other side. For an account
called `yz-win2$` the pattern is `\byz\-win2\$\b`, and in

```
yz-win2$'s AirPods Pro
```

the `'` after the `$` is not a word character either, so the pattern could not match
and the name went into the report unredacted. On Windows this is not a corner case — a
machine account is `<hostname>$` by convention. Names ending in `.` or `-` failed the
same way.

The boundary is now applied only at an edge that is a word character, so `ada` still
does not match inside `adam` and `yz-win2$` is redacted. The test that should have
caught this was itself the reason it did not: it took the name back out of
`pattern.pattern`, feeding in the *escaped* form, and so asserted that a string which
never appears in a report was redacted.

### Added — Scoop installs the native build on Windows on ARM

The release has shipped `YazSes-<version>-windows-arm64.exe` since v2.22.0, and the
Scoop manifest listed only `64bit`, so `scoop install yazses` handed every ARM machine
the x64 build to run under emulation. `refresh-package-manifests.py` now writes the
arm64 entry — and *removes* it when a release has no arm64 asset, since that leg is
`continue-on-error` in `build-windows.yml`: an entry left pointing at the previous
version would 404 instead of falling back to x64, and absent means "use 64bit" while
wrong means "cannot install".

### Fixed — two test files could abandon the whole Windows suite at collection

With the recorder's import fixed, the suite still stopped at `2 errors during
collection`, and pytest abandons the run rather than reporting the other 13675 results.
Both errors were a dependency failing at *load* rather than at resolution, which is the
case `pytest.importorskip` does not cover — it catches `ImportError`, and neither of
these is one:

- `test_diagnosis_portaudio_scope.py` guarded itself with
  `pytest.importorskip("sounddevice")`, but sounddevice raises `PortAudioError` from
  `Pa_Initialize()` during the import. `tests/conftest.py` now offers
  `sounddevice_or_skip()`, which skips on *any* failure and says which one.
- `test_feature_deps_cover_every_probe.py` shells out to `git ls-files` to decide what to
  scan, and git is not installed on a stock Windows host: `FileNotFoundError:
  [WinError 2]`. It now falls back to walking `src/`, which for this guard is strictly
  safer — it asserts every probe has an installable remedy, so a superset of files can
  only make it stricter.

A repository-hygiene guard and an audio-diagnosis test are both things a Windows user
never runs; silencing 13675 unrelated results is how a real regression stays invisible.

### Fixed — a machine with no audio device could not import YazSes at all

`import sounddevice` runs `Pa_Initialize()` during the import itself, and where there is
no usable audio system that raises rather than returning an empty device list:

```
sounddevice.PortAudioError: Error initializing PortAudio:
Internal PortAudio error [PaErrorCode -9986]
```

`audio/recorder.py` imported it at module scope and `core/daemon.py` imports the recorder
at *its* module scope, so `import yazses.core.daemon` was itself impossible on such a
host — an unhandled traceback from a line nobody called. Measured on a Windows Server
2022 VM with no audio device: **45 of the 46 test-collection errors** in the suite were
this one import, which is a large part of why regressions kept reaching Windows unseen.

It is not an exotic state. A stopped Windows Audio service, an RDP session without audio
redirection, a container and a CI runner all look identical to PortAudio — and
`yazses transcribe`, which needs no microphone at all, is exactly the command such a
machine is most likely to want. `audio/devices.py` already imported sounddevice inside
each function for this reason, which is why `yazses doctor` and `yazses audio devices`
*report* the problem instead of dying of it; the recorder now follows the same rule.
Opening a microphone may fail, importing a module may not.

### Fixed — `yazses doctor > log.txt` crashed on Windows

Measured on a real Windows Server 2022 host: `sys.stdout.encoding` is `cp1252` whenever
stdout is not a console — a redirect, a pipe, a CI capture, `yazses report` — and three
commands aborted mid-output with `UnicodeEncodeError: 'charmap' codec can't encode
characters`:

```
CRASH  rc=1  yazses doctor
CRASH  rc=1  yazses features
CRASH  rc=1  yazses quickstart
```

Those are the three commands somebody runs when something is already wrong, and then
pastes into an issue. The characters are not decoration in a rare branch: `→` appears 437
times across 166 modules — the arrow in nearly every "fix it like this" line — alongside
`⚠`, the `─` that frames a panel, and the `●`/`★` markers `yazses audio devices` uses for
the default and pinned microphone. Even where cp1252 *can* encode a character the result
was wrong: an em dash left as the single byte `0x97`, which a console on code page 437
draws as `ù` — observed piping `doctor` through `findstr` on the same machine.

`system/streams.py` now switches stdout and stderr to UTF-8 with `errors="replace"` at
the CLI entry point, and only when the current encoding cannot carry those characters —
so every UTF-8 machine, which is every normal Linux and macOS install, is left byte-for-
byte as it was. The replacement half matters as much: a diagnostic command that meets one
unmappable character prints `?` and keeps going instead of aborting halfway through the
report. The same failure occurs on a Linux container with no locale set, where the
answer is ASCII, and is fixed by the same code.

### Fixed — `doctor` called a Windows install healthy while nothing could be transcribed

On a real Windows host `yazses doctor` reported exactly two problems, and neither was
that dictation could never run there. It printed *"[WARN] STT model: base.en not
downloaded — fetched automatically on first dictation"* while, in the same virtualenv,
`import ctranslate2` was failing with `FileNotFoundError: Could not find module
'...\ctranslate2\ctranslate2.dll' (or one of its dependencies)` — the Microsoft Visual
C++ runtime, which [CTranslate2's installation
docs](https://opennmt.net/CTranslate2/installation.html) list as a Windows requirement
and a fresh Windows image does not always carry.

- **A new `STT engine` row asks whether the decoder loads at all**, and is printed above
  the model row, because a model that has not downloaded yet is a warning while a decoder
  that will not load is the reason nothing will ever be typed. It separates a missing
  package (`pip install`) from a library that will not load (the C++ runtime, linked), so
  neither answer sends the user in a circle. CTranslate2 is probed whatever `[stt] engine`
  says, since `stt/factory.py` falls back to faster-whisper for every other engine.
- **The suite now names the same condition.** It previously surfaced as three failures in
  `tests/test_settings_decode_controls.py` — a file about dropdown contents, and the only
  place that imports ctranslate2 directly — which is not what "this machine cannot
  transcribe anything" should look like. Those three skip and say where to look;
  `tests/test_the_decoder_can_load.py` fails under its own name with the fix.
- `docs/windows-install.md` documents the symptom and the remedy.

### Fixed — the release checksum could describe a binary that no longer existed

v2.32.0 published a `SHA256SUMS.txt` that matched **neither** Windows installer. The
release had been run twice for the same tag; on the second run every asset already
existed from the first, so `checksums.yml`'s "wait for the assets to appear" loop —
which counts *names* — was satisfied on its first poll, hashed the previous run's
binaries, and the still-running Windows build overwrote both `.exe` two to three minutes
later. The `.deb` and `.dmg` matched only because their builds happened to finish ten
seconds earlier. A name is not a file, and no amount of extra waiting fixes a check that
is already true. The same shape had already cost v2.20.0.

Windows builds are unsigned, so that hash is the only integrity signal a Windows user
has — `docs/code-signing.md` tells them to verify it, and a wrong value there reads as
"your download was tampered with". Chocolatey and Scoop derive their manifests from the
same file, so `choco upgrade yazses` refused to install at all.

- The workflow now waits on the producer **workflow runs** — the only thing that knows
  whether an asset is still being written — before it hashes anything.
- After uploading, it proves no artifact was written *after* `SHA256SUMS.txt`. That
  check makes no timing assumption, costs one API call, and fails the run red instead of
  publishing a wrong hash nobody looks at until an upgrade breaks.
- The set of workflows waited for is derived from the workflow files in the test suite,
  so a fourth producer cannot be added without being waited for.

### Fixed — `yazses doctor` told Windows and macOS users to run `apt`

The "Text-target guard" row offered `apt install python3-pyatspi gir1.2-atspi-2.0` as the
route to precision, un-gated by platform, so every Windows and macOS install got it —
observed verbatim in the `doctor` output from a real Windows machine. AT-SPI is a Linux
desktop technology; off Linux the precise path is not a missing package, it is
unreachable, and no command can move that row. It now says the guard is best-effort and
that precision is Linux-only, and keeps the remedy on the platform where it works.

## [2.32.0] - 2026-08-26

### Fixed — a meeting no longer disappears into a collapsed transcript

A real 41-minute meeting finalized as `status: "done"`, `capture: "ok"`, with a
`transcript.md` that was 93 repetitions of "Hello, hello, hello." The batch decode had
collapsed into a repetition loop — a known decoder failure — and every guard passed it:
`capture_state` asks whether audio was *heard* (it was), `attribution_suspect` asks who
said what (there was one speaker). Because the post-pass raised nothing, the recording
was deleted as a successful consumption and the meeting became unrecoverable. Its only
surviving record was `live.jsonl`, which nothing rendered and nothing mentioned.

- **Every meeting is now transcribed twice, and both are kept.** The rolling live decode
  is rendered to `live-transcript.md` on the way out — *before* the batch pass runs, so a
  finalize that dies still leaves it — and is never deleted.
- **The batch transcript is judged, and the verdict is written down.** A new pure
  `meeting/quality.py` measures repetition share, distinct-phrase ratio, longest
  back-to-back repeat, words-per-minute, and — the strongest signal, needing no threshold
  — how far the batch pass disagrees with the live decode of the same audio. Thresholds
  were measured against five real stored meetings; on that corpus the check catches the
  collapsed one (97% one phrase, 3.5% distinct, 16× live disagreement) and fires on none
  of the four healthy ones. Metrics land in `quality.json` for every meeting, healthy or
  not, so a verdict can be read next to the numbers it did *not* fire on.
- **The recording is kept when the verdict is bad**, regardless of `[meeting]
  retain_audio`. Deleting on "no exception" is what made the original meeting
  unrecoverable; the recording is the only input that can produce a better transcript.
- **The minutes pass is skipped on a collapsed transcript**, as it already was for a
  recording holding no speech. A summary of invented words reads exactly like a real
  one. `yazses meeting notes --force` overrides.
- **`yazses meeting recover` now accepts a meeting that finished badly**, not only one
  that never finished — previously `status: "done"` ended the conversation, so the
  meeting that most needed a retry was the one that could not have one. It archives the
  previous outputs to `attempts/<n>/` rather than overwriting them, and `--force`
  re-runs a meeting that finished cleanly.
- **Nothing is ever deleted.** No transcript, JSON, or markdown file is overwritten in
  place by a retry.

### Added — follow a meeting's transcript while it is still running

`live-transcript.md` is now appended to as each utterance is decoded, instead of being
rendered once at stop. The transcript was already crash-proof — `live.jsonl` has been
written incrementally since Meeting Mode shipped — but newline-delimited JSON is not
something a person opens mid-meeting, so a record that existed throughout a two-hour call
was unreadable until it ended.

- `yazses meeting start` prints the file's path and the `tail -f` command for it;
  `yazses meeting status` names the same file alongside the last few utterances.
- The incremental writer and the whole-file re-render produce byte-identical output, so
  the finalize pass never rewrites the file you have been reading. `live.jsonl` stays the
  source of truth: the re-render at stop and at every `meeting recover` repairs an append
  torn by a crash.
- Off with `[meeting] live_markdown = false` (default `true`), which restores the
  previous behaviour of writing the file once at stop.

### Added — `yazses meeting summary`, and an end-of-meeting readout

- New `yazses meeting summary [<id>]` (omit the id for the most recent): what the meeting
  produced, where each file is, what each file is *for*, and — first, above the file list
  — anything that should stop you reading the transcript as a record. Exits `2` when the
  transcript is not usable.
- The same readout is written into the meeting folder as `summary.md` at stop and shown
  as a desktop notification when the post-pass finishes. Meeting Mode has no key held and
  no terminal watched, and its post-pass ends long after the user has walked away; a
  post-pass that *fails* now notifies too, rather than reporting only to the log.
- The verdict reaches meetings recorded **before** the check existed: `meeting summary`
  computes it from the stored transcript and writes it back, so the fix applies backwards
  to meetings that already happened.
- `yazses meeting list` marks an unusable transcript `⚠ BAD TRANSCRIPT` and points at
  `live-transcript.md`. A finished-but-bad meeting is no longer described as
  `unfinished` — it ran to the end, and `recoverable` had quietly become a synonym for
  something it no longer meant.
- `yazses meeting stop` now names the three files that will appear and the command that
  explains them.

### Fixed — Snap setup and instructions now respect confinement

- `yazses setup` now detects a strictly confined snap and prints the two required
  `snap connect` commands instead of trying to execute `sudo` and crashing with
  `PermissionError`. Reproduced from the published 2.31.0 snap in a clean LXD
  container, which is the only way to meet the condition on purpose: a developer
  machine runs from a checkout and never enters confinement, which is why the
  crash reached a user before it reached a test.
- The Snap Store description and installation docs no longer present `yazses setup`
  as a host-provisioning step inside the strictly confined snap, where executing
  `sudo`, installing host packages, changing groups, and configuring `ydotoold`
  cannot work.
- Snap dictation is now labelled X11-only everywhere it is offered. Wayland pages use
  the universal Linux installer, while X11 Snap instructions explicitly connect both
  required interfaces before running `yazses doctor`.
- The install checklist now carries `snap connect yazses:raw-input`. It had only ever
  offered the microphone interface and then `usermod -aG input` — the loop that cannot
  succeed inside confinement ([#44](https://github.com/MSKazemi/yazses/issues/44)) —
  so the one screen telling a user what to do omitted the only step that grants the
  hotkey, while `yazses start`'s warning had known about it all along.
- `yazses quickstart` no longer reports "Prerequisites — already set up ✓" inside a
  snap whose interfaces are unconnected. A confined plan is empty because nothing in
  it is the app's to do, which is the opposite of a provisioned machine.
- `yazses setup` no longer exits with a traceback when a command cannot be executed
  at all. `check=False` suppresses a non-zero exit status, not a failure to `exec`,
  so a sandbox denial or a missing binary escaped as `PermissionError`/`FileNotFoundError`
  out of the one command whose job is repairing a machine that does not work yet.

### Improved — search and answer-engine discovery

- The Linux use-case page now answers the actual phrases appearing in Search Console
  (Linux voice typing, offline speech-to-text, Ubuntu and Wayland) in its title, opening
  answer and a concise question section, without changing the product claims.
- The homepage's structured data now connects the software entity to its canonical
  website and web page, and every page advertises the compact `llms.txt` product guide
  alongside its existing Markdown twin for machine readers.
- Sitemap entries now use each source page's latest committed date instead of claiming
  that all 475 pages changed on every build. Four duplicated design-index URLs caused
  by publishing a section README and its generated replacement were removed.

### Fixed — Snap publishing no longer aborts after finding an accepted revision

- Both architectures in the v2.31.0 publish run uploaded successfully, but the
  revision lookup never reached `snapcraft release`. By that point in the script
  `set -e` has been restored, and under it a failing command substitution in an
  assignment aborts the step -- so a single transient non-zero exit from
  `snapcraft revisions` killed the job on the first pass of the very loop written
  to retry it.
- The workflow now captures the revision table into a variable through an `if`,
  so a failed query is a skipped iteration rather than a dead job, and parses it
  afterwards. The bounded upload wait, architecture-qualified lookup and channel
  read-back are unchanged. A regression test executes the real workflow shell for
  both architectures and locks both failure boundaries.
- The upload passes `--release=stable,edge` as a hint, **not** as the mechanism:
  the explicit `snapcraft release` call remains what publishing depends on.
  Whether the store applies those channels once a pending review passes is
  plausible but has not been demonstrated here — revisions 388/389 establish only
  that omitting the flag leaves no channel, which does not establish the converse.
  Do not wait for a deferred release to appear; re-run the publish.

### Added — `[stt] condition_on_previous_text`, the knob the 2x2 found had no way to be reached

- The decode measurement below found a failure mode a user could not turn off: conditioning
  each window on the previous one's text sends a large checkpoint into a repetition loop on
  roughly 1.5 % of utterances, and nothing in `config.toml` reached the flag. `docs/benchmarks.md`
  had to end a section by naming a setting and admitting YazSes did not expose it.
- Defaults to `true`, which is faster-whisper's own default and what every published number
  was measured at, and it is **sent to the decoder only when you turn it off** -- pinning a
  library default explicitly would freeze it at today's value, the same reason
  `[stt] beam_size = 0` means "say nothing" rather than "say 5". Nothing changes for anyone
  who does not set it, and a test fails if the default path ever starts sending the kwarg.
- Threaded through the one `_decode_kwargs` seam, so `transcribe`, `transcribe_words` and
  the streaming `decode_window` all honour it. `[stt] language` was a documented key that
  did nothing for a year because those same three call sites each hardcoded `language="en"`;
  a test now reads the source of every decode path and fails one that builds its own kwargs,
  and a second test fails if a fourth decode path is added and left out of the first.
- Config-only for now: it is not in the Settings window, which carries the value settings
  a person changes often, and this is one for a user who has already configured a large
  checkpoint by hand.

### Measured — where the conditioning benefit changes sign, so the new key has a rule

- `[stt] condition_on_previous_text` shipped with `base.en` at one end of the evidence and
  `large-v3` at the other and nothing in between, which is a thin basis for guidance. Both
  arms were run five times each on `small.en` and `medium.en`, same 200 `test-other`
  utterances: **9.46 → 9.81 % (`base.en`), 5.59 → 5.70 % (`small.en`), 5.51 → 5.51 %
  (`medium.en`), 4.84-6.21 → 3.82 % (`large-v3`)**. The benefit shrinks monotonically and
  reaches exactly zero at `medium.en` — all ten decodes, both arms, return one hash, so the
  flag did not change a single token. `test-clean` agrees at lower amplitude.
- Counting decode passes says why, and not for the obvious reason. The share of utterances
  taking a second pass — the only ones a prompt can reach — falls with the checkpoint too:
  8 % on `base.en`, 1.5 % on `small.en`, 0.5 % on `medium.en`. But `medium.en`'s one
  multi-pass utterance *was* handed the previous text and the output is identical anyway.
  Two things shrink together: how often the prompt is delivered, and how much the model is
  moved when it is.
- **So the guidance is a size rule, not a preference**, and `docs/benchmarks.md` and the
  config comment now say it: leave it alone on `base.en` and `small.en`, it changes nothing
  on `medium.en`, set it `false` on `large-v3` and above.
- Two cross-checks arrived free. `small.en` 5.59 % and `medium.en` 5.51 % reproduce
  `paper/results/wer-test-other.json` exactly, from a different probe on a different day.
  And `small.en` `test-clean` 2.66 % reproduces the Xeon figure this page already prints
  against the laptop's 2.59 % — the per-ISA int8 kernel difference already documented, not
  a new disagreement.

### Fixed — `[stt] model` told users the larger checkpoints were a marginal gain

- The config reference said larger models "trade decode latency for marginal gains on
  clean speech", and this project's own archived numbers say the opposite: `small.en`
  removes **36 %** of `base.en`'s errors on clean audio (4.07 -> 2.59 %) and **41 %** on
  hard audio (9.46 -> 5.59 %), for about twice the decode time and still ~10x realtime.
  The sentence steered people away from a substantially better model. `base.en` stays
  the default -- it is the best *latency* trade for hold-to-talk -- but the reason is now
  the true one, with the measurements and where they came from.
- Also fixed the shape of the repair: the numbers were first written as an aligned table,
  which a config comment cannot carry. `scripts/gen-docs.py` flattens the comment block
  into a single markdown table cell, so the table arrived in the public reference as
  "model test-clean test-other tiny.en 4.82 11.77" and every generator test still passed.
  A test now fails any config comment whose cell contains aligned columns.

### Measured — the decode defaults were put to a 2x2 and both are kept

- `large-v3` decoding the same 200 `test-other` utterances five times produced five
  different WERs (4.84-6.21 %). The obvious repair was to decode greedily
  (`temperature=0.0`), and it was about to be recommended. Measuring the full 2x2 --
  temperature fallback on/off, crossed with `condition_on_previous_text` on/off, five
  decodes per arm, on `large-v3` *and* on `base.en`, the checkpoint a default install
  actually runs -- says otherwise, and **no default changes**.
- Greedy decoding is the **worst** arm measured anywhere: 15.26 % on `large-v3`
  `test-other` against a 4.84-6.21 % baseline, and 10.33 % on `base.en` `test-clean`
  against 4.01 %, almost all of it insertions (325). It is reproducible and wrong.
- Turning conditioning off is what actually fixes `large-v3` (3.82 %, one hash across
  five decodes) -- but it **reverses on `base.en`**, which gets worse on both splits
  (4.01 -> 4.24 % `test-clean`, 9.46 -> 9.81 % `test-other`) and *loses* its
  bit-reproducibility on `test-clean`. The shipped default is already the best arm on
  the shipped model, and already reproducible.
- The `large-v3` gain does not survive its own error bar. Scored per utterance and
  paired: -1.05 points, 95 % bootstrap CI **[-2.59, +0.16]**, which crosses zero;
  4 utterances better, 8 worse, 188 unchanged, exact sign test p = 0.39; and
  **95.7 % of the gain sits in 3 clips**, 38.3 % of it in one. It is a tail-risk
  setting for large checkpoints, and `docs/benchmarks.md` now says exactly that rather
  than selling it as a WER win.
- The mechanism was counted rather than argued. Conditioning was assumed to be
  long-form-only; **no clip in either corpus exceeds one 30 s window** (longest 27.2 s)
  and it still acts, because `seek` advances to the model's last emitted timestamp
  rather than by a full window, so 8 of 40 `test-clean` and 16 of 200 `test-other`
  utterances take a second pass and every one of them is handed previous-text tokens.
  With the flag off, zero are.
- Two hypotheses were refuted along the way and are published as such. Identical output
  hashes are **not** evidence that the temperature fallback never fired -- a fully
  rejected ladder returns the best average-logprob result it saw, which can be the
  temperature-0 decode it started from; direct counting shows 4-8 rejections per run
  where the hashes are identical. And the moving rejection count is not CTranslate2
  thread scheduling: across 28 decodes in three sessions the count moves at
  `cpu_threads=1` too, while the greedy rung at 0.0 is rejected exactly 3 times in
  every run of both arms. Pinning threads costs 2.05-2.19x and buys nothing.
- All of it is archived and re-derivable: seven new artifacts under
  `paper/results/probes/`, two more recovered from `paper/results/history/` (where
  `write_result` had put them when a re-run reused the same output name), their run logs,
  two new probes -- `decode_mechanism.py` and `thread_determinism.py`, 26 tests between
  them -- and a written-up account in `paper/results/probes/README.md` including both
  retired inferences. `MANIFEST.md` now attributes an artifact from its recorded command
  line when it predates the `produced_by` stamp, instead of printing an em dash beside a
  file that names its own script.


## [2.31.0] — 2026-08-24

### Changed — every archived benchmark result now records *which* utterances it scored

- Each file recorded `n_utterances: 200` and nothing identifying the 200. The selection is
  deterministic given the corpus — sorted ids, sorted speakers, round-robin, no RNG — but
  `librispeech_subset` skips an utterance whose `.flac` is absent and takes the next one, so
  a host with a partially extracted corpus scores a **different** set and still reports 200.
  These numbers come from a laptop, two rented x86 boxes and three CI runners, and
  "reproducible across CPUs" is a conclusion drawn from exactly that kind of comparison.
- Provenance gained a `corpus` block: the digest of the selected ids **in decode order**
  (order matters — `condition_on_previous_text` makes one utterance's decode depend on what
  preceded it), the requested and actual counts, the first and last id, and `n_missing`,
  which is non-zero precisely when this host's corpus is not the one a peer artifact's
  digest was taken over. Recorded inside `librispeech_subset`, where the data is, rather
  than asking eight `__main__` blocks to thread it through — the arrangement that had
  already failed for provenance itself and again for the command line.
- The check was then run. All three Linux hosts return `08c500680ad493e4` for 200 stratified
  `test-clean` utterances with the same first and last id, so the cross-host comparison
  stands; it is now pinned in a test that fails if the selection or the corpus moves.
  `test-other` is present on one box only, which is why every `test-other` number in the
  archive came from that box.

### Changed — every archived benchmark result now records the command that produced it

- `paper/results/` opened on the claim that its numbers can be re-derived from the harness
  and recorded, for all 83 artifacts, the producing *script* and never its arguments. The
  arguments are the measurement: `bench_wer.py` writes one filename for `200 test-clean` and
  for `500 test-other`, `bench_beam.py` writes one for the `base.en` and `tiny.en` grids
  whose disagreement decided ADR-v2-073, and `bench_diarization.py` writes one with and
  without `--max-speakers`. "Reproduce it from the harness" was an instruction that could not
  be followed, and nothing said so.
- Stamped at `_common.write_result`, on **both** of its paths — the branch that honours
  `run_all.py`'s shared provenance block would otherwise have been skipped, leaving most of
  the archive uncovered while a test of the other branch passed. Redacted before storage
  (`$HOME`, `$USER`): this is the one provenance field copied from a path a person typed.
  `MANIFEST.md` gained a **Command** column; a row showing `—` predates the field and a
  re-run fills it in.
- `MANIFEST.md` also described all seven `*-significance*.json` files with the same sentence
  as the grid they re-read, because the description matched by prefix — so the index asserted
  the beam grid had been measured three times per split when it was measured once and
  bootstrapped twice. An analysis is now labelled as one.

### Fixed — the latency governor discarded `[stt] beam_size` and loaded the model twice

- `pick_policy` hardcoded `beam_size=5` on both of its base paths. Two things followed from
  one line. A user who set `[stt] beam_size` got 5 anyway for as long as the governor was
  enabled — a documented key silently overridden by an unrelated feature. And `EnginePool`
  is keyed on `(model, beam_size)` and is handed the daemon's own engine under
  `(stt.model, stt.beam_size)`, which for the shipped config is `(model, 0)` — "pass nothing,
  let the engine choose". A base policy answering `(model, 5)` **missed that key on every
  normal-load burst**, so the pool started a background load of a second copy of the model
  already in memory. `pool.py`'s docstring names avoiding exactly that as a design goal.
  Nothing failed and nothing was logged; the process just held two engines for the session.
- The base paths now return `config.base_beam`, which the daemon fills from `[stt] beam_size`.
  The regression is asserted where it bit: at normal load the pool must return the engine it
  was constructed with and queue **no** background build, for a configured width of 0, 2 or 5.

### Changed — the governor's beam under load is 2, decided on `tiny.en` rather than argued

- The high-load policy narrowed the beam to **1** on the reasonable-sounding argument that a
  policy for a busy machine should buy back every cycle available. It had never been measured
  on the model that policy actually runs. The `[stt] beam_size` sweep in `docs/benchmarks.md`
  could not settle it either: that grid scores `base.en`, and this policy switches to
  `tiny.en`, so it measures a combination the product never executes.
- **The two grids disagree, and the disagreement is the result.** On `base.en`, beam 1 loses to
  beam 2 significantly (`p = 0.0026` hard, `p = 0.024` clean). On `tiny.en` it does not
  (`p = 0.41`, `p = 0.099`), so the earlier finding could not simply be carried across. What
  decides it is the ceiling: paired on the same utterances, beam 2 is **indistinguishable from
  beam 5** on both splits (`p = 0.27`, `p = 0.62`), while beam 1 **loses to beam 5 on clean
  audio** by 0.58 points (95 % CI [+0.09, +1.14], `p = 0.023`). Beam 2 reaches the best
  accuracy the three widths show; beam 1 demonstrably does not.
- It costs 2.1 % more decode on clean audio and 4.2 % on hard, against the 12–16 % beam 5 would
  cost over beam 2 — and the beam was never where this policy's saving came from. `base.en` at
  beam 5 decodes the hard split at RTF 0.0426, so `tiny.en` at beam 2 is still 31 % less decode
  time. Widening 1 → 2 hands back a twelfth of that saving on hard audio.
- The grids, the paired verdicts and the run log are archived
  (`paper/results/beam-governor-test-{clean,other}.json`, their `-significance` and
  `-significance-vs-beam2` companions). No new guard was needed on the published table: the
  existing one derives its rows from every `beam-*.json` in the archive, so the eight new rows
  were checked the moment they landed — and a one-digit mutation of any of them fails it.

### Fixed — six surfaces told users a shipped diarization backend was not shipped

- The `pyannote` adapter has shipped since 2026-08-13 behind the optional
  `diarization-pyannote` extra, and `system/backends.py` says so explicitly. Six live
  surfaces still said the opposite: the `--min-speakers` option help, the runtime note
  that fires when you pass it, `system/depsize.py` (citing `system/backends.py` as its
  authority while that file said the reverse), `config.py`'s `max_speakers` comment,
  the transcribe tutorial, and the CLI reference. **A user who needs a lower speaker
  bound was told no backend provides one**, so they never installed the extra that
  does. Every one now names the extra instead.
- `tests/test_docs_do_not_deny_shipped_backends.py` guards it. The existing
  deny-a-wired-feature guard structurally could not: it keys on capability slugs from
  `system/features.py`, and a pluggable backend is a *config value*, not a capability,
  so nothing in the registry ever mentions it. The new guard derives the shipped set
  from the adapter modules named at each `probe_backend` call site — shipping an
  adapter arms it the same day, with no list to maintain — and it found a sixth
  surface that a manual sweep had missed. Saying `deepfilternet` is unshipped stays
  correct and stays sayable; it genuinely has no adapter and cannot get one.

### Fixed — `features enable` warned about a "different Python" that was the same one

- `daemon_interpreter_differs` derived the daemon's environment prefix with
  `dirname(dirname(argv[0]))`. `argv[0]` is whatever was typed, so a daemon started
  as `.venv/bin/python -m yazses.main` yields the *relative* `.venv`, which can never
  equal an absolute `sys.prefix`. Every such daemon was reported as a foreign
  interpreter, and `features enable` then told the user to install into
  `.venv/bin/python` — a path that means something different in every directory and
  nothing in most. It is now resolved against the daemon's own working directory
  (`/proc/<pid>/cwd`), never the caller's, and still without `realpath`, because
  resolving a venv's `python` symlink to its shared base is what would make the check
  never fire at all.
- The existing test could only see this when the suite itself was launched with a
  relative interpreter path — it reads the host, and had been passing under
  `uv run python -m pytest` for as long as it existed. The pure `(argv0, cwd)` cases
  beside it now state the behaviour without depending on how pytest was invoked.

### Fixed — a `large-v3` instability figure compared two different corpora

- `docs/benchmarks.md` stated that `large-v3`'s `test-other` insertions "doubled from 89
  to 184 between the runs". **89 is the `test-clean` figure.** The two runs being compared
  were on different corpora with different reference-word counts (4 598 hits against
  3 619), so a cross-split difference was published as one split's run-to-run movement.
  The qualitative claim survives — insertions move, substitutions do not — but the
  supporting number did not, and the real within-split range is **101 to 184**.
- The distribution the page said "nobody has characterised yet" has now been measured:
  four more full decodes of the same 200 `test-other` utterances. Across five independent
  runs the substitutions (87), deletions (15) and hits (3 619) are **bit-identical**, so
  every WER is exactly `(102 + insertions) / 3721` and the entire 2.2-point spread is the
  insertion count. `large-v3` is not unreliable at recognising the words that were said;
  it is unreliable at *stopping*. The monotonic fall over the first three repeats
  (141 → 124 → 101) looked like a harness warm-up artefact; the fourth repeat's 144
  refutes that.
- `tests/test_benchmarks_match_results.py` now holds the published table to the artifact
  row by row, and to the identity in prose. It parses the table rather than searching the
  page: every figure in it is also quoted in the surrounding text, so a substring check
  passed a deliberately drifted cell.

### Fixed — the pyannote diarization backend's gated-model remedy was unreachable

- The backend carried a carefully written error naming both fixes for a gated Hugging
  Face model, and it only fired when `from_pretrained` **returned** `None`. On the path a
  new user actually hits — no stored token, so `huggingface_hub` **raises** first — they
  saw the raw upstream text instead, which names the token and never the acceptance step.
  A perfectly valid token still fails until the model conditions are accepted, so the
  message read as though the token were wrong.
- The remedy is now shared by both paths and names `pyannote/segmentation-3.0` alongside
  `pyannote/speaker-diarization-3.1`: the pipeline loads both, they are gated separately,
  and accepting only the one you asked for is the commoner near-miss than accepting
  neither. A failure that is *not* about access — a full disk, a dead network — is left
  to propagate untouched, because sending someone to a licence page for an hour is worse
  than the original message.
- The suggested login command was `huggingface-cli login`, a deprecation shim in the
  `huggingface_hub` 1.x this project already depends on; it is now `hf auth login`, with
  the old spelling kept as a parenthetical.

### Fixed — `meeting start --help` advertised a DER the product had stopped shipping

- **`yazses meeting start --help` told every user that speaker labelling scores "84 % DER
  at auto vs 29 % when the count is given".** Both figures were measured against
  `cluster_threshold = 0.5` on a four-meeting subset. ADR-v2-133 raised the shipped
  default to `1.2`, at which the *full* AMI test split scores **26.71 %** — so the help
  overstated the tool's own error rate roughly threefold and pushed users toward
  `--speakers` on evidence that no longer described the build they were running. The flag
  help now says what is still true and checkable: the count is exact rather than a cap on
  the shipped backend, so guessing it invents people.
- A guard already forbade those figures and did not catch this: it checked the string
  `speaker_count_advice()` returns, and this was a second surface saying the same wrong
  thing. `tests/test_cli_help_has_no_superseded_diarization_figures.py` now walks the
  Typer app itself — every command, every option — so a new command that copies the old
  sentence fails on the day it lands.

### Changed — a published AMI comparison was confounded and has been withdrawn

- `docs/benchmarks.md` read *"supplying the exact speaker count is now worse than letting
  the clustering estimate it — 29.42 % against 26.71 %"*. The artifacts behind those two
  rows differ in **two** variables: 29.42 % was measured at `cluster_threshold = 0.5`
  with the count supplied, 26.71 % at `1.2` with it estimated. The comparison cannot
  separate the threshold from the count, and within its own condition the data says the
  opposite — at `0.5`, supplying the count improves DER from 75.21 % to 29.42 %, the
  largest single effect on the page.
- What the data does support is the reason the default moved: **raising the threshold
  achieved more than supplying the count did, without asking the user for anything.**
  The deciding cell — threshold `1.2` *with* the count — had never been run and is now
  being measured. Until it lands, nothing claims a direction. The same confounded
  sentence was carried in the rationale docstrings of `recimport/factory.py` and
  `core/daemon.py::_handle_meeting_start`; both now state the limit instead.
- `bench_diarization.py` additionally reports the **time-weighted corpus DER** beside the
  per-recording mean. The mean stays the headline (a forty-minute meeting should not
  drown out three short ones), but every AMI and DIHARD table aggregates over speech
  time, and reporting only one of the two made this page quietly incomparable to the
  literature it is read against. Both are computed from rows already recorded, so the
  figure is re-derivable from artifacts that predate it. On the AMI test split the two
  are **26.71 %** (per recording) and **27.37 %** (per second of speech, over 8.5 hours
  of scored audio); the page now says which one to place beside a published table.
- The 26.71 % headline had **no per-recording artifact at all** — it was quoted from a
  sweep row, so it could not be decomposed, re-aggregated or bootstrapped by anyone,
  including us. `paper/results/diarization-ami16_corpus-der.json` is the first artifact
  behind it, and the published figure re-derives from its own 16 rows exactly.

### Changed — the beam-size table is now decided, and two of its readings were wrong

- **`beam_size = 2` and `beam_size = 5` are indistinguishable, and that is now a measured
  statement rather than a reading.** Bootstrapped paired on the utterances both settings
  decoded, `base.en` differs by 0.000 points on `test-clean` (95 % CI [−0.21, +0.18]) and
  0.03 on `test-other` (95 % CI [−0.33, +0.40]). The intervals exclude a benefit above
  about 0.4 points in either direction. Beam 5 costs 7.8 % more decode on hard audio and
  11.4 % on clean.
- **Two conclusions the page drew from the bare grid did not survive the paired test** and
  are now written as observations: that a wider beam can be worse (beam 8 at 9.84 % against
  beam 5 at 9.46 % — paired, p = 0.40) and that the effect reverses sign on `small.en` with
  clean audio (2.53 % against 2.66 % — paired, p = 0.15). Beam search beating greedy
  survived on both splits (p = 0.024 clean, p = 0.0010 hard).
- `[stt] beam_size` keeps its default of `0`, which means "let faster-whisper choose" and
  is deliberately not a pin.
- `analyze_beam.py` gained `--baseline=N` so the comparison that decides a default —
  5 against 2 — can be asked at all; the baseline is written into the artifact's filename
  so two analyses of one measurement cannot displace each other. `bench_beam.py` gained
  `--grid`/`--name` for the same reason, and refuses `--grid` without `--name`.
- All 14 WER cells reproduced **bit-identically** against the published table on a third
  independent run; the RTF column moved by up to 3 % and was rewritten from the artifact.

### Fixed — three extras were unsatisfiable on Intel macOS

- **`yazses[tts]`, `yazses[silero]` and `yazses[all]` had no resolvable answer on an
  Intel Mac.** Every `onnxruntime` from **1.24.0** onward publishes macOS **arm64 wheels
  only** — `1.23.2` is the last release with a `macosx_13_0_x86_64` wheel — and those
  three extras floored it at `>=1.27.0` with no marker. The same floor sat in
  `system/features.py`, so `yazses features enable read-back` failed there too.
- The requirement is now a PEP 508 marker fork (`>=1.23.2,<1.24` on Intel macOS,
  `>=1.27.0` everywhere else) with a matching `[tool.uv] constraint-dependencies` entry,
  because `useful-moonshine-onnx`, `onnx-asr` and `kokoro-onnx` also require
  `onnxruntime` with no marker of their own and a `[project]` marker cannot reach a
  dependency we do not declare.
- **The base install was never affected**, and the first draft of this entry said it was.
  `faster-whisper` asks for `onnxruntime<2,>=1.14`, so a resolver simply backtracks to
  1.23.2; `uv pip compile --python-platform x86_64-apple-darwin` confirms the committed
  pre-fix manifest resolving the base install cleanly. What was unsatisfiable was the
  three extras that stated the floor themselves.

### Fixed — `yazses[all]` still could not resolve on Intel macOS after that

- **Two more dependencies have no Intel macOS wheel at all**, and neither is fixable by
  choosing a version: `mediapipe` last shipped one in **0.10.21** (the `gaze` extra floors
  it at 0.10.35) and `torch`, which `pyannote.audio` pulls in, last shipped one in
  **2.2.2**. Resolving `yazses[all]` there failed on both.
- `all` now carries the platform marker on `mediapipe` and `pyannote.audio`, so **"install
  the lot" installs everything that can work on the machine asking**. `yazses[gaze]` and
  `yazses[diarization-pyannote]` deliberately keep failing loudly on that platform: an
  explicit request for one feature should say the feature is unavailable, not install a
  hollow subset.
- Gaze routing is X11-only by design (`gaze/desktop.py` returns `None` off X11), so on
  macOS this removes a ~100 MB dependency for a feature that could not have run there
  regardless.
- `tests/test_the_all_extra_is_the_union_it_claims.py` now understands markers: `all` may
  **narrow** a requirement to fewer platforms, never widen it, and never omit it.

### Changed — the 300 ms silence lead-in: no value is measurably better than none

- **The onset grid is now decided by a paired test, and it withdraws a claim.**
  `bench_onset.py` records the per-utterance outcome, so each cell is compared to its own
  row's baseline by exact McNemar. Sixteen comparisons; **none survives correction for
  multiplicity.** The previous text called the sign change "not marginal" and cited the
  40 ms row buying back 6–8 opening words — that row's best cell reaches only `p = 0.057`.
- **The only replicated signal runs the other way.** Two comparisons reach uncorrected
  `p < 0.05` in both replicates, both at 120 ms of lost speech, and both say the lead-in
  makes the opening word *worse* (143 → 127 at a 1000 ms lead, `p = 0.011`).
- `[accessibility] pre_speech_padding_ms` keeps its default of 300. Not vindicated —
  there is simply no evidence on which to move it, and it costs nothing measurable when
  the onset is intact (`p = 0.125`), which is the common case. What the grid *does*
  establish is that **no amount of prepended silence recovers a word that was never
  captured**: 120 ms of lost speech costs ~43 opening words in 200 and no lead-in
  recovers them.
- The grid itself is now the most reproducible thing on the page: **19 of 20 cells
  identical across four runs in two sessions**, while whole-utterance WER on those same
  rows moved by up to 0.88 points.

### Changed — the plausibility guard's recall is now published, and it is 1 in 12

- **The AMI test split had never been scored for whether the warning is *right*.** The
  benchmarks page reported that its two rules "agree 16 of 16", which compares the rules
  to each other and says nothing about either being correct. Scored properly at the
  shipped `[meeting] cluster_threshold = 1.2`: **twelve of sixteen recordings are
  genuinely over-split, and the guard fires on one.** Precision 1/1, specificity 4/4 —
  every warning it gave was true and it never interrupted a correct result — and recall
  **8%**.
- **This is the rule's shape, not its constant.** The test asks whether half the labels
  fall under the fragment threshold. Over-splitting in a forty-minute meeting means one
  participant cut into two *people-sized* clusters — `EN2002b` gives 6 labels for 4
  speakers with a smallest of 98 s, `ES2004d` gives 6 for 4 with two at 274 s and 498 s.
  A fragmentation test cannot see a merge-shaped error, so the ~2× residual over-count
  that ADR-v2-133's threshold change leaves behind is precisely the error its own guard
  is blind to.
- **The decision stands; the claim narrows.** The guard is a *catastrophe* detector — it
  caught the 86-label and 257-label results that produced the module — and it is not a
  check that speaker attribution is right. Both `docs/benchmarks.md` and ADR-v2-133 now
  say so with the number beside it, rather than leaving a reader to infer coverage from
  a false-alarm rate.

### Fixed — a published finding that a second run disproved

- **`docs/benchmarks.md` claimed `large-v3` "becomes the best Whisper checkpoint
  measured" on `test-other`. Re-running the matrix disproved it.** Same instance, same
  code, same 200 utterances: 4.86 % the first time, **7.69 %** the second — past
  `medium.en` (5.51 %) and `small.en` (5.59 %), from best of the four to worst. The
  companion claim that it "barely degrades" on hard audio (a 1.5× multiplier) went with
  it; the honest figure is 1.5× *or* 2.4× depending on the run. Both runs are now
  published side by side, because there is no basis for choosing one.
- **The re-run is a confirmed prediction, not only a correction.** Six of the eight
  engines returned **bit-identical** WERs. The two that moved — `tiny.en` by 0.16, and
  `large-v3` — are exactly the two the temperature-fallback mechanism isolated on
  `test-clean` weeks earlier, and `test-other` shares no utterance and no speaker with
  that split. The error breakdown says the same thing: `large-v3`'s substitutions are 87
  on both splits in both runs, while its `test-other` insertions went 89 → 184. It does
  not mis-hear more; it invents more.
- **This also retires the "small models are unstable" reading.** It is the smallest and
  the largest checkpoint, with the three in between stable on both splits — not a
  capacity effect but a first-choice decode that trips faster-whisper's
  compression-ratio and log-probability gates, `tiny.en` by truncating and `large-v3` by
  running on.
- **`_common.write_result` no longer destroys the run it replaces.** Every published
  table is keyed to a fixed filename, so the second `test-other` run overwrote the first
  and the numbers this page had been quoting survived only in a console log on a rented
  VM. A write that would *change* an existing file now copies the old one to
  `paper/results/history/`, named for the instant it was measured. An identical re-run
  archives nothing — reproducing a benchmark is the normal case and must not fill the
  directory with copies of the same numbers, or the directory stops being a record of
  disagreement. `tests/test_bench_result_history.py` pins all three behaviours.

### Added — the results behind every published number are committed, with their logs

- **`paper/results/` was gitignored.** `docs/benchmarks.md` opens on the claim that its
  numbers can be reproduced; `paper/benchmark/` was un-ignored months ago for exactly
  that reason, and the *results* those commands produce were still inside `paper/*`. The
  artifact naming the CPU, the OS, the library versions and the load average behind each
  published figure existed on one laptop and nowhere else — not citable, not comparable
  against a later run.
- **Provenance is stamped at the chokepoint.** `run_all.py` attached a shared block, so a
  single bench run from the command line — the documented way to re-measure one thing —
  wrote through `write_result` without one and overwrote the good file. Two of the seven
  archived results had no provenance at all. `_common.write_result` now stamps one when
  the caller did not.
- **`paper/results/probes/`** archives the exploratory measurements from a two-day window
  on rented compute: the diarization sweeps (including the one whose optimum turned out
  to lie outside its own range), the first DER on real human speech, the embedding-model
  comparison, the beam-size and lead-in grids, the plausibility-guard verdicts — each in
  an envelope naming the host, the producing script, and where a committed harness script
  has since replaced it. The run logs are archived beside them, redacted, because the
  per-recording lines are the part a later reader cannot reconstruct. The probe scripts
  themselves are committed under `paper/benchmark/probes/`: a number whose code is gone
  is not reproducible.
- **`tests/test_benchmark_results_are_archived.py`** fails the build on a result with no
  provenance, on a login name or home directory in any published file — logs included,
  since those were written on a machine where the home directory was in every path — and
  on a bench script that has neither an archived result nor a recorded reason it cannot
  have one.
- **The `*.log` rule would have swallowed the run logs.** `.gitignore` ignores `*.log`
  repository-wide, which is right everywhere except here: two of these 58 files are the
  *only* surviving record of a measurement, because a fixed result filename let a second
  run overwrite the first before `write_result` learned to displace into `history/`. The
  negation is narrow (`!paper/results/probes/logs/*.log`) and the reason is written
  beside it, so the next person to widen the global rule can see what it would cost.
- **Two of the three enforcement points agreed the archive was public; the one that
  decided did not.** `design/README.md` lists `paper/results/` as public and says in the
  same breath that `.gitignore`, `.git/hooks/pre-commit` and `hooks/design_tier.py` must
  agree, "changing one without the others is a bug". The hook still carried the
  allow-list written before any results existed, so the entire archive was uncommittable
  and the refusal read like a considered policy decision rather than a list that had not
  caught up. The allow-list is now anchored on extension rather than depth — harness and
  probe code as `.py`/`.md`/`.sh`, artifacts as `.json`/`.md`/`.log` — so a subdirectory
  under a published tree still cannot carry audio or the manuscript out.
  `tests/test_privacy_hook_blocks_what_it_calls_private.py` previously proved the hook
  does not under-block; it now also proves it does not over-block, taking the set of
  public trees from the contract table itself rather than restating it. Both directions
  were verified by mutation.
- **Committing the artifacts immediately caught a stale page.** The voice-activity-gate
  section reported 40 positive clips and a 3.4× median margin; re-running the bench to
  give `vad.json` its missing provenance produced 200 clips and 3.1×, and
  `tests/test_benchmarks_match_results.py` failed on the mismatch. The page now matches
  the artifact. That test could only ever compare the page against whatever happened to
  be on the machine — which is the case for committing the artifact in one line.
- **`bench_onset.py` records the per-utterance outcome, not only the count.** Two cells
  of its grid differ by four utterances in 200, and whether that is an effect or
  sampling noise is a *paired* question (McNemar over the utterances that change
  verdict). A count cannot be paired with another count, so the first version made its
  own smallest differences unanswerable without a full re-run.
- `bench_diarization.py` now records the corpus **name** rather than its absolute path,
  and writes into `paper/results/` by default; it only ever wrote where it was told to,
  which is why no diarization artifact had ever been archived.

### Added — the benchmark tables can now be asked whether a difference is real

- **A grid of percentages is not a ranking, and both published grids invited one.** The
  beam-size table's gaps are fractions of a point (4.01 against 4.07, 9.46 against 9.84)
  and the onset grid's are four utterances in 200; at n=200 the interval on any single
  cell is wider than every gap in its own table. Neither artifact carried what a
  comparison actually needs.
- **`paper/benchmark/analyze_onset.py`** — exact McNemar over the per-utterance
  first-word outcomes, paired within an arm and a cut. Paired, because every cell
  decodes the same 200 utterances and the ones both conditions agreed on carry no
  information; the exact binomial rather than the chi-square approximation, because the
  discordant count is routinely under ten and the approximation is not valid there.
- **`paper/benchmark/analyze_beam.py`** — paired bootstrap of the WER *difference*
  between two beam widths over shared utterance resamples (Bisani & Ney, ICASSP 2004).
  `bench_beam.py` now records per-utterance error counts and a 95 % interval so it has
  something to read. The pairing is the whole point and is tested as such: the guard
  computes an unpaired bootstrap on the same input and fails if the two intervals are
  not several times apart.
- **Both refuse an artifact that predates their input rather than falling back.** An
  unpaired test on two published levels would produce a number in the same confident
  tone while answering a different question, and the number is what gets quoted.
- **Beam search is not monotonic.** `base.en` on `test-other` scores 9.46 % at beam 5
  and **9.84 % at beam 8** — worse, for 8 % more decode — and `small.en` on `test-clean`
  is better greedy than at the shipped default. Whether either gap survives a paired
  test is open until the re-run lands, and the page says so instead of ranking the rows.
- **Every one of the twelve beam WERs reproduced bit-identically** across two runs on
  one instance half an hour apart, in separate processes with the models re-loaded,
  while their RTFs moved by up to 3 % — and by 23–26 % when a second job shared the
  box. Accuracy on a fixed subset is a property of the model; throughput is a property
  of the machine and of what else is running on it.
- **`tests/test_benchmarks_match_results.py` skipped when a result file was absent.**
  Correct while `paper/results/` was gitignored, a hole the moment it was committed: a
  deleted artifact would leave the page green with nothing behind it. A missing result
  is now a failure naming the file, and every measured beam row must appear on the page
  with both its WER and its RTF. The first version of that check matched the RTF by
  substring and passed `0.037` against a page saying `0.0377`.
- **`paper/benchmark/README.md` was five scripts behind** — `bench_beam.py`,
  `bench_onset.py`, `bench_plausibility.py`, `bench_streaming.py`,
  `bench_throughput.py`, and `make_features_table.py` made six. A reader deciding
  whether a published figure was reproducible would have concluded the instrument did
  not exist. `tests/test_bench_readme_lists_every_script.py` derives the set from the
  directory, in both directions, so the next one fails on the day it lands.

- **`paper/results/MANIFEST.md`** — one row per archived artifact naming what it
  measures, the machine it came from and when, generated by
  `paper/benchmark/make_results_index.py` from the files themselves. Sixty-six
  artifacts across two months, three machines and two dozen scripts had no index at
  all: which file backs a given figure, and whether two numbers were taken on the same
  machine, were answerable only by opening every file. Its guard checks the names
  against the **directory** in both directions rather than only re-running the
  generator, because a re-run-and-diff agrees with itself by construction and would
  pass a generator that silently skipped a whole subtree.
- **The headline WER table has no confidence interval and now says so.** The same three
  checkpoints on the same 200 utterances score 4.82/4.07/2.59 on the reference laptop
  and 5.18/4.01/2.66 on a 16-vCPU Xeon — every laptop figure inside the interval the
  Xeon run reports for the same model. Two tables on one page disagreeing by a third of
  a point reads as an error; it is the measurement, and the page now explains it.

### Measured — the same code on four instruction sets

- **`benchmark.yml` had never run.** Dispatched across every runner GitHub offers, it
  answers the standing objection that a WER is partly a property of the CPU that decoded
  it: CTranslate2 dispatches different int8 kernels per ISA and reduces partial sums in a
  different order. On 60 stratified `test-clean` utterances, `small.en` scored **2.05 %
  on all four** — x86_64 Linux, arm64 Linux, arm64 macOS, x86_64 Windows — while
  `base.en` spread 0.14 points and `tiny.en` 0.49. The spread closes as the model grows,
  which is the same pattern a thread-count experiment found on one laptop, now confirmed
  across architectures rather than across thread counts.
- The four runners' full artifacts are archived under `paper/results/platforms/`. Their
  **timings are deliberately not quoted**: the macOS runner reported a one-minute load
  average of 30.44 on three logical CPUs, which the provenance block records and a table
  of RTFs would have hidden.

### Fixed — the Intel macOS benchmark leg has never produced a number

- **`benchmark.yml`'s `macos-15-intel` row died in `uv sync` on every dispatch**, and
  `continue-on-error` turned that into a silent absence rather than a red job: a matrix
  row that looks measured and never was. `uv.lock` is one universal resolution and pins
  `onnxruntime` 1.28.0, which upstream publishes for macOS arm64 only — 1.23.2 was the
  last release with an x86_64 wheel — and `faster-whisper` depends on it unconditionally,
  so no choice of extras avoids it.
- `scripts/build-macos.sh` already resolves that leg unlocked for this exact reason; the
  benchmark workflow now does the same, resolving the project and the benchmark group in
  one command so the backtrack to 1.23.2 is made once with every requirement visible.
  Since `macos-15-intel` is the last Intel image GitHub offers (ADR-017), this is the only
  way the architecture is ever measured at all.
- **The workflow also cleared nothing before running.** Now that `paper/results/` is
  committed, the checkout arrives carrying another machine's results and the job uploads
  `paper/results/*.json` wholesale — so an artifact named for one runner would have
  contained a laptop's numbers next to its own, with only the provenance block to tell
  them apart.
- **How far this is verified.** The resolution was proven without a Mac —
  `uv pip compile --python-platform x86_64-apple-darwin` backtracks to
  `onnxruntime==1.23.2` and exits 0 — but a `workflow_dispatch` runs the copy of the
  workflow that is *on the branch*, so the leg itself cannot be exercised until this
  change lands. Until a dispatch produces `paper/results/platforms/macos-15-intel/`,
  Intel macOS remains the one architecture with no measurement, and the cross-ISA table
  says four runners rather than five.


### Fixed — the macOS app crashed on `yazses doctor`, and one tuple of strings was why

- **`system/doctor.py` imported `BSD_PREFIXES` from `yazses.platform.bsd`.** That module
  imports the Linux backend at module scope, because BSD reuses it wholesale — so a
  four-string tuple dragged the entire Linux platform package into `doctor` on every OS.
  From source this is invisible: a wheel carries every backend, the import resolves, and
  nothing looks wrong. Inside the PyInstaller macOS bundle, which correctly ships no Linux
  backend, `yazses doctor` died with `No module named 'yazses.platform.linux'`. The
  constant now lives in `platform/base.py` beside the other platform names, where asking
  "is this a BSD?" costs no backend import.
- **Nothing outside the platform package may now name an OS backend in a module-scope
  import**, checked two ways: by source across the whole tree, and by importing
  `system/doctor.py` in a subprocess and looking at what actually loaded. The backend set
  is derived from `platform/factory.py`'s own dispatch, so it stays right when a platform
  is added, and it correctly excludes `platform/emg/`, which is an activation source
  rather than an OS backend.
- Only the tag-time bundle smoke test could see this, which means it was found *during* a
  release rather than before one.

### Fixed — seven tests turned `main` red and skipped a release's PyPI publish

- **The benchmark harness's tests imported `psutil`, `jiwer` and `whisper-normalizer` at
  collection time.** Those live in the `benchmark` dependency *group*, which `uv sync`
  does not install, so every CI job running the suite raised `ModuleNotFoundError`. In
  `release.yml` that failed the `test` job and skipped `publish-pypi` outright.
- The mechanism to prevent this was already in the same file — three tests called
  `pytest.importorskip` for `scipy`, `jiwer` and `whisper_normalizer` — and the list was
  simply short of the dependency that mattered. A hand-written list of what to skip on is
  only ever as complete as the day it was written, so `tests/benchmark_deps.py` now
  **derives** the optional set from `pyproject.toml`'s `benchmark` group and from the bench
  module's own imports, transitively, `ast.walk`-ing into function bodies — because the
  imports that broke it were inside functions, so the module loaded cleanly and the failure
  landed at call time, several tests later.
- **A new `benchmark-harness` CI job installs the group and runs those tests on every
  push.** Skipping alone would have traded a red build for a silently green one:
  `benchmark.yml` is `workflow_dispatch` only, so nothing else would ever have run them.
  The job asserts the dependencies import before running anything, the same guard the `gui`
  job uses for Qt.


## [2.30.0] — 2026-08-24

### Measured — the 300 ms silence lead-in, and the guard's AMI claim

- **`[accessibility] pre_speech_padding_ms` does not do what the note beside it said.**
  Measured on 200 stratified LibriSpeech `test-clean` utterances with the leading room
  tone trimmed away (median 290 ms) so speech starts at sample 0: with the onset intact,
  every lead from 0 to 1000 ms lands inside the run-to-run noise band. Whisper needs no
  run-up. Where it *does* matter is when the key was caught late and speech is genuinely
  missing — and there it changes sign: 40 ms of speech gone and the lead-in recovers 6
  opening words in 200; 120 ms gone and it loses 11; 240 ms gone and it loses 4. The
  three clipped rows were run end to end twice and **all nine first-word counts
  reproduced exactly**, while WER moved by up to 1.0 point in the same cells. The
  default stays at 300 ms — the better half of the trade in the near-miss case, free in
  the common one — but the comment now states the measurement instead of a mechanism.
- **`tests/test_pre_speech_buffer_is_never_fed.py` overstated the surviving path.** It
  said the setting "works" through synthetic silence; that claim was the unmeasured one.
  Corrected to the numbers above, with the point it was written to protect intact: the
  variant that *could* recover a clipped onset retains real audio from before the key
  went down, and is deliberately never fed.
- **ADR-v2-133's "AMI is untouched" is no longer only arithmetic.** The full 16-recording
  AMI test split was scored at the shipped `cluster_threshold = 1.2` under both the flat
  20 s rule and the new scaled one: they agree **16 / 16**. The derived threshold clamps
  to the ceiling on twelve recordings, and on the four shorter sessions where it drops
  (13.8–19.1 s) no verdict changes. One firing under either rule, `IS1009d` — 6 labels
  for 4 speakers — and it is a real over-split.

### Fixed — a test hung every Windows CI run forever, and a hang reports nothing

- **`tests/test_settings_failure_is_visible.py::test_alert_is_a_no_op_off_windows` read
  `sys.platform` off the host,** so on Windows it took the branch its own name says it
  does not test: it called the real `user32.MessageBoxW`. That call is modal and
  synchronous — it returns the button the user clicked — so on an unattended runner it
  never returns. Four Windows CI jobs (runs `32661049814` and `32661231351`, Python 3.11
  and 3.12 alike) printed this test's name and then nothing for **2 h 30 m**, while the
  Linux and macOS jobs of the same runs finished in ten minutes. The test now forces the
  platform, so it tests the off-Windows guard on every OS instead of only where the guard
  is trivially true.
- **The success path had no test at all.** `alert` could have degraded to a permanent
  `return False` — the silence it exists to escape — and stayed green. A recording double
  now pins that on Windows it really calls `user32` with the message, the title and the
  documented flags.
- **A `conftest.py` tripwire makes the whole class of fault impossible.** Any test that
  reaches the real `MessageBoxW` now fails at teardown naming itself. It records rather
  than raises, because `wincon.alert` swallows every exception by design: a raise would
  be caught, turned into `return False`, and the test would pass with the box on screen.
- **Why it survived every Windows run until now.** A hang produces no result, not a red
  one, so nothing was ever reported. It only became reachable once the `os.kill(pid, 0)`
  liveness-probe crash at 49% was fixed and the run got far enough to meet it.

### Fixed — the "silero" VAD backend documented itself as cheap and costs 3 GB

- **`src/yazses/meeting/silero_vad.py` claimed "the ONNX path avoids a torch dependency".
  It does not.** `silero-vad` declares `torch` and `torchaudio` unconditionally — not
  behind its own `onnx-cpu` extra — and imports torch at module scope, so the ONNX path
  avoids torch only at inference. Resolved against this project's venv, `[silero]` adds
  **25 distributions, ~3.0 GB**, most of it the NVIDIA CUDA stack, on a CPU-only offline
  dictation tool. `[meeting] vad_backend` now states that cost where the choice is made,
  so it reaches `docs/configuration.md` rather than living in a module nobody opens.
- **The cache-first guard could not see a whole shape of call.**
  `tests/test_model_cache_first.py` scanned only *attribute* calls
  (`moonshine_onnx.MoonshineOnnxModel(...)`), so a loader imported directly — the ordinary
  way to call a module-level function, and how `load_silero_vad` is called — was invisible
  to the inventory that exists to prove no loader is missing. It now reads both shapes.
- **Loaders that need no wrapper are now listed with their reason, not omitted.** A new
  `_BUNDLED` registry records that `silero-vad` ships its ONNX inside the wheel and
  resolves it through `importlib.resources` — no hub, nothing to revalidate, nothing to
  hang — because an unwritten judgement is indistinguishable from an oversight, which is
  exactly how three loaders went unguarded before. A machine on which the extra *is*
  installed additionally checks that the ONNX is really there, so silero-vad moving its
  weights to the hub fails the build instead of silently reintroducing the hang.

### Fixed — the Flathub listing advertised 2.29.0 and the build installed 2.18.2

- **The Flatpak pinned `yazses-2.18.2-py3-none-any.whl` — eleven releases behind what its
  own store listing announced.** `packaging/flatpak/python3-yazses.json` now pins 2.29.0,
  URL and `sha256` both.
- The reason it went unnoticed is instructive: `test_the_newest_release_entry_matches_the_project_version`
  already held the **metainfo** to `pyproject.toml`, so the advertised half was kept current
  automatically while the installed half — a different file, checked by nothing — stayed
  where it was. Half a relationship checked is not the relationship checked. The pin is now
  held to the project version too, so bumping the version has to bump both.
- **Every Linux runtime dependency is now required to be pinned in the manifest.** The
  dependency list is regenerated only by a manual `workflow_dispatch` run whose artifact a
  human commits — it cannot be produced on a laptop, since the wheels must match the
  runtime's Python inside `org.kde.Sdk` — so a dependency added to `pyproject.toml`
  afterwards would simply be absent from the Flatpak. Platform-gated dependencies are
  excluded by reading their environment marker rather than by name, so the macOS and
  Windows ones stay correctly out of a Linux build without a list to maintain.

### Fixed — the config we hand people told them to undo a bug fix

- **The example config three packagers install stated two values the code disagrees
  with.** `examples/config.example.toml` is what `scripts/build-deb.sh`, `debian/rules`
  and `packaging/arch/PKGBUILD` all put in `/usr/share/yazses/`, and what the README
  links to — while `examples/config.toml`, which is generated from the dataclass defaults
  and stale-checked, ships nowhere. It set `[stt] model = "tiny.en"` against a default of
  `base.en`, silently downgrading accuracy for anyone who copied it, and
  `[audio] max_record_seconds = 90` against a default of `300` — the ceiling that was
  raised *because* 90 was cutting long dictations off, so copying the file re-introduced
  the bug that raised it.
- **The README's own config block was further out.** Under "Essential settings" it showed
  `model = "small.en"`, `max_record_seconds = 90` and `vad_threshold = 0.0008` against a
  shipped default of `0.01` — a silence gate twelve times more sensitive, handed to every
  reader of the front page, predisposing them to exactly the spurious-transcript problem
  `yazses mic-level` exists to fix. Neither `tiny.en` nor `0.0008` was ever the default:
  both have been what they are since the initial commit.
- **The Russian and Hindi landing pages carried a fifth error and a stale fourth value.**
  Their blocks were byte-identical to each other, every comment in English — copies of an
  older README, not translated content — offering `key = "space"` as the hold-to-talk key
  and `xdotool` as an injection backend the README says is not a token. Both now carry the
  corrected block. `docs/zh-CN/index.md` deliberately deviates and is untouched: a Chinese
  setup must set `[stt] language` and a non-`.en` model.
- Two guards already swept `examples/` and neither could see any of this: one rejects a
  key that does not **exist**, the other a key nothing **reads**. A live, correctly-spelled
  key holding the wrong *value* passed both. Values were the unchecked axis, and are now
  checked — with the swept region derived from the packaging scripts themselves, so
  pointing a packager at a different example tomorrow is covered without editing a list.

### Fixed — the new attribution guard fired on half of a corpus, and lied in three of those

The implausible-attribution warning shipped earlier in this cycle with a flat threshold:
a speaker label holding under **20 seconds** across a whole recording is a fragment, and
a result that is mostly fragments is unreliable. 20 s was measured on AMI, where a
recording runs forty minutes.

Scored against VoxConverse — short broadcast and web video, which is exactly what
`yazses transcribe` is handed — at the shipped `[recimport] cluster_threshold = 1.0`, it
fired on **7 of 15** recordings and only 4 of those were genuinely over-split. The other
three had a speaker count that was exactly right (8 labels for 8 people) or *too low*
(9 for 12, 14 for 17), so the sentence it printed — "a person's worth of speech split
apart rather than that many people" — was **false about the result it described**. A
guard that fires half the time and misdiagnoses three of those firings trains the user to
dismiss it, and then it is not protecting anything.

The threshold now scales with the recording: `min(20 s, max(5 s, 2 % of total speech))`.

| | VoxConverse @ 0.9 | VoxConverse @ 1.0 | 3-minute shatter |
|---|---|---|---|
| flat 20 s | 8 fire, 1 false | 7 fire, **3 false** | caught |
| scaled | 6 fire, **0 false** | 4 fire, **0 false** | caught |

Three things make this safe to change days after shipping it:

- **It can only relax.** The derived threshold is bounded above by the 20 s every
  published measurement used, so no result that was silent before can start warning.
- **AMI is untouched.** 2 % of half an hour is 36 s, above the ceiling — so the ADR's
  table and the 257-labels-for-four-people catastrophe that produced the module are still
  evaluated at exactly 20 s.
- **The floor is doing work a proportion cannot.** Shatter a three-minute clip into forty
  equal slivers and every label holds exactly `total/40`; a fraction-of-total threshold
  moves with the shattering and never catches it. Under five seconds of speech in a whole
  recording is not a participant on any recording length.

What it still does not cover is unchanged and stated in `design/adr/adr-v2-133`: it is
one-directional, so under-splitting and a collapse into a single cluster both pass.

### Fixed — what `beam_size` actually costs, instead of what the source assumed

`config.py` described `beam_size = 1` as "measurably faster and measurably worse". Both
halves were assumptions, and both are wrong in a way that matters to the Adaptive Latency
Governor, which is the thing that turns greedy decoding on.

Measured, 200 LibriSpeech utterances per cell, idle 16-vCPU Xeon, through the shipping
engine factory:

| Model | Split | beam 1 | beam 2 | beam 5 *(default)* |
|---|---|---|---|---|
| `base.en` | `test-clean` | 4.39 % | **4.01 %** | **4.01 %** |
| `base.en` | `test-other` | 10.56 % | 9.49 % | **9.46 %** |
| `small.en` | `test-clean` | **2.53 %** | — | 2.66 % |
| `small.en` | `test-other` | 6.18 % | — | **5.59 %** |

"Faster" is **11–16 %**, not a category change — about 20 ms on a five-second burst,
because the beam is not where a Whisper decode spends its time. "Worse" is a property of
the model and the audio rather than of beam search: greedy costs `base.en` 0.38 points on
clean audio and 1.07 on hard audio, and on `small.en` with clean audio it is *better* and
faster. And everything beam 5 buys, **beam 2 already has** — beams 2, 5 and 8 score
identically on `base.en`.

The default is unchanged. Beam 2 would save about 20 ms per burst, which nobody can
perceive, and 5 is the setting the rest of the world runs. What changes is that the
Governor's trade is now a number instead of a guess, and that `docs/benchmarks.md` and
the configuration reference carry it.

### Fixed — `pip install yazses[all]` was missing eight extras, and two guards said it could not be

- **`[all]` is now the union of every other extra**, computed and checked rather than
  remembered. It was hand-maintained and had fallen eight extras behind, so an install
  that asked for everything got no denoise, no Chinese script normalisation, no Silero
  VAD, no Moonshine, no EMG band, no MCP agent and no pyannote diarization — nine
  requirement strings in total. The omissions were never a resolver constraint:
  `pyproject.toml` declares no `conflicts` and `uv.lock` already resolved all nine
  together, so adding them changed the lock by fourteen lines and moved no version.
- The one deliberate exclusion is `voiceprint-resemblyzer`, which pins `setuptools<81`
  for the whole environment; an install asking for "everything" should not silently hold
  an unrelated build tool back, and its seam's default backend (ECAPA via `speechbrain`)
  is already in `[all]`. The reason is stated beside the list, and a guard fails if an
  exclusion loses its stated reason, names an extra that no longer exists, or points at a
  seam whose default backend has since left `[all]`.
- Two places already treated `[all]` as a computed aggregate and exempted it on that
  basis — `scripts/check_dependency_budget.py` and `tests/test_feature_pins_match_the_extras.py`.
  Both exemptions were sound given the relationship they named, and neither computed it,
  so both stayed green while it stopped holding. The equality is now proved in **both**
  directions: a new extra that `[all]` forgets fails, and so does a pin bumped in one
  place only, which would leave `[all]` quietly resolving an older version.

### Fixed — the 56 best-documented config keys were the ones the reference page said nothing about

`docs/configuration.md` derives its Notes column from the comment beside each field in
`config.py`, which made documenting a key the same act as commenting it. It read only
**trailing** comments — the `# ...` written after the field on the same line. An
explanation that runs to a paragraph cannot be written there, so the keys whose meaning
needed the most saying were exactly the ones that reached the page with an empty cell:
`[stt] engine`, `model`, `language`, `initial_prompt`, `cpu_threads`, `beam_size`,
`chinese_script`, `[injection] backend`, `[audio] device`, `[accessibility]
pre_speech_padding_ms` and 46 others, every one of them already explained at length in
the source directly above the field.

A leading comment block at the field's own indent is now read too. Indent equality is
the whole guard, and it is exact rather than approximate: a wrapped *trailing* comment
continues in the column of the `#` that opened it, always further right than the field
indent, so a continuation can never be mistaken for the next field's block — the misfiling
the trailing-only reader was written to avoid. `#:` is stripped, since two sections use
the sphinx attribute-comment spelling and the marker was reaching the page.

Two `[stt]` keys turned out to be undocumented in the source as well, and both are traps:
`device` (YazSes is CPU-first — every benchmark, latency target and model recommendation
assumes int8 on CPU, so `"cuda"` is supported but unmeasured) and `compute_type`, whose
supported set is a property of your CPU rather than of this project, and where an
unsupported value raises inside `WhisperModel(...)` and is reported as a missing *model*.

One existing guard had to be corrected rather than satisfied: it required every section's
`backend` note to be unique, as a proxy for "the lookup is keyed by class, not by field
name". `[recimport]` and `[meeting]` document their sherpa/pyannote choice in the same
words on purpose, so a correct extraction now fails a distinctness test. It asserts the
real property instead — each section's note must be written in that section's own source.

### Added — every shipped STT engine measured against every other, on easy and hard audio

`docs/benchmarks.md` compared three Whisper checkpoints on a laptop and described the
other engines on their vendors' word. All eight are now measured under one method — the
same 200-utterance speaker-stratified LibriSpeech subset, the same normaliser, every
engine built through the shipping `stt.factory.build_engine`, on an otherwise idle
16-vCPU Xeon:

| Engine / model | WER | Sub | Ins | RTF |
|---|---|---|---|---|
| `parakeet-tdt-0.6b-v2` | **2.06 %** | 73 | 11 | 0.050 |
| `small.en` | 2.66 % | 100 | 8 | 0.092 |
| `moonshine/base` | 3.17 % | 110 | 23 | **0.023** |
| `large-v3` | 3.23 % | **62** | **89** | 0.451 |
| `medium.en` | 3.28 % | 86 | 40 | 0.246 |
| `base.en` (default) | 4.01 % | 141 | 30 | 0.042 |
| `moonshine/tiny` | 4.20 % | 152 | 28 | 0.016 |
| `tiny.en` | 5.18 % | 166 | 42 | 0.028 |

The large Whisper models lose on **insertions, not recognition**: `large-v3` has the
fewest substitutions of anything measured and eleven times `small.en`'s insertions. And
`moonshine/base` reaches `large-v3`'s accuracy at twenty times the speed. Neither fact
was visible while the engines were being compared across separate published tables.

### Added — `--split test-other`, so "your WER will be worse" is a number

The benchmark harness only knew about LibriSpeech `test-clean`, so the page had always
warned that real WER is worse without measuring anything worse. `bench_wer.py` now takes
`--split` (`test-clean` | `test-other`) and writes to a split-specific result file, so a
hard-split run can never overwrite the headline numbers.

On `test-other` the default `base.en` goes from 4.01 % to 9.46 % — the difference between
an occasional fix and one word in ten. **The ranking inverts**: `small.en` beats
`medium.en` and `large-v3` on clean audio and falls behind both on hard audio, because
`large-v3`'s substitutions barely move (87 → 87) while `small.en`'s rise (100 → 161).
Parakeet (1.4×) and `large-v3` (1.5×) degrade least; everything else lands between 1.7×
and 2.5×.

### Fixed — a benchmark number that changes when you measure it twice, and one dictation that does

Repeating the whole matrix on the same box, same code, same subset: six of eight engines
return byte-identical numbers, and `tiny.en` (4.93–5.25 %) and `large-v3` (3.23–3.98 %)
do not. Decoding the same subset **twice inside one process** still differs on one
utterance in two hundred, and seeding CTranslate2's RNG changes nothing.

Decoding that one clip forty times names the mechanism. Its greedy decode *fails* and
emits a single word; faster-whisper's default `temperature=[0.0, 0.2, … 1.0]` fallback
catches that on the compression-ratio and log-probability checks and re-decodes by
**sampling** — 34 distinct outputs in 40 runs with defaults, exactly 1 with
`temperature=0.0`, and that one is the truncated word. Disabling the fallback is not a
fix; it trades a random correct-ish sentence for a deterministic wrong one.

This is a **product** behaviour, not only a benchmark artefact: on `tiny.en`, dictating
one long sentence twice can return two different transcripts, or one word. `base.en`,
`small.en` and the rest give one output in 40 either way, so the shipped default does not
do this — but anyone who picked `tiny.en` for speed is exposed to it. The published
`tiny.en` and `large-v3` rows now carry the spread instead of a false second decimal.

### Changed — the Parakeet speed claim was off by more than a factor of two

Five places said Parakeet TDT "beats whisper-large-v3 at roughly 4x whisper-small CPU
speed". The accuracy half survives measurement; the speed half does not.

On 200 LibriSpeech `test-clean` utterances, 16 Xeon vCPUs, int8 CPU, everything through
the shipping engine factory:

| engine | WER | real-time factor | vs `small.en` |
|---|---|---|---|
| `parakeet-tdt-0.6b-v2` | **2.06 %** | 0.050 | **1.8× faster** |
| `small.en` | 2.66 % | 0.092 | — |
| `large-v3` | 3.23 % | 0.451 | 0.2× |

So Parakeet is about **twice** whisper-small's speed, not four times, and ~20× realtime
rather than the vendor's ~30×. Two independent runs on the same box agree (1.79× and
1.84×). The accuracy claim holds and is now local rather than inherited — and the reason
it holds is worth stating, because it is not that Parakeet recognises better: `large-v3`
has the **fewest substitutions** of any model measured (62, against `small.en`'s 100) and
the **most insertions** (89, against 8). On dictation-length clips the large Whisper
models add words nobody said, and that is what costs them the comparison.

`docs/architecture.md`, `docs/features.md`, `docs/research/voice-control.md`,
`ROADMAP.md`, `src/yazses/config.py`, `src/yazses/stt/parakeet.py` and
`src/yazses/system/features.py` now quote the measurement.

### Changed — the speaker-clustering default was measured for the first time, and it was wrong

`[recimport] cluster_threshold` moves from `0.5` to `1.0` and `[meeting] cluster_threshold`
from `0.5` to `1.2`. Both had been carried since the feature shipped on the sherpa-onnx
example's value, never measured against annotated audio.

Measured on the **full AMI test split** (16 recordings, 543.7 minutes of real meetings,
scored against the human RTTM annotation):

| `cluster_threshold` | DER | mean speaker-count error |
|---|---|---|
| `0.5` (shipped) | 75.21% | +155.19 |
| `1.2` | **26.71%** | +2.06 |
| `0.5` + `max_speakers=4` (the exact truth) | 29.42% | +0.06 |

The shipped default invented **86 to 272 speakers** in a four-person meeting. It is a
dendrogram cut height under complete-linkage clustering, so it has to clear the worst-case
distance between two windows *of the same voice* — which grows with the length and
variability of the recording. `0.5` was a value for short, clean, few-speaker clips.

Two consequences beyond the number:

- **The threshold beats supplying the exact speaker count.** `26.71%` at `1.2` against
  `29.42%` for a run told the truth up front. `yazses transcribe --speakers` and Meeting
  Mode both advertised that flag as the fix for bad attribution; the hint has been rewritten
  to quote what was measured (the estimate is exactly right in 2 of 16 recordings) instead
  of promising an improvement, and to warn that the value is an *exact* count, not a maximum.
- **The two defaults are deliberately different.** On VoxConverse (15 dev recordings,
  137.7 minutes of broadcast and web video — shorter, noisier, up to 20 speakers) the
  optimum is `0.9` at 16.30% DER, with `1.2` collapsing to 42.13%. `[meeting]` gets `1.2`
  because meeting audio is what it records; `[recimport]` gets `1.0` because it imports
  whatever file it is handed — `1.0` costs one point of DER against the VoxConverse optimum
  (17.34%), has the lowest speaker-count error of the whole sweep (+0.73), and degrades
  gracefully toward meeting audio rather than off a cliff.

Full sweeps, both corpora, wins and losses, in `docs/benchmarks.md`; the decision and what
it does *not* claim in `design/adr/adr-v2-133-diarization-clustering-default.md`.

### Fixed

- **`yazses gaze calibrate` downloaded 219 MB and then refused.** Three things can stop
  calibration, and two of them are free to check: `[gaze] enabled` is a config flag, and
  the X11/`xdotool` desktop backend is a probe of the running session. Only the third —
  are the webcam dependencies present — needs an install, and it is the only one an
  install repairs. They were checked in the opposite order.

  So on a default install (`[gaze] enabled` is `false`) the command printed *"this
  downloads up to ~219 MB (12 packages), plus ~3.7 MB of model files"*, fetched it, and
  then said *"Ensure `[gaze] enabled = true`"*. On Wayland it fetched the same 219 MB to
  announce that external window focus is forbidden there — which no download can change.
  The project had already settled the principle elsewhere: `system/backends.py` exists so
  a factory "never sends the user after an extra that cannot supply that backend".

  The free questions are now asked first, by a pure `calibration_blocker()`, and each
  refusal names what to do instead. The turnkey install is unchanged once calibrating is
  actually possible. `yazses gaze status` no longer offers `yazses gaze calibrate` as the
  alternative for a disabled machine either — that was a pointer to a command that refuses.

  The reason this survived is that the test suite asserted it: the auto-install tests
  built a bare `Config()`, in which `[gaze] enabled` is `false`, and required the
  installer to run anyway. Those fixtures now describe a machine where calibration can
  work, and the ordering is pinned separately.

- **The liveness probe killed the process it was asked about, and on Windows that was the
  test runner.** Running the full suite on a real Windows Server 2022 box, it died at 49%:
  silently, with exit code 0, no traceback and no summary line. Twice, in the same place.
  The killer was the test whose entire job is to prove the probe answers both ways —
  `test_the_liveness_probe_is_not_trivially_true_or_false`, which asks whether *this*
  process is alive. `tests/conftest.py::_alive` spelled that `os.kill(pid, 0)`, the POSIX
  idiom, and CPython's `os.kill` on Windows has no signal semantics: anything that is not
  `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` falls through to `TerminateProcess(handle, sig)`. So
  signal 0 terminates the process and hands it exit code 0 — a failure indistinguishable
  from a pass to anything reading a status code, which is why no Windows run had ever got
  past the halfway mark and nothing said so.

  **The same idiom was still in shipped code.** `system/pid.py::is_running` is reached by
  `yazses status`, `yazses doctor` and the tray's poll loop, and on the branch where a PID
  file exists without a held lock — a daemon killed with `-9`, or an install predating the
  lock file — it terminated whatever process held that PID. After a PID recycle that is not
  the daemon; it is an unrelated program, killed by a status query, which then reports "not
  running".

  The project already knew. `platform/windows/lifecycle.py::process_alive` carries this
  explanation and the read-only `OpenProcess` + `GetExitCodeProcess` replacement, written
  after the probe was caught killing the very daemon `status` was asked about. What it did
  not do was own the only copy, and the guard that was supposed to prevent a second one —
  `test_is_running_never_calls_os_kill` — names one class and hands it a stub probe, so the
  real call never ran and it stayed green through both surviving call sites.

  The probe now has one home, `system/proc.py`, and three callers. The new guard walks the
  AST of every file under `src/`, `tests/`, `paper/`, `scripts/` and `hooks/` and fails on
  any `os.kill(_, 0)` outside the two files allowed to spell it: the implementation, where
  it sits behind a `sys.platform` branch, and the macOS lifecycle, which cannot execute on
  Windows at all. Verified on the same Windows box that produced the crash.

- **The tray greyed out Meeting Mode and never said why.** `MeetingEntry` states its own
  contract — `reason` is never empty on a disabled entry, because "a greyed-out entry with
  no explanation is worse than no entry at all: the user is left deciding between *this is
  broken* and *I am not allowed*, and the answer is usually neither." The Linux tray
  honoured it by hanging the reason off `QAction.setToolTip`, and a `QMenu` renders action
  tooltips only when `toolTipsVisible` is set. Nothing in the tree ever set it —
  `grep -rn "ToolTipsVisible" src/ tests/` returned nothing — so the reason was computed,
  attached, and never shown.

  The state it hid is the default one: Meeting Mode is off until you enable it, so a fresh
  install opens the tray menu to two dead entries and no explanation. The macOS and Windows
  trays leave both entries clickable and show the daemon's own refusal as a toast, which
  left Linux — the one tray that goes to the trouble of predicting the refusal — as the
  only one that could not explain it.

  A tooltip alone would not have been enough either. Where the desktop renders the tray
  menu itself (GNOME with AppIndicator exports it over dbusmenu) the popup is not a Qt
  widget, so no tooltip is ever drawn. The reason now appears as a visible, disabled line
  above the two entries whenever both are blocked for the same cause, and
  `toolTipsVisible` is switched on so the per-entry reasons work where the menu *is* Qt.
  `meeting_notice()` derives that line from the entries rather than re-reading the status,
  so the banner cannot come to disagree with what is actually greyed out.

- **The settings window started a 3.1 GB download and called it "a few minutes".**
  `yazses features enable <slug>` says what an install costs *before* it spends it
  (ADR-018) — it prints the marginal download note, and for a large one prefixes it with
  "⚠ Large download —" and "Ctrl-C now to stop", because "a download that turns out to be
  gigabytes is one the user should have been able to cancel". The settings window did none
  of it: nothing under `settingsui/` referenced `depsize` at all, `_auto_install` defaults
  to **true**, and the one line it showed was `Installing packages for <slug>… this can
  take a few minutes.`

  Measured against the real registry: 19 capabilities have a priceable install and **9**
  are ones the CLI shouts about — `multiprofile`, `cocktail` and `voiceguard` are each
  **~3.1 GB**, and `stt-parakeet` fetches ~600 MB of model files.

  It was worse in the window than in the terminal, not better. There is no cancel here:
  the install worker exposes no interrupt and Apply is disabled while it runs, so the
  CLI's "Ctrl-C now to stop" has no equivalent to offer. The number *before* the click is
  the only warning that can help — and this is the surface the settings epic exists to
  serve, i.e. the user least likely to have a terminal open to notice a disk filling.

  The window now shows the same marginal size the CLI quotes, marks a large one as such,
  and says plainly that it cannot be stopped once started. The decision is a pure function
  in `settingsui/deps.py` (`describe_install_start`) like the rest of that package, so the
  whole message matrix tests without a display, and a test fails the build if the Qt layer
  goes back to a hardcoded sentence of its own.

- **`yazses meeting relabel` re-cut the transcript it promised only to re-render.** Its
  own docstring says it re-renders "from `transcript.json`, never re-diarizing", and the
  CLI help says it "only re-renders". What it did was rebuild every utterance from the
  stored *words* through `merge_utterances` — the **diarized** path's segmentation rule —
  so relabelling reshaped the transcript in two ways the finalize pass had deliberately
  decided against.

  `recimport/pipeline.py` calls `merge_utterances` only under `if diarized:`; an
  undiarized recording gets exactly one utterance spanning the whole of it, because with
  no speaker turns there is nothing to break a run on and a silence gap is not a turn.
  `relabel` called it unconditionally, so a non-diarized transcript came back gap-split on
  the 1.0 s default. Measured on a real 11.6 s meeting: one utterance in, two out. Every
  meeting `yazses meeting list` reports on that machine is non-diarized — the normal state
  without the diarization extra, and exactly the user who reaches for `relabel` to put a
  name on an un-attributed transcript.

  The pipeline also runs `clean_text` over the utterances and drops the ones that clean to
  nothing, because Whisper narrates silence: an 11.6 s meeting of room noise finalized as
  `". . ."`. `relabel` rebuilt from `words`, which the pipeline leaves uncleaned on purpose
  (they are timing data feeding alignment and subtitle spans), and applied no cleaning of
  its own — so on the diarized path the artefacts the finalize pass had removed came back
  on the first relabel. Neither showed up as an error: the command printed the paths it
  wrote and exited 0.

  `relabel` now keeps the stored utterance shape when the meeting is not diarized, and
  shares the finalize pass's cleaning rule (`recimport.pipeline.cleaned_utterance`, made
  public for the purpose) rather than carrying a second copy of it that could drift. It is
  now idempotent — verified against all four stored meetings.

- **The Moonshine speech engine crashed on every utterance.** `[stt] engine = moonshine`
  raised `AssertionError: audio should be of shape [batch, samples]` from inside the
  upstream package for any audio at all, so the engine `docs/models.md` compares against
  the others had never transcribed anything.

  The adapter reshaped the buffer to `(1, N)` because that is what upstream's assertion
  message asks for. The assertion runs *after* `transcribe()` has called `load_audio()`,
  whose last line is `return audio[None, ...]` — it adds the batch axis itself, for any
  input that is not a file path. A pre-batched array therefore arrives as `(1, 1, N)` and
  fails the check the reshape was written to satisfy. The caller has to pass the array
  un-batched, and now does.

  The unit tests could not see it: the fake `moonshine_onnx` recorded its argument and
  asserted nothing, so it accepted a shape the real package rejects — a double built from
  the same misreading as the code it stands in for. It now mirrors upstream's actual
  pipeline (batch, then assert), and two new tests pin `load_audio`'s behaviour against
  the installed wheel rather than against the assertion's wording.

  Found by running the WER benchmark across every engine on real audio; it is not
  reachable from any test that mocks the package.

- **`yazses doctor` told a machine with a flawless install to reinstall the package.**
  Found on real hardware — a Windows Server 2022 box with zero sound devices — where the
  microphone row read *"PortAudio could not be loaded … this means a broken or partial
  install — run: `pip install --force-reinstall sounddevice`"*. The install was perfect.

  `sounddevice` calls `Pa_Initialize()` at module scope, so `import sounddevice` fails for
  two unrelated reasons and the exception type is the only thing that separates them: an
  `OSError: PortAudio library not found` means the runtime really is absent, while a
  `PortAudioError` can only be raised by a PortAudio that already **loaded**. The doctor's
  probe caught `Exception` and called both "missing", so a machine with no audio system at
  all was sent to reinstall a package that was never the problem — and after the reinstall
  the row says exactly the same thing.

  The same reasoning had already been applied once, to `system/diagnosis.py`, whose comment
  records that a `PortAudioError` proves PortAudio loaded and whose test names error `-9986`
  among the codes that must not be diagnosed as a missing library. That is precisely the
  code Windows raised. Two guards with two vocabularies, only one of them narrowed. The
  microphone row now distinguishes the two states and, for the second, says what is actually
  wrong per OS (no input device, or the sound service is not running) and says plainly that
  reinstalling will not help.

- **`yazses remote --stop` reported a failed disconnect as a successful one.** The remote
  injector proxy is one of exactly two paths in the daemon that can send what the user
  actually said off this machine (ADR-019), so "Remote session disconnected." is a privacy
  claim rather than a status line — and it was made unconditionally.

  `_handle_remote_stop` dropped the forwarder from the daemon *before* tearing it down,
  then caught everything `disconnect()` raised with a log line and returned `ok`.
  `RemoteForwarder.disconnect` clears its handle to the SSH child on its last line, so a
  `terminate()`/`kill()` that raises — a reaping race, a credential change — left the
  tunnel up with nothing holding a reference to it: no later `--stop` could reach it, and
  the user had already been told it was closed. The handle now goes back, unless a new
  session claimed the slot while the teardown was running outside the lock, and the
  failure is reported instead of swallowed.

  The CLI compounded it: the stop branch printed its error to stdout and exited 0, unlike
  the connect branch three lines below it, so a script could not tell the two apart.

- **`yazses remote --stop` demanded a host it then threw away.** `--stop` calls the daemon
  with no arguments — the daemon knows which session it holds — but `host` was a required
  positional, so `yazses remote --stop` exited 2 with "Missing argument 'host'" and closing
  a tunnel meant retyping the machine it went to. The argument is now optional; connecting
  without one fails with a sentence naming what is missing rather than a usage dump.

- **The accessibility wizard reset the accessibility settings.** `yazses enroll`
  measures two values and used to write them by deleting the whole `[accessibility]`
  section of `config.toml` and appending a fresh one — silently resetting the other five
  keys to their defaults: `pre_speech_padding_ms`, `vad_source`, `dysfluency_friendly`,
  `read_back` and `confirm_timeout_s`.

  `dysfluency_friendly` is the sharp end of it. That is the setting a disfluent speaker
  turns on deliberately, and this is the wizard written for that user; losing it as a
  side effect of calibrating a microphone inverts the purpose of the command.

  The writer had a second branch that round-tripped through `tomllib` and `tomli_w`,
  which keeps the keys and destroys every comment in the file instead. It never ran:
  `tomli_w` is declared by no extra and appears in `pyproject.toml` only inside a mypy
  override list, so the destructive fallback was always the live path. Both are gone —
  the wizard now writes through `system/configedit.py`, the comment-preserving writer
  `features`, `hotkey set`, `audio use` and `mic-level --set` already share.

- **Six surfaces told the user to install a VS Code extension that does not exist.**
  The `yazses jump` failure message, two `LspContextProvider` log lines, the `jump`
  entry in the feature registry (and so `docs/features.md`), `docs/cli-reference.md` and
  `docs/privacy-statement.md` all offered "install the YazSes VS Code extension" as the
  way to get an editor bridge. No such extension exists: there is no source for it in
  this repository, no marketplace listing and no publish workflow, and every design note
  that mentions it calls it a deferred, separately shipped artefact. A user who followed
  the instruction searched the marketplace, found nothing, and had no way to tell whether
  they had missed a step or the tool was broken.

  For `jump` it was worse than unhelpful. `VSCodeBridge.get_symbols` returns `{}` and
  `apply_motion` returns `False`, and `jump` calls both — so a published extension would
  still not have made the command work through that bridge. The message now names Neovim
  as the way to do it and says plainly that VS Code cannot.

  `tests/test_no_phantom_vscode_extension.py` scans `src/yazses/**.py` and `docs/**.md`
  for the wording, which is how the sixth site was found after a hand-audit had already
  been done. `design/` is out of scope: a design note may propose an artefact, and
  calling it deferred there is the honest thing to do.

- **`yazses fileopen` told every BSD user their OS was unsupported.** The launcher
  gated on `sys.platform.startswith("linux")` and fell through to
  `NotImplementedError: Unsupported platform: freebsd14` on FreeBSD, OpenBSD, NetBSD
  and DragonFly — the four systems `platform/factory.py` builds a real backend bundle
  for. `xdg-utils` is in ports and pkgsrc exactly as `xdotool` and `xclip` are, which
  is why the BSD backend is a thin composition over the Linux one rather than a
  parallel implementation; this was the last gate in `src/` outside `platform/linux/`
  that had not been told. The check now goes through `platform.bsd.is_bsd`, so it is a
  prefix match — `sys.platform` carries the major version and is never the bare OS name.

- **`yazses tune` proposed priming Whisper with words Whisper had made up.** The
  vocabulary proposal mines terms that appear in the "better" text of an event but
  not in what the live model produced, and "better" accepted either a human
  correction *or* `tune`'s own re-transcription by a larger Whisper. For spelling
  that is circular: `initial_prompt` priming exists precisely for words Whisper
  cannot spell, so the one source that must not supply the spelling is Whisper.

  Measured on a real 1646-event corpus: all 21 offered terms came from the
  re-transcription and none from a correction. Among them was `yasas` — a variant
  of the exact mis-hearing `stt/vocabulary.py` documents for this app's own name
  ("yes ses", "yaz says", "yacht says") — plus `snapp`, `cube`, and a `free`/`lance`
  split of "freelance". Applying it would have biased the decoder toward the broken
  spelling that the built-in prompt exists to prevent.

  The proposer and its held-out corroboration now both take spellings only from a
  human correction, the line `_propose_disfluency` already drew for the same reason.
  A corpus with no corrections now yields no vocabulary proposal, which is the
  correct answer rather than a confident wrong one. Separately, both now compare
  against the *effective* prompt via `merge_initial_prompt`, not the configured
  `[stt] initial_prompt` alone — the built-in app-name phrase was invisible to them,
  so an already-primed term could be proposed again.

- **The `voiceprint-resemblyzer` extra installed and then could not import, and the
  daemon reported it as available while doing so.** Resemblyzer requires
  `webrtcvad>=2.0.10`, whose first line is `import pkg_resources`; setuptools no
  longer ships that package (83.0.0 has none), so `from resemblyzer import
  VoiceEncoder` raises `ModuleNotFoundError` on any current environment. The extra
  now pins `setuptools<81` — upstream's own advice, worded that way in the
  deprecation warning — rather than the maintained `webrtcvad-wheels` fork, which
  would put a second distribution in charge of the `webrtcvad` module name alongside
  the one Resemblyzer pulls in by name.

  The message the user actually saw was worse than the failure: *"Voiceprint backend
  'resemblyzer' unavailable: backend 'resemblyzer' is available."* — a sentence that
  contradicts itself and discards the exception, which was the only text naming a
  cause. `voiceprint/factory.py` pasted `probe_backend`'s verdict onto an
  "unavailable:" prefix without checking whether the probe had anything to say, and
  the probe answers from `importlib.util.find_spec`, which reports whether a package
  sits on disk and never whether importing it works. `recimport/factory.py` already
  guards this exact case and explains it in a comment; the two were written from the
  same shape and only one got the fix.

- **A test's verdict depended on whether an optional dependency happened to be
  installed.** `tests/test_emg_pressure.py`'s fake board serves a single row of
  samples, but `BrainFlowSource._emg_channels` asks the real `BoardShim` for the
  channel map and only falls back to "all rows" when the import fails — and board
  -1 reports rows 1..16, every one past the end of a 1-row array, so `_consume`
  returned before the detector saw a sample. Green wherever `brainflow` is absent
  (every CI runner), red wherever it is present. The fake now pins the channel map
  it was built for. Two tests in `tests/test_backend_availability.py` had the
  mirror-image problem — they assert the message shown when an extra is *missing*
  and read that state off the machine instead of setting it — and now force it.

  All three were found by building a `uv sync --all-extras` box, which no CI job
  does, and running the suite on it.

- **Cache-first model loading left offline mode switched on, so Parakeet could
  never download.** `system/hfcache.py` forbids hub requests for the duration of a
  model load, setting both `HF_HUB_OFFLINE` in the environment and
  `huggingface_hub.constants.HF_HUB_OFFLINE` — because either alone is a silent
  no-op. Restoring only ever undid the second, through a module reference captured
  *before* the window opened. That reference is `None` in exactly the case the
  module exists to serve: its three callers (`onnx_asr`, speechbrain, pyannote) are
  lazy optional extras, so they import `huggingface_hub` for the first time *inside*
  the window, where it initialises its constant from the variable just set. The
  restore then ran through a stale `None` and the constant stayed `True` for the
  remaining life of the process.

  Everything after it was silently offline, starting with `load_cache_first`'s own
  retry-online fallback — the half that makes a *first* run work. So on a machine
  without the checkpoint already cached, `yazses features enable stt-parakeet`
  appeared to succeed and dictation kept running on faster-whisper: the cache miss
  was correct, the retry was already offline, and `build_engine` fell back with only
  a log line. faster-whisper hid it for the default engine, which is why it went
  unnoticed — it imports `huggingface_hub` at module scope, so for Whisper the
  constant was always already present and the original restore path was correct.
  `sys.modules` is now re-read on exit, and a hub that appeared during the window is
  restored from the environment as the library itself would compute it.

- **The `diarization` extra installed sherpa-onnx without its native libraries.**
  sherpa-onnx ships as two distributions: `sherpa-onnx` holds the Python bindings,
  `sherpa-onnx-core` holds `libonnxruntime.so` and the two sherpa `.so` files they
  link against. That dependency is declared in the wheel's `METADATA` and **not** in
  the sdist's `PKG-INFO`, and the resolver took the sdist's view while installing the
  wheel — so `uv.lock` recorded `sherpa-onnx` with no dependencies at all and
  `sherpa-onnx-core` appeared nowhere in it. `uv sync --extra diarization` therefore
  installed bindings with no runtime under them on every platform, and
  `import sherpa_onnx` raised `ImportError: libonnxruntime.so: cannot open shared
  object file`. `yazses features enable meeting` installed the same broken pair.

  Two layers hid it. `recimport.factory.build_diarizer` catches the failure and
  degrades to an unattributed transcript, which is the right behaviour for a meeting
  in progress but leaves only a log line. And `diarization_status` decides "the extra
  is installed" with `importlib.util.find_spec`, which answers *is it on disk*, not
  *can it import* — it found the package, reported ready, and so `meeting start`'s
  warning, whose whole purpose is that there is never a silent un-attributed
  transcript, stayed silent. No CI job installs this extra, so nothing exercised the
  combination. `sherpa-onnx-core` is now named explicitly in the extras and in
  `_FEATURE_DEPS`, the floor moves to 1.13.6, and
  `tests/test_diarization_extra_ships_its_runtime.py` guards both statically so it
  fails on every platform whether or not the extra is installed.

- **Windows: config writes used the locale code page, so one accent broke them.**
  Python's default text encoding is the locale code page — UTF-8 on Linux and macOS,
  **cp1252 on Windows**. `system/configedit.py`, the comment-preserving writer behind
  `yazses features enable`, `hotkey set` and `audio use`, both read and wrote
  `config.toml` through it. TOML is required by its own specification to be UTF-8, so
  the writer was reading a UTF-8 file as something else: a vocabulary entry, a path or
  a name carrying a single non-ASCII character raised `UnicodeDecodeError` on read or
  `UnicodeEncodeError` on write, and the command failed outright rather than
  degrading. `miclevel`, `accessibility/enroll` and `firstrun` write the same file the
  same way, and the JSON stores had it too — JSON being UTF-8 by specification as
  well. 30 call sites across 12 modules now name their encoding.

  `/proc/<pid>/cmdline` in `system/pid.py` deliberately takes `errors="replace"`
  instead: it is NUL-separated raw bytes that are only substring-checked, and the
  handler around it catches `OSError`, which `UnicodeDecodeError` is not — so a bare
  `encoding="utf-8"` there would have turned a silent pass into a crash.

- **The Windows jobs had never run a test, and running them found eleven failures.**
  None was a regression; it was the first look at code nothing had ever executed. The
  same cp1252 default broke 214 unencoded text-I/O call sites across 40 test files,
  and `str(path.relative_to(root))` — backslash-separated on Windows — matched none of
  the `yazses/...` literals the suite compares against. Both shapes are now failed by
  `tests/test_repo_hygiene_windows_safe_io.py`, whose scope is chosen so it can never
  fire on correct code: `tarfile.open`, `Image.open`, `os.open` and `Path.open("rb")`
  are all excluded, and the mode is read from the positional argument *or* the `mode=`
  keyword, since `Path.open` takes its mode where the builtin takes a buffer size.

  With those eleven fixed, one Windows-only defect remained and it was in a fixture:
  a test sandbox built from `XDG_CONFIG_HOME` alone, which platformdirs honours on
  Linux and ignores on Windows and macOS. The test edited the runner's real config,
  and only a teardown guard in `conftest.py` noticed. The fixture now sets the
  Windows and macOS variables too and — the actual repair — **asserts** that the
  resolved config directory lands inside `tmp_path`, because a sandbox that cannot
  fail is not evidence that anything was contained.

- **A macOS-only test imported a name that does not exist**, and every Linux run was
  green because a `skipif`-ed module is never imported at all. It failed the first
  time it reached a real Mac — the one place it existed to prove something rather than
  discover its own typo. `tests/test_platform_gated_tests_import_real_names.py` now
  resolves those names on any host. The other six tests in that file passed on
  `macos-latest`, so the IOKit binding behind the Input Monitoring fix is confirmed on
  Apple silicon rather than reasoned about.

- **Nothing verified what was inside the shipped `.dmg`.** `scripts/inspect-dmg.py`
  — the tool written precisely because the macOS bundle is the one artefact nobody
  on this project can open — was wired into no workflow at all, and could only fail
  on version and architecture. So a bundle missing a permission string inspected
  clean, which is the worst thing it could do: macOS refuses a service whose
  `NS*UsageDescription` is absent **without ever prompting**, so the build is green,
  the bundle is well formed, and hold-to-talk is simply dead with no dialog to
  answer. That is exactly how
  [#182](https://github.com/MSKazemi/yazses/issues/182) presented.

  The inspector now takes `--require-key` and `--require-keys-from-spec`, and
  `build-macos.yml` runs it on every `.dmg` it produces. The required keys are read
  out of `packaging/macos/yazses.spec` rather than restated, so a permission added
  there is covered the day it is added. The first run of the new guard found that
  `NSAppleEventsUsageDescription` had never been inspected either.

- **The Windows test jobs had been running zero tests, and reporting it as one
  broken file.** `tests/test_setup_probe_survives_a_passwdless_uid.py` imported
  `pwd` — POSIX-only — at module scope, so on Windows pytest failed during
  *collection*:

  ```
  collected 9525 items / 1 error / 8 skipped
  ERROR collecting tests/test_setup_probe_survives_a_passwdless_uid.py
  !!!!!!! Interrupted: 1 error during collection !!!!!!!
  ======== 8 skipped, 1 error in 14.19s ========
  ```

  A collection error aborts the whole session, so both Windows jobs stopped before
  running anything. `main` carried this for days: the cross-platform matrix existed
  and half of it was verifying nothing. Now `pytest.importorskip`, and
  `tests/test_repo_hygiene_posix_only_imports.py` fails the build on any test module
  that reintroduces the shape (a function-scope import and `importorskip` both stay
  legal — the hazard is module scope, not the import).

- **Two `quickstart` tests were platform-dependent without saying so**, which is why
  both macOS jobs were red. The prerequisites tick only renders on Linux, so
  `test_quickstart_still_ticks_when_the_probe_says_so` *could not* pass off Linux —
  and its counterpart, which asserts the string is **absent**, passed off Linux for
  the wrong reason: absent because the branch that prints it never ran. Both now pin
  the platform, which fixes the first and gives the second its meaning back. A
  `skipif` would have done neither.


- **macOS: the dictation key needed a permission YazSes never asked for.** On the
  first Macs this was ever run on ([#182](https://github.com/MSKazemi/yazses/issues/182)),
  Accessibility was granted and visibly enabled, `doctor` reported it and nothing
  else, and the hotkey did **nothing** — in any application. YazSes was also absent
  from Privacy → Microphone entirely, with no `+` button to add it.

  That is three symptoms and one cause. `MacosHotkey` observes the key with a
  `CGEventTap`, and since macOS 10.15 an observing keyboard tap requires user
  approval of **Input Monitoring** *in addition to* Accessibility — a separate TCC
  service, in a separate pane. YazSes never checked it, never requested it, and the
  bundle declared no `NSInputMonitoringUsageDescription`, so `CGEventTapCreate`
  returned NULL, the key never fired, nothing ever opened the microphone, and macOS
  therefore never showed the one-time microphone prompt that is what puts an app in
  that pane in the first place.

  Four surfaces, because the permission was invisible on all of them:

  - `MacosPermissions.check_input_monitoring()` / `request_input_monitoring()` read
    the service through IOKit (`IOHIDCheckAccess` / `IOHIDRequestAccess`, via
    `ctypes` — they are bare C functions, and which PyObjC wheel exposes them has
    moved between releases). Requesting is not cosmetic: **an app that never asks
    does not appear in the pane at all**, so "enable it in Settings" was not advice
    anyone could follow.
  - `yazses doctor` grows an **Input monitoring** row on macOS, next to Keyboard
    capture. `UNKNOWN` is a WARN, not a FAIL — before anything has asked, "never
    determined" and "refused" are the same value, and a red line in front of every
    new user would be wrong.
  - `MacosHotkey.run()` asks before creating the tap, and a NULL tap now names the
    grant we actually determined instead of naming Accessibility unconditionally —
    which, on the machine that reported this, was the one permission already on.
  - The `.app` declares `NSInputMonitoringUsageDescription`. Without the string
    macOS may refuse the service without ever prompting.

  The Accessibility remedy now points at the second switch too, which is the loop
  #182 was stuck in: re-toggling a permission that was already correct.

  ⚠ **Verified by tests and by Apple's documented behaviour, not on hardware** —
  there is no Mac in this project's CI or on the maintainer's desk. #182 stays open
  until someone confirms it on a real machine.

- **Every command in the macOS `.app` printed "No such option: `-B`".** Including
  the ones that worked: the first successful end-to-end run on a Mac reported
  captured, heard and cleaned — framed above and below by that error and by
  *"resource_tracker: process died unexpectedly … Some resources might leak"*
  ([#182](https://github.com/MSKazemi/yazses/issues/182)).

  In a PyInstaller bundle `sys.executable` **is the bundle**, and parts of the
  standard library relaunch `sys.executable` assuming it is a Python interpreter.
  `multiprocessing.resource_tracker` runs
  `[sys.executable, *interpreter_flags, "-c", "<program>"]`, and PyInstaller's
  bootloader sets `dont_write_bytecode`, so the child re-entered YazSes's own argv
  dispatch as `["-B", "-c", …]`, fell through to the Typer CLI, and was killed by a
  usage error — after which Python relaunched it and it happened again.

  `src/yazses/__main__.py` now recognises an interpreter relaunch before anything
  reads argv as a YazSes command, and runs the program the stdlib asked for.
  `multiprocessing.freeze_support()` covers the other relaunch shape
  (`--multiprocessing-fork`). Both are gated on `sys.frozen`: outside a bundle
  that argv cannot come from the stdlib, and executing it would turn a CLI typo
  into arbitrary code.

- **macOS Homebrew: the documented one-liner failed for every new user.** Homebrew
  now refuses to load a cask from an untrusted third-party tap, so
  `brew install --cask yazses` stopped with *"Refusing to load cask … from untrusted
  tap"*. `brew trust MSKazemi/yazses` is now in the README and the install guide.
  Found by running the route end to end on an Apple M4 — the route this project had
  marked "never executed" — by [@slegarraga](https://github.com/slegarraga).

### Added

- **Seven more of #164's unwired capabilities are now wired.** Same shape as the ten
  before them: a designed, tested, pure core with no caller. The registry's honest
  count moves from **95 wired / 52 planned to 102 / 45**.

  **Four answer to a phrase**, through the anchored router added with the previous
  batch rather than through four new branches in `core/daemon.py`:

  - `condense` — "condense …" (or "summarise"/"tighten") types the tightened version
    of the paragraph you just spoke. Extractive, local, no model. It works on *this*
    utterance rather than on text already on screen, which would need a caret
    position nothing can supply yet (#162).
  - `diagramvox` — "diagram login goes to dashboard if valid" types Mermaid (or DOT
    via `[diagramvox] flavor`). It declines an utterance that produced no **edge**:
    `parse_graph_utterance` answers a one-node graph for any prose at all, so
    "diagram the release process" would otherwise emit a flowchart wrapper around a
    fragment of your own sentence.
  - `spreadsheet` — "next cell" / "top of column" become key sequences. The trigger is
    a whole-utterance lookup, stricter than the `^…$` anchor, so "I want to move up in
    the company" cannot be claimed by it.
  - `echo` — "play that back" / "play 'weather'" replays **your own captured audio**,
    not TTS, which is the entire point: a homophone Whisper got wrong sounds correct
    when a synthesiser reads the wrong word back.

  **Three answer to the machine**, and need no key:

  - `fieldaware` — shapes dictation by the AT-SPI role of the focused *widget*, and
    **refuses to type into a password field**. This closes a real gap rather than
    adding a nicety: a password box *is* editable text, so `target_ok` looks at one
    and correctly says "yes, type here". Only the role tells them apart. The refusal
    deliberately does **not** fall back to the clipboard the way the no-text-target
    guard does — that guard rescues words from a window that cannot hold them; this
    one is refusing a destination you chose, and parking a password on the system
    clipboard would replace a small mistake with a larger one.
  - `srpace` — injects in clause-sized chunks at a screen reader's reading rate, so it
    can announce coherently instead of receiving twenty words as one event. It blocks
    the burst on purpose: pacing on a background thread would let the next release
    interleave its clauses with this one.
  - `suggestmode` — dictation lands as `{++a proposal++}`, and a `rewrite` lands as a
    CriticMarkup **diff** rather than a silent replacement. The rewrite path is the one
    place in the daemon holding both a *before* and an *after* for the same span.

  New: `[stt]`-independent `[diagramvox] flavor`, `[condense] max_sentences` and
  `[srpace] wpm` are now read; `TargetDetector.get_field_role()`; a `keys` spoken
  action; `spokencmd.router.tidy` is public.

### Notes

- **`#164`'s premise does not hold for most of the remaining 45.** The issue says the
  capabilities are "missing only their wiring". Measured against the tree, that is true
  for a shrinking minority — most are missing a declared extra, a sensor, a model, or a
  caret position. Five were examined closely this pass and **deliberately not wired**:

  - `screengrounded` — `[context]` (ADR-v2-004) *already* harvests window title,
    selection and clipboard into `initial_prompt`. Its only distinct source is the OCR
    pixel path, and `screenocr` is not a declared extra. Wiring the rest would have
    been a second way to do a thing the project already does.
  - `loadguard` — measured, not assumed: its two load-bearing signals (`filler_rate`,
    `self_corrections`) are not counted anywhere — `FilterResult` carries
    `chars_removed`, not a filler count. The one signal that *is* measurable, speech
    rate, is computed over the padded buffer (a 300 ms lead-in plus the key-held tail),
    so it understates rate and a single unaveraged signal saturates: every realistic
    burst measured 0.54–0.97 load, i.e. "elevated" or "high". A guard that fires on
    every caution-level command is the exact failure ADR-v2-065 names.
  - `scrub` — its replay half duplicates `echo`'s; its distinct half ("pick a word to
    re-dictate") needs a real caret position (#162).
  - `scribe` — `label_speakers`/`merge_turns`/`format_transcript` is what `meeting/`
    and `recimport/` already do.
  - `langroute` — not wiring. It needs the detected language surfaced from
    `info.language` (the wrapper discards it) via a new method on a
    **`@runtime_checkable`** Protocol, which breaks `isinstance` across the codebase,
    and Parakeet is English-only so it could not implement it.

  Also confirmed blocked on an **undeclared extra**, not on wiring: `voicehealth`
  (parselmouth), `cmdspotter` (kws), `pronunciation`, `audioguard` (soundawareness),
  `wakeword`, `codec`, `predict`, `voiceguard`, `spatialvad`, `gesture`, `affect`,
  `compose`, `rag`. `involuntary` was refused for the `corrdict` reason from the last
  batch: its thresholds are calibrated against a feature scale (`peak_energy`,
  `centroid_hz`) that no extractor in the tree defines, and a false positive **deletes
  speech**.

- **Ten capabilities that shipped as registry entries with no runtime code are now
  wired (#164).** Each had a designed, tested, pure core and no caller, so `yazses
  features enable <name>` refused it outright and the feature page marked it *planned*.
  The registry's honest count moves from **85 wired / 62 planned to 95 / 52**.

  **Six answer to a phrase**, and they share one door rather than a branch each:
  `spelling`, `code`, `math`, `spokenregex`, `snippets` and `voicetimer` now route
  through a single anchored router (`src/yazses/spokencmd/`). Their triggers are
  ordinary English — *spell*, *code*, *math*, *regex*, *insert*, *set a timer for* — so
  they run only while the dedicated **command key** is held, and every trigger is
  anchored at both ends so "the code review is on Friday" is typed rather than
  interpreted. Enabling one without `[hotkey] command_key` bound now says so instead of
  writing a config key nothing can reach.

  Their output goes through the **command-safety gate**, which is the load-bearing part:
  `spell romeo mike space dash romeo foxtrot space slash` assembles `rm -rf /` character
  for character, and it now waits for a spoken *confirm* exactly as if it had been
  dictated. Measured rather than assumed — the milder sibling `code` produces
  `rm - r f /`, which the gate scores safe because the spaces defeat the pattern.

  **Four answer to the machine.** `corrdict` replays corrections you have already made by
  hand ("yaz says" → "YazSes") once a substitution has enough support, mined from the
  encrypted learning corpus; `smartpaste` and `focusprofile` key off the focused window —
  Markdown bullets and autolinked URLs in a notes app, verbatim capture in a terminal so a
  cleanup pass cannot reword a command line; `latency` decodes with a lighter model at a
  greedy beam while the load average is high, loading it in the background so the governor
  never becomes the pause it exists to prevent.

  Each of the four refuses to turn on and quietly do nothing: enabling one without its
  precondition (`[learning] enabled`, a focused-window probe, a POSIX load average) prints
  what is missing.

- **`[stt] beam_size`** — decoder beam width. `0` (the default) keeps faster-whisper's own
  choice; `1` is greedy decoding, faster and less accurate. Added so the latency governor
  can ask for it, and available to anyone who wants that trade permanently.

- **`[latency] light_model`** — the model the governor decodes with under load
  (default `tiny.en`).

### Notes

- `corrdict` mines only pairs that *sound like* each other. Without that gate, rewording a
  sentence mined as cleanly as a misrecognition: `difflib` breaks a whole-sentence rewrite
  into exactly the short spans the length guard allows, so "send" → "forward" became a
  permanent substitution replayed into unrelated sentences. The two classes separate
  cleanly on measurement — misrecognitions score 0.75–0.83, rewordings 0.09–0.32.
- The speculative-decoding half of ADR-v2-073 is designed but not built, and no config key
  advertises it.
- `prosodypunct` and `hesitation` remain *planned*, and not for want of wiring: both need
  an F0 series, and no F0 extractor exists anywhere in `src/yazses`. `reask` has its signal
  already (per-word `probability` is on the `transcribe_words` records) but needs an
  interactive picker.

### Added — a measured Logseq app profile, and an AppImage probe to measure it with

`examples/config.logseq.toml`, opened by [@mercael91](https://github.com/mercael91)
([#309](https://github.com/MSKazemi/yazses/pull/309), closes
[#229](https://github.com/MSKazemi/yazses/issues/229)).

Logseq was the one app on the wanted list that neither the contributor nor the maintainer
could measure: it ships only as an AppImage, so it is in no apt repository, and mounting one
needs FUSE, which a container does not have. `scripts/appprobe/README.md` recorded that as a
limit of the harness. It is not one — `--appimage-extract` unpacks the squashfs with no FUSE
at all, and `Dockerfile.gui` now runs the extracted `AppRun`. The same recipe fits any other
AppImage-only app.

Measured against Logseq 2.0.1, driving the real xdotool XTEST injector at a block on the
journal page: `kubectl get pods --namespace prod` arrived **exact** — no auto-capitalisation,
both hyphens intact. A second run for the markup an outliner rewrites as you type,
`see /etc/hosts and [[my note]] ok`, also arrived exact: neither the `/` command menu nor the
`[[` page-reference popup ate the rest of the line.

One finding is specific to an outliner and is why the profile sets
`[injection] target_guard = "clipboard"`: clicking the empty page *below* the last bullet
focuses nothing, so a hold taken then has nowhere to put the words. Two probe runs differing
only in where they clicked gave `EXACT` on the bullet and `NOTHING` on the blank space under
it. In a text editor a click anywhere in the pane would have focused the editor.

`probe-gui.sh` gained `PROBE_CLICK_Y_PCT` (the vertical half of the click, which that finding
required) and `PROBE_TEXT` (a second, app-specific string; the default stays what every row in
the results table was measured with).

### Fixed

- **Desktop notifications could be swallowed before the tray showed them (Windows and
  macOS).** Where there is no `notify-send`, the daemon cannot pop a toast itself: it
  queues each one and hands it to the tray on the next status read, which is the only
  notification channel those platforms have. That read *drained* the queue — correct for
  a single consumer, except `status` has fourteen callers. The voice-activity overlay
  polls it continuously right alongside the tray and displays no notifications at all, so
  whichever poll landed first took the toast and it was lost. The tray's own menu did the
  same: opening it read `status` and swallowed anything pending.

  Only a caller that can display a toast now consumes the queue; every other reader — the
  overlay, `doctor`, the settings window, the CLI, and the daemon's own bug-report builder
  — leaves it in place. `status` still drains by default, so an older tray running against
  an upgraded daemon behaves exactly as before rather than re-showing the same toast on
  every poll. A build-time guard now finds every status reader in the source and fails
  until each one either opts out or is a declared displayer.

- **Two meeting participants whose names differed only in capitalisation destroyed each
  other's voiceprint on macOS and Windows.** A participant's display name is stored nowhere
  but the filename of their enrolled voiceprint, so the file *is* the identity. The path was
  derived from the name alone, which made `Amara` and `amara` two different people — on
  Linux. On macOS (APFS) and Windows (NTFS) the filesystem treats those as one file, so
  enrolling the second silently overwrote the first: the voiceprint of someone who had done
  nothing was replaced, and enrolling it back would replace the other one. Nothing reported
  it, because from YazSes's side the write succeeded.

  The same defect made `meeting enroll`'s own warning contradict what it then did. The
  "Replaced the existing voiceprint for …" check asked whether a file for that name existed
  — a question the filesystem answered case-insensitively — while the path it wrote to was
  built case-sensitively. So it truthfully warned you were about to replace Amara and then,
  on Linux, did not; and on macOS it replaced her whether or not it had warned.

  A name is now one participant regardless of case on every platform: an existing enrolment
  is resolved against what is actually enrolled, so `amara` finds Amara, replaces Amara, and
  keeps the spelling she was enrolled with. An exact match still wins, so a machine that
  already holds both variants — only reachable on a case-sensitive filesystem — keeps
  returning each of them for its own name rather than collapsing one into the other. Which
  person you get is no longer a property of the computer you are sitting at.

- **`yazses report` put dictated text in the bundle it tells you to attach to an issue.**
  The command's own help promises *"your settings with paths, identifiers and anything you
  typed yourself removed"* and *"your dictated text and the learning corpus are never
  included"*. The config, the log tail and the corpus were all filtered to make that true.
  The daemon's live status was inserted with no filter at all — and it carries the staged
  buffer, which is the text you have dictated and not yet committed, verbatim up to 240
  characters. Staged mode exists so you can review text *before* it is typed, so that field
  holds a real sentence precisely when you are in the middle of one, which is when you hit
  the bug you are reporting.

  The daemon block now goes through the same rules as the rest of the bundle: your own
  words are replaced by their length, queued notification text is reported by count, and
  every remaining string has your home directory and account name removed. Diagnostics are
  kept, not blanked — the microphone name, the failing path in an error message and the
  word counts beside the buffer all survive, because they are usually the answer. A
  build-time guard now reads the daemon's status fields out of its own source and fails
  until each new one is classified as either your words or a fact about the machine.

- **`yazses status` scored commands you spoke on purpose as dictation failures.** The
  gauge that answers "how often did dictation produce text" divided typed bursts by
  *every* burst, including ones held on the dedicated command key — which never types
  literal text, because an unrecognised phrase is ignored by design.

  Found running the daemon: `typed: 0 of 6 recent bursts (0%)` printed directly above a
  microphone warning, on a machine whose `--json` payload read
  `{"empty": 1, "command_unmatched": 4, "silent": 1}`. Four of the six were deliberate
  command presses; dictation was healthy.

  The conflation ran both ways, and the other direction could have hidden a real fault:
  a command that *matched* dispatches a key sequence, sets no discard reason, and so
  scored as `typed` — commands could hold the rate at 100% while dictation typed
  nothing. Command bursts are now counted and reported on their own line, so neither
  kind is averaged into the other and neither disappears. `total`, `typed` and `counts`
  in `--json` keep their old meaning for anything already reading them, and a new CLI
  talking to an older daemon falls back to the combined line rather than labelling it a
  dictation rate the payload cannot support.

- **`yazses status` under-reported uptime by however long the machine had been
  asleep.** Measured on a laptop: `ps` reported the daemon up 9 h 25 m with
  `NRestarts=0`, `yazses status` reported 5 h 29 m, and the difference was exactly
  `CLOCK_BOOTTIME - CLOCK_MONOTONIC` — 3 h 55 m 43 s with the lid shut. `time.monotonic()`
  stops ticking across a suspend on Linux.

  Uptime exists to reveal a daemon that predates an upgrade — a daemon runs the build it
  started with until restarted — so the error landed on precisely the device class where
  a process is most likely to be stale, and it grew with every night's sleep. The daemon
  now stamps and reads its start time with a clock that counts suspended time, probing
  for `CLOCK_BOOTTIME` rather than assuming a per-OS rule. Interval measurements are
  untouched: a decode, a hold and a meeting's elapsed time all still use
  `time.monotonic()`, which is the correct clock for a duration that only happens while
  the machine is awake.

- **A phrase YazSes heard, recognised and deliberately did not type counted as a
  microphone failure.** The mic guard watches for a run of bursts that produce no text,
  which is the direct "dictation stopped writing" symptom. Its reset asked a narrower
  question than the guard does: a burst cleared the run only if it produced a transcript
  **and** was not discarded for any reason at all. Most discard reasons are set *after* a
  transcript exists and decide only where the text goes — a phrase spoken under the
  command key that matched no command, an edit refused because nothing editable was
  focused. Those bursts were neither a success nor a failure, so they left the run
  standing instead of clearing it.

  Found running the daemon: `yazses status` reported `2 silent clips in a row — run
  'yazses audio status'` across an hour whose log holds three bursts transcribed at
  levels 0.0057–0.0118 under the command key. The microphone was working, and had proved
  it three times. The cost is not the wrong line: at `silent_streak_threshold` the next
  discard pops a toast saying the microphone stopped working, and with
  `auto_heal_device` on the daemon switches the capture device on evidence an hour stale
  and already contradicted.

  A burst now clears the run whenever it proves capture worked, whether or not the text
  was typed. `silent`, `empty`, `cocktail_gated`, `hallucination` and `post_filter` are
  deliberately excluded — each is evidence *about* the audio rather than about where
  text went, and the hallucination guard in particular fires exactly when non-speech
  decoded to fabricated words. A new discard reason defaults to *not* proof, so the
  guard stays sensitive, and a test reads the reasons out of `core/daemon.py` itself and
  fails the build on one that has been classified in neither direction.

- **The guard that checks YazSes only advises commands it has could not see most of
  the advice, and stopped at the command name.** It required a backtick, which is right
  for 200 markdown pages — prose would otherwise parse as command lines — and wrong for
  `src/`, where the advice a user actually reads is a `typer.echo` string. 337 of those
  carry no backticks, including four of the five places that print `yazses mic-level
  --set`. In `src/` the sweep now reads string literals via `ast`, so a command line in
  code (a `subprocess` argv, a fixture) is still not mistaken for advice.

  It also stopped at the second word, and a command name that resolves is not the whole
  promise: `yazses mic-level --set` is one string, and if the flag is renamed the command
  still dispatches, Typer exits 2 with "No such option", and the user meets that at the
  moment they were already following instructions out of a problem. Flags are now checked
  against the real parameters of the command that precedes them — 229 advice strings
  carry one, against 72 visible before. All resolve; the sweep found no defect and is
  pinned before the first rename does.

- **`yazses features enable <capability>` installed version floors below the ones
  `pyproject.toml` declares — 11 of 17 packages.** `[project.optional-dependencies]`
  says what `pip install yazses[gaze]` resolves; `system/features.py::_FEATURE_DEPS`
  holds the requirement strings actually handed to `uv pip install` when a user turns a
  capability on. Nothing compared them, and every difference ran the same way: the
  installer that users actually run asked for less. `opencv-python>=4.10` against the
  extra's `>=5.0`, `mcp>=1.9` against `>=1.28.1`, `PySide6>=6.8` against `>=6.11.1`, and
  `sherpa-onnx>=1.10` for `diarize` while `recimport` and `meeting` — the same package,
  three lines apart in the same map — said `>=1.13.4`.

  A floor is not a request for a version, it is a statement about what already counts as
  satisfied, so this is invisible on a clean machine and bites on a machine that already
  carries an older copy — opencv, onnxruntime and Qt being exactly the packages another
  project leaves behind. There, nothing upgrades, `missing_modules` reports the
  dependency present because the name imports, and the capability is switched on over a
  version the project says is too old. Every pin now equals its extra character for
  character, including the `[cpu,hub]` markers a version compare would wave through.

- **`useful-moonshine-onnx` was declared by no extra at all**, only by that map and the
  dev group, so the Moonshine STT engine was reachable through `features enable
  stt-moonshine` and through no packaging path. It now has a `moonshine` extra,
  registered in the dependency-budget map so a base install is checked for it like every
  other optional module.

  The guard is total over both facts and derives them rather than restating a pin a third
  time. The same property was already enforced one layer over — `install.sh` is held to
  the `desktop` extra on the stated grounds that "a comment is not a mechanism" — while
  `features enable`, which runs whenever anyone turns a capability on, had a mechanism
  for exactly one row.

  One of the stale floors was being *held* stale: `test_gaze_feature_declares_its_deps`
  asserted the literal strings `mediapipe>=0.10` and `opencv-python>=4.10`, so raising
  the map to match the `gaze` extra failed the suite. It now compares distribution
  names and leaves floors to the guard that owns them — a pin written down in three
  places has two places that can contradict it.

- **`yazses features disable read-back` reported the capability off while the daemon kept
  building a TTS engine for it.** `enable` writes two keys — `[tts] enabled = true` and
  `[accessibility] read_back = "final"` — and `disable` wrote only the second. The
  catalogue then showed it off, because its status reads both and one had flipped, while
  `build_tts` branches on `[tts] enabled` alone and kept returning a live backend. With
  the `tts` extra installed that loads Kokoro and, per `tts/download.py`, fetches **~340
  MB** the first time — for a capability the user had switched off. `disable` now clears
  both keys; `read-back` is the only feature that writes `[tts] enabled`, so nothing else
  depended on it staying on.

  It was the only asymmetric row of 147. Two properties now hold every feature to its
  registry entry: the keys `disable` writes must be the keys `enable` writes, and each
  list must actually move the capability's own status predicate — the second because
  `enable → disable == disable` is mere idempotence, which a `disable` that wrote `true`
  would satisfy trivially.

- **A typo in a config setting was accepted in silence, and what happened next depended
  on which module eventually read it.** `configcheck` validates values against a closed
  set, and `yazses doctor` reports its verdict as *"Config validity: every setting is a
  usable value"* — but the table held **two** entries while `config.py` documented
  twenty-three more closed sets in trailing `# a | b | c` comments. Measured through the
  real loader:

  ```
  [gaze] backend          = "mediapip"    accepted -> gaze silently never runs
  [voiceprint] backend    = "ecapa-tdnn"  accepted -> voiceprint silently disabled
  [meeting] output_format = "markdown"    accepted -> the post-pass later raises
  [stt] engine            = "whisper"     accepted -> warned, fell back to the default
  [injection] backend     = "xdotol"      caught   (the one entry that existed)
  ```

  The silent-disable cases are the worst of the three: the log line goes to a daemon log
  nobody reads, `yazses features` still shows the capability as ON, and it simply never
  runs. `[meeting] output_format` is the loudest — `render_transcript` raises on an
  unknown format, so a meeting cannot finalize until the config is corrected. Nothing is
  lost there: the canonical `transcript.json` is written before the human format and the
  recording is retained on a failed post-pass.

  Five settings are now validated — the two `output_format` fields (held equal to
  `render.VALID_FORMATS`, the constant that decides whether the post-pass raises),
  `[gaze] backend`, `[voiceprint] backend` and `[stt] engine`. Each was added only after
  reading the consumer, because enforcing a *wrong* set rejects a working config, which is
  worse than the silence it replaces. The remaining eighteen are recorded as a ratcheted
  backlog that a build gate can shrink but not grow, and `[commands] lsp_editor` is marked
  permanently unenforceable: nothing consumes it, and its comment and the architecture
  reference disagree about what its values are.

- **`yazses setup` crashed, and `yazses quickstart` lied, for any uid without an
  `/etc/passwd` entry.** `setup._current_user()` ended at
  `pwd.getpwuid(os.getuid()).pw_name` with no fallback, so it raised `KeyError` whenever
  the running uid had no account. `build_plan()` is the first thing both commands do.

  This is not an exotic machine — it is `docker run --user 4242:4242`, and it is what
  Kubernetes produces whenever `runAsUser` is an arbitrary uid. `docs/docker.md` *tells
  people to do it*: the image has an account for uid 1000 only, so the documented
  `--user "$(id -u):$(id -g)"` flag produces a passwd-less uid on every host whose uid is
  not 1000. `transcribe` was unaffected; the two commands that read the machine were not.

  The two failed differently, which is why it went unnoticed. `yazses setup` did not
  guard the call and exited with a raw traceback — on the one command whose entire job is
  to fix a machine's prerequisites. `yazses quickstart` guarded it with
  `except Exception: needs_setup = False` and printed **"Prerequisites — already set up
  ✓"**: a swallowed probe rendered as a positive claim, on the first screen a new user
  ever sees, and wrong exactly where it mattered — inside a fresh container almost
  nothing is set up.

  `_current_user()` is now total, falling back through `LOGNAME` to the numeric uid.
  Numeric is *answerable*, not merely non-raising: group membership is stored by name, so
  a uid with no account is correctly reported as not being in the `input` group, and
  `setup` offers to fix it. `quickstart` now distinguishes three states rather than two —
  a probe that fails prints "Check prerequisites — run `yazses doctor`" instead of a tick.

- **The feature catalogue priced a 600 MB speech engine at 4 MB.** `yazses features`
  showed `stt-parakeet` as a `~4.0 MB` download — the `onnx-asr` wheel — while the
  engine's own docstring, `docs/models.md` and `yazses features info` all said it fetches
  a ~600 MB model on first use. `docs/install-cost.md` published the same `~4 MB`, on a
  page that opens by promising measured numbers, listing the second-largest download
  YazSes can make beside its smallest.

  This is the 2026-08-18 defect returning through the guard that was supposed to prevent
  it. That guard keyed on files **named** `download.py`, which is a filename rather than
  a behaviour: the two alternative STT engines fetch their weights through their own
  library (`onnx_asr.load_model`, `MoonshineOnnxModel(...)`) and own no such file. The
  complete list already existed one test file away, in `test_model_cache_first.py`, and
  nothing compared the two.

  Now the classification is derived by walking the tree for hub-fetching calls, the two
  lists are held equal, and every priced module is checked against the size its own
  docstring states. Corrected: `stt-parakeet` `~4.0 MB` → `~604 MB`, `read-back` `~25 MB`
  → `~352 MB`, `diarize`/`meeting`/`recimport` `~18 MB` → `~62 MB`, `cocktail` now counts
  its ECAPA encoder, and `stt-moonshine` reads `~113 MB+` — a trailing `+` marking a
  figure that is a floor because the model files are not sized. `docs/install-cost.md` is
  now checked against the tool row by row.

- **The second STT engine fetched from Hugging Face without trying the cache first.**
  `stt/moonshine.py` built `MoonshineOnnxModel` directly, so it skipped `load_cache_first`
  and paid the hub revalidation round-trip that has no timeout (ADR-019). It was missed
  for the same reason as the size: the guard looked for named loader functions, and this
  one is a class call.

- **`yazses doctor` named an injector it had not consulted the config about.**
  `_injection_readiness` took `(is_wayland, is_x11)` and derived its answer from the
  session type and which tools were on PATH, printing `Injection: xdotool (X11)` as
  though naming the backend in use. `inject.auto.get_injector` reads `[injection]
  backend`, so the two answered different questions. Measured on the development
  machine before the fix:

  ```
  backend=auto       daemon uses -> XdotoolInjector      doctor says -> xdotool (X11)
  backend=clipboard  daemon uses -> ClipboardInjector    doctor says -> xdotool (X11)
  backend=wtype      daemon uses -> XdotoolInjector      doctor says -> xdotool (X11)
  ```

  Three disagreements, all silent: `clipboard` short-circuits in `get_injector` before
  any probe runs; `wtype` is Wayland-only and on X11 the setting simply did nothing, with
  nothing saying so; and on Wayland `wtype` *beats* a running ydotoold in `get_injector`
  while the check reported ydotool. `doctor` now takes the configured backend, names the
  one that will be built, and raises a separate `Injection setting` warning when the
  setting cannot be honoured rather than ignoring it quietly.

  The guard added the pass before could not catch this: it fails a function that calls
  `injector_factory()` without applying the config, and `doctor` never calls it — it is a
  second, independent derivation, which is precisely what nothing was comparing.
  `tests/test_doctor_names_the_injector_in_use.py` now holds them equal across every
  session type and backend: wherever `doctor` reports `OK`, `get_injector` must return
  the backend it named.

- **The uninstall page left two directories behind, and sent Windows users to a third
  that YazSes never reads.** `Paths` declares **five** directory roots; on Linux and macOS
  they follow the platform conventions and therefore sit in four different places.
  `docs/uninstall.md` — a page whose own description promises *"complete, honest"* removal —
  named two of them, and its final *"Check it is gone"* step printed `data: removed` after
  looking at the same two. On the development machine that left **3.6 MB in `~/.cache/yazses`**
  and **1.5 MB of daemon logs in `~/.local/state/yazses/log/`** untouched. The cache is the
  worse half: `commands/model_manager.py` puts a **2.2 GB** GGUF there. The log is the more
  sensitive one — at `log_level = "DEBUG"` it holds every transcript, which the privacy
  statement warns about while pointing at a directory the log is not in.

  Two claims were wrong rather than incomplete. `docs/privacy-statement.md` said
  *"Everything YazSes persists lives in one directory"* — it does not — and that the Whisper
  weights download into the data directory; all six on the development machine were in the
  Hugging Face cache, exactly where `docs/uninstall.md` had always correctly said they were.
  Both are corrected, and the three other roots now have their own section.

- **`%APPDATA%\yazses\config.toml` is a file YazSes never reads.** `platform/windows/paths.py`
  opens by warning that the layout is `CSIDL_LOCAL_APPDATA`, *"despite the `%APPDATA%`
  shorthand often used for it"* — and then ten surfaces used that shorthand, including a
  comment twenty lines below the warning and one of the two doc generators (its sibling
  `gen-example-config.py` had it right). A Windows user who followed the README got no error
  and no effect. Fixed in the generators, the README, four docs pages, two translations and
  the source comment; `tests/test_documented_paths_match_the_code.py` now fails the build on
  any surface that names the roaming path, deriving *"Local, not Roaming"* from the
  `PlatformDirs` call itself rather than from a substring search that the module's own
  warning trips.

- **`uninstall_autostart` meant two different things on two platforms.** macOS deletes its
  launchd plist; Linux ran `systemctl --user disable`, which only drops the symlink, and left
  `~/.config/systemd/user/yazses.service` on disk for ever — so the documented uninstall
  finished with a file YazSes had written still there, and `systemctl --user list-unit-files`
  still listing a program that was gone. Linux now removes the unit and reloads the daemon,
  matching macOS. Nothing is lost: `install_autostart` regenerates the unit from the running
  interpreter's own console script.

### Added

- **The three commands that exist to test the injector all tested a different one.**
  `platform.injector_factory` takes no arguments, so `[injection] backend` and
  `fallback_to_clipboard` reach the backend through environment variables that
  `inject.auto.get_injector` reads — and **only `core/daemon.py` set them**. `yazses inject`
  (*"tests the injector"*), `yazses test` and `yazses verify --type` each built `auto`.

  On a machine with `backend = "clipboard"` configured, `auto` selects `XdotoolInjector` —
  so a user who switched to clipboard-paste *because typing does not reach their app* had all
  three diagnostics prove the backend they had rejected, and `verify --type` certify one the
  daemon does not run.

  Two of them then misreported what they had built: `type(injector).__name__` is
  `LinuxInjector`, the selector, on every Linux machine whatever it chose. The daemon already
  preferred `backend_name` so `status` and `doctor` name the concrete backend; the CLI printed
  the wrapper, so its answer could not be compared with theirs. `yazses inject` now prints
  `Backend: XdotoolInjector`.

  Both halves moved into `inject/auto.py` (`apply_injection_config`, `describe_injector`) and
  `tests/test_injector_config_reaches_every_caller.py` fails the build on a function that
  builds an injector without applying the bridge, or that prints the wrapper class. An
  exported `YAZSES_INJECTOR` still wins over `backend = "auto"` — that is the documented
  one-run override, and the bridge leaves it alone.

- **`[stt] language` reached the decoder in one place and was dropped in four.**
  `FasterWhisperEngine.__init__` takes `language: str = "en"` and pins it on every decode, so
  a construction site that omits the argument does not get auto-detection — it gets **English**,
  silently, for a user who configured something else. `stt/factory.py` threaded it; nothing
  else did.

  `yazses verify` built the concrete class directly, so it ignored `[stt] engine` **and**
  `[stt] language`: a Parakeet user was certified on faster-whisper, and a Persian user was
  verified in English and then told *"the model returned nothing… try a larger one with
  `[stt] model`"* — the wrong knob, from the one command whose claim is that it runs the
  chain the daemon runs. It now calls `build_engine(cfg.stt)`, exactly as the daemon does.

  `yazses tune --retranscribe` re-transcribes the corpus to build **ground truth**; decoded in
  the wrong language, every proposal drawn from it was drawn from noise.

  `recimport/pipeline.py` — so `yazses transcribe` and `yazses meeting`'s post-pass — read
  `language` only to decide `task = "translate"`. `--language fa` set nothing else and had
  Persian audio transcribed as English with no error. The flag now takes any Whisper code,
  `""` auto-detects, `translate` still means X→English, and a non-English code on an `.en`
  checkpoint warns through the same `language_model_problem` rule the daemon uses instead of
  returning fluent nonsense. Defaults are unchanged: only values that previously did nothing
  behave differently.

  `tests/test_language_reaches_every_decoder.py` walks the tree for every
  `FasterWhisperEngine(...)` and fails the build on one that omits `language=`, and pins that
  `verify` builds through the factory while the daemon still does.

- **`yazses report` printed your name.** The bundle's promise is *"your settings with paths
  and identifiers removed"*, and the notification's **Prepare a bug report** button prefills a
  public GitHub issue form with it. What decided whether a value was an identifier was a
  key-name regex plus a two-item set of "free text" keys — a list of the fields someone had
  thought of. `[macros] author`, whose comment in `config.py` reads *"value substituted for
  `${author}`"*, was not on it, and came out of the redactor as `<redacted> Seyedkazemi
  Ardebili`: the account name matched, the surname did not, and the marker invites the reader
  to believe the field was cleaned. `[filters.disfluency] llm_endpoint` was the second —
  `host`, `address` and `port` are all in the key filter and "endpoint" was never spelled, so
  `http://192.168.1.50:1234/v1` travelled whole. `[bridge] device_name`, documented as *"last
  paired companion (informational)"*, is the third: a phone is usually named after its owner.

  All three are now replaced, and the classification is **total** rather than exceptional:
  every `str` field reachable from `Config` must be an identifier (`_REDACT_KEYS`), your own
  prose (`_FREE_TEXT_KEYS`) or a value from a published set (`_SETTING_KEYS`), and
  `tests/test_report_classifies_every_config_string.py` fails the build on a new one until
  someone decides which. Settings still come through verbatim — a bundle nobody can read is
  as useless as one that leaks — and prose keeps its length, so *"the vocabulary is set, and
  it is 400 characters"* survives while its contents do not.

- **The `DOWNLOAD` column in `yazses features` now counts model files, not just packages.**
  `feature_sizes.json` is generated by resolving **pip** closures, and a model file is not a
  package — so the catalogue priced **Read-Back Loop** at `~12 MB` while `tts/download.py`,
  the module whose whole job is fetching what that feature runs on, opened with *"one-time
  (~340 MB)"*. Both numbers were committed to this repository and nothing compared them.

  The consequence was not only a wrong label. `LOUD_DOWNLOAD_MB` exists to prevent exactly
  "I asked for a small feature and it filled my disk", and at 12 MB the one capability that
  fills a disk sat 238 MB under the threshold and could never trip it. `read-back` now reads
  `~352 MB` and warns loudly; `meeting`/`diarize`/`recimport` read `~62 MB` rather than `~18 MB`
  (45 MB of sherpa diarization models), and `gaze` `~223 MB`.

  `features enable` names the two separately — *"downloads ~12 MB (7 packages), plus ~340 MB
  of model files on first use"* — because they arrive at different times, and it now quotes the
  model even when every package is already installed, which is where the old early return told
  someone about to fetch 340 MB that there was nothing to download.

  `depsize._MODEL_FETCHERS` is keyed by the downloading module rather than by feature, and
  `tests/test_feature_size_counts_model_files.py` derives both sides from the tree: every
  `download.py` under `src/yazses` must be priced, and where a module states its own size in
  its docstring the price must equal it. A fifth downloader fails the build until someone
  decides what it costs. Not priced, and now said so in the docs: `stt-parakeet` and
  `stt-moonshine` fetch their weights inside their own libraries.

- **`yazses doctor` now reads `[learning] redact_patterns` and `capture_audio` together.**
  They sit one field apart in the same section and nothing in the tree compared them.
  Redaction runs at `_enc`, the single place text becomes a stored blob, so every transcript
  column really is covered — and `capture_audio` defaults to **true**, which writes the
  source audio beside the row. Someone who added a pattern to keep a card number out of the
  corpus has it scrubbed from six text columns and themselves reading it aloud in
  `clips/<id>.wav.enc`.

  Nothing is broken and nothing changed in what is captured: no redaction can reach into a
  waveform, and the clip is exactly what `yazses tune --retranscribe` needs to produce
  ground truth. What was missing is that the promise and its limit were never stated in the
  same place. Doctor is where someone looks to find out what is stored, so the two settings
  are now read there together — and stay silent unless learning is on *and* a pattern is
  actually set. The privacy statement says the same thing beside the setting.

- A setting or `--flag` named in a **shipped message** is now checked to exist, as one
  named in the docs already was. Three families of advice are guarded here — a command,
  a flag, a `[section] key` — and only the command guard covered both places advice
  lives. Its own docstring says why the shipped half is the half that matters:

  > an undocumented command is a gap, while advice naming a command that does not exist
  > is a dead end handed to someone who is already stuck.

  That reasoning is about *advice*, not about commands. A page is read while things are
  working; a runtime message is read when they are not. `yazses doctor`, the mic-change
  notification, the settings window and the "could not type that" toast all tell people
  what to set, and none of those strings had ever been compared against the config the
  daemon loads or the options the command accepts. Following a bad one produces no error
  at all — `configcheck` drops an unknown key deliberately, so the setting silently does
  nothing and the file still loads.

  **It finds nothing today** — zero across 101 backticked settings and 57 flagged
  invocations, out of 16,406 shipped string literals — which is the reason to pin it now
  rather than after it drifts, exactly as its two docs-side twins were pinned at zero.

  The predicates are imported from those twins rather than re-implemented, so a future
  change to either teaches this guard in the same commit; re-writing them is what
  produced the asymmetry in the first place. Both scans carry a corpus floor, because a
  guard whose input can quietly empty passes on everything.

  The extraction rule was measured, not assumed: requiring backticks gives 101 mentions
  and no false positives, while a bare `[section] word` gives 203 and reads ordinary
  English as settings (`[endpoint] is`, `[personalize] on`) along with `pyproject.toml`'s
  `[project] authors`, which belongs to a different file's schema entirely.

### Fixed

- **The privacy statement said your spoken notes-to-self were in the encrypted corpus. They
  are a plain text file.** The sentence sat inside the section explaining that the corpus is
  machine-bound AES-256-GCM with only coarse metadata in the clear: *"The `recall` and
  `scratch` note features read from this same local corpus."* Half right. Spoken Recall does
  query the encrypted corpus; Ambient Scratch appends each note to `scratch.jsonl` as plain
  JSON, and `recall/scratch.py` says so in its own docstring — *"Notes are plain local files
  under the user's data dir."*

  Auditing the rest of the directory found the same gap by omission. `src/` writes thirteen
  things under the data directory and the page named four. **Meeting Mode was not on the
  page at all** — the one capability that records other people's voices, keeps its
  transcripts and minutes in plain text, can retain the recording, and stores enrolled
  participants as voiceprints. Neither was `few_shots.toml`, which `yazses tune --apply`
  fills with decrypted utterances taken out of the corpus.

  The page now has a Meeting Mode section — including that recording other people may need
  their consent, which YazSes cannot judge for you — and a table accounting for every path
  in the data directory and whether it is encrypted. Three are not, and each is deliberate:
  a note dictated in order to be read back, examples you approved yourself, and a meeting
  transcript whose purpose is to be opened.

  The guard derives the set from the source rather than restating it, so a feature that
  starts writing somewhere new fails on the commit that adds it, when someone still knows
  what it holds. There is no allow-list for "not really user content": a lock file and a
  model cache are one table row each, which costs a line and removes a judgement call.

- **`yazses corpus forget` deleted the row and left the transcript in the file.** Its own
  help says what it is for — *"e.g. after dictating something private"* — and the privacy
  statement names it as the answer to *"if you need something gone now"*. A plain SQLite
  `DELETE` marks the page free and leaves the bytes in place. Measured on a corpus built in
  a temp directory: forget one event, find its exact encrypted blob at a byte offset in the
  freed page, decrypt it, and read the sentence back.

  Encryption is not the protection here, because the key is not elsewhere. `corpus.key` is
  machine-bound and lives beside `corpus.db` by design (ADR-012) — right for a local
  corpus, but it means residue in a freed page is readable by exactly the person the user
  ran `forget` to protect themselves from.

  `PRAGMA secure_delete = ON` now zeroes freed content on every delete path — `forget`,
  retention eviction, the size sweep, and anything added later. Fixing it at the connection
  rather than at the one call site with a test matters: retention is described in the code
  as *"a privacy control (ADR-012)"* and would have kept leaking. `forget` also compacts the
  database, which clears residue left by earlier versions — the pragma zeroes content as it
  is deleted, not content already deleted.

  The privacy statement now also says what this does **not** cover: the filesystem may keep
  the blocks of an unlinked clip or a deleted journal, which is below SQLite and below this
  project.

- **`[learning] max_corpus_mb` emptied a text-only corpus instead of trimming it.** The
  size sweep deleted the oldest event and re-measured, in a loop, until the corpus fitted
  under the cap. `DELETE` does not shrink a SQLite file — the pages go on its free list and
  the file stays exactly as large. With audio captured, the clips are unlinked alongside
  the rows, the directory shrinks and the loop converged; that is the only case the
  existing test covered, because it is the only case that existed when it was written.

  `[learning] capture_audio = false` is the other case, and the privacy statement offers it
  in the table of things you stay in control of — *"store text but not audio"*. With no
  clips, every deletion freed zero bytes and the loop ran until there was nothing left to
  delete. Measured on a 2.95 MB text-only corpus against a 1 MB cap: 1500 events in, 1500
  deletions, **0 events left, still 2.95 MB on disk**, 32.8 s spent. Every captured event
  destroyed, no disk reclaimed, and nothing said about it.

  The sweep now reclaims the freed pages, so what it measures is the size the file actually
  is, and stops as soon as a round frees nothing rather than continuing to delete. Sitting
  a little over the cap is the right failure for a disk limit: emptying the corpus to
  satisfy it costs the user everything the limit was protecting. It also drops the oldest
  events in proportional batches rather than one row per commit — the same corpus now keeps
  311 events at 0.62 MB, in 0.1 s.

- **The privacy statement said the diagnostic log never holds your dictated text. One
  supported setting away, it does.** `[general] log_level = "DEBUG"` writes each
  transcript into `daemon.log` — which is exactly what `docs/cli-reference.md` tells you
  to turn on to investigate a dictation problem, and that page was the only one that said
  so. `docs/privacy-statement.md` stated flatly that the transcript *"is not written to
  any log file"* and that the log records *"metadata only … never your dictated text"*.
  `docs/install-linux.md`, `docs/command-index.md`, both localized indexes and the
  `yazses logs` help string carried the same unconditioned promise.

  Nothing is uploaded either way and none of this changes what the daemon writes — the
  default is still metadata only, and `yazses report` has dropped every DEBUG line from
  its bundle since `18e0d7a`. What changes is that the pages now say which of the two
  they are describing, and how to clear the file if you turned `DEBUG` on.

  Measured through the real `Daemon._configure_logging` into a temp directory, emitting
  from the real call site: at `"INFO"` the sentence is absent from `daemon.log`; at
  `"DEBUG"` it is there in full. The new guard is page-level (the caveat lands in a
  different place on each page) and tied to the code — it scans `src/` for `.debug(…)`
  calls that pass user text, so if that ever stops being true the guard retires instead
  of forcing a caveat that would then be false.

- `yazses audio use` confirmed pins it had not checked meant anything.
  It called the resolver only to ask *did anything match?*, then echoed back the string
  the user had typed. Two kinds of name were accepted without a word, and neither can
  deliver what pinning promises.

  **A name several devices answer to.** `resolve_input_device` returns "the first
  substring match, in device order" — PortAudio's enumeration order, which is exactly
  what a hotplug or a reboot reshuffles. So an ambiguous pin keeps the failure mode
  pinning exists to remove while looking like it fixed it. This is easy to hit rather
  than theoretical: on the maintainer's laptop the capture list is three entries all
  named `sof-hda-dsp: - (hw:0,N)`, so the obvious thing to type matches all three.
  `yazses audio use sof-hda-dsp` now lists the candidates and exits 2 without writing
  anything — the user is at a prompt and their intent is genuinely underdetermined.

  **A name that is a route.** `default`, `pipewire` and `sysdefault` forward to whatever
  the sound server currently points at, so the device behind them can change with the
  name unchanged. `audio status` already refuses to *advise* an alias — the helper that
  does it carries a long comment about why — while `audio use` accepted one silently, so
  the two halves of the same guarantee disagreed. It is still pinned (it is not
  destructive, merely not a guarantee) and now says plainly that it cannot hold capture
  in place.

  A successful pin also names the device it resolved to instead of the string typed. A
  substring pin is meant to be loose; seeing what it caught is the only confirmation
  there is.

  The count and the resolution now come from one function, `match_input_devices`, with
  `resolve_input_device` returning the first of its results — so "which device is this?"
  and "is it the only one?" cannot drift apart. Pinning a device that is not plugged in
  yet still works: that case is deliberate and is covered by its own test.

- `yazses quickstart` promised to check the speech model and never did.
  Its docstring — which is also `yazses quickstart --help` — says it looks at
  "prerequisites, whether the daemon is running, the speech model, your hotkey".
  Three of those four were read. The model was not: step 2 printed *"It loads the speech
  model once (first run can take 10–30s)"* whatever the state of the disk.

  That sentence describes the *load* time for a checkpoint already downloaded, and says
  nothing about the case that goes wrong. On a machine where the model is missing, the
  first thing YazSes tells a new user to run is a command that will silently spend a
  ~141 MB download before it does anything — and behind a firewall, does not finish at
  all. That is [#310](https://github.com/MSKazemi/yazses/issues/310), the first bug ever
  reported by a real user.

  `docs/models.md` already had the answer and had it well: *"You do not have to leave it
  to chance. Fetch it as its own step."* The first screen a newcomer reads is the one
  place that advice never reached.

  Step 2 is now tri-state. Model present: it says so and names it. Model missing: the
  download becomes its own numbered step, before `yazses start`, because a blocked
  network should fail inside a command whose entire job is to download and can report
  why. Daemon already running: nothing about models at all — it has loaded one.

  Both surfaces answer from `stt.download.is_cached`, the same predicate `doctor` and
  `model list` use, and a test drives that one function and asserts `doctor` WARNs
  exactly when quickstart sends the user to download. A second opinion here would be a
  second answer, on the machine where it matters least to be inconsistent.

  Neither helper can cry wolf: an unreadable config or an unreadable cache reports the
  model as present, since a cosmetic check inventing a scary claim is worse than a
  cosmetic check staying quiet. The existing quickstart tests also stopped reading the
  host — they were taking whichever branch the developer's own Hugging Face cache
  happened to produce.

- The Flatpak build installed no launcher, no icon, and not even its own store listing.
  `packaging/flatpak/com.mskazemi.YazSes.metainfo.xml` declares
  `<component type="desktop-application">` and
  `<launchable type="desktop-id">com.mskazemi.YazSes.desktop</launchable>`, and
  `com.mskazemi.YazSes.yml` had three modules — portaudio, setuptools, and the generated
  wheel set — none of which installed a `.desktop` file, a hicolor icon, or the metainfo
  into `/app/share/metainfo/`. Searching the whole repository for the desktop-id matched
  exactly one file: the metainfo naming it.

  Installed like that, the app has no entry in any app grid, no icon in GNOME Software or
  KDE Discover, and Flathub's linter rejects a desktop-application whose launchable
  resolves to nothing — the same class of blocker that closed flathub#9765, where the
  metainfo turned out to have no `<screenshots>` block.

  Nothing reported it because every existing check reads the XML. `appstreamcli validate`
  passes — it did here, on this machine, before the fix — and so does pre-flight item 5
  in `SUBMISSION.md`, which is that command. Validating a file says nothing about whether
  the build ships it. The guards added now read the *manifest* and ask what lands in
  `/app`: the launchable's desktop file must exist and be installed, an icon named after
  the app ID must land under `hicolor/`, the metainfo must be installed, every `path:`
  source must be committed beside the manifest, and the desktop entry's `Exec` must name
  the command the manifest actually exports.

  The icon is the scalable `contrib/icons/yazses.svg`, copied flat beside the manifest
  because a Flathub repository cannot reach into `contrib/`. That is a second copy of the
  brand mark, so the drift guard that named `snap/gui/yazses.svg` was replaced by a sweep
  over every tracked SVG outside `docs/` — the old one covered the only copy that existed
  and would have said nothing about this one.

- Chocolatey's package page linked release notes ten versions out of date.
  `packaging/chocolatey/yazses.nuspec` declared `2.29.0` while its `<releaseNotes>`
  pointed at `releases/tag/v2.19.0` — the *Release Notes* link chocolatey.org renders
  on the package page, and what `choco info yazses` prints.

  `scripts/refresh-package-manifests.py::render_nuspec` rewrote `<version>` and nothing
  else, so the notes link only ever moved when someone edited it by hand. The script's
  own constants already name this failure — *"Chocolatey and Flatpak were refreshed by
  neither this script nor CI … Flathub advertised the wrong release notes"* — and
  `render_metainfo` was given the fix, with a docstring saying why. The nuspec got it
  for its version and not for its notes, in the same file, in the same change.

  `test_every_manifest_declares_the_same_version` could not see it: it compares each
  manifest's declared version against the others, and this was a second version *inside*
  a manifest that declared the right one. Every URL-bearing line in a single-file
  manifest is now required to name that manifest's own version, and the generator is
  pinned separately from its output — `--check` compares the file to what the same
  generator produces, so a generator that stopped rewriting the link would agree with a
  file that had not been rewritten.

  The winget tree is deliberately out of scope: its manifests live in per-version
  directories, where an old directory naming an old version is the format working. So
  are `homebrew/yazses.rb` and `arch/PKGBUILD`, which interpolate `v#{version}` and
  `${pkgver}` and therefore cannot drift at all — the two manifests that interpolate
  nothing are the two that could, and one did.

- The Flathub listing's **Help** button pointed at a page that 404s.
  `packaging/flatpak/com.mskazemi.YazSes.metainfo.xml` *is* the listing — GNOME Software
  and KDE Discover render it, and flathub.org indexes it — and its
  `<url type="help">` was written as `…/yazses/troubleshooting/`. The site sets
  `use_directory_urls: false`, so the page is `troubleshooting.html` and the directory
  form is a 404, served to someone who pressed Help because they were already stuck.

  `test_shipped_links_resolve.py` had both rules — the page must exist, and it must not
  use the directory form — and applied them only to Python strings, as though a link had
  to be *printed by the program* to be clicked. `test_flatpak_metainfo.py` reads that same
  file and checks its `<url>` fields, but only that none is a placeholder; it verifies
  every screenshot resolves to a real file while its own docstring says "a listing whose
  images 404 is worse than one with none".

  Both rules now run over every tracked file, so the snap listing, `pyproject.toml` (the
  PyPI sidebar), `CITATION.cff`, the AppStream metainfo, the install scripts and the docs
  are covered. Three exclusions are reasoned and tested rather than assumed: `…/yazses/apt`
  is the APT repository directory that `install-apt.sh` fetches `KEY.gpg` from, not a page;
  `sitemap.xml` and the feeds are generated assets, classified by extension so a new one
  needs no edit here; and a sentence-final period is not part of a URL, which `llms.txt`
  and the Flathub submission notes would both otherwise have failed on.

- The Configuration Reference gave a reader no way to tell a working setting from a
  dead one. 63 of its 447 keys are accepted by the loader, validated by `configcheck`
  and given a documented default while **no code reads them** — and they were rendered
  in the same `Key | Type | Default` rows as the keys that work. `[audio] sample_rate`
  is read; `[audio] channels` is the row directly beneath it and is not.

  The set was already known: `tests/test_config_keys_are_read.py` has gated it since
  the `[injection] fallback_to_clipboard` incident, where a key documented in seventeen
  places and defaulted to `true` was read by nothing, so anyone who turned it off was
  silently overruled. That test's own docstring left the rest open — *"whether the
  documentation should mark them is a separate question, and a real one: today a reader
  cannot tell which knobs do anything."*

  It is answered by moving the detector and the ledger into `scripts/config_status.py`,
  which the test and `scripts/gen-docs.py` now both read. The reference grows a **Status**
  column marking each inert key, and its legend counts them at generation time, so the
  prose cannot drift from the list the suite gates on — the failure that had left ADR-019
  claiming "seven" outbound calls when five of them had been the real number for months.

  The marking needs its own assertion against the rendered page: `test_gen_docs.py`
  compares the committed file to what the generator produces *now*, so dropping the
  column would keep it perfectly green.

- Sixteen example configs offered `[audio] channels`, a setting nothing reads. `examples/`
  is what people copy and `build-deb.sh` ships `config.example.toml` into
  `/usr/share/yazses/`. The existing guard rejects a key that does not *exist* — an
  unknown key is dropped and reported — but an inert one passes: it exists, it validates,
  it has a default. Removed, and the sweep now covers `examples/*.toml`.

  Disclosure counts as a fix, not only deletion. `config.vscode.toml` keeps
  `lsp_enabled = false` under a header explaining the key is inert in this build and why;
  that file is more honest than one where the key is merely absent, because a reader who
  has heard of the LSP bridge is told directly that it does nothing yet. The exemption
  is proximity-scoped so one paragraph cannot excuse an unrelated key elsewhere.

- The egress guard that enforces "nothing leaves your machine" could not see five
  modules. ADR-019's inventory is *enforced* rather than written down — a module that
  gains an outbound primitive fails the build until it is declared — but the detector's
  own vocabulary was two hand-written literals, and asking the opposite question ("is
  every network-capable import in the tree on that list?") found that it was not.

  `_NETWORK_ROOTS` had no `asyncio` and no `webbrowser`, so `remote/agent.py`
  (`asyncio.start_server`), `platform/emg/ble_backend.py` and `system/browser.py` were
  invisible. `_DEPENDENCY_LOADERS` had no `download_model`, so `stt/download.py` — the
  module whose entire job is fetching a checkpoint, written for issue #310 — and its CLI
  caller were invisible too. `tests/test_model_cache_first.py` already knew
  `snapshot_download`: two guards over one mechanism kept separate vocabularies, and a
  file fell between them.

  All five are legitimate and all five are now declared, with proofs rather than
  descriptions: `remote/agent.py`'s bind is pinned to `127.0.0.1` (it accepts text and
  types it into the focused window — `host="0.0.0.0"` is a one-word diff that would put
  that on the LAN), and the BLE backend is asserted to open no socket.

  The most useful find is a fourth *mechanism*: handing a URL to the browser.
  `report.issue_url` builds a pre-filled GitHub issue, and its docstring said "submits
  nothing" — true of the issue, misleading about the report, which is percent-encoded in
  the query string and so reaches github.com **when the page opens**, not when the user
  presses submit. The body was and remains `report.collect`'s redacted output, so no
  dictation is involved; the timing is what a reader deserved to be told. ADR-019 gains
  the section, the class, and a correction: it claimed "six of the seven only pull in"
  when the table has always held five fetches and two sends.

- `doctor` described one of the five things that reach Whisper's `initial_prompt`, and
  drew the wrong conclusion from it. Measured on a real machine: `yazses vocab list`
  printed **24 words** while, in the same minute, `yazses doctor` printed *"STT prompt: app
  name only (set `[stt] initial_prompt` to add vocabulary)"*. The daemon merges the
  configured prompt, the personal dictionary, `YAZSES_VOCABULARY`, corpus-mined terms and
  context-primed terms; the row read the first and reported it as the whole.

  That is worse than an incomplete row: it told someone who had already added vocabulary,
  by the route the product documents, to go and add vocabulary — so the honest reading was
  that `yazses vocab add` had done nothing. `system/vocabulary.py::prompt_summary` now names
  every source, and a guard pins the describing surface to the composing one so a sixth
  source cannot be merged while the diagnostic still names five. (Writing that guard is how
  the fifth, context priming, was found — it was missing from the first draft.)

- `yazses vocab add` ended with *"Apply it: yazses restart"*, and no restart was ever
  needed. `_effective_initial_prompt` runs inside `_on_hold_end` — once per burst — and
  `load_vocab` is uncached, so a word added now is primed on the next dictation. Proven
  against a single daemon object: add a word between two calls and the second call has it.
  The product asked for a daemon stop/start, and the model reload behind it, in **six**
  places (`vocab add`'s help, epilog and printed line, `vocab remove`'s help and epilog,
  and `vocab import`'s printed line) plus twice in the docs. All eight now say what
  actually happens, `vocab remove` confirms it too, and `docs/how-to/personal-vocabulary.md`
  gains the "confirm it is in use" step that the broken `doctor` row should have been all
  along.

- A microphone that failed to open cost 300 ms of speech, and only the retry was ever
  written down. `AudioRecorder.start` retries a transient open failure, and the retry works:
  measured on a real machine's log over 2026-08-18→20, **12 opens failed across 149 bursts
  (8%) and every one recovered on the second attempt** — only `attempt 1/3` ever appears.

  What nobody asked is what the recovery cost. By the time `start()` runs the key is already
  down, the tray is already green and the earcon has already told an eyes-free user to speak,
  so the pause is not idle time — it is speech, and it cannot be recovered afterwards, because
  the stream that would have buffered it is the stream that failed to open. The pause was a
  flat 300 ms: many times longer than the fault it was waiting out.

  The delays are now front-loaded — 50 ms, then 550 ms — so the common failure costs **50 ms
  instead of 300 ms**, while the cumulative wait before the final attempt stays at the previous
  600 ms, so nothing that used to recover now fails instead. The warning names the cost rather
  than reading as a hiccup that was handled, and `_OPEN_ATTEMPTS` is derived from the schedule
  so the two cannot drift. `system/diagnosis.py` had recorded the recovery ("it has always
  recovered") without the follow-up question; the old tests pinned how many times the retry
  slept and never what it slept for, which is why the number could be six times too large with
  nothing failing.

- `yazses meeting list` printed four meetings as four bare timestamps, and their lengths were
  on disk the whole time. Measured on a real machine: the four `meeting.json` files held
  `duration_s` of **11.6, 26.6, 56.7 and 8081.4** seconds — one two-hour meeting among three
  accidental starts — and the listing showed none of it, so telling them apart, which is what a
  person opens the list to do, meant opening four files.

  Why it stayed missing is the more useful half. The row was **three copies of one f-string**
  (`meeting status` has two branches, `meeting list` has one), so adding a column meant
  remembering three places. `_speaker_summary`, added by an earlier fix, even cites the
  8081-second meeting in its own docstring: that pass corrected the speaker column and left the
  duration sitting beside it.

  There is now one renderer, `_meeting_row`, and a test that fails if a second one appears —
  the duplication is the defect, and the missing column was its symptom. Length is formatted as
  `2h 14m` / `56s`, and a meeting that never finalized gains no second word for a fact its row
  already carries: it says `unfinished`, not `unfinished unknown`.

- `yazses verify` certified a microphone that was hearing nobody. Run in a quiet room with
  nobody speaking, on this machine: `[OK] Signal: level 0.0059 clears the gate … but only just
  (1.5x)`, `[OK] Transcription: heard "You"`, `✓ The whole chain ran`. "You" is the commonest
  thing Whisper returns for silence, and `verify` is the project's only check that produces
  evidence rather than inference — a false pass there is the most expensive false pass it has.

  The existing decision **not** to treat "You" as a ghost phrase is untouched and remains right:
  it is also an ordinary English word, no rule on the *output* separates the two cases, and a
  `verify` that wrongly fails sends someone to re-calibrate a microphone that was fine. But that
  dilemma only exists on the output side. On the input side the question has an answer, and this
  project already computes it — `recimport.audio_io.holds_no_speech` runs the Silero detector
  that `faster-whisper` bundles, and `yazses transcribe` has asked it since it was written.
  `verify` did not, so on the same room, the same minute and the same microphone, `transcribe`
  reported "no speech was recognised" while `verify` certified the pipeline.

  `verify` now asks too, after the gate check and before decoding: no speech in the recording is
  reported as the broken link, with the same remedy the other silence paths give. Only an
  explicit *yes, there is no speech* acts — where the detector cannot run it answers "unknown"
  and behaviour is exactly as before, which is also why every existing caller is unaffected.
  Confirmed both directions on real audio: the silent room now exits 1, and a LibriSpeech clip
  of real speech passes untouched.

- Three model loaders could hang forever on a machine that already had the model. Measured on
  this project's own laptop, twice: a **fully cached** `base.en` loaded in **1.9 s** with
  `HF_HUB_OFFLINE=1` and **had not finished after 180 s** without it, at 3 s of user CPU — blocked
  on I/O, not working. A hub round-trip to revalidate a snapshot has no timeout, and a network that
  neither answers nor refuses (a captive portal, a blackholed rule, hub rate-limiting) turns "load a
  file that is on disk" into a wait with no error and nothing to read.

  `stt/faster_whisper.py` was fixed for this once already, because it accepts
  `local_files_only=True`. The three others accept nothing of the kind: speechbrain's
  `from_hparams` (the ECAPA speaker encoder, on the path of `yazses meeting enroll` and of any
  transcript that names a speaker), `onnx_asr.load_model` (the ~600 MB Parakeet checkpoint) and
  pyannote's `from_pretrained`. They share the layer underneath — all four fetch through
  `huggingface_hub` — so the switch now sits there instead, in `system/hfcache.py`. A cached model
  loads with no request at all; a missing one is downloaded exactly as before, because trading a
  hang for a broken first run would be no improvement.

  Two details are load-bearing. The flag is set in the environment **and**, when
  `huggingface_hub` is already imported, on its in-process constant — that constant is read from
  the environment at import time, so the variable alone is a silent no-op for a package that
  imported the hub earlier. And a user who has set `HF_HUB_OFFLINE` themselves never gets a
  fallback download: `docs/how-to/air-gapped.md` tells people to verify a cached model that way,
  and a quiet fetch would make the check answer a different question.

  What let three loaders go unguarded is that nothing compared "modules that fetch a pretrained
  model" against "modules that load cache-first". Those two sets are now one test, so a fourth
  loader fails the build rather than reintroducing the hang.

- The guard on `ROADMAP.md`'s test-count floor cried wolf on ordinary `-k` runs. It decided
  "is this the whole suite?" by counting collected tests against a fixed 1000 — a threshold set
  when the suite was around 4300 and never revisited. At 7000+ tests an everyday subset clears it
  (`-k "docs"` collects 1108) and then fails the `4300+` floor, which reports a shrunken suite that
  does not exist. The test's own docstring says a guard that cries wolf during development gets
  deleted, so this was on its way to being the thing it warns about.

  The question is now asked of pytest rather than inferred from a count: `-k`, `-m`, `--deselect`,
  `--ignore`, `--lf`/`--ff` and naming a file or a node id each mean tests were removed, and
  nothing else does. The verdict stays independent of the claimed floor for the reason the
  previous author wrote down — scaling a threshold off the floor makes an absurdly *raised* floor
  **skip** the check instead of failing it, which is the one case the guard exists for. A run with
  the floor set to 99000 now fails with the real count rather than passing quietly.

- A meeting whose post-pass never finished kept its entire recording, and nothing offered it
  back. The daemon deletes `audio.wav` only **after** the batch pass that consumes it has
  succeeded — its failure branch logs that the file "has been KEPT … so it can be retried" — so a
  crash, a `kill`, a machine that slept or an out-of-memory notes model all leave the whole
  meeting on disk. That promise was made to the log and to nothing else. `yazses meeting list`
  flagged a meeting recoverable only when a `live.jsonl` existed, which is the *rolling* transcript
  the live decode happens to produce; a crash before the first utterance was decoded, or
  `[meeting] live_transcript = false`, leaves no such file, so the meeting printed as though it had
  finished — `? speaker(s)`, no warning — with the recording unmentioned beside it. And there was
  no retry: the audio was reachable only by finding the WAV by hand.

  The listing now flags a kept recording, says so as `unfinished` rather than guessing a speaker
  count, and names both surviving artefacts in the order they are worth reaching for. New
  **`yazses meeting recover <id>`** re-runs the transcription, diarization and naming on the kept
  recording and writes the same outputs `meeting stop` would have, marking the result
  `recovered: true`. It never deletes the recording — on a retry that file is the only copy, and a
  second failure must leave you no worse off than the first — and it refuses a meeting that already
  finished rather than overwriting a good transcript.

  One hazard is pinned by a test in two ways, because it would be silent and total: recovery must
  not go through `MeetingController`, since `MeetingSession.__init__` opens `audio.wav` with
  `wave.open(..., "wb")` and would truncate the recording it is recovering on its first line.

  One predicate, `store.has_recording`, answers "is there a recording here" for both the listing
  and the refusal — an empty 44-byte WAV header, which `WavFileSink` writes at session start, is
  not one. The refusal briefly carried its own copy of that number, which would have let the
  listing offer a recovery the command then declines.

- A meeting recorded against a muted microphone, or of a room where nobody spoke, was written
  up as a finished meeting — and summarised. `recimport.pipeline.transcribe_file` has always
  answered whether the audio held anything (`silent_input`, and now `no_speech`), and
  `meeting.finalize` wraps that same pipeline and **dropped both flags**: only `yazses transcribe`
  ever read them. So the recording that makes the CLI print a warning produced a meeting with
  `status: "done"`, a transcript of the words a speech model answers noise with, and — worst —
  `notes.md`, those words turned into confident bullet points by a local LLM. That is the one
  output nobody can audit afterwards, because by default the audio is deleted the moment the
  post-pass returns (`[meeting] retain_audio`). `meeting.json` now records a `capture` verdict
  (`ok` / `no_signal` / `no_speech`, written explicitly so a meeting from before this field is
  distinguishable from one that was checked), `yazses meeting list` says so on the meeting's line
  with the remedy that matches — a dead capture is a device problem, an empty room is not — and
  the notes pass is **refused**, at finalize and again on the `yazses meeting notes <id>` path
  that would otherwise walk straight around it. `--force` is there because a speech detector can
  be wrong about a very quiet talker and the transcript is right in front of you.

  Two things deliberately not done: `retain_audio` is **not** forced on for a flagged meeting —
  keeping audio the user asked to delete is a privacy decision, not a diagnostic one (ADR-011),
  and the flag is only known after the audio has served its purpose; and the transcript body is
  untouched, because `relabel` re-renders it from `transcript.json`, which does not carry these
  flags, so a banner written at finalize would silently vanish on the first relabel.
  Half of this gap was recorded in `tests/test_recimport_cleans_utterances.py` on 2026-08-19 and
  left open; `tests/test_meeting_capture_quality.py` closes it, and `docs/reliability.md` gains
  the section that explains why an empty recording produces a confident transcript rather than an
  empty one. Two existing finalize tests fed `np.zeros(...)` and expected minutes — a pairing the
  shipped code now refuses, and one that could not occur in the first place; they use the committed
  LibriSpeech clip, so the audio backing their fake transcript actually holds speech.

- `yazses transcribe` wrote a word nobody said, and said nothing about it. Four seconds of
  faint room hiss produced a sidecar file containing **`You`** — Whisper's stock answer to
  non-speech audio — with no warning of any kind. The guard that exists could not see it:
  `carries_no_signal()` tests the **peak** amplitude, deliberately, so that an hour of sparse
  interview is not called silent, and its floor is `1e-4`. The hiss peaked at `0.0036`, thirty-six
  times the floor and entirely ordinary for a real room. A peak answers *"was anything recorded"*;
  nothing about amplitude answers *"is any of it speech"*, and that is the question the
  hallucination turns on — a quiet talker and a noisy empty room occupy the same range. The
  pipeline now also asks the second question, with a detector: Silero, which `faster-whisper`
  already ships as a bundled 1.2 MB ONNX asset, so nothing is downloaded and nothing leaves the
  machine. `TranscriptResult` gains `no_speech`, and `transcribe` prints a note that keeps the
  remedy separate from the muted-microphone one — the file may simply hold music or room noise,
  in which case `yazses audio devices` is the wrong place to send anyone. An invented transcript
  also no longer counts as a success for the "star this project" nudge.

  It is a **detector, not a filter**, on purpose. Passing `vad_filter=True` into the decode would
  also stop the hallucination, and it re-segments the audio: measured on six LibriSpeech
  `test-clean` clips it left four transcripts identical and changed two, one of them for the worse
  (*"There were the only persons on the road"* → *"that were the only persons on the road"*). Real
  speech decodes exactly as it did; only what gets printed changed.
  `tests/test_no_speech_is_not_a_transcript.py` pins both halves, including that a genuine
  recording earns no note at all. Known gap, recorded rather than quietly widened:
  `meeting.finalize` wraps the same pipeline and drops `silent_input` — it drops `no_speech` too.

- An idle daemon burned CPU re-reading a string that cannot change. The IPC status payload
  carried `"version": _running_version()`, and that calls `importlib.metadata.version("yazses")`,
  which walks `sys.path` for a `.dist-info` on **every call** — **2.1 ms** measured. Status is
  not a one-shot: the voice-activity overlay polls it 4x a second while idle and 20x while
  recording, the tray 1x and 6.7x, and **both are on by default**. So a stock idle install spent
  roughly **40 s of CPU an hour** producing a value fixed at import — inside `self._lock`, the
  same mutex `_on_hold_start` takes when the hotkey goes down. Measured on a real session: an
  11-hour daemon reported 1 h 6 min of CPU. The lookup is now memoised, which is the same fact
  the field's own comment already states — *"a daemon keeps running the build it started with"*.
  (The measured session's 1 h 6 min is the whole cgroup — daemon, tray and overlay together;
  this one field accounts for about 7 min of it. The rest is the pollers themselves, which is a
  separate question.)
  The repository had even written the cost down: `tests/test_cli_startup_cost.py` guards against
  *importing* `importlib.metadata` because it is "the single most expensive import in the tree",
  one file away from a call site paying a comparable cost five times a second.
  `tests/test_status_poll_cost.py` pins it: the lookup happens once across 200 polls, a failed
  lookup is still `""` and still cached, and `_handle_status` may not inline a metadata lookup
  of its own.

### Changed

- `docs/how-to/cpu-and-battery.md` described **two** background pollers when there are three,
  and the one it omitted is both the fastest and on by default: the overlay's status poll at
  4 Hz idle / 20 Hz recording. The table now lists all three with their idle rates and the
  command that switches each off, and the page no longer implies the status call is free. The
  numbers are pinned to the code — `tests/test_status_poll_cost.py` reads the poll intervals out
  of `overlay/poller.py` and `tray/app.py` and the defaults out of the config dataclasses, so a
  changed interval or a flipped default fails the build instead of quietly making the page wrong.

- `yazses features enable denoise` turned the feature on and installed nothing, and the card
  that describes it said the opposite of what the code does. `denoise` is a registered,
  toggleable feature but was absent from `_FEATURE_DEPS`, the map that tells `enable` which pip
  packages a feature needs — so the command wrote `[denoise] enabled = true`, reported success,
  and left `noisereduce` uninstalled. The daemon then logged one warning at startup
  (*"the 'spectral' backend needs noisereduce ... audio is passed through unprocessed"*) and
  passed audio through untouched for the rest of the install; found on this machine as line 2 of
  a 574 KB `daemon.log`. `yazses features info denoise` compounded it by claiming *"the
  DeepFilterNet backend is NOT implemented in this build yet, so enabling this currently passes
  audio through unchanged"* — false since `denoise/spectral.py` shipped, and `DenoiseConfig`
  defaults to `spectral`, not `deepfilternet`. The map now pins `noisereduce>=3.0.3` to match the
  `denoise` extra in `pyproject.toml` (the extra the warning itself tells the user to install),
  and the card names the spectral backend and scopes the passthrough claim to DeepFilterNet,
  which caps `numpy<2.0` and cannot be installed here. `tests/test_feature_deps_cover_every_probe.py`
  generalises it: every `probe_backend(..., requires=…, extra=…)` call in `src/` must have some
  feature in `_FEATURE_DEPS` that installs the module it requires, so a backend that names an
  extra can no longer be reachable through an `enable` that does not fetch it.

- Half the public v2 features page described capabilities this build refuses to enable, and
  six of them named a pip extra that does not exist. `docs/v2-features.md` opens with *"Manage
  all of them with `yazses features enable <name>`"* — and that command exits 1 with *"designed
  but not yet wired into this build"* for every slug in `_UNWIRED`, which is **61 of the page's
  122 rows**. Nothing on the page said so. Six rows went further and told the reader to install
  the `affect`, `predict`, `scribe`, `rag`, `codec` or `voiceguard` extra; none of those exist
  in `pyproject.toml`, so the documented install route failed as well. A seventh named
  DeepFilterNet as the content of the `denoise` extra, which actually ships `noisereduce` —
  DeepFilterNet caps `numpy<2.0` against this project's `numpy>=2.4.6` and cannot be installed
  here at all, a fact `system/backends.py` already documented one file away. Unwired rows now
  carry a ◌ with a legend that shows the refusal verbatim, the false extras are named as
  not-existing rather than as an install step, and
  `tests/test_docs_features_page_is_honest.py` makes both mechanical: a row whose toggle is
  unwired must carry the mark, a wired row must not, the counts stated in the legend must match
  the table, and every extra named anywhere in `docs/*.md` must be declared in `pyproject.toml`.
  Wiring a feature and un-marking its row now happen together or the build goes red.

- A microphone the OS was refusing got no remedy on any platform, and on Windows the right
  remedy was attached to a row that can never fail. `PermissionsBackend` carried exactly one
  message, `how_to_grant()`, and `doctor` prints it on the **keyboard** row only — so a macOS
  microphone denied by TCC rendered as the bare word `denied` (the one message that existed
  names *Accessibility*, a different service whose toggle is probably already on), and
  `WindowsPermissions.how_to_grant()` — almost entirely microphone text, down to
  `ms-settings:privacy-microphone` — could not be printed at all, because
  `check_keyboard_capture()` on Windows always answers OK. There is now a
  `how_to_grant_microphone()` on the protocol and on all three backends: macOS names the
  **Microphone** pane, the never-asked case (`AVCaptureDevice` reports NotDetermined until
  something records, so the prompt has not appeared yet — hold the hotkey once), and a
  bundle-scoped `tccutil reset Microphone com.yazses.app`; Windows names the pane, the
  separate *"Let desktop apps access your microphone"* switch, and the no-device case; Linux
  says plainly that there is no per-app gate here and names the commands that show what the OS
  can see. Separately, `doctor` told **every** operating system to run
  `sudo apt install libportaudio2` when `sounddevice` could not import — including the two
  with no apt, and where the wheel *bundles* PortAudio, so the real cause is a partial install
  and the fix is a reinstall. `portaudio_advice()` now answers per OS (Debian, Fedora/Arch,
  FreeBSD ports, and a wheel reinstall on macOS/Windows) and a test fails the build if any
  platform is handed a package manager it does not have.

- A whole `doctor` row was unreachable on the only OS it exists for. The **Elevated
  windows** check — the one that explains why dictation works everywhere except Task
  Manager — was gated on `platform_name != "windows"`. `Platform.name` is a `sys.platform`
  string, so the Windows bundle reports `"win32"`: the comparison was false on Windows and
  the row never rendered, while `docs/capability-matrix.md` told the reader *"`yazses
  doctor` reports which case you are in"*. Nothing caught it because the unit test invented
  the same string it was testing against, `_elevation_check("windows")`, and passed. The
  three names now live in `platform/base.py` and every bundle sets `Platform(name=...)`
  from them, so a reader cannot drift from the bundle that declares it; BSD still reports
  the real `sys.platform` ("freebsd14"), which is why family checks there are a prefix
  match and never an equality test. `tests/test_doctor_platform_names.py` parses `doctor.py`
  and fails on any platform-name comparison against a bare literal, or against a value no
  `build_platform()` declares — and asserts the set of names the bundles publish is exactly
  the set `get_platform()` dispatches on. `docs/windows-install.md` now shows the row.

- macOS Accessibility advice had nothing to say to the person it was written for. `doctor`
  answered a denied keyboard-capture check with *"Grant Accessibility access in System
  Settings → Privacy & Security → Accessibility → enable YazSes"* — which is exactly the
  instruction someone reads it **after** having followed. Reported on #182/#241 by the first
  human ever to run the macOS build (an M2 on macOS 26.6.1): Accessibility visibly enabled,
  three install routes tried, denied every time. Both missing facts were already in this
  project and simply never put where a blocked user lands: `docs/macos-install.md` states
  that macOS treats an unsigned app as a new identity when its hash changes — so a stale
  grant still renders as an enabled toggle — and `AXIsProcessTrustedWithOptions` is
  process-scoped, so the executable being asked about is worth naming. The message now says
  both and offers `tccutil reset Accessibility com.yazses.app`, **with** the bundle id and a
  note explaining why: the bare form clears the Accessibility grant for every application on
  the Mac. A test asserts the unscoped form never appears, and another pins the bundle id
  against `packaging/macos/yazses.spec`, since a reset naming the wrong bundle silently does
  nothing. Deliberately makes no claim about how macOS attributes trust between a launching
  shell and a bundle — that needs a Mac to verify, and there is none; naming the binary lets
  a reader see a mismatch without being told a mechanism that might be wrong.

- The microphone guard could fire and leave no record. `_note_silent_discard` logged only
  inside its auto-heal branch, which needs a *different* last-good device — so on a machine
  whose microphone has not changed, the one thing it wrote was a desktop notification, and
  `system/notify.py` logs at INFO only when `notify-send` is **unavailable**. A delivered
  toast leaves nothing behind. The guard was therefore silent in precisely the case it exists
  for: a working microphone capturing audio the recogniser cannot use. Found on a real
  machine reporting 15 of 50 recent bursts producing no text, with 50 `Empty transcription --
  discarding.` lines in the log and nothing anywhere saying whether the guard had ever run.
  It now writes one line per streak naming the burst count, the device and the threshold, and
  whether it healed — before the `silent_streak_notify` opt-out, since that setting is the one
  case where a log line is the only record that can exist. This is where it matters: `yazses
  logs` is what the product tells you to read when dictation stops, and `yazses report`
  bundles that same tail into a bug report.

- A capability the config turns on that **no code reads** was shown as working, on every
  surface that could show it. `yazses features` badged it `● ON`, counted it in the group's
  `(n/m on)` tally, and `yazses features info` printed `● ON` four lines above *"it cannot be
  enabled yet"*; the Settings window rendered a **ticked, greyed-out** checkbox for it. Both
  facts — your setting and whether anything reads it — sat on the same object one field apart
  and were never compared. This is not reachable from `features enable`, which refuses an
  unwired capability; it is inherited, because eight *planned — designed, not yet wired*
  capabilities carry a `recommended` tier, and first-run seeding wrote every recommended slug
  into `config.toml` before the refusal existed. A new third badge, `◌ set`, says what is
  actually true, the group tally counts only capabilities that do something, and both the card
  and the Settings help name `yazses features disable <name>` to clear the key. `--on` still
  lists them on purpose — that view asks what your config turns on, and it is where you would
  look for a stale key. The table-alignment guard was extended to the new badge in the same
  change: its row pattern matched `●` and `○` only, so `◌` rows would have gone unchecked
  while the suite stayed green.

- `yazses tune` understated its own runtime by 3–4×. `--limit`'s help and the CLI reference
  both said a full corpus *"can take about an hour"*; measured on a real corpus, 50 clips took
  510 s wall clock with `small.en` on a laptop CPU — 9.6 s each — and a corpus sitting on the
  product's own default `max_corpus_mb = 500` holds ~1,460 clips, so a full run is close to
  four hours. The number is the entire reason to print it: the code's own comment says *"an
  hour is a decision (run it overnight, use `--limit`), while 'a while' is not"* — and an hour
  is something you wait for while four is something you schedule. Both surfaces now quote a
  per-clip rate with the hardware named, which can be true on every machine in a way a total
  cannot, and note that clip *count* predicts runtime rather than audio duration, since every
  clip is padded to 30 s before the encoder sees it.

- `yazses meeting status` never said whether Meeting Mode was on. With the feature off —
  which is the default — the entire output was a complaint that *"Speaker labels are on but
  the diarization extra is not installed"* followed by a list of past meetings. Nothing was
  on: `enabled` defaults to `false` while `diarize` defaults to `true`, so the speaker-label
  advice fired on a machine that will never record anything, and a meeting list under it
  read as a working feature missing one extra. The reader's conclusion is *install the
  extra*, when the fact that decides everything else is that nothing is running. The daemon
  already published `meeting_enabled` on its general `status` payload — the tray needed it
  for exactly this reason — and the handler whose whole job is Meeting Mode did not send it.
  It does now, and `status` leads with the feature state, names `yazses features enable
  meeting`, and lists earlier meetings as history rather than as current. A daemon that
  predates the change is treated as *unknown* and behaves exactly as before, because
  claiming "off" from a missing key would be a fact invented from an absent one.

- `yazses corpus status` described eviction it does not do, and the description made
  working behaviour look broken. Its warning read *"full — the oldest events are evicted on
  every capture to hold it here"*, but eviction runs in sweeps: when the daemon starts, then
  every 200 captures. So the reported size sits **above** the cap between sweeps — measured
  on a real machine at `514.2 MB of 500 MB`, with eviction working correctly and the log
  recording its last run at daemon start. Told the size is pinned to the cap on every write,
  the only conclusion available from a number above it is that the limit has failed. The
  warning now names the real cadence and says the size can read above the cap; the cadence
  constant moved next to `prune()` so the sentence and the loop cannot drift apart. The same
  point is now in the privacy statement, because `retention_days` is a privacy control and
  "applied in sweeps" is a different promise from "applied immediately" — `corpus forget`
  and `corpus destroy` remain immediate.

- `mic-level` printed the threshold from `config.toml` under the label **current**, on the
  one command whose whole subject is that number — and it is the command the product sends
  you to when dictation silently stops. The daemon reads `vad_threshold` once, at start, and
  never re-reads the file, so any change without a `yazses restart` leaves the two
  disagreeing. Measured live on a real machine: the file said `0.004` while the daemon's log
  recorded every discard against `0.0005`, so someone diagnosing *"Silent audio —
  discarding"* would have read the file's number, judged the gate sane, and been looking at
  a gate eight times lower than the one throwing their speech away. The line is now labelled
  `vad_threshold in config`, and when a running daemon is gating elsewhere the command names
  both numbers, which direction it drifted, and `yazses restart`. It stays silent with no
  daemon — calibrating before one exists is the ordinary first-setup case — and compares
  with `isclose` rather than `!=`, because both numbers have been through a TOML parse and a
  JSON round trip and a last-bit difference is noise, not drift.

- `yazses report` blanked the one setting its bug reports most needed. The bundle already
  records `daemon.hotkey`, the key the running daemon is actually bound to, so a report
  from a drifted machine carried **both halves** of the comparison that explains *"the
  hotkey does nothing"* — and redacted one of them. The cause was a substring match: the
  redaction filter looks for `key` in a setting's name to catch API keys and secrets, and
  `[hotkey] key` and `command_key` both contain it. Nothing was protected, either — the
  same twelve fixed names are printed unredacted by `doctor`, `status`, `quickstart`,
  `hotkey show` and the tray tooltip, and listed in `yazses hotkey set --help`. Values from
  a small published set are now kept, via an allowlist keyed by **(section, key)** and
  gated on the value being in that set — so a future `[api] key` is still redacted even if
  it happens to read `space`, and an unrecognised value, precisely the case where nobody
  knows what it is, falls through to redaction rather than out of it. Paths, addresses,
  tokens and free text are unchanged.

- `doctor` warned about a dead hotkey and then closed by telling you to hold it. The
  `Hotkey` row was taught to compare the configured key against the running daemon's; the
  **summary line** — the last thing read, and the only one carrying a command — still built
  its *"hold X to dictate"* hint from the config file. On a drifted machine the run ended
  `▲ Good to go (3 optional warnings above) — you're all set — hold right_alt to dictate.`
  one line below the warning explaining that `right_alt` does nothing. It also filed the
  drift under *optional*, alongside a missing accessibility package: one is cosmetic and the
  other means dictation does not work at all, and lumping them together is what teaches a
  reader to skim past both. The summary now leads with `▲ Dictation will not work until you
  restart` and puts `yazses restart` **before** the key in the sentence, since the
  configured key is the right one to hold only after the restart. A machine with no drift
  keeps its green line unchanged.

- `hotkey show` and `quickstart` told you to hold a key that does nothing. `doctor` was
  taught to compare the configured hotkey against the one the running daemon is bound to;
  it was not the only surface reading the wrong source. Measured mid-drift on a real
  machine — config `right_alt`, daemon bound to `right_ctrl` — `yazses hotkey show`
  printed both keys with their labels **swapped**, naming the key that actually dictates
  as the command key, and `yazses quickstart` step 3 said *"Hold right_alt, speak"*, which
  produces silence and no error. `quickstart` is the first screen a new user meets and its
  step 3 is a single imperative, so it now names the key that **works right now** and says
  why the file disagrees; `hotkey show` warns without changing what it reports, since its
  job is to report the configuration. Both consult the daemon best-effort: no daemon, an
  older daemon or an unanswerable socket means one line less, never an error.

- The privacy statement said the network is needed exactly once. *"The one time YazSes
  does need the network is the **first** run, to download the speech model… `yazses update`
  is the only other outbound action"* — true of the default configuration, and false the
  moment you enable anything. ADR-019's own inventory already listed five modules that
  download when a feature is switched on. Anyone who turned on read-back, diarization or
  gaze and watched a connection open would have caught the project's privacy page in a
  falsifiable sentence, which costs far more than the accurate version does: nothing you
  *said* ever leaves, and that claim is untouched. The page now scopes the first-run
  sentence to the default configuration, says that each optional feature fetches its own
  model once, and gives the gated `pyannote` backend a sentence of its own — it is the one
  fetch that carries your Hugging Face token, and so the only one that says **who** is
  asking. The release watcher is no longer described as manual-only either: it is opt-in,
  but when it is on it is genuinely automatic.

- The egress inventory could not see a model download. Its two scans find outbound
  *primitives* by import (`socket`, `requests`, …) and network-capable *programs* by the
  strings handed to `subprocess`. Neither can see `WhisperModel("base.en")` —
  a repository id that a library resolves against huggingface.co with no network import
  anywhere in this codebase. ADR-019 had recorded the gap in prose and named
  `faster-whisper` as "the obvious case"; three more were already in the tree — Parakeet,
  ECAPA and pyannote, the last of which sends a credential. A third scan now enumerates
  them, the ADR carries the table, and a new loader that is not declared fails the build.
  This is the third mechanism found by asking what the previous guard still could not see,
  which is now written down as the pattern rather than the incident.

- `verify` said the microphone cleared the silence gate without ever saying by how much.
  Four consecutive runs in a quiet room, against a `0.0040` gate, reported `[OK] Signal`
  at levels of `0.0052`–`0.0060` and then `[OK] Transcription` on three fully invented
  English sentences — "I just want you to know that it's your fault." among them. Only the
  fourth was caught, and only because it decoded to a row of dots that the cleaner empties.
  Nothing downstream can tell an invented sentence from a real one and `verify` deliberately
  does not try; that call is yours, and it needs one fact it was not being given. The Signal
  line now says when the level barely cleared, names the multiple, and points at
  `yazses mic-level --set`. The threshold comes from the daemon's own log rather than taste:
  across 172 recorded bursts the quietest one that produced any text sat at 2.0x the gate, so
  at 2.0x the note would have covered 26 of the 41 bursts that decoded to nothing and none of
  the 131 that did not.

- `doctor` printed `[OK]` on a hotkey that did nothing. The daemon reads `[hotkey] key`
  once, when it starts, and never again — so `yazses hotkey set` without a `yazses restart`
  leaves you holding the key you just configured while the daemon still listens for the old
  one. `doctor` had both facts in front of it: the configured key on its `Hotkey` row, and
  the daemon's own resolved key inside the `status` payload it already reads the PID, state
  and model from. It never compared them, so the one command a user runs to ask *is
  everything fine* answered yes for the single failure they cannot otherwise diagnose. The
  row now turns `[WARN]`, names both keys, and gives the fix. `auto` is resolved to the
  platform default first, so a correctly configured machine stays green.

- The macOS `.app` could not name its own version. PyInstaller bundles no `.dist-info`
  unless the spec asks for it, so inside the frozen bundle every reader of
  `importlib.metadata.version("yazses")` met `PackageNotFoundError` — `--version`, the
  About box, the updater, the diagnostic report, and `doctor`, which printed
  `[WARN] Version: yazses version metadata not found`. The Windows spec has collected
  metadata, and had a test pinning it, since the installer smoke test caught the same
  failure there; the macOS spec had neither. It now collects it, and the macOS packaging
  guards carry the matching check so the two platforms cannot drift apart again.

- An unsupported `[stt] compute_type` was reported as a missing speech model. The value's
  valid range is a property of your processor, and ctranslate2 rejects a bad one from
  inside the model constructor — which the loader wrapped as "the model is not on this
  machine, and it could not be downloaded", then offered three ways to download a file
  already in the cache. The daemon's desktop notification said the same. It now names
  `[stt] compute_type`, lists the types this machine actually supports, and points at the
  default `int8`; it also stops attempting a pointless download first, which on a
  firewalled machine buried the real cause under a network error.

### Fixed — an audio rule fired precisely when its own diagnosis was impossible

`audio-backend-missing` matched the marker `"portaudio"` and answered *"The audio backend
PortAudio could not be loaded… install it with `sudo apt install libportaudio2`."* PortAudio
puts its own name in the exception class, so that marker caught **every** `PortAudioError` —
and a `PortAudioError` can only be raised by a PortAudio that loaded. The advice was to
install a library that is demonstrably present, because it is the thing that raised.

Four codes were landing there, verified against the installed library: `-9997` invalid
sample rate, `-9999` unanticipated host error, `-9986` internal error, `-9973` incompatible
stream host API.

**`-9997` gets its own rule.** `[audio] sample_rate` is a documented, editable key, so an
unsupported value is a realistic edit rather than an exotic failure — someone setting 44100
or 48000 on a device that will not do it. It now names the setting and the value to go back
to. The other three fall through to the stage wording, which says less and says nothing
false.

`-9996` ("Invalid device") gets the numeric alias `mic-missing` always needed, for the same
reason `mic-busy` has one for `-9985`: a `PortAudioError` can arrive carrying only the code.
An existing test pinned that code to *"PortAudio could not be loaded"* — its claim about the
mechanism was right, only the example was wrong, and it now asserts the correct rule.

### Added — nothing but DEBUG may carry what the user said

Two promises were made in prose and enforced by nothing: `yazses logs` is *"metadata only"*,
and desktop notifications describe what happened rather than what was said. Both held —
measured on a real 5,465-line log against 1,262 recorded transcripts, searching for a
distinctive four-word window of each, **zero** hits; of 30 notification call sites, **zero**
carry transcript text.

But `yazses report` bundles that log tail for a public issue, and at `log_level = "DEBUG"` it
would have carried dictated text (fixed alongside this). That is what a promise kept by care
rather than by a check eventually costs, so both are mechanical now.

`len(text)` and `len(text.split())` stay allowed — counts are the whole point of the INFO
line — and `log.debug` may still carry the text, deliberately and as documented. Anything
else that passes a transcript variable *whole* to a shareable log level or to a notification
fails the build. The reviewed-exception list ships empty, and a test asserts it stays that
way.

### Fixed — `yazses report` promised "never transcripts" and would have included them at DEBUG

The bundle is designed to be attached to a public GitHub issue, and `system/report.py`'s
docstring says the log tail *"records levels, durations and word counts, never transcripts."*
That is true at the default log level and false one setting away from it. `core/daemon.py`
states the split where it writes them:

    # INFO: metadata only (length); DEBUG: the actual text.

`[general] log_level = "DEBUG"` is supported, and it is exactly what someone turns on to
investigate the problem they are about to report. The tail took every line verbatim.

**Verified rather than assumed:** searching this machine's real 5,465-line log for a
distinctive four-word window of each of 1,262 recorded transcripts found **zero** hits. The
default level really does keep dictation out — the defect is the reachable exception, not the
normal case.

DEBUG lines are **dropped rather than warned about**. A bundle that is safe to share only if
the reader noticed a warning is not safe to share; the value of that file is that its output
is safe *by construction*, which is the same reason the corpus is reported by size and never
opened. The number of omitted lines is stated, so nothing is hidden and anyone who needs them
can attach the log deliberately.

### Fixed — an unplugged pinned microphone was told to pin a microphone

PortAudio renders the failing device number into its message (`Error querying device 9999`).
The `mic-default-unresolved` rule matched a bare `"error querying device"`, so it caught
**every** index and answered all of them with advice written for one:

    YazSes could not reach your default microphone
    It retries, and this normally passes on its own. If it keeps happening, pin the
    microphone you want with `yazses audio use <name>`…

For a pinned device that has been unplugged, every sentence of that is wrong: it does not
retry into success, it will not pass on its own, and the user has already pinned the
microphone they want — that pin is the thing that broke. The rule's own comment says what it
was written for (*"PortAudio index -1 is 'the default device'"*); the marker just did not say
`-1`.

The table takes the first rule whose markers all appear, so `-1` keeps its own diagnosis and
any other index falls through to `mic-missing` — the same advice as its text form, because it
is the same fault phrased by number.

### Fixed — running out of memory was answered with "try once more"

`system/diagnosis.py` turns a caught failure into something the user can act on, and states
its own rule: *"Say the next command, not the category."* A decode failure it did not
recognise fell through to the stage wording — *"The speech model failed while decoding what
you said. Try once more."*

For a `MemoryError` that is not merely vague, it is wrong: the next attempt allocates the
same model and fails the same way, so "try once more" spends the user's time proving it. The
fix is a setting the project already exposes and documents — a smaller `[stt] model`. On CPU,
`medium` and `large-v3` are exactly the choices a user makes optimistically and a low-memory
machine refuses.

Matched on the class name as well as the text, because a bare `MemoryError()` carries **no
message at all** — a text-only rule would never fire on the commonest form. `ctranslate2`
reports allocation failures in its own words, so "cannot allocate memory" is matched too.

Still advice, never a decision: nothing about what the daemon does changed, and ordinary
decode failures keep the generic wording — a rule that swallowed every decode error would
tell everyone to shrink their model, which is wrong for almost all of them.

### Fixed — two state-file loaders promised tolerance and each missed one exception

Both docstrings already commit to it — `load_calibration` returns *"None if
absent/unreadable"*, `load_state` returns *"zeros if absent/unreadable"* — and both handled a
missing file, an empty one, unparseable JSON and bad bytes. Both were defeated by the same
input: **valid JSON that is not an object.**

    gaze_calibration.json  containing  "a string"  ->  TypeError
    wordgoal.json          containing  "a string"  ->  AttributeError

`yazses wordgoal status` answered with a traceback. The gaze one was caught by a blanket
`except Exception` in `_build_gaze_targeter`, so it degraded correctly — by accident, and
only because that caller happened to be defensive. Relying on that is how the other three
files in this class (`macros.toml`, `redact_patterns`, `vocabulary.txt`) became daemon
failures.

Each `except` tuple now lists the exception its own docstring already promised to absorb.
Nothing else changed: the pre-existing repairs — a calibration of the wrong dimensions is
still refused, a negative word count is still clamped — are pinned so the widened handler did
not swallow them.

### Fixed — one non-UTF-8 byte in `vocabulary.txt` broke every dictation burst

The daemon reads the personal dictionary on **every** burst, to build Whisper's
`initial_prompt`. `load_vocab` decoded strictly, so a single bad byte — one word pasted from
an editor in another encoding — raised `UnicodeDecodeError` inside the burst's `try`. A
directory at that path raised `IsADirectoryError` the same way.

Every dictation then failed with a generic "could not type that", the toast named nothing,
and the log said `UnicodeDecodeError` without mentioning the vocabulary file. The daemon
survived; the product did not work.

**Tolerant to read, strict to write.** Losing one mojibake term costs a word that would never
have matched anyway; losing every burst costs the product — so reading replaces the bad bytes
and logs the path. Writing must not: `add_vocab` and `remove_vocab` rewrite the *whole* file
from that list, so a tolerant read there would persist the replacement characters into the
user's dictionary — a silent corruption caused by trying to help. They refuse instead.

### Fixed — a typo in `macros.toml` stopped the daemon starting

`Daemon.__init__` calls `build_macro_table`, and `load_macros`'s own docstring is explicit:
*"A single bad entry is skipped (logged), never raised — a broken macro must not break the
daemon."* It handled an unparseable file and an entry missing its fields. Two shapes got
through:

    macro = "a string"          ->  AttributeError: 'str' object has no attribute 'get'
    [[macro]]
    trigger = 42                ->  AttributeError: 'int' object has no attribute 'strip'

Both raise out of the constructor, so the daemon does not start. `macros.toml` is a separate
file, so `configcheck` — which exists so that no config can stop the daemon starting — never
sees it and nothing else could catch this.

This was an oversight rather than a decision, and the sibling proves it: `build_style_rules`
is called from the same constructor, for the same kind of user-authored side file, and
already rejects a non-list `rule`, skips a non-table entry, and wraps the load in `except
Exception` with the comment *"a style sheet must never block startup"*. The macros loader now
does the same, and one bad entry still leaves the good ones loaded.

### Fixed — an invalid redaction pattern stopped the daemon starting

`[learning] redact_patterns` is a list of regexes scrubbed from text before it reaches the
encrypted corpus. `CorpusStore.__init__` compiles them and `Daemon.__init__` calls
`build_writer` unguarded, while type coercion accepts any string for a `list[str]`. So:

    [learning]
    enabled = true
    redact_patterns = ["[unclosed", "\d{4}"]

loaded with **zero** `ConfigProblem`s and then raised `re.PatternError` out of daemon
startup. The daemon did not start at all — which is exactly what `configcheck` exists to
prevent: loading is total, *"no config file can stop the daemon starting"*.

**Capture is now disabled rather than the pattern dropped.** Dropping it and capturing anyway
is the obvious repair and it is the wrong one: a pattern written to scrub secrets would be
silently skipped, and the text it was meant to remove would be written to the corpus — worse
than either the crash or the dormancy. So `build_writer` fails **closed**, the log says why,
and `configcheck` reports the pattern so `yazses doctor` names it under Config validity. Both
promises hold at once: the daemon starts, and nothing the user asked to scrub is stored
unscrubbed.

The two halves are independent on purpose — `configcheck` reports, `capture` decides — so a
caller that builds a `LearningConfig` in code is protected by the same check.

### Fixed — no surface said your dictation was being sent to another machine

`yazses remote <host>` opens an SSH tunnel and routes every transcript to an agent on the far
end. That is one of exactly two paths ADR-019 lists as able to transmit what you said, and
the project's central claim is that nothing leaves this machine.

The daemon has published `remote_connected` since that feature shipped. **Nothing read it** —
not `yazses status`, not the tray, not `doctor`. Found by mapping all 36 status keys to their
consumers: seven had none, and this was the one that mattered.

`state` cannot stand in for it. The daemon sets `REMOTE_ACTIVE` when the tunnel comes up, but
a burst moves through `RECORDING` → `TRANSCRIBING` and `_on_hold_end` finishes at `IDLE` — so
`state` says "remote" only until the *next* thing you dictate, after which status reads
exactly like a local session for the rest of the connection.

`yazses status` now says so. The tray is deliberately left alone: its five colours have
documented meanings and adding a sixth is a design change rather than a fix.

### Fixed — `yazses restart` destroyed a meeting's write-up, and the daemon was already saying so

Stopping a meeting starts a post-pass: batch diarization over the whole recording, then the
minutes. `_handle_meeting_stop` sets `meeting_finalizing` and runs that work inline. The
SIGTERM handler does not wait for it, and `yazses restart` sends SIGTERM, sleeps **one
second**, then SIGKILLs any survivor.

So stopping the daemon in that window kills the write-up. The rolling `live.jsonl` survives
— the store flags such folders recoverable — but the accurate speaker labels and the minutes
do not, and there is no `yazses meeting recover` to redo them.

The collision is likely rather than theoretical: `yazses features enable <name>` ends with
*"Apply it: yazses restart"*, so the product itself asks for a restart, routinely, with no
idea whether a meeting is being written up.

**The signal already existed.** The daemon has published `meeting_finalizing` since Meeting
Mode reached the tray, precisely because after a stop the state returns to IDLE while
diarization and the notes still run. The tray reads it; nothing on the stop path did — so
the one surface that could prevent the loss was the one not asking.

`yazses stop` and `yazses restart` now refuse while a write-up is running and name `--force`,
following the same pattern as `corpus destroy --i-mean-it`. Best-effort by design: an
unreachable, erroring or older daemon answers "not finalizing" and the command proceeds,
because refusing to stop a daemon you cannot query would be worse than the loss this guards
against.

### Added — a source-order assertion must search for something that occurs once

Several guards assert that one thing happens before another by comparing positions in
`inspect.getsource(...)`. `str.index` returns the **first** match, so if the needle also
appears in an import line, a comment or a docstring, the comparison measures that instead
and the guard passes regardless of the order it claims to check.

Three such guards were written and caught in a single day, each only by sabotaging the
source and watching the test stay green: a needle that also appeared in the function's own
import block (twice, in two different files), and one that matched an explanatory comment
written beside the change it was checking.

The rule is mechanical now, in the same spirit as the existing empty-glob guard. Every
source-order needle in the suite is resolved against the source it actually searches and
required to occur exactly once — unless the call passes an explicit `start` offset, which is
a deliberate "the next one after here".

Its first catch was one of the guards added earlier the same day: a bare `"sibling"` that
occurs three times in the function it searched. Coverage is dynamic, because the ambiguity
depends on the *target's* source rather than the test's, and a floor on the number of
resolved sites keeps a broken scan from reading as a clean bill of health.

### Changed — the enum table records why it is small, and the exclusions are pinned

The closed-set validation added alongside this covers `[injection] backend` and
`[injection] target_guard`. **Eight further settings are closed sets and are deliberately
absent**: `[gaze] backend`, `[gaze] zones`, `[stt] engine`, `[emg] mode`, `[cocktail] mode`,
`[meeting] vad_backend`, `[voiceprint] backend`, `[polyglot] lid`.

Each already fails safe and says so. An unrecognised gaze backend disables gaze; an
unrecognised meeting VAD backend falls back to the always-available calibrated gate; an
unrecognised STT engine falls back to faster-whisper "with an honest log line saying exactly
what happened". That is the opposite of `target_guard`, where a misspelling turned a guard
*on*. Adding them would be eight more chances to reject a value that works, for settings
whose failure is already visible.

That reasoning now lives next to the table, and the fail-safe behaviour is pinned — so if
one of them starts falling back to something *enabled*, the exclusion stops being justified
and a test says so.

### Fixed — a misspelled `off` left the no-text-target guard on, and nothing said so

`configcheck` repairs what it can and reports every decision as a `ConfigProblem`, which
`yazses doctor` renders as *"Config validity: every setting is a usable value"*. Coercion
only checked **types**, and these are `str` fields, so a typo was stored verbatim and
reported nothing:

    [injection] backend      = "clipbaord"
    [injection] target_guard = "of"

What happened next depended on the key and was invisible either way. No branch matches
`clipbaord`, so the auto path runs while you believe you forced the clipboard. And the
daemon tests `target_guard != "off"` — so a misspelled `off` leaves the no-text-target
guard **enabled**, which is the opposite of what was asked. Getting a feature you switched
off is a different class of wrong from getting a fallback you did not choose, and that is
what decided this was worth fixing.

Settings whose documented values are a closed set are now validated, falling back to the
default and reporting the problem in the same shape as every other repair. Only genuinely
closed sets are listed: `[stt] compute_type` is a property of the CPU, `[stt] language` is
open, and a model name is whatever is downloadable — guessing at those would reject valid
configs, which is the worse failure.

The Settings window had its own copy of both lists and now derives from the same table.
Two copies of a closed set disagree the first time one is extended, at which point the
window offers a value the loader throws away, or refuses one it accepts.

### Fixed — the Arch package would have shipped a man page stamped with the previous version

`man/yazses.1` carries the version and date in its `.TH` header, and the sync test
deliberately ignores that line — enforcing byte-equality would turn every version bump into
a red CI run until someone remembered `make man`, which is a landmine rather than a safety
net. That reasoning is right; its consequence went unexamined.

The stamp was then refreshed by nothing automatic. `make docs` regenerated the reference
pages and the architecture figures but not the man page, no workflow ran `make man`, and the
project rule that covers it — *"CLI change → `make man`"* — is tied to CLI changes, which a
version bump is not. The file sat at `yazses 2.28.0` in a tree preparing 2.29.0, with a green
suite, correctly.

`gen_man.body`'s own note said the shipped page *"always carries the right version
regardless"* because `build-deb.sh` regenerates it. True — for the `.deb`. Two packaging
paths install this file, and `packaging/arch/PKGBUILD` installs the **committed** one
unchanged, so the AUR package ships whatever stamp is in git.

`make docs` now regenerates the page too, so any "refresh the reference material" step
carries the stamp with it. Deliberately **not** added: a test that the committed stamp equals
the package version — that would redden CI on a bump, which is exactly the failure the
existing design avoids. The new test asserts the mechanism, which cannot fail on a bump.

### Fixed — `doctor` reported a broken login service and no way to fix it

Two branches, on the page someone opens when the daemon is running the wrong build:

    [FAIL] systemd unit: ExecStart=… does not exist — the service crash-loops
           (status 203/EXEC) … Point the unit at your real binary or reinstall.

    [WARN] systemd unit: ExecStart=… differs from the yazses-daemon on PATH (…)
           — the service may run a different or older build

The first offers "reinstall", which is drastic and unnecessary. The second offers nothing.
A repair already existed: `LinuxLifecycle.install_autostart` regenerates the unit whenever
`autostart.needs_rewrite` says the recorded path has moved — precisely both situations — and
`yazses autostart enable` is the only command that reaches it. Both messages now name it.

The warning also names **which** install the unit will follow, because
`resolve_daemon_command` prefers the console script beside the running interpreter — and
this warning only fires when there is more than one install, so bare advice to "run `yazses
autostart enable`" would be a coin flip on exactly the machine that produced it.

### Added — nothing a stock install turns on may swallow ordinary dictation

`system/firstrun.py` seeds a config for every new user, and several capabilities it enables
can **consume a burst**: `revise` backspaces the previous injection, `timeline` rewrites it,
`verbatim` flips a persistent mode and types nothing, `compute` replaces the utterance with a
number, `checkdigit` holds it pending a spoken confirm. Each was individually reasonable.
Nothing checked the property they share: on a stock install, a sentence someone actually
said must come out as text.

Measured over 1418 real dictation bursts, under the same condition the daemon applies:
`scratch that` fired 0 times, timeline 0, verbatim 0, checkdigit 0, and compute twice — both
genuine arithmetic. That is the number this guard defends, and every parser is also shown to
fire on its own command, because parsers that matched nothing would satisfy all of it.

No source changed: this is a property that held and now cannot quietly stop holding.

### Fixed — inline compute turned a score, a range and a phone number into arithmetic

`[compute] enabled` is seeded on for **every new install**, and when `evaluate` returns a
value the daemon replaces the whole utterance with it — the text you spoke is discarded, not
adjusted. So this was the default experience, not an opt-in risk.

An earlier fix stopped it collapsing prose (`"I ran 5 miles over 2 days"` → `"2.5"`) by
refusing anything with letters left after the operator words are consumed. A string of
digits and hyphens has no letters:

    10-15      ->  -5        a range
    2024-2025  ->  -1        a span of years
    9-11       ->  -2
    555-1234   ->  -679      a phone number
    3-1        ->  2         a score
    2-2        ->  0         found in a real corpus

Dictated subtraction does not look hyphenated: "seven minus three" becomes `7 - 3`, because
the word substitution leaves the spaces it found. So a **spaced** hyphen still computes and
a bare `N-N` does not. `+`, `*` and `/` are untouched — they do not appear in dates, scores,
phone numbers or version strings — and the rule only applies when the hyphen is the *only*
operator, so `2+2-3` is unaffected.

Measured over 1422 real transcripts, compute fired 3 times before and 2 after; both
survivors are arithmetic.

`2026-08-19` was already rejected, but only because `08` is not a valid Python integer
literal. `2026-8-19` would have evaluated to `1999`. Both spellings are now refused by the
rule rather than by luck.

### Fixed — a fresh install seeded a config key that nothing reads

`system/firstrun.py` seeds `config.toml` on the first daemon start, enabling the DEFAULT_ON
and RECOMMENDED tiers so a new user gets the intended experience without configuring
anything. It writes 14 keys. Thirteen are read by running code. One was not:

    [chords]
    enabled = true

`yazses chords "press control shift P"` is a CLI command that renders `ctrl+shift+p` and
never consults that key; no daemon code reads it, and there is no spoken grammar behind the
catalog's promise that *"Say any shortcut and it's pressed"*. So **every new install**
carried a setting that did nothing while `yazses features` listed the capability as ON —
and the entry's own text said *"Off by default"*, which the RECOMMENDED tier contradicted.

`chords` is now OPTIONAL, which makes both sentences true at once and changes no
functionality: the CLI works whether or not the key is present.

The guard matters more than the tier. One wrong tier is a one-word fix; what let it reach
every user is that nothing connected the seed to the question *"is this key read
anywhere?"*, and the tier of a new capability is easy to set optimistically. That answer is
now computed from the code on every test run.

Deliberately narrow: this checks the keys **first-run writes**, not every toggle in the
registry. The wider question — further features whose `enabled` key nothing reads — is a
design decision about wiring versus re-describing and is not settled here. What justifies
acting on this one alone is that those are toggles a user may choose to flip, while this one
was flipped *for* them, by default, on every fresh install.

### Fixed — `features enable dictation` said the capability does not exist

Found by sweeping `features enable` across all 147 catalog entries against a scratch
config. 67 were refused and 66 refusals were correct and well-worded — experimental ones
name the `--force` escape, unwired ones explain that enabling would change nothing. One was
not:

    $ yazses features enable dictation
    Unknown feature 'dictation'. Toggle names: … (147 names)

`dictation` is the **core** capability. `yazses features` lists it, `features info
dictation` describes it, and `feature_status()` returns it. Only `enable` and `disable`
claimed it did not exist — and answered with a dump of every other name, which is no help
to someone who typed a real one.

One condition was doing two jobs (`if feat is None or not feat.toggleable`). "Does not
exist" and "exists but is not a switch" are different facts with different remedies, and
the second is the one a user can act on: there is nothing to fix, the capability is already
on. A genuinely unknown name still says so, and that direction has its own test.

Also swept clean in the same pass: all 147 entries render under `features info`; enabling
each of the 80 toggleable ones produces **zero** config problems on reload, so the
comment-preserving TOML writer is sound across every section it touches; the JSON-RPC IPC
server survives 16 kinds of malformed request with a bounded read, a timeout and no crash;
and `system/updater.py` detects this machine's install method correctly and verifies an
upgrade out-of-process, which is the only way to see a version that changed under a running
interpreter.

### Fixed — `shellpipe` advertised a "run it" step that does not exist

The capability catalog said *"renders 'ls | grep error | wc -l' as text; nothing runs until
you say 'run it'"*. There is no "run it" grammar anywhere in the product, `shellpipe` is a
CLI command the daemon never sees, and its own docstring says *"it NEVER executes
anything"*.

The wording mattered more than it looks, because it reads as a **safety** claim: "nothing
runs *until*" implies something eventually does, under a confirmation. A user who believes
there is a confirm step is a user who might speak a pipeline expecting a gate to catch it.
There is no gate because there is no execution — which is safer, and worth saying plainly.
The description now says that, and a test asserts against the *code* that no execution path
exists, so adding one fails rather than silently making the sentence true again.

Third instance of one shape in this sweep, after `windowctl` (layout verbs its backend
cannot perform) and `wordgoal` (spoken progress with no grammar behind it): a description
written alongside a design outlives the part of the design that shipped.

`shellpipe/build.py::dryrun_wrap` — which turns `rm -rf build` into `rm -i -rf build` — is
the other half of that missing path and is called by nothing. It is kept rather than
deleted, because making that decision in advance is the valuable part, and now says so in
its own docstring. `tests/test_orphan_modules.py` tracks whole *modules* and this one is
reachable through its two other functions, so a function-level orphan was invisible to it;
it is pinned by a test instead.

### Fixed — the egress inventory could not see the SSH tunnel that carries your dictation

ADR-019 promises a complete list of every way data can leave the machine, and
`tests/test_egress_inventory.py` enforces it by scanning for **imports** of network
primitives. It cannot see `subprocess.Popen(["ssh", ...])` — and that is how
`remote/forwarder.py`, the reverse tunnel that actually carries dictated text off the
machine, sat outside an inventory written to enumerate exactly that. The limitation the
guard documented was *"a dependency making its own call"*; spawning a program was not
mentioned.

A second scan now covers programs. Two modules are declared: `remote/forwarder.py` (spawns
`ssh`) and `gitvoice/plan.py` (builds a `git` argv that `cli.py` runs only under `--run`,
and only with `--yes` when destructive — repository content at explicit request, never
dictation).

**The tunnel is deliberately not counted as a third send path.** The remote route is one
logical thing — dictation → loopback TCP → the tunnel → the agent on the far host — and
counting the two files separately would overstate the exposure the project publishes. What
it does correct is the ADR's own table, which named the remote host as
`remote/local_proxy.py`'s destination: that module connects to `127.0.0.1` and nowhere
else, and the tunnel is the half that makes loopback reach the named host. The table
described the route rather than the module.

The public claim — two code paths can send what you said — is unchanged and still asserted.

### Added — the overlay's envelope follower is pinned as adaptive

Two indicators read the same `audio_level`: the tray's level ring and the overlay's rings.
The ring mapped it against a fixed multiple of the gate and read full on 44% of real bursts
at the default threshold; the overlay normalises against an adaptive peak and does not.

Measured on a real 162-second recording, chunked the way the daemon chunks it (2537
readings): median intensity 0.35 at a 0.01 threshold and 0.42 at 0.0005 — **a 20× change in
the gate barely moves the output**, with 0% pegged at either. That is the property worth
protecting: brightness tracks *loud for this speaker* rather than an absolute level, so a
badly-set gate degrades the rings gently instead of pinning them.

The two components needed different answers to the same problem, and the file says so: the
ring must put the gate at a **fixed point on its circumference** — "past the notch" has to
mean the same thing on every microphone — so it cannot normalise adaptively, and got a
logarithmic absolute scale instead. Recorded so the two are not later "unified" into one
broken shape.

### Fixed — the tray's input-level ring read full for ordinary speech

The ring exists because the five badge colours all say what YazSes is *doing* and none says
whether the microphone is hearing anything — which come apart exactly when it matters. It
mapped the level linearly with full scale at **4× the gate**, and its comment claimed that
would "compress the tail so ordinary speech fills a useful amount of ring". Measured against
**1617 real recorded bursts**, it did the opposite:

    threshold 0.01  (the default)   ring fully pegged on  44% of bursts
    threshold 0.004                                       81%
    threshold 0.0005                                      97%

A meter that reads full for half of normal speech carries about one bit.

Raising 4× to a larger constant is not the fix, because the ratio is not scale-free across
users: a well-calibrated gate puts speech at 2–4×, while a gate set too low puts the *same
voice* at 40×. Any fixed linear span is wrong for somebody.

The scale is now logarithmic over a 100× (40 dB) span — the ordinary range of an audio
level meter, not a tuned number. Over the same bursts that is **0% pegged** at the default
threshold and 0% at 0.004, and the spread of readings stays near-constant at every
threshold, which is the property the linear map lacked. A gate set 40× below the voice still
reads near full, and should: that is a real fault the ring is entitled to show.

An existing test asserted that 5× the gate "is a shout" and must peg. The p90 of real burst
levels is 0.0786 against a 0.01 default gate, so that level is ordinary speech; the test now
uses a genuinely loud level and records why.

### Added — every documented `config.toml` example is now loaded by the real loader

A documented snippet is copy-pasted, not read. If it names a key that does not exist, or
gives a value of the wrong type, `configcheck` does exactly what it was built to do — drops
the key, repairs what it can, carries on — so the user gets a config that loads cleanly and
a setting that never applies. Nothing errors, and the doc is what taught them to write it.

The suite checked the config loader, and it checked that the docs build. Nothing put the two
together. All **62** examples pass today, so this ships as a guard rather than a fix: the
value is that the next one cannot be wrong silently.

Two exclusions, both narrow and both asserted. Blockquoted blocks have their `> ` callout
prefixes stripped — otherwise the Windows install example fails to parse and the natural
"fix" is to skip blockquotes entirely, silently dropping coverage. And one block in
`docs/troubleshooting.md` deliberately shows a wrong value beside a right one; blocks whose
comment says "wrong" are skipped, and the *count* of skipped blocks is pinned, because an
exemption that can grow silently is a hole rather than an exemption.

Also audited clean this pass: all 85 backticked `[section] key` references in the docs name
real settings; `[mcp]` and `[profiles]` have no `enabled` key because they are activated by
running a command or adding table entries rather than by a switch, which is why they are
absent from the feature registry.

### Added — the command-safety gate's ordering is now asserted, not assumed

`cmdsafety` judges the command *text*, so it only works if it sees the text **as it will be
typed** — after every transform that can turn spoken words into shell syntax. The daemon
does that today, and nothing checked it.

Verified against this project's own learning corpus first: **1422 real transcripts** of
ordinary dictation through `clean_text` and `assess_command` fired the gate **0 times**,
while it fires on all six destructive patterns it claims to catch. A guard is judged on how
rarely it interrupts, and on real speech it never did.

Dictating a command produces words, not symbols — "rm dash r f slash" — which is not
runnable, so the gate correctly stays quiet, and neither `apply_voice_punctuation` (which
handles punctuation) nor `apply_symbols` (emoji and Unicode marks) converts it. But
`code/spoken.py::spoken_symbols` *does* emit `/`, `|` and `-`. It is unwired today; wiring it
after the gate would make a dictated destructive command runnable text typed into a shell
with the guard never having seen it. The new test fails the day that module leaves
`_UNWIRED`, so the ordering is extended rather than rediscovered.

Also pinned: the disfluency filter altered 84 of those 1422 transcripts and every removal
was an adjacent stutter (`"do not do not push"` → `"do not push"`) — no content lost across
a whole corpus of real speech.

### Fixed — `yazses mic-level` calibrated to an empty room and said "recommended" anyway

Run four times with nobody speaking:

    mean level:    0.0036 / 0.0044 / 0.0048 / 0.0050
    recommended:   0.002  / 0.0022 / 0.0024 / 0.0025

Every one of those is *below* the room noise that produced it. Applied with `--set`, that is
exactly the state where room tone clears the gate, reaches the decoder, and comes back as a
confident invented word.

**The provable half.** `analyze` returns `max(0.002, mean * 0.5)`, so `is_silent` fires
below 0.002 while the floor binds below 0.004. Between them is a band where nothing warns
*and* the printed "recommended" is the constant, carrying nothing from the sample — laptop
room noise lands in it. That is now reported, and `--set` refuses: writing a gate below the
room level that produced it costs silent nonsense, while refusing costs a re-run.

**The half that cannot be fixed with a threshold.** The command cannot tell speech from room
tone, and the obvious discriminator does not work. Measured across this project's own
1619-event corpus, peak-to-mean for clips *with* text (p10 8.5, median 11.9, p90 17.3)
overlaps clips with *no* text (p10 6.7, median 8.6, p90 21.8) — and the no-text p90 is
*above* the speech p90. No cutoff separates them. So the assumption is stated instead of
hidden, on every reading rather than only the clamped band, and the judgement goes to the
person who knows whether they were speaking. A test fails if the disproved ratio is ever
added.

**Not done here:** a real fix measures twice — ambient, then speech — and puts the gate
between them. The product already records ambient in `yazses doctor --mic` and never
combines the two. That changes an interactive flow and the meaning of `--set`.

### Fixed — `yazses meeting notes` announced work it had already ruled out, then misdiagnosed it

Run against a real stored meeting:

    $ yazses meeting notes 20260803-095635
    Generating minutes locally… (this can take a few minutes)
    Notes are off or no local model is set. Enable `[meeting] notes` and set
    `[meeting] notes_model` to a local GGUF.

Two faults in three lines.

**The promise came before the check.** `generate_minutes` returns `None` immediately when
notes are off, so "this can take a few minutes" was printed for work that was never going
to start. The precondition costs nothing to ask and is now asked first.

**One message covered five states, and for one of them it was wrong advice.**
`generate_minutes` returns `None` when the transcript has no utterances, when `[meeting]
notes` is off, when `notes_model` is unset, when llama-cpp-python is missing, when the model
path is not a file, and when every window fails to parse. For an empty transcript, "notes
are off" is simply false — no configuration produces minutes from no utterances, and the
message sent the user to change settings that were already correct. Each state now names
itself, ordered by what has to be fixed first: an empty transcript cannot be fixed by
configuration at all, a missing dependency cannot be fixed by a config key, and a path that
does not exist cannot be fixed by setting the path again.

Once the preconditions pass, a `None` result now says the model produced nothing usable and
points at `yazses logs`, rather than blaming a setting that is already right.

The dependency probe uses `find_spec` rather than importing `llama_cpp`, which costs seconds
and loads native code — far too much for a question asked before any work begins.

### Fixed — "Restore defaults" left seven Settings rows untouched without naming them

The reset confirmation ended with *"your hotkey, microphone, vocabulary and any hand-edited
settings are left alone"*. That was accurate when the window held switches plus a hotkey and
a microphone. It now carries **nine** value rows, and seven — speech model, language, compute
type, initial prompt, injection backend, text-target guard, onset padding — went unnamed,
covered only by "any hand-edited settings".

They are not hand-edited: they are edited *in this window*, on the rows directly above the
button.

It matters because those seven are the settings most likely to have broken dictation in the
first place — a `compute_type` the CPU cannot do is reported as a missing *model*, a
`language` mismatched to an `.en` checkpoint transliterates into fluent nonsense with no
error, an injection backend of `clipboard` is a no-op in a terminal. Someone in that state
resets, applies, restarts, and is still broken with nothing saying the reset never covered
it.

All nine are named now, and `tests/test_reset_scope_names_every_value_row.py` derives the
row list from a real window — so a value row added later fails until it is named, which is
exactly how the seven fell out.

Also audited clean this pass: the Settings window renders all 147 capabilities with a label
and a tooltip, and every one of the 63 non-toggleable rows is genuinely disabled in Qt, with
a tooltip explaining that toggling it "would write a config key nothing reads, so it is
shown, not offered".

### Fixed — subtitles were emitted as single lines of up to 80 characters

Measured on a real 162-second recording through `yazses transcribe --format srt`: 22 cues,
reading rate fine everywhere (max 16.7 chars/second), and **18 of 22 lines wider than 42
characters**, up to 80.

`merge_word_timestamps` caps a segment at `max_chars=80` and its docstring calls that a
*line*, but the writers emitted the whole segment as one. Every subtitle standard assumes
about half that — EBU-TT-D, the BBC guidelines and Netflix's timed-text spec all sit at
37–42 characters over at most two lines, because that is what fits the video width at
default caption size. Going over does not fail loudly: the player wraps it itself, wherever
it likes, or lets it run off frame. The output looked correct in a text editor and wrong in
a video.

Captions are now wrapped to two lines of 42. The wrap happens in the writers, not in
segmentation, and 42 × 2 fits the existing 80-character budget exactly — so every cue
boundary and every timestamp is unchanged. Verified against the real recording before and
after: 22 cues either way, identical timestamps, identical words.

The split is balanced rather than greedy (a full line above a two-word line reads badly),
and text that cannot fit two lines gets more lines rather than being truncated — a caption
that loses words is worse than one that is too tall.

### Fixed — `yazses audio status` told you to pin a name that cannot be pinned

`audio status` resolves the OS default's routing alias through wpctl and prints the real
device, then — directly underneath — *"Pin a real one to be sure: `yazses audio use
<name>`"*. That reads as "type the name above", and it does not work:

    resolve_input_device("Raptor Lake-P/U/H cAVS Digital Microphone", devices) -> None

The friendly name comes from the sound server's graph; `audio use` matches against
PortAudio's capture list, which offers `sof-hda-dsp: - (hw:0,0)`, `sysdefault`, `pipewire`
and `default` — no entry naming a microphone, and most of them routes.

**The outcome was silent rather than an error.** `audio use` warns on an unmatched name and
then pins it anyway, deliberately, so a device can be pinned before it is plugged in. On its
own that is right; combined with advice to type an unmatchable name it is the worst case —
the pin is accepted, never resolves, capture quietly falls back to the alias, and you
believe you fixed the exact thing pinning exists to prevent.

The advice is now derived from whether the name resolves, and a name that is itself a route
is never offered (an alias behind an alias reproduces the same failure one layer down). A
machine whose every input is a route says so instead of pointing at an empty list.

**Not fixed:** that the hardware names are useless is what PortAudio reports for ALSA.
Mapping a wpctl node to a PortAudio index needs a PipeWire client library, which the code
already records as a dependency this project does not take on for one diagnostic.

### Changed — `yazses tune` called a proposal "validated" on four percent corroboration

Run against a real 1619-event corpus:

    [1] Upgrade the STT model   (evidence: 189 event(s); validated (9/238 held-out))
    [2] Add vocabulary          (evidence: 44 event(s); unverified — no held-out ...)

Nine out of 238 is under four percent. The bar for the word was `holdout_support > 0`, so
**one** corroborating event out of 238 would have earned it too — sitting next to a 44-event
proposal labelled "unverified", which reads as the weaker of the two. The label was doing
work the number should do, in the direction that matters most: these proposals write to
`config.toml`, and "validated" invites applying one.

The verdict is replaced by the rate — *"corroborated by 9 of 238 held-out events (4%)"*.
No threshold was invented: a reader tells 4% from 84% without being told which counts, and
any minimum would have been a guess dressed as a standard. Zero corroboration keeps its
plain words, because *no* support is a real distinction rather than a small number, and a
share that rounds to zero displays as `<1%` — a shown `0%` beside a non-zero count reads as
a bug.

Also audited clean in the same pass: the vocabulary proposal **appends** to any existing
`[stt] initial_prompt` rather than replacing it, so applying it cannot discard vocabulary
you added by hand.

### Fixed — a recorded meeting of room noise was stored as a transcript reading ". . ."

Found in a real meeting folder. An 11.6-second capture finalized as:

    meeting.json    {"duration_s": 11.6, "num_speakers": 0, "status": "done"}
    transcript.md   ". . ."
    transcript.json {"text": ". . .", "utterances": [{"text": ". . ."}]}

`status: "done"`, listed by `yazses meeting list` like any other meeting.

**The rule existed and was applied on one path only.** The daemon injects what survives
`clean_text`, never what the model returned — that is why a dictated `[BLANK_AUDIO]` is
discarded rather than typed. `clean_text` appeared nowhere in `recimport/` or `meeting/`, so
both file paths stored Whisper's artefacts as transcript content. It now runs at the single
point both callers share, `recimport.pipeline.transcribe_file`, which `meeting.finalize`
wraps. Utterances that clean to nothing are dropped rather than emptied, so a caller
counting them sees the truth.

**Why the existing signal did not catch it.** `transcribe_file` already computes
`carries_no_signal(audio)`, and its docstring is right that a hallucinated transcript cannot
be detected from the output. But it measures the input's **peak**, deliberately — an hour of
sparse interview must not be called silent — and a quiet room is not digital silence. The
two checks answer different questions: that one asks *was anything recorded at all*, this
one asks *did any of it survive cleaning*.

`words` are deliberately untouched: they are timing data feeding alignment and subtitle
spans, and an index into them is not this function's to invalidate.

## [2.29.0] — 2026-08-19

### Fixed — `yazses corpus status` showed a size with nothing to compare it against

On a real corpus:

      events:    1619 (200 discarded, 0 flagged wrong)
      size:      500.0 MB

500.0 MB is exactly `[learning] max_corpus_mb`. The corpus was sitting *on* its cap and
`Store.prune()` was evicting the oldest events on every capture to hold it there — the one
fact the line failed to convey. It read identically to a corpus with room to spare.

That matters beyond tidiness: `yazses tune` learns from what survives, so a silently
evicting corpus quietly changes what the product can learn about you — and the date range
gives no hint, because a corpus starting twelve days ago looks the same whether capture was
enabled twelve days ago or the cap deleted everything before it.

The size is now shown against the cap, with a warning naming **both** limits when it is
full. Both, because `prune()` applies age first and then size, either can be the binding
one, and they discard different things: age eviction drops what is stale, size eviction
drops what is oldest regardless of how recent that is.

The 95%-of-cap line is a display choice and is labelled as one — `prune` evicts while
`disk_size > max_bytes`, so a corpus held at the cap always measures a hair under it and
"500.0 of 500 MB" would otherwise read as headroom.

Also audited clean this pass: `yazses report`. Its bundle carries no dictated text, no
paths, no identifiers — the corpus is reported by size and never opened, as ADR-011
requires. And its corpus size is the real on-disk figure (clips included), matching what
`corpus status` prints.


### Fixed — `yazses verify` certified a microphone that was hearing nobody

Run for real in a quiet room with nobody speaking:

    [OK] Signal: level 0.0044 clears the gate (0.0005)
    [OK] Transcription: heard "You"
    ✓ Dictation works end to end on this machine.

Room noise cleared the gate, the model answered near-silence with a confident invented
word, and the one command whose job is to find the broken link declared success. `verify`
is the only check in the project that produces evidence rather than inference, so a false
pass there is the most expensive one it has.

**The known artefacts were never checked.** `clean_text` strips `[BLANK_AUDIO]`, but
Whisper's other silence artefacts are ordinary English and survive it. The repo already
recognises them — `postprocess/hallucination.py` carries the outro list and the
repetition-loop detector — and `verify` never asked. A clip of pure room noise decoding to
"Thanks for watching" printed as a passing step. Both are now consulted, whole-transcript
only, which is that module's own premise; an outro phrase *inside* real speech is untouched.

**The verdict claimed more than the run proved.** `verify` can show the chain ran; only you
can say the words are the ones you spoke. It now says exactly that, and names the two
commands to run when the transcript is not what you said.

**Deliberately unchanged:** "You" still passes. It is the commonest thing the model returns
for silence *and* an ordinary word someone may have said, and no automated check separates
them. The asymmetry runs the other way here than on the daemon's hot path — a `verify` that
wrongly passes costs one confusing session, while one that wrongly fails sends someone to
re-calibrate a microphone that was fine. So the checks stop at the artefacts with no
legitimate reading, and the judgement that needs a human is handed to the human with the
evidence beside it.

### Fixed — `doctor` claimed voice window focus works while the feature was off

The half of the previous fix that was missing. Gating the daemon on `[windowctl] enabled`
made `yazses doctor` wrong in the same breath:

    [OK] Voice window focus: xdotool (X11) — "focus the browser" works

That line came from the presence of `xdotool` alone, and was only ever true while voice
focus ran unconditionally. Doctor is exactly where someone looks *after* it did not work, so
a confident OK there is worse than no line at all.

It now reports the feature as off, with the command that enables it. The Wayland limitation
is still reported first even when the feature is off, because enabling it there would not
help — sending someone to run a command that cannot work on their session is worse than
telling them the platform said no.

### Fixed — the advice for a silent-clip streak led to a dead end

Found on a running daemon. `yazses status` reported:

    ⚠ mic:    2 silent clips in a row — run `yazses audio status`

and `yazses audio status` answered *"⚠ silent clips in a row: 2 — mic may have changed."*
and nothing else. A diagnosis with no remedy, at the end of a hop the product told you to
take. The one surface that named a command was the desktop toast, which fires once, at
`silent_streak_threshold` (default 3) — a streak the CLI already displays from 1.

Three surfaces, three phrasings of one fault. Both now come from one pure function
(`audio/device_monitor.py::silent_streak_advice`), the way the meeting/diarization advice
was already consolidated so the daemon and the CLI cannot drift.

**The cause was also asserted rather than known.** A silent discard is by definition
`mean(|audio|) < vad_threshold`, which has exactly three causes: nothing was said, the gate
sits above your voice, or capture is not receiving that microphone. *"Your mic may have
changed"* is only the third — and on a typical Linux desktop it is the one YazSes can least
confirm, because the OS default is a routing alias whose name does not change when the
device behind it does. `yazses audio status` printed that warning two lines above the guess.
All three are named now, with the command for each.

### Fixed — `windowctl` ignored its own toggle, and still advertised commands it cannot run

**`features disable windowctl` was a no-op.** Nothing read `[windowctl] enabled`.
`core/daemon.py` called `_try_window_focus` unconditionally in command mode, so voice
window focus ran for every user — including everyone who never enabled it — against both
the catalogue's own *"Off by default"* and the project rule that new features ship off. It
also cost a startup xdotool probe to users who had not asked for the feature.

`_build_window_backend` now returns `None` when the feature is off. That is the whole gate:
`_try_window_focus` already returns False on a `None` backend, so a disabled feature routes
down the path Wayland already takes and "focus the browser" is dictated as text rather than
consumed.

**The dead layout verbs were still being advertised.** An earlier fix removed *"move window
left half"* / *"workspace 3"* from the description, because their grammar is wired to
nothing and `WindowBackend` has no method that could ever carry them out. But a feature's
`example` and `use_case` live in two other dicts in `features.py`, and the guard added at
the time scanned only `name` and `why` — so `yazses features info windowctl` contradicted
itself on one screen:

    ... Rearranging windows by voice is designed but not connected yet.
    Use when:  When you want to arrange windows and switch workspaces ...
    Example:   Say 'move window left half' or 'workspace 3' ...

Both now describe focusing, which is what runs, and the guard reads every field the user is
shown — plus a second assertion that fails if a new display field is added without being
brought into scope. `docs/v2-features.md` carried the same claim and is corrected.

### Fixed — two pure spoken-text modules that were wrong in the same shape

Both are in `features._UNWIRED`, so neither reaches a user today. They are fixed now
because whoever wires them would inherit the defect, and in both cases the rule was
*written down* and enforced by nothing.

**`code/spoken.py` — "fat arrow" was dictated as `fat ->`.** The substitution table is
grouped by meaning and carries the comment *"Longest phrases first"*, but `("arrow", "->")`
sat above `("fat arrow", "=>")`, so the shorter phrase matched inside the longer one. The
order is now derived (`_ORDERED`, longest-first) rather than hand-maintained: a word-bounded
phrase can only be shadowed by a longer one, so a phrase added in the wrong place cannot
reintroduce it. The authored list stays grouped for reading, and a property test over the
whole table fails on a bad addition rather than only on today's known pair.

**`condense/extract.py` — the summariser preferred the least informative sentence.** Score
was mean content-word frequency divided by the sentence's own length, so a one-word
interjection scored the full frequency of that word over one word and beat everything:

    "... Ship it. The release needs the changelog updated and the tags pushed ..."
        ->  "We should ship the release today. Ship it."

Ramble is exactly what this feature consumes, and it is full of "Right.", "Okay.", "Sure."
The divisor now has a floor of 2 — one content word is not a measurement.

The floor is deliberately no higher. Sweeping it showed no value is simply better: at 3 the
summariser starts discarding legitimate short sentences ("Fix the wheel."), and it takes 4–5
to out-rank a two-word echo. 2 is the largest value that removes a failure with no
legitimate counterpart. Both ends are pinned by tests so raising it fails rather than
quietly dropping real content.

### Fixed — a macro with two `${cursor}` markers typed one of them

`expand` positions the caret at the **first** `${cursor}`, as documented, by splitting the
template there and measuring the tail. Any further markers stayed in that tail and went
straight to the injector:

    template  "a${cursor}b${cursor}c"
    typed     "ab${cursor}c"

`${cursor}` is not a variable name, so `_resolve_vars` leaves it alone by design (unknown
tokens are kept literal), and nothing else removed it. A user who wrote two markers — easy
to do while editing a template — got the marker text in their document.

The extras are now stripped before the tail is measured, so the caret still lands where
the first marker was, now measured against the text actually injected. Unknown variables
are still left literal, which is deliberate and different: a stray `${...}` may be
something the user meant to type, while a second cursor marker is a directive already
honoured once.

### Fixed — enabling `[translit]` transliterated every English sentence into Persian

`detect_scheme`'s docstring promised *"so English passes through"*, and it returned the
scheme for **any** all-ASCII text — which is every English sentence. The caller
transliterates whenever it is truthy, so:

    "hello how are you"        ->  "ههللو هوو اره یو"
    "send me the file please"  ->  "سهند مه تهه فیله پلهاسه"
    "the quick brown fox"      ->  "تهه قویcک بروون فوx"

The gate never gated. Enabling the feature did not degrade English dictation, it destroyed
it — and the stray Latin `c` and `x` show the output was not even well-formed Persian.

Detection now does what it always claimed: a sentence containing a very common English
word is left alone. A Finglish sentence whose romanization collides with one ("to
khoobi?", where Persian *to* is "you") stays in Latin script — the right direction, since
a missed transliteration leaves readable text while a false one produces nonsense the user
cannot read back.

`[translit] enabled` is off by default, so this affected whoever turned it on.

### Fixed — the grammar fixer turned "an FBI agent" into "a FBI agent"

`fix_articles` decided purely on whether the following word's first *letter* is a vowel.
An initialism's article depends on how it is **said**: "FBI" is spelled out — "an
eff-bee-eye" — so it takes "an". Nine of ten correct initialisms were rewritten wrong:

    an FBI agent  ->  a FBI agent
    an MRI scan   ->  a MRI scan
    an SSD drive  ->  a SSD drive
    an XML file   ->  a XML file

A grammar corrector introducing grammar errors into text that was already right.

The article before an all-caps token is now left alone. No rule keyed on spelling can
separate the two kinds: "FBI" is spelled out and takes "an", "NATO" is said as a word and
takes "a", and nothing in the string distinguishes them. A missed correction costs
nothing; a false one corrupts.

Ordinary words are unaffected, including the hard cases the module exists for — "an hour",
"a user", "a university", "an honest man" — and a merely capitalised word like "Apple" is
still corrected, since the check is all-caps rather than capitalisation.

### Fixed — inline compute replaced whole sentences with a number

`evaluate` is documented as turning **a whole-utterance arithmetic expression** into its
answer, and did not check that. After mapping the operator words it stripped every
character that was not a digit or an operator, so any sentence carrying two numbers and
one operator word collapsed to an expression:

    "I ran 5 miles over 2 days"    ->  "2.5"
    "chapter 3 minus chapter 1"    ->  "2"
    "we met 2 times in 3 days"     ->  "6"

Six of eight ordinary sentences. "over" and "times" are common English words, and unlike
the other text transforms this one does not mangle the utterance — it **discards** it and
types a number instead.

Anything left after the lead-in words and the operator words have been consumed now means
the utterance was prose, and prose is returned untouched. Every real calculation still
works, including percentages and the spoken "percent".

`[compute] enabled` is off by default, so it affected whoever turned it on.

### Fixed — an LLM rewrite could change a number and pass the guard meant to catch it

`_tokens_preserved` checked that each meaning-critical token still appeared in the output
with a plain substring test. That is right for a word and wrong for a number:
`"100" in "1000"` is True, so

    "transfer 100 dollars"  ->  "Transfer 1000 dollars."   accepted
    "upgrade to v2.1"       ->  "Upgrade to v2.10."        accepted

An amount changed by an order of magnitude, in dictated text, waved through by the one
check whose purpose is that such tokens survive.

A token carrying a digit must now match on a word boundary. Anything else keeps the
lenient test deliberately — "API" surviving as "APIs" is ordinary reformatting, and
tightening that would reject rewrites the feature exists to make. A trailing sentence
period, currency prefix and percent suffix all still pass.

### Fixed — autopair appended a stray apostrophe to "it's"

`balance_delimiters` tracked `'` in the same stack as brackets, so every apostrophe read
as an *opening single quote* and got a closer appended:

    "it's fine"            ->  "it's fine'"
    "the user's file"      ->  "the user's file'"
    "I can't see O'Brien"  ->  unchanged, because the two happened to pair up

That last case is the awkward one: the behaviour depended on whether the utterance held an
**odd or even** number of contractions, so it looked intermittent rather than broken — and
contractions are among the commonest words in English. `autopair` is wired into the
dictation path and off by default, so it affected anyone who turned it on, on most
sentences they spoke.

A quotation never opens directly after a letter or digit — there is a space or a line
start first — while an apostrophe always follows one. Closing is unchanged: once a `'` has
opened, the next one closes it, so `he said 'hi'` still balances, as do `"`, `` ` `` and all
three bracket pairs.

### Fixed — "undo that sentence" deleted the whole burst when it ended in a full stop

`_trailing_count` found the last sentence terminator with `rfind` over the whole string,
then refused it when it sat in the final position — which is exactly where a completed
sentence puts one. The fallback then deleted everything:

    "One. Two three."   ->  15 backspaces, the whole burst gone
    "One. Two three"    ->  11 backspaces, leaving "One."       (correct)

So the feature worked only on a burst whose final sentence had **no** terminator, and
dictation ends sentences with one — from voice punctuation or from Whisper's own. The
common case was the broken one, and the failure removes text the user did not ask to
remove.

The search now ignores the burst's own final terminator, so the boundary found is the one
*between* sentences.

`test_undo_word_and_sentence` used `"Hello world. Bye now"` — no trailing period — so it
pinned the intended semantics exactly and never exercised the shape that failed. It passes
unchanged.

### Fixed — approving one `tune` proposal changed two settings

`set_toml_key` substituted the key **anywhere in the file**, with no section scope and no
`count`. Both `[stt]` and `[meeting]` carry a key called `model`, so approving `yazses
tune`'s top proposal — *"Upgrade the STT model"* — also rewrote the meeting transcription
model:

    [stt]
    model = "base.en"   ->  "small.en"    approved
    [meeting]
    model = "tiny.en"   ->  "small.en"    not approved, not mentioned

That is the top proposal on a real corpus, so it is the most likely `--apply` to be run.

There were two config writers, and each was missing what the other had. `set_toml_key`
rendered arrays correctly and could not scope a section; `configedit.set_config_key`
scoped the section and rendered a list as a quoted Python repr —
`filler_words = "['um', 'uh']"` — which parses as a *string*, so `configcheck` reports
"should be a list" and falls back to the default, discarding an approved change. Nothing
passed it a list today, so that half was latent.

There is now one writer and it does both.

### Fixed — `mic-level --set` could report success and change nothing

`update_threshold_in_config` replaced a `vad_threshold` assignment **anywhere in the
file**. A key a user had put under the wrong section was rewritten instead of the real
one, and the command reported `updated vad_threshold = …` while
`[accessibility] vad_threshold` kept its previous value:

    [audio]
    vad_threshold = 0.09          ← rewritten, and dead: configcheck ignores it
    [accessibility]
    pre_speech_padding_ms = 300   ← the real setting, never touched

`configcheck` already prints *"[audio] vad_threshold: is not a known setting; ignored"*
about that line, so the mistake was visible to the system and edited anyway.

It lands where it hurts most: `yazses mic-level --set` is what the documentation
recommends when words are being dropped, so the user is already stuck, runs the suggested
fix, is told it worked, and dictation still fails. The adaptive retuner writes through the
same function.

The replacement is now scoped to the `[accessibility]` section; a key found elsewhere is
left alone and the real one is added. This also removes the latent version of the bug:
`[meeting]` already has `vad_backend` and `silero_threshold`, and a `[meeting]
vad_threshold` would have been clobbered by every `mic-level --set`.

### Fixed — the adaptive silence gate could lower itself for no benefit

`AdaptiveThreshold.suggest` promises *"a threshold that would have let the rejected bursts
through"*. It computed `max(loudest * safety_factor, min_threshold)` and returned it
whenever it was below the current gate — without checking that the floor had not raised it
back above the audio it was meant to rescue.

With a muted or dead microphone the bursts sit at the digital noise floor. Levels around
0.00002 against a floor of 0.0005 proposed **0.0005** — twenty-five times above the audio
it claimed to admit, so those bursts would still be discarded at the new gate.

The change bought nothing and cost something: a lower silence gate admits more room noise,
and near-silence reaching the model is answered with invented text.

This is exactly the case the class is careful about everywhere else — its own docstring
warns that the same symptom comes from a muted microphone, "where lowering the gate fixes
nothing and only makes the next failure noisier" — and the floor let it through anyway. A
proposal that would not admit the loudest rejected burst is now refused.

### Fixed — an acronym and a Title-Case word produced identical braille

`_encode_word` emitted one capital indicator whenever the first letter was upper case. In
UEB a single `⠠` capitalises **only the letter after it**; a word in capitals takes the
*capitals word indicator*, `⠠⠠`. So:

    "ABC"  ->  ⠠⠁⠃⠉
    "Abc"  ->  ⠠⠁⠃⠉      identical

A reader got "Abc" either way, on a refreshable display or an embossed page, with no way
to tell which was written. Acronyms are common in dictated text — "API", "NASA", "PDF" —
and this is output nobody sighted proofreads, which is why it stayed wrong.

"I" and "A" keep the single indicator: they are one letter, not a word in capitals.

Not fixed: a mixed-case word ("McDonald") still takes one leading indicator where UEB
marks each capital individually. That needs per-letter handling rather than a prefix, and
unlike the all-caps case it is visibly under-marked rather than silently ambiguous.

### Fixed — `yazses tune` offered to delete the word "this" from every dictation

`_propose_disfluency` counts words that appeared in a wrong transcript and not in the
user's correction, and proposes the frequent ones as filler words. It had no notion of
what can plausibly *be* a filler — and correcting a dictation removes ordinary words all
the time. "send **this** to Bob" corrected to "send **that** to Bob" makes "this" a
removed word; twice, and it is proposed. Applying it writes `this` into
`[filters.disfluency] filler_words`, and the filter then strips that word from everything
the user says.

On a real corpus the proposal was `okay, this, one`. It is now `okay`.

An ordinary function word is refused unless it is one a filler is plausibly drawn from —
"well" is both, and blocking it outright would stop a genuine filler being discovered. A
strict allow-list would be worse than the bug, since the point is to find a *personal*
verbal tic; the rule blocks the dangerous class while leaving discovery possible.

### Fixed — every voice command was a silent no-op in remote mode

`RemoteInjectorProxy` is the injector the daemon uses while forwarding to an SSH host, and
two of its three methods were stubs:

    def inject_backspaces(self, count): pass  # Not forwarded in v0.3.0
    def inject_key_sequence(self, keys): pass  # Not forwarded in v0.3.0

`commands/dispatch.py` routes everything that is **not** DICTATE through
`inject_key_sequence`, so "save", "copy", "paste" and "undo" reached that `pass` and
stopped. Dictation kept working, which is what made it invisible: the user says "save",
is watching the *remote* screen, and nothing happens and nothing is said.

It was never a missing capability — `remote/inject.py`, the injector on the remote host,
has implemented both all along. The agent's JSON-RPC dispatch simply had no method for
them, so there was no way to ask. It now accepts `keys` and `backspaces`, and the proxy
sends them.

An older agent answers `Method not found`, which the client already logs and survives, so
a new local YazSes against an old remote degrades to the previous behaviour rather than
failing. Empty sequences never reach the wire.

### Fixed — re-enrolling a meeting participant destroyed the first voiceprint in silence

`enroll_participant` writes to a path derived from the display name, with no existence
check, so:

    yazses meeting enroll <a> speaker_0 --name Alice
    yazses meeting enroll <b> speaker_1 --name Alice

replaced the first Alice's biometric voiceprint and printed the same success message
either way.

Replacing is legitimate — a longer or cleaner recording gives a better embedding — so it
is not blocked. Doing it silently is the problem: from inside YazSes a *second person
named Alice* and a *re-enrollment of the same Alice* look identical, and only one of those
is what the user meant. The data is biometric and was enrolled deliberately under an
explicit-consent policy (ADR-011/012), which is precisely the kind not to overwrite
without a word.

`yazses meeting enroll` now says when it replaced an existing voiceprint, and names the
file it replaced.

### Fixed — one brace in a summary threw away the whole meeting minutes

`_extract_json` pulls the JSON object out of an LLM reply by counting braces, and counted
them without tracking string context. The first `}` inside any *value* closed the object
early, `json.loads` failed on the fragment, and `{}` came back:

    {"summary": "the config needs a } here"}   ->  {}
    {"summary": "use { to open a block"}       ->  {}

Minutes of a technical meeting are exactly where a brace turns up in prose — a config
snippet, a code fragment, a bit of JSON read aloud — and the loss is silent, because
`_parse_minutes` turns `{}` into empty `Minutes`. Every field went, not just the summary:
decisions and action items with it, and `yazses meeting notes` wrote a blank page and
reported nothing.

The scanner now tracks string context and backslash escapes. Fenced replies, surrounding
prose and nested objects still work, and genuinely unparseable output still yields `{}`
rather than a guess.

This is the default path: the grammar-constrained alternative (`[meeting] notes_grammar`)
is optional.

### Fixed — a crashed meeting's recovery transcript was unreadable, and unmentioned

`session.py` streams every finalized live line to `live.jsonl` throughout a meeting, and
`append_live_line` says why: *"so a daemon crash mid-meeting still leaves a partial
transcript on disk"*. Both ends of that were broken.

**The reader could not read it.** `read_live_lines` decoded with strict UTF-8, outside its
`try`. A write cut in the middle of a multi-byte character — exactly how the file gets
damaged, since the premise is that the process died mid-write — raised `UnicodeDecodeError`
for the **whole file**, discarding every complete line before the tear along with it. It
now decodes with `errors="replace"`, and the torn line is dropped by the JSON guard that
already handled truncated lines.

**Nothing mentioned it.** `read_live_lines` had no caller anywhere in `src/`, and
`yazses meeting list` — the only place `recoverable` would be seen — computed the flag and
printed the meeting without it. So an hour-long meeting cut short by a crash left its
partial transcript on disk with nothing in the product acknowledging it existed. The
listing now flags it and says how many lines are recoverable, and from where.

Whether a dedicated `meeting recover` command should exist is a larger question left open;
this makes the data findable, which it was not.

### Fixed — `srt`/`vtt` merged two speakers into one caption and dropped their names

`_render_subtitles` threw the speaker away and segmented on silence and line length
alone, so a diarized recording produced:

    00:00:00,000 --> 00:00:04,000
    hello there hi          ← Alice's words and Bob's, together, unattributed

Two faults, and the second is the serious one. The missing label is a loss; the **merge**
makes the caption assert something untrue — that one person said all of it — and a
subtitle file is read by people who were not in the room and cannot tell.

`render.py`'s own docstring names this exact failure as the thing to avoid ("never
silently dropped — WhisperX's documented bug"). The promise was kept for `txt`, `md` and
`json`, and broken for the two formats most likely to be handed to someone else.

Captions are now segmented per contiguous speaker run, so one can never straddle a speaker
change, and each carries the display name when the recording is diarized. Undiarized
output is unchanged — there is no speaker to name.

### Fixed — `transcribe --rename` for a speaker who isn't there did nothing, silently

`resolve_names` returns a map documented as `{canonical_speaker_id: display_name}`, and it
copied every rename into it without checking the speaker exists. A mistyped or
out-of-range id — `--rename speaker_5=Bob` on a two-speaker file, or `Speaker_0` with the
wrong case — added a key naming nobody, which no renderer looks up.

The rename did nothing and reported nothing, so the transcript came back saying
"Speaker 1" and the user was left to work out whether diarization had failed, the syntax
was wrong, or they had miscounted the speakers.

The map now contains only speakers that are in the recording, and `yazses transcribe` says
which `--rename` keys matched nothing — listing the ids the recording *does* have, which
is the thing the user needs and cannot otherwise discover without re-running.

### Fixed — diarized transcripts attributed words to the wrong speaker

`_nearest_speaker` filled an unmatched word from the nearest turn by the distance between
**midpoints**, and compared that to `fill_nearest_max` — whose name and docstring both
promise "within N **seconds**" of the turn. Those agree only when turns are short. Meeting
turns are not, and two wrong answers followed on ordinary input:

* **The same gap, opposite outcomes.** A word 0.1 s after a 100-second turn was *dropped*
  (its midpoint is 50 s away), while the identical 0.1 s gap after a 0.5-second turn was
  assigned. Whether a word got a speaker depended on how long that speaker had been
  talking.
* **The wrong speaker.** A word 0.2 s after speaker A's turn and 0.8 s before speaker B's
  was given to **B**, because B's turn is short and its midpoint close. Putting words in
  the wrong person's mouth is the one error a diarized transcript must not make quietly —
  it reads as fact.

Distance is now the real gap to the turn, zero when they touch. Both existing guards are
unchanged: the `fill_nearest_max` cap still refuses a distant turn, and a word shorter
than `backchannel_max` is still left unassigned rather than stolen by a neighbour. Ties
break to the earliest-starting turn, matching how the overlap branch already breaks its
own.

Affects `yazses transcribe --diarize` and Meeting Mode, which share these cores.

### Fixed — self-repair deleted a word out of ordinary speech

`_EDIT_TERMS` includes a bare `i mean`, and the rule **drops the word before the editing
term**. "I mean" is one of the commonest phrases in English, so:

    that is not what I mean at all    ->  that is not at all
    this is exactly what I mean       ->  (the preceding word deleted)

Real dictation, a word removed silently. This is the same shape as a defect this project
has already had once in the disfluency filter's self-correction triggers; the lesson had
not reached `selfrepair`.

Only the **bare** term is now guarded, and only by the word in front of it: "what",
"know", "how" and the pronouns, which make `<X> I mean` an ordinary construction rather
than a correction. The explicit markers — "no I mean", "make that", "or rather", "no make
it" — stay unrestricted, so the feature's advertised example (`email Sarah no I mean Sara`
→ `email Sara`) and chained repairs are untouched, and `meet at three I mean four` still
repairs.

The asymmetry decides the ambiguous case, as it does for the ITN email guard: a missed
repair leaves the words as spoken and the user reads them; a false one deletes a word
silently.

### Fixed — dictating "look at the dot com boom" produced "look@the.com boom"

`_EMAIL_RE` matches `<words> at <words with a spoken dot>`, and its comment justifies the
single guard it had: *"the domain MUST contain a spoken 'dot' so a plain 'at' in ordinary
speech ('meet at noon') never matches."* That does stop "meet at noon", and nothing about
the far commoner shape — an ordinary sentence containing *"at &lt;word&gt; dot &lt;word&gt;"*:

    look at the dot com boom          ->  look@the.com boom
    point at the dot on the screen    ->  point@the.on the screen
    meet me at the dot matrix printer ->  meet me@the.matrix printer

Eight of eight realistic sentences were rewritten into email addresses mid-prose.

Two further conditions now apply, both satisfied by every spoken address and rarely by
English: the domain's **last** label must be a real TLD, and its **first** must not be an
article. Either alone is insufficient — "look at the dot com boom" ends in a genuine TLD,
and "at company dot headquarters" opens with a real label — so both are checked.

When the check fails the words are left exactly as spoken. A missed address costs one
hand-typed line; a false one silently corrupts a sentence the user dictated and may never
re-read.

Real addresses are unaffected: `john dot doe at gmail dot com`, `me at company dot co dot
uk` and `first dot last at university dot edu` all still convert.

### Fixed — `yazses acronyms expand` corrupted a document when run twice

`expand_document` writes an acronym's first use as `Full Name (ACR)`. It did not notice
when the text already said that, so it expanded the `ACR` inside its own parentheses, and
each further run nested one level deeper:

    once   The Application Programming Interface (API) is stable.
    twice  The Application Programming Interface (Application Programming Interface (API)) is stable.

Running the command again after editing a document is the ordinary thing to do, and
nothing warned.

The repair was already in the module: `AcronymState.observe` is documented as *"Learn
'Full Name (ACR)' definitions already present in text (marks them expanded)"* — written
for exactly this and never called. It is called now, so the rule for "already expanded"
stays in one place instead of becoming a second, subtly different check.

### Fixed — a failure notification stayed on screen forever, with nothing to click

Both notification call sites sent **every** failure at `urgency="critical"`, and the
freedesktop spec exempts that level from expiry on purpose: a critical alert must not be
missed, so the server keeps it until the user acts. Applied to a dictation burst that
failed to inject — transient, already finished, nothing to decide — that produced a
pop-up which outranked everything else on the desktop and waited for a click it had no
button to receive. It is the visible half of the orphaned-`notify-send` defect fixed in
2.28.0: that one leaked the process, this one leaves the pop-up.

The level now follows whether the toast is **answerable**. A recognised fault already
carries the command that fixes it, so it goes out at `normal` urgency with a timeout and
clears itself like any other notification. Only the unrecognised one — the toast offering
**[Prepare a bug report]** — stays `critical` and persistent, because it is asking a
question and `--wait` needs it to survive until you answer.

The urgency is the load-bearing half: GNOME Shell applies its own timing and largely
ignores a requested duration, while KDE and dunst honour it, so both are sent. A guard
fails the build if either call site hardcodes an urgency again instead of going through
`notify.toast_policy()` — one literal in one place is how the two paths drift apart.

### Fixed — the hallucination guard missed a loop that ends mid-phrase

`is_repetition_loop` required the repeated unit to tile the text **exactly**
(`if n % unit != 0: continue`). Real loops rarely oblige: the decoder stops at a segment
or token boundary, so the last repeat is usually cut short. Taken from a live corpus,
this was **typed into the editor**:

    each machete de shiramasun ×3 + "each"

Thirteen words, and thirteen is prime — no unit divides it, so a textbook degenerate loop
scored as ordinary speech and reached the injector.

The unit may now be interrupted on its last repeat, provided the remainder is a **prefix
of the unit** — which is what a cut-off repeat looks like. A tail that is anything else
means the loop ended and speech resumed, so `the the the cat sat on the mat` is still left
alone, as is `very very very good`.

`[hallucination] enabled` remains **false** by default; this changes what the guard
detects when it is on, not whether it is on.

Found by running `yazses transcribe` on a real 1.5-second clip from the corpus: it
produced **nothing**, while the daemon's stored transcript for the same audio was that
loop. Isolating the difference showed the pre-speech padding is what provokes it —
`raw → ''`, `+300 ms of leading silence → "Each machine they should have us in it."`. The
padding that stops the first word being clipped can also turn near-silence into fabricated
text, and the guard built to catch the result was missing its commonest shape.

### Fixed — a destructive-command pattern that could never fire

`assess_command` lower-cases a dictated command before matching, and `_DANGEROUS`
contained a pattern with a literal uppercase flag:

    (r"\bchmod\s+-R\s+0*777\b", "recursive world-writable")

Against lower-cased input that can never match, so `chmod -R 777 /` was classified
`safe` — and here `safe` does not mean "reported as low risk", it means the command is
typed straight through with **no confirmation**. A guard entry that cannot fire is worse
than an absent one, because it reads as coverage.

The same run found a second gap inside the guard's own declared category: `rm
--recursive --force /data` is the identical command to `rm -rf /data`, and both `rm`
patterns read only the short flag cluster, so it too was `safe`.

Both fixed, plus two structural guards: no pattern may contain a literal uppercase letter
(the mechanism), and every pattern must match its own worked example (the coverage), so a
new entry cannot be added and quietly do nothing.

### Fixed — `redact_patterns` scrubbed four of the six stored text fields

`[learning] redact_patterns` is documented as *"Regexes scrubbed from text before
storage"*. It was applied by `CorpusWriter` over a hand-written four-field tuple, but the
store persists **six**, and three of its methods write text without going near the
writer: `mark_wrong`, `update_correction_for` and `set_retx`.

So `correction_text` and `retx_text` were stored unscrubbed. `retx_text` is the one that
matters — it is a **re-transcription of the same audio** the patterns were added to
protect, so a user who scrubbed a card number or a password out of `raw_text` had
`yazses tune --retranscribe` write it straight back into the corpus.

The corpus is encrypted at rest and machine-bound, so this was never an exposure off the
machine (ADR-011 holds). It was a failure of the narrower promise `redact_patterns`
makes: that certain content is never stored at all.

Redaction now lives at `CorpusStore._enc`, the single point where text becomes a stored
blob, so "encrypted" and "redacted" are the same set **by construction** rather than by
two lists agreeing. The writer still scrubs before enqueuing so a secret does not sit in
an in-memory queue, but it now scrubs every string value rather than a listed subset —
the subset being exactly what failed. `yazses tune` passes the patterns when it opens the
store.

Existing corpora are not rewritten; rows already stored keep whatever they hold.

### Fixed — `yazses audio use` could write a config.toml that does not parse

`set_config_key` had **two** renderings of a value and only one escaped anything. The
inferred path escaped backslashes and quotes; the explicit `quote=True` branch
interpolated raw — and that is the branch `yazses audio use` and the settings window
take. A microphone named `My "Best" Mic` produced:

    device = "My "Best" Mic"

That is not a contained failure. An unparseable `config.toml` makes `configcheck` fall
back to *"could not be read; using defaults throughout"*, so **every** setting the user
had is silently reset by an unrelated one-word command. Neither renderer handled a
newline, which is illegal inside a TOML basic string and does the same thing, and a
backslash was quietly corrupted — `path\to\thing` round-tripped with a real tab in it,
because `\t` was read back as an escape.

Both paths now go through one `quote_toml_string`, which escapes the full TOML basic
string set and emits `\uXXXX` for control characters. The settings window still
collapses newlines in `[stt] initial_prompt` before calling — defence in depth — but it
is no longer the only thing standing between a pasted two-line prompt and a wiped
`[stt]` section.

### Fixed — a negative `vad_threshold` was type-correct, catastrophic, and reported valid

`configcheck` validated **types**, and `doctor` reported the result as *"Config validity:
every setting has the expected type"*. So this loaded with **zero problems**:

    [accessibility]
    vad_threshold = -5.0
    pre_speech_padding_ms = -900

`is_silent_calibrated` is `mean(abs(audio)) < vad_threshold`, which against a negative
threshold is **never true** — so nothing is ever discarded as silence, and every burst,
including the ones where nobody spoke, reaches the model to hallucinate on. The user who
ran `doctor` to ask whether their config was good was told it was.

A numeric setting can no longer be negative unless it is genuinely signed. Which is
which is **derived from the shipped default**, not from a hand-maintained list: a setting
whose own default is >= 0 is a magnitude (a duration, a size, a count, an RMS threshold),
while `[hallucination] logprob_threshold`, `[reask] threshold` and `[whispermode]
tilt_min` ship negative defaults because they are log-probabilities and signed measures,
and keep accepting negatives. A new signed setting brings its own permission with it.

Rejected values fall back to the default and are reported like every other config
problem, so `doctor` and the daemon's startup listing both show them. The validity check
now says "every setting is a usable value", which is what it verifies.

### Fixed — `yazses doctor` printed two different checks both called "Microphone"

    [OK] Microphone: ok
    ...
    [OK] Microphone: OS default: default → Raptor Lake-P/U/H cAVS Digital Microphone

Two questions under one name: *can a microphone be reached at all* (permission/hardware)
and *which device will be used* (config summary). `doctor` output is what people paste
into issues, so "Microphone failed" was unanswerable without asking which one.

The config-summary row is now **Input device**, in both its pinned and unpinned branches.

### Fixed — `yazses reflow` cut "Firstly" into "ly", and never stripped a filler

Two defects in the command whose stated purpose is turning "a long rambling monologue"
into an outline.

`_BULLET_MARKERS` lists "first" before "firstly" and "second" before "secondly", and the
strip loop broke on the first match — so the rest of the longer word stayed in the
bullet:

    "Firstly we fix the tray."   ->  "- ly we fix the tray"
    "Secondly we ship it."       ->  "- ly we ship it"

Three of the commonest spoken outline markers each produced nonsense in the text the user
keeps. Matching is now longest-first — the same rule `yazses case` needs for
"snake"/"snake case" and `gitvoice` for its separators.

Second, only ordering words were ever stripped, so the single commonest thing in a
rambling monologue survived into the outline: *"Um we should fix the tray"*, *"So
basically the icon dies"*. Leading fillers are now stripped too, sourced from
`DisfluencyConfig.filler_words` — the list the dictation filter already uses — rather
than a second copy that would drift from it. Only the sentence-initial extras ("so",
"well", "right", "basically") are local, because mid-sentence those are ordinary words
and must stay.

Stripping repeats, because speech stacks markers: *"so um basically I need to update the
docs"* opens with three and now yields `- [ ] I need to update the docs`.

### Fixed — none of `yazses screenplay`'s documented forms worked when spoken

The command exists, in its own words, for "drafting a script by voice". All three forms
it recognises required punctuation no speech model emits — a colon, a comma, and a pair
of parentheses:

    scene: interior coffee shop, day     Alice (character) hello     transition: cut to

Said aloud, none matched, and `to_fountain` falls through to "anything else becomes an
action line" — so the raw words went into the screenplay, silently:

    "scene interior coffee shop day"  ->  scene interior coffee shop day

Every separator is now optional. `scene` and `transition` are anchored on a distinctive
keyword, so dropping the colon costs nothing. `(character)` needed more care: bare
"character" is an ordinary word, so the parenthesis-free form is read as a cue only when
the preceding text looks like a name — at most three words, not opening with a
determiner. `the character walks in` stays an action line, and the parenthesised form
stays exact.

This was the third instance of one shape in a single audit, after the `gitvoice` branch
separators and `yazses case`'s mandatory colon: the voice path requiring a character the
voice cannot produce.

### Fixed — `yazses case` required a colon you cannot dictate

The documented spoken form is *"make this snake case: …"*, and the CLI stripped the
directive with `if ":" in src: payload = src.split(":", 1)[1]`. Said aloud there is no
colon, so the directive was recased along with the text — and the command answered
confidently rather than refusing:

    make this snake case: hello world  ->  hello_world                       ✓
    make this snake case hello world   ->  make_this_snake_case_hello_world  ✗

A plausible wrong answer, which is precisely the failure `gitvoice` avoids by design.

The directive is now located by its style phrase and the remainder taken as the payload,
so the colon is optional. Trailing forms work too (*"hello world in snake case"*), and
the payload is sliced from the original string rather than the lower-cased copy used for
matching, so `make this snake case MyThing` still yields `my_thing` instead of losing its
word boundaries first.

### Added — spoken separators in branch names (`dash`, `hyphen`, `underscore`, `dot`)

`feature/login` and `fix-tray-crash` are both ordinary branch conventions, and neither
can be *dictated* — nothing turns the silence between two words into a `/` or a `-`, so
the speaker says the separator. Only `slash` was understood:

    create branch feature slash login   ->  git checkout -b feature/login   ✓
    create branch feature dash login    ->  Could not parse a git command.  ✗

which put the hyphenated half of real branch names out of reach in a voice-first
product. The refusal even advertised `'create branch …'` — the form it had just
rejected.

The substitution also existed twice, once in `ref_src_for_push` and once beside the
branch verbs, and both copies handled only `slash`. Both now call one `despeak_ref`, and
the tests cross every separator against every ref-reading verb, so a separator only one
path honours fails in CI rather than in a terminal.

Applied only where a ref is read: `commit with message fix the dash in the title` keeps
its word.

### Fixed — `yazses tune` proposed priming Whisper with its own hallucinations

Run against a real 1,617-event corpus, the top vocabulary proposal — the one `--apply`
offers to write into `[stt] initial_prompt` — was:

    for you thanks watching these cube assess within aspects can needed yasas grom
    two both and referees finished one etc why

Two defects in twenty-one terms.

**Stopwords.** Eleven are function words. `initial_prompt` is a bounded budget (the
decoder sees only the last ~224 tokens) and Whisper already knows "for" and "and", so
each one displaced a term that would have helped. The miner's rule — *in the correction,
absent from the live transcript* — catches them because rephrasing changes which function
words appear, not because the model cannot hear them.

**Hallucination feedback, the serious one.** `for`, `you`, `thanks`, `watching` are the
words of *"Thank you for watching"* — the silence hallucination YazSes ships a guard to
delete. The loop: a clip decodes to the ghost phrase, the user re-dictates, the
re-dictation lacks those words, the miner reads them as vocabulary the model keeps
missing, and priming them biases the decoder **toward** the phrase. The product would
have been tuning itself into the failure it guards against.

Mined terms are now filtered against a stopword list and against `ghost_words()`, derived
from `_GHOST_PHRASES` itself rather than copied — a copy drifts, and the two disagreeing
silently is this bug one layer up. On the same corpus the proposal went from 21 terms to
the 8 real ones.

Not fixed, and worth knowing: `yasas` and `grom` survive. They are mis-hearings of
"YazSes" and "from" that arrived through the re-transcribed text, so the ground truth
itself is wrong — a limitation of re-transcription as an oracle, not something a word
list can settle.

### Fixed — the tray supervisor threw away every reason the tray died

Both places that launch the tray passed `stderr=subprocess.DEVNULL`. The tray is a
separate process, so everything it printed on the way down was discarded — a real
daemon log showed four relaunches in one evening, three inside ninety seconds, with no
indication of the cause anywhere.

The give-up branch documented the omission without noticing it: *"tray died 5 times;
not relaunching again. Start it manually with `yazses tray` to see the error it
prints."* That advice exists only because the error was thrown away, and it asks the
user to reproduce by hand a failure the daemon had already watched happen five times.

It matters past the terminal too: the daemon log is what `yazses report` attaches to an
issue, so "the tray keeps dying" was reportable only without evidence.

The tray's stderr is now captured (truncated per launch, so it answers why the tray that
just died died, not the previous six) and logged with each relaunch and with the give-up
message. If the capture file cannot be opened the launch falls back to `DEVNULL` — a
tray that starts without diagnostics beats diagnostics that stop the tray starting.

### Fixed — Apply restarted the daemon while it was still downloading the packages

`_on_apply` starts the optional-dependency install on a background thread ("this can
take a few minutes") and then, without waiting for it, offers the restart. Enabling a
capability with heavy extras — `stt-parakeet`, `gaze` — therefore restarted the daemon
*before its packages existed*, so it came back up with the capability switched **on** in
config and its import still failing. The window said it applied.

`_run_restart` is also a synchronous `subprocess.run(..., timeout=90)` on the **UI
thread**, so accepting that prompt froze the window for up to a minute and a half while
the install thread streamed progress into it — and a frozen window is what a desktop
offers to force-close.

The restart is now held until the install finishes, and offered from
`_on_install_finished` — including when packages failed, since the rest of the change
did land and still needs a restart. A change that downloads nothing still restarts
immediately, as before.

### Fixed — `yazses verify` certified a chain the daemon discards

Found by running the command in a quiet room with nobody speaking. Ambient noise cleared
the silence gate, the model answered near-silence, and the report ended with
**"✓ Dictation works end to end on this machine."**

The daemon does not type what the model returns — it types what survives `clean_text`,
and a burst that cleans to nothing is discarded before injection. `verify` tested the
**raw** string, so `[BLANK_AUDIO]`, the commonest thing Whisper emits for silence, is
non-empty, printed as `heard "[BLANK_AUDIO]"`, and passed:

| | daemon | `yazses verify` (before) |
|---|---|---|
| model returns `[BLANK_AUDIO]` | cleans to `""`, discards, types nothing | ✓ works end to end |

A muted microphone passed the one check whose entire job is to name the broken link,
while the module's own docstring claimed it "runs the real chain end to end". It ran the
chain minus the step that decides whether anything gets typed.

`verify` now applies the cleaner, injects the cleaned string rather than the raw one, and
when cleaning empties a transcript it says the model heard silence and points at the
microphone — not at `[stt] model`, which would send you to download a larger model to
fix a muted input device.

## [2.28.0] — 2026-08-18

### Fixed — an actionable notification outlived the process that raised it, forever

A toast offering **[Prepare a bug report]** runs `notify-send --wait`, which blocks
until someone clicks it, and `--urgency critical` means it never expires on its own.
That wait ran on a **daemon** thread, and its 120-second cap lived inside that thread —
so it only ever fired in a process that stayed alive long enough to reach it. In the
long-lived daemon it did; in every short-lived process it could not. A CLI command,
`yazses verify`, or one `pytest` run exits in seconds, the daemon thread is abandoned
without unwinding, its `except TimeoutExpired` never runs, nobody calls `kill()`, and
the pop-up is reparented to `systemd --user` and stays on the desktop until the session
ends. A machine running the suite on a loop accumulated 33 of them in 75 minutes, each
describing an injection failure that had never happened.

In-flight toasts are now tracked and killed at interpreter exit, so one dies with
whatever raised it; a toast started as the interpreter goes down is not started at all,
rather than spawned into the gap after the shutdown hook stopped looking.

Separately, the four daemon-level tests that drive a deliberately failing injection or
capture were popping *real* pop-ups on the developer's screen. None of them was written
wrong — three predate `_report_failure` entirely, and adding it dropped a `notify()`
into `except` blocks they had been exercising all along, so the side effect arrived
without a single test changing. The suite is now hermetic against the notifier at the
source, the way it already is against the user's real log file.

### Added — one guard for every link YazSes shows you

A URL in a shipped string is compiled into the `.exe`, the `.dmg`, the snap and the
`.deb`. If it 404s, the person who finds out is the user, alone, at the moment they
were already stuck.

Three instances of that shape landed in three days — a diagnosis module linking three
how-to pages that have never existed, a bundle reading `yazses.log` where the file is
`daemon.log`, and a tooltip naming `yazses models` where the command is
`yazses model list`. Each got a guard afterwards, one per module. This is the general
one: every docs link in a user-visible string must resolve to a real page, must end
`.html` (the site sets `use_directory_urls: false`, so `<name>/` is a 404), and any
link to a repo *named* yazses must be under `MSKazemi`.

It reads **f-strings**, which is how the diagnosis module builds every URL. Without
that the guard was vacuous for the very file it was written to generalise: an
`ast.Constant` scan sees only the fragment `"/page.html"`, which carries no site
prefix and matches nothing. Docstrings are excluded — they are developer-facing, and
holding them to a user-visible standard produces noise rather than findings.

### Fixed — a flaky test that could fail the whole gate at random

`test_notifier_available_uses_which` failed once in a full run, then passed alone and
on the next run. The file captured the real `notifier_available` at **import time**, on
the stated assumption that imports happen before the autouse fixture that stubs it —
and the failure was `assert False is True`, exactly what that stub returns. The
mechanism was not pinned down, so the assumption was removed rather than reasoned
about: the module is now executed into a private namespace that no patch of the
installed one can reach.

### Fixed — the clipboard list and the spoken ordinals pointed opposite ways

`yazses cliphistory list` prints a newest-first numbered list — `1. DDD … 4. AAA` —
while `recall "the first one"` returned `AAA`, i.e. #4, and `"the last one"` returned
`DDD`, i.e. #1.

The resolver is **not** changed, and that is the point: *"the first thing I copied"*
meaning the oldest is the right reading of that sentence and is tested as such, while
the help documents *"the second one"* as entry #2, which is positional. Both readings
are correct English and they point opposite ways — the ambiguity is in the language.

What was fixable is the surface that implied a contradiction and never stated the
rule. The list now names its ends (`1. DDD ← most recent`, `4. AAA ← oldest`), a
single entry gets no label because it is both, and `recall --help` says which words
mean which end.

### Fixed — `gitvoice` threw away the branch you named, on `push` alone

Every ref-taking rule in the spoken-git grammar captures its ref — except `push`.
`push to main` rendered a bare `git push`, which pushes the **current** branch to its
upstream, so naming a branch while standing on a different one pushed the other one.
`force push to main` did it destructively. The module's own comment already describes
this class of defect for `delete branch feature slash login`; it was still live in the
command where it costs the most.

`push to main` now renders `git push origin main`, an explicit remote is honoured
(`push to upstream develop`), a bare `push` stays bare, and `feature slash login`
becomes `feature/login` here as everywhere else. Assuming `origin` when only a branch
is named is deliberate: on a repo whose remote is called something else it stops with
*"'origin' does not appear to be a git repository"* and nothing happens — a visible
wrong guess beats an invisible right-looking one.

The confirm gate and undo hint still recognise the longer argv, which is checked, since
a safety gate that stopped matching once the command gained a ref would be worse than
the bug.

### Fixed — `shellpipe` searched for the word "for"

The stage grammar listed `search for` but not `grep for`, so the most natural phrasing
put the connective **into the pattern**: "grep for error" rendered `grep 'for error'`,
which matches nothing, and "find lines matching error" rendered
`grep 'lines matching error'`. Only the stilted "grep error" worked. Connecting words
are now part of the grammar — and "grep forbidden" still searches for `forbidden`,
because the connective must be followed by whitespace to count.

### Fixed — a bug report could carry your personal dictionary

`yazses report` promises *"your dictated text is never in it"*, and the log honours
that by recording word counts rather than words. The **config** section did not.

Found by auditing a real bundle, which was clean — but only because that machine
has no `[stt]` section, and `yazses tune` proposes writing one. Given a realistic
value, the old redaction returned:

```
"<redacted> Seyedkazemi Ardebili, <redacted>.seyedkazemi@gmail.com, KubeIntellect…"
```

The account name matched and nothing else did. The surname, the email domain, the
employer and two project names travelled into the report **wearing a `<redacted>`
marker** — which is worse than no redaction at all, because it invites the reader to
conclude the field was cleaned. Partial redaction of free text is a false negative
with a badge on.

Two rules close it. Known prose keys (`[stt] initial_prompt`,
`[filters.disfluency] llm_system_prompt`) are replaced wholesale rather than
filtered. And **every list and dict value is summarised by size**: those passed
through *verbatim* before, and they are exactly where user prose lives — the snippet
table, the per-app profile map, and `[learning] redact_patterns`, which is the
subtlest of the three since those regexes describe what the user considers secret.

The size is kept, because an empty vocabulary and a 400-term one are a real
difference to whoever reads the report, and a count identifies nobody.

### Added — `yazses tune --limit N`, and an estimate instead of "a while"

`tune` had two speeds: re-transcribe the whole corpus, or skip the pass entirely
with `--no-retranscribe` — which drops the step that finds the actual
mis-transcriptions. On a real corpus that is ~1,600 clips through `small.en` on CPU;
a run left going for ten minutes had not finished.

`retranscribe(limit=)` had existed the whole time, **called by nothing, and
referenced by no test**. Wiring it as written would have shipped the wrong feature:
`store.events()` is `ORDER BY id`, so a limit took the **oldest** clips — the least
relevant half, recorded with a model, microphone, threshold and vocabulary the user
may since have changed. It now takes the most recent N, which is the half that
reflects what dictation does today.

The progress line also carries a time estimate once a rate can be measured. "A large
corpus can take a while" is honest and useless: an hour is a decision — run it
overnight, or use `--limit` — and "a while" is not. The estimate is deliberately
coarse (rounded to five minutes above the hour), because the rate wanders with clip
length and "~52 min" would claim a precision the measurement does not have; it stays
silent rather than guessing before the first clips are done, and on the final tick.

### Fixed — "speaker labels unavailable" recommended a 45 MB download that fixes nothing

`yazses meeting status` computed *why* speaker labels were unavailable — correctly
distinguishing "the Python package is missing" from "the model files are missing" —
and then printed the same remedy for both: `yazses transcribe --download-models`.
With the extra missing, that fetches ~45 MB, changes nothing (the absent thing is an
importable module), and returns the identical message. The daemon's `meeting start`
warning named both remedies unconditionally, which is better but still asks for a
step that cannot be acted on yet.

Both now go through one `diarization_advice()`, which names **the next action, not
the whole path**: with the extra missing, `yazses features enable meeting` is the one
command, and the message says the models follow. Mentioning a second step the user
cannot take yet is how the wrong one gets attempted first.

Two cases it now handles that neither surface did: a `pyannote` backend is never told
to "run" a download, because its pipeline is a *gated* repo and a missing cache may
mean the terms were never accepted — that is only knowable by trying; and
`[meeting] diarize = true` with a backend that cannot diarize is reported as the
config fault it is, rather than sending someone to install something that would change
nothing.

### Fixed — the Settings window told you to run a command that does not exist

The model dropdown's tooltip said *"Same list as `yazses models`"*, and
`docs/settings-gui.md` repeated it. The command is **`yazses model list`**;
`yazses models` exits 2 with *"No such command"*. Two surfaces, one invented name,
and every test passed — because nothing compared the strings we ship against the
CLI we ship.

There is now a guard for that direction. `test_cli_reference_covers_every_command`
already asked whether each shipped command is *documented*; this asks whether each
command we *name* exists. The second failure is worse: an undocumented command is a
gap, while advice naming a command that does not exist is a dead end handed to
someone who is already stuck. It is the third instance in three days of the same
shape — strings that are only wrong at the moment a user acts on them, after doc
links to pages that never existed and a bundle reading the wrong log filename.

The guard keys on **backticked** invocations. A first version matched `yazses`
anywhere and returned thirty-odd false positives — `cd yazses`,
`pipx install yazses`, `sudo snap refresh yazses`, the repo's own name in a clone
URL — against one real defect, which is a guard nobody keeps. A backtick is the mark
that means "type this". `docs/releases/` and `docs/research/` are excluded for
reasons about what those pages are: release notes describe what a past version
shipped, and research pages pose open questions where naming something that does not
exist yet is the point.

### Fixed — two defects in yesterday's error reporting, found by auditing a real machine

A nine-hour session on a live daemon, audited rather than reasoned about, and both
findings are in code added the same day.

**The classifier missed the only failure actually happening.** The single warning
that machine produced all day — five times — was `Error querying device -1`, and it
fell straight through to the generic *"an unexpected error stopped that from
working"*. PortAudio index −1 is the default device, so this is the default failing
to resolve, which on PipeWire/ALSA happens while it is being switched. It now says
so, and says that pinning a microphone with `yazses audio use <name>` stops a change
of default from interrupting dictation. The rule set had been written from
plausible-looking error text; the observed strings now have their own test, keyed to
where each was seen.

**The issue-body limit bounded the wrong quantity.** The body travels as a URL query
parameter, and percent-encoding expands it — ~1.27x for a log line, ~1.45x for a
Markdown heading, 3x for punctuation-dense text, and 9x for non-Latin script, where
each UTF-8 byte becomes three characters. A 6000-character body, comfortably "within
the limit", produced a **12,972-character URL** on a real report from this machine.
Past roughly 8 kB the user lands on an *empty* issue form, so the failure is total
rather than partial. The trimming loop now measures the encoded length, and the tests
assert on the whole URL across three alphabets rather than on the raw body.

### Fixed — the Snap Store showed a different logo from every other surface

The icon in the Snap Store listing, and in the app grid of every snap install, was
**not the YazSes mark**. It was a white square with a blue speech-bubble outline, a
navy Y and a violet-to-cyan waveform — against the purple-gradient badge used by the
website favicon, the Windows `.exe`, the macOS `.app`, the `.deb`, and both tray
badges. Two logos, one product, and the wrong one on the primary Linux channel.

The cause is structural rather than a mistake anyone made. `scripts/gen-icons.py` is
documented as the one renderer for the mark, and it owned exactly two outputs: the
`.ico` and the `.icns`. The Linux icons were shipped by `build-deb.sh` and
`snapcraft.yaml` and regenerated by **nothing**, so whatever was drawn by hand in June
stayed. Measured, the `.deb` PNGs had quietly drifted too — the right design from an
older `render_mark`, differing on 0.6–5.9% of pixels once composited (max delta
30/255): invisible in use, and never going to correct itself.

The generator now owns every shipped raster icon, `snap/gui/yazses.svg` carries the
canonical drawing rather than the superseded one, and `make icons` redraws the set. A
test reads the size list out of `build-deb.sh`'s own shell loop and the `icon:` line
out of `snapcraft.yaml`, so a channel that starts shipping a new icon fails the build
until the generator learns about it — in either direction, including a size the `.deb`
wants that the generator does not produce.

`--check` now compares **decoded pixels rather than file bytes**. PNG output is not
reproducible across platforms — zlib version and Pillow build change the compressed
stream for pixel-identical input — which `tests/test_icon_assets.py` had already
learned by turning the Windows and macOS CI legs red on assets that were correct.
Byte comparison would have worked by accident while `--check` stayed a local command,
and broken for whoever wired it into CI.

⚠ If the speech-bubble drawing was the intended direction, the fix runs the other way
and costs six surfaces instead of one — say so and it will be redone that way.

### Added — when something breaks, YazSes now tells you, and says what to do

The gap this closes is not detection. The daemon already caught these failures — it
just told nobody. A microphone that will not open was caught, logged, and written to
`last_error`, and then the state went back to `IDLE`, which the tray paints **idle
blue**. So you held the key, spoke a sentence, nothing was typed, and every surface
you could see reported a healthy daemon. A pipeline error did the same.

`system/diagnosis.py` turns a caught failure into a title, a plain-English cause and
a **concrete next step** — "Another program is using your microphone; close it, or
pick a different one with `yazses audio devices`", not "Microphone unavailable".
Wired into the three paths that were silent: capture, the transcribe/inject pipeline,
and a failed meeting start.

Three rules it holds to. **Every failure gets a diagnosis, including unrecognised
ones** — a classifier that returned nothing for the unexpected case would go quiet
exactly when a user most needs a message, and "unexpected" is the normal state of a
bug. **A diagnosis is advice, never a decision** — nothing here changes what the
daemon does, so a wrong guess costs a misleading sentence, not a working feature. And
any given fault is announced **at most once every five minutes**: a broken microphone
fails on every burst, and five identical toasts teach people to dismiss YazSes
notifications, which costs more than the suppressed repeats.

### Added — "Prepare a bug report", which prepares and does not report

ADR-v2-132's option (b), now built. When YazSes **cannot identify** a failure, the
notification offers a button that assembles the redacted diagnostic bundle and opens
GitHub's issue form **pre-filled**. You read it, in GitHub's own UI, under your own
account, and press submit yourself.

**YazSes sends nothing.** The browser makes the request, so this adds no outbound path
— ADR-019's egress inventory is unchanged and its guard was not edited, which is the
condition the ADR set for accepting this option at all.

That guard did fire once, on `from urllib.parse import urlencode`: its root list
contains `urllib`, deliberately conservatively, even though `urllib.parse` cannot open
a socket. Both obvious responses were wrong — registering `report.py` in the egress
inventory would claim a module that sends nothing sends something, and relaxing the
guard would trade a real protection for convenience in the one file whose first line
is *"Nothing is ever sent anywhere"*. The percent-encoder is therefore written by hand
and pinned against `urllib.parse.quote` in the tests, which sit outside the scanned
tree.

The offer is gated on YazSes not recognising the fault, rather than on the fault
repeating (which is what the ADR had wondered about). A recognised failure already
carries the command that fixes it, and an issue about a missing `ydotool` helps
nobody — least of all the person who now has two things to do instead of one.

### Added — four more settings in the window, chosen for how each one fails

The settings window covered 147 capability toggles and, until recently, three
values. `[stt] model`, `[stt] language` and `[injection] backend` arrived last
week; this adds **compute type, vocabulary, the no-text-target guard and
pre-speech padding**. All four were editable only by hand-writing TOML.

They were picked for their failure modes rather than their popularity:

**Compute type** is the accuracy/speed lever below model size, and an unsupported
value produces the worst error message in the product. It raises inside the model
load, and that is re-raised as `ModelUnavailableError` — so the user is told their
*model* is unavailable and handed three ways to download a model they already have.
Nothing anywhere mentions quantisation. The list is now asked of ctranslate2 for the
configured device, so it can only offer what this machine can actually load. That
also means a value shown because it is already in the config is still refused when
selected — displaying a value must not make it settable.

**Vocabulary** (`[stt] initial_prompt`) is what `yazses tune` proposes additions to;
accepting one previously meant editing TOML. Newlines are collapsed, because a
literal newline makes the file unparseable and the loader's repair falls the whole
`[stt]` section back to defaults — so pasting a two-line vocabulary would silently
reset the model and the language with it.

**Nowhere to type** (`[injection] target_guard`) is the setting behind the tray's
yellow badge, and the daemon compares it against `"off"` and treats everything else
as on — so an unrecognised value silently means "clipboard" while reading back as
whatever was typed. Refused rather than accepted.

**Pre-speech padding** is the fix for a symptom nobody connects to a setting: the
first word of every burst going missing.

The Apply loop had to stop assuming every row is a combo box — a `QLineEdit` has no
`currentText()` and a `QSpinBox` has no `currentData()` — so each row now carries its
own reader. Wiring one to the wrong widget type raises inside a Qt slot, where the
traceback goes nowhere a user can see, so the window tests drive all four through a
real Apply rather than trusting the unit tests next door.

The settings-window documentation had also fallen behind the previous three
additions, and still described "the three settings that are values rather than
switches". It now lists all ten.

### Added — Meeting Mode can be started and stopped from the tray icon

Meeting Mode is the one thing YazSes does with no key to hold. It runs hands-free for up
to an hour, and the only way to begin or end one was `yazses meeting start` in a terminal
— which is exactly what nobody has open once a call has started. **Start meeting** and
**Stop meeting** are now in the tray click-menu on Linux, macOS and Windows.

The refusal is the half worth describing. Meeting Mode ships off by default, so the state
most people meet first is one where the entry cannot work, and a menu row that fails
silently teaches nothing. On Linux — whose menu is rebuilt on every open — the
inapplicable entry is greyed out with the reason attached: *Meeting Mode is off, turn it
on in Settings*, *a meeting is already running*, *still finishing the last meeting*. The
rumps and pystray menus are built once at startup and cannot re-derive themselves, so
both entries stay clickable there and the daemon's own answer carries the reason.

Two states drive this that nothing published before. The daemon's `state` says `meeting`
while capturing, but it cannot say whether the feature is enabled at all, and — the one
that actually bites — it returns to `idle` the moment capture stops while diarization and
the notes are still being written. Without `meeting_finalizing`, the menu would cheerfully
offer a new meeting on top of a post-pass that had not finished writing the last one.

The decision of what a click may do stays in one pure function shared by all three trays,
and the daemon remains the authority: a click always makes the call and always shows the
answer that comes back, warnings included — including the one saying a transcript will
come back with no speaker names because the diarization models are missing.

### Fixed — the Windows Settings window could not open, and explained itself where nobody could see

Reported from a Windows install: the tray's **Settings…** and **About** entries "do not
work, do not show anything". Three faults line up to produce exactly that silence, and
only the first is a missing feature.

**The bundle shipped no Qt.** Qt moved out of the base dependencies and into the
`desktop` extra. `snap/snapcraft.yaml` was updated in the same breath, and says so in a
comment — *"it is now the `desktop` extra, so it MUST be listed"* — but both PyInstaller
builds still ran a bare `uv sync --no-dev`. PySide6 was therefore missing from the
environment PyInstaller analyses, and the shipped `.exe` contained no GUI at all.
**macOS has the identical defect**: the `.dmg` cannot open Settings either, and nobody
had reported it.

**The explanation went to a stream that discards it.** The settings entry point handles
a missing PySide6 correctly — it prints why and exits. But the tray launches it as a
*windowed* process, which has no console, and the stream fixup then binds `stderr` to
`os.devnull` precisely so that writes cannot raise. That function already **returns**
whether output will be visible, and the caller discarded the answer. There is now a
native message-box fallback, which needs no dependency — which matters, given the reason
for the message is that a GUI toolkit is missing.

**About overran the buffer Windows gives it.** With no dialog available, About is shown
as a balloon, whose body is a 256-wide-character field; the About text is 347. It is now
trimmed by dropping whole lines rather than cutting one — a half-printed URL still looks
clickable — keeping the version at the top, since that is what About is opened for.

The installer smoke test checked that three files exist and ran `--version` and `doctor`;
it never opened the window. A new guard pins the invariant at the build scripts instead.

## [2.27.0] — 2026-08-17

### Fixed — four crashes waiting behind a type gate that said it was clean

`make types` describes itself as *"advisory — currently clean; don't add errors"*.
It was not clean. Seven errors stood in it, and because CI does not run mypy,
nothing ever failed to say so.

Four were real `AttributeError`s waiting on a code path, not checker pedantry:

- **Rewrite crashed if it arrived during startup.** `_try_rewrite` guarded the LLM
  cleaner for exactly this reason and then dereferenced the injector two lines
  later without a guard. It now reports that injection is not ready, which is what
  the neighbouring branch already did.
- **Asking you a spoken question could crash the same way.** The recorder and the
  STT engine are both None until startup finishes; the listener now returns an
  empty answer, which its caller already handles as "no answer given".
- **The tray reaped subprocesses through a controller that may not exist.** The
  new None check sits outside the existing `except` on purpose: a missing
  controller is a wiring bug and a raised exception is a transient `waitpid`
  failure, and swallowing both in one handler made them look identical.
- **The brand mark built its colour with a generator**, losing the
  exactly-three-channels guarantee the RGBA paste depends on.

The fifth is `onnx_asr` — a genuinely optional dependency with no stubs — and now
carries an explicit ignore rather than sitting in the count. mypy: **7 → 0** across
488 files.

### Added — the second clipboard path is documented, and its platform limit

"My dictation went to the clipboard instead of being typed" has **two** causes with
confusingly similar names, and the troubleshooting page covered only one.
`[injection] target_guard` handles *no text field*; `[injection]
fallback_to_clipboard` handles *there was a field and the typing backend failed*.

The second had no prose anywhere — only a row in the generated settings table — even
though turning it off is a real remedy: a typing timeout can fire after part of the
text is already typed, the fallback then pastes the whole thing again, and a streaming
commit deletes a span computed from the first copy. Anyone who has met doubled text
wants the primary backend to fail loudly instead.

⚠ And it is **Linux only**. The macOS and Windows injectors have no clipboard fallback
at all, so the key is inert there in both directions: turning it off changes nothing,
and leaving it at its `true` default does not give you the safety net the name implies.

### Fixed — the README described two capabilities that are not wired

Both were written in the present tense, as things YazSes does.

**The Tier 2 SLM router**, in four places: *"an optional ~0.5B SLM router catches
phrasings the grammar misses"*, *"when its confidence is low, an optional ~0.5B SLM
router takes a second look"*, in the pipeline diagram, and in the models list. Nothing
in `src/` constructs `SLMRouter`; `grammar.classify()` accepts the parameter and both
daemon call sites pass only `macro_table`. The repo's own orphan ledger already recorded
it as *"a plumbed seam never filled"* — the README simply had not caught up.

The concrete cost was in the models list, which invited `yazses model download` for the
Qwen GGUF. Nothing loads it, so that download was pure disk and bandwidth. The command
itself stays recommended for pre-fetching a *speech* model behind a firewall, which is
what it is genuinely for.

**LSP context improving dictation accuracy.** `_effective_initial_prompt` calls
`compose_context_prompt(..., use_lsp=False)` — hardcoded, while `[context] use_lsp`
defaults to `true` and is read by nothing. The prompt is built from your vocabulary and
mined terms only.

The correction is deliberately narrow, because **the neighbouring claim is true**:
`yazses jump "go to function parse_config"` really does resolve symbols through the
editor bridge (`cli.py` constructs `LspContextProvider` for exactly that). So the README
now separates LSP *navigation*, which works, from LSP *into the transcription prompt*,
which is designed and not wired.

### Fixed — "comment this line" was typed into your file instead of commenting it

The README lists it as a spoken command. The pattern allowed exactly **one** trailing
word — `^comment(?:\s+(?:this|line|selection|out))?$` — so `"comment this"` worked and
`"comment this line"`, the phrase people actually say and the one the README printed,
fell through to DICTATE and got typed into the buffer.

Widened to accept `this line`, `the line` and `this selection` as well. Safe because
the pattern is anchored at **both** ends, which is this project's rule for spoken
grammars: only those exact utterances match, and prose like *"this line is a comment"*
still classifies as dictation — checked, not assumed.

### Fixed — `xdotool` was documented as an injection backend and is not one

`backend = "auto"  # auto | xdotool | ydotool | wtype | clipboard` in the README and in
`examples/config.example.toml`. `get_injector` handles `clipboard` and, on Wayland,
`wtype`; everything else falls through to the automatic path. So `xdotool` is not a
token: on X11 it appears to work only because `auto` already selects xdotool there, and
on Wayland asking for it silently gets you ydotool.

Corrected to the set the daemon itself names (`auto | type | ydotool | wtype |
clipboard`), with a note on why `xdotool` is absent — it is the kind of value someone
sets deliberately after reading a troubleshooting thread.

### Fixed — the README told Linux users to hold the wrong key

`| Linux | ``Space`` |` in the README's first table, and *"Hold the hotkey (Space on
Linux…)"* on the docs home page. The Linux default is **Right Alt**: `[hotkey] key`
defaults to `auto`, which resolves to `platform.default_hotkey`, which is `right_alt`,
and first-run seeding never writes a hotkey.

This is the first thing a new Linux user does. They hold Space, nothing happens, and
the reasonable conclusion is that YazSes does not work. `cli.py` even records why a
modifier was chosen — *"so it doesn't collide with normal typing the way `space`
can"* — so the docs recommended the key the code had deliberately rejected.

Corrected in four places: both prose claims, the README's settings snippet
(`key = "space"` → `key = "auto"`, with what `auto` resolves to per platform), and
`examples/config.example.toml`, which is a file people copy.

### Fixed — Intel Mac users were sent away from a build that exists

The README said the `.dmg` is *"Apple Silicon only"* and *"On an Intel Mac, use
pipx"*; `docs/macos-install.md` went further, explaining that an Intel `.dmg` "would
need a second CI job" that had not been paid for.

**That job exists.** Since v2.22.0 the bundle is built as a per-architecture matrix
(`macos-15-intel` alongside `macos-latest`), and v2.26.0 carries both
`YazSes-2.26.0-macos-arm64.dmg` and `YazSes-2.26.0-macos-x86_64.dmg`. Intel users were
being routed away from a native app that had been shipping for four releases.

The Homebrew half of the claim is **kept**, because it is still true: the cask declares
`depends_on arch: :arm64` and refuses on Intel. The Intel CI leg is
`continue-on-error`, so the pages now say a release can ship without it and PyPI is the
fallback when that happens.

### Fixed — eight pages told you to enable features that cannot be enabled

`system/features.py` states it plainly: a capability with `wired = False` is *"designed
but not yet wired into any runtime path: enabling it would write a config key nothing
reads. `features enable` refuses these."* `yazses features` labels them **planned —
designed, not yet wired**.

The documentation did not carry that distinction. Twenty lines across eight pages
spelled out `yazses features enable <slug>` for unwired capabilities, in ordinary
"Capability | Enable with | For" tables beside features that work, with nothing to say
the command would be refused.

The accessibility page was the worst of them — six unwired slugs (`hesitation`,
`breath`, `involuntary`, `voicehealth`, `autostop`, `mousegrid`) offered to the readers
least able to route around a dead end.

Every one is now marked *planned — not yet wired*, next to the command or in the
sentence directly above it where a fenced block cannot carry an inline note. The
capabilities stay listed: that is how someone finds one to wire, which is what
[#164](https://github.com/MSKazemi/yazses/issues/164) asks for. Handing over a command
that cannot work is the part that had to go.

A guard follows `_UNWIRED` rather than a copied list, so wiring a feature retires the
marker requirement by itself, and a new unwired capability inherits it the day it lands.

### Fixed — the remote how-to promised a `default_host` that cannot work

It showed `[remote] default_host` as *"host to use when none is given"*, in a block
introduced as "the defaults the `remote` command uses when you omit flags".

**The host cannot be omitted.** It is a required positional argument: `yazses remote`
with no host exits with *"Missing argument 'host'"* before any configuration is read,
so there is no code path on which a default could apply. `default_host` appears exactly
once in the source — its own declaration — and nothing else reads it. Its three
siblings in that block (`ssh_port`, `agent_port`, `key_file`) are all genuinely wired,
which is what made the dead one easy to miss.

The page now says so rather than teaching a setting that silently does nothing. The key
is left in place: the loader accepts it, and removing a key people may already have set
is a separate decision from documenting it honestly.

Found by cross-referencing every how-to and tutorial against the ledger of config keys
no code reads — one hit across all of them, which is the useful part of that answer.

### Added — the silent-audio how-to now covers "Empty transcription"

The troubleshooting page someone reaches for when dictation stops was written for one
message — `Silent audio -- discarding`, the gate rejecting the burst. It routed
everything else to *"nothing is being recorded"*, which is the wrong page for the
opposite problem.

`Empty transcription -- discarding` means the audio **passed** the gate, reached the
model, and decoded to nothing. The gate is not the fault and moving it will not help.
Measured on a machine in exactly that state: four bursts at levels 0.0022–0.0069
against **0.0199** for its own last successful dictation — audible, and far too quiet
to recognise.

The new step names the real cause (which microphone, at what gain), shows how to see
the device behind the `default` alias, and gives the two commands that fix it. It also
records that a run of these now trips the mic-change guard, which previously counted
only silent discards — so a microphone that heard you but yielded nothing was invisible
to the thing built to notice.

### Fixed — `--min-speakers` still advertised itself as a lower bound

This cycle taught the run to say that `--min-speakers` is ignored by the diarizer this
build ships. It did not change the flag's own `--help`, which still read *"Lower bound
on the auto-detected speaker count."*

So the false claim stayed at the source, and everything downstream inherited it: the
generated command index repeated it verbatim, and the transcription tutorial went
further and told people to *"use `--min-speakers` / `--max-speakers` to give a range
instead of an exact number"* — which is wrong twice over, since `--max-speakers` forces
an exact count rather than capping one.

The help now says the flag is ignored, names why (only the unshipped pyannote adapter
reads it) and points at `--speakers`, which does constrain the count. The command index
and man page are regenerated from it, and the tutorial says plainly that there is no
range option on the shipped diarizer.

A warning at runtime does not undo a wrong `--help`: the help is what people read
*before* running the command, which is when the decision is made.

### Fixed — the tray left a zombie behind every time you opened Settings

Observed in a live process tree, not a fixture:

```
yazses-tray    (1442790)
└── yazses-settings (1802882)  Z, 4023s
```

A settings window that had been closed **67 minutes earlier** was still holding a PID
as a zombie. The tray spawns it with `Popen` and deliberately does not wait — right,
because blocking would freeze the icon for as long as the window is open — but nothing
ever called `poll()` either. `subprocess` only reaps opportunistically when the *next*
`Popen` is created, so opening Settings once and closing it leaks until the tray
happens to spawn something else, and opening it repeatedly accumulates.

The controller now remembers what it started and reaps finished children from the
tray's existing per-tick update: one `poll()` per live child per tick, nothing when
there are none, and it never raises into the icon.

Found while investigating a separate report — *"selecting a feature in the GUI and
applying it closes YazSes"* — which is not this, and is still open. The process tree
that answers that question is what showed the zombie.

### Fixed — the man page's release date stopped resolving at 2.25.0

`scripts/gen-man.py` stamps `.TH` with the version's date from the changelog, rather
than `datetime.today()`, so the page stays byte-identical across CI runs until the
commands actually change. It matched `## [X.Y.Z] - YYYY-MM-DD` with an ASCII hyphen.

Every release from 2.25.0 writes an **em dash**. So the lookup stopped resolving, the
stamp fell back to `unreleased`, and the header test permits exactly that string — so
nothing noticed. 2.24.0, the last heading written with a hyphen, was the last one that
worked.

The pattern now accepts a hyphen, an en dash or an em dash: a formatting choice should
not be able to quietly disable the thing the function exists to do. `man/yazses.1` is
regenerated — its stamp had been showing **2.24.0**, three releases behind, since the
body-only sync check deliberately excludes `.TH` so that a version bump cannot redden
CI.

### Added — `yazses status` reports how often dictation actually produced text

```
  latency:  base.en p50 1332 ms (n=4, need 20 for p95)
  typed:    6 of 14 recent bursts (43%)
```

`stt/latency.py` was added because decode time *"has always been measured and logged
but was never summarised, so the one number that predicts whether dictation feels
usable was only available by reading a log by eye."* Exactly the same was true of the
more basic number — whether a burst produced any text at all — and a fast decode that
types nothing is not usable at all.

This exists because that reading-by-eye had to be done. On a real machine the outcome
went from **21 typed of 30 bursts to 6 of 14** over about six hours — the failure rate
doubling while its owner was actively trying to dictate, with the per-burst result in
the log the whole time and nothing adding it up.

A bounded window rather than a lifetime rate: a lifetime average is dominated by
history and moves too slowly to show a change that started this morning, which is the
case worth catching. It reports on a healthy run too, because a number that only
appears when things are bad gives you no baseline — you cannot tell 70% from 100% when
it matters. Silent below five bursts, since "0% of 1" would be believed.

Any outcome string is counted, including one this version has never heard of: an
outcome nobody counted is how a failure mode stays invisible. The line is absent
against an older daemon that does not send the field.

A burst that **raised** — an injection that failed, a backend that went away — is
counted as `error` rather than as success. `discard_reason` is set on the ten paths
that *decide* not to type, but not on the one where something throws, because that
lands in the pipeline's `except` handler and records `last_error` instead. Counting
those as typed would make the gauge report failures as successes, which is worse than
having no gauge: it is consulted exactly when something is wrong. (`event["injected"]`
cannot stand in for it — that is set *before* dispatch, so it records the intention to
type rather than the result.)

## [2.26.0] — 2026-08-17

### Added — `audio status` and `doctor` name the microphone behind the `default` alias

Saying *"that is a routing alias"* is true but not yet useful. On the screen someone
opens when dictation has stopped, the question is **which microphone is it using**:

```
OS default:    default
               → Raptor Lake-P/U/H cAVS Digital Microphone  (volume 65%)
               ⚠ that is a routing alias, not a microphone — …
```

That line is the diagnosis, and until now it could only be obtained by leaving YazSes
and reading `wpctl status` by hand — which is exactly how the machine that prompted
this was found to be routed to its internal microphone array at 65% gain, with a second
source sitting at 100%.

Resolved through `wpctl`, the way this project already reaches `notify-send`,
`xdotool` and `wl-copy`: used when present, absent without complaint, never required,
and never raising into the caller. The parsing is pure and tested against real output,
reads only the `Sources:` block (`Sinks:` has the same row shape and its own starred
default, and reporting a speaker as the microphone would be worse than silence), and
returns nothing at all when no source is marked default — which source is current is
then genuinely unknown, and guessing is how a diagnostic starts lying.

`doctor` carries the same line, and had the same gap — it is the surface the
documentation points at first, and it reported the bare alias:

```
[OK] Microphone: OS default: default → Raptor Lake-P/U/H cAVS Digital Microphone
     (volume 65%) (pin with `yazses audio use <name>`)
```

Both suppress the arrow when the default is already a real device, since resolving a
name to itself is noise.

### Fixed — `audio status` hid that "default" is a route, not a microphone

```
OS default:    default
```

On ALSA and PipeWire, `default` is a virtual entry that forwards to whichever device
is current — PortAudio reports it at its own index, in the same list as
`sof-hda-dsp: - (hw:0,0)`. Whatever microphone it points at, the name it reports is
`default`.

That is a limitation with teeth, because the device-change watcher spots a switch by
**comparing that name over time**. Against an alias it compares `default` with
`default` for ever, so on the most common Linux audio stack the proactive half of the
mic guard cannot fire: the microphone behind the alias changes and nothing on screen
changes with it.

Reading through the alias needs a PipeWire or PulseAudio client library, which is not a
dependency worth taking on for one diagnostic. So the limitation is named where someone
looks when dictation has stopped working and they are trying to find out what it is
listening to, along with the remedy that does work — pinning a real device with
`yazses audio use <name>`.

The streak-based half of the guard is unaffected: it counts outcomes, not device names,
and now counts empty transcriptions too (above).

### Fixed — a mic that hears you but yields nothing never tripped the guard

The mic-change guard counts *silent* discards: audio below `vad_threshold`. A run of
them auto-heals capture back to the last-good device and notifies *"Heard nothing 3× in
a row — your mic may have changed."*

An **empty transcription** — audio that clears the gate, reaches the model, and decodes
to nothing — logged one line and returned. It did not count toward the streak, did not
notify, did not auto-heal, and played no earcon. So a microphone capturing audible but
unintelligible audio (too quiet, wrong device, badly attenuated) discarded for ever
with `silent_streak` stuck at `0`, while the guard built for exactly that symptom saw a
perfectly healthy microphone.

Observed live rather than reasoned about: four consecutive empty transcriptions at
levels **0.0022–0.0069**, on a machine whose last successful capture measured
**0.0199**. Nothing was typed and nothing was said, four times.

From the user's side the two failures are the same event — hold the key, speak, no text
appears — and the notification's advice (`yazses mic-level --set`, `yazses audio
devices`) is the right advice for both. The empty path now calls the same handler, so a
streak of them heals and notifies exactly as a silent streak does, and plays the error
earcon for the reason the silent branch already documents: nothing will be typed, and
without a screen that is indistinguishable from a slow decode.

A single empty transcription still says nothing — the threshold (3 consecutive, reset by
any success) is unchanged, so holding the key without speaking costs nothing.

### Fixed — `gitvoice` truncated a branch name and aimed a destructive command at it

```
"delete branch feature slash login"       ->  git branch -D feature
"delete branch my slash deep slash name"  ->  git branch -D my
"create branch feature slash login"       ->  git checkout -b feature
```

`feature/login` spoken is *"feature slash login"*, and `feature/…` is the most common
branch convention there is. The ref patterns capture `[\w./-]+`, which stops at the
space, and `re.search` is unanchored — so everything after the first segment was
discarded and a **destructive command was emitted against a different ref than the one
named**, with nothing to show that anything had been dropped.

Two fixes. A spoken `slash` now makes the `/` it sounds like, so the common case
produces the branch the user said. And the ref patterns are anchored at **both** ends,
which is this project's own documented rule for spoken grammars — *"a suffix match
swallows 'click undo' instead of typing it"*. Anything the grammar does not model now
refuses and prints the hint listing what it understands, rather than emitting a
partially-understood command.

Case is still preserved on the captured ref, per the module's existing reasoning about
case-sensitive refs and paths: `delete branch Feature slash Login` gives
`Feature/Login`.

## [2.25.1] — 2026-08-17

### Fixed — a missing file was reported as a format problem

Asking the MCP server to transcribe a path that does not exist answered:

```
RuntimeError: Could not decode '/nonexistent.wav' as audio. Neither PyAV nor ffmpeg
could read it, so it is probably not an audio or video file, or it is truncated.
```

The real error, one line above in the log, was `[Errno 2] No such file or directory`.
Every cause offered is wrong, and each one sends the reader to inspect the file's
contents instead of its name.

`load_audio`'s docstring already promised `FileNotFoundError` for a missing path and
nothing checked for one — the second time this function has been found not honouring
its own documented contract, after the ffmpeg fallback. The path is only reachable
programmatically, since the CLI rejects a missing file at argument parsing, which is
why it took an agent-facing surface to surface it.

A directory is deliberately left to the decoder: it exists, so calling it missing would
be a different wrong cause.

### Fixed — two status lines that read as faults

**`yazses meeting list` called an undiarized meeting "0 speaker(s)".** On a real
machine that line described an 8081-second meeting with a 1.7 MB transcript, which
reads as a failed recording. All three stored meetings are `diarized: false` — speaker
labelling was never attempted, which is a different statement from "nobody spoke". It
now says `not diarized`.

Written as `diarized is False` rather than a falsy test: an older `meeting.json`
without the key says nothing either way, and guessing would assert something the file
does not contain. Both rendering sites — `meeting status` and `meeting list` — now go
through one helper instead of repeating the format.

**`yazses status` printed `uptime: 48176.17s`.** Thirteen hours, in seconds, to two
decimal places that were never measured. It now reads `13h 24m`. The value matters
most when it is large, because a long uptime is how you notice a daemon still running
the build it started with.

### Fixed — `yazses tune` looked like a hang for as long as it took

Run against a real corpus (3683 events, 3280 of them with audio), `tune` printed:

```
Loading re-transcription model 'small.en'...
```

and then nothing at all. Still nothing eight minutes later, still going. The model was
already cached, so that was the re-transcription itself — thousands of clips through a
larger model on CPU, in silence. At the observed rate the run would have taken about
two hours, and nothing on screen distinguished that from a crash.

Nothing was broken. But the number of clips is known before any audio is touched — it
is a metadata query — so there was no reason to withhold it. It now announces the
total up front and reports movement every 25 clips:

```
Re-transcribing 3280 captured clip(s) with the tune model — the slow step; a large
corpus can take a while.
  25/3280 clip(s)…
```

`retranscribe()` gained an optional `progress(done, total)` callback, called once with
`(0, total)` before the first clip. Its existing `limit` parameter — designed, tested
and passed by nobody — still bounds the work for anyone who wants a shorter run.

### Fixed — the mic-level check was suppressed exactly when it mattered

On a real machine, `yazses doctor --mic` printed:

```
[OK] Mic level: ambient 0.0010 under vad_threshold 0.0005
```

0.0010 is not under 0.0005. The warning was conditioned on `not stats.is_silent`, and
`is_silent` is measured against a **fixed** floor (`miclevel._MIN_THRESHOLD`, 0.002)
that has nothing to do with the user's gate. So for any `vad_threshold` below 0.002
the warning was suppressed across the whole band between the two — which is exactly
the band where the gate sits under the room's noise floor — and the OK branch then
asserted "under" for a value that was over.

That is the condition this check exists to find, and it has a consequence worth
naming: when the gate is below the room, ordinary silence passes it and reaches the
model, which answers near-silence with a confident invented word. The same
hallucination behind the two `transcribe` and `verify` fixes above, on the path where
the text is typed into whatever you had focused.

Now compared against the user's gate and nothing else, with the consequence and the
fix in the message. A dead microphone is excluded (`mean_abs > 0`), because nothing
captured at all is the Microphone check's business and a gate of `0` would otherwise
blame the gate for a mic that recorded nothing.

### Fixed — `yazses verify` reported a word count instead of the word

Run in a quiet room with nobody speaking:

```
[OK] Signal: level 0.0013 clears the gate (0.0005)
[OK] Transcription: produced 1 word(s)
✓ Dictation works end to end on this machine.
```

The one word was Whisper's silence hallucination. Ambient noise cleared the gate, the
model answered near-silence with a confident invented word, and the command whose
entire purpose is to prove the chain honestly certified it.

The case that matters is not a user who said nothing — it is a **muted or wrong
microphone in a room with any noise in it**, which produces exactly this and is the
situation `verify` exists for.

Whether a word is invented cannot be decided reliably. Whether it is what you said
can — by you, instantly, if it is on the screen. The line now reads `heard "You"`,
truncated for a long dictation with the full word count kept. It costs nothing and it
is the single most informative thing this command could print, because the person
running it is the only one who knows what they said.

### Fixed — `yazses report` understated the learning corpus 430x

Two surfaces, one corpus, measured on a real machine:

```
yazses report          corpus: 3.0 MB
yazses corpus status   size:   1294.9 MB
```

`report` sized `corpus.db` and nothing else. The encrypted audio clips beside it are
almost all of a real corpus — 3.0 MB of database against 1291.9 MB of audio here.

That number is the one attached to bug reports, so a maintainer reading *3 MB* rules
the corpus out of a disk-space problem it is in fact causing. It is also what a user
checks against `[learning] max_corpus_mb` (default 500): reading the report, someone
2.5x over the cap concludes they are comfortably under it.

Both now go through one helper, the same stat calls the store already prunes against,
so they cannot drift again. Nothing is opened or decrypted — this is filesystem
metadata, as before.

Reported in **mebibytes**, which is what the cap enforces (`max_mb * 1024 * 1024`) and
what `corpus status` prints. The first fix divided by 1e6 and made the two surfaces
disagree — 1357.8 against 1294.9 for one corpus — which reads as a bug in one of them
and leaves the number not comparable to the cap it exists to be compared against.
(Both label mebibytes as "MB"; that imprecision is pre-existing and left alone.)

### Fixed — silence transcribed to a confident word, reported as a transcript

Two seconds of digital silence through `yazses transcribe` produces this:

```
Wrote out.txt
$ cat out.txt
You
```

A word, with a start and an end time, in the JSON output as an utterance. That is
Whisper's well-known silence hallucination, and the empty-transcript note shipped
alongside it cannot see it — the transcript is not empty.

Nothing about the output separates an invented word from a real one, so the check has
to be about the input, where the answer is unambiguous: **audio with no signal in it
cannot contain speech.** A muted microphone, an input device held by another
application, and capture pointed at the wrong device all produce exactly this, and all
three are ordinary — they are why this project has a mic-change guard, a silent-streak
tracker and an error earcon on the dictation path. The file path had none of it.

`transcribe` now says the audio carries no signal, that the text was produced from
silence and is not trustworthy, and names the three causes. The transcript is still
written — you may want to see what was invented — but it is no longer presented as a
result, and it no longer earns the "a star helps" pointer.

Measured on the **peak**, not the mean. The daemon's silence gate averages, which is
right for a hold-to-talk burst that is nearly all speech and wrong for a file: an hour
of interview with sparse talking averages to almost nothing, so a mean-based gate would
call a real recording silent.

Every test in `test_cli_transcribe.py` had been decoding `np.zeros(16000)` into
"hello there general" — a pairing that cannot occur, and one that hid this from all of
them. The fixture now carries a noise floor.

### Fixed — the release gate named a channel missing while it was still building

The v2.25.0 report listed Docker/GHCR as absent. Re-checking minutes later showed
`tags=2.25.0`: the image was in flight, published by the same tag push, and the gate
waited for four of the five channels CI produces.

The report exists to be a standing, itemised statement of what is missing. A channel
that publishes two minutes later was never missing, and a report that cries wolf on
its own build gets discounted along with everything true in it.

The wait now polls `--ci-only` — CORE plus the container image — instead of counting
assets in bash. That also removes the second implementation of "is this published",
which is what caused the defect above: the bash was hardened to two bundles per
platform and the script it then asked for a verdict was not, so the gate waited on a
stricter condition than the one it certified. Snap stays excluded, because it uploads
here but reaches `stable` only after store review and can never be waited on.

`--core-only` is deliberately unchanged: it answers *is this release broken for a user
on that OS*, which is what may demote a release to pre-release, and a missing image is
a gap in reach rather than a broken download.

### Fixed — the release gate certified a platform on one architecture of a pair

`release-complete.yml` counts `deb > 1 && dmg > 1 && exe > 1` in its wait loop, and
says why: *"at least one .dmg" let it print "All platforms published" for a release
carrying no Intel bundle — which is exactly what happened for v2.20.0 and v2.21.0.*

The wait was hardened. The check it delegates the **verdict** to was not.
`check_release_assets` took the first asset matching each suffix, so the published
summary table and `--core-only` both accepted a half-built release. `--core-only` is
what decides whether an incomplete release keeps the **Latest** label, so a release
carrying only an arm64 `.dmg` was never demoted and Intel users were sent to a
download that did not exist.

Run against the real releases after the fix:

| Release | macOS | Windows |
|---|---|---|
| v2.20.0 | ❌ only `YazSes-2.20.0.dmg` | ❌ only `-windows-x64.exe` |
| v2.21.0 | ❌ only `-macos-arm64.dmg` | ❌ only `-windows-x64.exe` |
| v2.25.0 | ✅ both | ✅ both |

Both architectures are now required, and the detail column names the assets it found
rather than implying them — the evidence for a ✅ is now visible in the report.

## [2.25.0] — 2026-08-17

### Fixed — `doctor` told a running daemon to start

Its closing line contradicted its own warning three lines above:

```
[WARN] Daemon: running (PID 4054, state idle) — ... run `yazses restart` ...
▲ Good to go (3 optional warnings above) — run `yazses start`, then hold ...
```

The verdict decided whether a daemon was running by reading the check's **tag**
(`== "OK"`), which was sound only while a running daemon was always OK. v2.24.0
introduced a running-but-`WARN` state for a stale daemon and did not update this
line, so a demonstrably running daemon read as stopped and the last thing you are
told to do — the line people act on — named the wrong command.

The verdict now reads the daemon check's own detail rather than re-asking the OS, so
the bottom line cannot disagree with what was printed above it, and a stale daemon
gets `yazses restart`. Producer and consumer share one constant, with a test that
fails if a running branch hardcodes its prefix again.

Found by running `yazses doctor` on a machine whose daemon predated the upgrade —
a state that cannot be manufactured in a fixture, and the regression was mine.

### Added — `yazses transcribe --format json` has a documented shape

The research guide told people to use it because it is "structured, for import into
other tools", and never said what the structure is — so anyone writing that import
had to run the command and reverse-engineer the fields. The
[interview guide](docs/use-cases/research-interview-transcription.md) now shows the
real output, with a field table and the two things a parser needs and could not have
guessed: `speaker` is a cluster id rather than a person and does not carry across
files, and the empty shapes differ (undiarized output still has utterances with an
empty `speaker`; nothing-recognised output has none at all).

Nothing about the output changed. It was already more dependable than it was
described.

### Fixed — the loopback guard answered differently on Python 3.11 and 3.12

`is_loopback_endpoint` trusted `IPv6Address.is_loopback`, and CPython only began
counting IPv4-mapped addresses as loopback in **3.13**. On 3.11 and 3.12 the same endpoint —
`http://[::ffff:127.0.0.1]:11434`, which genuinely reaches this machine — was
refused.

The project supports 3.11 through 3.14, so a privacy guard was giving two different
answers depending on the interpreter: a config that worked on one machine was
rejected on another, with a message about sending dictated text off-device. It now
resolves the IPv4 mapping itself, so every supported Python agrees.

The security direction was never wrong — the older interpreters were the stricter —
but a guard whose answer depends on the interpreter cannot be reasoned about.


### Fixed — a bare JSON array over IPC got no reply and a traceback in the log

`[1,2,3]`, `"hello"`, `42`, `null` and `true` are all valid JSON, and none of them
has a `.get`. `Request.from_json` therefore left an `AttributeError` for that one
class of malformed input, while `ipc/server.py` catches `(ValueError,
UnicodeDecodeError)` to answer with a JSON-RPC parse error.

So the caller got a closed socket and **no reply at all**, and the per-connection
thread died printing a traceback into the daemon log — which reads like a crash to
whoever later opens `yazses logs` about something real. Every other malformed input
was answered properly.

Both parsers now reject non-objects with `ValueError`, which is the contract the
server was already written against. Fixed in the parser rather than by widening the
server's `except`, so the guarantee holds for every caller — the client parses
responses with the same expectation.

The blast radius was bounded and worth stating: connections are handled one thread
each, so the accept loop survived and the daemon stayed reachable.


### Fixed — the MCP server handed agents Python internals

Calling `transcribe` without its argument returned this to the model on the other
end:

```
TypeError: transcribe_tool.<locals>._run() missing 1 required positional
argument: 'path'
```

An internal closure name and a traceback string, from which the caller has to guess
which field it left out. The arguments are now bound against the tool's signature
*before* it runs, and a mismatch is answered from the JSON Schema `tools/list`
already publishes: *"transcribe: missing a required argument: 'path'. Required:
path. Accepts: path, diarize."*

`tools/call` with no `name` said *"No tool named None"*, which reads as though
`None` were a name that had been tried rather than a field that was omitted. It now
says which field is missing and what the server offers.

Found by fuzzing the server over a real pipe with fifteen malformed requests. The
protocol handling itself came back clean — correct `-32700`, `-32600` and `-32601`
codes, notifications correctly unanswered, a 200 KB payload and 200-deep nesting
survived, no crash and no traceback on stderr. Only the human-readable half was
wrong, which is the half an agent reads.


### Fixed — `vad_threshold = inf` loaded cleanly and stopped dictation completely

Config loading is deliberately total (#52): a bad file yields a working daemon, the
documented default, and a `ConfigProblem` that `doctor` shows under **Config
validity**. `nan` and `inf` are floats, so the type check waved them straight
through — no repair, no problem reported, value accepted.

The one that bites is `[accessibility] vad_threshold`. The silence gate is
`mean(|audio|) < threshold`, so:

- `inf` discards **every** burst — you hold the key, speak, and nothing is ever
  typed;
- `nan` makes the comparison false forever, so the gate stops gating at all.

Either way `yazses doctor` reported no config problem, because as far as the checker
was concerned nothing was wrong. Non-finite numbers are now rejected for every float
field, falling back to the documented default and reporting it like any other
repair. `"0.004"` → `0.004` still repairs as before.

Found by fuzzing the loader with fifteen adversarial files — binary, null bytes,
unparseable TOML, 200 KB strings, deep nesting, RTL unicode. **None of them made it
raise**, which is the invariant holding; these two were accepted *too* quietly.


### Fixed — `--max-speakers` invented speakers instead of capping them

`--help` called it *"Upper bound on the auto-detected speaker count"*. On the shipped
`sherpa` diarizer it becomes `FastClusteringConfig(num_clusters=N)`, which is an
**exact** cluster count — so `--max-speakers 6` on a three-person recording does not
allow up to six, it manufactures six by splitting real speakers apart.

Measured rather than reasoned about, against sherpa-onnx 1.13.5 on two
well-separated synthetic speakers:

| `num_clusters` | clusters produced |
|---|---|
| `-1` (auto) | 2 ✓ |
| `2` | 2 ✓ |
| `4` | **4** |
| `6` | **6** |

The help text, the command's own epilog (*"cap the count with …"*) and the config
comments now say what it does. `0` still auto-detects and remains the default, so
recordings and meetings are unaffected unless a bound was set deliberately.

A real upper bound is not implemented — that needs a second clustering pass and the
diarization models to verify end to end. The measurement above is recorded so
whoever has them does not have to rediscover it.


### Fixed — `--min-speakers` did nothing on the diarizer this build ships

`yazses transcribe --help` describes it as *"Lower bound on the auto-detected speaker
count"*. Only `recimport/pyannote_backend.py` reads `min_speakers`, and pyannote is
one of the adapters this build does not ship — `system/backends.py` calls that class
out separately from *"the optional dependency is missing"*, precisely so a factory
never sends someone after an extra that cannot supply the backend.

The default `sherpa` diarizer reads `max_speakers` alone. So a user asking for at
least three speakers got no error, no effect, and a transcript that ignored the
floor — discovered, if at all, by reading the result.

It now says so before the transcription starts, names the backend actually in use,
and points at `--speakers` as the flag that does constrain the count. Silent when no
lower bound was asked for, and silent without `--diarize`, where speaker bounds are
meaningless anyway.


### Fixed — an undecodable file showed you the ffmpeg command line

Pointing `yazses transcribe` at something that is not audio — a `.docx`, a truncated
download, a renamed file — printed this:

```
Transcription failed: Command '['ffmpeg', '-nostdin', '-threads', '0', '-i',
'/…/notes.docx', '-f', 'f32le', '-ac', '1', '-ar', '16000', '-']' returned
non-zero exit status 183.
```

It names neither the problem nor anything you can do about it.

`load_audio` already promised better. Its docstring says it *"raises `RuntimeError`
if no decoder can read it (neither PyAV nor a system ffmpeg)"* — but the ffmpeg
fallback was unguarded, so that promise held only when ffmpeg was **absent**. In the
ordinary case, with ffmpeg installed and the file simply not being audio, a raw
`subprocess.CalledProcessError` escaped instead. The function broke its own contract
on its most likely failure.

It now raises the documented error, says the file is probably not audio or is
truncated, and lists formats that do work. The no-ffmpeg branch keeps its own advice
— *install ffmpeg* — because that is the useful thing to say when that is the fault.


### Fixed — `yazses transcribe` reported success over an empty transcript

Audio with nothing recognisable in it — music, silence, or speech in a language an
English-only model cannot read — produced an empty file, the message `Wrote
transcript.txt`, and then the one-time *"if this was useful, a star helps"* pointer.
Success, by every signal the command gives.

That is the silent failure this project spends its earcons and guards avoiding, on
the surface where most people meet YazSes working for the first time: `transcribe`
is the one path needing no microphone, no hotkey and no re-login, so it is what the
container and Codespace trials run.

It now says the transcript is empty and names causes you can act on, the useful one
being the English-only model — which you can neither see nor guess from a blank
file. The pointer no longer treats an empty transcript as a success.

The check reads `result.utterances`, not the rendered text: a VTT with no cues is
still `WEBVTT`, so a check on the string would have stayed silent for exactly one of
the five formats.


## [2.24.0] - 2026-08-17

### Fixed — the docs described two pipeline stages that do not exist

`grammar.classify()` accepts an `slm_router` argument and **nothing constructs
one**, so Tier 1 decides every utterance. The daemon never constructs
`LspContextProvider`, so **no editor context has ever reached the transcription
prompt**. `docs/architecture.md` described both as working parts of the pipeline,
and four config keys were documented as knobs with no hint that nothing reads them.

The repo already knew about half of it: `tests/test_orphan_modules.py` records
`commands.slm_router` as *"a plumbed seam never filled"*. The ledger and the
architecture page were both checked in, disagreeing.

**The privacy statement is the part that mattered most.** It said that with
`lsp_enabled = true` YazSes reads your active file path, language and cursor line
into every transcription prompt, and offered turning it off as a mitigation. None of
that happened — it overstated what is collected and offered protection against
nothing. Corrected in place, with what is actually true: the editor bridge is
contacted only when you run `yazses jump`, for that one invocation.

`yazses jump` does **not** require `lsp_enabled = true` either, though the CLI
reference said so — it contacts the editor directly however that key is set.

Found by sweeping all 432 config fields for names never referenced outside
`config.py`, then triaging the 32 hits by whether the owning feature ships.


### Fixed — `[injection] fallback_to_clipboard` was documented and read by nothing

`LinuxInjector` built its clipboard fallback unconditionally. The setting appears in
**seventeen** places across the docs and the example configs people copy, defaults
to `true`, and no code ever looked at it — so anyone who turned it off was silently
overruled.

Turning it off is a remedy, not a preference. `inject/xdotool.py` already records
the failure it answers: a timeout can fire *after* xdotool has typed part of the
text, `LinuxInjector` reads that as "the backend is broken", the clipboard paste
types the text a second time, and the streaming commit then deletes a span computed
from the first copy. Someone who has met that wants the primary backend to fail
loudly instead — and asked for exactly that, in writing, to no effect.

Bridged through an environment variable the way `[injection] backend` already is,
for the reason that bridge gives in its own comment: no platform factory signature
has to move, and non-Linux platforms ignore it.

Found by sweeping every config field for ones never named outside `config.py`. Of
432 fields, 32 are never referenced; most belong to capabilities honestly listed as
*planned — not yet wired*, where that is expected rather than a defect.


### Fixed — `[learning] retention_days` and `max_corpus_mb` did nothing

`CorpusStore.prune()` has existed since the learning corpus shipped, with its own
tests, and **nothing in `src/` ever called it**. Both settings were documented — *"auto-evict
events older than this"*, *"cap corpus size; oldest events trimmed first"* — and
neither was ever applied.

Found by running `yazses corpus status` on a real machine: **1292 MB against the
500 MB default cap, spanning 38 days against the 30-day default retention**, on a
config that had changed neither.

The disk cost is the lesser half. Retention is a privacy control (ADR-012): the
promise is that captured audio and transcripts age out, and they were not ageing
out. A privacy limit that silently does not apply is worse than one that was never
offered, because the user has already decided they are protected by it.

The writer now prunes on its background thread — once at start, then every 200
events, so a daemon left running for weeks cannot grow without limit and no disk
work lands on the dictation path. A failing prune is logged and swallowed: a dead
writer thread stops capture silently, which is far worse than a corpus briefly over
its cap.

!!! warning "This evicts data the first time your daemon restarts"

    If your corpus is over its limits, the first restart after upgrading will apply
    them. Raise `max_corpus_mb` / `retention_days` **before** restarting if you want
    to keep what is there. `yazses corpus status` shows the current size.


### Fixed — `yazses report` leaked the account name in paths outside `$HOME`

The bundle exists to be pasted into a public issue, and its own help promises
"settings with paths and identifiers removed". It replaced the home directory
everywhere, which is why `/home/<you>/…` correctly became `~/…` — and left the
account name untouched wherever it appeared in a path that is *not* under `$HOME`:

    /media/<you>/USB-STICK/note.wav      a file transcribed off a drive
    /run/media/<you>/…                   the same, other distributions
    /tmp/pytest-of-<you>/…               how this was noticed

The first is the one that matters in ordinary use. Found by running
`yazses report --print` on a real machine and counting: the account name appeared
six times, zero of them under a home path.

The account name is now redacted on word boundaries as well. Names shorter than
three characters, and generic ones (`root`, `ubuntu`, `ci`, `runner`, `test` and
friends) are deliberately left alone — such an account identifies nobody, and
blanking a common short word would shred the surrounding log into unreadable
diagnostics. Redaction that destroys the report defeats its purpose as surely as
redaction that misses.


### Fixed — the test suite was writing into the user's real diagnostic log

`yazses logs` prints `~/.local/state/yazses/log/daemon.log`, and `yazses report`
bundles a tail of it into bug reports. Running the test suite put **44 KB** of test
output there per run: fake recorders, deliberately invalid backends, and injected
`OSError`s with tracebacks pointing into `tests/`. Anyone reading that log to
diagnose a real fault would find `Microphone unavailable` and `uv is gone` and have
no way to know none of it happened to them.

The mechanism is that `Daemon.run()` attaches a `RotatingFileHandler` to the **root**
logger and never removes it, so a single test calling the real `run()` redirected
every later test in the session into the file. Two such tests lived in the same
file, and the second was only found after the first was fixed.

Separately, `_configure_logging` was not idempotent: a second call added a second
handler on the same file, so every line was written twice and the 1 MB rotation
threshold arrived twice as fast — halving how much history a bug report can carry.
It now returns early if the root logger already has that file.

Guarded rather than fixed case by case: an autouse fixture fails any test that
leaves a file handler on the root logger, and removes it so one careless test
cannot take the rest of the session with it. Verified by measurement — a full run
moved the real log 44 KB before, 0 bytes after.


### Fixed — `doctor` said "Good to go" about a daemon running an older build

Upgrading replaces the files on disk. It does not touch a process that is already
running, so the daemon keeps executing the build it started with until `yazses
restart`. `doctor` printed the **CLI's** version on one line and the daemon's
**liveness** on the next, never compared them, and concluded the machine was
healthy — so the surface you open to ask *is everything fine* answered yes while
dictation ran last week's code.

Found on the maintainer's own machine, not hypothesised: a daemon up 8.6 hours,
hours older than the v2.23.0 tag `doctor` was reporting on the line above it.

The daemon now reports its own version over IPC and `doctor` compares the two,
naming both and the fix. A daemon that reports **no** version is treated as
evidence rather than as an unknown — the field is new, so its absence means the
process is older than the CLI reading it, which is exactly the common case.

Same shape as the `uv tool upgrade` defect fixed in 2.20.0: the command succeeded,
and nothing checked that anything had actually moved.


### Fixed — the reduced-motion probe asked the wrong things on two platforms

Both probes were written from memory and neither could be exercised on the machine
that wrote them, which is the condition under which a wrong answer is invisible:
the call fails, the probe returns "cannot tell", and that is indistinguishable from
a desktop with no such setting. Reduced motion would simply never engage and
nothing would look broken.

**macOS** shelled out to `defaults read com.apple.universalaccess reduceMotion`, an
undocumented preference key that is absent until the user has toggled the setting
once. It now asks `NSWorkspace.accessibilityDisplayShouldReduceMotion` — the
supported API, and pyobjc is already an unconditional dependency there — with the
`defaults` read kept only as a fallback.

**Linux** asked GNOME's `gsettings` and nothing else. It now asks the **XDG desktop
portal** first, which two things depend on: desktops beyond GNOME implement a portal
backend, and — the one that actually bites — **YazSes ships as a snap**, where a
confined process reading `gsettings` may be answering about the sandbox rather than
about the user's session. Verified against this machine's live portal, not inferred.

**Windows**' `SPI_GETCLIENTAREAANIMATION` was checked against the Win32 reference
and was already right. It is now a named constant with its inverted polarity written
down — `pvParam` receives TRUE when animations are *enabled* — and pinned by a test,
because an unexplained inverted boolean is where a later tidy-up introduces a bug.


### Fixed — “never mind” meant three different things

2.23.0 shipped `[audio] voice_answer` accepting “never mind” as a way to dismiss the
mic toast, and the gate's own docstring claimed its vocabulary did not overlap the
command-safety gate's. It did. “never mind” is one of `DEFAULT_CANCEL_WORDS`, where
it means *discard the held command*, and it is a self-correction trigger for the
disfluency filter besides.

Because the mic gate deliberately runs second, saying it with both pending cancelled
the held command and left the toast unanswered — the same words doing different
things according to state the user cannot see, which is precisely what ADR-021's
one-release-phrase rule exists to prevent.

Removed from the mic answers, leaving “ignore”, “ignore that” and “dismiss”, which
mean nothing else here. The claim is now enforced instead of asserted: a test fails
if any mic answer is also a default confirm or cancel word, so adding a phrase to
either list re-runs the check.


### Fixed — `yazses features` went ragged as its own list grew

The table's columns were fixed *minimum* widths, so any name or toggle longer than
them pushed DOWNLOAD and ADVICE right for that row alone. With 147 capabilities, 10
rows had drifted out of alignment — and `overlay-reduced-motion`, added in 2.23.0,
made it 11. Nothing failed, because nothing was looking at it.

Widths are now measured across every row the table will show, so the groups line up
with each other too. The two columns are treated differently on purpose: **TOGGLE
NAME grows to fit and is never truncated**, because it is copied into `yazses
features enable <name>` and a clipped slug is a command that does not run; NAME is
prose and is clipped with an ellipsis, since sizing to the longest display name
would widen all 147 rows by nine columns to accommodate two.

Guarded, including against the naive fix: one test pins that every row's ADVICE
column starts at the same offset, a second that every slug appears intact, and a
third that the registry still contains a slug longer than the old fixed width — the
first two are vacuous on a table with nothing long in it.

## [2.23.0] - 2026-08-16

### Added — the mic guard's question can be answered out loud (`[audio] voice_answer`)

The mic-change guard is the one part of the pipeline that *asks* rather than tells:
when capture moves, or a run of clips comes back silent, it offers **Re-calibrate**,
**Pin this mic** and **Ignore**. Those were buttons and only buttons, so the daemon
interrupted you with a question about your microphone that could only be answered
with a pointer — and the person seeing it is the one whose dictation has just
stopped working, which is the worst possible moment to be sent to the mouse.

ADR-022 counts this as one of exactly two daemon-initiated states with no voice-only
exit. This is the half that needs no change to the command-safety gate: the three
actions are already dispatched from a string key, so the spoken route reaches the
same handler as the click and the two cannot drift apart.

Two limits do most of the work, and both are about *not* firing. The whole utterance
must be the answer — "please ignore the second paragraph" is prose and gets typed,
the lesson `commands/revise.py` already learned by anchoring at both ends. And the
words only count inside `voice_answer_window_s` (default 45 s) of the toast; an
unbounded window would arm "ignore" as a control word for the rest of the session,
and once it closes the word types normally rather than being swallowed.

It runs after `[cmdsafety]` and `[checkdigit]` and before staged dictation, and both
halves of that position are decisions: a held `rm -rf` keeps first claim on the
utterance, and the staged buffer would otherwise swallow the answer as ordinary
text. An AST guard pins the order.

Off by default, like the other guards that consume a burst which would otherwise be
typed. That leaves Spec 1's metric at 2 until it is switched on, which is worth
saying plainly rather than claiming the baseline moved.

### Added — the overlay can stop moving (`[overlay] reduced_motion`)

The voice-activity overlay expands rings outward from near the pointer, sixty times
a second, for as long as you hold the key. That is the pattern people with
vestibular disorders and motion sensitivity ask software to stop doing, and every
desktop already carries a setting where they have said so — GNOME's *Reduce
Animation*, macOS's *Reduce motion*, Windows's *Animation effects*. YazSes read
none of them. `docs/assets/extra.css` has honoured `prefers-reduced-motion` on the
documentation site for months: the site respected the preference, the accessibility
product it documents did not.

`[overlay] reduced_motion` is `auto` | `on` | `off`, defaulting to `auto` — follow
the desktop. A desktop YazSes cannot read resolves to full motion, which is exactly
what the overlay did before, so nobody's overlay changes on the strength of a failed
probe; KDE, Xfce and bare window managers set `on` explicitly.

Reduced motion removes **motion, not information**. The overlay answers one question
— am I being heard, and how loudly — and a user asking for less animation has not
asked to stop being told. So the reduced form keeps the ring and drops the travel:
one steady circle while recording, brightness following your voice in four discrete
bands. Discrete because a brightness recomputed each frame from a live microphone
shimmers, and a shimmer at 60 Hz is its own accessibility problem rather than a fix
for one. It also shows the ring during silence, which the animated form does not —
tolerable when rings are about to appear, not when none ever will.

The desktop is asked once at overlay startup, never on the render tick, and the
probe never raises: an indicator that failed to appear because a settings key could
not be read would be a worse bug than the one this fixes.

Both accessibility settings are listed by `yazses features` (`mic-voice-answer`,
`overlay-reduced-motion`) rather than living only in prose. An opt-in accessibility
capability nobody can find is one nobody switches on. Disabling `overlay-reduced-motion`
restores `auto` rather than writing `off` — overriding a user whose desktop asked for
less motion is a different opinion, not an off switch.

### Added — an example config must say what was observed, not what should work

`examples/config.<app>.toml` files are copied verbatim by newcomers, so a wrong one
costs more than no one at all. Three checks already guarded them: valid TOML, every
key resolving to a real field on a real section, and an opening comment. All three
pass just as happily on a profile nobody ran — valid TOML, real keys, real values
and a header can be written without the application ever being opened, and that is
the failure the task issues warn about in as many words.

The 14 app profiles in the tree already record what was seen, several with the
dictated and arrived text side by side. Nothing enforced it. `check-app-profile.py`
and the test suite now do, with `config.example.toml` (the generic template) and
`config.terminal.toml` (a per-use-case example) exempt by name, because neither
names an application to have been observed in.

The check lives in the script rather than only in the suite, and that placement is
the point. A fork PR from a first-time contributor arrives with every real workflow
held at `action_required`, so the suite cannot see the file until a maintainer
clears it; the script runs on the contributor's own machine, while they can still
fix it. It cannot detect a fabricated marker word and does not claim to — it makes
the requirement mechanical rather than remembered.

A marker word inside an unresolved `TODO` does not count. The review on PR #309
handed the contributor a starter file headed `TODO(you): replace this block with
what you actually observed.` — and the word "observed" in that instruction satisfied
the check on its own, so the likeliest next submission would have passed it by
quoting the instruction to fill it in. TODO lines are skipped rather than the file
being rejected for containing one, because a profile that says "TODO: not tested on
Wayland" is doing exactly what these files are for; it is only the *evidence* a TODO
cannot supply.

### Fixed — ruff was told `_common` is a stranger, and its autofix acted on it

`paper/benchmark/` is the reproducibility code `docs/benchmarks.md` points readers at,
and it sits outside the `src tests scripts` the gate lints, so it had drifted to seven
findings — two genuinely unused imports and five unsorted import blocks.

The interesting half is why the autofix was not simply safe to apply. The nine benchmark
scripts import a sibling helper as a bare `from _common import …`, because they run from
that directory, and every one of them keeps it in its own block. Ruff had no way to know
that and read it as third-party, so `--fix` folded `_common` in among `jiwer` and `numpy`
— a correct-by-its-own-lights rewrite of a grouping the author chose. `known-first-party
= ["_common"]` teaches it, after which the fix touches only what is actually wrong: one
file that had been "broken" dropped out of the diff entirely.

The lint *scope* is deliberately unchanged. `src tests scripts` is a recorded decision —
`.devcontainer/setup.sh` once said `ruff check .` and exited 1 on a clean checkout — and
widening it is not a cleanup.

## [2.22.0] - 2026-08-16

### Fixed — six ways YazSes starts itself, five of which could not work in a bundle

The audit that followed the Windows Settings… bug, which was not a one-off. Every
component that spawns another one — the daemon launching the tray and the overlay,
the Settings window's Restart, the macOS and Linux lifecycle backends starting the
daemon — used `[sys.executable, "-m", "yazses.x"]`.

That is correct for a pip, pipx or uv install and silently wrong inside the shipped
`.app` and `.exe`. There, `sys.executable` is the application, not an interpreter;
the bundle dispatches on argv; and an unrecognised first argument falls through to
the CLI, which exits 2 with no console to print to. So in a bundle the tray never
appeared, the overlay never appeared, the crashed-tray supervisor's five relaunch
attempts each did nothing, and Apply→Restart never restarted — with no error
anywhere. They now go through one resolver that asks the bundle by its mode flag.

Three further defects came out of writing it down:

- **The macOS Settings button pointed at a file that does not exist.** The earlier
  fix named a `yazses-cli` sibling on any frozen non-Windows build, and the macOS
  `.app` ships exactly one executable. Its test asserted that behaviour, so the bug
  was green. The sibling is now tested for rather than inferred from the platform.
- **The overlay had no argv a bundle would accept at all** — `__main__.py` carried no
  `--overlay` branch, so it was unreachable from a bundle by construction.
- **`python -m yazses.cli --version` printed nothing and exited 0.** No
  `if __name__ == "__main__"` block, so the module was imported and discarded. That
  is the documented last-resort launch path, taken by exactly the installs with no
  other way to report a failure. Both it and `yazses.settingsui.app` now have one.

A console script **beside the running interpreter** is now preferred over PATH. This
machine carries a pipx copy, a `uv tool` copy and a checkout venv at once, and the
checkout's `yazses` shadows the installed one — so PATH-first meant a daemon from one
install could launch the tray from another, disagreeing about config, version and
socket.

Settings goes through its own `yazses-settings` gui-script, so on Windows it is
launched by `pythonw.exe` and opens no console behind the window.

The frozen paths cannot be exercised where this was written — no bundle, no Windows,
no macOS — so every input is injectable and the decision is tested rather than the
spawn. Proof on a real bundle is still owed.

### Added — the Settings window's threshold slider has a live level meter

Hold your dictation key and speak: the bar shows whether you are clearing the
silence line, and re-judges as you drag the slider, so you can see when you have
moved it far enough. Without it the slider is a person guessing at a float.

It was deferred on a reason that turned out to be wrong — "it needs an audio stream
in the window". It does not. The daemon already publishes `audio_level` in its
status reply; it is what the tray's level ring has been drawing for weeks. The
window asks the same running process, which is also the only correct answer: a
second capture stream would fight the one dictation uses.

Running it against a live daemon caught the defect that mattered. `audio_level`
only moves during a hold, so at rest the meter read 0.0 and announced *"below the
line — audio this quiet is discarded as silence"*: a claim about the user's
microphone made at a moment when nothing was listening. It now says so instead.

### Changed — the macOS bundle is half the size it was

143.9 MB → 70.4 MB for Apple Silicon, measured across two builds of the same commit.
`uv sync` was installing the **dev group** — pytest, mypy, ruff, hypothesis, a
moonshine ONNX model — into the environment PyInstaller then analyses, so a linter
and a test runner were being shipped inside the application.

The Intel bundle did not move (88.96 → 88.95 MB), which is the confirmation rather
than an anomaly: that leg installs the project alone and never carried the dev group.
Windows saved less than 3 MB — its spec already excluded most of it — and is changed
for the same reason regardless.

### Fixed — the Intel .dmg and the ARM64 .exe have not been built for two releases

Both cross-architecture bundle legs were failing, and both workflows reported
success: they are `continue-on-error`, which is right for a new cross-arch job and
means the failure appears nowhere a person looks — not the run summary, the checks
list, or the release page. v2.21.0 shipped neither file.

macOS Intel died on `uv sync`: the lock pins onnxruntime 1.28.0, which upstream
publishes for macOS arm64 only, and faster-whisper requires onnxruntime with no
marker. That leg now resolves unlocked, where it backtracks to the last release
with an Intel wheel. Pinning the project back below 1.24 would have cost every
other platform two years of runtime for one architecture Apple has already
scheduled for removal. `pipx install yazses` on Intel resolves the same way and was
never affected — it was the bundle that was missing, not the path.

Windows ARM64 died before compiling anything, asking `uv` for an interpreter it had
no build of: `setup-uv` was pinned to `0.5.x` in these two workflows and `latest`
in the other five. That pin predates Windows ARM64 Python entirely. With it lifted
the leg produced a 160 MB `YazSes-2.21.0-windows-arm64.exe` on its first run — the
first native Windows ARM installer this project has built.

`test_platform_support_claims.py` now cross-checks both build matrices against
`docs/platform-support.md`, so an advisory leg can never be written up as a shipped
one, and a blocking leg can never be left understated.

### Fixed — every Linux arm64 channel was documented as unavailable, and all of them work

Measured against the Snap Store API, the published APT index and the `.deb` control
fields rather than this repository's manifests. The snap has an arm64 build on
`stable`, not edge-only. The `.deb` declares `Architecture: all` and contains no
compiled code, so the `amd64` and `arm64` release assets are the same package with
different names — the architecture in the filename is the build host's — and the
APT repo has therefore served arm64 all along.

arm64 users were being sent to a slower install path for something they already
had. Documentation drift is usually an overclaim; this one cost people support that
existed.

### Fixed — the tray icon's mark was unreadable on two of its five states

The "Y" was painted white on every state colour. Measured with the contrast maths
already in the codebase, white scores **1.71:1 on yellow**, 3.06 on green and 4.23
on red — against WCAG AA's 4.5. Three of five failed, and the worst by a distance
is yellow, which is the badge meaning *"recording, but there is nowhere to type"*.

That is the state a user most needs to notice, wearing the least readable mark of
the set. An icon that says "your words are going nowhere" and cannot be read is not
doing the one job it exists for.

The glyph colour is now chosen by contrast, per badge — black on yellow, green, red
and blue; white on purple. Yellow goes from **1.71:1 to 12.30:1**, measured on the
rendered icon. Both Linux and Windows share the decision, so they cannot diverge.

Black or white rather than a computed tint: at 16 px the mark is a few hundred
pixels of stroke, and a mid-tone loses to the badge whatever the maths says.

`settingsui/theme.py` has computed contrast since the Settings window's secondary
text was found failing AA on both themes. This is the first time anything else has
used it — the tray is where it was most needed and least applied.


### Added — an agent can ask you a question out loud, and hear your answer

ADR-020 decided that the genuinely novel thing YazSes can offer another agent is not
transcription — it is **a human**. An agent stalled on a decision only a person can
make has, until now, one route: put text on a screen and wait for someone to notice,
read it, and type. Voice is the cheapest interrupt a working person can service,
because it needs neither their eyes nor their hands.

`ask_human(question, timeout_s)` is now the MCP server's second tool. It speaks the
question, listens for the spoken answer, and hands it back to the calling agent.

**Off by default**, and it stays that way until `[mcp] ask_human = true`. It is not
even listed until then: a tool that is offered and always refuses teaches a model to
stop calling it.

The restraints are the feature, not decoration — ADR-020 says it "ships with these,
or does not ship":

- **A budget.** `[mcp] ask_human_per_hour` (default 3), shared across every caller
  because it protects the person rather than each agent's fair share. Nothing a
  caller does earns another slot; a refusal says when the next one frees.
- **Never during a hold.** If you are mid-sentence the daemon knows, and the question
  waits — without costing the agent a slot, since that would punish it for your timing.
- **The caller is named** in what is spoken, so "who is asking" is never ambiguous.
- **The answer goes back to the caller, never into the focused window.** This is why
  it lives in the daemon rather than the MCP server: the daemon owns the microphone,
  knows about the hold, and owns the injector that must not fire.
- **A question that could not be asked costs nothing** — no speakers, a busy device,
  or you walked away. An agent should not lose its hour to a question nobody heard.

Silence is reported as silence rather than as an empty answer, because "they said
nothing meaningful" and "they never answered" are different facts an agent will act
on differently. A caller's timeout is capped at two minutes: an agent asking for an
hour is holding the microphone hostage.


### Added — the microphone and the silence threshold are in the settings window too

The remaining two settings that are values rather than switches. `settingsui/controls.py`
was written for exactly these three, tested, and called from nowhere; all of it is
now wired.

**Microphone** mirrors `yazses audio devices`, marks and all — ● the system default,
★ the pinned one — with *Follow the system default* first, because that is the state
most people should be in. If audio cannot be enumerated at all (no sound card, a busy
device, a container) the dropdown is empty and the window still opens: refusing to
show every other setting because a microphone is missing would be the worse failure.

**Silence threshold** is a logarithmic slider with the exact value beside it. The
range spans three orders of magnitude — ≈0.0005 for a quiet voice, ≈0.05 for a noisy
room — so a linear slider would put every usable value in the leftmost few pixels,
and a slider without a readout is a user guessing at a float.

It writes an unquoted number, so the value stays a float rather than becoming the
string `"0.004"` for the config loader to repair. And the untouched slider writes
nothing: comparing the resulting floats made an idle Apply rewrite the key every
time, because quantising 0.01 through 1000 integer steps returns 0.01001.

### Added — the hold-to-talk key can be changed from the settings window

The key you hold to dictate is the most personal setting YazSes has, and it could
only be changed by typing a command or editing TOML. The settings window offered
feature checkboxes and nothing else — even though the validation for a hotkey
picker was already written, already tested, and had no caller.

**Settings → Hold-to-talk key** is a dropdown, not a press-a-key capture: the
backends bind eleven specific keys, and a capture box would happily accept F13 and
leave you unable to dictate with nothing on screen connecting the two. It offers
the same list as `yazses hotkey set`, refuses before writing, and applies on Apply
with the usual restart prompt.

It also refuses a key that is already the **command key**, comparing through the
aliases — `right_option` and `right_alt` are one physical key under two names, so a
string comparison waves that clash through and command mode then swallows every
dictation burst.

### Fixed — the command key could be set to the dictation key on a default install

Two ways, both silent. The check compared `[hotkey] command_key` against the raw
`[hotkey] key`, which on a fresh install is the sentinel `"auto"` — never equal to
a real key name, so the clash was invisible on exactly the config every new install
starts with. And it compared strings, so `right_option` against a dictation key of
`right_alt` sailed through as different names for one physical key.

### Fixed — `yazses hotkey set right_option` was refused by a key every backend binds

Four copies of the accepted-keys list existed: a private `_KEY_MAP` in each of the
three platform hotkey backends, and `_HOTKEYS` in `cli.py` carrying the comment
*"mirror platform/linux/hotkey.py keymap"*. The mirror had drifted. Every backend
binds `right_option` and `left_option` — macOS's names for the alt keys, present so
one config file behaves the same on all three systems — and the CLI rejected both:

```console
$ yazses hotkey set right_option
Unknown key 'right_option'. Choose one of: right_alt, left_alt, ...
```

So the config file accepted a key the command that writes it would not.

The list now lives once in `yazses/hotkeys/names.py`, and a test reads every
backend's `_KEY_MAP` to prove the offered set is bindable on all three — the
direction that matters, since offering a key nothing can bind leaves someone unable
to dictate with no explanation.

### Fixed — the tray's **Settings…** could not open the settings window on the Windows installer

Clicking **Settings…** in the tray produced a notification reading *"Could not open
Settings — is `yazses` on PATH?"*, and nothing opened. Reported from a live Windows
install.

Every tray backend — Linux, macOS and Windows — launched the window with the literal
`["yazses", "settings"]`, which assumes a console script on PATH. The PyInstaller
bundle has no such thing: it ships `YazSesApp.exe` and `yazses-cli.exe` beside each
other and puts neither on PATH. So the button was impossible on precisely the build
whose users are least likely to have a terminal to fall back to — and the message,
while accurate, asked the user to fix an assumption the application had no business
making.

`tray/launch.py::settings_command()` now resolves it once for all three backends: a
frozen bundle uses the `yazses-cli` sitting next to the running binary, otherwise a
console script on PATH, otherwise `[sys.executable, "-m", "yazses.cli", …]` — which
works for any interpreter that can import the package. PATH is deliberately not
consulted first when frozen: a machine can carry both the installer's app and an old
`pip install`, and the stray one would silently open another version's settings.

The same argv now backs the tray's **Restart**, which had the identical assumption.

### Changed — every `yazses` command starts in about half the time

`yazses status`, `yazses stop`, `--help`, and the completion that runs on every Tab
all import `yazses.cli` first. Two things at module scope were charging them for
work they never did: `yazses.system.updater` pulled in `urllib.request` and
`http.client` — a whole network stack — for the benefit of `yazses update` alone,
and `import yazses` resolved the installed version through `importlib.metadata`,
which walks `sys.path` hunting for a `.dist-info` and was the single most expensive
import in the tree.

Both are now deferred to the point of use: the updater imports inside `update()`,
and `__version__` resolves on first access (PEP 562) and is cached thereafter.
Measured on the development machine, importing `yazses.cli` fell from **181 ms to
110 ms — a 39% reduction**. Nothing changes about *what* the version says; only
when it is read.

`tests/test_cli_startup_cost.py` pins it by asking a fresh interpreter which
modules an import actually pulled, rather than timing anything — a wall-clock
assertion would be flaky on a loaded CI runner, while "was this imported" is exact.

## [2.21.0] - 2026-08-15

Sixty-nine commits had built up behind `v2.20.0` without reaching anyone. The
theme, read back across them, is **things that were reported as working and were
not**: a CI job that could only ever be red, eleven tests that were skipped in
every job, three packaging guards that passed by iterating an empty list, a
CLI-reference guard that checked 58 names and ignored 50, a crashed daemon that
stayed dead on Windows and macOS while a tray watched and did nothing, and an
"Update installed" message for upgrades that never happened.

### Added — `yazses features` prices what it offers

The catalogue listed 145 capabilities and told you what none of them cost. The size
existed — `yazses features enable <name>` has printed it since ADR-018 — but only at
the moment the download began, which is after the decision, not before it. Three
capabilities (`cocktail`, `multiprofile`, `voiceguard`) resolve to ~3.1 GB each,
because `speechbrain` pulls PyTorch and the CUDA stack behind a name that reads like
a small audio filter.

`yazses features` now carries a **DOWNLOAD** column. It quotes the whole dependency
closure on a fresh install, which is the honest figure for a table anyone reads;
`features enable` keeps quoting what is missing on *your* machine, which is the
figure you actually pay. Blank means nothing to download — true of most capabilities,
since they are pure logic that ships in the base install.

The number is a lookup in a table that ships inside the package, so the listing stays
offline and instant (ADR-011, ADR-018). A capability whose size is unknown shows
nothing rather than a guess.

New: **[Install only what you need](docs/how-to/install-only-what-you-need.md)** — how
to read the column, what the advice tiers mean, and how to keep a dictation-only
install small.

### Security — the open `diskcache` advisory now has a published assessment, pinned by tests

Dependabot has an open alert on `diskcache` ≤ 5.6.3 (unsafe pickle
deserialization) with **no patched release upstream**, so it cannot be closed by
bumping a version. It appears in every supply-chain scan run against this
repository, and there was nowhere to read what it means here. An unanswered alert
is not neutral: it is how the *next* finding gets waved through by someone who has
learned the alerts are noise.

It is not exploitable as shipped, and `.github/SECURITY.md` now gives the
reasoning rather than asserting the conclusion. `diskcache` is not a dependency of
YazSes; it arrives only under `llama-cpp-python`, which is opt-in (`slm`, `notes`
and `all` extras, never `project.dependencies`), so a default install never
downloads it. And the vulnerability requires a cache file to be unpickled —
`llama_cpp` reads one only when a caller installs a cache via
`Llama.set_cache(...)`, which YazSes never does.

Both of those are load-bearing claims about this codebase, and this project has
already shipped changelog entries describing code that was never on `main`. So
`tests/test_dependency_advisories.py` pins them: the suite fails if
`llama-cpp-python` becomes a base dependency, if anything starts touching a
llama-cpp cache or importing `diskcache`, or if the assessment disappears from the
policy while the guards remain. It also asserts the AST scanner can still match a
real call — a security detector that silently stops matching reports "all clear"
forever, which is the worst failure available to it.

### Fixed — a CI job that could only ever be red, for weeks

The `freebsd` leg had failed on **every** run, `main` included. Being advisory it
blocked nothing; it simply made a red X in Tests look normal, which costs more
than the coverage it was meant to add, because the next red X gets the same shrug.

It was never a FreeBSD problem. `pip install -e .` resolves `faster-whisper` →
`ctranslate2`, and PyPI has neither a FreeBSD wheel **nor an sdist** for it — pip
reports `from versions: none`, so there was nothing to build from either. The job
died on an unsatisfiable install before running a single test.

The coverage it exists for never needed that stack: the claim under test is that
FreeBSD really selects and builds the composed BSD backend, which needs
`sys.platform` to genuinely be `freebsdN`, not a transcription engine. Measured in
a clean venv, all 48 tests in `tests/test_platform_bsd_and_fallback.py` pass with
numpy, platformdirs and typer alone. The job now installs `--no-deps` plus those
and runs exactly that file; the suite-wide run is gone rather than tolerated,
since most of it imports the transcription stack and would reinstate the permanent
red. **CI is now green on every job for the first time.**

`docs/platform-support.md` said "nobody has run YazSes on real BSD hardware" and
that the job "has never got that far". Both were true when written and are not
now, so the page has been corrected — including the part that has *not* changed:
nobody has dictated a word on BSD, because the speech pipeline still cannot be
installed there. The row stays ⚗️ for that reason, not for the platform layer.

### Fixed — eleven tests behind an optional extra were skipped in every job

`uv sync` installs base dependencies only, so any test guarded by an optional
extra skipped in the main job — and until now, in *every* job. Fourteen tests were
reporting green while executing nothing.

This is the hole the GUI job was built to close, still open for four other extras,
and that precedent is the argument: the settings-window tests had been skipped in
CI for their entire life, and their first real execution immediately found two
shipped defects. A test that is always skipped is not a test.

The new `extras` job covers the extras whose cost is trivial. `chinese` is a
single pure-Python package, and installing it takes `tests/test_han_script.py`
from 30 passed / 11 skipped to **41 passed** — eleven assertions about Simplified
vs Traditional output that had never run anywhere, on a code path a user in Taipei
hits on every utterance, and one that has already produced a real user-visible bug
in this project.

Built like the GUI job, because the failure mode is identical: import the extra
explicitly first, run with `-rs`, and fail the job on any `SKIPPED` line. Three
tests stay uncovered — `notes`/`slm` compiles a C++ inference engine, and
`diarization-pyannote` and `voiceprint-resemblyzer` each pull torch (~2 GB). That
is a real gap, and it is named in the job rather than hidden behind a green tick.

### Fixed — three packaging guards passed on an empty set, and now the rule is mechanical

`for path in SOMEWHERE.glob("*"): assert <property>(path)` is green in two
situations: every file satisfies the property, and **there are no files**. The
output is identical, and the second is what a rename, a moved directory or a
changed suffix produces — which is exactly when the guard was needed.

Found three times in one day, which is what turned it from a bug into a rule:

- Four checks globbed `README.*.md` at the repo root. The translations moved to
  `docs/<lang>/index.md` and all four went quietly green while checking zero files.
- `test_cli_reference_covers_every_command.py` read only the top level of the Click
  tree, so ~50 subcommands behind 15 groups were never looked at.
- The three fixed here: `test_the_winget_identifier_is_the_current_one` and
  `test_no_packaging_file_still_names_the_retired_org` (which passed with
  `packaging/` **absent entirely**), and
  `test_the_repo_ships_a_locale_manifest_for_every_winget_version` — that last one
  guards a defect that has already shipped once, a winget submission missing its
  `defaultLocale`.

Each was proved vacuous first, by pointing it at an empty directory and watching it
pass, then fixed by binding the glob to a name and asserting it non-empty — the
idiom the repo already used in `test_docs_current_version_claims.py`.

`tests/test_repo_hygiene_vacuous_guards.py` now walks the suite's own AST and fails
on the shape, so the fourth occurrence is caught by a machine rather than by
someone happening to look. It carries its own detector test: a check for a silent
failure that fails silently is the same bug one level up.

### Fixed — the CLI-reference guard checked 58 command names and ignored the other 50

`tests/test_cli_reference_covers_every_command.py` exists because three commands
once shipped with no entry in `docs/cli-reference.md`. It walked
`typer.main.get_command(app).commands` — the **top level only**. Fifteen of those
58 names are groups carrying roughly fifty subcommands between them, and the guard
never opened one: `yazses meeting` appearing anywhere in the document made the
whole group look documented.

Two had drifted through the hole. `yazses meeting enroll` — the command that names
a speaker for good, as opposed to `relabel`, which fixes one transcript — and
`yazses gaze status` were both in `docs/command-index.md` and both in the man page,
and in neither case in the reference the docs site links as canonical.

- The guard now walks the tree and asserts every invocable path, groups included.
- It descends by asking for `.commands`, **not** by `isinstance(cmd, click.Group)`:
  under Click 8.4, `typer.core.TyperGroup` does not subclass `click.Group`, so an
  isinstance walk finds no subcommands at all and passes while checking nothing —
  the same silent pass, reintroduced by the fix for it. A second test pins that the
  walk really reaches the subcommands.
- Both missing commands are documented, with examples and the constraint that
  actually bites: `meeting enroll` needs the audio, which stop deletes unless
  `[meeting] retain_audio = true`.

### Fixed — a crashed daemon stayed dead on Windows and macOS, watched by a tray that did nothing

Linux gets this for free: the systemd user unit carries `Restart=on-failure`, so a
daemon that dies comes back. launchd's `KeepAlive` does the same on macOS *when the
daemon is run as an agent*. The Windows autostart is an `HKCU\Run` value, which
fires exactly once at login and never again — so a daemon that crashed at 10am
stayed dead until the user logged out and back in.

The tray was already watching. It polls `status`, it had already gone red, and it
holds the lifecycle handle — it simply had no instruction to act. It now relaunches
a daemon it sees has died, bounded by `MAX_DAEMON_RELAUNCHES` with a
`RELAUNCH_COOLDOWN_S` gap, so a daemon that cannot start is not restarted forever in
a loop. The bound matters more than the relaunch: a crash-loop that reads as
"working" is worse than one that visibly stops.

Also relays what the daemon could not show. `system/notify.py` shells out to
`notify-send`, which exists only on Linux, so every self-healing event — the
microphone auto-heal, a VAD retune, a silent-streak warning — was **log-only** on
Windows and macOS. Those are precisely the events a user needs to see, because each
one means YazSes quietly changed its own behaviour. The daemon now queues them onto
its `status` reply and the tray shows them natively on whichever platform it is.

### Added — an Intel macOS build, and `.dmg` filenames that name their architecture

Implements [ADR-017](design/adr/adr-017-intel-mac-support-has-a-deadline.md). CI now
builds `YazSes-<version>-macos-x86_64.dmg` on `macos-15-intel` alongside the Apple
Silicon one, closing the gap [#264](https://github.com/MSKazemi/yazses/issues/264)
described — at no cost, since GitHub-hosted runners are free for public repositories.

**The rename matters as much as the new build.** The `.dmg` was called
`YazSes-<version>.dmg`, which reads as though it were for everybody — and that is a
large part of why an Apple-silicon-only bundle went unnoticed for months. Both bundles
now carry their architecture, and `build-macos.sh` derives it from `uname -m` rather
than taking a flag, because PyInstaller does not cross-compile: the build host *is* the
target, and a flag is a second thing that can disagree with the runner label.

The Intel leg is **advisory** (`continue-on-error`), exactly as the `windows-11-arm` leg
is: `macos-15-intel` has never completed a build here, and a brand-new
cross-architecture job must not be able to fail a release the primary build completed
fine. The Homebrew cask still tracks arm64 only, and will until the Intel build has been
green a few times — a cask whose hash is a guess is worse than no cask.

Renaming an asset is the change that breaks a download link silently: the URL still
resolves, to a 404, and a failed download is the first thing a new user sees. The cask,
the manifest refresher and the release notes were all updated, and
`tests/test_macos_artifact_naming.py` now pins the four places that have to agree about
the name and never see each other.

**The deadline is not ours.** `macos-15-intel` is the last x86_64 image GitHub Actions
will offer, available until **August 2027**; `macos-13` was retired on 2025-12-04. When
it goes, `pipx install yazses` is the Intel path that outlives it.

### Fixed — secondary text in the Settings window failed WCAG AA on every theme

The window styled its descriptions, hints and filter status with `color: gray` — a
literal `#808080`, repeated in five places. Measured against Qt's own defaults that is
**3.43:1** on the light window and **3.44:1** on the dark one, where normal text needs
**4.5:1**. Not marginally, and not on an unusual theme: on both of the backgrounds most
users actually have.

It is now computed from the desktop's own palette — the theme's text colour blended
toward its background only as far as contrast allows — so it reads as secondary and stays
legible whether the desktop is light, dark or something else. If a theme's *own* text
colour already falls below AA, the window leaves it unchanged rather than fading it
further; that is the theme's problem and making it worse would not help.

Measured cost: **0.33 ms** added across the five call sites at window construction, and
nothing at idle — it runs once per widget, not per frame.

For a project whose research pages argue that assistive technology is priced out of reach
and skips Linux, unreadable secondary text in its own settings window was the wrong detail
to get wrong. `tests/test_settingsui_theme.py` keeps the old value on record as a failing
case, so the change cannot later be mistaken for a matter of taste.

### Added — a dictated card number with a misheard digit no longer types

`checkdigit` had a complete, tested implementation of Luhn, ISBN-10, ISBN-13 and Verhoeff
plus single-digit fix suggestion — and no caller, so `yazses features enable checkdigit`
refused it. It is now wired, as the first step of
[ADR-021](design/adr/adr-021-invest-in-error-cost.md).

With `yazses features enable checkdigit`, a dictated number that *fails its own checksum*
is held and announced instead of typed, with the single-digit correction offered when
exactly one candidate passes. Release it with the same spoken **"confirm"** the command
safety gate uses — one release word, not one per guard.

**The design constraint is how rarely it fires, not how much it catches.** A guard that
stops a house number or a year teaches you to dismiss it, and a dismissed guard is worse
than none: it costs attention and catches nothing. So it only examines an utterance that is
a *bare* number (prose containing a number is prose), at least 12 digits, and failing
**every** scheme whose length it fits — a 13-digit string is not an ISBN-10, so ISBN-10's
opinion of it is noise. Anything satisfying an applicable checksum types with no comment.

Why this one first: a misheard digit is the cheapest error to catch and among the most
expensive to miss, because nothing downstream notices. It surfaces as a declined payment or
a wrong record, not as a typo.

### Added — the tray icon now shows whether your microphone is actually hearing you

The badge has five colours and every one of them describes what YazSes is *doing*.
None of them describes whether the microphone is picking anything up — and those two
come apart exactly when it matters: a muted mic, a USB-C monitor that stole capture, a
`vad_threshold` sitting above your voice. In all three the badge is green for
"recording", you speak a whole sentence, and nothing is typed. That is the symptom
behind [`silent-audio-discarding`](docs/how-to/silent-audio-discarding.md) and the
silent-streak guard, and until now the icon looked identical throughout.

While a burst is recording, the badge carries a **live input-level ring** with a notch
marking the silence gate. Short of the notch, what you are saying will be discarded;
past it, it will be transcribed. You find out *during* the sentence instead of after it.

The design decision that makes it readable on any machine: **the gate is anchored at a
fixed point on the ring** rather than the ring being a linear map of the raw level.
`audio_level` is `mean(|samples|)`, whose useful range depends on the microphone, the
room and the threshold — drawn linearly, a quiet setup would sit invisibly near zero and
a loud one would peg. Anchored, "past the notch" means the same thing everywhere.

No daemon change and no new IPC: `audio_level` and `vad_threshold` were already
published for the voice-activity overlay, and simply were not reaching the tray.

The ring is hidden whenever drawing it would say something untrue — when not recording
(a ring on an idle badge implies YazSes is listening, which is the one thing this icon
must never imply), when the threshold is missing or non-positive so the notch would have
no meaning, and when the status is malformed. It never raises: it runs inside the icon
paint path, where an exception loses the tray.

### Added — `yazses features` says what a capability will download, before it downloads it

Implements ADR-018's first decision. `yazses features info <slug>` now shows a **Cost**
line, and `features enable` prints the size before fetching anything — loudly, with a
Ctrl-C hint, when it is large.

The case that motivated it, now measured: **the three speaker-voiceprint features
(`cocktail`, `multiprofile`, `voiceguard`) download 3.1 GB across 37 packages.**
`speechbrain` resolves to PyTorch *and the entire NVIDIA CUDA stack* — cuDNN, NCCL,
cuSPARSE, cuSOLVER — none of which YazSes uses, because everything here runs on the CPU.
That is **7× the size of YazSes itself**, and nothing told the user before the progress
bar started. `[voiceprint] backend = "resemblyzer"` is the lighter alternative.

The full table is in [what installing costs](docs/install-cost.md); the range runs from
0.5 MB (`chinese-script`) to those 3.1 GB.

Three properties, each ruling out an easier implementation:

- **Marginal, not total.** The `tts`, `silero` and `parakeet` extras each name an
  `onnxruntime` that a base install already has via `faster-whisper`. Measured: `read-back`
  declares three packages and needs one; `stt-moonshine` declares one and needs **none**, so
  enabling it is free and now says so. The figure is computed against what is missing *on
  this machine*, which `deps.missing_modules` already answers.
- **Resolved closures, not wheel sizes.** `speechbrain`'s own wheel is a few MB. Pricing the
  wheel would tell a user a feature is cheap immediately before it fills their disk, so
  `scripts/gen-feature-sizes.py` resolves each feature with `uv pip install --dry-run`
  against a clean base environment and prices every distribution in the result.
- **Offline and instant.** The catalogue lists 144 capabilities and must render with no
  outbound connection (ADR-011). Sizes come from a committed table, never a live query — a
  stale number is acceptable, a hang is not.

A partially-installed feature is quoted as **"up to"** its full closure rather than
apportioned, because apportioning would be a guess and this is the direction to be wrong in:
told "up to 2.4 GB" and given 300 MB you are mildly surprised; told 300 MB and given 2.4 GB
you were misled about the only thing you asked. An unknown size shows **nothing** rather than
zero. A missing or corrupt table degrades the catalogue quietly instead of taking it down.

### Decided — show what a feature costs before enabling it; no third-party plug-ins

[ADR-018](design/adr/adr-018-feature-packs-and-the-plugin-question.md), answering "a user who
only wants dictation should install only what dictation needs, and anything more should come
as a plug-in".

Measuring first changed the answer. **That architecture already exists** — 21 optional
extras, lazy imports, on-demand install via `features enable`, models fetched on first use —
**and it is near its floor.** A base install is 414 MB, of which 84% is four binary wheels
that arrive with faster-whisper; YazSes' own code is 4 MB. The floor belongs to the speech
engine's dependency tree, and the one packaging lever with real leverage (Qt, 648 MB) was
already pulled in #259.

So the decision is about the two things genuinely missing: **`yazses features` will show the
marginal cost** of enabling a feature — marginal, because `tts`/`silero`/`parakeet` all
declare an `onnxruntime` that a base install already has, and a naive total would quote 53 MB
nobody downloads — and a **named `minimal` intent** with honest per-install-path figures.

**Third-party plug-in loading is declined, and this reverses ADR-009.** A plug-in would sit
on the dictation hot path with the microphone, the transcript and the injector — every word
the user speaks, and the ability to type anything anywhere. ADR-009 accepted "plugins run in
the daemon process and are trusted (no sandboxing)", and that was sound for the system it
described: a **Rust** core where plugin support sits behind a `python-plugins` cargo feature,
so a build without it *cannot* load foreign code. That core was never built. In the Python
daemon that shipped there is no build-time gate, so any plugin mechanism is live for every
install — including everyone who chose this tool for the promise in ADR-011. ADR-009 is
annotated in place, and ADR-018 records what would change the decision: a real isolation
boundary, which is the "v2 restricted sub-interpreters" ADR-009 deferred without costing.

### Fixed — the Flathub listing had no screenshots, and nothing in the repo read that file

[#45](https://github.com/MSKazemi/yazses/issues/45) records the closed Flathub submission
([flathub#9765](https://github.com/flathub/flathub/pull/9765)) as blocked on one thing: a
demo video. Reading `com.mskazemi.YazSes.metainfo.xml` turned up a second blocker nobody had
noticed — it had **no `<screenshots>` block at all**. That file *is* the store listing;
GNOME Software and KDE Discover render it and flathub.org indexes it as a page. Flathub's
linter flags a desktop-application with none, and the listing would have shipped with no
images. Four captioned screenshots added, and `tests/test_flatpak_metainfo.py` now guards
listing completeness — including that every screenshot URL resolves to a file that exists in
this repository and that its declared dimensions match the real image, which no linter checks.

Two stale claims corrected while there: `packaging/flatpak/README.md` said
`python3-yazses.json` was "**not committed yet**" and `.github/workflows/flatpak.yml` called
that "the single reason the submission has never been made" — it has been committed all
along, with 45 pinned wheels. New `packaging/flatpak/SUBMISSION.md` carries the resubmission
pack: why the bot closed the first PR (a custom description instead of the template), the
filled-in template body ready to paste, the `new-pr` base-branch requirement, and a shot list
for the video.

### Fixed — every release was fully attested and still scored 0/10 for signed releases

`b3c4197` added build-provenance attestations to the `.deb`, `.dmg`, `.exe` and the PyPI
wheel, `gh attestation verify` finds them, and [#116](https://github.com/MSKazemi/yazses/issues/116)
recorded OpenSSF `Signed-Releases` as done on that basis. The live Scorecard API still
reports **0/10 — "Project has not signed or included provenance with any releases."**

The attestations are real; they live in GitHub's attestations API. Scorecard does not look
there. Its `Signed-Releases` check reads the **filenames of the last five releases' assets**
and counts `.asc`, `.sig`, `.sign`, `.minisig`, `.sigstore`, `.sigstore.json` and
`.intoto.jsonl`. v2.20.0's assets are two `.deb`, a `.dmg`, an `.exe` and `SHA256SUMS.txt` —
nothing a verifier can see. The signing was never the gap; publishing it was.

All three release workflows now attach the attestation bundle from the attest step's
`bundle-path` output as a `.intoto.jsonl` asset. That is worth doing beyond the score: it
lets someone who downloaded an artifact and is now offline verify it against a file that came
with it, instead of an API call they cannot make. `tests/test_release_provenance_assets.py`
holds it structurally across all three workflows, since the previous failure was one of them
silently diverging.

### Changed — Intel Mac support has a published end date, and it is GitHub's, not ours

[#264](https://github.com/MSKazemi/yazses/issues/264) asked whether to *pay* for an Intel
macOS runner or declare Apple silicon only. Both premises were stale. GitHub Actions is free
for standard runners on public repositories — this repo already runs `macos-latest` on every
push and every tag — so an Intel leg costs runner minutes, not money. And `macos-13`, the
Intel image the question assumes, was **retired on 4 December 2025**.

The answer is neither option: build Intel now on `macos-15-intel`, advisory like the
`windows-11-arm` leg, and write the deadline down. That label is the **last** x86_64 image
Actions will offer, available until **August 2027**, with x86_64 macOS support ending in Fall
2027. Recorded as [ADR-017](design/adr/adr-017-intel-mac-support-has-a-deadline.md), with the
horizon now stated on the platform-support page so an Intel Mac owner can see that
`pipx install yazses` is the path that outlives the bundle.

### Added — the Command Safety Gate is wired: a misheard `rm -rf` now waits for "confirm"

`cmdsafety` had a designed, unit-tested classifier, a config section, a registry
entry and a feature-page description — and no caller, so `yazses features enable
cmdsafety` refused it and the page said "not possible yet". It is the shape issue
[#164](https://github.com/MSKazemi/yazses/issues/164) describes: the algorithm was
never the missing part, the door was.

Dictation into a shell fails differently from dictation into a document — the
mistake *executes*. With `yazses features enable cmdsafety`, a destructive dictated
command (`rm -rf`, `mkfs`, `dd of=`, `curl | sh`, `git push --force`, a fork bomb) is
held and announced instead of typed, and runs only after you say **"confirm"**. Say
anything else and the held command is discarded and your words are typed normally —
there is no modal state to get stuck in, and the gate only ever fails in the
direction of *not* running the command.

**It judges the command text, not the focused window.** The feature was designed as a
*terminal* gate, and the obvious implementation asks the focus detector what has
focus. That answer is unavailable exactly where the guard matters most: focus
detection needs AT-SPI or X11, so on Wayland without AT-SPI the window class is
empty, and a guard that silently stops protecting on a whole display server is worse
than none. The patterns are specific enough that prose almost never matches; a false
positive costs one spoken word, and the reverse mistake cannot be undone.

Control words must be the **whole** utterance — "cancel the meeting" is dictated
text. Loose matching of ordinary English words is how a previous wiring attempt in
this repo swallowed 4 of 6 test phrases, and `cmdsafety/spoken.py` anchors for the
same reason `commands/revise.py` does. Emptying `confirm_words` falls back to the
defaults rather than leaving a held command unreleasable. New guide:
[Stop a misheard command from running](how-to/command-safety.md). Off by default.

### Fixed — PyPI was told YazSes supports two Python versions; CI proves four

A cross-platform support audit compared every claim the project makes about
operating systems and interpreters against what the code does and what CI actually
runs. The prose came out clean: `docs/platform-support.md` and
`docs/capability-matrix.md` match the code row for row, and the "macOS 11 (Big Sur)
or newer" floor turns out to be exactly the floor its dependencies impose —
`ctranslate2` publishes `macosx_11_0` wheels for both `arm64` and `x86_64`, which
also confirms that Intel Macs really can install via `pipx`.

The drift was in the metadata nobody reads by eye. `pyproject.toml` claimed
`Programming Language :: Python :: 3.11` and `3.12` only, while the test matrix has
been running the full suite on **3.13 and 3.14** since they were added. PyPI renders
those classifiers as the project's own answer to "does this run on my Python?", and
distro packagers and dependency dashboards filter on them without ever seeing a CI
matrix — so support that had been green for weeks was invisible to exactly the
people who cannot check it another way. Both classifiers are added.

`tests/test_platform_support_claims.py` now holds the invariant in **both**
directions, so a matrix entry without a classifier, or a classifier with no matrix
entry behind it, fails the suite. It also pins one deliberate omission:
`Operating System :: POSIX :: BSD` stays absent. A BSD backend ships and is
unit-tested, but `pip install yazses` cannot succeed there — `ctranslate2` has no
BSD wheel and no sdist ([#306](https://github.com/MSKazemi/yazses/issues/306)) — and
a classifier asserts that the install works. That claim becomes true when the
install does, not when the list is tidied.

### Fixed — `uv.lock` still recorded the project as 2.18.2 after two releases shipped

Found while re-locking for the audit above. `uv.lock` carries its own
`[[package]] name = "yazses"` version entry, and nothing regenerates it except an
actual `uv lock`/`uv sync` — so v2.19.0 and v2.20.0 both shipped with the lock
naming the version before them. `test_sbom.py` did not catch it: that guard
compares the *dependency* graph against the lock, and both sides were consistent
the entire time. The project's own version entry had no guard at all.

This matters because `uv.lock` is committed precisely so a fresh clone can
reproduce the environment a release was built and tested in, and it is the file a
downstream packager or auditor reads to answer "what was in this release?" — a lock
that misnames the thing being locked makes that record ambiguous.
`test_packaging_metadata.py` now pins it to `pyproject.toml`.

### Fixed — every Windows install was told to update itself with `pip`

`yazses update` detected the install method from three path substrings and fell
back to `pip` for everything else. There is no fourth branch, so **every** Windows
install — the Inno `.exe`, Chocolatey, winget, Scoop — came out as a pip install
and was told to run `pip install --upgrade yazses`. Inside the PyInstaller bundle
there is no pip to run it; where a system pip exists elsewhere on the machine, that
command installs an unrelated second copy into some other Python, prints success,
and leaves the `.exe` the user actually launches sitting at the old version. An
upgrade command that exits 0 without upgrading anything is worse than none.

- **The Windows channels are now first-class install methods** —
  `windows-installer`, `choco`, `winget`, `scoop`. Detection reads `sys.frozen`
  (PyInstaller) and Chocolatey's package marker rather than guessing from a path,
  and is injectable so the classification is tested on every OS.
- **They are checked against the GitHub release, not PyPI.** The `.exe` is a
  release asset; PyPI carries no `.exe` and has, in the past, lagged a tag
  entirely — so asking PyPI about a Windows install could answer "up to date"
  when it was not. Drafts and prereleases are refused: their tags exist before
  the assets do.
- **`windows-installer` has no upgrade command, and says so with steps.** The
  upgrade is a downloaded `.exe` and there is nothing safe to shell out to, so the
  CLI and the tray print the four steps to do it, plus the `winget` / `choco` /
  `scoop` one-liners for people who installed through a package manager.
- **The Chocolatey, Scoop and winget manifests were still pinned to 2.19.0** after
  v2.20.0 shipped, so `choco upgrade` / `scoop update` / `winget upgrade` would
  never have found the new release at all. Refreshed against the real v2.20.0
  assets; `tests/test_platform_windows_hardening.py` was already red on this.

### Fixed — a blocked update check read as a broken YazSes

`yazses update` answered a failed lookup with "Could not determine the latest
version" and exit 1. Behind a firewall or a corporate proxy — the same
configuration that produced #310 — that is all the user got: no reason, no way
forward, and the strong implication that YazSes itself was broken. It is not.
Dictation is entirely local and a blocked update check changes nothing about it.

The failure path now says that in the first line and then prints the steps that
still work, per install method. Same in the tray, and after an upgrade command
that failed.

### Added — an opt-in check that tells you once when a new release lands (off by default)

Nothing in YazSes ever announced a new version; you had to remember to run
`yazses update`. `[general] update_check` adds a background watcher that notices a
newer release and shows one desktop notification with the exact steps to install it.

It **ships off**, and that is deliberate rather than cautious: this is the only
thing in YazSes that opens an outbound connection on its own, and "nothing leaves
the machine" is the product, not a preference. Enabled, it sends a plain "what is
the latest version" GET to github.com or PyPI — no voice, no text, no config, no
identifier — but that is still a choice the user makes. Turn it on with
`yazses features enable update-check`.

Three properties it holds when it is on: it runs on its own thread and swallows
every failure, so a firewall makes it a silent no-op and never touches dictation;
it announces a version once rather than once per check, and a newer release
re-arms it; and the notification carries the update steps, so a Windows-installer
user is not told "2.21.0 is available" with nothing to act on.

### Fixed — the benchmarks page told readers to run a harness that was not in the repo

`docs/benchmarks.md` is public and its whole claim is that "every number on this
page … can be reproduced with the commands at the bottom". Those commands were
`git clone`, `uv sync --group benchmark`, and `paper/benchmark/run_all.py`. All
three failed: `.gitignore` excluded the entire `paper/` tree (confirmed — the path
404s on GitHub), and the committed `pyproject.toml` had no `benchmark` dependency
group, because the group only existed in a private copy of the file. A page whose
credibility rests on reproducibility was not reproducible by anyone.

`paper/benchmark/` is now published — 11 files, ~84 KB of pure Python, no data and
no manuscript. `paper/data/` (688 MB of LibriSpeech), the manuscript sources, and
the third-party PDFs used for reference checking stay private and are still
ignored. The `benchmark` dependency group is in `pyproject.toml`, `uv.lock` and
`sbom.cdx.json` are regenerated to match, and the LibriSpeech download snippet now
creates `paper/data/` instead of `cd`-ing into a directory a fresh clone does not
have.

### Measured — streaming transcription is a loss on every model but `tiny.en`

The benchmarks page reported *decode* time. It never reported the number a user
actually experiences, and the one every commercial dictation product advertises:
**after you stop speaking, how long until the text is there?** The streaming path
had no published latency at all. Measuring it (`paper/benchmark/bench_streaming.py`,
15 speaker-stratified LibriSpeech utterances fed at real time) contradicted the
docs:

- **Streaming makes the final text arrive later, not sooner.** `commit()` re-decodes
  the whole utterance on release regardless, so the 300 ms rolling loop is competing
  with the decode that actually produces your text. Speech-end → text goes 0.92 s →
  1.22 s on `tiny.en`, and **1.42 s → 2.21 s on `base.en`**.
- **On the default model it usually shows nothing at all.** In **9 of 15** `base.en`
  utterances LocalAgreement confirmed no prefix before the key was released — median
  visible-at-release **0 %**. A rolling window over a growing 10-second buffer takes
  longer than the speech that fills it. `tiny.en` keeps up: a partial in 15/15
  utterances, 72 % of the text on screen at release.

So `yazses features enable streaming` on default settings was a straight downgrade,
and nothing said so. `features enable` now prints the measured caveat when
`[stt] model` is not `tiny.en` (`system/features.py::enable_caveat` — advice, not a
refusal; the user may have a reason). `docs/benchmarks.md` gains a *speech end →
text* section, and the claims in `docs/features.md` and
`docs/how-to/cpu-and-battery.md` that streaming "buys perceived latency" are now
qualified with the model it is true for. The `StreamingConfig` default-off comment
previously justified itself only on injection-correctness grounds; it now carries
the latency evidence too.

### Added — the commercial dictation cluster in the comparison

`docs/comparison.md` covered the open-source and offline tools but none of the
products that rank for "best voice dictation software": Willow Voice, Voice In,
Windows Voice Typing. Added, with a distinction worth stating precisely — Willow's
**Private Mode is a retention control, not local processing**. Their privacy policy
says Willow "uses cloud infrastructure to provide fast and accurate voice
dictation", and describes Private Mode as processing audio "transiently to return a
transcription" without retaining it or training on it. That is a real commitment,
and it is a different guarantee from audio that never leaves the machine. Checked
2026-08-15.

### Changed — the repo root was 28 READMEs deep before anything else

A visitor landing on the repository met `README.ar.md` through `README.zh-TW.md`
before reaching `src/`, `docs/`, or any file that says what this is. The
translations earned their place — 28 languages is the reach — but the root is the
first screen a stranger reads, and it was spent on files each of which is useful
to roughly one reader in twenty-eight.

- **The 28 translations are now `docs/<lang>/index.md`.** They are published pages
  rather than blobs: each carries `title`/`description`/`alternates` front matter,
  `hooks/hreflang.py` turns `alternates` into reciprocal `hreflang` tags, and
  mkdocs lists them under a `Languages` section. A `blob/main/README.xx.md` page
  can carry no `hreflang` and no `canonical`, so this is the surface they were
  always supposed to have. The badge block is dropped from each translation — its
  links were root-relative and rendered broken on the site.
- **The five community-health files moved to `.github/`.** GitHub surfaces
  `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`, `GOVERNANCE` and `SUPPORT` from
  there identically — same links in the issue and PR flows, same community
  profile — for no root cost.
- **Four guards globbed `README.*.md` at the repo root, and every one of them
  passes on an empty set.** `scripts/check-translations.py`,
  `gen-readme-translation.py`, `test_contributors_wall.py` and
  `test_citation_metadata.py` would all have gone quietly green while checking
  zero files after the move — the drift check, the contributor wall and the
  citation identifier included. They read `docs/*/index.md` now and assert the
  count is 28.
- `campaign/tasks.json` listed `README.<lang>.md` in 224 `allowed_paths` entries;
  a contributor task whose allowed path does not exist is a task nobody can do.

**The old `blob/main/README.xx.md` URLs 404 from here on.** Nothing inside the
repository still points at them, but anything posted to a regional community
during the localization pushes does; the replacement is the site page, which
carries the hreflang signal those links never could.

### Added — the settings window explains every option, and can undo itself

The switchboard listed ~200 capabilities as a checkbox, a name and a tier. That
answers "is it on?" and nothing else: not what the capability does to your
dictation, not when you would want it, and — the one a config file makes
checkable — not what ticking the box actually writes. The material to answer all
three already existed; `yazses features info` has printed it for a year. Only the
window had no way to show it.

- **A filter box.** `yazses features` has had `--on`/`--tier`/`--category` since
  it was written; the window had none of it, so reaching a capability meant
  scrolling past every other one — and a row you never reach cannot explain
  itself, however good its help text is. It matches the name, the toggle name,
  the category *and* the description, so `stutter` finds Dysfluency-Friendly;
  `on:`/`off:`/`tier:rec` take the same words the CLI flags take. Visibility
  only: a hidden row keeps its staged edit, and Apply and Restore defaults act on
  every capability, not the visible ones.
- **Every row explains itself, three ways.** A one-line summary under the label
  (always visible, so a category is scannable), the full card on hover, and a
  **?** button that opens that same card in a dialog. The button is there *as
  well as* the tooltip, not instead of it: hover is unreachable by keyboard,
  unavailable on touch, and never announced by a screen reader — which for this
  project's users is not a detail. Rows also carry an accessible description, so
  the help is spoken rather than merely displayed.
- **The card names the config keys.** Alongside what it does, when to use it, an
  example and any packages it installs, each row states the exact
  `[section] key = value` writes ticking it performs — so the window stays
  auditable against a `config.toml` you may also be editing by hand. A greyed row
  explains *why* it is greyed, instead of just refusing to move.
- **Restore defaults.** Puts every switch back to the state a fresh install ships
  with. It stages rather than writes, and names every capability it would touch,
  split into on and off, before anything happens — so a misclick costs nothing.
  It never enables an experimental capability (those are by definition not the
  advised set), it only writes the rows that actually differ rather than churning
  all ~200 keys, and it leaves your hotkey, microphone, threshold and vocabulary
  alone. It is a reset of the switchboard, not of your config file.
- **`yazses features reset`** is the same operation in a terminal, with
  `--dry-run`, `--yes` and `--no-install` — so a headless box, an SSH session, or
  a distribution too old to load Qt is not cut off from it. Both surfaces read
  one definition of "default" (`features.default_state()`), which is the same set
  first-run seeds, so they cannot drift.

All of the wording is pure and unit-tested (`settingsui/help.py`), because the
window itself is skipped wherever PySide6 is absent — CI included.

### Fixed — the settings window's tests had never run anywhere

`tests/test_settingsui_window.py` is skipped without PySide6, which CI does not
install (Qt is deliberately not a base dependency), so the Qt shell was verified
by nothing. Running it for the first time turned up two defects it had been
written to catch and then never executed:

- **The tests hung on any machine with a daemon running.** They stubbed the
  experimental dialog but not the restart one, and Apply asks the *host* whether
  a daemon is up. On a developer's own machine — i.e. anyone actually using
  YazSes — Apply opened a real modal dialog and the run blocked forever. Green in
  CI purely because no daemon runs there.
- **A partly-failed Apply reported itself as a clean save.** The restart outcome
  overwrote Apply's summary, and that summary was the only place the window said
  some rows had failed and were still staged. The two are now composed, not
  replaced.

### Fixed — "Update installed" was reported for upgrades that never happened

Reported from a real install: the tray's **Check for updates…** offered 2.19.0 → 2.20.0,
**Install now** said *"Update installed. Restart the daemon"*, the daemon was restarted,
and it came back on 2.19.0. Every time.

The upgrade really did run — and really did nothing. `uv tool upgrade yazses` prints
`Nothing to upgrade` and **exits 0** when the tool was installed with an exact version pin
(`uv tool install yazses==2.19.0`); the pip family behaves the same way for a constraint it
cannot satisfy. Both the tray and `yazses update` treated exit 0 as proof, so the one piece
of information that would have explained it — uv's own hint about the pin — was thrown away
and replaced with a success message.

An exit code is no longer taken as evidence. `updater.run_upgrade_checked()` runs the
upgrade and then re-reads the installed version **out of process** (the caller is still
running the code it started with, so its own import machinery cannot see the new one), and
reports one of four outcomes: upgraded, command failed, version unreadable, or *finished but
unchanged*. The last one names the version you are still on and how to get out of it —
`uv tool install 'yazses[desktop]@latest'`, with the extras kept, because a bare
`yazses@latest` installs base dependencies only and silently removes PySide6, the tray and
the overlay along with it.

`yazses update` now exits non-zero in that case rather than printing "Updated to 2.20.0"
directly over the package manager's "Nothing to upgrade".

**The way out is now reachable without the updater.** A repair to the update path cannot
be delivered *through* the update path — whoever is stuck is, by definition, running the
build that lacks the repair, and no amount of improving the client reaches them. So the
recovery route is out of band: a new how-to page,
[The update said it worked but the version did not change](https://mskazemi.com/yazses/how-to/update-did-nothing.html),
carries the reinstall command per install method, and `pinned_install_hint()` now ends at
that URL for **every** method rather than only `uv`. The others fell through to "run it in
a terminal to see what it reported", which tells someone who has just run it nothing.

Two more no-op-with-exit-0 cases are named where they were previously silent: a `pip`
install held by a pin or a constraint file (`pip install --upgrade --force-reinstall
'yazses[desktop]'`) and a **held snap**, which refuses to refresh and still exits 0
(`sudo snap refresh --unhold yazses`). Both flags were checked against the tools
themselves; methods whose reinstall command is *not* verified get the page instead of a
guessed flag, since a guess that also does nothing repeats the original failure. The
Windows installer channel is quoted no command at all — that upgrade is a download.

`tests/test_updater.py` pins both halves: every install method's hint must name the
recovery page, and that URL must resolve to a page that exists in `docs/` (including the
`.html` suffix — `use_directory_urls: false`, so the trailing-slash form 404s). A stable
URL compiled into a released client is quoted at the exact moment the user has already
been misled once, and nothing downstream can correct it.

## [2.20.0] - 2026-08-14

### Fixed — a blocked model download killed the daemon instead of explaining (#310)

Reported by [@AtmanActive](https://github.com/AtmanActive) on Windows 10 behind
the [Fort](https://github.com/tnodir/fort) firewall: on first run the daemon
tried to fetch the Whisper model, the firewall refused the socket
(`WinError 10013`), and the process died with a raw `huggingface_hub` traceback —
which the PyInstaller bundle renders as a modal *"Failed to execute script"*.
Nothing on screen said what YazSes wanted, why, or what to do about it.

`core/daemon.py::run()` wrapped `_build_pipeline()` in `try`/`finally` with no
`except`, so **every** startup failure escaped to the top. Notably `stt/factory.py`
already got this right for the Parakeet and Moonshine engines ("dictation must
still come up"); the default engine had no such guard.

Now: `stt/errors.py::ModelUnavailableError` carries ready-to-print guidance —
the cause, a firewall hint when the cause reads like one, and the three ways to
get the model (`yazses model download <name>`, unblock and restart, or fetch the
repo by hand into the printed cache directory). The daemon holds itself in
`ERROR` state with that text attached rather than exiting, so the tray turns red
with the reason and `yazses status` can answer — exiting would have taken the
tray down too, leaving a vanished window as the only symptom.

### Added — `yazses model download` handles speech models, not just SLMs

The model can now be fetched as a deliberate, watchable step instead of a side
effect of the first dictation, which is the only workable route on a firewalled
or air-gapped machine. `yazses model list` gained a speech-to-text section
showing every model and whether it is already present, plus the cache path.

New `stt/download.py` owns the name→repository mapping, mirrored from
faster-whisper's private table and **kept honest by a test that fails on drift**.
It is not derivable: `large` resolves to `large-v3`, `turbo` comes from a
different organisation, and the distil models use another prefix — so a URL
built from a template would have sent three of them to a 404.

### Fixed — the documented model-cache path was wrong on Windows

`docs/windows-install.md` said `%LOCALAPPDATA%\huggingface\hub`. huggingface_hub
actually uses `~/.cache/huggingface/hub` on every platform, so anyone placing a
model by hand was putting it where nothing would read it. `doctor` now asks
huggingface_hub for the path rather than re-deriving it, which also makes it
honour `HF_HUB_CACHE` and `XDG_CACHE_HOME` instead of only `HF_HOME`.

### Fixed — Windows shipped without its icon, and the tray showed a blank disc

Reported with screenshots: the desktop shortcut carried PyInstaller's generic
default artwork, and the tray icon beside the clock was a plain flat blue circle
with jagged edges. Two separate causes, both long-standing.

- **`assets/yazses.ico` never existed.** `packaging/windows/yazses.spec` had
  referenced it since the file was written, behind
  `icon=str(ICON) if ICON.exists() else None` — so every build silently passed
  `icon=None` and shipped the default icon to the desktop shortcut, the Start
  menu, the taskbar and Add/Remove Programs. `packaging/macos/yazses.spec`
  carried the identical dangling `assets/yazses.icns`. Both now **fail the build**
  rather than degrading in silence, and the containers are generated and
  committed. The installer brands itself too (`SetupIconFile`), so the downloaded
  `.exe` is no longer a generic blob in Explorer.
- **The tray glyph is now the YazSes mark** — a rounded badge with the white "Y",
  matching Linux — instead of a bare disc. Pillow anti-aliases nothing, which is
  where the jagged edge came from; the mark is supersampled and downsampled as
  coverage, so it has neither jagged edges nor the dark halo the naive fix
  introduces. Below 40 px the sound-wave bars are sub-pixel, so small frames
  carry a simplified variant rather than a grey smear.
- **The Windows tray now obeys the shared colour policy.** It had kept a private
  seven-entry table that bypassed `tray/menu.py::icon_spec`, so Windows showed
  different colours from Linux for the same state, had **no** command-mode purple
  and **no** "no text field focused" yellow, and rendered five of the twelve tray
  states — including Meeting Mode — as idle blue. Both trays now share one
  `status_from_model` bridge.
- **The tray tooltip's "Mic:" line was always wrong.** The daemon reported the
  active input device, but `TrayModel` had no field for it, so every platform
  showed `Mic: default` however the microphone was pinned.
- New `scripts/gen-icons.py` renders both containers from one shared
  `yazses.brandmark` renderer — the same code the tray glyph uses, so the
  shortcut icon and the tray badge cannot drift apart.

Also fixed while in the file: `build-windows.yml`'s installer smoke test still
looked for `YazSes.exe`, renamed to `YazSesApp.exe` in 13d7a6d, so the payload
check threw on every run and the matching uninstall assertion silently passed
without ever checking anything.

### Added — About, Help and Check for updates in the tray menu

The tray menu ended at daemon control, so the three questions you have *at the
icon* — what version am I running, where are the docs, is there a newer release —
could only be answered in a terminal (`yazses about`, `yazses update`), which is
exactly what a tray user does not have open. All three are now menu entries, on
**Linux, macOS and Windows**:

- **About YazSes** — version, tagline and clickable Website / Source / Issues
  links, from the same `branding.contact_lines()` block `doctor` prints.
- **Help ▸** — Documentation, Troubleshooting, Report a bug…, each opening the
  page in your browser.
- **Check for updates…** — asks PyPI or your snap channel, then offers
  **Install now** when the upgrade can run without a password. A snap install is
  shown `sudo snap refresh yazses` to run in a terminal instead: launched from a
  tray click there is nowhere to type a password, so an Install button there
  would hang invisibly. The check runs on a worker thread — a 5-second network
  lookup on the UI loop would freeze the icon and the menu with it.

Windows had shipped a `Help` entry wired to nothing (`enabled=False`); it is now
real. The cross-OS parity test written for #63 was generalised from `Settings…`
to every shared label, including the wiring check that would have caught that
placeholder, and its macOS check now compares full `@rumps.clicked` label
*paths* so submenu entries aren't misread as one label bound three times.

### Fixed — every CLI command was unreachable on the Windows installer

`yazses doctor` on Windows printed nothing and then died in a message box with
`AttributeError: 'NoneType' object has no attribute 'isatty'`. Two defects,
stacked:

**The console shim could never win.** The bundle ships two binaries on purpose —
a windowed one for the tray/daemon and `yazses-cli.exe` for the CLI — with a
`yazses.cmd` shim putting the console one on `PATH`. But the windowed binary was
named `YazSes.exe`, Windows resolves a bare `yazses` through `PATHEXT` (which
lists `.EXE` before `.CMD`), and NTFS is case-insensitive. `YazSes.exe` therefore
answered to `yazses` and shadowed the shim in the same directory. Every
`yazses <command>` reached the *windowed* binary, which has no console — so
`yazses doctor` and `yazses -h` printed nothing whatsoever. The shim shipped as
dead code and the two-binary split it existed to enable never engaged for
anyone. The windowed binary is now `YazSesApp.exe`; the installer deletes a
leftover `YazSes.exe` on upgrade, or the orphan would keep shadowing the shim.

**A missing stdout was fatal rather than degrading.** `sys.stdout` is `None` in a
GUI-subsystem PyInstaller build, so `sys.stdout.isatty()` — used to decide
colour — raised instead of answering "not a tty". New `system/streams.py`
centralises that policy and is used everywhere the std streams are touched
(`doctor`, `vocab export`, the upgrade nudge, `setup`'s calibration prompt).
`system/wincon.py` adds the second line of defence: a CLI command that reaches
the windowed binary anyway now borrows the launching terminal's console via
`AttachConsole`, and falls back to `os.devnull` rather than leaving the streams
`None`.

Reported from a live Windows install; hold-to-talk dictation itself was working.

## [2.19.0] - 2026-08-14

### Added — About, Help and Check for updates in the tray menu

The tray menu ended at daemon control, so the three questions you have *at the
icon* — what version am I running, where are the docs, is there a newer release —
could only be answered in a terminal (`yazses about`, `yazses update`), which is
exactly what a tray user does not have open. All three are now menu entries, on
**Linux, macOS and Windows**:

- **About YazSes** — version, tagline and clickable Website / Source / Issues
  links, from the same `branding.contact_lines()` block `doctor` prints.
- **Help ▸** — Documentation, Troubleshooting, Report a bug…, each opening the
  page in your browser.
- **Check for updates…** — asks PyPI or your snap channel, then offers
  **Install now** when the upgrade can run without a password. A snap install is
  shown `sudo snap refresh yazses` to run in a terminal instead: launched from a
  tray click there is nowhere to type a password, so an Install button there
  would hang invisibly. The check runs on a worker thread — a 5-second network
  lookup on the UI loop would freeze the icon and the menu with it.

Windows had shipped a `Help` entry wired to nothing (`enabled=False`); it is now
real. The cross-OS parity test written for #63 was generalised from `Settings…`
to every shared label, including the wiring check that would have caught that
placeholder, and its macOS check now compares full `@rumps.clicked` label
*paths* so submenu entries aren't misread as one label bound three times.

### Fixed — three shipped commands were missing from the CLI reference

`docs/cli-reference.md` documented 55 of the 58 commands the CLI actually ships.
`gitvoice`, `fileopen` and `jump` were absent — all three appeared in the
generated `docs/command-index.md`, so the gap was only visible by diffing the
generated index against the hand-written reference.

The reference is hand-written on purpose (example-first, grouped like the CLI's
own `--help` panels), and the cost of that choice is exactly this. It is now
guarded: `tests/test_cli_reference_covers_every_command.py` asserts against the
**live Click tree**, not against the generated index — a stale index would agree
with a stale reference and both would pass.

Also documented: the **Voice Undo/Redo timeline** (`[timeline]`, off by default).
The voice-command reference had only the `undo` command, which sends Ctrl+Z; the
timeline is a different mechanism that steps back over what YazSes itself
injected ("undo two words", "undo the last sentence", "redo"). Reading the old
page, a user would reasonably conclude "undo two words" sent Ctrl+Z twice.

### Fixed — the roadmap's headline numbers were stale again

`ROADMAP.md` claimed **141 capabilities (74 wired / 67 planned)** and **3049
tests**; the registry and the suite say **144 (79 / 65)** and **4005**. The same
counts in `docs/mobile/index.md` were stale *and* did not add up (68 + 72 ≠ 141).

That file already carried a note that these numbers had gone stale once before,
"each one understating what had actually shipped". They did it again, in the same
direction. So the fix is not just the numbers: the two commands that re-derive
them from `yazses.system.features` and from `pytest` now sit beside them, and the
text says to re-derive rather than edit.

### Fixed — the FreeBSD job timed out instead of installing YazSes

Contributed by [@mercael91](https://github.com/mercael91)
([#307](https://github.com/MSKazemi/yazses/pull/307)). The advisory `freebsd` job
had never once run the suite, and because it is `continue-on-error` the workflow
reported success every time — so `platform/bsd/` looked covered while being
covered by nothing.

PyPI ships no FreeBSD wheels, so every compiled dependency is a source build.
`cryptography` needs a Rust toolchain and died on `metadata-generation-failed`;
`numpy` compiled from its 20 MB sdist for 38 minutes and hit the 45-minute limit,
which GitHub reports as *"cancelled"* rather than as a build being too slow. Both
now come from `pkg` where the ports version satisfies the pin exactly
(`py312-numpy` 2.4.6 against `numpy>=2.4.6`) and from `rust` where it does not
(`py312-cryptography` is 48.0.1 against `cryptography>=50.0.0`). The job went
from **45m04s timing out** to **5m29s with a readable error**.

**It is still red, and that is now an honest result rather than a broken one.**
`faster-whisper` needs `ctranslate2`, which publishes 35 wheels — macOS, manylinux,
Windows — no source distribution, and has no FreeBSD port. `pip install -e .`
therefore cannot succeed on FreeBSD as the dependency set stands, which is a fact
about the platform rather than a CI defect. Tracked in
[#306](https://github.com/MSKazemi/yazses/issues/306).

### Fixed — the BSD row on the platform-support page claimed an install that fails

Following directly from the above, and the more consequential half of it.
[`docs/platform-support.md`](https://mskazemi.com/yazses/platform-support.html) listed
FreeBSD and the other BSDs as **✅ `pipx` (PyPI)** — which that page's own legend
defines as *"published and installable today"*. It is not: `pip install yazses` fails
during dependency resolution, before any YazSes code is reached, because `ctranslate2`
has neither a BSD wheel nor an sdist.

Nobody had run the install, and the CI job that was supposed to prove it is
`continue-on-error`, so it reported success every run while never getting past `pkg`.
The row is now **❌ with the resolver error quoted**, and the claim that "a CI job now
runs the suite in a real FreeBSD VM" is corrected to say it has never got that far.

Choosing a different speech engine does not help — `faster-whisper` is a hard
dependency rather than an extra, so the Whisper stack would have to move behind an
extra first. `py312-onnxruntime` *is* in ports, so the Parakeet path is plausible; it
is untested and is not claimed.

### Added — the CLI demo now plays in the docs site (#23)

`docs/watch-the-cli.md` embeds `docs/demo/yazses-cli.cast` in a real player. The
cast has existed since August and was only ever *linked* — which meant reading
the demo required installing `asciinema` first, so in practice nobody saw it.

The player (asciinema-player 3.17.0, Apache-2.0) is **vendored into
`docs/assets/asciinema/` and served from this site, not a CDN**. That is not
incidental: a tool whose entire claim is that your voice never leaves your
machine cannot have documentation that reports every reader's IP address to a
third party. This site already had that bug once, with Google Fonts.

The upstream issue also asks for an upload to asciinema.org. That needs an
account, so it stays with the maintainer — and the self-hosted player is the
better answer for this project anyway.

### Added — Obsidian, Zed and GNOME Terminal configs, and two more harness claims withdrawn

`examples/config.{obsidian,zed,gnome-terminal}.toml`, each measured the same
way: inject into a live window, read back what arrived. All three are byte for
byte exact. (#188, #219, #222)

Every one of them had been recorded as impossible, and every one was a property
of the container rather than of the application:

- **GNOME Terminal** was *"no window, even with `dbus-launch`"*. The session bus
  was never the problem — `gnome-terminal-server` refuses to start under a
  non-UTF-8 locale, and a container defaults to `ANSI_X3.4-1968`. The base image
  now sets `LANG=C.UTF-8`.
- **Zed** exits with *"Failed to create surface"* without a Vulkan device, and
  then stacks an "Unsupported GPU" notice on a "Trust this project?" prompt —
  which **Escape cannot answer**, only Return. Hence `PROBE_PRE_KEYS`.
- **Obsidian** opens on its vault picker, so there is genuinely nothing to type
  into until a vault exists.

Zed's saved file carries a trailing newline that the dictation did not contain.
That is its ensure-final-newline-on-save, not mangling — checked with `od`,
because a naive read-back reports it as a mismatch and it is not one.

`probe.sh` gains `PROBE_WAIT` (the 7-second default is far too short for a
D-Bus-activated app, and a slow start is indistinguishable from a dead one in
the output). The known-limits table now separates apps that need an account
(Slack, Discord — only the login field is reachable, and a config asserting the
untested composer would be worse than none) from apps that are merely not
packaged for apt (Logseq).

### Added — Firefox and Thunderbird configs, and a wrong result withdrawn

`examples/config.{firefox,thunderbird}.toml`, each written from a measurement,
plus `probe-gui.sh` and `Dockerfile.gui` so the measurement can be repeated.
Both deliver `kubectl get pods --namespace prod` byte for byte. (#225, #226)

VS Code (#185) was measured here too and reached the same verdict independently,
but the profile that ships is [@Mr-Neutr0n](https://github.com/Mr-Neutr0n)'s from
[#305](https://github.com/MSKazemi/yazses/pull/305) — see the entry below. Two
people finding the same first-run modal from opposite directions is the strongest
evidence in this changelog that it is real.

**This corrects a claim this project published.** `scripts/appprobe/README.md`
said Electron *"opens a window and no keystroke ever lands"* and that Gecko
produced *"no window at all"*. Both were wrong, and both were wrong about the
harness rather than about the toolkit:

- **VS Code was showing a first-run modal** — *"Sign in to use GitHub Copilot"* —
  which swallowed every keystroke silently. Two Escapes before typing, and it
  returns the text exactly. A screenshot showed this in seconds; ninety seconds
  of extra waiting had not, because the wait was never the problem.
- **`apt install firefox` on Ubuntu 24.04 installs a snap stub**, a script that
  prints `snap install firefox` and exits. With no snapd in a container the
  browser never starts. Taking the tarball from Mozilla instead, Firefox and
  Thunderbird both work.

The probe now reports `DIALOG_ONLY` with a screenshot when the only window on
screen is too small to be the application, rather than `NO_WINDOW` — the two
were indistinguishable in the output, and that is precisely how the wrong
conclusion got recorded. **A negative result from a harness is a claim about the
harness until you have looked at the screen.**

`docs/how-to/app-profiles.md` gains a section on the same distinction for users:
text that never arrives is usually a dialog in front of the window, or the wrong
text field having focus — neither of which the "no text target" guard can catch,
because in both cases a real text target does have focus.
### Added — a VS Code app profile, and a check on every app profile

`examples/config.vscode.toml`, contributed by
[@Mr-Neutr0n](https://github.com/Mr-Neutr0n) ([#305](https://github.com/MSKazemi/yazses/pull/305)) —
the first Electron editor covered by [#43](https://github.com/MSKazemi/yazses/issues/43),
and the one asked for most.

It records the two ways dictation into VS Code looks broken when it is not, both
found by measurement rather than from reports: a first-run modal (*"Sign in to use
GitHub Copilot"*) absorbs every keystroke silently, and the Chat panel is a second
genuine text target that the "no text target" guard cannot tell from the editor.
Injection itself is exact — `kubectl get pods --namespace prod` arrives with its
capitalisation and both hyphens intact.

`tests/test_app_example_configs.py` now checks every `examples/config.<app>.toml`,
which nothing did before. Config loading is deliberately total ([#52](https://github.com/MSKazemi/yazses/issues/52)):
an unknown key is dropped and recorded, never raised. So a profile naming a setting
that does not exist — or putting a real one under the wrong section — installed
cleanly, started cleanly, and silently did nothing. These files are copied verbatim
by newcomers, and #43 invites many more of them.

### Added — build provenance on every release artifact

The `.deb`, `.dmg`, `.exe` and the PyPI wheel now carry a signed attestation
stating that *this exact file was produced by this workflow, from this commit, in
this repository*. Generated by GitHub's OIDC identity during the release run, so
there is no private key to leak.

```bash
gh attestation verify yazses_2.18.2_amd64.deb --repo MSKazemi/yazses
```

**This matters most because the binaries are still unsigned.** Until code signing
lands, provenance is the only cryptographic link between a download and this source
tree — and a tool people run against everything they say should not ask to be
trusted on hosting alone. PyPI uploads carry [PEP 740](https://peps.python.org/pep-0740/)
attestations from the same trusted-publishing identity.

Stated plainly on the [code-signing page](https://mskazemi.com/yazses/code-signing.html):
the first release carrying these has not been cut, so a verification failure on an
older artifact means it predates the change. Part of `Signed-Releases` in
[#116](https://github.com/MSKazemi/yazses/issues/116) — the remaining Scorecard
items are owner decisions.

### Verified — the Android skeleton's architecture rules, by breaking them on purpose

The `android/` skeleton was built but had never been executed — its README still
said *"design complete, no code yet"*, because the authoring machine had no JDK. A
container has one. `android/verify.sh` now runs the whole thing on
`gradle:8.10-jdk21` with no local toolchain:

| Rule | How it is enforced | Result |
|---|---|---|
| `:core:*` cannot import `android.*` | by construction — a `kotlin("jvm")` module has no `android.jar` on its classpath | **enforced**: `Unresolved reference 'android'` |
| `:core:*` may not depend on `:feature:*` | `checkLayering`, wired into every `check` | **enforced**: `:core:vocab (implementation) -> :feature:ime` |

Both are tested by **adding the violation and requiring the build to fail**, with a
clean-tree baseline first so a check that always failed could not pass for the
wrong reason. `gradle test` is green on the `:core:*` modules, and the module map
resolves exactly as `docs/mobile/architecture.md` §3 specifies.

Scoped honestly: only the pure-JVM half is exercised. The Android modules need the
SDK, which CI installs and this script does not claim to cover. (#84)

### Fixed — three bugs found by actually running Meeting Mode (#48)

- **`yazses meeting stop` reported "Daemon is not running" on a daemon that was
  working.** A timeout and an absent daemon raise the same error, and stopping
  waits for the in-flight live decode before answering — which routinely exceeds
  the 2-second IPC timeout. The meeting finalized successfully five seconds after
  the CLI declared the daemon dead. It now asks the single-instance lock (which
  cannot be stale) before saying so, and otherwise says the daemon is still
  finalizing and where the results will land. **Telling someone they lost a
  meeting they did not lose is the worst thing this command can do.**
- **`yazses features enable <name>` can install into an interpreter the daemon
  never loads.** Here the daemon came from a `uv tool` install and `yazses` on
  PATH came from a checkout, so the `diarization` extra landed in the wrong
  environment — and the daemon then told the user to run
  `yazses features enable meeting`, the command they had just run. It now detects
  the mismatch and prints the command that actually fixes it. The check compares
  **environment prefixes, not interpreter paths**: a venv's `python` is a symlink
  to a shared base, so the obvious `/proc/PID/exe` comparison silently never
  fires — which is exactly what the first draft did.
- **A test asserted the absence of an optional dependency.**
  `test_factory_returns_none_when_extra_missing` passed only while sherpa-onnx
  was not installed, so installing the `diarization` extra — which
  `yazses features enable meeting` does — turned `main` red with nothing wrong in
  the code. It now forces the import to fail instead of assuming the machine will.

### Fixed — the Nix flake had never been evaluated, and did not evaluate

Its own header said so: *"authored, NOT YET EVALUATED … the authoring machine has
no Nix and fetching a Nix binary to get one was not an acceptable trade."* A
container has Nix, so that trade no longer exists —
`packaging/nix/build-and-test.sh` runs `nix flake check` on `nixos/nix`.

The first evaluation found two real defects:

- **`yazses-desktop` failed outright** with *attribute 'dependencies' missing*.
  It used `overrideAttrs`, which sees the derivation **after**
  `buildPythonApplication` has consumed `dependencies` and turned it into
  `propagatedBuildInputs`. `overridePythonAttrs` is the one that sees the
  arguments.
- **The version was pinned at 2.17.0** while the project had moved to 2.18.2.

`nix flake check` now passes for `x86_64-linux`, and the flake header states what
is still unproven — aarch64 and Darwin, which the check omits, and installing from
a real NixOS machine rather than a container. A `docs/install-linux.md` section
covers `nix run` and the headless/desktop split. (#68)

### Added — the AUR package, built and installed on a clean Arch container

`packaging/arch/build-and-test.sh` runs what the issue asked for on
`archlinux:base-devel`: the PKGBUILD parses, `.SRCINFO` matches it, the package
builds (`yazses-2.18.2-1-any.pkg.tar.zst`), installs, and `yazses --version`
prints `2.18.2`.

**The finding worth recording: a bare `makepkg -si` cannot complete, and the
PKGBUILD is not at fault.** Two runtime deps live in the AUR
(`python-faster-whisper`, `python-sounddevice`), and faster-whisper pulls a
further AUR chain — ctranslate2, tokenizers, onnxruntime, av. `makepkg` never
fetches AUR dependencies by design; only a helper resolves them recursively, so
the correct instruction is `yay -S yazses` and the docs now say that instead of
letting a user hit *target not found* and assume the package is broken.

The script therefore verifies what it can and states plainly what it does not:
`yazses doctor` end to end is not claimed, because the dependency chain is the
helper's job. (#67)

### Added — a Fedora/RHEL package, built and installed on a clean Fedora container

`packaging/fedora/yazses.spec`, plus `build-and-test.sh` which runs the issue's
acceptance criterion rather than asserting it: build the RPM on a clean Fedora 41,
install it, run `yazses doctor`. Verified — `yazses-2.18.2-1.fc41.x86_64.rpm`
installs, `/usr/bin/yazses` resolves, `yazses --version` prints `2.18.2`, and
`doctor` reports exactly the three things a container legitimately lacks (no
`input` group, no audio device, no autostart).

Two things the spec is deliberately honest about, and the docs repeat both:

- **It bundles its Python dependencies** (~380 MB installed). The idiomatic
  approach declares each as a `python3dist(...)` require, and that is not possible
  today — faster-whisper, ctranslate2 and onnx-asr are not in the Fedora
  repositories, so such a spec would fail dependency generation on a clean build.
  Bundling is fine for a COPR and is **not** fine for official Fedora, which is
  the issue's stretch goal and a much larger job.
- **`portaudio` is required; the injection tools are not.** `xdotool`/`xclip` are
  *Recommends* and `ydotool`/`wl-clipboard` *Suggests*, because
  `yazses transcribe` needs none of them and a hard dependency would pull an X11
  stack onto a headless machine. (#77)

### Added — seven tested app configs, and a finding about apps that rewrite dictation

`examples/config.{kitty,alacritty,konsole,tmux,neovim,emacs,libreoffice-writer}.toml`,
each written from a measurement rather than from assumption.

**Method.** Each application was launched on an isolated virtual X display inside a
container and driven with the same `xdotool` XTEST path the daemon uses — so the
application could not distinguish it from a real keypress — and what arrived was
read back. The speech half is not covered by this; the configs say so.

**The finding.** Terminals and code editors deliver the text byte for byte,
including `--namespace`, `&&` and `src/main.py`. LibreOffice Writer does not:

| | |
|---|---|
| dictated | `kubectl get pods --namespace prod` |
| arrived | `Kubectl get pods –namespace prod` |

AutoCapitalise made `kubectl` a different command, and AutoCorrect replaced the
double hyphen with an **en dash** — a flag no program accepts, and nearly
invisible on re-reading. **No YazSes setting can prevent it**, because it happens
inside Writer after the characters arrive, so the config documents the two
Writer options to turn off instead of pretending to fix it.
[The app-profiles guide](https://mskazemi.com/yazses/how-to/app-profiles.html)
now explains how to test whether your own application does the same.

### Added — `:core:audio`, `:core:vad`, and a `vad_gate` contract both platforms share

The silence gate now has **contract vectors of its own** (`contract/vectors/vad_gate.json`,
generated from `audio/vad_calibrated.py`), so "what counts as silence" is one
definition rather than two implementations that drift. The Kotlin port passes all
nine, and `:core:contract-test` is up to **225 cases** across seven files.

The cases are chosen to pin the parts that are easy to get wrong:

- **Mean, not peak.** One loud click among fifteen silent samples has a peak of 0.9
  and a mean of 0.056 — a door slam is not a burst worth transcribing. Writing this
  case caught the first draft, where the example was too short to demonstrate its
  own claim and the expectation contradicted the description.
- **Empty audio is silence**, because handing an empty buffer to a recogniser is
  how a confident hallucination gets typed into someone's document.
- **Lowering the gate is what makes a quiet voice usable** — the whole reason the
  threshold is calibrated rather than fixed.

`:core:audio` has the pre-speech ring buffer, with the test that matters: audio
captured after the key was pressed still contains the leading word. People with
hypophonia have delayed voice onset, and without this the opening syllable is
simply missing.

`:platform:audio` has the `AudioRecord` shim — 16 kHz mono PCM16 on a dedicated
thread that never blocks on decode, with permission-revoked and mic-stolen ending
in a clean stop and a reason rather than a crash inside a keyboard. **It compiles
and has not been run on a device**, which is what the remaining boxes on #88 are.

Declaring `RECORD_AUDIO` in `:platform:audio` rather than `:app` made the new
privacy gate fail, which is the gate working: the golden file and the ADR's
permission table were both updated in the same change, with the reason.

### Added — `:core:commands` and `:core:vocab` in Kotlin

The Tier-1 grammar classifier and the `initial_prompt` merge, both verified
against their shipping vectors. `:core:contract-test` now runs **215 cases**
across six vector files.

The grammar's every pattern is anchored at both ends, which is the whole safety
property: an unanchored rule turns a sentence that merely contains the words into
a command, and "click undo" stops being typed. Dictation is the default because
typing a command by mistake is recoverable and executing dictation by mistake is
not.

Checked red-green — deleting one `undo` rule failed 4 vectors, so a green run
means the vectors actually ran. (#94)

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
