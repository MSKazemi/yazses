---
title: YazSes troubleshooting — dictation not working, no text, mic issues
description: Fixes for the most common YazSes problems — hotkey not firing, no text appearing, silent audio discarded, microphone switching, and Wayland text injection.
---

# Troubleshooting

## Start here: prove where it breaks

Before reading further, let YazSes tell you which part is broken:

```sh
yazses verify     # records you, then runs capture → silence gate → transcription → cleaning
```

It reports each link in the chain and stops at the first failure, so you get the one thing
to fix rather than four symptoms of it. `yazses doctor` complements it by checking
prerequisites — a mic exists, the injector is installed, the model is cached — but every one
of those can pass while dictation still produces nothing, which is why `verify` exists.

If you want to report a problem, `yazses report` writes a diagnostic file locally — versions,
daemon state, settings with paths and identifiers removed, and the metadata-only log tail.
Your dictated text is never in it, and **nothing is uploaded**; the file is yours to read
before deciding to attach it to an issue.

## YazSes usually tells you first

Most failures now announce themselves as a desktop notification that names the cause and
the command that fixes it — a microphone another program has taken, a missing `ydotool`, a
full disk. So the first thing to do is read the message rather than start here.

Two details worth knowing:

- **The same problem is announced once every five minutes, not once per attempt.** A
  microphone that will not open fails on every burst, and repeat toasts would only teach
  you to dismiss them. The state is still in `yazses status` and the tray tooltip
  throughout.
- **When YazSes cannot work out what went wrong**, the notification carries a *Prepare a
  bug report* button. It assembles the same redacted bundle `yazses report` writes and
  opens GitHub's issue form with it **filled in** — you read it there, in your own
  browser and account, and press submit yourself. **YazSes sends nothing**; the browser
  makes the request. A failure YazSes *does* recognise gets no button, because it already
  told you the fix.

!!! tip "Some of this fixes itself — check before you debug"

    A microphone that was stolen mid-session, a silence gate that drifted above
    your voice, a crashed daemon and a crashed tray all recover on their own, and
    each says so when it happens. If you are about to debug one of those, read
    **[what recovers by itself, and what does not](reliability.md)** first — it
    also lists the failures that are deliberately left for you, so you can tell
    which kind you are looking at.

## My desktop asked to allow "Remote Desktop" — why does a dictation app want that?

Because on Wayland there is no narrower permission to ask for. `RemoteDesktop` is the
only portal interface that lets one application type into another's window, so every tool
that types on your behalf — dictation, accessibility software, automation — goes through
the same door, and inherits the name it was given for its original purpose, screen
sharing. The confirm button says **Share** for the same reason.

What YazSes actually requests is the keyboard and nothing else:

- it asks the portal for `KEYBOARD` devices only, never the pointer;
- it never touches the ScreenCast interface, so no screen capture is possible with it;
- the calls are local D-Bus to your own desktop — no network, consistent with YazSes
  being offline by design.

**Your top bar will show a screen-sharing indicator the whole time the daemon runs.** That
is your desktop reporting that a `RemoteDesktop` session is open; it cannot tell that the
session was granted the keyboard alone, so it shows its generic icon. It is not evidence
that anything is being captured or sent.

You are asked **once** — the answer is remembered with a restore token stored at
`~/.local/share/yazses/portal_remote_desktop_token` (mode `0600`). Delete that file to be
asked again.

### Getting rid of the prompt entirely

The portal is a *fallback*. YazSes prefers `ydotool`, which injects directly and needs no
permission dialog, and only falls through to the portal when `ydotoold` is not running.

Two things have to be true for `ydotool` to work, and on a stock Ubuntu **neither is by
default** — which is why most Wayland users land on the portal:

1. the **`ydotoold` daemon** must be installed. On Debian/Ubuntu it is a *separate package*
   from the `ydotool` client, so installing `ydotool` alone leaves the service pointing at
   a binary that does not exist;
2. `/dev/uinput` must be openable by your user. It ships `0600 root:root`, so belonging to
   the `input` group grants nothing without a udev rule.

`yazses setup` now does both:

```sh
yazses setup      # installs ydotoold + the /dev/uinput udev rule, joins `input`
# log out and back in — the group and the rule only apply to a new session
yazses doctor     # the Injection line names the backend actually in use
```

**The log-out is not optional.** Until you start a new session the rule has not reached it,
`ydotoold` still cannot open the device, and YazSes will keep using the portal.

The exception is the **strictly confined snap**, which has no package manager and cannot
install a udev rule — there the portal is genuinely the only way to type on Wayland, and
`yazses setup` is not offered.

If you declined the dialog, dictation falls back to pasting via the clipboard, which is a
no-op in terminals. Approve it, or run `yazses setup`, then `yazses restart`.

## It works, but not after I reboot

YazSes is a daemon, so it should already be running when you sit down:

```sh
yazses autostart status   # will it come back after the next reboot?
yazses autostart enable   # make it
```

Installing with `pipx`, `uv tool` or `pip` does not set this up on its own. `yazses doctor`
reports it as a **Starts at login** check.

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

In TOML, only string values take quotes. Numbers (`int`, `float`) and booleans must be bare, and the [Configuration Reference](configuration.md) lists the expected type for every key. A quoted number loads without any error and only fails later, deep in the pipeline, so the message never mentions the file you edited.

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

## YazSes typed a sentence I never said

Speech models do not return "I heard nothing". Given near-silence they return their best
guess at what a person would have said, and that guess is ordinary, fluent English — not
gibberish you could spot. YazSes filters the recognisable cases (a blank marker, a caption
artefact, a phrase repeating in a loop) but an invented sentence is indistinguishable from
a real one to everything except you.

What makes it happen is a silence gate set *below* your room, so the noise floor is treated
as speech and sent to be transcribed. Check it:

```sh
yazses verify
```

If the `Signal` line ends with **"but only just"** and a multiple close to `1`, that is the
cause. Your voice should sit several times above the gate; noise sits just over it.

```sh
yazses mic-level --set   # measure this room, write the threshold
yazses restart
```

Then run `yazses verify` again in a quiet room without speaking. The outcome you want is
`verify` **failing** at either `Signal` or `Speech` — the model being *given* nothing is the
only reliable way to stop it inventing. `Speech` is the one that fires when room noise
clears the gate: it runs a speech detector on what was actually recorded, so a quiet room
is named as a quiet room rather than transcribed into a confident word.

Raising the gate too far has the opposite failure and it is the visible one: quiet speech is
dropped with `Silent audio -- discarding` in `yazses logs`. That is why the automatic tuner
only ever lowers the gate — a mic that hears too little tells you so, and a mic that hears
too much does not.

## Windows: one app gets `????` or `----` where the words should be

The giveaway is that it is *one application*. The same dictation lands correctly in a
browser and arrives in an editor or a notes app as the right **number** of characters
with every one of them wrong — rows of `?`, `-` or `.`.

Nothing is wrong with the transcript. YazSes types on Windows with `SendInput` and the
`KEYEVENTF_UNICODE` flag, and Microsoft documents two ways an application can receive
that keystroke incorrectly:

- **An ANSI window.** Windows converts each character to the application's ANSI codepage
  on the way in and substitutes `?` for anything that codepage cannot represent.
- **A text service that does not unpack `VK_PACKET`.** `KEYEVENTF_UNICODE` synthesises a
  *VK_PACKET* keystroke that carries the character as data. A text input service that
  does not read it out runs the keystroke through your keyboard layout instead, so the
  whole sentence comes out as the same wrong character repeated.

Chromium handles `VK_PACKET` explicitly, which is why the browser is always fine.

Find out which window you are really typing into:

```sh
yazses inject -d 5 --diagnose "hello world"
```

You then have five seconds to click into the application under test. It reports the
focused control, whether it is a Unicode window, and your active keyboard layout, and
then types. If the text is mangled there too, the application is the cause. If it is
clean there but dictation is not, the problem is in the hold-to-talk path, not the
injector — say so in an issue.

The fix is to paste rather than type, which depends on neither condition:

```toml
[injection]
backend = "clipboard"
```

```sh
yazses restart
```

The transcript goes on the clipboard as Unicode text and YazSes sends a real Ctrl+V.
Your previous clipboard contents are put back afterwards. Two trade-offs come with it,
and they are why typing remains the default: Ctrl+V is literal in most terminals, so
dictation into a terminal stops working, and applications that refuse paste (some
password fields) receive nothing.

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
