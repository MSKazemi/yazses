"""Tests for ``yazses.biosignal.xdf``: XDF (LabRecorder) loading through a fake ``pyxdf``.

``pyxdf`` is optional and never required here: a fake module is put in ``sys.modules``.
Its stream dicts mimic what ``pyxdf.load_xdf`` returns — XML converted by its
``_xml2dict``, so every element is a *list* (``info["name"][0]``) and
``desc/channels/channel`` is a list of dicts of lists — with numeric samples as a
``(samples, channels)`` array and string markers as a list of lists.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import types

import numpy as np
import pytest

from yazses.biosignal.types import ChannelInfo, EventKind, SignalKind
from yazses.biosignal.xdf import list_xdf_streams, load_xdf

T0 = 5000.0         # LSL clock: seconds since some boot, nowhere near zero


def _info(name: str, typ: str, srate: float, n_ch: int, fmt: str = "float32",
          channels: list[dict] | None = None) -> dict:
    desc: object = None
    if channels is not None:
        desc = {"channels": [{"channel": [
            {k: [v] for k, v in ch.items()} for ch in channels]}]}
    return {"name": [name], "type": [typ], "channel_count": [str(n_ch)],
            "nominal_srate": [repr(float(srate))], "channel_format": [fmt],
            "desc": [desc], "stream_id": 1, "effective_srate": float(srate)}


def _signal_stream(data: np.ndarray, fs: float, *, name: str = "OpenBCI", typ: str = "EEG",
                   channels: list[dict] | None = None, stamps: np.ndarray | None = None) -> dict:
    n = data.shape[0]
    if stamps is None:
        stamps = T0 + np.arange(n) / fs
    return {"info": _info(name, typ, fs, data.shape[1], channels=channels),
            "time_series": data, "time_stamps": stamps}


def _marker_stream(marks: list[tuple[float, str]], name: str = "Markers") -> dict:
    return {"info": _info(name, "Markers", 0.0, 1, fmt="string"),
            "time_series": [[text] for _, text in marks],
            "time_stamps": np.array([t for t, _ in marks], dtype=np.float64)}


@pytest.fixture
def fake_pyxdf(monkeypatch):
    """Install a fake ``pyxdf``; set ``.streams`` (or ``.error``) before calling load_xdf."""
    mod = types.ModuleType("pyxdf")
    mod.streams = []
    mod.error = None
    mod.calls = []

    def load_xdf(filename, *args, **kwargs):
        mod.calls.append(filename)
        if mod.error is not None:
            raise mod.error
        return mod.streams, {"info": {"version": ["1.0"]}}

    def resolve_streams(filename):
        return [{"stream_id": 1, "name": "OpenBCI", "type": "EEG"}]

    mod.load_xdf = load_xdf
    mod.resolve_streams = resolve_streams
    monkeypatch.setitem(sys.modules, "pyxdf", mod)
    return mod


@pytest.fixture
def xdf_path(tmp_path):
    p = tmp_path / "session.xdf"
    p.write_bytes(b"XDF:")          # content is irrelevant: the fake pyxdf reads nothing
    return p


CHANNELS = [
    {"label": "Fp1", "type": "EEG", "unit": "microvolts"},
    {"label": "EMG_jaw", "type": "EMG", "unit": "mV"},
    {"label": "ECG", "type": "ECG", "unit": "microvolts"},
    {"label": "EOG_V", "type": "EOG", "unit": "uV"},
]


def _data(n: int = 1000, n_ch: int = 4, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 30, (n, n_ch)).astype(np.float32)


def test_loads_channels_units_and_markers(fake_pyxdf, xdf_path):
    x = _data()
    fake_pyxdf.streams = [
        _signal_stream(x, 250.0, channels=CHANNELS),
        _marker_stream([(T0 + 1.0, "blink"), (T0 + 2.5, "squeeze"), (T0 + 3.0, "Double Blink"),
                        (T0 + 3.5, "trial start")]),
    ]
    rec = load_xdf(xdf_path)
    assert fake_pyxdf.calls == [str(xdf_path)]
    assert rec.stream_name == "OpenBCI" and rec.stream_type == "EEG"
    assert rec.fs == 250.0 and rec.t0 == 0.0 and rec.data.dtype == np.float64
    assert rec.channels == (ChannelInfo("Fp1", SignalKind.EEG),
                            ChannelInfo("EMG_jaw", SignalKind.EMG),
                            ChannelInfo("EOG_V", SignalKind.EOG))      # ECG left out
    np.testing.assert_allclose(rec.data[0], x[:, 0].astype(np.float64))
    np.testing.assert_allclose(rec.data[1], x[:, 1].astype(np.float64) * 1000.0)
    assert [(e.kind, pytest.approx(e.t)) for e in rec.events] == [
        (EventKind.BLINK, 1.0), (EventKind.SQUEEZE_ON, 2.5), (EventKind.DOUBLE_BLINK, 3.0)]
    assert [a.text for a in rec.annotations] == ["blink", "squeeze", "Double Blink",
                                                 "trial start"]
    assert rec.events[0].detail["source"] == "xdf"
    assert rec.effective_srate == 250.0


def test_markers_stay_on_their_sample_across_dropped_samples(fake_pyxdf, xdf_path, caplog):
    fs = 100.0
    k = np.arange(200)
    stamps = T0 + np.where(k < 100, k, k + 50) / fs     # 50 samples lost after sample 99
    fake_pyxdf.streams = [
        _signal_stream(_data(200, 1), fs, channels=[{"label": "Fp1"}], stamps=stamps),
        _marker_stream([(T0 + 200 / fs, "blink"), (T0 + 120 / fs, "blink"),
                        (T0 + 999.0, "blink")]),
    ]
    with caplog.at_level(logging.WARNING):
        rec = load_xdf(xdf_path)
    # LSL time of sample 150 is T0 + 200/fs; on the gapless replay it is 150/fs. The marker
    # in the dropped stretch (LSL sample 120) lands between samples 99 and 100.
    assert [round(e.t, 6) for e in rec.events] == [pytest.approx(0.995, abs=0.006), 1.5]
    assert "gaps in its time stamps" in caplog.text
    assert "1 marker(s) lie outside" in caplog.text


@pytest.mark.parametrize("kwargs, expected", [
    ({"stream": "Muse"}, "Muse"),
    ({"stream_type": "emg"}, "Myo"),
    ({}, "Muse"),                    # the EEG-typed stream wins over an accelerometer
])
def test_stream_selection(fake_pyxdf, xdf_path, kwargs, expected):
    fake_pyxdf.streams = [
        _signal_stream(_data(10, 3), 52.0, name="Muse ACC", typ="Accelerometer"),
        _signal_stream(_data(10, 4), 256.0, name="Muse", typ="EEG"),
        _marker_stream([(T0, "x")]),
    ]
    if expected == "Myo":
        fake_pyxdf.streams.append(_signal_stream(_data(10, 8), 200.0, name="Myo", typ="EMG"))
    assert load_xdf(xdf_path, **kwargs).stream_name == expected


def test_ambiguous_or_missing_stream_is_an_error(fake_pyxdf, xdf_path):
    fake_pyxdf.streams = [_signal_stream(_data(10, 2), 250.0, name="A"),
                          _signal_stream(_data(10, 2), 500.0, name="B")]
    with pytest.raises(ValueError, match=r"2 streams match .* 'A' \(type EEG, 250 Hz\)"):
        load_xdf(xdf_path)
    with pytest.raises(ValueError, match="no numeric regular-rate stream matches"):
        load_xdf(xdf_path, stream="C")
    fake_pyxdf.streams = [_marker_stream([(T0, "blink")])]
    with pytest.raises(ValueError, match="no numeric regular-rate stream"):
        load_xdf(xdf_path)


def test_stream_without_metadata_uses_generic_names_and_stream_type(fake_pyxdf, xdf_path,
                                                                    caplog):
    fake_pyxdf.streams = [_signal_stream(_data(20, 2), 200.0, name="Myo", typ="EMG")]
    with caplog.at_level(logging.INFO):
        rec = load_xdf(xdf_path)
    assert rec.channels == (ChannelInfo("ch1", SignalKind.EMG), ChannelInfo("ch2", SignalKind.EMG))
    assert "assuming microvolts" in caplog.text


def test_metadata_count_mismatch_falls_back_to_generic_names(fake_pyxdf, xdf_path, caplog):
    fake_pyxdf.streams = [_signal_stream(_data(20, 3), 250.0, channels=CHANNELS[:2])]
    with caplog.at_level(logging.WARNING):
        rec = load_xdf(xdf_path)
    assert [c.name for c in rec.channels] == ["ch1", "ch2", "ch3"]
    assert "lists 2 channels but the stream has 3" in caplog.text


def test_label_heuristics_apply_when_types_are_absent(fake_pyxdf, xdf_path):
    chans = [{"label": "Fp1"}, {"label": "EOG left"}, {"label": "ECG"}, {"label": "AUX1",
                                                                          "type": "AUX"}]
    fake_pyxdf.streams = [_signal_stream(_data(20, 4), 250.0, typ="ExG", channels=chans)]
    rec = load_xdf(xdf_path)
    assert rec.channels == (ChannelInfo("Fp1", SignalKind.EEG),
                            ChannelInfo("EOG left", SignalKind.EOG))


def test_explicit_channels_and_kind_overrides(fake_pyxdf, xdf_path):
    chans = CHANNELS + [{"label": "Temp", "type": "EEG", "unit": "degC"}]
    fake_pyxdf.streams = [_signal_stream(_data(20, 5), 250.0, channels=chans)]
    rec = load_xdf(xdf_path, channels=["EOG_V", "ECG"], kinds={"ECG": "emg"})
    assert rec.channels == (ChannelInfo("EOG_V", SignalKind.EOG),
                            ChannelInfo("ECG", SignalKind.EMG))
    with pytest.raises(ValueError, match="cannot tell what 'ECG' measures"):
        load_xdf(xdf_path, channels=["ECG"])
    with pytest.raises(ValueError, match="'Temp' is in 'degC', not a voltage"):
        load_xdf(xdf_path, channels=["Temp"])
    with pytest.raises(ValueError, match="has no channel 'Cz'"):
        load_xdf(xdf_path, channels=["Cz"])
    with pytest.raises(ValueError, match="channels=\\[\\] selects nothing"):
        load_xdf(xdf_path, channels=[])
    with pytest.raises(ValueError, match="unknown signal kind"):
        load_xdf(xdf_path, kinds={"Fp1": "ecg"})


def test_no_usable_channel_explains_itself(fake_pyxdf, xdf_path):
    chans = [{"label": "ECG", "type": "ECG", "unit": "uV"}]
    fake_pyxdf.streams = [_signal_stream(_data(20, 1), 250.0, channels=chans)]
    with pytest.raises(ValueError, match=r"no EEG/EMG/EOG voltage channel \(ECG \[ECG, uV\]\)"):
        load_xdf(xdf_path)


def test_numeric_marker_stream_and_marker_stream_filter(fake_pyxdf, xdf_path):
    numeric = {"info": _info("Triggers", "Markers", 0.0, 1),
               "time_series": np.array([[1.0], [2.0]]),
               "time_stamps": np.array([T0 + 0.5, T0 + 1.5])}
    fake_pyxdf.streams = [_signal_stream(_data(500, 1), 250.0, channels=[{"label": "Fp1"}]),
                          numeric, _marker_stream([(T0 + 1.0, "blink")], name="Other")]
    rec = load_xdf(xdf_path, event_map={"1": "jaw_clench", "blink": "blink"})
    assert [(e.kind, e.t) for e in rec.events] == [
        (EventKind.JAW_CLENCH, pytest.approx(0.5)), (EventKind.BLINK, pytest.approx(1.0))]
    only = load_xdf(xdf_path, marker_streams=["Other"])
    assert [a.text for a in only.annotations] == ["blink"]


def test_non_finite_samples_become_zero(fake_pyxdf, xdf_path, caplog):
    x = _data(10, 1)
    x[3, 0] = np.nan
    fake_pyxdf.streams = [_signal_stream(x, 250.0, channels=[{"label": "Fp1"}])]
    with caplog.at_level(logging.WARNING):
        rec = load_xdf(xdf_path)
    assert rec.data[0, 3] == 0.0 and "non-finite" in caplog.text


def test_unreadable_file_is_a_value_error(fake_pyxdf, xdf_path):
    fake_pyxdf.error = RuntimeError("invalid variable-length integer encountered.")
    with pytest.raises(ValueError, match="not a readable XDF file"):
        load_xdf(xdf_path)


def test_missing_file(fake_pyxdf, tmp_path):
    with pytest.raises(FileNotFoundError):
        load_xdf(tmp_path / "nope.xdf")
    with pytest.raises(FileNotFoundError):
        list_xdf_streams(tmp_path / "nope.xdf")


def test_list_streams_passes_headers_through(fake_pyxdf, xdf_path):
    assert list_xdf_streams(xdf_path) == [{"stream_id": 1, "name": "OpenBCI", "type": "EEG"}]


def test_missing_pyxdf_names_the_extra(monkeypatch, xdf_path):
    monkeypatch.setitem(sys.modules, "pyxdf", None)     # makes `import pyxdf` fail
    with pytest.raises(ImportError, match=r"install the 'xdf' extra"):
        load_xdf(xdf_path)
    with pytest.raises(ImportError, match="'xdf' extra"):
        list_xdf_streams(xdf_path)


def test_module_imports_without_pyxdf():
    code = ("import sys; sys.modules['pyxdf'] = None; "
            "import yazses.biosignal.xdf, yazses.biosignal.edf; print('ok')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
