---
title: Platform validation matrix — what has been tried on real hardware
description: Which YazSes platforms, install routes and features have been verified on real devices, which have only passed CI, and which nobody has tried. Every cell cites its evidence or says UNVERIFIED.
---

# Platform validation matrix

This page answers a narrower question than [platform support](platform-support.md). Support says
what is **published and installable**. This page says what a **person has actually run on a real
machine**, with the evidence, and where nobody has.

* Evidence was read from the public issues, merged pull requests and CI runs listed in the
  [evidence log](#evidence-log) on **2026-10-16** (one row, Windows arm64, corrected on
  2026-10-20 from E23). Nothing here is inferred from how the code
  looks. If a cell has no entry in the log, it says **UNVERIFIED**.
* The latest release at that date is v2.42.0. Hardware evidence is for the version named in each
  entry, and **a later release does not inherit it**.
* The words and the rules for what counts are in the
  [evidence standard](contribute/validation.md). The Mac-specific plan is the
  [macOS validation campaign](contribute/macos-validation.md).

The project maintainer has no Mac and no Windows machine, and CI cannot answer a permission prompt
or hear a microphone. Every hardware cell below exists because a volunteer ran the check.

## Reading a cell

| Word | Meaning |
|---|---|
| **Verified (HW)** | A named human, a real device, the exact version, with output. |
| **Failed (HW)** | The same, and it did not work. Kept until a positive record replaces it. |
| **CI only** | An automated job passed; no person has tried it. |
| **Reported** | Someone says so, but the record is missing a field (usually the OS build or the raw `doctor` output). The Gap column names it. |
| **Blocked** | Cannot be tried until a named issue is resolved. |
| **UNVERIFIED** | Nobody has tried it. |

`E<n>` points to a row in the [evidence log](#evidence-log). A cell's version is the YazSes version
that was tested.

## macOS

Apple silicon and Intel are separate rows: they ship separate `.dmg` files.

| Setup | Install | First launch | Permissions | Capture + transcription | Text injection | Start / restart / stop | Update path | Last human validation | Gap / next tester |
|---|---|---|---|---|---|---|---|---|---|
| **Apple silicon, `.dmg`** | **Verified (HW)** E2 E3. 2.37.2 and 2.40.0: drag to Applications works; the unsigned-app prompt appears as documented. | **Verified (HW)** E3. 2.40.0: opens after the "Open Anyway" step in System Settings; menu-bar icon appears. | **Failed (HW)** E3. 2.40.0: Accessibility and Input Monitoring both switched on, yet `doctor` and the daemon log say denied; unchanged after `tccutil reset`. Cause unknown ([#562](https://github.com/MSKazemi/yazses/issues/562)). | **Verified (HW)** E1. 2.29.0, 2026-08-21: `verify` captured, passed the silence gate and transcribed a test phrase. Not repeated on a later release. | **Blocked** E3. The hotkey never fires on 2.40.0 ([#562](https://github.com/MSKazemi/yazses/issues/562)), and nobody has run `yazses verify --type`, which reaches the injector without the key. No report has seen typed text on a Mac. | **Failed (HW)** E3. 2.40.0: `doctor` said "Daemon: not running" while one ran; an old daemon outlived days and a relaunch exited as a duplicate. Whether Quit was used is unknown ([#578](https://github.com/MSKazemi/yazses/issues/578)). | UNVERIFIED | 2026-10-05 (E3) | Needs a Mac on a release newer than v2.42.0. The `doctor` fix from #562 is not in v2.42.0. Run the [reporter script](contribute/macos-validation.md#reporter-script). |
| **Apple silicon, Homebrew cask** | **Reported** E4 E5. The cask installs once `brew trust MSKazemi/yazses` is run. Both runs used a stale 2.18.2 tap, not today's. | **Reported** E4. 2.18.2 tap: the app did not stay running and showed no icon. Predates the fixes; not the behaviour of a current build. | **Reported** E4. 2.18.2 tap: no prompt appeared. Same caveat. | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | 2026-08-28 (E4, stale tap) | Anyone on today's cask: `brew trust MSKazemi/yazses`, install, then the reporter script. |
| **Apple silicon, pipx** | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | The permission goes to the terminal app, not to a bundle. [#182](https://github.com/MSKazemi/yazses/issues/182) and [#216](https://github.com/MSKazemi/yazses/issues/216) both ask; nobody has walked it. |
| **Intel, `.dmg`** | **CI only** E21. The x86_64 `.dmg` builds and its contents are verified on an Intel runner (v2.42.0). | **CI only** E21. The bundle's `--cli --version` and `doctor` run on that runner; a GUI launch is not exercised. | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | An Intel Mac with the x86_64 `.dmg`. [#216](https://github.com/MSKazemi/yazses/issues/216) still tells testers the `.dmg` will not work; that text is out of date. |
| **Intel, pipx** | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | An Intel Mac. This route outlives GitHub's Intel runners (see [platform support](platform-support.md#macos)). |

## Windows

| Setup | Install | First launch | Permissions | Capture + transcription | Text injection | Start / restart / stop | Update path | Last human validation | Gap / next tester |
|---|---|---|---|---|---|---|---|---|---|
| **Windows 11 x64, pipx or install script** | **Reported** E10 E12. 2.36.0: install script (E10) and pipx (E12). | **Reported** E10 E11. 2.36.0: daemon starts; `doctor` clean apart from an autostart warning. | UNVERIFIED | **Reported** E10 E11. Two independent reports, 2.36.0, built-in laptop microphone, `base.en`, CPU int8. | **Reported** E10 E11. Browser, VS Code, PowerShell, Notepad, terminal. | **Failed (HW)** E12 E13. 2.36.0: `start` printed a traceback though the daemon came up; `restart` crashed. Both fixed in `ece081f`. On that commit the hotkey set in config was not applied after `restart`, and a blank console window stayed open. No later hardware result is posted ([#330](https://github.com/MSKazemi/yazses/issues/330) is open). | UNVERIFIED | 2026-09-30 (E13) | Re-run the [#330](https://github.com/MSKazemi/yazses/issues/330) checklist on v2.41.0 or later. Reports E10 and E11 lack the OS build and the raw `doctor` text. Nobody has said whether a privacy prompt appeared. |
| **Windows 11 x64, Scoop** | **Reported** E12. 2.36.0. | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | **Failed (HW)** E12. 2.36.0: same `start` and `restart` failures as above, reproduced on this route too. | UNVERIFIED | 2026-09-08 (E12) | The Scoop bucket is still open work ([#79](https://github.com/MSKazemi/yazses/issues/79)). Needs a full run, not only lifecycle. |
| **Windows 11 x64, `.exe` installer** | **CI only** E22. Silent install, payload present, `yazses-cli --version` and `doctor` run, `PATH` entry added and removed (v2.42.0). | **CI only** E22. The CLI runs; the windowed app is not launched. | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | No human report names this route. |
| **Windows 11 arm64, `.exe` installer** | **CI only** E22 E23. The `windows-arm64` leg passed the same install, run and uninstall checks on v2.42.0, but that file was an x64 build; from v2.43.1 there is no arm64 installer and ARM PCs run the x64 one (E23). | **CI only** E22 | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | A Windows-on-ARM device running the x64 installer. A runner has no microphone and no hold-to-talk key. |
| **Windows 10 x64, any route** | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | [#217](https://github.com/MSKazemi/yazses/issues/217). The one volunteer asked has no Windows 10 machine (E40). |

## Linux

| Setup | Install | First launch | Permissions | Capture + transcription | Text injection | Start / restart / stop | Update path | Last human validation | Gap / next tester |
|---|---|---|---|---|---|---|---|---|---|
| **Ubuntu 24.04, GNOME Wayland** | UNVERIFIED | UNVERIFIED | UNVERIFIED | **Reported** E30. Dell Inspiron built-in microphone with PipeWire 1.0.5: clean capture at the default `vad_threshold`. Version and install route not stated. | UNVERIFIED | UNVERIFIED | UNVERIFIED | 2026-09-10 (E30, merge date) | [#206](https://github.com/MSKazemi/yazses/issues/206) has no report. Wayland injection is the open question. |
| **Ubuntu 24.04, GNOME X11** | UNVERIFIED | UNVERIFIED | UNVERIFIED | **Reported** E31 E32. Built-in and external microphones. No version stated. | **Reported** E31 E32. VS Code, Bash, gedit (E31); terminal, VS Code, commit messages (E32). | UNVERIFIED | UNVERIFIED | 2026-09-30 (E31) | E32 is the maintainer's own machine, so treat it as the least independent entry here. [#207](https://github.com/MSKazemi/yazses/issues/207) is still open. |
| **Any other distro or desktop** | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | The open slots: [#171](https://github.com/MSKazemi/yazses/issues/171), [#172](https://github.com/MSKazemi/yazses/issues/172), [#180](https://github.com/MSKazemi/yazses/issues/180), [#181](https://github.com/MSKazemi/yazses/issues/181), [#208](https://github.com/MSKazemi/yazses/issues/208) to [#215](https://github.com/MSKazemi/yazses/issues/215). None has a comment. |

Not shown because there is no hardware evidence to put in a row: FreeBSD and the other BSDs
(see [platform support](platform-support.md#bsd--experimental)), and the snap, Flatpak, apt and
Nix routes on any desktop. Those are published, which is a statement about availability and not
about validation.

## What CI covers

CI is a floor, and the cells above that say **CI only** rest on it.

* **E20.** The test suite passes on Linux, macOS and Windows runners, and on Linux arm64, at the
  commit this page was written against. The suite mocks audio and the speech model
  ([AGENTS.md](https://github.com/MSKazemi/yazses/blob/main/AGENTS.md)), so it cannot show that
  anything was heard.
* **E21, E22.** The release builds produce the macOS and Windows installers and exercise the built
  bundle (version, `doctor`, install and uninstall on Windows). They do not launch the windowed
  app.
* **What no runner can prove.** The header of
  [`macos-smoke.yml`](https://github.com/MSKazemi/yazses/blob/main/.github/workflows/macos-smoke.yml)
  states it: Accessibility, Input Monitoring and Microphone prompts, Gatekeeper, real dictation and
  the menu-bar icon need a GUI session and a human.

## Evidence log

Dates are the date of the report. Handles are public GitHub handles from the linked thread.

| ID | Source | Tester | Date | Setup and version |
|---|---|---|---|---|
| E1 | [#182, attachment comment](https://github.com/MSKazemi/yazses/issues/182#issuecomment-5367712375), [result quoted by the maintainer](https://github.com/MSKazemi/yazses/issues/182#issuecomment-5381056157) | @happytester-funbugs | 2026-08-21 | Apple M2, macOS 26.6.2, `.dmg`, v2.29.0 (the latest then) |
| E2 | [#182 comment](https://github.com/MSKazemi/yazses/issues/182#issuecomment-5795293149) | @happytester-funbugs | 2026-09-23 | Mac mini, Apple M2, macOS 26.6.2, `.dmg` arm64, v2.37.2 |
| E3 | [#562](https://github.com/MSKazemi/yazses/issues/562) and its [comments](https://github.com/MSKazemi/yazses/issues/562#issuecomment-5996423099) | @happytester-funbugs | 2026-10-01 to 2026-10-05 | Mac mini, Apple M2, macOS 26.6.2, `.dmg` arm64, fresh install, v2.40.0 |
| E4 | [PR #318](https://github.com/MSKazemi/yazses/pull/318) (merged 2026-08-28), SHOWCASE.md entry | @hoti-code | 2026-08-28 | Apple M5, macOS 26.5.1, Homebrew cask, tap then at 2.18.2 |
| E5 | [#182 comment](https://github.com/MSKazemi/yazses/issues/182#issuecomment-5376508008) | @slegarraga | 2026-08-21 | Apple M4, macOS 26.6, Homebrew cask, 2.18.2. Stopped before the permission prompts |
| E10 | [#183 comment](https://github.com/MSKazemi/yazses/issues/183#issuecomment-5519159097) | @visheshbpatel | 2026-09-03 | Windows 11 (build not stated), install script, v2.36.0 |
| E11 | [PR #328](https://github.com/MSKazemi/yazses/pull/328) (merged 2026-09-03) | @fall-water-zxc | 2026-09-03 | Windows 11 Home, built-in microphone, v2.36.0 |
| E12 | [#330](https://github.com/MSKazemi/yazses/issues/330) | @fall-water-zxc | 2026-09-08 | Windows 11 Home, Scoop and pipx, v2.36.0 |
| E13 | [#330 comment 09-15](https://github.com/MSKazemi/yazses/issues/330#issuecomment-5680958582), [09-22](https://github.com/MSKazemi/yazses/issues/330#issuecomment-5772475462), [09-30](https://github.com/MSKazemi/yazses/issues/330#issuecomment-5903377369) | @fall-water-zxc | 2026-09-15 to 2026-09-30 | Windows 11 Home, pipx environment at commit `ece081f` |
| E20 | [test.yml run 38796431889](https://github.com/MSKazemi/yazses/actions/runs/38796431889) | CI | 2026-10-15 | Commit `6edac14c`: ubuntu, macos-latest, windows-latest, ubuntu-24.04-arm |
| E21 | [build-macos.yml run 37237196913](https://github.com/MSKazemi/yazses/actions/runs/37237196913) | CI | 2026-10-04 | Tag v2.42.0, `macos-arm64` and `macos-x86_64` legs |
| E22 | [build-windows.yml run 37237196915](https://github.com/MSKazemi/yazses/actions/runs/37237196915) | CI | 2026-10-04 | Tag v2.42.0, `windows-x64` and `windows-arm64` legs |
| E23 | [v2.43.1 release notes](https://github.com/MSKazemi/yazses/releases/tag/v2.43.1) | maintainer | 2026-10-17 | Windows arm64 installer dropped: the asset had been an x64 build (added 2026-10-20) |
| E30 | [PR #333](https://github.com/MSKazemi/yazses/pull/333) (merged 2026-09-10) | @Akgithub2028 | 2026-09-10 | Ubuntu 24.04 LTS, GNOME Wayland, PipeWire 1.0.5, Dell Inspiron 15 3520 |
| E31 | [PR #546](https://github.com/MSKazemi/yazses/pull/546) (merged 2026-09-30), SHOWCASE.md entry | @AmothissacrajT | 2026-09-30 | Ubuntu 24.04.5, X11, Razer HyperClear and built-in microphones |
| E32 | SHOWCASE.md entry, [commit b6e61dab](https://github.com/MSKazemi/yazses/commit/b6e61dab) | @MSKazemi (maintainer) | 2026-08-01 | Ubuntu, GNOME X11, built-in microphone. No version stated |
| E40 | [#217 comment](https://github.com/MSKazemi/yazses/issues/217#issuecomment-5935001330) | @visheshbpatel | 2026-10-01 | Declined: no Windows 10 machine |

Further Windows 11 entries exist in SHOWCASE.md ([#317](https://github.com/MSKazemi/yazses/pull/317),
[#391](https://github.com/MSKazemi/yazses/pull/391),
[#547](https://github.com/MSKazemi/yazses/pull/547)). They state an operating system and a
microphone but no version or build, so they are not counted as evidence in any cell above.

## Keeping this page honest

* A maintainer adds a row to the log when a report arrives, and changes only the cells that report
  covers. A report that fills in more of the [evidence record](contribute/validation.md#the-evidence-record)
  upgrades a cell from **Reported** to **Verified (HW)**.
* A **Failed (HW)** cell is replaced only by a newer hardware record, never by a merged fix.
* `tests/test_validation_matrix.py` fails the build when a cell uses a word outside the table above,
  claims evidence without an `E<n>` that exists in the log, or when the log holds a row without a
  link.
