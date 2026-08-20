"""macOS permission checks — Accessibility (TCC) and Microphone (AVCaptureDevice).

Both require PyObjC. Imports are local so that the module can be imported on
non-Mac systems for static checks without crashing.
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
            "for every app on the Mac, not only this one)"
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
