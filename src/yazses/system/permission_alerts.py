"""Decide which permission denials are worth interrupting the user about.

Every OS permission YazSes needs already had a probe and a remedy string --
`platform/*/permissions.py` has carried both for a long time. They had exactly one
consumer: `system/doctor.py`, a command you have to know to run. Nothing checked a
permission on the daemon's startup path, so on a Mac the failure looked like this:
the daemon starts, reaches IDLE, the menu-bar icon paints healthy, you hold the key
and **nothing happens** -- which is, word for word, what the first human to run the
macOS build reported on #182.

The same shape on Linux: `check_keyboard_capture` answers DENIED when no
`/dev/input/event*` is readable, `how_to_grant` has had the exact `usermod` fix all
along, and the user was never shown either.

Pure and dependency-free -- no notify-send, no PyObjC, no platform import. The caller
probes (that part is I/O and platform-specific) and hands the answers here; this
module only decides what is worth saying. That is what makes the policy testable on a
machine that is not a Mac, which is every machine this project is developed on.

**Only DENIED speaks.** UNKNOWN is silent, deliberately and for a reason the project
has already paid for once: macOS reports a microphone nobody has been asked about yet
as `NotDetermined`, and PyObjC being absent reports UNKNOWN too. Turning "I could not
tell" into a warning is how a working install gets reddened by a probe that never
ran -- the same three-valued rule `system/snap.py` follows for interface state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: The probe answers this module understands. Plain strings rather than the
#: `PermissionState` enum, so nothing here imports the platform layer.
OK = "ok"
DENIED = "denied"
UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class PermissionAlert:
    """One permission the user has to grant, phrased for them."""

    #: Stable identifier, used to rate-limit repeats across restarts. Never shown.
    key: str
    title: str
    #: The consequence, in the user's terms — what they will observe going wrong.
    what: str
    #: How to grant it. Comes from the platform backend's own remedy string, so
    #: there is one source of truth per OS and this module invents no advice.
    fix: str

    @property
    def body(self) -> str:
        return f"{self.what}\n{self.fix}"


@dataclass(frozen=True)
class PermissionProbe:
    """What the platform backend answered. Built by the caller, never here."""

    keyboard: str = UNKNOWN
    microphone: str = UNKNOWN
    #: macOS only; None where the backend does not implement the check.
    input_monitoring: str | None = None

    keyboard_fix: str = ""
    microphone_fix: str = ""
    input_monitoring_fix: str = ""


def alerts_for(probe: PermissionProbe) -> list[PermissionAlert]:
    """The permission problems worth a notification, most blocking first.

    Ordered by what it costs the user. A keyboard grant that is missing means
    dictation cannot even begin, so it outranks a microphone that would only fail
    once they got that far -- and showing both at once, when both are denied on a
    fresh Mac, would be two toasts for what is really one "finish setting me up".
    """
    alerts: list[PermissionAlert] = []

    if probe.keyboard == DENIED:
        alerts.append(
            PermissionAlert(
                key="keyboard-capture",
                title="YazSes cannot see the hold-to-talk key",
                what="Reading the keyboard was refused, so holding the key does "
                "nothing and dictation never starts.",
                fix=probe.keyboard_fix,
            )
        )

    if probe.input_monitoring == DENIED:
        alerts.append(
            PermissionAlert(
                key="input-monitoring",
                title="YazSes cannot read the keyboard on this Mac",
                what="macOS gates this behind Input Monitoring, a separate grant "
                "from Accessibility, and it has not been given.",
                fix=probe.input_monitoring_fix,
            )
        )

    if probe.microphone == DENIED:
        alerts.append(
            PermissionAlert(
                key="microphone",
                title="YazSes is not allowed to use the microphone",
                what="Audio input was refused, so dictation will hear nothing "
                "even when the hotkey works.",
                fix=probe.microphone_fix,
            )
        )

    return alerts


def requests_for(probe: PermissionProbe) -> list[tuple[str, str]]:
    """The OS prompts worth raising now, as ``(slug, method name on the backend)``.

    #562: a fresh macOS install showed no Accessibility prompt at all. The backend has
    had `request_keyboard_capture` since the first macOS commit, and nothing in `src/`
    called it -- so the one switch the user must flip never offered itself, and after a
    `tccutil reset` the app was not even listed in the pane to switch on.

    Only a *specific* state asks (ADR-021): a denied keyboard grant, and a microphone
    macOS has not been asked about yet (`NotDetermined` maps to UNKNOWN). A microphone
    that was refused is not asked again -- macOS would not show a prompt for it. The
    caller still rate-limits by slug and skips a backend without the method, so the
    names here are a request, not a promise.
    """
    wanted: list[tuple[str, str]] = []
    if probe.keyboard == DENIED:
        wanted.append(("keyboard-capture", "request_keyboard_capture"))
    if probe.microphone == UNKNOWN:
        wanted.append(("microphone", "request_microphone"))
    return wanted


def probe_state(perms: object, method: str) -> str | None:
    """One backend probe as a plain string, or None where it did not run. Never raises."""
    check = getattr(perms, method, None)
    if check is None:
        return None
    try:
        return str(getattr(check(), "value", "")) or None
    except Exception:  # noqa: BLE001 - a probe that raises is a probe that did not run
        return None


def grants_given_since_start(
    at_start: Mapping[str, str | None], now: Mapping[str, str | None]
) -> list[str]:
    """Grants that were missing when the daemon started and are present now.

    The hotkey tap reads its Input Monitoring grant when it is created, at daemon start
    (#578). A daemon that started before the grant therefore keeps a deaf tap after the
    user flips the switch, and nothing said so: the Settings toggle looked right, the
    next launch exited as a duplicate, and `doctor` had nothing to compare.

    Not OK -> OK is the only transition reported. OK -> OK and OK -> denied are not this
    problem, and a state that was never determined at either end says nothing.
    """
    return sorted(
        name
        for name, was in at_start.items()
        if was in (DENIED, UNKNOWN) and now.get(name) == OK
    )


_GRANT_LABELS = {"input_monitoring": "Input Monitoring"}


def stale_grant_note(names: list[str]) -> str:
    """One line for `doctor`: which grant the running daemon predates, and the fix."""
    shown = " and ".join(_GRANT_LABELS.get(n, n) for n in names)
    return (
        f"started before {shown} was granted, so its keyboard hook was built without "
        "it and will not see the grant. Fix: run `yazses restart` (in the .app: "
        "`/Applications/YazSes.app/Contents/MacOS/YazSes --cli restart`), then check "
        "`ps aux | grep -i [y]azses` shows one daemon"
    )


__all__ = [
    "DENIED",
    "NOT_APPLICABLE",
    "OK",
    "UNKNOWN",
    "PermissionAlert",
    "PermissionProbe",
    "alerts_for",
    "grants_given_since_start",
    "probe_state",
    "requests_for",
    "stale_grant_note",
]
