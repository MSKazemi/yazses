---
description: "A community list of microphones that work well with YazSes, each with the vad_threshold that actually worked on a real machine. Adding yours takes two minutes and needs no Python."
---

# Known-good microphones

Microphone quality affects transcription accuracy more than almost anything else you can
change — more than the Whisper model size, in most rooms. This page is a **community list**:
real microphones, on real machines, with the `vad_threshold` that actually worked.

**Adding your microphone is a genuinely useful two-minute contribution**, and you do not need
to know any Python. See [Add yours](#add-yours) below.

!!! note "No entries yet — be the first"

    This page was created so people can append to it without waiting for anyone. If the table
    below is still empty when you read this, add the first row.

## The list

Sorted by microphone name. Entries are contributors' own reports, not endorsements, and
nothing here is tested by the maintainers.

| Microphone | Type | OS / desktop | `vad_threshold` | Notes |
|---|---|---|---|---|
| _(your entry here)_ | | | | |

## Add yours

1. **Measure your mic** — this prints the number the table wants:

    ```sh
    yazses mic-level
    ```

    It records for a few seconds, reports your average level against the current threshold,
    and recommends a value. Add `--set` if you want it written to your config as well.

2. **Check your room** while you're there — this warns if ambient noise is loud enough to
   trip the silence gate on its own:

    ```sh
    yazses doctor --mic
    ```

3. **Add one row** to the table above, in alphabetical order by microphone name, and delete
   the `_(your entry here)_` placeholder row if it is still present.

4. Open a pull request titled `docs: add <microphone> to known-good microphones`.

### What to put in each column

| Column | What to write |
|---|---|
| **Microphone** | The model as it is sold — `Blue Yeti`, `Jabra Evolve2 65`, `ThinkPad T14 built-in`. |
| **Type** | `USB`, `built-in`, `XLR + interface`, `Bluetooth`, or `headset`. |
| **OS / desktop** | e.g. `Ubuntu 26.04 / GNOME (Wayland)`, `macOS 15`, `Windows 11`. Wayland vs X11 matters. |
| **`vad_threshold`** | What `yazses mic-level` recommended, or the value you settled on. |
| **Notes** | The useful part — how far from your mouth, whether it needed the gain turned down, whether Bluetooth mode hurt quality. |

**Negative results are welcome and wanted.** A microphone that transcribed badly, needed an
odd threshold, or dropped to 8 kHz in headset mode is *more* useful to the next reader than
another good result. Say so plainly in the notes.

### Good to know

- **`vad_threshold` is machine-specific.** It is compared against `mean(|audio|)` for your
  input, so a value that works on a quiet desktop may cut off speech in a noisy room. Treat
  the numbers here as starting points, not settings to copy blindly.
- **If dictation logs `Silent audio -- discarding`,** your speech is falling below the gate —
  lower the threshold. If room noise produces spurious transcripts, raise it. See
  [Troubleshooting](troubleshooting.md).
- YazSes can also **pin** an input so a newly-connected device cannot steal capture:
  `yazses audio use "<name>"`. Worth noting in your entry if you needed it.
