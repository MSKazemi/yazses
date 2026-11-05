# Research: what an unprivileged dictation tool can do on GNOME and KDE Wayland

**Issue:** [#818](https://github.com/MSKazemi/yazses/issues/818) · **Parent:** [#790](https://github.com/MSKazemi/yazses/issues/790) · **Related:** [#643](https://github.com/MSKazemi/yazses/issues/643), [#642](https://github.com/MSKazemi/yazses/issues/642), [#418](https://github.com/MSKazemi/yazses/issues/418), [#102](https://github.com/MSKazemi/yazses/issues/102)  
**Date / base:** 2026-11-05, `MSKazemi/yazses@a241a77b6c59d65fb9265a0475d42f1a97fdfe6a`  
**Status:** Research note (not a decision). ADR-030 freeze unchanged. No `src/` change, no runtime capability, no promise of universal Wayland support.  
**Nothing in this note was tested on any compositor.** Every GNOME, KDE and wlroots statement is documentation, upstream source as summarised by a fetch tool, or a reading of this repository. No session was run, no portal dialog was seen, no key was injected.

## 0. Method and labels

| Label | Meaning |
|---|---|
| `[Verified-primary-source]` | A primary document (protocol page, portal spec, upstream source file) was fetched on 2026-11-05 and the fetch summary states it. **Fetches return a small model's text summary, not the page: nothing below was read in full, and a summariser error is possible.** |
| `[Upstream-claim]` | A secondary upstream statement: a mailing-list or forum snippet seen only in search results, a bug title, or a relay of a primary source I did not re-read today. |
| `[Verified-in-code]` | Read in this repository at the base SHA. This proves what the code does, not what a compositor does. |
| `[Assumption]` | My inference. | 
| `[Unknown]` | No source found, or the source was blocked. |

Matrix cells use `VPS`, `UC`, `VIC`, `ASM`, `UNK` for the five labels, plus a source id from section 7. Blocked or unreadable: GitLab pages (`gitlab.gnome.org`, `gitlab.freedesktop.org`) returned challenge pages, so GNOME MR 88, libei's repository page and Mutter issues were **not read**. The wayland.app support tables show a version number or `x` with no legend in the fetched text; I read `x` as "not implemented" `[Assumption]`, which agrees with this repo's own comments.

## 1. Answers in brief

1. **Injection.** GNOME and KDE both offer the RemoteDesktop portal, and both portal backends were reported to implement keyboard notify, EIS hand-off and a restore path `[Verified-primary-source]` (S1, S7, S8). The wlroots virtual-keyboard and input-method protocols are listed as not implemented by Mutter 51 and KWin 6.7 `[Upstream-claim]` (S2, S3). `uinput` (ydotool) is compositor-independent but needs `/dev/uinput` access and assumes the keyboard layout `[Verified-primary-source]` (S6).
2. **Reading the focused widget.** Over AT-SPI D-Bus, not through the compositor. The AT-SPI device-event controller does not work on Wayland (no keyboard or mouse sniffing) `[Verified-primary-source]` (S13); focus and caret events were not mentioned either way and are `[Unknown]` on hardware.
3. **Semantic targeting.** The accessible tree is per-toolkit. Whether an app exposes one at all depends on activation (Qt, Chromium, Electron). Screen coordinates and focus control through AT-SPI are limited, see [#418 spec](../specs/eye-wayland-gaze-target.md) `[Upstream-claim]` (S21).
4. **Consent.** A dialog per new portal session; a restore token or restore data skips it when still valid; a token is single use and a failed restore silently becomes a dialog `[Verified-primary-source]` (S1, S7, S8).
5. **Biggest gap for #643.** The validation matrix has **no injection record** for GNOME or KDE Wayland, and KDE has no row at all `[Verified-in-code]` (section 5).

## 2. Limitation matrix

Rows are capabilities; columns are session families. "wlroots" means Sway, Hyprland, river, labwc, niri, Wayfire and similar. Sessions are not tested; cells report documents.

| Capability | GNOME (Mutter) | KDE Plasma (KWin) | wlroots family | X11 baseline |
|---|---|---|---|---|
| **A1** RemoteDesktop portal, keysym notify | Backend maps to `org.gnome.Mutter.RemoteDesktop` session with keycode and keysym notify. VPS S7 | Backend implements `NotifyKeyboardKeysym` via KWin wayland integration. VPS S8 | `xdg-desktop-portal-wlr` lists only Screenshot and ScreenCast. VPS S12. Other wlroots portal backends: UNK | not needed; XTEST, UC S21 |
| **A2** libei / EIS hand-off (`ConnectToEIS`) | Backend passes device types to Mutter `ConnectToEIS`. VPS S7 | Backend calls KWin `org.kde.KWin.EIS.RemoteDesktop.connectToEIS`. VPS S8 | UNK | n/a |
| **A3** `zwp_virtual_keyboard_v1` (wtype) | Mutter 51 `x`. UC S2 | KWin 6.7 `x`. UC S2 | Sway 1.11, Hyprland, river, labwc, niri, Wayfire, COSMIC listed supported. UC S2. Manager may answer `unauthorized`. VPS S2 | n/a |
| **A4** `zwp_input_method_v2` commit_string | `x`. UC S3 | `x`. UC S3 | Sway, Hyprland, river, labwc listed; Wayfire `x`. UC S3 | n/a (IBus/XIM: UNK) |
| **A5** `text-input-v3` (app side) | Mutter 51 and KWin 6.7 listed as implementing it, but it is the app-to-compositor side; no way for a third party to read another app's text is described. UC S4 | same, UC S4 | listed (Sway, Hyprland, river). UC S4 | n/a |
| **A6** KDE `fake_input` | n/a | Page: "Regular clients must not use this protocol"; no compositor listed on wayland.app. VPS S11 | n/a | n/a |
| **A7** uinput (`ydotoold`) | Compositor-independent; needs `/dev/uinput` access (usually root or udev rule). VPS S6. Does GNOME accept the virtual device: UNK | same. UNK on KDE | same. VPS S6 | works on X11 and console. VPS S6 |
| **A8** Clipboard set (`wl-copy`) then paste key | `ext-data-control-v1`: Mutter 51 `x`. UC S10. wl-copy workaround on GNOME: UC S22 (forum snippet only) | KWin 6.7 listed supported. UC S10 | Sway, Hyprland, river listed. UC S10 | `xclip` plus `xdotool` (VIC `clipboard.py`) |
| **B1** Focus, role, editable state of the focused widget | AT-SPI D-Bus, not compositor API. ASM; HW record UNK | same. ASM; HW UNK | same bus; session-start of the a11y bus: UNK | UC S13 (device controller works on X11) |
| **B2** Active window title / app name | AT-SPI top-level name (VIC `atspi_tree.py`); compositor-independent. ASM | same. ASM | same. ASM; `ext-foreign-toplevel-list` gives title and app id. UC S21 | EWMH. UC S21 |
| **B3** List *other* windows | `Shell.Introspect.GetWindows` is allow-listed. UC S21 | `plasma_window_management`: "regular clients must not use". UC S21 | foreign-toplevel protocols list windows, no geometry. UC S21 | `_NET_CLIENT_LIST`. UC S21 |
| **B4** Global key monitoring for an AT (Orca) | AT-SPI sniffing absent on Wayland (VPS S13); new Mutter D-Bus grab API was only a merge request in 2023 (VPS S14); current state UNK | KWin has an a11y keyboard monitor; open bugs on shift combinations and learn mode, search snippets only. UC S20 | UNK | works. VPS S13 |
| **C1** Widget screen coordinates | GTK4 answers screen-relative extents with (0, 0). UC S21 | same toolkit result; Qt: UNK (S21 did not examine it) | toolkit-dependent. UNK | toolkit-dependent. UNK |
| **C2** Focus another window | Shell extension only. UC S21 | KWin scripting only. UC S21 | `wlr-foreign-toplevel` `activate`. UC S21 | `_NET_ACTIVE_WINDOW`. UC S21 |
| **D1** Consent prompt | Modal GTK dialog unless restore data validates. VPS S7 | Dialog unless restore data matches or app is "mega-authorized" in the permission store; then a notification. VPS S8 | virtual-keyboard: compositor policy, none documented. UNK | none |
| **D2** Persistence | `persist_mode` and restore data stored; no dialog on valid restore. VPS S7. Lifetime, lock screen, upgrade behaviour: UNK | `persist_mode` returns restore data; matching request skips dialog. VPS S8. Lifetime: UNK | n/a | n/a |

Counts (machine-counted from this table): 64 cells (16 rows by 4 columns). 41 cite a source id: 15 with `VPS` only, 25 with `UC` only, 1 with both. The other 23: 10 are "not applicable / none" (A2 to A6 and D1/D2 where the mechanism does not exist for that session), 8 are `UNK` (A2, A7, B1, B4, C1 x2, D1 on wlroots or KDE), 4 are `ASM` only (B1 and B2 on GNOME and KDE), 1 is `VIC` only (A8 X11). 16 cells contain an `UNK` clause somewhere, including the 8 above. A cell citing S21 relays the in-repo spec's upstream sources, which this run did not re-fetch, so its `UC` is weaker than a `VPS`.

### 2.1 Toolkit activation (question c)

| Toolkit | How AT-SPI is exposed | When it is on |
|---|---|---|
| GTK4 | direct D-Bus, `gtk4/gtk/a11y`. VPS S15 | UNK. The fetched page did not say. |
| GTK3 | via ATK. VPS S15 | UNK |
| Qt 5/6 | direct D-Bus. VPS S15 | `org.a11y.Status.IsEnabled` true, or `QT_LINUX_ACCESSIBILITY_ALWAYS_ON`; docs.rs mirror, snippet only. UC S19 |
| Chromium | ATK (page unsure). VPS S15 | `--force-renderer-accessibility` or `chrome://accessibility`. VPS S17. Linux auto-detection was paused in 2020 for false positives. UC S18. Current behaviour: UNK |
| Electron | not covered. VPS S15 | Enabled "in the presence of assistive technology"; `app.setAccessibilitySupportEnabled`; no Linux detail. VPS S16 |
| Firefox | ATK. VPS S15 | UNK |

`[Assumption]` Chrome-based apps and Electron apps (VS Code, browsers, chat apps) are the surfaces where a read-back may return nothing until accessibility is activated. The reports are from 2020 to 2022; today's behaviour is `[Unknown]`.

## 3. Orca's approach (question b)

`[Upstream-claim]` Orca historically took keys through the AT-SPI key filter that depended on toolkits notifying the registry; GTK4 stopped notifying, and Wayland has no X11-style grab (S13, S14, search results S20). The replacement is a compositor-side key grab and monitor API, with trust granted by installation rather than by a Wayland authentication step (meeting record S14: "we don't have a mechanism to do authentication or privilege escalation via Wayland"). `[Verified-primary-source]` That is a privileged channel for screen readers; nothing in the pages read shows an unprivileged dictation tool being offered it. YazSes does not use it: its hold-to-talk key comes from evdev `[Verified-in-code]` (`platform/linux/hotkey.py`), which needs input-device access rather than a compositor grant.

## 4. Mapping to YazSes backends

`[Verified-in-code]` (`inject/registry.py`, `inject/auto.py`, `platform/linux/injector.py`, `inject/clipboard.py`).

| Session (env detection) | `auto` ladder | Consent rule |
|---|---|---|
| Wayland (`WAYLAND_DISPLAY` set) | `ydotool` (rank 10), `portal` (20), `wtype` (30), then `clipboard` as floor. `unicode` is never auto. | `ydotool` and `wtype` need none. `portal` needs consent: a stored restore token, the backend named in config, a strict snap, or `consent=allow`. `deny` blocks it. |
| X11 (`DISPLAY` only) | `xdotool` (rank 10), then `clipboard` | none |

What each target means:

* **GNOME or KDE Wayland, ydotoold ready.** `ydotool` is chosen `[Verified-in-code]`. Whether GNOME or KDE accepts the uinput device and types correctly is `[Unknown]`; the repo's `doctor` text says "works on any Wayland compositor" `[Verified-in-code]`, a claim with no hardware record behind it (section 5).
* **GNOME or KDE Wayland, no ydotoold, consent given (token on disk).** `PortalInjector` is chosen. It uses `NotifyKeyboardKeysym` only; `ConnectToEIS`, `RequestClipboard`, `input_method` and libei appear nowhere in `src/` `[Verified-in-code]` (grep). The portal spec says that after `ConnectToEIS` the `Notify*` calls fail `[Verified-primary-source]` (S1), so the two paths are exclusive and the choice is already made in favour of `Notify*`.
* **GNOME or KDE Wayland, no ydotoold, no consent.** `wtype` is marked unavailable for desktops containing `gnome`, `kde` or `plasma` `[Verified-in-code]`, so `auto` lands on `clipboard`. The paste step then tries ydotool, then `wtype` unconditionally, else raises "No tool available" `[Verified-in-code]` (`_paste_wayland`). `LinuxInjector` adds no second fallback when the primary is already the clipboard `[Verified-in-code]`.
* **wlroots, no ydotoold.** The portal is unavailable (S12), so `wtype` is chosen; this is the one place the backend matches the protocol table (A3).

### 4.1 Where failure is silent, or may be

1. **Portal notify is fire-and-forget** `[Verified-in-code]` (`_send_notify` docstring): a dropped event and an acted-on event look identical. The existing code says so itself.
2. **Restore failure becomes a dialog.** `[Verified-primary-source]` The portal spec says a failed restore is ignored and the user prompted (S1), and the token is invalidated by use. `[Verified-in-code]` YazSes writes the new token after each `Start` and calls `warm()` at daemon start to put the dialog at login. Whether a GNOME or KDE login or lock-screen cycle forces a new dialog is `[Unknown]`.
3. **uinput types by keycode against the active layout.** `[Verified-primary-source]` ydotool "does not recognize if the user is using a custom keyboard layout" (S6). `[Verified-in-code]` The repo documents silent loss of accented and non-Latin characters (`ydotool.py`, issue #329) and routes non-ASCII runs elsewhere.
4. **AT-SPI returns "unknown", and unknown means proceed.** `[Verified-in-code]` The target tracker is tri-state; `None` is treated as OK so a guard never false-alarms. If the focused app has accessibility off, the tracker may simply never fire, and the no-text-target guard stays quiet `[Assumption]`.
5. **wtype exit behaviour conflicts.** `[Verified-in-code]` `registry.py` says Mutter and KWin make wtype "exit cleanly having done nothing". `[Verified-primary-source]` The fetched `wtype` `main.c` calls `fail("Compositor does not support the virtual keyboard protocol")` which exits `EXIT_FAILURE` (S5, master branch, summary). Both cannot hold for current wtype; which version users have is `[Unknown]`. The paste path uses `check=True`, so it would raise on a non-zero exit.
6. **`doctor` hygiene `[Verified-in-code]`.** `_probe_ydotool` in `registry.py` has statements after its final `return` that cannot run. Not part of this research change; flagged for the maintainer.

## 5. Validation records (what is Verified (HW), Reported, CI-only)

`[Verified-in-code]` Read from `docs/validation-matrix.md`, `docs/platform-support.md` and `docs/contribute/validation.md` at the base SHA.

| Row | Capture | Text injection | Last validation |
|---|---|---|---|
| Ubuntu 24.04, GNOME Wayland | **Reported** (E30, PipeWire 1.0.5, no version or install route) | **UNVERIFIED** | 2026-09-10 |
| Ubuntu 24.04, GNOME X11 | Reported (E31, E32) | Reported (E31, E32; E32 is the maintainer's machine) | 2026-09-30 |
| KDE Plasma, any session | no row; "Any other distro or desktop" is UNVERIFIED in every column | UNVERIFIED | none |
| wlroots family | no row | UNVERIFIED | none |

* There is **no Verified (HW) cell of any kind in the Linux table**, and no CI-only Linux cell. The matrix test forbids a page saying "full Wayland" until both a GNOME and a KDE Wayland row grade capture and injection Verified (HW) with a version `[Verified-in-code]` (matrix "Keeping this page honest").
* The tester slots for #643 are #432, #433 (GNOME) and #434, #438 (KDE) in `design/eye-control/BEGINNER_TESTING.md` `[Verified-in-code]`.
* The in-repo [#418 spec](../specs/eye-wayland-gaze-target.md) already owes three live checks (Introspect refusal, plasma window management refusal, `gaze status` row). Nothing here changes its answer: gaze target is `none` on every Wayland session.
* `[Assumption]` Qt's AT-SPI behaviour on Wayland is the largest unexamined item for KDE, because Plasma apps are Qt.

## 6. Gaps, hardware checklist, open questions

### 6.1 Gaps (what is missing, in rough order of value for #643)

1. No hardware record of any injection backend on GNOME or KDE Wayland.
2. No record of which backend `auto` chose on those machines, so no record that the doctor ladder predicts the daemon.
3. No record of the portal's dialog, its restore across logout, reboot and upgrade, or its behaviour on a locked screen.
4. No record of AT-SPI focus and role events from GTK4, Qt, Chromium and Electron apps on either desktop, with and without accessibility activation.
5. A source conflict on wtype's failure mode (4.1 item 5) that one command resolves.

### 6.2 Checklist for one GNOME session and one KDE session (to record, not results)

Record for each machine: distro, release, desktop and compositor version (`gnome-shell --version`, `plasmashell --version`), `echo $XDG_SESSION_TYPE $XDG_CURRENT_DESKTOP`, YazSes version and install route, and the evidence-record fields in `docs/contribute/validation.md`.

- [ ] `yazses doctor` output verbatim, and `yazses inject` / `yazses status` backend name (`describe_injector`).
- [ ] Which backend `auto` chose; then each of `ydotool`, `portal`, `wtype`, `clipboard` forced in turn, with the typed result in a terminal, a GTK4 editor, a Qt editor, a Chromium page and an Electron app (typed text, nothing, wrong characters, duplicates).
- [ ] Non-ASCII text (accented, non-Latin) and a non-US layout, for ydotool and portal.
- [ ] `wtype x` exit code and stderr text, on both desktops (resolves 4.1 item 5).
- [ ] `/dev/uinput` mode and whether `ydotoold` runs as the user; does the virtual device type at all.
- [ ] Portal: first-run dialog text and parent; does it appear without a parent window; state of the screen-sharing indicator while active.
- [ ] Portal persistence: token written; restart daemon (dialog?); log out and in; reboot; lock screen mid-session; update the desktop package. Record each as dialog or no dialog.
- [ ] Portal drop test: is any dropped key detectable (compare typed length with the field content).
- [ ] AT-SPI: with `pyatspi` installed, does `AtspiFocusTracker` report a role for each app above, with and without `--force-renderer-accessibility` / `QT_LINUX_ACCESSIBILITY_ALWAYS_ON`; does the active-window walk find the window.
- [ ] AT-SPI on a password field and a terminal: confirm role is reported and text is not read.
- [ ] Does the no-text-target guard warn with focus on the desktop, on a button, on a read-only page.
- [ ] Clipboard path: does `wl-copy` set the clipboard on GNOME without a visible window flash; is the previous clipboard restored or lost.
- [ ] Do not record any real speech or private text; use synthetic phrases (AGENTS.md privacy rule).

### 6.3 Open questions for the maintainer

1. Is the `doctor` wording "works on any Wayland compositor" for ydotool acceptable before a GNOME and a KDE record exist, given #643 forbids "full Wayland"?
2. Should the portal's `ConnectToEIS` path be evaluated at all, given it excludes `Notify*` and would need an EIS client? (A design question; this note authorises nothing.)
3. Which wins when sources conflict on wtype: the in-code comment or upstream source? A hardware answer is cheap (6.2).
4. Who is the named tester for KDE? #434 and #438 exist; no KDE row exists in the matrix.
5. Should a "Blocked" or "Failed (HW)" grade be preferred over silence if portal persistence turns out to prompt after every login?
6. Is a KDE-specific path worth a child issue, since KDE offers restore data, a permission-store grant and, in S11, only a testing-grade fake input protocol? (Not recommended here without evidence.)

## 7. Sources (all read 2026-11-05 unless marked)

All are landing pages or source views, never a file download. "Summary" means a WebFetch text summary, not a full read.

* S1 RemoteDesktop portal, <https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html> (summary; documents interface version 2).
* S2 virtual-keyboard-unstable-v1, <https://wayland.app/protocols/virtual-keyboard-unstable-v1> (summary; `x` marker undefined).
* S3 input-method-unstable-v2, <https://wayland.app/protocols/input-method-unstable-v2> (summary).
* S4 text-input-unstable-v3, <https://wayland.app/protocols/text-input-unstable-v3> (summary).
* S5 wtype `main.c`, <https://github.com/atx/wtype/blob/master/main.c> (summary; branch at fetch time, version unknown). Its README, <https://github.com/atx/wtype>, named no protocol.
* S6 ydotool README, <https://github.com/ReimuNotMoe/ydotool> (summary).
* S7 xdg-desktop-portal-gnome `src/remotedesktop.c`, read through a GitHub mirror at `raw.githubusercontent.com/GNOME/xdg-desktop-portal-gnome/main/src/remotedesktop.c` (summary; the GitLab original and MR 88 at <https://gitlab.gnome.org/GNOME/xdg-desktop-portal-gnome/-/merge_requests/88> were blocked and **not read**).
* S8 xdg-desktop-portal-kde `src/remotedesktop.cpp`, <https://github.com/KDE/xdg-desktop-portal-kde> mirror, `raw.githubusercontent.com/KDE/xdg-desktop-portal-kde/master/src/remotedesktop.cpp` (summary).
* S9 libei, <https://libinput.pages.freedesktop.org/libei/> (summary; names no compositor). The GitLab repository page was blocked.
* S10 ext-data-control-v1, <https://wayland.app/protocols/ext-data-control-v1> (summary; `x` marker undefined).
* S11 KDE fake input, <https://wayland.app/protocols/kde-fake-input> (summary).
* S12 xdg-desktop-portal-wlr, <https://github.com/emersion/xdg-desktop-portal-wlr> (summary).
* S13 AT-SPI device event controller notes, <https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/de-controller.html> (summary).
* S14 AT-SPI meeting record 2023-01-13, <https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/meeting-2023-01-13.html> (summary; dated).
* S15 AT-SPI toolkits, <https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/toolkits.html> (summary).
* S16 Electron accessibility, <https://www.electronjs.org/docs/latest/tutorial/accessibility> (summary).
* S17 Chromium accessibility design doc, <https://www.chromium.org/developers/design-documents/accessibility/> (summary; no Linux detection text).
* S18 Orca list, Chromium flag needed again, <https://lists.gnome.org/archives/orca-list/2020-May/msg00298.html> (**search snippet only, page not opened**).
* S19 Qt `QAccessible` via docs.rs, <https://docs.rs/qt_gui/latest/qt_gui/struct.QAccessible.html> (**snippet only**; not the official Qt 6 page, which returned 404).
* S20 KWin a11y keyboard monitor bugs, <https://bugs.kde.org/show_bug.cgi?id=512189>, <https://bugs.kde.org/show_bug.cgi?id=507144>, <https://bugs.kde.org/show_bug.cgi?id=493054> (**titles in search results only, not opened**); Wayland key-grab background, <https://lists.freedesktop.org/archives/wayland-devel/2021-February/041736.html> (snippet only).
* S21 In-repo spec `design/specs/eye-wayland-gaze-target.md`, which relays xdg-activation, `wlr-foreign-toplevel`, `ext-foreign-toplevel-list`, KWin scripting, `Shell.Introspect` and GTK4 AT-SPI source findings. Read here; its upstream sources were **not re-fetched** today.
* S22 NixOS Discourse on wl-copy, <https://discourse.nixos.org/t/wl-copy-not-working/44557> (**snippet only**). The wl-clipboard README, <https://github.com/bugaevc/wl-clipboard>, states no compositor requirements.

Not examined: Flatpak or snap confinement of AT-SPI, Xwayland apps under AT-SPI beyond bug 493054's title, GlobalShortcuts, InputCapture, Hyprland/COSMIC/Sway portal backends, and any non-Ubuntu distro.
