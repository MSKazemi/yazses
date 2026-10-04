"""Prove that typed text ARRIVES — not merely that typing did not raise.

Every other signal YazSes has about injection is a statement about the *sender*:
``ydotoold`` accepted the client, the process exited 0, the kernel saw the key events,
``yazses status`` counted the burst as "typed". On 2026-10-04 all of them were green
while the dictated text went into the voice-activity overlay, which Wayland had given
keyboard focus, and nothing appeared anywhere the user looked. A sender cannot see where
its keystrokes land.

The only honest proof is to type into a window we own and **observe the text arrive**.
This module is that orchestration and nothing else. The window (a subprocess), the typer
and the healer are injected, so every verdict below is tested without a display, in the
same split as ``meeting/segmenter.py`` (pure) vs ``meeting/silero_vad.py`` (backend).

Four verdicts, and the asymmetry between them is deliberate:

* ``delivered`` — the probe had focus, we typed, the exact text arrived.
* ``not_delivered`` — the probe had focus, we typed, nothing arrived. The sender is
  broken or the compositor is dropping its events. The only verdict worth healing.
* ``garbled`` — something arrived and it is not what we typed (a layout mismatch, a
  dropped key). Restarting the sender would not fix a layout, so this never heals.
* ``inconclusive`` — the probe never got focus (or could not open), so nothing was
  typed and nothing can be said. It must never read as a pass: a check that says "fine"
  when it could not look is the failure this module exists to remove.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

DELIVERED = "delivered"
NOT_DELIVERED = "not_delivered"
GARBLED = "garbled"
INCONCLUSIVE = "inconclusive"

#: How long to wait for the probe window to take focus / for the text to arrive. The
#: injector types ~12 ms per character, so a short sentence needs well under a second;
#: the rest is the compositor's latency, not ours.
FOCUS_TIMEOUT_S = 4.0
TEXT_TIMEOUT_S = 4.0


class Probe(Protocol):
    """A window whose only job is to receive typed text and say what it got."""

    def wait_focused(self, timeout: float) -> bool: ...

    def wait_text(self, expected: str, timeout: float) -> str:
        """Block until the window holds ``expected`` or the timeout lapses; return what
        it holds *at that moment* (``""`` when nothing arrived)."""
        ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Delivery:
    verdict: str
    detail: str
    received: str = ""
    #: What the healer did, when one ran. Empty when none did.
    healed: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict == DELIVERED


def prove_delivery(
    text: str,
    *,
    open_probe: Callable[[], Probe],
    type_text: Callable[[str], None],
    focus_timeout: float = FOCUS_TIMEOUT_S,
    text_timeout: float = TEXT_TIMEOUT_S,
) -> Delivery:
    """One attempt: open the probe, wait for focus, type ``text``, see what arrived."""
    try:
        probe = open_probe()
    except Exception as exc:  # noqa: BLE001 — "no probe" is an answer, not a crash
        return Delivery(
            INCONCLUSIVE,
            f"no probe window could be opened ({exc}), so delivery was not checked — "
            "nothing was typed.",
        )
    try:
        if not probe.wait_focused(focus_timeout):
            return Delivery(
                INCONCLUSIVE,
                "the probe window never received keyboard focus, so this cannot say "
                "whether typing works — nothing was typed. Click the window if it is "
                "visible and run it again.",
            )
        try:
            type_text(text)
        except Exception as exc:  # noqa: BLE001 — the failure IS the result
            return Delivery(NOT_DELIVERED, f"could not type the text: {exc}")
        got = probe.wait_text(text, text_timeout)
    finally:
        probe.close()

    if got == text:
        return Delivery(DELIVERED, f"typed {len(text)} characters and they arrived", got)
    if not got.strip():
        return Delivery(
            NOT_DELIVERED,
            "the probe window had keyboard focus and the text was typed, but nothing "
            "arrived — the keystrokes are leaving YazSes and not reaching the window.",
            got,
        )
    return Delivery(
        GARBLED,
        f'typed "{_clip(text)}" but the window received "{_clip(got)}" — characters were '
        "dropped or remapped (a keyboard-layout mismatch, or events lost in transit).",
        got,
    )


def prove_with_heal(
    attempt: Callable[[], Delivery],
    heal: Callable[[], str | None] | None,
) -> Delivery:
    """Run ``attempt``; on ``not_delivered`` — and only then — heal and try once more.

    ``heal`` returns a one-line description of what it did, or ``None`` when there was
    nothing it could act on (which leaves the first verdict standing, untouched). It is
    tried exactly once: a loop here would hide a persistent fault behind retries.
    """
    first = attempt()
    if first.verdict != NOT_DELIVERED or heal is None:
        return first
    try:
        action = heal()
    except Exception as exc:  # noqa: BLE001 — a failed heal must not mask the finding
        return replace(first, detail=f"{first.detail} (Healing was attempted and failed: {exc}.)")
    if not action:
        return first
    second = attempt()
    if second.ok:
        return Delivery(
            DELIVERED,
            f"{second.detail} — after healing: {action}",
            second.received,
            healed=action,
        )
    return Delivery(
        second.verdict,
        f"{second.detail} Healing ({action}) did not fix it.",
        second.received,
        healed=action,
    )


def _clip(s: str, n: int = 40) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"
