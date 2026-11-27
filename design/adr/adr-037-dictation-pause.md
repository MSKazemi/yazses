# ADR-037 — Pausing dictation (proposed)

**Status:** Proposed (2026-11-27) · pure rules and tests only (`src/yazses/core/dictation_pause.py`, imported by nothing); no daemon, IPC, CLI, tray or config change; awaiting the maintainer's decision  
**Decision owner:** YazSes maintainer (pending). A new IPC method and CLI surface are L3 work (AGENTS.md, "Public interfaces").  
**Context:** [ADR-010](adr-010.md), [ADR-019](adr-019-egress-inventory-and-escalation.md), [ADR-021](adr-021-invest-in-error-cost.md), [ADR-v2-127](adr-v2-127-live-meeting-mode.md), [ADR-v2-148](adr-v2-148-hands-free-composition.md)

## Context

There is no way to pause dictation short of stopping the daemon.

- `TrayState.PAUSED` exists. The macOS tray has a glyph for it, and the meeting, enrolment
  and idle-unload guards in `core/daemon.py` accept it. Nothing ever sets it.
- The macOS menu had a "Pause hotkey" entry whose handler only showed a message; the key
  went on recording. It is being removed rather than left to mislead.
- `yazses handsfree pause` (ADR-v2-148) stops hands-free inputs. The keyboard still dictates.

A real pause has to be enforced where recording starts, and recording starts in more than
one place. A gate on the hotkey alone would be the same false promise as the menu entry.

## Decision (proposed)

**While dictation is paused, the daemon opens no microphone for dictation, starts no turn
that could type speech, and discards the recording that is open.** It is a promise about
dictation, not a microphone mute: a running meeting and the hands-free control inputs keep
listening, and every surface that reports the pause must not claim otherwise.

The pause is a flag held beside the daemon's state. Storing it *in* `TrayState` would let
the next burst, meeting or read-back overwrite it, and would change every existing
`state == IDLE` guard (a mouth switch, for one, would go deaf). The daemon keeps its
internal state as today and reports `paused` only where it would otherwise report `idle`.
Every other state (meeting, transcribing, injecting, remote, error, loading, read-back,
enrolling) is reported unchanged, because each names something the user still needs to see.

### Every activation path

| Path | Entry point in `core/daemon.py` | While paused |
|---|---|---|
| Dictation key, hold | `_on_hold_start` | Refused |
| Dictation key, toggle (`[hotkey] mode`) | `_on_toggle_press` | A new recording is refused; the latch is not set |
| Tap-to-latch hands-free turn (`[autostop]`) | `_on_hold_start`, `_autostop_defer_end` | Refused; nothing latches |
| Command key | `_on_command_hold_start` | Refused; `_command_mode` is not set |
| EMG (serial, BLE), face and biosignal switches held to talk or command | the two handlers above | Refused |
| Wake word (`[wakeword]`) | none: `wakeword/detector.py` has no caller | A future spotter must hold no stream while paused and must ask the gate before recording |
| Vocal Morse (listens and types) | `_start_morsevox`, `_try_morse_mode`, `_morse_inject` | Mode ends, its stream closes and stays closed |
| Punch-In (IPC `punch_in`, with or without `respoken`) | `_handle_punch_in` | Refused with a reason |
| `ask_human` (MCP) | `_handle_ask_human` | Refused as *deferred* ("not now"), before anything is spoken, spending no budget |
| Face switch `confirm` (types held dictation) | `_switch_confirm` | Refused; the held item stays held. `cancel` still works |
| Meeting: `meeting start`, `stop`, auto-stop, the running capture | `_handle_meeting_*` | **Unaffected.** The pause reply says a meeting is still recording |
| Dictation key during a meeting | `_on_hold_start` | Refused, like any dictation |
| Head pointer, gesture chords, mouth switch, vocal joystick, voice mouse grid, face `select`, biosignal blink or clench commands | their own runtimes | **Unaffected**; `handsfree pause` stops them. The mouse grid's spoken phrases arrive by dictation, so only its `mousegrid` IPC can still drive it |
| IPC `inject`, `staged commit`, `send_to`, `say` | their handlers | **Unaffected**: explicit commands that capture nothing |
| Re-calibrate, enrolment | `_handle_recalibrate_mic`, `_handle_enroll_start` | **Unaffected**: the user asked for that recording, and it types nothing |

A refused press types nothing at all, including the backspaces that clean up leaked
characters of a character hotkey: while paused that key is the user's. The synthetic
modifier key-up on release stays (it types nothing and prevents a stuck modifier). A press
still silences read-back, but arms no proofreading target. The first press of each pause
shows one notification ("Dictation is paused"); each refused press may play the error
earcon where `[earcon]` is on.

### A pause during a burst

| When the pause arrives | What happens |
|---|---|
| Recording (hold, toggle, tap-latch, switch, command) | **Discarded.** Audio is not transcribed, typed, staged or written to the learning corpus. Latches (toggle, tap-latch, biosignal) and `_command_mode` are cleared. The user is told |
| Recording with live partials already typed (`[streaming]`) | The streaming injector is sealed and the partials **stay on screen**. No backspaces: focus may have moved to the tray menu |
| `ask_human` or Punch-In listening | Stopped and discarded; the caller gets a refusal |
| Released, now transcribing or typing (or waiting for a model reload) | **Finishes.** The user ended that burst on purpose. The reply says so |
| Vocal Morse mode | Ends; characters already typed stay |

The key that was held releases later; that release finds no burst and does nothing.

Why discard rather than type: the likely way to pause is a menu or a second window, so the
text would land in the wrong place. Repeating a sentence is cheaper than text in the wrong
application (ADR-021).

### Resume

Only an explicit resume lifts the pause: no timeout, voice phrase, gesture or
`handsfree resume`. Resume starts nothing; a key held across it must be pressed again.
`handsfree pause` and this pause are independent flags, and neither command touches the
other's. Hands-free resume while dictation is paused leaves Vocal Morse's stream closed and
says why. The pause is held in memory: after a restart, crash or reboot dictation is on.
The tray does not replace a daemon that reports `paused` (`core/takeover.py` already
excludes it).

## Rules the wiring must keep

1. Ask the gate (`admit`) and enter `RECORDING` under the same hold of the daemon lock, and
   take that lock to pause. Otherwise a pause lands between the question and the answer.
2. Ask `still_allowed` again after `recorder.start()` returns (a pause may have landed while
   the device opened) and when `_on_hold_end` claims the burst, before it moves to
   `TRANSCRIBING`. A release racing the pause then discards too, whoever stops the
   recorder. A pause after the claim does not affect the burst.
3. Clear the latches synchronously inside the pause. Their watcher threads are too slow: a
   quick resume and press would meet a latch that is still set.
4. Vocal Morse must not share its `handsfree` pause flag: add the dictation pause to what
   its stream opening checks, close the stream on pause, reopen on resume only if hands-free
   input is not paused.

The first two use `Admission` tickets so that pause-then-resume during one recording still
voids it. This ADR's module holds the decisions; the daemon supplies the effects.

## Proposed interfaces (not implemented)

- **IPC** (ADR-010 contract, additive): method `dictation`, `action` = `status`, `pause` or
  `resume`. Reply: `ok`, `paused`, and for `pause` also `discarded`, `finishing` and
  `meeting_recording`. No `toggle`: two surfaces toggling at once end in the state nobody
  chose.
- **`status`:** `state` is `paused` when idle and paused; a `dictation` block with `paused`
  and `paused_for_s` is present in every state. Readers of `state` that list the ready
  states (`cli.py`) must accept `paused`, and the report redactor must classify the block.
- **CLI:** `yazses dictation pause | resume | status`.
- **Tray:** one "Pause dictation" / "Resume dictation" entry on all three trays, driven by
  the `dictation` block so it is right during a meeting too.
- **Config:** none. The feature does nothing until someone invokes it.

## Alternatives rejected

- **Unhook the hotkey listener.** Misses the switches, Punch-In, `ask_human` and Morse, and
  re-grabbing a key can fail, leaving no way back.
- **Reuse `handsfree pause`.** It would silence a hands-free user's pointer when they only
  meant to stop typing, and its resume has camera re-arm semantics.
- **Stop the daemon.** Already possible; it unloads the model and drops the meeting.
- **Gate at the injector.** The microphone would still record.

## Consequences

- Pause and resume need the keyboard, pointer or a terminal. A user who works only by voice
  and switches cannot reach either in the first version.
- A third thing called "pause" exists next to hands-free and Head-Pointer pause, so every
  surface must say "dictation".
- A future capture path must be added to `CapturePath`; the tests fail until it is put on
  one side. They cannot detect a new `recorder.start()` that never asks.

## Questions for the maintainer

1. Discard the open recording (proposed), type it, or keep it in the staged buffer?
2. Should a burst already being transcribed finish (proposed) or be withheld?
3. Should the pause survive a restart? Proposed: no.
4. Should it also close the mouth-switch and vocal-joystick microphones, or stop a meeting?
   Proposed: neither.
5. Should a switch binding be able to pause and resume in a later step?
6. Are the names `dictation` and `yazses dictation pause` right?
