"""`[emg] ble_address` must actually build a source, not merely be readable (#164).

The setting was documented in `config.py`, described in the architecture reference,
and printed by `yazses doctor` as a flat `OK`. `core/daemon.py::_build_activation_sources`
read `device_port` and nothing else, so an armband paired over Bluetooth was
configured, reported healthy, and never connected — and there is no symptom to
notice, because the failure of a hotkey is silence, which is what a hotkey you are
not pressing also produces.

`BLEEMGBackend` duck-types the same `HotkeyBackend` and takes the same two
callbacks as the serial `EMGBackend`, so the fix is the same wiring with a different
transport. These tests pin that it stays wired, that the mode routing is shared
between the two transports rather than reimplemented for one, and that `doctor`
stops claiming OK for an address that cannot connect.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DAEMON = ROOT / "src" / "yazses" / "core" / "daemon.py"


class _Daemon:
    """The two attributes `_build_activation_sources` touches, and four callbacks.

    Calling the real constructor would load a model and open a socket. The method
    under test is a factory over config, so it is exercised unbound — which also
    means a rename of the callbacks it wires shows up here as an AttributeError
    rather than silently binding something else.
    """

    _modality_roles: dict[str, str] = {}

    def _on_hold_start(self, leaked: int) -> None: ...
    def _on_hold_end(self) -> None: ...
    def _on_command_hold_start(self, leaked: int) -> None: ...
    def _on_command_hold_end(self) -> None: ...


def _sources(monkeypatch: pytest.MonkeyPatch, **emg):
    """Run the real factory against a config stub, with both backends faked."""
    from yazses.core.daemon import Daemon as RealDaemon

    built: list[tuple[str, tuple]] = []

    class _Serial:
        def __init__(self, *a, **k) -> None:
            built.append(("serial", a))

    class _Ble:
        def __init__(self, *a, **k) -> None:
            built.append(("ble", a))

    import yazses.platform.emg.backend as serial_mod
    import yazses.platform.emg.ble_backend as ble_mod

    monkeypatch.setattr(serial_mod, "EMGBackend", _Serial)
    monkeypatch.setattr(ble_mod, "BLEEMGBackend", _Ble)

    class _Emg:
        device_port = emg.get("device_port", "")
        ble_address = emg.get("ble_address", "")
        baud_rate = 115200
        mode = emg.get("mode", "command")

    class _Cfg:
        emg = _Emg()

    out = RealDaemon._build_activation_sources(_Daemon(), _Cfg())
    return out, built


def test_nothing_is_built_when_neither_transport_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMG is off by default and must stay a no-op for everyone else."""
    sources, built = _sources(monkeypatch)
    assert sources == []
    assert built == []


def test_a_ble_address_alone_builds_a_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect: this returned an empty list, with no error and no log."""
    sources, built = _sources(monkeypatch, ble_address="AA:BB:CC:DD:EE:FF")
    assert len(sources) == 1
    assert [kind for kind, _ in built] == ["ble"]
    assert built[0][1][0] == "AA:BB:CC:DD:EE:FF"


def test_a_serial_port_alone_still_builds_exactly_one_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression risk of the change: don't break the transport that worked."""
    sources, built = _sources(monkeypatch, device_port="/dev/ttyUSB0")
    assert len(sources) == 1
    assert [kind for kind, _ in built] == ["serial"]


def test_both_transports_configured_builds_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two physical devices. Silently picking one for the user would be a guess."""
    sources, built = _sources(
        monkeypatch, device_port="/dev/ttyUSB0", ble_address="AA:BB:CC:DD:EE:FF"
    )
    assert len(sources) == 2
    assert sorted(kind for kind, _ in built) == ["ble", "serial"]


@pytest.mark.parametrize(
    "mode,expected_start",
    [("command", "_on_command_hold_start"), ("full_text", "_on_hold_start")],
)
def test_both_transports_share_one_mode_decision(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected_start: str
) -> None:
    """`[emg] mode` must route BLE exactly as it routes serial.

    Reimplementing the mode choice per transport is how the two drift: a squeeze
    over Bluetooth would dictate while the same squeeze over USB ran a command.
    """
    _, built = _sources(
        monkeypatch, device_port="/dev/ttyUSB0", ble_address="AA:BB", mode=mode
    )
    starts = {kind: args[-2] for kind, args in built}
    assert starts["serial"] == starts["ble"], "the two transports diverged on mode"
    assert starts["ble"].__name__ == expected_start


def test_a_failure_in_one_transport_does_not_take_the_other_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMG init must never be able to stop the daemon starting."""
    import yazses.platform.emg.backend as serial_mod
    import yazses.platform.emg.ble_backend as ble_mod
    from yazses.core.daemon import Daemon as RealDaemon

    class _Boom:
        def __init__(self, *a, **k) -> None:
            raise RuntimeError("no device")

    class _Ok:
        def __init__(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(serial_mod, "EMGBackend", _Boom)
    monkeypatch.setattr(ble_mod, "BLEEMGBackend", _Ok)

    class _Emg:
        device_port = "/dev/ttyUSB0"
        ble_address = "AA:BB"
        baud_rate = 115200
        mode = "command"

    class _Cfg:
        emg = _Emg()

    sources = RealDaemon._build_activation_sources(_Daemon(), _Cfg())
    assert len(sources) == 1, "the working transport was lost with the broken one"


def test_the_daemon_names_the_ble_backend_at_all() -> None:
    """Cheap backstop: the module was an entry in the orphan registry for a reason."""
    assert "BLEEMGBackend" in DAEMON.read_text(encoding="utf-8")


def test_doctor_does_not_report_ok_for_an_address_that_cannot_connect() -> None:
    """`BLEEMGBackend.run()` logs and returns when bleak is missing.

    Nobody watching for a hotkey sees a log line, so a flat OK next to the address
    is the misleading half of the row: the address is fine and the connection is
    impossible.
    """
    source = (ROOT / "src" / "yazses" / "system" / "doctor.py").read_text(encoding="utf-8")
    row = source.split('"EMG BLE address"')[1][:600]
    assert "bleak" in row, "the row does not consider whether bleak is installed"
    assert "WARN" in row
