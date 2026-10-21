---
title: Stop hands-free input by voice
description: Say a short phrase to pause the Head-Pointer, gesture chords and face switch without touching anything. What it matches, what it never does, how to change the phrase, and how to resume.
---

# Stop hands-free input by voice

When the pointer, the gesture chords and the face switch are doing the work, the moment you
most need to stop them is the moment you can least aim a pointer or reach a key. The **voice
stop word** is one more way to stop, and it needs neither: say the phrase and every hands-free
input pauses, exactly as if you had run `yazses handsfree pause`.

## Turn it on

It is on whenever the hands-free preset is on:

```toml
[handsfree]
enabled = true
```

The preset fills in `[handsfree_safety] stop_phrase = "pause hands free"`. That default is
**provisional**: nobody has measured how reliably speech recognition transcribes it across
accents, microphones and rooms, so treat it as a starting value (`yazses handsfree explain`
says so too). Check it works in your own room before you rely on it.

Outside the preset the stop word is **off** (`stop_phrase = ""`), and turning on the global
stop alone does not enable it. To use it without the rest of the preset, or to change the
phrase:

```toml
[handsfree_safety]
enabled = true
stop_phrase = "freeze the pointer"
```

To keep the preset but switch only the voice stop off, set `voice_stop = false` under
`[handsfree]`, or set `stop_phrase = ""`. A key you write always wins over the preset.

The phrase must be **2 to 6 words**. A single word such as "stop" is refused at load, with a
message, and the stop word stays off: one word is far too often the whole of something you
dictate, and a stop that fires on ordinary dictation is one people learn to switch off.

## What counts as saying it

Only a **whole utterance** that is the phrase. Case, punctuation at the edges and the way the
recogniser spaces or hyphenates a word do not matter: "Pause hands free.", "pause hands-free"
and "pause handsfree" are the same phrase.

Nothing else counts. Dictating a sentence that merely contains the words types the sentence:

| You say | What happens |
|---|---|
| "pause hands free" | Hands-free input pauses. Nothing is typed. |
| "Pause hands-free." | The same. |
| "I will pause hands free mode while I type this" | Typed as dictation. Nothing pauses. |
| "please pause hands free" | Typed as dictation. Add "please" to your own phrase if you want it. |
| "pause hands free and resume" | Typed as dictation. |

## What happens when it fires

- Every hands-free input stops: the pointer, the gesture chords and the face switch. With the
  global stop (`[handsfree_safety] enabled`) off, only the Head-Pointer can be paused, and the
  notification says so rather than letting you believe more was stopped.
- The words are **not typed** into the focused application.
- You get a notification (and the stop tone if earcons are on) saying what was paused and how
  to resume. If nothing could be paused, the notification says that instead.
- It works whether the gate is active, paused or faulted, and saying it again while paused is
  harmless.

## It only ever pauses

There is no resume phrase, on purpose. A phrase that re-arms a pointer you just stopped is a
separate risk, and a recogniser that mishears it would undo your stop. To resume, use any of:

```bash
yazses handsfree resume
```

or Tray → **Settings…** → **Hands-free controls…** (the tray menu itself has no hands-free item).

## Limits you should know

- The phrase reaches YazSes as a **dictation burst**: something has to start capture (a hotkey,
  or the face switch while it is still running). Once hands-free is paused the face switch no
  longer starts a burst, so after a pause you resume with the commands above, not by voice.
- Real speech recognition of the default phrase has not been measured. If it is often
  misheard in your setup, choose a phrase that your microphone and accent transcribe cleanly,
  and keep `yazses handsfree pause` and Tray → **Settings…** → **Hands-free controls…** as
  your fallbacks.
- Nothing about this leaves your machine: the phrase is matched on the transcript, locally.
