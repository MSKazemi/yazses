"""Tests for ``yazses.biosignal.boards``: the table of known boards and ``preset_for``.

Pure data. Spec strings are checked by parsing them with ``open_source`` -- constructing a
source never opens hardware (``start()`` is never called) and BrainFlow is never imported.
"""

from __future__ import annotations

import sys

import pytest

from yazses.biosignal.bitalino import BITalinoSource
from yazses.biosignal.boards import (
    BRAINFLOW_SYNTHETIC_ID,
    BoardPreset,
    known_boards,
    preset_for,
    unit_of,
)
from yazses.biosignal.lsl_source import LSLBlockSource
from yazses.biosignal.myo import MyoSource
from yazses.biosignal.sources import (
    SYNTHETIC_BOARD_ID,
    BrainFlowBlockSource,
    SyntheticSource,
    open_source,
)
from yazses.biosignal.thinkgear import ThinkGearSource

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
    # A template still holding its placeholder (`thinkgear:<port>`, `myo:<address>`) is not
    # a spec a user can open as written; the real-value tests below cover those.
    if spec and "<" not in spec:
        open_source(spec)


def test_parsing_specs_never_imports_brainflow(monkeypatch: pytest.MonkeyPatch):
    """With brainflow made un-importable, building every spec still works."""
    monkeypatch.setitem(sys.modules, "brainflow", None)
    monkeypatch.setitem(sys.modules, "brainflow.board_shim", None)
    for preset in ALL:
        spec = preset.source_spec()
        if spec and "<" not in spec:
            open_source(spec)
        # preset_for reads BrainFlow, synthetic and the four device schemes from the spec; the
        # DIY serial device has no spec, so it is found by its name.
        lookup = spec if spec else preset.name
        assert preset_for(lookup) is not None


NON_BRAINFLOW = [b for b in ALL if b.spec_template]
NON_BRAINFLOW_NAMES = ("lsl-stream", "neurosky-thinkgear", "bitalino", "myo")
REAL_PORT = "/dev/ttyUSB0"
REAL_MYO_ADDRESS = "AA:BB:CC:DD:EE:FF"


def test_non_brainflow_presets_are_exactly_the_four_new_sources():
    assert tuple(b.name for b in NON_BRAINFLOW) == NON_BRAINFLOW_NAMES
    for b in NON_BRAINFLOW:
        assert b.board_id is None
        assert b.spec_template.split(":", 1)[0] in ("lsl", "thinkgear", "bitalino", "myo")


def test_non_brainflow_presets_follow_the_brainflow_rows():
    """Hardware-free and BrainFlow rows come first; the new sources are appended after."""
    index = {b.name: i for i, b in enumerate(ALL)}
    last_brainflow = max(i for i, b in enumerate(ALL) if b.board_id is not None)
    assert min(index[n] for n in NON_BRAINFLOW_NAMES) > last_brainflow


@pytest.mark.parametrize(
    ("name", "extra"),
    [
        ("lsl-stream", "`lsl` extra"),
        ("neurosky-thinkgear", "`emg` extra"),
        ("bitalino", "`emg` extra"),
        ("myo", "`ble` extra"),
    ],
)
def test_non_brainflow_notes_name_their_extra(name: str, extra: str):
    preset = preset_for(name)
    assert preset is not None
    assert extra in preset.notes
    assert "emg-band" not in preset.notes


def test_lsl_stream_spec_is_the_fixed_type_query():
    preset = preset_for("lsl-stream")
    assert preset is not None
    assert preset.kind_hint == "mixed"
    assert preset.serial_required is False
    assert preset.source_spec() == "lsl:type=EEG"
    assert preset.source_spec("/dev/ttyUSB0") == "lsl:type=EEG"


@pytest.mark.parametrize(
    ("name", "template"),
    [
        ("neurosky-thinkgear", "thinkgear:<port>"),
        ("bitalino", "bitalino:<port>"),
    ],
)
def test_serial_templates_substitute_the_port(name: str, template: str):
    preset = preset_for(name)
    assert preset is not None
    assert preset.serial_required is True
    assert preset.spec_template == template
    # No port: the placeholder stays, which is what `yazses biosignal boards` prints.
    assert preset.source_spec() == template
    assert preset.source_spec("") == template
    assert preset.source_spec("<port>") == template
    # A real-looking port is substituted, stripped of surrounding whitespace.
    assert preset.source_spec(f"  {REAL_PORT} ") == template.replace("<port>", REAL_PORT)
    assert preset.source_spec("COM3") == template.replace("<port>", "COM3")


def test_myo_template_keeps_its_address_placeholder():
    preset = preset_for("myo")
    assert preset is not None
    assert preset.serial_required is False
    assert preset.kind_hint == "emg"
    assert preset.spec_template == "myo:<address>"
    assert preset.source_spec() == "myo:<address>"
    assert preset.source_spec("  ") == "myo:<address>"


@pytest.mark.parametrize("name", NON_BRAINFLOW_NAMES)
def test_non_brainflow_specs_open_with_real_values_without_hardware(
    name: str, monkeypatch: pytest.MonkeyPatch,
):
    """Built with a real port/address, each spec parses to its source class; pylsl, serial
    and bleak are made un-importable, so construction cannot touch them."""
    for mod in ("pylsl", "serial", "bleak"):
        monkeypatch.setitem(sys.modules, mod, None)
    preset = preset_for(name)
    assert preset is not None
    if name == "myo":
        spec = preset.spec_template.replace("<address>", REAL_MYO_ADDRESS)
    else:
        spec = preset.source_spec(REAL_PORT)
    expected = {
        "lsl-stream": LSLBlockSource,
        "neurosky-thinkgear": ThinkGearSource,
        "bitalino": BITalinoSource,
        "myo": MyoSource,
    }[name]
    src = open_source(spec)                           # parse only: start() is never called
    assert isinstance(src, expected)


def test_real_port_reaches_the_bitalino_and_thinkgear_sources():
    src = open_source(preset_for("bitalino").source_spec(REAL_PORT))  # type: ignore[union-attr]
    assert isinstance(src, BITalinoSource)
    assert src.port == REAL_PORT
    tg = open_source(preset_for("neurosky-thinkgear").source_spec(REAL_PORT))  # type: ignore[union-attr]
    assert isinstance(tg, ThinkGearSource)
    assert tg.port == REAL_PORT


def test_real_myo_address_reaches_the_source():
    spec = preset_for("myo").spec_template.replace("<address>", REAL_MYO_ADDRESS)  # type: ignore[union-attr]
    assert spec == f"myo:{REAL_MYO_ADDRESS}"
    src = open_source(spec)
    assert isinstance(src, MyoSource)


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


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("lsl:type=EEG", "lsl-stream"),
        ("lsl:Muse", "lsl-stream"),
        ("lsl:source_id=abc-123", "lsl-stream"),
        ("LSL:type=EEG", "lsl-stream"),
        ("thinkgear:/dev/rfcomm0", "neurosky-thinkgear"),
        ("thinkgear:COM3:baud=57600,name=Fp1", "neurosky-thinkgear"),
        ("thinkgear:<port>", "neurosky-thinkgear"),
        ("bitalino:COM5:A1=emg,fs=1000", "bitalino"),
        ("bitalino:/dev/ttyUSB0", "bitalino"),
        ("myo:AA:BB:CC:DD:EE:FF", "myo"),
        ("myo:<address>", "myo"),
        ("  myo:AA:BB:CC:DD:EE:FF  ", "myo"),
    ],
)
def test_preset_for_resolves_the_device_schemes(spec: str, expected: str):
    """The four non-BrainFlow sources resolve from their spec, so `doctor` can advise on them."""
    found = preset_for(spec)
    assert found is not None
    assert found.name == expected
    assert found.board_id is None


@pytest.mark.parametrize("spec", ["lsl", "thinkgear", "bitalino2:COM5", "myo2:x", "nope:x"])
def test_unlisted_or_bare_scheme_is_still_none(spec: str):
    assert preset_for(spec) is None


def test_device_scheme_resolution_never_yields_a_brainflow_id():
    """`brainflow:` ids come only from the BrainFlow rows; no device scheme may add one."""
    for spec in ("lsl:type=EEG", "thinkgear:/dev/rfcomm0", "bitalino:COM5", "myo:AA:BB:CC:DD:EE:FF"):
        found = preset_for(spec)
        assert found is not None and found.board_id is None
        assert not found.source_spec().startswith("brainflow:")


def test_count_unit_presets_are_the_myo_and_the_gforce_armbands():
    assert {b.name for b in ALL if b.unit == "counts"} == {"gforce-pro", "gforce-dual", "myo"}
    assert {b.unit for b in ALL} <= {"uV", "counts"}


@pytest.mark.parametrize(
    ("spec", "unit"),
    [
        ("myo:AA:BB:CC:DD:EE:FF", "counts"),
        ("brainflow:16", "counts"),
        ("brainflow:19:/dev/ttyUSB0", "counts"),
        ("brainflow:38", "uV"),
        ("brainflow:12345", "uV"),
        ("synthetic", "uV"),
        ("lsl:type=EEG", "uV"),
        ("thinkgear:/dev/rfcomm0", "uV"),
        ("bitalino:COM5", "uV"),
        ("file:session.csv", "uV"),
        ("", "uV"),
    ],
)
def test_unit_of_says_what_the_source_reports(spec: str, unit: str):
    assert unit_of(spec) == unit


def test_preset_for_bool_is_not_an_id():
    """True == 1 in Python, and 1 is the Ganglion; a bool must not find it."""
    assert preset_for(1) is not None
    assert preset_for(True) is None
    assert preset_for(False) is None


#: BrainFlow's boards that stream over a network socket, from `brainflow.board_shim.BoardIds`
#: (read from brainflow on 2026-11-01): STREAMING -2, GALEA 3, GANGLION_WIFI 4, CYTON_WIFI 5,
#: CYTON_DAISY_WIFI 6, NTL_WIFI 50, AAVAA_V3 53, BIOLISTENER 64.
NETWORK_BOARD_IDS = (-2, 3, 4, 5, 6, 50, 53, 64)


@pytest.mark.parametrize("board_id", NETWORK_BOARD_IDS)
def test_a_network_board_is_refused_before_anything_opens(board_id):
    with pytest.raises(ValueError, match="nothing may leave this machine"):
        open_source(f"brainflow:{board_id}")


def test_the_table_lists_no_network_board():
    assert not {b.board_id for b in known_boards()} & set(NETWORK_BOARD_IDS)


def test_an_unlisted_brainflow_id_is_refused():
    assert preset_for("brainflow:12345") is None
    with pytest.raises(ValueError, match="biosignal boards"):
        open_source("brainflow:12345")


def test_every_listed_brainflow_board_opens():
    ids = [b.board_id for b in known_boards() if b.board_id is not None]
    assert ids
    for board_id in ids:
        assert isinstance(open_source(f"brainflow:{board_id}"), BrainFlowBlockSource)
