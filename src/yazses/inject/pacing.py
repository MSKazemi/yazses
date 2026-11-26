"""`[injection] type_delay_ms`: how fast the typing backends type. Pure.

Keystroke pacing, not the decode and not post-processing, is where the time goes
after a dictation is transcribed: at today's ~12 ms per character a 150-word burst
takes ~9.3 s to appear (design/research/2026-11-20-dictation-latency-inject.md,
recommendation 1). This module turns the one user-facing number into each backend's
own flags.

The value reaches the backends through ``YAZSES_TYPE_DELAY_MS``, set by
`inject.auto.apply_injection_config`, for the same reason ``[injection] backend``
does: `platform.injector_factory` takes no arguments.

``None`` -- the default, written ``-1`` in the config -- means **each backend keeps
the pacing it always had**, which is not one number: xdotool ``--delay 12``, ydotool
1.x ``-d 6 -H 6``, ydotool 0.1.x ``--key-delay 6``, wtype no ``-d`` at all (its own
default, 0). So an install that has not set the key types exactly as before.
"""
from __future__ import annotations

import os

#: The environment variable `apply_injection_config` writes.
ENV_VAR = "YAZSES_TYPE_DELAY_MS"

#: Inclusive bounds; the same ones `config.InjectionConfig.type_delay_ms` declares.
MIN_MS = 0
MAX_MS = 200


def parse_type_delay(raw: object) -> int | None:
    """``raw`` as a usable per-character delay in ms, or ``None`` for "backend default".

    Anything that is not a whole number in ``MIN_MS..MAX_MS`` -- including the
    ``-1`` sentinel, an empty string and garbage -- is ``None``. The config loader has
    already warned about an out-of-range value; this is the second line, so a hand-set
    environment variable can never hand a backend a negative or enormous delay.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            return None
    if MIN_MS <= value <= MAX_MS:
        return value
    return None


def type_delay_ms() -> int | None:
    """The configured per-character delay, read at call time; ``None`` = backend default."""
    return parse_type_delay(os.environ.get(ENV_VAR))


def ydotool_v1_pacing(delay_ms: int) -> tuple[int, int]:
    """``(key_delay, key_hold)`` for ydotool 1.x ``-d``/``-H`` from a per-character budget.

    1.x spends ``-d`` after each event and ``-H`` holding each key, so today's 6/6 is a
    12 ms character. The budget is split the same way: 12 gives 6/6, 5 gives 3/2, and
    0 gives 0/0. ``-d`` gets the odd millisecond because it is the gap between keys,
    which is what a compositor that drops events needs most.
    """
    hold = delay_ms // 2
    return delay_ms - hold, hold


def ydotool_v0_key_delay(delay_ms: int) -> int:
    """``--key-delay`` for ydotool 0.1.x, which has no hold time.

    The inter-key half of the 1.x split, so a given setting maps to the same
    ``--key-delay`` 0.1.x already receives at that pacing (12 -> 6, today's value).
    """
    return ydotool_v1_pacing(delay_ms)[0]


def typing_timeout(chars: int, delay_ms: int | None, *, default_s_per_char: float) -> float:
    """Timeout for typing *chars* characters at *delay_ms*.

    With the backend default (``None``) the per-character budget is the caller's own,
    unchanged. With an explicit delay the budget is 2.5x that delay, but never less than
    the default budget: a slower setting must not turn a long dictation into a timeout,
    which ``LinuxInjector`` reads as a broken backend and answers by pasting the whole
    text a second time.
    """
    per_char = default_s_per_char
    if delay_ms is not None:
        per_char = max(per_char, delay_ms / 1000.0 * 2.5)
    return 10.0 + max(chars, 0) * per_char
