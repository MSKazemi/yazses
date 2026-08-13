"""Capture a selection, rewrite it locally, type it back (#99).

Orchestration only — the grammar and the safety policy are
`commands/rewrite.py`, and the model is whatever callable the daemon injects. So
the whole flow is exercised in tests with a fake clipboard, a fake model and a
fake injector: no desktop, no GGUF, no network.

## The order of operations is the safety design

1. **Read the selection.** PRIMARY first, because highlighting is the gesture
   people actually make; CLIPBOARD as the fallback.
2. **Save the original to the clipboard before anything else.** The undo path has
   to exist *before* the risky step, not after it — if the rewrite is typed and
   the process dies, the user's text is still one paste away.
3. **Rewrite, under a timeout.** A local model that stalls must not hold the
   dictation pipeline.
4. **Check the result** against the instruction's plausibility band. A refusal
   here leaves the selection untouched, which is always the safe outcome.
5. **Type it**, replacing the selection.

Nothing leaves the machine at any step; the model is a local GGUF via the same
llama-cpp path `postprocess/llm_cleanup.py` already uses.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from yazses.commands.rewrite import RewriteIntent, check_rewrite

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RewriteOutcome:
    """What happened, for logging, notification and the learning corpus."""

    ok: bool
    action: str
    reason: str = ""
    original: str = ""
    rewritten: str = ""
    elapsed_ms: float = 0.0

    @property
    def message(self) -> str:
        """One line for a toast. Says what happened to the user's text."""
        if self.ok:
            return f"Rewrote the selection ({self.action}, {self.elapsed_ms:.0f} ms)."
        return f"Left the selection unchanged — {self.reason}."


def rewrite_selection(
    intent: RewriteIntent,
    *,
    read_selection: Callable[[], str],
    rewrite: Callable[[str, str], str],
    inject: Callable[[str], None],
    save_original: Callable[[str], bool] | None = None,
    fallback_text: str = "",
) -> RewriteOutcome:
    """Run one voice rewrite. Never raises; every failure leaves text alone.

    ``fallback_text`` is the last dictated burst, used when nothing is selected —
    the same affordance Punch-In gives, so "make this shorter" straight after
    dictating still means something.
    """
    started = time.monotonic()
    try:
        original = (read_selection() or "").strip()
    except Exception as exc:
        log.debug("selection read failed: %s", exc, exc_info=True)
        original = ""
    if not original:
        original = (fallback_text or "").strip()
    if not original:
        return RewriteOutcome(False, intent.action, "nothing is selected")

    # Before the risky step, never after it.
    if save_original is not None:
        try:
            save_original(original)
        except Exception:
            log.debug("could not save the original to the clipboard", exc_info=True)

    try:
        candidate = rewrite(intent.instruction, original)
    except TimeoutError:
        return RewriteOutcome(False, intent.action, "the local model timed out",
                              original=original)
    except Exception as exc:
        log.warning("Rewrite failed: %s", exc, exc_info=True)
        return RewriteOutcome(False, intent.action, f"the local model failed ({exc})",
                              original=original)

    rejection = check_rewrite(original, candidate, intent)
    if rejection is not None:
        log.info("Rewrite rejected (%s): %s", intent.action, rejection)
        return RewriteOutcome(False, intent.action, str(rejection), original=original)

    text = candidate.strip()
    try:
        inject(text)
    except Exception as exc:
        log.warning("Rewrite injection failed: %s", exc, exc_info=True)
        return RewriteOutcome(False, intent.action, f"could not type the rewrite ({exc})",
                              original=original)

    elapsed = (time.monotonic() - started) * 1000.0
    log.info("Rewrite (%s): %d chars -> %d in %.0f ms.",
             intent.action, len(original), len(text), elapsed)
    return RewriteOutcome(True, intent.action, original=original, rewritten=text,
                          elapsed_ms=elapsed)
