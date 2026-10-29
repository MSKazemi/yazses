"""Properties of ``yazses.biosignal.pipeline`` (spec: design/specs/biosignal-pipeline.md).

The pipeline is driven with small fakes (detector, quality monitor, ledger, governor) so
the composition logic -- gates, the stuck-squeeze invariants, desensitization -- is tested
in isolation from the real detectors. Everything is deterministic and offline.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.biosignal import pipeline as pl
from yazses.biosignal.fprate import ActivationLedger, GovernorAction
from yazses.biosignal.pipeline import (
    DEFAULT_INTENT_MAP,
    BiosignalPipeline,
    PartsRequest,
    PipelineOptions,
    PipelineParts,
    build_parts,
    events_to_intents,
    intent_vocabulary,
)
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind

FS = 100.0
CH = (ChannelInfo("emg0", SignalKind.EMG),)
LOGGER = "yazses.biosignal.pipeline"


# ---------------------------------------------------------------------------
# Fakes and helpers


def blk(i: int = 0, *, value: float = 0.0, n: int = 100, channels=CH, fs: float = FS):
    """Block number ``i``: one second long, so it spans ``[i, i + 1)`` seconds."""
    data = np.full((len(channels), n), value, dtype=float)
    return SampleBlock(data=data, fs=fs, channels=channels, t0=float(i) * (n / fs))


def ev(kind, t=0.5, conf=1.0, **detail):
    return BioEvent(kind=kind, t=t, confidence=conf, channel="emg0", detail=dict(detail))


ON, OFF = EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF


class FakeDetector:
    """Emits ``script[i]`` on its i-th block; raises from block ``raise_at`` on."""

    def __init__(self, script=(), raise_at=None):
        self.script = [list(s) for s in script]
        self.raise_at = raise_at
        self.calls = 0
        self.resets = 0
        self.seen: list[SampleBlock] = []

    def process(self, block):
        self.seen.append(block)
        i, self.calls = self.calls, self.calls + 1
        if self.raise_at is not None and i >= self.raise_at:
            raise RuntimeError("detector exploded")
        return self.script[i] if i < len(self.script) else []

    def reset(self):
        self.resets += 1


class ScalableDetector(FakeDetector):
    """A detector that accepts a threshold rescale (as the real ones do)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.scales: list[float] = []

    def set_sensitivity_scale(self, factor):
        self.scales.append(factor)


class RejectingScalable(FakeDetector):
    def set_sensitivity_scale(self, factor):
        raise ValueError("no")


class OldStyleScalable(FakeDetector):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.scales: list[float] = []

    def set_threshold_scale(self, factor):
        self.scales.append(factor)


class Status(Enum):
    GOOD = 1
    BAD = 2


class FakeQuality:
    def __init__(self, overall="GOOD", suppress=False):
        self.overall, self.suppress = overall, suppress
        self.seen: list[SampleBlock] = []
        self.resets = 0
        self.fail = False

    def update(self, block):
        self.seen.append(block)
        if self.fail:
            raise RuntimeError("monitor exploded")
        return SimpleNamespace(overall=self.overall, suppress_events=self.suppress)

    def reset(self):
        self.resets += 1


class FakeLedger:
    def __init__(self, cancel_result=7):
        self.calls: list[tuple] = []
        self.cancel_result = cancel_result
        self.fail = False

    def record(self, event):
        if self.fail:
            raise RuntimeError("ledger exploded")
        self.calls.append(("record", event.kind))

    def start(self):
        self.calls.append(("start",))

    def pause(self):
        self.calls.append(("pause",))

    def mark_cancelled_latest(self, kind=None):
        self.calls.append(("cancel", kind))
        return self.cancel_result

    def names(self):
        return [c[0] for c in self.calls]


class FakeGovernor:
    state = "ok"

    def __init__(self, action=None):
        self.action = action or GovernorAction.ok()
        self.updates = 0
        self.releases = 0
        self.fail_update = False
        self.fail_release = False

    def update(self):
        self.updates += 1
        if self.fail_update:
            raise RuntimeError("governor exploded")
        return self.action

    def release(self):
        self.releases += 1
        if self.fail_release:
            raise RuntimeError("release exploded")
        self.action = GovernorAction.ok()
        return self.action


def make(*detectors, quality=None, ledger=None, governor=None, chains=None, **opts):
    return BiosignalPipeline(PipelineParts(
        detectors=list(detectors), quality=quality, ledger=ledger, governor=governor,
        chain_factories=chains or {}, options=PipelineOptions(**opts)))


def kinds(result):
    return [e.kind for e in result.events]


# ---------------------------------------------------------------------------
# Parts are all optional


def test_pipeline_with_no_parts_at_all_still_processes_blocks():
    """``PipelineParts`` with every piece absent (and no parts argument) is a working no-op."""
    for pipe in (BiosignalPipeline(), BiosignalPipeline(PipelineParts())):
        result = pipe.process(blk(0))
        assert result.events == ()
        assert result.status.blocks == 1
        assert result.status.quality == "unknown"
        assert result.status.detectors == 0
        assert pipe.ledger is None and pipe.governor is None
        assert pipe.governor_state == ""


def test_detector_only_pipeline_forwards_events_in_time_order():
    """With just a detector, events pass and are merged in time order across detectors."""
    a = FakeDetector([[ev(EventKind.BLINK, t=0.8)]])
    b = FakeDetector([[ev(EventKind.JAW_CLENCH, t=0.2)]])
    result = make(a, b).process(blk(0))
    assert kinds(result) == [EventKind.JAW_CLENCH, EventKind.BLINK]
    assert result.status.accepted == 2 and result.status.dropped == 0


def test_status_as_dict_is_plain_and_complete():
    """The IPC snapshot is a plain dict carrying every documented field."""
    d = make().process(blk(0)).status.as_dict()
    assert set(d) == {"quality", "rate_per_hour", "suspended", "reason", "desensitized",
                      "squeeze_active", "blocks", "accepted", "dropped", "detectors"}
    assert d["desensitized"] == 1.0 and d["suspended"] is False


# ---------------------------------------------------------------------------
# A failing stage is disabled with one warning; the others continue


def test_raising_detector_is_removed_with_one_warning_others_continue(caplog):
    """A detector that raises is dropped once (one warning); the healthy one keeps working."""
    bad = FakeDetector(raise_at=0)
    good = FakeDetector([[ev(EventKind.BLINK)], [ev(EventKind.BLINK)], [ev(EventKind.BLINK)]])
    pipe = make(bad, good)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        results = [pipe.process(blk(i)) for i in range(3)]
    assert [len(r.events) for r in results] == [1, 1, 1]
    assert bad.calls == 1                       # never asked again
    assert results[-1].status.detectors == 1
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1


def test_raising_quality_monitor_is_disabled_once_and_gate_opens(caplog):
    """A quality monitor that raises turns the gate off with one warning; events then pass."""
    q = FakeQuality()
    q.fail = True
    det = FakeDetector([[ev(EventKind.BLINK)]] * 3)
    pipe = make(det, quality=q)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        results = [pipe.process(blk(i)) for i in range(3)]
    assert [len(r.events) for r in results] == [1, 1, 1]
    assert len(q.seen) == 1                     # not consulted again after the failure
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_raising_ledger_is_disabled_once_and_events_still_flow(caplog):
    """A ledger that raises stops the accounting, not the events."""
    ledger = FakeLedger()
    ledger.fail = True
    det = FakeDetector([[ev(EventKind.BLINK)]] * 3)
    pipe = make(det, ledger=ledger)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        results = [pipe.process(blk(i)) for i in range(3)]
    assert [len(r.events) for r in results] == [1, 1, 1]
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1
    assert pipe.note_cancelled() is False       # a disabled ledger cancels nothing


def test_raising_governor_is_disabled_once_and_events_still_flow(caplog):
    """A governor that raises means "no automatic suspension", with one warning."""
    gov = FakeGovernor()
    gov.fail_update = True
    det = FakeDetector([[ev(EventKind.BLINK)]] * 3)
    pipe = make(det, governor=gov)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        results = [pipe.process(blk(i)) for i in range(3)]
    assert [len(r.events) for r in results] == [1, 1, 1]
    assert gov.updates == 1
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_raising_filter_chain_leaves_channel_unfiltered_with_one_warning(caplog):
    """A chain that raises is disabled for that channel; the detector still gets the raw data."""
    class Boom:
        def process(self, x):
            raise RuntimeError("filter exploded")

    det = FakeDetector()
    pipe = make(det, chains={SignalKind.EMG: lambda fs: Boom()})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        pipe.process(blk(0, value=3.0))
        pipe.process(blk(1, value=3.0))
    assert all(np.all(b.data == 3.0) for b in det.seen)
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_chain_factory_that_raises_is_tolerated(caplog):
    """A filter chain that cannot even be built leaves the signal unfiltered."""
    def factory(fs):
        raise RuntimeError("no chain")

    det = FakeDetector([[ev(EventKind.BLINK)]])
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = make(det, chains={SignalKind.EMG: factory}).process(blk(0, value=1.0))
    assert kinds(result) == [EventKind.BLINK]


# ---------------------------------------------------------------------------
# Filtering


def test_each_channel_gets_its_own_chain_and_detector_sees_filtered_data():
    """One chain per channel (no shared filter state); detectors read the filtered block."""
    made = []

    class Doubler:
        def __init__(self):
            made.append(self)
            self.resets = 0

        def process(self, x):
            return np.asarray(x) * 2.0

        def reset(self):
            self.resets += 1

    two = (ChannelInfo("a", SignalKind.EMG), ChannelInfo("b", SignalKind.EMG))
    det = FakeDetector()
    q = FakeQuality()
    pipe = make(det, quality=q, chains={SignalKind.EMG: lambda fs: Doubler()})
    pipe.process(blk(0, value=1.0, channels=two))
    assert len(made) == 2 and made[0] is not made[1]
    assert np.all(det.seen[0].data == 2.0)
    assert np.all(q.seen[0].data == 1.0)        # the quality monitor judges the RAW signal
    pipe.process(blk(1, value=1.0, channels=two))
    assert len(made) == 2                       # chains are reused, not rebuilt


def test_chain_that_changes_block_length_is_disabled(caplog):
    """A chain returning a different length cannot be trusted: channel is left unfiltered."""
    class Shorten:
        def process(self, x):
            return np.asarray(x)[:-1]

    det = FakeDetector()
    pipe = make(det, chains={SignalKind.EMG: lambda fs: Shorten()})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        pipe.process(blk(0, value=5.0))
    assert det.seen[0].data.shape == (1, 100) and np.all(det.seen[0].data == 5.0)


def test_sampling_rate_change_rebuilds_chains():
    """After a reconnect at another fs the old coefficients are discarded."""
    fs_seen = []

    class Chain:
        def __init__(self, fs):
            fs_seen.append(fs)

        def process(self, x):
            return np.asarray(x)

        def reset(self):
            pass

    pipe = make(chains={SignalKind.EMG: Chain})
    pipe.process(blk(0, fs=100.0))
    pipe.process(blk(1, fs=100.0))
    pipe.process(blk(2, fs=200.0, n=200))
    assert fs_seen == [100.0, 200.0]


# ---------------------------------------------------------------------------
# Quality gate


def test_bad_quality_drops_detector_events_and_counts_them():
    """While quality is BAD no new event is accepted (invariant 2); they are counted as dropped."""
    det = FakeDetector([[ev(EventKind.BLINK)], [ev(EventKind.JAW_CLENCH)]])
    pipe = make(det, quality=FakeQuality("BAD"))
    results = [pipe.process(blk(i)) for i in range(2)]
    assert all(r.events == () for r in results)
    assert results[-1].status.dropped == 2 and results[-1].status.accepted == 0
    assert results[-1].status.quality == "bad"


@pytest.mark.parametrize("overall", ["bad", "BAD", Status.BAD])
def test_gate_accepts_strings_and_enums_for_bad(overall):
    """``overall`` may be a string in any case or an enum member named BAD."""
    pipe = make(FakeDetector([[ev(EventKind.BLINK)]]), quality=FakeQuality(overall))
    assert pipe.process(blk(0)).events == ()


def test_suppress_events_flag_closes_gate_even_when_overall_is_not_bad():
    """A report that says ``suppress_events`` closes the gate regardless of ``overall``."""
    pipe = make(FakeDetector([[ev(EventKind.BLINK)]]), quality=FakeQuality("GOOD", suppress=True))
    assert pipe.process(blk(0)).events == ()


def test_good_and_degraded_quality_pass_events():
    """Only BAD closes the gate; GOOD and DEGRADED are trusted."""
    for overall in ("GOOD", "DEGRADED", Status.GOOD):
        pipe = make(FakeDetector([[ev(EventKind.BLINK)]]), quality=FakeQuality(overall))
        assert kinds(pipe.process(blk(0))) == [EventKind.BLINK]


def test_detectors_keep_tracking_while_gate_is_closed():
    """The gate is on the detectors' OUTPUT: they still see every block while gated."""
    det = FakeDetector()
    pipe = make(det, quality=FakeQuality("BAD"))
    for i in range(3):
        pipe.process(blk(i))
    assert det.calls == 3


def test_flatline_source_makes_no_phantom_trigger_with_the_real_monitor():
    """A flatline (dead electrode) judged by the real monitor yields silence, never an event."""
    from yazses.biosignal.quality import SignalQualityMonitor

    chatty = FakeDetector([[ev(ON, level="light")], [ev(EventKind.BLINK)]] * 20)
    pipe = make(chatty, quality=SignalQualityMonitor())
    accepted = []
    for i in range(40):
        accepted += list(pipe.process(blk(i, value=0.0)).events)
    assert accepted == []
    assert pipe.squeeze_active is False


def test_real_squeeze_off_passes_a_closed_gate():
    """A real SQUEEZE_OFF is never gated: dropping it would strand the held key."""
    q = FakeQuality("GOOD")
    det = FakeDetector([[ev(ON)], [ev(OFF, conf=0.01)]])
    pipe = make(det, quality=q)
    assert kinds(pipe.process(blk(0))) == [ON]
    q.overall = "BAD"
    result = pipe.process(blk(1))
    assert kinds(result) == [OFF]                       # exactly one OFF, the detector's own
    assert result.events[0].detail.get("synthetic") is None
    assert pipe.squeeze_active is False


def test_gate_closing_under_a_held_squeeze_emits_one_synthetic_off_in_the_same_result():
    """Gate closes while squeeze is held -> synthetic OFF now, not on some later block."""
    q = FakeQuality("GOOD")
    pipe = make(FakeDetector([[ev(ON)]]), quality=q)
    pipe.process(blk(0))
    assert pipe.squeeze_active is True
    q.overall = "BAD"
    result = pipe.process(blk(1))
    assert kinds(result) == [OFF]
    assert result.events[0].detail["synthetic"] is True
    assert result.events[0].t == 2.0                    # end of the block that closed the gate
    assert result.status.squeeze_active is False
    assert kinds(pipe.process(blk(2))) == []            # and nothing further is emitted


def test_orphan_off_is_not_forwarded():
    """An OFF for an ON that was never forwarded releases nothing and is not forwarded."""
    pipe = make(FakeDetector([[ev(OFF)]]))
    result = pipe.process(blk(0))
    assert result.events == () and result.status.accepted == 0


def test_squeeze_that_starts_and_ends_in_one_block_is_not_left_held():
    """ON and OFF inside a single block are both forwarded; nothing stays held."""
    det = FakeDetector([[ev(ON, t=0.2), ev(OFF, t=0.6)]])
    pipe = make(det)
    result = pipe.process(blk(0))
    assert kinds(result) == [ON, OFF]
    assert pipe.squeeze_active is False and result.status.squeeze_active is False


def test_squeeze_inside_one_block_while_gated_leaves_no_orphan_off():
    """With the gate closed both the ON and its OFF are dropped -- no unpaired OFF."""
    pipe = make(FakeDetector([[ev(ON, t=0.2), ev(OFF, t=0.6)]]), quality=FakeQuality("BAD"))
    result = pipe.process(blk(0))
    assert result.events == () and pipe.squeeze_active is False


def test_squeeze_on_while_gated_is_dropped():
    """A new squeeze may not start while the signal is untrusted."""
    pipe = make(FakeDetector([[ev(ON)]]), quality=FakeQuality("BAD"))
    result = pipe.process(blk(0))
    assert result.events == () and pipe.squeeze_active is False


# ---------------------------------------------------------------------------
# Failing detector and governor releases a held squeeze


def test_detector_raising_while_squeeze_held_yields_a_synthetic_off(caplog):
    """The detector that held the squeeze dies: nothing would send its OFF, so we do."""
    holder = FakeDetector([[ev(ON)]], raise_at=1)
    other = FakeDetector([[], [ev(EventKind.BLINK)]])
    pipe = make(holder, other)
    pipe.process(blk(0))
    assert pipe.squeeze_active is True
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = pipe.process(blk(1))
    assert kinds(result) == [EventKind.BLINK, OFF] or set(kinds(result)) == {EventKind.BLINK, OFF}
    off = next(e for e in result.events if e.kind is OFF)
    assert off.detail["synthetic"] is True and off.detail["reason"] == "detector failed"
    assert pipe.squeeze_active is False
    assert result.status.detectors == 1


def test_governor_suspend_under_held_squeeze_emits_off_in_the_same_result():
    """Suspension is a stop: a held squeeze is closed in the very result that suspends."""
    gov = FakeGovernor()
    pipe = make(FakeDetector([[ev(ON)]]), governor=gov)
    pipe.process(blk(0))
    assert pipe.squeeze_active
    gov.action = GovernorAction.suspend("too many false positives")
    result = pipe.process(blk(1))
    assert kinds(result) == [OFF]
    assert result.events[0].detail["synthetic"] is True
    assert "too many false positives" in result.events[0].detail["reason"]
    assert result.status.suspended and not result.status.squeeze_active
    assert result.status.reason == "too many false positives"


def test_squeeze_started_in_the_suspending_block_is_released_too():
    """ON accepted in the same block the governor suspends is followed by an OFF."""
    gov = FakeGovernor(GovernorAction.suspend("budget"))
    pipe = make(FakeDetector([[ev(ON)]]), governor=gov)
    result = pipe.process(blk(0))
    assert kinds(result) == [ON, OFF]
    assert pipe.squeeze_active is False


def test_suspended_pipeline_drops_new_events_but_passes_a_real_off():
    """While suspended nothing new is accepted; OFF-for-a-held-squeeze would still pass."""
    gov = FakeGovernor(GovernorAction.suspend("budget"))
    det = FakeDetector([[], [ev(EventKind.BLINK), ev(ON)], [ev(OFF)]])
    pipe = make(det, governor=gov)
    pipe.process(blk(0))
    result = pipe.process(blk(1))
    assert result.events == () and result.status.dropped == 2
    assert pipe.process(blk(2)).events == ()           # orphan OFF, nothing held


def test_suspension_ends_when_the_governor_says_ok():
    """When the governor returns to OK the pipeline accepts events again."""
    gov = FakeGovernor(GovernorAction.suspend("budget"))
    det = FakeDetector([[], [ev(EventKind.BLINK)], [ev(EventKind.BLINK)]])
    pipe = make(det, governor=gov)
    pipe.process(blk(0))
    assert pipe.process(blk(1)).events == ()
    gov.action = GovernorAction.ok()
    pipe.process(blk(2))                               # governor consulted after this block
    assert pipe.status.suspended is False and pipe.status.reason == ""


# ---------------------------------------------------------------------------
# Desensitization


def test_scale_hook_is_used_instead_of_the_confidence_floor():
    """A detector with ``set_sensitivity_scale`` is rescaled and NOT also floored."""
    det = ScalableDetector([[], [ev(EventKind.BLINK, conf=0.1)]])
    gov = FakeGovernor(GovernorAction.desensitize(2.0, "noisy"))
    pipe = make(det, governor=gov)
    pipe.process(blk(0))
    assert det.scales == [2.0]
    assert kinds(pipe.process(blk(1))) == [EventKind.BLINK]    # no second penalty
    assert pipe.status.desensitized == 2.0


def test_confidence_floor_is_used_when_there_is_no_scale_hook():
    """A detector without the hook is desensitized by raising the confidence floor."""
    det = FakeDetector([[], [ev(EventKind.BLINK, conf=0.7), ev(EventKind.JAW_CLENCH, conf=0.8)]])
    gov = FakeGovernor(GovernorAction.desensitize(1.5, "noisy"))
    pipe = make(det, governor=gov)                     # base 0.5 * 1.5 = 0.75
    pipe.process(blk(0))
    result = pipe.process(blk(1))
    assert kinds(result) == [EventKind.JAW_CLENCH]
    assert result.status.dropped == 1


def test_exactly_one_mechanism_per_event_when_detectors_are_mixed():
    """With min_confidence 0.4 and factor 1.5: scaled floor stays 0.4, unscaled becomes 0.6."""
    scaled = ScalableDetector([[], [ev(EventKind.BLINK, conf=0.5)]])
    plain = FakeDetector([[], [ev(EventKind.JAW_CLENCH, conf=0.5)]])
    gov = FakeGovernor(GovernorAction.desensitize(1.5, "noisy"))
    pipe = make(scaled, plain, governor=gov, min_confidence=0.4)
    pipe.process(blk(0))
    assert kinds(pipe.process(blk(1))) == [EventKind.BLINK]


def test_old_style_threshold_scale_hook_is_honoured():
    """``set_threshold_scale`` counts as a rescale hook too."""
    det = OldStyleScalable()
    pipe = make(det, governor=FakeGovernor(GovernorAction.desensitize(3.0)))
    pipe.process(blk(0))
    assert det.scales == [3.0]


def test_rejecting_scale_hook_falls_back_to_the_floor(caplog):
    """A hook that raises is disabled with one warning and the floor covers that detector."""
    det = RejectingScalable([[], [ev(EventKind.BLINK, conf=0.4)]])
    pipe = make(det, governor=FakeGovernor(GovernorAction.desensitize(2.0)))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        pipe.process(blk(0))
        assert pipe.process(blk(1)).events == ()       # floor 1.0 > 0.4
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_repeated_identical_action_does_not_rescale_every_block():
    """The governor repeats itself each block; the detector is told only on a change."""
    det = ScalableDetector()
    gov = FakeGovernor(GovernorAction.desensitize(2.0))
    pipe = make(det, governor=gov)
    for i in range(4):
        pipe.process(blk(i))
    assert det.scales == [2.0]
    gov.action = GovernorAction.desensitize(3.0)
    pipe.process(blk(4))
    assert det.scales == [2.0, 3.0]


def test_factor_resets_to_exactly_one_when_governor_returns_ok():
    """Returning to OK restores the detectors to exactly 1.0 and clears the floor."""
    det = ScalableDetector()
    gov = FakeGovernor(GovernorAction.desensitize(2.0))
    pipe = make(det, governor=gov)
    pipe.process(blk(0))
    gov.action = GovernorAction.ok()
    result = pipe.process(blk(1))
    assert det.scales == [2.0, 1.0]
    assert result.status.desensitized == 1.0

    plain = FakeDetector([[], [], [ev(EventKind.BLINK, conf=0.1)]])
    gov2 = FakeGovernor(GovernorAction.desensitize(2.0))
    pipe2 = make(plain, governor=gov2)
    pipe2.process(blk(0))
    gov2.action = GovernorAction.ok()
    pipe2.process(blk(1))
    assert kinds(pipe2.process(blk(2))) == [EventKind.BLINK]


def test_desensitizing_never_blocks_a_squeeze_release():
    """OFF ignores the confidence floor, and a level change while held is not floored."""
    det = FakeDetector([[ev(ON, conf=1.0)], [ev(ON, conf=0.05, level="hard")],
                        [ev(OFF, conf=0.01)]])
    gov = FakeGovernor()
    pipe = make(det, governor=gov)
    pipe.process(blk(0))
    gov.action = GovernorAction.desensitize(2.0)
    assert kinds(pipe.process(blk(1))) == [ON]         # level change while held
    assert kinds(pipe.process(blk(2))) == [OFF]
    assert pipe.squeeze_active is False


def test_governor_release_resets_factor_and_clears_suspension_at_once():
    """The user's "carry on" drops desensitization and suspension immediately."""
    det = ScalableDetector([[], [ev(EventKind.BLINK)]])
    gov = FakeGovernor(GovernorAction.suspend("budget"))
    pipe = make(det, governor=gov)
    pipe.process(blk(0))
    assert pipe.status.suspended
    action = pipe.governor_release()
    assert action.kind.value == "ok"
    assert pipe.status.suspended is False and pipe.status.reason == ""
    assert pipe.status.desensitized == 1.0
    assert kinds(pipe.process(blk(1))) == [EventKind.BLINK]


def test_governor_release_after_desensitize_restores_detector_scale():
    det = ScalableDetector()
    gov = FakeGovernor(GovernorAction.desensitize(2.0))
    pipe = make(det, governor=gov)
    pipe.process(blk(0))
    pipe.governor_release()
    assert det.scales == [2.0, 1.0] and pipe.status.desensitized == 1.0


# ---------------------------------------------------------------------------
# Ledger accounting


def test_ledger_is_paused_while_gated_and_started_when_live():
    """Gated time is not exposure: pause while the gate is closed, start when it reopens."""
    q = FakeQuality("GOOD")
    ledger = FakeLedger()
    pipe = make(quality=q, ledger=ledger)
    pipe.process(blk(0))
    q.overall = "BAD"
    pipe.process(blk(1))
    q.overall = "GOOD"
    pipe.process(blk(2))
    assert ledger.names() == ["start", "pause", "start"]


def test_ledger_is_paused_while_suspended():
    """Suspension is not exposure either (evaluated from the block after it begins)."""
    ledger = FakeLedger()
    gov = FakeGovernor(GovernorAction.suspend("budget"))
    pipe = make(ledger=ledger, governor=gov)
    pipe.process(blk(0))
    pipe.process(blk(1))
    assert ledger.names() == ["start", "pause"]


def test_only_accepted_events_are_recorded_in_the_ledger():
    """Dropped events must not be counted as activations."""
    ledger = FakeLedger()
    q = FakeQuality("GOOD")
    det = FakeDetector([[ev(EventKind.BLINK)], [ev(EventKind.JAW_CLENCH)]])
    pipe = make(det, quality=q, ledger=ledger)
    pipe.process(blk(0))
    q.overall = "BAD"
    pipe.process(blk(1))
    assert [c for c in ledger.calls if c[0] == "record"] == [("record", EventKind.BLINK)]


# ---------------------------------------------------------------------------
# note_cancelled / governor_release


def test_note_cancelled_reports_whether_the_ledger_matched_and_consults_governor():
    ledger = FakeLedger(cancel_result=3)
    gov = FakeGovernor()
    pipe = make(ledger=ledger, governor=gov)
    assert pipe.note_cancelled(EventKind.JAW_CLENCH) is True
    assert ("cancel", EventKind.JAW_CLENCH) in ledger.calls
    assert gov.updates == 1
    ledger.cancel_result = None
    assert pipe.note_cancelled() is False


def test_note_cancelled_without_ledger_is_false():
    assert make().note_cancelled() is False


def test_note_cancelled_can_trigger_suspension():
    """A cancellation that pushes the governor over budget suspends straight away."""
    gov = FakeGovernor(GovernorAction.suspend("budget"))
    pipe = make(ledger=FakeLedger(), governor=gov)
    pipe.note_cancelled()
    assert pipe.status.suspended is True


def test_governor_release_without_governor_returns_ok():
    action = make().governor_release()
    assert action.kind.value == "ok"


def test_governor_release_is_idempotent():
    """Releasing twice (or with nothing to release) is harmless and always OK."""
    gov = FakeGovernor(GovernorAction.desensitize(2.0))
    pipe = make(ScalableDetector(), governor=gov)
    pipe.process(blk(0))
    first, second = pipe.governor_release(), pipe.governor_release()
    assert first.kind.value == second.kind.value == "ok"
    assert pipe.status.desensitized == 1.0 and pipe.status.suspended is False


def test_governor_release_that_raises_is_tolerated(caplog):
    gov = FakeGovernor()
    gov.fail_release = True
    pipe = make(governor=gov)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        action = pipe.governor_release()
        pipe.governor_release()
    assert action.kind.value == "ok"
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_note_cancelled_waits_for_a_block_in_progress():
    """``process`` and ``note_cancelled`` are serialized by one lock."""
    entered, release = threading.Event(), threading.Event()

    class Blocking(FakeDetector):
        def process(self, block):
            entered.set()
            release.wait(5.0)
            return []

    ledger = FakeLedger()
    pipe = make(Blocking(), ledger=ledger)
    feeder = threading.Thread(target=pipe.process, args=(blk(0),), daemon=True)
    canceller = threading.Thread(target=pipe.note_cancelled, daemon=True)
    try:
        feeder.start()
        assert entered.wait(5.0)
        canceller.start()
        canceller.join(0.1)
        assert canceller.is_alive()                    # blocked behind the running block
        assert not any(c[0] == "cancel" for c in ledger.calls)
    finally:
        release.set()
        feeder.join(5.0)
        canceller.join(5.0)
    assert any(c[0] == "cancel" for c in ledger.calls)


def test_concurrent_cancel_release_and_process_do_not_corrupt_state():
    """Hammering the thread-safe entry points from other threads raises nothing."""
    from yazses.biosignal.fprate import BudgetGovernor, FalsePositiveBudget

    now = [0.0]
    ledger = ActivationLedger(clock=lambda: now[0])
    gov = BudgetGovernor(ledger, FalsePositiveBudget(max_cancelled_per_hour=3.0, enabled=True))
    det = FakeDetector([[ev(EventKind.BLINK)]] * 200)
    pipe = make(det, ledger=ledger, governor=gov)
    errors: list[BaseException] = []

    def hammer(fn):
        try:
            for _ in range(100):
                fn()
        except BaseException as exc:                   # noqa: BLE001 - report to the test
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(f,), daemon=True)
               for f in (pipe.note_cancelled, pipe.governor_release, pipe.governor_release)]
    for t in threads:
        t.start()
    try:
        for i in range(100):
            pipe.process(blk(i))
    finally:
        for t in threads:
            t.join(10.0)
    assert errors == []
    assert not any(t.is_alive() for t in threads)
    assert pipe.status.blocks == 100


# ---------------------------------------------------------------------------
# reset and rate


def test_reset_forgets_stream_state_without_announcing_a_release():
    """``reset`` resets chains, detectors and the monitor and forgets a held squeeze silently."""
    q = FakeQuality()
    det = FakeDetector([[ev(ON)]])
    pipe = make(det, quality=q)
    pipe.process(blk(0))
    assert pipe.squeeze_active
    pipe.reset()
    assert det.resets == 1 and q.resets == 1
    assert pipe.squeeze_active is False
    assert pipe.process(blk(1)).events == ()


def test_rate_per_hour_extrapolates_from_recent_accepted_events():
    """The reported rate counts accepted events (not OFFs) over the observed span."""
    det = FakeDetector([[ev(EventKind.BLINK, t=1.0), ev(EventKind.BLINK, t=2.0)]])
    pipe = make(det)
    status = pipe.process(blk(0, n=1000)).status       # block spans [0, 10)
    assert status.rate_per_hour == pytest.approx(2 * 3600.0 / 9.0)


def test_rate_window_forgets_old_events():
    det = FakeDetector([[ev(EventKind.BLINK, t=1.0)], [], []])
    pipe = make(det, rate_window_s=5.0)
    pipe.process(blk(0))
    pipe.process(blk(1))
    assert pipe.process(blk(10)).status.rate_per_hour == 0.0


# ---------------------------------------------------------------------------
# events_to_intents / intent_vocabulary


def test_default_map_sends_double_blink_to_undo_and_leaves_jaw_clench_unmapped():
    events = [ev(EventKind.DOUBLE_BLINK, conf=0.9), ev(EventKind.JAW_CLENCH),
              ev(EventKind.BLINK)]
    intents = events_to_intents(events)
    assert [(i.label, i.confidence, i.source) for i in intents] == [
        ("undo", 0.9, "biosignal:double_blink")]
    assert DEFAULT_INTENT_MAP == {"double_blink": "undo"}


def test_map_keys_may_be_strings_or_eventkinds():
    events = [ev(EventKind.JAW_CLENCH), ev(EventKind.DOUBLE_BLINK)]
    by_enum = events_to_intents(events, {EventKind.JAW_CLENCH: "send"})
    by_text = events_to_intents(events, {" JAW_Clench ".strip().lower(): "send"})
    assert [i.label for i in by_enum] == ["send"] == [i.label for i in by_text]
    both = events_to_intents(events, {EventKind.JAW_CLENCH: "send", "double_blink": "undo"})
    assert [i.label for i in both] == ["send", "undo"]


def test_string_keys_are_case_and_space_insensitive():
    out = events_to_intents([ev(EventKind.JAW_CLENCH)], {"  Jaw_Clench ": "  send  "})
    assert [i.label for i in out] == ["send"]


def test_squeeze_events_are_never_mapped_even_if_the_user_asks():
    """Squeezes are modes, not intents; a map entry for them is inert."""
    mapping = {"squeeze_on": "dictate", EventKind.SQUEEZE_OFF: "stop"}
    assert events_to_intents([ev(ON), ev(OFF)], mapping) == []
    assert intent_vocabulary(mapping) == ()


def test_empty_label_and_empty_map_produce_no_intent():
    assert events_to_intents([ev(EventKind.JAW_CLENCH)], {"jaw_clench": "  "}) == []
    assert events_to_intents([ev(EventKind.DOUBLE_BLINK)], {}) == []   # {} is the user's map


def test_intent_confidence_is_clamped_and_nan_becomes_zero():
    out = events_to_intents(
        [ev(EventKind.JAW_CLENCH, conf=7.0), ev(EventKind.JAW_CLENCH, conf=float("nan")),
         ev(EventKind.JAW_CLENCH, conf=-1.0)], {"jaw_clench": "send"})
    assert [i.confidence for i in out] == [1.0, 0.0, 0.0]


def test_source_prefix_is_configurable():
    out = events_to_intents([ev(EventKind.DOUBLE_BLINK)], source="eog")
    assert out[0].source == "eog:double_blink"


def test_intents_are_labels_drawn_only_from_the_declared_vocabulary():
    """Every emitted label is in the vocabulary (labels only, never free text)."""
    mapping = {"double_blink": "undo", EventKind.JAW_CLENCH: "send"}
    vocab = set(intent_vocabulary(mapping))
    events = [ev(k) for k in EventKind]
    assert {i.label for i in events_to_intents(events, mapping)} <= vocab == {"undo", "send"}


def test_intent_vocabulary_defaults_dedupes_and_skips_blank_labels():
    assert intent_vocabulary() == ("undo",)
    assert intent_vocabulary({"a": "x", "b": "x", "c": " ", EventKind.BLINK: "y"}) == ("x", "y")


# ---------------------------------------------------------------------------
# build_parts


def test_build_parts_with_everything_off_has_filters_quality_and_no_detectors():
    parts = build_parts(PartsRequest(fs=FS))
    assert parts.detectors == [] and parts.governor is None and parts.ledger is None
    assert parts.quality is not None
    assert set(parts.chain_factories) == set(SignalKind)


def test_build_parts_only_builds_filters_for_the_channel_kinds_present():
    parts = build_parts(PartsRequest(fs=FS, channels=CH))
    assert set(parts.chain_factories) == {SignalKind.EMG}


def test_build_parts_ledger_and_governor_switches():
    assert build_parts(PartsRequest(fs=FS, with_ledger=True)).governor is None
    assert build_parts(PartsRequest(fs=FS, with_ledger=True)).ledger is not None
    parts = build_parts(PartsRequest(fs=FS, max_cancelled_per_hour=5.0))
    assert parts.ledger is not None and parts.governor is not None


def test_build_parts_uses_from_calibration_when_the_profile_has_the_amplitudes(monkeypatch):
    """A profile with blink_amplitude / clench_power builds the detectors from calibration."""
    from yazses.biosignal.artifacts import BlinkDetector, JawClenchDetector

    calls = []
    real_blink_cal, real_jaw_cal = BlinkDetector.from_calibration, JawClenchDetector.from_calibration

    def blink_cal(fs, amp, **kw):
        calls.append(("blink", fs, amp, kw))
        return real_blink_cal(fs, amp, **kw)

    def jaw_cal(fs, power, **kw):
        calls.append(("jaw", fs, power, kw))
        return real_jaw_cal(fs, power, **kw)

    monkeypatch.setattr(BlinkDetector, "from_calibration", staticmethod(blink_cal))
    monkeypatch.setattr(JawClenchDetector, "from_calibration", staticmethod(jaw_cal))
    monkeypatch.setattr(pl, "_load_profile",
                        lambda request: SimpleNamespace(blink_amplitude=150.0, clench_power=40.0))
    parts = build_parts(PartsRequest(fs=FS, double_blink=True, jaw_clench=True, channels=CH))
    assert len(parts.detectors) == 2
    blink_call = next(c for c in calls if c[0] == "blink")
    jaw_call = next(c for c in calls if c[0] == "jaw")
    assert blink_call[1:3] == (FS, 150.0) and blink_call[3] == {"double_only": True}
    assert jaw_call[1:3] == (FS, 40.0) and "speech_guard" in jaw_call[3]
    assert callable(jaw_call[3]["speech_guard"])


def test_build_parts_calibrated_blink_threshold_matches_from_calibration(monkeypatch):
    from yazses.biosignal.artifacts import BlinkDetector

    monkeypatch.setattr(pl, "_load_profile",
                        lambda request: SimpleNamespace(blink_amplitude=400.0, clench_power=None))
    (det,) = build_parts(PartsRequest(fs=FS, double_blink=True)).detectors
    expected = BlinkDetector.from_calibration(FS, 400.0, double_only=True)
    assert det.min_amplitude_uv == expected.min_amplitude_uv


def test_build_parts_without_a_profile_or_amplitudes_uses_default_detectors(monkeypatch):
    """No profile, or a profile lacking the values, falls back to the plain constructors."""
    from yazses.biosignal.artifacts import BlinkDetector, JawClenchDetector

    def boom(*a, **k):
        raise AssertionError("from_calibration must not be used")

    monkeypatch.setattr(BlinkDetector, "from_calibration", staticmethod(boom))
    monkeypatch.setattr(JawClenchDetector, "from_calibration", staticmethod(boom))
    for profile in (None, SimpleNamespace(blink_amplitude=None, clench_power=0.0),
                    SimpleNamespace(blink_amplitude=float("nan"), clench_power=-3.0)):
        monkeypatch.setattr(pl, "_load_profile", lambda request, p=profile: p)
        parts = build_parts(PartsRequest(fs=FS, double_blink=True, jaw_clench=True))
        assert [type(d).__name__ for d in parts.detectors] == [
            "BlinkDetector", "JawClenchDetector"]


def test_build_parts_refuses_an_uncalibrated_emg_switch(tmp_path):
    """EMG needs a per-person calibration; without a profile the switch stays off."""
    parts = build_parts(PartsRequest(fs=FS, emg=True,
                                     calibration_file=str(tmp_path / "missing.json")))
    assert parts.detectors == []


def test_built_pipeline_is_usable_on_a_synthetic_block():
    """The assembled real parts run end to end on a block without raising."""
    parts = build_parts(PartsRequest(fs=FS, double_blink=True, jaw_clench=True,
                                     with_ledger=True, channels=CH))
    rng = np.random.default_rng(0)
    block = SampleBlock(data=rng.normal(0, 1, (1, 100)), fs=FS, channels=CH, t0=0.0)
    result = BiosignalPipeline(parts).process(block)
    assert result.status.blocks == 1
