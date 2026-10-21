"""Where a hummed gesture meets the daemon (ADR-v2-103, #164 WIRE-CONTOUR-001).

`Daemon._contour_gesture` calls :func:`run_hum_gesture` from two places in `_on_hold_end`, and
only while ``[contour] enabled`` -- with the section off this module is never imported:

1. **Before the #598 no-speech discard** (owner decision 2026-10-21). A burst the speech
   detector has just found no speech in would otherwise be dropped before a hum could be
   classified. There is no transcript yet, so the detector's "no speech" verdict stands in for
   the empty-transcript half of the non-word gate, and ``transcript`` is ``None``. The
   mostly-voiced half still applies in full. A burst that is not a recognised hum is then
   discarded exactly as before.
2. **After transcription, before the empty-transcript discard.** A burst the detector *did*
   take for speech reaches the decoder; if what came back is empty or only hum spellings, and
   the audio is mostly voiced, it is a gesture. Any other transcript falls through unchanged.

A recognised gesture runs its command through an existing daemon path and returns without
typing anything. ``confirm`` / ``cancel`` answer a held confirmation (the same holder the
spoken "confirm" and the face switch answer, a no-op when nothing is held); ``undo`` deletes
the last burst YazSes itself typed, as "scratch that" does. A *flat* hum is unmapped by default
(owner decision 2026-10-21), so a thinking "hmm" does nothing.

The thresholds in :mod:`yazses.contour.burst` were checked on synthetic tones only, never on
recorded hums (AGENTS.md rule 9).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping

from yazses.contour.burst import burst_to_command

#: The commands the daemon can run for a hum. A gesture mapped to anything else falls through.
DISPATCHABLE: frozenset[str] = frozenset({"confirm", "cancel", "undo"})


def run_hum_gesture(
    audio,
    sample_rate: int,
    transcript: str | None,
    handlers: Mapping[str, Callable[[], str]],
) -> tuple[str, str] | None:
    """Run the command a hummed burst names: ``(command, outcome)``, or ``None`` to fall through.

    ``None`` -- and no handler called -- when the burst is not a non-word voiced hum, when its
    shape is unmapped (a flat hum, by default), or when no handler exists for its command.
    ``transcript`` is ``None`` only before decoding, when the caller already holds a positive
    "no speech" finding for the burst.
    """
    command = burst_to_command(transcript, audio, sample_rate)
    if command is None or command not in DISPATCHABLE:
        return None
    handler = handlers.get(command)
    if handler is None:
        return None
    return command, handler()


def scratch_last_burst(ledger, injector, *, target_ok: bool | None) -> str:
    """``undo``: delete the last burst YazSes typed, as "scratch that" does. Returns the outcome.

    Refused when the focused window is known not to be editable -- the backspaces would land in
    someone else's text. Peeks, injects, and only then pops the ledger, so a failed injection
    leaves the record intact (the same order as the spoken path).
    """
    if target_ok is False:
        return "not applied: no editable target, the backspaces would go to another window"
    n = len(ledger.last_text())
    if n > 0:
        injector.inject_key_sequence(["BackSpace"] * n)
        ledger.scratch_last()
    return f"scratched {n} chars"
