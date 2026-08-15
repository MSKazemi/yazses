---
title: Stop a misheard command from running — the Command Safety Gate
description: YazSes can hold a destructive dictated command (rm -rf, mkfs, dd, curl to sh, git push --force) until you say confirm, so a misrecognition cannot fire it. How to turn it on, what it catches, and what it deliberately does not.
---

# Stop a misheard command from running

Dictation into a shell has a failure mode that dictation into a document does not:
**the mistake executes.** A misheard word in an email is a typo you fix. A misheard
word in a terminal can be `rm -rf` against the wrong path, and there is nothing to
fix afterwards.

The **Command Safety Gate** holds a dangerous command instead of typing it, and waits
for you to say **"confirm"**.

## Turn it on

```bash
yazses features enable cmdsafety
yazses restart
```

Off by default, like every feature that changes what happens to your keystrokes.

## What it does

Dictate something destructive and nothing is typed:

```
you say:   "rm dash rf slash home slash work"
YazSes:    ⚠ Held: recursive/forced delete. Say "confirm" to run it.
you say:   "confirm"
YazSes:    types  rm -rf /home/work
```

Say anything else instead and the held command is **discarded**, and what you just
said is typed as normal dictation. You never have to remember a magic word to escape
— the gate only ever fails in the direction of *not* running the command.

| You say next | What happens |
|---|---|
| `confirm` | The held command is typed. |
| `cancel` | The held command is discarded. Nothing is typed. |
| anything else | The held command is discarded, and your words are typed normally. |

## What it catches

From `cmdsafety/classify.py`, first match wins:

| Pattern | Why |
|---|---|
| `rm -rf`, `rm -r`, `rm -f` | recursive/forced delete |
| `dd … of=` | raw disk write |
| `mkfs` | format filesystem |
| `shutdown`, `reboot`, `halt`, `poweroff` | power state change |
| `git push --force` / `-f` | force push |
| `git reset --hard` | discards changes |
| `curl … \| sh`, `wget … \| bash` | pipe download to shell |
| `> /dev/sd*`, `/dev/nvme*` | overwrite block device |
| `:(){ :\|: }` | fork bomb |
| `chmod -R 777` | recursive world-writable |

`sudo`, `git clean -dfx`, `truncate` and moves into a system path are classified
**caution** — noted, but not held. Holding everything containing `sudo` would make
the feature unusable and train you to say "confirm" reflexively, which is the same as
not having it.

## What it deliberately does not do

**It does not check whether a terminal is focused.** The feature was designed as a
*terminal* gate, and the obvious implementation asks the focus detector what has
focus. That answer is not available in the sessions where the guard matters most:
focus detection needs AT-SPI or X11, so on Wayland without AT-SPI the window class is
simply empty. A guard that silently stops protecting on an entire display server is
worse than no guard, because you believe it is on.

So the gate reads the command text and nothing else. The patterns above are specific
enough that ordinary prose almost never matches one, and when it does the cost is
saying "confirm" once. The reverse mistake — letting a misheard `rm -rf /` through
because the compositor hid the window class — cannot be undone. The costs are
asymmetric, so the gate fails safe.

**It is not a sandbox.** It gates what YazSes *types*. It has no view of what you type
by hand, what a script runs, or what a command does once confirmed.

**It holds one command at a time.** A second dangerous command replaces the first,
which is discarded rather than queued.

## Change the words

```toml
[cmdsafety]
enabled = true
confirm_words = ["confirm", "do it now"]
cancel_words  = ["cancel", "never mind"]
```

A phrase only counts when it is the **whole** utterance. "Cancel the meeting" is
dictated text, not a control word — ordinary English words are also commands, and
matching them loosely is how a previous attempt in this project swallowed 4 of 6 test
phrases.

Leaving a list empty falls back to the defaults rather than removing the words, so a
config edit cannot leave a held command with no way to release it.

## Related

- [Staged dictation](../features.md) — review a whole burst before any of it types.
  Complementary: staged catches *any* mis-transcription, this one catches the
  unrecoverable ones even when you are typing straight through.
- [Dictating code and technical vocabulary](../use-cases/dictating-code.md)
- [Voice commands](../use-cases/voice-commands.md)
