"""When to tell the user that a running meeting has stopped hearing anything. Pure.

``MeetingController.status()["stalled_s"]`` says how long no audio has arrived. Whether
that earns a notification is a separate decision, and the rule is deliberately narrow:

* only past :data:`STALL_NOTIFY_S`, so a device that blips and returns says nothing;
* once per stall, so a dead microphone is not a toast every few seconds;
* re-armed only after audio has resumed (``stalled_s`` back to zero), so a second,
  separate stall is announced again.

Nothing here stops the meeting. A device may come back, and the one thing that ends a
stalled meeting is the wall-clock cap in ``MeetingController``.
"""
from __future__ import annotations

#: Seconds without audio before the user is told. Well past ``controller._STALL_REPORT_S``.
STALL_NOTIFY_S = 30.0

#: How often the daemon's watchdog looks, in seconds. Coarse on purpose: it exists for the
#: meeting that is *not* producing chunks, and a few seconds' lag on a 30 s notice is noise.
WATCH_INTERVAL_S = 5.0

#: Fixed text: no device names, no transcript, nothing that varies with the meeting.
STALL_TITLE = "YazSes — meeting is not hearing audio"
STALL_BODY = (
    "No audio has arrived for over 30 seconds. Check that the microphone is connected "
    "and not in use elsewhere. The meeting stays open and ends at its time limit."
)


class StallNotice:
    """Edge detector over ``stalled_s`` samples: ``observe`` is True once per stall."""

    def __init__(self, threshold_s: float = STALL_NOTIFY_S) -> None:
        self._threshold = float(threshold_s)
        self._announced = False

    def observe(self, stalled_s: float) -> bool:
        """Feed one ``stalled_s`` reading; True exactly when a notice should be sent."""
        if stalled_s <= 0:
            self._announced = False  # audio is arriving again: the next stall is a new one
            return False
        if stalled_s >= self._threshold and not self._announced:
            self._announced = True
            return True
        return False
