---
title: YazSes v2 voice-first interaction layer
description: "The YazSes v2 features: voice-first interaction beyond dictation — perception, personalization and multi-modal input, each one switchable with yazses features."
---

# v2 Voice-First Interaction Layer

YazSes v2 grows from a dictation daemon into a broader **voice-first interaction
layer** — still 100% on-device and privacy-first. These features ship in the stable
v2 line (v2.12.0 onward). Every row in the wave tables below is wired: `yazses features
enable` turns it on. Capabilities that are designed but not built are listed separately,
in [Designed, not built](#designed-not-built).

**Every v2 feature is off in YazSes's built-in defaults.** The config a fresh install
writes on its first start switches on the *recommended* tier, and eight features on this
page are in it: `cmdsafety`, `spelling`, `verbatim`, `corrdict`, `compute`, `timeline`,
`focusprofile` and `checkdigit`. Everything else stays off until you turn it on, and
`yazses features disable <name>` turns any of those eight off.

This page covers the v2 waves A–N only. It does not list later work such as Meeting Mode,
the Parakeet and Moonshine engines or the hands-free stack; [Features](features.md) lists
every capability, generated from the registry.

Manage all of them with the switchboard:

```bash
yazses features                 # list every capability + on/off + how to toggle
yazses features enable <name>   # turn one on (writes your config)
yazses restart                  # apply
```

Experimental features refuse `enable` unless you add `--force`.

**The wave tables list only what `features enable` will actually turn on.** A capability
that has a design and a place in the registry but **no runtime code in this build** is
not in them. It is listed once, at the end of this page, under
[Designed, not built](#designed-not-built) — with the design record behind it; `yazses
features` calls it *planned* — and `yazses features enable <name>` refuses it outright:

```
$ yazses features enable bridge
Glasses↔Desktop Bridge is designed but not yet wired into this build — enabling it would
change nothing (no runtime code reads its config yet).
It stays listed so contributors can pick it up; see the matching design/adr/ entry.
```

**<!-- registry:unwired -->25<!-- /registry --> capabilities are in that state today**, out
of <!-- registry:total -->149<!-- /registry --> in the registry. Both numbers are counted
from the feature registry when the docs are generated, not typed by hand.

### "Hold the command key" — what that means

Six capabilities below say it: **Phonetic Spelling Mode**, **Spoken Code Mode**, **Spoken
Math**, **Spoken Regex Builder**, **Voice Snippets** and **Local Voice Timer**. Each is
triggered by a leading word — `spell …`, `code …`, `math …`, `regex …`, `insert …`,
`set a timer for …` — and those are ordinary English. Left on the normal dictation key
they would claim sentences you meant to type, so they only run while a **dedicated
command key** is held:

```
yazses hotkey command right_ctrl   # bind one (any key you do not type with)
yazses restart
```

Without one bound, `yazses features enable spelling` still writes the config key and
says so:

```
Heads up: this capability only runs while the dedicated command key is held, and
[hotkey] command_key is not set — so enabling it now changes nothing you can trigger.
```

Every trigger is anchored at **both** ends, so "the code review is on Friday" is typed
rather than interpreted, and each capability's output goes through the same command-safety
gate as ordinary dictation — spelling out `romeo mike space dash romeo foxtrot space slash`
assembles `rm -rf /`, and that waits for a spoken **confirm** exactly as if you had
dictated it.

### The four that answer to the machine instead

Four more were wired at the same time and need no key, because what triggers them is not
something you say:

| Toggle | Trigger | Needs |
|---|---|---|
| `corrdict` — Self-Learning Correction Dictionary | a fix you have made ≥ `min_support` times | `[learning] enabled`; it mines your own corrections |
| `smartpaste` — Smart-Paste | the app that has focus | `[injection] target_guard` not `"off"` |
| `focusprofile` — Focus-Class Auto-Profile | the app that has focus | `[injection] target_guard` not `"off"` |
| `latency` — Adaptive Latency Governor | the 1-minute load average | POSIX; Windows exposes no load average |

Each says so when you enable it without its precondition, rather than turning on and
doing nothing.

## Dictation upgrades (Wave A)

| Feature | Toggle | What it does |
|---|---|---|
| **Confidence Ink** | `confidence` | Flags words the recognizer was unsure about (from Whisper's own probabilities) so you can re-pick them by voice instead of re-dictating. Local only. |
| **Prosody pause→sentence** | `[prosody] pause_sentence_ms` | Inserts a period when you pause for a sentence-length gap. |
| **Spoken Edit Mode** | `spoken-edit` | Edit the last dictation by voice — "change *their* to *there*", "delete the last sentence". Command-key gated. |
| **Context-Primed Dictation** | `context` | Primes the recognizer with terms from the active window/selection so domain words are transcribed right. Read transiently, **never stored**. |

## New capabilities (Wave B)

| Feature | Toggle | What it does |
|---|---|---|
| **Personal Adapter** | `personalize` | Biases the recognizer toward *your* jargon and names, mined from your local corpus. Nothing leaves the machine. |
| **Spoken Recall & Scratch** | `recall` | Search your past dictations (`yazses recall <query>`) and capture spoken notes-to-self (`yazses scratch`). Corpus-local. |
| **Voice Pilot (AT-SPI)** | `pilot` | Hold the command key and say "click Save", "press OK" or "toggle dark mode": the focused window's accessibility tree is read and the control clicked. It acts at once only on **one exact match**; a partial match, a tie or a destructive label ("Delete", "Send") waits for a spoken **confirm**, which reads the window again and clicks only if the very same control is still there (same label, same kind, no extra identical one), and otherwise says why it did nothing. "check X" / "uncheck X" leave a box that is already in that state alone, and wait for a confirm when its state cannot be read; that confirm re-reads the box and clicks nothing if it changed in the meantime or is gone. "uncheck" on a radio button is refused, since a radio button is turned off by choosing another option. Reads labels only, **no screenshots**. Linux with `python3-pyatspi`; experimental, untested on real hardware. |

## Experimental (Wave C — `--force` to enable)

| Feature | Toggle | What it does |
|---|---|---|
| **Accessibility Continuum** | `continuum` | Whisper/Low-Effort Mode lowers the mic gate so quiet or effortful speech is still captured (no shouting). |
| **Modality Role Router** | `modality` | Assigns each input its fastest role (gaze→point, EMG→command, voice→dictation). Needs EMG/gaze hardware. |
| **Gaze-Routed Dictation** | `[gaze] route_dictation` | Sends the next dictation to the window you look at, with a focus fallback and a confirm for destructive actions. Confidence is measured per frame (left/right eye agreement), so poor frames fall back instead of misrouting. Needs a webcam + calibration (X11). |
| **Gaze Deixis** | `[gaze] deixis` | In command mode, "close this" / "focus that window" / "minimize that" act on the window you are *looking at*, not the one with focus. Destructive actions confirm via a toast. On by default inside the opt-in gaze feature. |

## Wave D (v2.1) — new frontier features (all off by default)

A fresh 2026 state-of-the-art round. Manage them with `yazses features enable/disable`.

| Feature | Toggle | What it does |
|---|---|---|
| **Speech Translation** | `translate` | Dictate in another language, type English — uses Whisper's built-in translate (X→English, no extra download); other targets via the `seamless` backend. |
| **Predictive Completion** (experimental) | `predict` | After a dictation is typed, a small local model suggests the rest of the sentence in a notification; say "take it" or "accept suggestion" within 10 seconds to type it, "discard" to drop it, or just keep talking. Only those three phrases answer it, and only as the whole utterance: a one-word "No.", "Decline." or "Keep it." is typed like any other words and dismisses the offer, and so is "take it easy". Nothing is typed without the accept. Needs llama-cpp-python (the `slm` extra) and a GGUF model at `[predict] model_path`; without them it stays dormant and says why once in the daemon log. `--force`; untested with a real model. |
| **Noise Suppression** | `denoise` | Cleans background noise/echo before transcription so dictation works in noisy rooms. Needs the `denoise` extra, which installs the **spectral** backend (`noisereduce`). DeepFilterNet is *not* installable here — every release of it caps `numpy<2.0` while YazSes needs `numpy>=2.4.6`. |
| **Voice Guard** (experimental) | `voiceguard` | Refuses a dictation burst, before it is transcribed, when the speaker does not match your enrolled voiceprint. Speaker match only: no anti-spoof model ships, so a recording of your voice is still admitted. Needs `[voiceprint]` on and `yazses enroll-voice`; `--force`. No `voiceguard` extra exists; the speaker-embedding dependency is the `voiceprint` extra. |

Wave D also produced designs that are not built; they are listed under
[Designed, not built](#designed-not-built).

## Wave E (v2.1) — more frontier features (all off by default)

| Feature | Toggle | What it does |
|---|---|---|
| **Hallucination Guard** | `hallucination` | Drops Whisper's fabricated ghost text on silence/noise (the phantom "Thank you.") before it's typed. |
| **Voice Snippets** | `snippets` | Say a trigger ("insert my signature") to type a stored template. Hold the command key. |
| **Phonetic Corrector** | `phonetic` | Fixes mis-heard proper nouns by sound ("Cuber Netties" → "Kubernetes"). |
| **Hands-Free Auto-Stop** | `autostop` | Tap once and speak; recording auto-stops when you finish. A longer hold is still hold-to-talk. |
| **Voice Mouse Grid** (exp) | `mousegrid` | Say "mouse grid", then cell numbers, then "click" to drive the cursor and click by voice via a numbered grid, on any pixels. Needs absolute pointer motion (X11 or macOS). |
| **Spoken Code Mode** | `code` | Dictate code: spoken symbols → punctuation ("code def sync open paren self close paren colon" → `def sync(self):`), and a style phrase plus words → one identifier ("code self dot camel case user name" → `self.userName`; camel/pascal/snake/kebab/constant case). The identifier ends at the next symbol, the next style phrase, "end case", or the end of the phrase. Hold the command key. |
| **Spoken Math (LaTeX)** | `math` | Dictate equations → LaTeX ("x squared plus y squared" → `x^{2} + y^{2}`). Hold the command key. |
| **Vocal-Strain Guard** (exp) | `voicehealth` | Advises a break when your voice shows rising strain over a session (advisory only; thresholds tuned on synthetic signals). Needs the `prosody` extra, `--force`. |

Auto-Stop and Voice Mouse Grid were designed as two thirds of a **zero-touch bundle**
whose third part, Wake-Word Activation, is [designed, not built](#designed-not-built) —
so today no keyword starts a dictation; your activation input (the hotkey by default)
still does. Multi-User Profiles, also from this wave, is not built either.

## Wave F — self-improvement, adaptation & new modalities (v2.2)

All OFF by default. Pure logic ships now; heavy models load only when you enable the feature.
Toggle with `yazses features enable <name>`.

| Feature | `features` name | What it does |
|---|---|---|
| **Speaking Coach** | `coach` | Private analytics of your dictation: filler rate, words-per-minute, vocabulary diversity. |
| **Smart-Paste** | `smartpaste` | Markdown bullets and autolinked URLs in a notes app; terminals, editors and mail left exactly as dictated. Needs the focused-window probe. |
| **Dictation Reflow** | `reflow` | Say "structure this" to rewrite a ramble into bullets + action items. |
| **Acoustic Context Profiles** | `acoustic_profiles` | Judges the room quiet or noisy from the quietest moments of each recording and, in a noisy room, holds flat background noise to a slightly higher silence gate (relative to your own threshold, in memory only). |
| **Gesture Chords** | `gesture` | Bind multi-input chords (held key + nod / key / sEMG squeeze) to actions. |

## Wave G — normalization, privacy & new modalities (v2.3)

All OFF by default. Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Entity ITN** | `itn` | Spoken emails/versions → written form, no command words ("john dot doe at gmail dot com"). |
| **Redaction Ink** | `redaction` | Masks spoken secrets (cards via Luhn, SSNs, keys) before they're typed. |
| **Field-Aware Dictation** | `fieldaware` | Shapes output by the focused field; refuses to type into password fields. |
| **Corpus Voiceprint Scrub** | `corpus_scrub` | Speaker-anonymizes stored learning audio (keeps content, not voice). |
| **Grammar Repair** | `gec` | Minimal-edit article/agreement fixes for non-native dictation. |
| **Screen-Grounded Dictation** | `screengrounded` | Primes STT with names visible in the focused window so they transcribe right. The window's labels are read through AT-SPI when you press the key, used for that one burst, and never stored or logged. Linux with `python3-pyatspi`; no OCR yet; experimental, untested on real hardware. |
| **Head-Pointer** | `headpointer` | Move + click the cursor by head pose; pairs with voice. Experimental: not yet validated with users. |

## Wave H — normalization, structured input & awareness (v2.4)

All OFF by default. Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Emoji & Symbol by Voice** | `symbols` | Speak symbols/emoji/arrows → Unicode ("right arrow" → →). |
| **Voice Unit Conversion** | `convert` | "twenty miles in kilometers" → "32.19 kilometers", offline. |
| **Spoken Temporal Normalizer** | `temporal` | "next Friday" → a concrete date, from the local clock. |
| **Mid-Utterance Self-Repair** | `self_repair` | "email Sarah no I mean Sara" → "email Sara" before typing. |
| **Spoken Spreadsheet** | `spreadsheet` | Grid navigation by voice ("next row", "next cell", "top of column"). Cell addressing ("go to B7") is **not implemented**: it needs an app-specific Go To binding, and Excel and Calc do not agree on one. |
| **Clipboard-History by Voice** | `cliphistory` | Recall recent copies by voice ("the second thing I copied"). |
| **On-Device Condense** | `condense` | Insert a tightened summary of your own long dictation. |
| **Slot-Filling Dictation** | `slotfill` | One utterance fills a named-field template. |

## Wave I — safety, patterns & power tools (v2.5)

All OFF in the built-in defaults; `cmdsafety` is in the recommended set a fresh install switches on. `latency` was too until it was moved out, because it loads a second model (about 116 MB of RAM). Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Terminal Command Safety Gate** | `cmdsafety` | Holds a destructive terminal command until you say "confirm". |
| **Spoken Regex Builder** | `spokenregex` | Build search patterns by voice ("four digits dash two digits" → `\d{4}-\d{2}`). Hold the command key. |
| **Structured-Markup Dictation** | `markup` | Speak lists/tables → Markdown/org ("bullet list: apples; oranges"). |
| **Document Find-and-Replace** | `findreplace` | Edit the whole document by voice ("replace every utilise with use"). |
| **Hotwords** | `hotwords` | Repairs your vocabulary words the recogniser mis-heard, after decoding, with any engine (guarded; logs each change). Does not bias the decoder. |
| **Voice Window Control** | `windowctl` | Raise a window by name ("focus the browser"), or arrange it ("move window left half", "workspace 3"). X11 only. |
| **Citation-by-Voice** | `cite` | "cite Vaswani 2017" → a formatted citation from your local .bib, offline. |
| **Adaptive Latency Governor** | `latency` | Decodes with a lighter model at a greedy beam while the load average is high. POSIX only; speculative decoding not built. |
| **Diarized Conversation Capture** | `diarize` | Attributed multi-speaker Markdown (**Alice:** …) with rename-by-voice. |

## Wave J — precision input, safety & recovery (v2.6)

All OFF in the built-in defaults; `spelling`, `verbatim` and `corrdict` are in the recommended set a fresh install switches on. Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Phonetic Spelling Mode** | `spelling` | NATO words → exact characters for passwords/codes ("capital alpha bravo double lima" → `Abll`). Hold the command key. |
| **Voice Git Choreographer** | `gitvoice` | `yazses gitvoice "<phrase>"` turns a spoken git phrase into a git command and prints it with how to undo it; `--run` runs it, and a destructive one (force-push, hard reset, `branch -D`) never runs without `--yes`. A command-line tool: there is no spoken-confirm path in the daemon, and it needs no `features enable` — nothing reads `[gitvoice] enabled`. |
| **Confidence-Gated Re-Ask** | `reask` | Holds a burst whose one uncertain their/there-style word Whisper could not settle, and lets you say "second" (or the word) to patch just that word. Opt-in. |
| **Verbatim / Autoformat Toggle** | `verbatim` | "dictate verbatim" freezes all formatting mid-burst; "resume formatting" restores it. |
| **Self-Learning Correction Dictionary** | `corrdict` | Auto-fixes the ASR errors you keep correcting, learned from your own edits. Needs `[learning] enabled`. |
| **Voice Fuzzy File Open** | `fileopen` | "open the mortgage notes" → fuzzy-matches and opens a local file. |
| **Voice Jump-to-Symbol** | `jump` | "go to line 240" / "jump to function tokenize" → the editor moves there. |
| **Spoken Shell Pipeline Builder** | `shellpipe` | Speak stages → render a shell pipeline as text; nothing runs until "run it". |
| **Recording Import** | `recimport` | `yazses transcribe <file>` — transcribe existing recordings offline (wav/mp3/m4a/ogg/flac/opus/mp4) to a sidecar .txt/.md/.srt/.vtt/.json. `--diarize` tags speakers ("Speaker 1:"); `--names`/`--rename` or an enrolled voiceprint name them. Diarizer = sherpa-onnx (`diarization` extra). |

## Wave K — keyboard, compute & session tools (v2.7)

All OFF in the built-in defaults; `compute`, `timeline` and `focusprofile` are in the recommended set a fresh install switches on. Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Chorded Shortcut Synthesis** | `chords` | `yazses chords "press control shift P"` prints the key combo (`ctrl+shift+p`, one per line) to review, script or bind. A command-line tool: it presses nothing, dictation does not recognise spoken shortcuts, and it needs no `features enable` — nothing reads `[chords] enabled`. |
| **Inline Compute** | `compute` | "what's 15% of 240" → types 36, on-device (never `eval`). |
| **Voice Case Transform** | `casetransform` | Recase the selection ("make this snake_case", "camelCase", "SHOUT"). |
| **Auto-Pairing & Wrap** | `autopair` | Balances brackets/quotes in dictated code; "wrap this in parens". |
| **Voice Undo/Redo Timeline** | `timeline` | Undo/redo YazSes output across bursts by voice, even where Ctrl+Z is unreliable. |
| **Session Bookmarks** | `bookmarks` | "bookmark here as intro" + "jump to my last bookmark" for long sessions; the caret position comes from the accessibility layer, never a keypress count. Hold the command key. |
| **Spoken Table Entry** | `tablecsv` | "row: Ada, 1815, London" → tab/comma cells, "next row" advances. |
| **Word-Count & Goal Tracker** | `wordgoal` | Count dictated words, set a goal, ask "how many words so far?" |
| **Local Voice Timer** | `voicetimer` | "set a timer for 25 minutes" — offline; announced by a desktop notification. Hold the command key. |
| **Focus-Class Auto-Profile** | `focusprofile` | Dictates verbatim into a terminal or editor when no `[profiles.app]` glob matches, so a cleanup pass cannot reword a command line. |

Wave K is complete — all ten features are wired. Three of them (`compute`, `timeline`,
`focusprofile`) are switched on by a fresh install's config; the rest are off by default.

## Non-speech & prosodic interaction (Wave L)

A new area: non-speech vocal signals and acoustic prosody as interaction channels — for users who can
phonate but not articulate discrete words, and for word-free eyes-free control.

| Feature | `features` name | What it does |
|---|---|---|
| **Vocal Joystick** | `vocaljoystick` | Continuous analog cursor control by sustaining vowels ("eee"→up-left, "ooo"→up-right, "ahh"→down-right, louder=faster, a held pitch jump=click). Armed by `yazses handsfree resume`, stopped by `yazses handsfree pause` or the stop phrase; the microphone is open only while armed. Thresholds tuned on synthetic signals only. Experimental. |
| **Earcon Feedback** | `earcon` | Non-speech state tones (rising motif = recording, buzz = low confidence) — eyes-free, faster than read-back. |
| **Prosodic Auto-Punctuation** | `prosodypunct` | Inserts periods and commas from the pauses in how you speak — no need to say "comma". Fills gaps only; punctuation the recognizer already wrote is kept. |
| **Hesitation-Hold Endpointing** | `hesitation` | Holds a hands-free turn open on filled pauses ("uhh…") instead of cutting you off. Needs `autostop`. Experimental. |
| **Pitch-Contour Gestures** | `contour` | Hum a shape — rise=confirm, fall=cancel, rise-fall=undo; a flat hum does nothing. Word-free, and only on an empty or hum-only transcript. Tuned on synthetic tones only. Experimental. |
| **Whisper-Aware Mode** | `whispermode` | Detects whispered speech (no fundamental frequency — pure DSP, no model). With `command_channel` (default on): *whisper* a phrase and it runs as a command, speak normally and it types — a hands-free, socially-silent mode switch on a plain microphone. |
| **Mouth-Sound Switch Access** | `mouthswitch` | Single-switch scanning without words: a lip pop starts (or stops) a highlight in the overlay that steps through Enter, Undo, Scroll up, Scroll down and Click every `dwell_s` (1.2 s); a tongue click runs the item lit when the click began, and the scan keeps going on that item, so another click repeats it. Armed by `yazses handsfree resume`, stopped by `yazses handsfree pause` or the stop phrase. Where the overlay cannot run, each step is announced with an earcon and, with read-back on or `[mouthswitch] speak_names`, the item's name (`speak_names` leaves read-back of your dictation off). Thresholds tuned on synthetic sounds only, untested on real hardware. Experimental. |
| **Involuntary-Vocalization Excision** | `involuntary` | Drops cough/throat-clear/sneeze before they corrupt the transcript. |

Wave L: eight of its ten features are wired and off by default, and four of those
(`vocaljoystick`, `hesitation`, `contour`, `mouthswitch`) are experimental and need `--force`.
The other two, `spatialvad` and `breath`, are [designed, not built](#designed-not-built).

## Minimal-bandwidth AAC & text-intelligence (Wave M)

The lowest-bandwidth input methods and new text-intelligence layers.

| Feature | `features` name | What it does |
|---|---|---|
| **Vocal Morse** | `morsevox` | Type by Morse with your voice: a short hum is a dot, a long hum a dash, and each decoded letter is typed (speech-to-text is not run); adaptive timing. Start it by saying "morse mode" or by humming one long steady tone (`[morsevox] entry_hum_s`, 1.5 s); `exit_silence_s` (3 s) of silence ends it, and so does the end-of-work prosign SK (`...-.-` keyed as one character, with no letter gap between S and K), which is not typed. With the hum entry on, the microphone stays open while the daemon runs (a level only, nothing recorded); `yazses handsfree pause` closes it. Thresholds tuned on synthetic signals only. Experimental. |
| **Checksum-Validated Entry** | `checkdigit` | Verifies dictated account/ID numbers (Luhn/ISBN/Verhoeff) and suggests fixes. |
| **Semantic Line Breaks** | `sembr` | Breaks prose one clause per source line so git diffs stay clean. |
| **Acronym & Glossary Manager** | `acronyms` | Expands acronyms on first use, contracts after, warns on undefined. |
| **Style-Consistency Enforcer** | `styleguard` | Applies your house style sheet to each dictation (Vale-lite). |
| **Suggestion-Mode Dictation** | `suggestmode` | Emits edits as CriticMarkup tracked changes for later review. |
| **Screenplay Auto-Format** | `screenplay` | Formats dictated scenes/dialogue as Fountain screenplay markup. |
| **Spaced-Repetition Capture** | `srscap` | "remember that X is Y" → a local Anki cloze card (SM-2). |
| **Diagrams-as-Code by Voice** | `diagramvox` | Dictate a flowchart → Mermaid/Graphviz source, no canvas. |
| **Interruptible Proofreading** (exp) | `proofback` | Hold the key during the read-back of a dictation: what you say next replaces the text from the word being read. Needs Read-Back on. |

Wave M: all ten of its features are wired; `checkdigit` is switched on by a fresh
install's config and the rest are off by default.

## Structural editing, i18n & accessibility-output (Wave N)

Structural code editing, internationalization, and accessibility-output correctness.

| Feature | `features` name | What it does |
|---|---|---|
| **Transliteration** | `translit` | Dictate a native language in Latin letters → native script (Finglish→Persian). |
| **BrailleOut** | `brailleout` | Emit dictation as Grade-2 UEB Unicode Braille for Braille displays. |
| **Spoken Outline** | `outline` | "New item / indent / promote / collapse" drives an outline tree → Markdown/OPML. |
| **Diacritize** | `diacritize` | Restore dropped diacritics — "cafe" → "café", "naive" → "naïve". |
| **SafeGlyph** | `safeglyph` | Flag Unicode confusables/invisibles in identifiers and URLs before injection. |
| **WordFind** | `wordfind` | Offline reverse dictionary — describe a word, get a ranked shortlist. |
| **Echo** | `echo` | "Play that back" replays your own captured audio for a text span (not TTS). |
| **Screen-Reader Pacing** | `srpace` | Pace injection to a screen reader's reading rate, clause-chunked. |

Wave N: eight of its ten features are wired and off by default. The other two,
`hatselect` and `loadguard`, are [designed, not built](#designed-not-built).

## Designed, not built

**Nothing in this section works in this build.** Each capability below has a design
record and a place in the feature registry, and **no runtime code reaches it**:
`yazses features enable <name>` refuses every one, and `yazses features` lists them as
*planned*. They stay listed because this is where a contributor picks one up: each
links the design it would follow, and most also have a `WIRE-*` task in the
[contributor task list](contribute/tasks.md).

**<!-- registry:unwired -->25<!-- /registry --> capabilities** are designed, not built
today — the list below is checked against the registry, so wiring one moves its row back
into its wave's table.

| Capability | Toggle | Wave | Design | What it would do |
|---|---|---|---|---|
| **True Code-Switch** | `polyglot` | B | [ADR-v2-008](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-008-code-switch.md) | Decode a burst that mixes the two languages of a declared `[polyglot] pair` with a code-switch adapter you train yourself. Nothing yet tells the daemon which parts of a burst are in which language, so every burst is decoded by the `[stt]` model with or without an adapter. |
| **Voice-to-Tool (Spoken MCP)** | `agent` | B | [ADR-v2-006](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-006-spoken-mcp.md) | Run allowlisted tools by voice via MCP, with state-changing tools asking first, using a local planner model. |
| **Glasses↔Desktop Bridge** | `bridge` | C | [ADR-v2-013](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-013-glasses-desktop-bridge.md) | Dictate from a paired phone or glasses while the desktop does STT and typing, over a local link only. |
| **Tone-Aware Formatting** | `affect` | D | [ADR-v2-017](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-017-tone-aware-formatting.md) | Add `!`/`?` from your vocal tone, beyond pause punctuation. No tone-detection dependency ships yet. |
| **Meeting Scribe** | `scribe` | D | [ADR-v2-019](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-019-meeting-scribe.md) | A streaming "who said what" transcript tagging you **You** and others **Speaker N**. What ships instead: `yazses meeting` and `yazses transcribe --diarize` (the `diarization` extra). |
| **Ask My Notes (voice RAG)** | `rag` | D | [ADR-v2-020](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-020-voice-grounded-rag.md) | Answer a spoken question from, and cite, your own local notes and documents. |
| **Codec Streaming** | `codec` | D | [ADR-v2-022](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-022-codec-streaming.md) | Route decoding to a low-latency streaming neural-codec engine (Kyutai/Mimi); English/French-centric. |
| **Multi-User Profiles** | `multiprofile` | E | [ADR-v2-028](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-028-multiuser-voiceprint-profiles.md) | Load each enrolled speaker's own vocabulary, hotkey and cleanup from their voiceprint (`[voiceprint] multi_profile`). |
| **Wake-Word Activation** | `wakeword` | E | [ADR-v2-033](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-033-wake-word.md) | Start dictation hands-free on a keyword: always listening, local only. |
| **Audio-Anchored Scrubbing** | `scrub` | F | [ADR-v2-037](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-037-audio-anchored-scrubbing.md) | Keep word timestamps so you can replay what you said or re-dictate one word. |
| **Mood Ledger** | `sentiment` | F | [ADR-v2-040](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-040-mood-ledger.md) | A private speech-sentiment journal whose labels stay in the encrypted corpus. |
| **Pronunciation Feedback** | `pronunciation` | F | [ADR-v2-041](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-041-pronunciation-feedback.md) | Per-phoneme good/fair/poor practice scoring for accent and L2 training. |
| **Personal Read-Back Voice** | `readback_clone` | F | [ADR-v2-042](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-042-personal-readback-voice.md) | Read the transcript back in a clone of your own voice (OpenVoice V2). |
| **Two-Way Live Interpreter** | `interpret` | F | [ADR-v2-044](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-044-two-way-interpreter.md) | A face-to-face mode that detects each turn and translates it into the other language. |
| **Compose-in-Target-Language** | `compose` | G | [ADR-v2-049](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-049-compose-target-language.md) | Speak your strongest language and inject the text in a target language. |
| **Silent Lip-Reading** | `lipread` | G | [ADR-v2-053](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-053-silent-lip-reading.md) | Dictate with no audible voice while a webcam reads your lips. |
| **Sign-Language Input** | `sign` | G | [ADR-v2-054](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-054-sign-language-input.md) | Recognise ASL signed to the webcam and type it. |
| **Ambient Audio-Event Guard** | `audioguard` | H | [ADR-v2-061](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-061-ambient-audio-event-guard.md) | Pause or alert on a doorbell, phone, alarm or your name. |
| **Few-Shot Command Spotter** | `cmdspotter` | H | [ADR-v2-064](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-064-few-shot-command-spotter.md) | Enrolled low-latency micro-commands ("send", "stop"). |
| **Per-Language Auto Switching** | `langroute` | I | [ADR-v2-072](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-072-per-language-model-switching.md) | Detect the language you speak and hot-swap to its model and ITN. |
| **Crowd-Proof Dictation** | `crowdproof` | J | [ADR-v2-084](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-084-crowd-proof-dictation.md) | Reconstruct your voice out of overlapping babble before STT (open-plan office, café). |
| **Beam-Steered Spatial VAD** | `spatialvad` | L | [ADR-v2-098](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-098-spatial-vad.md) | With two mics, gate out sound that does not come from your seat, by its arrival direction. |
| **Breath-Paced Dictation** | `breath` | L | [ADR-v2-099](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-099-breath-paced-dictation.md) | Segment dictation by your natural breath groups rather than silence. |
| **HatSelect** | `hatselect` | N | [ADR-v2-115](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-115-hatselect.md) | Address tokens by spoken label ("delete bravo") for structural editing. |
| **LoadGuard** | `loadguard` | N | [ADR-v2-121](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-121-loadguard.md) | Widen confirmations or defer risky actions when speech shows rising cognitive load. |

Two Wave D directions never got a registry entry at all, because both wait on hardware:
**silent-speech (sEMG)** dictation by mouthing words
([ADR-v2-023](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-023-silent-speech-semg.md)),
and **pure-vision screen commanding** for surfaces with no accessibility tree
([ADR-v2-024](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-024-vlm-screen-commanding.md)).

## Privacy

Every v2 feature honours the same guarantees as the rest of YazSes: on-device
processing, no telemetry, and no transcript persistence unless you explicitly enable
the encrypted learning corpus. Context and gaze signals are read transiently and never
stored. See the
[privacy statement](https://github.com/MSKazemi/yazses/blob/main/docs/privacy-statement.md).
