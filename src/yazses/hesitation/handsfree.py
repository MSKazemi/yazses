"""Hesitation-hold for hands-free turns: ``[hesitation]`` + ``[autostop]`` -> endpoint judge.

ADR-v2-101 (wiring amendment, 2026-10-21). The daemon calls :func:`build_monitor` only when
``[hesitation] enabled`` is true, so a default install never imports this module.

**One base threshold.** ``[autostop] silence_timeout_ms`` is the commit threshold of a
hands-free turn, and it stays that: hesitation only *extends* it, by ``[hesitation]
hold_extra_ms``, right after a detected filled pause. ``[hesitation] commit_ms`` therefore
defaults to ``0`` -- "use the auto-stop timeout" -- and any other value is ignored with a
warning rather than becoming a second, competing threshold. The auto-stop floor
(``MIN_SILENCE_TIMEOUT_MS``) applies here too, so the judge and the turn agree on the base.

**Hands-free only.** Hold-to-talk ends on key release, so nothing waits on a silence decision
there. With ``[autostop]`` off there is no turn to extend and no monitor is built.

The thresholds the monitor uses (300 ms of sustained voicing, a 400 ms trailing window,
25 Hz of F0 range, 0.7 spectral stability) were checked on synthetic tones only, never on
recorded speech.
"""
from __future__ import annotations

import logging
import math

from yazses.endpoint.autostop import MIN_SILENCE_TIMEOUT_MS
from yazses.hesitation.stream import HesitationMonitor

log = logging.getLogger(__name__)


def commit_ms_for(autostop_cfg) -> float:
    """The plain commit threshold: ``[autostop] silence_timeout_ms`` with the turn's floor. Pure."""
    try:
        timeout = float(getattr(autostop_cfg, "silence_timeout_ms", 800))
    except (TypeError, ValueError):
        timeout = 800.0
    if not math.isfinite(timeout):
        timeout = 800.0
    return max(timeout, float(MIN_SILENCE_TIMEOUT_MS))


def hold_extra_ms_for(hesitation_cfg) -> float:
    """``[hesitation] hold_extra_ms``, never negative: the feature may only lengthen. Pure."""
    try:
        extra = float(getattr(hesitation_cfg, "hold_extra_ms", 0.0))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(extra) or extra < 0:
        return 0.0
    return extra


def build_monitor(hesitation_cfg, autostop_cfg, sample_rate: int) -> HesitationMonitor | None:
    """The live filled-pause judge for hands-free turns, or None when it cannot apply.

    None when ``[hesitation]`` is off, or when ``[autostop]`` is off (hold-to-talk has no
    silence decision to extend). The monitor's :meth:`~HesitationMonitor.decision` is the
    ``endpoint`` that :class:`yazses.endpoint.autostop.AutoStopTurn` consults.
    """
    if not getattr(hesitation_cfg, "enabled", False):
        return None
    if not getattr(autostop_cfg, "enabled", False):
        log.info("[hesitation] is on but [autostop] is off: hesitation-hold only extends a "
                 "hands-free turn's silence timeout, so it has no effect in hold-to-talk.")
        return None
    commit = commit_ms_for(autostop_cfg)
    try:
        configured = float(getattr(hesitation_cfg, "commit_ms", 0.0) or 0.0)
    except (TypeError, ValueError):
        configured = 0.0
    if configured and configured != commit:
        log.warning("[hesitation] commit_ms = %s is ignored: the base threshold is [autostop] "
                    "silence_timeout_ms (%s ms). Set hold_extra_ms to change how long a filled "
                    "pause extends it.", configured, int(commit))
    extra = hold_extra_ms_for(hesitation_cfg)
    log.info("Hesitation-hold enabled (experimental): a filled pause extends the %d ms "
             "auto-stop timeout by %d ms.", int(commit), int(extra))
    return HesitationMonitor(int(sample_rate), commit_ms=commit, hold_extra_ms=extra)

