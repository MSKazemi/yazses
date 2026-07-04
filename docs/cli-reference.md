# CLI Reference

All commands are available as `yazses <command>` once installed globally
(`uv tool install` / `pipx install`), or as `uv run yazses <command>` from the
repo.

**Getting help.** Every command and subcommand accepts both `-h` and `--help`;
each shows its options plus a worked **Examples** block. `yazses --help` lists
all commands grouped into panels (Daemon, Setup & calibration, Dictation &
correction, Remote, Learning & tuning, Updates & maintenance); bare `yazses`
shows the same help. `yazses --version` / `-V` prints the version.

**Tab completion.** Run `yazses --install-completion` once to enable `<Tab>`
completion of commands and options in your shell (`yazses --show-completion`
prints the script to inspect or customise).

## Daemon lifecycle

| Command | Description |
|---|---|
| `yazses start` | Start the daemon detached (PID-file tracked). Under systemd, prefer `systemctl --user start yazses`. |
| `yazses stop` | Stop the running daemon (SIGTERM). |
| `yazses restart` | Stop **all** daemons (including stray/detached ones) and start exactly one. Use this if dictation is being typed twice. |
| `yazses status` | Show state, hotkey, model, injection backend, uptime (over IPC). |
| `yazses features` | List every capability, whether it's on/off, its toggle name, and what's advised. |
| `yazses features info` | Describe **every** capability — name, what it does, and a usage example (the full catalog). |
| `yazses features info <name>` | Describe one capability — what it does, a usage example, and how to enable it. |
| `yazses features enable <name>` | Turn a capability **on** (writes your config), then `yazses restart`. |
| `yazses features disable <name>` | Turn a capability **off**, then `yazses restart`. |
| `yazses-daemon` | Run the daemon in the **foreground** (logs to console) — useful for debugging. |

`yazses start` restarts cleanly if a daemon is already running (never spawns a duplicate).

### Turning features on and off

`yazses features` is the friendly switchboard — no config-file editing needed:

```bash
yazses features                      # see everything + the TOGGLE NAME column + advice
yazses features info                 # describe ALL capabilities + usage examples (pipe to less)
yazses features info dysfluency      # what it does + a usage example + how to enable
yazses features enable dysfluency    # turn one on  (use the TOGGLE NAME)
yazses features disable streaming    # turn one off
yazses restart                       # apply
```

Each row shows an **advice** tier:

| Tier | Meaning |
|---|---|
| `core` | Always on (e.g. Dictation core) — can't be toggled. |
| `recommended (on by default)` | Shipped on; keep it (Voice commands, Mid-Thought Undo, overlay). |
| `recommended` | Safe and useful — worth enabling (e.g. Dysfluency-Friendly if you stutter). |
| `optional` | Enable only if you want that capability (Punch-In, Prosody Ink, Read-Back, …). |
| `experimental — not advised yet` | Known rough edges (Cocktail Filter, Glance-Type). Refused unless you pass `--force`. |

Experimental features are guarded: `yazses features enable cocktail` prints why it's
not advised and exits; add `--force` to override.

## Personal dictionary (words STT mis-hears)

| Command | Description |
|---|---|
| `yazses vocab add <word> ...` | Add words/names to your dictionary so they're spelled right. Then `yazses restart`. |
| `yazses vocab list` | Show your dictionary. |
| `yazses vocab remove <word>` | Remove a word. |

Stored at `~/.config/yazses/vocabulary.txt`; the daemon merges these into Whisper's
`initial_prompt` on every dictation.

### Moving your dictionary to another device

Your dictionary and settings are plain files under `~/.config/yazses/`, so they
move with a simple copy — no export step:

```bash
# on the new device, after installing YazSes:
mkdir -p ~/.config/yazses
scp olddevice:~/.config/yazses/vocabulary.txt ~/.config/yazses/   # the dictionary
scp olddevice:~/.config/yazses/config.toml    ~/.config/yazses/   # hotkey, VAD, etc.
yazses restart
```

Keep `vocabulary.txt` in your dotfiles/backup and it follows you everywhere. The
opt-in learning corpus (`~/.local/share/yazses/`) is **not** part of this — it is
encrypted on-device data and is intentionally not portable (see the
[privacy statement](privacy-statement.md)).

## Hold-to-talk key

| Command | Description |
|---|---|
| `yazses hotkey show` | Show the current dictation key, the command key (if any), and the choices. |
| `yazses hotkey set <key>` | Change the key you hold to **dictate** (e.g. `right_ctrl`), then `yazses restart`. |
| `yazses hotkey command <key>` | Set a dedicated **command** key, or `off` to disable it. Then `yazses restart`. |

Choices: `right_alt` (default), `left_alt`, `right_ctrl`, `left_ctrl`, `right_shift`,
`left_shift`, `right_meta`, `left_meta`, `space`. Prefer a dedicated modifier so it
doesn't collide with normal typing.

### Dedicated command key (force command mode)

By default one key does both jobs: you hold the dictation key, speak, and YazSes
**auto-detects** whether your phrase was a command ("save", "undo") or text. That's
fine for most use, but an exactly-matching phrase can fire a command when you meant
to type it.

A dedicated command key removes the ambiguity. Bind a **second** key — when you hold
it, everything you say is parsed as a command and **never typed as literal text**
(an unrecognised phrase is simply ignored, not inserted):

```bash
yazses hotkey command right_ctrl   # dictate on right_alt, command on right_ctrl
yazses restart
yazses hotkey command off           # back to single-key auto-detect
```

- The command key must be **different** from your dictation key.
- Holding the **dictation** key still works exactly as before (text, with command
  auto-detection).
- Holding the **command** key: "save" → Ctrl+S even though it would normally be text;
  "hello there" → ignored (no command matched), nothing typed.

### Voice command reference

Hold the command key (or, with auto-detect, the dictation key) and say one of
these. Phrases are matched case-insensitively and trailing punctuation is
ignored, so "Save file." works the same as "save". Spelled-out numbers
("delete the last **three** words") are accepted.

| Say | Does |
|---|---|
| "undo" / "undo that" · "undo N times" | Ctrl+Z (× N) |
| "save" / "save file" | Ctrl+S |
| "copy" / "copy that" · "cut" · "paste" | Ctrl+C / Ctrl+X / Ctrl+V |
| "comment" / "comment this" | toggle comment (Ctrl+/) |
| "select all" · "select N lines" · "select to end" | selection |
| "delete the last word" · "delete the last N words" | delete word(s) |
| "delete the last line" · "delete the last N lines" | delete line(s) |
| "new line" / "enter" / "press enter" | Enter |
| "tab" · "escape" · "press backspace" | Tab / Esc / Backspace |
| "page up" · "page down" | Page Up / Page Down |
| "go up / down / left / right" (or "move …") | arrow keys |
| "end of line" · "beginning of line" | End / Home |
| "go to line N" | jump to line N |
| "go to function NAME" · "go to class NAME" · "open file NAME" | editor navigation |
| "run the tests" · "run the build" · "run CMD" | run in terminal |
| "rename this to NAME" | rename symbol (F2) |

Don't see a command you want? Tell us — the grammar is easily extended. Natural-
language commands beyond this fixed list require the optional Tier 2 SLM router
(`[commands] slm_model_path`), which is off by default.

## Updating

| Command | Description |
|---|---|
| `yazses update` | Check for a newer version and offer to install it. Detects the install method and checks the matching source — the tracked **snap** channel for snap installs, **PyPI** for pip / pipx / uv-tool. Only upgrades when the available version is strictly newer (never a downgrade). |
| `yazses update --check` | Only report what's available; don't install. |
| `yazses update --yes` | Install the update without prompting. |

After a successful update, restart the daemon to load it:
`systemctl --user restart yazses` (or `yazses stop && yazses start`).

## Diagnostics & tuning

| Command | Description |
|---|---|
| `yazses setup` | **Linux provisioning, one command.** Installs the audio + injection system packages (`libportaudio2`, `xdotool`, `ydotool`, `wtype`, `xclip`, `wl-clipboard`), adds you to the `input` group, and on Wayland sets up + enables the `ydotoold` user service (required for injection on GNOME/KDE Wayland, where `wtype` is blocked). Idempotent — only fixes what's missing. Re-login after a group change. |
| `yazses setup --dry-run` | Show what `setup` would install/change without doing it. |
| `yazses doctor` | Health check: installed version, daemon status (PID/state/model), **install consistency** (duplicate `yazses` on `PATH`; systemd `ExecStart` pointing at a missing/different binary), keyboard capture, **which input device the hotkey binds to** (flags a virtual injector device that would make the hotkey dead), microphone, session type, injection tools, **injection readiness + `ydotoold` status**, STT model availability, model cache, config dir, active config + hotkey summary, (EMG port / enabled extras if configured). |
| `yazses doctor --mic` | As above, plus record a short ambient clip and warn if room level meets/exceeds `accessibility.vad_threshold`. |
| `yazses mic-level` | Record ~4s, report your average mic level vs the current `vad_threshold`, and recommend a threshold. |
| `yazses mic-level --set` | Same, and write the recommended `vad_threshold` to `config.toml` in place (comments preserved). |
| `yazses mic-level -s N` | Record for `N` seconds instead of 4. |
| `yazses logs` | Print the last 40 lines of the diagnostic log (**metadata only** — never your dictated text). |
| `yazses logs -n N` | Show the last `N` lines. |
| `yazses logs --path` | Print the log file path only (`~/.local/state/yazses/log/daemon.log`). |

## Transcribe a recording (file → text, fully offline)

`yazses transcribe <file>` transcribes an existing audio file **offline** and writes a text file next
to it (`talk.mp3 → talk.txt`). It runs the same local `faster-whisper` STT engine as live dictation —
nothing is uploaded, no cloud, no account. With `--diarize` it also tags who said what. This is a
CLI-only path; it doesn't touch the daemon, hotkey, or your dictation config.

| Command | Description |
|---|---|
| `yazses transcribe talk.mp3` | Transcribe to `talk.txt` next to the input. Accepts wav/mp3/m4a/ogg/flac/opus/mp4. |
| `yazses transcribe mtg.m4a --diarize` | Tag speakers: each line is `Speaker 1: …`, `Speaker 2: …`. |
| `yazses transcribe mtg.wav --diarize --names "Alice,Bob"` | Use real names, mapped to speakers in order of first appearance. |
| `yazses transcribe mtg.wav --diarize --rename speaker_0=Alice` | Name a specific speaker (repeatable). |
| `yazses transcribe lecture.mp3 --format srt` | Write a subtitle file (`txt \| md \| srt \| vtt \| json`). |
| `yazses transcribe call.ogg --diarize --speakers 2` | Force an exact speaker count (`0`/omitted = auto). Also `--min-speakers` / `--max-speakers`. |
| `yazses transcribe talk.mp3 --model small.en` | Override the STT model for this run — `small.en` is more accurate (slower) than `base.en`. Defaults to your `[stt]` model. |
| `yazses transcribe note.m4a --language translate` | Transcribe any language into English. |
| `yazses transcribe clip.wav -o out.txt` | Write to an explicit path instead of the sidecar default. |
| `yazses transcribe mtg.m4a --download-models` | Fetch the ~15 MB sherpa diarization models (one-time; needed for `--diarize`), then exit. |

Notes:
- **Speaker tags need the diarization extra:** `uv sync --extra diarization` (sherpa-onnx — CPU-only, no
  PyTorch, no GPU, no account). Without it, `--diarize` degrades to a plain transcript and tells you.
- **Speaker naming is opt-in and private.** With `--diarize` and an enrolled voiceprint
  (`yazses enroll-voice`), your own voice is auto-labelled **"You"**; everyone else is `Speaker N`
  unless you name them. No new data is stored and no one is ever enrolled automatically — speaker
  voiceprints are biometric data and stay encrypted on this machine. You are responsible for having
  permission to record and transcribe the audio.
- `json` output is lossless (per-word timestamps + speaker); `srt`/`vtt` are subtitles.

## Dictation & injection

| Command | Description |
|---|---|
| `yazses test` | End-to-end self-test: types `YazSes OK` into the focused window (no speaking) so you can confirm injection works. Focus a text editor first. |
| `yazses inject "text"` | Inject text into the focused app without recording (tests the injection backend). |
| `yazses enroll` | Run the accessibility calibration wizard (writes `vad_threshold`, etc.). Note: can set a too-high threshold in a noisy room — verify with `yazses mic-level`. |
| `yazses punch-in` | Re-speak just the wrong phrase to correct the last dictation burst. Records a short window, aligns it against the last burst, deletes it and retypes it corrected. Requires `[punch_in] enabled = true`. |
| `yazses punch-in --dry-run` | List candidate spans without editing, so you can confirm first. |
| `yazses punch-in --choose N` | Apply the candidate at rank `N` (0 = best match). |
| `yazses say "text"` | Speak text aloud through the offline TTS voice (Read-Back Loop). Requires `[tts] enabled = true`. |

### Choosing the injection backend

YazSes types your words into the focused app. On Wayland the default (`auto`)
**types** via ydotool, which works in every app — editors, browsers, **and
terminals** — and never touches your clipboard. If you'd rather paste (instant,
but does nothing in terminals where `Ctrl+V` is literal, and overwrites the
clipboard), set the backend:

```toml
[injection]
backend = "clipboard"   # "auto" (default) | "type" | "clipboard" | "wtype"
```

Or per-run without editing config: `YAZSES_INJECTOR=clipboard`. Run `yazses
restart` after changing it. `yazses status` shows the backend actually in use.

### Voice punctuation (opt-in)

Enable with `yazses features enable voice-punctuation`, then speak the name of a
mark to insert it (say `yazses restart` after enabling):

| Say | Inserts |
|---|---|
| "comma" | `,` |
| "period" / "full stop" | `.` |
| "question mark" | `?` |
| "exclamation mark" | `!` |
| "colon" / "semicolon" | `:` / `;` |
| "new line" | line break |
| "new paragraph" | blank line |
| "tab key" | tab |

Example: *"the tests pass comma ship it period"* → `the tests pass, ship it.`
It is **off by default** because these words also appear in ordinary speech.

## Voice-activity overlay (sonar)

A standalone process that draws neon "sonar" rings near the cursor, expanding and
pulsing with your live voice level while you dictate. PySide6 ships in the base
install (and is bundled in the snap), so the overlay works out of the box — no
extra step. For true see-through rings on X11 you need a compositor (e.g.
`picom`) running.

| Command | Description |
|---|---|
| `yazses overlay` | Run the overlay in the foreground (preview/debug). Connects to the running daemon over IPC. |
| `yazses-overlay` | Same, as a direct console script (this is what the daemon auto-launches). |

Auto-launch with the daemon is **on by default** (`[overlay] enabled = true`);
set it to `false` to opt out. The daemon only spawns the overlay when a display
(`DISPLAY`/`WAYLAND_DISPLAY`) is present **and** PySide6 is installed — if the
`overlay` extra is missing it logs a one-line hint and carries on, so dictation
is never affected.

`[overlay]` config keys:

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Auto-launch the overlay alongside the daemon (soft no-op without PySide6). |
| `style` | `"sonar"` | Visual style (reserved for future styles). |
| `position` | `"cursor"` | `cursor` \| `bottom_center` \| `top_center` \| `corner`. |
| `react_to_voice` | `true` | Drive the animation from live mic level (vs a steady pulse). |
| `accent` | `"#00e5ff"` | Ring colour (neon cyan). |
| `size_px` | `220` | Overlay window square size. |
| `fps` | `60` | Render frame rate. |
| `cursor_offset_px` | `28` | Offset from the pointer (so it isn't under the caret). |

## Remote dictation

| Command | Description |
|---|---|
| `yazses remote <host>` | Forward voice typing to a remote SSH host. `--port/-p`, `--key-file/-i`, `--stop`. |
| `yazses-agent --listen <port>` | Run the remote injection agent on the remote host. |

## Self-improvement loop (opt-in, local, encrypted)

Requires `[learning] enabled = true` (off by default; ADR-012). All data stays
on the machine, encrypted at rest with a machine-bound key.

| Command | Description |
|---|---|
| `yazses tune` | Analyse the captured corpus and **print** proposed config diffs (vocabulary, `vad_threshold`, model, disfluency rules, SLM few-shots). Each proposal is checked against a recent **held-out** slice of the corpus and labelled *validated (N/M held-out)* / *unverified* / *unvalidated (corpus too small)* (ADR-014); corroborated proposals are listed first. Dry-run; changes nothing. |
| `yazses tune --apply` | Same, but review each proposal interactively and write approved ones to `config.toml` (comments preserved). |
| `yazses tune --no-retranscribe` | Skip the larger-model re-transcription pass (faster; uses only flagged/edited signals). |
| `yazses mark-wrong` | Flag the last dictation as a misrecognition (a learning signal). Routed through the running daemon. |
| `yazses mark-wrong -c "what you said"` | Same, attaching the correct text. |
| `yazses corpus status` | Show corpus location, event/discard/flag counts, size, and date range. |
| `yazses corpus forget --minutes N` | Delete events captured in the last `N` minutes (e.g. after dictating something private). |
| `yazses corpus destroy --i-mean-it` | Irreversibly wipe the corpus (database + audio clips). |

### Insights from your corpus (private, on-device)

These read only your local encrypted corpus and require `[learning] enabled = true`.
Nothing leaves the machine.

| Command | Description |
|---|---|
| `yazses coach` | Speaking-style analytics from your recent dictations — filler-word rate, words-per-minute, vocabulary variety. |
| `yazses coach -n 200` | Analyse the last `N` dictations (default `100`). |
| `yazses recall <words…>` | Search your past dictations for those words (Spoken Recall). Also needs `[recall] enabled = true`. |
| `yazses recall` | Show your most recent dictations (no query). |
| `yazses scratch` | Show ambient scratch notes captured by saying "note to self …" in command mode (needs `[recall] scratch = true`). `list` is the default. |
| `yazses scratch clear` | Delete all scratch notes. |

## Models (Tier 2 SLM intent routing)

| Command | Description |
|---|---|
| `yazses model list` | List available / downloaded SLM intent-routing models. |
| `yazses model download <name>` | Download an SLM model. |

## Voice macros (Say-Macro)

Off by default. Enable in `config.toml`, then define triggers in a sibling
`macros.toml`:

```toml
# config.toml
[macros]
enabled = true
author  = "Your Name"      # value substituted for ${author}
path    = "macros.toml"    # relative to the config dir, or absolute
```

```toml
# macros.toml — speak the trigger alone to expand it
[[macro]]
trigger = "license header"
type    = "text"
text    = "# SPDX-License-Identifier: MIT\n# Copyright (c) ${date} ${author}\n"

[[macro]]
trigger = "try except"
type    = "snippet"        # ${cursor} marks where the caret lands after expansion
snippet = "try:\n    ${cursor}\nexcept Exception as exc:\n    raise"
```

- **Matching is whole-utterance exact** (case/whitespace/trailing-punctuation
  insensitive): saying *"license header"* on its own fires; saying it inside a
  sentence does not, so macros never trigger mid-dictation.
- A macro takes precedence over a built-in command of the same phrase.
- **Placeholders:** `${cursor}` (snippet caret, first occurrence), `${date}`
  (`YYYY-MM-DD`), `${time}` (`HH:MM`), `${author}` (from config), `${clipboard}`.
  Unknown `${...}` tokens are left literal. No shell/command execution.
- `type = "actions"` (OS/app key chains) is parsed but dormant in this release
  (lands in P2).

## Mid-Thought Undo

On by default (`[revise] enabled = true`). Say **"scratch that"** (or "delete
that" / "no scratch that") as a whole utterance to delete the last thing YazSes
typed — it issues backspaces, so it works in any text field, and a buffer ledger
ensures it never deletes more than YazSes injected. Saying the phrase inside a
sentence ("scratch the surface") does not trigger it. Disable with
`[revise] enabled = false`.

## Punch-In — correct by re-speaking (off by default)

Enable with `[punch_in] enabled = true`. Run `yazses punch-in`, re-speak just the
wrong phrase, and YazSes locates the closest span in the last burst it typed
(stdlib `difflib`), deletes that burst, and retypes it corrected. Because pure
respeak fixes only ~35% on the first try (Suhm 2001), the alignment surfaces the
top candidates rather than silently splicing — use `--dry-run` to review them and
`--choose N` to apply a specific span.

```toml
[punch_in]
enabled = true
min_score = 0.5         # minimum difflib similarity to surface a span
max_candidates = 3
record_seconds = 4.0    # re-record window for the respoken phrase
```

## Prosody Ink — prosody-driven formatting (off by default, batch dictation only)

Enable with `[prosody] enabled = true`. A long inter-word pause becomes a
paragraph break; with `format = "markdown"` and the `prosody` extra
(`uv sync --extra prosody` → parselmouth) vocal emphasis becomes **bold**.
`format = "none"` keeps paragraph breaks (universal whitespace) and drops bold.
Dictation only; skipped on the streaming path. When enabled, `yazses doctor`
reports whether the `prosody` extra is importable (WARN if missing — pause→¶ still
works, only emphasis is disabled).

```toml
[prosody]
enabled = true
format = "markdown"        # none | markdown
pause_paragraph_ms = 700
emphasis_enabled = true
emphasis_sensitivity = 0.65
max_latency_ms = 150       # above this, logs a warning and degrades to pause-only
```

## Dysfluency-Friendly Mode — clean stuttered / dysarthric dictation (off by default)

Enable with `[accessibility] dysfluency_friendly = true`. The disfluency filter then
collapses sub-word repetitions (`b-b-because` → `because`), short fragment runs
(`b b because` → `because`), heavy unigram repeats (`the the the` → `the`), and
prolongations (`sooo` → `so`) out of the final text — while protecting proper nouns,
code identifiers, URLs, intentional hyphenation (`re-read`), and emphasis (`very very`).
It also widens pre-speech padding for delayed voice onset. It does **not** change
endpointing: YazSes is hold-to-talk, so you control when the utterance ends (ADR-015).
Fully offline, no model training. When on, `yazses doctor` shows the mode's status.

```toml
[accessibility]
dysfluency_friendly = true     # one switch: enables the collapse pass + wider onset padding

# Fine-grained knobs (set individually instead of the preset if you prefer):
[filters.disfluency]
collapse_repetitions = true        # b-b-because / b b because / the the the
collapse_prolongations = true      # sooo -> so
prolongation_min_run = 3           # letter-run length that triggers collapse
repetition_max_fragment_len = 2    # max length of a stutter "fragment"
```

## Read-Back Loop — hear your dictation (off by default)

Enable with `[tts] enabled = true` and `[accessibility] read_back = "final"`, then
install the offline voice: `uv sync --extra tts` (Kokoro-82M, Apache-2.0). After
each dictation YazSes speaks the transcript back so you can verify by ear — useful
eyes-free or with low vision. Commands are never read back. `yazses say "text"`
speaks arbitrary text on demand. A hold during playback barges in (stops the voice).

```toml
[tts]
enabled = true
engine = "kokoro"          # kokoro (default) | melo | kitten
voice = "default"
speed = 1.0
max_readback_chars = 600   # longer bursts are truncated with "…"

[accessibility]
read_back = "final"        # off (default) | final | confirm (P2: spoken yes/no/redo)
```

## Ghost Ahead — endpoint pre-warm (off by default)

Enable with `[endpoint] enabled = true`. The daemon predicts *when* you stop
(stable confirmed prefix + trailing silence) and pre-warms the decode path to hide
release latency. Pre-warm is harmless — the authoritative transcript still happens
on real hold-release, so a wrong guess can never truncate text. Speculative
finalize stays gated behind `speculative_finalize` (Phase 2).

```toml
[endpoint]
enabled = true
prewarm = true
debounce_ms = 500          # anti-thrash between endpoint fires
```

---

# v2 — perceptual & personalization layer (all off by default)

Four advanced features that personalize and focus recognition. All are **off by
default**, **fully local**, and need an optional extra and/or hardware (mic/webcam)
or a one-time training step. Plans: `design/v2-cognitive-layer/`.

| Command | Description |
|---|---|
| `yazses enroll-voice` | Record a sample and save your encrypted **speaker voiceprint** (needed by Cocktail Filter + Voiceprint Mind). Requires `[voiceprint] enabled` + `uv sync --extra voiceprint`. |
| `yazses gaze calibrate` | Calibrate webcam gaze → screen zones for **Glance-Type**. Requires `[gaze] enabled` + a webcam + `pip install l2cs mediapipe opencv-python`. |

## Voiceprint Mind — personalize STT to your voice (`[personalize]`)
P1 (available now): bias the recognizer toward your vocabulary so it spells your
jargon and proper nouns. Set `YAZSES_VOCABULARY="GitHub,Kubernetes,kubectl"` and:
```toml
[personalize]
enabled = true
max_prompt_terms = 64
# lora = true   # P2: opt-in nightly LoRA personal fine-tune (needs compute; gated)
```
P2 (LoRA fine-tune on your own audio) is planned and gated on a held-out WER win.

## Cocktail Filter — ignore other voices (`[cocktail]`)
Drops audio frames that aren't *you* before transcription, so a nearby voice never
enters the text. Enroll once (`yazses enroll-voice`), then:
```toml
[voiceprint]
enabled = true             # speaker embedder (uv sync --extra voiceprint)
[cocktail]
enabled = true             # mode = "gate" (P1); "suppress" (P2) is gated on a model
target_threshold = 0.6     # higher = stricter "is this me?"
```

## Glance-Type — look at a pane to target it (`[gaze]`)
Coarse webcam gaze picks the screen zone/window your next dictation lands in
(look-to-pane, not look-to-caret). Needs a webcam + a one-time `yazses gaze calibrate`:
```toml
[gaze]
enabled = true
zones = "grid3x3"          # grid3x3 | grid2x2 | windows
camera_index = 0
```
The camera is used in-RAM during a hold only — frames are never stored or sent.

## Polyglot Switch — mixed-language dictation (`[polyglot]`)
Transcribe speech that mixes two languages (e.g. `fa-en`). Needs a trained
code-switch adapter for the pair (stock Whisper can't code-switch); the routing is
scaffolded and the adapter is gated on a held-out MER win.
```toml
[polyglot]
enabled = true
pair = "fa-en"
adapter_path = ""          # path to the trained CS adapter; empty = dormant
```

`yazses doctor` reports whether each enabled feature's extra is importable.

## Diagnostic log format

`yazses logs` shows lines like:

```
INFO yazses.core.daemon: Transcribed 2.1s audio in 480 ms (model base.en, level 0.0043)
INFO yazses.core.daemon: Injecting 24 chars, 5 words.
INFO yazses.core.daemon: Silent audio -- discarding (level 0.0009 < vad_threshold 0.0021; run 'yazses mic-level --set' to retune).
```

These are **metadata only** — audio level, latency, model, counts, and errors.
The actual transcript text is logged only when `general.log_level = "DEBUG"` in
`config.toml`.
