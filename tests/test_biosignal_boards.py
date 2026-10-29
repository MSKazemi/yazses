"""Tests for ``yazses.biosignal.boards``: the table of known boards and ``preset_for``.

Pure data. Spec strings are checked by parsing them with ``open_source`` -- constructing a
source never opens hardware (``start()`` is never called) and BrainFlow is never imported.
"""

from __future__ import annotations

import sys

import pytest

from yazses.biosignal.boards import (
    BRAINFLOW_SYNTHETIC_ID,
    BoardPreset,
    known_boards,
    preset_for,
)
from yazses.biosignal.sources import (
    SYNTHETIC_BOARD_ID,
    BrainFlowBlockSource,
    SyntheticSource,
    open_source,
)

ALL = known_boards()
BRAINFLOW_BOARDS = [b for b in ALL if b.board_id is not None]
KIND_HINTS = {"emg", "eeg", "emg+eeg", "mixed"}


def test_known_boards_is_non_empty_stable_and_typed():
    assert len(ALL) > 0
    assert known_boards() is ALL or known_boards() == ALL
    assert all(isinstance(b, BoardPreset) for b in ALL)


def test_names_are_unique_and_normalised():
    names = [b.name for b in ALL]
    assert len(names) == len(set(names))
    for name in names:
        assert name == name.strip().lower()
        assert " " not in name and "_" not in name


def test_board_ids_are_unique_ints():
    ids = [b.board_id for b in BRAINFLOW_BOARDS]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, int) and not isinstance(i, bool) for i in ids)


def test_includes_the_synthetic_boards():
    assert any(b.name == "synthetic" and b.board_id is None for b in ALL)
    assert any(b.board_id == -1 for b in ALL)
    assert BRAINFLOW_SYNTHETIC_ID == -1 == SYNTHETIC_BOARD_ID


def test_no_hardware_options_come_first():
    """Boards that need no hardware (generated, BrainFlow's synthetic) precede real devices."""
    assert ALL[0].name == "synthetic"
    needs_device = [i for i, b in enumerate(ALL) if b.board_id is not None and b.board_id >= 0]
    no_device_boards = [i for i, b in enumerate(ALL) if b.board_id == BRAINFLOW_SYNTHETIC_ID]
    assert no_device_boards and max(no_device_boards) < min(needs_device)


@pytest.mark.parametrize("preset", ALL, ids=lambda b: b.name)
def test_every_preset_is_fully_described(preset: BoardPreset):
    assert preset.kind_hint in KIND_HINTS
    assert preset.channels_hint.strip()
    assert preset.notes.strip()
    assert isinstance(preset.serial_required, bool)


@pytest.mark.parametrize("preset", ALL, ids=lambda b: b.name)
def test_presets_are_immutable(preset: BoardPreset):
    with pytest.raises(AttributeError):
        preset.name = "other"          # type: ignore[misc]


def test_extra_hint_only_on_presets_that_need_brainflow():
    for b in ALL:
        needs = "emg-band" in b.notes
        assert needs == (b.board_id is not None), b.name


# ------------------------------------------------------------------ source_spec


def test_synthetic_spec_is_synthetic_and_opens_without_hardware():
    preset = preset_for("synthetic")
    assert preset is not None
    assert preset.source_spec() == "synthetic"
    assert isinstance(open_source(preset.source_spec()), SyntheticSource)


def test_diy_serial_is_not_a_biosignal_source():
    preset = preset_for("diy-serial")
    assert preset is not None
    assert preset.board_id is None
    assert preset.source_spec() == ""
    assert preset.source_spec("/dev/ttyUSB0") == ""
    assert preset.serial_required is True


@pytest.mark.parametrize("preset", BRAINFLOW_BOARDS, ids=lambda b: b.name)
def test_brainflow_spec_round_trips_through_open_source(preset: BoardPreset):
    spec = preset.source_spec()
    assert spec == f"brainflow:{preset.board_id}"
    src = open_source(spec)                           # parse only: start() is never called
    assert isinstance(src, BrainFlowBlockSource)
    assert src._board_id == preset.board_id
    assert src._serial_port == ""
    assert src.available is False and src._board is None


@pytest.mark.parametrize("preset", BRAINFLOW_BOARDS, ids=lambda b: b.name)
def test_brainflow_spec_with_port_round_trips(preset: BoardPreset):
    spec = preset.source_spec("  /dev/ttyUSB0 ")
    assert spec == f"brainflow:{preset.board_id}:/dev/ttyUSB0"
    src = open_source(spec)
    assert isinstance(src, BrainFlowBlockSource)
    assert (src._board_id, src._serial_port) == (preset.board_id, "/dev/ttyUSB0")


def test_blank_port_adds_no_trailing_colon():
    preset = preset_for(0)
    assert preset is not None
    assert preset.source_spec("   ") == "brainflow:0"


def test_windows_port_survives_the_round_trip():
    preset = preset_for(0)
    assert preset is not None
    src = open_source(preset.source_spec("COM3"))
    assert isinstance(src, BrainFlowBlockSource)
    assert src._serial_port == "COM3"


@pytest.mark.parametrize("preset", ALL, ids=lambda b: b.name)
def test_every_nonempty_spec_is_accepted_by_open_source(preset: BoardPreset):
    spec = preset.source_spec()
    if spec:
        open_source(spec)


def test_parsing_specs_never_imports_brainflow(monkeypatch: pytest.MonkeyPatch):
    """With brainflow made un-importable, building every spec still works."""
    monkeypatch.setitem(sys.modules, "brainflow", None)
    monkeypatch.setitem(sys.modules, "brainflow.board_shim", None)
    for preset in ALL:
        spec = preset.source_spec()
        if spec:
            open_source(spec)
        assert preset_for(spec or preset.name) is not None


# ------------------------------------------------------------------ preset_for


@pytest.mark.parametrize("preset", ALL, ids=lambda b: b.name)
def test_preset_for_finds_every_preset_by_name(preset: BoardPreset):
    assert preset_for(preset.name) is preset


@pytest.mark.parametrize("preset", BRAINFLOW_BOARDS, ids=lambda b: b.name)
def test_preset_for_finds_brainflow_presets_by_every_id_form(preset: BoardPreset):
    assert preset_for(preset.board_id) is preset
    assert preset_for(str(preset.board_id)) is preset
    assert preset_for(f" {preset.board_id} ") is preset
    assert preset_for(preset.source_spec()) is preset
    assert preset_for(preset.source_spec("/dev/ttyUSB0")) is preset
    assert preset_for(preset.source_spec().upper()) is preset


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Muse 2", "muse-2"),
        ("muse_2", "muse-2"),
        ("  MUSE-S  ", "muse-s"),
        ("OpenBCI Cyton", "openbci-cyton"),
        ("openbci_cyton_daisy", "openbci-cyton-daisy"),
        ("synthetic", "synthetic"),
        (-1, "brainflow-synthetic"),
        ("-1", "brainflow-synthetic"),
        (0, "openbci-cyton"),
        ("0", "openbci-cyton"),
        (38, "muse-2"),
        ("brainflow:0:/dev/ttyUSB0", "openbci-cyton"),
        ("brainflow:-1", "brainflow-synthetic"),
        ("BrainFlow:46", "openbci-ganglion-native"),
    ],
)
def test_preset_for_lookup_forms(query, expected):
    found = preset_for(query)
    assert found is not None
    assert found.name == expected


def test_int_lookup_never_matches_the_boardless_presets():
    """``board_id`` is None for synthetic / diy-serial; no int may find them."""
    for query in (0, 1, -1, 99):
        found = preset_for(query)
        assert found is None or found.board_id == query


@pytest.mark.parametrize(
    "query",
    [
        "", "   ", "nonsense", "muse", "brainflow", "brainflow:", "brainflow:abc",
        "brainflow:99999", 99999, -2, "99999", "1.5", None, 3.5, [], b"muse-2", True, False,
    ],
)
def test_preset_for_unknown_returns_none_and_never_raises(query):
    assert preset_for(query) is None


def test_preset_for_bool_is_not_an_id():
    """True == 1 in Python, and 1 is the Ganglion; a bool must not find it."""
    assert preset_for(1) is not None
    assert preset_for(True) is None
    assert preset_for(False) is None


def test_unlisted_brainflow_id_still_opens_even_though_preset_for_says_none():
    """The table is advice: an id it does not list may still be a valid board."""
    assert preset_for("brainflow:12345") is None
    assert isinstance(open_source("brainflow:12345"), BrainFlowBlockSource)
