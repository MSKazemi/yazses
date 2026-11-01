"""Tests for ``yazses.biosignal.edf``: EDF / EDF+ / BDF / BDF+ reading and writing.

Two independent sides meet here. ``_edf_bytes`` below builds files byte by byte straight
from the field table in the EDF spec (https://www.edfplus.info/specs/edf.html) — it shares
no code with the module — so the reader is checked against the spec, not against the
writer. The writer is then checked by reading its output back and by inspecting the raw
header bytes. All fixtures are synthetic and live in ``tmp_path``.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from yazses.biosignal.edf import (
    DEFAULT_EVENT_MAP,
    Annotation,
    annotation_kind,
    annotations_to_events,
    guess_kind,
    load_edf,
    read_edf_header,
    unit_scale,
    write_edf,
)
from yazses.biosignal.evaluate import evaluate
from yazses.biosignal.sources import SyntheticSource, iter_blocks
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")

EDF_V = b"0       "
BDF_V = b"\xffBIOSEMI"


# ------------------------------------------------------------------------------------
# an independent, spec-table EDF builder
# ------------------------------------------------------------------------------------


def _sig(label: str, spr: int, *, dim: str = "uV", pmin: str = "-1000", pmax: str = "1000",
         dmin: str = "-32768", dmax: str = "32767", transducer: str = "") -> dict:
    return dict(label=label, spr=spr, dim=dim, pmin=pmin, pmax=pmax, dmin=dmin, dmax=dmax,
                transducer=transducer)


def _ann_sig(spr: int, *, bdf: bool = False) -> dict:
    lo, hi = ("-8388608", "8388607") if bdf else ("-32768", "32767")
    return _sig("BDF Annotations" if bdf else "EDF Annotations", spr, dim="", pmin="-1",
                pmax="1", dmin=lo, dmax=hi)


def _f(value: str | bytes, width: int) -> bytes:
    raw = value if isinstance(value, bytes) else value.encode("latin-1")
    assert len(raw) <= width
    return raw.ljust(width, b" ")


def _edf_bytes(signals: list[dict], records: list[list[bytes]], *, version: bytes = EDF_V,
               reserved: str = "", n_records: str | None = None, duration: str = "1",
               patient: str | bytes = "X X X X", header_bytes: str | None = None) -> bytes:
    ns = len(signals)
    head = version + _f(patient, 80) + _f("Startdate X X X X", 80) + _f("01.01.85", 8)
    head += _f("00.00.00", 8) + _f(header_bytes or str(256 * (ns + 1)), 8)
    head += _f(reserved, 44) + _f(n_records if n_records is not None else str(len(records)), 8)
    head += _f(duration, 8) + _f(str(ns), 4)
    for key, width in (("label", 16), ("transducer", 80), ("dim", 8), ("pmin", 8),
                       ("pmax", 8), ("dmin", 8), ("dmax", 8), (None, 80), ("spr", 8),
                       (None, 32)):
        for s in signals:
            head += _f(str(s[key]) if key else "", width)
    assert len(head) == 256 * (ns + 1)
    return head + b"".join(b"".join(rec) for rec in records)


def _i16(values) -> bytes:
    return np.asarray(values, dtype="<i2").tobytes()


def _i24(values) -> bytes:
    out = bytearray()
    for v in values:
        out += int(v).to_bytes(3, "little", signed=True)
    return bytes(out)


def _tal_bytes(*tals: bytes, size: int) -> bytes:
    blob = b"".join(tals)
    assert len(blob) <= size
    return blob.ljust(size, b"\x00")


def _put(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _blocks(data: np.ndarray, fs: float, channels, *, t0: float = 0.0, step: int = 50):
    return [SampleBlock(data=data[:, i:i + step], fs=fs, channels=channels,
                        t0=t0 + i / fs) for i in range(0, data.shape[1], step)]


# ------------------------------------------------------------------------------------
# reading — scaling, sample formats, selection
# ------------------------------------------------------------------------------------


def test_plain_edf_scaling_follows_the_spec_formula(tmp_path):
    # gain = (pmax - pmin) / (dmax - dmin); phys = (dig - dmin) * gain + pmin
    sig = _sig("Fp1", 4, pmin="-100", pmax="100", dmin="-2048", dmax="2047")
    digital = [-2048, 0, 2047, 1000]
    p = _put(tmp_path, "a.edf", _edf_bytes([sig], [[_i16(digital)]]))
    rec = load_edf(p)
    gain = 200 / 4095
    expected = [(d + 2048) * gain - 100 for d in digital]
    np.testing.assert_allclose(rec.data[0], expected, rtol=0, atol=1e-12)
    assert rec.fs == 4.0
    assert rec.channels == (ChannelInfo("Fp1", SignalKind.EEG),)
    assert rec.header.variant == "EDF"
    assert rec.events == () and rec.annotations == ()
    assert rec.t0 == 0.0


def test_samples_are_little_endian_twos_complement_across_records(tmp_path):
    sig = _sig("C3", 2, pmin="-32768", pmax="32767")      # gain 1 -> phys == digital
    records = [[_i16([1, -1])], [_i16([-32768, 32767])], [_i16([256, -256])]]
    rec = load_edf(_put(tmp_path, "le.edf", _edf_bytes([sig], records)))
    np.testing.assert_allclose(rec.data[0], [1, -1, -32768, 32767, 256, -256])


def test_bdf_24bit_samples_decode_sign_and_byte_order(tmp_path):
    sig = _sig("A1", 4, pmin="-8388608", pmax="8388607", dmin="-8388608", dmax="8388607")
    values = [-8388608, -1, 8388607, 0x123456]
    p = _put(tmp_path, "b.bdf", _edf_bytes([sig], [[_i24(values)]], version=BDF_V,
                                          reserved="24BIT"))
    rec = load_edf(p)
    np.testing.assert_allclose(rec.data[0], values)
    assert rec.header.variant == "BDF"
    assert rec.header.bytes_per_sample == 3


def test_bdf_status_channel_is_left_out(tmp_path):
    eeg = _sig("Fp1", 2, dmin="-8388608", dmax="8388607")
    status = _sig("Status", 2, dim="Boo", pmin="-8388608", pmax="8388607",
                  dmin="-8388608", dmax="8388607")
    p = _put(tmp_path, "s.bdf", _edf_bytes([eeg, status], [[_i24([0, 1]), _i24([5, 6])]],
                                          version=BDF_V, reserved="24BIT"))
    assert [c.name for c in load_edf(p).channels] == ["Fp1"]


@pytest.mark.parametrize("dim, factor", [("uV", 1.0), ("µV", 1.0), ("mV", 1e3), ("V", 1e6),
                                         ("nV", 1e-3)])
def test_physical_units_are_scaled_to_microvolts(tmp_path, dim, factor):
    sig = _sig("EMG1", 1, dim=dim, pmin="-32768", pmax="32767")
    rec = load_edf(_put(tmp_path, "u.edf", _edf_bytes([sig], [[_i16([10])]])))
    assert rec.data[0, 0] == pytest.approx(10 * factor)


def test_mixed_rates_pick_the_largest_group_or_the_requested_one(tmp_path):
    sigs = [_sig("Fp1", 4), _sig("Fp2", 4), _sig("EMG chin", 2), _sig("Temp", 1, dim="degC")]
    rec_bytes = [_i16([1, 2, 3, 4]), _i16([5, 6, 7, 8]), _i16([9, 10]), _i16([11])]
    p = _put(tmp_path, "m.edf", _edf_bytes(sigs, [rec_bytes]))
    auto = load_edf(p)
    assert [c.name for c in auto.channels] == ["Fp1", "Fp2"] and auto.fs == 4.0
    slow = load_edf(p, fs=2)
    assert slow.channels == (ChannelInfo("EMG chin", SignalKind.EMG),) and slow.fs == 2.0
    with pytest.raises(ValueError, match="no eligible signal at 3 Hz"):
        load_edf(p, fs=3)
    with pytest.raises(ValueError, match="different sampling rates"):
        load_edf(p, channels=["Fp1", "EMG chin"])
    picked = load_edf(p, channels=["Fp2", "Fp1"])
    assert [c.name for c in picked.channels] == ["Fp2", "Fp1"]
    with pytest.raises(ValueError, match="not a voltage"):
        load_edf(p, channels=["Temp"], kinds={"Temp": "eeg"})
    with pytest.raises(ValueError, match="no signal labelled"):
        load_edf(p, channels=["Cz"])


def test_equal_sized_rate_groups_tie_break_to_the_higher_rate(tmp_path):
    sigs = [_sig("EMG1", 2), _sig("Fp1", 4)]
    p = _put(tmp_path, "tie.edf", _edf_bytes(sigs, [[_i16([1, 2]), _i16([1, 2, 3, 4])]]))
    assert load_edf(p).fs == 4.0


def test_kind_overrides_and_non_kind_channels(tmp_path):
    sigs = [_sig("ECG", 2), _sig("EXG1", 2), _sig("Fp1", 2)]
    p = _put(tmp_path, "k.edf", _edf_bytes(sigs, [[_i16([0, 0])] * 3]))
    assert [c.name for c in load_edf(p).channels] == ["EXG1", "Fp1"]   # ECG is not a kind
    rec = load_edf(p, kinds={"ECG": "emg", "EXG1": SignalKind.EOG})
    assert dict((c.name, c.kind) for c in rec.channels) == {
        "ECG": SignalKind.EMG, "EXG1": SignalKind.EOG, "Fp1": SignalKind.EEG}
    with pytest.raises(ValueError, match="cannot tell what 'ECG' measures"):
        load_edf(p, channels=["ECG"])
    with pytest.raises(ValueError, match="unknown signal kind"):
        load_edf(p, kinds={"Fp1": "ecg"})


def test_no_eligible_signal_explains_itself(tmp_path):
    p = _put(tmp_path, "t.edf", _edf_bytes([_sig("Temp", 1, dim="degC")], [[_i16([1])]]))
    with pytest.raises(ValueError, match=r"no EEG/EMG/EOG voltage signal found \(Temp \[degC\]"):
        load_edf(p)


def test_empty_dimension_is_assumed_microvolts_only_when_named(tmp_path, caplog):
    p = _put(tmp_path, "d.edf", _edf_bytes([_sig("Fp1", 1, dim="")], [[_i16([0])]]))
    with pytest.raises(ValueError, match="no EEG/EMG/EOG voltage"):
        load_edf(p)
    with caplog.at_level(logging.WARNING):
        rec = load_edf(p, channels=["Fp1"])
    assert rec.channels[0].name == "Fp1" and "assuming microvolts" in caplog.text


def test_non_ascii_free_text_is_tolerated(tmp_path):
    p = _put(tmp_path, "n.edf", _edf_bytes([_sig("Fp1", 1)], [[_i16([0])]],
                                          patient="X M 01-JAN-1990 Jos\xe9".encode("latin-1")))
    assert load_edf(p).header.patient.endswith("José")


# ------------------------------------------------------------------------------------
# reading — annotations, TALs, time keeping
# ------------------------------------------------------------------------------------


def test_edf_plus_annotations_become_ground_truth(tmp_path):
    ann_spr = 40                                    # 80 bytes per record
    r0 = _tal_bytes(b"+0\x14\x14\x00", b"+0.5\x14Blink\x14\x00",
                    b"+0.75\x151.5\x14squeeze\x14\x00", size=80)
    r1 = _tal_bytes(b"+1\x14\x14\x00", b"+1.25\x14jaw_clench\x14Lights off\x14\x00",
                    "+1.5\x14café\x14\x00".encode(), size=80)
    sigs = [_sig("Fp1", 2), _ann_sig(ann_spr)]
    p = _put(tmp_path, "ann.edf", _edf_bytes(
        sigs, [[_i16([0, 0]), r0], [_i16([0, 0]), r1]], reserved="EDF+C"))
    rec = load_edf(p)
    assert rec.header.variant == "EDF+C"
    assert rec.data.shape == (1, 4)                     # annotation signal is not a channel
    assert [(a.onset, a.text, a.duration) for a in rec.annotations] == [
        (0.5, "Blink", None), (0.75, "squeeze", 1.5), (1.25, "jaw_clench", None),
        (1.25, "Lights off", None), (1.5, "café", None)]
    assert [(e.kind, e.t) for e in rec.events] == [
        (EventKind.BLINK, 0.5), (EventKind.SQUEEZE_ON, 0.75), (EventKind.JAW_CLENCH, 1.25),
        (EventKind.SQUEEZE_OFF, 2.25)]
    assert all(type(e.t) is float for e in rec.events)


def test_bdf_plus_annotation_signal(tmp_path):
    r0 = _tal_bytes(b"+0\x14\x14\x00", b"+0.25\x14blink\x14\x00", size=30)
    sigs = [_sig("Fp1", 2, dmin="-8388608", dmax="8388607"), _ann_sig(10, bdf=True)]
    p = _put(tmp_path, "ann.bdf", _edf_bytes(sigs, [[_i24([0, 0]), r0]], version=BDF_V,
                                            reserved="BDF+C"))
    rec = load_edf(p)
    assert rec.header.variant == "BDF+C"
    assert [(e.kind, e.t) for e in rec.events] == [(EventKind.BLINK, 0.25)]


def test_time_keeping_sets_t0(tmp_path):
    r0 = _tal_bytes(b"+3\x14\x14\x00", b"+3.5\x14blink\x14\x00", size=40)
    p = _put(tmp_path, "tk.edf", _edf_bytes([_sig("Fp1", 2), _ann_sig(20)],
                                           [[_i16([0, 0]), r0]], reserved="EDF+C"))
    rec = load_edf(p)
    assert rec.t0 == 3.0 and rec.events[0].t == 3.5


def test_discontinuous_file_maps_onsets_onto_the_gapless_timeline(tmp_path, caplog):
    # records start at 0 s and 10 s (a 9 s gap); replay concatenates them
    r0 = _tal_bytes(b"+0\x14\x14\x00", b"+0.5\x14blink\x14\x00", size=60)
    r1 = _tal_bytes(b"+10\x14\x14\x00", b"+10.25\x14blink\x14\x00",
                    b"+5\x14blink\x14\x00", size=60)       # +5 lies in the gap
    p = _put(tmp_path, "d.edf", _edf_bytes([_sig("Fp1", 2), _ann_sig(30)],
                                          [[_i16([0, 0]), r0], [_i16([0, 0]), r1]],
                                          reserved="EDF+D"))
    with caplog.at_level(logging.WARNING):
        rec = load_edf(p)
    assert rec.header.discontinuous
    assert [e.t for e in rec.events] == [0.5, 1.25]
    assert "outside the recorded samples" in caplog.text


def test_malformed_tal_is_skipped_with_a_warning(tmp_path, caplog):
    r0 = _tal_bytes(b"+0\x14\x14\x00", b"0.5\x14no sign\x14\x00", b"+0.7\x14blink\x14\x00",
                    b"+0.8\x14unterminated\x00", size=80)
    p = _put(tmp_path, "bad.edf", _edf_bytes([_sig("Fp1", 2), _ann_sig(40)],
                                            [[_i16([0, 0]), r0]], reserved="EDF+C"))
    with caplog.at_level(logging.WARNING):
        rec = load_edf(p)
    assert [a.text for a in rec.annotations] == ["blink"]
    assert "2 malformed annotation list(s) skipped" in caplog.text


def test_custom_event_map_replaces_the_default(tmp_path):
    r0 = _tal_bytes(b"+0\x14\x14\x00", b"+0.5\x14T1\x14\x00", b"+0.6\x14blink\x14\x00",
                    size=60)
    p = _put(tmp_path, "map.edf", _edf_bytes([_sig("Fp1", 2), _ann_sig(30)],
                                            [[_i16([0, 0]), r0]], reserved="EDF+C"))
    rec = load_edf(p, event_map={"t1": "jaw_clench"})
    assert [(e.kind, e.t) for e in rec.events] == [(EventKind.JAW_CLENCH, 0.5)]


# ------------------------------------------------------------------------------------
# reading — defensive behaviour
# ------------------------------------------------------------------------------------


def _good(**kw) -> bytes:
    return _edf_bytes([_sig("Fp1", 2)], [[_i16([0, 0])], [_i16([0, 0])]], **kw)


@pytest.mark.parametrize("data, message", [
    (b"0       short", "too short"),
    (b"9" + _good()[1:], "not an EDF or BDF file"),
    (_good(header_bytes="1024"), "header says 1024 bytes"),
    (_good(duration="abc"), "'duration of a data record' is not a number"),
    (_good(duration="nan"), "not finite"),
    (_edf_bytes([_sig("Fp1", 2, dmin="10", dmax="10")], [[_i16([0, 0])]]),
     "digital maximum 10 is not above"),
    (_edf_bytes([_sig("Fp1", 2, pmin="5", pmax="5")], [[_i16([0, 0])]]),
     "physical minimum and maximum are both"),
    (_edf_bytes([_sig("Fp1", 0)], []), "0 samples per record"),
    (_edf_bytes([_sig("Fp1", 2, dmin="-1.5")], [[_i16([0, 0])]]), "not an integer"),
    (_good(n_records="5"), "truncated recording"),
    (_good(n_records="99999999"), "truncated recording"),     # absurd count, no allocation
    (_good(n_records="-7"), "invalid number of data records"),
    (_good()[:-1], "truncated recording"),
    (_good(duration="0"), "annotation-only file"),
    (_edf_bytes([_sig("Fp1", 2)], [], n_records="0"), "no data records"),
])
def test_malformed_files_raise_clear_errors(tmp_path, data, message):
    p = _put(tmp_path, "bad.edf", data)
    with pytest.raises(ValueError, match=message):
        load_edf(p)


def test_zero_signals_is_rejected(tmp_path):
    head = _good()[:252] + b"0   "
    with pytest.raises(ValueError, match="number of signals must be"):
        load_edf(_put(tmp_path, "z.edf", head))


def test_unknown_record_count_is_derived_from_the_file(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        rec = load_edf(_put(tmp_path, "u.edf", _good(n_records="-1")))
    assert rec.header.n_records == 2 and rec.n_samples == 4
    assert "derived 2" in caplog.text
    with pytest.raises(ValueError, match="last data record is truncated"):
        load_edf(_put(tmp_path, "u2.edf", _good(n_records="-1")[:-1]))


def test_trailing_bytes_are_ignored_with_a_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        rec = load_edf(_put(tmp_path, "t.edf", _good() + b"\x00\x00\x00"))
    assert rec.n_samples == 4 and "3 trailing bytes" in caplog.text


def test_max_bytes_caps_what_is_read(tmp_path):
    p = _put(tmp_path, "big.edf", _good())
    with pytest.raises(ValueError, match="exceeds max_bytes=4"):
        load_edf(p, max_bytes=4)
    assert read_edf_header(p).n_records == 2


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_edf(tmp_path / "nope.edf")
    with pytest.raises(FileNotFoundError):
        read_edf_header(tmp_path / "nope.edf")


# ------------------------------------------------------------------------------------
# heuristics and mapping
# ------------------------------------------------------------------------------------


@pytest.mark.parametrize("label, transducer, kind", [
    ("EEG Fpz-Cz", "", SignalKind.EEG),
    ("Fp1", "", SignalKind.EEG),
    ("FC5.", "", SignalKind.EEG),           # PhysioNet EEGMMIDB style
    ("Fc5.", "", SignalKind.EEG),
    ("C3-A2", "", SignalKind.EEG),
    ("TP9", "", SignalKind.EEG),
    ("Oz", "", SignalKind.EEG),
    ("EOG horizontal", "", SignalKind.EOG),
    ("HEOG", "", SignalKind.EOG),
    ("LOC", "", SignalKind.EOG),
    ("EMG submental", "", SignalKind.EMG),
    ("EMG1", "", SignalKind.EMG),
    ("Chin", "", SignalKind.EMG),
    ("Fp2", "EOG electrode", SignalKind.EOG),   # the writer's transducer field reads back
    ("ECG", "", None),
    ("EKG II", "", None),
    ("Resp oro-nasal", "", None),
    ("Temp rectal", "", None),
    ("Status", "", None),
    ("EXG3", "", SignalKind.EEG),           # says nothing -> default
])
def test_guess_kind(label, transducer, kind):
    assert guess_kind(label, transducer) is kind


def test_guess_kind_default_can_be_none():
    assert guess_kind("Ch7", default=None) is None


@pytest.mark.parametrize("unit, factor", [("uV", 1.0), ("UV", 1.0), ("µV", 1.0),
                                          ("μV", 1.0), ("microvolts", 1.0), ("mV", 1e3),
                                          ("V", 1e6), ("nV", 1e-3), ("degC", None),
                                          ("", None), (None, None), ("Boo", None)])
def test_unit_scale(unit, factor):
    assert unit_scale(unit) == factor


def test_annotation_kind_normalises_text():
    assert annotation_kind("Double-Blink") is EventKind.DOUBLE_BLINK
    assert annotation_kind("  JAW_CLENCH ") is EventKind.JAW_CLENCH
    assert annotation_kind("Lights off") is None
    assert annotation_kind("go", {"go": EventKind.SQUEEZE_ON}) is EventKind.SQUEEZE_ON
    with pytest.raises(ValueError, match="unknown event kind"):
        annotation_kind("go", {"go": "wink"})
    for kind in EventKind:                     # every kind's own name maps back
        assert DEFAULT_EVENT_MAP[kind.value.replace("_", " ")] is kind


def test_annotations_to_events_adds_squeeze_off_for_a_duration():
    events = annotations_to_events([Annotation(2.0, "squeeze", 0.5),
                                    Annotation(1.0, "squeeze")])
    assert [(e.kind, e.t) for e in events] == [
        (EventKind.SQUEEZE_ON, 1.0), (EventKind.SQUEEZE_ON, 2.0), (EventKind.SQUEEZE_OFF, 2.5)]
    assert events[1].detail == {"annotation": "squeeze", "source": "edf", "duration": 0.5}


# ------------------------------------------------------------------------------------
# writing
# ------------------------------------------------------------------------------------

CH3 = (ChannelInfo("Fp1", SignalKind.EEG), ChannelInfo("EMG1", SignalKind.EMG),
       ChannelInfo("Fp2", SignalKind.EOG))


def _signal(n: int = 1000, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 50, (3, n))
    x[2] += 2000.0                           # a DC offset: the range must follow the data
    return x


@pytest.mark.parametrize("fmt, levels", [("edf", 65535), ("bdf", 16777215)])
def test_round_trip_preserves_samples_kinds_and_events(tmp_path, fmt, levels):
    x = _signal()
    events = [BioEvent(EventKind.BLINK, 6.0), BioEvent(EventKind.SQUEEZE_ON, 7.5),
              BioEvent(EventKind.SQUEEZE_OFF, 8.25)]
    p = tmp_path / f"rt.{fmt}"
    n = write_edf(p, _blocks(x, 250.0, CH3, t0=5.0), events=events)
    assert n == 1000
    rec = load_edf(p)
    assert rec.header.variant == f"{fmt.upper()}+C"
    assert rec.fs == 250.0 and rec.channels == CH3 and rec.t0 == 0.0
    step = (x.max(axis=1) - x.min(axis=1)) / levels
    err = np.abs(rec.data[:, :1000] - x).max(axis=1)
    assert np.all(err <= step * 0.51 + 1e-9)          # half a quantisation step (+ rounding)
    # the file clock starts at the first sample, so events move by -t0 together with it
    assert [(e.kind, e.t) for e in rec.events] == [
        (EventKind.BLINK, 1.0), (EventKind.SQUEEZE_ON, 2.5), (EventKind.SQUEEZE_OFF, 3.25)]


def test_final_record_is_edge_padded(tmp_path):
    x = _signal(n=260)
    p = tmp_path / "pad.edf"
    assert write_edf(p, _blocks(x, 250.0, CH3)) == 260
    rec = load_edf(p)
    assert rec.n_samples == 500                       # two 1-s records
    np.testing.assert_allclose(rec.data[:, 260:], np.repeat(rec.data[:, 259:260], 240, axis=1))


def test_written_header_bytes_follow_the_field_table(tmp_path):
    x = _signal(n=500)
    p = tmp_path / "h.edf"
    write_edf(p, _blocks(x, 250.0, CH3), start=datetime(2026, 3, 2, 14, 5, 9))
    raw = p.read_bytes()
    ns = 4                                            # 3 channels + EDF Annotations
    assert raw[:8] == EDF_V
    assert raw[8:88].rstrip() == b"X X X X"
    assert raw[88:168].rstrip() == b"Startdate 02-MAR-2026 X X YazSes"
    assert raw[168:176] == b"02.03.26" and raw[176:184] == b"14.05.09"
    assert int(raw[184:192]) == 256 * (ns + 1)
    assert raw[192:236].rstrip() == b"EDF+C"
    assert int(raw[236:244]) == 2 and float(raw[244:252]) == 1.0 and int(raw[252:256]) == ns
    labels = raw[256:256 + 16 * ns]
    assert labels[48:64] == b"EDF Annotations "
    hdr = read_edf_header(p)
    assert len(raw) == hdr.header_bytes + hdr.n_records * hdr.record_bytes
    ann = hdr.signals[-1]
    assert (ann.digital_min, ann.digital_max) == (-32768, 32767)
    assert hdr.signals[1].transducer == "EMG electrode"
    assert hdr.signals[0].physical_dimension == "uV"


def test_default_identification_is_anonymous(tmp_path):
    p = tmp_path / "anon.bdf"
    write_edf(p, _blocks(_signal(n=250), 250.0, CH3))
    raw = p.read_bytes()
    assert raw[:8] == BDF_V and raw[192:197] == b"BDF+C"
    assert raw[168:184] == b"01.01.8500.00.00"
    assert raw[88:168].rstrip() == b"Startdate X X X YazSes"


@posix_only
def test_written_file_is_private(tmp_path):
    p = tmp_path / "private.edf"
    p.write_bytes(b"old")
    os.chmod(p, 0o644)
    write_edf(p, _blocks(_signal(n=250), 250.0, CH3))
    assert (p.stat().st_mode & 0o777) == 0o600


def test_explicit_physical_range_clips_and_warns(tmp_path, caplog):
    x = np.array([[-500.0, 0.0, 10.0, 500.0]])
    ch = (ChannelInfo("EMG1", SignalKind.EMG),)
    p = tmp_path / "clip.edf"
    with caplog.at_level(logging.WARNING):
        write_edf(p, [SampleBlock(x, 4.0, ch)], physical_range=(-100.0, 100.0))
    assert "2 sample(s) outside physical_range were clipped" in caplog.text
    rec = load_edf(p)
    np.testing.assert_allclose(rec.data[0], [-100, 0, 10, 100], atol=200 / 65535)


def test_constant_channel_and_non_finite_samples(tmp_path, caplog):
    x = np.array([[0.0, 0.0, np.nan, 0.0]])
    ch = (ChannelInfo("Fp1", SignalKind.EEG),)
    p = tmp_path / "flat.edf"
    with caplog.at_level(logging.WARNING):
        write_edf(p, [SampleBlock(x, 4.0, ch)])
    assert "non-finite" in caplog.text
    np.testing.assert_allclose(load_edf(p).data[0], 0.0, atol=1 / 65535)


def test_annotations_are_written_with_durations(tmp_path):
    p = tmp_path / "a.edf"
    write_edf(p, _blocks(_signal(n=750), 250.0, CH3),
              annotations=[Annotation(0.5, "squeeze", 1.25), Annotation(2.9, "Lights off")])
    rec = load_edf(p)
    assert [(a.onset, a.text, a.duration) for a in rec.annotations] == [
        (0.5, "squeeze", 1.25), (2.9, "Lights off", None)]
    assert [(e.kind, e.t) for e in rec.events] == [
        (EventKind.SQUEEZE_ON, 0.5), (EventKind.SQUEEZE_OFF, 1.75)]


@pytest.mark.parametrize("kwargs, blocks, message", [
    ({}, [], "no blocks to write"),
    ({"fmt": "gdf"}, None, "fmt must be"),
    ({"record_seconds": 0.003}, None, "not a whole number of samples"),
    ({"record_seconds": 0}, None, "record_seconds must be > 0"),
    ({"physical_range": (5.0, 5.0)}, None, "high > low"),
    ({"patient": "José"}, None, "printable ASCII"),
    ({"annotations": [Annotation(0.1, "a\x14b")]}, None, "reserved TAL byte"),
    ({"start": datetime(1970, 1, 1)}, None, "1985..2084"),
])
def test_writer_rejects_bad_input(tmp_path, kwargs, blocks, message):
    if blocks is None:
        blocks = _blocks(_signal(n=250), 250.0, CH3)
    with pytest.raises(ValueError, match=message):
        write_edf(tmp_path / "x.edf", blocks, **kwargs)


def test_writer_rejects_unwritable_channel_names_and_changes(tmp_path):
    long_name = (ChannelInfo("A" * 17, SignalKind.EEG),)
    with pytest.raises(ValueError, match="longer than 16"):
        write_edf(tmp_path / "x.edf", [SampleBlock(np.zeros((1, 4)), 4.0, long_name)])
    a = SampleBlock(np.zeros((3, 4)), 4.0, CH3)
    b = SampleBlock(np.zeros((3, 4)), 8.0, CH3)
    with pytest.raises(ValueError, match="changed mid-recording"):
        write_edf(tmp_path / "y.edf", [a, b])


def test_kind_that_will_not_read_back_is_warned(tmp_path, caplog):
    ch = (ChannelInfo("EMG1", SignalKind.EEG),)
    with caplog.at_level(logging.WARNING):
        write_edf(tmp_path / "w.edf", [SampleBlock(np.zeros((1, 4)), 4.0, ch)])
    assert "will read back as emg" in caplog.text


# ------------------------------------------------------------------------------------
# end to end: a labelled file scores through evaluate()
# ------------------------------------------------------------------------------------


class _TruthEcho:
    """A stand-in detector that reports every truth event inside the block it sees."""

    def __init__(self, truth):
        self._truth = list(truth)

    def process(self, block):
        end = block.t0 + block.duration
        return [e for e in self._truth if block.t0 <= e.t < end]

    def reset(self):
        return None


def test_synthetic_session_round_trips_into_evaluate(tmp_path):
    src = SyntheticSource("mixed", seed=3, duration=4.0)
    src.schedule_blink(1.0).schedule_squeeze(2.0, 0.5).schedule_clench(3.0, 0.3)
    blocks = list(iter_blocks(src))
    p = tmp_path / "session.edf"
    write_edf(p, blocks, events=src.ground_truth())
    rec = load_edf(p)
    assert [c.name for c in rec.channels] == [c.name for c in src.channels]
    assert [(e.kind, round(e.t, 6)) for e in rec.events] == [
        (e.kind, round(e.t - blocks[0].t0, 6)) for e in src.ground_truth()]
    replay = [SampleBlock(rec.data[:, i:i + 50], rec.fs, rec.channels, t0=rec.t0 + i / rec.fs)
              for i in range(0, rec.n_samples, 50)]
    report = evaluate(replay, _TruthEcho(rec.events), truth=rec.events)
    assert report.overall.recall == 1.0 and report.overall.precision == 1.0
