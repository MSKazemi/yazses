import time

from yazses.overlay.poller import (
    StatusPoller,
    StatusSnapshot,
    next_interval,
    parse_status,
)


def test_next_interval_fast_while_recording():
    assert next_interval("recording") < next_interval("idle")
    assert next_interval("transcribing") == next_interval("idle")


def test_parse_status_reads_fields():
    snap = parse_status(
        {"state": "recording", "audio_level": 0.12, "vad_threshold": 0.02}
    )
    assert snap.state == "recording"
    assert snap.audio_level == 0.12
    assert snap.vad_threshold == 0.02
    assert snap.reachable is True


def test_parse_status_is_defensive():
    snap = parse_status({"state": 123, "audio_level": "nope"})
    assert snap.state == "idle"
    assert snap.audio_level == 0.0
    assert snap.vad_threshold == 0.01


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def call(self, method, **params):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_poller_publishes_latest_snapshot():
    client = _FakeClient({"state": "recording", "audio_level": 0.3, "vad_threshold": 0.01})
    poller = StatusPoller(client)
    poller.start()
    try:
        assert _wait_for(lambda: poller.latest().state == "recording")
        snap = poller.latest()
        assert snap.audio_level == 0.3
        assert snap.reachable is True
    finally:
        poller.stop()


def test_poller_marks_unreachable_on_error():
    client = _FakeClient(RuntimeError("daemon down"))
    poller = StatusPoller(client)
    poller.start()
    try:
        assert _wait_for(lambda: poller.latest().reachable is False)
    finally:
        poller.stop()


def test_initial_snapshot_unreachable():
    poller = StatusPoller(_FakeClient({}))
    assert poller.latest() == StatusSnapshot(reachable=False)
