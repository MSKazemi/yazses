# 🎙️ YazSes Showcase — how people use it

A community list of real YazSes setups. Seeing how others dictate helps newcomers get started —
and adding yours is a friendly **first contribution**.

## Add yours (a 2-minute PR)

1. Copy the block below to the **bottom** of this file (new entries go last to avoid conflicts).
2. Fill it in — keep it short.
3. Open a PR titled `showcase: add <your name/handle>`.

```markdown
### <your name or @handle>
- **OS / desktop:** e.g. Ubuntu 24.04 (GNOME, X11)
- **Mic:** e.g. Blue Yeti / laptop built-in
- **Apps you dictate into:** e.g. terminal, VS Code, email
- **How you use YazSes:** one or two lines — what it replaced, what you love, a tip
```

Any setup is welcome — beginner or power user. 💛

---

## Setups

### @MSKazemi (maintainer)
- **OS / desktop:** Ubuntu (GNOME, X11)
- **Mic:** laptop built-in (pinned with `yazses audio use`)
- **Apps you dictate into:** terminal, VS Code, git commit messages, GitHub issues
- **How you use YazSes:** hold-to-talk for everything I'd otherwise type — commit messages, notes,
  and long-form prose. The tray icon + mic-change auto-heal mean it "just works" even when a
  USB-C monitor tries to steal the mic. Tip: run `yazses mic-level --set` once after any mic change.

### @jayavandhiniMK
- **OS / desktop:** Windows 11 Home
- **Mic:** Laptop built-in microphone
- **Apps you dictate into:** VS Code, terminal, GitHub
- **How you use YazSes:** I use YazSes for coding, writing, and everyday text input.
  It helps me dictate quickly while working on projects and open-source contributions.

### @hoti-code
- **OS / desktop:** macOS (Apple silicon)
- **Mic:** MacBook Air built-in microphone
- **Apps you dictate into:** TextEdit
- **How you use YazSes:** Tested the Homebrew cask install for
  [#182](https://github.com/MSKazemi/yazses/issues/182). Install and the Gatekeeper override
  succeeded, but the app did not stay running, no menu-bar icon appeared, macOS showed no
  Accessibility / Input Monitoring / Microphone prompt, the Right Option hotkey produced no
  text, and `doctor` reported keyboard capture and microphone access denied.
  **Diagnosis: the tap was serving 2.18.2** — frozen since 2026-08-13 because `TAP_TOKEN` was
  never set — so this run predates both macOS fixes (`3bffc07`, `7b039fb`) and is not the
  current build's behaviour. This report is what surfaced the frozen tap, which no dashboard
  was reporting.

### @visheshbpatel
- **OS / desktop:** Windows 11
- **Mic:** Laptop built-in microphone
- **Apps you dictate into:** Web browser, VS Code, PowerShell, GitHub
- **How you use YazSes:** Tested YazSes on Windows 11 while working on an open-source contribution. I used it for writing GitHub comments, typing commands and notes in PowerShell, and writing in VS Code. Dictation successfully converted speech to text and injected it into the tested applications. It worked well as a hands-free text input method for everyday development tasks.


<!-- Add your entry above this line's section by appending a new ### block at the end. -->
