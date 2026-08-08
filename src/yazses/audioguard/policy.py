"""Sound-event → policy + debounce (pure) — ADR-v2-061.

Map a detected sound-event label to an action and suppress repeats during a cooldown. Pure and
deterministic; the sound classifier that produces labels lives behind the ``soundawareness`` extra.
"""
from __future__ import annotations

# Urgent/interrupting sounds → pause dictation.
_PAUSE = frozenset([
    "alarm", "fire_alarm", "smoke_detector", "siren", "doorbell", "telephone",
    "phone_ring", "ringtone", "baby_cry", "crying", "glass_break",
])
# Attention-worthy but non-urgent → notify only.
_NOTIFY = frozenset(["knock", "name_called", "dog_bark", "microwave", "kettle"])


def event_policy(label: str) -> str:
    """Map a sound-event label to ``pause`` / ``notify`` / ``ignore``. Pure."""
    key = (label or "").lower().strip()
    if key in _PAUSE:
        return "pause"
    if key in _NOTIFY:
        return "notify"
    return "ignore"


class EventDebouncer:
    """Fire a label's policy once, then suppress the same label for a cooldown. Pure state.

    Call :meth:`fire` once per detected event; it returns the policy (``pause``/``notify``) the
    first time and ``None`` while that label is still cooling down. A different actionable label
    fires immediately.
    """

    def __init__(self, cooldown_frames: int = 30) -> None:
        self._cooldown = cooldown_frames
        self._last_label: str | None = None
        self._remaining = 0

    def tick(self) -> None:
        """Advance one frame of cooldown (call when no event fires). Pure state."""
        if self._remaining > 0:
            self._remaining -= 1
            if self._remaining == 0:
                self._last_label = None

    def fire(self, label: str):
        """Return the policy to act on, or ``None`` if suppressed/ignored. Pure state."""
        policy = event_policy(label)
        if policy == "ignore":
            return None
        key = (label or "").lower().strip()
        if key == self._last_label and self._remaining > 0:
            return None
        self._last_label = key
        self._remaining = self._cooldown
        return policy
