"""StreamingEngine: start() after request_stop() while the old decode is still in flight
used to flip a shared flag back to True before the old loop looked, leaving TWO decode
loops running against one buffer. Each loop now owns a stop token that is never cleared."""
from __future__ import annotations

import threading

import numpy as np

from yazses.stt.streaming import StreamingEngine

_WAIT = 5.0


def test_restart_while_previous_decode_in_flight_leaves_one_loop():
    gate, in_decode = threading.Event(), threading.Event()
    decoders: list[str] = []

    class Engine:
        def decode_window(self, audio):
            decoders.append(threading.current_thread().name)
            in_decode.set()
            gate.wait(_WAIT)
            return "x"

    eng = StreamingEngine(Engine(), partial_interval_ms=1)
    eng.start()
    eng.push(np.zeros(16000, dtype=np.float32))
    assert in_decode.wait(_WAIT)
    old = eng._thread
    assert old is not None
    eng.request_stop()  # hold-end of a discarded burst, no join
    eng.start()         # pressed again before the old decode returns
    new = eng._thread
    assert new is not None and new is not old
    gate.set()          # the old decode now returns
    old.join(_WAIT)
    assert not old.is_alive(), "the retired decode loop was revived by start()"
    eng.stop()
    assert not new.is_alive()


def test_retired_loop_does_not_publish_into_the_new_utterance():
    gate, in_decode = threading.Event(), threading.Event()
    first = threading.Event()

    class Engine:
        def decode_window(self, audio):
            if not first.is_set():
                first.set()
                in_decode.set()
                gate.wait(_WAIT)
            return "stale hypothesis"

    eng = StreamingEngine(Engine(), partial_interval_ms=1)
    eng.start()
    eng.push(np.zeros(16000, dtype=np.float32))
    assert in_decode.wait(_WAIT)
    old = eng._thread
    assert old is not None
    eng.request_stop()
    eng.start()         # resets the state for the new utterance
    gate.set()
    old.join(_WAIT)
    assert not old.is_alive()
    with eng._lock:
        assert eng._prev_hypothesis == ""
        assert eng._pending_partial is None
    eng.stop()


def test_start_twice_without_stop_retires_the_first_loop():
    class Engine:
        def decode_window(self, audio):
            return ""

    eng = StreamingEngine(Engine(), partial_interval_ms=1)
    eng.start()
    first = eng._thread
    assert first is not None
    eng.start()
    first.join(_WAIT)
    assert not first.is_alive()
    eng.stop()
