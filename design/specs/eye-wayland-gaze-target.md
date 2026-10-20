# Spec: Gaze-Target Semantics on Wayland — a Capability Model, Not a Guess

| Field | Value |
|---|---|
| **ID** | spec-eye-wayland-gaze-target |
| **Status** | Accepted (desk research; not yet validated on a live GNOME or KDE session) |
| **Date** | 2026-10-20 |
| **Modules** | `src/yazses/gaze/target_capabilities.py` (the matrix, pure), `src/yazses/gaze/target_semantics.py` (the plan, pure), `core/daemon.py` (`_deixis_without_gaze_target`) |
| **Related** | ADR-v2-010 (gaze-routed dictation), ADR-v2-146 (pointer output is a separate boundary), ADR-v2-148 (recovery hierarchy), ADR-v2-149 (one coordinate space), [glance-type.md](glance-type.md), [eye-pointer-output.md](eye-pointer-output.md), risk R-15 |
| **Issues** | #418 (EYE-WAYLAND-001) |

## Problem

Glance-Type asks one question: *which window should get the next dictation?* The Remote
Desktop portal work (#403) gives YazSes pointer events on Wayland. That is a different
question. Being allowed to move a cursor does not tell YazSes which window is under the gaze
point, and it does not let YazSes focus that window. This spec separates the two questions,
records what each desktop actually lets an ordinary client do, and defines what gaze may
honestly do with that.

## Capabilities

A gaze target needs **three** capabilities. A fourth, pointer injection, is listed beside
them so nobody mistakes it for one of them.

| Capability | Meaning | Needed for a gaze target? |
|---|---|---|
| `absolute_position` | the gaze point is a pixel in coordinates the desktop shares with this process | yes |
| `window_geometry` | the rectangles of *other* applications' windows | yes |
| `window_focus` | the right to raise and focus another application's window | yes |
| `pointer_injection` | moving and clicking a cursor (output, ADR-v2-146) | **no** — never read by the derivation |

What an ordinary client gets for each capability is one of four values:

- `yes`: a stable, documented, cross-desktop interface, with no extra grant;
- `consent`: an XDG desktop portal, after the user grants it, and only where the desktop's
  portal backend implements that portal;
- `compositor_specific`: only through one compositor's own interface, such as a protocol
  reserved for the desktop shell, an allow-listed D-Bus API, a shell extension or compositor
  scripting;
- `no`: no interface exists.

**The derivation rule.** A session supports a gaze target only when all three target
capabilities are `yes`. `consent` and `compositor_specific` never count, and
`pointer_injection` is never read (`gaze_target_supported()`). This rule is what turns
#418's third acceptance criterion into something a test can check: no compositor-private
path can become a default requirement, because by construction it cannot make a target.

## Platform matrix

These are findings from documentation. Where a cell says **unverified**, nothing has been
measured on a real session. The code holds the same matrix as data in
`src/yazses/gaze/target_capabilities.py` (`SESSION_CAPABILITIES`), and
`tests/test_gaze_target_capabilities.py` checks that every source id it cites is listed below.

| Session | screen position | other windows' geometry | focus another window | pointer injection | Gaze target |
|---|---|---|---|---|---|
| X11 | yes, root-window coordinates [ewmh] | yes, `_NET_CLIENT_LIST` and window geometry [ewmh] | yes, `_NET_ACTIVE_WINDOW` [ewmh] | yes, XTEST [xtest] | **window under the gaze point** |
| Wayland, GNOME | no [wayland-core][portal-screencast][portal-inputcapture] | compositor-specific: `org.gnome.Shell.Introspect` is allow-listed [gnome-shell-introspect]; AT-SPI screen coordinates answer `(0, 0)` in GTK 4 [atspi-component][gtk4-atspi-screen-coords] | compositor-specific: a Shell extension only. xdg-activation does not apply [xdg-activation], and AT-SPI `GrabFocus` is unsupported in GTK 4 [gtk4-atspi-grabfocus] | consent, via the RemoteDesktop portal [portal-remotedesktop] | **none** |
| Wayland, KDE Plasma | compositor-specific: KWin scripting `cursorPos` [kwin-scripting] | compositor-specific: `org_kde_plasma_window_management` [kde-plasma-window-management], or KWin scripting `frameGeometry` [kwin-scripting] | compositor-specific: KWin scripting `activeWindow` [kwin-scripting]. xdg-activation does not apply [xdg-activation] | consent, via the RemoteDesktop portal [portal-remotedesktop] | **none** |
| Wayland, other (wlroots family and others) | no [wayland-core] | compositor-specific: compositor IPC only. The foreign-toplevel protocols carry no geometry [wlr-foreign-toplevel][ext-foreign-toplevel-list] | compositor-specific: `wlr-foreign-toplevel-management` `activate`, on wlroots-family compositors only [wlr-foreign-toplevel] | consent, only where the portal backend implements it; xdg-desktop-portal-wlr does not [xdpw] | **none** |
| Windows, macOS | not assessed (outside #418) | not assessed | not assessed | — | **none** (no YazSes window backend yet) |
| headless | no | no | no | no | **none** |

### Findings behind the matrix

1. **The Wayland core protocol gives a client only surface-local pointer coordinates.**
   `wl_pointer.motion` reports "the location relative to the focused surface". No core
   request returns a global pointer position or another client's surface position
   [wayland-core].
2. **The portals give no window list, no geometry and no focus.**
   - RemoteDesktop's `NotifyPointerMotionAbsolute` takes a position in a PipeWire stream's
     logical coordinate space, which ties it to a ScreenCast stream. It is output only:
     nothing in the interface returns the pointer position, a window list, geometry or
     focus [portal-remotedesktop].
   - ScreenCast's stream `position` exists only for monitor streams and "may not be
     equivalent to a position in a pixel coordinate space" [portal-screencast].
   - InputCapture's zones are logical screen regions, and "there is no guarantee that two
     applications see the same screen zones" [portal-inputcapture].
3. **xdg-activation cannot focus another application's window.** The protocol is
   token-based: a token is passed to the client being activated, and that client activates
   *its own* surface. The compositor may ignore the request, for example because of
   focus-stealing prevention [xdg-activation].
4. **The foreign-toplevel protocols list windows but give no geometry.**
   - `ext-foreign-toplevel-list-v1` sends a title, an app id and an identifier. It has no
     geometry and no actions [ext-foreign-toplevel-list].
   - `wlr-foreign-toplevel-management` adds `activate`, `close` and state changes, but no
     geometry. Its `set_rectangle` is a hint from the client to the compositor for animations.
     wayland.app lists it for Sway, Hyprland, river, Wayfire, labwc and niri, but not for
     Mutter or KWin [wlr-foreign-toplevel].
5. **On GNOME, window listing is reserved for allow-listed callers.**
   `org.gnome.Shell.Introspect.GetWindows` returns AccessDenied unless the sender is on the
   Shell's allow-list (the XDG desktop portals) or the Shell is in unsafe mode, which is a
   debugging setting [gnome-shell-introspect]. A Shell extension can do more, but that is
   code running inside the compositor that the user would have to install. It is a
   compositor-private path by definition.
6. **On KDE, window geometry and focus exist, but only through KWin's own interfaces.**
   - `org_kde_plasma_window_management` has a `geometry` event and a `set_state` (active)
     request. Its own description says it is "a desktop environment implementation detail"
     and that "regular clients must not use this protocol" [kde-plasma-window-management].
   - The KWin scripting API (KWin 6) exposes `frameGeometry`, `activeWindow` and `cursorPos`
     [kwin-scripting]. A script runs *inside* the compositor. That makes it the most capable
     path on any Wayland desktop and also the most invasive one.
7. **AT-SPI cannot place a widget on the screen under GTK 4, and cannot focus through it.**
   The Component interface defines screen-, window- and parent-relative coordinate types
   [atspi-component]. GTK 4 answers a screen-relative request with `(0, 0)`
   [gtk4-atspi-screen-coords] and answers `GrabFocus` with `NotSupported`
   [gtk4-atspi-grabfocus]. An accessibility tree can therefore describe what is *inside* a
   window, in that window's own coordinates. It cannot tell YazSes which window a desktop
   pixel belongs to. **Unverified:** Qt's AT-SPI bridge on Wayland was not examined, and
   the matrix does not rely on it.

## What gaze may honestly do

`GazeTargetPlan` (`gaze/target_semantics.py`) carries the session's matrix row and two
decisions derived from it:

| | gaze target available (X11 with xdotool) | no gaze target (every Wayland session, headless, Windows, macOS, X11 without xdotool) |
|---|---|---|
| `dictation_route` | `gazed_window` | `focused_window`: dictation goes where the user's focus already is, and gaze claims nothing |
| `destructive_deixis` ("close this") | `by_config`: `[gaze] confirm_destructive` and `refuse_destructive_fallback` decide (ADR-v2-010, ADR-v2-148) | `refuse`: the command is consumed, nothing is closed, and the user is told why |
| non-destructive deixis ("focus that") | acts on the gazed window | refused with the same feedback |
| look-to-pane, calibration | active | dormant, with the reason in `gaze status`, `doctor`, `status` and the settings panel |

The `refuse` row is the answer to #418's fourth acceptance criterion. Gaze cannot pick a
window on these sessions, so the focused window is not a stand-in for a target that does
not exist, and `refuse_destructive_fallback = false` does not change that. Before this
spec, a Wayland "close this" built no targeter, fell through every handler and was
discarded as `command_unmatched`. Nothing was closed, but nothing was said either. It is
now discarded as `deixis_no_gaze_target`, with a notification.

A coarse screen *zone* is deliberately not offered as a Wayland target. Nothing on these
sessions can turn a zone into a window or an action, so a zone would be a number with no
consumer, and a future caller could mistake it for a target.

## Answers to the issue's research questions

| Question | Answer |
|---|---|
| What window or accessible-object geometry does AT-SPI give under GNOME/KDE Wayland? | Window-relative geometry only. Screen coordinates are `(0, 0)` in GTK 4 (finding 7). Qt was not examined. |
| Can YazSes identify a target window without compositor-private APIs? | No, on any Wayland desktop examined (findings 1–6). |
| Is focus or raise allowed through supported accessibility APIs? | No. AT-SPI `GrabFocus` is unsupported in GTK 4, and xdg-activation only lets a client activate its own surface (findings 3 and 7). |
| What is the honest fallback? | Dictation goes to the focused window, and gaze commands are refused with a reason ("What gaze may honestly do"). |
| Is moving or clicking through RemoteDesktop a desirable fallback? | Not as a gaze target. A click at the gaze point would hand focus to whatever is under a coarse webcam estimate (ADR-v2-010 error envelope), with no way to check first which window that is. That is exactly the guess this spec rules out. A Head-Pointer user who clicks deliberately is a different feature (ADR-v2-146, #403). |

## Possible future paths (none is a default requirement)

Each path below would be a new `TargetBasis`, opt-in and off by default, and each needs
validation on hardware before it ships. Each belongs in its own child issue, not in #418.

- **KDE Plasma via KWin scripting.** This is the only examined path that offers all three
  capabilities (finding 6). It would need three things: a calibration surface placed on a
  known output in KWin's coordinate space (ADR-v2-149), a decision on whether loading a
  script into the compositor is an acceptable trust boundary, and a live Plasma 6 check.
- **wlroots family.** `wlr-foreign-toplevel-management` can focus a window but cannot locate
  one. Per-compositor IPC (Sway, Hyprland) can do both, but every compositor would need its
  own backend.
- **GNOME.** No path without a Shell extension. If GNOME ever ships a public, per-app
  introspection API, re-examine.
- **A Wayland accessibility protocol.** The proposed successor architecture has the
  compositor publish global information, such as the set of all surfaces with
  accessibility trees, and keeps every coordinate surface-relative. If it lands, it is the
  supported path to re-examine.

## Validation still owed

Acceptance criterion two asks for GNOME and KDE behaviour "investigated with current
supported APIs". This spec does that from documentation and toolkit source. It has **not**
been observed on a live session. Three things remain:

1. On a GNOME Wayland session, record the `org.gnome.Shell.Introspect.GetWindows` refusal
   and a GTK 4 screen-coordinate `GetExtents` answer.
2. On a Plasma 6 Wayland session, record whether the plasma window management protocol is
   refused to an unlisted client.
3. Confirm that `yazses gaze status` prints the matrix row on both sessions.

None of these can change the shipped answer, which is `none` on Wayland. They can only
confirm it, or refine a cell from "compositor-specific" toward "no".

## Sources

Each id below appears in `SOURCES` in `src/yazses/gaze/target_capabilities.py`. All are
landing pages or upstream source views, never a file download.

- [wayland-core] Wayland core protocol — <https://wayland.app/protocols/wayland>
- [portal-remotedesktop] XDG Desktop Portal, RemoteDesktop — <https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html>
- [portal-screencast] XDG Desktop Portal, ScreenCast — <https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html>
- [portal-inputcapture] XDG Desktop Portal, InputCapture — <https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.InputCapture.html>
- [xdg-activation] xdg-activation-v1 — <https://wayland.app/protocols/xdg-activation-v1>
- [wlr-foreign-toplevel] wlr-foreign-toplevel-management-unstable-v1 — <https://wayland.app/protocols/wlr-foreign-toplevel-management-unstable-v1>
- [ext-foreign-toplevel-list] ext-foreign-toplevel-list-v1 — <https://wayland.app/protocols/ext-foreign-toplevel-list-v1>
- [kde-plasma-window-management] KDE plasma window management — <https://wayland.app/protocols/kde-plasma-window-management>
- [kwin-scripting] KWin Scripting API (KWin 6) — <https://develop.kde.org/docs/plasma/kwin/api/>
- [gnome-shell-introspect] GNOME Discourse, GetWindows AccessDenied (Emmanuele Bassi, 2024-05-28) — <https://discourse.gnome.org/t/unable-to-call-the-remote-getwindows-gnome-method-via-dbus/21201>
- [atspi-component] AT-SPI `org.a11y.atspi.Component` — <https://ubuntu.com/desktop/docs/en/latest/reference/accessibility/dbus/org.a11y.atspi.Component>
- [gtk4-atspi-screen-coords] GTK 4, `gtk/a11y/gtkatspiutils.c` — <https://gitlab.gnome.org/GNOME/gtk/-/blob/main/gtk/a11y/gtkatspiutils.c>
- [gtk4-atspi-grabfocus] GTK 4, `gtk/a11y/gtkatspicomponent.c` — <https://gitlab.gnome.org/GNOME/gtk/-/blob/main/gtk/a11y/gtkatspicomponent.c>
- [xdpw] xdg-desktop-portal-wlr — <https://github.com/emersion/xdg-desktop-portal-wlr>
- [ewmh] Extended Window Manager Hints — <https://specifications.freedesktop.org/wm-spec/latest/>
- [xtest] X11 XTEST extension — <https://www.x.org/releases/X11R7.7/doc/xextproto/xtest.html>

The successor-architecture note in "Possible future paths" is from the AT-SPI developers'
proposal: <https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/new-protocol.html>.
The matrix does not depend on it.
