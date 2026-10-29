"""Known boards: a small, verified table of presets for ``[biosignal] source``.

Pure data and string handling -- stdlib only, no hardware access, no ``brainflow`` import.
A preset tells a person (and ``yazses biosignal doctor``) what a board is, what it can
measure and which ``source`` string to write; it never opens anything.

**Every BrainFlow board id here was read from the installed package**, not remembered:
``brainflow.board_shim.BoardIds`` and the static ``BoardShim`` getters (device name,
sampling rate, EEG/EMG/EOG channel counts and the EEG electrode names) on BrainFlow 5.23.0,
which is what the ``emg-band`` extra (``brainflow>=5.22.2``) installs. A board whose id could
not be verified is left out rather than guessed; :func:`preset_for` returns ``None`` for it,
and ``brainflow:<id>`` still *works* for any id BrainFlow itself knows
(``yazses biosignal doctor --boards`` lists them). The hints are advice for choosing a
source and placing electrodes, not a promise about firmware or a given unit.

Boards whose connection needs an IP address (the OpenBCI WiFi shields) are not listed:
``brainflow:<board_id>[:<serial_port>]`` has nowhere to carry one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: BrainFlow's synthetic board id (``BoardIds.SYNTHETIC_BOARD``), the same constant the
#: ``brainflow:`` source scheme documents.
BRAINFLOW_SYNTHETIC_ID = -1

_EXTRA_NOTE = "needs the `emg-band` extra (BrainFlow)"


@dataclass(frozen=True)
class BoardPreset:
    """One way of getting samples in, as a plain description.

    ``board_id`` is BrainFlow's integer id, or ``None`` for a path that is not a BrainFlow
    board (the built-in generator, the DIY serial device). ``kind_hint`` says which signal
    kinds the board is good for (``"emg"``, ``"eeg"``, ``"emg+eeg"``, ``"mixed"``);
    ``channels_hint`` is the channel count, sampling rate and any electrode names the
    package reports; ``serial_required`` is whether a serial port (a USB dongle or the
    device's own port) has to be given; ``notes`` is one line of plain advice.
    """

    name: str
    board_id: int | None
    kind_hint: str
    channels_hint: str
    serial_required: bool
    notes: str = ""

    def source_spec(self, serial_port: str = "") -> str:
        """The ``[biosignal] source`` string for this preset, or ``""`` when it has none.

        ``synthetic`` for the built-in generator; ``brainflow:<id>[:<port>]`` for a
        BrainFlow board (the port is added only when given -- a preset that needs one
        still produces a string without it, and ``serial_required`` says so). The DIY
        serial device is not a biosignal source: it is configured under ``[emg]`` and
        returns ``""``.
        """
        if self.board_id is None:
            return "synthetic" if self.name == "synthetic" else ""
        port = serial_port.strip()
        return f"brainflow:{self.board_id}" + (f":{port}" if port else "")


_BOARDS: tuple[BoardPreset, ...] = (
    BoardPreset(
        name="synthetic",
        board_id=None,
        kind_hint="mixed",
        channels_hint="2 frontal EEG + 2 EMG, generated (built-in)",
        serial_required=False,
        notes="No hardware and no extras: to try the pipeline, `yazses biosignal monitor` and "
              "`doctor`. Cannot be calibrated, since there is no body to calibrate on.",
    ),
    BoardPreset(
        name="diy-serial",
        board_id=None,
        kind_hint="emg",
        channels_hint="1 EMG, detected on the microcontroller",
        serial_required=True,
        notes="A MyoWare 2.0 or BioAmp EXG Pill on a microcontroller speaking the YESP serial "
              "protocol. Not a `[biosignal] source`: set `[emg] device_port` instead "
              "(needs the `emg` extra, pyserial).",
    ),
    BoardPreset(
        name="brainflow-synthetic",
        board_id=BRAINFLOW_SYNTHETIC_ID,
        kind_hint="mixed",
        channels_hint="16 channels at 250 Hz (Fz C3 Cz C4 Pz PO7 Oz PO8 F5 F7 F3 F1 F2 F4 F6 F8)",
        serial_required=False,
        notes=f"BrainFlow's own test board, no hardware; checks the BrainFlow install end to "
              f"end ({_EXTRA_NOTE}).",
    ),
    BoardPreset(
        name="openbci-cyton",
        board_id=0,
        kind_hint="emg+eeg",
        channels_hint="8 channels at 250 Hz (Fp1 Fp2 C3 C4 P7 P8 O1 O2)",
        serial_required=True,
        notes="OpenBCI Cyton over its USB dongle (e.g. /dev/ttyUSB0 on Linux). Pins can be "
              "EMG or EEG electrodes; say which per channel. " + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="openbci-ganglion",
        board_id=1,
        kind_hint="emg+eeg",
        channels_hint="4 channels at 200 Hz",
        serial_required=True,
        notes="OpenBCI Ganglion through a BLED112 USB dongle. Without a dongle use "
              "`openbci-ganglion-native` (board 46), which talks Bluetooth LE directly. "
              + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="openbci-cyton-daisy",
        board_id=2,
        kind_hint="emg+eeg",
        channels_hint="16 channels at 125 Hz (Fp1 Fp2 C3 C4 P7 P8 O1 O2 F7 F8 F3 F4 T7 T8 "
                      "P3 P4)",
        serial_required=True,
        notes="OpenBCI Cyton with the Daisy module over the Cyton's USB dongle; the sampling "
              "rate halves to 125 Hz. " + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="openbci-ganglion-native",
        board_id=46,
        kind_hint="emg+eeg",
        channels_hint="4 channels at 200 Hz",
        serial_required=False,
        notes="OpenBCI Ganglion over the computer's own Bluetooth LE, no dongle. "
              + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="unicorn",
        board_id=8,
        kind_hint="eeg",
        channels_hint="8 channels at 250 Hz (Fz C3 Cz C4 Pz PO7 Oz PO8)",
        serial_required=False,
        notes="g.tec Unicorn Hybrid Black over Bluetooth. EEG only; the frontal channels "
              "carry blinks. " + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="callibri-emg",
        board_id=10,
        kind_hint="emg",
        channels_hint="1 EMG channel at 1000 Hz",
        serial_required=False,
        notes="Neurotech Callibri electrode in EMG mode over Bluetooth LE: a ready-made "
              "single-muscle squeeze switch. " + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="muse-2",
        board_id=38,
        kind_hint="eeg",
        channels_hint="4 channels at 256 Hz (TP9 AF7 AF8 TP10)",
        serial_required=False,
        notes="Muse 2 over the computer's Bluetooth. Forehead sensors (AF7, AF8) pick up "
              "blinks and jaw clenches; it has no EMG channel. " + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="muse-s",
        board_id=39,
        kind_hint="eeg",
        channels_hint="4 channels at 256 Hz (TP9 AF7 AF8 TP10)",
        serial_required=False,
        notes="Muse S over the computer's Bluetooth. Same sensors as the Muse 2: blinks and "
              "jaw clenches, no EMG. " + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="muse-2-bled",
        board_id=22,
        kind_hint="eeg",
        channels_hint="4 channels at 256 Hz (TP9 AF7 AF8 TP10)",
        serial_required=True,
        notes="Muse 2 through a BLED112 USB dongle, for a computer whose own Bluetooth does "
              "not work with `muse-2`. " + _EXTRA_NOTE + ".",
    ),
    BoardPreset(
        name="muse-s-bled",
        board_id=21,
        kind_hint="eeg",
        channels_hint="4 channels at 256 Hz (TP9 AF7 AF8 TP10)",
        serial_required=True,
        notes="Muse S through a BLED112 USB dongle, for a computer whose own Bluetooth does "
              "not work with `muse-s`. " + _EXTRA_NOTE + ".",
    ),
)


def known_boards() -> tuple[BoardPreset, ...]:
    """Every preset, in a stable order: no-hardware options first, then boards by id."""
    return _BOARDS


def _norm(text: str) -> str:
    return re.sub(r"[\s_]+", "-", text.strip().lower())


def preset_for(name_or_id: str | int) -> BoardPreset | None:
    """The preset named ``name_or_id``, or ``None`` when there is none. Never raises.

    Accepts a preset name (case, spaces and underscores ignored: ``"Muse 2"`` finds
    ``muse-2``), a BrainFlow board id as an int or a digit string (``38``, ``"-1"``), or a
    whole ``[biosignal] source`` spec (``"brainflow:0:/dev/ttyUSB0"``, ``"synthetic"``).
    A BrainFlow id that is not in the table returns ``None`` -- the table is advice, and
    an id it does not list may still be a valid board.
    """
    if isinstance(name_or_id, bool):
        return None
    if isinstance(name_or_id, int):
        return next((b for b in _BOARDS if b.board_id == name_or_id), None)
    if not isinstance(name_or_id, str):
        return None
    text = name_or_id.strip()
    if not text:
        return None
    scheme, _, rest = text.partition(":")
    if scheme.strip().lower() == "brainflow":
        board = rest.partition(":")[0].strip()
        try:
            return preset_for(int(board))
        except ValueError:
            return None
    try:
        return preset_for(int(text))
    except ValueError:
        pass
    key = _norm(text)
    return next((b for b in _BOARDS if b.name == key), None)


__all__ = ["BRAINFLOW_SYNTHETIC_ID", "BoardPreset", "known_boards", "preset_for"]
