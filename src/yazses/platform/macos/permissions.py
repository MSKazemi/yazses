"""macOS permission checks — Accessibility, Input Monitoring, and Microphone.

Three TCC services, not two, and the third is the one that was missing. The
hotkey is a ``CGEventTap`` over keyboard events, and **since macOS 10.15 such a
tap needs Input Monitoring approval in addition to Accessibility** — a fact this
module never checked, the bundle never declared a usage string for, and no
surface ever named. See :meth:`MacosPermissions.check_input_monitoring`.

Accessibility and Microphone go through PyObjC; Input Monitoring goes through
``IOKit`` via :mod:`ctypes`, because ``IOHIDCheckAccess``/``IOHIDRequestAccess``
are plain C functions that PyObjC does not reliably expose. Every import is
local so the module still imports on non-Mac systems for static checks.
"""

from __future__ import annotations

import logging
import sys

from yazses.platform.base import PermissionState

log = logging.getLogger(__name__)

#: `CFBundleIdentifier` from `packaging/macos/yazses.spec`. Passed to `tccutil`
#: so a reset is scoped to YazSes -- the bare form clears every application's
#: grant for that service, which is a far worse outcome than the problem.
_BUNDLE_ID = "com.yazses.app"


# AVAuthorizationStatus values from Apple's AVFoundation framework.
_AV_NOT_DETERMINED = 0
_AV_RESTRICTED = 1
_AV_DENIED = 2
_AV_AUTHORIZED = 3

# IOHIDRequestType / IOHIDAccessType from IOKit/hid/IOHIDLib.h (macOS 10.15+).
# `kIOHIDRequestTypeListenEvent` is the one an *observing* event tap needs;
# `kIOHIDRequestTypePostEvent` (0) is for synthesising input and is a different
# grant, which is why asking for the wrong one would answer the wrong question.
_HID_REQUEST_LISTEN_EVENT = 1
_HID_ACCESS_GRANTED = 0
_HID_ACCESS_DENIED = 1
_HID_ACCESS_UNKNOWN = 2


#: Where IOKit lives on every macOS that can run this app. Tried *before*
#: `ctypes.util.find_library`, deliberately.
#:
#: Since macOS 11 system frameworks are not files on disk -- they live in the dyld
#: shared cache. `find_library` copes by asking `_dyld_shared_cache_contains_path`,
#: but that helper raises `NotImplementedError` on some builds and `dyld_find`
#: swallows it and reports the framework as missing. `CDLL` loads a cache-only
#: path perfectly well, so going straight at the constant is both simpler and more
#: reliable than the search that exists to *find* this exact constant.
#:
#: The failure this avoids is silent: a `None` here downgrades Input Monitoring to
#: UNKNOWN forever, which renders as a WARN with advice attached and looks exactly
#: like "the user has not been asked yet". The fix for #182 would appear to be
#: shipped and do nothing.
_IOKIT_FRAMEWORK = "/System/Library/Frameworks/IOKit.framework/IOKit"


def _iokit():
    """Return the IOKit handle, or ``None`` where it cannot be loaded.

    Separated so the two Input Monitoring calls share one failure mode and so a
    test can substitute it. ``ctypes`` rather than PyObjC on purpose:
    ``IOHIDCheckAccess`` is a bare C function, not an Objective-C selector, and
    which PyObjC framework wheel exposes it has moved between releases — a
    missing symbol here would silently downgrade the check to UNKNOWN forever.

    Two attempts, in this order: the constant framework path (see
    :data:`_IOKIT_FRAMEWORK`), then `find_library` as a fallback for any layout
    that constant does not describe.
    """
    import ctypes
    import ctypes.util

    try:
        return ctypes.CDLL(_IOKIT_FRAMEWORK)
    except OSError:
        pass

    path = ctypes.util.find_library("IOKit")
    if path is None:
        log.warning("IOKit not found; Input Monitoring cannot be determined")
        return None
    try:
        return ctypes.CDLL(path)
    except OSError:
        log.warning("IOKit could not be loaded; Input Monitoring is unknown")
        return None


class MacosPermissions:
    """PermissionsBackend for macOS."""

    def check_keyboard_capture(self) -> PermissionState:
        try:
            from ApplicationServices import (  # type: ignore[import-not-found]
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
            from CoreFoundation import (  # type: ignore[import-not-found]
                kCFBooleanFalse,
            )
        except ImportError:
            log.warning("PyObjC ApplicationServices not available")
            return PermissionState.UNKNOWN

        # Pass prompt=False to check silently. The hotkey backend triggers the
        # prompt explicitly via :meth:`request_keyboard_capture` when needed.
        options = {kAXTrustedCheckOptionPrompt: kCFBooleanFalse}
        return PermissionState.OK if AXIsProcessTrustedWithOptions(options) else PermissionState.DENIED

    def check_microphone(self) -> PermissionState:
        try:
            from AVFoundation import (  # type: ignore[import-not-found]
                AVCaptureDevice,
                AVMediaTypeAudio,
            )
        except ImportError:
            log.warning("PyObjC AVFoundation not available")
            return PermissionState.UNKNOWN

        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        if status == _AV_AUTHORIZED:
            return PermissionState.OK
        if status == _AV_DENIED or status == _AV_RESTRICTED:
            return PermissionState.DENIED
        return PermissionState.UNKNOWN  # NotDetermined → user hasn't been asked yet

    def check_input_monitoring(self) -> PermissionState:
        """Report the **Input Monitoring** grant — the one that was never checked.

        `MacosHotkey` observes the dictation key with a ``CGEventTap`` over
        keyboard events. Since macOS 10.15 that requires user approval of
        **Input Monitoring** *as well as* Accessibility, and the two are separate
        TCC services granted in separate panes. YazSes asked for neither the
        string nor the grant, so on a Mac the whole chain looked like this:

        * the user grants Accessibility, which `doctor` checks and reports OK;
        * `CGEventTapCreate` returns NULL anyway, because Input Monitoring is
          not granted, so the hotkey does nothing at all;
        * nothing ever opens the microphone, so macOS never shows its one-time
          microphone prompt and **YazSes never appears in the Microphone list**.

        That is exactly the report on #182: Accessibility visibly on, hotkey
        dead, and the app absent from Privacy → Microphone with no way to add it.
        Both later symptoms are downstream of this one grant, which is why a
        missing row here read as two unrelated bugs.

        UNKNOWN rather than DENIED when IOKit cannot answer: on this service
        "not determined" and "refused" are the same return value to a caller
        that has never asked, and reporting a refusal we cannot substantiate
        would send the reader to a pane where there is nothing yet to toggle.
        """
        lib = _iokit()
        if lib is None:
            return PermissionState.UNKNOWN
        try:
            import ctypes

            fn = lib.IOHIDCheckAccess
        except AttributeError:
            # Pre-10.15. `LSMinimumSystemVersion` is 11.0, so this is defensive.
            log.warning("IOHIDCheckAccess unavailable; Input Monitoring is unknown")
            return PermissionState.UNKNOWN
        fn.restype = ctypes.c_uint32
        fn.argtypes = [ctypes.c_uint32]
        try:
            status = int(fn(_HID_REQUEST_LISTEN_EVENT))
        except Exception:  # pragma: no cover - defensive
            log.exception("IOHIDCheckAccess raised")
            return PermissionState.UNKNOWN
        if status == _HID_ACCESS_GRANTED:
            return PermissionState.OK
        if status == _HID_ACCESS_DENIED:
            return PermissionState.DENIED
        return PermissionState.UNKNOWN  # _HID_ACCESS_UNKNOWN → never asked

    def request_input_monitoring(self) -> bool:
        """Ask macOS for Input Monitoring, showing its one-time prompt.

        Returns whether access is granted **now**. It is called before the event
        tap is created rather than after it fails, because a NULL tap carries no
        reason: the same NULL answers "not granted", "asked and refused" and
        "asked and the user has not answered yet". Asking first is what puts the
        app in the Input Monitoring list at all — an app that never requests it
        does not appear there, which is the state #182 described for Microphone
        and the reason "just enable it in Settings" was not advice anyone could
        follow.
        """
        lib = _iokit()
        if lib is None:
            return False
        try:
            import ctypes

            fn = lib.IOHIDRequestAccess
        except AttributeError:
            return False
        fn.restype = ctypes.c_bool
        fn.argtypes = [ctypes.c_uint32]
        try:
            return bool(fn(_HID_REQUEST_LISTEN_EVENT))
        except Exception:  # pragma: no cover - defensive
            log.exception("IOHIDRequestAccess raised")
            return False

    def how_to_grant_input_monitoring(self) -> str:
        """Remedy for Input Monitoring — a third pane, not a rewording of the first.

        Kept apart from :meth:`how_to_grant` for the reason that made this bug
        expensive: sending someone to Accessibility for an Input Monitoring
        problem sends them to a toggle that is *already on*, which reads as "the
        app is lying to me" rather than "there is a second switch".
        """
        return (
            "Allow Input Monitoring in System Settings:\n"
            "  System Settings -> Privacy & Security -> Input Monitoring -> enable YazSes.\n"
            "Or open the pane directly:\n"
            "  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent'\n"
            "This is a different service from Accessibility. Since macOS 10.15 the\n"
            "dictation key needs BOTH, and Accessibility being on says nothing about\n"
            "this one -- an enabled Accessibility toggle with a dead hotkey is what\n"
            "a missing Input Monitoring grant looks like.\n"
            "Not listed at all? An app only appears here once it has asked. Launch\n"
            "YazSes and hold the dictation key once, then look again.\n"
            "Listed and enabled but still refused? These builds are unsigned, so\n"
            "macOS sees a new identity whenever the binary changes and the old\n"
            "approval stops applying. Reset just this app's decision:\n"
            f"  tccutil reset ListenEvent {_BUNDLE_ID}\n"
            "(the bundle id matters -- drop it and that command clears the grant\n"
            "for every app on the Mac, not only this one)"
        )

    def request_keyboard_capture(self) -> None:
        try:
            from ApplicationServices import (  # type: ignore[import-not-found]
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
            from CoreFoundation import (  # type: ignore[import-not-found]
                kCFBooleanTrue,
            )
        except ImportError:
            return
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: kCFBooleanTrue})

    def how_to_grant(self) -> str:
        """Say what to do *and* what to do when the obvious thing did not work.

        The first three lines used to be the whole message, and they are the
        instruction a blocked user has already followed -- so `doctor` had nothing
        to offer the person who is actually stuck. Reported on #182/#241 by the
        first human ever to run the macOS build: Accessibility visibly enabled for
        YazSes, three install routes (two `.dmg` versions and Homebrew), and the
        check still answering denied every time.

        The two additions are things this project already knows and had never put
        where someone looks after it failed:

        * **The grant goes stale on an unsigned build.** `docs/macos-install.md`
          states it outright -- macOS treats an unsigned app as a new identity each
          time its hash changes -- and a stale entry still *renders* as an enabled
          toggle, which is exactly the "but it is switched on" report.
        * **The answer is about this process.** `AXIsProcessTrustedWithOptions` is
          process-scoped, so naming the executable it asked about is the difference
          between "YazSes is broken" and "I granted access to a different copy".

        Deliberately no claim about how macOS attributes trust between a launching
        shell and a bundle: that would need a Mac to verify and there is none here.
        Naming the binary lets the reader see the mismatch without being told a
        mechanism that might be wrong.
        """
        return (
            "Grant Accessibility access in System Settings:\n"
            "  System Settings → Privacy & Security → Accessibility → enable YazSes.\n"
            "Or open the pane directly:\n"
            "  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'\n"
            f"This answer is about the program now running -- {sys.executable} --\n"
            "and not about any other copy of YazSes on this Mac.\n"
            "Already enabled and still denied? These builds are unsigned, so macOS\n"
            "sees a new identity whenever the binary changes and the old grant stops\n"
            "applying while the toggle still looks on. Remove YazSes from that list,\n"
            "add it back, then relaunch -- or reset just this app's decision:\n"
            f"  tccutil reset Accessibility {_BUNDLE_ID}\n"
            "(the bundle id matters -- drop it and that command clears the grant\n"
            "for every app on the Mac, not only this one)\n"
            "Accessibility is also not the only switch. Since macOS 10.15 the\n"
            "dictation key needs Input Monitoring too, in its own pane -- check the\n"
            "'Input monitoring' row above before toggling this one again."
        )

    def how_to_grant_microphone(self) -> str:
        """A denied microphone is a *different* TCC service from Accessibility.

        `doctor` had one remedy for both rows and printed it only on the keyboard
        one, so a Mac whose microphone is refused rendered as the bare word
        `denied`: no pane, no command, nothing to act on. Sending that reader to
        Privacy & Security -> Accessibility -- the only advice this class had --
        would have been worse than silence, because the toggle there is already on.

        Two macOS-specific facts a blocked reader needs, and neither is guessable:

        * **"denied" here can mean "never asked".** `AVCaptureDevice` reports
          `NotDetermined` until something actually opens the microphone, and macOS
          only shows its one-time prompt at that moment. `check_microphone` maps
          that to UNKNOWN rather than DENIED, so the honest instruction is to hold
          the hotkey once and answer the prompt -- not to hunt through Settings.
        * **The grant is attached to a code identity, not a name.** These builds
          are unsigned, so a new binary is a new identity and the old approval
          stops applying while the entry still looks enabled -- the same trap
          `how_to_grant` documents for Accessibility, and the reason a reset is
          offered rather than "toggle it off and on".
        """
        return (
            "Allow the microphone in System Settings:\n"
            "  System Settings -> Privacy & Security -> Microphone -> enable YazSes.\n"
            "Or open the pane directly:\n"
            "  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone'\n"
            "Never seen a microphone prompt? macOS only asks the first time an app\n"
            "actually records: hold the hotkey once and answer it.\n"
            "Listed and enabled but still refused? These builds are unsigned, so\n"
            "macOS sees a new identity whenever the binary changes and the old\n"
            "approval stops applying. Reset just this app's microphone decision:\n"
            f"  tccutil reset Microphone {_BUNDLE_ID}\n"
            "(the bundle id matters -- drop it and that command clears the\n"
            "microphone grant for every app on the Mac, not only this one)\n"
            "This is the Microphone service, not Accessibility -- they are granted\n"
            "separately and one being on says nothing about the other."
        )
