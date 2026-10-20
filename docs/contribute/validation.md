---
title: Release validation checklist and evidence standard
description: What a human tester checks on a real machine for every YazSes release, and exactly what evidence turns a platform or install route into verified on hardware. Provisional standard; privacy rules included.
---

# Release validation checklist and evidence standard

CI proves that the code runs on a runner. It cannot hold a key, grant a permission prompt or hear a
microphone, and the defects that reached users on macOS and Windows were all of that kind. This
page is the shared rule for when a platform or install route may be called **verified**, and the
checklist a tester follows to produce that evidence.

!!! info "Status: provisional"

    This is the first version, written from the proposals in
    [#387](https://github.com/MSKazemi/yazses/issues/387). Nothing here is a threshold measured on
    many machines; the staleness rule and the check list will change after they have been used for
    a few releases. The results live in the [validation matrix](../validation-matrix.md); the Mac
    campaign built on this page is [macOS validation campaign](macos-validation.md).

You do not need to run every check on every platform. A report that covers three rows honestly is
worth more than one that claims twelve. **Say "not tested" for anything you skipped** — a blank is
read as a gap to fill, not as a pass.

## The evidence vocabulary

Every cell in the matrix carries exactly one of these words.

| Status | Meaning | Needs |
|---|---|---|
| **Verified (HW)** | "Verified on hardware": a named human ran the check on a real machine and it worked | A complete [evidence record](#the-evidence-record) |
| **Failed (HW)** | A named human ran it on a real machine and it did not work | The same record, plus what happened instead |
| **CI only** | "Verified by automated test only": a job passed; no person has tried it | A link to the run, and what the job actually does |
| **Reported** | "Reported by user, not reproduced": someone said it works or fails, but the record is incomplete | The report; the missing fields go in the Gap column |
| **Blocked** | Could not be tried because an earlier step fails or no suitable device exists | What blocks it and which issue tracks that |
| **UNVERIFIED** | "Not yet tested": nobody has tried it | Nothing; this is the honest default |

Two rules keep the words honest:

1. **A virtual machine or a CI runner is never "hardware".** A runner has no microphone and no
   held key, and a VM usually has no real audio path or permission prompt. Those results are
   **CI only**, or **Reported** if a person ran them in a VM and says so.
2. **"Verified" belongs to the version that was tested.** A cell records the YazSes version and the
   date. A later release does not inherit it; the cell is simply older evidence until someone
   repeats the check. When a release changes the area a cell covers, that cell is due for a re-test.

Both a **last positive** and a **last negative** record are worth keeping for the same check: *when
did this last work, and when did it last fail?* That is more useful to a troubleshooter than one
status word, and the status word is derived from those two records. A failure stays visible after
the fix ships and is replaced by a positive record only when someone confirms the fix on hardware.
(This last point is a provisional choice; see [open questions](#open-questions).)

## The evidence record

For a result to count as **Verified (HW)** or **Failed (HW)**, the report contains
all of the following. A report that lacks one is still welcome; it is graded **Reported** and the
missing item is named as the gap.

| Field | What to write | How to get it |
|---|---|---|
| Who | Your GitHub handle | — |
| Date | The day you ran it | — |
| Device | Model and CPU/chip (for example "Mac mini, Apple M2", "Dell laptop, Intel, Windows 11 Home") | Settings, About |
| OS build | Full version, not "latest" | macOS `sw_vers`; Windows `winver`; Linux `cat /etc/os-release` |
| Session | Linux only: X11 or Wayland, and the desktop | `echo $XDG_SESSION_TYPE $XDG_CURRENT_DESKTOP` |
| Install route | One of: `.dmg`, Homebrew cask, pipx, `uv tool`, `.exe` installer, Scoop, winget, snap, Flatpak, apt/`.deb`, install script, source | what you actually ran |
| Fresh or upgrade | Fresh install, or upgraded from which version | — |
| YazSes version | Exact | `yazses --version` |
| Command output | `yazses doctor` pasted as text, and `yazses verify` if you got that far | see [Privacy](#privacy-rules) |
| Observed result | What appeared, and in which application | one line per check |
| Not tested | Every check below you skipped or could not run | say so explicitly |

"It works" with none of this is a claim, not evidence. The Windows 11 report in
[#183](https://github.com/MSKazemi/yazses/issues/183) is a good model for the shape: numbered
steps, the model, the compute type, the injection backend and the four applications tried.

## Privacy rules

Nothing leaves your machine unless you attach it, so read what you attach.

* **Never attach audio, a transcript of what you said, voiceprints or learning-corpus files.** The
  checks below need none of them. If you want to show that text appeared, name the application
  and say "a short test sentence appeared"; do not paste a dictated paragraph.
* **Remove your username, hostname and home path** from `doctor` output, logs and screenshots.
  `yazses report` writes a redacted diagnostic file locally and uploads nothing; read it before
  attaching. SHOWCASE entries are scanned for home paths and emails by
  `scripts/check-compatibility.py`.
* **Crop screenshots** to the dialog or settings pane in question. Do not include other windows,
  notifications or browser tabs.
* A camera-based or microphone-based test must use a short synthetic phrase you are willing to
  publish ("testing one two three"), not a conversation.

## What to run on every release

Groups follow the structure proposed by the tester who volunteered for this role in #387. Run the
ones that fit your device; each line is *do this, attach that*.

### Install

| # | Check | Attach |
|---|---|---|
| INS-1 | Install by **one** documented route, exactly as its guide says ([Linux](../install-linux.md), [macOS](../macos-install.md), [Windows](../windows-install.md)). Every documented route needs its own test; do not assume one covers another | the route, the version, any error shown |
| INS-2 | Negative test for a known limit the guide states (for example, "needs administrator rights", "unsigned: right-click, Open"). Confirm the limit and the message are still as documented | the message, verbatim |
| INS-3 | Uninstall by the route in [Uninstalling](../uninstall.md) and confirm nothing is left running | `ps` / Task Manager result, or "none" |

### First use

| # | Check | Attach |
|---|---|---|
| USE-1 | First launch: does it start, and does something visible show (tray or menu-bar icon)? | yes/no and where |
| USE-2 | Permissions: were you asked, was the prompt findable, did granting it work? Name **each** permission separately (macOS: Accessibility, Input Monitoring, Microphone; Windows: microphone privacy switch; Wayland: portal prompt) | one line per permission |
| USE-3 | `yazses doctor`, then `yazses verify` | both outputs, redacted |
| USE-4 | Documentation check: did the guide's troubleshooting section match what you saw? | the page and the mismatch |
| USE-5 | First successful dictation: hold the key, say a short test sentence, release | which application the text landed in |

### Everyday dictation

| # | Check | Attach |
|---|---|---|
| DIC-1 | Hold-to-talk into a plain text editor | application name, result |
| DIC-2 | Into a browser text box and a terminal | per application |
| DIC-3 | Start, `restart` and stop: `yazses start`, `yazses status`, `yazses restart`, `yazses stop`. After a restart, does `status` show the daemon, and does the key still work? (If you changed a setting first, it should now apply.) | the four outputs |
| DIC-4 | Overflow: a small text field and more speech than fits | what happened to the rest |
| DIC-5 | Background noise and rapid speech, one short phrase each | whether text appeared; no transcript |
| DIC-6 | Long session, a few minutes, still running at the end | `yazses status` at the end |

### Meeting mode

| # | Check | Attach |
|---|---|---|
| MTG-1 | `yazses meeting start`, a short call from a source you control, then `yazses meeting stop` (needs `[meeting] enabled = true`; see [meeting notes](../meeting-notes-offline.md)). Does a transcript file result? | file exists and its size; **not its content** |
| MTG-2 | Speaker change markers present when two voices alternate | yes/no |
| MTG-3 | Delete the meeting files by the route the meeting guide describes, and confirm they are gone | what you ran, the result |

Meeting-mode checks involve other people's speech. Use only your own voice or a consenting
participant, and never attach the output.

### Upgrade and regression

| # | Check | Attach |
|---|---|---|
| UPG-1 | Upgrade by the route's standard command from a previous release | from-version, to-version, errors |
| UPG-2 | Remove and reinstall the new version | same |
| UPG-3 | After either, repeat USE-3 and USE-5. A permission that stopped applying after an upgrade counts as a **Failed** here | doctor output |
| REG-1 | For every bug fixed in this release that was reported on a platform you own, run the reporter's original steps | the bug number and the result |

The "closed bugs" group starts empty. Add a line per closed platform bug so the next release re-runs
it; a fix that has only ever passed in CI is not yet a regression check.

## How to report

Open an issue from the platform's existing test issue
([#182](https://github.com/MSKazemi/yazses/issues/182) for Apple silicon,
[#216](https://github.com/MSKazemi/yazses/issues/216) for Intel Mac,
[#183](https://github.com/MSKazemi/yazses/issues/183) for Windows 11,
[#217](https://github.com/MSKazemi/yazses/issues/217) for Windows 10, or the Linux distro issue
listed in the [task finder](find.md)), or reply on one that already exists. Paste this block and
fill it in.

```markdown
**Tester:** @your-handle      **Date:** YYYY-MM-DD
**Device:** model, CPU/chip
**OS build:** full version (Linux: session + desktop)
**Install route:** …         **Fresh or upgrade:** …
**YazSes version:** (output of `yazses --version`)

| Check | Result (worked / failed / not tested) | Note (no dictated text) |
|---|---|---|
| INS-1 | | |
| USE-1 | | |
| USE-2 (each permission) | | |
| USE-3 doctor / verify | | output below |
| USE-5 first dictation | | application: |
| DIC-3 start/restart/stop | | |
| UPG-1 upgrade | | from → to |

<details><summary>yazses doctor (redacted)</summary>

…paste…

</details>

**Not tested / could not verify:** …
```

A maintainer then adds the result to the [validation matrix](../validation-matrix.md) with a link to
your comment. You do not have to edit the matrix yourself.

## Open questions

These were put to the tester in #387 and are unanswered at the time of writing. The provisional
answers above stand until they reply.

1. **Mobile rows.** iOS, iPadOS and Android appear in the proposed setup codes. YazSes does not
   support them (see [platform support](../platform-support.md) and the
   [mobile notes](../mobile/index.md)), so they are not in the matrix. They can be reserved when
   a mobile build exists.
2. **After a fix.** A failure record is kept visible until a positive hardware record replaces it,
   rather than clearing when the fix merges. This costs a longer table and avoids a cell turning
   green on a fix nobody has run.
3. **A searchable dashboard** was proposed. The matrix is a plain table first; a dashboard can be
   generated from it once the table has been used for a few releases.
