# macOS: what "Quit" does, and which first-run prompts YazSes raises

Evidence note for [#578](https://github.com/MSKazemi/yazses/issues/578) (a daemon survived
"Quit") and [#562](https://github.com/MSKazemi/yazses/issues/562) (a fresh `.dmg` install on
macOS 26.6.2 shows no permission prompt). Written from the code and the reporter's
`daemon.log`; **nobody on this project has a Mac**, so every statement about what macOS
does is marked. Status labels: **READ** = seen in this repository's source or in the
reporter's pasted log; **DOC** = from Apple documentation as recalled, not re-fetched
here; **UNVERIFIED** = needs a real Mac.

## 1. The process model (READ)

| Piece | What starts it | Notes |
|---|---|---|
| Tray (menu-bar icon) | Double-clicking the `.app` runs the bundle with its default mode, `--tray` (`packaging/macos/yazses.spec`). | Holds `tray.lock`. |
| Daemon | The tray spawns it with `start_new_session` if `lifecycle.is_running()` is false; the launchd login item (`com.yazses.daemon`) also runs it. | Holds `daemon.lock`; blocks in `CFRunLoopRun` inside `MacosHotkey.run`. |
| Second tray | The daemon launches *its own* tray and a supervisor thread that relaunches it every 20 s if `tray.lock` is free. | When the user's tray already holds the lock the daemon's tray logs "A YazSes tray is already running; exiting." This is benign duplicate suppression, not an error. |

launchd (`render_launch_agent`): `RunAtLoad` true, `KeepAlive` is `{Crashed: true}` only. By
the plist's own semantics a clean exit after SIGTERM or an IPC `shutdown` is not restarted
(UNVERIFIED on a Mac; DOC for `KeepAlive`). So the launchd agent is **not** the reason a daemon
survived Quit. Nothing was changed in the plist.

## 2. What Quit did before this change (READ for the code, UNVERIFIED for the mechanism)

`MacosTray.run` built `rumps.App("YazSes", ...)` with rumps' default quit button and then
called `self._app.run()` followed by `self._on_quit()`. The on-quit callback is what sends
the IPC `shutdown` (`tray/app.py::_on_quit`). rumps' built-in Quit calls
`NSApplication.terminate:`, and AppKit's `NSApplicationMain` never returns (DOC), so the line
after `run()` very probably never executed. The Windows tray puts the same call in a
`finally` around `icon.run()`; the macOS one had no equivalent.

This explains every line of the #562 log without a second hypothesis:

* `2026-10-02 10:16` the daemon starts (tray pid 1303 launched by the daemon exits at once:
  the user's own tray holds `tray.lock`).
* `2026-10-05 16:17:01.129` the supervisor finds `tray.lock` **free** and relaunches a tray.
  The tray the user quit was gone; no `Shutting down.` line was ever written by that daemon,
  i.e. the `shutdown` RPC never arrived. That is the answer to "why did the supervisor say
  *tray is not running* while the lock was held": **the lock was not held at that moment.**
* The text under "it said: A YazSes tray is already running" is *not* about the tray that
  just died. `_last_tray_error` reads `tray-stderr.log`, which holds the stderr of the last
  tray **the daemon launched**, that is the duplicate from 10-02 that exited at once. It is a
  stale, misleading attachment (not fixed; see section 6).
* `16:17:01.842` the relaunched tray found `lifecycle.is_running()` false (the
  case-sensitive process-name bug, already fixed on main in `1e20ebd3`), spawned a second
  daemon, and that one exited "Another YazSes daemon is already running".

What would falsify this: `ps aux | grep -i [y]azses` after pressing Quit on a build with the
new menu still listing a daemon.

## 3. What was changed for Quit

The Quit fix that shipped is v2.43.1's (`7326b59f`): `platform/macos/tray.py` registers the
shutdown call on rumps' `before_quit` event, which fires from `applicationWillTerminate:` on
the stock Quit path, and keeps the post-`run()` call as a de-duplicated backstop
(`tests/test_macos_tray_quit_stops_the_daemon.py`). An earlier draft of this note proposed a
second mechanism (`quit_button=None` plus an explicit "Quit YazSes" entry that sent
`shutdown` on a worker thread before `rumps.quit_application`); it was dropped when this
work landed, so that one fix exists, not two. Contract either way: *Quit stops the daemon,
then the icon.* (Linux differs on purpose: its "Quit tray" leaves the daemon running.)

Not changed: `MacosHotkey.stop` calls `CFRunLoopStop` from the IPC thread. I believe
`CFRunLoopStop` wakes the loop itself (DOC) and did not add a blind `CFRunLoopWakeUp`;
if a daemon survives an IPC `shutdown` that did arrive (the log would then contain
`Shutting down.`), that is the next suspect. `yazses restart` is unaffected: it escalates to
SIGKILL.

## 4. Which first-run prompts exist (READ)

| Grant | Needed for | Requested by the code before this change | Requested now |
|---|---|---|---|
| Input Monitoring | The listen-only `CGEventTap` (the hotkey) | Yes, `IOHIDRequestAccess` in `MacosHotkey.run` (at daemon start, not on the first key hold as the docs said) | unchanged |
| Accessibility | Posting keystrokes (`CGEventPost` in `MacosInjector`) | **No.** `request_keyboard_capture` existed on the Protocol and on `MacosPermissions` with **zero callers** in `src/` | Yes, at start when the check says denied |
| Microphone | Recording | **No.** The prompt waited for the first recording, which needs a hotkey that cannot work without Input Monitoring | Yes, at start when the status is `NotDetermined` (macOS-only `request_microphone`, via `getattr`, not on the Protocol) |

Consequences for the #562 flow: after `tccutil reset Accessibility com.yazses.app` the app
is removed from the Accessibility list and, with no request, never re-added; the docs said
"On first launch, YazSes triggers macOS to show an Accessibility prompt", which was false.
Both new requests share the existing persisted five-minute rate limit
(`system/diagnosis.should_notify`), so a login item cannot put a system dialog up at every
start; only an undecided or denied grant asks.

A note on the `doctor` wording: the "Keyboard capture" row checks Accessibility, but the
hotkey tap itself is listen-only and needs Input Monitoring; Accessibility gates *typing*.
The wording was left as is (changing it is a product decision), but it is why a green
Accessibility row with a dead hotkey reads as a contradiction.

## 5. A daemon that predates a grant (#578)

The Input Monitoring grant is read when the tap is created (the in-repo comments and the
docs say so; UNVERIFIED on a Mac, though System Settings itself offers "Quit & Reopen" for
several privacy toggles). The daemon now records the Input Monitoring answer at start and,
only if it was not OK, re-asks **from its own process** (so the answer is about YazSes and
not about the terminal a user typed `doctor` into, the attribution problem in #562), at most
every 30 s, and reports `stale_permissions: ["input_monitoring"]` in `status`. `doctor`'s
Daemon row turns WARN with the restart command. Healthy installs never probe. Daemons built
before this change cannot report it; for them `doctor`'s existing version-skew WARN applies.

## 6. Findings not acted on

1. `_last_tray_error` can attach another launch's stderr to a later death (section 2).
2. Double-clicking the `.app` starts two trays (the user's, and the daemon's duplicate that
   exits). Benign, but it makes the log read like an error.
3. `docs/macos-install.md` still told Sequoia/Tahoe users to right-click *Open*, which those
   releases no longer offer for unsigned apps (DOC). The page now leads with Settings → Privacy
   & Security → Open Anyway, the flow the #562 reporter actually followed.
4. In #562 the reporter's headset microphone stopped working on 10-06; that is hardware and
   unrelated. `mic-level --set` choosing three different thresholds is #579.
5. The ad-hoc signature (`Signature=adhoc`, `Internal requirements count=0`, from the pasted
   `codesign` output) makes the code identity a cdhash, so every build is a new TCC identity.
   This is the existing, documented reason a grant "stops applying while the toggle looks on";
   only signing fixes it (`design/packaging/macos-signing.md`).

## 7. UNVERIFIED on a real Mac

1. rumps' `before_quit` event fires on the stock Quit path (from the rumps 0.4.0 source,
   not run).
2. Quit really stops the daemon, and no tray reappears 20 s later.
3. `AXIsProcessTrustedWithOptions(prompt=True)` shows a dialog from the background daemon
   process, and does so once per launch while untrusted.
4. `AVCaptureDevice.requestAccessForMediaType:completionHandler:` through PyObjC accepts a
   Python lambda as the block and shows the microphone prompt from a non-GUI process.
5. A grant given after start leaves the existing tap deaf, so a restart is what is needed.
6. Whether the Input Monitoring prompt (`IOHIDRequestAccess`) appears for a daemon launched
   by the tray with `start_new_session`, versus launched by launchd.

## 8. Questions for the #562 / #578 reporter

On a build containing this change (for 1 and 2, v2.43.1 or later):

1. After pressing Quit in the menu bar, what do `ps aux | grep -i [y]azses` and
   `launchctl list | grep yazses` print? Then, 30 seconds later, again.
2. Does the icon come back after Quit? If so, how long after?
3. On first launch after `tccutil reset Accessibility com.yazses.app` and
   `tccutil reset ListenEvent com.yazses.app` and `tccutil reset Microphone com.yazses.app`:
   which system dialogs appear, in which order, and what does each say?
4. After switching a toggle on while YazSes is running, what does `yazses doctor` (run as
   `/Applications/YazSes.app/Contents/MacOS/YazSes --cli doctor`) print on the Daemon row?
5. The last 40 lines of `~/Library/Logs/yazses/daemon.log` after step 3, and whether
   `Shutting down.` appears there after Quit.
