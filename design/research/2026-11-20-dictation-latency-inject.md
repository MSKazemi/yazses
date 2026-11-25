# Dictation latency after the decode: post-processing, injection and the state machine

**Date:** 2026-11-20 · **Status:** measurement record and owner recommendations ·
**Author:** Mohsen Seyedkazemi Ardebili · **Scope:** from "transcript ready" to "text in the
focused window" on the default hold-to-talk path. The decode itself (`stt/`, `audio/`) is
out of scope here.

Evidence labels: **[M]** measured in this repository on 2026-11-20 · **[F]** a primary
source says so · **[O]** engineering judgement · **[U]** not verified.

Machine: 4 cores, Linux, CPython 3.12, shared with other jobs (`uptime` load 1.7–7.3 during
the runs, so the medians below matter more than the p95s). No `xdotool`, `ydotool` or
`wtype` is installed on it, so **no real keystroke was sent**. The injection numbers are a
real process spawn plus ydotool's documented pacing, run through a stand-in binary that
sleeps that pacing (method below). They are not a uinput or X11 measurement.

---

## 1. Where the time goes

For a 40-word dictation (205 characters) on the default configuration:

| Stage | Cost | Label |
|---|---|---|
| Default post-processing chain (cleaner, disfluency filter, command grammar, profile, continuation spacing) | **0.13 ms** median (0.36 ms at 150 words) | [M] |
| Its first-burst cost (lazy imports, regex compilation) | ~2 ms, once per process | [M] |
| Typing it with `xdotool type --delay 12` (X11) or `ydotool type -d 6 -H 6` (Wayland) | **~2.5 s** (12 ms × 205 chars) | [F] pacing / [O] total |
| ydotool flood guard after the typing (60 key-ups × 12 ms) | **~730 ms** before this change, **~420 ms** after | [M] stand-in |
| Hold-end hotkey key-up, in series in front of the decode | **~18 ms** (1 key), ~31 ms (2 keys) | [M] stand-in |

The post-processing chain is four orders of magnitude below the typing. There is nothing to
win there, which agrees with the 0.29 ms already recorded in `docs/benchmarks.md`
("Everything that isn't the model is free"). Nearly all the time after the decode is
**keystroke pacing**, and the pacing is a default.

Per-stage medians from the 300-repetition run, in µs (median / p95):

| Words | clean_text | disfluency | classify | resolve_profile | continuation | total |
|---|---|---|---|---|---|---|
| 10 | 2.6 / 2.7 | 56.6 / 102 | 16.3 / 17.5 | 0.7 / 1.4 | 8.4 / 8.6 | **85** |
| 40 | 1.1 / 1.2 | 93.3 / 115 | 24.9 / 28.4 | 0.6 / 0.7 | 7.3 / 21.8 | **127** |
| 150 | 1.2 / 1.3 | 279 / 537 | 68.7 / 132 | 0.6 / 0.7 | 7.7 / 7.8 | **357** |

The subprocess count per burst was already minimal: `XdotoolInjector` and `WtypeInjector`
type the whole burst in **one** spawn, and so does `YdotoolInjector` for ASCII text, plus one
spawn for its flood guard. There is no per-chunk spawning to collapse on the default path
(`[srpace]` pacing, off by default, is the exception by design).

## 2. What changed (text and ordering unchanged)

### 2.1 The ydotool flood guard releases the keys the burst pressed, not a fixed sweep

After every `ydotool type`, `YdotoolInjector` sent a key-up for each of keycodes 2..57 plus
the four hotkey modifiers: 60 tokens. `ydotool key` waits its key delay after **every**
token, 12 ms in 1.x unless told otherwise (the repository's own `ydotool_key_timeout`
budgets for exactly this), so the guard cost about 720 ms per burst. That is longer than a
`base.en` decode of a short sentence.

ydotool 1.x `type` does not consult the layout. It maps each character through a fixed
US-QWERTY table and lets the active XKB layout interpret the keycode, which is why #329 lost
accented letters. So which keycodes a successful `type` pressed is a pure function of the
text. `release_tokens_after_typing(text)` releases exactly those, plus both shifts, left
Ctrl/Alt, Space and the four hotkey modifiers on every burst. The pacing is the same, and
it never sends a token the old sweep did not send. A character outside the table (a control
character) falls back to the full sweep, and so does a `type` that failed mid-string, the
one case nobody has measured.

| Burst | Tokens | Guard time (median, n=20 interleaved A/B) |
|---|---|---|
| 10 words / 57 chars | 60 → 29 | 736 → 364 ms (p95 745 → 371) |
| 40 words / 205 chars | 60 → 34 | 730 → 418 ms (p95 737 → 427) |
| 150 words / 773 chars | 60 → 34 | 728 → 416 ms (p95 734 → 421) |

[M], stand-in method. Saving: **~310–370 ms per burst on every Wayland ydotool session.**
The guard still runs after the text is on screen. What the saving buys is the time until
the daemon is ready for the next burst. With `[srpace]` pacing it also buys every gap
*between* paced clauses, because each clause is its own `inject` call.

### 2.2 The hold-end hotkey key-up runs alongside the decode

`_release_hotkey_modifier` (the stuck-right-Alt fix) ran synchronously on every hold-end,
in front of the decode: one spawn plus 12 ms per key, ~18 ms for the default `right_alt`.
It now runs on a thread while the decode runs. Every keystroke waits for it: the join sits
in `_active_injector()` (which every post-hold-end injection path uses), right after the
decode, and in the pipeline's `finally`. So the key-up still lands before any typed
character. With streaming partials on screen it stays synchronous, because an early
discard cancels them with backspaces through `StreamingInjector`, which does not go through
`_active_injector`. Saving: **~18 ms per burst (~31 ms with a command key)**, Wayland with
ydotool only. X11 never spawned anything here.

## 3. Owner recommendations (L3: defaults and behaviour, not changed here)

Ranked by size. None of these is implemented. Each needs a hardware check of the kind
ADR-030 pillar 1 asks for before any default moves.

1. **Keystroke pacing is the latency.** At 12 ms per character, a 150-word dictation takes
   ~9.3 s to type on X11 and on Wayland ydotool [F pacing, O total]. Halving the delay
   halves that. Proposal: a dormant `[injection] type_delay_ms` (default 12, unchanged),
   so a user can opt in and the validation matrix can record which applications keep every
   character at 6, 4 and 0 ms. `xdotool --delay 0` is known to drop or reorder keys in some
   toolkits and over remote sessions [U]. That risk is why this is a measurement task
   before it is a default.
2. **Long bursts into non-terminal windows could paste.** `ClipboardInjector` is a near
   constant ~0.3 s on Wayland: 150 ms settle, plus ydotool Ctrl+V at a 40 ms key delay
   [O, from the code]. That beats typing for anything over ~25 characters. It overwrites
   the clipboard and does nothing in terminals (where Ctrl+V is literal), and terminals are
   the agent-era target ADR-030 names. So any version of this must be opt-in, length-gated
   and gated by app class (`focusprofile` already classifies `shell`/`code`), and it must
   restore the clipboard. That is a feature, not a tuning change, and it falls under the
   breadth freeze.
3. **The flood guard's own pacing.** After 2.1 the guard still spends ~12 ms per token,
   ~400 ms on a long burst. Sending its key-ups with `-d 0` would make it ~5 ms. Whether
   mutter drops back-to-back synthetic key-ups the way it drops a final one is not known
   [U]. The guard exists because of mutter's dropped events, so this needs a GNOME
   Wayland check, not a guess.
4. **Do nothing to the post-processing chain.** Sub-millisecond at 150 words. Pre-warming
   imports would save ~2 ms once per process.

## 4. Method

- Post-processing: each default stage called on synthetic 10/40/150-word transcripts, 300
  repetitions per stage, `time.perf_counter`. Cold costs come from five fresh processes
  that import `yazses.core.daemon` first (as a running daemon has), then time the first
  call of each stage.
- Injection: a stand-in `ydotool` on `PATH` sleeps 12 ms per `key` token, which is
  ydotool 1.x's documented default pacing. Old and new release argv were run through the
  real `run_ydotool` → `subprocess.run`, interleaved A/B, 20 rounds per length. A bare
  `subprocess.run(["true"])` spawn measured 3.98 ms median on this machine.
- Everything above uses synthetic text. No user audio or transcript was used.
