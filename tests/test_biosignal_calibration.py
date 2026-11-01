"""Tests for ``yazses.biosignal.calibration``: the guided per-user calibration.

All data is synthetic (fixed seeds), the clocks are injected, and every file goes under
``tmp_path`` -- nothing here touches the real data directory.
"""

from __future__ import annotations

import json
import logging
import stat
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from yazses.biosignal import calibration as cal
from yazses.biosignal.calibration import (
    PROFILE_FILENAME,
    SCHEMA_VERSION,
    TERMINAL,
    CalibrationConfig,
    CalibrationError,
    CalibrationPhase,
    CalibrationProfile,
    CalibrationSession,
    IssueCode,
    default_profile_path,
    load_profile,
    profile_is_stale,
    profile_matches,
    save_profile,
)
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

FS = 250.0
EMG = ChannelInfo("emg", SignalKind.EMG)
EOG = ChannelInfo("eog", SignalKind.EOG)
EEG = ChannelInfo("eeg", SignalKind.EEG)
ALL3 = (EMG, EOG, EEG)
NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)

# Default config: settle 1 s is discarded, then relax 5 s / squeeze 4 s / blink 10 s / clench 8 s.
RELAX_S = 1.0 + 5.0
SQUEEZE_S = 1.0 + 4.0
BLINK_S = 1.0 + 10.0
CLENCH_S = 1.0 + 8.0


# --------------------------------------------------------------------------- helpers


class Stream:
    """A seeded synthetic 3-channel (emg, eog, eeg) signal generator."""

    def __init__(self, seed: int = 1) -> None:
        self.rng = np.random.default_rng(seed)

    def phase(
        self,
        seconds: float,
        emg_sigma: float = 2.0,
        *,
        blinks: tuple[float, ...] = (),
        clenches: tuple[float, ...] = (),
        burst_at: tuple[float, float] | None = None,
        burst_sigma: float = 40.0,
    ) -> np.ndarray:
        n = int(round(seconds * FS))
        t = np.arange(n) / FS
        data = np.zeros((3, n))
        data[0] = self.rng.normal(0.0, emg_sigma, n)
        data[1] = self.rng.normal(0.0, 1.0, n)
        data[2] = self.rng.normal(0.0, 1.0, n)
        for c in blinks:
            data[1] += 150.0 * np.exp(-0.5 * ((t - c) / 0.06) ** 2)
        for c in clenches:
            m = (t > c) & (t < c + 0.8)
            data[2][m] += self.rng.normal(0.0, 30.0, int(m.sum()))
        if burst_at is not None:
            m = (t >= burst_at[0]) & (t < burst_at[1])
            data[0][m] += self.rng.normal(0.0, burst_sigma, int(m.sum()))
        return data


def block(data: np.ndarray, channels=ALL3, fs: float = FS) -> SampleBlock:
    return SampleBlock(np.asarray(data, dtype=float), fs, tuple(channels))


def emg_block(data: np.ndarray) -> SampleBlock:
    return block(data[:1], (EMG,))


def good_relax(s: Stream) -> np.ndarray:
    return s.phase(RELAX_S, 2.0)


def good_light(s: Stream) -> np.ndarray:
    return s.phase(SQUEEZE_S, 6.0)


def good_hard(s: Stream) -> np.ndarray:
    return s.phase(SQUEEZE_S, 14.0)


def make_session(**kwargs) -> CalibrationSession:
    kwargs.setdefault("wall_clock", lambda: NOW)
    return CalibrationSession("testboard", ALL3, FS, **kwargs)


def run_squeeze_session(seed: int = 1) -> CalibrationSession:
    """A session driven through RELAX -> LIGHT -> HARD with clean data, now DONE."""
    s = Stream(seed)
    sess = make_session(include_squeeze=True)
    for data in (good_relax(s), good_light(s), good_hard(s)):
        assert sess.feed(block(data)) is None
    assert sess.phase is CalibrationPhase.DONE
    return sess


def full_stream(seed: int = 1) -> np.ndarray:
    """All five phases back to back, as one array."""
    s = Stream(seed)
    return np.concatenate(
        [
            good_relax(s),
            good_light(s),
            good_hard(s),
            s.phase(BLINK_S, 2.0, blinks=(3.0, 5.0, 7.0)),
            s.phase(CLENCH_S, 2.0, clenches=(2.0, 4.0, 6.0)),
        ],
        axis=1,
    )


def make_profile(**overrides) -> CalibrationProfile:
    base = {
        "created_at": NOW.isoformat(timespec="seconds"),
        "board_id": "testboard",
        "channels": ("emg", "eog"),
        "channel_kinds": ("emg", "eog"),
        "fs": FS,
        "baseline_rms": 2.0,
        "noise_floor": 2.4,
        "mvc_rms": 14.0,
        "light_rms": 6.0,
        "blink_amplitude": 150.0,
        "clench_power": 1700.0,
        "thresholds": {"light": 4.5, "hard": 9.5, "onset": 4.5, "offset": 3.3, "blink": 75.0},
        "phases": ("relax", "squeeze_light", "squeeze_hard"),
    }
    base.update(overrides)
    return CalibrationProfile(**base)


# --------------------------------------------------------------------------- happy path


def test_squeeze_session_produces_ordered_thresholds() -> None:
    """RELAX -> LIGHT -> HARD yields a profile whose thresholds are correctly ordered."""
    profile = run_squeeze_session().result()
    th = profile.thresholds
    assert profile.noise_floor >= profile.baseline_rms > 0
    assert profile.noise_floor < th["onset"]
    assert th["onset"] <= th["light"] < th["hard"]
    assert th["offset"] < th["onset"]
    assert th["offset"] > profile.baseline_rms
    assert profile.light_rms is not None and profile.mvc_rms is not None
    assert profile.light_rms < profile.mvc_rms
    assert profile.phases == ("relax", "squeeze_light", "squeeze_hard")
    assert "blink" not in th and "clench" not in th


def test_profile_records_identity_and_wall_clock() -> None:
    """The profile carries board, channels, kinds, fs and the injected UTC timestamp."""
    profile = run_squeeze_session().result()
    assert profile.board_id == "testboard"
    assert profile.channels == ("emg", "eog", "eeg")
    assert profile.channel_kinds == ("emg", "eog", "eeg")
    assert profile.fs == FS
    assert profile.created_at == NOW.isoformat(timespec="seconds")
    assert profile.schema_version == SCHEMA_VERSION


def test_naive_wall_clock_is_taken_as_utc() -> None:
    """A naive injected wall clock is stamped as UTC rather than raising."""
    s = Stream(2)
    sess = make_session(include_squeeze=True, wall_clock=lambda: datetime(2026, 1, 2, 3, 4, 5))
    for data in (good_relax(s), good_light(s), good_hard(s)):
        sess.feed(block(data))
    assert sess.result().created_at == "2026-01-02T03:04:05+00:00"


def test_full_session_with_blink_and_clench() -> None:
    """All five phases run and fill every optional measurement and threshold."""
    sess = make_session(include_squeeze=True, include_blink=True, include_clench=True)
    assert [p.value for p in sess.phases] == [
        "relax", "squeeze_light", "squeeze_hard", "blink_x3", "clench_x3",
    ]
    assert sess.feed(block(full_stream())) is None
    assert sess.phase is CalibrationPhase.DONE and sess.finished
    profile = sess.result()
    assert profile.blink_amplitude and profile.blink_amplitude > 50
    assert profile.clench_power and profile.clench_power > 0
    th = profile.thresholds
    assert 0 < th["blink"] < profile.blink_amplitude
    assert 0 < th["clench"] < profile.clench_power
    assert profile.phases[-2:] == ("blink_x3", "clench_x3")


def test_result_is_independent_of_block_chunking() -> None:
    """Counting is in samples: one big block and many small ones calibrate identically."""
    data = full_stream(3)
    whole = make_session(include_squeeze=True, include_blink=True, include_clench=True)
    whole.feed(block(data))
    chunked = make_session(include_squeeze=True, include_blink=True, include_clench=True)
    for start in range(0, data.shape[1], 997):  # prime-sized, straddles phase boundaries
        assert chunked.feed(block(data[:, start : start + 997])) is None
    assert chunked.phase is CalibrationPhase.DONE
    assert chunked.result().to_dict() == whole.result().to_dict()


def test_block_with_reordered_channels_is_accepted() -> None:
    """Blocks naming the same channels in another order are reordered, not rejected."""
    s = Stream(4)
    sess = make_session(include_squeeze=True)
    order = [2, 0, 1]
    shuffled = (EEG, EMG, EOG)
    for data in (good_relax(s), good_light(s), good_hard(s)):
        assert sess.feed(block(data[order], shuffled)) is None
    assert sess.phase is CalibrationPhase.DONE
    reference = run_squeeze_session(4).result()
    assert sess.result().thresholds == reference.thresholds


def test_progress_and_prompt_track_phases() -> None:
    """Progress fractions stay in [0, 1], rise monotonically, and prompts differ by phase."""
    s = Stream(5)
    sess = make_session(include_squeeze=True)
    prompts = {sess.prompt()}
    seen = [sess.progress().overall_fraction]
    for data in (good_relax(s), good_light(s), good_hard(s)):
        half = data.shape[1] // 2
        sess.feed(block(data[:, :half]))
        mid = sess.progress()
        assert 0.0 < mid.phase_fraction < 1.0
        assert 0.0 <= mid.overall_fraction <= 1.0
        seen.append(mid.overall_fraction)
        sess.feed(block(data[:, half:]))
        seen.append(sess.progress().overall_fraction)
        prompts.add(sess.prompt())
    assert seen == sorted(seen)
    assert len(prompts) == 4  # relax, light, hard, done
    final = sess.progress()
    assert final.phase is CalibrationPhase.DONE
    assert final.phase_fraction == final.overall_fraction == 1.0
    assert sess.phase in TERMINAL


def test_default_plan_follows_channel_kinds() -> None:
    """With include_squeeze unset, squeeze phases run only when an EMG channel exists."""
    with_emg = CalibrationSession("b", (EMG,), FS)
    assert with_emg.phases == (
        CalibrationPhase.RELAX, CalibrationPhase.SQUEEZE_LIGHT, CalibrationPhase.SQUEEZE_HARD,
    )
    eeg_only = CalibrationSession("b", (EEG,), FS)
    assert eeg_only.phases == (CalibrationPhase.RELAX,)


# --------------------------------------------------------------------------- rejection


def assert_plain_language(issue) -> None:
    """The message is for a person: a sentence, with no machine identifiers in it."""
    assert issue.message.endswith((".", "!"))
    assert len(issue.message.split()) >= 5
    assert "_" not in issue.message
    for code in IssueCode:
        assert code.value not in issue.message


def test_noisy_relax_is_rejected_and_phase_restarts() -> None:
    """A burst during rest -> NOT_QUIET; the phase restarts and a quiet retry passes."""
    s = Stream(6)
    sess = make_session(include_squeeze=True)
    issue = sess.feed(block(s.phase(RELAX_S, 2.0, burst_at=(3.0, 4.5))))
    assert issue is not None
    assert issue.code is IssueCode.NOT_QUIET
    assert issue.phase is CalibrationPhase.RELAX
    assert issue.attempt == 1 and not issue.fatal
    assert_plain_language(issue)
    assert sess.phase is CalibrationPhase.RELAX
    assert sess.last_issue is issue
    assert sess.prompt().startswith(issue.message)  # the reason leads the retry prompt
    assert sess.progress().phase_fraction == 0.0  # buffer was dropped

    assert sess.feed(block(good_relax(s))) is None
    assert sess.phase is CalibrationPhase.SQUEEZE_LIGHT
    assert sess.last_issue is None  # cleared once the phase passed


def test_flat_signal_is_no_signal() -> None:
    """A dead (all-zero) electrode is NO_SIGNAL, not 'quiet but fine'."""
    sess = make_session(include_squeeze=True)
    issue = sess.feed(block(np.zeros((3, int(RELAX_S * FS)))))
    assert issue is not None and issue.code is IssueCode.NO_SIGNAL
    assert_plain_language(issue)


def test_too_weak_light_squeeze_is_rejected_then_retry_passes() -> None:
    """A squeeze barely above rest -> SQUEEZE_TOO_WEAK; the same phase is retried."""
    s = Stream(7)
    sess = make_session(include_squeeze=True)
    assert sess.feed(block(good_relax(s))) is None
    issue = sess.feed(block(s.phase(SQUEEZE_S, 2.5)))
    assert issue is not None
    assert issue.code is IssueCode.SQUEEZE_TOO_WEAK
    assert issue.phase is CalibrationPhase.SQUEEZE_LIGHT
    assert_plain_language(issue)
    assert sess.phase is CalibrationPhase.SQUEEZE_LIGHT
    assert sess.feed(block(good_light(s))) is None
    assert sess.phase is CalibrationPhase.SQUEEZE_HARD


def test_too_weak_hard_squeeze_is_rejected() -> None:
    """The weak-squeeze check also guards the firm squeeze phase."""
    s = Stream(8)
    sess = make_session(include_squeeze=True)
    sess.feed(block(good_relax(s)))
    sess.feed(block(good_light(s)))
    issue = sess.feed(block(s.phase(SQUEEZE_S, 2.5)))
    assert issue is not None and issue.code is IssueCode.SQUEEZE_TOO_WEAK
    assert issue.phase is CalibrationPhase.SQUEEZE_HARD
    assert sess.phase is CalibrationPhase.SQUEEZE_HARD


def test_brief_squeeze_is_rejected() -> None:
    """A squeeze held for well under a second -> SQUEEZE_TOO_BRIEF."""
    s = Stream(9)
    sess = make_session(include_squeeze=True)
    sess.feed(block(good_relax(s)))
    data = s.phase(SQUEEZE_S, 2.0, burst_at=(2.0, 2.5), burst_sigma=40.0)
    issue = sess.feed(block(data))
    assert issue is not None and issue.code is IssueCode.SQUEEZE_TOO_BRIEF
    assert sess.phase is CalibrationPhase.SQUEEZE_LIGHT


def test_hard_not_harder_than_light_is_rejected() -> None:
    """A 'firm' squeeze no stronger than the gentle one -> HARD_NOT_HARDER, HARD restarts."""
    s = Stream(10)
    sess = make_session(include_squeeze=True)
    sess.feed(block(good_relax(s)))
    assert sess.feed(block(good_light(s))) is None
    issue = sess.feed(block(good_light(s)))  # same strength again
    assert issue is not None
    assert issue.code is IssueCode.HARD_NOT_HARDER
    assert issue.phase is CalibrationPhase.SQUEEZE_HARD
    assert_plain_language(issue)
    assert sess.phase is CalibrationPhase.SQUEEZE_HARD
    assert sess.feed(block(good_hard(s))) is None
    assert sess.phase is CalibrationPhase.DONE


def test_nan_samples_are_rejected() -> None:
    """Non-finite samples are BAD_SAMPLES and are not silently believed."""
    s = Stream(11)
    sess = make_session(include_squeeze=True)
    data = good_relax(s)
    data[0, 10] = np.nan
    issue = sess.feed(block(data))
    assert issue is not None and issue.code is IssueCode.BAD_SAMPLES
    assert sess.phase is CalibrationPhase.RELAX


def test_blinks_not_found_and_too_many_blinks() -> None:
    """No blinks and a flurry of blinks are different, plain-language rejections."""
    s = Stream(12)
    sess = make_session(include_squeeze=False, include_blink=True)
    assert sess.feed(block(good_relax(s))) is None
    assert sess.phase is CalibrationPhase.BLINK_X3
    none = sess.feed(block(s.phase(BLINK_S, 2.0)))
    assert none is not None and none.code is IssueCode.BLINKS_NOT_FOUND
    assert_plain_language(none)
    many = sess.feed(block(s.phase(BLINK_S, 2.0, blinks=tuple(1.5 + 1.2 * i for i in range(8)))))
    assert many is not None and many.code is IssueCode.TOO_MANY_BLINKS
    assert many.attempt == 2
    assert sess.feed(block(s.phase(BLINK_S, 2.0, blinks=(3.0, 5.0, 7.0)))) is None
    assert sess.phase is CalibrationPhase.DONE


def test_clenches_not_found() -> None:
    """A clench phase with no jaw activity is CLENCHES_NOT_FOUND."""
    s = Stream(13)
    sess = make_session(include_squeeze=False, include_clench=True)
    assert sess.feed(block(good_relax(s))) is None
    issue = sess.feed(block(s.phase(CLENCH_S, 2.0)))
    assert issue is not None and issue.code is IssueCode.CLENCHES_NOT_FOUND
    assert sess.phase is CalibrationPhase.CLENCH_X3


# --------------------------------------------------------------------------- retry budget


def test_three_failed_attempts_are_fatal() -> None:
    """The third rejection of one phase ends the session as FAILED with a fatal issue."""
    s = Stream(14)
    sess = make_session(include_squeeze=True)
    issues = [
        sess.feed(block(s.phase(RELAX_S, 2.0, burst_at=(3.0, 4.5)))) for _ in range(3)
    ]
    assert [i.attempt for i in issues] == [1, 2, 3]
    assert [i.fatal for i in issues] == [False, False, True]
    assert sess.phase is CalibrationPhase.FAILED
    assert sess.finished and sess.phase in TERMINAL
    assert "electrode" in issues[-1].message.lower()
    assert "electrode" in sess.prompt().lower()
    with pytest.raises(CalibrationError):
        sess.result()
    # Further data after the end is ignored, not an error.
    assert sess.feed(block(good_relax(s))) is None
    assert sess.phase is CalibrationPhase.FAILED


def test_attempt_budget_is_per_phase_and_configurable() -> None:
    """max_attempts comes from the config; a phase's budget does not leak to the next."""
    s = Stream(15)
    sess = make_session(include_squeeze=True, config=CalibrationConfig(max_attempts=2))
    first = sess.feed(block(s.phase(RELAX_S, 2.0, burst_at=(3.0, 4.5))))
    assert first is not None and not first.fatal
    assert sess.feed(block(good_relax(s))) is None  # passes on the 2nd try
    weak = sess.feed(block(s.phase(SQUEEZE_S, 2.5)))
    assert weak is not None and weak.attempt == 1 and not weak.fatal
    weak2 = sess.feed(block(s.phase(SQUEEZE_S, 2.5)))
    assert weak2 is not None and weak2.fatal
    assert sess.phase is CalibrationPhase.FAILED


def test_stall_detection_with_injected_clock() -> None:
    """tick() (and an empty feed) report a stalled source only after stall_timeout_s."""
    now = [100.0]
    sess = make_session(include_squeeze=True, clock=lambda: now[0])
    assert sess.tick() is None
    now[0] += 4.9
    assert sess.feed(None) is None
    now[0] += 0.2
    issue = sess.feed(None)
    assert issue is not None and issue.code is IssueCode.STALLED
    assert issue.attempt == 1
    # The stall timer was reset by the report: no immediate second complaint.
    assert sess.tick() is None


def test_data_resets_stall_timer() -> None:
    """Receiving a block counts as a sign of life."""
    now = [0.0]
    s = Stream(16)
    sess = make_session(include_squeeze=True, clock=lambda: now[0])
    now[0] = 4.0
    sess.feed(block(good_relax(s)[:, :100]))
    now[0] = 8.0  # 4 s since the last block, under the 5 s timeout
    assert sess.tick() is None


# --------------------------------------------------------------------------- result / abort


def test_result_before_done_raises() -> None:
    """result() on an unfinished session raises CalibrationError naming the phase."""
    sess = make_session(include_squeeze=True)
    with pytest.raises(CalibrationError, match="relax"):
        sess.result()
    sess.feed(block(good_relax(Stream(17))))
    with pytest.raises(CalibrationError):
        sess.result()


def test_abort_ends_session_and_drops_data() -> None:
    """abort() -> ABORTED, buffers dropped, result() raises, later feeds are inert."""
    s = Stream(18)
    sess = make_session(include_squeeze=True)
    sess.feed(block(good_relax(s)[:, :500]))
    sess.abort()
    assert sess.phase is CalibrationPhase.ABORTED and sess.finished
    assert sess.progress().phase_fraction == 0.0
    assert sess.prompt() == "Calibration cancelled."
    with pytest.raises(CalibrationError):
        sess.result()
    assert sess.feed(block(good_relax(s))) is None
    assert sess.phase is CalibrationPhase.ABORTED


def test_abort_after_done_keeps_the_profile() -> None:
    """abort() on a finished session does not destroy the result."""
    sess = run_squeeze_session()
    sess.abort()
    assert sess.phase is CalibrationPhase.DONE
    assert sess.result().thresholds


# --------------------------------------------------------------------------- feed validation


def test_fs_mismatch_raises_value_error() -> None:
    """A block at a different sampling rate is a programming error."""
    sess = CalibrationSession("b", (EMG,), FS)
    wrong = SampleBlock(np.zeros((1, 100)), FS * 2, (EMG,))
    with pytest.raises(ValueError, match="fs"):
        sess.feed(wrong)


def test_fs_within_tolerance_is_accepted() -> None:
    """The 1 % sampling-rate tolerance applies to blocks too."""
    sess = CalibrationSession("b", (EMG,), FS)
    close = SampleBlock(np.ones((1, 10)) * np.arange(10), FS * 1.005, (EMG,))
    assert sess.feed(close) is None


def test_channel_mismatch_raises_value_error() -> None:
    """Different channel names (or a different count) are a programming error."""
    sess = CalibrationSession("b", (EMG,), FS)
    other = SampleBlock(np.zeros((1, 100)), FS, (ChannelInfo("other", SignalKind.EMG),))
    with pytest.raises(ValueError, match="channels"):
        sess.feed(other)
    two = SampleBlock(np.zeros((2, 100)), FS, (EMG, EOG))
    with pytest.raises(ValueError, match="channels"):
        sess.feed(two)


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"fs": 0.0}, "fs"),
        ({"fs": float("nan")}, "fs"),
        ({"channels": ()}, "channel"),
        ({"channels": (EMG, EMG)}, "unique"),
        ({"channels": (EEG,), "include_squeeze": True}, "EMG"),
        ({"channels": (EMG,), "include_blink": True}, "EOG or EEG"),
        ({"channels": (EOG,), "include_clench": True}, "EEG or EMG"),
        ({"config": CalibrationConfig(max_attempts=0)}, "max_attempts"),
    ],
)
def test_constructor_validation(kwargs, match) -> None:
    """Impossible session set-ups fail at construction with a clear message."""
    params = {"board_id": "b", "channels": (EMG,), "fs": FS}
    params.update(kwargs)
    with pytest.raises(ValueError, match=match):
        CalibrationSession(
            params.pop("board_id"), params.pop("channels"), params.pop("fs"), **params
        )


# --------------------------------------------------------------------------- profile


def test_profile_repr_and_summary_redact_amplitudes() -> None:
    """repr() and summary() carry identity only, never a measured amplitude."""
    profile = make_profile(baseline_rms=123.456789, mvc_rms=987.654321)
    for text in (repr(profile), profile.summary()):
        assert "testboard" in text
        for secret in ("123.456789", "987.654321", "baseline_rms", "mvc_rms", "thresholds"):
            assert secret not in text
    assert "redacted" in repr(profile)
    assert str(profile) == repr(profile)
    assert f"{profile!r}" == repr(profile)


def test_to_dict_from_dict_round_trip() -> None:
    """from_dict(to_dict(p)) == p, and the dict is plain JSON."""
    profile = run_squeeze_session().result()
    data = profile.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert isinstance(data["channels"], list) and isinstance(data["phases"], list)
    assert CalibrationProfile.from_dict(data) == profile


def test_round_trip_with_missing_optional_measurements() -> None:
    """Optional measurements stay None through a round trip."""
    profile = make_profile(
        mvc_rms=None, light_rms=None, blink_amplitude=None, clench_power=None, thresholds={}
    )
    again = CalibrationProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
    assert again == profile and again.mvc_rms is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2},
        {"schema_version": True},
        {"schema_version": None},
        {"created_at": "not a time"},
        {"created_at": 5},
        {"board_id": None},
        {"channels": []},
        {"channels": ["a"], "channel_kinds": ["emg", "eog"]},
        {"channel_kinds": ["emg", "thought"]},
        {"channels": "emg"},
        {"fs": 0},
        {"fs": -250.0},
        {"fs": float("nan")},
        {"fs": "250"},
        {"fs": True},
        {"baseline_rms": -1.0},
        {"mvc_rms": 0},
        {"thresholds": [1, 2]},
        {"thresholds": {"light": -1.0}},
        {"thresholds": {"light": float("inf")}},
        {"phases": "relax"},
    ],
)
def test_from_dict_rejects_malformed_values(mutation) -> None:
    """Anything malformed raises ValueError rather than building a bogus profile."""
    data = make_profile().to_dict()
    data.update(mutation)
    with pytest.raises(ValueError):
        CalibrationProfile.from_dict(data)


def test_default_profile_path_uses_explicit_data_dir(tmp_path) -> None:
    """With an explicit directory the lookup never consults the real data dir."""
    assert default_profile_path(data_dir=tmp_path) == tmp_path / PROFILE_FILENAME
    assert default_profile_path(str(tmp_path)) == tmp_path / PROFILE_FILENAME


# --------------------------------------------------------------------------- persistence


def test_save_load_round_trip(tmp_path) -> None:
    """save_profile then load_profile returns an equal profile (creating the directory)."""
    profile = run_squeeze_session().result()
    path = default_profile_path(data_dir=tmp_path / "nested" / "dir")
    save_profile(profile, path)
    assert path.is_file()
    assert load_profile(path) == profile
    assert load_profile(str(path)) == profile  # str paths work too


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_saved_profile_is_owner_only(tmp_path) -> None:
    """The file is mode 0o600 regardless of umask (it is biometric-adjacent)."""
    import os

    path = default_profile_path(data_dir=tmp_path)
    old = os.umask(0o000)
    try:
        save_profile(make_profile(), path)
    finally:
        os.umask(old)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    save_profile(make_profile(board_id="again"), path)  # overwrite keeps the mode
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path) -> None:
    """After a save only the target remains in the directory."""
    path = default_profile_path(data_dir=tmp_path)
    save_profile(make_profile(), path)
    save_profile(make_profile(board_id="second"), path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [PROFILE_FILENAME]
    loaded = load_profile(path)
    assert loaded is not None and loaded.board_id == "second"


def test_failed_save_keeps_old_profile_and_cleans_up(tmp_path, monkeypatch) -> None:
    """If the final rename fails the old file is intact and no temp file is left."""
    path = default_profile_path(data_dir=tmp_path)
    original = make_profile()
    save_profile(original, path)

    def boom(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr(cal.os, "replace", boom)
    with pytest.raises(OSError, match="disk on fire"):
        save_profile(make_profile(board_id="new"), path)
    monkeypatch.undo()
    assert sorted(p.name for p in tmp_path.iterdir()) == [PROFILE_FILENAME]
    assert load_profile(path) == original


def test_load_missing_file_returns_none(tmp_path) -> None:
    """The normal first-run case: no file, no exception."""
    assert load_profile(tmp_path / "nope.json") is None
    assert load_profile(tmp_path) is None  # a directory is not a profile


def test_load_corrupt_json_returns_none(tmp_path, caplog) -> None:
    """Garbage on disk -> None plus a warning that does not echo the contents."""
    path = tmp_path / PROFILE_FILENAME
    path.write_text('{"baseline_rms": 4242.4242, oops', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="yazses.biosignal.calibration"):
        assert load_profile(path) is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert "4242" not in caplog.text


def test_load_non_utf8_and_non_object_return_none(tmp_path) -> None:
    """Binary junk and a JSON list are both just 'no usable profile'."""
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00\x80garbage")
    assert load_profile(binary) is None
    as_list = tmp_path / "list.json"
    as_list.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_profile(as_list) is None


def test_load_wrong_schema_version_returns_none(tmp_path) -> None:
    """A file from a different layout version is ignored (the user recalibrates)."""
    path = tmp_path / PROFILE_FILENAME
    data = make_profile().to_dict()
    data["schema_version"] = SCHEMA_VERSION + 1
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_profile(path) is None
    del data["schema_version"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_profile(path) is None


def test_load_implausible_values_returns_none(tmp_path) -> None:
    """A syntactically valid file with a negative amplitude is not trusted."""
    path = tmp_path / PROFILE_FILENAME
    data = make_profile().to_dict()
    data["baseline_rms"] = -3.0
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_profile(path) is None


def test_load_oversized_file_returns_none(tmp_path) -> None:
    """A multi-megabyte file is not ours and is not even parsed."""
    path = tmp_path / PROFILE_FILENAME
    path.write_text(" " * ((1 << 20) + 1), encoding="utf-8")
    assert load_profile(path) is None


def test_load_never_raises_on_unreadable_path(tmp_path) -> None:
    """A path whose parent is a file (OSError territory) still returns None."""
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert load_profile(blocker / "child.json") is None


# --------------------------------------------------------------------------- staleness


def test_profile_is_stale_by_age() -> None:
    """Older than max_age_days is stale; younger is not; the limit is configurable."""
    old = make_profile(created_at=(NOW - timedelta(days=31)).isoformat())
    recent = make_profile(created_at=(NOW - timedelta(days=29)).isoformat())
    assert profile_is_stale(old, NOW)
    assert not profile_is_stale(recent, NOW)
    assert profile_is_stale(recent, NOW, max_age_days=5)
    assert not profile_is_stale(old, NOW, max_age_days=40)
    assert not profile_is_stale(make_profile(created_at=NOW.isoformat()), NOW)


def test_profile_is_stale_when_timestamp_unparsable() -> None:
    """A timestamp that cannot be trusted counts as stale."""
    for bad in ("", "yesterday-ish", "2026-13-45T99:00:00"):
        assert profile_is_stale(make_profile(created_at=bad), NOW)


def test_profile_is_stale_when_future_dated() -> None:
    """A far-future stamp is stale; a small clock skew is tolerated."""
    far = make_profile(created_at=(NOW + timedelta(days=2)).isoformat())
    skew = make_profile(created_at=(NOW + timedelta(minutes=30)).isoformat())
    assert profile_is_stale(far, NOW)
    assert not profile_is_stale(skew, NOW)


def test_profile_is_stale_with_naive_now_assumes_utc() -> None:
    """A naive ``now`` is read as UTC, giving the same answer as the aware one."""
    naive_now = NOW.replace(tzinfo=None)
    fresh = make_profile(created_at=(NOW - timedelta(days=1)).isoformat())
    old = make_profile(created_at=(NOW - timedelta(days=31)).isoformat())
    assert not profile_is_stale(fresh, naive_now)
    assert profile_is_stale(old, naive_now)


def test_profile_is_stale_with_non_utc_offsets() -> None:
    """Timestamps with an offset are compared as instants, not as wall-clock strings."""
    plus5 = timezone_stamp(NOW - timedelta(days=29), hours=5)
    assert not profile_is_stale(make_profile(created_at=plus5), NOW)
    plus5_old = timezone_stamp(NOW - timedelta(days=31), hours=5)
    assert profile_is_stale(make_profile(created_at=plus5_old), NOW)


def timezone_stamp(instant: datetime, hours: int) -> str:
    from datetime import timezone

    return instant.astimezone(timezone(timedelta(hours=hours))).isoformat()


# --------------------------------------------------------------------------- matching


def test_profile_matches_ignores_channel_order() -> None:
    """Same board, channels (any order) and fs match."""
    profile = make_profile()
    assert profile_matches(profile, "testboard", ["emg", "eog"], FS)
    assert profile_matches(profile, "testboard", ["eog", "emg"], FS)
    assert profile_matches(profile, "testboard", [EOG, EMG], FS)  # ChannelInfo accepted


def test_profile_matches_rejects_different_identity() -> None:
    """A different board, a different/extra/missing channel never matches."""
    profile = make_profile()
    assert not profile_matches(profile, "otherboard", ["emg", "eog"], FS)
    assert not profile_matches(profile, "testboard", ["emg"], FS)
    assert not profile_matches(profile, "testboard", ["emg", "eog", "eeg"], FS)
    assert not profile_matches(profile, "testboard", ["emg", "ecg"], FS)
    assert not profile_matches(profile, "testboard", ["emg", "emg"], FS)


def test_profile_matches_fs_tolerance_is_one_percent() -> None:
    """Within 1 % of the stored rate matches; 2 % off does not; bad rates never do."""
    profile = make_profile()
    assert profile_matches(profile, "testboard", ["emg", "eog"], FS * 1.009)
    assert profile_matches(profile, "testboard", ["emg", "eog"], FS * 0.991)
    assert not profile_matches(profile, "testboard", ["emg", "eog"], FS * 1.02)
    assert not profile_matches(profile, "testboard", ["emg", "eog"], FS * 0.98)
    for bad in (0.0, -FS, float("nan"), float("inf")):
        assert not profile_matches(profile, "testboard", ["emg", "eog"], bad)


def test_profile_from_session_matches_its_own_setup() -> None:
    """The profile a session produces matches the setup it was calibrated on."""
    profile = run_squeeze_session().result()
    assert profile_matches(profile, "testboard", ALL3, FS)
    assert not profile_is_stale(profile, NOW + timedelta(days=1))
    assert profile_is_stale(replace(profile, created_at="garbage"), NOW)
