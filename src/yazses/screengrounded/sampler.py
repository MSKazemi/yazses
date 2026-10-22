"""Screen-Grounded Dictation as the daemon uses it: one snapshot per hold (ADR-v2-051, #164).

At the start of a hold the daemon calls :meth:`ScreenTermSampler.begin`, which reads the
focused window's accessibility tree on a background thread (``grounding/onscreen.py``)
and mines its labels and text with the pure :func:`~yazses.screengrounded.harvest.harvest_terms`.
When the burst is decoded, :meth:`take` hands those terms to the initial-prompt builder
-- or nothing, if the read has not finished, failed, or found no interesting term.

Three rules, each from the ADR:

* **Off the hot path.** Recording starts without waiting for the read, and the decode
  waits at most ``wait_s`` for it. A slow or hung application costs this burst its
  screen terms, never its transcript.
* **One hold only.** :meth:`take` empties the sampler, so terms read for one burst never
  bias the next one -- the screen may have changed -- and nothing is kept between holds.
* **In RAM, never logged, never stored, never sent.** Only the count of terms is logged.
"""

from __future__ import annotations

import logging
import threading

from yazses.grounding.onscreen import OnScreenReader
from yazses.screengrounded.harvest import harvest_terms

log = logging.getLogger(__name__)

#: How long the decode waits for a read still in flight. The read normally finished
#: long before -- it started when the key went down -- so this only bounds the case of
#: a very short burst over a very large window.
DEFAULT_WAIT_S = 0.15


#: Window chrome every application shares. Reading order puts the menu bar first, so
#: without this "File, Edit, View, Help" would take the first slots of a capped term
#: list ahead of the names in the content -- the words this feature exists to prime.
_CHROME_ROLES = frozenset({
    "menu bar", "menu", "menu item", "check menu item", "radio menu item",
    "tool bar", "status bar", "scroll bar", "separator",
})


def terms_from_candidates(candidates, max_terms: int) -> list[str]:
    """Interesting on-screen terms from snapshot candidates' labels, chrome skipped. Pure."""
    if int(max_terms) <= 0:
        return []
    labels = [getattr(c, "label", None) or "" for c in candidates or ()
              if (getattr(c, "role", "") or "").strip().lower() not in _CHROME_ROLES]
    return harvest_terms(labels, max_terms=int(max_terms))


class ScreenTermSampler:
    """Reads the focused window at hold start; yields its terms once, at decode."""

    def __init__(self, reader: OnScreenReader, *, max_terms: int = 32) -> None:
        self._reader = reader
        self._max_terms = int(max_terms)
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._terms: list[str] = []
        self._generation = 0
        self._active = False

    def begin(self) -> None:
        """Start reading the focused window for this hold. Never blocks, never raises."""
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._terms = []
            self._done = threading.Event()
            done = self._done
            self._active = True

        def run() -> None:
            terms: list[str] = []
            try:
                candidates = self._reader.read()
                if candidates:
                    terms = terms_from_candidates(candidates, self._max_terms)
            except Exception:
                log.debug("screen-grounded read failed", exc_info=True)
            with self._lock:
                # A newer hold has begun: this read belongs to a burst that is gone.
                if generation == self._generation:
                    self._terms = terms
            done.set()
            log.debug("Screen-grounded: %d term(s) read for this hold.", len(terms))

        threading.Thread(target=run, name="screengrounded", daemon=True).start()

    def take(self, wait_s: float = DEFAULT_WAIT_S) -> list[str]:
        """This hold's terms (possibly none), and forget them. Waits at most *wait_s*."""
        with self._lock:
            if not self._active:
                return []
            done = self._done
        done.wait(max(float(wait_s), 0.0))
        with self._lock:
            terms = self._terms if done.is_set() else []
            self._terms = []
            self._active = False
            # Bump the generation so a read still in flight cannot refill the sampler
            # after its burst has already been decoded.
            self._generation += 1
        return list(terms)


__all__ = ["DEFAULT_WAIT_S", "ScreenTermSampler", "terms_from_candidates"]
