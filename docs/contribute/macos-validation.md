---
title: macOS validation campaign — open Mac issues and the next tests
description: Audit of the open macOS testing issues as of 2026-10-16, what each still needs, and five concrete tests for volunteers with a Mac, with a copy-paste script that gathers the evidence without audio or transcripts.
---

# macOS validation campaign

YazSes has no Mac in its CI that can click a permission prompt, and the maintainer owns none, so
every fact about the `.app` on a real Mac comes from a volunteer. This page audits the open Mac
issues, says what is known and unknown, and lists the next five tests. It builds on the
[evidence standard](validation.md); the results table is the
[validation matrix](../validation-matrix.md).

Status as of **2026-10-16**, with every issue state read from GitHub that day. The latest release
is v2.42.0. This page changed nothing on GitHub: the recommendations below are for the maintainer.

## What is known on Apple silicon

All hardware evidence is from one person's Mac mini (Apple M2, macOS 26.6.2). The other Mac runs on
record used a stale Homebrew tap at 2.18.2. Details and links are in the matrix, rows E1 to E5.

* **Works:** download, drag to Applications, the Gatekeeper override, launch and the menu-bar icon
  (v2.37.2 and v2.40.0). Capture, the silence gate and an on-device transcription ran from the
  command line on v2.29.0.
* **Does not work:** on v2.40.0 the hold-to-talk key does nothing. `doctor` and the daemon log say
  Accessibility and Input Monitoring are denied while both toggles show on, and the state did not
  change after `tccutil reset` for this app ([#562](https://github.com/MSKazemi/yazses/issues/562)).
  No Mac has yet shown a typed character.
* **Unknown:** whether it is that machine or that macOS build; whether the fixes in v2.43.0–v2.43.2
  change anything, and whether the permission-prompt fix now on main (unreleased) does; whether any Mac updates in place without losing its
  grants; and everything about pipx and Homebrew on a current release.

## What is unverified on Intel

Everything that needs a person. CI builds the x86_64 `.dmg` and runs its CLI on an Intel runner, but
no human has opened it, answered a prompt, or used pipx on an Intel Mac. The route that outlives
GitHub's Intel runners (see [platform support](../platform-support.md#macos)) is pipx.

## The open Mac issues

| Issue | State | Verdict | What it still needs |
|---|---|---|---|
| [#182](https://github.com/MSKazemi/yazses/issues/182) Apple silicon test | open | **Active.** The umbrella for Apple silicon. Its acceptance (install by a route, `doctor`, dictate into a real window) is met up to the last step only. | A hotkey-driven dictation that types text. Its "two unknowns" paragraph is out of date: the `.app` has launched on hardware (E3) and the cask has installed (E4, E5). |
| [#562](https://github.com/MSKazemi/yazses/issues/562) hotkey dead on 2.40.0 | open | **Active, the blocker.** The reproduction behind every macOS cell in the matrix. | A retest on v2.43.0 or later (the first to carry `1e20ebd3`), and on the first release after v2.43.2 for the permission prompt, plus a second Mac (task 1 and task 4 below). |
| [#578](https://github.com/MSKazemi/yazses/issues/578) daemon survived "Quit" | open | **Active, undiagnosed.** (After this audit, v2.43.1 shipped a fix on 2026-10-17; not yet confirmed on a Mac.) | `ps` and `launchctl` output before and after Quit (task 1). The issue itself says it needs a Mac. |
| [#579](https://github.com/MSKazemi/yazses/issues/579) `mic-level --set` varies | open | **Related, not Mac-specific.** It was seen on a Mac but is a threshold-rule decision. | A decision, not a Mac. It affects whether `verify` passes on a quiet voice. |
| [#241](https://github.com/MSKazemi/yazses/issues/241) microphone-permission guide | open | **Mostly met in another place.** The troubleshooting section of [Install on macOS](../macos-install.md#troubleshooting) now covers Gatekeeper, Accessibility, Input Monitoring, the stale-grant case and the unreachable microphone prompt. | A tester-written walk-through in the order the dead ends were hit, if the original volunteer still wants to write it. The maintainer offered to unassign. |
| [#216](https://github.com/MSKazemi/yazses/issues/216) Intel test | open | **Misleading new contributors.** It says the `.dmg` has no Intel build and the cask refuses. An x86_64 `.dmg` has shipped since v2.22.0 and v2.42.0 attaches one. The cask still refuses Intel. | A rewrite asking for the x86_64 `.dmg` and pipx (task 2 and task 5). |
| [#24](https://github.com/MSKazemi/yazses/issues/24) macOS (general) | open | **Mostly superseded** by #182 and #216, as its own header says. Its checklist is still a good regression list and is covered by the [checklist](validation.md#what-to-run-on-every-release). | Keep as the catch-all for anything the two issues above do not fit; the setup block (`pipx install --pre`) is out of date. |
| [#264](https://github.com/MSKazemi/yazses/issues/264) pay for an Intel runner? | open | **Resolved in substance.** Its premise (a billed runner) is recorded as false in ADR-017; the Intel `.dmg` builds on a free runner with a deadline of August 2027. | Closing, with a link to [platform support](../platform-support.md#macos). |

Housekeeping for the maintainer, not done here: refresh #182 and #216, close #264 with the ADR link,
and keep #24 as the catch-all.

### Findings that should become permanent checks

* **Two permission switches for one key.** Accessibility and Input Monitoring are separate, and
  `doctor` reports them in separate rows. This is check USE-2 for every Mac report.
* **A grant can look on and not apply.** The bundle is unsigned, and the verified evidence
  (the `codesign` output in #562) shows an ad hoc signature with no team identifier. Whether that
  is *why* the grants stop applying is a hypothesis, not a result. Check UPG-3 covers it.
* **Which program is asked.** `doctor` run from Terminal may be judged by Terminal's permission,
  not the app's. This is also a hypothesis from one report; the daemon log is the reliable witness.
* **The Gatekeeper path changed in practice.** The documented route is right-click, Open. The
  report on macOS 26.6.2 had to use System Settings, Privacy & Security, Open Anyway
  ([#562](https://github.com/MSKazemi/yazses/issues/562)). The [install page](../macos-install.md#first-launch--gatekeeper-bypass)
  does not mention it yet. This is a documentation gap to confirm on a second Mac.

## The permission checks every Mac tester runs

Run these in order and record the result of each **separately**. A pass on one says nothing about
the next.

| Step | Where | What you should see | `doctor` row |
|---|---|---|---|
| Gatekeeper | Finder, then System Settings, Privacy & Security | The unsigned-app block, then a way past it | not shown |
| Accessibility | Privacy & Security, Accessibility | YazSes listed and switched on | Keyboard capture |
| Input Monitoring | Privacy & Security, Input Monitoring | A prompt the first time you hold the key; then YazSes listed | Input monitoring |
| Microphone | Privacy & Security, Microphone | A prompt on the first recording; YazSes only appears after that | Microphone |

Quit and relaunch YazSes after each grant: the permission is read when the keyboard tap is created.
To forget one decision for this app only, keep the bundle id; without it the command resets every
app on the Mac:

```sh
tccutil reset Accessibility com.yazses.app
tccutil reset ListenEvent com.yazses.app
tccutil reset Microphone com.yazses.app
```

## Install routes to repeat after every release

| Route | Why it needs repeating |
|---|---|
| Apple silicon `.dmg` | The main route; the only one with hardware evidence. |
| Intel x86_64 `.dmg` | Separate build, no human evidence at all. |
| Homebrew cask (Apple silicon) | The cask is rewritten from the repository at each release, and a stale tap hid the fixes for weeks (E4). |
| pipx (either chip) | Permissions attach to the terminal app, not to a bundle. Nobody has walked it. |
| Upgrade in place from the previous release | A changed unsigned binary is a new identity to macOS; nobody has checked whether the grants survive. |

## The next five tests

Each is a volunteer task. Say on the linked issue that you are taking it, so nobody duplicates it.
You do not need to test more than one.

1. **Retest the hotkey on the first release after v2.43.2** (Apple silicon, `.dmg`; [#562](https://github.com/MSKazemi/yazses/issues/562),
   [#578](https://github.com/MSKazemi/yazses/issues/578)). Install it, run the
   [reporter script](#reporter-script), hold Right Option once and say whether a prompt appeared,
   then press Quit in the menu-bar and run the "after Quit" lines. *Done when:* the script output
   is attached and the log shows either `CGEventTap enabled` or the new warning.
2. **Open the x86_64 `.dmg` on an Intel Mac** ([#216](https://github.com/MSKazemi/yazses/issues/216)).
   Gatekeeper, first launch, the four permission steps, `doctor`. *Done when:* the script output
   and the Gatekeeper path you took are attached. A failure to open is a valid result.
3. **Homebrew cask on today's tap** (Apple silicon; [#182](https://github.com/MSKazemi/yazses/issues/182)).
   `brew tap MSKazemi/yazses`, `brew trust MSKazemi/yazses`, `brew install --cask yazses`, then
   the script. *Done when:* the cask version matches the release and the app stays running.
4. **Reproduce or refute #562 on a different Mac** (Apple silicon, not the M2 Mac mini, ideally a
   different macOS 26 patch level). *Done when:* the script output from a second machine is
   attached. This tells us whether the dead key is the build or the one machine.
5. **pipx on a Mac** (either chip; [#182](https://github.com/MSKazemi/yazses/issues/182),
   [#216](https://github.com/MSKazemi/yazses/issues/216)). `pipx install yazses`,
   `yazses quickstart`, grant the permissions to your **terminal** app. *Done when:* the output of
   `yazses doctor` and the name of the app that received each prompt are attached.

## Reporter script

This script only reads. It changes no setting and sends nothing anywhere. It writes a file to your
Desktop with your user name, computer name and home folder masked. **Open the file and read it
before you attach it.** It contains no audio and no dictated text, but the log is yours to check.

Paste it into Terminal as one block. For tasks that use pipx or Homebrew, change `APP` and `yz`
to match what you installed.

```sh
APP=/Applications/YazSes.app
yz() { "$APP/Contents/MacOS/YazSes" --cli "$@"; }      # for pipx, use: yz() { yazses "$@"; }
OUT="$HOME/Desktop/yazses-mac-report.txt"
H=$(hostname -s)
redact() { sed -e "s|$HOME|~|g" -e "s|$H|<host>|g" -e "s|$USER|<user>|g"; }
{
  echo "## Date";            date -u +%Y-%m-%dT%H:%MZ
  echo; echo "## Device and OS"; sw_vers; uname -m; sysctl -n machdep.cpu.brand_string
  echo; echo "## YazSes version"; yz --version
  echo; echo "## Signature";    codesign -dv --verbose=2 "$APP" 2>&1 | grep -E 'Identifier|Signature|TeamIdentifier'
  echo; echo "## Install route"; brew list --cask 2>/dev/null | grep -ix yazses && echo "Homebrew cask"
  echo; echo "## doctor";       yz doctor 2>&1
  echo; echo "## Processes";    ps aux | grep -i '[y]azses'
  echo; echo "## launchd";      launchctl list | grep -i yazses
  echo; echo "## Daemon log (last 60 lines)"; tail -n 60 "$HOME/Library/Logs/yazses/daemon.log" 2>&1
} 2>&1 | redact > "$OUT"
echo "Wrote $OUT"
```

Then do these by hand, in this order, and write the answers in your report:

1. Quit YazSes from the menu-bar icon, open it from Applications, **hold Right Option once**. Did a
   prompt appear? Name it (Input Monitoring, Accessibility or Microphone). Allow it, quit, reopen.
2. Open an empty TextEdit document, put the cursor in it, run `yz verify --type` and say only
   **"testing one two three"**. Did that text appear in TextEdit? (`verify` prints what it heard, so
   speak only that phrase.)
3. Press **Quit** in the menu-bar icon, then append the process state to the file:

```sh
{ echo; echo "## After Quit"; ps aux | grep -i '[y]azses'; launchctl list | grep -i yazses; } 2>&1 | redact >> "$OUT"
```

### What to post

Reply on the issue for your task with this, and attach the Desktop file (or paste it in a
`<details>` block). Leave a line as "not tested" rather than deleting it.

```markdown
**Tester:** @your-handle      **Date:** YYYY-MM-DD
**Mac:** model, chip, macOS version (from the file)      **Route:** .dmg / Homebrew / pipx
**YazSes version:** (from the file)

- Gatekeeper path I took: …
- Prompts I saw, in order (Accessibility / Input Monitoring / Microphone / none): …
- Did holding Right Option produce a prompt or any effect: …
- `verify --type` typed the test phrase into TextEdit: yes / no / not tested
- After Quit, a YazSes process was still listed: yes / no / not tested
- Not tested / could not verify: …
```
