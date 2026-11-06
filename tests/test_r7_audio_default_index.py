"""The OS default input is marked by PortAudio's *index*, not guessed from its name.

``sounddevice.default.device`` is an ``_InputOutputPair`` -- an object with
``__getitem__`` that is neither a ``list`` nor a ``tuple``. ``_default_input_index``
only indexed into lists and tuples, so for the real object it fell through to
``int(pair)``, which raises ``TypeError``; the ``except`` turned that into ``None`` on
every call. The index path was dead, and every caller fell back to matching the default
by *name* -- which marks every device sharing that name as the default (two identical
USB microphones, or the same microphone listed once per host API).

Synthetic and Linux-only: a stand-in ``sounddevice`` module is placed in
``sys.modules``, so no PortAudio, audio server or real device is touched. The stand-in
pair mirrors the shape of ``sounddevice._InputOutputPair`` (``__getitem__`` and
``__repr__`` only).
"""
from __future__ import annotations

import sys
import types

import pytest

from yazses.audio import devices


class _PairLike:
    """Same surface as ``sounddevice._InputOutputPair``: indexable, not a sequence type."""

    def __init__(self, inp, out):
        self._pair = [inp, out]

    def __getitem__(self, index):
        index = {"input": 0, "output": 1}.get(index, index)
        return self._pair[index]

    def __repr__(self):
        return "[{0[0]!r}, {0[1]!r}]".format(self)


def _fake_sd(default_pair, default_name="USB Mic"):
    mod = types.ModuleType("sounddevice")
    mod.default = types.SimpleNamespace(device=default_pair)

    def query_devices(device=None, kind=None):
        if kind == "input":
            return {"name": default_name}
        raise AssertionError("unexpected query")

    mod.query_devices = query_devices
    return mod


@pytest.fixture
def fake_sd(monkeypatch):
    def install(pair, name="USB Mic"):
        monkeypatch.setitem(sys.modules, "sounddevice", _fake_sd(pair, name))

    return install


def test_default_index_is_read_from_an_input_output_pair(fake_sd):
    fake_sd(_PairLike(3, 5))
    assert devices._default_input_index() == 3


def test_unset_default_in_a_pair_is_none(fake_sd):
    fake_sd(_PairLike(-1, -1))
    assert devices._default_input_index() is None


def test_plain_int_and_tuple_defaults_still_work(fake_sd):
    fake_sd(4)
    assert devices._default_input_index() == 4
    fake_sd((2, 7))
    assert devices._default_input_index() == 2


def test_an_explicit_default_name_does_not_consult_portaudio(monkeypatch):
    # With the index path alive, a caller that passes only ``default_name`` must still
    # get that hint honoured, not the host's real default index.
    def boom():
        raise AssertionError("PortAudio consulted despite an explicit hint")

    monkeypatch.setattr(devices, "_default_input_index", boom)
    monkeypatch.setattr(devices, "current_default_input_name", boom)
    raw = [{"name": "hw mic", "max_input_channels": 1},
           {"name": "default", "max_input_channels": 2}]
    found = devices.list_input_devices(query=lambda: raw, default_name="default")
    assert [d.index for d in found if d.is_default] == [1]


def test_only_the_default_index_is_marked_among_duplicate_names(fake_sd):
    # Two identical microphones; PortAudio's default input is the second one (index 2).
    fake_sd(_PairLike(2, 0), name="USB Mic")
    raw = [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "USB Mic", "max_input_channels": 1},
        {"name": "USB Mic", "max_input_channels": 1},
    ]
    found = devices.list_input_devices(query=lambda: raw)
    marked = [d.index for d in found if d.is_default]
    assert marked == [2]
