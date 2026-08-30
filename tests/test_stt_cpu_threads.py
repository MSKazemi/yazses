"""`[stt] cpu_threads` — capping the cores the decoder may use.

Measured on a 20-core laptop, `base.en`, 11-second clip, three runs per setting:
a decode taking ~1 s of wall time spends ~5.5 s of CPU. That is the right trade on
mains power and the wrong one on battery, and nothing capped it before this.

The honest part, which the docs also state: capping at 4 changed nothing on that
machine. The trade only appears below it (2 → ~17% less CPU for ~35% more latency).
"""

from __future__ import annotations

import dataclasses

from tests.decoder_stack import needs_faster_whisper
from yazses.config import SttConfig


def test_the_default_leaves_the_library_alone():
    """0 must mean "unchanged", so adding this setting changed nobody's behaviour."""
    assert SttConfig().cpu_threads == 0


@needs_faster_whisper
def test_zero_passes_no_thread_argument_at_all():
    """Passing cpu_threads=0 explicitly is not the same as omitting it; ctranslate2
    would read 0 as a request, not as a default."""
    import inspect

    from yazses.stt import faster_whisper as fw

    source = inspect.getsource(fw._load_model)
    assert "> 0" in source, "only a positive value may be forwarded"
    assert "extra" in source


@needs_faster_whisper
def test_a_positive_value_reaches_the_model(monkeypatch):
    from yazses.stt import faster_whisper as fw

    seen = {}

    class _FakeModel:
        def __init__(self, name, **kw):
            seen.update(kw)

    monkeypatch.setattr(fw, "WhisperModel", _FakeModel)
    fw._load_model("tiny.en", "cpu", "int8", 3)
    assert seen.get("cpu_threads") == 3


@needs_faster_whisper
def test_zero_reaches_the_model_as_nothing(monkeypatch):
    from yazses.stt import faster_whisper as fw

    seen = {}

    class _FakeModel:
        def __init__(self, name, **kw):
            seen.update(kw)

    monkeypatch.setattr(fw, "WhisperModel", _FakeModel)
    fw._load_model("tiny.en", "cpu", "int8", 0)
    assert "cpu_threads" not in seen


@needs_faster_whisper
def test_the_factory_threads_the_setting_through(monkeypatch):
    """A config key the engine never receives is a documented no-op — the exact
    shape of the `[stt] language` bug this project already had.

    Driven through the real factory rather than read out of its source, so it
    fails if the wiring moves rather than if the wording does.
    """
    from yazses.stt import faster_whisper as fw
    from yazses.stt.factory import build_engine

    seen = {}

    class _FakeModel:
        def __init__(self, name, **kw):
            seen.update(kw)

    monkeypatch.setattr(fw, "WhisperModel", _FakeModel)
    build_engine(dataclasses.replace(SttConfig(), cpu_threads=6))
    assert seen.get("cpu_threads") == 6


def test_it_is_settable_from_config():
    cfg = dataclasses.replace(SttConfig(), cpu_threads=2)
    assert cfg.cpu_threads == 2
