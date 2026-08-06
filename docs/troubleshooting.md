---
title: YazSes troubleshooting — dictation not working, no text, mic issues
description: Fixes for the most common YazSes problems — hotkey not firing, no text appearing, silent audio discarded, microphone switching, and Wayland text injection.
---

# Troubleshooting

## Dictation stopped working right after I edited config.toml

If every hold is accepted but no text ever appears, read the log first:

```sh
yazses logs
```

A line like this means the pipeline threw an exception on every burst:

```
WARNING yazses.core.daemon: Pipeline error: ufunc 'less' did not contain a loop
with signature matching types (Float32DType, StrDType) -> None
```

`Float32DType` is your audio, `StrDType` is a config value that should have been a number. The usual cause is a quoted number in `config.toml`:

```toml
[accessibility]
vad_threshold = "0.004"   # wrong — this is a string
vad_threshold = 0.004     # right — bare number
```

In TOML, only string values take quotes. Numbers (`int`, `float`) and booleans must be bare, and the [Configuration Reference](configuration.html) lists the expected type for every key. A quoted number loads without any error and only fails later, deep in the pipeline, so the message never mentions the file you edited.

The safe way to change a setting is to let YazSes write it, since these commands always emit the right type:

```sh
yazses features enable <name>    # feature toggles
yazses hotkey set right_ctrl     # hold-to-talk key
yazses audio use "<mic name>"    # input device
yazses mic-level --set           # measure and write vad_threshold
```

## Dictation still works, but it behaves differently than it used to

Every setting that affects the pipeline is announced when the daemon starts, so the log is an accurate record of what was actually in effect — including on previous days.

```sh
yazses logs -n 25          # this run's startup banner
```

A healthy start looks roughly like this. Each line reflects a config value, so a line that is present, missing, or different from what you remember tells you exactly which setting changed:

```
Loading STT model 'base.en'...          ← [stt] model
Injection backend: XdotoolInjector      ← [injection] backend
Streaming STT enabled (partial …)       ← [streaming] enabled  (absent when off)
Command key enabled: hold right_alt …   ← [hotkey] command_key (absent when unset)
YazSes ready. Hold right_ctrl to dictate.  ← [hotkey] key
Launched voice-activity overlay …       ← [overlay] enabled
```

To compare against a day when it behaved the way you wanted, look at the rotated log, which keeps the previous startups:

```sh
grep -h "YazSes ready\|Streaming STT\|Command key\|Loading STT model" \
  ~/.local/state/yazses/log/daemon.log.1 ~/.local/state/yazses/log/daemon.log
```

Two settings are worth checking first, because both change how dictation feels without ever producing an error:

- **`[streaming] enabled = true`** runs a transcription pass every 300 ms during the hold, on top of the final one. On a CPU-only machine that competes with the transcription that actually produces your text. It is off by default for this reason.
- **`[accessibility] vad_threshold`** decides what counts as silence. Too high and quiet speech is dropped with `Silent audio -- discarding`; too low and room noise is transcribed. It is specific to your microphone and room — run `yazses mic-level --set` rather than copying a value from someone else.

## Dictation stops after connecting a USB-C monitor or headset

Some monitors, docks, and headsets register an audio input and become the operating system's default microphone. When that input is silent or very quiet, YazSes can keep running but stop writing dictated text because each recording is discarded as silence.

Check which device YazSes is using:

```sh
yazses audio status
yazses audio devices
```

The mic-change guard normally detects a default-input change and switches back to the last working microphone. To prevent the operating system from changing the capture device again, pin the intended microphone using a case-insensitive part of its displayed name, then restart YazSes:

```sh
yazses audio use "Built-in Microphone"
yazses restart
```

Run `yazses audio status` again to confirm that the pinned microphone is active. To return to following the operating system default later, run:

```sh
yazses audio use --clear
yazses restart
```
