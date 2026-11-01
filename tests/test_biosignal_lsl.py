"""LSL block source: spec parsing, stream selection, metadata, timestamps, confinement.

No liblsl is needed: the pure parts are tested directly and the source runs against a
fake ``pylsl`` module injected into ``sys.modules``.
"""

from __future__ import annotations

import ast
import configparser
import logging
import os
import platform
import stat
import sys
import types
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from yazses.biosignal import lsl_source
from yazses.biosignal.lsl_source import (
    LIBLSL_CONFIG,
    LSLBlockSource,
    LslChannelMeta,
    LslSpec,
    LslStreamError,
    LslTimeline,
    StreamSummary,
    check_stream_usable,
    is_local_host,
    list_lsl_streams,
    open_lsl_source,
    parse_channel_metadata,
    parse_lsl_spec,
    resolve_channels,
    select_stream,
    unit_scale_to_uv,
)
from yazses.biosignal.types import BlockSource, ChannelInfo, SignalKind

# ====================================================================================
# fake pylsl
# ====================================================================================


def _channels_xml(rows: list[tuple[str, str, str]]) -> str:
    chans = "".join(f"<channel><label>{lab}</label><type>{typ}</type><unit>{unit}</unit>"
                    "</channel>" for lab, typ, unit in rows)
    return f"<?xml version='1.0'?><info><name>x</name><desc><channels>{chans}</channels></desc></info>"


class FakeInfo:
    def __init__(self, name: str = "obci_eeg1", type_: str = "EEG", *, source_id: str = "",
                 hostname: str | None = None, uid: str = "", channel_count: int = 2,
                 nominal_srate: float = 250.0, channel_format: int = 1,
                 xml: str = "") -> None:
        self._v = {"name": name, "type": type_, "source_id": source_id,
                   "hostname": platform.node() if hostname is None else hostname,
                   "uid": uid or f"uid-{name}-{source_id}", "channel_count": channel_count,
                   "nominal_srate": nominal_srate, "channel_format": channel_format}
        self._xml = xml

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_") or item not in self._v:
            raise AttributeError(item)
        return lambda: self._v[item]

    def as_xml(self) -> str:
        return self._xml


class FakeInlet:
    def __init__(self, info: FakeInfo, chunks: deque, log: list, *, fail_pull: bool = False,
                 **kw: Any) -> None:
        self.info_obj, self.kw, self.chunks, self.log = info, kw, chunks, log
        self.fail_pull = fail_pull
        self.closed = False

    def info(self, timeout: float = 0.0) -> FakeInfo:
        self.log.append(("info", timeout))
        return self.info_obj

    def open_stream(self, timeout: float = 0.0) -> None:
        self.log.append(("open_stream", timeout))

    def pull_chunk(self, timeout: float = 0.0, max_samples: int = 1024) -> tuple[list, list]:
        if self.fail_pull:
            raise RuntimeError("the stream has been lost.")
        if not self.chunks:
            return [], []
        return self.chunks.popleft()

    def close_stream(self) -> None:
        self.closed = True


def make_fake_pylsl(infos: list[FakeInfo], chunks: list | None = None, *,
                    fail_pull: bool = False, with_content_setter: bool = True) -> Any:
    mod: Any = types.ModuleType("pylsl")
    mod.calls = []
    mod.inlets = []
    queue: deque = deque(chunks or [])

    def resolve_byprop(prop: str, value: str, minimum: int = 1, timeout: float = 0.0) -> list:
        cfg = os.environ.get("LSLAPICFG", "")
        mod.calls.append(("resolve_byprop", prop, value, timeout, cfg,
                          Path(cfg).read_text(encoding="utf-8") if cfg else "",
                          oct(stat.S_IMODE(os.stat(cfg).st_mode)) if cfg else ""))
        return [i for i in infos if getattr(i, prop)() == value]

    def resolve_streams(wait_time: float = 1.0) -> list:
        mod.calls.append(("resolve_streams", wait_time, os.environ.get("LSLAPICFG", "")))
        return list(infos)

    def stream_inlet(info: FakeInfo, **kw: Any) -> FakeInlet:
        inlet = FakeInlet(info, queue, mod.calls, fail_pull=fail_pull, **kw)
        mod.inlets.append(inlet)
        return inlet

    mod.resolve_byprop = resolve_byprop
    mod.resolve_streams = resolve_streams
    mod.StreamInlet = stream_inlet
    mod.proc_clocksync = 1
    if with_content_setter:
        mod.set_config_content = lambda content: mod.calls.append(("set_config_content", content))
    return mod


@pytest.fixture(autouse=True)
def _fresh_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test is a fresh process as far as liblsl's once-only config is concerned."""
    monkeypatch.setattr(lsl_source, "_pinned", False)
    monkeypatch.delenv("LSLAPICFG", raising=False)


def _install(monkeypatch: pytest.MonkeyPatch, fake: Any) -> Any:
    monkeypatch.setitem(sys.modules, "pylsl", fake)
    return fake


# ====================================================================================
# spec parsing
# ====================================================================================


@pytest.mark.parametrize(("spec", "expected"), [
    ("lsl:Muse", LslSpec("name", "Muse")),
    ("LSL: obci_eeg1 ", LslSpec("name", "obci_eeg1")),
    ("lsl:name=Muse", LslSpec("name", "Muse")),
    ("lsl:type=EEG", LslSpec("type", "EEG")),
    ("lsl:TYPE = EMG", LslSpec("type", "EMG")),
    ("lsl:source_id=Muse-1234", LslSpec("source_id", "Muse-1234")),
    ("lsl:a=b", LslSpec("name", "a=b")),          # unknown key: the whole text is a name
    ("lsl:name=x=y", LslSpec("name", "x=y")),
])
def test_parse_lsl_spec(spec: str, expected: LslSpec) -> None:
    assert parse_lsl_spec(spec) == expected


@pytest.mark.parametrize("spec", [
    "lsl:", "lsl:  ", "lsl:type=", "brainflow:-1", "Muse", "lsl:it's", 'lsl:type="EEG"',
    "lsl:a\tb",
])
def test_parse_lsl_spec_rejects(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_lsl_spec(spec)


def test_open_lsl_source_builds_an_unstarted_source() -> None:
    src = open_lsl_source("lsl:type=EMG", timeout_s=0.5)
    assert isinstance(src, LSLBlockSource)
    assert src.spec == LslSpec("type", "EMG")
    assert src.available is False and src.fs == 0.0 and src.channels == ()
    assert isinstance(src, BlockSource)


@pytest.mark.parametrize("kw", [
    {"prop": "hostname"}, {"timeout_s": 0.0}, {"timeout_s": float("nan")}, {"block_s": -1.0},
])
def test_constructor_validates(kw: dict) -> None:
    with pytest.raises(ValueError):
        LSLBlockSource("Muse", **kw)


def test_constructor_refuses_a_quote_that_would_rewrite_the_query() -> None:
    with pytest.raises(ValueError):
        LSLBlockSource("x' or name='y")


# ====================================================================================
# stream selection
# ====================================================================================


def _summary(name: str = "Muse", type_: str = "EEG", **kw: Any) -> StreamSummary:
    base: dict[str, Any] = {"channel_count": 4, "nominal_srate": 256.0, "channel_format": 1}
    base.update(kw)
    return StreamSummary(name, type_, **base)


def test_select_stream_picks_the_single_match() -> None:
    a, b = _summary("Muse", uid="1"), _summary("Muse PPG", "PPG", uid="2")
    assert select_stream([a, b], LslSpec("name", "Muse")) is a
    assert select_stream([a, b], LslSpec("type", "PPG")) is b


def test_select_stream_counts_one_outlet_once() -> None:
    a = _summary(uid="same")
    assert select_stream([a, _summary(uid="same")], LslSpec("type", "EEG")) is a


def test_select_stream_fails_closed_on_ambiguity() -> None:
    a, b = _summary("Muse", source_id="A", uid="1"), _summary("obci", source_id="B", uid="2")
    with pytest.raises(LslStreamError, match="2 LSL streams match") as err:
        select_stream([a, b], LslSpec("type", "EEG"))
    assert "source_id=A" in str(err.value) and "source_id=B" in str(err.value)


def test_select_stream_none_and_exact_match_only() -> None:
    with pytest.raises(LslStreamError, match="no LSL stream"):
        select_stream([_summary("muse")], LslSpec("name", "Muse"))
    with pytest.raises(LslStreamError):
        select_stream([], LslSpec("type", "EEG"))


@pytest.mark.parametrize(("kw", "match"), [
    ({"nominal_srate": 0.0}, "irregular"),
    ({"nominal_srate": float("nan")}, "irregular"),
    ({"channel_format": 3}, "not numeric"),
    ({"channel_format": 0}, "not numeric"),
    ({"channel_count": 0}, "no channels"),
])
def test_check_stream_usable_fails_closed(kw: dict, match: str) -> None:
    with pytest.raises(LslStreamError, match=match):
        check_stream_usable(_summary(**kw))


@pytest.mark.parametrize("fmt", [1, 2, 4, 5, 6, 7])
def test_check_stream_usable_accepts_numeric_formats(fmt: int) -> None:
    check_stream_usable(_summary(channel_format=fmt))


@pytest.mark.parametrize(("stream", "local", "ok"), [
    ("", "laptop", True),
    ("laptop", "laptop", True),
    ("Laptop.local", "laptop", True),
    ("laptop.example.org", "LAPTOP", True),
    ("other-pc", "laptop", False),
])
def test_is_local_host(stream: str, local: str, ok: bool) -> None:
    assert is_local_host(stream, local) is ok


# ====================================================================================
# channel metadata
# ====================================================================================


def test_parse_channel_metadata_reads_label_type_unit() -> None:
    xml = _channels_xml([("TP9", "EEG", "microvolts"), ("Right AUX", "AUX", "")])
    assert parse_channel_metadata(xml) == [
        LslChannelMeta("TP9", "EEG", "microvolts"), LslChannelMeta("Right AUX", "AUX", "")]


def test_parse_channel_metadata_partial_fields() -> None:
    xml = "<info><desc><channels><channel><label>C3</label></channel></channels></desc></info>"
    assert parse_channel_metadata(xml) == [LslChannelMeta("C3", "", "")]


@pytest.mark.parametrize("xml", ["", "<info><desc/></info>", "<info><desc>", "not xml"])
def test_parse_channel_metadata_absent_or_broken_is_empty(xml: str) -> None:
    assert parse_channel_metadata(xml) == []


def test_parse_channel_metadata_ignores_an_oversized_description() -> None:
    big = _channels_xml([("C3", "EEG", "uV")]).replace("<name>x</name>",
                                                       "<name>" + "x" * (1 << 20) + "</name>")
    assert parse_channel_metadata(big) == []


@pytest.mark.parametrize(("unit", "scale"), [
    ("", 1.0), ("microvolts", 1.0), ("uV", 1.0), ("µV", 1.0), ("μV", 1.0),
    ("mV", 1e3), ("millivolts", 1e3), ("V", 1e6), ("volts", 1e6), ("nV", 1e-3),
    (" micro volts ", 1.0),
])
def test_unit_scale_to_uv(unit: str, scale: float) -> None:
    assert unit_scale_to_uv(unit) == pytest.approx(scale)


@pytest.mark.parametrize("unit", ["counts", "normalized", "g", "%"])
def test_unit_scale_to_uv_unknown_is_none(unit: str) -> None:
    assert unit_scale_to_uv(unit) is None


def test_resolve_channels_without_metadata_inherits_the_stream_type() -> None:
    lay = resolve_channels("EMG", 2, [])
    assert lay.channels == (ChannelInfo("EMG1", SignalKind.EMG), ChannelInfo("EMG2", SignalKind.EMG))
    assert lay.indices == (0, 1) and lay.scales == (1.0, 1.0)


def test_resolve_channels_uses_per_channel_types_and_drops_the_rest() -> None:
    metas = [LslChannelMeta("Fp1", "EEG", "uV"), LslChannelMeta("ax", "ACC", "g"),
             LslChannelMeta("EOG_V", "EOG", "mV"), LslChannelMeta("C3", "", "")]
    lay = resolve_channels("EEG", 4, metas)
    assert lay.indices == (0, 2, 3)
    assert lay.channels == (ChannelInfo("Fp1", SignalKind.EEG), ChannelInfo("EOG_V", SignalKind.EOG),
                            ChannelInfo("C3", SignalKind.EEG))
    assert lay.scales == (1.0, 1e3, 1.0)


def test_resolve_channels_disambiguates_repeated_labels() -> None:
    metas = [LslChannelMeta("X", "EMG"), LslChannelMeta("X", "EMG"), LslChannelMeta("X", "EMG")]
    assert [c.name for c in resolve_channels("EMG", 3, metas).channels] == ["X", "X#2", "X#3"]


def test_resolve_channels_ignores_misaligned_metadata(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        lay = resolve_channels("EEG", 3, [LslChannelMeta("Fp1", "EEG")])
    assert [c.name for c in lay.channels] == ["EEG1", "EEG2", "EEG3"]
    assert "ignoring the channel metadata" in caplog.text


def test_resolve_channels_override_turns_aux_into_emg() -> None:
    metas = [LslChannelMeta("TP9", "EEG"), LslChannelMeta("Right AUX", "AUX")]
    lay = resolve_channels("EEG", 2, metas, channel_kinds={"Right AUX": "emg"})
    assert lay.indices == (1,)
    assert lay.channels == (ChannelInfo("Right AUX", SignalKind.EMG),)


def test_resolve_channels_override_of_an_unknown_name_warns(
        caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING), pytest.raises(LslStreamError):
        resolve_channels("EEG", 1, [], channel_kinds={"nope": SignalKind.EMG})
    assert "unknown LSL channel" in caplog.text


def test_resolve_channels_rejects_a_bad_override_kind() -> None:
    with pytest.raises(ValueError, match="unknown signal kind"):
        resolve_channels("EEG", 1, [], channel_kinds={"EEG1": "ecg"})


def test_resolve_channels_fails_closed_on_a_non_voltage_unit() -> None:
    with pytest.raises(LslStreamError, match="not a voltage"):
        resolve_channels("EEG", 1, [LslChannelMeta("C3", "EEG", "counts")])


def test_resolve_channels_uv_scale_overrides_units() -> None:
    lay = resolve_channels("EEG", 1, [LslChannelMeta("C3", "EEG", "counts")], uv_scale=0.02235)
    assert lay.scales == (pytest.approx(0.02235),)


@pytest.mark.parametrize("stream_type", ["Markers", "ExG", ""])
def test_resolve_channels_with_nothing_usable_fails_closed(stream_type: str) -> None:
    with pytest.raises(LslStreamError, match="channel_kinds"):
        resolve_channels(stream_type, 2, [])


# ====================================================================================
# timeline: LSL timestamps -> t0, gaps, blocks
# ====================================================================================

FS = 100.0
CH = (ChannelInfo("EMG1", SignalKind.EMG),)


def _chunk(start_ts: float, n: int, *, first: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    data = (first + np.arange(n, dtype=np.float64))[None, :]
    return data, start_ts + np.arange(n) / FS


def _drain(tl: LslTimeline) -> list:
    out = []
    while (blk := tl.pop()) is not None:
        out.append(blk)
    return out


def test_timeline_starts_at_zero_and_stays_continuous() -> None:
    tl = LslTimeline(FS, CH)
    tl.push(*_chunk(5000.0, 10))
    tl.push(*_chunk(5000.1, 10, first=10))
    blocks = _drain(tl)
    assert [b.t0 for b in blocks] == pytest.approx([0.0, 0.1])
    assert np.concatenate([b.data for b in blocks], axis=1)[0].tolist() == list(range(20))
    assert tl.origin == 5000.0 and tl.gap_samples == 0


def test_timeline_snaps_jitter() -> None:
    tl = LslTimeline(FS, CH)
    tl.push(*_chunk(10.0, 10))
    data, ts = _chunk(10.1, 10)
    tl.push(data, ts + 0.03)                      # 30 ms late: under the 50 ms tolerance
    assert [b.t0 for b in _drain(tl)] == pytest.approx([0.0, 0.1])
    assert tl.gap_samples == 0


def test_timeline_detects_a_gap_inside_a_chunk() -> None:
    tl = LslTimeline(FS, CH, min_samples=1000)
    ts = np.concatenate([10.0 + np.arange(5) / FS, 10.0 + 0.5 + np.arange(5) / FS])
    tl.push(np.arange(10, dtype=np.float64)[None, :], ts)
    first = tl.pop()
    assert first is not None and first.t0 == pytest.approx(0.0) and first.n_samples == 5
    assert tl.pop() is None                       # post-gap samples wait for min_samples
    assert tl.gap_samples == 45                   # 0.5 s - 5 samples at 100 Hz
    tl.push(*_chunk(10.55, 1000, first=5))
    second = tl.pop()
    assert second is not None and second.t0 == pytest.approx(0.5)
    assert second.data[0, 0] == 5


def test_timeline_never_rewinds() -> None:
    tl = LslTimeline(FS, CH)
    tl.push(*_chunk(10.0, 10))
    tl.push(*_chunk(9.0, 10))                     # clock stepped back by a second
    blocks = _drain(tl)
    assert [b.t0 for b in blocks] == pytest.approx([0.0, 0.1])
    assert tl.gap_samples == 0


def test_timeline_accumulates_to_min_samples() -> None:
    tl = LslTimeline(FS, CH, min_samples=4)
    tl.push(*_chunk(0.0, 3))
    assert tl.pop() is None
    tl.push(*_chunk(0.03, 2, first=3))
    blk = tl.pop()
    assert blk is not None and blk.n_samples == 5 and blk.t0 == 0.0


def test_timeline_tolerates_missing_timestamps() -> None:
    tl = LslTimeline(FS, CH)
    data, ts = _chunk(1.0, 4)
    ts[2] = np.nan
    tl.push(data, ts)
    blk = tl.pop()
    assert blk is not None and blk.n_samples == 4 and tl.gap_samples == 0


def test_timeline_rejects_mismatched_lengths_and_bad_fs() -> None:
    with pytest.raises(ValueError):
        LslTimeline(FS, CH).push(np.zeros((1, 3)), np.zeros(2))
    with pytest.raises(ValueError):
        LslTimeline(0.0, CH)


# ====================================================================================
# confinement: liblsl must be pinned to this machine before its first call
# ====================================================================================


def test_the_pinned_config_is_machine_scoped_with_no_peers() -> None:
    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # type: ignore[assignment,method-assign]
    cfg.read_string(LIBLSL_CONFIG)
    assert cfg["multicast"]["ResolveScope"] == "machine"
    assert cfg["multicast"]["MachineAddresses"] == "{127.0.0.1}"
    assert cfg["multicast"]["TTLOverride"] == "0"
    assert cfg["lab"]["KnownPeers"] == "{}"


def _start(monkeypatch: pytest.MonkeyPatch, infos: list[FakeInfo], chunks: list | None = None,
           **kw: Any) -> tuple[LSLBlockSource, Any]:
    fake = _install(monkeypatch, make_fake_pylsl(infos, chunks,
                                                 fail_pull=kw.pop("fail_pull", False),
                                                 with_content_setter=kw.pop("setter", True)))
    src = LSLBlockSource(kw.pop("stream", "obci_eeg1"), **kw)
    src.start()
    return src, fake


def test_resolve_runs_under_a_private_machine_only_config(monkeypatch: pytest.MonkeyPatch) -> None:
    src, fake = _start(monkeypatch, [FakeInfo()])
    assert src.available, src.last_error
    names = [c[0] for c in fake.calls]
    assert names.index("set_config_content") < names.index("resolve_byprop")
    assert fake.calls[names.index("set_config_content")][1] == LIBLSL_CONFIG
    _, _, _, _, cfg_path, cfg_text, mode = fake.calls[names.index("resolve_byprop")]
    assert cfg_text == LIBLSL_CONFIG
    if os.name != "nt":
        assert mode == oct(0o600)
    # Afterwards: the variable is gone again and the private file is deleted.
    assert "LSLAPICFG" not in os.environ
    assert not Path(cfg_path).exists() and not Path(cfg_path).parent.exists()


def test_a_users_lslapicfg_is_overridden_then_restored(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    wide = tmp_path / "lsl_api.cfg"
    wide.write_bytes(b"[multicast]\nResolveScope = global\n")
    monkeypatch.setenv("LSLAPICFG", str(wide))
    with caplog.at_level(logging.INFO, logger="yazses.biosignal.lsl_source"):
        src, fake = _start(monkeypatch, [FakeInfo()])
    assert src.available
    resolve = next(c for c in fake.calls if c[0] == "resolve_byprop")
    assert resolve[4] != str(wide) and resolve[5] == LIBLSL_CONFIG
    assert os.environ["LSLAPICFG"] == str(wide)
    assert "Ignoring LSLAPICFG" in caplog.text


def test_the_env_file_alone_still_pins_an_old_liblsl(monkeypatch: pytest.MonkeyPatch) -> None:
    src, fake = _start(monkeypatch, [FakeInfo()], setter=False)
    assert src.available
    resolve = next(c for c in fake.calls if c[0] == "resolve_byprop")
    assert resolve[5] == LIBLSL_CONFIG


def test_the_pin_happens_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    src, fake = _start(monkeypatch, [FakeInfo()])
    src.stop()
    src.start()
    assert [c[0] for c in fake.calls].count("set_config_content") == 1
    assert lsl_source._pinned is True


def test_a_failed_first_resolve_does_not_set_the_content_twice(
        monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, make_fake_pylsl([FakeInfo()]))
    def boom(wait_time: float = 0.0) -> list:
        raise RuntimeError("liblsl failed")
    fake.resolve_streams = boom
    with pytest.raises(RuntimeError):
        list_lsl_streams(timeout_s=0.0)
    assert lsl_source._pinned is True          # liblsl holds the content from here on
    with pytest.raises(RuntimeError):
        list_lsl_streams(timeout_s=0.0)
    assert [c[0] for c in fake.calls].count("set_config_content") == 1


def test_an_old_liblsl_is_pinned_again_after_a_failed_first_call(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Without in-memory content the pin is a file that is deleted afterwards. If that first
    call failed, nothing says liblsl read it, so the next call must not run without one."""
    fake = _install(monkeypatch, make_fake_pylsl([FakeInfo()], with_content_setter=False))
    seen: list[str | None] = []
    def boom(wait_time: float = 0.0) -> list:
        seen.append(os.environ.get("LSLAPICFG"))
        raise RuntimeError("liblsl failed")
    fake.resolve_streams = boom
    for _ in range(2):
        with pytest.raises(RuntimeError):
            list_lsl_streams(timeout_s=0.0)
    assert lsl_source._pinned is False
    assert all(seen) and len(seen) == 2


def test_list_lsl_streams_resolves_under_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, make_fake_pylsl([FakeInfo("Muse", source_id="M1")]))
    streams = list_lsl_streams(timeout_s=0.25)
    assert [s.name for s in streams] == ["Muse"] and streams[0].source_id == "M1"
    call = next(c for c in fake.calls if c[0] == "resolve_streams")
    assert call[1] == 0.25 and call[2]                # LSLAPICFG was set during the call


def test_the_module_opens_no_socket_of_its_own() -> None:
    """Belt and braces next to tests/test_egress_inventory.py: same roots, this file only."""
    roots = {"urllib", "http", "socket", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
             "asyncio", "webbrowser"}
    tree = ast.parse(Path(lsl_source.__file__).read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & roots


# ====================================================================================
# the source end to end (fake pylsl)
# ====================================================================================


def test_missing_pylsl_is_a_logged_no_op_naming_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pylsl", None)        # makes `import pylsl` fail
    with pytest.raises(ImportError, match="'lsl' extra"):
        lsl_source._import_pylsl()
    src = LSLBlockSource("Muse")
    src.start()
    assert src.available is False and "'lsl' extra" in src.last_error
    assert src.read() is None
    assert "LSLAPICFG" not in os.environ and lsl_source._pinned is False


def test_streams_scaled_blocks_with_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    xml = _channels_xml([("EMG_L", "EMG", "mV"), ("acc", "ACC", "g")])
    info = FakeInfo(channel_count=2, nominal_srate=FS, xml=xml)
    chunk = ([[0.001, 9.0], [0.002, 9.0], [0.003, 9.0], [0.004, 9.0]],
             [700.0, 700.01, 700.02, 700.03])
    chunk2 = ([[0.005, 9.0]] * 4, [700.04, 700.05, 700.06, 700.07])
    src, fake = _start(monkeypatch, [info], [chunk, chunk2], block_s=0.0)
    assert src.available, src.last_error
    assert src.fs == FS and src.channels == (ChannelInfo("EMG_L", SignalKind.EMG),)
    assert src.stream_info is not None and src.stream_info.name == "obci_eeg1"
    inlet = fake.inlets[0]
    assert inlet.kw["processing_flags"] == 1 and inlet.kw["recover"] is True
    assert ("open_stream", 2.0) in fake.calls
    b1 = src.read()
    assert b1 is not None and b1.t0 == 0.0 and b1.data.shape == (1, 4)
    assert b1.data[0].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0])     # mV -> µV
    b2 = src.read()
    assert b2 is not None and b2.t0 == pytest.approx(0.04)
    assert src.read() is None and src.gap_samples == 0
    src.stop()
    assert inlet.closed and src.available is False and src.read() is None


def test_block_s_sets_the_minimum_block(monkeypatch: pytest.MonkeyPatch) -> None:
    info = FakeInfo(channel_count=1, nominal_srate=FS, type_="EMG")
    chunks = [([[1.0]] * 2, [1.0, 1.01]), ([[1.0]] * 2, [1.02, 1.03])]
    src, _ = _start(monkeypatch, [info], chunks, block_s=0.04)
    assert src.read() is None
    blk = src.read()
    assert blk is not None and blk.n_samples == 4


@pytest.mark.parametrize(("info", "match"), [
    (FakeInfo(nominal_srate=0.0), "irregular"),
    (FakeInfo(channel_format=3), "not numeric"),
    (FakeInfo(hostname="someone-elses-pc"), "not this machine"),
    (FakeInfo(type_="Markers"), "channel_kinds"),
    (FakeInfo(name="other"), "no LSL stream"),
])
def test_unusable_streams_leave_the_source_unavailable(
        monkeypatch: pytest.MonkeyPatch, info: FakeInfo, match: str) -> None:
    src, fake = _start(monkeypatch, [info])
    assert src.available is False
    assert match in src.last_error
    assert src.read() is None
    assert all(i.closed for i in fake.inlets)


def test_ambiguous_type_match_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    src, _ = _start(monkeypatch, [FakeInfo("a", source_id="1"), FakeInfo("b", source_id="2")],
                    stream="EEG", prop="type")
    assert src.available is False and "2 LSL streams match" in src.last_error


def test_a_lost_stream_fails_closed_on_read(monkeypatch: pytest.MonkeyPatch) -> None:
    src, fake = _start(monkeypatch, [FakeInfo()], fail_pull=True)
    assert src.available
    assert src.read() is None
    assert src.available is False and "stopped streaming" in src.last_error
    assert fake.inlets[0].closed


def test_a_wrongly_shaped_chunk_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    src, _ = _start(monkeypatch, [FakeInfo(channel_count=2)], [([[1.0, 2.0, 3.0]], [1.0])])
    assert src.read() is None
    assert src.available is False and "expected (n, 2)" in src.last_error


def test_channel_kinds_and_uv_scale_reach_the_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    xml = _channels_xml([("TP9", "EEG", "microvolts"), ("Right AUX", "AUX", "counts")])
    src, _ = _start(monkeypatch, [FakeInfo(channel_count=2, xml=xml)],
                    [([[5.0, 2.0]], [3.0])], channel_kinds={"Right AUX": "emg"}, uv_scale=0.5,
                    block_s=0.0)
    assert src.channels == (ChannelInfo("Right AUX", SignalKind.EMG),)
    blk = src.read()
    assert blk is not None and blk.data[0, 0] == pytest.approx(1.0)
