"""`yazses biosignal monitor` shows when the stream-integrity gate is holding events.

``integrity_lines`` renders the ``status["integrity"]`` shape runner.py exposes
(``IntegrityReport.as_dict()``), so the monitor and the daemon status use one vocabulary.
Pure rendering: no source, no clock. The end-to-end monitor run is in
``test_biosignal_cli_devices.py``, next to the existing backwards-timestamp test.
"""
from __future__ import annotations

import pytest

from yazses.biosignal.cli_impl import integrity_lines
from yazses.biosignal.integrity import RECOVER_S


def _held(**over) -> dict:
    status = {
        "gate_closed": True,
        "violations": {"t0_backwards": 1},
        "last_violation": {"code": "t0_backwards", "detail": "t0 went back 0.4 s",
                           "t": 1.6, "block": 9},
        "clean_s": 0.4,
        "stalled": False,
    }
    status.update(over)
    return status


def _open_after_violation(**over) -> dict:
    status = _held(gate_closed=False, clean_s=RECOVER_S + 0.5)
    status.update(over)
    return status


def test_held_gate_names_state_reason_and_time_to_clear():
    lines = integrity_lines(_held(), recover_s=1.0)
    text = "\n".join(lines)
    assert "Events HELD" in text
    assert "stream-integrity gate is closed" in text
    assert "Reason: t0_backwards (t0 went back 0.4 s)" in text
    assert "Cleared? not yet: 0.4 of 1.0 s of clean signal, 0.6 s to go" in text


def test_held_gate_says_when_the_stream_has_stalled():
    text = "\n".join(integrity_lines(_held(stalled=True, clean_s=0.0), recover_s=1.0))
    assert "stalled" in text
    assert "0.0 of 1.0 s" in text


def test_held_gate_never_reports_negative_time_to_go():
    text = "\n".join(integrity_lines(_held(clean_s=5.0), recover_s=1.0))
    assert "0.0 s to go" in text


def test_held_gate_defaults_recover_window_to_the_module_constant():
    text = "\n".join(integrity_lines(_held(clean_s=0.0)))
    assert f"0.0 of {RECOVER_S:.1f} s" in text


def test_cleared_gate_after_a_violation_says_so_once():
    lines = integrity_lines(_open_after_violation(), recover_s=1.0)
    assert len(lines) == 1
    assert "cleared" in lines[0]
    assert "1 violation(s) so far" in lines[0]
    assert "HELD" not in lines[0]


def test_clean_stream_renders_nothing():
    """No violation ever: the monitor stays silent, as it did before this line existed."""
    clean = {"gate_closed": False, "violations": {}, "last_violation": None, "clean_s": 12.0,
             "stalled": False}
    assert integrity_lines(clean) == []


@pytest.mark.parametrize("status", [None, {}])
def test_missing_status_renders_nothing(status):
    assert integrity_lines(status) == []


def test_held_line_is_not_produced_for_an_open_gate():
    text = "\n".join(integrity_lines(_open_after_violation()))
    assert "HELD" not in text
    assert "not yet" not in text


def test_pump_calls_on_idle_for_each_empty_read_and_not_for_blocks():
    """A stall is flagged on an empty read; on_idle is how the monitor shows it while it lasts."""
    from yazses.biosignal.cli_impl import _pump

    class _Source:
        def __init__(self, reads):
            self._reads = list(reads)

        def start(self):
            pass

        def stop(self):
            pass

        def read(self):
            item = self._reads.pop(0)
            if isinstance(item, EOFError):
                raise item
            return item

    class _Pipeline:
        def process(self, block):
            return block

    idle: list[int] = []
    seen: list[object] = []
    source = _Source([None, None, "block-1", None, EOFError()])
    why = _pump(source, _Pipeline(), lambda b, r: seen.append(b),
                on_idle=lambda: idle.append(1))
    assert why == "end of recording"
    assert seen == ["block-1"]
    assert len(idle) == 3
