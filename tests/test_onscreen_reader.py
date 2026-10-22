"""`grounding/onscreen.py`: one backend, probed once, every call under a wall-clock deadline.

The backend here is a fake whose calls can be made to block on an event, which is how a
hung application looks from inside a synchronous D-Bus call. Nothing sleeps for long: the
reader's deadline is set to a few hundredths of a second and every blocked fake is
released at the end of its test.
"""

from __future__ import annotations

import threading

from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.grounding.onscreen import OnScreenReader


def _cand(label: str, eid: str = "n0") -> SemanticCandidate:
    return SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id=eid,
                             role="push button", captured_at_s=0.0, confidence=1.0,
                             label=label, actions=("click",))


class Fake:
    def __init__(self, cands=(), *, block: threading.Event | None = None,
                 raises: bool = False, act: bool = True) -> None:
        self.cands = tuple(cands)
        self.block = block
        self.raises = raises
        self.act = act
        self.snapshots = 0
        self.performed: list[tuple[str, str]] = []

    def snapshot(self, *, window_id=None, region=None):
        self.snapshots += 1
        if self.block is not None:
            self.block.wait(5)
        if self.raises:
            raise RuntimeError("bus went away")
        return self.cands

    def perform(self, entity_id, action):
        if self.block is not None:
            self.block.wait(5)
        self.performed.append((entity_id, action))
        return self.act


def test_a_read_returns_the_backends_candidates():
    reader = OnScreenReader(lambda: Fake([_cand("Save")]))
    got = reader.read()
    assert got is not None and [c.label for c in got] == ["Save"]


def test_no_backend_reads_as_none_not_as_empty():
    """`None` = could not read; `()` = read, nothing labelled. A message needs to know which."""
    assert OnScreenReader(lambda: None).read() is None
    assert OnScreenReader(lambda: Fake([])).read() == ()


def test_the_factory_runs_once_and_only_on_first_use():
    calls: list[int] = []

    def factory():
        calls.append(1)
        return Fake([_cand("Save")])

    reader = OnScreenReader(factory)
    assert calls == []
    reader.read()
    reader.read()
    reader.perform("n0", "click")
    assert calls == [1]


def test_a_factory_that_raises_leaves_the_reader_unavailable():
    def boom():
        raise RuntimeError("no accessibility bus")

    reader = OnScreenReader(boom)
    assert reader.available() is False
    assert reader.read() is None
    assert reader.perform("n0", "click") is False


def test_a_backend_that_raises_reads_as_none():
    assert OnScreenReader(lambda: Fake(raises=True)).read() is None


def test_a_hung_backend_costs_the_deadline_and_no_more():
    gate = threading.Event()
    fake = Fake([_cand("Save")], block=gate)
    reader = OnScreenReader(lambda: fake, timeout_s=0.05)
    try:
        assert reader.read() is None
    finally:
        gate.set()


def test_a_second_read_while_the_first_is_stuck_does_not_pile_up_threads():
    gate = threading.Event()
    fake = Fake([_cand("Save")], block=gate)
    reader = OnScreenReader(lambda: fake, timeout_s=0.05)
    try:
        assert reader.read() is None
        assert reader.read() is None
        assert fake.snapshots == 1, "a second call was sent into the same hung application"
    finally:
        gate.set()


def test_perform_passes_the_id_and_action_through_and_reports_the_result():
    fake = Fake([_cand("Save")])
    reader = OnScreenReader(lambda: fake)
    assert reader.perform("n0", "click") is True
    assert fake.performed == [("n0", "click")]
    fake.act = False
    assert reader.perform("n0", "click") is False


def test_perform_refuses_an_empty_id_or_action_without_calling_the_backend():
    fake = Fake()
    reader = OnScreenReader(lambda: fake)
    assert reader.perform("", "click") is False
    assert reader.perform("n0", "") is False
    assert fake.performed == []


def test_a_hung_action_is_reported_as_not_done():
    gate = threading.Event()
    reader = OnScreenReader(lambda: Fake(block=gate), timeout_s=0.05)
    try:
        assert reader.perform("n0", "click") is False
    finally:
        gate.set()


def test_anything_that_is_not_a_candidate_is_dropped():
    reader = OnScreenReader(lambda: Fake([_cand("Save"), "not a candidate", None]))
    got = reader.read()
    assert got is not None and [c.label for c in got] == ["Save"]
